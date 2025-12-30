"""Dry-run output components for MAMFast UI.

These components display what would happen without making changes.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.panel import Panel
from rich.table import Table

from shelfr.ui.core import console


@dataclass
class DryRunTransform:
    """A single field transformation shown in dry-run output."""

    field: str
    before: str
    after: str
    rule: str | None = None


def print_dry_run_header(count: int) -> None:
    """Print the dry-run panel header.

    Args:
        count: Number of releases to process

    Example:
        >>> print_dry_run_header(5)
        ╭─────────────────────────────────────╮
        │ Dry Run: Processing 5 releases      │
        ╰─────────────────────────────────────╯
    """
    console.print(
        Panel(
            f"Dry Run: Processing {count} release{'s' if count != 1 else ''}",
            border_style="yellow",
            padding=(0, 2),
        )
    )
    console.print()


def print_dry_run_release(
    transforms: list[DryRunTransform],
    release_title: str | None = None,
    source_path: str | None = None,
    target_path: str | None = None,
) -> None:
    """Print a before/after table for a single release in dry-run mode.

    Args:
        transforms: List of field transformations to display
        release_title: Optional release title to show above the table
        source_path: Original source folder name
        target_path: Target folder name after transformations
    """
    if release_title:
        console.print(f"[bold]{release_title}[/]")

    # Show source/target paths if provided
    if source_path:
        console.print(f"  [dim]Source:[/] {source_path}")
    if target_path:
        if source_path and source_path != target_path:
            console.print(f"  [dim]Target:[/] [green]{target_path}[/]")
        elif source_path:
            console.print("  [dim]Target:[/] [dim](unchanged)[/]")

    # Filter to only transformations that actually changed something
    changes = [t for t in transforms if t.before != t.after]

    if not changes:
        if not source_path:  # Only show this if we didn't already show paths
            console.print("  [dim]✓ No transformations needed[/]")
        console.print()
        return

    table = Table(
        show_header=True,
        header_style="bold",
        box=None,
        padding=(0, 1),
        expand=True,
    )
    table.add_column("Field", style="cyan", width=14)
    table.add_column("Before", style="red", overflow="fold", ratio=1)
    table.add_column("After", style="green", overflow="fold", ratio=1)

    for t in changes:
        table.add_row(t.field, t.before, t.after)
        if t.rule:
            # Add rule info as a dim row below
            console.print(table)
            console.print(f"  [dim]rule:[/] [yellow]{t.rule}[/]")
            # Create new table for next transform
            table = Table(
                show_header=False,
                box=None,
                padding=(0, 1),
                expand=True,
            )
            table.add_column("Field", style="cyan", width=14)
            table.add_column("Before", style="red", overflow="fold", ratio=1)
            table.add_column("After", style="green", overflow="fold", ratio=1)
    else:
        # Print the last table if no rule on last item
        if changes and not changes[-1].rule:
            console.print(table)
        elif changes and changes[-1].rule:
            pass  # Already printed above

    console.print()


def print_dry_run_summary(processed: int, would_change: int, no_change: int) -> None:
    """Print a summary at the end of dry-run.

    Args:
        processed: Total releases checked
        would_change: Number that would have changes
        no_change: Number unchanged

    Example:
        >>> print_dry_run_summary(10, 3, 7)
        Summary: 10 releases checked, 3 would change, 7 unchanged
    """
    console.print(
        f"[dim]Summary:[/] {processed} releases checked, "
        f"[green]{would_change}[/] would change, "
        f"[dim]{no_change}[/] unchanged"
    )


def print_dry_run_action(action: str, target: str, details: str | None = None) -> None:
    """Print a single dry-run action.

    Args:
        action: The action that would be taken (e.g., "CREATE", "DELETE", "RENAME")
        target: The target of the action
        details: Optional additional details

    Example:
        >>> print_dry_run_action("CREATE", "/mnt/books/New Book", "hardlink from source")
          [DRY RUN] CREATE /mnt/books/New Book
            hardlink from source
    """
    console.print(f"  [warning][DRY RUN][/] [bold]{action}[/] {target}")
    if details:
        console.print(f"    [dim]{details}[/]")
