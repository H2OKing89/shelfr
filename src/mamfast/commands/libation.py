"""Libation CLI wrapper commands for MAMFast.

Provides a comprehensive, user-friendly wrapper around LibationCli with:
- Rich formatted output and progress indicators
- Helpful tooltips and hints for new users
- Status monitoring and book management
- Interactive prompts and confirmations

Commands:
    mamfast libation scan        - Scan Audible for new books
    mamfast libation liberate    - Download pending books
    mamfast libation status      - Show library status
    mamfast libation search      - Search your library
    mamfast libation export      - Export library data
    mamfast libation settings    - View/manage Libation settings
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.columns import Columns
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text

from mamfast.console import console
from mamfast.exceptions import LibationError
from mamfast.paths import log_dir
from mamfast.utils.cmd import CmdError, docker
from mamfast.utils.validation import validate_asin

logger = logging.getLogger(__name__)


# =============================================================================
# Rich UI Components
# =============================================================================


def print_libation_header(
    title: str,
    subtitle: str | None = None,
    *,
    dry_run: bool = False,
    hint: str | None = None,
) -> None:
    """Print a styled Libation command header with optional hints."""
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
            subtitle="[dim]mamfast wrapper[/]" if not hint else f"[dim]{hint}[/]",
            border_style="blue",
            padding=(0, 2),
        )
    )

    console.print()


def print_hint_box(hints: list[str], title: str = "💡 Tips") -> None:
    """Print a box with helpful hints for users."""
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
    """Print formatted command help with examples."""
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
    """Print a formatted table of books."""
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
        table.add_row("...", f"[dim]+ {remaining} more books[/]", "", "", "")

    console.print(table)


def print_status_dashboard(status: dict[str, int], title: str = "Library Status") -> None:
    """Print a rich dashboard showing library status."""
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


# =============================================================================
# Libation Interaction Helpers
# =============================================================================


@dataclass
class LibationCommandResult:
    """Result from running a Libation command."""

    success: bool
    returncode: int
    stdout: str = ""
    stderr: str = ""
    parsed_data: Any = None
    error_message: str = ""


def _run_libation_cmd(
    container: str,
    *args: str,
    timeout: int = 300,
    ok_codes: tuple[int, ...] = (0,),
) -> LibationCommandResult:
    """Run a LibationCli command in the container."""
    try:
        result = docker(
            "exec",
            container,
            "/libation/LibationCli",
            *args,
            timeout=timeout,
            ok_codes=ok_codes,
        )

        # If we get here, exit code was in ok_codes
        return LibationCommandResult(
            success=True,
            returncode=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    except CmdError as e:
        # docker() raises CmdError when exit code not in ok_codes or on timeout
        return LibationCommandResult(
            success=False,
            returncode=e.exit_code,
            stdout=e.stdout,
            stderr=e.stderr,
            error_message=str(e) if not e.timed_out else f"Command timed out after {timeout}s",
        )
    except Exception as e:
        # Catch any other unexpected errors
        return LibationCommandResult(
            success=False,
            returncode=-1,
            error_message=str(e),
        )


def _export_library(container: str) -> list[dict[str, Any]]:
    """Export library data from Libation as JSON."""
    export_path = "/tmp/mamfast_export.json"

    # Run export command
    result = _run_libation_cmd(container, "export", "-p", export_path, "-j")
    if not result.success:
        raise LibationError(
            f"Export failed: {result.error_message or result.stderr}",
            return_code=result.returncode,
        )

    # Read the exported JSON
    try:
        read_result = docker("exec", container, "cat", export_path, timeout=30)
        books = json.loads(read_result.stdout)
        return list(books) if isinstance(books, list) else []
    finally:
        # Cleanup
        with contextlib.suppress(CmdError):
            docker("exec", container, "rm", "-f", export_path, timeout=10)


def _get_library_status(books: list[dict[str, Any]]) -> dict[str, int]:
    """Get status counts from library export."""
    status_counts: dict[str, int] = {}
    for book in books:
        status = book.get("BookStatus", "Unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    return status_counts


# =============================================================================
# CLI Commands
# =============================================================================


def cmd_libation(args: argparse.Namespace) -> int:
    """Main entry point for libation subcommand group."""
    # If no subcommand, show help/status
    if not hasattr(args, "libation_func") or args.libation_func is None:
        return cmd_libation_status(args)
    result: int = args.libation_func(args)
    return result


def cmd_libation_scan(args: argparse.Namespace) -> int:
    """Scan Audible library for new books."""
    from mamfast.config import reload_settings

    print_libation_header(
        "Scan Audible Library",
        "Indexing your Audible purchases into Libation's database",
        dry_run=args.dry_run,
        hint="Tip: New books become 'Pending' until liberated",
    )

    # Show helpful hints for new users
    if not args.dry_run:
        print_hint_box(
            [
                "Scanning checks Audible for NEW purchases only",
                "Books found are marked 'NotLiberated' (pending download)",
                "Use 'mamfast libation liberate' to download pending books",
                "Run with --liberate to scan AND download in one step",
            ]
        )

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        console.print(f"[red]✗ Configuration error:[/] {e}")
        console.print("[dim]Hint: Ensure config/config.yaml exists[/]")
        return 1

    container = settings.libation_container

    if args.dry_run:
        console.print("[yellow]Would execute:[/]")
        console.print(f"  docker exec {container} /libation/LibationCli scan")
        if args.liberate:
            console.print(f"  docker exec {container} /libation/LibationCli liberate")
        return 0

    # Check container is running
    console.print("[bold]Checking Libation container...[/]")
    try:
        docker("container", "inspect", "-f", "{{.State.Running}}", container)
        console.print(f"  [green]✓[/] Container '{container}' is running")
    except CmdError:
        console.print(f"  [red]✗[/] Container '{container}' not found or not running")
        console.print(f"\n[dim]Hint: Start the container with 'docker start {container}'[/]")
        return 1

    # Run scan with progress
    console.print("\n[bold]Scanning Audible library...[/]")
    with console.status("  Querying Audible API...", spinner="dots"):
        result = _run_libation_cmd(container, "scan", timeout=600)

    if result.success:
        console.print("  [green]✓[/] Scan complete")

        # Parse scan output for "New: X" count
        new_match = re.search(r"New:\s*(\d+)", result.stdout)
        if new_match:
            new_count = int(new_match.group(1))
            if new_count > 0:
                console.print(f"  [cyan]→[/] Found [bold]{new_count}[/] new book(s)")
            else:
                console.print("  [dim]→ No new books found this scan[/]")

        # Show any stdout messages
        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                if line.strip() and "New:" not in line:
                    console.print(f"  [dim]{line.strip()}[/]")
    else:
        console.print(f"  [red]✗[/] Scan failed (exit code: {result.returncode})")
        if result.stderr:
            console.print(f"  [dim]{result.stderr[:200]}[/]")
        return result.returncode

    # Show current status
    console.print("\n[bold]Library Status:[/]")
    try:
        books = _export_library(container)
        status = _get_library_status(books)
        print_status_dashboard(status)

        pending = status.get("NotLiberated", 0)
        if pending > 0:
            console.print()
            if args.liberate:
                console.print(f"[cyan]→[/] Proceeding to download {pending} pending book(s)...")
                # Recursively call liberate
                args_copy = argparse.Namespace(**vars(args))
                args_copy.asin = None
                args_copy.force = False
                return cmd_libation_liberate(args_copy)
            else:
                console.print(f"[yellow]![/] {pending} book(s) waiting for download")
                console.print(
                    "[dim]Hint: Run 'mamfast libation liberate' or use '--liberate' flag[/]"
                )

    except Exception as e:
        console.print(f"  [yellow]![/] Could not fetch status: {e}")

    return 0


def cmd_libation_liberate(args: argparse.Namespace) -> int:
    """Download and decrypt pending audiobooks."""
    from mamfast.config import reload_settings

    asin = getattr(args, "asin", None)
    skip_confirm = getattr(args, "yes", False)

    title = "Download Audiobooks"
    if asin:
        title = f"Download Book: {asin}"

    print_libation_header(
        title,
        "Downloading and decrypting audiobooks from Audible",
        dry_run=args.dry_run,
        hint="Downloads go to your configured Libation output folder",
    )

    if not args.dry_run:
        print_hint_box(
            [
                "This downloads ALL pending (NotLiberated) books by default",
                "Use --asin XXXXXX to download a specific book",
                "Use --force to re-download already liberated books",
                "Downloads are saved to Libation's configured Books folder",
                "Use --yes / -y to skip confirmation prompt",
            ]
        )

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        console.print(f"[red]✗ Configuration error:[/] {e}")
        return 1

    container = settings.libation_container

    if args.dry_run:
        cmd = f"docker exec {container} /libation/LibationCli liberate"
        if asin:
            cmd += f" {asin}"
        if getattr(args, "force", False):
            cmd += " -f"
        console.print("[yellow]Would execute:[/]")
        console.print(f"  {cmd}")
        return 0

    # Get current status first
    console.print("[bold]Checking pending downloads...[/]")
    try:
        books = _export_library(container)
        status = _get_library_status(books)
        pending = status.get("NotLiberated", 0)

        if asin:
            # Check if specific ASIN exists
            book = next((b for b in books if b.get("AudibleProductId") == asin), None)
            if not book:
                console.print(f"  [red]✗[/] Book with ASIN '{asin}' not found")
                return 1
            console.print(f"  [green]✓[/] Found: {book.get('Title', 'Unknown')}")
            pending = 1
        elif pending == 0 and not getattr(args, "force", False):
            console.print("  [dim]→ No pending downloads[/]")
            console.print("\n[dim]All books are already liberated![/]")
            print_hint_box(
                [
                    "Run 'mamfast libation scan' to check for new purchases",
                    "Use '--force' to re-download existing books",
                ]
            )
            return 0
        else:
            console.print(f"  [cyan]→[/] {pending} book(s) pending download")

    except Exception as e:
        console.print(f"  [yellow]![/] Could not check status: {e}")
        console.print("  [dim]Proceeding with liberate anyway...[/]")
        pending = 0  # Unknown

    # Confirmation prompt (unless --yes or dry-run)
    if not skip_confirm and not asin and pending > 0:
        from rich.prompt import Confirm

        console.print()
        if not Confirm.ask(f"[yellow]Download {pending} pending book(s)?[/] This may take a while"):
            console.print("[dim]Cancelled.[/]")
            return 0

    # Run liberate with progress
    console.print(f"\n[bold]Downloading {'book' if asin else 'audiobooks'}...[/]")

    # Build command
    cmd_args = ["liberate"]
    if asin:
        cmd_args.append(asin)
    if getattr(args, "force", False):
        cmd_args.append("-f")

    # Use longer timeout for downloads (4 hours)
    # Note: ok_codes=(0, 1) allows exit code 1 for partial success/warnings
    with console.status(
        f"  Downloading {pending if pending else 'audiobooks'}...",
        spinner="dots",
    ):
        result = _run_libation_cmd(container, *cmd_args, timeout=14400, ok_codes=(0, 1))

    if result.success:
        console.print("  [green]✓[/] Download complete")

        # Parse output for completed books
        completed = result.stdout.count("Completed:")
        if completed > 0:
            console.print(f"  [cyan]→[/] Downloaded {completed} book(s)")

        # Log output for debugging
        if result.stdout:
            log_path = _save_libation_log("liberate", result.stdout, result.stderr)
            console.print(f"  [dim]Log saved: {log_path}[/]")

    else:
        console.print(f"  [red]✗[/] Download failed (exit code: {result.returncode})")
        if result.stderr:
            # Show last few lines of error
            error_lines = result.stderr.strip().split("\n")[-5:]
            for line in error_lines:
                console.print(f"    [dim]{line}[/]")
        return result.returncode

    # Show updated status
    console.print("\n[bold]Updated Status:[/]")
    try:
        books = _export_library(container)
        status = _get_library_status(books)
        print_status_dashboard(status)
    except Exception as e:
        console.print(f"  [yellow]![/] Could not refresh status: {e}")

    return 0


def cmd_libation_status(args: argparse.Namespace) -> int:
    """Show Libation library status and statistics."""
    from mamfast.config import reload_settings

    print_libation_header(
        "Library Status",
        "Overview of your Libation audiobook library",
        hint="Quick view of your collection",
    )

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        console.print(f"[red]✗ Configuration error:[/] {e}")
        return 1

    container = settings.libation_container

    console.print("[bold]Fetching library data...[/]")
    try:
        books = _export_library(container)
    except Exception as e:
        console.print(f"  [red]✗[/] Failed to export library: {e}")
        console.print(f"\n[dim]Hint: Is the container '{container}' running?[/]")
        return 1

    status = _get_library_status(books)

    console.print(f"  [green]✓[/] Found {len(books):,} books in library")
    console.print()

    # Show dashboard
    print_status_dashboard(status)

    # Show pending books if any
    pending_books = [b for b in books if b.get("BookStatus") == "NotLiberated"]
    if pending_books:
        console.print()
        print_book_table(
            pending_books,
            title="📥 Pending Downloads",
            show_status=False,
            limit=10,
        )
        console.print("\n[dim]Hint: Run 'mamfast libation liberate' to download these books[/]")

    # Show error books if any
    error_books = [b for b in books if b.get("BookStatus") == "Error"]
    if error_books:
        console.print()
        print_book_table(
            error_books,
            title="❌ Failed Downloads",
            show_status=False,
            limit=5,
        )
        console.print(
            "\n[dim]Hint: Use 'mamfast libation liberate --force --asin XXXXX' to retry[/]"
        )

    # Show recent additions
    recent = sorted(
        [b for b in books if b.get("DateAdded")],
        key=lambda x: x.get("DateAdded", ""),
        reverse=True,
    )[:5]

    if recent:
        console.print()
        console.print("[bold]📅 Recently Added:[/]")
        for book in recent:
            date = book.get("DateAdded", "")[:10]
            title_str = book.get("Title", "Unknown")[:50]
            console.print(f"  [dim]{date}[/] {title_str}")

    # Quick actions hint
    console.print()
    print_hint_box(
        [
            "mamfast libation scan      → Check for new Audible purchases",
            "mamfast libation liberate  → Download pending books",
            "mamfast libation search    → Search your library",
            "mamfast libation export    → Export library data",
        ],
        title="🚀 Quick Actions",
    )

    return 0


def cmd_libation_search(args: argparse.Namespace) -> int:
    """Search Libation library."""
    from mamfast.config import reload_settings

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
                f'Try: mamfast libation search "author:{query}"',
                f'Try: mamfast libation search "title:{query}"',
                "Use Lucene query syntax for advanced searches",
            ]
        )
    else:
        console.print(f"  [red]✗[/] Search failed: {result.error_message or result.stderr}")
        return 1

    return 0


def cmd_libation_export(args: argparse.Namespace) -> int:
    """Export Libation library data."""
    from mamfast.config import reload_settings

    output_path = Path(args.output)
    format_type = args.format

    print_libation_header(
        "Export Library",
        f"Exporting your library to {format_type.upper()}",
    )

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        console.print(f"[red]✗ Configuration error:[/] {e}")
        return 1

    container = settings.libation_container

    if args.dry_run:
        console.print("[yellow]Would export to:[/]")
        console.print(f"  {output_path}")
        return 0

    console.print(f"[bold]Exporting library to {output_path}...[/]")

    # Map format to flag
    format_flags = {"json": "-j", "csv": "-c", "xlsx": "-x"}
    flag = format_flags.get(format_type, "-j")

    # Export to container temp path first
    container_path = f"/tmp/mamfast_export.{format_type}"
    result = _run_libation_cmd(container, "export", "-p", container_path, flag)

    if not result.success:
        console.print(f"  [red]✗[/] Export failed: {result.error_message or result.stderr}")
        return 1

    # Copy from container to host
    try:
        docker("cp", f"{container}:{container_path}", str(output_path), timeout=30)
        console.print(f"  [green]✓[/] Exported to: {output_path}")

        # Show file size
        if output_path.exists():
            size = output_path.stat().st_size
            size_str = f"{size / 1024:.1f} KB" if size > 1024 else f"{size} bytes"
            console.print(f"  [dim]Size: {size_str}[/]")

    except CmdError as e:
        console.print(f"  [red]✗[/] Failed to copy export: {e}")
        return 1
    finally:
        # Cleanup
        with contextlib.suppress(CmdError):
            docker("exec", container, "rm", "-f", container_path, timeout=10)

    return 0


def cmd_libation_settings(args: argparse.Namespace) -> int:
    """View Libation settings."""
    from mamfast.config import reload_settings

    print_libation_header(
        "Libation Settings",
        "Current configuration of your Libation installation",
    )

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        console.print(f"[red]✗ Configuration error:[/] {e}")
        return 1

    container = settings.libation_container

    # Check for specific setting
    setting_name = getattr(args, "setting", None)

    console.print("[bold]Fetching settings...[/]")

    cmd_args = ["get-setting"]
    if getattr(args, "list_enum", False):
        cmd_args.append("-l")
    if setting_name:
        cmd_args.append(setting_name)

    result = _run_libation_cmd(container, *cmd_args)

    if result.success:
        console.print()
        if result.stdout:
            # Parse and display settings nicely
            lines = result.stdout.strip().split("\n")

            if setting_name:
                # Single setting
                console.print(Panel(result.stdout.strip(), title=f"Setting: {setting_name}"))
            else:
                # Create a nice table for all settings
                table = Table(
                    title="Libation Settings",
                    show_header=True,
                    header_style="bold cyan",
                )
                table.add_column("Setting", style="cyan")
                table.add_column("Value")

                # Parse the table output from Libation
                for line in lines:
                    if "|" in line and "---" not in line:
                        parts = [p.strip() for p in line.split("|") if p.strip()]
                        if len(parts) >= 2:
                            table.add_row(parts[0], parts[1])

                console.print(table)

        console.print()
        print_hint_box(
            [
                "mamfast libation settings FileTemplate → View specific setting",
                "mamfast libation settings --list-enum  → Show enum options",
                "Override at runtime: -o SettingName=Value",
            ]
        )
    else:
        console.print(f"  [red]✗[/] Failed to get settings: {result.error_message}")
        return 1

    return 0


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
        ("scan", "Check Audible for new purchases", "mamfast libation scan"),
        ("liberate", "Download pending audiobooks", "mamfast libation liberate"),
        ("books", "List your audiobook library", "mamfast libation books --status pending"),
        ("redownload", "Re-download specific book(s)", "mamfast libation redownload B0XXX"),
        ("status", "Show library status dashboard", "mamfast libation status"),
        ("search", "Search your library", 'mamfast libation search "Sanderson"'),
        ("export", "Export library to file", "mamfast libation export -o lib.json"),
        ("set-status", "Update book download status", "mamfast libation set-status -n"),
        ("convert", "Convert M4B to MP3", "mamfast libation convert"),
        ("settings", "View Libation configuration", "mamfast libation settings"),
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
                "  [green]$[/] mamfast libation scan --liberate\n"
                "  [dim]Scans AND downloads in one step[/]\n\n"
                "[bold]Manual Workflow:[/]\n"
                "  [green]$[/] mamfast libation scan      [dim]# Check for new books[/]\n"
                "  [green]$[/] mamfast libation status    [dim]# See what's pending[/]\n"
                "  [green]$[/] mamfast libation liberate  [dim]# Download pending[/]\n\n"
                "[bold]Download Specific Book:[/]\n"
                "  [green]$[/] mamfast libation liberate --asin B0DK9T5P28\n\n"
                "[bold]Re-download a Book:[/]\n"
                "  [green]$[/] mamfast libation redownload B0DK9T5P28\n\n"
                "[bold]List Your Books:[/]\n"
                "  [green]$[/] mamfast libation books --status pending"
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


# =============================================================================
# Additional Commands
# =============================================================================


def cmd_libation_books(args: argparse.Namespace) -> int:
    """List audiobooks in Libation library with filtering."""
    from mamfast.config import reload_settings

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
                "mamfast libation books --limit 100",
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
            "mamfast libation books --status pending  → Show only pending downloads",
            "mamfast libation books --author Sanderson → Filter by author",
            "mamfast libation books --show-asin       → Show ASIN column",
            "mamfast libation redownload <ASIN>       → Re-download a specific book",
        ],
        title="🔍 Filter Tips",
    )

    return 0


def cmd_libation_redownload(args: argparse.Namespace) -> int:
    """Re-download specific audiobook(s) by marking as NotLiberated and liberating."""
    from mamfast.config import reload_settings

    asins = args.asins
    skip_confirm = getattr(args, "yes", False)

    print_libation_header(
        "🔄 Re-download Audiobooks",
        f"Re-downloading {len(asins)} book(s)",
        dry_run=args.dry_run,
        hint="This marks books for re-download and liberates them",
    )

    if not args.dry_run:
        print_hint_box(
            [
                "This will mark the book(s) as 'Not Downloaded' then liberate them",
                "Useful when files are corrupted or you want a fresh copy",
                "Original files may be overwritten based on Libation settings",
                "Use --yes / -y to skip confirmation prompt",
            ]
        )

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        console.print(f"[red]✗ Configuration error:[/] {e}")
        return 1

    container = settings.libation_container

    if args.dry_run:
        console.print("[yellow]Would execute:[/]")
        for asin in asins:
            console.print(f"  1. Mark {asin} as 'Not Downloaded'")
            console.print(f"  2. Liberate (download) {asin}")
        return 0

    # Verify ASINs exist
    console.print("[bold]Verifying books...[/]")
    book_info: list[str] = []
    try:
        books = _export_library(container)
        asin_to_book = {str(b.get("AudibleProductId", "")): b for b in books}

        for asin in asins:
            if asin not in asin_to_book:
                console.print(f"  [red]✗[/] ASIN '{asin}' not found in library")
                return 1
            book = asin_to_book[asin]
            title = book.get("Title", "Unknown")
            subtitle = book.get("Subtitle", "")
            author = book.get("AuthorNames", "Unknown")
            full_title = f"{title}: {subtitle}" if subtitle and subtitle not in title else title
            book_info.append(f"{full_title} by {author}")
            console.print(f"  [green]✓[/] Found: {full_title} by {author}")

    except Exception as e:
        console.print(f"  [yellow]![/] Could not verify ASINs: {e}")
        console.print("  [dim]Proceeding anyway...[/]")

    # Confirmation prompt (unless --yes or dry-run)
    if not skip_confirm:
        console.print()
        if not Confirm.ask(
            f"[yellow]Re-download {len(asins)} book(s)?[/] This will overwrite existing files"
        ):
            console.print("[dim]Cancelled.[/]")
            return 0

    # Step 1: Mark as Not Downloaded
    console.print("\n[bold]Step 1: Marking as 'Not Downloaded'...[/]")
    for asin in asins:
        result = _run_libation_cmd(container, "set-status", "-n", "-f", asin, timeout=60)
        if result.success:
            console.print(f"  [green]✓[/] Marked {asin}")
        else:
            console.print(f"  [red]✗[/] Failed to mark {asin}: {result.error_message}")
            return 1

    # Step 2: Liberate
    console.print("\n[bold]Step 2: Downloading...[/]")
    for asin in asins:
        with console.status(f"  Downloading {asin}...", spinner="dots"):
            result = _run_libation_cmd(
                container,
                "liberate",
                asin,
                timeout=7200,  # 2 hour timeout per book
            )

        if result.returncode == 0:
            console.print(f"  [green]✓[/] Downloaded {asin}")
            if result.stdout and "Completed:" in result.stdout:
                console.print(f"    [dim]{result.stdout.split('Completed:')[-1].strip()[:60]}[/]")
        else:
            console.print(f"  [red]✗[/] Failed to download {asin}")
            if result.stderr:
                console.print(f"    [dim]{result.stderr[:100]}[/]")

    console.print("\n[green]✓[/] Re-download complete!")

    # Save log
    log_path = _save_libation_log("redownload", str(asins), "")
    console.print(f"[dim]Log saved: {log_path}[/]")

    return 0


def cmd_libation_set_status(args: argparse.Namespace) -> int:
    """Set download status for books in library."""
    from mamfast.config import reload_settings

    mark_downloaded = getattr(args, "downloaded", False)
    mark_not_downloaded = getattr(args, "not_downloaded", False)
    force = getattr(args, "force", False)
    asins = getattr(args, "asins", [])
    skip_confirm = getattr(args, "yes", False)

    if not mark_downloaded and not mark_not_downloaded:
        console.print("[red]✗[/] Must specify --downloaded (-d) or --not-downloaded (-n)")
        return 1

    action_desc = []
    if mark_downloaded:
        action_desc.append("mark existing as 'Downloaded'")
    if mark_not_downloaded:
        action_desc.append("mark missing as 'Not Downloaded'")

    # Determine scope description for confirmation
    scope = f"{len(asins)} book(s)" if asins else "ALL books in library"

    print_libation_header(
        "📋 Set Book Status",
        f"Will {' and '.join(action_desc)}",
        dry_run=args.dry_run,
    )

    if not args.dry_run:
        print_hint_box(
            [
                "-d/--downloaded: Mark books WITH audio files as 'Downloaded'",
                "-n/--not-downloaded: Mark books WITHOUT files as 'Not Downloaded'",
                "--force: Set status regardless of file existence",
                "Use --yes / -y to skip confirmation prompt",
            ]
        )

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        console.print(f"[red]✗ Configuration error:[/] {e}")
        return 1

    container = settings.libation_container

    # Build command args
    cmd_args = ["set-status"]
    if mark_downloaded:
        cmd_args.append("-d")
    if mark_not_downloaded:
        cmd_args.append("-n")
    if force:
        cmd_args.append("-f")
    cmd_args.extend(asins)

    if args.dry_run:
        console.print("[yellow]Would execute:[/]")
        console.print(f"  docker exec {container} /libation/LibationCli {' '.join(cmd_args)}")
        return 0

    # Confirmation prompt for potentially destructive operation
    if not skip_confirm and not asins:
        # Only prompt when affecting ALL books (no specific ASINs)
        console.print()
        if not Confirm.ask(
            f"[yellow]Update status for {scope}?[/] This modifies Libation's database"
        ):
            console.print("[dim]Cancelled.[/]")
            return 0

    console.print("[bold]Updating status...[/]")
    with console.status("  Processing library...", spinner="dots"):
        result = _run_libation_cmd(container, *cmd_args, timeout=settings.libation.command_timeout)

    if result.success:
        console.print("  [green]✓[/] Status updated")
        if result.stdout:
            for line in result.stdout.strip().split("\n")[:5]:
                if line.strip():
                    console.print(f"  [dim]{line.strip()}[/]")
    else:
        console.print(f"  [red]✗[/] Failed: {result.error_message or result.stderr}")
        return 1

    return 0


def cmd_libation_convert(args: argparse.Namespace) -> int:
    """Convert M4B audiobooks to MP3 format."""
    from mamfast.config import reload_settings

    asins = getattr(args, "asins", [])

    print_libation_header(
        "🔊 Convert to MP3",
        f"Converting {len(asins) if asins else 'all'} audiobook(s)",
        dry_run=args.dry_run,
        hint="Converts M4B (AAC) to MP3 format",
    )

    if not args.dry_run:
        print_hint_box(
            [
                "Converts downloaded M4B files to MP3 format",
                "Conversion settings are in Libation config (bitrate, etc.)",
                "Specify ASINs to convert specific books, or omit for all",
            ]
        )

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        console.print(f"[red]✗ Configuration error:[/] {e}")
        return 1

    container = settings.libation_container

    cmd_args = ["convert"]
    cmd_args.extend(asins)

    if args.dry_run:
        console.print("[yellow]Would execute:[/]")
        console.print(f"  docker exec {container} /libation/LibationCli {' '.join(cmd_args)}")
        return 0

    console.print("[bold]Converting audiobooks...[/]")
    with console.status("  Converting (this may take a while)...", spinner="dots"):
        result = _run_libation_cmd(container, *cmd_args, timeout=settings.libation.liberate_timeout)

    if result.returncode == 0:
        console.print("  [green]✓[/] Conversion complete")
        if result.stdout:
            for line in result.stdout.strip().split("\n")[-5:]:
                if line.strip():
                    console.print(f"  [dim]{line.strip()}[/]")
    else:
        console.print(f"  [red]✗[/] Conversion failed: {result.error_message}")
        if result.stderr:
            console.print(f"  [dim]{result.stderr[:200]}[/]")
        return 1

    return 0


# =============================================================================
# Helper Functions
# =============================================================================


def _save_libation_log(command: str, stdout: str, stderr: str) -> Path:
    """Save Libation command output to log file."""
    libation_log_dir = log_dir() / "libation"
    libation_log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    log_path = libation_log_dir / f"{command}_{timestamp}.log"

    content = f"Command: {command}\n"
    content += f"Timestamp: {datetime.now(UTC).isoformat()}\n"
    content += "\n--- STDOUT ---\n"
    content += stdout or "(empty)"
    content += "\n\n--- STDERR ---\n"
    content += stderr or "(empty)"

    log_path.write_text(content)
    return log_path


# =============================================================================
# CLI Parser Setup
# =============================================================================


def add_libation_parser(subparsers: Any) -> None:
    """Add the libation command group to the CLI parser."""
    # Main libation parser
    libation_parser = subparsers.add_parser(
        "libation",
        help="Libation audiobook manager integration",
        description="Manage your Audible audiobook library through Libation",
        epilog="""
Examples:
  mamfast libation                    Show library status (default)
  mamfast libation scan               Check Audible for new purchases
  mamfast libation scan --liberate    Scan and download new books
  mamfast libation liberate           Download all pending audiobooks
  mamfast libation search "Sanderson" Search your library
  mamfast libation export -o lib.json Export library to JSON
  mamfast libation guide              Show detailed integration guide

Tip: Use 'mamfast --dry-run libation <cmd>' to preview without changes.
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    libation_parser.set_defaults(func=cmd_libation, libation_func=None)

    # Libation subcommands
    libation_sub = libation_parser.add_subparsers(
        dest="libation_cmd",
        title="commands",
        metavar="<command>",
    )

    # -------------------------------------------------------------------------
    # scan: Scan Audible library
    # -------------------------------------------------------------------------
    scan_parser = libation_sub.add_parser(
        "scan",
        help="Scan Audible library for new purchases",
        description=(
            "Check your Audible account for new book purchases and add them to Libation's database."
        ),
        epilog="""
What this does:
  1. Connects to Audible API via your saved credentials
  2. Compares your purchases against Libation's database
  3. NEW books are added with status 'NotLiberated' (pending download)

Note: This does NOT download any books. Use 'liberate' or '--liberate' for that.

Examples:
  mamfast libation scan              Scan only
  mamfast libation scan --liberate   Scan and download new books
""",
    )
    scan_parser.add_argument(
        "--liberate",
        action="store_true",
        help="Also download new books after scanning",
    )
    scan_parser.set_defaults(libation_func=cmd_libation_scan)

    # -------------------------------------------------------------------------
    # liberate: Download audiobooks
    # -------------------------------------------------------------------------
    liberate_parser = libation_sub.add_parser(
        "liberate",
        help="Download and decrypt pending audiobooks",
        description="Download all audiobooks marked as 'NotLiberated' from your Audible library.",
        epilog="""
What this does:
  1. Finds all books with status 'NotLiberated'
  2. Downloads encrypted audio from Audible
  3. Decrypts to M4B format
  4. Saves to your configured Books folder

Examples:
  mamfast libation liberate                    Download all pending
  mamfast libation liberate --asin B0DK9T5P28  Download specific book
  mamfast libation liberate --force            Re-download existing books
""",
    )
    liberate_parser.add_argument(
        "--asin",
        type=validate_asin,
        metavar="ASIN",
        help="Download only this specific book (Audible ASIN, e.g., B0DK9T5P28)",
    )
    liberate_parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force re-download even if already liberated",
    )
    liberate_parser.set_defaults(libation_func=cmd_libation_liberate)

    # -------------------------------------------------------------------------
    # status: Show library status
    # -------------------------------------------------------------------------
    status_parser = libation_sub.add_parser(
        "status",
        help="Show library status and statistics",
        description="Display a dashboard of your Libation library status.",
    )
    status_parser.set_defaults(libation_func=cmd_libation_status)

    # -------------------------------------------------------------------------
    # search: Search library
    # -------------------------------------------------------------------------
    search_parser = libation_sub.add_parser(
        "search",
        help="Search your audiobook library",
        description="Search for books in your Libation library using Lucene query syntax.",
        epilog="""
Search syntax (Lucene):
  title:Mistborn          Search by title
  author:Sanderson        Search by author
  "exact phrase"          Exact phrase match
  fantasy AND epic        Boolean operators

Examples:
  mamfast libation search "Brandon Sanderson"
  mamfast libation search "title:Way of Kings"
  mamfast libation search "author:Reki" --limit 50
""",
    )
    search_parser.add_argument(
        "query",
        type=str,
        help="Search query (Lucene syntax supported)",
    )
    search_parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=20,
        help="Maximum results to show (default: 20)",
    )
    search_parser.set_defaults(libation_func=cmd_libation_search)

    # -------------------------------------------------------------------------
    # export: Export library data
    # -------------------------------------------------------------------------
    export_parser = libation_sub.add_parser(
        "export",
        help="Export library data to file",
        description="Export your Libation library to JSON, CSV, or Excel format.",
    )
    export_parser.add_argument(
        "-o",
        "--output",
        type=str,
        required=True,
        metavar="PATH",
        help="Output file path",
    )
    export_parser.add_argument(
        "--format",
        "-f",
        choices=["json", "csv", "xlsx"],
        default="json",
        help="Export format (default: json)",
    )
    export_parser.set_defaults(libation_func=cmd_libation_export)

    # -------------------------------------------------------------------------
    # settings: View settings
    # -------------------------------------------------------------------------
    settings_parser = libation_sub.add_parser(
        "settings",
        help="View Libation configuration settings",
        description="Display current Libation settings and configuration.",
    )
    settings_parser.add_argument(
        "setting",
        nargs="?",
        type=str,
        help="Specific setting name to view (optional)",
    )
    settings_parser.add_argument(
        "--list-enum",
        "-l",
        action="store_true",
        help="Show all possible values for enum settings",
    )
    settings_parser.set_defaults(libation_func=cmd_libation_settings)

    # -------------------------------------------------------------------------
    # books: List audiobooks with filtering
    # -------------------------------------------------------------------------
    books_parser = libation_sub.add_parser(
        "books",
        help="List audiobooks in your library",
        description="Display your audiobook library with optional filtering by status or author.",
        epilog="""
Status filter options:
  liberated / downloaded   Books that have been downloaded
  pending / notliberated   Books waiting to be downloaded
  error / failed           Books that failed to download

Examples:
  mamfast libation books                        List all books
  mamfast libation books --status pending       Show only pending downloads
  mamfast libation books --author "Sanderson"   Filter by author name
  mamfast libation books --limit 100            Show more results
  mamfast libation books --show-asin            Include ASIN column
""",
    )
    books_parser.add_argument(
        "--status",
        "-s",
        type=str,
        choices=["liberated", "downloaded", "pending", "notliberated", "error", "failed"],
        help="Filter by book status",
    )
    books_parser.add_argument(
        "--author",
        "-a",
        type=str,
        help="Filter by author name (partial match)",
    )
    books_parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=50,
        help="Maximum books to display (default: 50)",
    )
    books_parser.add_argument(
        "--show-asin",
        action="store_true",
        help="Show ASIN column in output",
    )
    books_parser.set_defaults(libation_func=cmd_libation_books)

    # -------------------------------------------------------------------------
    # redownload: Re-download specific books
    # -------------------------------------------------------------------------
    redownload_parser = libation_sub.add_parser(
        "redownload",
        help="Re-download specific audiobook(s)",
        description=(
            "Mark audiobook(s) as 'Not Downloaded' and then liberate them again. "
            "Useful when files are corrupted or you want a fresh download."
        ),
        epilog="""
This performs two steps:
  1. Marks the book as 'Not Downloaded' (set-status -n -f)
  2. Liberates (downloads) the book

Examples:
  mamfast libation redownload B0DK9T5P28
  mamfast libation redownload B0DK9T5P28 B0ABC1234X
  mamfast --dry-run libation redownload B0DK9T5P28
""",
    )
    redownload_parser.add_argument(
        "asins",
        nargs="+",
        type=validate_asin,
        metavar="ASIN",
        help="One or more book ASINs to re-download (e.g., B0DK9T5P28)",
    )
    redownload_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    redownload_parser.set_defaults(libation_func=cmd_libation_redownload)

    # -------------------------------------------------------------------------
    # set-status: Set download status for books
    # -------------------------------------------------------------------------
    set_status_parser = libation_sub.add_parser(
        "set-status",
        help="Set download status for books",
        description=(
            "Update download status based on whether audio files exist. "
            "Useful for syncing Libation's database with actual file state."
        ),
        epilog="""
Examples:
  mamfast libation set-status -d              Mark existing files as Downloaded
  mamfast libation set-status -n              Mark missing files as Not Downloaded
  mamfast libation set-status -d -n           Both operations
  mamfast libation set-status -n -f B0DK9T5P28   Force mark specific book
""",
    )
    set_status_parser.add_argument(
        "-d",
        "--downloaded",
        action="store_true",
        help="Mark books WITH audio files as 'Downloaded'",
    )
    set_status_parser.add_argument(
        "-n",
        "--not-downloaded",
        action="store_true",
        help="Mark books WITHOUT audio files as 'Not Downloaded'",
    )
    set_status_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force set status regardless of file existence",
    )
    set_status_parser.add_argument(
        "asins",
        nargs="*",
        type=validate_asin,
        metavar="ASIN",
        help="Specific book ASINs (optional, default: all books)",
    )
    set_status_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    set_status_parser.set_defaults(libation_func=cmd_libation_set_status)

    # -------------------------------------------------------------------------
    # convert: Convert M4B to MP3
    # -------------------------------------------------------------------------
    convert_parser = libation_sub.add_parser(
        "convert",
        help="Convert M4B audiobooks to MP3",
        description="Convert M4B (AAC) audiobook files to MP3 format.",
        epilog="""
Conversion settings (bitrate, mono/stereo, etc.) are configured in Libation.
Use 'mamfast libation settings' to view current settings.

Examples:
  mamfast libation convert                    Convert all books
  mamfast libation convert B0DK9T5P28         Convert specific book
""",
    )
    convert_parser.add_argument(
        "asins",
        nargs="*",
        type=validate_asin,
        metavar="ASIN",
        help="Specific book ASINs to convert (optional, default: all)",
    )
    convert_parser.set_defaults(libation_func=cmd_libation_convert)

    # -------------------------------------------------------------------------
    # guide: Detailed tutorial/guide
    # -------------------------------------------------------------------------
    guide_parser = libation_sub.add_parser(
        "guide",
        help="Show detailed tutorial and integration guide",
        description="Comprehensive guide to using Libation with MAMFast.",
    )
    guide_parser.set_defaults(libation_func=cmd_libation_guide)
