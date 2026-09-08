"""Pure release packaging primitives shared by CI and manifest creation."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from onesearch_shared import MINIMUM_SUPPORTED_PROTOCOL_VERSION, PROTOCOL_VERSION

_TARGETS = {
    "linux-amd64": "linux-amd64",
    "linux-arm64": "linux-arm64",
    "win32-x64": "windows-x64",
}


def should_launch_windows_service(platform: str, argv: list[str]) -> bool:
    """SCM starts the frozen Windows binary without a Click subcommand."""
    return platform == "win32" and not argv


def artifact_name(version: str, platform: str, *, updater: bool = False) -> str:
    """Return the uploaded asset basename for a native target."""
    label = _TARGETS[platform]
    prefix = "onesearch-agent-updater" if updater else "onesearch-agent"
    suffix = ".exe" if platform == "win32-x64" else ""
    return f"{prefix}-{version}-{label}{suffix}"


def manifest_url(repository: str, version: str, platform: str) -> str:
    return (
        f"https://github.com/{repository}/releases/download/v{version}/"
        f"{artifact_name(version, platform)}"
    )


def checksum_lines(directory: Path) -> list[str]:
    """Return sorted checksums for release binaries only."""
    artifacts = sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.name.startswith("onesearch-agent-")
    )
    return [f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}" for path in artifacts]


def _raw_key(value: str, name: str) -> bytes:
    try:
        key = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError(f"{name} must be base64") from error
    if len(key) != 32:
        raise ValueError(f"{name} must contain a raw 32-byte Ed25519 key")
    return key


def validate_public_key(value: str) -> bytes:
    """Return a strict raw Ed25519 public key for release artifact embedding."""
    return _raw_key(value.strip(), "public key")


def verify_key_pair(private_key: str, public_key: str) -> None:
    private = _raw_key(private_key, "private key")
    supplied = validate_public_key(public_key)
    derived = Ed25519PrivateKey.from_private_bytes(private).public_key().public_bytes_raw()
    if not hmac.compare_digest(derived, supplied):
        raise ValueError("public key does not match private key")


def sign_bytes(payload: bytes, private_key: str) -> bytes:
    return Ed25519PrivateKey.from_private_bytes(_raw_key(private_key, "private key")).sign(payload)


def sign_manifest(
    *, artifact: Path, platform: str, version: str, url: str, private_key: str
) -> dict:
    contents = artifact.read_bytes()
    manifest = {
        "version": version,
        "protocol_min": MINIMUM_SUPPORTED_PROTOCOL_VERSION,
        "protocol_max": PROTOCOL_VERSION,
        "platform": platform,
        "url": url,
        "size": len(contents),
        "sha256": hashlib.sha256(contents).hexdigest(),
    }
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    signature = sign_bytes(payload, private_key)
    return {"manifest": manifest, "signature": base64.b64encode(signature).decode()}
