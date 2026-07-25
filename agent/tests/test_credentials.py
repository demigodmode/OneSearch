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


@pytest.mark.skipif(__import__("os").name == "nt", reason="POSIX modes")
def test_file_store_rejects_permissive_token_file(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    token = state / "credential"
    token.write_text("secret")
    token.chmod(0o644)
    with pytest.raises(CredentialError):
        FileCredentialStore(state).load()
