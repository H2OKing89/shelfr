"""ABS restore command - restore archived books to the library.

This module contains the `cmd_abs_restore` command handler.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from mamfast.commands.abs._common import (
    console,
    fatal_error,
    print_dry_run,
    print_header,
    print_info,
    print_step,
    print_success,
    print_warning,
)


def cmd_abs_restore(args: argparse.Namespace) -> int:
    """Restore archived books to the library.

    Lists available archives or restores a specific archived book
    back to the library root.
    """
    from mamfast.abs.trumping import (
        TrumpingError,
        discover_archives,
        restore_from_archive,
    )
    from mamfast.config import reload_settings

    print_header("Archive Restore", dry_run=args.dry_run)

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    # Check if ABS is enabled
    if not hasattr(settings, "audiobookshelf") or not settings.audiobookshelf.enabled:
        print_warning("Audiobookshelf integration is not enabled in config")
        return 1

    abs_config = settings.audiobookshelf

    # Get trumping config for archive_root
    trumping_config = abs_config.import_settings.trumping
    if not trumping_config.archive_root:
        fatal_error("No archive_root configured for trumping")
        print_info("Set audiobookshelf.import.trumping.archive_root in config.yaml")
        return 1

    archive_root = Path(trumping_config.archive_root)

    # Get library root for restoration destination
    if not abs_config.path_map:
        fatal_error("No path_map configured for Audiobookshelf")
        return 1
    library_root = Path(abs_config.path_map[0].host)

    # List mode or no path specified - show available archives
    list_only = getattr(args, "list", False)
    archive_path = getattr(args, "archive_path", None)
    filter_asin = getattr(args, "asin", None)

    if list_only or archive_path is None:
        # List available archives
        print_step(1, 1, "Discovering archives")

        archives = discover_archives(archive_root, asin=filter_asin)

        if not archives:
            if filter_asin:
                print_info(f"No archives found for ASIN {filter_asin}")
            else:
                print_info("No archives found")
            return 0

        console.print()
        console.print(f"[bold]Found {len(archives)} archive(s)[/]")
        console.print()

        for archive in archives:
            asin_display = f"[cyan]{archive.asin}[/]" if archive.asin else "[dim]No ASIN[/]"
            console.print(f"  {asin_display}")
            console.print(f"    Path: [dim]{archive.archive_path}[/]")
            console.print(f"    Archived: {archive.archived_at}")
            console.print(f"    Reason: {archive.reason}")
            if archive.original_format:
                quality = archive.original_format
                if archive.original_bitrate:
                    quality += f" @ {archive.original_bitrate}kbps"
                console.print(f"    Quality: {quality}")
            console.print()

        console.print("[dim]To restore, run:[/]")
        console.print("  mamfast abs-restore <archive-path>")
        return 0

    # Restore mode - restore specific archive
    if not archive_path.exists():
        fatal_error(f"Archive path does not exist: {archive_path}")
        return 1

    sidecar = archive_path / ".mamfast_trump.json"
    if not sidecar.exists():
        fatal_error(
            f"Invalid archive - missing .mamfast_trump.json: {archive_path}",
            "Make sure the path points to an archived book folder",
        )
        return 1

    print_step(1, 1, "Restoring archive")
    print_info(f"Source: {archive_path}")
    print_info(f"Target: {library_root}")

    if args.dry_run:
        folder_name = archive_path.name
        print_dry_run(f"Would restore {folder_name} to {library_root / folder_name}")
        return 0

    try:
        restored_path = restore_from_archive(
            archive_path=archive_path,
            library_root=library_root,
            dry_run=args.dry_run,
        )
        if restored_path:
            print_success(f"Restored to: {restored_path}")
            print_info("Run ABS library scan to pick up the restored book")
        return 0
    except TrumpingError as e:
        fatal_error(str(e))
        return 1


__all__ = ["cmd_abs_restore"]
