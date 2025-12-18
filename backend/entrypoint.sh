#!/bin/bash
# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

set -e

echo "Starting OneSearch backend..."

# Run database migrations
echo "Running database migrations..."
uv run alembic upgrade head

# Start the application
echo "Starting FastAPI server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
