"""Async HTTP client wrapper for the Control Center REST API.

Uses a **persistent** ``httpx.AsyncClient`` that is created once and
reused across all requests, honouring ``http_timeout`` and ``tls_verify``
from :pymod:`control_center_mcp.config`.
"""

from typing import Any

import httpx

from control_center_mcp.config import settings

API_PREFIX = "/api/v1"


class ControlCenterClient:
    """Thin async wrapper around the Control Center REST API.

    A single ``httpx.AsyncClient`` is created on first use and shared
    across every method call. All calls are read-only and unauthenticated.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        verify: bool | None = None,
    ) -> None:
        self.base_url = (base_url or settings.control_center_url).rstrip("/")
        self._timeout = timeout if timeout is not None else settings.http_timeout
        self._verify = verify if verify is not None else settings.tls_verify
        self._client: httpx.AsyncClient | None = None

    # --- lifecycle ------------------------------------------------------

    def _get_client(self) -> httpx.AsyncClient:
        """Return the shared ``httpx.AsyncClient``, creating it on first call."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                verify=self._verify,
            )
        return self._client

    async def aclose(self) -> None:
        """Close the underlying HTTP client (for graceful shutdown)."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # --- helpers --------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self.base_url}{API_PREFIX}{path}"

    # --- cluster endpoints ----------------------------------------------

    async def list_clusters(self) -> dict[str, Any]:
        """GET /api/v1/clusters"""
        client = self._get_client()
        resp = await client.get(self._url("/clusters"))
        resp.raise_for_status()
        return resp.json()

    async def get_cluster(self, cluster_id: str) -> dict[str, Any]:
        """GET /api/v1/clusters/{id}"""
        client = self._get_client()
        resp = await client.get(self._url(f"/clusters/{cluster_id}"))
        resp.raise_for_status()
        return resp.json()

    # --- cluster occupancy endpoints ------------------------------------

    async def list_reservations(self, **params: Any) -> dict[str, Any]:
        """GET /api/v1/reservations (with optional query params)."""
        client = self._get_client()
        resp = await client.get(self._url("/reservations"), params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_current_reservation(self, cluster_id: str) -> dict[str, Any]:
        """GET /api/v1/reservations/cluster/{cluster_id}/current"""
        client = self._get_client()
        resp = await client.get(
            self._url(f"/reservations/cluster/{cluster_id}/current"),
        )
        resp.raise_for_status()
        return resp.json()
