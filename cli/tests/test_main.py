from click.testing import CliRunner

from onesearch.api import APIError
from onesearch.context import Context
from onesearch.main import cli


def test_cli_group_exists():
    assert cli.name == "cli" or cli is not None


def test_no_args_shows_startup_panel():
    runner = CliRunner()
    result = runner.invoke(cli, [])
    assert result.exit_code == 0
    assert "OneSearch" in result.output


def test_no_args_with_explicit_url_does_not_show_unconfigured(monkeypatch):
    monkeypatch.setattr("onesearch.main._render_startup_panel", lambda ctx: print(f"startup:{ctx.url}"))
    runner = CliRunner()
    result = runner.invoke(cli, ["--url", "http://testserver"], obj=Context())
    assert result.exit_code == 0
    assert "startup:http://testserver" in result.output


def test_no_args_with_degraded_backend_shows_degraded_status(monkeypatch):
    class FakeAPI:
        def health(self, allow_degraded=False):
            assert allow_degraded is True
            return {"status": "degraded", "version": "0.12.0"}

        def whoami(self):
            raise APIError("Not authenticated", status_code=401)

    monkeypatch.setattr("onesearch.main._has_configured_backend", lambda resolved_url=None: True)
    monkeypatch.setattr(Context, "get_api", lambda self: FakeAPI())

    runner = CliRunner()
    result = runner.invoke(cli, ["--url", "http://testserver"], obj=Context())
    assert result.exit_code == 0
    assert "Status: degraded" in result.output
    assert "Error:" not in result.output
