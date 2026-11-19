from datetime import date, datetime, timezone
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import fournos
from app.services.recurring_schedule import calendar_starts


@pytest.mark.parametrize("last_scheduled,created,trigger_now,phase,pending", [
    ("2026-11-18T10:00:00Z", "2026-11-17T09:00:00Z", False, "Recurring", True),
    (None, "2026-11-19T09:00:00Z", False, "Recurring", True),
    ("invalid", "2026-11-19T09:00:00Z", False, "Recurring", True),
    ("2026-11-19T10:01:00Z", "2026-11-17T09:00:00Z", False, "Recurring", False),
    (None, "2026-11-19T10:02:00Z", True, "Recurring", True),
    (None, "2026-11-19T10:02:00Z", True, "Stopped", False),
])
def test_recurring_dispatch_state(last_scheduled, created, trigger_now, phase, pending):
    job = {
        "metadata": {"creationTimestamp": created, "annotations": {fournos.k8s.ANNOTATION_TRIGGER_NOW: str(trigger_now)}},
        "spec": {"schedule": "0 10 * * *"},
        "status": {"phase": phase, "lastScheduledTime": last_scheduled},
    }
    now = datetime(2026, 11, 19, 10, 5, tzinfo=timezone.utc)
    row = fournos._recurring_job_to_response(job, include_lock_owner=False, as_of=now)
    assert row["dispatch_pending"] is pending
    assert row["next_scheduled_time"] == (
        datetime(2026, 11, 20, 10, tzinfo=timezone.utc) if phase == "Recurring" else None
    )


def test_warning_and_calendar_use_the_same_fournos_schedules(monkeypatch):
    class FixedTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 19, 10, tzinfo=timezone.utc).astimezone(tz)

    def template(name, schedule, phase="Recurring", cluster="demo"):
        return {
            "metadata": {"name": name}, "spec": {"cluster": cluster, "schedule": schedule},
            "status": {"phase": phase},
        }

    listed = Mock(return_value=[
        template("quarter-hour", "*/15 * * * *"),
        template("monthly", "0 12 1 * *"),
        template("weekday", "0,30 10-12 * NOV MON-FRI"),
        template("invalid", "not a schedule"),
        template("stopped", "*/15 * * * *", phase="Stopped"),
        template("elsewhere", "* * * * *", cluster="another"),
    ])
    monkeypatch.setattr(fournos, "datetime", FixedTime)
    monkeypatch.setattr(fournos.k8s, "list_fournos_jobs", listed)
    app = FastAPI()
    app.include_router(fournos.router)
    with TestClient(app) as client:
        def overview(**params):
            response = client.get("/fournos/clusters/demo/overview", params=params)
            assert response.status_code == 200, response.text
            return {j["name"]: j for j in response.json()["recurring_jobs"]}

        live = overview()
        assert "elsewhere" not in live
        assert live["quarter-hour"]["next_scheduled_time"] == "2026-11-19T10:15:00Z"
        assert live["monthly"]["next_scheduled_time"] == "2026-12-01T12:00:00Z"
        assert live["stopped"]["next_scheduled_time"] is None
        assert live["invalid"]["next_scheduled_time"] is None
        listed.assert_called_once_with(raise_on_error=True)
        day = overview(calendar_date="2026-11-19", calendar_timezone="America/New_York")
        starts = day["quarter-hour"]["calendar_starts"]["2026-11-19"]
        assert len(starts) == 96
        assert starts[20:24] == ["05:00", "05:15", "05:30", "05:45"]
        assert day["weekday"]["calendar_starts"]["2026-11-19"] == [
            "05:00", "05:30", "06:00", "06:30", "07:00", "07:30",
        ]
        assert all(day[name]["calendar_starts"] == {} for name in ("monthly", "stopped", "invalid"))
        month = overview(calendar_date="2026-11-19", calendar_view="month", calendar_timezone="America/New_York")
        assert month["monthly"]["calendar_starts"] == {"2026-11-01": ["07:00"]}
        assert len(month["quarter-hour"]["calendar_starts"]) == 30
        assert month["quarter-hour"]["calendar_starts"]["2026-11-19"] == ["00:00"]


def test_calendar_uses_local_day_boundaries_and_template_creation_time():
    zone = ZoneInfo("America/New_York")
    fall = calendar_starts("0 * * * *", date(2026, 11, 1), "day", zone, None)
    assert len(fall["2026-11-01"]) == 25
    spring = calendar_starts("0 * * * *", date(2026, 3, 8), "day", zone, None)
    assert len(spring["2026-03-08"]) == 23
    created = datetime(2026, 11, 19, 23, 15, tzinfo=timezone.utc)
    starts = calendar_starts("*/15 * * * *", created.date(), "day", ZoneInfo("UTC"), created)
    assert starts == {"2026-11-19": ["23:30", "23:45"]}
