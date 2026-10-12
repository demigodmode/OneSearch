# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Render supervisord config for the unified container."""
import os
import sys

from .meili_sizing import MEMORY_VAR, THREADS_VAR, MeiliSizing, read_memory_facts, size_meilisearch

BASE_CONFIG = """# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

[supervisord]
nodaemon=true
user=root
logfile=/var/log/supervisor/supervisord.log
pidfile=/var/run/supervisord.pid
loglevel=info

[program:nginx]
command=/usr/sbin/nginx -g "daemon off;"
autostart=true
autorestart=true
priority=10
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0

{meilisearch_program}
[program:uvicorn]
command=/app/start-backend.sh
directory=/app/backend
user=onesearch
autostart=true
autorestart=true
priority=20
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
environment={uvicorn_environment}
"""

MEILISEARCH_COMMAND = " ".join([
    "/usr/local/bin/meilisearch",
    "--db-path /app/meili_data",
    "--http-addr 127.0.0.1:7700",
])

MEILISEARCH_ENVIRONMENT = [
    'MEILI_MASTER_KEY="%(ENV_MEILI_MASTER_KEY)s"',
    'MEILI_ENV="production"',
    'MEILI_NO_ANALYTICS="true"',
]

MEILISEARCH_PROGRAM = """[program:meilisearch]
command={command}
directory=/app/meili_data
user=onesearch
autostart=true
autorestart=true
priority=15
environment={environment}
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0

"""


def render_supervisord_config(managed_meili: bool, sizing: MeiliSizing | None = None) -> str:
    """Return supervisord config for external or managed Meilisearch mode."""
    environment = ['PATH="/home/onesearch/.local/bin:%(ENV_PATH)s"']
    meilisearch_program = ""

    if managed_meili:
        meili_environment = list(MEILISEARCH_ENVIRONMENT)
        if sizing:
            meili_environment.extend([
                f'{THREADS_VAR}="{sizing.threads}"',
                f'{MEMORY_VAR}="{sizing.memory}"',
            ])
        meilisearch_program = MEILISEARCH_PROGRAM.format(
            command=MEILISEARCH_COMMAND,
            environment=",".join(meili_environment),
        )
        environment.extend([
            'MEILI_URL="http://127.0.0.1:7700"',
            'MEILI_MASTER_KEY="%(ENV_MEILI_MASTER_KEY)s"',
        ])

    return BASE_CONFIG.format(
        meilisearch_program=meilisearch_program,
        uvicorn_environment=",".join(environment),
    )


if __name__ == "__main__":
    managed = os.environ.get("ONESEARCH_MANAGED_MEILI", "false").lower() == "true"
    sizing = None
    if managed:
        try:
            sizing = size_meilisearch(read_memory_facts())
        except ValueError as e:
            sys.exit(str(e))
        # stdout is the config file, so the log lines go to stderr
        for line in [sizing.summary, *sizing.warnings]:
            print(line, file=sys.stderr)

    print(render_supervisord_config(managed, sizing), end="")
