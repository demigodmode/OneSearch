"""Configuration management commands."""

import click
import yaml

from onesearch.config import (
    get_config_path,
    load_config,
    get_config_value,
    set_config_value,
    delete_config_value,
    DEFAULT_CONFIG,
)
from onesearch.context import console, err_console
from onesearch.main import cli


@cli.group()
def config():
    """Manage CLI configuration.

    \b
    Configuration priority (highest to lowest):
    1. CLI flags (--url)
    2. Environment variables (ONESEARCH_URL)
    3. Config file (~/.config/onesearch/config.yml)
    4. Defaults

    \b
    Examples:
      onesearch config show
      onesearch config set backend_url http://onesearch.local:8000
      onesearch config get backend_url
    """
    pass


@config.command("show")
@click.option("--path", is_flag=True, help="Show config file path only.")
def config_show(path: bool):
    """Show current configuration."""
    config_path = get_config_path()

    if path:
        console.print(str(config_path))
        return

    console.print(f"\n[dim]Config file:[/dim] {config_path}")
    console.print(f"[dim]Exists:[/dim] {config_path.exists()}\n")

    config_data = load_config()
    if not config_data:
        console.print("[dim]No configuration set.[/dim]")
        console.print("\nCreate a config with: [cyan]onesearch config set <key> <value>[/cyan]")
        console.print("Or initialize defaults: [cyan]onesearch config init[/cyan]")
        return

    # Pretty print config
    console.print("[bold]Current Configuration:[/bold]")
    yaml_str = yaml.safe_dump(config_data, default_flow_style=False, sort_keys=False)
    for line in yaml_str.strip().split("\n"):
        if ":" in line and not line.strip().startswith("#"):
            key, _, value = line.partition(":")
            console.print(f"  [cyan]{key}[/cyan]:{value}")
        else:
            console.print(f"  {line}")


@config.command("get")
@click.argument("key")
def config_get(key: str):
    """Get a configuration value.

    \b
    Arguments:
      KEY  Configuration key (e.g., backend_url, output.colors)
    """
    value = get_config_value(key)
    if value is None:
        err_console.print(f"[yellow]Key not found:[/yellow] {key}")
        raise SystemExit(1)

    if isinstance(value, (dict, list)):
        console.print(yaml.safe_dump(value, default_flow_style=False))
    else:
        console.print(str(value))


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str):
    """Set a configuration value.

    \b
    Arguments:
      KEY    Configuration key (e.g., backend_url, output.colors)
      VALUE  Value to set

    \b
    Examples:
      onesearch config set backend_url http://onesearch.local:8000
      onesearch config set output.colors false
      onesearch config set defaults.search_limit 50
    """
    # Try to parse value as YAML for proper types
    try:
        parsed_value = yaml.safe_load(value)
    except Exception:
        parsed_value = value

    set_config_value(key, parsed_value)
    console.print(f"[green]✓[/green] Set [cyan]{key}[/cyan] = {parsed_value}")


@config.command("unset")
@click.argument("key")
def config_unset(key: str):
    """Remove a configuration value.

    \b
    Arguments:
      KEY  Configuration key to remove
    """
    if delete_config_value(key):
        console.print(f"[green]✓[/green] Removed [cyan]{key}[/cyan]")
    else:
        err_console.print(f"[yellow]Key not found:[/yellow] {key}")
        raise SystemExit(1)


@config.command("init")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing config.")
def config_init(force: bool):
    """Initialize configuration file with defaults.

    Creates a config file at ~/.config/onesearch/config.yml (Linux/Mac)
    or %APPDATA%/onesearch/config.yml (Windows).
    """
    config_path = get_config_path()

    if config_path.exists() and not force:
        console.print(f"[yellow]Config file already exists:[/yellow] {config_path}")
        console.print("\nUse [cyan]--force[/cyan] to overwrite.")
        return

    # Create config directory
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Write default config
    default_content = DEFAULT_CONFIG.format(config_path=config_path)
    with open(config_path, "w") as f:
        f.write(default_content)

    console.print(f"[green]✓[/green] Created config file: {config_path}")
    console.print("\nEdit this file or use [cyan]onesearch config set <key> <value>[/cyan]")
