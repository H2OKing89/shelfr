"""Shared UI components for Libation commands.

This module contains Rich UI helpers used across Libation commands.
"""

from __future__ import annotations

import logging
from typing import Any

from rich.columns import Columns
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from shelfr.console import console

logger = logging.getLogger(__name__)


def print_libation_header(
    title: str,
    subtitle: str | None = None,
    *,
    dry_run: bool = False,
    hint: str | None = None,
) -> None:
    """Print a styled Libation command header with optional hints.

    Examples:
        >>> print_libation_header("Export Library", subtitle="Exporting to JSON")
        >>> print_libation_header("Import Books", dry_run=True, hint="Use --yes to skip prompts")
    """
    content = Text()
    content.append("📚 ", style="bold")
    content.append(title, style="bold white")

    if subtitle:
        content.append(f"\n{subtitle}", style="dim")

    if dry_run:
        content.append("\n[DRY RUN] ", style="yellow bold")
        content.append("No changes will be made", style="yellow")

    console.print(
        Panel(
            content,
            title="[bold cyan]Libation[/]",
            subtitle="[dim]shelfr wrapper[/]" if not hint else f"[dim]{hint}[/]",
            border_style="blue",
            padding=(0, 2),
        )
    )

    console.print()


def print_hint_box(hints: list[str], title: str = "💡 Tips") -> None:
    """Print a box with helpful hints for users.

    Examples:
        >>> print_hint_box(["Run with --dry-run first", "Check logs for details"])
        >>> print_hint_box(["Use --verbose for more output"], title="Pro Tips")
    """
    if not hints:
        return

    content = Text()
    for i, hint in enumerate(hints):
        if i > 0:
            content.append("\n")
        content.append("• ", style="cyan")
        content.append(hint, style="dim")

    console.print(
        Panel(
            content,
            title=f"[cyan]{title}[/]",
            border_style="dim cyan",
            padding=(0, 1),
        )
    )
    console.print()


def print_command_help(
    command: str,
    description: str,
    examples: list[tuple[str, str]],
    options: list[tuple[str, str, str]] | None = None,
) -> None:
    """Print formatted command help with examples.

    Examples:
        >>> print_command_help(
        ...     "libation status",
        ...     "Show library status",
        ...     [("shelfr libation status", "Show all books")],
        ... )
    """
    console.print(f"\n[bold cyan]{command}[/] - {description}\n")

    if options:
        opt_table = Table(show_header=True, header_style="bold", box=None)
        opt_table.add_column("Option", style="green")
        opt_table.add_column("Default", style="dim")
        opt_table.add_column("Description")

        for opt, default, desc in options:
            opt_table.add_row(opt, default, desc)

        console.print(opt_table)
        console.print()

    console.print("[bold]Examples:[/]")
    for cmd, desc in examples:
        console.print(f"  [green]$[/] [white]{cmd}[/]")
        console.print(f"    [dim]{desc}[/]")


def print_book_table(
    books: list[dict[str, Any]],
    title: str = "Books",
    *,
    show_status: bool = True,
    limit: int = 20,
) -> None:
    """Print a formatted table of books.

    Examples::

        books = [{"Title": "Example", "AuthorNames": "Author", "AudibleProductId": "B0ABC"}]
        print_book_table(books, title="Library", limit=10)
    """
    if not books:
        console.print(f"[dim]No {title.lower()} found[/]")
        return

    table = Table(
        title=f"[bold]{title}[/] ({len(books)} total)",
        show_header=True,
        header_style="bold cyan",
        show_edge=True,
        row_styles=["", "dim"],
    )

    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Title", style="white", max_width=40, overflow="ellipsis")
    table.add_column("Author", style="cyan", max_width=25, overflow="ellipsis")
    table.add_column("ASIN", style="dim", width=12)

    if show_status:
        table.add_column("Status", justify="center", width=14)

    displayed = books[:limit]
    for i, book in enumerate(displayed, 1):
        # Extract author name - Libation exports as flat string "AuthorNames"
        author_name = str(book.get("AuthorNames", "")).strip() or "Unknown"
        author_name = author_name[:25]  # Truncate for display

        # Build full title (Title + Subtitle if present)
        book_title = str(book.get("Title", "Unknown")).strip()
        subtitle = str(book.get("Subtitle", "")).strip()
        if subtitle and subtitle not in book_title:
            book_title = f"{book_title}: {subtitle}"

        row: list[str] = [
            str(i),
            book_title[:40],
            author_name,
            str(book.get("AudibleProductId", "-")),  # Libation uses AudibleProductId, not Asin
        ]

        if show_status:
            status = str(book.get("BookStatus", "Unknown"))
            status_style = {
                "Liberated": "[green]✓ Liberated[/]",
                "NotLiberated": "[yellow]⏳ Pending[/]",
                "Error": "[red]✗ Error[/]",
            }.get(status, f"[dim]{status}[/]")
            row.append(status_style)

        table.add_row(*row)

    if len(books) > limit:
        remaining = len(books) - limit
        # Match column count based on whether status column is shown
        if show_status:
            table.add_row("...", f"[dim]+ {remaining} more books[/]", "", "", "")
        else:
            table.add_row("...", f"[dim]+ {remaining} more books[/]", "", "")

    console.print(table)


def print_status_dashboard(status: dict[str, int], title: str = "Library Status") -> None:
    """Print a rich dashboard showing library status.

    Examples:
        >>> status = {"Liberated": 150, "NotLiberated": 25, "Error": 3}
        >>> print_status_dashboard(status, title="Audible Library Status")
    """
    # Status cards
    cards: list[Panel] = []

    # Liberated card
    liberated = status.get("Liberated", 0)
    cards.append(
        Panel(
            f"[bold green]{liberated:,}[/]\n[dim]Downloaded[/]",
            title="[green]✓ Liberated[/]",
            border_style="green",
            width=18,
        )
    )

    # Pending card
    pending = status.get("NotLiberated", 0)
    pending_style = "yellow" if pending > 0 else "dim"
    cards.append(
        Panel(
            f"[bold {pending_style}]{pending:,}[/]\n[dim]Waiting[/]",
            title=f"[{pending_style}]⏳ Pending[/]",
            border_style=pending_style,
            width=18,
        )
    )

    # Error card
    errors = status.get("Error", 0)
    error_style = "red" if errors > 0 else "dim"
    cards.append(
        Panel(
            f"[bold {error_style}]{errors:,}[/]\n[dim]Failed[/]",
            title=f"[{error_style}]✗ Errors[/]",
            border_style=error_style,
            width=18,
        )
    )

    # Total card
    total = sum(status.values())
    cards.append(
        Panel(
            f"[bold cyan]{total:,}[/]\n[dim]Books[/]",
            title="[cyan]📚 Total[/]",
            border_style="cyan",
            width=18,
        )
    )

    console.print(Panel(Columns(cards, equal=True, expand=True), title=f"[bold]{title}[/]"))


__all__ = [
    "print_book_table",
    "print_command_help",
    "print_hint_box",
    "print_libation_header",
    "print_status_dashboard",
]
