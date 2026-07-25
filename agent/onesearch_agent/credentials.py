"""Credential stores that never include tokens in diagnostics."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import keyring


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
            if self.state_dir.stat().st_uid != os.getuid():
                raise CredentialError("state directory owner is unsafe")

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
        if os.name != "nt" and self.path.stat().st_uid != os.getuid():
            raise CredentialError("credential owner is unsafe")
        token = self.path.read_text().strip()
        if not token:
            raise CredentialError("credential is blank")
        return token


class KeyringCredentialStore:
    def __init__(self, server_url: str, agent_name: str):
        host = urlsplit(server_url).netloc
        self.service = f"onesearch-agent:{host}"
        self.username = agent_name

    def save(self, token: str):
        if not token.strip():
            raise CredentialError("credential is blank")
        if self.load(optional=True) is not None:
            raise CredentialError("credential already exists")
        try:
            keyring.set_password(self.service, self.username, token)
        except Exception as error:
            raise CredentialError("system credential store is unavailable") from error

    def load(self, optional=False):
        try:
            token = keyring.get_password(self.service, self.username)
        except Exception as error:
            if optional:
                return None
            raise CredentialError("system credential store is unavailable") from error
        if token is None and optional:
            return None
        if not token or not token.strip():
            raise CredentialError("credential is unavailable")
        return token


def credential_store(config, *, system: str | None = None, docker: bool = False):
    system = system or os.name
    if config.credential_store == "file" or docker:
        return FileCredentialStore(config.state_dir)
    keyring_store = KeyringCredentialStore(config.server_url, config.agent_name)
    if config.credential_store == "keyring" or system == "nt":
        return keyring_store
    try:
        keyring_store.load(optional=True)
        return keyring_store
    except CredentialError:
        return FileCredentialStore(config.state_dir)
