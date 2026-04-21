from click.testing import CliRunner

from onesearch.main import cli


def test_login_command_exists():
    runner = CliRunner()
    result = runner.invoke(cli, ["login", "--help"])
    assert result.exit_code == 0
    assert "login" in result.output.lower()


def test_login_with_token_stores_token(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(cli, ["login", "--token"], input="abc123\n")
    assert result.exit_code == 0
    assert "stored" in result.output.lower()


def test_logout_command_exists():
    runner = CliRunner()
    result = runner.invoke(cli, ["logout", "--help"])
    assert result.exit_code == 0
    assert "logout" in result.output.lower()


def test_whoami_command_exists():
    runner = CliRunner()
    result = runner.invoke(cli, ["whoami", "--help"])
    assert result.exit_code == 0
    assert "whoami" in result.output.lower()
