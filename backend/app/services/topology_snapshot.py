"""One durable, on-demand topology observation per cluster."""
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cluster import ClusterTopologySnapshot as Snapshot
from app.utils.logger import create_logger

logger = create_logger("Topology")
FRESH_FOR = timedelta(minutes=5)
# A stopped backend must eventually release its claim. Late writers are fenced.
CLAIM_LIFETIME = timedelta(minutes=3)


def utcnow():
    return datetime.utcnow()


async def clear_if_target_changed(db, cluster, target):
    if cluster.api_server_url != target:
        await db.execute(delete(Snapshot).where(Snapshot.cluster_id == cluster.id))


async def read(db: AsyncSession, cluster_id: str, known_changed_at: datetime | None = None):
    # Clients that already have this graph need only a few bytes of metadata.
    known = None
    nodes_column = Snapshot.nodes
    if known_changed_at is not None and known_changed_at.tzinfo is not None:
        known = known_changed_at.astimezone(timezone.utc).replace(tzinfo=None)
        nodes_column = case((Snapshot.changed_at != known, Snapshot.nodes))
    result = await db.execute(select(
        Snapshot.checked_at, Snapshot.changed_at, Snapshot.last_check_failed, nodes_column.label("nodes"),
    ).where(Snapshot.cluster_id == cluster_id))
    row = result.first()
    checked = row.checked_at if row else None
    changed = row.changed_at if row else None
    metadata = {
        "last_checked_at": checked.replace(tzinfo=timezone.utc) if checked else None,
        "last_changed_at": changed.replace(tzinfo=timezone.utc) if changed else None,
        "check_due": checked is None or checked <= utcnow() - FRESH_FOR,
        "last_check_failed": bool(row and row.last_check_failed),
    }
    if changed is not None and changed == known:
        return {**metadata, "unchanged": True}

    nodes = (row.nodes if row else None) or []
    control_plane, workers, infra = [], [], []
    for node in nodes:
        roles = node["roles"]
        if "master" in roles or "control-plane" in roles:
            control_plane.append(node)
        elif "infra" in roles:
            infra.append(node)
        else:
            workers.append(node)
    return {
        **metadata,
        "nodes": nodes, "total_nodes": len(nodes), "workers": workers,
        "infra": infra, "control_plane": control_plane,
        "zones": sorted({node["zone"] for node in nodes if node["zone"] != "unknown"}),
    }


async def check(db: AsyncSession, cluster_id: str, discover, known_changed_at: datetime | None = None):
    """Share checks across replicas without holding a DB connection during discovery."""
    started = utcnow()
    insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else pg_insert
    statement = insert(Snapshot).values(cluster_id=cluster_id, checking_since=started)
    claim = statement.on_conflict_do_update(
        index_elements=[Snapshot.cluster_id], set_={"checking_since": started},
        where=(
            or_(Snapshot.checked_at.is_(None), Snapshot.checked_at <= started - FRESH_FOR)
            & or_(Snapshot.checking_since.is_(None), Snapshot.checking_since <= started - CLAIM_LIFETIME)
        ),
    ).returning(Snapshot.checking_since, Snapshot.node_versions, Snapshot.nodes)
    owned = (await db.execute(claim)).first()
    await db.commit()

    if owned is None:
        # Only join a check already in flight. Release the connection between reads.
        delay = 0.2
        while True:
            checking = await db.scalar(select(Snapshot.checking_since).where(Snapshot.cluster_id == cluster_id))
            await db.commit()
            if checking is None or checking <= utcnow() - CLAIM_LIFETIME:
                break
            await asyncio.sleep(delay)
            delay = min(delay * 2, 2)
    else:
        try:
            versions, nodes = await discover(owned.node_versions, owned.nodes)
        except Exception as exc:
            logger.warning(f"Topology check failed for {cluster_id}: {type(exc).__name__}")
            values = {"last_check_failed": True}
        else:
            now = utcnow()
            values = {"checked_at": now, "last_check_failed": False}
            if versions != owned.node_versions:
                values["node_versions"] = versions
            if nodes != owned.nodes:
                values.update(nodes=nodes, changed_at=now)
        await db.execute(update(Snapshot).where(
            Snapshot.cluster_id == cluster_id, Snapshot.checking_since == started,
        ).values(**values, checking_since=None))
        await db.commit()
    return await read(db, cluster_id, known_changed_at)
