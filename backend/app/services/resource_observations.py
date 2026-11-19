"""Last successful observations for cluster panels and management inventory."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, select

from app.models.cluster import ResourceObservation as Observation
from app.services import snapshot_checks

INVENTORY_TTL = timedelta(minutes=5)
WORKLOAD_TTL = timedelta(seconds=30)
LOCK_TTL = timedelta(seconds=15)


def _due(row, now, ttl):
    if row is None:
        return True
    if row.failed_at:
        return row.failed_at <= now - snapshot_checks.RETRY_DELAY
    return row.checked_at is None or row.checked_at <= now - ttl


async def observe(db, source, section, *, cluster_id=None, ttl=INVENTORY_TTL, discover=None, known_changed_at=None):
    key = {"source": source, "section": section}
    # Most returning viewers need timestamps only. Leave the full workload list
    # and Kubernetes revision maps in the database on those requests.
    payload = Observation.payload
    if known_changed_at is not None and known_changed_at.tzinfo is not None:
        known = known_changed_at.astimezone(timezone.utc).replace(tzinfo=None)
        payload = case((Observation.changed_at != known, Observation.payload))
    statement = select(
        payload.label("payload"), Observation.checked_at, Observation.changed_at,
        Observation.failed_at, Observation.last_check_failed,
    ).filter_by(**key)
    row = (await db.execute(statement)).first()
    if discover is not None and _due(row, datetime.utcnow(), ttl):
        async def collect(old):
            payload, versions = await discover(old.payload, old.versions)
            values = {}
            if payload != old.payload:
                values.update(payload=payload, changed_at=datetime.utcnow())
            if versions != old.versions:
                values["versions"] = versions
            return values

        await snapshot_checks.refresh(
            db, Observation, key, fresh_for=ttl, columns=(Observation.payload, Observation.versions),
            initial={"cluster_id": cluster_id}, collect=collect,
        )
        row = (await db.execute(statement)).first()
    checked = row.checked_at if row else None
    changed = row.changed_at if row else None
    return (row.payload if row else None), {
        "last_checked_at": checked.replace(tzinfo=timezone.utc) if checked else None,
        "last_changed_at": changed.replace(tzinfo=timezone.utc) if changed else None,
        "last_check_failed": bool(row and row.last_check_failed),
        "check_due": _due(row, datetime.utcnow(), ttl),
    }
