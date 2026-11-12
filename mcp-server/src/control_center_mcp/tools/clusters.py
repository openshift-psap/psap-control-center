"""Cluster-related MCP tools.

Provides tools for listing clusters, checking cluster status, and finding
available (unoccupied) clusters in the PSAP Control Center.
"""

from typing import Any

import httpx

from control_center_mcp.client import ControlCenterClient


async def list_clusters(client: ControlCenterClient | None = None) -> dict[str, Any]:
    """List every cluster registered in the Control Center.

    USECASE:
        Get an overview of all clusters, including name, status, GPU info,
        and provider.

    INPUT:
        No parameters required.

    OUTPUT:
        A dict with ``status`` = ``"ok"`` and a ``clusters`` list.  Each
        entry has ``id``, ``name``, ``status``, ``gpu_count``, ``gpu_type``,
        ``provider``, and ``is_active``.

    EXAMPLE:
        >>> result = await list_clusters()
        >>> result["clusters"][0]["name"]
        'gpu-cluster-01'
    """
    client = client or ControlCenterClient()
    try:
        data = await client.list_clusters()
    except httpx.HTTPStatusError as exc:
        return {"status": "error", "message": f"API error: {exc.response.status_code}"}
    except httpx.HTTPError as exc:
        return {"status": "error", "message": f"Connection error: {exc}"}

    clusters = [
        {
            "id": c["id"],
            "name": c["name"],
            "status": c.get("status", "unknown"),
            "gpu_count": c.get("gpu_count"),
            "gpu_type": c.get("gpu_type"),
            "provider": c.get("provider", "unknown"),
            "is_active": c.get("is_active", True),
        }
        for c in data.get("clusters", [])
    ]
    return {"status": "ok", "clusters": clusters, "total": len(clusters)}


async def get_cluster_status(
    cluster_name: str,
    client: ControlCenterClient | None = None,
) -> dict[str, Any]:
    """Check who is currently using a specific cluster.

    USECASE:
        Find out whether a cluster is free or occupied, and if occupied,
        who reserved it and until when.

    INPUT:
        ``cluster_name`` — the human-readable cluster name (case-insensitive).

    OUTPUT:
        A dict with ``status`` = ``"available"`` or ``"occupied"``.
        When occupied, includes ``reservation`` details (user, team, end_time).
        Returns ``status`` = ``"not_found"`` if the cluster name is unknown.

    EXAMPLE:
        >>> result = await get_cluster_status("gpu-cluster-01")
        >>> result["status"]
        'available'
    """
    client = client or ControlCenterClient()
    try:
        data = await client.list_clusters()
    except httpx.HTTPError as exc:
        return {"status": "error", "message": f"Connection error: {exc}"}

    # Case-insensitive lookup
    cluster = None
    for c in data.get("clusters", []):
        if c["name"].lower() == cluster_name.lower():
            cluster = c
            break

    if cluster is None:
        return {
            "status": "not_found",
            "message": f"No cluster named '{cluster_name}' found.",
        }

    try:
        occupancy = await client.get_current_reservation(cluster["id"])
    except httpx.HTTPStatusError as exc:
        return {"status": "error", "message": f"API error: {exc.response.status_code}"}
    except httpx.HTTPError as exc:
        return {"status": "error", "message": f"Connection error: {exc}"}

    if not occupancy.get("occupied", False):
        return {
            "status": "available",
            "cluster_name": cluster["name"],
            "cluster_id": cluster["id"],
        }

    reservations = occupancy.get("reservations", [])
    reservation_info = None
    if reservations:
        r = reservations[0]
        reservation_info = {
            "user_name": r.get("user_name"),
            "team": r.get("team"),
            "title": r.get("title"),
            "start_time": r.get("start_time"),
            "end_time": r.get("end_time"),
            "reservation_type": r.get("reservation_type", "cluster"),
            "gpu_count": r.get("gpu_count"),
        }

    return {
        "status": "occupied",
        "cluster_name": cluster["name"],
        "cluster_id": cluster["id"],
        "reservation": reservation_info,
    }


async def list_available_clusters(
    client: ControlCenterClient | None = None,
) -> dict[str, Any]:
    """List clusters that have no active reservation right now.

    Fetches the cluster list and the full reservation list in two API
    calls, then cross-references locally to determine availability.
    This avoids the N+1 query pattern of checking each cluster
    individually.

    USECASE:
        Quickly find which clusters are free and can be reserved
        immediately.

    INPUT:
        No parameters required.

    OUTPUT:
        A dict with ``status`` = ``"ok"`` and an ``available`` list of
        cluster summaries.

    EXAMPLE:
        >>> result = await list_available_clusters()
        >>> len(result["available"])
        2
    """
    client = client or ControlCenterClient()
    try:
        clusters_data = await client.list_clusters()
    except httpx.HTTPError as exc:
        return {"status": "error", "message": f"Connection error: {exc}"}

    try:
        reservations_data = await client.list_reservations()
    except httpx.HTTPError as exc:
        return {"status": "error", "message": f"Connection error: {exc}"}

    # Build a set of cluster IDs that have an active reservation
    active_reservations = reservations_data.get("reservations", [])
    occupied_cluster_ids: set[str] = {
        r["cluster_id"]
        for r in active_reservations
        if r.get("status") == "active" and r.get("cluster_id")
    }

    clusters = clusters_data.get("clusters", [])
    available: list[dict[str, Any]] = []

    for cluster in clusters:
        if not cluster.get("is_active", True):
            continue
        if cluster["id"] in occupied_cluster_ids:
            continue
        available.append(
            {
                "id": cluster["id"],
                "name": cluster["name"],
                "gpu_count": cluster.get("gpu_count"),
                "gpu_type": cluster.get("gpu_type"),
                "provider": cluster.get("provider", "unknown"),
            }
        )

    return {"status": "ok", "available": available, "total": len(available)}
