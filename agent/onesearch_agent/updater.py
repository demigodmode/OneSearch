"""Out-of-process, recoverable native agent update transaction."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .update import UpdateError, UpdateResult


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
        state_dir = state_dir.resolve()
        current_binary = current_binary.resolve()
        state_dir.mkdir(parents=True, exist_ok=True)
        updates = state_dir / "updates"
        updates.mkdir(exist_ok=True)
        staged = updates / ("agent-" + version + ".staged")
        backup = current_binary.with_name(current_binary.name + ".previous")
        _durable_write(staged, artifact)
        transaction = cls(
            path=updates / "transaction.json",
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
    def load(cls, path: Path):
        try:
            data = json.loads(path.read_text())
            transaction = cls(
                path=path.resolve(),
                state_dir=Path(data["state_dir"]).resolve(),
                current_binary=Path(data["current_binary"]).resolve(),
                staged_binary=Path(data["staged_binary"]).resolve(),
                backup_binary=Path(data["backup_binary"]).resolve(),
                version=data["version"],
                started_at=float(data["started_at"]),
                phase=data["phase"],
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise UpdateError("update transaction is malformed") from error
        if transaction.path.parent != transaction.state_dir / "updates":
            raise UpdateError("transaction path is unsafe")
        if (
            transaction.staged_binary.parent != transaction.path.parent
            or transaction.backup_binary.parent != transaction.current_binary.parent
        ):
            raise UpdateError("transaction path is unsafe")
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

    def run(self, transaction_path: Path) -> UpdateResult:
        transaction = UpdateTransaction.load(transaction_path)
        # Any interrupted state is returned to a known good binary before retrying.
        if transaction.phase in {"backed_up", "switched"} and transaction.backup_binary.exists():
            if transaction.current_binary.exists():
                transaction.current_binary.unlink()
            os.replace(transaction.backup_binary, transaction.current_binary)
            transaction = transaction.save("rolled_back")
            self.service_manager.start()
            return UpdateResult("rolled_back", transaction.version)
        self.service_manager.stop()
        transaction = transaction.save("stopping")
        if transaction.current_binary.exists():
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
        self.service_manager.stop()
        if transaction.current_binary.exists():
            transaction.current_binary.unlink()
        os.replace(transaction.backup_binary, transaction.current_binary)
        transaction.save("rolled_back")
        self.service_manager.start()
        return UpdateResult("rolled_back", transaction.version)

    def _healthy(self, transaction: UpdateTransaction) -> bool:
        try:
            marker = json.loads((transaction.state_dir / "healthy.json").read_text())
            return (
                marker["version"] == transaction.version
                and float(marker["timestamp"]) > transaction.started_at
            )
        except (OSError, KeyError, ValueError, TypeError, json.JSONDecodeError):
            return False
