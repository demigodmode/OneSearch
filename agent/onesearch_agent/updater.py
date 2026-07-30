"""Out-of-process, recoverable native agent update transaction."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .update import UpdateError, UpdateResult


def _link_or_reparse(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def _regular(path: Path, *, required: bool = True) -> bool:
    if _link_or_reparse(path):
        raise UpdateError("update path must not be a symlink or reparse point")
    if not path.exists():
        if required:
            raise UpdateError("update file is missing")
        return False
    if not path.is_file():
        raise UpdateError("update path must be a regular file")
    return True


def _safe_directory(path: Path, *, create: bool = False) -> Path:
    # Check each existing component before resolve(), which would otherwise hide a link.
    candidate = path.absolute()
    for parent in (candidate, *candidate.parents):
        if parent.exists() and _link_or_reparse(parent):
            raise UpdateError("update directory must not be a symlink or reparse point")
    if create:
        candidate.mkdir(parents=True, exist_ok=True)
    if not candidate.is_dir():
        raise UpdateError("update state directory is invalid")
    return candidate.resolve()


def _safe_ancestry(path: Path) -> None:
    """Reject links in every existing ancestor without requiring the leaf to exist."""
    candidate = path.absolute()
    for parent in (candidate, *candidate.parents):
        if parent.exists() and _link_or_reparse(parent):
            raise UpdateError("update directory must not be a symlink or reparse point")


def _validate_version(version: str) -> None:
    if not version or any(character not in "0123456789." for character in version):
        raise UpdateError("update version is invalid")


def _durable_write(path: Path, value: bytes) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    try:
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:  # Windows does not allow opening directories this way.
        pass


@dataclass(frozen=True)
class UpdateTransaction:
    path: Path
    state_dir: Path
    current_binary: Path
    staged_binary: Path
    backup_binary: Path
    version: str
    started_at: float
    phase: str

    @classmethod
    def create(cls, *, state_dir: Path, current_binary: Path, artifact: bytes, version: str):
        _validate_version(version)
        state_dir = _safe_directory(state_dir, create=True)
        _regular(current_binary)
        current_binary = current_binary.absolute().resolve()
        updates = _safe_directory(state_dir / "updates", create=True)
        staged = updates / ("agent-" + version + ".staged")
        backup = current_binary.with_name(current_binary.name + ".previous")
        transaction_path = updates / "transaction.json"
        for path in (staged, backup, transaction_path):
            if path.exists() or _link_or_reparse(path):
                raise UpdateError("update transaction has unexplained existing state")
        _durable_write(staged, artifact)
        transaction = cls(
            path=transaction_path,
            state_dir=state_dir,
            current_binary=current_binary,
            staged_binary=staged,
            backup_binary=backup,
            version=version,
            started_at=time.time(),
            phase="staged",
        )
        transaction.save()
        return transaction

    @classmethod
    def load(cls, path: Path, *, expected_current_binary: Path | None = None):
        try:
            _regular(path)
            data = json.loads(path.read_text())
            raw_state_dir = Path(data["state_dir"])
            raw_current = Path(data["current_binary"])
            raw_staged = Path(data["staged_binary"])
            raw_backup = Path(data["backup_binary"])
            # Reject raw ancestry before resolve() can erase the evidence of a link.
            if not all(
                item.is_absolute() for item in (raw_state_dir, raw_current, raw_staged, raw_backup)
            ):
                raise UpdateError("update transaction is malformed")
            _safe_directory(raw_state_dir)
            _safe_ancestry(raw_current.parent)
            _safe_ancestry(raw_staged.parent)
            _safe_ancestry(raw_backup.parent)
            trusted_state_dir = path.absolute().parent.parent
            if raw_state_dir.absolute() != trusted_state_dir:
                raise UpdateError("transaction path is unsafe")
            transaction = cls(
                path=path.resolve(),
                state_dir=raw_state_dir.resolve(),
                current_binary=raw_current.resolve(),
                staged_binary=raw_staged.resolve(),
                backup_binary=raw_backup.resolve(),
                version=data["version"],
                started_at=float(data["started_at"]),
                phase=data["phase"],
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise UpdateError("update transaction is malformed") from error
        state_dir = _safe_directory(transaction.state_dir)
        updates = _safe_directory(state_dir / "updates")
        if transaction.path != updates / "transaction.json":
            raise UpdateError("transaction path is unsafe")
        if transaction.staged_binary != updates / (
            "agent-" + transaction.version + ".staged"
        ) or transaction.backup_binary != transaction.current_binary.with_name(
            transaction.current_binary.name + ".previous"
        ):
            raise UpdateError("transaction path is unsafe")
        _validate_version(transaction.version)
        if expected_current_binary is not None:
            _regular(expected_current_binary)
            if transaction.current_binary != expected_current_binary.absolute().resolve():
                raise UpdateError("transaction current binary does not match expected sibling")
        for item in (
            transaction.current_binary,
            transaction.staged_binary,
            transaction.backup_binary,
        ):
            if _link_or_reparse(item):
                raise UpdateError("update path must not be a symlink or reparse point")
        return transaction

    def save(self, phase: str | None = None):
        value = self if phase is None else UpdateTransaction(**{**self.__dict__, "phase": phase})
        _durable_write(
            value.path,
            json.dumps(
                {
                    "state_dir": str(value.state_dir),
                    "current_binary": str(value.current_binary),
                    "staged_binary": str(value.staged_binary),
                    "backup_binary": str(value.backup_binary),
                    "version": value.version,
                    "started_at": value.started_at,
                    "phase": value.phase,
                },
                sort_keys=True,
            ).encode(),
        )
        return value


class UpdateHelper:
    """Only this process stops the service and swaps native executable files."""

    def __init__(self, *, service_manager, sleep=time.sleep, clock=time.time, deadline=30):
        self.service_manager, self.sleep, self.clock, self.deadline = (
            service_manager,
            sleep,
            clock,
            deadline,
        )

    def run(
        self, transaction_path: Path, *, expected_current_binary: Path | None = None
    ) -> UpdateResult:
        transaction = UpdateTransaction.load(
            transaction_path, expected_current_binary=expected_current_binary
        )
        if transaction.phase not in {
            "staged",
            "stopping",
            "backed_up",
            "switched",
            "started",
            "rolled_back",
        }:
            raise UpdateError("update transaction phase is invalid")
        if not self.service_manager.is_managed():
            raise UpdateError("OneSearch Agent service is not installed or managed")
        # A crash can happen after current was moved but before the phase write.
        # The backup is the only known-good copy; restore it without touching it first.
        if transaction.phase == "stopping" and not transaction.current_binary.exists():
            _regular(transaction.backup_binary)
            os.replace(transaction.backup_binary, transaction.current_binary)
            transaction = transaction.save("rolled_back")
            self.service_manager.start()
            return UpdateResult("rolled_back", transaction.version)
        # Once the replacement was started, health has not been durably proven. Never
        # start a second attempt by moving the new binary over the only old copy.
        if transaction.phase in {"backed_up", "switched", "started", "rolled_back"}:
            return self._rollback(transaction)
        _regular(transaction.current_binary)
        _regular(transaction.staged_binary)
        self.service_manager.stop()
        transaction = transaction.save("stopping")
        os.replace(transaction.current_binary, transaction.backup_binary)
        transaction = transaction.save("backed_up")
        os.replace(transaction.staged_binary, transaction.current_binary)
        transaction = transaction.save("switched")
        self.service_manager.start()
        transaction = transaction.save("started")
        until = self.clock() + self.deadline
        while self.clock() <= until:
            if self._healthy(transaction):
                transaction.backup_binary.unlink(missing_ok=True)
                transaction.path.unlink(missing_ok=True)
                return UpdateResult("installed", transaction.version)
            self.sleep(1)
        return self._rollback(transaction)

    def _rollback(self, transaction: UpdateTransaction) -> UpdateResult:
        # A completed rollback is idempotent: only restart the known-good service.
        if transaction.phase == "rolled_back":
            _regular(transaction.current_binary)
            self.service_manager.start()
            return UpdateResult("rolled_back", transaction.version)
        _regular(transaction.backup_binary)
        self.service_manager.stop()
        if transaction.current_binary.exists():
            _regular(transaction.current_binary)
            transaction.current_binary.unlink()
        os.replace(transaction.backup_binary, transaction.current_binary)
        transaction = transaction.save("rolled_back")
        try:
            self.service_manager.start()
        except Exception as error:
            # Keep the transaction: a later helper invocation can restart the
            # known-good binary, and operators have a durable diagnosis.
            raise UpdateError("update rollback could not restart the service") from error
        return UpdateResult("rolled_back", transaction.version)

    def _healthy(self, transaction: UpdateTransaction) -> bool:
        try:
            marker_path = transaction.state_dir / "healthy.json"
            _regular(marker_path)
            marker = json.loads(marker_path.read_text())
            timestamp = float(marker["timestamp"])
            return (
                marker["version"] == transaction.version
                and timestamp > transaction.started_at
                and timestamp <= self.clock() + 300
            )
        except (UpdateError, OSError, KeyError, ValueError, TypeError, json.JSONDecodeError):
            return False
