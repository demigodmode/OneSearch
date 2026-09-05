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

from .packaging import validate_public_key


class UpdateError(RuntimeError):
    """A release artifact was absent, malformed, or unsafe to install."""


MAX_MANIFEST_BYTES = 1024 * 1024
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024


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
        release_manifest_url: str | None = None,
        fetch: Callable[[str], bytes | dict] | None = None,
        notify: Callable[[str], None] | None = None,
        container: bool | None = None,
        current_version: str = "0.0.0",
    ):
        self.public_key = public_key or _embedded_public_key()
        self.platform = platform
        self.release_manifest_url = release_manifest_url or (
            "https://github.com/demigodmode/OneSearch/releases/latest/download/agent-manifest-"
            + platform
            + ".json"
        )
        self.fetch = fetch
        self.notify = notify or (lambda message: None)
        self.container = (
            bool(os.environ.get("DOCKER_CONTAINER")) if container is None else container
        )
        self.current_version = current_version

    def check(self, *, auto_update: bool) -> UpdateResult:
        if not auto_update:
            return UpdateResult("disabled")
        self.notify(
            "Auto-update contacts " + _host(self.release_manifest_url) + " for signed releases."
        )
        manifest = self._manifest()
        comparison = _compare_versions(manifest["version"], self.current_version)
        if comparison == 0:
            return UpdateResult("current", manifest["version"])
        if comparison < 0:
            raise UpdateError("release version is older than this agent")
        return UpdateResult("available", manifest["version"])

    def _manifest(self) -> dict:
        payload = (
            self.fetch(self.release_manifest_url)
            if self.fetch
            else _download(self.release_manifest_url, maximum=MAX_MANIFEST_BYTES)
        )
        manifest, signature = _signed_manifest(payload)
        _verify_signature(self.public_key, manifest, signature)
        _validate_manifest(manifest, self.platform)
        return manifest

    def stage(self, *, auto_update: bool, current_binary: Path, state_dir: Path):
        """Download a verified update without ever touching the running binary."""
        if not auto_update:
            return UpdateResult("disabled")
        self.notify(
            "Auto-update contacts " + _host(self.release_manifest_url) + " for signed releases."
        )
        manifest = self._manifest()
        comparison = _compare_versions(manifest["version"], self.current_version)
        if comparison == 0:
            return UpdateResult("current", manifest["version"])
        if comparison < 0:
            raise UpdateError("release version is older than this agent")
        if self.container:
            self.notify(
                "A newer agent image is available; Docker containers are never self-updated."
            )
            return UpdateResult("notify", manifest["version"])
        from .updater import UpdateTransaction

        if not self.fetch:
            with urlopen(  # noqa: S310 - the artifact URL is signed by the release key
                manifest["url"], timeout=30
            ) as response:
                return UpdateTransaction.create_streamed(
                    state_dir=state_dir,
                    current_binary=current_binary,
                    stream=response,
                    version=manifest["version"],
                    expected_size=manifest["size"],
                    expected_sha256=manifest["sha256"],
                )
        artifact = _as_bytes(self.fetch(manifest["url"]))
        if len(artifact) != manifest["size"]:
            raise UpdateError("artifact size does not match signed manifest")
        if hashlib.sha256(artifact).hexdigest() != manifest["sha256"]:
            raise UpdateError("artifact checksum does not match signed manifest")
        return UpdateTransaction.create(
            state_dir=state_dir,
            current_binary=current_binary,
            artifact=artifact,
            version=manifest["version"],
        )

    def apply(
        self,
        *,
        auto_update: bool,
        current_binary: Path,
        health_check: Callable[[], bool],
    ) -> UpdateResult:
        raise UpdateError("in-process updates are unsupported; use the separate updater helper")

    def recover(self, current_binary: Path) -> bool:
        """Restore the last known-good binary after an interrupted swap."""
        backup = current_binary.with_name(current_binary.name + ".bak")
        if not backup.exists():
            return False
        os.replace(backup, current_binary)
        return True


def _embedded_public_key() -> bytes:
    value = os.environ.get("ONESEARCH_AGENT_UPDATE_PUBLIC_KEY")
    if value is None:
        value = files("onesearch_agent").joinpath("release_public_key.txt").read_text().strip()
    if not value:
        raise UpdateError("native updates are unavailable: no release public key was embedded")
    try:
        return validate_public_key(value)
    except ValueError as error:
        raise UpdateError(
            "native updates are unavailable: embedded public key is invalid"
        ) from error


def _download(url: str, *, maximum: int) -> bytes:
    with urlopen(url, timeout=30) as response:  # noqa: S310 - URL is signed only after download
        chunks, total = [], 0
        while chunk := response.read(64 * 1024):
            total += len(chunk)
            if total > maximum:
                raise UpdateError("release download exceeds maximum size")
            chunks.append(chunk)
        return b"".join(chunks)


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
    if not isinstance(manifest["size"], int) or not 0 < manifest["size"] <= MAX_ARTIFACT_BYTES:
        raise UpdateError("release manifest artifact size is invalid")
    if not isinstance(manifest["sha256"], str) or len(manifest["sha256"]) != 64:
        raise UpdateError("release manifest checksum is invalid")
    if not all(character in "0123456789abcdef" for character in manifest["sha256"]):
        raise UpdateError("release manifest checksum is invalid")
    if not isinstance(manifest["version"], str) or not _version(manifest["version"]):
        raise UpdateError("release manifest version is invalid")
    if not isinstance(manifest["url"], str) or not manifest["url"].startswith("https://"):
        raise UpdateError("release manifest artifact URL is invalid")


def _host(url: str) -> str:
    return url.split("/", 3)[2]


def _version(value: str) -> tuple[int, ...] | None:
    try:
        parts = tuple(int(part) for part in value.split("."))
    except ValueError:
        return None
    return parts if len(parts) == 3 and all(part >= 0 for part in parts) else None


def _is_newer(candidate: str, current: str) -> bool:
    return _compare_versions(candidate, current) > 0


def _compare_versions(candidate: str, current: str) -> int:
    candidate_parts = _version(candidate)
    current_parts = _version(current)
    if not candidate_parts or not current_parts:
        raise UpdateError("release version is invalid")
    return (candidate_parts > current_parts) - (candidate_parts < current_parts)
