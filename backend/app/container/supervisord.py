# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Render supervisord config for the unified container."""
import os

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

MEILISEARCH_PROGRAM = f"""[program:meilisearch]
command={MEILISEARCH_COMMAND}
user=onesearch
autostart=true
autorestart=true
priority=15
environment=MEILI_MASTER_KEY="%(ENV_MEILI_MASTER_KEY)s",MEILI_ENV="production",MEILI_NO_ANALYTICS="true"
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0

"""


def render_supervisord_config(managed_meili: bool) -> str:
    """Return supervisord config for external or managed Meilisearch mode."""
    environment = ['PATH="/home/onesearch/.local/bin:%(ENV_PATH)s"']
    meilisearch_program = ""

    if managed_meili:
        meilisearch_program = MEILISEARCH_PROGRAM
        environment.extend([
            'MEILI_URL="http://127.0.0.1:7700"',
            'MEILI_MASTER_KEY="%(ENV_MEILI_MASTER_KEY)s"',
        ])

    return BASE_CONFIG.format(
        meilisearch_program=meilisearch_program,
        uvicorn_environment=",".join(environment),
    )


if __name__ == "__main__":
    print(
        render_supervisord_config(
            os.environ.get("ONESEARCH_MANAGED_MEILI", "false").lower() == "true"
        ),
        end="",
    )
