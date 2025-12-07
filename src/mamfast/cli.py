"""MAMFast CLI - Command-line interface for audiobook upload automation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mamfast.config import NamingConfig

from mamfast import __version__
from mamfast.console import (
    DryRunTransform,
    confirm,
    console,
    fatal_error,
    print_check_category,
    print_config_section,
    print_directory_status,
    print_dry_run,
    print_dry_run_header,
    print_dry_run_release,
    print_dry_run_summary,
    print_error,
    print_header,
    print_info,
    print_release_table,
    print_status_table,
    print_step,
    print_success,
    print_summary,
    print_validation_summary,
    print_warning,
    render_libation_status,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="mamfast",
        description="Fast MAM audiobook upload automation tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  mamfast scan              # Run Libation scan for new books
  mamfast discover          # List unprocessed audiobooks
  mamfast prepare           # Stage new audiobooks (hardlink + rename)
  mamfast metadata          # Fetch Audnex + MediaInfo for staged releases
  mamfast torrent           # Create .torrent files
  mamfast upload            # Upload torrents to qBittorrent
  mamfast run               # Full pipeline: scan → upload
  mamfast run --skip-scan   # Full pipeline without Libation scan
        """,
    )

    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"mamfast {__version__}",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )

    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path("config/config.yaml"),
        help="Path to config.yaml (default: ./config/config.yaml)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without making changes",
    )

    # Subcommands
    subparsers = parser.add_subparsers(
        dest="command",
        title="commands",
        metavar="<command>",
    )

    # -------------------------------------------------------------------------
    # scan: Run Libation
    # -------------------------------------------------------------------------
    scan_parser = subparsers.add_parser(
        "scan",
        help="Run libationcli scan in Libation container",
    )
    scan_parser.add_argument(
        "--liberate",
        action="store_true",
        help="Also run liberate to download new books (waits for completion)",
    )
    scan_parser.set_defaults(func=cmd_scan)

    # -------------------------------------------------------------------------
    # discover: Find new audiobooks
    # -------------------------------------------------------------------------
    discover_parser = subparsers.add_parser(
        "discover",
        help="List new (unprocessed) audiobooks found in Libation library",
    )
    discover_parser.add_argument(
        "--all",
        action="store_true",
        help="Show all audiobooks, not just unprocessed ones",
    )
    discover_parser.set_defaults(func=cmd_discover)

    # -------------------------------------------------------------------------
    # prepare: Stage audiobooks
    # -------------------------------------------------------------------------
    prepare_parser = subparsers.add_parser(
        "prepare",
        help="Stage new audiobooks for upload (hardlink + MAM-compliant rename)",
    )
    prepare_parser.add_argument(
        "--asin",
        type=str,
        help="Process specific release by ASIN only",
    )
    prepare_parser.set_defaults(func=cmd_prepare)

    # -------------------------------------------------------------------------
    # metadata: Fetch Audnex + MediaInfo
    # -------------------------------------------------------------------------
    metadata_parser = subparsers.add_parser(
        "metadata",
        help="Fetch metadata (Audnex + MediaInfo) for staged releases",
    )
    metadata_parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        help="Path to specific audiobook directory to process",
    )
    metadata_parser.add_argument(
        "--asin",
        type=str,
        help="Process specific release by ASIN only",
    )
    metadata_parser.set_defaults(func=cmd_metadata)

    # -------------------------------------------------------------------------
    # torrent: Create .torrent files
    # -------------------------------------------------------------------------
    torrent_parser = subparsers.add_parser(
        "torrent",
        help="Create .torrent files for staged releases using mkbrr",
    )
    torrent_parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        help="Path to specific audiobook directory to process",
    )
    torrent_parser.add_argument(
        "--preset",
        type=str,
        help="Override mkbrr preset (default from config)",
    )
    torrent_parser.add_argument(
        "--asin",
        type=str,
        help="Process specific release by ASIN only",
    )
    torrent_parser.set_defaults(func=cmd_torrent)

    # -------------------------------------------------------------------------
    # upload: Add to qBittorrent
    # -------------------------------------------------------------------------
    upload_parser = subparsers.add_parser(
        "upload",
        help="Upload .torrent files to qBittorrent",
    )
    upload_parser.add_argument(
        "--paused",
        action="store_true",
        help="Add torrents in paused state",
    )
    upload_parser.set_defaults(func=cmd_upload)

    # -------------------------------------------------------------------------
    # run: Full pipeline
    # -------------------------------------------------------------------------
    run_parser = subparsers.add_parser(
        "run",
        help="Run full pipeline: scan → discover → prepare → metadata → torrent → upload",
        epilog="Tip: Use 'mamfast --dry-run run' to preview without making changes.",
    )
    run_parser.add_argument(
        "--skip-scan",
        action="store_true",
        help="Skip Libation scan step",
    )
    run_parser.add_argument(
        "--skip-metadata",
        action="store_true",
        help="Skip metadata fetching step",
    )
    run_parser.set_defaults(func=cmd_run)

    # -------------------------------------------------------------------------
    # status: Show processing status
    # -------------------------------------------------------------------------
    status_parser = subparsers.add_parser(
        "status",
        help="Show processing status of all releases",
    )
    status_parser.set_defaults(func=cmd_status)

    # -------------------------------------------------------------------------
    # config: Debug config loading
    # -------------------------------------------------------------------------
    config_parser = subparsers.add_parser(
        "config",
        help="Print loaded configuration (for debugging)",
    )
    config_parser.set_defaults(func=cmd_config)

    # -------------------------------------------------------------------------
    # check: Health check command
    # -------------------------------------------------------------------------
    check_parser = subparsers.add_parser(
        "check",
        help="Run health checks to verify environment setup",
        epilog="Use category flags to run specific checks only.",
    )
    check_parser.add_argument(
        "--config-only",
        action="store_true",
        help="Run configuration checks only",
    )
    check_parser.add_argument(
        "--paths-only",
        action="store_true",
        help="Run path checks only",
    )
    check_parser.add_argument(
        "--services-only",
        action="store_true",
        help="Run service connectivity checks only",
    )
    check_parser.set_defaults(func=cmd_check)

    # -------------------------------------------------------------------------
    # validate: Validate discovered releases
    # -------------------------------------------------------------------------
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate all discovered releases (discovery, metadata checks)",
        epilog="Runs validation checks without processing releases.",
    )
    validate_parser.add_argument(
        "--asin",
        type=str,
        help="Validate specific release by ASIN only",
    )
    validate_parser.add_argument(
        "--json",
        action="store_true",
        help="Output validation report as JSON",
    )
    validate_parser.set_defaults(func=cmd_validate)

    # -------------------------------------------------------------------------
    # validate-config: Validate configuration files
    # -------------------------------------------------------------------------
    validate_config_parser = subparsers.add_parser(
        "validate-config",
        help="Validate all configuration files (naming.json, config.yaml, etc.)",
        epilog="Validates JSON structure, regex patterns, and required fields.",
    )
    validate_config_parser.set_defaults(func=cmd_validate_config)

    # -------------------------------------------------------------------------
    # dry-run: Preview naming transformations
    # -------------------------------------------------------------------------
    dry_run_parser = subparsers.add_parser(
        "dry-run",
        help="Preview naming transformations without making changes",
        epilog="Shows before/after for title filtering and folder renaming.",
    )
    dry_run_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of releases to process (default: 10)",
    )
    dry_run_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show all fields, including unchanged ones",
    )
    dry_run_parser.add_argument(
        "--asin",
        type=str,
        help="Preview specific release by ASIN only",
    )
    dry_run_parser.set_defaults(func=cmd_dry_run)

    # -------------------------------------------------------------------------
    # check-duplicates: Find potential duplicate releases
    # -------------------------------------------------------------------------
    duplicates_parser = subparsers.add_parser(
        "check-duplicates",
        help="Find potential duplicate releases in library using fuzzy matching",
        epilog="Uses RapidFuzz to find near-duplicate titles.",
    )
    duplicates_parser.add_argument(
        "--threshold",
        type=int,
        default=85,
        help="Minimum similarity percentage to consider duplicate (default: 85)",
    )
    duplicates_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of duplicate pairs to show (default: 20)",
    )
    duplicates_parser.add_argument(
        "--include-processed",
        action="store_true",
        help="Include already processed releases in scan",
    )
    duplicates_parser.set_defaults(func=cmd_check_duplicates)

    # -------------------------------------------------------------------------
    # check-suspicious: Find over-aggressive title cleaning
    # -------------------------------------------------------------------------
    suspicious_parser = subparsers.add_parser(
        "check-suspicious",
        help="Check for over-aggressive title cleaning by naming rules",
        epilog="Compares original titles to cleaned versions and flags significant changes.",
    )
    suspicious_parser.add_argument(
        "--threshold",
        type=int,
        default=50,
        help="Maximum similarity below which a change is suspicious (default: 50)",
    )
    suspicious_parser.add_argument(
        "--asin",
        type=str,
        help="Check specific release by ASIN only",
    )
    suspicious_parser.add_argument(
        "--include-processed",
        action="store_true",
        help="Include already processed releases in scan",
    )
    suspicious_parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    suspicious_parser.set_defaults(func=cmd_check_suspicious)

    # -------------------------------------------------------------------------
    # abs-init: Initialize Audiobookshelf connection
    # -------------------------------------------------------------------------
    abs_init_parser = subparsers.add_parser(
        "abs-init",
        help="Initialize and verify Audiobookshelf connection",
        epilog="Tests ABS API connection and discovers available libraries.",
    )
    abs_init_parser.set_defaults(func=cmd_abs_init)

    # -------------------------------------------------------------------------
    # abs-import: Import staged books to Audiobookshelf library
    # -------------------------------------------------------------------------
    abs_import_parser = subparsers.add_parser(
        "abs-import",
        help="Import staged audiobooks to Audiobookshelf library",
        epilog="Moves staged books to ABS library structure with duplicate detection.",
    )
    abs_import_parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Specific folder(s) to import (default: all in staging)",
    )
    abs_import_parser.add_argument(
        "-d",
        "--duplicate-policy",
        choices=["skip", "warn", "overwrite"],
        default=None,
        help="Override duplicate handling policy (default: from config)",
    )
    abs_import_parser.add_argument(
        "--no-scan",
        action="store_true",
        help="Don't trigger ABS library scan after import",
    )
    abs_import_parser.add_argument(
        "--no-abs-search",
        action="store_true",
        help="Disable ABS metadata search for missing ASINs (uses config default otherwise)",
    )
    abs_import_parser.add_argument(
        "--confidence",
        type=float,
        default=None,
        metavar="THRESHOLD",
        help="Minimum confidence (0.0-1.0) for ABS search matches (default: from config or 0.75)",
    )
    abs_import_parser.add_argument(
        "--no-trump",
        action="store_true",
        help="Disable trumping for this run (ignore config setting)",
    )
    abs_import_parser.add_argument(
        "--trump-aggressiveness",
        choices=["conservative", "balanced", "aggressive"],
        default=None,
        metavar="LEVEL",
        help="Override trumping aggressiveness (default: from config)",
    )
    abs_import_parser.add_argument(
        "--cleanup-strategy",
        choices=["none", "hide", "move", "delete"],
        default=None,
        metavar="STRATEGY",
        help="Override cleanup strategy for Libation source files (default: from config)",
    )
    abs_import_parser.add_argument(
        "--cleanup-path",
        type=Path,
        default=None,
        metavar="PATH",
        help="Override cleanup path for 'move' strategy (default: from config)",
    )
    abs_import_parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Disable post-import cleanup (ignore config setting)",
    )
    abs_import_parser.set_defaults(func=cmd_abs_import)

    # -------------------------------------------------------------------------
    # abs-check-duplicate: Check if ASIN exists in library
    # -------------------------------------------------------------------------
    abs_check_parser = subparsers.add_parser(
        "abs-check-duplicate",
        help="Check if an ASIN already exists in the library index",
        epilog="Quick lookup to check for duplicates before importing.",
    )
    abs_check_parser.add_argument(
        "asin",
        type=str,
        help="ASIN to check (e.g., B0DK27WWT8)",
    )
    abs_check_parser.set_defaults(func=cmd_abs_check_duplicate)

    # -------------------------------------------------------------------------
    # abs-trump-check: Preview trumping decisions for folders
    # -------------------------------------------------------------------------
    abs_trump_parser = subparsers.add_parser(
        "abs-trump-check",
        help="Preview trumping decisions for staged folders",
        epilog="Shows what would be replaced, kept, or rejected based on quality comparison.",
    )
    abs_trump_parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Specific folder(s) to check (default: all in staging)",
    )
    abs_trump_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed quality comparison tables",
    )
    abs_trump_parser.set_defaults(func=cmd_abs_trump_check)

    # -------------------------------------------------------------------------
    # abs-restore: Restore archived books to library
    # -------------------------------------------------------------------------
    abs_restore_parser = subparsers.add_parser(
        "abs-restore",
        help="Restore archived books to library",
        epilog="Restore books that were archived by trumping back to the library.",
    )
    abs_restore_parser.add_argument(
        "archive_path",
        nargs="?",
        type=Path,
        help="Specific archive folder to restore (default: list archives)",
    )
    abs_restore_parser.add_argument(
        "--asin",
        type=str,
        help="Filter archives by ASIN",
    )
    abs_restore_parser.add_argument(
        "--list",
        action="store_true",
        help="List available archives without restoring",
    )
    abs_restore_parser.set_defaults(func=cmd_abs_restore)

    # -------------------------------------------------------------------------
    # abs-cleanup: Standalone cleanup of already-imported Libation sources
    # -------------------------------------------------------------------------
    abs_cleanup_parser = subparsers.add_parser(
        "abs-cleanup",
        help="Cleanup Libation source files after import",
        epilog=(
            "Standalone cleanup of Libation source folders that have been imported.\n"
            "Supports multiple strategies: hide (add marker), move, or delete."
        ),
    )
    abs_cleanup_parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Specific folder(s) to cleanup (default: all eligible in library_root)",
    )
    abs_cleanup_parser.add_argument(
        "--strategy",
        choices=["none", "hide", "move", "delete"],
        default=None,
        metavar="STRATEGY",
        help="Cleanup strategy (default: from config)",
    )
    abs_cleanup_parser.add_argument(
        "--cleanup-path",
        type=Path,
        default=None,
        metavar="PATH",
        help="Destination for 'move' strategy (default: from config)",
    )
    abs_cleanup_parser.add_argument(
        "--no-verify-seed",
        action="store_true",
        help="Skip verification of seed hardlinks (DANGEROUS)",
    )
    abs_cleanup_parser.add_argument(
        "--min-age-days",
        type=int,
        default=None,
        metavar="DAYS",
        help="Only cleanup sources older than N days (default: from config)",
    )
    abs_cleanup_parser.set_defaults(func=cmd_abs_cleanup)

    # -------------------------------------------------------------------------
    # abs-rename: Rename folders in ABS library to MAM naming schema
    # -------------------------------------------------------------------------
    abs_rename_parser = subparsers.add_parser(
        "abs-rename",
        help="Rename audiobook folders in ABS library to match MAM naming schema",
        epilog=(
            "Normalizes folder names in your Audiobookshelf library to follow\n"
            "the MAM naming convention for consistency and better organization."
        ),
    )
    abs_rename_parser.add_argument(
        "--source",
        type=Path,
        default=None,
        metavar="PATH",
        help="Directory to scan (default: ABS library from config)",
    )
    abs_rename_parser.add_argument(
        "--pattern",
        type=str,
        default="*",
        metavar="GLOB",
        help="Glob pattern to filter folders (default: *)",
    )
    abs_rename_parser.add_argument(
        "--fetch-metadata",
        action="store_true",
        help="Fetch missing metadata from Audnex API",
    )
    abs_rename_parser.add_argument(
        "--abs-search",
        action="store_true",
        help="Use ABS Audible search for ASIN resolution (network calls)",
    )
    abs_rename_parser.add_argument(
        "--abs-search-confidence",
        type=float,
        default=0.75,
        metavar="THRESHOLD",
        help="Minimum confidence for ABS search matches (default: 0.75)",
    )
    abs_rename_parser.add_argument(
        "--interactive",
        action="store_true",
        help="Prompt for confirmation on each rename",
    )
    abs_rename_parser.add_argument(
        "--rename-files-inside",
        action="store_true",
        help="Also rename media files inside folder to match folder name",
    )
    abs_rename_parser.add_argument(
        "--report",
        type=Path,
        default=None,
        metavar="PATH",
        help="Output JSON report of changes to file",
    )
    abs_rename_parser.set_defaults(func=cmd_abs_rename)

    # -------------------------------------------------------------------------
    # abs-orphans: Find and clean up orphaned ABS folders
    # -------------------------------------------------------------------------
    abs_orphans_parser = subparsers.add_parser(
        "abs-orphans",
        help="Find and clean up orphaned folders in ABS library",
        epilog=(
            "Finds orphaned folders that have metadata.json but no audio files.\n"
            "These are often created by ABS when it creates duplicate library entries."
        ),
    )
    abs_orphans_parser.add_argument(
        "--source",
        type=Path,
        default=None,
        metavar="PATH",
        help="Directory to scan (default: ABS library from config)",
    )
    abs_orphans_parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Remove orphaned folders (only those with matching audio folder)",
    )
    abs_orphans_parser.add_argument(
        "--cleanup-all",
        action="store_true",
        help="Remove ALL orphaned folders (even without matches - DANGEROUS)",
    )
    abs_orphans_parser.add_argument(
        "--min-match-score",
        type=float,
        default=0.5,
        metavar="SCORE",
        help="Minimum similarity score to consider a match (default: 0.5)",
    )
    abs_orphans_parser.add_argument(
        "--report",
        type=Path,
        default=None,
        metavar="PATH",
        help="Output JSON report of orphaned folders to file",
    )
    abs_orphans_parser.set_defaults(func=cmd_abs_orphans)

    # -------------------------------------------------------------------------
    # abs-resolve-asins: Batch resolve ASINs for Unknown/ books via ABS search
    # -------------------------------------------------------------------------
    abs_resolve_parser = subparsers.add_parser(
        "abs-resolve-asins",
        help="Resolve ASINs for Unknown/ books via ABS metadata search",
        epilog="Phase 5: Search Audible via ABS to find ASINs for books in Unknown/.",
    )
    abs_resolve_parser.add_argument(
        "--path",
        type=Path,
        help="Specific folder to resolve (default: scan Unknown/)",
    )
    abs_resolve_parser.add_argument(
        "--confidence",
        type=float,
        default=0.75,
        help="Minimum confidence threshold (0-1, default: 0.75)",
    )
    abs_resolve_parser.add_argument(
        "--write-sidecar",
        action="store_true",
        help="Write resolved ASINs to sidecar JSON files",
    )
    abs_resolve_parser.set_defaults(func=cmd_abs_resolve_asins)

    return parser


# =============================================================================
# Command implementations (stubs - to be filled in)
# =============================================================================


def cmd_scan(args: argparse.Namespace) -> int:
    """Run Libation scan."""
    from mamfast.config import reload_settings
    from mamfast.libation import get_libation_status, run_liberate, run_scan

    print_header("Libation Scan", dry_run=args.dry_run)

    try:
        reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    if args.dry_run:
        print_dry_run("Would execute: docker exec Libation /libation/LibationCli scan")
        if args.liberate:
            print_dry_run("Would execute: docker exec Libation /libation/LibationCli liberate")
        return 0

    total_steps = 2 if args.liberate else 1
    print_step(1, total_steps, "Running scan")
    result = run_scan()

    if result.stdout:
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                print_info(line.strip())

    if result.success:
        print_success("Scan complete")
    else:
        print_error(f"Scan failed (exit code: {result.returncode})")
        return result.returncode

    status = None
    try:
        status = get_libation_status()
    except RuntimeError as exc:
        print_warning(f"Unable to fetch Libation status: {exc}")
    else:
        console.print()
        render_libation_status(status)

    # Optionally run liberate
    if args.liberate:
        if status is not None and not status.has_pending:
            print_info("No audiobooks staged for download (NotLiberated=0). Skipping liberate.")
            return 0

        console.print()
        print_step(2, 2, "Running liberate (downloading new books)")
        liberate_result = run_liberate()

        if liberate_result.stdout:
            for line in liberate_result.stdout.strip().split("\n"):
                if line.strip():
                    print_info(line.strip())

        if liberate_result.success:
            print_success("Liberate complete")

            # Show updated status when available
            try:
                new_status = get_libation_status()
            except RuntimeError:
                pass
            else:
                console.print()
                render_libation_status(new_status, title="Libation Status (Post-Liberate)")
        else:
            print_error(f"Liberate failed (exit code: {liberate_result.returncode})")
            return liberate_result.returncode
    else:
        if status is not None and status.has_pending:
            print_warning(
                f"{status.not_liberated} audiobooks are staged for download. "
                "Run 'mamfast scan --liberate' or the full workflow to download them."
            )

    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    """Discover new audiobooks."""
    from mamfast.config import reload_settings
    from mamfast.discovery import get_new_releases, scan_library
    from mamfast.logging_setup import set_console_quiet

    set_console_quiet(True)

    show_all = getattr(args, "all", False)
    title = "All Releases" if show_all else "New Releases"
    print_header(f"Discover {title}")

    try:
        reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        set_console_quiet(False)
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    releases = scan_library() if show_all else get_new_releases()

    set_console_quiet(False)
    print_release_table(releases, title=title)
    return 0


def cmd_prepare(args: argparse.Namespace) -> int:
    """Stage audiobooks for upload."""
    from mamfast.config import reload_settings
    from mamfast.discovery import get_new_releases, get_release_by_asin
    from mamfast.hardlinker import stage_release
    from mamfast.logging_setup import set_console_quiet

    set_console_quiet(True)
    print_header("Prepare Releases", dry_run=args.dry_run)

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        set_console_quiet(False)
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    # Get releases to process
    if args.asin:
        release = get_release_by_asin(args.asin)
        if not release:
            set_console_quiet(False)
            fatal_error(f"Release not found with ASIN: {args.asin}")
            return 1
        releases = [release]
    else:
        releases = get_new_releases()

    if not releases:
        set_console_quiet(False)
        console.print("[success]✓[/] No new releases to prepare")
        return 0

    console.print(f"Found [highlight]{len(releases)}[/] release(s) to stage\n")

    staged = 0
    failed = 0

    for release in releases:
        console.print(f"[dim]→[/] {release.display_name}")

        if args.dry_run:
            from mamfast.utils.naming import filter_title, transliterate_text

            if release.source_dir:
                original_name = release.source_dir.name
                filtered_name = filter_title(original_name, settings.filters.remove_phrases)
                filtered_name = transliterate_text(filtered_name, settings.filters)
                seed_path = settings.paths.seed_root / filtered_name
                if original_name != filtered_name:
                    print_info(f"Original: {original_name}")
                    print_info(f"Filtered: {filtered_name}")
            else:
                seed_path = settings.paths.seed_root / "unknown"
            print_dry_run(f"Would hardlink to: {seed_path}")
            staged += 1
            continue

        try:
            staging_dir = stage_release(release)
            print_success(f"Staged: {staging_dir.name}")
            staged += 1
        except Exception as e:
            print_error(f"Failed: {e}")
            failed += 1

    set_console_quiet(False)
    print_summary(staged, failed)
    return 0 if failed == 0 else 1


def cmd_metadata(args: argparse.Namespace) -> int:
    """Fetch metadata."""
    from mamfast.config import reload_settings
    from mamfast.discovery import extract_asin_from_name
    from mamfast.logging_setup import set_console_quiet
    from mamfast.metadata import (
        build_mam_json,
        fetch_all_metadata,
        save_mam_json,
    )
    from mamfast.models import AudiobookRelease

    set_console_quiet(True)
    print_header("Fetch Metadata", dry_run=args.dry_run)

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        set_console_quiet(False)
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    torrent_output = settings.paths.torrent_output

    # Determine which directories to process
    if args.path:
        target_dir = Path(args.path).resolve()
        if not target_dir.exists():
            set_console_quiet(False)
            fatal_error(f"Path does not exist: {target_dir}")
            return 1
        if not target_dir.is_dir():
            set_console_quiet(False)
            fatal_error(f"Path is not a directory: {target_dir}")
            return 1
        staged_dirs = [target_dir]
        console.print(f"Target: [highlight]{target_dir.name}[/]\n")
    elif args.asin:
        seed_root = settings.paths.seed_root
        if not seed_root.exists():
            set_console_quiet(False)
            fatal_error(f"Seed directory does not exist: {seed_root}")
            return 1

        staged_dirs = []
        for d in seed_root.iterdir():
            if not d.is_dir():
                continue
            if args.asin in d.name:
                staged_dirs.append(d)
                continue
            for f in d.iterdir():
                asin = extract_asin_from_name(f.name)
                if asin == args.asin:
                    staged_dirs.append(d)
                    break

        if not staged_dirs:
            set_console_quiet(False)
            fatal_error(f"No staged directory found for ASIN: {args.asin}")
            return 1
    else:
        seed_root = settings.paths.seed_root
        if not seed_root.exists():
            set_console_quiet(False)
            print_warning(f"Seed directory does not exist yet: {seed_root}")
            print_info("Run 'mamfast prepare' first to stage releases.")
            return 0
        staged_dirs = [d for d in seed_root.iterdir() if d.is_dir()]

    if not staged_dirs:
        set_console_quiet(False)
        console.print("[success]✓[/] No releases to process")
        return 0

    if not args.path:
        console.print(f"Found [highlight]{len(staged_dirs)}[/] staged release(s)\n")

    success = 0
    for staging_dir in staged_dirs:
        console.print(f"[dim]→[/] {staging_dir.name}")

        # Find m4b file
        m4b_files = list(staging_dir.glob("*.m4b"))
        m4b_path = m4b_files[0] if m4b_files else None

        # Extract ASIN
        asin = None
        if m4b_path:
            asin = extract_asin_from_name(m4b_path.name)
        if not asin:
            asin = extract_asin_from_name(staging_dir.name)

        # Fail fast: skip if no ASIN and no m4b file - can't produce useful metadata
        if not asin and not m4b_path:
            print_warning(f"Skipping {staging_dir.name}: no ASIN found and no .m4b file")
            continue

        if args.dry_run:
            print_dry_run(f"Would fetch Audnex for ASIN: {asin}")
            print_dry_run(f"Would run MediaInfo on: {m4b_path}")
            print_dry_run(f"Would generate MAM JSON in: {torrent_output}")
            success += 1
            continue

        audnex_data, mediainfo_data, audnex_chapters = fetch_all_metadata(
            asin=asin,
            m4b_path=m4b_path,
            output_dir=staging_dir,
        )

        if audnex_data:
            print_success("Audnex metadata fetched")
        else:
            print_warning("Audnex: not found")

        if audnex_chapters:
            chapter_count = len(audnex_chapters.get("chapters", []))
            print_success(f"Audnex chapters: {chapter_count} chapters")
        else:
            print_warning("Audnex chapters: not found")

        if mediainfo_data:
            print_success("MediaInfo extracted")
        else:
            print_warning("MediaInfo: failed")

        # Build and save MAM JSON
        release = AudiobookRelease(
            asin=asin,
            staging_dir=staging_dir,
            main_m4b=m4b_path,
            audnex_metadata=audnex_data,
            mediainfo_data=mediainfo_data,
            audnex_chapters=audnex_chapters,
        )

        mam_data = build_mam_json(release, audnex_chapters=audnex_chapters)
        if mam_data.get("title"):
            json_name = f"{staging_dir.name}.json"
            json_path = torrent_output / json_name
            save_mam_json(mam_data, json_path)
            print_success(f"MAM JSON: {json_name}")
        else:
            print_warning("MAM JSON: no title available")

        success += 1

    set_console_quiet(False)
    print_summary(success, len(staged_dirs) - success)
    return 0


def cmd_torrent(args: argparse.Namespace) -> int:
    """Create torrents."""
    from mamfast.config import reload_settings
    from mamfast.logging_setup import set_console_quiet
    from mamfast.mkbrr import check_docker_available, create_torrent

    set_console_quiet(True)
    print_header("Create Torrents", dry_run=args.dry_run)

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        set_console_quiet(False)
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    # Check Docker
    if not check_docker_available():
        set_console_quiet(False)
        fatal_error("Docker is not available", "Ensure Docker is installed and running")
        return 1

    # Determine directories
    if args.path:
        target_dir = Path(args.path).resolve()
        if not target_dir.exists():
            set_console_quiet(False)
            fatal_error(f"Path does not exist: {target_dir}")
            return 1
        if not target_dir.is_dir():
            set_console_quiet(False)
            fatal_error(f"Path is not a directory: {target_dir}")
            return 1
        staged_dirs = [target_dir]
        console.print(f"Target: [highlight]{target_dir.name}[/]\n")
    elif args.asin:
        seed_root = settings.paths.seed_root
        if not seed_root.exists():
            set_console_quiet(False)
            fatal_error(f"Seed directory does not exist: {seed_root}")
            return 1
        staged_dirs = [d for d in seed_root.iterdir() if d.is_dir() and args.asin in d.name]
        if not staged_dirs:
            set_console_quiet(False)
            fatal_error(f"No staged directory found for ASIN: {args.asin}")
            return 1
    else:
        seed_root = settings.paths.seed_root
        if not seed_root.exists():
            set_console_quiet(False)
            print_warning(f"Seed directory does not exist yet: {seed_root}")
            print_info("Run 'mamfast prepare' first to stage releases.")
            return 0
        staged_dirs = [d for d in seed_root.iterdir() if d.is_dir()]

    if not staged_dirs:
        set_console_quiet(False)
        console.print("[success]✓[/] No releases to process")
        return 0

    preset = args.preset or settings.mkbrr.preset
    console.print(f"Preset: [highlight]{preset}[/]")
    if not args.path:
        console.print(f"Found [highlight]{len(staged_dirs)}[/] staged release(s)\n")

    success = 0
    failed = 0

    for staging_dir in staged_dirs:
        console.print(f"[dim]→[/] {staging_dir.name}")

        if args.dry_run:
            print_dry_run(f"Would create torrent with preset: {preset}")
            success += 1
            continue

        result = create_torrent(
            content_path=staging_dir,
            preset=preset,
        )

        if result.success:
            print_success(f"Created: {result.torrent_path.name if result.torrent_path else 'ok'}")
            success += 1
        else:
            print_error(f"Failed: {result.error}")
            failed += 1

    set_console_quiet(False)
    print_summary(success, failed)
    return 0 if failed == 0 else 1


def cmd_upload(args: argparse.Namespace) -> int:
    """Upload to qBittorrent."""
    from mamfast.config import reload_settings
    from mamfast.qbittorrent import test_connection, upload_torrent

    print_header("Upload Torrents", dry_run=args.dry_run)

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    # Quiet mode for clean Rich UI
    from mamfast.logging_setup import set_console_quiet

    set_console_quiet(True)

    # Test connection
    console.print(f"Connecting to [highlight]{settings.qbittorrent.host}[/]")
    if not test_connection():
        set_console_quiet(False)
        fatal_error("Cannot connect to qBittorrent", "Check host and credentials in config")
        return 1
    print_success("Connected to qBittorrent\n")

    # Find torrents
    torrent_dir = settings.paths.torrent_output
    if not torrent_dir.exists():
        set_console_quiet(False)
        fatal_error(f"Torrent directory does not exist: {torrent_dir}")
        return 1

    torrent_files = list(torrent_dir.glob("*.torrent"))

    if not torrent_files:
        set_console_quiet(False)
        console.print("[success]✓[/] No torrent files to upload")
        return 0

    console.print(f"Found [highlight]{len(torrent_files)}[/] torrent file(s)\n")

    success = 0
    failed = 0

    for torrent_path in torrent_files:
        console.print(f"[dim]→[/] {torrent_path.name}")

        # Determine save path
        staging_name = torrent_path.stem
        save_path = settings.paths.library_root / staging_name
        if not save_path.exists():
            save_path = settings.paths.seed_root / staging_name

        if args.dry_run:
            print_dry_run(f"Would upload with save_path: {save_path}")
            success += 1
            continue

        result = upload_torrent(
            torrent_path=torrent_path,
            save_path=save_path,
            paused=args.paused,
        )

        if result:
            print_success("Uploaded")
            success += 1
        else:
            print_error("Failed to upload")
            failed += 1

    set_console_quiet(False)
    print_summary(success, failed)
    return 0 if failed == 0 else 1


def cmd_run(args: argparse.Namespace) -> int:
    """Run full pipeline."""
    from mamfast.config import reload_settings
    from mamfast.logging_setup import set_console_quiet
    from mamfast.workflow import full_run

    # Quiet mode for clean Rich UI (suppress INFO logs on console)
    set_console_quiet(True)

    print_header("Full Pipeline", dry_run=args.dry_run)

    try:
        reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        set_console_quiet(False)
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    result = full_run(
        skip_scan=args.skip_scan,
        skip_metadata=args.skip_metadata,
        dry_run=args.dry_run,
    )

    set_console_quiet(False)

    if result.failed > 0:
        return 1
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show status."""
    from mamfast.config import reload_settings
    from mamfast.utils.state import get_stats, load_state

    print_header("Status")

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    # Stats
    stats = get_stats()
    console.print("[title]Processing Stats[/]")
    console.print(f"  Processed: [success]{stats['processed']}[/]")
    console.print(f"  Failed: [error]{stats['failed']}[/]")

    # Directories
    console.print("\n[title]Directories[/]")

    lib_root = settings.paths.library_root
    if lib_root.exists():
        book_count = len([d for d in lib_root.iterdir() if d.is_dir()])
        print_directory_status("Library", lib_root, True, book_count)
    else:
        print_directory_status("Library", lib_root, False)

    seed_root = settings.paths.seed_root
    if seed_root.exists():
        seed_count = len([d for d in seed_root.iterdir() if d.is_dir()])
        print_directory_status("Seed Root", seed_root, True, seed_count)
    else:
        print_directory_status("Seed Root", seed_root, False)

    torrent_out = settings.paths.torrent_output
    if torrent_out.exists():
        torrent_count = len(list(torrent_out.glob("*.torrent")))
        print_directory_status("Torrents", torrent_out, True, torrent_count)
    else:
        print_directory_status("Torrents", torrent_out, False)

    # Recent processed/failed
    state = load_state()
    processed = state.get("processed", {})
    failed = state.get("failed", {})

    if processed or failed:
        console.print()
        print_status_table(processed, failed, limit=5)

    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Run health checks to verify environment setup."""
    from mamfast.config import reload_settings
    from mamfast.validation import (
        CheckCategory,
        ValidationResult,
        check_categories,
        check_config,
        check_paths,
        check_services,
    )

    print_header("MAMFast Health Check")

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1
    except Exception as e:
        fatal_error(f"Error loading config: {e}")
        return 1

    # Determine which checks to run
    run_config = args.config_only or not (args.paths_only or args.services_only)
    run_paths = args.paths_only or not (args.config_only or args.services_only)
    run_services = args.services_only or not (args.config_only or args.paths_only)
    run_categories = not (args.config_only or args.paths_only or args.services_only)

    result = ValidationResult()

    # Run selected checks using print_check_category helper
    if run_config:
        config_result = check_config(settings)
        result.merge(config_result)
        print_check_category(result, CheckCategory.CONFIG, "Configuration")

    if run_paths:
        paths_result = check_paths(settings)
        result.merge(paths_result)
        print_check_category(result, CheckCategory.PATHS, "Paths")

    if run_services:
        print_info("Checking connectivity (this may take a moment)...")
        services_result = check_services(settings)
        result.merge(services_result)
        print_check_category(result, CheckCategory.SERVICES, "Services")

    if run_categories:
        cat_result = check_categories(settings)
        result.merge(cat_result)
        print_check_category(result, CheckCategory.CATEGORIES, "Categories")

    # Summary using print_validation_summary helper
    console.print()
    print_validation_summary(result)

    return 0 if result.passed else 1


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate all discovered releases."""
    import json as json_module
    from datetime import datetime

    from mamfast.config import reload_settings
    from mamfast.discovery import get_new_releases, get_release_by_asin
    from mamfast.logging_setup import set_console_quiet
    from mamfast.utils.state import get_processed_identifiers
    from mamfast.validation import (
        DiscoveryValidation,
        ValidationReport,
    )

    set_console_quiet(True)

    output_json = getattr(args, "json", False)
    if not output_json:
        print_header("Validate Releases")

    try:
        reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        set_console_quiet(False)
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    # Get releases to validate
    if args.asin:
        release = get_release_by_asin(args.asin)
        if not release:
            set_console_quiet(False)
            print_error(f"Release not found: {args.asin}")
            return 1
        releases = [release]
    else:
        releases = get_new_releases()

    set_console_quiet(False)

    if not releases:
        if output_json:
            console.print(json_module.dumps({"releases": [], "summary": {"total": 0}}))
        else:
            print_info("No new releases found to validate")
        return 0

    # Run validation on each release
    processed = get_processed_identifiers()
    discovery_validator = DiscoveryValidation(processed_identifiers=processed)

    reports: list[ValidationReport] = []
    total_warnings = 0
    total_errors = 0

    for i, release in enumerate(releases, 1):
        # Create report
        report = ValidationReport(
            asin=release.asin,
            title=release.title or release.display_name,
            validated_at=datetime.now().isoformat(),
        )

        # Discovery validation
        discovery_result = discovery_validator.validate(release)
        report.discovery_result = discovery_result
        total_warnings += discovery_result.warning_count
        total_errors += discovery_result.error_count

        reports.append(report)

        # Print progress (non-JSON mode)
        if not output_json:
            status = "✅" if discovery_result.passed else "❌"
            console.print(f"\n[bold][{i}/{len(releases)}] {release.display_name}[/]")
            console.print(f"  ASIN: {release.asin or 'N/A'}")
            console.print(f"  Status: {status}")

            for check in discovery_result.checks:
                console.print(f"    {check.icon} {check.message}")

            if discovery_result.warning_count > 0:
                console.print(f"  [warning]⚠️ {discovery_result.warning_count} warning(s)[/]")
            if discovery_result.error_count > 0:
                console.print(f"  [error]❌ {discovery_result.error_count} error(s)[/]")

    # Output
    if output_json:
        output = {
            "releases": [r.to_dict() for r in reports],
            "summary": {
                "total": len(reports),
                "passed": sum(1 for r in reports if r.all_passed),
                "failed": sum(1 for r in reports if not r.all_passed),
                "total_warnings": total_warnings,
                "total_errors": total_errors,
            },
        }
        console.print(json_module.dumps(output, indent=2))
    else:
        # Summary
        console.print()
        passed_count = sum(1 for r in reports if r.all_passed)
        failed_count = len(reports) - passed_count

        if failed_count == 0 and total_warnings == 0:
            console.print(f"[success]Summary:[/] All {len(reports)} releases validated ✅")
        elif failed_count == 0:
            console.print(
                f"[success]Summary:[/] {passed_count}/{len(reports)} validated, "
                f"[warning]{total_warnings} warning(s)[/] ⚠️"
            )
        else:
            console.print(
                f"[error]Summary:[/] {passed_count}/{len(reports)} validated, "
                f"[error]{failed_count} failed[/], "
                f"[warning]{total_warnings} warning(s)[/]"
            )

    return 0 if total_errors == 0 else 1


def cmd_validate_config(args: argparse.Namespace) -> int:
    """Validate all configuration files."""
    import json as json_module
    from pathlib import Path

    from pydantic import ValidationError as PydanticValidationError

    from mamfast.schemas.naming import validate_naming_json

    print_header("Validate Configuration Files")

    # Determine where to look for supporting config files (naming.json, categories.json)
    # Priority: 1) Same directory as config file, 2) config/ subdirectory relative to parent
    if args.config:
        config_parent = args.config.parent
        # Check if files exist beside the config file first (standalone layout)
        if (config_parent / "naming.json").exists():
            config_dir = config_parent
            use_subdir = False
        else:
            # Fall back to config/ subdirectory (structured layout: project/config/config.yaml)
            config_dir = config_parent.parent
            use_subdir = True
    else:
        config_dir = Path(".")
        use_subdir = True

    errors_found = False

    # Validate naming.json
    if use_subdir:
        naming_path = config_dir / "config" / "naming.json"
    else:
        naming_path = config_dir / "naming.json"
    console.print(f"\n[bold]Checking:[/] {naming_path}")

    if not naming_path.exists():
        print_warning(f"naming.json not found at {naming_path}")
    else:
        try:
            with open(naming_path, encoding="utf-8") as f:
                data = json_module.load(f)

            schema = validate_naming_json(data)

            # Count rules for summary
            rule_count = (
                len(schema.format_indicators.phrases)
                + len(schema.genre_tags.phrases)
                + len(schema.series_suffixes.patterns)
                + len(schema.publisher_tags.phrases)
                + len(schema.subtitle_patterns.remove_patterns)
                + len(schema.subtitle_redundancy_rules.rules)
            )

            print_success(f"naming.json: valid (v{schema.version}, {rule_count} rules)")

            # Show breakdown
            print_info(f"  Format indicators: {len(schema.format_indicators.phrases)}")
            print_info(f"  Genre tags: {len(schema.genre_tags.phrases)}")
            print_info(f"  Series suffixes: {len(schema.series_suffixes.patterns)}")
            print_info(f"  Publisher tags: {len(schema.publisher_tags.phrases)}")
            print_info(
                f"  Subtitle remove patterns: {len(schema.subtitle_patterns.remove_patterns)}"
            )
            print_info(f"  Subtitle keep patterns: {len(schema.subtitle_patterns.keep_patterns)}")
            print_info(f"  Redundancy rules: {len(schema.subtitle_redundancy_rules.rules)}")
            print_info(f"  Author mappings: {len(schema.author_map)}")
            print_info(f"  Preserve exact: {len(schema.preserve_exact.titles)}")

        except json_module.JSONDecodeError as e:
            print_error(f"naming.json: invalid JSON - {e}")
            errors_found = True
        except PydanticValidationError as e:
            print_error("naming.json: validation failed")
            for error in e.errors():
                loc = " -> ".join(str(x) for x in error["loc"])
                print_error(f"  {loc}: {error['msg']}")
            errors_found = True

    # Validate config.yaml (basic check - loads without error)
    config_path = args.config if args.config else config_dir / "config" / "config.yaml"
    console.print(f"\n[bold]Checking:[/] {config_path}")

    if not config_path.exists():
        print_warning(f"config.yaml not found at {config_path}")
    else:
        try:
            from mamfast.config import reload_settings

            settings = reload_settings(config_file=config_path)
            print_success("config.yaml: valid (loaded successfully)")
            print_info(f"  Library root: {settings.paths.library_root}")
            print_info(f"  Seed root: {settings.paths.seed_root}")
        except Exception as e:
            print_error(f"config.yaml: {e}")
            errors_found = True

    # Validate categories.json
    if use_subdir:
        categories_path = config_dir / "config" / "categories.json"
    else:
        categories_path = config_dir / "categories.json"
    console.print(f"\n[bold]Checking:[/] {categories_path}")

    if not categories_path.exists():
        print_warning(f"categories.json not found at {categories_path}")
    else:
        try:
            with open(categories_path, encoding="utf-8") as f:
                categories = json_module.load(f)
            if isinstance(categories, dict):
                print_success(f"categories.json: valid ({len(categories)} genre mappings)")
            else:
                print_error("categories.json: expected a dictionary")
                errors_found = True
        except json_module.JSONDecodeError as e:
            print_error(f"categories.json: invalid JSON - {e}")
            errors_found = True

    # Summary
    console.print()
    if errors_found:
        console.print("[error]Validation failed with errors[/]")
        return 1
    else:
        console.print("[success]All configuration files validated successfully ✅[/]")
        return 0


def cmd_dry_run(args: argparse.Namespace) -> int:
    """Preview naming transformations without making changes."""
    from mamfast.config import reload_settings
    from mamfast.discovery import get_new_releases, get_release_by_asin
    from mamfast.logging_setup import set_console_quiet
    from mamfast.utils.naming import filter_title, transliterate_text

    set_console_quiet(True)

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        set_console_quiet(False)
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    naming_config = settings.naming

    # Get releases to process
    if args.asin:
        release = get_release_by_asin(args.asin)
        if not release:
            set_console_quiet(False)
            fatal_error(f"Release not found with ASIN: {args.asin}")
            return 1
        releases = [release]
    else:
        releases = get_new_releases()
        if args.limit and args.limit > 0:
            releases = releases[: args.limit]

    set_console_quiet(False)

    if not releases:
        console.print("[dim]No new releases to preview[/]")
        return 0

    # Print header
    print_dry_run_header(len(releases))

    # Track stats
    would_change = 0
    no_change = 0

    # Process each release
    for release in releases:
        transforms: list[DryRunTransform] = []

        # Original folder name from source
        original_name = release.source_dir.name if release.source_dir else release.title
        final_name = original_name

        # Step 1: filter_title removes phrases
        filtered_name = filter_title(
            original_name,
            settings.filters.remove_phrases,
            naming_config=naming_config,
        )

        if original_name != filtered_name:
            # Determine which rule caused the change by re-running with verbose
            # For now, detect the rule type heuristically
            rule = _detect_rule(original_name, filtered_name, naming_config)
            transforms.append(
                DryRunTransform(
                    field="title",
                    before=original_name,
                    after=filtered_name,
                    rule=rule,
                )
            )
            final_name = filtered_name

        # Step 2: transliterate (Japanese characters, etc.)
        transliterated = transliterate_text(filtered_name, settings.filters)
        if filtered_name != transliterated:
            transforms.append(
                DryRunTransform(
                    field="title",
                    before=filtered_name,
                    after=transliterated,
                    rule="transliteration",
                )
            )
            final_name = transliterated

        # Track stats
        if transforms:
            would_change += 1
        else:
            no_change += 1

        # Always print release info (show what we're checking)
        release_label = f"{release.title}" if release.title else original_name
        if release.asin:
            release_label += f" [dim]({release.asin})[/dim]"

        print_dry_run_release(
            transforms,
            release_title=release_label,
            source_path=original_name,
            target_path=final_name,
        )

    # Print summary
    print_dry_run_summary(len(releases), would_change, no_change)
    return 0


def _detect_rule(original: str, filtered: str, naming_config: NamingConfig | None) -> str | None:
    """Detect which naming rule caused a transformation."""
    if not naming_config:
        return None

    # Check format indicators (e.g., "(Light Novel)")
    for phrase in naming_config.format_indicators:
        if phrase.lower() in original.lower() and phrase.lower() not in filtered.lower():
            return f"format_indicators: {phrase}"

    # Check genre tags
    for phrase in naming_config.genre_tags:
        if phrase.lower() in original.lower() and phrase.lower() not in filtered.lower():
            return f"genre_tags: {phrase}"

    # Check publisher tags
    for phrase in naming_config.publisher_tags:
        if phrase.lower() in original.lower() and phrase.lower() not in filtered.lower():
            return f"publisher_tags: {phrase}"

    # Check hardcoded patterns (Book XX, Vol XX, etc.)
    import re

    if re.search(r"\bBook\s+\d+", original, re.IGNORECASE) and not re.search(
        r"\bBook\s+\d+", filtered, re.IGNORECASE
    ):
        return "hardcoded_patterns: Book N"

    if re.search(r"\bVol(?:ume)?\.?\s+\d+", original, re.IGNORECASE) and not re.search(
        r"\bVol(?:ume)?\.?\s+\d+", filtered, re.IGNORECASE
    ):
        return "volume_patterns"

    return "naming_rules"


def cmd_check_duplicates(args: argparse.Namespace) -> int:
    """Find potential duplicate releases in library."""
    from mamfast.config import reload_settings
    from mamfast.discovery import get_new_releases, scan_library
    from mamfast.logging_setup import set_console_quiet
    from mamfast.utils.fuzzy import find_duplicates

    set_console_quiet(True)

    try:
        reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        set_console_quiet(False)
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    # Get releases - either all or just new
    releases = scan_library() if args.include_processed else get_new_releases()

    set_console_quiet(False)

    if not releases:
        console.print("[dim]No releases found to check[/]")
        return 0

    # Extract titles for duplicate detection
    titles = [r.title for r in releases if r.title]
    threshold = args.threshold

    console.print(
        f"[bold]Checking {len(releases)} releases for duplicates[/] "
        f"[dim](threshold: {threshold}%)[/]\n"
    )

    # Find duplicates
    duplicates = find_duplicates(titles, threshold=threshold)

    if not duplicates:
        console.print("[success]✓ No potential duplicates found[/]")
        return 0

    # Limit results
    limit = args.limit
    shown_duplicates = duplicates[:limit]

    # Build Rich table
    from rich.table import Table

    table = Table(
        title=f"[warning]Found {len(duplicates)} Potential Duplicate Pair(s)[/]",
        show_header=True,
        header_style="bold",
    )
    table.add_column("Release 1", style="cyan", overflow="fold")
    table.add_column("Release 2", style="cyan", overflow="fold")
    table.add_column("Similarity", style="yellow", justify="right")
    table.add_column("ASINs", style="dim")

    for dup in shown_duplicates:
        # Find the actual releases to get ASINs
        r1 = next((r for r in releases if r.title == dup.item1), None)
        r2 = next((r for r in releases if r.title == dup.item2), None)

        asin_info = ""
        if r1 and r2:
            if r1.asin == r2.asin:
                asin_info = f"Same: {r1.asin}"
            else:
                asin_info = f"{r1.asin or '?'} / {r2.asin or '?'}"

        table.add_row(
            dup.item1[:50] + "..." if len(dup.item1) > 50 else dup.item1,
            dup.item2[:50] + "..." if len(dup.item2) > 50 else dup.item2,
            f"{dup.similarity:.0f}%",
            asin_info,
        )

    console.print(table)

    if len(duplicates) > limit:
        console.print(
            f"\n[dim]Showing {limit} of {len(duplicates)} pairs. Use --limit to show more.[/]"
        )

    return 0


def cmd_check_suspicious(args: argparse.Namespace) -> int:
    """Check for over-aggressive title cleaning by naming rules."""
    import json as json_module

    from mamfast.config import reload_settings
    from mamfast.console import print_suspicious_changes
    from mamfast.discovery import get_new_releases, get_release_by_asin, scan_library
    from mamfast.logging_setup import set_console_quiet
    from mamfast.utils.fuzzy import analyze_change
    from mamfast.utils.naming import filter_title

    set_console_quiet(True)

    output_json = getattr(args, "json", False)

    try:
        reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        set_console_quiet(False)
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    # Get releases
    if args.asin:
        release = get_release_by_asin(args.asin)
        if not release:
            set_console_quiet(False)
            print_error(f"Release not found: {args.asin}")
            return 1
        releases = [release]
    elif args.include_processed:
        releases = scan_library()
    else:
        releases = get_new_releases()

    set_console_quiet(False)

    if not releases:
        if output_json:
            console.print(json_module.dumps({"suspicious": [], "summary": {"total": 0}}))
        else:
            console.print("[dim]No releases found to check[/]")
        return 0

    threshold = args.threshold
    if not output_json:
        console.print(
            f"[bold]Checking {len(releases)} releases for suspicious title changes[/] "
            f"[dim](threshold: {threshold}% similarity)[/]\n"
        )

    # Check each release
    suspicious: list[tuple[str, str, str, float]] = []

    for release in releases:
        if not release.title:
            continue

        original = release.title
        cleaned = filter_title(original)

        # Use fuzzy analysis to detect suspicious changes
        # Pass CLI threshold so is_suspicious uses user-supplied value
        analysis = analyze_change(original, cleaned, threshold=threshold)

        if analysis.is_suspicious:
            suspicious.append(
                (
                    release.asin or "",
                    original,
                    cleaned,
                    analysis.similarity,
                )
            )

    # Output results
    if output_json:
        output = {
            "suspicious": [
                {
                    "asin": asin,
                    "original": orig,
                    "cleaned": clean,
                    "similarity": sim,
                }
                for asin, orig, clean, sim in suspicious
            ],
            "summary": {
                "total": len(releases),
                "suspicious_count": len(suspicious),
                "threshold": threshold,
            },
        }
        console.print(json_module.dumps(output, indent=2))
    else:
        print_suspicious_changes(suspicious)

        console.print()
        if suspicious:
            console.print(
                f"[warning]Found {len(suspicious)} suspicious change(s)[/] "
                f"out of {len(releases)} releases"
            )
        else:
            console.print(
                f"[success]✓ All {len(releases)} releases have safe title transformations[/]"
            )

    return 1 if suspicious else 0


def cmd_config(args: argparse.Namespace) -> int:
    """Print loaded configuration."""
    from mamfast.config import reload_settings

    print_header("Configuration")

    try:
        settings = reload_settings(config_file=args.config)

        print_config_section(
            "Environment",
            {
                "Libation container": settings.libation_container,
                "Docker binary": settings.docker_bin,
                "Target UID:GID": f"{settings.target_uid}:{settings.target_gid}",
                "Environment": settings.env,
                "Log level": settings.log_level,
            },
        )

        print_config_section(
            "Paths",
            {
                "Library root": settings.paths.library_root,
                "Seed root": settings.paths.seed_root,
                "Torrent output": settings.paths.torrent_output,
            },
        )

        print_config_section(
            "mkbrr",
            {
                "Image": settings.mkbrr.image,
                "Preset": settings.mkbrr.preset,
                "Host data root": settings.mkbrr.host_data_root,
            },
        )

        print_config_section(
            "qBittorrent",
            {
                "Host": settings.qbittorrent.host,
                "Category": settings.qbittorrent.category,
                "Tags": ", ".join(settings.qbittorrent.tags),
                "Auto TMM": settings.qbittorrent.auto_tmm,
                "Save path": settings.qbittorrent.save_path or "(default)",
            },
        )

        print_config_section(
            "MAM",
            {
                "Max filename length": settings.mam.max_filename_length,
                "Allowed extensions": ", ".join(settings.mam.allowed_extensions),
            },
        )

        console.print("\n[success]✓[/] Configuration loaded successfully")
        return 0

    except FileNotFoundError as e:
        fatal_error(f"Config file not found: {e}")
        return 1
    except Exception as e:
        fatal_error(f"Error loading config: {e}")
        return 1


# =============================================================================
# Audiobookshelf Commands (stubs for PR 1)
# =============================================================================


def cmd_abs_init(args: argparse.Namespace) -> int:
    """Initialize and verify Audiobookshelf connection.

    Tests API connectivity and discovers available libraries.
    """
    from mamfast.abs.client import AbsAuthError, AbsClient, AbsConnectionError
    from mamfast.abs.paths import PathMapper
    from mamfast.config import reload_settings

    print_header("Audiobookshelf Init", dry_run=args.dry_run)

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    # Check if ABS is enabled in config
    if not hasattr(settings, "audiobookshelf") or not settings.audiobookshelf.enabled:
        print_warning("Audiobookshelf integration is not enabled in config")
        print_info("Set audiobookshelf.enabled: true in config.yaml")
        return 1

    abs_config = settings.audiobookshelf

    # Step 1: Test connection
    print_step(1, 3, "Testing connection to Audiobookshelf")
    print_info(f"Host: {abs_config.host}")

    client = AbsClient.from_config(abs_config)

    try:
        user = client.authorize()
        print_success(f"Connected as: {user.username} ({user.user_type})")
        if user.has_admin:
            print_info("User has admin permissions")
    except AbsAuthError as e:
        print_error(f"Authentication failed: {e}")
        print_info("Check your API key in config/config.yaml or .env")
        client.close()
        return 1
    except AbsConnectionError as e:
        print_error(f"Connection failed: {e}")
        print_info("Check that Audiobookshelf is running and accessible")
        client.close()
        return 1

    # Step 2: List libraries
    print_step(2, 3, "Discovering libraries")

    try:
        libraries = client.get_libraries()
    except Exception as e:
        print_error(f"Failed to fetch libraries: {e}")
        client.close()
        return 1

    # Filter to audiobook libraries only
    audiobook_libs = [lib for lib in libraries if lib.media_type == "book"]

    if not audiobook_libs:
        print_warning("No audiobook libraries found")
        client.close()
        return 1

    print_success(f"Found {len(audiobook_libs)} audiobook library(ies)")

    # Show configured vs discovered libraries
    configured_ids = {lib.id for lib in abs_config.libraries}

    for lib in audiobook_libs:
        is_configured = lib.id in configured_ids
        configured_lib = next((cl for cl in abs_config.libraries if cl.id == lib.id), None)
        managed = bool(configured_lib and configured_lib.mamfast_managed)

        status = ""
        if is_configured and managed:
            status = " [cyan](mamfast_managed)[/]"
        elif is_configured:
            status = " [dim](configured)[/]"
        else:
            status = " [yellow](not in config)[/]"

        folders_str = ", ".join(lib.folders) if lib.folders else "(no folders)"
        console.print(f"  • [bold]{lib.name}[/]{status}")
        console.print(f"    ID: [dim]{lib.id}[/]")
        console.print(f"    Folders: [dim]{folders_str}[/]")

    # Step 3: Show path mappings
    print_step(3, 3, "Path mapping configuration")

    if abs_config.docker_mode:
        if abs_config.path_map:
            print_info("Docker mode enabled with path mappings:")
            for pm in abs_config.path_map:
                mapper = PathMapper(pm.container, pm.host)
                console.print(f"  • Container: [cyan]{mapper.container_prefix}[/]")
                console.print(f"    Host:      [cyan]{mapper.host_prefix}[/]")

                # Test the mapping with a sample path
                sample_container = f"{mapper.container_prefix}/Author/Book"
                sample_host = mapper.to_host(sample_container)
                console.print(f"    Example:   {sample_container} → [dim]{sample_host}[/]")
        else:
            print_warning("Docker mode enabled but no path_map configured")
            print_info("Add path_map to audiobookshelf config for path translation")
    else:
        print_info("Docker mode disabled (paths used as-is)")

    # Summary
    console.print()
    print_success("Audiobookshelf connection verified")

    # Show hints for next steps
    managed_libs = [lib for lib in abs_config.libraries if lib.mamfast_managed]
    if not managed_libs:
        print_info("Next: Add library IDs to config with mamfast_managed: true")
        print_info("Then run: mamfast abs-import")
    else:
        print_info(
            f"Next: Run 'mamfast abs-import' to import staged books "
            f"to {len(managed_libs)} managed library(ies)"
        )

    client.close()
    return 0


def cmd_abs_import(args: argparse.Namespace) -> int:
    """Import staged audiobooks to Audiobookshelf library.

    Moves staged books to ABS library structure with duplicate detection.
    Uses atomic rename to preserve hardlinks to seed folder.

    Duplicate detection uses in-memory ASIN index built from ABS API,
    always providing fresh data.
    """
    from pathlib import Path

    from mamfast.abs import (
        AbsClient,
        build_asin_index,
        discover_staged_books,
        import_batch,
        trigger_scan_safe,
        validate_import_prerequisites,
    )
    from mamfast.abs.importer import build_clean_file_name
    from mamfast.config import reload_settings

    print_header("Audiobookshelf Import", dry_run=args.dry_run)

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

    # Get managed library (for now, use first managed library)
    managed_libs = [lib for lib in abs_config.libraries if lib.mamfast_managed]
    if not managed_libs:
        fatal_error("No mamfast_managed libraries configured")
        print_info("Set mamfast_managed: true on a library in config.yaml")
        return 1

    # Use first managed library
    target_library = managed_libs[0]

    # Get ABS library root from path_map (destination for imports)
    if not abs_config.path_map:
        fatal_error("No path_map configured for Audiobookshelf")
        return 1

    # Use first path map's host path as ABS library root
    abs_library_root = Path(abs_config.path_map[0].host)

    # Get import source directory (library_root = where new audiobooks are staged)
    import_source = settings.paths.library_root

    # Validate prerequisites (no longer checks for index DB)
    print_step(1, 6, "Validating prerequisites")
    errors = validate_import_prerequisites(import_source, abs_library_root)
    if errors:
        for err in errors:
            print_error(err)
        return 1
    print_success("Prerequisites validated")

    # Discover books to import
    print_step(2, 6, "Discovering staged books")
    if args.paths:
        # Specific paths provided
        staging_folders = [p for p in args.paths if p.is_dir()]
        if not staging_folders:
            print_warning("No valid directories in provided paths")
            return 1
    else:
        staging_folders = discover_staged_books(import_source)

    if not staging_folders:
        print_info("No staged books to import")
        return 0

    print_info(f"Found {len(staging_folders)} audiobook(s) to import")

    # Determine duplicate policy
    dup_policy = args.duplicate_policy or abs_config.import_settings.duplicate_policy

    # Connect to ABS and build ASIN index
    print_step(3, 6, "Building ASIN index from ABS")
    try:
        client = AbsClient(
            host=abs_config.host,
            api_key=abs_config.api_key,
            timeout=abs_config.timeout_seconds,
        )
        # Test connection first
        user = client.authorize()
        print_success(f"Connected as {user.username}")
    except Exception as e:
        fatal_error(f"Failed to connect to ABS: {e}")
        return 1

    # Build in-memory ASIN index (fetches all items, caches for this session)
    try:
        asin_index = build_asin_index(client, target_library.id)
        print_success(f"Indexed {len(asin_index)} books with ASINs")
    except Exception as e:
        client.close()  # Clean up on error
        fatal_error(f"Failed to build ASIN index: {e}")
        return 1

    # Determine if we should use ABS search for missing ASINs
    # Default from config (abs_search: true), can be disabled with --no-abs-search
    config_abs_search = abs_config.import_settings.abs_search
    no_abs_search_flag = getattr(args, "no_abs_search", False)
    use_abs_search = config_abs_search and not no_abs_search_flag

    # Use confidence from CLI if provided, else from config
    confidence = getattr(args, "confidence", None)
    if confidence is None:
        confidence = abs_config.import_settings.abs_search_confidence

    # Validate confidence threshold (common mistake: passing 75 instead of 0.75)
    if not 0.0 <= confidence <= 1.0:
        client.close()
        fatal_error(
            f"Invalid confidence value: {confidence}",
            "Confidence must be between 0.0 and 1.0 (e.g., 0.75 for 75%)",
        )
        return 1

    abs_client_for_import = client if use_abs_search else None
    if not use_abs_search:
        client.close()

    # Perform import
    print_step(4, 6, "Importing to library")
    print_info(f"Source: {import_source}")
    print_info(f"Target: {abs_library_root}")
    print_info(f"Duplicate policy: {dup_policy}")
    if use_abs_search:
        print_info(f"ABS search enabled (confidence: {confidence:.0%})")
    else:
        print_info("ABS search disabled (set abs_search: true in config or remove --no-abs-search)")

    # Get unknown ASIN policy from config
    from mamfast.abs.importer import UnknownAsinPolicy

    unknown_asin_policy_str = abs_config.import_settings.unknown_asin_policy
    # UnknownAsinPolicy enum uses lowercase values (import, quarantine, skip)
    unknown_asin_policy = UnknownAsinPolicy(unknown_asin_policy_str.lower())
    quarantine_path_str = abs_config.import_settings.quarantine_path
    quarantine_path = Path(quarantine_path_str) if quarantine_path_str else None

    # Get ignore patterns from config
    ignore_patterns = abs_config.import_settings.ignore_file_extensions or []

    print_info(f"Unknown ASIN policy: {unknown_asin_policy_str}")
    if quarantine_path:
        print_info(f"Quarantine path: {quarantine_path}")
    if ignore_patterns:
        print_info(f"Ignoring file patterns: {', '.join(ignore_patterns)}")

    if args.dry_run:
        print_dry_run(f"Would import {len(staging_folders)} book(s)")

    # Build trumping preferences from config with CLI overrides
    from mamfast.config import build_cleanup_prefs, build_trump_prefs

    trump_prefs = build_trump_prefs(
        abs_config.import_settings.trumping,
        enabled_override=False if args.no_trump else None,
        aggressiveness_override=args.trump_aggressiveness,
    )
    if trump_prefs:
        print_info(f"Trumping enabled (aggressiveness: {trump_prefs.aggressiveness.value})")
    elif args.no_trump:
        print_info("Trumping disabled (--no-trump)")

    # Build cleanup preferences from config with CLI overrides
    # Cleanup will run as a separate Step 5 after import, not during import_batch
    no_cleanup = getattr(args, "no_cleanup", False)
    cleanup_strategy_override = "none" if no_cleanup else getattr(args, "cleanup_strategy", None)
    cleanup_path_override = getattr(args, "cleanup_path", None)
    cleanup_path_override_str = str(cleanup_path_override) if cleanup_path_override else None

    cleanup_prefs = build_cleanup_prefs(
        abs_config.import_settings.cleanup,
        strategy_override=cleanup_strategy_override,
        cleanup_path_override=cleanup_path_override_str,
    )

    # Import cleanup module for later use
    from mamfast.abs.cleanup import CleanupStrategy

    # Build path mapper for container↔host conversion (needed for trumping)
    path_mapper: PathMapper | None = None
    if abs_config.path_map:
        from mamfast.abs.paths import PathMapper

        path_mappings = [{"container": pm.container, "host": pm.host} for pm in abs_config.path_map]
        path_mapper = PathMapper(mappings=path_mappings) if path_mappings else None

    # Import with progress display
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TaskID,
        TextColumn,
        TimeElapsedColumn,
    )

    # Track the progress task ID so callback can update it
    progress_task_id: TaskID | None = None

    def progress_callback(current: int, total: int, folder: Path) -> None:
        """Update progress bar with current book being processed."""
        nonlocal progress_task_id
        if progress_task_id is not None and progress_ctx is not None:
            # Truncate folder name to fit nicely
            book_name = folder.name[:50] + "..." if len(folder.name) > 50 else folder.name
            progress_ctx.update(progress_task_id, completed=current, current_book=book_name)

    try:
        # Create progress display
        progress_ctx = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TextColumn("[dim]{task.fields[current_book]}[/dim]"),
            console=console,
            transient=False,  # Keep visible after completion
        )

        with progress_ctx:
            progress_task_id = progress_ctx.add_task(
                "Importing",
                total=len(staging_folders),
                current_book="",
            )

            result = import_batch(
                staging_folders=staging_folders,
                library_root=abs_library_root,
                asin_index=asin_index,
                abs_client=abs_client_for_import,
                abs_search_confidence=confidence,
                staging_root=import_source,
                duplicate_policy=dup_policy,
                unknown_asin_policy=unknown_asin_policy,
                quarantine_path=quarantine_path,
                ignore_patterns=ignore_patterns,
                trump_prefs=trump_prefs,
                path_mapper=path_mapper,
                cleanup_prefs=None,  # Cleanup runs separately in Step 5
                source_paths={f: f for f in staging_folders},  # 1:1 mapping in staging
                seed_root=settings.paths.seed_root,
                progress_callback=progress_callback,
                dry_run=args.dry_run,
            )

            # Mark as complete
            progress_ctx.update(
                progress_task_id,
                completed=len(staging_folders),
                current_book="Done!",
            )

    except Exception as e:
        if use_abs_search:
            client.close()  # Clean up on error
        fatal_error(f"Import failed: {e}")
        return 1

    # Close client if we kept it open for ABS search
    if use_abs_search:
        client.close()

    # Display results
    # Track categories for summary (initialized before results loop)
    asin_count = 0
    no_asin_count = 0
    heur_count = 0

    # Display results
    if result.results:
        console.print()
        console.print("[bold]Import Results[/bold]")
        console.print()

        # Legend for status tags
        console.print("[dim]Legend:[/dim]")
        console.print("  [bold green][ASIN][/bold green]     Matched by ASIN in ABS index")
        console.print("  [bold yellow][NO-ASIN][/bold yellow]  No ASIN; imported under Unknown/")
        console.print(
            "  [bold magenta][HEUR][/bold magenta]     "
            "Heuristic path (no ASIN; guessed author/structure)"
        )
        console.print()

        # Build tree data for final layout preview
        tree_data: dict[str, dict[str, dict[str, list[str]]]] = {}

        for r in result.results:
            # Determine classification
            has_asin = bool(r.asin)
            is_unknown_author = False
            is_heuristic = False

            if r.parsed:
                is_unknown_author = r.parsed.author in ("Unknown", "", None)
                # Heuristic: no series info and no year typically means less metadata
                is_heuristic = not r.parsed.series and not r.parsed.year and not has_asin

            if has_asin and not is_unknown_author:
                asin_count += 1
                class_tag = "[bold green][ASIN][/bold green]"
                class_desc = "matched in ABS index"
                if r.asin:
                    class_desc = f"{r.asin} matched in ABS index"
            elif has_asin and is_unknown_author:
                asin_count += 1  # Still has ASIN, just unknown author
                class_tag = "[bold yellow][ASIN][/bold yellow]"
                class_desc = f"{r.asin} matched (author unknown)"
            elif is_heuristic:
                heur_count += 1
                class_tag = "[bold magenta][HEUR][/bold magenta]"
                class_desc = "heuristic path (no ASIN; guessed author/structure)"
            else:
                no_asin_count += 1
                class_tag = "[bold yellow][NO-ASIN][/bold yellow]"
                class_desc = "no ASIN in folder or mediainfo"

            # Status icon and color
            if r.status in ("success", "trump_replaced"):
                status_icon = "[green]✓[/green]"
            elif r.status in ("duplicate", "skipped", "trump_kept_existing", "trump_rejected"):
                status_icon = "[yellow]⏭[/yellow]"
            else:
                status_icon = "[red]✗[/red]"

            # Main line: status icon, folder name
            console.print(f"{status_icon} [cyan]{r.staging_path.name}[/cyan]")

            # Classification line with description
            console.print(f"  {class_tag} {class_desc}")

            # Source path
            console.print(f"  [dim][SRC][/dim] {r.staging_path}")

            # Destination path and file handling
            if r.status == "success" and r.target_path:
                console.print(f"  [dim][DST][/dim] {r.target_path}")

                # Build tree data for this book
                # Build tree data using actual destination path structure
                # Path structure: library_root/Author/[Series/]FolderName
                if r.target_path:
                    try:
                        rel_path = r.target_path.relative_to(abs_library_root)
                        parts = rel_path.parts

                        if len(parts) >= 1:
                            author = parts[0]
                            if len(parts) == 2:
                                # No series: Author/FolderName
                                series = ""
                                folder_name = parts[1]
                            elif len(parts) >= 3:
                                # With series: Author/Series/FolderName
                                series = parts[1]
                                folder_name = parts[2]
                            else:
                                # Just author folder somehow
                                series = ""
                                folder_name = author

                            if author not in tree_data:
                                tree_data[author] = {}
                            if series not in tree_data[author]:
                                tree_data[author][series] = {}
                            if folder_name not in tree_data[author][series]:
                                tree_data[author][series][folder_name] = []
                    except ValueError:
                        pass  # Can't make relative path

                # Helper to check if a filename matches ignore patterns
                def should_ignore(filename: str) -> bool:
                    """Check if filename matches any ignore pattern."""
                    if not ignore_patterns:
                        return False
                    import fnmatch

                    filename_lower = filename.lower()
                    for pattern in ignore_patterns:
                        pattern_lower = pattern.lower()
                        is_glob_match = "*" in pattern and fnmatch.fnmatch(
                            filename_lower, pattern_lower
                        )
                        is_ext_match = pattern.startswith(".") and filename_lower.endswith(
                            pattern_lower
                        )
                        if is_glob_match or is_ext_match:
                            return True
                    return False

                # List files with rename preview (excluding ignored files)
                source_folder = r.staging_path if args.dry_run else r.target_path
                if source_folder.exists():
                    files = sorted(
                        f.name
                        for f in source_folder.iterdir()
                        if f.is_file() and not should_ignore(f.name)
                    )

                    # In dry-run, compute what files would be renamed to
                    rename_map: dict[str, str] = {}
                    if args.dry_run and r.parsed:
                        try:
                            parsed = r.parsed
                            for f in source_folder.iterdir():
                                if not f.is_file() or should_ignore(f.name):
                                    continue
                                ext = f.suffix.lower()
                                if f.name.lower().endswith(".metadata.json"):
                                    ext = ".metadata.json"
                                clean_name = build_clean_file_name(parsed, extension=ext)
                                if f.name != clean_name:
                                    rename_map[f.name] = clean_name
                        except (ValueError, KeyError):
                            pass  # Can't build clean file name; skip rename preview

                    # Show files
                    if files:
                        console.print("  [dim]Files:[/dim]")
                        for filename in files:
                            new_name = rename_map.get(filename)
                            if new_name and new_name != filename:
                                console.print(
                                    f"    [dim]{filename}[/dim]\n"
                                    f"      → [green]{new_name}[/green]"
                                )
                            else:
                                console.print(f"    [dim]{filename}[/dim]")

                            # Add to tree data using path structure
                            if r.target_path:
                                try:
                                    rel_path = r.target_path.relative_to(abs_library_root)
                                    parts = rel_path.parts
                                    if len(parts) >= 2:
                                        author = parts[0]
                                        series = parts[1] if len(parts) >= 3 else ""
                                        folder_name = parts[-1]
                                        final_name = new_name or filename
                                        if folder_name in tree_data.get(author, {}).get(series, {}):
                                            tree_data[author][series][folder_name].append(
                                                final_name
                                            )
                                except ValueError:
                                    pass  # Can't make relative path; skip adding file to tree

            elif r.status == "trump_replaced":
                # Trumping: replaced existing with new (better quality)
                console.print(f"  [green]🔄 TRUMPED:[/green] {r.error or 'Better quality'}")
                if r.target_path:
                    console.print(f"  [dim][DST][/dim] {r.target_path}")
            elif r.status == "trump_kept_existing":
                # Trumping: kept existing (no improvement)
                reason = r.error or "No quality improvement"
                console.print(f"  [dim]⏭️  KEPT EXISTING:[/dim] {reason}")
            elif r.status == "trump_rejected":
                # Trumping: rejected incoming (worse quality)
                console.print(f"  [yellow]❌ REJECTED:[/yellow] {r.error or 'Lower quality'}")
            elif r.status == "duplicate" and r.error:
                if "Already exists at " in r.error:
                    existing_path = r.error.replace("Already exists at ", "")
                    console.print(f"  [dim][DST][/dim] [yellow]EXISTS:[/yellow] {existing_path}")
                else:
                    console.print("  [dim][DST][/dim] [yellow]Duplicate[/yellow]")
            elif r.error:
                console.print(f"  [red]Error:[/red] {r.error}")

            console.print()

        # Render library tree preview (dry-run only, and only if we have data)
        if args.dry_run and tree_data and result.success_count > 0:
            from rich.tree import Tree

            console.print()
            console.print("[bold]Planned Library Layout[/bold]")
            console.print()

            tree = Tree(f"[bold cyan]{abs_library_root}[/bold cyan]")

            for author in sorted(tree_data.keys()):
                # Highlight "Unknown" author branch as needing attention
                if author == "Unknown":
                    author_branch = tree.add(
                        f"[bold yellow]{author}[/bold yellow] [dim](needs ASIN)[/dim]"
                    )
                else:
                    author_branch = tree.add(f"[blue]{author}[/blue]")
                series_dict = tree_data[author]

                for series in sorted(series_dict.keys()):
                    if series:
                        series_branch = author_branch.add(f"[magenta]{series}[/magenta]")
                        parent = series_branch
                    else:
                        parent = author_branch

                    for folder_name in sorted(series_dict[series].keys()):
                        folder_branch = parent.add(f"[cyan]{folder_name}[/cyan]")
                        for file_name in sorted(series_dict[series][folder_name]):
                            folder_branch.add(f"[dim]{file_name}[/dim]")

            console.print(tree)
            console.print()

    # ─────────────────────────────────────────────────────────────────────────
    # Step 5: Post-import cleanup of source folders
    # ─────────────────────────────────────────────────────────────────────────
    cleanup_success_count = 0
    cleanup_skipped_count = 0
    cleanup_failed_count = 0
    # Track which source paths would be cleaned (for dry-run "remaining" simulation)
    cleanup_would_succeed_paths: set[Path] = set()
    cleanup_would_skip_paths: set[Path] = set()

    if cleanup_prefs.strategy != CleanupStrategy.NONE:
        print_step(5, 6, "Post-import cleanup")

        # Display cleanup settings
        print_info(f"Strategy: {cleanup_prefs.strategy.value}")
        if cleanup_prefs.strategy == CleanupStrategy.MOVE and cleanup_prefs.cleanup_path:
            print_info(f"Cleanup path: {cleanup_prefs.cleanup_path}")
        if cleanup_prefs.require_seed_exists:
            print_info("Requires seed hardlinks to exist")

        # Only cleanup successful imports that weren't trumped
        # Note: trump_replaced files were already MOVED during import (not hardlinked),
        # so their source paths no longer exist and cleanup should skip them
        cleanup_eligible = [r for r in result.results if r.status == "success"]

        if not cleanup_eligible:
            print_info("No eligible folders for cleanup (no successful imports)")
        else:
            from mamfast.abs.cleanup import cleanup_source

            if args.dry_run:
                print_dry_run(f"Would cleanup {len(cleanup_eligible)} source folder(s)")

            # Run cleanup with progress
            cleanup_progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                TextColumn("[dim]{task.fields[current_folder]}[/dim]"),
                console=console,
                transient=False,
            )

            with cleanup_progress:
                cleanup_task = cleanup_progress.add_task(
                    "Cleaning up",
                    total=len(cleanup_eligible),
                    current_folder="",
                )

                for i, r in enumerate(cleanup_eligible):
                    # Update progress
                    name = r.staging_path.name
                    folder_name = name[:40] + "..." if len(name) > 40 else name
                    cleanup_progress.update(cleanup_task, completed=i, current_folder=folder_name)

                    # Source path is the staging_path for direct staging imports
                    source_path = r.staging_path

                    cleanup_result = cleanup_source(
                        source_path=source_path,
                        prefs=cleanup_prefs,
                        seed_root=settings.paths.seed_root,
                        asin=r.asin,
                        dry_run=args.dry_run,
                    )

                    if cleanup_result.status in ("success", "dry_run"):
                        cleanup_success_count += 1
                        cleanup_would_succeed_paths.add(source_path)
                    elif cleanup_result.status == "skipped":
                        cleanup_skipped_count += 1
                        cleanup_would_skip_paths.add(source_path)
                    else:
                        cleanup_failed_count += 1

                # Mark complete
                cleanup_progress.update(
                    cleanup_task,
                    completed=len(cleanup_eligible),
                    current_folder="Done!",
                )

        # Prune empty directories from staging area
        # This handles empty author/series dirs left by shutil.move() during trumping
        pruned_count = 0
        if cleanup_prefs.prune_empty_dirs:
            from mamfast.abs.cleanup import prune_empty_dirs

            if args.dry_run:
                pruned_count = prune_empty_dirs(import_source, dry_run=True)
                if pruned_count > 0:
                    print_dry_run(f"Would prune {pruned_count} empty director(y/ies)")
            else:
                pruned_count = prune_empty_dirs(import_source, dry_run=False)
                if pruned_count > 0:
                    print_info(f"Pruned {pruned_count} empty director(y/ies)")

        # Show remaining folders in source directory after cleanup
        # In dry-run: simulate what would remain (trumped + cleanup-skipped)
        # In real run: show actual filesystem state
        console.print()

        if args.dry_run:
            # Simulate: remaining = all sources - cleanup successes
            # Trumped folders stay (not imported), cleanup-skipped stay (no seed)
            trumped_paths = {
                r.staging_path
                for r in result.results
                if r.status in ("trump_kept_existing", "trump_rejected", "duplicate")
            }
            # Remaining = trumped + cleanup-skipped (cleanup successes would be moved)
            simulated_remaining = trumped_paths | cleanup_would_skip_paths

            print_info(
                f"Would remain in source directory " f"({len(simulated_remaining)} folder(s)):"
            )

            if simulated_remaining:
                from rich.tree import Tree as RemainingTree

                remaining_tree = RemainingTree(f"[dim]{import_source}[/dim]")
                sorted_remaining = sorted(simulated_remaining, key=lambda p: p.name)
                for folder in sorted_remaining[:20]:
                    # Color-code by reason
                    if folder in trumped_paths:
                        remaining_tree.add(f"[dim]{folder.name}[/dim] [cyan](trumped)[/cyan]")
                    else:
                        remaining_tree.add(f"[yellow]{folder.name}[/yellow] [red](no seed)[/red]")
                if len(sorted_remaining) > 20:
                    remaining_tree.add(f"[dim]... and {len(sorted_remaining) - 20} more[/dim]")
                console.print(remaining_tree)
            else:
                print_success("Source directory would be empty (all folders cleaned up)")
        else:
            # Real run: show actual filesystem state
            print_info("Remaining in source directory:")
            remaining_folder_names: list[str] = []
            try:
                if import_source.exists():
                    for item in sorted(import_source.iterdir()):
                        if item.is_dir() and not item.name.startswith("."):
                            remaining_folder_names.append(item.name)
            except OSError:
                pass

            if remaining_folder_names:
                from rich.tree import Tree as RemainingTree

                remaining_tree = RemainingTree(f"[dim]{import_source}[/dim]")
                for folder_name in remaining_folder_names[:20]:
                    remaining_tree.add(f"[yellow]{folder_name}[/yellow]")
                if len(remaining_folder_names) > 20:
                    remaining_tree.add(
                        f"[dim]... and {len(remaining_folder_names) - 20} more[/dim]"
                    )
                console.print(remaining_tree)
            else:
                print_success("Source directory is empty (all folders cleaned up)")

        console.print()

    else:
        # No cleanup - skip to step 6
        if no_cleanup:
            print_info("Cleanup disabled (--no-cleanup), skipping Step 5")
        # Implicit: cleanup strategy is "none" in config

    # Summary
    print_step(6, 6, "Complete")

    # Build summary panel
    from rich.panel import Panel
    from rich.table import Table

    summary_table = Table(show_header=False, box=None, padding=(0, 2))
    summary_table.add_column("Label", style="dim")
    summary_table.add_column("Value", justify="right")

    total_books = len(result.results)
    needs_review_count = no_asin_count + heur_count

    summary_table.add_row("Books processed:", str(total_books))
    summary_table.add_row(
        "  [bold green][ASIN][/bold green]",
        f"[green]{asin_count}[/green]",
    )
    summary_table.add_row(
        "  [bold yellow][NO-ASIN][/bold yellow]",
        f"[yellow]{no_asin_count}[/yellow]",
    )
    summary_table.add_row(
        "  [bold magenta][HEUR][/bold magenta]",
        f"[magenta]{heur_count}[/magenta]",
    )
    summary_table.add_row("", "")
    summary_table.add_row("Duplicate policy:", dup_policy)
    summary_table.add_row("Destination root:", str(abs_library_root))
    summary_table.add_row("", "")

    if args.dry_run:
        summary_table.add_row("Ready to import:", f"[green]{result.success_count}[/green]")
    else:
        summary_table.add_row("Imported:", f"[green]{result.success_count}[/green]")

    if result.duplicate_count > 0:
        summary_table.add_row("Skipped (duplicate):", f"[yellow]{result.duplicate_count}[/yellow]")
    if result.failed_count > 0:
        summary_table.add_row("Failed:", f"[red]{result.failed_count}[/red]")

    # Trumping statistics (if any trumping occurred)
    if result.trump_replaced_count > 0:
        summary_table.add_row(
            "Trumped (replaced):", f"[green]{result.trump_replaced_count}[/green]"
        )
    if result.trump_kept_existing_count > 0:
        summary_table.add_row(
            "Trumped (kept existing):", f"[dim]{result.trump_kept_existing_count}[/dim]"
        )
    if result.trump_rejected_count > 0:
        summary_table.add_row(
            "Trumped (rejected):", f"[yellow]{result.trump_rejected_count}[/yellow]"
        )

    # Cleanup statistics (if cleanup was enabled)
    # Use "would" language in dry-run mode to make it clear these are predictions
    if cleanup_success_count > 0:
        if args.dry_run:
            summary_table.add_row(
                "Cleanup (would succeed):", f"[green]{cleanup_success_count}[/green]"
            )
        else:
            summary_table.add_row("Cleanup (success):", f"[green]{cleanup_success_count}[/green]")
    if cleanup_skipped_count > 0:
        if args.dry_run:
            summary_table.add_row("Cleanup (would skip):", f"[dim]{cleanup_skipped_count}[/dim]")
        else:
            summary_table.add_row("Cleanup (skipped):", f"[dim]{cleanup_skipped_count}[/dim]")
    if cleanup_failed_count > 0:
        if args.dry_run:
            summary_table.add_row("Cleanup (would fail):", f"[red]{cleanup_failed_count}[/red]")
        else:
            summary_table.add_row("Cleanup (failed):", f"[red]{cleanup_failed_count}[/red]")

    if needs_review_count > 0:
        # Build breakdown of what needs review
        review_parts = []
        if no_asin_count > 0:
            review_parts.append(f"[NO-ASIN]={no_asin_count}")
        if heur_count > 0:
            review_parts.append(f"[HEUR]={heur_count}")
        review_breakdown = f" ({', '.join(review_parts)})" if review_parts else ""
        summary_table.add_row(
            "Needs review:",
            f"[yellow]{needs_review_count}[/yellow]{review_breakdown}",
        )

    if args.dry_run:
        panel_title = "[bold yellow]DRY RUN Summary[/bold yellow]"
        panel_border = "yellow"
        footer = "\n[yellow]⚠️  DRY RUN: No files were moved or renamed[/yellow]"
    else:
        panel_title = "[bold green]Import Summary[/bold green]"
        panel_border = "green"
        footer = f"\n[green]✅ Import completed: {result.success_count} book(s) imported[/green]"

    console.print()
    console.print(Panel(summary_table, title=panel_title, border_style=panel_border))
    console.print(footer)
    console.print()

    # Trigger ABS scan (if not dry run and not --no-scan)
    if not args.dry_run and not args.no_scan and result.success_count > 0:
        trigger_mode = abs_config.import_settings.trigger_scan
        if trigger_mode != "none":
            try:
                with AbsClient(
                    host=abs_config.host,
                    api_key=abs_config.api_key,
                    timeout=abs_config.timeout_seconds,
                ) as scan_client:
                    if trigger_scan_safe(scan_client, target_library.id):
                        print_success("Triggered ABS library scan")
                    else:
                        print_warning(
                            "Failed to trigger ABS scan (files will appear on next scheduled scan)"
                        )
            except Exception as e:
                print_warning(f"Could not trigger ABS scan: {e}")

    return 1 if result.failed_count > 0 else 0


def cmd_abs_check_duplicate(args: argparse.Namespace) -> int:
    """Check if an ASIN already exists in the ABS library.

    Quick lookup for duplicate detection using in-memory index from ABS API.
    """
    from mamfast.abs import AbsClient, asin_exists, build_asin_index, is_valid_asin
    from mamfast.config import reload_settings

    asin = args.asin.upper().strip()

    # Validate ASIN format
    if not is_valid_asin(asin):
        print_error(f"Invalid ASIN format: {asin}")
        print_info("ASIN should be 10 characters starting with B0")
        return 1

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

    # Connect to ABS and build index
    print_info(f"Checking ASIN {asin} against ABS library...")
    try:
        client = AbsClient(
            host=abs_config.host,
            api_key=abs_config.api_key,
            timeout=abs_config.timeout_seconds,
        )
        asin_index = build_asin_index(client, target_library.id)
    except Exception as e:
        fatal_error(f"Failed to query ABS: {e}")
        return 1

    # Check index
    exists, existing_path = asin_exists(asin_index, asin)

    if exists:
        entry = asin_index[asin]
        print_warning(f"ASIN {asin} already exists:")
        print_info(f"  Title: {entry.title}")
        if entry.author:
            print_info(f"  Author: {entry.author}")
        print_info(f"  Path: {entry.path}")
        return 1
    else:
        print_success(f"ASIN {asin} not found in library - safe to import")
        return 0


def cmd_abs_trump_check(args: argparse.Namespace) -> int:
    """Preview trumping decisions for staged folders.

    Shows what would be replaced, kept, or rejected based on quality comparison
    against existing library content. Does not modify any files.
    """
    from pathlib import Path

    from mamfast.abs import AbsClient, asin_exists, build_asin_index, discover_staged_books
    from mamfast.abs.asin import extract_asin
    from mamfast.abs.importer import parse_mam_folder_name
    from mamfast.abs.paths import PathMapper
    from mamfast.abs.trumping import (
        TrumpDecision,
        TrumpPrefs,
        adjust_for_aggressiveness,
        decide_trump,
        extract_trumpable_meta,
        is_multi_file_layout,
    )
    from mamfast.config import reload_settings
    from mamfast.console import (
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
    trump_prefs_preview = TrumpPrefs(
        enabled=True,
        aggressiveness=trump_prefs.aggressiveness,
        min_bitrate_increase_kbps=trump_prefs.min_bitrate_increase_kbps,
        prefer_chapters=trump_prefs.prefer_chapters,
        prefer_stereo=trump_prefs.prefer_stereo,
        min_duration_ratio=trump_prefs.min_duration_ratio,
        max_duration_ratio=trump_prefs.max_duration_ratio,
        archive_root=trump_prefs.archive_root,
        archive_by_year=trump_prefs.archive_by_year,
        own_ripper_tags=trump_prefs.own_ripper_tags,
    )

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
    except Exception as e:
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


def cmd_abs_restore(args: argparse.Namespace) -> int:
    """Restore archived books to the library.

    Lists available archives or restores a specific archived book
    back to the library root.
    """
    from pathlib import Path

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


def cmd_abs_cleanup(args: argparse.Namespace) -> int:
    """Cleanup Libation source files after import.

    Standalone cleanup command for manually triggering cleanup of
    already-imported Libation source folders. Useful when:
    - Import was run without cleanup enabled
    - Cleanup failed during import and needs retry
    - Batch cleanup of historical imports
    """
    import logging

    from mamfast.abs.cleanup import (
        CleanupResult,
        CleanupStrategy,
        cleanup_source,
        is_cleanup_eligible,
        verify_seed_exists,
    )
    from mamfast.config import build_cleanup_prefs, reload_settings

    logger = logging.getLogger(__name__)

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
    from dataclasses import replace

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
        candidates = [p for p in args.paths if p.is_dir()]
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
            seed_exists, seed_path = verify_seed_exists(folder, seed_root)
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
    from rich.panel import Panel
    from rich.table import Table

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


def cmd_abs_rename(args: argparse.Namespace) -> int:
    """Rename audiobook folders in ABS library to match MAM naming schema.

    Normalizes folder names in your Audiobookshelf library to follow
    the MAM naming convention for consistency and better organization.
    """
    from pathlib import Path

    from mamfast.abs.rename import (
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
                )
                print_info("ABS search enabled")
            except Exception as e:
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
            rename_files_inside=args.rename_files_inside,
        )
    finally:
        if abs_client:
            abs_client.close()

    # Generate report if requested
    if args.report:
        generate_report(
            results,
            candidates,
            summary,
            args.report,
            source_dir=source_dir,
            dry_run=args.dry_run,
        )
        print_success(f"Report written to {args.report}")

    # Return error code if there were failures
    if summary.errors > 0:
        return 1
    return 0


def cmd_abs_orphans(args: argparse.Namespace) -> int:
    """Find and clean up orphaned folders in ABS library.

    Orphaned folders have metadata.json but no audio files. These are
    often created by ABS when it creates duplicate library entries.
    """
    import json as json_module
    from datetime import UTC, datetime

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
        if settings and settings.audiobookshelf.path_map:
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

    from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

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
            console.print(f"\n  [red]ORPHAN:[/]  {rel_path}")
            console.print(f"  [green]MATCH:[/]   {match_rel}")
            console.print(f"  [dim]Score: {orphan.match_score:.1%}, Files: {orphan.files}[/]")

    # Show orphaned folders without matches
    if result.orphaned_no_match:
        console.print("\n[bold yellow]Orphaned folders with NO matching folder:[/]")
        for orphan in sorted(result.orphaned_no_match, key=lambda x: str(x.path)):
            rel_path = orphan.path.relative_to(source_dir)
            console.print(f"  {rel_path}")
            console.print(f"    [dim]Files: {orphan.files}[/]")

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
        with open(args.report, "w", encoding="utf-8") as f:
            json_module.dump(report_data, f, indent=2)
        print_success(f"Report written to {args.report}")

    # Cleanup if requested
    if args.cleanup or args.cleanup_all:
        print_step(2, total_steps, "Cleaning up orphaned folders")

        if args.cleanup_all:
            # Clean up ALL orphans (dangerous)
            all_orphans = result.orphaned_with_match + result.orphaned_no_match
            if not args.dry_run:
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
            "\n[dim]Use --cleanup to remove orphans with matches, " "or --cleanup-all for all.[/]"
        )

    return 0


def cmd_abs_resolve_asins(args: argparse.Namespace) -> int:
    """Resolve ASINs for Unknown/ books via ABS metadata search.

    Phase 5: Batch search Audible (via ABS) to find ASINs for books
    that were imported without ASIN and placed in Unknown/.
    """
    import json as json_module
    from datetime import UTC, datetime

    from mamfast.abs import AbsClient, resolve_asin_via_abs_search
    from mamfast.config import reload_settings

    print_header("ABS ASIN Resolver", dry_run=args.dry_run)

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    abs_config = settings.audiobookshelf
    if not abs_config.enabled:
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
                    sidecar_path.write_text(
                        json_module.dumps(sidecar_data, indent=2, sort_keys=True)
                    )
                    print_info(f"  Wrote: {sidecar_path.name}")
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


def main() -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args()

    # Setup logging (file only, console output handled by Rich)
    from mamfast.config import reload_settings
    from mamfast.logging_setup import setup_logging

    log_level = "DEBUG" if args.verbose else "INFO"

    # Get log file from config
    log_file = None
    try:
        settings = reload_settings(config_file=args.config)
        log_file = settings.paths.log_file
    except Exception:
        pass  # Config may not exist yet; logging works without log file

    # Use Rich console logging for readable output, but keep it quiet unless verbose
    setup_logging(
        log_level=log_level,
        log_file=log_file,
        rich_console=True,
        quiet_console=not args.verbose,
    )

    # No command - show help
    if args.command is None:
        parser.print_help()
        return 0

    # Run command
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
