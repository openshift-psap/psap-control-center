"""Shared fixtures for MCP server tests."""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from control_center_mcp.client import ControlCenterClient

# ---------------------------------------------------------------------------
# Sample data returned by the mock client
# ---------------------------------------------------------------------------

SAMPLE_CLUSTERS: dict[str, Any] = {
    "clusters": [
        {
            "id": "1",
            "name": "gpu-cluster-01",
            "status": "healthy",
            "gpu_count": "8",
            "gpu_type": "A100",
            "provider": "ibm",
            "is_active": True,
        },
        {
            "id": "2",
            "name": "gpu-cluster-02",
            "status": "healthy",
            "gpu_count": "4",
            "gpu_type": "H100",
            "provider": "aws",
            "is_active": True,
        },
        {
            "id": "3",
            "name": "inactive-cluster",
            "status": "unreachable",
            "gpu_count": "0",
            "gpu_type": None,
            "provider": "ibm",
            "is_active": False,
        },
    ],
    "total": 3,
}

SAMPLE_OCCUPANCY_FREE: dict[str, Any] = {
    "occupied": False,
    "reservations": [],
}

SAMPLE_OCCUPANCY_BUSY: dict[str, Any] = {
    "occupied": True,
    "reservations": [
        {
            "user_name": "bob",
            "team": "ml-ops",
            "title": "Training run",
            "start_time": "2025-06-01T08:00:00Z",
            "end_time": "2025-06-01T20:00:00Z",
            "reservation_type": "cluster",
            "gpu_count": None,
        },
    ],
}

SAMPLE_RESERVATIONS: dict[str, Any] = {
    "reservations": [
        {
            "id": "10",
            "title": "alice job",
            "cluster_id": "1",
            "cluster_name": "gpu-cluster-01",
            "user_name": "alice",
            "user_email": "alice@example.com",
            "team": "ml-training",
            "start_time": "2025-06-01T09:00:00Z",
            "end_time": "2025-06-01T17:00:00Z",
            "status": "active",
            "reservation_type": "cluster",
            "gpu_count": None,
        },
        {
            "id": "11",
            "title": "bob job",
            "cluster_id": "2",
            "cluster_name": "gpu-cluster-02",
            "user_name": "bob",
            "user_email": "bob@example.com",
            "team": "ml-ops",
            "start_time": "2025-06-01T10:00:00Z",
            "end_time": "2025-06-01T12:00:00Z",
            "status": "active",
            "reservation_type": "gpu",
            "gpu_count": 2,
        },
    ],
    "total": 2,
}

SAMPLE_CREATED_RESERVATION: dict[str, Any] = {
    "id": "99",
    "title": "alice on gpu-cluster-01",
    "cluster_id": "1",
    "cluster_name": "gpu-cluster-01",
    "user_name": "alice",
    "user_email": "alice@example.com",
    "team": "ml-training",
    "start_time": "2025-06-01T09:00:00Z",
    "end_time": "2025-06-01T17:00:00Z",
    "status": "active",
    "reservation_type": "cluster",
}

SAMPLE_CANCELLED_RESERVATION: dict[str, Any] = {
    "id": "10",
    "title": "alice job",
    "cluster_id": "1",
    "cluster_name": "gpu-cluster-01",
    "user_name": "alice",
    "status": "cancelled",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_client() -> ControlCenterClient:
    """Return a ControlCenterClient with all methods mocked.

    The underlying ``_client`` is set to a sentinel so tests can verify
    connection reuse without hitting a real server.
    """
    client = ControlCenterClient(base_url="http://test:8000")
    client.list_clusters = AsyncMock(return_value=SAMPLE_CLUSTERS)
    client.get_cluster = AsyncMock()
    client.list_reservations = AsyncMock(return_value=SAMPLE_RESERVATIONS)
    client.get_current_reservation = AsyncMock(return_value=SAMPLE_OCCUPANCY_FREE)
    client.create_reservation = AsyncMock(return_value=(201, SAMPLE_CREATED_RESERVATION))
    client.cancel_reservation = AsyncMock(return_value=(200, SAMPLE_CANCELLED_RESERVATION))
    client.hard_delete_reservation = AsyncMock(return_value=204)
    return client
