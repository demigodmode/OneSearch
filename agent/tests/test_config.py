import os
from pathlib import Path

import pytest
from onesearch_agent.config import AgentConfig, ConfigError, load_config
from pydantic import ValidationError


def test_config_rejects_missing_url_and_empty_or_relative_roots(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ValidationError):
        AgentConfig(allowed_roots=[])
    with pytest.raises(ValidationError):
        AgentConfig(server_url="https://host", allowed_roots=[{"root_id": "r", "path": "relative"}])
    with pytest.raises(ValidationError):
        AgentConfig(
            server_url="https://user:pass@host", allowed_roots=[{"root_id": "r", "path": str(root)}]
        )


def test_config_preserves_advertised_path_and_rejects_unknown_toml(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    config = tmp_path / "agent.toml"
    root_text = str(root).replace("\\", "\\\\")
    config.write_text(
        f'server_url = "http://example.test/"\nallowed_roots = [{{root_id = "docs", path = "{root_text}"}}]\nunknown = 1\n'
    )
    with pytest.raises(ConfigError, match="unknown: Extra inputs are not permitted"):
        load_config(config)


def _roots_error(roots) -> str:
    with pytest.raises(ValidationError) as error:
        AgentConfig(server_url="http://host", allowed_roots=roots)
    return str(error.value)


def test_config_reports_every_bad_root_by_id(tmp_path: Path):
    good = tmp_path / "good"
    good.mkdir()
    a_file = tmp_path / "file.txt"
    a_file.write_text("x")
    message = _roots_error([
        {"root_id": "good", "path": str(good)},
        {"root_id": "gone", "path": str(tmp_path / "gone")},
        {"root_id": "file", "path": str(a_file)},
        {"root_id": "rel", "path": "relative/path"},
        {"root_id": "good", "path": str(good)},
    ])

    assert "root 'gone'" in message and "does not exist" in message
    assert "root 'file'" in message and "not a directory" in message
    assert "root 'rel'" in message and "must be absolute" in message
    assert "root 'good': root_id is used more than once" in message


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0, reason="root reads everything")
def test_config_reports_a_root_this_user_cannot_read(tmp_path: Path):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        assert "not readable by this user" in _roots_error([{"root_id": "locked", "path": str(locked)}])
    finally:
        locked.chmod(0o755)


def test_config_errors_do_not_echo_the_whole_config(tmp_path: Path):
    config = tmp_path / "agent.toml"
    config.write_text(
        'server_url = "https://user:secret@host"\nallowed_roots = [{root_id = "r", path = "/nope"}]\n'
    )
    with pytest.raises(ConfigError) as error:
        load_config(config)

    assert "secret" not in str(error.value)
    assert "server_url:" in str(error.value)


def test_missing_config_file_says_which_file(tmp_path: Path):
    with pytest.raises(ConfigError, match="unable to read agent configuration"):
        load_config(tmp_path / "missing.toml")


@pytest.mark.parametrize("url", ["ftp://host", "https://host/?q=1", "https://host/#x"])
def test_config_rejects_unsafe_urls(tmp_path: Path, url: str):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ValidationError):
        AgentConfig(server_url=url, allowed_roots=[{"root_id": "r", "path": str(root)}])


def test_config_strips_trailing_slash_and_has_no_secret_field(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    value = AgentConfig(
        server_url="http://host/", allowed_roots=[{"root_id": "r", "path": str(root)}]
    )
    assert value.server_url == "http://host"
    assert "token" not in repr(value).lower()
