"""Reservation-related MCP tools.

Provides tools for creating, cancelling, and listing reservations in the
PSAP Control Center.
"""

from datetime import datetime
from typing import Any

import httpx

from control_center_mcp.client import ControlCenterClient

VALID_RESERVATION_TYPES = ("cluster", "gpu")
VALID_PRIORITIES = ("undefined", "minor", "normal", "critical", "blocker")


def _validate_reservation_inputs(
    reservation_type: str,
    gpu_count: int | None,
    start_time: str,
    end_time: str,
    priority: str,
) -> dict[str, Any] | None:
    """Validate reservation inputs client-side before calling the API.

    Returns a structured error dict if validation fails, or ``None`` if
    all inputs are valid.
    """
    # reservation_type
    if reservation_type not in VALID_RESERVATION_TYPES:
        return {
            "status": "error",
            "message": (
                f"Invalid reservation_type '{reservation_type}'. "
                f"Must be one of: {', '.join(VALID_RESERVATION_TYPES)}."
            ),
        }

    # gpu_count vs reservation_type
    if reservation_type == "gpu":
        if gpu_count is None or gpu_count < 1:
            return {
                "status": "error",
                "message": "gpu_count must be >= 1 when reservation_type is 'gpu'.",
            }
    elif reservation_type == "cluster" and gpu_count is not None:
        # Silently ignore gpu_count for cluster reservations — it will not
        # be sent to the API.
        pass

    # priority
    if priority not in VALID_PRIORITIES:
        return {
            "status": "error",
            "message": (
                f"Invalid priority '{priority}'. Must be one of: {', '.join(VALID_PRIORITIES)}."
            ),
        }

    # Datetime parsing
    try:
        parsed_start = datetime.fromisoformat(start_time)
    except (ValueError, TypeError):
        return {
            "status": "error",
            "message": f"start_time '{start_time}' is not a valid ISO 8601 datetime.",
        }

    try:
        parsed_end = datetime.fromisoformat(end_time)
    except (ValueError, TypeError):
        return {
            "status": "error",
            "message": f"end_time '{end_time}' is not a valid ISO 8601 datetime.",
        }

    if parsed_end <= parsed_start:
        return {
            "status": "error",
            "message": "end_time must be after start_time.",
        }

    return None


async def create_reservation(
    cluster_name: str,
    user_name: str,
    user_email: str,
    team: str,
    start_time: str,
    end_time: str,
    title: str = "",
    reservation_type: str = "cluster",
    gpu_count: int | None = None,
    purpose: str = "",
    priority: str = "normal",
    client: ControlCenterClient | None = None,
) -> dict[str, Any]:
    """Reserve a cluster (or GPUs on a cluster) for a time window.

    Performs client-side validation of inputs before making API calls.

    USECASE:
        Book a cluster so that other team members know it is in use.

    INPUT:
        ``cluster_name``     — human-readable cluster name (case-insensitive).
        ``user_name``        — who is reserving.
        ``user_email``       — contact email.
        ``team``             — team name.
        ``start_time``       — ISO 8601 start (e.g. ``"2025-06-01T09:00:00Z"``).
        ``end_time``         — ISO 8601 end.
        ``title``            — short title for the reservation (defaults to
                               ``"<user_name> on <cluster_name>"``).
        ``reservation_type`` — ``"cluster"`` (whole cluster) or ``"gpu"``
                               (partial).
        ``gpu_count``        — required when ``reservation_type`` is ``"gpu"``.
        ``purpose``          — free-text purpose.
        ``priority``         — one of ``"undefined"``, ``"minor"``,
                               ``"normal"``, ``"critical"``, ``"blocker"``.

    OUTPUT:
        ``status`` = ``"ok"`` with ``reservation`` details on success.
        ``status`` = ``"conflict"`` when the time slot is already taken.
        ``status`` = ``"not_found"`` if the cluster name is unknown.
        ``status`` = ``"error"`` for validation failures or other errors.

    EXAMPLE:
        >>> result = await create_reservation(
        ...     cluster_name="gpu-cluster-01",
        ...     user_name="alice",
        ...     user_email="alice@example.com",
        ...     team="ml-training",
        ...     start_time="2025-06-01T09:00:00Z",
        ...     end_time="2025-06-01T17:00:00Z",
        ... )
        >>> result["status"]
        'ok'
    """
    # --- Client-side validation ---
    validation_error = _validate_reservation_inputs(
        reservation_type=reservation_type,
        gpu_count=gpu_count,
        start_time=start_time,
        end_time=end_time,
        priority=priority,
    )
    if validation_error is not None:
        return validation_error

    client = client or ControlCenterClient()

    # Resolve cluster name → id
    try:
        clusters_data = await client.list_clusters()
    except httpx.HTTPError as exc:
        return {"status": "error", "message": f"Connection error: {exc}"}

    cluster = None
    for c in clusters_data.get("clusters", []):
        if c["name"].lower() == cluster_name.lower():
            cluster = c
            break

    if cluster is None:
        return {
            "status": "not_found",
            "message": f"No cluster named '{cluster_name}' found.",
        }

    effective_title = title or f"{user_name} on {cluster['name']}"

    payload: dict[str, Any] = {
        "title": effective_title,
        "cluster_id": cluster["id"],
        "user_name": user_name,
        "user_email": user_email,
        "team": team,
        "start_time": start_time,
        "end_time": end_time,
        "reservation_type": reservation_type,
        "purpose": purpose,
        "priority": priority,
    }
    if reservation_type == "gpu" and gpu_count is not None:
        payload["gpu_count"] = gpu_count

    try:
        status_code, body = await client.create_reservation(payload)
    except httpx.HTTPError as exc:
        return {"status": "error", "message": f"Connection error: {exc}"}

    if status_code == 201:
        return {"status": "ok", "reservation": body}
    if status_code == 409:
        return {
            "status": "conflict",
            "message": body.get("detail", "Time slot conflicts with an existing reservation."),
        }
    return {
        "status": "error",
        "message": f"Unexpected response ({status_code}): {body}",
    }


async def cancel_reservation(
    reservation_id: str,
    client: ControlCenterClient | None = None,
) -> dict[str, Any]:
    """Cancel an existing reservation by its ID (soft cancel via POST).

    USECASE:
        Free up a cluster by cancelling a reservation that is no longer
        needed.  Uses the POST /cancel endpoint which performs a soft
        cancel (sets status to cancelled) rather than permanently
        deleting the record.

    INPUT:
        ``reservation_id`` — the reservation ID to cancel.

    OUTPUT:
        ``status`` = ``"ok"`` with ``reservation`` details on success.
        ``status`` = ``"not_found"`` if the reservation does not exist.
        ``status`` = ``"error"`` for other failures.

    EXAMPLE:
        >>> result = await cancel_reservation("42")
        >>> result["status"]
        'ok'
    """
    client = client or ControlCenterClient()

    try:
        status_code, body = await client.cancel_reservation(str(reservation_id))
    except httpx.HTTPError as exc:
        return {"status": "error", "message": f"Connection error: {exc}"}

    if status_code == 200:
        return {"status": "ok", "reservation": body}
    if status_code == 404:
        return {
            "status": "not_found",
            "message": f"Reservation {reservation_id} not found.",
        }
    return {"status": "error", "message": f"Unexpected response ({status_code}): {body}"}


async def list_my_reservations(
    user_email: str,
    client: ControlCenterClient | None = None,
) -> dict[str, Any]:
    """List reservations belonging to a specific user.

    USECASE:
        See all of your current and upcoming reservations.

    INPUT:
        ``user_email`` — the email address to filter by.

    OUTPUT:
        ``status`` = ``"ok"`` with a ``reservations`` list filtered to
        the given user.

    EXAMPLE:
        >>> result = await list_my_reservations("alice@example.com")
        >>> len(result["reservations"])
        1
    """
    client = client or ControlCenterClient()

    try:
        data = await client.list_reservations()
    except httpx.HTTPError as exc:
        return {"status": "error", "message": f"Connection error: {exc}"}

    all_reservations = data.get("reservations", [])
    mine = [
        {
            "id": r["id"],
            "title": r.get("title", ""),
            "cluster_id": r.get("cluster_id"),
            "cluster_name": r.get("cluster_name"),
            "user_name": r.get("user_name"),
            "start_time": r.get("start_time"),
            "end_time": r.get("end_time"),
            "status": r.get("status"),
            "reservation_type": r.get("reservation_type", "cluster"),
            "gpu_count": r.get("gpu_count"),
        }
        for r in all_reservations
        if (r.get("user_email") or "").lower() == user_email.lower()
    ]
    return {"status": "ok", "reservations": mine, "total": len(mine)}
