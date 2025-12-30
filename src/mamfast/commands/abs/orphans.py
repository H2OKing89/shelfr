"""ABS orphans command - find and clean up orphaned folders in ABS library.

This module contains the `cmd_abs_orphans` command handler.
"""

from __future__ import annotations

import argparse
import json as json_module
from datetime import UTC, datetime
from pathlib import Path

from mamfast.commands.abs._common import (
    confirm,
    console,
    fatal_error,
    print_dry_run,
    print_header,
    print_step,
    print_success,
    print_warning,
)


def cmd_abs_orphans(args: argparse.Namespace) -> int:
    """Find and clean up orphaned folders in ABS library.

    Orphaned folders have metadata.json but no audio files. These are
    often created by ABS when it creates duplicate library entries.
    """
    from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

    from mamfast.abs.cleanup import (
        cleanup_orphaned_folders,
        scan_orphaned_folders,
    )
    from mamfast.config import reload_settings

    print_header("ABS Orphan Finder", dry_run=args.dry_run)

    # Load settings to get default library path
    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError:
        settings = None

    # Determine source directory
    source_dir = args.source
    if not source_dir:
        # Get ABS library root from path_map (like abs-import does)
        if (
            settings
            and hasattr(settings, "audiobookshelf")
            and settings.audiobookshelf
            and settings.audiobookshelf.path_map
        ):
            source_dir = Path(settings.audiobookshelf.path_map[0].host)
        else:
            fatal_error(
                "No source directory specified",
                "Use --source or configure audiobookshelf.path_map in config",
            )
            return 1

    if not source_dir.is_dir():
        fatal_error(f"Source directory does not exist: {source_dir}")
        return 1

    console.print(f"  → Source: {source_dir}")
    console.print()

    # Scan for orphaned folders with progress display
    total_steps = 2 if (args.cleanup or args.cleanup_all) else 1
    print_step(1, total_steps, "Scanning for orphaned folders")

    progress_ctx = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,  # Clear after completion
    )

    with progress_ctx:
        task_id = progress_ctx.add_task("Scanning...", total=None)

        def update_progress(description: str, _advance: int | None = None) -> None:
            """Update progress spinner with current status."""
            progress_ctx.update(task_id, description=description)

        result = scan_orphaned_folders(
            source_dir,
            min_match_score=args.min_match_score,
            progress_callback=update_progress,
        )

    # Display results
    total_orphaned = len(result.orphaned_with_match) + len(result.orphaned_no_match)
    console.print("\n[bold]Scan Results:[/]")
    console.print(f"  Total folders with metadata.json: {result.total_metadata_folders}")
    console.print(f"  Folders with audio: {result.total_audio_folders}")
    console.print(f"  [yellow]Orphaned (no audio): {total_orphaned}[/]")
    console.print(f"    With matching audio folder: {len(result.orphaned_with_match)}")
    console.print(f"    No match found: {len(result.orphaned_no_match)}")
    console.print()

    # Show orphaned folders with matches
    if result.orphaned_with_match:
        console.print("[bold cyan]Orphaned folders WITH matching audio folder:[/]")
        for orphan in sorted(result.orphaned_with_match, key=lambda x: str(x.path)):
            rel_path = orphan.path.relative_to(source_dir)
            match_rel = (
                orphan.matching_folder.relative_to(source_dir) if orphan.matching_folder else None
            )
            files_display = ", ".join(orphan.files[:5]) if orphan.files else "(no files)"
            if len(orphan.files) > 5:
                files_display += f" (+{len(orphan.files) - 5} more)"
            console.print(f"\n  [red]ORPHAN:[/]  {rel_path}")
            console.print(f"  [green]MATCH:[/]   {match_rel}")
            console.print(f"  [dim]Score: {orphan.match_score:.1%}, Files: {files_display}[/]")

    # Show orphaned folders without matches
    if result.orphaned_no_match:
        console.print("\n[bold yellow]Orphaned folders with NO matching folder:[/]")
        for orphan in sorted(result.orphaned_no_match, key=lambda x: str(x.path)):
            rel_path = orphan.path.relative_to(source_dir)
            files_display = ", ".join(orphan.files[:5]) if orphan.files else "(no files)"
            if len(orphan.files) > 5:
                files_display += f" (+{len(orphan.files) - 5} more)"
            console.print(f"  {rel_path}")
            console.print(f"    [dim]Files: {files_display}[/]")

    # Generate report if requested
    if args.report:
        report_data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "source_dir": str(source_dir),
            "summary": {
                "total_metadata_folders": result.total_metadata_folders,
                "total_audio_folders": result.total_audio_folders,
                "orphaned_with_match": len(result.orphaned_with_match),
                "orphaned_no_match": len(result.orphaned_no_match),
            },
            "orphaned_with_match": [
                {
                    "path": str(o.path),
                    "name": o.path.name,
                    "files": o.files,
                    "matching_folder": str(o.matching_folder) if o.matching_folder else None,
                    "match_name": o.matching_folder.name if o.matching_folder else None,
                    "match_score": round(o.match_score * 100, 1),
                }
                for o in result.orphaned_with_match
            ],
            "orphaned_no_match": [
                {
                    "path": str(o.path),
                    "name": o.path.name,
                    "files": o.files,
                }
                for o in result.orphaned_no_match
            ],
        }
        try:
            with open(args.report, "w", encoding="utf-8") as f:
                json_module.dump(report_data, f, indent=2)
            print_success(f"Report written to {args.report}")
        except OSError as e:
            print_warning(f"Failed to write report to {args.report}: {e}")

    # Cleanup if requested
    if args.cleanup or args.cleanup_all:
        print_step(2, total_steps, "Cleaning up orphaned folders")

        if args.cleanup_all:
            # Clean up ALL orphans (dangerous)
            all_orphans = result.orphaned_with_match + result.orphaned_no_match
            skip_confirm = getattr(args, "yes", False)
            if not args.dry_run and not skip_confirm:
                console.print(
                    "[bold red]WARNING: --cleanup-all will remove folders "
                    "without matching audio![/]"
                )
                if not confirm("Are you sure you want to continue?"):
                    console.print("Aborted.")
                    return 0
            cleanup_result = cleanup_orphaned_folders(
                all_orphans, dry_run=args.dry_run, require_match=False
            )
        else:
            # Only clean up orphans with matches (safer)
            cleanup_result = cleanup_orphaned_folders(
                result.orphaned_with_match, dry_run=args.dry_run, require_match=True
            )

        # Show cleanup results
        if args.dry_run:
            print_dry_run(f"Would remove {cleanup_result.removed} orphaned folders")
        else:
            print_success(f"Removed {cleanup_result.removed} orphaned folders")

        if cleanup_result.skipped > 0:
            console.print(f"  Skipped: {cleanup_result.skipped}")
        if cleanup_result.failed > 0:
            print_warning(f"Failed to remove: {cleanup_result.failed}")
            return 1
    else:
        console.print(
            "\n[dim]Use --cleanup to remove orphans with matches, or --cleanup-all for all.[/]"
        )

    return 0


__all__ = ["cmd_abs_orphans"]
