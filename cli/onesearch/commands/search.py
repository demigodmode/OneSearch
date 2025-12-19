# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Search command."""

import json

import click
from rich.markup import escape
from rich.text import Text

from onesearch.api import APIError
from onesearch.context import Context, pass_context, console, err_console
from onesearch.main import cli


def format_size(size_bytes: int | None) -> str:
    """Format bytes as human-readable size."""
    if size_bytes is None:
        return "-"
    size: float = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if abs(size) < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def highlight_snippet(text: str, query: str) -> Text:
    """Create a Rich Text with query terms highlighted."""
    result = Text()
    text_lower = text.lower()
    query_terms = query.lower().split()

    i = 0
    while i < len(text):
        matched = False
        for term in query_terms:
            if text_lower[i:].startswith(term):
                result.append(text[i:i + len(term)], style="bold yellow")
                i += len(term)
                matched = True
                break
        if not matched:
            result.append(text[i])
            i += 1

    return result


@cli.command()
@click.argument("query")
@click.option("--source", "-s", "source_id", help="Filter by source ID.")
@click.option("--type", "-t", "file_type", type=click.Choice(["text", "markdown", "pdf"]), help="Filter by file type.")
@click.option("--limit", "-l", default=20, help="Max results to return.", show_default=True)
@click.option("--offset", "-o", default=0, help="Result offset for pagination.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON for scripting.")
@pass_context
def search(
    ctx: Context,
    query: str,
    source_id: str | None,
    file_type: str | None,
    limit: int,
    offset: int,
    as_json: bool,
):
    """Search indexed documents.

    \b
    Arguments:
      QUERY  Search query string

    \b
    Examples:
      onesearch search "kubernetes deployment"
      onesearch search "python" --source 1 --type pdf --limit 10
      onesearch search "error" --json | jq '.results[].path'
    """
    api = ctx.get_api()
    try:
        result = api.search(
            query=query,
            source_id=source_id,
            file_type=file_type,
            limit=limit,
            offset=offset,
        )

        out = ctx.get_console()

        if as_json:
            console.print(json.dumps(result, indent=2))
            return

        # Backend returns: {results, total, limit, offset, processing_time_ms}
        results = result.get("results", [])
        total = result.get("total", len(results))
        processing_time = result.get("processing_time_ms", 0)

        if not results:
            out.print(f"[dim]No results found for:[/dim] [cyan]{escape(query)}[/cyan]")
            return

        out.print(f"\nFound [green]{total}[/green] results in [dim]{processing_time}ms[/dim]\n")

        for i, hit in enumerate(results, start=offset + 1):
            # Title line - backend returns: basename, source_name
            filename = hit.get("basename", hit.get("path", "Unknown").split("/")[-1])
            source_name = hit.get("source_name", "Unknown")
            console.print(f"[bold][{i}][/bold] [cyan]{escape(filename)}[/cyan] [dim]({source_name})[/dim]")

            # Metadata line - backend returns: type, size_bytes, modified_at
            file_type_display = hit.get("type", "unknown")
            size = format_size(hit.get("size_bytes"))
            modified = hit.get("modified_at", "-")
            # modified_at is Unix timestamp
            if isinstance(modified, int):
                from datetime import datetime
                modified = datetime.fromtimestamp(modified).strftime("%Y-%m-%d")
            console.print(f"    Path: {escape(hit.get('path', '-'))}")
            console.print(f"    Type: {file_type_display} | Size: {size} | Modified: {modified}")

            # Snippet - backend returns pre-formatted snippet
            snippet = hit.get("snippet", "")
            if snippet:
                snippet = snippet.replace("\n", " ").strip()
                highlighted = highlight_snippet(snippet, query)
                console.print("    ", end="")
                console.print(highlighted)

            console.print()

        # Pagination hint (only in non-quiet mode)
        if offset + len(results) < total:
            next_offset = offset + limit
            out.print(f"[dim]Showing {offset + 1}-{offset + len(results)} of {total}. ")
            out.print(f"Use --offset {next_offset} for more results.[/dim]")

    except APIError as e:
        err_console.print(f"[red]Error:[/red] {e.message}")
        raise SystemExit(1)
