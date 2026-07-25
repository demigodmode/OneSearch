from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner
from onesearch_agent.cli import main


def _config(path: Path, root: Path):
    root_text = str(root).replace("\\", "\\\\")
    path.write_text(
        f'server_url = "http://host"\nallowed_roots = [{{root_id="r", path="{root_text}"}}]\n'
    )


def test_cli_help_has_no_secret_options():
    result = CliRunner().invoke(main, ["enroll", "--help"])
    assert result.exit_code == 0
    assert "--code" not in result.output and "--token" not in result.output


def test_config_check_is_safe(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    config = tmp_path / "agent.toml"
    _config(config, root)
    result = CliRunner().invoke(main, ["--config", str(config), "config", "check"])
    assert result.exit_code == 0 and str(root) not in result.output


def test_top_level_help_exposes_planned_commands():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert all(command in result.output for command in ["enroll", "run", "config", "service"])


def test_enroll_uses_hidden_prompt_and_never_echoes_secret(tmp_path: Path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    config = tmp_path / "agent.toml"
    _config(config, root)
    saved = []

    class Store:
        def save(self, token):
            saved.append(token)

    class Client:
        def __init__(self, *args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def enroll(self, code, value):
            assert code == "one-time-code" and value.allowed_roots[0].root_id == "r"
            return SimpleNamespace(agent_token="permanent-secret")

    monkeypatch.setattr("onesearch_agent.cli.credential_store", lambda config: Store())
    monkeypatch.setattr("onesearch_agent.cli.AgentClient", Client)
    result = CliRunner().invoke(
        main,
        ["--config", str(config), "enroll", "--server", "http://host"],
        input="one-time-code\n",
    )
    assert result.exit_code == 0 and saved == ["permanent-secret"]
    assert "one-time-code" not in result.output and "permanent-secret" not in result.output


def test_service_cli_delegates_and_propagates_safe_error(tmp_path: Path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    config = tmp_path / "agent.toml"
    _config(config, root)
    calls = []
    monkeypatch.setattr(
        "onesearch_agent.cli.install", lambda path, executable: calls.append((path, executable))
    )
    result = CliRunner().invoke(main, ["--config", str(config), "service", "install"])
    assert result.exit_code == 0 and calls[0][1].endswith("python.exe")
