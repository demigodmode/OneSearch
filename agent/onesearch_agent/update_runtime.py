"""Shared service-only update hooks for native agent entry points."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .update import UpdateError, UpdateManager
from .updater import _durable_write
from .updater_cli import launch


def write_healthy_marker(state_dir: Path, version: str, timestamp: float) -> None:
    """Publish health only after the runtime has completed a fresh heartbeat."""
    state_dir.mkdir(parents=True, exist_ok=True)
    _durable_write(
        state_dir / "healthy.json",
        json.dumps({"version": version, "timestamp": timestamp}, sort_keys=True).encode(),
    )


def stage_and_launch(*, config, platform: str, version: str, current_binary: Path, managed: bool):
    """Prepare a signed replacement only from an OS-managed native process."""
    if not config.auto_update:
        return None
    if not managed:
        raise UpdateError(
            "automatic updates require the installed OneSearch Agent service; "
            "run 'onesearch-agent service install' or update manually"
        )
    prepared = UpdateManager(
        platform=platform,
        current_version=version,
        container=bool(os.environ.get("DOCKER_CONTAINER")),
    ).stage(auto_update=True, current_binary=current_binary, state_dir=config.state_dir)
    if getattr(prepared, "path", None):
        launch(prepared.path)
    return prepared
