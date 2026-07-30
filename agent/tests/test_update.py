import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from onesearch_agent.update import UpdateError, UpdateManager
from onesearch_shared import MINIMUM_SUPPORTED_PROTOCOL_VERSION, PROTOCOL_VERSION


def test_update_manager_is_available():
    assert UpdateManager is not None


@pytest.fixture
def signing_key():
    return Ed25519PrivateKey.generate()


def signed_manifest(key, *, artifact=b"new-agent", **overrides):
    manifest = {
        "version": "1.4.0",
        "protocol_min": MINIMUM_SUPPORTED_PROTOCOL_VERSION,
        "protocol_max": PROTOCOL_VERSION,
        "platform": "win32-x64",
        "url": "https://releases.example/onesearch-agent.exe",
        "size": len(artifact),
        "sha256": hashlib.sha256(artifact).hexdigest(),
    } | overrides
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return {
        "manifest": manifest,
        "signature": base64.b64encode(key.sign(payload)).decode(),
    }


def manager(key, **kwargs):
    public_key = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return UpdateManager(public_key=public_key, platform="win32-x64", **kwargs)


def test_updates_are_off_by_default_without_contacting_release_host(signing_key):
    contacts = []
    result = manager(signing_key, fetch=lambda url: contacts.append(url)).check(auto_update=False)
    assert result.action == "disabled"
    assert contacts == []


def test_auto_update_discloses_release_host_contact(signing_key):
    notices = []
    result = manager(
        signing_key,
        release_manifest_url="https://releases.example/manifest.json",
        fetch=lambda url: signed_manifest(signing_key),
        notify=notices.append,
    ).check(auto_update=True)
    assert result.action == "available"
    assert "releases.example" in notices[0]


def test_rejects_manifest_with_invalid_ed25519_signature(signing_key):
    payload = signed_manifest(signing_key)
    payload["signature"] = base64.b64encode(b"wrong").decode()
    with pytest.raises(UpdateError, match="signature"):
        manager(signing_key, fetch=lambda url: payload).check(auto_update=True)


def test_rejects_checksum_mismatch_before_replacing_binary(signing_key, tmp_path: Path):
    current = tmp_path / "onesearch-agent.exe"
    current.write_bytes(b"old-agent")
    payload = signed_manifest(signing_key, sha256="0" * 64)
    with pytest.raises(UpdateError, match="checksum"):
        manager(
            signing_key,
            fetch=lambda url: payload if url.endswith("manifest.json") else b"new-agent",
        ).apply(auto_update=True, current_binary=current, health_check=lambda: True)
    assert current.read_bytes() == b"old-agent"


def test_rejects_incompatible_protocol_range(signing_key):
    payload = signed_manifest(signing_key, protocol_min=PROTOCOL_VERSION + 1)
    with pytest.raises(UpdateError, match="protocol"):
        manager(signing_key, fetch=lambda url: payload).check(auto_update=True)


def test_replaces_binary_atomically_after_a_healthy_start(signing_key, tmp_path: Path):
    current = tmp_path / "onesearch-agent.exe"
    current.write_bytes(b"old-agent")
    payload = signed_manifest(signing_key)
    result = manager(
        signing_key, fetch=lambda url: payload if url.endswith("manifest.json") else b"new-agent"
    ).apply(auto_update=True, current_binary=current, health_check=lambda: True)
    assert result.action == "installed"
    assert current.read_bytes() == b"new-agent"
    assert not current.with_suffix(".exe.bak").exists()


def test_restores_previous_binary_when_restarted_agent_is_unhealthy(signing_key, tmp_path: Path):
    current = tmp_path / "onesearch-agent.exe"
    current.write_bytes(b"old-agent")
    payload = signed_manifest(signing_key)
    result = manager(
        signing_key, fetch=lambda url: payload if url.endswith("manifest.json") else b"new-agent"
    ).apply(auto_update=True, current_binary=current, health_check=lambda: False)
    assert result.action == "rolled_back"
    assert current.read_bytes() == b"old-agent"


def test_docker_agent_notifies_but_never_replaces_container(signing_key, tmp_path: Path):
    current = tmp_path / "onesearch-agent"
    current.write_bytes(b"old-agent")
    payload = signed_manifest(signing_key)
    result = manager(
        signing_key,
        container=True,
        fetch=lambda url: payload if url.endswith("manifest.json") else b"new-agent",
    ).apply(auto_update=True, current_binary=current, health_check=lambda: True)
    assert result.action == "notify"
    assert current.read_bytes() == b"old-agent"
