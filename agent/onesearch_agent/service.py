"""Small, explicit OS service lifecycle wrappers."""

from __future__ import annotations

import os
import subprocess
import unicodedata
from pathlib import Path

from .config import load_config
from .credentials import credential_store


class ServiceError(RuntimeError):
    pass


def validate_service_backend(config_path: Path) -> None:
    if not config_path.is_absolute():
        raise ServiceError("service configuration path must be absolute")
    try:
        config = load_config(config_path)
        credential_store(config).load()
    except Exception as error:
        raise ServiceError("service credential backend is unavailable") from error


def _systemd_arg(value: str) -> str:
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ServiceError("service path is unsafe")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def _run(args):
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode:
        raise ServiceError("service operation failed")


def install(config: Path, executable: str, *, system: str | None = None, home: Path | None = None):
    system = system or os.name
    if os.environ.get("DOCKER_CONTAINER"):
        raise ServiceError("services are unsupported in containers")
    validate_service_backend(config)
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
            f"[Unit]\nDescription=OneSearch Agent\n\n[Service]\nExecStart={_systemd_arg(executable)} -m onesearch_agent.cli --config {_systemd_arg(str(config))} run\nRestart=always\nRestartSec=5\n\n[Install]\nWantedBy=default.target\n"
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
