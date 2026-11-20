import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.api import clusters as clusters_api
from app.schemas.cluster import RefreshDisplayPreferenceUpdate
from app.services import user_preference_service


def test_refresh_display_mode_is_allowlisted():
    assert RefreshDisplayPreferenceUpdate(mode="countdown").mode == "countdown"
    assert RefreshDisplayPreferenceUpdate(mode="last_update").mode == "last_update"

    with pytest.raises(ValidationError):
        RefreshDisplayPreferenceUpdate(mode="arbitrary")


def test_new_preference_is_keyed_by_subject_and_name(monkeypatch):
    monkeypatch.setattr(
        user_preference_service.settings,
        "DATABASE_URL",
        "sqlite+aiosqlite:///test.db",
    )
    lookup = MagicMock()
    lookup.scalar_one_or_none.return_value = None
    session = MagicMock()
    session.execute = AsyncMock(return_value=lookup)
    session.flush = AsyncMock()

    preference = asyncio.run(user_preference_service.save_preference(
        session,
        subject="google:immutable-subject",
        preference_key="clusters.refresh_display_mode",
        value={"mode": "last_update"},
    ))

    assert preference.subject == "google:immutable-subject"
    assert preference.preference_key == "clusters.refresh_display_mode"
    assert preference.value == {"mode": "last_update"}
    session.add.assert_called_once_with(preference)
    session.flush.assert_awaited_once()


def test_postgres_preference_save_is_atomic_upsert(monkeypatch):
    monkeypatch.setattr(
        user_preference_service.settings,
        "DATABASE_URL",
        "postgresql+asyncpg://test/test",
    )
    expected = object()
    result = MagicMock()
    result.scalar_one.return_value = expected
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    saved = asyncio.run(user_preference_service.save_preference(
        session,
        subject="google:immutable-subject",
        preference_key="clusters.refresh_display_mode",
        value={"mode": "countdown"},
    ))

    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (subject, preference_key) DO UPDATE" in sql
    assert saved is expected


def test_missing_refresh_preference_defaults_to_countdown(monkeypatch):
    monkeypatch.setattr(
        clusters_api.user_preference_service,
        "get_preference",
        AsyncMock(return_value=None),
    )

    db = object()
    response = asyncio.run(clusters_api.get_refresh_display_preference(
        user={"subject": "google:user-one"},
        db=db,
    ))

    assert response.mode == "countdown"
    clusters_api.user_preference_service.get_preference.assert_awaited_once_with(
        db,
        subject="google:user-one",
        preference_key=clusters_api.REFRESH_DISPLAY_PREFERENCE_KEY,
    )


def test_refresh_preference_update_uses_authenticated_subject(monkeypatch):
    timestamp = datetime.now(timezone.utc)
    saved = SimpleNamespace(updated_at=timestamp)
    save = AsyncMock(return_value=saved)
    monkeypatch.setattr(
        clusters_api.user_preference_service,
        "save_preference",
        save,
    )
    db = MagicMock()
    db.commit = AsyncMock()

    response = asyncio.run(clusters_api.update_refresh_display_preference(
        RefreshDisplayPreferenceUpdate(mode="last_update"),
        user={"subject": "google:user-one"},
        db=db,
    ))

    assert response.mode == "last_update"
    assert response.updated_at == timestamp
    save.assert_awaited_once_with(
        db,
        subject="google:user-one",
        preference_key=clusters_api.REFRESH_DISPLAY_PREFERENCE_KEY,
        value={"mode": "last_update"},
    )
    db.commit.assert_awaited_once()


def test_sidebar_choices_round_trip_for_the_authenticated_account_only(monkeypatch):
    import httpx
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.api import auth as auth_api
    from app.core.auth import COOKIE_NAME, create_session_token
    from app.core.database import get_db
    from app.models.user_preference import UserPreference

    monkeypatch.setattr(user_preference_service.settings, "DATABASE_URL", "sqlite+aiosqlite://")

    async def exercise():
        engine = create_async_engine("sqlite+aiosqlite://")
        try:
            async with engine.begin() as conn:
                await conn.run_sync(UserPreference.__table__.create)
            sessions = async_sessionmaker(engine, expire_on_commit=False)

            async def test_db():
                async with sessions() as session:
                    yield session

            app = FastAPI()
            app.include_router(auth_api.router)
            app.dependency_overrides[get_db] = test_db
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                assert (await client.get("/me/sidebar")).status_code == 401
                assert (await client.put("/me/sidebar/desktop", json={"expanded": False})).status_code == 401
                first = create_session_token("first", "user", subject="local:first")
                client.cookies.set(COOKIE_NAME, first)
                assert (await client.put("/me/sidebar/tools", json={"expanded": False})).is_success
                assert (await client.put("/me/sidebar/desktop", json={"expanded": False})).is_success
                assert (await client.put("/me/sidebar/desktop", json={"expanded": True})).is_success
                assert (await client.put("/me/sidebar/arbitrary", json={"expanded": True})).status_code == 422
                client.cookies.set(COOKIE_NAME, create_session_token("second", "user", subject="local:second"))
                assert (await client.get("/me/sidebar")).json() == {}
                client.cookies.set(COOKIE_NAME, first)
                assert (await client.get("/me/sidebar")).json() == {"desktop": True, "tools": False}
        finally:
            await engine.dispose()

    asyncio.run(exercise())
