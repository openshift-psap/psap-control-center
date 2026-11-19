import asyncio
from datetime import datetime, timedelta
from threading import Lock
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import clusters
from app.models.cluster import Cluster
from app.models.gpu_pod_history import ClusterGpuSnapshot, GpuPodHistory
from app.services import cluster_service, cost_snapshot_service, gpu_status_cache
from app.services.gpu_pod_history_service import record_gpu_snapshot
from app.services.kubernetes_service import GpuAllocationStatus, GpuPodInfo, KubernetesService


@pytest_asyncio.fixture
async def gpu_db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'gpu.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            for model in (Cluster, GpuPodHistory, ClusterGpuSnapshot):
                await conn.run_sync(model.__table__.create)
        async with sessions.begin() as db:
            cluster = Cluster(name="test", kubeconfig_path="test", infra_id="test")
            db.add(cluster)
        yield sessions, cluster.id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_gpu_history_changes_only_on_fresh_complete_observations(monkeypatch, gpu_db):
    sessions, cluster_id = gpu_db
    async with sessions() as db:
        probe = Mock()
        probe.get_cluster_info.return_value = {"status": "connected"}
        probe.get_namespaces.return_value = []
        probe.get_resource_usage.return_value = {}
        probe.get_gpu_allocation.return_value = GpuAllocationStatus(
            gpu_pods=[GpuPodInfo("trainer", "test", 1)], pod_inventory_complete=True,
        )
        monkeypatch.setattr(clusters, "KubernetesService", lambda _: probe)
        monkeypatch.setattr(cluster_service, "KubernetesService", lambda _: probe)
        monkeypatch.setattr(cost_snapshot_service, "update_current_day", AsyncMock())
        service = cluster_service.ClusterService(db)

        response = await clusters.get_gpu_status(cluster_id, db)
        assert response.gpu_pods[0].name == "trainer"
        record = (await db.scalars(select(GpuPodHistory))).one()
        first_seen = record.last_seen
        await clusters.get_gpu_status(cluster_id, db)
        await db.refresh(record)
        assert record.last_seen == first_seen
        probe.get_gpu_allocation.assert_called_once()

        probe.get_gpu_allocation.return_value = GpuAllocationStatus()
        await service.refresh_cluster_status(cluster_id)
        await db.refresh(record)
        assert record.finished_at is None
        assert record.last_seen == first_seen

        probe.get_gpu_allocation.return_value = GpuAllocationStatus(pod_inventory_complete=True)
        await service.refresh_cluster_status(cluster_id)
        await db.refresh(record)
        assert record.finished_at is not None
        assert record.last_seen > first_seen

        probe.get_gpu_allocation.return_value = GpuAllocationStatus(
            gpu_pods=[GpuPodInfo("trainer", "test", 2)], pod_inventory_complete=True,
        )
        await service.refresh_cluster_status(cluster_id)
        await db.refresh(record)
        assert record.finished_at is None
        assert record.gpu_count == 2


@pytest.mark.parametrize("mode", ["legacy", "dra"])
def test_empty_pod_inventory_requires_a_successful_list(mode):
    probe = Mock(spec=KubernetesService)
    probe._load_gpu_config_from_configmap.return_value = {}
    probe._list_nodes_snapshot.return_value = SimpleNamespace(items=[])
    probe.custom_objects.list_cluster_custom_object.return_value = {"items": [{
        "spec": {"driver": "gpu.nvidia.com", "nodeName": "node", "devices": [{}]},
    }]}
    def observe():
        if mode == "dra":
            return KubernetesService._get_gpu_allocation_dra(probe, "v1")
        return KubernetesService._get_gpu_allocation_legacy(probe)

    probe._list_pods_snapshot.side_effect = RuntimeError("Pod list unavailable")
    assert not observe().pod_inventory_complete
    probe._list_pods_snapshot.side_effect = None
    observed_at = datetime.utcnow() - timedelta(minutes=1)
    probe._list_pods_snapshot.return_value = observed_at, SimpleNamespace(items=[])
    status = observe()
    assert status.pod_inventory_complete
    assert status.observed_at == observed_at


def test_shared_kubernetes_pod_list_keeps_its_first_observation_time():
    probe = Mock(spec=KubernetesService)
    probe._pods_snapshot = None
    probe._pods_snapshot_lock = Lock()
    observed_at, pods = KubernetesService._list_pods_snapshot(probe)
    assert KubernetesService._list_pods_snapshot(probe) == (observed_at, pods)
    probe.core_v1.list_pod_for_all_namespaces.assert_called_once()


@pytest.mark.asyncio
async def test_delayed_scheduled_refresh_cannot_retire_pod_seen_by_cold_api(monkeypatch, gpu_db):
    sessions, cluster_id = gpu_db
    early = datetime.utcnow() - timedelta(seconds=5)
    later = datetime.utcnow()
    scheduled = Mock()
    scheduled.get_gpu_allocation.return_value = GpuAllocationStatus(
        observed_at=early, total_gpus=1, pod_inventory_complete=True,
    )
    scheduled.get_cluster_info.return_value = {"status": "connected"}
    scheduled.get_resource_usage.return_value = {}
    scheduled.get_namespaces.return_value = []
    api = Mock()
    api.get_gpu_allocation.return_value = GpuAllocationStatus(
        observed_at=later, total_gpus=4, pod_inventory_complete=True,
        gpu_pods=[GpuPodInfo("trainer", "test", 1)],
    )
    monkeypatch.setattr(cluster_service, "KubernetesService", lambda _: scheduled)
    monkeypatch.setattr(clusters, "KubernetesService", lambda _: api)
    monkeypatch.setattr(cost_snapshot_service, "update_current_day", AsyncMock())

    gpu_read = asyncio.Event()
    release_other_probe = asyncio.Event()
    async with sessions() as scheduler_db:
        scheduler = cluster_service.ClusterService(scheduler_db)

        async def run_probe(fn, executor):
            if fn is scheduled.get_namespaces:
                await release_other_probe.wait()
            result = fn()
            if fn is scheduled.get_gpu_allocation:
                gpu_read.set()
            return result

        monkeypatch.setattr(scheduler, "_run_in_thread", run_probe)
        refresh = asyncio.create_task(scheduler.refresh_cluster_status(cluster_id))
        try:
            await asyncio.wait_for(gpu_read.wait(), timeout=5)
            async with sessions() as api_db:
                response = await clusters.get_gpu_status(cluster_id, api_db)
                assert response.gpu_pods[0].name == "trainer"
        finally:
            release_other_probe.set()
            status = await asyncio.wait_for(refresh, timeout=5)
    assert status.gpu_count == "4"
    async with sessions() as db:
        record = (await db.scalars(select(GpuPodHistory))).one()
        assert (record.first_seen, record.last_seen, record.finished_at) == (later, later, None)
        assert (await clusters.get_gpu_status(cluster_id, db)).gpu_pods[0].name == "trainer"
    api.get_gpu_allocation.assert_called_once()


@pytest.mark.asyncio
async def test_late_or_duplicate_pod_list_cannot_reopen_finished_history_after_cache_expiry(gpu_db):
    sessions, cluster_id = gpu_db
    start = datetime.utcnow() - timedelta(hours=1)
    end = start + timedelta(minutes=1)
    running = GpuAllocationStatus(
        observed_at=start, pod_inventory_complete=True, gpu_pods=[GpuPodInfo("trainer", "test", 1)],
    )
    finished = GpuAllocationStatus(observed_at=end, pod_inventory_complete=True)
    async with sessions.begin() as db:
        await record_gpu_snapshot(db, cluster_id, running)
    async with sessions.begin() as db:
        await record_gpu_snapshot(db, cluster_id, finished)
    for stale_time in (start, end):
        running.observed_at = stale_time
        async with sessions.begin() as db:
            assert await gpu_status_cache.get(db, cluster_id) is None
            winner = await record_gpu_snapshot(db, cluster_id, running)
            assert winner == finished.to_dict()
            record = (await db.scalars(select(GpuPodHistory))).one()
            assert (record.first_seen, record.last_seen, record.finished_at) == (start, end, end)


@pytest.mark.asyncio
async def test_complete_inventory_can_advance_history_after_newer_partial_snapshot(gpu_db):
    sessions, cluster_id = gpu_db
    start = datetime.utcnow() - timedelta(minutes=2)
    complete = GpuAllocationStatus(
        observed_at=start, pod_inventory_complete=True, gpu_pods=[GpuPodInfo("trainer", "test", 1)],
    )
    partial = GpuAllocationStatus(observed_at=start + timedelta(minutes=2), total_gpus=4)
    finished = GpuAllocationStatus(observed_at=start + timedelta(minutes=1), pod_inventory_complete=True)
    async with sessions.begin() as db:
        await record_gpu_snapshot(db, cluster_id, complete)
    async with sessions.begin() as db:
        await record_gpu_snapshot(db, cluster_id, partial)
    async with sessions() as db:
        assert await record_gpu_snapshot(db, cluster_id, finished) == partial.to_dict()
        await db.rollback()
    async with sessions.begin() as db:
        record = (await db.scalars(select(GpuPodHistory))).one()
        assert record.finished_at is None
        assert await record_gpu_snapshot(db, cluster_id, finished) == partial.to_dict()
    async with sessions() as db:
        snapshot = await db.get(ClusterGpuSnapshot, cluster_id)
        assert (snapshot.observed_at, snapshot.pod_inventory_at) == (partial.observed_at, finished.observed_at)
        record = (await db.scalars(select(GpuPodHistory))).one()
        assert record.finished_at == finished.observed_at


@pytest.mark.asyncio
async def test_failed_history_write_returns_live_status_and_same_observation_can_retry(monkeypatch, gpu_db):
    sessions, cluster_id = gpu_db
    probe = Mock()
    observation = GpuAllocationStatus(
        pod_inventory_complete=True, gpu_pods=[GpuPodInfo("trainer", "test", 1)],
    )
    probe.get_gpu_allocation.return_value = observation
    monkeypatch.setattr(clusters, "KubernetesService", lambda _: probe)
    async with sessions() as db:
        with monkeypatch.context() as patch:
            patch.setattr(db, "commit", AsyncMock(side_effect=SQLAlchemyError("write failed")))
            response = await clusters.get_gpu_status(cluster_id, db)
        assert response.gpu_pods[0].name == "trainer"
        assert await db.get(ClusterGpuSnapshot, cluster_id) is None
        assert not (await db.scalars(select(GpuPodHistory))).all()
    async with sessions() as db:
        await clusters.get_gpu_status(cluster_id, db)
        record = (await db.scalars(select(GpuPodHistory))).one()
        assert (record.first_seen, record.last_seen) == (observation.observed_at, observation.observed_at)
    assert probe.get_gpu_allocation.call_count == 2
