FROM python:3.12-slim

WORKDIR /app

# Install project dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Copy application source
COPY src/ ./src/

ENV PYTHONPATH=/app/src
ENV CONTROL_CENTER_URL=http://backend:8000
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8080

EXPOSE 8080

CMD ["python", "-m", "control_center_mcp.server"]
