"""ABS resolve-asins command - resolve ASINs for Unknown/ books.

This module contains the `cmd_abs_resolve_asins` command handler.
"""

from __future__ import annotations

import argparse
import json as json_module
from datetime import UTC, datetime
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


def cmd_abs_resolve_asins(args: argparse.Namespace) -> int:
    """Resolve ASINs for Unknown/ books via ABS metadata search.

    Phase 5: Batch search Audible (via ABS) to find ASINs for books
    that were imported without ASIN and placed in Unknown/.
    """
    from mamfast.abs import AbsClient, resolve_asin_via_abs_search
    from mamfast.config import reload_settings

    print_header("ABS ASIN Resolver", dry_run=args.dry_run)

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    # Check if ABS is configured and enabled
    if not hasattr(settings, "audiobookshelf") or not settings.audiobookshelf.enabled:
        fatal_error("Audiobookshelf integration is not enabled in config")
        return 1

    abs_config = settings.audiobookshelf
    if not abs_config.host or not abs_config.api_key:
        fatal_error("Audiobookshelf integration is not enabled in config")
        return 1

    if not abs_config.host or not abs_config.api_key:
        fatal_error(
            "Missing ABS credentials",
            "Set AUDIOBOOKSHELF_HOST and AUDIOBOOKSHELF_API_KEY in .env",
        )
        return 1

    # Get ABS library root from path_map (same as abs-import)
    if not abs_config.path_map:
        fatal_error("No path_map configured for Audiobookshelf")
        return 1
    abs_library_root = Path(abs_config.path_map[0].host)

    # Determine what to scan
    if args.path:
        if not args.path.exists():
            fatal_error(f"Path not found: {args.path}")
            return 1
        if not args.path.is_dir():
            fatal_error(f"Path is not a directory: {args.path}")
            return 1
        # Scan subfolders of the provided path
        folders_to_scan = [
            f for f in args.path.iterdir() if f.is_dir() and not f.name.startswith(".")
        ]
    else:
        # Default: scan Unknown/ folder
        unknown_folder = abs_library_root / "Unknown"
        if not unknown_folder.exists():
            print_info("No Unknown/ folder found - nothing to resolve")
            return 0
        folders_to_scan = [
            f for f in unknown_folder.iterdir() if f.is_dir() and not f.name.startswith(".")
        ]

    if not folders_to_scan:
        print_info("No folders to process")
        return 0

    # Validate confidence threshold (common mistake: passing 75 instead of 0.75)
    confidence = args.confidence
    if not 0.0 <= confidence <= 1.0:
        fatal_error(
            f"Invalid confidence value: {confidence}",
            "Confidence must be between 0.0 and 1.0 (e.g., 0.75 for 75%)",
        )
        return 1

    print_info(f"Found {len(folders_to_scan)} folder(s) to resolve")
    print_info(f"Confidence threshold: {confidence:.0%}")

    # Connect to ABS
    print_step(1, 3, "Connecting to ABS")
    try:
        client = AbsClient(
            host=abs_config.host,
            api_key=abs_config.api_key,
            timeout=abs_config.timeout_seconds,
        )
    except Exception as e:
        fatal_error(f"Failed to connect to ABS: {e}")
        return 1

    # Process folders (using with statement for proper cleanup)
    print_step(2, 3, "Searching for ASINs")
    resolved_count = 0
    failed_count = 0

    with client:
        try:
            user = client.authorize()
            print_success(f"Connected as {user.username}")
        except Exception as e:
            fatal_error(f"Failed to authorize with ABS: {e}")
            return 1

        for folder in folders_to_scan:
            folder_name = folder.name
            console.print(f"\n[dim]→[/] {folder_name}")

            # Parse folder name for title/author
            # For abs-resolve-asins, we're dealing with non-MAM folders that need ASIN resolution.
            # Use conservative extraction - only split on " - " pattern which reliably indicates
            # "Author - Title" format. Don't use MAM parser which may incorrectly extract
            # parenthetical content like "(Light Novel)" as author.
            title: str = folder_name  # Default to full folder name
            author: str | None = None

            if " - " in folder_name:
                # Simple "Author - Title" split (e.g., "Quentin Kilgore - Primal Imperative 2")
                parts = folder_name.split(" - ", 1)
                author = parts[0].strip()
                title = parts[1].strip() if len(parts) > 1 else folder_name

            if args.dry_run:
                print_dry_run(f"Would search: title={title!r}, author={author!r}")
                continue

            # Search via ABS
            resolution = resolve_asin_via_abs_search(
                client,
                title=title,
                author=author,
                confidence_threshold=confidence,
            )

            if resolution.found:
                resolved_count += 1
                print_success(f"Found ASIN: {resolution.asin}")
                print_info(f"  Source: {resolution.source_detail}")

                # Write sidecar if requested
                if args.write_sidecar:
                    sidecar_path = folder / "_mamfast_resolved_asin.json"
                    sidecar_data = {
                        "asin": resolution.asin,
                        "source": resolution.source,
                        "source_detail": resolution.source_detail,
                        "resolved_at": datetime.now(UTC).isoformat(),
                        "original_folder": folder_name,
                    }
                    try:
                        sidecar_path.write_text(
                            json_module.dumps(sidecar_data, indent=2, sort_keys=True)
                        )
                        print_info(f"  Wrote: {sidecar_path.name}")
                    except OSError as e:
                        print_warning(f"  Failed to write sidecar: {e}")
            else:
                failed_count += 1
                print_warning("No confident match found")

    # Summary
    print_step(3, 3, "Summary")
    console.print()

    if args.dry_run:
        print_dry_run(f"Would resolve {len(folders_to_scan)} folder(s)")
    else:
        print_info(f"Resolved: {resolved_count}")
        print_info(f"Not found: {failed_count}")

        if resolved_count > 0 and args.write_sidecar:
            print_success("Sidecar files written - run abs-import to move books")

    return 0


__all__ = ["cmd_abs_resolve_asins"]
