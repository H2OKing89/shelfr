"""State management CLI commands.

Provides operator tools for managing processed.json state:
- list: View processed/failed entries
- prune: Remove stale entries
- retry: Clear failed entry for re-processing
- clear: Remove processed entry for full re-run
"""

from __future__ import annotations

import argparse
import json
import logging
from typing import Any

from mamfast.console import console, print_error, print_info, print_success, print_warning
from mamfast.utils.state import (
    clear_failed,
    find_stale_entries,
    get_stats,
    is_failed,
    is_processed,
    load_state,
    prune_stale_entries,
    update_state,
)

logger = logging.getLogger(__name__)


def cmd_state_list(args: argparse.Namespace) -> int:
    """List state entries (processed and/or failed).

    Displays processed and/or failed entries from the state file with
    optional filtering and output format control.

    Args:
        args: Parsed command-line arguments with the following fields:
            - processed (bool): If True, show only processed entries.
            - failed (bool): If True, show only failed entries.
            - limit (int | None): Maximum number of entries to display.
            - json (bool): If True, output as JSON instead of formatted text.

    Returns:
        int: Exit code. 0 on success, non-zero on error.

    Raises:
        StateCorruptionError: If the state file is corrupt and unrecoverable.
        StateLockError: If unable to acquire state file lock.
        OSError: If state file cannot be read due to permissions or IO error.
    """
    state = load_state()
    stats = get_stats()

    # Determine what to show
    show_processed = args.processed or (not args.failed)
    show_failed = args.failed or (not args.processed)

    if args.json:
        # Machine-readable output
        output = {}
        if show_processed:
            output["processed"] = state.get("processed", {})
        if show_failed:
            output["failed"] = state.get("failed", {})
        output["stats"] = stats
        console.print_json(json.dumps(output, indent=2, default=str))
        return 0

    # Human-readable output
    console.print()
    console.print("[bold]State Summary[/bold]")
    console.print(f"  Processed: [green]{stats['processed']}[/green]")
    console.print(f"  Failed: [red]{stats['failed']}[/red]")
    console.print()

    limit = args.limit or 20

    if show_processed and stats["processed"] > 0:
        count = min(limit, stats["processed"])
        console.print(f"[bold cyan]Processed Entries[/bold cyan] (most recent {count})")
        console.print()

        # Sort by processed_at descending
        processed = state.get("processed", {})
        sorted_entries = sorted(
            processed.items(),
            key=lambda x: x[1].get("processed_at", ""),
            reverse=True,
        )[:limit]

        for identifier, entry in sorted_entries:
            title = entry.get("title", "Unknown")
            status = entry.get("status", "COMPLETE")
            processed_at = entry.get("processed_at", "")[:10]  # Just date
            console.print(f"  [dim]{identifier}[/dim]")
            console.print(f"    {title} | [cyan]{status}[/cyan] | {processed_at}")

        if stats["processed"] > limit:
            console.print(f"\n  [dim]... and {stats['processed'] - limit} more[/dim]")
        console.print()

    if show_failed and stats["failed"] > 0:
        console.print(
            f"[bold red]Failed Entries[/bold red] (most recent {min(limit, stats['failed'])})"
        )
        console.print()

        # Sort by failed_at descending
        failed = state.get("failed", {})
        sorted_entries = sorted(
            failed.items(),
            key=lambda x: x[1].get("failed_at", ""),
            reverse=True,
        )[:limit]

        for identifier, entry in sorted_entries:
            title = entry.get("title", "Unknown")
            error = entry.get("error", "Unknown error")[:50]
            retry_count = entry.get("retry_count", 0)
            failed_at = entry.get("failed_at", "")[:10]  # Just date
            console.print(f"  [dim]{identifier}[/dim]")
            console.print(f"    {title}")
            console.print(f"    [red]{error}[/red] | retries: {retry_count} | {failed_at}")

        if stats["failed"] > limit:
            console.print(f"\n  [dim]... and {stats['failed'] - limit} more[/dim]")
        console.print()

    return 0


def cmd_state_prune(args: argparse.Namespace) -> int:
    """Prune stale entries from state."""
    dry_run = args.dry_run

    # Find stale entries
    stale = find_stale_entries()

    if not stale:
        print_success("No stale entries found")
        return 0

    # Group by identifier for display
    stale_by_id: dict[str, list[tuple[str, str, str]]] = {}
    for identifier, title, status, missing in stale:
        if identifier not in stale_by_id:
            stale_by_id[identifier] = []
        stale_by_id[identifier].append((title, status, missing))

    console.print(f"\n[bold]Stale Entries Found: {len(stale_by_id)}[/bold]\n")

    for identifier, issues in stale_by_id.items():
        title = issues[0][0]
        status = issues[0][1]
        missing_paths = [i[2] for i in issues]

        console.print(f"  [dim]{identifier}[/dim]")
        console.print(f"    {title} | [cyan]{status}[/cyan]")
        console.print(f"    Missing: [red]{', '.join(missing_paths)}[/red]")

    console.print()

    if dry_run:
        print_warning(f"Would remove {len(stale_by_id)} stale entries (dry-run)")
        return 0

    # Actually prune
    removed = prune_stale_entries(dry_run=False)
    print_success(f"Removed {len(removed)} stale entries")

    return 0


def cmd_state_retry(args: argparse.Namespace) -> int:
    """Clear a failed entry to allow re-processing."""
    identifier = args.asin
    dry_run = args.dry_run

    if not is_failed(identifier):
        print_info(f"Not found in failed state: {identifier}")
        return 0  # Not an error - graceful handling

    if dry_run:
        print_warning(f"Would clear failed entry: {identifier} (dry-run)")
        return 0

    if clear_failed(identifier):
        print_success(f"Cleared failed state for: {identifier}")
        print_info("The release will be re-processed on next run")
    else:
        print_error(f"Failed to clear: {identifier}")
        return 1

    return 0


def cmd_state_clear(args: argparse.Namespace) -> int:
    """Clear a processed entry to force full re-run."""
    identifier = args.asin
    dry_run = args.dry_run

    if not is_processed(identifier):
        print_info(f"Not found in processed state: {identifier}")
        return 0  # Not an error - graceful handling

    if dry_run:
        print_warning(f"Would clear processed entry: {identifier} (dry-run)")
        return 0

    def _clear(state: dict[str, Any]) -> None:
        if identifier in state.get("processed", {}):
            del state["processed"][identifier]
            logger.info("Cleared processed state for: %s", identifier)

    update_state(_clear)
    print_success(f"Cleared processed state for: {identifier}")
    print_info("The release will be fully re-processed on next run")

    return 0


def cmd_state_export(args: argparse.Namespace) -> int:
    """Export state to JSON file."""
    from pathlib import Path

    state = load_state()
    output_path = args.output

    if output_path:
        try:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            print_success(f"Exported state to: {output_path}")
        except OSError as e:
            logger.exception("Failed to export state to %s", output_path)
            print_error(f"Failed to export state: {e}")
            return 1
    else:
        console.print_json(json.dumps(state, indent=2, default=str))

    return 0


# Dispatch table for state subcommands
STATE_COMMANDS = {
    "list": cmd_state_list,
    "prune": cmd_state_prune,
    "retry": cmd_state_retry,
    "clear": cmd_state_clear,
    "export": cmd_state_export,
}


def cmd_state(args: argparse.Namespace) -> int:
    """Dispatch to state subcommand."""
    subcommand = getattr(args, "state_command", None)

    if not subcommand:
        print_error("No state subcommand specified. Use: list, prune, retry, clear, export")
        return 1

    handler = STATE_COMMANDS.get(subcommand)
    if not handler:
        print_error(f"Unknown state subcommand: {subcommand}")
        return 1

    return handler(args)
