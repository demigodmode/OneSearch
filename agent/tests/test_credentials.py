from pathlib import Path

import pytest
from onesearch_agent.credentials import CredentialError, FileCredentialStore


def test_file_store_rejects_blank_token_and_never_puts_token_in_error(tmp_path: Path):
    store = FileCredentialStore(tmp_path / "state")
    with pytest.raises(CredentialError) as error:
        store.save("   ")
    assert "   " not in str(error.value)


@pytest.mark.skipif(__import__("os").name == "nt", reason="POSIX modes")
def test_file_store_rejects_permissive_token_file(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    token = state / "credential"
    token.write_text("secret")
    token.chmod(0o644)
    with pytest.raises(CredentialError):
        FileCredentialStore(state).load()
