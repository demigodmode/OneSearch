# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Shared CLI context and utilities."""

import io

import click
from rich.console import Console

from onesearch.api import OneSearchAPI
from onesearch.config import get_auth_token

# Rich console for output
console = Console()
err_console = Console(stderr=True)

# Quiet console that discards output
_quiet_console = Console(file=io.StringIO(), force_terminal=False)


class Context:
    """CLI context object passed to commands."""

    def __init__(self):
        self.api: OneSearchAPI | None = None
        self.verbose: bool = False
        self.quiet: bool = False
        self.url: str = "http://localhost:8000"
        self.token: str | None = None

    def get_api(self) -> OneSearchAPI:
        """Get or create the API client."""
        if self.api is None:
            self.token = get_auth_token()
            self.api = OneSearchAPI(base_url=self.url, token=self.token)
        return self.api

    def reset_api(self) -> None:
        """Clear cached API client after config/auth changes."""
        self.api = None
        self.token = None

    def get_console(self) -> Console:
        """Get the appropriate console based on quiet mode."""
        if self.quiet:
            return _quiet_console
        return console


pass_context = click.make_pass_decorator(Context, ensure=True)
