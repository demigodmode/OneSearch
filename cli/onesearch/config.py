# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Configuration management for OneSearch CLI."""

import os
from pathlib import Path
from typing import Any

import yaml


def get_config_dir() -> Path:
    """Get the configuration directory path."""
    # Use XDG_CONFIG_HOME on Linux, or appropriate dir on Windows/Mac
    if os.name == "nt":  # Windows
        config_base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:  # Linux/Mac
        config_base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_base / "onesearch"


def get_config_path() -> Path:
    """Get the configuration file path."""
    return get_config_dir() / "config.yml"


def load_config() -> dict:
    """Load configuration from file.

    Returns:
        Configuration dictionary, or empty dict if file doesn't exist.
    """
    config_path = get_config_path()
    if not config_path.exists():
        return {}

    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f) or {}
            return config
    except Exception:
        return {}


def save_config(config: dict) -> None:
    """Save configuration to file.

    Args:
        config: Configuration dictionary to save.
    """
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)

    config_path = get_config_path()
    with open(config_path, "w") as f:
        yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)


def get_config_value(key: str, default: Any = None) -> Any:
    """Get a configuration value.

    Args:
        key: Dot-separated key path (e.g., "output.colors").
        default: Default value if key not found.

    Returns:
        Configuration value or default.
    """
    config = load_config()
    keys = key.split(".")
    value = config

    for k in keys:
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            return default

    return value


def set_config_value(key: str, value: Any) -> None:
    """Set a configuration value.

    Args:
        key: Dot-separated key path (e.g., "output.colors").
        value: Value to set.
    """
    config = load_config()
    keys = key.split(".")

    # Navigate to the parent dict
    current = config
    for k in keys[:-1]:
        if k not in current or not isinstance(current[k], dict):
            current[k] = {}
        current = current[k]

    # Set the value
    current[keys[-1]] = value
    save_config(config)


def delete_config_value(key: str) -> bool:
    """Delete a configuration value.

    Args:
        key: Dot-separated key path.

    Returns:
        True if value was deleted, False if not found.
    """
    config = load_config()
    keys = key.split(".")

    # Navigate to the parent dict
    current = config
    for k in keys[:-1]:
        if k not in current or not isinstance(current[k], dict):
            return False
        current = current[k]

    # Delete the key
    if keys[-1] in current:
        del current[keys[-1]]
        save_config(config)
        return True
    return False


def get_backend_url() -> str:
    """Get the backend URL from config/env/default.

    Priority:
    1. Environment variable ONESEARCH_URL
    2. Config file backend_url
    3. Default http://localhost:8000
    """
    # Check environment first
    env_url = os.environ.get("ONESEARCH_URL")
    if env_url:
        return env_url

    # Check config file
    config_url = get_config_value("backend_url")
    if config_url:
        return config_url

    # Default
    return "http://localhost:8000"


# Default configuration template
DEFAULT_CONFIG = """\
# OneSearch CLI Configuration
# Location: {config_path}

# Backend API URL
backend_url: http://localhost:8000

# Output settings
output:
  colors: true
  format: table  # table or json

# Default values for commands
defaults:
  search_limit: 20
"""
