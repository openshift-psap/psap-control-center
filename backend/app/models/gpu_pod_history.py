from sqlalchemy import (
    Column, String, Integer, DateTime, JSON,
    ForeignKey, UniqueConstraint,
)
from datetime import datetime
import uuid

from app.core.database import Base


class ClusterGpuSnapshot(Base):
    __tablename__ = "cluster_gpu_snapshots"

    cluster_id = Column(String(36), ForeignKey("clusters.id", ondelete="CASCADE"), primary_key=True)
    observed_at = Column(DateTime, nullable=False)
    status = Column(JSON, nullable=False)
    # A newer partial allocation can update the display, but cannot retire pods.
    pod_inventory_at = Column(DateTime, nullable=True)


class GpuPodHistory(Base):
    __tablename__ = "gpu_pod_history"

    id = Column(
        String(36), primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    cluster_id = Column(
        String(36),
        ForeignKey("clusters.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    pod_name = Column(String(512), nullable=False)
    namespace = Column(String(255), nullable=False)
    gpu_count = Column(Integer, nullable=False, default=1)
    node = Column(String(255), nullable=True)
    first_seen = Column(
        DateTime, nullable=False, default=datetime.utcnow,
    )
    last_seen = Column(
        DateTime, nullable=False, default=datetime.utcnow,
    )
    finished_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "cluster_id", "namespace", "pod_name",
            name="uq_cluster_ns_pod",
        ),
    )

    def __repr__(self):
        return (
            f"<GpuPodHistory("
            f"{self.namespace}/{self.pod_name} "
            f"gpu={self.gpu_count})>"
        )
