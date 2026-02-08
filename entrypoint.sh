#!/bin/bash
# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

set -e

echo "Starting OneSearch..."

# Ensure data directory is owned by onesearch user
# (Docker volumes may be root-owned on first create or upgrades)
chown -R onesearch:onesearch /app/data 2>/dev/null || true

# Run database migrations as onesearch user
echo "Running database migrations..."
cd /app/backend
su -s /bin/bash -p onesearch -c "alembic upgrade head"

# Start supervisord (manages nginx + uvicorn)
echo "Starting services..."
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
