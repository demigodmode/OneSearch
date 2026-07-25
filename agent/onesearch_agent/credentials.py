"""Credential stores that never include tokens in diagnostics."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path


class CredentialError(RuntimeError):
    pass


class FileCredentialStore:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.path = state_dir / "credential"

    def _secure_dir(self):
        if self.state_dir.is_symlink():
            raise CredentialError("state directory is unsafe")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            self.state_dir.chmod(0o700)
            mode = stat.S_IMODE(self.state_dir.stat().st_mode)
            if mode & 0o077:
                raise CredentialError("state directory permissions are unsafe")

    def save(self, token: str):
        if not token.strip():
            raise CredentialError("credential is blank")
        self._secure_dir()
        if self.path.exists():
            raise CredentialError("credential already exists")
        fd, name = tempfile.mkstemp(dir=self.state_dir)
        try:
            if os.name != "nt":
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as handle:
                handle.write(token)
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def load(self) -> str:
        self._secure_dir()
        if self.path.is_symlink() or not self.path.is_file():
            raise CredentialError("credential is unavailable")
        if os.name != "nt" and stat.S_IMODE(self.path.stat().st_mode) & 0o077:
            raise CredentialError("credential permissions are unsafe")
        token = self.path.read_text().strip()
        if not token:
            raise CredentialError("credential is blank")
        return token
