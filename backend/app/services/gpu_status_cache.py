"""Shared per-cluster GPU snapshots, ordered by the time the pod list was read."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.gpu_pod_history import ClusterGpuSnapshot


# Allow one missed three-minute refresh before the API makes a live read.
GPU_STATUS_CACHE_TTL_SECONDS = 6 * 60


async def get(db: AsyncSession, cluster_id: str, *, since: datetime | None = None) -> dict | None:
    if since is None:
        since = datetime.utcnow() - timedelta(seconds=GPU_STATUS_CACHE_TTL_SECONDS)
    return await db.scalar(select(ClusterGpuSnapshot.status).where(
        ClusterGpuSnapshot.cluster_id == cluster_id, ClusterGpuSnapshot.observed_at >= since,
    ))


async def store(db: AsyncSession, cluster_id: str, observed_at: datetime, status: dict) -> dict:
    """Lock the cluster's snapshot until commit and return the newest observation."""
    insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else pg_insert
    stmt = insert(ClusterGpuSnapshot).values(
        cluster_id=cluster_id, observed_at=observed_at, status=status,
    )
    accepted = await db.scalar(stmt.on_conflict_do_update(
        index_elements=[ClusterGpuSnapshot.cluster_id],
        set_={"observed_at": stmt.excluded.observed_at, "status": stmt.excluded.status},
        where=ClusterGpuSnapshot.observed_at < stmt.excluded.observed_at,
    ).returning(ClusterGpuSnapshot.cluster_id))
    if accepted is not None:
        return status
    # The TTL controls live reads; even an expired row still orders outstanding writes.
    winner = await db.execute(
        select(ClusterGpuSnapshot.status).where(ClusterGpuSnapshot.cluster_id == cluster_id)
    )
    return winner.scalar_one()
