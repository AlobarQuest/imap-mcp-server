FROM python:3.11-slim

WORKDIR /app

# Install curl for Coolify health checks
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install dependencies first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ src/

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser
USER appuser

EXPOSE 8000

ENV MCP_TRANSPORT=streamable-http
ENV PORT=8000

HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=15s \
    CMD curl -f http://127.0.0.1:8000/health || exit 1

CMD ["python", "-m", "src.server"]
