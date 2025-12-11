"""OneSearch CLI entry point."""

import sys

import click

from onesearch import __version__
from onesearch.context import Context, pass_context, console, err_console

# Context settings for all commands
CONTEXT_SETTINGS = {
    "help_option_names": ["-h", "--help"],
}


def get_default_url() -> str:
    """Get the default backend URL from config/env/default."""
    from onesearch.config import get_backend_url
    return get_backend_url()


@click.group(context_settings=CONTEXT_SETTINGS)
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
@pass_context
def cli(ctx: Context, url: str, verbose: bool):
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
    ctx.url = url
    ctx.verbose = verbose


# Import and register command groups after cli is defined
from onesearch.commands import source, search, status, config  # noqa: E402, F401


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
