"""ABS trump command - preview trumping decisions for staged folders.

This module contains the `cmd_abs_trump_check` command handler.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from shelfr.commands.abs._common import (
    console,
    fatal_error,
    print_header,
    print_info,
    print_step,
    print_success,
    print_warning,
)


def cmd_abs_trump_check(args: argparse.Namespace) -> int:
    """Preview trumping decisions for staged folders.

    Shows what would be replaced, kept, or rejected based on quality comparison
    against existing library content. Does not modify any files.
    """
    from shelfr.abs import AbsClient, asin_exists, build_asin_index, discover_staged_books
    from shelfr.abs.asin import extract_asin
    from shelfr.abs.importer import parse_mam_folder_name
    from shelfr.abs.paths import PathMapper
    from shelfr.abs.trumping import (
        TrumpDecision,
        TrumpPrefs,
        adjust_for_aggressiveness,
        decide_trump,
        extract_trumpable_meta,
        is_multi_file_layout,
    )
    from shelfr.config import reload_settings
    from shelfr.console import (
        print_trump_comparison_table,
        print_trump_decision,
        print_trump_summary,
    )

    print_header("Trumping Preview")

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

    # Get managed library
    managed_libs = [lib for lib in abs_config.libraries if lib.mamfast_managed]
    if not managed_libs:
        fatal_error("No mamfast_managed libraries configured")
        return 1
    target_library = managed_libs[0]

    # Get import source directory (staging root)
    import_source = settings.paths.library_root

    # Get trumping preferences from config
    trumping_config = abs_config.import_settings.trumping
    if not trumping_config.enabled:
        print_warning("Trumping is not enabled in config")
        print_info("Set audiobookshelf.import.trumping.enabled: true")
        print_info("Showing what WOULD happen if trumping were enabled...")

    trump_prefs = TrumpPrefs.from_config(trumping_config)
    # Force enabled for preview purposes
    trump_prefs_preview = replace(trump_prefs, enabled=True)

    # Discover books to check
    print_step(1, 3, "Discovering staged books")
    if args.paths:
        # Specific paths provided
        staging_folders = [p for p in args.paths if p.is_dir()]
        if not staging_folders:
            print_warning("No valid directories in provided paths")
            return 1
    else:
        staging_folders = discover_staged_books(import_source)

    if not staging_folders:
        print_info("No staged books to check")
        return 0

    print_info(f"Found {len(staging_folders)} audiobook(s) to check")

    # Build path mapper for container→host conversion
    path_mappings = [{"container": pm.container, "host": pm.host} for pm in abs_config.path_map]
    path_mapper = PathMapper(mappings=path_mappings) if path_mappings else None

    # Connect to ABS and build index
    print_step(2, 3, "Building ASIN index from ABS")
    try:
        client = AbsClient(
            host=abs_config.host,
            api_key=abs_config.api_key,
            timeout=abs_config.timeout_seconds,
        )
        asin_index = build_asin_index(client, target_library.id)
        client.close()
        print_success(f"Indexed {len(asin_index)} books with ASINs")
    except (ConnectionError, TimeoutError, OSError) as e:
        fatal_error(f"Failed to query ABS: {e}")
        return 1
    except Exception as e:
        # Catch any other API-related errors
        fatal_error(f"Failed to query ABS: {e}")
        return 1

    # Check trumping for each folder
    print_step(3, 3, "Analyzing trumping decisions")
    console.print()

    replaced_count = 0
    kept_existing_count = 0
    rejected_count = 0
    keep_both_count = 0
    no_asin_count = 0
    no_duplicate_count = 0
    multi_file_count = 0

    for folder in staging_folders:
        console.print(f"[bold]{folder.name}[/]")

        # Parse folder name to extract ASIN
        parsed = parse_mam_folder_name(folder.name)
        asin = parsed.asin if parsed else None

        # Also try extracting from folder contents (mediainfo)
        if not asin:
            asin = extract_asin(str(folder))

        if not asin:
            no_asin_count += 1
            console.print("  [dim]⏭ No ASIN - cannot check for duplicates[/]")
            console.print()
            continue

        # Check if ASIN exists in library
        is_dup, _ = asin_exists(asin_index, asin)
        if not is_dup:
            no_duplicate_count += 1
            console.print(f"  [green]✓ ASIN {asin} not in library - new book[/]")
            console.print()
            continue

        # Check for multi-file layout (trumping doesn't apply)
        if is_multi_file_layout(folder):
            multi_file_count += 1
            console.print("  [dim]⏭ Multi-file layout - trumping skipped[/]")
            console.print()
            continue

        # Get existing entry and check its layout
        # Convert container path to host path for local file operations
        existing_entry = asin_index[asin]
        if path_mapper:
            existing_folder = path_mapper.to_host(existing_entry.path)
        else:
            existing_folder = Path(existing_entry.path)
        if not existing_folder.exists():
            console.print(f"  [yellow]⚠ Existing folder not found: {existing_entry.path}[/]")
            console.print()
            continue
        if is_multi_file_layout(existing_folder):
            multi_file_count += 1
            console.print("  [dim]⏭ Existing is multi-file - trumping skipped[/]")
            console.print()
            continue

        # Extract metadata and compare
        existing_meta = extract_trumpable_meta(existing_folder, asin)
        incoming_meta = extract_trumpable_meta(folder, asin)

        decision, reason = decide_trump(existing_meta, incoming_meta, trump_prefs_preview)
        decision, reason = adjust_for_aggressiveness(decision, reason, trump_prefs_preview)

        # Show verbose comparison if requested
        if getattr(args, "verbose", False):
            print_trump_comparison_table(
                existing_format=existing_meta.format,
                incoming_format=incoming_meta.format,
                existing_bitrate=existing_meta.bitrate_kbps,
                incoming_bitrate=incoming_meta.bitrate_kbps,
                existing_sample_rate=existing_meta.sample_rate_hz,
                incoming_sample_rate=incoming_meta.sample_rate_hz,
                existing_duration=existing_meta.duration_sec,
                incoming_duration=incoming_meta.duration_sec,
                existing_chapters=existing_meta.has_chapters,
                incoming_chapters=incoming_meta.has_chapters,
                existing_stereo=existing_meta.is_stereo,
                incoming_stereo=incoming_meta.is_stereo,
            )

        # Display decision
        print_trump_decision(
            decision_name=decision.name,
            reason=reason,
            existing_format=existing_meta.format,
            incoming_format=incoming_meta.format,
            existing_bitrate=existing_meta.bitrate_kbps,
            incoming_bitrate=incoming_meta.bitrate_kbps,
        )

        # Show existing location
        console.print(f"  [dim]Existing: {existing_entry.path}[/]")

        # Update counts
        match decision:
            case TrumpDecision.REPLACE_WITH_NEW:
                replaced_count += 1
            case TrumpDecision.KEEP_EXISTING:
                kept_existing_count += 1
            case TrumpDecision.REJECT_NEW:
                rejected_count += 1
            case TrumpDecision.KEEP_BOTH:
                keep_both_count += 1

        console.print()

    # Summary
    console.print("[bold]Summary[/]")
    console.print(f"  Total checked: {len(staging_folders)}")
    if no_asin_count:
        console.print(f"  [dim]No ASIN: {no_asin_count}[/]")
    if no_duplicate_count:
        console.print(f"  [green]New books: {no_duplicate_count}[/]")
    if multi_file_count:
        console.print(f"  [dim]Multi-file (skipped): {multi_file_count}[/]")

    # Trumping summary if any duplicates were found
    trumping_total = replaced_count + kept_existing_count + rejected_count + keep_both_count
    if trumping_total > 0:
        print_trump_summary(
            replaced=replaced_count,
            kept_existing=kept_existing_count,
            rejected=rejected_count,
        )
        if keep_both_count > 0:
            console.print(f"  📁 Keep both: [dim]{keep_both_count}[/]")

    return 0


__all__ = ["cmd_abs_trump_check"]
