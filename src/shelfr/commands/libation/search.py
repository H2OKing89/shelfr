"""Search commands: search, books.

These commands allow searching and listing audiobooks.
"""

from __future__ import annotations

import argparse
import logging
from typing import Any

from rich.panel import Panel
from rich.table import Table

from shelfr.console import console

from ._common import (
    export_library as _export_library,
)
from ._common import (
    get_library_status as _get_library_status,
)
from ._common import (
    run_libation_cmd as _run_libation_cmd,
)
from ._ui import print_hint_box, print_libation_header, print_status_dashboard

logger = logging.getLogger(__name__)


def cmd_libation_search(args: argparse.Namespace) -> int:
    """Search Libation library."""
    from shelfr.config import reload_settings

    query = args.query

    print_libation_header(
        f"Search: {query}",
        "Searching your Libation audiobook library",
    )

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        console.print(f"[red]✗ Configuration error:[/] {e}")
        return 1

    container = settings.libation_container

    console.print("[bold]Searching...[/]")

    # Use Libation's search command
    limit = getattr(args, "limit", 20)
    result = _run_libation_cmd(container, "search", "-n", str(limit), query)

    if result.success:
        if result.stdout:
            # Parse and display search results nicely
            console.print()
            console.print(Panel(result.stdout.strip(), title="Search Results"))
        else:
            console.print("  [dim]No results found[/]")

        console.print()
        print_hint_box(
            [
                f'Try: shelfr libation search "author:{query}"',
                f'Try: shelfr libation search "title:{query}"',
                "Use Lucene query syntax for advanced searches",
            ]
        )
    else:
        console.print(f"  [red]✗[/] Search failed: {result.error_message or result.stderr}")
        return 1

    return 0


def cmd_libation_books(args: argparse.Namespace) -> int:
    """List audiobooks in Libation library with filtering."""
    from shelfr.config import reload_settings

    status_filter = getattr(args, "status", None)
    author_filter = getattr(args, "author", None)
    limit = getattr(args, "limit", 50)
    show_asin = getattr(args, "show_asin", False)

    filter_desc = []
    if status_filter:
        filter_desc.append(f"status={status_filter}")
    if author_filter:
        filter_desc.append(f"author contains '{author_filter}'")

    subtitle = f"Filters: {', '.join(filter_desc)}" if filter_desc else "All audiobooks"

    print_libation_header(
        "📚 Your Audiobook Library",
        subtitle,
        hint="Use filters to narrow down results",
    )

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        console.print(f"[red]✗ Configuration error:[/] {e}")
        return 1

    container = settings.libation_container

    console.print("[bold]Loading library...[/]")
    try:
        books = _export_library(container)
    except Exception as e:
        console.print(f"  [red]✗[/] Failed to load library: {e}")
        return 1

    # Apply filters
    filtered_books = books

    if status_filter:
        status_map = {
            "liberated": "Liberated",
            "downloaded": "Liberated",
            "pending": "NotLiberated",
            "notliberated": "NotLiberated",
            "error": "Error",
            "failed": "Error",
        }
        target_status = status_map.get(status_filter.lower(), status_filter)
        filtered_books = [b for b in filtered_books if b.get("BookStatus") == target_status]

    if author_filter:
        author_lower = author_filter.lower()
        filtered_books = [
            b for b in filtered_books if author_lower in str(b.get("AuthorNames", "")).lower()
        ]

    # Sort by series name, then by series order number
    def sort_key(book: dict[str, Any]) -> tuple[str, int, str]:
        series = str(book.get("SeriesNames", "") or "").strip()
        # Extract numeric position from SeriesOrder (format: "17 : Series Name")
        series_order_raw = str(book.get("SeriesOrder", "") or "").strip()
        order_num = 9999  # Default for non-series or unparseable
        if series_order_raw and ":" in series_order_raw:
            pos_str = series_order_raw.split(":")[0].strip()
            if pos_str.isdigit():
                order_num = int(pos_str)
        title = str(book.get("Title", "")).strip()
        # Sort: series name (empty series last), then order number, then title
        return (series or "~~~", order_num, title)

    filtered_books = sorted(filtered_books, key=sort_key)

    console.print(f"  [green]✓[/] Found {len(filtered_books)} matching books")
    console.print()

    if not filtered_books:
        console.print("[dim]No books match your filters[/]")
        print_hint_box(
            [
                "Try removing filters to see all books",
                "Status options: liberated, pending, error",
                "shelfr libation books --limit 100",
            ]
        )
        return 0

    # Build and display table
    shown = min(limit, len(filtered_books))
    table = Table(
        title=f"[bold]Audiobooks[/] ({len(filtered_books)} total, showing {shown})",
        show_header=True,
        header_style="bold cyan",
        row_styles=["", "dim"],
    )

    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Title", style="white", max_width=55, overflow="ellipsis")
    table.add_column("Author", style="cyan", max_width=25, overflow="ellipsis")
    table.add_column("Series", style="magenta", width=5, justify="center")
    if show_asin:
        table.add_column("ASIN", style="dim", width=12)
    table.add_column("", justify="center", width=4)  # Status column (compact)

    for i, book in enumerate(filtered_books[:limit], 1):
        # Extract first author only - Libation exports as comma-separated string "AuthorNames"
        author_raw = str(book.get("AuthorNames", "")).strip()
        author_name = author_raw.split(",")[0].strip() if author_raw else "Unknown"
        author_name = author_name[:25]  # Truncate for display

        # Build full title (Title + Subtitle if present for better disambiguation)
        title = str(book.get("Title", "Unknown")).strip()
        subtitle = str(book.get("Subtitle", "")).strip()
        if subtitle and subtitle not in title:
            title = f"{title}: {subtitle}"

        # Extract series position from SeriesOrder (format: "17 : Series Name")
        series_order_raw = str(book.get("SeriesOrder", "")).strip()
        series_pos = ""
        if series_order_raw and ":" in series_order_raw:
            pos_str = series_order_raw.split(":")[0].strip()
            if pos_str.isdigit():
                series_pos = f"#{int(pos_str):02d}"  # Pad to 2 digits
            elif pos_str:
                series_pos = f"#{pos_str}"

        # Compact status badge
        status = str(book.get("BookStatus", "Unknown"))
        status_display = {
            "Liberated": "[green]DL[/]",
            "NotLiberated": "[red]NDL[/]",
            "Error": "[red]ERR[/]",
        }.get(status, "[dim]?[/]")

        row: list[str] = [
            str(i),
            title[:55],
            author_name,
            series_pos,
        ]
        if show_asin:
            row.append(str(book.get("AudibleProductId", "-")))  # Libation field name
        row.append(status_display)

        table.add_row(*row)

    console.print(table)

    if len(filtered_books) > limit:
        console.print(
            f"\n[dim]Showing {limit} of {len(filtered_books)} books. Use --limit to see more.[/]"
        )

    # Show summary stats
    status_counts = _get_library_status(filtered_books)
    console.print()
    print_status_dashboard(status_counts, title="Filtered Results Summary")

    print_hint_box(
        [
            "shelfr libation books --status pending  → Show only pending downloads",
            "shelfr libation books --author Sanderson → Filter by author",
            "shelfr libation books --show-asin       → Show ASIN column",
            "shelfr libation redownload <ASIN>       → Re-download a specific book",
        ],
        title="🔍 Filter Tips",
    )

    return 0


__all__ = [
    "cmd_libation_books",
    "cmd_libation_search",
]
