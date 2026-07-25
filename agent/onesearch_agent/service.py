"""Small, explicit OS service lifecycle wrappers."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


class ServiceError(RuntimeError):
    pass


def _run(args):
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode:
        raise ServiceError("service operation failed")


def install(config: Path, executable: str, *, system: str | None = None, home: Path | None = None):
    system = system or os.name
    if os.environ.get("DOCKER_CONTAINER"):
        raise ServiceError("services are unsupported in containers")
    if system == "nt":
        _run(
            [
                executable,
                "-m",
                "onesearch_agent.windows_service",
                "--config",
                str(config),
                "--startup",
                "auto",
                "install",
            ]
        )
        _run([executable, "-m", "onesearch_agent.windows_service", "start"])
        return
    if system == "posix":
        unit = (home or Path.home()) / ".config/systemd/user/onesearch-agent.service"
        unit.parent.mkdir(parents=True, exist_ok=True)
        temporary = unit.with_suffix(".tmp")
        temporary.write_text(
            f"[Unit]\nDescription=OneSearch Agent\n\n[Service]\nExecStart={executable} -m onesearch_agent.cli --config {config} run\nRestart=always\nRestartSec=5\n\n[Install]\nWantedBy=default.target\n"
        )
        os.replace(temporary, unit)
        _run(["systemctl", "--user", "daemon-reload"])
        _run(["systemctl", "--user", "enable", "--now", "onesearch-agent.service"])
        return
    raise ServiceError("services are unsupported on this platform")


def uninstall(*, system: str | None = None, home: Path | None = None):
    system = system or os.name
    if system == "nt":
        executable = os.sys.executable
        _run([executable, "-m", "onesearch_agent.windows_service", "stop"])
        _run([executable, "-m", "onesearch_agent.windows_service", "remove"])
        return
    if system == "posix":
        unit = (home or Path.home()) / ".config/systemd/user/onesearch-agent.service"
        _run(["systemctl", "--user", "disable", "--now", "onesearch-agent.service"])
        if unit.exists():
            unit.unlink()
        _run(["systemctl", "--user", "daemon-reload"])
        return
    raise ServiceError("services are unsupported on this platform")
