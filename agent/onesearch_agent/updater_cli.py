"""Entry point packaged separately from the agent service executable."""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
from pathlib import Path

import click

from .updater import UpdateHelper


class ServiceManager:
    def __init__(self, platform=None, runner=None):
        self.platform = platform or sys.platform
        self.runner = runner or self._subprocess_runner

    def stop(self):
        self._require_managed()
        self._run(
            ["sc", "stop", "OneSearchAgent"]
            if self.platform == "win32"
            else ["systemctl", "--user", "stop", "onesearch-agent.service"]
        )

    def start(self):
        self._require_managed()
        self._run(
            ["sc", "start", "OneSearchAgent"]
            if self.platform == "win32"
            else ["systemctl", "--user", "start", "onesearch-agent.service"]
        )

    def _run(self, args):
        result = self.runner(args)
        code = result if isinstance(result, int) else result.returncode
        if code == 1060:
            raise RuntimeError("OneSearch Agent service is not installed")
        benign = {0}
        if args[-2] == "stop":
            benign.add(1062)
        if args[-2] == "start":
            benign.add(1056)
        if code not in benign:
            raise RuntimeError("service operation failed")

    def is_managed(self):
        args = (
            ["sc", "query", "OneSearchAgent"]
            if self.platform == "win32"
            else [
                "systemctl",
                "--user",
                "show",
                "onesearch-agent.service",
                "--property=LoadState",
                "--value",
            ]
        )
        result = self.runner(args)
        code = result if isinstance(result, int) else result.returncode
        if code != 0:
            return False
        output = getattr(result, "stdout", "") or ""
        return self.platform == "win32" or output.strip() not in {"", "not-found", "inactive"}

    def _require_managed(self):
        if not self.is_managed():
            raise RuntimeError("OneSearch Agent service is not installed")

    @staticmethod
    def _subprocess_runner(args):
        return subprocess.run(args, check=False)


@click.command()
@click.option("--transaction", type=click.Path(path_type=Path), required=True)
def main(transaction):
    helper = Path(sys.executable)
    expected = _expected_agent_binary(helper)
    UpdateHelper(service_manager=ServiceManager()).run(
        transaction, expected_current_binary=expected
    )


def _expected_agent_binary(helper: Path) -> Path:
    suffix = ".exe" if helper.name.lower().endswith(".exe") else ""
    expected_name = "onesearch-agent-updater" + suffix
    if helper.name.lower() != expected_name:
        raise RuntimeError("updater must be the fixed-name separate native helper")
    return helper.with_name("onesearch-agent" + suffix)


def launch(
    transaction: Path, *, platform=None, run=subprocess.Popen, helper=None, pid=None, token=None
):
    platform = platform or sys.platform
    helper = (
        Path(helper)
        if helper
        else Path(sys.executable).with_name(
            "onesearch-agent-updater" + (".exe" if platform == "win32" else "")
        )
    )
    if not helper.exists():
        raise RuntimeError("separate native updater helper is unavailable; install manually")
    if platform == "linux":
        unit = f"onesearch-agent-updater-{pid or os.getpid()}-{token or secrets.token_hex(6)}"
        process = run(
            [
                "systemd-run",
                "--user",
                "--collect",
                "--property=Type=exec",
                f"--unit={unit}",
                str(helper),
                "--transaction",
                str(transaction),
            ]
        )
        if process.poll() not in (None, 0):
            raise RuntimeError("transient updater helper failed to launch")
        return process
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    return run([str(helper), "--transaction", str(transaction)], creationflags=flags)
