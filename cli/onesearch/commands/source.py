"""Source management commands."""

import click
from rich.table import Table

from onesearch.api import APIError
from onesearch.context import Context, pass_context, console, err_console
from onesearch.main import cli


def parse_patterns(patterns: str | None) -> list[str] | None:
    """Parse comma-separated patterns into a list."""
    if not patterns:
        return None
    return [p.strip() for p in patterns.split(",") if p.strip()]


def format_patterns(patterns: list[str] | None) -> str:
    """Format a list of patterns for display."""
    if not patterns:
        return "*"
    return ", ".join(patterns)


@cli.group()
def source():
    """Manage search sources.

    \b
    Examples:
      onesearch source list
      onesearch source add "Documents" /data/docs
      onesearch source show 1
      onesearch source reindex 1
      onesearch source delete 1
    """
    pass


@source.command("list")
@pass_context
def source_list(ctx: Context):
    """List all configured sources."""
    api = ctx.get_api()
    try:
        sources = api.list_sources()

        if not sources:
            console.print("[dim]No sources configured.[/dim]")
            console.print("\nAdd a source with: [cyan]onesearch source add <name> <path>[/cyan]")
            return

        table = Table(title="Sources")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Name", style="green")
        table.add_column("Root Path")
        table.add_column("Include Patterns", style="dim")
        table.add_column("Exclude Patterns", style="dim")

        for s in sources:
            table.add_row(
                str(s["id"]),
                s["name"],
                s["root_path"],
                format_patterns(s.get("include_patterns")),
                format_patterns(s.get("exclude_patterns")) if s.get("exclude_patterns") else "-",
            )

        console.print(table)
    except APIError as e:
        err_console.print(f"[red]Error:[/red] {e.message}")
        raise SystemExit(1)


@source.command("add")
@click.argument("name")
@click.argument("path")
@click.option("--include", "-i", help="Include patterns (comma-separated globs).")
@click.option("--exclude", "-e", help="Exclude patterns (comma-separated globs).")
@pass_context
def source_add(ctx: Context, name: str, path: str, include: str | None, exclude: str | None):
    """Add a new source.

    \b
    Arguments:
      NAME  Friendly name for the source
      PATH  Root path to index

    \b
    Examples:
      onesearch source add "Documents" /data/docs
      onesearch source add "Notes" /data/notes --include "**/*.md,**/*.txt"
      onesearch source add "Code" /data/code --exclude "**/node_modules/**,**/.git/**"
    """
    api = ctx.get_api()
    try:
        result = api.create_source(
            name=name,
            root_path=path,
            include_patterns=parse_patterns(include),
            exclude_patterns=parse_patterns(exclude),
        )
        console.print(f"[green]✓[/green] Created source [cyan]{result['name']}[/cyan] (ID: {result['id']})")
        console.print(f"  Path: {result['root_path']}")
        if result.get("include_patterns"):
            console.print(f"  Include: {format_patterns(result['include_patterns'])}")
        if result.get("exclude_patterns"):
            console.print(f"  Exclude: {format_patterns(result['exclude_patterns'])}")
        console.print("\nRun [cyan]onesearch source reindex {id}[/cyan] to start indexing.".format(id=result['id']))
    except APIError as e:
        err_console.print(f"[red]Error:[/red] {e.message}")
        raise SystemExit(1)


@source.command("show")
@click.argument("source_id")
@pass_context
def source_show(ctx: Context, source_id: str):
    """Show details for a source.

    \b
    Arguments:
      SOURCE_ID  The source ID to show
    """
    api = ctx.get_api()
    try:
        s = api.get_source(source_id)
        console.print(f"\n[bold cyan]{s['name']}[/bold cyan] (ID: {s['id']})")
        console.print(f"  Root Path:        {s['root_path']}")
        console.print(f"  Include Patterns: {format_patterns(s.get('include_patterns'))}")
        console.print(f"  Exclude Patterns: {format_patterns(s.get('exclude_patterns')) if s.get('exclude_patterns') else '-'}")
        if s.get("created_at"):
            console.print(f"  Created:          {s['created_at']}")
        if s.get("updated_at"):
            console.print(f"  Updated:          {s['updated_at']}")
    except APIError as e:
        err_console.print(f"[red]Error:[/red] {e.message}")
        raise SystemExit(1)


@source.command("delete")
@click.argument("source_id")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@pass_context
def source_delete(ctx: Context, source_id: str, yes: bool):
    """Delete a source.

    \b
    Arguments:
      SOURCE_ID  The source ID to delete

    This will remove the source configuration and all indexed documents
    from this source.
    """
    api = ctx.get_api()
    try:
        # Get source info for confirmation
        s = api.get_source(source_id)

        if not yes:
            console.print(f"[yellow]Warning:[/yellow] This will delete source [cyan]{s['name']}[/cyan] (ID: {source_id})")
            console.print(f"  Path: {s['root_path']}")
            console.print("\nAll indexed documents from this source will be removed.")
            if not click.confirm("Are you sure?"):
                console.print("[dim]Aborted.[/dim]")
                return

        api.delete_source(source_id)
        console.print(f"[green]✓[/green] Deleted source [cyan]{s['name']}[/cyan]")
    except APIError as e:
        err_console.print(f"[red]Error:[/red] {e.message}")
        raise SystemExit(1)


@source.command("reindex")
@click.argument("source_id")
@pass_context
def source_reindex(ctx: Context, source_id: str):
    """Trigger reindex for a source.

    \b
    Arguments:
      SOURCE_ID  The source ID to reindex

    This will scan the source path and index all matching files.
    """
    api = ctx.get_api()
    try:
        s = api.get_source(source_id)
        console.print(f"[dim]Reindexing source [cyan]{s['name']}[/cyan]...[/dim]")

        result = api.reindex_source(source_id)

        # Backend returns: {"message": ..., "stats": {...}}
        stats = result.get("stats", {})

        console.print(f"\n[green]✓[/green] Reindex completed for [cyan]{s['name']}[/cyan]")
        console.print(f"  Files scanned:  {stats.get('total_scanned', 0)}")
        console.print(f"  New files:      {stats.get('new_files', 0)}")
        console.print(f"  Modified:       {stats.get('modified_files', 0)}")
        console.print(f"  Unchanged:      {stats.get('unchanged_files', 0)}")
        console.print(f"  [green]Successful:   {stats.get('successful', 0)}[/green]")
        if stats.get("failed", 0) > 0:
            console.print(f"  [yellow]Failed:       {stats.get('failed', 0)}[/yellow]")
        if stats.get("skipped", 0) > 0:
            console.print(f"  Skipped:      {stats.get('skipped', 0)}")
    except APIError as e:
        err_console.print(f"[red]Error:[/red] {e.message}")
        raise SystemExit(1)
