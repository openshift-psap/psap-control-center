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

mcp = FastMCP(
    "Control Center",
    instructions=(
        "MCP server for the PSAP Control Center — list clusters, check "
        "occupancy, and find available clusters."
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


if __name__ == "__main__":
    mcp.run(
        transport="sse",
        host=settings.mcp_host,
        port=settings.mcp_port,
    )
