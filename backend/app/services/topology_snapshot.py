"""One durable, on-demand topology observation per cluster."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cluster import ClusterTopologySnapshot as Snapshot, ResourceObservation
from app.services import snapshot_checks

FRESH_FOR = timedelta(minutes=5)


def utcnow():
    return datetime.utcnow()


async def clear_if_target_changed(db, cluster, target):
    # A replacement identity on the same server can see different namespaces or operators.
    await db.execute(delete(ResourceObservation).where(ResourceObservation.cluster_id == cluster.id))
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
    async def collect(old):
        versions, nodes = await discover(old.node_versions, old.nodes)
        values = {}
        if versions != old.node_versions:
            values["node_versions"] = versions
        if nodes != old.nodes:
            values.update(nodes=nodes, changed_at=utcnow())
        return values

    await snapshot_checks.refresh(
        db, Snapshot, {"cluster_id": cluster_id}, fresh_for=FRESH_FOR,
        columns=(Snapshot.node_versions, Snapshot.nodes), collect=collect, clock=utcnow,
    )
    return await read(db, cluster_id, known_changed_at)
