# Multi-stage build for smaller final image with uv

# Stage 1: Builder - Install dependencies with uv
FROM python:3.13-slim as builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency files (including lock file for reproducibility)
COPY pyproject.toml uv.lock ./

# Install dependencies using uv with lock file for pinned versions
# --system installs to system Python (no venv in Docker)
# Lock file already pins exact versions
RUN uv pip sync --system uv.lock

# Stage 2: Runtime - Minimal production image
FROM python:3.13-slim

# Install curl for healthcheck
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 onesearch && \
    mkdir -p /app/data && \
    chown -R onesearch:onesearch /app

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY --chown=onesearch:onesearch . .

# Copy and set up entrypoint script
COPY --chown=onesearch:onesearch entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Switch to non-root user
USER onesearch

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Run entrypoint script (which runs migrations then starts app)
ENTRYPOINT ["/app/entrypoint.sh"]
