"""Tests for reservation tools."""

from unittest.mock import AsyncMock

import httpx
import pytest

from control_center_mcp.client import ControlCenterClient
from control_center_mcp.tools.reservations import (
    cancel_reservation,
    create_reservation,
    list_my_reservations,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_KWARGS: dict = {
    "cluster_name": "gpu-cluster-01",
    "user_name": "alice",
    "user_email": "alice@example.com",
    "team": "ml-training",
    "start_time": "2025-06-01T09:00:00Z",
    "end_time": "2025-06-01T17:00:00Z",
}


# --- create_reservation: happy path ----------------------------------------


@pytest.mark.asyncio
async def test_create_reservation_ok(mock_client: ControlCenterClient) -> None:
    result = await create_reservation(**_VALID_KWARGS, client=mock_client)
    assert result["status"] == "ok"
    assert result["reservation"]["id"] == "99"


@pytest.mark.asyncio
async def test_create_reservation_cluster_not_found(mock_client: ControlCenterClient) -> None:
    result = await create_reservation(
        **{**_VALID_KWARGS, "cluster_name": "nonexistent"},
        client=mock_client,
    )
    assert result["status"] == "not_found"


@pytest.mark.asyncio
async def test_create_reservation_conflict(mock_client: ControlCenterClient) -> None:
    mock_client.create_reservation = AsyncMock(
        return_value=(409, {"detail": "Conflicts with existing reservation."}),
    )
    result = await create_reservation(**_VALID_KWARGS, client=mock_client)
    assert result["status"] == "conflict"
    assert "Conflicts" in result["message"]


@pytest.mark.asyncio
async def test_create_reservation_auto_title(mock_client: ControlCenterClient) -> None:
    """When no title is given, one is auto-generated."""
    await create_reservation(**_VALID_KWARGS, client=mock_client)
    call_args = mock_client.create_reservation.call_args
    payload = call_args[0][0] if call_args[0] else call_args[1].get("data", {})
    assert payload["title"] == "alice on gpu-cluster-01"


@pytest.mark.asyncio
async def test_create_reservation_connection_error(mock_client: ControlCenterClient) -> None:
    mock_client.list_clusters = AsyncMock(side_effect=httpx.ConnectError("refused"))
    result = await create_reservation(**_VALID_KWARGS, client=mock_client)
    assert result["status"] == "error"
    assert "Connection error" in result["message"]


# --- create_reservation: client-side validation ----------------------------


@pytest.mark.asyncio
async def test_create_reservation_invalid_type(mock_client: ControlCenterClient) -> None:
    """Invalid reservation_type is rejected before any API call."""
    result = await create_reservation(
        **{**_VALID_KWARGS, "reservation_type": "invalid"},
        client=mock_client,
    )
    assert result["status"] == "error"
    assert "reservation_type" in result["message"]
    mock_client.list_clusters.assert_not_called()


@pytest.mark.asyncio
async def test_create_reservation_gpu_count_required(mock_client: ControlCenterClient) -> None:
    """gpu_count must be >= 1 when type is 'gpu'."""
    result = await create_reservation(
        **{**_VALID_KWARGS, "reservation_type": "gpu", "gpu_count": None},
        client=mock_client,
    )
    assert result["status"] == "error"
    assert "gpu_count" in result["message"]


@pytest.mark.asyncio
async def test_create_reservation_gpu_count_zero(mock_client: ControlCenterClient) -> None:
    """gpu_count=0 is not valid for GPU reservations."""
    result = await create_reservation(
        **{**_VALID_KWARGS, "reservation_type": "gpu", "gpu_count": 0},
        client=mock_client,
    )
    assert result["status"] == "error"
    assert "gpu_count" in result["message"]


@pytest.mark.asyncio
async def test_create_reservation_bad_start_time(mock_client: ControlCenterClient) -> None:
    """Unparseable start_time is rejected."""
    result = await create_reservation(
        **{**_VALID_KWARGS, "start_time": "not-a-date"},
        client=mock_client,
    )
    assert result["status"] == "error"
    assert "start_time" in result["message"]


@pytest.mark.asyncio
async def test_create_reservation_bad_end_time(mock_client: ControlCenterClient) -> None:
    """Unparseable end_time is rejected."""
    result = await create_reservation(
        **{**_VALID_KWARGS, "end_time": "garbage"},
        client=mock_client,
    )
    assert result["status"] == "error"
    assert "end_time" in result["message"]


@pytest.mark.asyncio
async def test_create_reservation_end_before_start(mock_client: ControlCenterClient) -> None:
    """end_time before start_time is rejected."""
    result = await create_reservation(
        **{
            **_VALID_KWARGS,
            "start_time": "2025-06-01T17:00:00Z",
            "end_time": "2025-06-01T09:00:00Z",
        },
        client=mock_client,
    )
    assert result["status"] == "error"
    assert "end_time must be after start_time" in result["message"]


@pytest.mark.asyncio
async def test_create_reservation_bad_priority(mock_client: ControlCenterClient) -> None:
    """Invalid priority is rejected."""
    result = await create_reservation(
        **{**_VALID_KWARGS, "priority": "urgent"},
        client=mock_client,
    )
    assert result["status"] == "error"
    assert "priority" in result["message"]


# --- cancel_reservation (POST /cancel) ------------------------------------


@pytest.mark.asyncio
async def test_cancel_reservation_ok(mock_client: ControlCenterClient) -> None:
    """cancel_reservation calls POST /cancel and returns the reservation."""
    result = await cancel_reservation("10", client=mock_client)
    assert result["status"] == "ok"
    assert result["reservation"]["status"] == "cancelled"
    # Verify it called cancel_reservation (POST), not hard_delete
    mock_client.cancel_reservation.assert_called_once_with("10")
    mock_client.hard_delete_reservation.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_reservation_not_found(mock_client: ControlCenterClient) -> None:
    mock_client.cancel_reservation = AsyncMock(return_value=(404, {}))
    result = await cancel_reservation("999", client=mock_client)
    assert result["status"] == "not_found"


@pytest.mark.asyncio
async def test_cancel_reservation_connection_error(mock_client: ControlCenterClient) -> None:
    mock_client.cancel_reservation = AsyncMock(side_effect=httpx.ConnectError("refused"))
    result = await cancel_reservation("42", client=mock_client)
    assert result["status"] == "error"


# --- list_my_reservations --------------------------------------------------


@pytest.mark.asyncio
async def test_list_my_reservations_found(mock_client: ControlCenterClient) -> None:
    result = await list_my_reservations("alice@example.com", client=mock_client)
    assert result["status"] == "ok"
    assert result["total"] == 1
    assert result["reservations"][0]["user_name"] == "alice"


@pytest.mark.asyncio
async def test_list_my_reservations_none(mock_client: ControlCenterClient) -> None:
    result = await list_my_reservations("nobody@example.com", client=mock_client)
    assert result["status"] == "ok"
    assert result["total"] == 0


@pytest.mark.asyncio
async def test_list_my_reservations_case_insensitive(mock_client: ControlCenterClient) -> None:
    """Email filtering is case-insensitive."""
    result = await list_my_reservations("Alice@Example.COM", client=mock_client)
    assert result["status"] == "ok"
    assert result["total"] == 1


# --- connection reuse ------------------------------------------------------


@pytest.mark.asyncio
async def test_client_reuses_connection() -> None:
    """The ControlCenterClient creates a single httpx.AsyncClient and reuses it."""
    client = ControlCenterClient(base_url="http://test:8000")
    http_client_1 = client._get_client()
    http_client_2 = client._get_client()
    assert http_client_1 is http_client_2, "httpx.AsyncClient should be reused"
    await client.aclose()


@pytest.mark.asyncio
async def test_client_respects_config() -> None:
    """Verify that timeout and verify settings are passed to httpx.AsyncClient."""
    client = ControlCenterClient(base_url="http://test:8000", timeout=5.0, verify=False)
    http_client = client._get_client()
    assert http_client.timeout.connect == 5.0
    assert http_client._transport._pool._ssl_context.verify_mode.name == "CERT_NONE"
    await client.aclose()
