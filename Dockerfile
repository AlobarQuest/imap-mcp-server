FROM python:3.11-slim

WORKDIR /app

# Install curl (Coolify health checks) and unzip (bws install)
RUN apt-get update && apt-get install -y --no-install-recommends curl unzip && rm -rf /var/lib/apt/lists/*

# Install bws CLI (Bitwarden Secrets Manager)
RUN ARCH=$(dpkg --print-architecture) \
    && if [ "$ARCH" = "amd64" ]; then TRIPLE="x86_64-unknown-linux-gnu"; \
       elif [ "$ARCH" = "arm64" ]; then TRIPLE="aarch64-unknown-linux-gnu"; \
       else echo "Unsupported arch: $ARCH" && exit 1; fi \
    && curl -fsSL \
        "https://github.com/bitwarden/sdk-sm/releases/download/bws-v1.0.0/bws-${TRIPLE}-1.0.0.zip" \
        -o /tmp/bws.zip \
    && unzip /tmp/bws.zip -d /tmp/bws-extract \
    && mv /tmp/bws-extract/bws /usr/local/bin/bws \
    && chmod +x /usr/local/bin/bws \
    && rm -rf /tmp/bws.zip /tmp/bws-extract

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code and entrypoint
COPY src/ src/
COPY start.sh .
RUN chmod +x start.sh

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser
USER appuser

EXPOSE 8000

ENV MCP_TRANSPORT=streamable-http
ENV PORT=8000

HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=15s \
    CMD curl -f http://127.0.0.1:8000/health/live || exit 1

CMD ["./start.sh"]
