from urllib.parse import quote
from unittest.mock import AsyncMock, MagicMock, Mock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import fournos
from app.core.auth import COOKIE_NAME, create_session_token
from app.services import mlflow_artifacts as artifacts

RUN = "abcdef12" * 4
RUN_URL = f"https://mlflow.example/#/experiments/5/runs/{RUN}/artifacts?workspace=team"


@pytest.fixture
def explorer(monkeypatch):
    monkeypatch.setattr(artifacts.settings, "MLFLOW_TRACKING_URI", "https://mlflow.example")
    monkeypatch.setattr(artifacts.settings, "MLFLOW_BASE_URL", None)
    session = AsyncMock()
    session.scalar.return_value = RUN_URL
    database = MagicMock()
    database.return_value.__aenter__.return_value = session
    monkeypatch.setattr(fournos, "AsyncSessionLocal", database)
    live = Mock(return_value=None)
    monkeypatch.setattr(fournos.k8s, "get_fournos_job", live)
    upstream = Mock()
    options = artifacts.mlflow_client_options
    monkeypatch.setattr(artifacts, "mlflow_client_options", lambda ws: {
        **options(ws), "transport": httpx.MockTransport(upstream),
    })
    app = FastAPI()
    app.include_router(fournos.router)
    with TestClient(app, base_url="http://test/fournos/jobs/demo/mlflow/") as client:
        yield client, session, upstream, live


def sign_in(client):
    client.cookies.set(COOKIE_NAME, create_session_token("team-member", "user"))


@pytest.mark.parametrize("route", ["artifacts", "preview?path=result.txt"])
def test_signed_out_requests_stop_before_lookup(explorer, route):
    client, session, upstream, live = explorer
    assert client.get(route).status_code == 401
    session.scalar.assert_not_called()
    upstream.assert_not_called()
    live.assert_not_called()


def test_folder_uses_recorded_run_and_workspace_and_forwards_pagination(explorer):
    client, _, upstream, live = explorer
    sign_in(client)
    upstream.return_value = httpx.Response(200, json={
        "root_uri": "storage-location",
        "files": [{"path": "test/index.json", "file_size": "120"}, {"path": "test/suite", "is_dir": True}],
        "next_page_token": "second",
    })
    response = client.get("artifacts", params={"path": "test", "page_token": "first", "run_id": "ignored"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "files": [{"path": "test/index.json", "file_size": 120, "is_dir": False},
                  {"path": "test/suite", "file_size": None, "is_dir": True}],
        "next_page_token": "second",
    }
    request = upstream.call_args.args[0]
    assert request.url.host == "mlflow.example"
    assert dict(request.url.params) == {"path": "test", "page_token": "first", "run_id": RUN}
    assert request.headers["X-MLFLOW-WORKSPACE"] == "team"
    live.assert_not_called()


def test_live_reference_when_archive_has_no_link(explorer):
    client, session, upstream, live = explorer
    sign_in(client)
    session.scalar.return_value = None
    live.return_value = {"status": {"engineStatus": {"forge": {"exportArtifacts": {
        "caliper_artifacts_export": {"backends": {"mlflow": {"run_url": RUN_URL}}}
    }}}}}
    upstream.return_value = httpx.Response(200, content=b"duration: 1567")
    response = client.get("preview", params={"path": "test/test_duration.yaml"})
    assert response.status_code == 200 and response.json() == {"text": "duration: 1567"}
    assert response.headers["cache-control"] == "private, no-store"
    request = upstream.call_args.args[0]
    assert dict(request.url.params) == {"run_uuid": RUN, "path": "test/test_duration.yaml"}
    live.assert_called_once_with("demo")


@pytest.mark.parametrize("path", ["../other", "/elsewhere", "a/../b", "a%2Fb", "a\\b"])
def test_invalid_path_stops_before_mlflow(explorer, path):
    client, _, upstream, _ = explorer
    sign_in(client)
    assert client.get("preview?path=" + quote(path, safe="")).status_code == 422
    upstream.assert_not_called()


def test_foreign_link_and_missing_run(explorer):
    client, session, upstream, _ = explorer
    sign_in(client)
    session.scalar.return_value = RUN_URL.replace("mlflow.example", "another.example")
    assert client.get("artifacts").status_code == 422
    session.scalar.return_value = ""
    assert client.get("artifacts").status_code == 404
    upstream.assert_not_called()


@pytest.mark.parametrize("response,status", [
    (httpx.Response(200, content=b"a\x00b"), 415),
    (httpx.Response(200, content=b"\xff"), 415),
    (httpx.Response(302, headers={"Location": "https://another.example/file"}), 502),
    (httpx.Response(401), 403),
    (httpx.Response(404), 404),
    (httpx.Response(200, content=b"x" * (artifacts.PREVIEW_LIMIT + 1)), 413),
    (httpx.Response(200, stream=httpx.ByteStream(b"x" * (artifacts.PREVIEW_LIMIT + 1))), 413),
])
def test_preview_errors_and_stream_limit(explorer, response, status):
    client, _, upstream, _ = explorer
    sign_in(client)
    upstream.return_value = response
    assert client.get("preview", params={"path": "result"}).status_code == status
    assert upstream.call_count == 1
