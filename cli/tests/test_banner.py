import io

from rich.console import Console

from onesearch.banner import build_startup_panel


def render_text(renderable):
    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=False, width=120)
    console.print(renderable)
    return buffer.getvalue()


def test_unconfigured_banner_mentions_backend_setup():
    panel = build_startup_panel(configured=False, backend_url=None)
    output = render_text(panel)
    assert "backend" in output.lower()
    assert "config set backend_url" in output.lower()


def test_healthy_banner_shows_versions():
    panel = build_startup_panel(
        configured=True,
        backend_url="http://infra-stack:8000",
        server_status="healthy",
        auth_state="logged in as admin",
        cli_version="0.11.1",
        server_version="0.12.0",
    )
    output = render_text(panel)
    assert "cli: 0.11.1" in output.lower()
    assert "server: 0.12.0" in output.lower()


def test_error_banner_shows_unreachable_message():
    panel = build_startup_panel(
        configured=True,
        backend_url="http://infra-stack:8000",
        error_message="backend unreachable",
    )
    output = render_text(panel)
    assert "backend unreachable" in output.lower()
