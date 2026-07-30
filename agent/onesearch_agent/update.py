"""Signed native-agent update support."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from urllib.request import urlopen

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from onesearch_shared import MINIMUM_SUPPORTED_PROTOCOL_VERSION, PROTOCOL_VERSION


class UpdateError(RuntimeError):
    """A release artifact was absent, malformed, or unsafe to install."""


@dataclass(frozen=True)
class UpdateResult:
    action: str
    version: str | None = None


class UpdateManager:
    """Verify and optionally install signed native agent releases."""

    def __init__(
        self,
        *,
        public_key: bytes | None = None,
        platform: str,
        release_manifest_url: str = (
            "https://github.com/demigodmode/OneSearch/releases/latest/download/agent-manifest.json"
        ),
        fetch: Callable[[str], bytes | dict] | None = None,
        notify: Callable[[str], None] | None = None,
        container: bool | None = None,
    ):
        self.public_key = public_key or _embedded_public_key()
        self.platform = platform
        self.release_manifest_url = release_manifest_url
        self.fetch = fetch or _download
        self.notify = notify or (lambda message: None)
        self.container = (
            bool(os.environ.get("DOCKER_CONTAINER")) if container is None else container
        )

    def check(self, *, auto_update: bool) -> UpdateResult:
        if not auto_update:
            return UpdateResult("disabled")
        self.notify(
            "Auto-update contacts " + _host(self.release_manifest_url) + " for signed releases."
        )
        payload = self.fetch(self.release_manifest_url)
        manifest, signature = _signed_manifest(payload)
        _verify_signature(self.public_key, manifest, signature)
        _validate_manifest(manifest, self.platform)
        return UpdateResult("available", manifest["version"])

    def apply(
        self,
        *,
        auto_update: bool,
        current_binary: Path,
        health_check: Callable[[], bool],
    ) -> UpdateResult:
        result = self.check(auto_update=auto_update)
        if result.action != "available":
            return result
        if self.container:
            self.notify(
                "A newer agent image is available; Docker containers are never self-updated."
            )
            return UpdateResult("notify", result.version)

        payload = self.fetch(self.release_manifest_url)
        manifest, signature = _signed_manifest(payload)
        _verify_signature(self.public_key, manifest, signature)
        _validate_manifest(manifest, self.platform)
        artifact = _as_bytes(self.fetch(manifest["url"]))
        if len(artifact) != manifest["size"]:
            raise UpdateError("artifact size does not match signed manifest")
        if hashlib.sha256(artifact).hexdigest() != manifest["sha256"]:
            raise UpdateError("artifact checksum does not match signed manifest")
        return _replace_and_check(current_binary, artifact, result.version, health_check)


def _embedded_public_key() -> bytes:
    value = os.environ.get("ONESEARCH_AGENT_UPDATE_PUBLIC_KEY")
    if value is None:
        value = files("onesearch_agent").joinpath("release_public_key.txt").read_text().strip()
    if not value:
        raise UpdateError("native updates are unavailable: no release public key was embedded")
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as error:
        raise UpdateError(
            "native updates are unavailable: embedded public key is invalid"
        ) from error


def _download(url: str) -> bytes:
    with urlopen(url, timeout=30) as response:  # noqa: S310 - URL is signed only after download
        return response.read()


def _as_bytes(value: bytes | dict) -> bytes:
    if not isinstance(value, bytes):
        raise UpdateError("release download was not binary data")
    return value


def _signed_manifest(value: bytes | dict) -> tuple[dict, bytes]:
    if isinstance(value, bytes):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise UpdateError("release manifest is not valid JSON") from error
    if not isinstance(value, dict) or not isinstance(value.get("manifest"), dict):
        raise UpdateError("release manifest is malformed")
    try:
        signature = base64.b64decode(value["signature"], validate=True)
    except (KeyError, TypeError, ValueError) as error:
        raise UpdateError("release manifest signature is malformed") from error
    return value["manifest"], signature


def _verify_signature(public_key: bytes, manifest: dict, signature: bytes) -> None:
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            signature, json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        )
    except (InvalidSignature, ValueError, TypeError) as error:
        raise UpdateError("release manifest signature verification failed") from error


def _validate_manifest(manifest: dict, platform: str) -> None:
    required = {"version", "protocol_min", "protocol_max", "platform", "url", "size", "sha256"}
    if required - manifest.keys():
        raise UpdateError("release manifest is incomplete")
    if manifest["platform"] != platform:
        raise UpdateError("release manifest is for another platform")
    if not isinstance(manifest["protocol_min"], int) or not isinstance(
        manifest["protocol_max"], int
    ):
        raise UpdateError("release manifest protocol range is invalid")
    if (
        manifest["protocol_min"] > manifest["protocol_max"]
        or manifest["protocol_max"] < MINIMUM_SUPPORTED_PROTOCOL_VERSION
        or manifest["protocol_min"] > PROTOCOL_VERSION
    ):
        raise UpdateError("release manifest protocol range is incompatible")
    if not isinstance(manifest["size"], int) or manifest["size"] < 0:
        raise UpdateError("release manifest artifact size is invalid")
    if not isinstance(manifest["sha256"], str) or len(manifest["sha256"]) != 64:
        raise UpdateError("release manifest checksum is invalid")


def _replace_and_check(
    current_binary: Path, artifact: bytes, version: str, health_check: Callable[[], bool]
) -> UpdateResult:
    staged = current_binary.with_name(f".{current_binary.name}.{version}.new")
    backup = current_binary.with_name(current_binary.name + ".bak")
    with staged.open("wb") as handle:
        handle.write(artifact)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(current_binary, backup)
        os.replace(staged, current_binary)
        if not health_check():
            raise UpdateError("updated agent did not report a healthy heartbeat")
    except Exception:
        if backup.exists():
            os.replace(backup, current_binary)
        staged.unlink(missing_ok=True)
        return UpdateResult("rolled_back", version)
    backup.unlink(missing_ok=True)
    return UpdateResult("installed", version)


def _host(url: str) -> str:
    return url.split("/", 3)[2]
