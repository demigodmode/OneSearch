"""Console commands for configuration, enrollment, and the heartbeat shell."""

from __future__ import annotations

import asyncio
import platform
from pathlib import Path

import click

from . import __version__
from .client import AgentClient, AgentIncompatible, AgentPending, AgentRevoked
from .config import load_config
from .credentials import CredentialError, FileCredentialStore


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
    config = _config(ctx).model_copy(update={"server_url": server})
    store = FileCredentialStore(config.state_dir)
    if store.path.exists():
        raise click.ClickException("a credential already exists")
    code = click.prompt("Enrollment code", hide_input=True)

    async def go():
        async with AgentClient(config.server_url) as client:
            return await client.enroll(code, config)

    try:
        response = asyncio.run(go())
        store.save(response.agent_token)
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
    token = FileCredentialStore(value.state_dir).load()

    async def loop():
        async with AgentClient(value.server_url, token) as client:
            while True:
                try:
                    await client.heartbeat(__version__, platform.platform())
                except AgentPending:
                    pass
                except (AgentRevoked, AgentIncompatible):
                    raise
                await asyncio.sleep(30)

    try:
        asyncio.run(loop())
    except KeyboardInterrupt:
        pass
    except CredentialError as error:
        raise click.ClickException(str(error)) from error
    except (AgentRevoked, AgentIncompatible) as error:
        raise click.ClickException(str(error)) from error


@main.group()
def service():
    """Install or remove an operating-system service."""


@service.command("install")
def service_install():
    raise click.ClickException("service installation is unavailable in this runtime")


@service.command("uninstall")
def service_uninstall():
    raise click.ClickException("service installation is unavailable in this runtime")
