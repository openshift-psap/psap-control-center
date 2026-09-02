"""Environment-based configuration for the Control Center MCP server."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuration loaded from environment variables.

    Attributes:
        control_center_url: Base URL of the Control Center REST API.
        admin_username: HTTP Basic Auth username for write operations.
        admin_password: HTTP Basic Auth password for write operations.
        mcp_host: Host to bind the MCP SSE transport to.
        mcp_port: Port to bind the MCP SSE transport to.
        http_timeout: Timeout in seconds for HTTP requests to the Control Center API.
        tls_verify: Whether to verify TLS certificates when connecting to the API.
    """

    control_center_url: str = "http://localhost:8000"
    admin_username: str = "admin"
    admin_password: str = "admin"
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8080
    http_timeout: float = 30.0
    tls_verify: bool = True

    model_config = {"env_prefix": "", "case_sensitive": False}


settings = Settings()
