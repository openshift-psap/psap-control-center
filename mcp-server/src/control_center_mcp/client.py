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
    across every method call.  Read operations are unauthenticated.
    Write operations (POST, PUT, DELETE) use HTTP Basic Auth with the
    configured admin credentials.
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

    def _auth(self) -> httpx.BasicAuth:
        return httpx.BasicAuth(settings.admin_username, settings.admin_password)

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

    # --- reservation endpoints ------------------------------------------

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

    async def create_reservation(self, data: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """POST /api/v1/reservations (authenticated).

        Returns ``(status_code, response_body)`` so callers can handle
        409 Conflict without catching exceptions.
        """
        client = self._get_client()
        resp = await client.post(
            self._url("/reservations"),
            json=data,
            auth=self._auth(),
        )
        return resp.status_code, resp.json() if resp.content else {}

    async def cancel_reservation(self, reservation_id: str) -> tuple[int, dict[str, Any]]:
        """POST /api/v1/reservations/{id}/cancel (authenticated).

        Soft-cancel a reservation.  Returns ``(status_code, response_body)``.
        """
        client = self._get_client()
        resp = await client.post(
            self._url(f"/reservations/{reservation_id}/cancel"),
            auth=self._auth(),
        )
        return resp.status_code, resp.json() if resp.content else {}

    async def hard_delete_reservation(self, reservation_id: str) -> int:
        """DELETE /api/v1/reservations/{id} (authenticated).

        Permanently delete a reservation.  This is a destructive operation.
        Returns the HTTP status code.
        """
        client = self._get_client()
        resp = await client.delete(
            self._url(f"/reservations/{reservation_id}"),
            auth=self._auth(),
        )
        return resp.status_code
