from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import clusters
from app.models.cluster import Cluster
from app.models.gpu_pod_history import GpuPodHistory
from app.services import cluster_service, cost_snapshot_service
from app.services.kubernetes_service import GpuAllocationStatus, GpuPodInfo, KubernetesService


@pytest.mark.asyncio
async def test_gpu_history_changes_only_on_fresh_complete_observations(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Cluster.__table__.create)
        await conn.run_sync(GpuPodHistory.__table__.create)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            cluster = Cluster(name="test", kubeconfig_path="test", infra_id="test")
            db.add(cluster)
            await db.commit()

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

            response = await clusters.get_gpu_status(cluster.id, db)
            assert response.gpu_pods[0].name == "trainer"
            record = (await db.scalars(select(GpuPodHistory))).one()
            first_seen = record.last_seen
            await clusters.get_gpu_status(cluster.id, db)
            await db.refresh(record)
            assert record.last_seen == first_seen
            probe.get_gpu_allocation.assert_called_once()

            probe.get_gpu_allocation.return_value = GpuAllocationStatus()
            await service.refresh_cluster_status(cluster.id)
            await db.refresh(record)
            assert record.finished_at is None
            assert record.last_seen == first_seen

            probe.get_gpu_allocation.return_value = GpuAllocationStatus(pod_inventory_complete=True)
            await service.refresh_cluster_status(cluster.id)
            await db.refresh(record)
            assert record.finished_at is not None
            assert record.last_seen > first_seen

            probe.get_gpu_allocation.return_value = GpuAllocationStatus(
                gpu_pods=[GpuPodInfo("trainer", "test", 2)], pod_inventory_complete=True,
            )
            await service.refresh_cluster_status(cluster.id)
            await db.refresh(record)
            assert record.finished_at is None
            assert record.gpu_count == 2
    finally:
        await engine.dispose()


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
    probe._list_pods_snapshot.return_value = SimpleNamespace(items=[])
    assert observe().pod_inventory_complete
