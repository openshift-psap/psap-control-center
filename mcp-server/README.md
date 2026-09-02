# Control Center MCP Server

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that
exposes the PSAP Control Center's cluster and reservation management as
AI-callable tools.  Built with
[FastMCP](https://github.com/jlowin/fastmcp) and designed for remote
deployment over SSE transport.

## Architecture

```
┌─────────────────┐       HTTP/REST       ┌──────────────────────┐
│  AI Assistant    │ ◄── SSE (MCP) ──►    │  MCP Server          │
│  (MCP client)    │                       │  (this project)      │
└─────────────────┘                       └──────────┬───────────┘
                                                     │
                                                     │ httpx (async)
                                                     ▼
                                          ┌──────────────────────┐
                                          │  Control Center API   │
                                          │  /api/v1/*            │
                                          └──────────────────────┘
```

The MCP server is a **thin HTTP client** — it does **not** access the
database directly.  All operations go through the Control Center REST API.

## Available Tools

### Cluster Tools

| Tool | Description |
|------|-------------|
| `tool_list_clusters` | List every registered cluster with name, status, GPU info, and provider. |
| `tool_get_cluster_status` | Check if a specific cluster is available or occupied (by name, case-insensitive). |
| `tool_list_available_clusters` | List only the clusters that are free right now. |

### Reservation Tools

| Tool | Description |
|------|-------------|
| `tool_create_reservation` | Reserve a cluster (or GPUs) for a time window. Handles 409 conflicts gracefully. |
| `tool_cancel_reservation` | Cancel (delete) a reservation by ID. |
| `tool_list_my_reservations` | List reservations belonging to a specific user (by email). |

## Setup

### Prerequisites

- Python 3.12+
- A running instance of the PSAP Control Center API

### Install

```bash
cd mcp-server
pip install -e ".[dev]"
```

### Configuration

All settings are read from environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `CONTROL_CENTER_URL` | `http://localhost:8000` | Base URL of the Control Center API |
| `ADMIN_USERNAME` | `admin` | HTTP Basic Auth user for write operations |
| `ADMIN_PASSWORD` | `admin` | HTTP Basic Auth password for write operations |
| `MCP_HOST` | `0.0.0.0` | Host to bind the SSE server to |
| `MCP_PORT` | `8080` | Port to bind the SSE server to |

### Run Locally

```bash
export CONTROL_CENTER_URL=http://localhost:8000
export ADMIN_USERNAME=admin
export ADMIN_PASSWORD=changeme
cd mcp-server
PYTHONPATH=src python -m control_center_mcp.server
```

The server will start on `http://0.0.0.0:8080` with SSE transport.

## Development

### Lint & Format

```bash
ruff check mcp-server/
ruff format mcp-server/
```

### Tests

Tests use mocked HTTP clients — no running server required:

```bash
cd mcp-server
pip install -e ".[dev]"
pytest tests/ -v
```

## Docker Deployment

```bash
cd mcp-server
docker build -t control-center-mcp .
docker run -p 8080:8080 \
  -e CONTROL_CENTER_URL=http://backend:8000 \
  -e ADMIN_USERNAME=admin \
  -e ADMIN_PASSWORD=changeme \
  control-center-mcp
```

## Connecting an AI Client

Point your MCP-compatible AI client to the SSE endpoint:

```
http://<host>:8080/sse
```

## Project Structure

```
mcp-server/
├── pyproject.toml          # Project metadata & dependencies
├── Dockerfile              # Container image
├── README.md               # This file
├── src/
│   └── control_center_mcp/
│       ├── __init__.py
│       ├── server.py       # FastMCP app + tool registration
│       ├── client.py       # Async HTTP client for CC API
│       ├── config.py       # Env-based config (pydantic-settings)
│       └── tools/
│           ├── __init__.py
│           ├── clusters.py     # Cluster tools
│           └── reservations.py # Reservation tools
└── tests/
    ├── __init__.py
    ├── conftest.py         # Shared fixtures & mock data
    ├── test_clusters.py    # Cluster tool tests
    └── test_reservations.py# Reservation tool tests
```

## License

Apache-2.0 — see the repository root `LICENSE` file.
