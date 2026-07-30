#!/bin/sh
set -eu

case "${PUID:-}" in ''|*[!0-9]*) echo "PUID must be numeric" >&2; exit 64 ;; esac
case "${PGID:-}" in ''|*[!0-9]*) echo "PGID must be numeric" >&2; exit 64 ;; esac

if [ "$(id -u)" = "0" ]; then
    groupmod --gid "$PGID" onesearch
    usermod --uid "$PUID" --gid "$PGID" onesearch
    chown "$PUID:$PGID" /var/lib/onesearch-agent
    exec su -s /bin/sh -c 'exec onesearch-agent "$@"' onesearch -- "$@"
fi

exec onesearch-agent "$@"
