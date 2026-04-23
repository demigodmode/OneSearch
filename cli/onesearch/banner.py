# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Startup banner rendering for the OneSearch CLI."""

from __future__ import annotations

from rich.console import Group
from rich.panel import Panel
from rich.text import Text


def _version_tuple(version: str | None) -> tuple[int, ...]:
    if not version:
        return ()
    parts = []
    for chunk in version.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def build_startup_panel(
    *,
    configured: bool,
    backend_url: str | None,
    server_status: str | None = None,
    auth_state: str | None = None,
    cli_version: str | None = None,
    server_version: str | None = None,
    error_message: str | None = None,
):
    """Build the startup banner panel."""
    lines: list[str] = []
    title = Text("OneSearch", style="bold cyan")

    if cli_version:
        lines.append(f"CLI: {cli_version}")
    if server_version:
        lines.append(f"Server: {server_version}")
    if backend_url:
        lines.append(f"Backend: {backend_url}")

    if not configured:
        lines.extend(
            [
                "",
                "No backend configured.",
                "Run: onesearch config set backend_url http://host:8000",
                "Then: onesearch login",
            ]
        )
        return Panel("\n".join(lines), title=title)

    if auth_state:
        lines.append(f"Auth: {auth_state}")
    if server_status:
        lines.append(f"Status: {server_status}")

    if error_message:
        lines.extend(["", f"Error: {error_message}"])

    if _version_tuple(server_version) > _version_tuple(cli_version):
        lines.extend(
            [
                "",
                "Update available: server is newer than this CLI. Consider updating onesearch-cli.",
            ]
        )

    if not error_message:
        lines.extend(
            [
                "",
                "Try:",
                '  onesearch search "compose"',
                "  onesearch source list",
                "  onesearch status",
            ]
        )

    return Panel(Group(*lines), title=title)
