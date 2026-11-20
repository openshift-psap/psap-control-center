from uuid import uuid4
import asyncio
import threading
from unittest.mock import Mock

import httpx
import pytest
import yaml
from fastapi import FastAPI
from kubernetes import client
from urllib3 import ProxyManager

from app.api import auth, hearth
from app.core.kubernetes import management_configuration
from app.services.hearth_service import HearthService


@pytest.mark.parametrize(("host", "proxied"), [
    ("192.0.2.10", False),          # Kubernetes-injected service IP
    ("api.cluster.test", False),    # configured DNS exclusion
    ("api.external.test", True),    # still needs the outbound proxy
])
def test_management_transport_uses_service_ip_and_proxy_exclusions(tmp_path, monkeypatch, host, proxied):
    for name in ("https_proxy", "http_proxy", "HTTP_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://other-proxy.example.test:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.test:8080")
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "192.0.2.10")
    monkeypatch.setenv("NO_PROXY", ".cluster.test")
    path = tmp_path / "kubeconfig"
    path.write_text(yaml.safe_dump({
        "current-context": "test",
        "contexts": [{"name": "test", "context": {"cluster": "test", "user": "reader"}}],
        "clusters": [{"name": "test", "cluster": {"server": f"https://{host}:443"}}],
        "users": [{"name": "reader", "user": {}}],
    }))
    configuration = management_configuration(str(path))
    with client.ApiClient(configuration) as api:
        transport = api.rest_client.pool_manager
        assert isinstance(transport, ProxyManager) is proxied
        if proxied:
            assert transport.proxy.host == "proxy.example.test"


@pytest.mark.asyncio
async def test_sign_in_config_remains_responsive_during_hearth_lookup(monkeypatch, observation_db):
    started = threading.Event()
    release = threading.Event()

    def slow_lookup():
        started.set()
        assert release.wait(timeout=4), "Hearth lookup blocked the API event loop"
        return []

    monkeypatch.setattr(hearth.settings, "HEARTH_ENABLED", True)
    monkeypatch.setattr(hearth.get_hearth_service(), "is_configured", lambda: True)
    key = "hearth:" + str(uuid4())
    monkeypatch.setattr(hearth.get_hearth_service(), "inventory_source", lambda: key)
    monkeypatch.setattr(hearth.get_hearth_service(), "list_clusters", slow_lookup)
    app = FastAPI()
    async def database():
        async with observation_db() as db:
            yield db
    app.dependency_overrides[hearth.get_db] = database
    app.include_router(hearth.router, prefix="/hearth")
    app.include_router(auth.router, prefix="/auth")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as api:
        lookup = asyncio.create_task(api.get("/hearth/status"))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            response = await asyncio.wait_for(api.get("/auth/config"), timeout=1)
            assert response.status_code == 200
            assert "google_enabled" in response.json()
        finally:
            release.set()
            assert (await lookup).status_code == 200


def test_hearth_inventory_requests_have_deadlines(monkeypatch):
    service = HearthService()
    api = Mock()
    api.list_namespaced_custom_object.return_value = {"items": []}
    api.get_namespaced_custom_object.return_value = {"metadata": {"name": "sample"}}
    monkeypatch.setattr(service, "_get_api", lambda: api)
    service.list_clusters()
    service.get_cluster("sample")
    for call in (api.list_namespaced_custom_object, api.get_namespaced_custom_object):
        assert call.call_args.kwargs["_request_timeout"] > 0
