import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import update

from app.api import clusters, hearth
from app.models.cluster import Cluster, ResourceObservation
from app.models.gpu_pod_history import ClusterGpuSnapshot
from app.schemas.hearth import HearthClusterResponse
from app.services import resource_observations as observations
from app.services.kubernetes_service import KubernetesService


async def register(sessions):
    key = str(uuid4())
    async with sessions.begin() as db:
        db.add(Cluster(id=key, name=key, kubeconfig_path="qa", status="healthy"))
    return key


async def age(sessions, source, seconds, section=None):
    statement = update(ResourceObservation).where(ResourceObservation.source == source)
    if section:
        statement = statement.where(ResourceObservation.section == section)
    async with sessions.begin() as db:
        await db.execute(statement.values(checked_at=datetime.utcnow() - timedelta(seconds=seconds)))


@pytest.mark.asyncio
async def test_operator_count_and_stale_failure(observation_db, monkeypatch):
    key = await register(observation_db)
    probe = Mock()
    probe.check_operators.return_value = ({"operators": [{"name": "gpu"}], "total": 1}, {"id": "v1"})
    monkeypatch.setattr(clusters, "KubernetesService", lambda _: probe)
    async with observation_db() as db:
        assert (await clusters.get_cluster(key, db)).operator_count is None
        assert (await clusters.get_cluster_operators(key, db, saved_only=True))["empty"]
        probe.check_operators.assert_not_called()
        first = await clusters.get_cluster_operators(key, db)
        assert first["total"] == 1
        assert (await clusters.get_cluster(key, db)).operator_count == 1
        assert (await clusters.get_cluster_operators(key, db, known_changed_at=first["observation"]["last_changed_at"]))["unchanged"]
    await age(observation_db, key, 305)
    probe.check_operators.side_effect = RuntimeError("cannot list CSVs")
    async with observation_db() as db:
        before = await clusters.get_cluster_operators(key, db, saved_only=True)
        failed = await clusters.get_cluster_operators(key, db)
        assert failed["total"] == 1 and failed["observation"]["last_check_failed"]
        assert failed["observation"]["last_checked_at"] == before["observation"]["last_checked_at"]
        assert failed["observation"]["last_changed_at"] == first["observation"]["last_changed_at"]
    assert probe.check_operators.call_count == 2


def test_operator_revision_check_avoids_downloading_unchanged_csvs():
    probe = Mock(spec=KubernetesService)
    probe._object_versions = KubernetesService._object_versions
    saved = {"total": 1, "operators": [{"name": "gpu"}]}
    versions = {"uid": "42"}
    probe._collection.return_value = {
        "kind": "PartialObjectMetadataList", "items": [{"metadata": {"uid": "uid", "resourceVersion": "42"}}],
    }
    assert KubernetesService.check_operators(probe, saved, versions) == (saved, versions)
    probe.custom_objects.list_cluster_custom_object.assert_not_called()


@pytest.mark.asyncio
async def test_ocp_advances_version_and_keeps_failed_ingress(observation_db, monkeypatch):
    key = await register(observation_db)
    values = dict(clusterversions={"cluster_version": "1"}, networks={"network_type": "OVN"},
                  infrastructures={"platform": "IBM"}, ingresses={"ingress_domain": "old.example"})
    def fetch(name):
        if name not in values:
            raise OSError("lookup failed")
        return values[name]
    probe = Mock()
    probe.get_ocp_resource.side_effect = fetch
    monkeypatch.setattr(clusters, "KubernetesService", lambda _: probe)
    async with observation_db() as db:
        first = await clusters.get_ocp_details(key, db)
        assert first["ingress_domain"] == "old.example"
        assert (await clusters.get_ocp_details(key, db))["observation"] == first["observation"]
    assert probe.get_ocp_resource.call_count == 4
    await age(observation_db, key, 310, "clusterversions")
    await age(observation_db, key, 310, "ingresses")
    values["clusterversions"] = {"cluster_version": "2"}
    del values["ingresses"]
    async with observation_db() as db:
        partial = await clusters.get_ocp_details(key, db)
    assert partial["ingress_domain"] == "old.example" and partial["cluster_version"] == "2"
    assert partial["observation"]["failed_resources"] == ["ingresses"]
    assert probe.get_ocp_resource.call_count == 6


@pytest.mark.asyncio
async def test_concurrent_workload_readers_share_observation_and_namespace_scope(observation_db):
    key = await register(observation_db)
    started, release = asyncio.Event(), asyncio.Event()
    async def collect(*_):
        started.set()
        await release.wait()
        return {"total_pods": 3}, None
    probe = AsyncMock(side_effect=collect)

    async def read(section="workloads:*"):
        async with observation_db() as db:
            return await observations.observe(db, key, section, ttl=observations.WORKLOAD_TTL, cluster_id=key, discover=probe)

    winner = asyncio.create_task(read())
    await asyncio.wait_for(started.wait(), 3)
    followers = [asyncio.create_task(read()) for _ in range(5)]
    await asyncio.sleep(0.05)
    release.set()
    results = await asyncio.wait_for(asyncio.gather(winner, *followers), 10)
    assert all(result == results[0] for result in results)
    probe.assert_awaited_once()
    await read("workloads:training")
    await age(observation_db, key, 31, "workloads:*")
    again = await read()
    assert probe.await_count == 3
    assert again[1]["last_changed_at"] == results[0][1]["last_changed_at"]


@pytest.mark.asyncio
async def test_hearth_readers_share_inventory_and_never_claim_stale_availability(observation_db, monkeypatch):
    service = Mock()
    source = "hearth:" + str(uuid4())
    service.inventory_source.return_value = source
    sample = HearthClusterResponse(name="atlas", kubeconfig_secret="ref", locked=False, owner="team", gpu_summary="4 GPUs")
    service.list_clusters.return_value = [sample]
    monkeypatch.setattr(hearth, "get_hearth_service", lambda: service)
    monkeypatch.setattr(hearth.settings, "HEARTH_ENABLED", True)
    async with observation_db() as db:
        assert (await hearth.get_hearth_status(db)).cluster_names == ["atlas"]
        assert (await hearth.list_hearth_clusters(db)).available
        assert (await hearth.get_hearth_cluster("atlas", db)).locked is False
    service.list_clusters.assert_called_once()
    await age(observation_db, source, 16)
    service.list_clusters.side_effect = OSError("unreachable")
    async with observation_db() as db:
        with pytest.raises(HTTPException) as problem:
            await hearth.get_hearth_cluster("atlas", db)
        assert problem.value.status_code == 503
        detail = await hearth.get_hearth_cluster("atlas", db, allow_saved_hardware=True)
        assert detail.gpu_summary == "4 GPUs" and detail.observed_at is not None
        assert detail.locked is None and detail.owner is None and not detail.availability_verified
        assert not (await hearth.list_hearth_clusters(db)).available
        service.inventory_source.return_value = "hearth:" + str(uuid4())
        with pytest.raises(HTTPException):
            await hearth.get_hearth_cluster("atlas", db, allow_saved_hardware=True)


@pytest.mark.asyncio
async def test_card_batch_distinguishes_unknown_idle_active_and_scopes_results(observation_db):
    keys = [await register(observation_db) for _ in range(4)]
    now = datetime.utcnow()
    async with observation_db.begin() as db:
        db.add(ClusterGpuSnapshot(cluster_id=keys[3], observed_at=now, status={
            "total_gpus": 0, "allocated_gpus": 0, "pod_inventory_complete": False,
        }))
        for i, key in enumerate(keys[:2]):
            pods = [{"name": "a", "namespace": "ns", "gpu_count": 2}, {"name": "b", "namespace": "ns", "gpu_count": 1}] if i else []
            db.add(ClusterGpuSnapshot(cluster_id=key, observed_at=now - timedelta(minutes=10 * i), status={
                "total_gpus": 4, "allocated_gpus": 3 * i, "gpu_pods": pods, "gpu_types": [],
                "nodes": [{"gpu_capacity": 4, "name": "worker"}],
            }))
    async with observation_db() as db:
        all_rows = await clusters.list_clusters(db=db, include_gpu_summary=True)
        summaries = all_rows.gpu_summaries
        assert keys[2] not in summaries and keys[3] not in summaries
        assert summaries[keys[0]].allocated_gpus == 0 and not summaries[keys[0]].stale
        active = summaries[keys[1]]
        assert active.stale and active.observed_at is not None and active.gpu_nodes == 1
        assert active.namespaces[0].gpu_count == 3 and len(active.namespaces[0].pods) == 2
        page = await clusters.list_clusters(db=db, limit=1, include_gpu_summary=True)
        assert set(page.gpu_summaries).issubset({c.id for c in page.clusters})


@pytest.mark.asyncio
async def test_submission_verifies_hearth_selection_against_live_inventory(monkeypatch):
    from app.api import fournos
    from app.schemas.ui_schema import UiPipeline

    service = Mock()
    monkeypatch.setattr(fournos, "get_hearth_service", lambda: service)
    monkeypatch.setattr(fournos.settings, "HEARTH_ENABLED", True)
    service.get_cluster.return_value = HearthClusterResponse(
        name="atlas", kubeconfig_secret="ref", locked=True,
        hardware={"gpus": [{"short_name": "H200", "vendor": "NVIDIA", "model": "Hopper", "count": 8}]},
    )
    pipeline = UiPipeline(key="matrix", gpu_type="h200")
    await fournos._verify_hearth_target("atlas", pipeline)
    pipeline.gpu_type = "mi355x"
    with pytest.raises(HTTPException) as incompatible:
        await fournos._verify_hearth_target("atlas", pipeline)
    assert incompatible.value.status_code == 409
    pipeline.clusters = ["atlas"]
    await fournos._verify_hearth_target("atlas", pipeline)
    service.get_cluster.return_value = None
    with pytest.raises(HTTPException) as removed:
        await fournos._verify_hearth_target("atlas", pipeline)
    assert removed.value.status_code == 409
    service.get_cluster.side_effect = OSError()
    with pytest.raises(HTTPException) as unavailable:
        await fournos._verify_hearth_target("atlas", pipeline)
    assert unavailable.value.status_code == 503
    assert service.get_cluster.call_count == 5



def test_unchanged_namespaced_workloads_only_read_metadata():
    probe = Mock(spec=KubernetesService)
    probe._object_versions = KubernetesService._object_versions
    probe._collection.side_effect = [
        {"items": [{"metadata": {"uid": "pod-id", "resourceVersion": "12"}}]}, {"items": []},
    ]
    saved = {"pods": [{"name": "worker"}]}
    versions = {"pods": {"pod-id": "12"}, "deployments": {}}
    assert KubernetesService.check_workloads(probe, "training", saved, versions) == (saved, versions)
    assert [call.args[0] for call in probe._collection.call_args_list] == [
        "/api/v1/namespaces/training/pods", "/apis/apps/v1/namespaces/training/deployments",
    ]
    probe.core_v1.list_namespaced_pod.assert_not_called()


@pytest.mark.asyncio
async def test_workload_api_publishes_changes_and_keeps_last_success_on_failure(observation_db, monkeypatch):
    key = await register(observation_db)
    probe = Mock()
    probe.check_workloads.return_value = ({"total_pods": 1}, {"pods": {"sample": "v1"}})
    monkeypatch.setattr(clusters, "KubernetesService", lambda _: probe)
    async with observation_db() as db:
        first = await clusters.get_cluster_workloads(key, namespace="training", db=db)
        assert first["total_pods"] == 1
        probe.check_workloads.assert_called_once_with("training", None, None)
    await age(observation_db, key, 31)
    probe.check_workloads.return_value = ({"total_pods": 2}, {"pods": {"sample": "v2"}})
    async with observation_db() as db:
        second = await clusters.get_cluster_workloads(
            key, namespace="training", db=db, known_changed_at=first["observation"]["last_changed_at"],
        )
        assert second["total_pods"] == 2
    await age(observation_db, key, 31)
    probe.check_workloads.side_effect = OSError()
    async with observation_db() as db:
        failed = await clusters.get_cluster_workloads(
            key, namespace="training", db=db, known_changed_at=second["observation"]["last_changed_at"],
        )
        assert failed["unchanged"] and failed["observation"]["last_check_failed"]
        saved = await clusters.get_cluster_workloads(key, namespace="training", db=db, saved_only=True)
        assert saved["total_pods"] == 2
