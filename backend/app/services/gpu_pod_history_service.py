from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, tuple_, update
from datetime import datetime
from typing import List, Dict, Any

from app.models.gpu_pod_history import ClusterGpuSnapshot, GpuPodHistory
from app.services import gpu_status_cache
from app.services.kubernetes_service import GpuAllocationStatus


async def record_gpu_snapshot(db: AsyncSession, cluster_id: str, allocation: GpuAllocationStatus) -> dict:
    """Stage the latest snapshot and complete inventory together in the caller's transaction."""
    observed_at = allocation.observed_at
    snapshot = allocation.to_dict()
    latest = await gpu_status_cache.store(db, cluster_id, observed_at, snapshot)
    if allocation.pod_inventory_complete:
        # A newer incomplete probe can refresh allocation counts, but only complete
        # lists establish that pods are gone. Advance the two timestamps independently.
        advanced = await db.scalar(
            update(ClusterGpuSnapshot)
            .where(
                ClusterGpuSnapshot.cluster_id == cluster_id,
                or_(
                    ClusterGpuSnapshot.pod_inventory_at.is_(None),
                    ClusterGpuSnapshot.pod_inventory_at < observed_at,
                ),
            )
            .values(pod_inventory_at=observed_at)
            .returning(ClusterGpuSnapshot.cluster_id)
        )
        if advanced is not None:
            await _sync_gpu_pods(db, cluster_id, snapshot["gpu_pods"], observed_at)
    return latest


async def _sync_gpu_pods(
    db: AsyncSession,
    cluster_id: str,
    active_pods: List[Dict[str, Any]],
    observed_at: datetime,
) -> None:
    active_keys = {
        (p["namespace"], p["name"]) for p in active_pods
    }

    # Include finished rows only for pods we see again. Most historical rows
    # never need to be read during periodic cluster refreshes.
    relevant_rows = GpuPodHistory.finished_at.is_(None)
    if active_keys:
        relevant_rows = or_(
            relevant_rows,
            tuple_(GpuPodHistory.namespace, GpuPodHistory.pod_name).in_(active_keys),
        )
    result = await db.execute(
        select(GpuPodHistory).where(
            GpuPodHistory.cluster_id == cluster_id,
            relevant_rows,
        ).execution_options(populate_existing=True)
    )
    existing: List[GpuPodHistory] = list(
        result.scalars().all()
    )
    existing_by_key = {
        (r.namespace, r.pod_name): r for r in existing
    }

    for key, record in existing_by_key.items():
        if key not in active_keys and record.finished_at is None:
            record.finished_at = observed_at
            record.last_seen = observed_at

    for pod in active_pods:
        key = (pod["namespace"], pod["name"])
        if key in existing_by_key:
            record = existing_by_key[key]
            if record.finished_at is not None:
                record.finished_at = None
                record.first_seen = observed_at
            record.last_seen = observed_at
            record.gpu_count = pod["gpu_count"]
            record.node = pod.get("node")
        else:
            db.add(GpuPodHistory(
                cluster_id=cluster_id,
                pod_name=pod["name"],
                namespace=pod["namespace"],
                gpu_count=pod["gpu_count"],
                node=pod.get("node"),
                first_seen=observed_at,
                last_seen=observed_at,
            ))


async def get_pod_history(
    db: AsyncSession,
    cluster_id: str,
    limit: int = 25,
) -> List[GpuPodHistory]:
    """Return recently finished GPU pods, newest first."""
    result = await db.execute(
        select(GpuPodHistory)
        .where(
            and_(
                GpuPodHistory.cluster_id == cluster_id,
                GpuPodHistory.finished_at.is_not(None),
            )
        )
        .order_by(GpuPodHistory.finished_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
