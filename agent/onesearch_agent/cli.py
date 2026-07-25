"""Console commands for configuration, enrollment, and the heartbeat shell."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click

from .client import AgentClient, AgentDisabled, AgentIncompatible, AgentRevoked
from .config import config_path, load_config
from .credentials import (
    CredentialError,
    FileCredentialStore,
    KeyringCredentialStore,
    credential_store,
)
from .runtime import run_runtime
from .service import ServiceError, install, uninstall


def _config(ctx):
    return load_config(ctx.obj["config"])


@click.group()
@click.option("--config", type=click.Path(path_type=Path), default=None)
@click.pass_context
def main(ctx, config):
    """OneSearch remote agent."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = config


@main.command()
@click.option("--server", required=True)
@click.pass_context
def enroll(ctx, server):
    """Enroll this machine."""
    current = _config(ctx)
    config = current.__class__.model_validate({**current.model_dump(), "server_url": server})
    if config.server_url != current.server_url:
        raise click.ClickException("enrollment server must match configured server")
    store = credential_store(config)
    try:
        if store.load(optional=True) is not None:
            raise click.ClickException("a credential already exists")
    except (AttributeError, TypeError) as error:
        if getattr(store, "path", None) and store.path.exists():
            raise click.ClickException("a credential already exists") from error
    code = click.prompt("Enrollment code", hide_input=True)

    async def go():
        async with AgentClient(config.server_url) as client:
            return await client.enroll(code, config)

    try:
        response = asyncio.run(go())
        store.save(response.agent_token)
        try:
            FileCredentialStore(config.state_dir).save_backend_marker(
                "keyring" if isinstance(store, KeyringCredentialStore) else "file"
            )
        except CredentialError as error:
            try:
                store.delete()
            except CredentialError:
                raise click.ClickException("enrollment needs credential recovery") from error
            raise click.ClickException("enrollment could not persist credential backend") from error
    except Exception as error:
        raise click.ClickException("enrollment failed") from error
    click.echo("Enrollment submitted; admin approval is pending.")


@main.group()
def config():
    """Inspect agent configuration."""


@config.command("check")
@click.pass_context
def config_check(ctx):
    value = _config(ctx)
    click.echo(
        f"server={value.server_url}\nagent={value.agent_name}\nroots={len(value.allowed_roots)}\ncredential={value.credential_store}"
    )


@main.command()
@click.pass_context
def run(ctx):
    """Run the heartbeat shell; no jobs are claimed before a worker is supplied."""
    value = _config(ctx)
    token = credential_store(value).load()

    async def loop():
        async with AgentClient(value.server_url, token) as client:
            await run_runtime(client)

    try:
        asyncio.run(loop())
    except KeyboardInterrupt:
        pass
    except CredentialError as error:
        raise click.ClickException(str(error)) from error
    except (AgentRevoked, AgentIncompatible, AgentDisabled) as error:
        raise click.ClickException(str(error)) from error


@main.group()
def service():
    """Install or remove an operating-system service."""


@service.command("install")
@click.pass_context
def service_install(ctx):
    try:
        install(config_path(str(ctx.obj["config"]) if ctx.obj["config"] else None), sys.executable)
    except ServiceError as error:
        raise click.ClickException(str(error)) from error


@service.command("uninstall")
def service_uninstall():
    try:
        uninstall()
    except ServiceError as error:
        raise click.ClickException(str(error)) from error


if __name__ == "__main__":  # pragma: no cover
    main()
