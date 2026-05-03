#!/bin/bash
# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

set -e

if [ "${ONESEARCH_MANAGED_MEILI:-false}" = "true" ]; then
    echo "Waiting for managed Meilisearch..."
    for attempt in $(seq 1 60); do
        if curl -fsS http://127.0.0.1:7700/health >/dev/null; then
            echo "Managed Meilisearch is ready"
            break
        fi

        if [ "$attempt" = "60" ]; then
            echo "Managed Meilisearch did not become ready in time" >&2
            exit 1
        fi

        sleep 1
    done
fi

exec /usr/local/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001
