import asyncio
import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import Response
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import clusters
from app.models.cluster import Cluster, ClusterTopologySnapshot
from app.services import topology_snapshot as snapshots
from app.services.kubernetes_service import KubernetesService


@pytest_asyncio.fixture
async def store(tmp_path):
    # Optional integration run against a disposable PostgreSQL database.
    engine = create_async_engine(os.getenv("TOPOLOGY_TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{tmp_path}/db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        for table in (Cluster.__table__, ClusterTopologySnapshot.__table__):
            await conn.run_sync(lambda sync, t=table: t.create(sync, checkfirst=True))
    async with sessions.begin() as db:
        cluster = Cluster(name=str(uuid4()), kubeconfig_path="test", api_server_url="old")
        db.add(cluster)
    try:
        yield sessions, cluster.id
    finally:
        await engine.dispose()


def node(pods=1):
    return {"name": "worker", "roles": ["worker"], "zone": "east", "pod_count": pods}


@pytest.mark.asyncio
async def test_navigation_cooldown_changes_and_retry(store, monkeypatch):
    sessions, cluster_id = store
    now = datetime(2026, 11, 1)
    monkeypatch.setattr(snapshots, "utcnow", lambda: now)
    probe = Mock()
    probe.check_topology.return_value = ({"worker": "v1"}, [node()])
    constructor = Mock(return_value=probe)
    monkeypatch.setattr(clusters, "KubernetesService", constructor)

    async def check():
        async with sessions() as db:
            return await clusters.check_cluster_topology(cluster_id, db)

    async with sessions() as db:
        empty = await clusters.get_cluster_topology(cluster_id, Response(), db)
        assert empty["check_due"] and empty["last_checked_at"] is None
    constructor.assert_not_called()
    first = await check()
    assert first["workers"] == [node()] and first["zones"] == ["east"]
    assert first["last_changed_at"] == first["last_checked_at"]
    now += timedelta(minutes=5) - timedelta(microseconds=1)
    assert await check() == first
    probe.check_topology.assert_called_once_with(None, None)
    now += timedelta(microseconds=1)
    # A new revision can also be a heartbeat with identical graph content.
    probe.check_topology.return_value = ({"worker": "v2"}, [node()])
    second = await check()
    assert second["last_checked_at"] > first["last_checked_at"]
    assert second["last_changed_at"] == first["last_changed_at"]
    async with sessions() as db:
        metadata = await clusters.get_cluster_topology(cluster_id, Response(), db, first["last_changed_at"])
    assert metadata["unchanged"] and "nodes" not in metadata and "workers" not in metadata
    assert metadata["last_checked_at"] == second["last_checked_at"]
    now += timedelta(minutes=5)
    probe.check_topology.side_effect = OSError("upstream unavailable")
    stale = await check()
    assert stale["last_check_failed"] and stale["check_due"]
    assert stale["last_checked_at"] == second["last_checked_at"]
    assert stale["nodes"] == [node()]
    probe.check_topology.side_effect = None
    probe.check_topology.return_value = ({"worker": "v2"}, [node(2)])
    updated = await check()
    assert updated["last_changed_at"] == updated["last_checked_at"] > second["last_checked_at"]
    assert updated["nodes"] == [node(2)] and not updated["last_check_failed"]
    async with sessions() as db:
        assert await clusters.get_cluster_topology(cluster_id, Response(), db, first["last_changed_at"]) == updated
    # New readers get the committed snapshot even if no Kubernetes client can start.
    async with sessions() as db:
        assert await clusters.get_cluster_topology(cluster_id, Response(), db) == updated
    assert constructor.call_count == 4


@pytest.mark.asyncio
async def test_overlapping_visits_share_one_check_and_readers_get_saved_graph(store):
    sessions, cluster_id = store
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow(*_):
        entered.set()
        await release.wait()
        return {}, []

    discover = AsyncMock(side_effect=slow)

    async def visit():
        async with sessions() as db:
            return await snapshots.check(db, cluster_id, discover)

    winner = asyncio.create_task(visit())
    await asyncio.wait_for(entered.wait(), 3)
    followers = [asyncio.create_task(visit()) for _ in range(6)]
    try:
        async with sessions() as db:
            pending = await asyncio.wait_for(clusters.get_cluster_topology(cluster_id, Response(), db), 2)
            assert pending["last_changed_at"] is None
        await asyncio.sleep(0.1)
    finally:
        release.set()
    results = await asyncio.wait_for(asyncio.gather(winner, *followers), 5)
    assert all(item == results[0] for item in results)
    assert results[0]["last_changed_at"] is not None and results[0]["nodes"] == []
    discover.assert_awaited_once()


@pytest.mark.asyncio
async def test_old_check_cannot_overwrite_new_cluster_target(store):
    sessions, cluster_id = store
    entered, release = asyncio.Event(), asyncio.Event()

    async def old_probe(*_):
        entered.set()
        await release.wait()
        return {"worker": "old"}, [node(1)]

    async def old_check():
        async with sessions() as db:
            return await snapshots.check(db, cluster_id, old_probe)

    stale_writer = asyncio.create_task(old_check())
    await asyncio.wait_for(entered.wait(), 3)
    try:
        async with sessions.begin() as db:
            cluster = await db.get(Cluster, cluster_id)
            await snapshots.clear_if_target_changed(db, cluster, "new")
            cluster.api_server_url = "new"
        async with sessions() as db:
            new = await snapshots.check(db, cluster_id, AsyncMock(return_value=({"worker": "new"}, [node(7)])))
    finally:
        release.set()
    assert await stale_writer == new


def test_lightweight_check_reuses_node_details_and_counts_assigned_pods():
    client = Mock(spec=KubernetesService)
    client._topology_pod_counts = KubernetesService._topology_pod_counts.__get__(client)
    client._topology_collection.side_effect = [
        {"kind": "Table", "columnDefinitions": [{"name": "Name"}, {"name": "Node"}],
         "rows": [{"cells": ["a", "worker"]}, {"cells": ["b", "worker"]}, {"cells": ["c", "<none>"]}]},
        {"items": [{"metadata": {"name": "worker", "resourceVersion": "42"}}]},
    ]
    versions, nodes = KubernetesService.check_topology(client, {"worker": "42"}, [node()])
    assert versions == {"worker": "42"} and nodes == [node(2)]
    client.core_v1.list_node.assert_not_called()
    client.core_v1.list_pod_for_all_namespaces.assert_not_called()


def test_changed_node_revision_reads_details_and_pod_list_fallback():
    client = Mock(spec=KubernetesService)
    client._topology_pod_counts = KubernetesService._topology_pod_counts.__get__(client)
    client._topology_collection.side_effect = [
        {"kind": "PodList", "items": [{"spec": {"nodeName": "worker"}}]},
        {"items": [{"metadata": {"name": "worker", "resourceVersion": "43"}}]},
    ]
    current = SimpleNamespace(metadata=SimpleNamespace(name="worker", resource_version="44"))
    client.core_v1.list_node.return_value.items = [current]
    client._topology_node.return_value = node()
    assert KubernetesService.check_topology(client, {"worker": "42"}, [node()]) == ({"worker": "44"}, [node()])
    client._topology_node.assert_called_once_with(current, 1)


def test_kubernetes_client_reads_negotiated_topology_representations():
    import json
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from threading import Thread
    from kubernetes import client

    requests = []

    class Api(BaseHTTPRequestHandler):
        def do_GET(self):
            accept = self.headers["Accept"]
            requests.append((self.path, accept))
            if self.path.startswith("/api/v1/pods"):
                data = {"kind": "Table", "columnDefinitions": [{"name": "Node"}], "rows": [{"cells": ["w1"]}]}
            elif "PartialObjectMetadataList" in accept:
                data = {"kind": "PartialObjectMetadataList", "items": [{"metadata": {"name": "w1", "resourceVersion": "7"}}]}
            else:
                data = {"kind": "NodeList", "items": [{"metadata": {"name": "w1", "resourceVersion": "7"},
                         "status": {"capacity": {"cpu": "4"}, "conditions": [{"type": "Ready", "status": "True"}]}}]}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

    server = HTTPServer(("127.0.0.1", 0), Api)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config = client.Configuration()
        config.host = f"http://127.0.0.1:{server.server_port}"
        config.proxy = None
        with client.ApiClient(config) as api:
            cluster = KubernetesService.__new__(KubernetesService)
            cluster._api_client = api
            cluster._core_v1 = client.CoreV1Api(api)
            versions, nodes = cluster.check_topology(None, None)
            assert nodes[0]["name"] == "w1" and nodes[0]["pod_count"] == 1 and nodes[0]["status"] == "Ready"
            assert cluster.check_topology(versions, nodes) == (versions, nodes)
        assert len(requests) == 4
        assert requests[0][0] == "/api/v1/pods?includeObject=None" and "as=Table" in requests[0][1]
        assert "as=PartialObjectMetadataList" in requests[-1][1]
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
