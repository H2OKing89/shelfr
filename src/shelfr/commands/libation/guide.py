"""Guide command: show detailed tutorial.

This command displays a comprehensive guide for Libation integration.
"""

from __future__ import annotations

import argparse
import logging

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from shelfr.console import console

from ._ui import print_hint_box, print_libation_header

logger = logging.getLogger(__name__)


def cmd_libation_guide(args: argparse.Namespace) -> int:
    """Show detailed guide for Libation integration."""
    print_libation_header(
        "Libation Guide",
        "Comprehensive guide to Libation CLI integration",
    )

    # Overview panel
    console.print(
        Panel(
            Text.from_markup(
                "[bold]Libation[/] is an Audible audiobook manager that:\n"
                "  • [cyan]Scans[/] your Audible library for purchases\n"
                "  • [cyan]Downloads[/] and decrypts audiobooks to M4B\n"
                "  • [cyan]Manages[/] your local audiobook collection\n\n"
                "[bold]Key Concept:[/] [yellow]scan[/] and [yellow]liberate[/] are separate!\n"
                "  • [yellow]scan[/] indexes books → marks as 'NotLiberated'\n"
                "  • [yellow]liberate[/] downloads all 'NotLiberated' books"
            ),
            title="[bold cyan]About Libation[/]",
            border_style="cyan",
        )
    )

    console.print()

    # Commands table
    table = Table(
        title="Available Commands",
        show_header=True,
        header_style="bold cyan",
        show_edge=True,
    )
    table.add_column("Command", style="green", width=12)
    table.add_column("Description", width=32)
    table.add_column("Example", style="dim")

    commands = [
        ("scan", "Check Audible for new purchases", "shelfr libation scan"),
        ("liberate", "Download pending audiobooks", "shelfr libation liberate"),
        ("books", "List your audiobook library", "shelfr libation books --status pending"),
        ("redownload", "Re-download specific book(s)", "shelfr libation redownload B0XXX"),
        ("status", "Show library status dashboard", "shelfr libation status"),
        ("search", "Search your library", 'shelfr libation search "Sanderson"'),
        ("export", "Export library to file", "shelfr libation export -o lib.json"),
        ("set-status", "Update book download status", "shelfr libation set-status -n"),
        ("convert", "Convert M4B to MP3", "shelfr libation convert"),
        ("settings", "View Libation configuration", "shelfr libation settings"),
    ]

    for cmd, desc, example in commands:
        table.add_row(cmd, desc, example)

    console.print(table)

    # Common workflows
    console.print()
    console.print(
        Panel(
            Text.from_markup(
                "[bold]Full Workflow (recommended):[/]\n"
                "  [green]$[/] shelfr libation scan --liberate\n"
                "  [dim]Scans AND downloads in one step[/]\n\n"
                "[bold]Manual Workflow:[/]\n"
                "  [green]$[/] shelfr libation scan      [dim]# Check for new books[/]\n"
                "  [green]$[/] shelfr libation status    [dim]# See what's pending[/]\n"
                "  [green]$[/] shelfr libation liberate  [dim]# Download pending[/]\n\n"
                "[bold]Download Specific Book:[/]\n"
                "  [green]$[/] shelfr libation liberate --asin B0DK9T5P28\n\n"
                "[bold]Re-download a Book:[/]\n"
                "  [green]$[/] shelfr libation redownload B0DK9T5P28\n\n"
                "[bold]List Your Books:[/]\n"
                "  [green]$[/] shelfr libation books --status pending"
            ),
            title="[bold cyan]Common Workflows[/]",
            border_style="green",
        )
    )

    console.print()
    print_hint_box(
        [
            "Use --dry-run with any command to preview actions",
            "Use -v/--verbose to see detailed output",
            "Libation logs are saved to logs/libation/",
            "Configure Libation container in config/config.yaml",
        ],
        title="💡 Pro Tips",
    )

    return 0


__all__ = ["cmd_libation_guide"]
