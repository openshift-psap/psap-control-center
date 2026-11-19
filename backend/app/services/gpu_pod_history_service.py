from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, tuple_
from datetime import datetime
from typing import List, Dict, Any

from app.models.cluster import Cluster
from app.models.gpu_pod_history import GpuPodHistory
from app.services import gpu_status_cache
from app.services.kubernetes_service import GpuAllocationStatus
from app.utils.logger import create_logger

logger = create_logger("GpuPodHistoryService")


async def record_gpu_snapshot(db: AsyncSession, cluster_id: str, allocation: GpuAllocationStatus) -> dict:
    """Publish a fresh observation. Only a complete pod list can retire missing pods."""
    snapshot = allocation.to_dict()
    gpu_status_cache.store(cluster_id, snapshot)
    if allocation.pod_inventory_complete:
        try:
            await sync_gpu_pods(db, cluster_id, snapshot["gpu_pods"])
        except Exception as exc:
            await db.rollback()
            logger.warning(f"GPU pod history sync failed for cluster {cluster_id}: {exc}")
    return snapshot


async def sync_gpu_pods(
    db: AsyncSession,
    cluster_id: str,
    active_pods: List[Dict[str, Any]],
) -> None:
    """
    Upsert currently-running GPU pods and mark
    vanished ones as finished.
    """
    # A cold API read and a scheduled refresh may discover the same new pod.
    # Serialize their upserts per cluster, including across backend workers.
    await db.execute(select(Cluster.id).where(Cluster.id == cluster_id).with_for_update())
    now = datetime.utcnow()

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
        )
    )
    existing: List[GpuPodHistory] = list(
        result.scalars().all()
    )
    existing_by_key = {
        (r.namespace, r.pod_name): r for r in existing
    }

    for key, record in existing_by_key.items():
        if key not in active_keys and record.finished_at is None:
            record.finished_at = now
            record.last_seen = now

    for pod in active_pods:
        key = (pod["namespace"], pod["name"])
        if key in existing_by_key:
            record = existing_by_key[key]
            if record.finished_at is not None:
                record.finished_at = None
                record.first_seen = now
            record.last_seen = now
            record.gpu_count = pod["gpu_count"]
            record.node = pod.get("node")
        else:
            db.add(GpuPodHistory(
                cluster_id=cluster_id,
                pod_name=pod["name"],
                namespace=pod["namespace"],
                gpu_count=pod["gpu_count"],
                node=pod.get("node"),
                first_seen=now,
                last_seen=now,
            ))

    await db.commit()


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
