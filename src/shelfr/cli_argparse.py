"""MAMFast CLI - Legacy argparse command-line interface.

⚠ DEPRECATED: This module is deprecated and will be removed in v2.0.
Use the Typer-based CLI via `mamfast` command instead.

This module is preserved for backward compatibility with existing scripts
and tests. No new features will be added to this interface.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from shelfr import __version__
from shelfr.commands import (  # Import all command handlers from the commands subpackage
    add_libation_parser,
    cmd_abs_check_duplicate,
    cmd_abs_cleanup,
    cmd_abs_import,
    cmd_abs_init,
    cmd_abs_orphans,
    cmd_abs_rename,
    cmd_abs_resolve_asins,
    cmd_abs_restore,
    cmd_abs_trump_check,
    cmd_check,
    cmd_check_duplicates,
    cmd_check_suspicious,
    cmd_config,
    cmd_preview_naming,
    cmd_run,
    cmd_state,
    cmd_status,
    cmd_validate,
    cmd_validate_config,
)
from shelfr.utils.validation import validate_asin

# Deprecation logger - warning emitted at runtime in build_parser()
_deprecation_logger = logging.getLogger("mamfast.deprecation")
_deprecation_warned = False


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all subcommands."""
    global _deprecation_warned
    if not _deprecation_warned:
        _deprecation_logger.warning(
            "cli_argparse is deprecated and will be removed in v2.0. "
            "Use the 'mamfast' Typer CLI instead."
        )
        _deprecation_warned = True

    parser = argparse.ArgumentParser(
        prog="mamfast",
        description="Fast MAM audiobook upload automation tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  mamfast run               # Full pipeline: scan → upload
  mamfast run --skip-scan   # Full pipeline without Libation scan
  mamfast status            # Show processing status
  mamfast check             # Run health checks

Libation Management:
  mamfast libation          # Show library status dashboard
  mamfast libation scan     # Check Audible for new purchases
  mamfast libation liberate # Download all pending audiobooks
  mamfast libation search   # Search your audiobook library
  mamfast libation guide    # Detailed Libation integration guide
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

    # NOTE: Individual step commands (scan, discover, prepare, torrent, upload)
    # have been removed from the main CLI. Use:
    #   - `mamfast libation scan` and `mamfast libation list` for Libation operations
    #   - `mamfast tools prepare` for staging releases
    #   - `mamfast run` for the full pipeline (handles all steps internally)

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
    run_parser.add_argument(
        "--no-run-lock",
        action="store_true",
        help="DANGEROUS: Bypass run lock (can cause data corruption if multiple instances run)",
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
        "-a",
        "--asin",
        type=validate_asin,
        metavar="ASIN",
        help="Validate specific release by ASIN only (format: B0XXXXXXXXX)",
    )
    validate_parser.add_argument(
        "-j",
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
    # preview-naming: Preview naming transformations
    # -------------------------------------------------------------------------
    preview_naming_parser = subparsers.add_parser(
        "preview-naming",
        help="Preview naming transformations without making changes",
        epilog="Shows before/after for title filtering and folder renaming.",
    )
    preview_naming_parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=20,
        help="Maximum number of releases to process (default: 20)",
    )
    preview_naming_parser.add_argument(
        "-a",
        "--asin",
        type=validate_asin,
        metavar="ASIN",
        help="Preview specific release by ASIN only (format: B0XXXXXXXXX)",
    )
    preview_naming_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    preview_naming_parser.set_defaults(func=cmd_preview_naming)

    # -------------------------------------------------------------------------
    # check-duplicates: Find potential duplicate releases
    # -------------------------------------------------------------------------
    duplicates_parser = subparsers.add_parser(
        "check-duplicates",
        help="Find potential duplicate releases in library using fuzzy matching",
        epilog="Uses RapidFuzz to find near-duplicate titles.",
    )
    duplicates_parser.add_argument(
        "-t",
        "--threshold",
        type=int,
        default=85,
        help="Minimum similarity percentage to consider duplicate (default: 85)",
    )
    duplicates_parser.add_argument(
        "-n",
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
    duplicates_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Output as JSON",
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
        "-t",
        "--threshold",
        type=int,
        default=50,
        help="Maximum similarity below which a change is suspicious (default: 50)",
    )
    suspicious_parser.add_argument(
        "-a",
        "--asin",
        type=validate_asin,
        metavar="ASIN",
        help="Check specific release by ASIN only (format: B0XXXXXXXXX)",
    )
    suspicious_parser.add_argument(
        "--include-processed",
        action="store_true",
        help="Include already processed releases in scan",
    )
    suspicious_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    suspicious_parser.set_defaults(func=cmd_check_suspicious)

    # -------------------------------------------------------------------------
    # state: State management commands
    # -------------------------------------------------------------------------
    state_parser = subparsers.add_parser(
        "state",
        help="Manage processed.json state (list, prune, retry, clear)",
        epilog="Use 'mamfast state <subcommand> --help' for subcommand details.",
    )
    state_subparsers = state_parser.add_subparsers(
        dest="state_command",
        title="state subcommands",
        metavar="<subcommand>",
    )

    # state list
    state_list_parser = state_subparsers.add_parser(
        "list",
        help="List state entries (processed and/or failed)",
    )
    state_list_parser.add_argument(
        "--processed",
        action="store_true",
        help="Show only processed entries",
    )
    state_list_parser.add_argument(
        "--failed",
        action="store_true",
        help="Show only failed entries",
    )
    state_list_parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=20,
        help="Maximum entries to show (default: 20)",
    )
    state_list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Output as JSON (machine-readable)",
    )

    # state prune
    state_subparsers.add_parser(
        "prune",
        help="Remove stale entries with missing required paths",
        epilog="Tip: Use 'mamfast --dry-run state prune' to preview changes.",
    )

    # state retry
    state_retry_parser = state_subparsers.add_parser(
        "retry",
        help="Clear a failed entry to allow re-processing",
    )
    state_retry_parser.add_argument(
        "asin",
        help="ASIN or identifier to clear from failed state",
    )

    # state clear
    state_clear_parser = state_subparsers.add_parser(
        "clear",
        help="Clear a processed entry to force full re-run",
    )
    state_clear_parser.add_argument(
        "asin",
        help="ASIN or identifier to clear from processed state",
    )

    # state export
    state_export_parser = state_subparsers.add_parser(
        "export",
        help="Export state to JSON file",
    )
    state_export_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Output file path (default: stdout)",
    )

    state_parser.set_defaults(func=cmd_state)

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
    abs_import_parser.add_argument(
        "--no-metadata",
        action="store_true",
        help="Disable metadata.json generation (ignore config setting)",
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
        type=validate_asin,
        metavar="ASIN",
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
        "--detailed",
        action="store_true",
        dest="detailed",
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
        "-a",
        "--asin",
        type=str,
        metavar="ASIN",
        help="Filter archives by ASIN (format: B0XXXXXXXXX)",
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
        "--force",
        action="store_true",
        help="Rename files inside folders even when folder names are already correct",
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

    # -------------------------------------------------------------------------
    # libation: Enhanced Libation CLI wrapper
    # -------------------------------------------------------------------------
    add_libation_parser(subparsers)

    return parser


def main() -> int:
    """Main entry point.

    ⚠ DEPRECATED: This entry point is deprecated. Use `mamfast` instead.
    """
    # Show deprecation banner
    from shelfr.console import console

    console.print("\n[yellow]⚠  This argparse CLI is deprecated. Use 'mamfast' instead.[/yellow]")
    console.print("[dim]This interface will be removed in v2.0[/dim]\n")

    parser = build_parser()
    args = parser.parse_args()

    # Setup logging (file only, console output handled by Rich)
    from shelfr.config import reload_settings
    from shelfr.logging_setup import setup_logging

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
