"""MAMFast CLI - Command-line interface for audiobook upload automation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mamfast import __version__
from mamfast.console import (
    console,
    fatal_error,
    print_check_category,
    print_config_section,
    print_directory_status,
    print_dry_run,
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

    return parser


# =============================================================================
# Command implementations (stubs - to be filled in)
# =============================================================================


def cmd_scan(args: argparse.Namespace) -> int:
    """Run Libation scan."""
    from mamfast.config import reload_settings
    from mamfast.libation import run_scan

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

    print_step(1, 2 if args.liberate else 1, "Running scan")
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

    # Optionally run liberate
    if args.liberate:
        from mamfast.libation import run_liberate

        console.print()
        print_step(2, 2, "Running liberate (downloading new books)")
        liberate_result = run_liberate()

        if liberate_result.stdout:
            for line in liberate_result.stdout.strip().split("\n"):
                if line.strip():
                    print_info(line.strip())

        if liberate_result.success:
            print_success("Liberate complete")
        else:
            print_error(f"Liberate failed (exit code: {liberate_result.returncode})")
            return liberate_result.returncode

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

        if args.dry_run:
            print_dry_run(f"Would fetch Audnex for ASIN: {asin}")
            print_dry_run(f"Would run MediaInfo on: {m4b_path}")
            print_dry_run(f"Would generate MAM JSON in: {torrent_output}")
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

    config_dir = args.config.parent.parent if args.config else Path(".")
    errors_found = False

    # Validate naming.json
    naming_path = config_dir / "config" / "naming.json"
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
    categories_path = config_dir / "config" / "categories.json"
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
        pass

    # Use non-rich console for logging (file-focused)
    setup_logging(log_level=log_level, log_file=log_file, rich_console=False)

    # No command - show help
    if args.command is None:
        parser.print_help()
        return 0

    # Run command
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
