import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api import fournos, reservations
from app.schemas.reservation import ModificationRequestCreate, ReservationUpdate


def _reservation(*, creator="google:owner", user_name="editable-beneficiary"):
    return SimpleNamespace(
        created_by_subject=creator,
        user_name=user_name,
    )


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
