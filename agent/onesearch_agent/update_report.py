"""Durable, sanitized update-check state for agent heartbeats."""

from __future__ import annotations

import os
from pathlib import Path

from onesearch_shared import AgentUpdateReport

from .update import UpdateError, UpdateManager

_DAILY_SECONDS = 24 * 60 * 60
_RETRY_SECONDS = 60 * 60


class UpdateReporter:
    def __init__(self, *, auto_update, platform, version, state_dir, update_manager=None, clock):
        self.auto_update = auto_update
        self.state_dir = Path(state_dir)
        self.clock = clock
        self.manager = update_manager
        self.platform = platform
        self.version = version
        self._report = self._load() or AgentUpdateReport(
            auto_update=auto_update, runtime_kind="docker" if os.environ.get("DOCKER_CONTAINER") else "native",
            status="not_checked", checked_at=0,
        )

    def _path(self):
        return self.state_dir / "update-report.json"

    def _load(self):
        try:
            return AgentUpdateReport.model_validate_json(self._path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _save(self):
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            temporary = self._path().with_suffix(".tmp")
            temporary.write_text(self._report.model_dump_json(), encoding="utf-8")
            os.replace(temporary, self._path())
        except OSError:
            pass

    def report(self):
        return self._report

    def record_install_error(self, error):
        message = str(error).lower()
        code = "install_unavailable" if "require" in message or "unavailable" in message else "install_failed"
        self._report = AgentUpdateReport(
            auto_update=self.auto_update, runtime_kind=self._report.runtime_kind,
            status="error", checked_at=int(self.clock()), error_code=code,
        )
        self._save()

    def check_if_due(self):
        now = int(self.clock())
        delay = _RETRY_SECONDS if self._report.status == "error" else _DAILY_SECONDS
        if self._report.checked_at and now - self._report.checked_at < delay:
            return False
        try:
            manager = self.manager or UpdateManager(platform=self.platform, current_version=self.version)
            result = manager.check(auto_update=True)
            self._report = AgentUpdateReport(
                auto_update=self.auto_update, runtime_kind=self._report.runtime_kind,
                status=result.action, available_version=result.version if result.action == "available" else None,
                checked_at=now,
            )
        except UpdateError as error:
            message = str(error).lower()
            code = "network"
            if any(value in message for value in ("manifest", "signature", "checksum", "version", "platform")):
                code = "invalid_manifest"
            if "incompatible" in message or "older" in message:
                code = "incompatible"
            self._report = AgentUpdateReport(
                auto_update=self.auto_update, runtime_kind=self._report.runtime_kind,
                status="error", checked_at=now, error_code=code,
            )
        self._save()
        return True
