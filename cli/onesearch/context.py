# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Shared CLI context and utilities."""

import click
from rich.console import Console

from onesearch.api import OneSearchAPI

# Rich console for output
console = Console()
err_console = Console(stderr=True)


class Context:
    """CLI context object passed to commands."""

    def __init__(self):
        self.api: OneSearchAPI | None = None
        self.verbose: bool = False
        self.url: str = "http://localhost:8000"

    def get_api(self) -> OneSearchAPI:
        """Get or create the API client."""
        if self.api is None:
            self.api = OneSearchAPI(base_url=self.url)
        return self.api


pass_context = click.make_pass_decorator(Context, ensure=True)
