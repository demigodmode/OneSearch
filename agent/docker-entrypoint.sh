#!/bin/sh
set -eu

case "${PUID:-}" in ''|*[!0-9]*) echo "PUID must be numeric" >&2; exit 64 ;; esac
case "${PGID:-}" in ''|*[!0-9]*) echo "PGID must be numeric" >&2; exit 64 ;; esac
if [ "$PUID" = 0 ]; then echo "PUID must not be root" >&2; exit 64; fi
if [ "$PGID" = 0 ]; then echo "PGID must not be root" >&2; exit 64; fi

if [ "$(id -u)" = "0" ]; then
    current_uid="$(id -u onesearch)"; current_gid="$(id -g onesearch)"
    group="$(getent group "$PGID" | cut -d: -f1 || true)"
    if [ -n "$group" ] && [ "$group" != onesearch ]; then echo "PGID $PGID is already used by group '$group'" >&2; exit 64; fi
    user="$(getent passwd "$PUID" | cut -d: -f1 || true)"
    if [ -n "$user" ] && [ "$user" != onesearch ]; then echo "PUID $PUID is already used by user '$user'" >&2; exit 64; fi
    [ "$current_gid" = "$PGID" ] || groupmod --gid "$PGID" onesearch
    [ "$current_uid" = "$PUID" ] || usermod --uid "$PUID" onesearch
    usermod --gid onesearch onesearch
    chown -R "$PUID:$PGID" /var/lib/onesearch-agent
    exec gosu onesearch onesearch-agent "$@"
fi

exec onesearch-agent "$@"
