import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from onesearch_agent.update import UpdateError, UpdateManager
from onesearch_agent.updater import UpdateHelper, UpdateTransaction
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
    with pytest.raises(UpdateError, match="in-process"):
        manager(
            signing_key,
            fetch=lambda url: payload if url.endswith(".json") else b"new-agent",
        ).apply(auto_update=True, current_binary=current, health_check=lambda: True)
    assert current.read_bytes() == b"old-agent"


def test_rejects_incompatible_protocol_range(signing_key):
    payload = signed_manifest(signing_key, protocol_min=PROTOCOL_VERSION + 1)
    with pytest.raises(UpdateError, match="protocol"):
        manager(signing_key, fetch=lambda url: payload).check(auto_update=True)


def test_in_process_update_cannot_replace_a_running_binary(signing_key, tmp_path: Path):
    current = tmp_path / "onesearch-agent.exe"
    current.write_bytes(b"old-agent")
    with pytest.raises(UpdateError, match="in-process"):
        manager(signing_key).apply(
            auto_update=True, current_binary=current, health_check=lambda: True
        )
    assert current.read_bytes() == b"old-agent"


def test_in_process_update_never_attempts_windows_locked_executable(signing_key, tmp_path: Path):
    current = tmp_path / "onesearch-agent.exe"
    current.write_bytes(b"old-agent")
    with pytest.raises(UpdateError, match="in-process"):
        manager(signing_key).apply(
            auto_update=True, current_binary=current, health_check=lambda: False
        )
    assert current.read_bytes() == b"old-agent"


def test_docker_agent_notifies_but_never_replaces_container(signing_key, tmp_path: Path):
    current = tmp_path / "onesearch-agent"
    current.write_bytes(b"old-agent")
    payload = signed_manifest(signing_key)
    result = manager(
        signing_key,
        container=True,
        fetch=lambda url: payload if url.endswith(".json") else b"new-agent",
    ).stage(auto_update=True, current_binary=current, state_dir=tmp_path / "state")
    assert result.action == "notify"
    assert current.read_bytes() == b"old-agent"


def test_rejects_replayed_or_downgrade_release(signing_key):
    payload = signed_manifest(signing_key, version="1.3.0")
    with pytest.raises(UpdateError, match="newer"):
        manager(signing_key, current_version="1.3.0", fetch=lambda url: payload).check(
            auto_update=True
        )


def test_recovers_interrupted_replacement_from_durable_backup(signing_key, tmp_path: Path):
    current = tmp_path / "onesearch-agent.exe"
    backup = tmp_path / "onesearch-agent.exe.bak"
    current.write_bytes(b"partial-agent")
    backup.write_bytes(b"old-agent")
    assert manager(signing_key).recover(current) is True
    assert current.read_bytes() == b"old-agent"


def test_stage_fetches_one_verified_manifest_and_never_replaces_current_binary(
    signing_key, tmp_path
):
    current = tmp_path / "onesearch-agent.exe"
    current.write_bytes(b"old-agent")
    calls = []
    payload = signed_manifest(signing_key)
    prepared = manager(
        signing_key,
        fetch=lambda url: calls.append(url) or (payload if url.endswith(".json") else b"new-agent"),
    ).stage(auto_update=True, current_binary=current, state_dir=tmp_path / "state")
    assert current.read_bytes() == b"old-agent"
    assert prepared.path.exists()
    assert (
        calls.count(
            "https://github.com/demigodmode/OneSearch/releases/latest/download/agent-manifest-win32-x64.json"
        )
        == 1
    )


def test_helper_rolls_back_when_new_heartbeat_is_wrong_or_stale(tmp_path):
    current = tmp_path / "onesearch-agent.exe"
    current.write_bytes(b"old")
    state = tmp_path / "state"
    transaction = UpdateTransaction.create(
        state_dir=state, current_binary=current, artifact=b"new", version="1.4.0"
    )
    manager = FakeServiceManager()
    result = UpdateHelper(service_manager=manager, sleep=lambda _: None, deadline=0).run(
        transaction.path
    )
    assert result.action == "rolled_back"
    assert current.read_bytes() == b"old"
    assert manager.calls == ["stop", "start", "stop", "start"]


def test_helper_accepts_only_new_expected_healthy_marker(tmp_path):
    current = tmp_path / "onesearch-agent"
    current.write_bytes(b"old")
    state = tmp_path / "state"
    transaction = UpdateTransaction.create(
        state_dir=state, current_binary=current, artifact=b"new", version="1.4.0"
    )
    manager = FakeServiceManager()
    (state / "healthy.json").write_text(
        json.dumps({"version": "1.4.0", "timestamp": transaction.started_at + 1})
    )
    result = UpdateHelper(service_manager=manager, sleep=lambda _: None).run(transaction.path)
    assert result.action == "installed"
    assert current.read_bytes() == b"new"


def test_helper_rejects_tampered_transaction_paths(tmp_path):
    state = tmp_path / "state"
    transaction = UpdateTransaction.create(
        state_dir=state,
        current_binary=tmp_path / "onesearch-agent",
        artifact=b"new",
        version="1.4.0",
    )
    payload = json.loads(transaction.path.read_text())
    payload["current_binary"] = str(tmp_path.parent / "outside")
    transaction.path.write_text(json.dumps(payload))
    with pytest.raises(UpdateError, match="transaction path"):
        UpdateHelper(service_manager=FakeServiceManager()).run(transaction.path)


class FakeServiceManager:
    def __init__(self):
        self.calls = []

    def stop(self):
        self.calls.append("stop")

    def start(self):
        self.calls.append("start")
