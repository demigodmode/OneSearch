#!/bin/bash
# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

set -e

echo "Starting OneSearch..."

# Ensure data directories are owned by onesearch user
# (Docker volumes may be root-owned on first create or upgrades)
chown -R onesearch:onesearch /app/data 2>/dev/null || true

if [ "${ONESEARCH_MANAGED_MEILI:-false}" = "true" ]; then
    if [ -z "${MEILI_MASTER_KEY:-}" ]; then
        echo "MEILI_MASTER_KEY is required when ONESEARCH_MANAGED_MEILI=true" >&2
        exit 1
    fi

    echo "Managed Meilisearch enabled"
    mkdir -p /app/meili_data
    chown -R onesearch:onesearch /app/meili_data 2>/dev/null || true
    export MEILI_URL="http://127.0.0.1:7700"
fi

# Render supervisord config for the selected search backend mode
python -m app.container.supervisord > /etc/supervisor/conf.d/supervisord.conf

# Run database migrations as onesearch user
echo "Running database migrations..."
cd /app/backend
su -s /bin/bash -p onesearch -c "alembic upgrade head"

# Start supervisord (manages nginx + uvicorn)
echo "Starting services..."
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
