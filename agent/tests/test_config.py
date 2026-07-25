from pathlib import Path

import pytest
from onesearch_agent.config import AgentConfig, load_config
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
    with pytest.raises(ValidationError):
        load_config(config)


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
