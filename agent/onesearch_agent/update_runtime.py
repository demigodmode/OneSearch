"""Shared service-only update hooks for native agent entry points."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

from .update import UpdateError, UpdateManager
from .updater import _durable_write, _safe_ancestry
from .updater_cli import launch


def _regular_native(path: Path) -> bool:
    try:
        _safe_ancestry(path)
    except UpdateError:
        return False
    return (
        path.is_file()
        and not path.is_symlink()
        and not bool(getattr(path, "is_junction", lambda: False)())
    )


def native_update_layout(current_binary: Path) -> Path | None:
    """Return the sibling updater only for the fixed frozen distribution layout."""
    suffix = ".exe" if sys.platform == "win32" else ""
    if not getattr(sys, "frozen", False) or current_binary.name != "onesearch-agent" + suffix:
        return None
    helper = current_binary.with_name("onesearch-agent-updater" + suffix)
    return helper if _regular_native(current_binary) and _regular_native(helper) else None


def write_healthy_marker(state_dir: Path, version: str, timestamp: float) -> None:
    """Publish health only after the runtime has completed a fresh heartbeat."""
    _safe_ancestry(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    _safe_ancestry(state_dir)
    _durable_write(
        state_dir / "healthy.json",
        json.dumps({"version": version, "timestamp": timestamp}, sort_keys=True).encode(),
    )


def stage_and_launch(
    *,
    config,
    platform: str,
    version: str,
    current_binary: Path,
    managed: bool,
    notify: Callable[[str], None] | None = None,
):
    """Prepare a signed replacement only from an OS-managed native process."""
    if not config.auto_update:
        return None
    container = bool(os.environ.get("DOCKER_CONTAINER"))
    if container:
        return UpdateManager(
            platform=platform,
            current_version=version,
            container=True,
            notify=notify,
        ).stage(auto_update=True, current_binary=current_binary, state_dir=config.state_dir)
    if not managed:
        raise UpdateError(
            "automatic updates require the installed OneSearch Agent service; "
            "run 'onesearch-agent service install' or update manually"
        )
    if native_update_layout(current_binary) is None:
        raise UpdateError(
            "automatic updates require the installed native OneSearch Agent; update manually"
        )
    prepared = UpdateManager(
        platform=platform,
        current_version=version,
        container=False,
        notify=notify,
    ).stage(auto_update=True, current_binary=current_binary, state_dir=config.state_dir)
    if getattr(prepared, "path", None):
        launch(prepared.path)
    return prepared
