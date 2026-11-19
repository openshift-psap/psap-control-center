"""Tests for the Control Center API client."""

import pytest

from control_center_mcp.client import ControlCenterClient


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
