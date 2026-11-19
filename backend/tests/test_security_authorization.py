import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api import fournos, reservations
from app.core.auth import COOKIE_NAME, create_session_token
from app.models.fournos_job import FournosJob, FournosJobWorkItem
from app.schemas.fournos import CreateClusterLockRequest
from app.schemas.reservation import ModificationRequestCreate, ReservationUpdate


def _reservation(*, creator="google:owner", user_name="editable-beneficiary"):
    return SimpleNamespace(
        created_by_subject=creator,
        user_name=user_name,
    )


@pytest.mark.parametrize("signed_in", [False, True])
@pytest.mark.parametrize("tab", ["live", "history"])
def test_job_list_owner_is_public_and_work_items_follow_session(monkeypatch, tab, signed_in):
    owner = "Example Owner"
    item = {"provider": "jira", "key": "TEST-1", "url": "https://example.org/TEST-1"}
    live = {"metadata": {"name": "test-job"}, "spec": {"owner": owner}}
    archived = FournosJob(name="test-job", owner=owner, project="demo", cluster="test",
                          pipeline="", preset="", status="Succeeded", message="")
    archived.work_items = [FournosJobWorkItem(**item)]
    monkeypatch.setattr(fournos, "_get_live_jobs", AsyncMock(return_value=[live]))
    monkeypatch.setattr(fournos, "AsyncSessionLocal", MagicMock())
    monkeypatch.setattr(fournos.db_svc, "list_jobs", AsyncMock(return_value=([archived], 1)))
    monkeypatch.setattr(fournos.db_svc, "get_work_items_by_job_names",
                        AsyncMock(return_value={"test-job": [item]}))
    app = FastAPI()
    app.include_router(fournos.router)
    with TestClient(app) as client:
        if signed_in:
            client.cookies.set(COOKIE_NAME, create_session_token("viewer", "user"))
        response = client.get("/fournos/runs", params={"tab": tab})

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    job, = response.json()["jobs"]
    assert job["owner"] == owner
    assert job["work_items"] == ([item] if signed_in else [])


@pytest.mark.parametrize("signed_in", [False, True])
@pytest.mark.parametrize("live", [False, True])
def test_job_detail_shows_recorded_owner_and_protects_requester_data(monkeypatch, live, signed_in):
    owner = "Example Owner"
    work_item = {"provider": "jira", "key": "TEST-1", "url": "https://example.org/TEST-1"}
    archived = FournosJob(name="test-job", owner=owner, project="demo", cluster="test", pipeline="",
                          status="Succeeded", message="", requester_subject="google:fixture", requester_email="private@example.org")
    archived.work_items = [FournosJobWorkItem(**work_item)]
    job = {
        "metadata": {"name": archived.name, "annotations": {fournos.REQUESTER_EMAIL_ANNOTATION: archived.requester_email}},
        "spec": {"owner": owner},
        "status": {"phase": "Pending"},
    }
    monkeypatch.setattr(fournos.k8s, "get_fournos_job", Mock(return_value=job if live else None))
    monkeypatch.setattr(fournos.k8s, "list_pods_for_job", Mock(return_value=[]))
    monkeypatch.setattr(fournos.k8s, "list_pipelineruns_for_job", Mock(return_value=[]))
    monkeypatch.setattr(fournos, "AsyncSessionLocal", MagicMock())
    monkeypatch.setattr(fournos.db_svc, "get_job_by_name", AsyncMock(return_value=archived))
    app = FastAPI()
    app.include_router(fournos.router)
    with TestClient(app) as client:
        if signed_in:
            client.cookies.set(COOKIE_NAME, create_session_token("viewer", "user"))
        response = client.get("/fournos/jobs/test-job")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    data = response.json()
    assert data["job"]["spec"]["owner"] == owner
    assert fournos.REQUESTER_EMAIL_ANNOTATION not in data["job"]["metadata"]["annotations"]
    assert data["work_items"] == ([work_item] if signed_in else [])
    assert data["can_edit_work_items"] is False


def test_reservation_ownership_uses_immutable_subject():
    reservation = _reservation(user_name="attacker@example.com")

    with pytest.raises(HTTPException) as exc_info:
        reservations._require_owner_or_admin(
            reservation,
            {
                "subject": "google:attacker",
                "username": "attacker@example.com",
                "email": "attacker@example.com",
                "name": "attacker@example.com",
                "role": "user",
            },
            "cancel",
        )

    assert exc_info.value.status_code == 403

    reservations._require_owner_or_admin(
        reservation,
        {"subject": "google:owner", "role": "user"},
        "cancel",
    )
    reservations._require_owner_or_admin(
        _reservation(creator=None),
        {"subject": "google:admin", "role": "admin"},
        "cancel",
    )


def test_non_owner_cannot_mutate_reservation(monkeypatch):
    service = SimpleNamespace(
        get_reservation=AsyncMock(return_value=_reservation()),
        update_reservation=AsyncMock(),
        delete_reservation=AsyncMock(),
        cancel_reservation=AsyncMock(),
        request_modification=AsyncMock(),
    )
    monkeypatch.setattr(reservations, "ReservationService", lambda _db: service)
    attacker = {"subject": "google:attacker", "role": "user"}

    async def exercise_routes():
        calls = [
            reservations.update_reservation(
                "reservation-id",
                ReservationUpdate(title="renamed"),
                _user=attacker,
                db=object(),
            ),
            reservations.delete_reservation(
                "reservation-id", _user=attacker, db=object()
            ),
            reservations.cancel_reservation(
                "reservation-id", _user=attacker, db=object()
            ),
            reservations.request_modification(
                "reservation-id",
                ModificationRequestCreate(title="renamed"),
                BackgroundTasks(),
                _user=attacker,
                db=object(),
            ),
        ]
        for call in calls:
            with pytest.raises(HTTPException) as exc_info:
                await call
            assert exc_info.value.status_code == 403

    asyncio.run(exercise_routes())
    service.update_reservation.assert_not_awaited()
    service.delete_reservation.assert_not_awaited()
    service.cancel_reservation.assert_not_awaited()
    service.request_modification.assert_not_awaited()


def test_public_job_metadata_removes_requester_identity_without_mutation():
    metadata = {
        "name": "job-name",
        "annotations": {
            fournos.REQUESTER_SUBJECT_ANNOTATION: "google:12345",
            fournos.REQUESTER_EMAIL_ANNOTATION: "person@example.com",
            fournos.REQUESTER_NAME_ANNOTATION: "Example Person",
            fournos.REQUESTER_PROVIDER_ANNOTATION: "google",
            "example.com/safe": "retained",
        },
    }

    public_metadata = fournos._public_job_metadata(metadata)

    assert public_metadata["annotations"] == {"example.com/safe": "retained"}
    assert fournos.REQUESTER_EMAIL_ANNOTATION in metadata["annotations"]


def test_public_job_spec_keeps_run_owner_and_hides_standalone_lock_holder():
    spec = {"cluster": "test-cluster", "owner": "Example Person"}
    assert fournos._public_job_spec(spec, include_lock_owner=False) == spec
    lock = {**spec, "lockOnly": True}
    assert "owner" not in fournos._public_job_spec(lock, include_lock_owner=False)
    assert fournos._public_job_spec(lock, include_lock_owner=True) == lock
    assert lock["owner"] == "Example Person"


def test_anonymous_cpt_list_shows_owners_without_enabling_owner_filter(monkeypatch):
    from starlette.requests import Request

    group = {
        "id": "group-id",
        "project": "rhaiis",
        "version_label": "vLLM-0.26.0",
        "accelerator": "amd",
        "cluster": "mi355x",
        "status": "Succeeded",
        "owners": ["runner"],
        "owner_label": "runner",
        "attempts": [{"id": "run-id", "owner": "runner"}],
    }

    async def load_groups(group_ids):
        return [group] if group["id"] in group_ids else []

    async def page_group_ids(_filters, _page, _per_page):
        return 1, [group["id"]]

    async def filter_options(include_owner):
        return {
            "projects": ["rhaiis"],
            "versions": ["vLLM-0.26.0"],
            "accelerators": ["amd"],
            "clusters": ["mi355x"],
            "owners": ["runner"] if include_owner else [],
        }

    monkeypatch.setattr(fournos, "_load_cpt_run_groups", load_groups)
    monkeypatch.setattr(fournos, "_page_cpt_group_ids", page_group_ids)
    monkeypatch.setattr(fournos, "_cpt_filter_options", filter_options)
    request = Request({"type": "http", "headers": []})

    response = asyncio.run(fournos.list_cpt_runs(
        request,
        project="",
        version="",
        accelerator="",
        cluster="",
        owner="runner",
        show_stopped=False,
    ))

    assert len(response["groups"]) == 1
    assert response["groups"][0]["owners"] == ["runner"]
    assert response["groups"][0]["owner_label"] == "runner"
    assert response["groups"][0]["attempts"][0]["owner"] == "runner"
    assert response["filter_options"]["owners"] == []


def test_authenticated_cpt_list_retains_owner_filter(monkeypatch):
    from starlette.requests import Request

    groups = [
        {
            "id": "owned",
            "project": "rhaiis",
            "version_label": "vLLM-0.26.0",
            "accelerator": "amd",
            "cluster": "mi355x",
            "status": "Succeeded",
            "owners": ["runner"],
            "owner_label": "runner",
            "attempts": [{"id": "run-id", "owner": "runner"}],
        },
        {
            "id": "other",
            "project": "rhaiis",
            "version_label": "vLLM-0.26.0",
            "accelerator": "amd",
            "cluster": "mi355x",
            "status": "Succeeded",
            "owners": ["other"],
            "owner_label": "other",
            "attempts": [{"id": "other-run", "owner": "other"}],
        },
    ]

    async def load_groups(group_ids):
        return [group for group in groups if group["id"] in group_ids]

    async def page_group_ids(filters, _page, _per_page):
        matching = [group for group in groups if not filters["owner"] or filters["owner"] in group["owners"]]
        return len(matching), [group["id"] for group in matching]

    async def filter_options(include_owner):
        return {
            "projects": ["rhaiis"],
            "versions": ["vLLM-0.26.0"],
            "accelerators": ["amd"],
            "clusters": ["mi355x"],
            "owners": ["other", "runner"] if include_owner else [],
        }

    monkeypatch.setattr(fournos, "_load_cpt_run_groups", load_groups)
    monkeypatch.setattr(fournos, "_page_cpt_group_ids", page_group_ids)
    monkeypatch.setattr(fournos, "_cpt_filter_options", filter_options)
    monkeypatch.setattr(fournos, "get_current_user", lambda _request: {"subject": "user"})
    request = Request({"type": "http", "headers": []})

    response = asyncio.run(fournos.list_cpt_runs(
        request,
        project="",
        version="",
        accelerator="",
        cluster="",
        owner="runner",
        show_stopped=False,
    ))

    assert [group["id"] for group in response["groups"]] == ["owned"]
    assert response["groups"][0]["owners"] == ["runner"]
    assert response["filter_options"]["owners"] == ["other", "runner"]


def test_public_cpt_detail_shows_owners(monkeypatch):
    group = {
        "id": "group-id",
        "owners": ["runner"],
        "owner_label": "runner",
        "attempts": [{"id": "run-id", "owner": "runner"}],
    }

    async def load_groups(group_ids):
        return [group] if group["id"] in group_ids else []

    monkeypatch.setattr(fournos, "_load_cpt_run_groups", load_groups)
    response = asyncio.run(fournos.get_cpt_run_group("group-id"))

    assert response["owners"] == ["runner"]
    assert response["owner_label"] == "runner"
    assert response["attempts"][0]["owner"] == "runner"


def test_live_summary_requires_successful_kubernetes_list(monkeypatch):
    observed = []

    async def get_live_jobs(*, raise_on_error=False):
        observed.append(raise_on_error)
        if raise_on_error:
            raise RuntimeError("Kubernetes API unavailable")
        return []

    monkeypatch.setattr(fournos, "_get_live_jobs", get_live_jobs)

    with pytest.raises(RuntimeError, match="Kubernetes API unavailable"):
        asyncio.run(fournos.live_jobs_summary())

    assert observed == [True]


def test_testing_owner_prefers_verified_display_name():
    user = {
        "subject": "google:12345",
        "username": "person@example.com",
        "email": "person@example.com",
        "name": "Example Person",
        "auth_provider": "google",
        "role": "user",
    }

    assert fournos._verified_owner(user) == "Example Person"
    assert fournos._verified_owner({**user, "name": ""}) == "person@example.com"


def test_requester_scope_uses_only_authenticated_subject():
    user = {"subject": "google:12345"}

    assert fournos._requester_subject_for_scope("all", None) is None
    assert fournos._requester_subject_for_scope("mine", user) == "google:12345"

    with pytest.raises(HTTPException) as exc_info:
        fournos._requester_subject_for_scope("mine", None)
    assert exc_info.value.status_code == 401


def test_live_requester_filter_reads_immutable_annotation():
    job = {
        "metadata": {
            "annotations": {
                fournos.REQUESTER_SUBJECT_ANNOTATION: "google:12345",
            }
        },
        "spec": {"owner": "Editable Display Name"},
    }

    assert fournos._live_job_requester_subject(job) == "google:12345"
    assert fournos._live_job_requester_subject({"metadata": {}}) == ""


def test_recurring_child_inherits_requester_for_live_filter_without_mutation():
    child = {
        "metadata": {
            "labels": {fournos.k8s.LABEL_RECURRING_PARENT: "nightly-parent"}
        }
    }

    resolved = fournos._inherit_live_requester(
        child, {"nightly-parent": "google:12345"}
    )

    assert fournos._live_job_requester_subject(resolved) == "google:12345"
    assert fournos._live_job_requester_subject(child) == ""


def test_cluster_lock_ignores_client_supplied_owner(monkeypatch):
    captured = {}

    def create_fournos_job(body):
        captured["body"] = body
        return body

    monkeypatch.setattr(fournos.k8s, "create_fournos_job", create_fournos_job)
    user = {
        "subject": "google:12345",
        "username": "person@example.com",
        "email": "person@example.com",
        "name": "Example Person",
        "auth_provider": "google",
        "role": "user",
    }
    request = CreateClusterLockRequest(
        cluster="test-cluster",
        owner="Spoofed Owner",
        reason="Maintenance",
    )

    response = asyncio.run(fournos.create_cluster_lock(request, user=user))

    assert captured["body"]["spec"]["owner"] == "Example Person"
    assert response["owner"] == "Example Person"
