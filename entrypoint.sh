#!/bin/bash
# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

set -e

echo "Starting OneSearch..."

configure_runtime_user() {
    local target_uid="${PUID:-$(id -u onesearch)}"
    local target_gid="${PGID:-$(id -g onesearch)}"

    if [[ ! "$target_uid" =~ ^[0-9]+$ ]]; then
        echo "PUID must be a numeric user ID" >&2
        exit 1
    fi
    if [[ ! "$target_gid" =~ ^[0-9]+$ ]]; then
        echo "PGID must be a numeric group ID" >&2
        exit 1
    fi

    local current_uid current_gid target_group existing_user
    current_uid="$(id -u onesearch)"
    current_gid="$(id -g onesearch)"

    target_group="$(getent group "$target_gid" | cut -d: -f1 || true)"
    if [ -z "$target_group" ]; then
        if [ "$target_gid" != "$current_gid" ]; then
            groupmod -g "$target_gid" onesearch
        fi
        target_group="onesearch"
    fi

    existing_user="$(getent passwd "$target_uid" | cut -d: -f1 || true)"
    if [ -n "$existing_user" ] && [ "$existing_user" != "onesearch" ]; then
        echo "PUID $target_uid is already used by user '$existing_user'" >&2
        exit 1
    fi

    if [ "$target_uid" != "$current_uid" ]; then
        usermod -u "$target_uid" onesearch
    fi
    usermod -g "$target_group" onesearch
}

configure_runtime_user

# Ensure data directories are owned by the runtime onesearch user/group
# (Docker volumes may be root-owned on first create or upgrades)
chown -R "$(id -u onesearch):$(id -g onesearch)" /app/data 2>/dev/null || true

if [ "${ONESEARCH_MANAGED_MEILI:-false}" = "true" ]; then
    if [ -z "${MEILI_MASTER_KEY:-}" ]; then
        echo "MEILI_MASTER_KEY is required when ONESEARCH_MANAGED_MEILI=true" >&2
        exit 1
    fi

    echo "Managed Meilisearch enabled"
    mkdir -p /app/meili_data
    chown -R "$(id -u onesearch):$(id -g onesearch)" /app/meili_data 2>/dev/null || true
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
