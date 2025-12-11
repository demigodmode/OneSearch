"""Status and health commands."""

import json
from datetime import datetime

import click
from rich.table import Table

from onesearch.api import APIError
from onesearch.context import Context, pass_context, console, err_console
from onesearch.main import cli


def format_timestamp(ts) -> str:
    """Format a timestamp for display."""
    if not ts:
        return "-"
    if isinstance(ts, str):
        # ISO format string
        if "T" in ts:
            return ts.replace("T", " ").split(".")[0]
        return ts
    if isinstance(ts, (int, float)):
        # Unix timestamp
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    return str(ts)


@cli.command()
@click.argument("source_id", required=False)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON for scripting.")
@pass_context
def status(ctx: Context, source_id: str | None, as_json: bool):
    """Show indexing status for sources.

    \b
    Arguments:
      SOURCE_ID  Optional source ID for detailed status

    \b
    Examples:
      onesearch status           # All sources
      onesearch status my-docs   # Specific source
      onesearch status --json    # JSON output
    """
    api = ctx.get_api()
    try:
        if source_id is not None:
            # Detailed status for specific source
            # Backend returns flat: {source_id, source_name, total_files, successful, failed, skipped, last_indexed_at, failed_files}
            result = api.source_status(source_id)
            if as_json:
                console.print(json.dumps(result, indent=2, default=str))
                return

            console.print(f"\n[bold cyan]{result.get('source_name', 'Unknown')}[/bold cyan] (ID: {result.get('source_id', source_id)})")
            console.print()

            console.print("[bold]Indexing Statistics:[/bold]")
            console.print(f"  Total Files:  {result.get('total_files', 0)}")
            console.print(f"  [green]Successful: {result.get('successful', 0)} ✓[/green]")

            failed = result.get("failed", 0)
            if failed > 0:
                console.print(f"  [red]Failed:     {failed} ✗[/red]")
            else:
                console.print(f"  Failed:     0")

            skipped = result.get("skipped", 0)
            if skipped > 0:
                console.print(f"  [yellow]Skipped:    {skipped}[/yellow]")

            last_indexed = format_timestamp(result.get("last_indexed_at"))
            console.print(f"  Last Index: {last_indexed}")

            # Show failed files if any
            failed_files = result.get("failed_files", [])
            if failed_files:
                console.print(f"\n[bold red]Failed Files ({len(failed_files)}):[/bold red]")
                for f in failed_files[:10]:  # Show first 10
                    console.print(f"  • {f.get('path', 'Unknown')}")
                    if f.get("error"):
                        console.print(f"    [dim]{f['error']}[/dim]")
                if len(failed_files) > 10:
                    console.print(f"  [dim]... and {len(failed_files) - 10} more[/dim]")
        else:
            # Overview status for all sources
            # Backend returns: {sources: [{source_id, source_name, total_files, successful, failed, skipped, last_indexed_at, ...}]}
            result = api.status()
            if as_json:
                console.print(json.dumps(result, indent=2, default=str))
                return

            sources = result.get("sources", [])
            if not sources:
                console.print("[dim]No sources configured.[/dim]")
                console.print("\nAdd a source with: [cyan]onesearch source add <name> <path>[/cyan]")
                return

            table = Table(title="Source Status")
            table.add_column("Source", style="cyan")
            table.add_column("Total", justify="right")
            table.add_column("Success", justify="right", style="green")
            table.add_column("Failed", justify="right")
            table.add_column("Skipped", justify="right")
            table.add_column("Last Indexed")

            for s in sources:
                # Check for error status
                if s.get("error"):
                    table.add_row(
                        f"{s.get('source_name', 'Unknown')} ({s.get('source_id', '?')})",
                        "-",
                        "-",
                        f"[red]Error[/red]",
                        "-",
                        "-",
                    )
                    continue

                failed = s.get("failed", 0)
                failed_str = f"[red]{failed} ✗[/red]" if failed > 0 else "0"

                last_indexed = format_timestamp(s.get("last_indexed_at"))

                table.add_row(
                    f"{s.get('source_name', 'Unknown')} ({s.get('source_id', '?')})",
                    str(s.get("total_files", 0)),
                    f"{s.get('successful', 0)} ✓",
                    failed_str,
                    str(s.get("skipped", 0)),
                    last_indexed,
                )

            console.print()
            console.print(table)
            console.print()

    except APIError as e:
        err_console.print(f"[red]Error:[/red] {e.message}")
        raise SystemExit(1)


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON for scripting.")
@pass_context
def health(ctx: Context, as_json: bool):
    """Check system health.

    Verifies connectivity to the backend and Meilisearch.

    \b
    Examples:
      onesearch health
      onesearch health --json
    """
    api = ctx.get_api()
    try:
        result = api.health()

        if as_json:
            console.print(json.dumps(result, indent=2))
            return

        console.print()
        # Backend returns status as "healthy" or "degraded"
        overall = result.get("status", "unknown")
        if overall == "healthy":
            console.print("[bold green]✓ System Healthy[/bold green]")
        else:
            console.print(f"[bold yellow]⚠ System Status: {overall}[/bold yellow]")

        console.print()
        console.print(f"  Backend:     {ctx.url} [green]✓[/green]")
        console.print(f"  Service:     {result.get('service', 'onesearch-backend')} v{result.get('version', '?')}")

        # Meilisearch status - backend returns {status: "available"|"degraded"|...}
        meili = result.get("meilisearch", {})
        meili_status = meili.get("status", "unknown")
        if meili_status in ("available", "healthy"):
            console.print(f"  Meilisearch: Connected [green]✓[/green]")
        else:
            console.print(f"  Meilisearch: [yellow]{meili_status}[/yellow]")

        console.print()

    except APIError as e:
        err_console.print(f"[red]✗ System Unhealthy[/red]")
        err_console.print(f"\n  Backend: {ctx.url} [red]✗[/red]")
        err_console.print(f"  Error: {e.message}")
        console.print()
        raise SystemExit(1)
