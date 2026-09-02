"""FastMCP server for the PSAP Control Center.

Registers all tools from the ``tools/`` subpackage and exposes them
over the SSE transport.
"""

from fastmcp import FastMCP

from control_center_mcp.client import ControlCenterClient
from control_center_mcp.config import settings
from control_center_mcp.tools.clusters import (
    get_cluster_status,
    list_available_clusters,
    list_clusters,
)
from control_center_mcp.tools.reservations import (
    cancel_reservation,
    create_reservation,
    list_my_reservations,
)

mcp = FastMCP(
    "Control Center",
    instructions=(
        "MCP server for the PSAP Control Center — manage GPU cluster "
        "reservations and check availability."
    ),
)

# Shared client instance (uses settings from env)
_client = ControlCenterClient()


# --- Cluster tools -------------------------------------------------------


@mcp.tool()
async def tool_list_clusters() -> dict:
    """List every cluster registered in the Control Center.

    Returns cluster names, statuses, GPU counts, and providers.
    """
    return await list_clusters(client=_client)


@mcp.tool()
async def tool_get_cluster_status(cluster_name: str) -> dict:
    """Check who is currently using a specific cluster.

    Args:
        cluster_name: The human-readable cluster name (case-insensitive).

    Returns availability status and current reservation details if occupied.
    """
    return await get_cluster_status(cluster_name, client=_client)


@mcp.tool()
async def tool_list_available_clusters() -> dict:
    """List clusters that have no active reservation right now.

    Returns only active clusters that are free for immediate use.
    """
    return await list_available_clusters(client=_client)


# --- Reservation tools ----------------------------------------------------


@mcp.tool()
async def tool_create_reservation(
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
) -> dict:
    """Reserve a cluster (or GPUs on a cluster) for a time window.

    Args:
        cluster_name: Human-readable cluster name (case-insensitive).
        user_name: Who is reserving.
        user_email: Contact email.
        team: Team name.
        start_time: ISO 8601 start time.
        end_time: ISO 8601 end time.
        title: Short title (auto-generated if empty).
        reservation_type: "cluster" or "gpu".
        gpu_count: Required when reservation_type is "gpu".
        purpose: Free-text purpose description.
        priority: One of "undefined", "minor", "normal", "critical", "blocker".

    Returns reservation details on success, or conflict/error info.
    """
    return await create_reservation(
        cluster_name=cluster_name,
        user_name=user_name,
        user_email=user_email,
        team=team,
        start_time=start_time,
        end_time=end_time,
        title=title,
        reservation_type=reservation_type,
        gpu_count=gpu_count,
        purpose=purpose,
        priority=priority,
        client=_client,
    )


@mcp.tool()
async def tool_cancel_reservation(reservation_id: str) -> dict:
    """Cancel (delete) an existing reservation by its ID.

    Args:
        reservation_id: The reservation ID to delete.

    Returns confirmation or error details.
    """
    return await cancel_reservation(reservation_id, client=_client)


@mcp.tool()
async def tool_list_my_reservations(user_email: str) -> dict:
    """List reservations belonging to a specific user.

    Args:
        user_email: The email address to filter by.

    Returns matching reservations for the given user.
    """
    return await list_my_reservations(user_email, client=_client)


if __name__ == "__main__":
    mcp.run(
        transport="sse",
        host=settings.mcp_host,
        port=settings.mcp_port,
    )
