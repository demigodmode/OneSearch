"""Entry point packaged separately from the agent service executable."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click

from .updater import UpdateHelper


class ServiceManager:
    def __init__(self, platform=None):
        self.platform = platform or sys.platform

    def stop(self):
        self._run(
            ["sc", "stop", "OneSearchAgent"]
            if self.platform == "win32"
            else ["systemctl", "--user", "stop", "onesearch-agent.service"]
        )

    def start(self):
        self._run(
            ["sc", "start", "OneSearchAgent"]
            if self.platform == "win32"
            else ["systemctl", "--user", "start", "onesearch-agent.service"]
        )

    def _run(self, args):
        if subprocess.run(args, check=False).returncode not in (0, 1060, 1062, 1056):
            raise RuntimeError("service operation failed")


@click.command()
@click.option("--transaction", type=click.Path(path_type=Path), required=True)
def main(transaction):
    UpdateHelper(service_manager=ServiceManager()).run(transaction)


def launch(transaction: Path, *, platform=None, run=subprocess.Popen):
    platform = platform or sys.platform
    helper = Path(sys.executable).with_name(
        "onesearch-agent-updater" + (".exe" if platform == "win32" else "")
    )
    if not helper.exists():
        raise RuntimeError("separate native updater helper is unavailable; install manually")
    if platform == "linux":
        return run(
            [
                "systemd-run",
                "--user",
                "--unit=onesearch-agent-updater",
                str(helper),
                "--transaction",
                str(transaction),
            ]
        )
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    return run([str(helper), "--transaction", str(transaction)], creationflags=flags)
