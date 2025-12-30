"""ABS cleanup command - cleanup Libation source files after import.

This module contains the `cmd_abs_cleanup` command handler.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import replace
from pathlib import Path

from mamfast.commands.abs._common import (
    console,
    fatal_error,
    print_dry_run,
    print_error,
    print_header,
    print_info,
    print_step,
    print_success,
    print_warning,
)

logger = logging.getLogger(__name__)


def cmd_abs_cleanup(args: argparse.Namespace) -> int:
    """Cleanup Libation source files after import.

    Standalone cleanup command for manually triggering cleanup of
    already-imported Libation source folders. Useful when:
    - Import was run without cleanup enabled
    - Cleanup failed during import and needs retry
    - Batch cleanup of historical imports
    """
    from rich.panel import Panel
    from rich.table import Table

    from mamfast.abs.cleanup import (
        CleanupResult,
        CleanupStrategy,
        cleanup_source,
        is_cleanup_eligible,
        verify_seed_exists,
    )
    from mamfast.config import build_cleanup_prefs, reload_settings

    print_header("Audiobookshelf Cleanup", dry_run=args.dry_run)

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    # Check if ABS is enabled
    if not hasattr(settings, "audiobookshelf") or not settings.audiobookshelf.enabled:
        print_warning("Audiobookshelf integration is not enabled in config")
        print_info("Set audiobookshelf.enabled: true in config.yaml")
        return 1

    abs_config = settings.audiobookshelf

    # Build cleanup preferences from config with CLI overrides
    strategy_override = getattr(args, "strategy", None)
    cleanup_path_override = getattr(args, "cleanup_path", None)
    cleanup_path_override_str = str(cleanup_path_override) if cleanup_path_override else None

    cleanup_prefs = build_cleanup_prefs(
        abs_config.import_settings.cleanup,
        strategy_override=strategy_override,
        cleanup_path_override=cleanup_path_override_str,
    )

    # Apply CLI overrides for require_seed_exists and min_age_days
    # Use dataclass replace() for cleaner field overrides
    no_verify_seed = getattr(args, "no_verify_seed", False)
    if no_verify_seed:
        cleanup_prefs = replace(cleanup_prefs, require_seed_exists=False)

    min_age_override = getattr(args, "min_age_days", None)
    if min_age_override is not None:
        cleanup_prefs = replace(cleanup_prefs, min_age_days=min_age_override)

    # Validate cleanup strategy
    if cleanup_prefs.strategy == CleanupStrategy.NONE:
        print_warning("Cleanup strategy is 'none' - nothing to do")
        print_info("Use --strategy to specify a cleanup strategy (hide, move, delete)")
        return 0

    if cleanup_prefs.strategy == CleanupStrategy.MOVE and not cleanup_prefs.cleanup_path:
        fatal_error("Cleanup strategy is 'move' but no cleanup_path configured")
        print_info("Set cleanup.cleanup_path in config.yaml or use --cleanup-path")
        return 1

    # Get seed_root for hardlink verification
    seed_root = settings.paths.seed_root

    # Get library_root (source of Libation files)
    library_root = settings.paths.library_root

    # Discover folders to cleanup
    print_step(1, 3, "Discovering cleanup candidates")
    if args.paths:
        # Specific paths provided
        candidates: list[Path] = [p for p in args.paths if p.is_dir()]
        if not candidates:
            print_warning("No valid directories in provided paths")
            return 1
    else:
        # Discover all eligible folders in library_root (recursive search)
        # Audiobooks are typically at Author/Series/Book or Author/Book level
        candidates = []

        def should_ignore_dir(name: str) -> bool:
            """Check if directory should be ignored."""
            if name in cleanup_prefs.ignore_dirs:
                return True
            return bool(name.startswith("."))

        def find_eligible_folders(root: Path, depth: int = 0, max_depth: int = 4) -> None:
            """Recursively find eligible folders."""
            if depth > max_depth:
                return
            try:
                for folder in root.iterdir():
                    if not folder.is_dir():
                        continue
                    if should_ignore_dir(folder.name):
                        continue
                    # Check if this folder is eligible for cleanup
                    if is_cleanup_eligible(folder):
                        candidates.append(folder)
                    else:
                        # Not eligible, search deeper (Author/Series folders)
                        find_eligible_folders(folder, depth + 1, max_depth)
            except PermissionError:
                logger.warning("Permission denied: %s", root)

        find_eligible_folders(library_root)

    if not candidates:
        print_info("No eligible folders found for cleanup")
        return 0

    print_info(f"Found {len(candidates)} cleanup candidate(s)")

    # Display cleanup settings
    print_step(2, 3, "Cleanup settings")
    print_info(f"Strategy: {cleanup_prefs.strategy.value}")
    if cleanup_prefs.strategy == CleanupStrategy.MOVE:
        print_info(f"Cleanup path: {cleanup_prefs.cleanup_path}")
    if cleanup_prefs.require_seed_exists:
        print_info(f"Require seed exists: Yes (seed_root: {seed_root})")
    else:
        print_warning("Require seed exists: No (DANGEROUS - data loss possible)")
    if cleanup_prefs.min_age_days > 0:
        print_info(f"Minimum age: {cleanup_prefs.min_age_days} days")

    if args.dry_run:
        print_dry_run(f"Would cleanup {len(candidates)} folder(s)")

    # Process cleanup
    print_step(3, 3, "Processing cleanup")
    results: list[CleanupResult] = []
    success_count = 0
    skipped_count = 0
    failed_count = 0

    for folder in candidates:
        # Verify seed exists if required
        if cleanup_prefs.require_seed_exists:
            seed_exists, _seed_path = verify_seed_exists(folder, seed_root)
            if not seed_exists:
                result = CleanupResult(
                    source_path=folder,
                    status="skipped",
                    strategy=cleanup_prefs.strategy,
                    error="Seed hardlinks not found",
                )
                results.append(result)
                skipped_count += 1
                print_warning(f"Skipped {folder.name}: seed hardlinks not found")
                continue

        # Perform cleanup
        result = cleanup_source(
            source_path=folder,
            prefs=cleanup_prefs,
            seed_root=seed_root,
            dry_run=args.dry_run,
        )
        results.append(result)

        if result.status == "success":
            success_count += 1
            if result.strategy == CleanupStrategy.HIDE:
                print_success(f"Hidden: {folder.name}")
            elif result.strategy == CleanupStrategy.MOVE:
                print_success(f"Moved: {folder.name} → {result.destination}")
            elif result.strategy == CleanupStrategy.DELETE:
                print_success(f"Deleted: {folder.name}")
        elif result.status == "dry_run":
            success_count += 1
            print_dry_run(f"Would cleanup: {folder.name}")
        elif result.status == "skipped":
            skipped_count += 1
            print_warning(f"Skipped: {folder.name} ({result.error})")
        else:
            failed_count += 1
            print_error(f"Failed: {folder.name} ({result.error})")

    # Summary
    console.print()

    summary_table = Table(show_header=False, box=None, padding=(0, 2))
    summary_table.add_column("Label", style="dim")
    summary_table.add_column("Value", justify="right")

    summary_table.add_row("Folders processed:", str(len(results)))
    summary_table.add_row("Strategy:", cleanup_prefs.strategy.value)
    summary_table.add_row("", "")

    if args.dry_run:
        summary_table.add_row("Would cleanup:", f"[green]{success_count}[/green]")
    else:
        summary_table.add_row("Cleaned up:", f"[green]{success_count}[/green]")

    if skipped_count > 0:
        summary_table.add_row("Skipped:", f"[yellow]{skipped_count}[/yellow]")
    if failed_count > 0:
        summary_table.add_row("Failed:", f"[red]{failed_count}[/red]")

    if args.dry_run:
        panel_title = "[bold yellow]DRY RUN Summary[/bold yellow]"
        panel_border = "yellow"
    else:
        panel_title = "[bold green]Cleanup Summary[/bold green]"
        panel_border = "green"

    console.print(Panel(summary_table, title=panel_title, border_style=panel_border))
    console.print()

    return 1 if failed_count > 0 else 0


__all__ = ["cmd_abs_cleanup"]
