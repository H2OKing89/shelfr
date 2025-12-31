"""Management commands: redownload, set-status, convert.

These commands manage book status and redownload/conversion.
"""

from __future__ import annotations

import argparse
import logging
from datetime import UTC, datetime
from pathlib import Path

from rich.prompt import Confirm

from shelfr.console import console
from shelfr.paths import log_dir
from shelfr.ui.icons import get_icons

from ._common import (
    export_library as _export_library,
)
from ._common import (
    run_libation_cmd as _run_libation_cmd,
)
from ._ui import print_hint_box, print_libation_header

logger = logging.getLogger(__name__)


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


def cmd_libation_redownload(args: argparse.Namespace) -> int:
    """Re-download specific audiobook(s) by marking as NotLiberated and liberating."""
    from shelfr.config import reload_settings
    from shelfr.libation import run_liberate_with_progress

    asins = args.asins
    skip_confirm = getattr(args, "yes", False)

    print_libation_header(
        "↻ Re-download Audiobooks",
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
        result = _run_libation_cmd(
            container, "set-status", "-n", "-f", asin, timeout=settings.libation.command_timeout
        )
        if result.success:
            console.print(f"  [green]✓[/] Marked {asin}")
        else:
            console.print(f"  [red]✗[/] Failed to mark {asin}: {result.error_message}")
            return 1

    # Step 2: Liberate
    # Use run_liberate_with_progress which supports verbose mode (-v)
    # In verbose mode: TTY passthrough shows Libation's native progress bar
    # In normal mode: Clean spinner output
    verbose = getattr(args, "verbose", False)
    console.print("\n[bold]Step 2: Downloading...[/]")
    for asin in asins:
        liberate_result = run_liberate_with_progress(
            pending_count=1,
            console=console,
            verbose=verbose,
            asin=asin,
        )

        if liberate_result.success:
            console.print(f"  [green]✓[/] Downloaded {asin}")
            if liberate_result.log_path:
                # Extract completion info from log if available
                try:
                    log_content = Path(liberate_result.log_path).read_text()
                    if "Completed:" in log_content:
                        completed_line = log_content.split("Completed:")[-1].split("\n")[0].strip()
                        console.print(f"    [dim]{completed_line[:60]}[/]")
                except Exception:
                    pass
        else:
            console.print(f"  [red]✗[/] Failed to download {asin}")
            if liberate_result.error_message:
                console.print(f"    [dim]{liberate_result.error_message[:100]}[/]")

    console.print("\n[green]✓[/] Re-download complete!")

    # Save log
    log_path = _save_libation_log("redownload", str(asins), "")
    console.print(f"[dim]Log saved: {log_path}[/]")

    return 0


def cmd_libation_set_status(args: argparse.Namespace) -> int:
    """Set download status for books in library."""
    from shelfr.config import reload_settings

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

    icons = get_icons()
    print_libation_header(
        f"{icons.update} Set Book Status",
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
    from shelfr.config import reload_settings

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


__all__ = [
    "cmd_libation_convert",
    "cmd_libation_redownload",
    "cmd_libation_set_status",
]
