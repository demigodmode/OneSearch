# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""OneSearch CLI entry point."""

import os
import sys

import click

from onesearch import __version__
from onesearch.api import APIError
from onesearch.banner import build_startup_panel
from onesearch.config import load_config
from onesearch.context import Context, console, err_console

# Context settings for all commands
CONTEXT_SETTINGS = {
    "help_option_names": ["-h", "--help"],
}


def get_default_url() -> str:
    """Get the default backend URL from config/env/default."""
    from onesearch.config import get_backend_url
    return get_backend_url()


def _has_configured_backend(resolved_url: str | None = None) -> bool:
    config_data = load_config()
    return bool(resolved_url or os.environ.get("ONESEARCH_URL") or config_data.get("backend_url"))


def _render_startup_panel(ctx: Context) -> None:
    configured = _has_configured_backend(ctx.url)
    if not configured:
        console.print(
            build_startup_panel(
                configured=False,
                backend_url=None,
                cli_version=__version__,
            )
        )
        return

    api = ctx.get_api()
    try:
        health = api.health(allow_degraded=True)
        server_version = health.get("version")
        server_status = health.get("status", "unknown")
        auth_state = "not logged in"

        try:
            user = api.whoami()
            auth_state = f"logged in as {user.get('username', 'unknown')}"
        except APIError as auth_error:
            if auth_error.status_code not in (401, 403):
                console.print(
                    build_startup_panel(
                        configured=True,
                        backend_url=ctx.url,
                        cli_version=__version__,
                        server_version=server_version,
                        server_status=server_status,
                        error_message=auth_error.message,
                    )
                )
                return

        console.print(
            build_startup_panel(
                configured=True,
                backend_url=ctx.url,
                cli_version=__version__,
                server_version=server_version,
                server_status=server_status,
                auth_state=auth_state,
            )
        )
    except APIError as e:
        console.print(
            build_startup_panel(
                configured=True,
                backend_url=ctx.url,
                cli_version=__version__,
                error_message=e.message,
            )
        )


@click.group(context_settings=CONTEXT_SETTINGS, invoke_without_command=True)
@click.version_option(version=__version__, prog_name="onesearch")
@click.option(
    "--url",
    envvar="ONESEARCH_URL",
    default=get_default_url,
    help="Backend API URL.",
    show_default=True,
)
@click.option(
    "-v", "--verbose",
    is_flag=True,
    help="Enable verbose output.",
)
@click.option(
    "-q", "--quiet",
    is_flag=True,
    help="Suppress non-essential output. Only show results/errors.",
)
@click.pass_context
def cli(click_ctx: click.Context, url: str, verbose: bool, quiet: bool):
    """OneSearch - Self-hosted, privacy-focused search for your homelab.

    Search across all your files, documents, and notes from a single,
    unified command-line interface.

    \b
    Examples:
      onesearch search "kubernetes deployment"
      onesearch source list
      onesearch status
      onesearch health

    Use 'onesearch COMMAND --help' for more information on a command.
    """
    ctx = click_ctx.ensure_object(Context)
    ctx.url = url
    ctx.verbose = verbose
    ctx.quiet = quiet

    if click_ctx.invoked_subcommand is None:
        _render_startup_panel(ctx)


# Import and register command groups after cli is defined
from onesearch.commands import auth, config, search, source, status  # noqa: E402, F401


def main():
    """Main entry point."""
    try:
        cli()
    except KeyboardInterrupt:
        err_console.print("\n[yellow]Aborted.[/yellow]")
        sys.exit(130)
    except Exception as e:
        # Show concise error; users can use -v for more details
        err_console.print(f"[red]Error:[/red] {type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
