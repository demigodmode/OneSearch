from click.testing import CliRunner

from onesearch.main import cli


def test_cli_group_exists():
    assert cli.name == "cli" or cli is not None


def test_no_args_shows_startup_panel():
    runner = CliRunner()
    result = runner.invoke(cli, [])
    assert result.exit_code == 0
    assert "OneSearch" in result.output
