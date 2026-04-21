# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Authentication commands."""

import click

from onesearch.api import APIError
from onesearch.config import delete_config_value, set_config_value
from onesearch.context import Context, console, err_console, pass_context
from onesearch.main import cli


@cli.command()
@click.option("--token", "use_token", is_flag=True, help="Prompt for a bearer token instead of username/password.")
@pass_context
def login(ctx: Context, use_token: bool):
    """Authenticate and store a CLI token."""
    if use_token:
        token = click.prompt("Token", hide_input=False)
        set_config_value("auth.token", token)
        ctx.reset_api()
        console.print("[green]✓[/green] Token stored for OneSearch CLI")
        return

    username = click.prompt("Username")
    password = click.prompt("Password", hide_input=True)

    api = ctx.get_api()
    try:
        result = api.login(username, password)
        token = result.get("access_token")
        if not token:
            raise click.ClickException("Login succeeded but no access token was returned.")

        set_config_value("auth.token", token)
        ctx.reset_api()
        console.print(f"[green]✓[/green] Logged in as [cyan]{username}[/cyan]")
    except APIError as e:
        err_console.print(f"[red]Error:[/red] {e.message}")
        raise SystemExit(1) from e


@cli.command()
@pass_context
def logout(ctx: Context):
    """Remove the stored CLI token."""
    delete_config_value("auth.token")
    ctx.reset_api()
    console.print("[green]✓[/green] Logged out")


@cli.command()
@pass_context
def whoami(ctx: Context):
    """Show the current authenticated user."""
    api = ctx.get_api()
    try:
        user = api.whoami()
        console.print(f"Logged in as [cyan]{user.get('username', 'unknown')}[/cyan]")
        console.print(f"Backend: [dim]{ctx.url}[/dim]")
    except APIError as e:
        err_console.print(f"[red]Error:[/red] {e.message}")
        raise SystemExit(1) from e
