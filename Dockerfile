# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

# Unified multi-stage build for OneSearch
# Combines frontend, backend, and CLI into a single image

# =============================================================================
# Stage 1: Build Frontend
# =============================================================================
FROM node:18-alpine AS frontend-builder

WORKDIR /app

# Copy dependency files
COPY frontend/package.json frontend/package-lock.json ./

# Install dependencies
RUN npm ci

# Copy source code
COPY frontend/ .

# Build production bundle
RUN npm run build

# =============================================================================
# Stage 2: Build Backend + CLI
# =============================================================================
FROM python:3.13-slim AS backend-builder

# Install uv for fast package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy workspace root files
COPY pyproject.toml uv.lock ./

# Copy backend and CLI packages
COPY backend/ ./backend/
COPY cli/ ./cli/

# Install all workspace packages to user directory
RUN uv pip install --system ./backend ./cli

# =============================================================================
# Stage 3: Runtime
# =============================================================================
FROM python:3.13-slim

# Install nginx, supervisor, and curl for healthcheck
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        nginx \
        supervisor \
        curl && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir -p /var/log/supervisor

# Create non-root user for uvicorn
RUN useradd -m -u 1000 onesearch && \
    mkdir -p /app/data && \
    chown -R onesearch:onesearch /app

WORKDIR /app

# Copy installed Python packages from builder
COPY --from=backend-builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=backend-builder /usr/local/bin /usr/local/bin

# Copy backend application code
COPY --chown=onesearch:onesearch backend/ ./backend/

# Copy frontend build
COPY --from=frontend-builder /app/dist ./frontend/

# Copy configuration files
COPY nginx.conf /etc/nginx/nginx.conf
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Copy and set up entrypoint script
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Fix nginx permissions (Debian uses www-data, not nginx)
RUN mkdir -p /var/cache/nginx /var/log/nginx && \
    chown -R www-data:www-data /var/cache/nginx && \
    chown -R www-data:www-data /var/log/nginx && \
    touch /var/run/nginx.pid && \
    chown -R www-data:www-data /var/run/nginx.pid

# Create data directory with correct permissions
RUN mkdir -p /app/data && chown -R onesearch:onesearch /app/data

# Expose port (nginx listens on 8000)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/api/health || exit 1

# Run entrypoint (migrations + supervisord)
ENTRYPOINT ["/app/entrypoint.sh"]
