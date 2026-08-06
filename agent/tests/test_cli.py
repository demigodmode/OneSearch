from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner
from onesearch_agent.cli import main
from onesearch_agent.client import (
    AgentAmbiguousResultError,
    AgentDisabled,
    AgentIncompatible,
    AgentRevoked,
)
from onesearch_agent.credentials import CredentialError


def _config(path: Path, root: Path):
    root_text = str(root).replace("\\", "\\\\")
    state_text = str(path.parent / "state").replace("\\", "\\\\")
    path.write_text(
        f'server_url = "http://host"\nstate_dir = "{state_text}"\nallowed_roots = [{{root_id="r", path="{root_text}"}}]\n'
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
    assert all(
        command in result.output for command in ["enroll", "run", "config", "service", "update"]
    )


def test_manual_update_check_discloses_and_checks_even_when_auto_update_is_off(
    tmp_path: Path, monkeypatch
):
    root = tmp_path / "root"
    root.mkdir()
    config = tmp_path / "agent.toml"
    _config(config, root)
    seen = []

    class Updates:
        def __init__(self, **kwargs):
            seen.append(kwargs)

        def check(self, *, auto_update):
            assert auto_update is True
            return SimpleNamespace(action="available", version="1.4.0")

    monkeypatch.setattr("onesearch_agent.cli.UpdateManager", Updates)
    result = CliRunner().invoke(main, ["--config", str(config), "update", "check"])
    assert result.exit_code == 0 and "1.4.0" in result.output and seen


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


def test_enroll_honors_file_credential_policy(tmp_path: Path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    config = tmp_path / "agent.toml"
    _config(config, root)
    seen = []

    class Store:
        def load(self, optional=False):
            return None

        def save(self, token):
            seen.append(token)

    class Client:
        def __init__(self, *args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def enroll(self, code, value):
            return SimpleNamespace(agent_token="secret")

    monkeypatch.setenv("ONESEARCH_AGENT_CREDENTIAL_STORE", "file")
    monkeypatch.setattr("onesearch_agent.cli.credential_store", lambda value: Store())
    monkeypatch.setattr("onesearch_agent.cli.AgentClient", Client)
    result = CliRunner().invoke(
        main, ["--config", str(config), "enroll", "--server", "http://host"], input="code\n"
    )
    assert result.exit_code == 0 and seen == ["secret"] and "secret" not in result.output


def test_enroll_rejects_mismatched_server_before_prompt(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    config = tmp_path / "agent.toml"
    _config(config, root)
    result = CliRunner().invoke(
        main, ["--config", str(config), "enroll", "--server", "https://other"]
    )
    assert result.exit_code != 0 and "match configured" in result.output


def test_enroll_save_failure_revokes_without_echoing_secrets(tmp_path: Path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    config = tmp_path / "agent.toml"
    _config(config, root)
    calls = []

    class Store:
        def load(self, optional=False):
            return None

        def save(self, token):
            raise OSError("disk")

    class Client:
        def __init__(self, *args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def enroll(self, code, value):
            return SimpleNamespace(agent_token="token-secret", agent_id="agent-1")

        async def revoke_self(self):
            calls.append("revoke")

    monkeypatch.setattr("onesearch_agent.cli.credential_store", lambda value: Store())
    monkeypatch.setattr("onesearch_agent.cli.AgentClient", Client)
    result = CliRunner().invoke(
        main, ["--config", str(config), "enroll", "--server", "http://host"], input="code-secret\n"
    )
    assert calls == ["revoke"] and "new code" in result.output
    assert "token-secret" not in result.output and "code-secret" not in result.output


def test_enroll_save_failure_revoke_ambiguity_gives_admin_guidance(tmp_path: Path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    config = tmp_path / "agent.toml"
    _config(config, root)
    calls = []

    class Store:
        def load(self, optional=False):
            return None

        def save(self, token):
            raise OSError("disk")

    class Client:
        def __init__(self, *args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def enroll(self, code, value):
            return SimpleNamespace(agent_token="token-secret", agent_id="agent-1")

        async def revoke_self(self):
            calls.append("revoke")
            raise AgentAmbiguousResultError("unknown")

    monkeypatch.setattr("onesearch_agent.cli.credential_store", lambda value: Store())
    monkeypatch.setattr("onesearch_agent.cli.AgentClient", Client)
    result = CliRunner().invoke(
        main, ["--config", str(config), "enroll", "--server", "http://host"], input="code-secret\n"
    )
    assert calls == ["revoke"] and "agent-1" in result.output and "admin" in result.output
    assert "token-secret" not in result.output and "code-secret" not in result.output


def test_run_preserves_terminal_agent_error(tmp_path: Path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    config = tmp_path / "agent.toml"
    _config(config, root)
    monkeypatch.setattr(
        "onesearch_agent.cli.credential_store", lambda value: SimpleNamespace(load=lambda: "token")
    )

    async def fail(client, *, worker, **kwargs):
        assert worker is not None
        raise AgentRevoked("agent revoked")

    monkeypatch.setattr("onesearch_agent.cli.run_runtime", fail)
    result = CliRunner().invoke(main, ["--config", str(config), "run"])
    assert "agent revoked" in result.output and "configuration unavailable" not in result.output


def test_run_prints_docker_auto_update_notice(monkeypatch, tmp_path):
    value = SimpleNamespace(auto_update=True, state_dir=tmp_path / "state")

    def stage(*, notify, **kwargs):
        assert kwargs["managed"] is False
        notify("A newer agent image is available; Docker containers are never self-updated.")

    def missing_token():
        raise CredentialError("credential is unavailable")

    monkeypatch.setenv("DOCKER_CONTAINER", "1")
    monkeypatch.setattr("onesearch_agent.cli._config", lambda ctx: value)
    monkeypatch.setattr("onesearch_agent.cli._linux_systemd_managed", lambda: False)
    monkeypatch.setattr("onesearch_agent.cli.stage_and_launch", stage)
    monkeypatch.setattr(
        "onesearch_agent.cli.credential_store",
        lambda config: SimpleNamespace(load=missing_token),
    )

    result = CliRunner().invoke(main, ["run"])

    assert result.exit_code != 0
    assert "A newer agent image is available" in result.output
    assert "never self-updated" in result.output
    assert "credential is unavailable" in result.output


@pytest.mark.parametrize("error", [AgentDisabled("disabled"), AgentIncompatible("incompatible")])
def test_run_preserves_other_terminal_agent_errors(tmp_path: Path, monkeypatch, error):
    root = tmp_path / "root"
    root.mkdir()
    config = tmp_path / "agent.toml"
    _config(config, root)
    monkeypatch.setattr(
        "onesearch_agent.cli.credential_store", lambda value: SimpleNamespace(load=lambda: "token")
    )

    async def fail(client, *, worker, **kwargs):
        assert worker is not None
        raise error

    monkeypatch.setattr("onesearch_agent.cli.run_runtime", fail)
    result = CliRunner().invoke(main, ["--config", str(config), "run"])
    assert str(error) in result.output and "configuration unavailable" not in result.output


def test_run_malformed_config_is_safe(tmp_path: Path):
    config = tmp_path / "agent.toml"
    config.write_text("not = [valid")
    result = CliRunner().invoke(main, ["--config", str(config), "run"])
    assert "configuration is unavailable" in result.output
