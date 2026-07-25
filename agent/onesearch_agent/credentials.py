"""Credential stores that never include tokens in diagnostics."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import keyring


class CredentialError(RuntimeError):
    pass


def _is_posix() -> bool:
    return os.name != "nt"


def _uid() -> int:
    return os.getuid()


def _validate_posix_metadata(symlink: bool, mode: int, owner: int, label: str) -> None:
    if symlink:
        raise CredentialError(f"{label} is unsafe")
    if mode & 0o077:
        raise CredentialError(f"{label} permissions are unsafe")
    if owner != _uid():
        raise CredentialError(f"{label} owner is unsafe")


class FileCredentialStore:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.path = state_dir / "credential"
        self.marker_path = state_dir / "credential-backend"

    def save_backend_marker(self, backend: str) -> None:
        if backend not in {"file", "keyring"}:
            raise CredentialError("credential backend marker is invalid")
        self._secure_dir()
        if self.marker_path.exists() or self.marker_path.is_symlink():
            raise CredentialError("credential backend marker already exists")
        fd, name = tempfile.mkstemp(dir=self.state_dir)
        try:
            if _is_posix():
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as handle:
                handle.write(backend)
            os.link(name, self.marker_path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def load_backend_marker(self) -> str | None:
        self._secure_dir()
        if not self.marker_path.exists():
            return None
        if self.marker_path.is_symlink():
            raise CredentialError("credential backend marker is unsafe")
        if _is_posix():
            info = self.marker_path.stat()
            _validate_posix_metadata(
                False, stat.S_IMODE(info.st_mode), info.st_uid, "credential backend marker"
            )
        value = self.marker_path.read_text().strip()
        if value not in {"file", "keyring"}:
            raise CredentialError("credential backend marker is invalid")
        return value

    def _secure_dir(self):
        if self.state_dir.is_symlink():
            raise CredentialError("state directory is unsafe")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if _is_posix():
            self.state_dir.chmod(0o700)
            info = self.state_dir.stat()
            _validate_posix_metadata(
                False, stat.S_IMODE(info.st_mode), info.st_uid, "state directory"
            )

    def save(self, token: str):
        if not token.strip():
            raise CredentialError("credential is blank")
        self._secure_dir()
        if self.path.exists():
            raise CredentialError("credential already exists")
        fd, name = tempfile.mkstemp(dir=self.state_dir)
        try:
            if _is_posix():
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as handle:
                handle.write(token)
            try:
                os.link(name, self.path)
            except FileExistsError as error:
                raise CredentialError("credential already exists") from error
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def load(self) -> str:
        self._secure_dir()
        if self.path.is_symlink() or not self.path.is_file():
            raise CredentialError("credential is unavailable")
        if _is_posix():
            info = self.path.stat()
            _validate_posix_metadata(False, stat.S_IMODE(info.st_mode), info.st_uid, "credential")
        token = self.path.read_text().strip()
        if not token:
            raise CredentialError("credential is blank")
        return token

    def delete(self) -> None:
        if self.path.is_symlink():
            raise CredentialError("credential is unsafe")
        if self.path.exists():
            self.path.unlink()


class KeyringCredentialStore:
    def __init__(self, server_url: str, agent_name: str):
        parsed = urlsplit(server_url)
        identity = urlunsplit(
            (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", "")
        )
        digest = hashlib.sha256(identity.encode()).hexdigest()
        self.service = "onesearch-agent"
        self.username = f"{agent_name}:{digest}"

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
            raise CredentialError("system credential store is unavailable") from error
        if token is None and optional:
            return None
        if not token or not token.strip():
            raise CredentialError("credential is unavailable")
        return token

    def delete(self) -> None:
        try:
            keyring.delete_password(self.service, self.username)
        except Exception as error:
            raise CredentialError("system credential store is unavailable") from error


def credential_store(config, *, system: str | None = None, docker: bool = False):
    system = system or os.name
    marker_store = FileCredentialStore(config.state_dir)
    remembered = marker_store.load_backend_marker()
    configured = os.environ.get("ONESEARCH_AGENT_CREDENTIAL_STORE", config.credential_store)
    if configured not in {"auto", "file", "keyring"}:
        raise CredentialError("credential store policy is invalid")
    if system == "nt" and configured == "file" and not docker:
        raise CredentialError("file credentials are unavailable on native Windows")
    if configured == "file" or docker or os.environ.get("ONESEARCH_AGENT_DOCKER") == "1":
        if remembered == "keyring":
            raise CredentialError("credential backend changed from keyring")
        return FileCredentialStore(config.state_dir)
    if remembered == "file":
        return marker_store
    keyring_store = KeyringCredentialStore(config.server_url, config.agent_name)
    backend = keyring.get_keyring()
    backend_name = f"{backend.__class__.__module__}.{backend.__class__.__name__}".lower()
    if (
        "keyrings.alt" in backend_name
        or "fail" in backend_name
        or getattr(backend, "priority", 0) <= 0
    ):
        if system == "nt" or configured == "keyring" or remembered == "keyring":
            raise CredentialError("system credential store is unavailable")
        return FileCredentialStore(config.state_dir)
    if configured == "keyring" or system == "nt":
        return keyring_store
    try:
        keyring_store.load(optional=True)
        return keyring_store
    except CredentialError:
        return FileCredentialStore(config.state_dir)
