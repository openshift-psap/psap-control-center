from sqlalchemy import (
    Column, String, Float, DateTime, JSON, Text,
    ForeignKey,
)
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from app.core.database import Base


class ClusterCost(Base):
    __tablename__ = "cluster_costs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    cluster_id = Column(
        String(36),
        ForeignKey("clusters.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    currency = Column(String(10), nullable=False, default="USD")

    billing_month = Column(String(7), nullable=True)  # e.g. "2026-07"
    total_cost = Column(Float, nullable=True)
    node_breakdown = Column(JSON, nullable=True)

    prior_billing_month = Column(String(7), nullable=True)  # e.g. "2026-06"
    prior_total_cost = Column(Float, nullable=True)
    prior_node_breakdown = Column(JSON, nullable=True)

    unmatched_line_items = Column(JSON, nullable=True)
    fetched_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    error = Column(Text, nullable=True)

    cluster = relationship("Cluster", back_populates="cost")

    def __repr__(self):
        return f"<ClusterCost(cluster_id={self.cluster_id}, total_cost={self.total_cost})>"
