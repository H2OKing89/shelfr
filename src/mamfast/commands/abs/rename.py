"""ABS rename command - rename audiobook folders to match MAM naming schema.

This module contains the `cmd_abs_rename` command handler.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from mamfast.commands.abs._common import (
    fatal_error,
    print_header,
    print_info,
    print_success,
    print_warning,
)


def cmd_abs_rename(args: argparse.Namespace) -> int:
    """Rename audiobook folders in ABS library to match MAM naming schema.

    Normalizes folder names in your Audiobookshelf library to follow
    the MAM naming convention for consistency and better organization.
    """
    from mamfast.abs.rename import (
        generate_html_report,
        generate_report,
        run_rename_pipeline,
    )
    from mamfast.config import reload_settings

    print_header("ABS Rename", dry_run=args.dry_run)

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    # Get source directory
    source_dir: Path
    if args.source:
        source_dir = args.source
    else:
        # Use ABS library path from config
        if not hasattr(settings, "audiobookshelf") or not settings.audiobookshelf.enabled:
            fatal_error("Audiobookshelf integration is not enabled in config")
            print_info("Either enable ABS or specify --source PATH")
            return 1

        abs_config = settings.audiobookshelf
        if not abs_config.path_map:
            fatal_error("No path_map configured for Audiobookshelf")
            return 1

        # Use first path map's host path as source
        source_dir = Path(abs_config.path_map[0].host)

    if not source_dir.exists():
        fatal_error(f"Source directory does not exist: {source_dir}")
        return 1

    print_info(f"Source: {source_dir}")
    if args.pattern != "*":
        print_info(f"Pattern: {args.pattern}")

    # Optionally create ABS client for search
    abs_client = None
    if args.abs_search:
        from mamfast.abs import AbsClient

        if not hasattr(settings, "audiobookshelf") or not settings.audiobookshelf.enabled:
            print_warning("ABS search requested but Audiobookshelf is not enabled")
        else:
            abs_config = settings.audiobookshelf
            try:
                abs_client = AbsClient(
                    host=abs_config.host,
                    api_key=abs_config.api_key,
                    timeout=abs_config.timeout_seconds,
                )
                print_info("ABS search enabled")
            except (ConnectionError, TimeoutError, OSError) as e:
                print_warning(f"Failed to create ABS client: {e}")

    # Run the rename pipeline
    try:
        results, summary, candidates = run_rename_pipeline(
            source_dir=source_dir,
            pattern=args.pattern,
            fetch_metadata=args.fetch_metadata,
            abs_client=abs_client,
            abs_search_confidence=args.abs_search_confidence,
            naming_config=getattr(settings, "naming", None),
            dry_run=args.dry_run,
            interactive=args.interactive,
            force=args.force,
        )
    finally:
        if abs_client:
            abs_client.close()

    # Generate report if requested
    if args.report:
        report_path = Path(args.report)
        try:
            report_data = generate_report(
                results,
                candidates,
                summary,
                report_path,
                source_dir=source_dir,
                dry_run=args.dry_run,
            )
            print_success(f"JSON report written to {report_path}")

            # Also generate HTML report
            html_path = report_path.with_suffix(".html")
            generate_html_report(report_data, html_path)
            print_success(f"HTML report written to {html_path}")
        except OSError as e:
            print_warning(f"Failed to write report: {e}")

    # Return error code if there were failures
    if summary.errors > 0:
        return 1
    return 0


__all__ = ["cmd_abs_rename"]
