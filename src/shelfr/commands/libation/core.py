"""Core Libation commands: scan, liberate, status.

These are the primary commands for managing Libation library.
"""

from __future__ import annotations

import argparse
import logging
import re

from shelfr.console import console
from shelfr.utils.cmd import CmdError, docker

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


def _build_override_args(overrides: list[str] | None) -> list[str]:
    """Build Libation CLI override arguments from a list of KEY=VALUE strings.

    Args:
        overrides: List of override strings like ["FileDownloadQuality=Normal", "UseWidevine=true"]

    Returns:
        List of CLI arguments like ["-o", "FileDownloadQuality=Normal", "-o", "UseWidevine=true"]
    """
    if not overrides:
        return []
    result: list[str] = []
    for override in overrides:
        result.extend(["-o", override])
    return result


def _check_container_health(container: str) -> tuple[bool, str | None]:
    """Check if Libation container is running and mounts are healthy.

    This detects common issues like stale file handles on UNRAID after array restarts.

    Args:
        container: Name of the Docker container

    Returns:
        Tuple of (is_healthy, error_message). error_message is None if healthy.
    """
    # Check if container is running
    try:
        result = docker("container", "inspect", "-f", "{{.State.Running}}", container, timeout=10)
        if result.stdout.strip().lower() != "true":
            return False, f"Container '{container}' exists but is not running"
    except CmdError as e:
        err_msg = e.stderr[:100] if e.stderr else "unknown error"
        return False, f"Container '{container}' not found: {err_msg}"

    # Check if /data mount is accessible (common Libation mount point)
    # This catches stale file handles that occur on UNRAID after array restarts
    try:
        docker("exec", container, "ls", "/data", timeout=10)
    except CmdError as e:
        error_msg = e.stderr or ""
        if "stale" in error_msg.lower() or "cannot access" in error_msg.lower():
            return False, (
                "Container mounts appear stale (common after UNRAID array restart). "
                f"Try: docker restart {container}"
            )
        # If /data doesn't exist, that's a config issue but not a health issue
        logger.debug("Could not list /data in container (may not exist): %s", e)

    return True, None


def cmd_libation_scan(args: argparse.Namespace) -> int:
    """Scan Audible library for new books."""
    from shelfr.config import reload_settings

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
                "Use 'shelfr libation liberate' to download pending books",
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
    overrides = getattr(args, "overrides", None)
    override_str = " ".join(f"-o {o}" for o in (overrides or []))

    if args.dry_run:
        console.print("[yellow]Would execute:[/]")
        cmd = f"docker exec {container} /libation/LibationCli scan"
        if override_str:
            cmd += f" {override_str}"
        console.print(f"  {cmd}")
        if args.liberate:
            cmd = f"docker exec {container} /libation/LibationCli liberate"
            if override_str:
                cmd += f" {override_str}"
            console.print(f"  {cmd}")
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
    override_args = _build_override_args(overrides)
    if override_args:
        console.print(f"  [dim]Using overrides: {', '.join(overrides or [])}[/]")
    with console.status("  Querying Audible API...", spinner="dots"):
        result = _run_libation_cmd(
            container, "scan", *override_args, timeout=settings.libation.scan_timeout
        )

    if result.success:
        console.print("  [green]✓[/] Scan complete")

        # Parse scan output for "New: X" count
        new_match = re.search(r"New:\s*(\d+)", result.stdout)
        new_count = 0
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

        # Explain "New: 0" confusion for novice users (common misconception)
        if new_count == 0 and pending > 0:
            console.print()
            print_hint_box(
                [
                    "'New: 0' means no NEW purchases were found on Audible",
                    f"But you have {pending} book(s) still waiting to download!",
                    "These are from previous scans that weren't liberated yet",
                    "Run 'shelfr libation liberate' to download them",
                ],
                title="💡 Understanding 'New: 0'",
            )

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
                    "[dim]Hint: Run 'shelfr libation liberate' or use '--liberate' flag[/]"
                )

    except Exception as e:
        console.print(f"  [yellow]![/] Could not fetch status: {e}")

    return 0


def cmd_libation_liberate(args: argparse.Namespace) -> int:
    """Download and decrypt pending audiobooks."""
    from shelfr.config import reload_settings
    from shelfr.libation import run_liberate_with_progress

    asin = getattr(args, "asin", None)
    skip_confirm = getattr(args, "yes", False)
    pdf_only_flag = getattr(args, "pdf", False)

    title = "Download PDFs Only" if pdf_only_flag else "Download Audiobooks"
    if asin:
        title = f"Download {'PDF for' if pdf_only_flag else 'Book:'} {asin}"

    subtitle = (
        "Downloading PDFs from Audible"
        if pdf_only_flag
        else "Downloading and decrypting audiobooks from Audible"
    )
    print_libation_header(
        title,
        subtitle,
        dry_run=args.dry_run,
        hint="Downloads go to your configured Libation output folder",
    )

    if not args.dry_run:
        hints = [
            "This downloads ALL pending (NotLiberated) books by default",
            "Use --asin XXXXXX to download a specific book",
            "Use --force to re-download already liberated books",
            "Downloads are saved to Libation's configured Books folder",
            "Use --yes / -y to skip confirmation prompt",
        ]
        if pdf_only_flag:
            hints.insert(0, "PDF-only mode: Only downloading PDF companion files")
        print_hint_box(hints)

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        console.print(f"[red]✗ Configuration error:[/] {e}")
        return 1

    container = settings.libation_container
    overrides = getattr(args, "overrides", None)
    override_str = " ".join(f"-o {o}" for o in (overrides or []))
    pdf_only = getattr(args, "pdf", False)

    if args.dry_run:
        cmd = f"docker exec {container} /libation/LibationCli liberate"
        if pdf_only:
            cmd += " -p"
        if asin:
            cmd += f" {asin}"
        if getattr(args, "force", False):
            cmd += " -f"
        if override_str:
            cmd += f" {override_str}"
        console.print("[yellow]Would execute:[/]")
        console.print(f"  {cmd}")
        return 0

    # Pre-flight health check (catches stale mounts on UNRAID)
    console.print("[bold]Checking Libation container...[/]")
    is_healthy, health_error = _check_container_health(container)
    if not is_healthy:
        console.print(f"  [red]✗[/] {health_error}")
        console.print(f"\n[dim]Hint: Try 'docker restart {container}' to fix stale mounts[/]")
        return 1
    console.print(f"  [green]✓[/] Container '{container}' is healthy")

    # Get current status first
    console.print("\n[bold]Checking pending downloads...[/]")
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
                    "Run 'shelfr libation scan' to check for new purchases",
                    "Use '--force' to re-download existing books",
                ]
            )
            return 0
        else:
            console.print(f"  [cyan]→[/] {pending} book(s) pending download")

    except Exception as e:
        console.print(f"  [yellow]![/] Could not check status: {e}")
        console.print("  [dim]Proceeding with liberate anyway...[/]")
        pending = None  # Unknown

    # Confirmation prompt (unless --yes or dry-run)
    if not skip_confirm and not asin:
        from rich.prompt import Confirm

        console.print()
        if pending is not None and pending > 0:
            # Known count - show specific prompt
            prompt = f"[yellow]Download {pending} pending book(s)?[/] This may take a while"
            if not Confirm.ask(prompt):
                console.print("[dim]Cancelled.[/]")
                return 0
        elif pending is None and not Confirm.ask(
            "[yellow]Download pending books?[/] (count unknown \u2014 may take a while)"
        ):
            # Unknown count - show generic prompt
            console.print("[dim]Cancelled.[/]")
            return 0
        # If pending == 0, no confirmation needed (already handled earlier)

    # Run liberate with progress
    download_type = "PDFs" if pdf_only else ("book" if asin else "audiobooks")
    console.print(f"\n[bold]Downloading {download_type}...[/]")

    # Check for verbose mode
    verbose = getattr(args, "verbose", False)

    # Build extra args for liberate command (flags like -p, -f, -o)
    extra_args: list[str] = []
    if pdf_only:
        extra_args.append("-p")
    if getattr(args, "force", False):
        extra_args.append("-f")
    # Add override args
    override_args = _build_override_args(overrides)
    if override_args:
        console.print(f"  [dim]Using overrides: {', '.join(overrides or [])}[/]")
        extra_args.extend(override_args)

    # Use run_liberate_with_progress which supports verbose mode (-v)
    # In verbose mode: TTY passthrough shows Libation's native progress bar
    # In normal mode: Clean spinner output
    liberate_result = run_liberate_with_progress(
        pending_count=pending if pending else 1,
        console=console,
        verbose=verbose,
        asin=asin,
        extra_args=extra_args if extra_args else None,
    )

    if liberate_result.success:
        console.print("  [green]✓[/] Download complete")

        if liberate_result.downloaded_count > 0:
            console.print(f"  [cyan]→[/] Downloaded {liberate_result.downloaded_count} book(s)")

        if liberate_result.log_path:
            console.print(f"  [dim]Log saved: {liberate_result.log_path}[/]")

    else:
        console.print(f"  [red]✗[/] Download failed (exit code: {liberate_result.returncode})")
        if liberate_result.error_message:
            console.print(f"    [dim]{liberate_result.error_message}[/]")
        return liberate_result.returncode

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
    from shelfr.config import reload_settings

    from ._ui import print_book_table

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
        console.print("\n[dim]Hint: Run 'shelfr libation liberate' to download these books[/]")

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
            "\n[dim]Hint: Use 'shelfr libation liberate --force --asin XXXXX' to retry[/]"
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
            "shelfr libation scan      → Check for new Audible purchases",
            "shelfr libation liberate  → Download pending books",
            "shelfr libation search    → Search your library",
            "shelfr libation export    → Export library data",
        ],
        title="🚀 Quick Actions",
    )

    return 0


__all__ = [
    "cmd_libation_liberate",
    "cmd_libation_scan",
    "cmd_libation_status",
]
