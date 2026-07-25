from pathlib import Path

import pytest
from onesearch_agent.credentials import (
    CredentialError,
    FileCredentialStore,
    KeyringCredentialStore,
    credential_store,
)


def test_file_store_rejects_blank_token_and_never_puts_token_in_error(tmp_path: Path):
    store = FileCredentialStore(tmp_path / "state")
    with pytest.raises(CredentialError) as error:
        store.save("   ")
    assert "   " not in str(error.value)


def test_file_store_never_overwrites(tmp_path: Path):
    store = FileCredentialStore(tmp_path / "state")
    store.save("one")
    with pytest.raises(CredentialError):
        store.save("two")
    assert store.load() == "one"


def test_windows_auto_selects_keyring(tmp_path: Path):
    config = type(
        "Config",
        (),
        {
            "credential_store": "auto",
            "server_url": "https://host",
            "agent_name": "a",
            "state_dir": tmp_path,
        },
    )()
    assert isinstance(credential_store(config, system="nt"), KeyringCredentialStore)


def test_docker_forces_file_store(tmp_path: Path):
    config = type(
        "Config",
        (),
        {
            "credential_store": "keyring",
            "server_url": "https://host",
            "agent_name": "a",
            "state_dir": tmp_path,
        },
    )()
    assert isinstance(credential_store(config, docker=True), FileCredentialStore)


def test_keyring_name_is_server_scoped():
    assert (
        KeyringCredentialStore("https://one.test", "agent").service
        != KeyringCredentialStore("https://two.test", "agent").service
    )


def test_linux_auto_falls_back_to_file_when_keyring_errors(tmp_path: Path, monkeypatch):
    config = type(
        "Config",
        (),
        {
            "credential_store": "auto",
            "server_url": "https://host",
            "agent_name": "a",
            "state_dir": tmp_path,
        },
    )()
    monkeypatch.setattr(
        KeyringCredentialStore,
        "load",
        lambda self, optional=False: (_ for _ in ()).throw(CredentialError("unavailable")),
    )
    assert isinstance(credential_store(config, system="posix"), FileCredentialStore)


def test_linux_auto_prefers_usable_keyring(tmp_path: Path, monkeypatch):
    config = type(
        "Config",
        (),
        {
            "credential_store": "auto",
            "server_url": "https://host",
            "agent_name": "a",
            "state_dir": tmp_path,
        },
    )()
    monkeypatch.setattr(KeyringCredentialStore, "load", lambda self, optional=False: "present")
    assert isinstance(credential_store(config, system="posix"), KeyringCredentialStore)


def test_windows_auto_never_selects_file_after_keyring_error(tmp_path: Path, monkeypatch):
    config = type(
        "Config",
        (),
        {
            "credential_store": "auto",
            "server_url": "https://host",
            "agent_name": "a",
            "state_dir": tmp_path,
        },
    )()
    monkeypatch.setattr(
        KeyringCredentialStore,
        "load",
        lambda self, optional=False: (_ for _ in ()).throw(CredentialError("no keyring")),
    )
    assert isinstance(credential_store(config, system="nt"), KeyringCredentialStore)


def test_posix_security_checks_reject_symlink_owner_and_mode(tmp_path: Path, monkeypatch):
    store = FileCredentialStore(tmp_path / "state")
    store.state_dir.mkdir()
    store.path.write_text("secret")
    monkeypatch.setattr("onesearch_agent.credentials._is_posix", lambda: True)
    monkeypatch.setattr("onesearch_agent.credentials.os.getuid", lambda: 100)

    class Stat:
        st_mode = 0o100600
        st_uid = 200

    monkeypatch.setattr(Path, "stat", lambda self: Stat())
    monkeypatch.setattr(Path, "is_symlink", lambda self: False)
    with pytest.raises(CredentialError):
        store.load()


def test_posix_secure_write_sets_directory_and_file_modes(tmp_path: Path, monkeypatch):
    store = FileCredentialStore(tmp_path / "state")
    modes = []
    monkeypatch.setattr("onesearch_agent.credentials._is_posix", lambda: True)
    monkeypatch.setattr("onesearch_agent.credentials.os.getuid", lambda: 100)
    original_chmod = Path.chmod
    monkeypatch.setattr(
        Path, "chmod", lambda self, mode: (modes.append(mode), original_chmod(self, mode))[1]
    )
    store.save("secret")
    assert 0o700 in modes and __import__("stat").S_IMODE(store.path.stat().st_mode) == 0o600


@pytest.mark.skipif(__import__("os").name == "nt", reason="POSIX modes")
def test_file_store_rejects_permissive_token_file(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    token = state / "credential"
    token.write_text("secret")
    token.chmod(0o644)
    with pytest.raises(CredentialError):
        FileCredentialStore(state).load()
