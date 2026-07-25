from pathlib import Path

from click.testing import CliRunner

from onesearch_agent.cli import main


def _config(path: Path, root: Path):
    path.write_text(
        f'server_url = "http://host"\nallowed_roots = [{{root_id="r", path="{str(root).replace("\\", "\\\\")}"}}]\n'
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
