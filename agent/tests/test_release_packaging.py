import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from onesearch_agent.packaging import (
    artifact_name,
    checksum_lines,
    manifest_url,
    should_launch_windows_service,
    sign_bytes,
    sign_manifest,
    verify_key_pair,
)
from onesearch_agent.update import UpdateManager


def test_artifact_names_and_manifest_url_use_one_explicit_target_mapping():
    assert artifact_name("1.4.0", "linux-amd64") == "onesearch-agent-1.4.0-linux-amd64"
    assert artifact_name("1.4.0", "win32-x64") == "onesearch-agent-1.4.0-windows-x64.exe"
    assert manifest_url("owner/repo", "1.4.0", "linux-amd64").endswith(
        "/v1.4.0/onesearch-agent-1.4.0-linux-amd64"
    )


def test_checksum_lines_include_only_final_binary_assets_in_sorted_order(tmp_path: Path):
    (tmp_path / "z-manifest.json").write_text("{}")
    (tmp_path / "onesearch-agent-1.4.0-linux-amd64").write_bytes(b"agent")
    (tmp_path / "onesearch-agent-updater-1.4.0-linux-amd64").write_bytes(b"updater")
    (tmp_path / "SHA256SUMS").write_text("old")
    assert checksum_lines(tmp_path) == [
        f"{hashlib.sha256(b'agent').hexdigest()}  onesearch-agent-1.4.0-linux-amd64",
        f"{hashlib.sha256(b'updater').hexdigest()}  onesearch-agent-updater-1.4.0-linux-amd64",
    ]


def test_key_pair_requires_base64_raw_matching_32_byte_keys():
    private = Ed25519PrivateKey.generate()
    private_raw = private.private_bytes_raw()
    public_raw = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    verify_key_pair(base64.b64encode(private_raw).decode(), base64.b64encode(public_raw).decode())
    with pytest.raises(ValueError, match="match"):
        verify_key_pair(
            base64.b64encode(private_raw).decode(), base64.b64encode(b"x" * 32).decode()
        )


def test_checksum_signature_uses_the_raw_ed25519_key_contract():
    private = Ed25519PrivateKey.generate()
    payload = b"checksum lines\n"
    signature = sign_bytes(payload, base64.b64encode(private.private_bytes_raw()).decode())
    private.public_key().verify(signature, payload)


def test_produced_manifest_is_accepted_by_update_manager(tmp_path: Path):
    private = Ed25519PrivateKey.generate()
    artifact = tmp_path / artifact_name("1.4.0", "linux-amd64")
    artifact.write_bytes(b"agent release")
    envelope = sign_manifest(
        artifact=artifact,
        platform="linux-amd64",
        version="1.4.0",
        url=manifest_url("owner/repo", "1.4.0", "linux-amd64"),
        private_key=base64.b64encode(private.private_bytes_raw()).decode(),
    )
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    result = UpdateManager(
        public_key=public, platform="linux-amd64", current_version="1.3.0", fetch=lambda _: envelope
    ).check(auto_update=True)
    assert result.version == "1.4.0"
    assert envelope["manifest"] == json.loads(json.dumps(envelope["manifest"]))


def test_windows_frozen_entry_dispatches_only_no_cli_invocations_to_scm():
    assert should_launch_windows_service("win32", [])
    assert not should_launch_windows_service("win32", ["run"])
    assert not should_launch_windows_service("win32", ["--help"])
    assert not should_launch_windows_service("win32", ["unknown"])
    assert not should_launch_windows_service("linux", [])
