import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.api import fournos as fournos_api
from app.core import database as database_core
from app.schemas.fournos import HistoryViewState
from app.services import fournos_db_service as db_service


def _query_statement(monkeypatch, **filters):
    monkeypatch.setattr(
        db_service.settings,
        "DATABASE_URL",
        "postgresql+asyncpg://test/test",
    )
    page_result = MagicMock()
    page_result.all.return_value = []
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[page_result, count_result])

    asyncio.run(db_service.list_jobs(session, **filters))

    return session.execute.await_args_list[0].args[0]


def _where_sql(statement) -> str:
    compiled = statement.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": False},
    )
    return str(compiled).split("WHERE", 1)[1]


def test_public_query_uses_non_identity_full_text_vector(monkeypatch):
    statement = _query_statement(monkeypatch, query="zeus forge")
    where_sql = _where_sql(statement)

    assert "to_tsvector" in where_sql
    assert "plainto_tsquery" in where_sql
    assert "source_repository" in where_sql
    assert "requester_email" not in where_sql
    assert "requester_name" not in where_sql


def test_authenticated_identity_query_is_separate(monkeypatch):
    statement = _query_statement(monkeypatch, identity="person@example.com")
    where_sql = _where_sql(statement)

    assert "to_tsvector" in where_sql
    assert "requester_email" in where_sql
    assert "requester_name" in where_sql
    assert "owner" in where_sql


def test_combined_provenance_filters_are_anded_and_index_friendly(monkeypatch):
    statement = _query_statement(
        monkeypatch,
        failure_outcome="failed",
        repository="OpenShift-PSAP/Performance-Scale-CI",
        pr_number=42,
        source_sha="abc123",
        forge="sha256:feedface",
        tags=["nightly", "h200"],
    )
    where_sql = _where_sql(statement)

    assert "failure_outcome" in where_sql
    assert "lower(fournos_jobs.source_repository)" in where_sql
    assert "source_pr_number" in where_sql
    assert "source_requested_sha" in where_sql
    assert "source_resolved_sha" in where_sql
    assert "forge_execution" in where_sql
    assert "split_part" in where_sql
    assert "fournos_jobs.tags @>" in where_sql


def test_history_view_state_normalizes_and_rejects_unknown_fields():
    state = HistoryViewState(
        query="  zeus  ",
        repository="  owner/repo  ",
        tags=[" nightly ", "nightly", "", "h200"],
    )

    assert state.query == "zeus"
    assert state.repository == "owner/repo"
    assert state.tags == ["nightly", "h200"]

    with pytest.raises(ValidationError):
        HistoryViewState.model_validate({"unknown_filter": "unsafe"})

    with pytest.raises(ValidationError):
        HistoryViewState(tags=["x" * 101])

    with pytest.raises(ValidationError):
        HistoryViewState(history_date="2026-99-99")

    with pytest.raises(ValidationError):
        HistoryViewState(from_time="27:15")

    with pytest.raises(ValidationError):
        HistoryViewState(source_sha="not-a-sha")

    with pytest.raises(ValidationError):
        HistoryViewState(per_page=37)

    with pytest.raises(ValidationError):
        HistoryViewState(status="Running")

    with pytest.raises(ValidationError):
        HistoryViewState(failure_outcome="success")


def test_history_preference_is_keyed_by_authenticated_subject(monkeypatch):
    monkeypatch.setattr(db_service.settings, "DATABASE_URL", "sqlite://")
    lookup = MagicMock()
    lookup.scalar_one_or_none.return_value = None
    session = MagicMock()
    session.execute = AsyncMock(return_value=lookup)
    session.flush = AsyncMock()

    preference = asyncio.run(
        db_service.save_history_preference(
            session,
            subject="google:immutable-subject",
            schema_version=1,
            state={"query": "zeus"},
        )
    )

    assert preference.subject == "google:immutable-subject"
    assert preference.state == {"query": "zeus"}
    session.add.assert_called_once_with(preference)
    session.flush.assert_awaited_once()


def test_postgres_preference_save_is_atomic_upsert(monkeypatch):
    monkeypatch.setattr(
        db_service.settings,
        "DATABASE_URL",
        "postgresql+asyncpg://test/test",
    )
    expected = object()
    result = MagicMock()
    result.scalar_one.return_value = expected
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    saved = asyncio.run(
        db_service.save_history_preference(
            session,
            subject="google:immutable-subject",
            schema_version=1,
            state={"query": "zeus"},
        )
    )

    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (subject) DO UPDATE" in sql
    assert saved is expected


def test_identity_search_requires_authentication():
    fournos_api._validate_identity_search("", None)
    fournos_api._validate_identity_search("person@example.com", {"subject": "google:1"})

    with pytest.raises(HTTPException) as exc_info:
        fournos_api._validate_identity_search("person@example.com", None)
    assert exc_info.value.status_code == 401


def test_anonymous_sort_cannot_use_redacted_identity():
    assert fournos_api._visible_sort_by("owner", None) == ""
    assert fournos_api._visible_sort_by("date", None) == "date"
    assert fournos_api._visible_sort_by(
        "owner", {"subject": "google:1"}
    ) == "owner"


def test_history_search_indexes_cover_public_identity_and_tags():
    ddl = "\n".join(database_core._POSTGRES_INDEX_DDLS)
    assert "ix_fournos_jobs_public_search_gin" in ddl
    assert "ix_fournos_jobs_identity_search_gin" in ddl
    assert "ix_fournos_jobs_tags_gin" in ddl
    assert "ix_fournos_jobs_forge_version_prefix" in ddl
    assert "ix_fournos_jobs_forge_digest_prefix" in ddl
    assert "ix_fournos_jobs_requested_sha_prefix" in ddl
    assert "ix_fournos_jobs_resolved_sha_prefix" in ddl
