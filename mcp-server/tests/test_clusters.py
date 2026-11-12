"""Tests for cluster tools."""

from unittest.mock import AsyncMock

import httpx
import pytest

from control_center_mcp.client import ControlCenterClient
from control_center_mcp.tools.clusters import (
    get_cluster_status,
    list_available_clusters,
    list_clusters,
)

SAMPLE_OCCUPANCY_FREE: dict = {
    "occupied": False,
    "reservations": [],
}

SAMPLE_OCCUPANCY_BUSY: dict = {
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

SAMPLE_RESERVATIONS_ACTIVE: dict = {
    "reservations": [
        {
            "id": "10",
            "cluster_id": "1",
            "status": "active",
            "user_name": "alice",
        },
    ],
    "total": 1,
}

SAMPLE_RESERVATIONS_EMPTY: dict = {
    "reservations": [],
    "total": 0,
}


# --- list_clusters ---------------------------------------------------------


@pytest.mark.asyncio
async def test_list_clusters_ok(mock_client: ControlCenterClient) -> None:
    result = await list_clusters(client=mock_client)
    assert result["status"] == "ok"
    assert result["total"] == 3
    names = [c["name"] for c in result["clusters"]]
    assert "gpu-cluster-01" in names


@pytest.mark.asyncio
async def test_list_clusters_connection_error(mock_client: ControlCenterClient) -> None:
    mock_client.list_clusters = AsyncMock(side_effect=httpx.ConnectError("refused"))
    result = await list_clusters(client=mock_client)
    assert result["status"] == "error"
    assert "Connection error" in result["message"]


@pytest.mark.asyncio
async def test_list_clusters_returns_all_fields(mock_client: ControlCenterClient) -> None:
    """Ensure returned cluster dicts contain expected keys."""
    result = await list_clusters(client=mock_client)
    for cluster in result["clusters"]:
        assert "id" in cluster
        assert "name" in cluster
        assert "status" in cluster
        assert "gpu_count" in cluster
        assert "gpu_type" in cluster
        assert "provider" in cluster
        assert "is_active" in cluster


@pytest.mark.asyncio
async def test_list_clusters_empty(mock_client: ControlCenterClient) -> None:
    """Handle an empty clusters list."""
    mock_client.list_clusters = AsyncMock(return_value={"clusters": [], "total": 0})
    result = await list_clusters(client=mock_client)
    assert result["status"] == "ok"
    assert result["total"] == 0
    assert result["clusters"] == []


# --- get_cluster_status ----------------------------------------------------


@pytest.mark.asyncio
async def test_get_cluster_status_available(mock_client: ControlCenterClient) -> None:
    mock_client.get_current_reservation = AsyncMock(return_value=SAMPLE_OCCUPANCY_FREE)
    result = await get_cluster_status("gpu-cluster-01", client=mock_client)
    assert result["status"] == "available"
    assert result["cluster_name"] == "gpu-cluster-01"


@pytest.mark.asyncio
async def test_get_cluster_status_occupied(mock_client: ControlCenterClient) -> None:
    mock_client.get_current_reservation = AsyncMock(return_value=SAMPLE_OCCUPANCY_BUSY)
    result = await get_cluster_status("GPU-CLUSTER-01", client=mock_client)
    assert result["status"] == "occupied"
    assert result["reservation"]["user_name"] == "bob"


@pytest.mark.asyncio
async def test_get_cluster_status_not_found(mock_client: ControlCenterClient) -> None:
    result = await get_cluster_status("nonexistent", client=mock_client)
    assert result["status"] == "not_found"


@pytest.mark.asyncio
async def test_get_cluster_status_case_insensitive(mock_client: ControlCenterClient) -> None:
    """Cluster lookup is case-insensitive."""
    result = await get_cluster_status("GPU-Cluster-02", client=mock_client)
    assert result["status"] == "available"
    assert result["cluster_name"] == "gpu-cluster-02"


# --- list_available_clusters -----------------------------------------------


@pytest.mark.asyncio
async def test_list_available_clusters_all_free(mock_client: ControlCenterClient) -> None:
    """When no active reservations exist, all active clusters are available."""
    mock_client.list_reservations = AsyncMock(return_value=SAMPLE_RESERVATIONS_EMPTY)
    result = await list_available_clusters(client=mock_client)
    assert result["status"] == "ok"
    # inactive-cluster should be excluded
    assert result["total"] == 2
    names = [c["name"] for c in result["available"]]
    assert "inactive-cluster" not in names


@pytest.mark.asyncio
async def test_list_available_clusters_some_occupied(mock_client: ControlCenterClient) -> None:
    """When cluster 1 has an active reservation, only cluster 2 is available."""
    mock_client.list_reservations = AsyncMock(return_value=SAMPLE_RESERVATIONS_ACTIVE)
    result = await list_available_clusters(client=mock_client)
    assert result["status"] == "ok"
    assert result["total"] == 1
    assert result["available"][0]["name"] == "gpu-cluster-02"


@pytest.mark.asyncio
async def test_list_available_clusters_no_n_plus_one(mock_client: ControlCenterClient) -> None:
    """list_available_clusters must NOT call get_current_reservation (no N+1)."""
    mock_client.list_reservations = AsyncMock(return_value=SAMPLE_RESERVATIONS_EMPTY)
    mock_client.get_current_reservation = AsyncMock(
        side_effect=AssertionError("N+1 detected: get_current_reservation should not be called"),
    )
    result = await list_available_clusters(client=mock_client)
    assert result["status"] == "ok"
    mock_client.get_current_reservation.assert_not_called()
