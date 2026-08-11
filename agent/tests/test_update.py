import base64
import hashlib
import io
import json
import sys
from pathlib import Path
from urllib.error import URLError

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from onesearch_agent import update as update_module
from onesearch_agent.update import MAX_ARTIFACT_BYTES, UpdateError, UpdateManager, UpdateResult
from onesearch_agent.update_runtime import native_update_layout, stage_and_launch
from onesearch_agent.updater import UpdateHelper, UpdateTransaction
from onesearch_agent.updater_cli import ServiceManager, launch
from onesearch_shared import MINIMUM_SUPPORTED_PROTOCOL_VERSION, PROTOCOL_VERSION


def test_update_reporter_checks_disabled_auto_update_without_staging(tmp_path):
    from onesearch_agent.update_report import UpdateReporter

    class Updates:
        def check(self, *, auto_update):
            assert auto_update is True
            return UpdateResult("available", "1.5.0")

    reporter = UpdateReporter(
        auto_update=False,
        platform="linux-amd64",
        version="1.4.0",
        state_dir=tmp_path,
        update_manager=Updates(),
        clock=lambda: 1_700_000_000,
    )

    assert reporter.check_if_due() is True
    assert reporter.report().model_dump() == {
        "auto_update": False,
        "runtime_kind": "native",
        "status": "available",
        "available_version": "1.5.0",
        "checked_at": 1_700_000_000,
        "error_code": None,
    }


def test_update_reporter_converts_manifest_transport_failure_to_hourly_network_retry(tmp_path):
    from onesearch_agent.update_report import UpdateReporter

    class Updates:
        def check(self, *, auto_update):
            raise URLError("connection reset")

    reporter = UpdateReporter(
        auto_update=False, platform="linux-amd64", version="1.4.0", state_dir=tmp_path,
        update_manager=Updates(), clock=lambda: 1_700_000_000,
    )

    assert reporter.check_if_due() is True
    assert reporter.report().status == "error"
    assert reporter.report().error_code == "network"
    assert reporter.check_if_due() is False


def test_update_reporter_reconciles_changed_local_auto_update_and_checks_again(tmp_path):
    from onesearch_agent.update_report import UpdateReporter

    class Updates:
        def __init__(self): self.calls = 0
        def check(self, *, auto_update):
            self.calls += 1
            return UpdateResult("current", "1.4.0")

    old_updates = Updates()
    UpdateReporter(auto_update=False, platform="linux-amd64", version="1.4.0", state_dir=tmp_path, update_manager=old_updates, clock=lambda: 1_700_000_000).check_if_due()
    updates = Updates()
    reporter = UpdateReporter(auto_update=True, platform="linux-amd64", version="1.4.0", state_dir=tmp_path, update_manager=updates, clock=lambda: 1_700_000_001)

    assert reporter.report().auto_update is True
    assert reporter.check_if_due() is True and updates.calls == 1


def test_update_reporter_marks_local_permission_failure_as_install_unavailable(tmp_path):
    from onesearch_agent.update_report import UpdateReporter

    reporter = UpdateReporter(auto_update=True, platform="linux-amd64", version="1.4.0", state_dir=tmp_path, clock=lambda: 1_700_000_000)

    reporter.record_install_error(PermissionError("state volume denied"))

    assert reporter.report().error_code == "install_unavailable"


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


class RecordingResponse:
    def __init__(
        self,
        value: bytes,
        *,
        chunk_size: int | None = None,
        on_read=None,
        fail_after: int | None = None,
    ):
        self._value = io.BytesIO(value)
        self._chunk_size = chunk_size
        self._on_read = on_read
        self._fail_after = fail_after
        self.closed = False
        self.reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True
        self._value.close()

    def read(self, size: int = -1) -> bytes:
        self.reads += 1
        if self._fail_after is not None and self.reads > self._fail_after:
            raise OSError("connection lost")
        if self._on_read:
            self._on_read()
        if self._chunk_size is not None:
            size = min(size, self._chunk_size)
        return self._value.read(size)


def production_responses(
    monkeypatch,
    manifest: dict,
    artifact: bytes,
    *,
    chunk_size=None,
    artifact_on_read=None,
    artifact_fail_after=None,
):
    manifest_response = RecordingResponse(json.dumps(manifest).encode())
    artifact_response = RecordingResponse(
        artifact,
        chunk_size=chunk_size,
        on_read=artifact_on_read,
        fail_after=artifact_fail_after,
    )
    contacts = []

    def open_url(url, *, timeout):
        contacts.append((url, timeout))
        return manifest_response if url.endswith(".json") else artifact_response

    buffered_download = update_module._download

    def manifest_only_download(url, *, maximum):
        if not url.endswith(".json"):
            raise AssertionError("production artifacts must not use the buffered downloader")
        return buffered_download(url, maximum=maximum)

    monkeypatch.setattr("onesearch_agent.update.urlopen", open_url)
    monkeypatch.setattr("onesearch_agent.update._download", manifest_only_download)
    return contacts, manifest_response, artifact_response


def test_updates_are_off_by_default_without_contacting_release_host(signing_key):
    contacts = []
    result = manager(signing_key, fetch=lambda url: contacts.append(url)).check(auto_update=False)
    assert result.action == "disabled"
    assert contacts == []


def test_production_download_streams_verified_artifact_before_publishing_transaction(
    signing_key, monkeypatch, tmp_path
):
    artifact = b"streamed-agent-binary"
    payload = signed_manifest(signing_key, artifact=artifact)
    state_dir = tmp_path / "state"
    contacts, manifest_response, artifact_response = production_responses(
        monkeypatch,
        payload,
        artifact,
        chunk_size=3,
        artifact_on_read=lambda: assert_transaction_not_published(state_dir),
    )
    current = tmp_path / "onesearch-agent.exe"
    current.write_bytes(b"old-agent")

    transaction = manager(signing_key).stage(
        auto_update=True,
        current_binary=current,
        state_dir=state_dir,
    )

    assert transaction.staged_binary.read_bytes() == artifact
    assert transaction.path.exists()
    assert contacts == [
        (
            "https://github.com/demigodmode/OneSearch/releases/latest/download/"
            "agent-manifest-win32-x64.json",
            30,
        ),
        ("https://releases.example/onesearch-agent.exe", 30),
    ]
    assert artifact_response.reads > 2
    assert manifest_response.closed
    assert artifact_response.closed


def assert_transaction_not_published(state_dir: Path) -> None:
    assert not (state_dir / "updates" / "transaction.json").exists()


@pytest.mark.parametrize(
    ("artifact", "overrides", "message"),
    [
        (b"short", {"size": 6}, "size"),
        (b"overflow", {"size": 7}, "size"),
        (b"content", {"sha256": "0" * 64}, "checksum"),
    ],
)
def test_production_stream_failure_closes_response_and_removes_partial_update(
    signing_key, monkeypatch, tmp_path, artifact, overrides, message
):
    payload = signed_manifest(signing_key, artifact=artifact, **overrides)
    _, _, artifact_response = production_responses(monkeypatch, payload, artifact, chunk_size=2)
    current = tmp_path / "onesearch-agent.exe"
    current.write_bytes(b"old-agent")
    state_dir = tmp_path / "state"

    with pytest.raises(UpdateError, match=message):
        manager(signing_key).stage(
            auto_update=True,
            current_binary=current,
            state_dir=state_dir,
        )

    assert artifact_response.closed
    assert_transaction_not_published(state_dir)
    assert list((state_dir / "updates").glob("*")) == []


def test_oversized_signed_artifact_is_rejected_before_artifact_contact(signing_key, tmp_path):
    payload = signed_manifest(signing_key, size=MAX_ARTIFACT_BYTES + 1)
    contacts = []
    current = tmp_path / "onesearch-agent.exe"
    current.write_bytes(b"old-agent")

    with pytest.raises(UpdateError, match="size"):
        manager(
            signing_key,
            fetch=lambda url: contacts.append(url) or payload,
        ).stage(
            auto_update=True,
            current_binary=current,
            state_dir=tmp_path / "state",
        )

    assert len(contacts) == 1


def test_production_stream_read_failure_closes_response_and_removes_partial_update(
    signing_key, monkeypatch, tmp_path
):
    artifact = b"partial-download"
    payload = signed_manifest(signing_key, artifact=artifact)
    _, _, artifact_response = production_responses(
        monkeypatch,
        payload,
        artifact,
        chunk_size=2,
        artifact_fail_after=2,
    )
    current = tmp_path / "onesearch-agent.exe"
    current.write_bytes(b"old-agent")
    state_dir = tmp_path / "state"

    with pytest.raises(OSError, match="connection lost"):
        manager(signing_key).stage(
            auto_update=True,
            current_binary=current,
            state_dir=state_dir,
        )

    assert artifact_response.closed
    assert_transaction_not_published(state_dir)
    assert list((state_dir / "updates").glob("*")) == []


def test_production_stream_publication_failure_removes_verified_staged_file(
    signing_key, monkeypatch, tmp_path
):
    artifact = b"verified-download"
    payload = signed_manifest(signing_key, artifact=artifact)
    _, _, artifact_response = production_responses(
        monkeypatch,
        payload,
        artifact,
        chunk_size=2,
    )
    current = tmp_path / "onesearch-agent.exe"
    current.write_bytes(b"old-agent")
    state_dir = tmp_path / "state"

    def fail_publication(cls, **kwargs):
        raise UpdateError("transaction publication failed")

    monkeypatch.setattr(UpdateTransaction, "_publish", classmethod(fail_publication))

    with pytest.raises(UpdateError, match="publication"):
        manager(signing_key).stage(
            auto_update=True,
            current_binary=current,
            state_dir=state_dir,
        )

    assert artifact_response.closed
    assert_transaction_not_published(state_dir)
    assert list((state_dir / "updates").glob("*")) == []


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
    downloads = []
    notices = []
    result = manager(
        signing_key,
        container=True,
        fetch=lambda url: downloads.append(url)
        or (payload if url.endswith(".json") else b"new-agent"),
        notify=notices.append,
    ).stage(auto_update=True, current_binary=current, state_dir=tmp_path / "state")
    assert result.action == "notify"
    assert any("newer agent image is available" in notice.lower() for notice in notices)
    assert len(downloads) == 1
    assert all("manifest" in url for url in downloads)
    assert current.read_bytes() == b"old-agent"


def test_stage_and_launch_forwards_docker_notice_without_launching(monkeypatch, tmp_path):
    current = tmp_path / "onesearch-agent"
    current.write_bytes(b"old-agent")
    notices = []
    manager_options = []

    class Updates:
        def __init__(self, **kwargs):
            manager_options.append(kwargs)

        def stage(self, *, auto_update, current_binary, state_dir):
            assert auto_update is True
            assert current_binary == current
            assert state_dir == tmp_path / "state"
            manager_options[-1]["notify"](
                "A newer agent image is available; Docker containers are never self-updated."
            )
            return UpdateResult("notify", "1.4.0")

    monkeypatch.setenv("DOCKER_CONTAINER", "1")
    monkeypatch.setattr("onesearch_agent.update_runtime.UpdateManager", Updates)
    monkeypatch.setattr(
        "onesearch_agent.update_runtime.launch",
        lambda path: pytest.fail(f"container update attempted to launch {path}"),
    )

    result = stage_and_launch(
        config=type("Config", (), {"auto_update": True, "state_dir": tmp_path / "state"})(),
        platform="linux-x64",
        version="1.3.0",
        current_binary=current,
        managed=False,
        notify=notices.append,
    )

    assert result == UpdateResult("notify", "1.4.0")
    assert manager_options[0]["container"] is True
    assert notices == [
        "A newer agent image is available; Docker containers are never self-updated."
    ]
    assert current.read_bytes() == b"old-agent"


def test_stage_and_launch_keeps_native_launch_behavior_with_notices(monkeypatch, tmp_path):
    suffix = ".exe" if sys.platform == "win32" else ""
    current = tmp_path / ("onesearch-agent" + suffix)
    helper = tmp_path / ("onesearch-agent-updater" + suffix)
    prepared = tmp_path / "prepared-update.json"
    current.write_bytes(b"old-agent")
    helper.write_bytes(b"updater")
    notices = []
    launched = []

    class Prepared:
        path = prepared

    class Updates:
        def __init__(self, **kwargs):
            assert kwargs["container"] is False
            self.notify = kwargs["notify"]

        def stage(self, *, auto_update, current_binary, state_dir):
            assert auto_update is True
            assert current_binary == current
            self.notify("Signed agent update 1.4.0 is ready.")
            return Prepared()

    monkeypatch.delenv("DOCKER_CONTAINER", raising=False)
    monkeypatch.setattr("onesearch_agent.update_runtime.sys.frozen", True, raising=False)
    monkeypatch.setattr("onesearch_agent.update_runtime.UpdateManager", Updates)
    monkeypatch.setattr("onesearch_agent.update_runtime.launch", launched.append)

    result = stage_and_launch(
        config=type("Config", (), {"auto_update": True, "state_dir": tmp_path / "state"})(),
        platform="win32-x64",
        version="1.3.0",
        current_binary=current,
        managed=True,
        notify=notices.append,
    )

    assert isinstance(result, Prepared)
    assert notices == ["Signed agent update 1.4.0 is ready."]
    assert launched == [prepared]


def test_source_python_cannot_begin_automatic_update_contact(monkeypatch, tmp_path):
    class Config:
        auto_update, state_dir = True, tmp_path / "state"

    monkeypatch.setattr("onesearch_agent.update_runtime.sys.frozen", False, raising=False)
    with pytest.raises(UpdateError, match="manual"):
        stage_and_launch(
            config=Config(),
            platform="linux-x64",
            version="1.3.0",
            current_binary=tmp_path / "python",
            managed=True,
        )


def test_native_update_layout_requires_fixed_frozen_siblings(monkeypatch, tmp_path):
    suffix = ".exe" if sys.platform == "win32" else ""
    agent = tmp_path / ("onesearch-agent" + suffix)
    helper = tmp_path / ("onesearch-agent-updater" + suffix)
    agent.write_bytes(b"agent")
    helper.write_bytes(b"helper")
    monkeypatch.setattr("onesearch_agent.update_runtime.sys.frozen", True, raising=False)
    assert native_update_layout(agent) == helper
    assert native_update_layout(tmp_path / "python") is None
    helper.unlink()
    assert native_update_layout(agent) is None


def test_native_update_paths_reject_a_linked_install_parent(monkeypatch, tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(actual, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlink creation is unavailable: {error}")
    suffix = ".exe" if sys.platform == "win32" else ""
    agent = actual / ("onesearch-agent" + suffix)
    helper = actual / ("onesearch-agent-updater" + suffix)
    agent.write_bytes(b"agent")
    helper.write_bytes(b"helper")
    monkeypatch.setattr("onesearch_agent.update_runtime.sys.frozen", True, raising=False)

    with pytest.raises(UpdateError, match="symlink|reparse"):
        UpdateTransaction.create(
            state_dir=tmp_path / "state",
            current_binary=linked / agent.name,
            artifact=b"new",
            version="1.4.0",
        )
    assert native_update_layout(linked / agent.name) is None


def test_helper_recovers_crash_after_backup_move_while_stopping(tmp_path):
    current = tmp_path / "onesearch-agent"
    current.write_bytes(b"old")
    transaction = UpdateTransaction.create(
        state_dir=tmp_path / "state", current_binary=current, artifact=b"new", version="1.4.0"
    ).save("stopping")
    current.replace(transaction.backup_binary)
    manager = FakeServiceManager()
    result = UpdateHelper(service_manager=manager).run(transaction.path)
    assert result.action == "rolled_back"
    assert current.read_bytes() == b"old"
    assert manager.calls == ["start"]


def test_stopping_transaction_with_current_binary_resumes_swap_safely(tmp_path):
    current = tmp_path / "onesearch-agent"
    current.write_bytes(b"old")
    transaction = UpdateTransaction.create(
        state_dir=tmp_path / "state", current_binary=current, artifact=b"new", version="1.4.0"
    ).save("stopping")
    result = UpdateHelper(service_manager=FakeServiceManager(), deadline=0).run(transaction.path)
    assert result.action == "rolled_back"
    assert current.read_bytes() == b"old"


def test_rejects_replayed_or_downgrade_release(signing_key):
    payload = signed_manifest(signing_key, version="1.2.0")
    with pytest.raises(UpdateError, match="older"):
        manager(signing_key, current_version="1.3.0", fetch=lambda url: payload).check(
            auto_update=True
        )


def test_same_version_is_already_current(signing_key):
    payload = signed_manifest(signing_key, version="1.3.0")
    result = manager(signing_key, current_version="1.3.0", fetch=lambda url: payload).check(
        auto_update=True
    )
    assert result == UpdateResult("current", "1.3.0")


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


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")
def test_staged_and_swapped_native_binary_preserves_safe_executable_mode(tmp_path):
    current = tmp_path / "onesearch-agent"
    current.write_bytes(b"old")
    current.chmod(0o6755)
    transaction = UpdateTransaction.create(
        state_dir=tmp_path / "state", current_binary=current, artifact=b"new", version="1.4.0"
    )
    assert transaction.staged_binary.stat().st_mode & 0o7777 == 0o755
    (tmp_path / "state" / "healthy.json").write_text(
        json.dumps({"version": "1.4.0", "timestamp": transaction.started_at + 1})
    )
    UpdateHelper(service_manager=FakeServiceManager(), sleep=lambda _: None).run(transaction.path)
    assert current.stat().st_mode & 0o7777 == 0o755


def test_helper_rejects_tampered_transaction_paths(tmp_path):
    state = tmp_path / "state"
    (tmp_path / "onesearch-agent").write_bytes(b"old")
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
        UpdateHelper(service_manager=FakeServiceManager()).run(
            transaction.path, expected_current_binary=tmp_path / "onesearch-agent"
        )


def test_helper_started_transaction_never_replaces_last_good_backup(tmp_path):
    current = tmp_path / "onesearch-agent"
    current.write_bytes(b"old")
    state = tmp_path / "state"
    transaction = UpdateTransaction.create(
        state_dir=state, current_binary=current, artifact=b"new", version="1.4.0"
    )
    transaction = transaction.save("started")
    transaction.backup_binary.write_bytes(b"old")
    current.write_bytes(b"new")
    result = UpdateHelper(service_manager=FakeServiceManager(), deadline=0).run(transaction.path)
    assert result.action == "rolled_back"
    assert current.read_bytes() == b"old"


class FakeServiceManager:
    def __init__(self):
        self.calls = []

    def stop(self):
        self.calls.append("stop")

    def start(self):
        self.calls.append("start")

    def is_managed(self):
        return True


def test_transaction_refuses_paths_outside_fixed_sibling_layout(tmp_path):
    current = tmp_path / "onesearch-agent"
    current.write_bytes(b"old")
    transaction = UpdateTransaction.create(
        state_dir=tmp_path / "state", current_binary=current, artifact=b"new", version="1.4.0"
    )
    payload = json.loads(transaction.path.read_text())
    payload["current_binary"] = str(tmp_path / "other" / "onesearch-agent")
    payload["backup_binary"] = str(tmp_path / "other" / "onesearch-agent.previous")
    transaction.path.write_text(json.dumps(payload))
    with pytest.raises(UpdateError, match="expected"):
        UpdateTransaction.load(transaction.path, expected_current_binary=current)


def test_transaction_refuses_symlinked_state_ancestry(tmp_path):
    current = tmp_path / "onesearch-agent"
    current.write_bytes(b"old")
    UpdateTransaction.create(
        state_dir=tmp_path / "state", current_binary=current, artifact=b"new", version="1.4.0"
    )
    actual = tmp_path / "actual-state"
    (tmp_path / "state").replace(actual)
    try:
        (tmp_path / "state").symlink_to(actual, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(UpdateError, match="symlink"):
        UpdateTransaction.load(tmp_path / "state" / "updates" / "transaction.json")


def test_linux_transient_helper_is_collected_and_collision_safe(tmp_path):
    calls = []

    class Process:
        def poll(self):
            return None

    transaction = tmp_path / "transaction.json"
    helper = tmp_path / "onesearch-agent-updater"
    helper.write_bytes(b"helper")
    result = launch(
        transaction,
        platform="linux",
        run=lambda args, **kwargs: calls.append((args, kwargs)) or Process(),
        helper=helper,
        pid=123,
        token="safe",
    )
    assert result.poll() is None
    args, kwargs = calls[0]
    assert args[:5] == [
        "systemd-run",
        "--user",
        "--collect",
        "--property=Type=exec",
        "--unit=onesearch-agent-updater-123-safe",
    ]
    assert args[-3:] == [str(helper), "--transaction", str(transaction)] and kwargs == {}


def test_linux_transient_helper_rejects_immediate_failure(tmp_path):
    helper = tmp_path / "onesearch-agent-updater"
    helper.write_bytes(b"helper")
    with pytest.raises(RuntimeError, match="failed"):
        launch(
            tmp_path / "t",
            platform="linux",
            helper=helper,
            run=lambda *_a, **_k: type("P", (), {"poll": lambda self: 1})(),
        )


@pytest.mark.parametrize("method,code", [("stop", 1062), ("start", 1056)])
def test_service_manager_accepts_only_benign_already_state(method, code):
    seen = []
    service = ServiceManager(
        platform="win32",
        runner=lambda args: seen.append(args) or (0 if args[1] == "query" else code),
    )
    getattr(service, method)()
    assert seen


@pytest.mark.parametrize("method", ["stop", "start"])
def test_service_manager_rejects_absent_windows_service(method):
    service = ServiceManager(platform="win32", runner=lambda args: 1060)
    with pytest.raises(RuntimeError, match="not installed"):
        getattr(service, method)()
