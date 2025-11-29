"""MAMFast CLI - Command-line interface for audiobook upload automation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mamfast import __version__


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

    return parser


# =============================================================================
# Command implementations (stubs - to be filled in)
# =============================================================================


def cmd_scan(args: argparse.Namespace) -> int:
    """Run Libation scan."""
    from mamfast.config import reload_settings
    from mamfast.libation import run_scan

    print("🔍 Running Libation scan...")

    try:
        reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        print(f"❌ Config error: {e}")
        return 1

    if args.dry_run:
        print("  [DRY RUN] Would execute: docker exec Libation /libation/LibationCli scan")
        if args.liberate:
            print("  [DRY RUN] Would execute: docker exec Libation /libation/LibationCli liberate")
        return 0

    result = run_scan()

    # Display output
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)

    if result.success:
        print("✅ Scan complete")
    else:
        print(f"❌ Scan failed (exit code: {result.returncode})")
        return result.returncode

    # Optionally run liberate to download new books
    if args.liberate:
        from mamfast.libation import run_liberate

        print("\n📥 Running Libation liberate (downloading new books)...")
        liberate_result = run_liberate()

        if liberate_result.stdout:
            print(liberate_result.stdout)
        if liberate_result.stderr:
            print(liberate_result.stderr)

        if liberate_result.success:
            print("✅ Liberate complete")
        else:
            print(f"❌ Liberate failed (exit code: {liberate_result.returncode})")
            return liberate_result.returncode

    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    """Discover new audiobooks."""
    from mamfast.config import reload_settings
    from mamfast.discovery import get_new_releases, print_release_summary, scan_library

    print("📚 Discovering audiobooks...")

    try:
        reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        print(f"❌ Config error: {e}")
        return 1

    # Show all or just new?
    show_all = getattr(args, "all", False)

    if show_all:
        releases = scan_library()
        print("\nAll releases in library:")
    else:
        releases = get_new_releases()
        print("\nNew (unprocessed) releases:")

    print_release_summary(releases)
    return 0


def cmd_prepare(args: argparse.Namespace) -> int:
    """Stage audiobooks for upload."""
    from mamfast.config import reload_settings
    from mamfast.discovery import get_new_releases, get_release_by_asin
    from mamfast.hardlinker import stage_release

    print("📦 Preparing audiobooks for upload...")

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        print(f"❌ Config error: {e}")
        return 1

    # Get releases to process
    if args.asin:
        release = get_release_by_asin(args.asin)
        if not release:
            print(f"❌ Release not found with ASIN: {args.asin}")
            return 1
        releases = [release]
    else:
        releases = get_new_releases()

    if not releases:
        print("✅ No new releases to prepare")
        return 0

    print(f"Found {len(releases)} release(s) to stage\n")

    staged = 0
    failed = 0

    for release in releases:
        print(f"  → {release.display_name}")

        if args.dry_run:
            # Hardlinks go to seed_root for qBittorrent seeding
            seed_path = settings.paths.seed_root / release.safe_dirname
            print(f"    [DRY RUN] Would hardlink to: {seed_path}")
            continue

        try:
            staging_dir = stage_release(release)
            print(f"    ✅ Hardlinked to: {staging_dir}")
            staged += 1
        except Exception as e:
            print(f"    ❌ Failed: {e}")
            failed += 1

    print(f"\n📊 Staged: {staged}, Failed: {failed}")
    return 0 if failed == 0 else 1


def cmd_metadata(args: argparse.Namespace) -> int:
    """Fetch metadata."""
    from mamfast.config import reload_settings
    from mamfast.discovery import get_release_by_asin
    from mamfast.metadata import fetch_all_metadata

    print("📋 Fetching metadata...")

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        print(f"❌ Config error: {e}")
        return 1

    # Find releases that have been staged
    staging_root = settings.paths.staging_root
    if not staging_root.exists():
        print(f"❌ Staging directory does not exist: {staging_root}")
        return 1

    staged_dirs = [d for d in staging_root.iterdir() if d.is_dir()]

    if args.asin:
        # Find specific release
        release = get_release_by_asin(args.asin)
        if not release:
            print(f"❌ Release not found with ASIN: {args.asin}")
            return 1

        # Find its staging dir - check both directory name and files inside
        from mamfast.discovery import extract_asin_from_name
        matching_dirs = []
        for d in staged_dirs:
            # Check directory name
            if args.asin in d.name:
                matching_dirs.append(d)
                continue
            # Check files inside the directory for ASIN
            for f in d.iterdir():
                asin = extract_asin_from_name(f.name)
                if asin == args.asin:
                    matching_dirs.append(d)
                    break
        staged_dirs = matching_dirs
        if not staged_dirs:
            print(f"❌ No staged directory found for ASIN: {args.asin}")
            return 1

    if not staged_dirs:
        print("✅ No staged releases to process")
        return 0

    print(f"Found {len(staged_dirs)} staged release(s)\n")

    success = 0
    for staging_dir in staged_dirs:
        print(f"  → {staging_dir.name}")

        # Find m4b file first
        m4b_files = list(staging_dir.glob("*.m4b"))
        m4b_path = m4b_files[0] if m4b_files else None

        # Extract ASIN from m4b filename (has ASIN), fallback to dir name
        from mamfast.discovery import extract_asin_from_name
        asin = None
        if m4b_path:
            asin = extract_asin_from_name(m4b_path.name)
        if not asin:
            asin = extract_asin_from_name(staging_dir.name)

        if args.dry_run:
            print(f"    [DRY RUN] Would fetch Audnex for ASIN: {asin}")
            print(f"    [DRY RUN] Would run MediaInfo on: {m4b_path}")
            continue

        audnex_data, mediainfo_data = fetch_all_metadata(
            asin=asin,
            m4b_path=m4b_path,
            output_dir=staging_dir,
        )

        if audnex_data:
            print("    ✅ Audnex: audnex.json")
        else:
            print("    ⚠️ Audnex: not found")

        if mediainfo_data:
            print("    ✅ MediaInfo: mediainfo.json")
        else:
            print("    ⚠️ MediaInfo: failed")

        success += 1

    print(f"\n📊 Processed: {success}/{len(staged_dirs)}")
    return 0


def cmd_torrent(args: argparse.Namespace) -> int:
    """Create torrents."""
    from mamfast.config import reload_settings
    from mamfast.mkbrr import check_docker_available, create_torrent

    print("🧲 Creating torrents...")

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        print(f"❌ Config error: {e}")
        return 1

    # Check Docker is available
    if not check_docker_available():
        print("❌ Docker is not available")
        return 1

    # Find staged releases
    staging_root = settings.paths.staging_root
    if not staging_root.exists():
        print(f"❌ Staging directory does not exist: {staging_root}")
        return 1

    staged_dirs = [d for d in staging_root.iterdir() if d.is_dir()]

    if args.asin:
        staged_dirs = [d for d in staged_dirs if args.asin in d.name]

    if not staged_dirs:
        print("✅ No staged releases to process")
        return 0

    preset = args.preset or settings.mkbrr.preset
    print(f"Using preset: {preset}")
    print(f"Found {len(staged_dirs)} staged release(s)\n")

    success = 0
    failed = 0

    for staging_dir in staged_dirs:
        print(f"  → {staging_dir.name}")

        if args.dry_run:
            print(f"    [DRY RUN] Would create torrent with preset: {preset}")
            continue

        result = create_torrent(
            content_path=staging_dir,
            preset=preset,
        )

        if result.success:
            print(f"    ✅ Created: {result.torrent_path}")
            success += 1
        else:
            print(f"    ❌ Failed: {result.error}")
            failed += 1

    print(f"\n📊 Created: {success}, Failed: {failed}")
    return 0 if failed == 0 else 1


def cmd_upload(args: argparse.Namespace) -> int:
    """Upload to qBittorrent."""
    from mamfast.config import reload_settings
    from mamfast.qbittorrent import test_connection, upload_torrent

    print("⬆️  Uploading to qBittorrent...")

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        print(f"❌ Config error: {e}")
        return 1

    # Test connection
    print(f"Connecting to: {settings.qbittorrent.host}")
    if not test_connection():
        print("❌ Cannot connect to qBittorrent")
        return 1
    print("✅ Connected\n")

    # Find torrent files
    torrent_dir = settings.paths.torrent_output
    if not torrent_dir.exists():
        print(f"❌ Torrent directory does not exist: {torrent_dir}")
        return 1

    torrent_files = list(torrent_dir.glob("*.torrent"))

    if not torrent_files:
        print("✅ No torrent files to upload")
        return 0

    print(f"Found {len(torrent_files)} torrent file(s)\n")

    success = 0
    failed = 0

    for torrent_path in torrent_files:
        print(f"  → {torrent_path.name}")

        # Determine save path (staging dir with matching name)
        staging_name = torrent_path.stem
        save_path = settings.paths.staging_root / staging_name

        if not save_path.exists():
            # Fallback to seed root
            save_path = settings.paths.seed_root / staging_name

        if args.dry_run:
            print(f"    [DRY RUN] Would upload with save_path: {save_path}")
            continue

        result = upload_torrent(
            torrent_path=torrent_path,
            save_path=save_path,
            paused=args.paused,
        )

        if result:
            print("    ✅ Uploaded")
            success += 1
        else:
            print("    ❌ Failed")
            failed += 1

    print(f"\n📊 Uploaded: {success}, Failed: {failed}")
    return 0 if failed == 0 else 1


def cmd_run(args: argparse.Namespace) -> int:
    """Run full pipeline."""
    from mamfast.config import reload_settings
    from mamfast.workflow import full_run

    print("🚀 Running full pipeline...")

    try:
        reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        print(f"❌ Config error: {e}")
        return 1

    result = full_run(
        skip_scan=args.skip_scan,
        skip_metadata=args.skip_metadata,
        dry_run=args.dry_run,
    )

    if result.failed > 0:
        return 1
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show status."""
    from mamfast.config import reload_settings
    from mamfast.utils.state import get_stats, load_state

    print("📊 MAMFast Status\n")

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        print(f"❌ Config error: {e}")
        return 1

    # State stats
    stats = get_stats()
    print(f"Processed releases: {stats['processed']}")
    print(f"Failed releases: {stats['failed']}")

    # Check directories
    print("\n📁 Directories:")

    lib_root = settings.paths.libation_library_root
    if lib_root.exists():
        print(f"  ✅ Library: {lib_root}")
    else:
        print(f"  ❌ Library: {lib_root} (not found)")

    staging = settings.paths.staging_root
    if staging.exists():
        staged_count = len([d for d in staging.iterdir() if d.is_dir()])
        print(f"  ✅ Staging: {staging} ({staged_count} releases)")
    else:
        print(f"  ⚠️  Staging: {staging} (not created yet)")

    torrent_out = settings.paths.torrent_output
    if torrent_out.exists():
        torrent_count = len(list(torrent_out.glob("*.torrent")))
        print(f"  ✅ Torrents: {torrent_out} ({torrent_count} files)")
    else:
        print(f"  ⚠️  Torrents: {torrent_out} (not found)")

    # Show recent processed
    state = load_state()
    processed = state.get("processed", {})

    if processed:
        print("\n📚 Recently processed:")
        # Sort by processed_at, show last 5
        items = sorted(
            processed.items(),
            key=lambda x: x[1].get("processed_at", ""),
            reverse=True,
        )[:5]

        for asin, info in items:
            title = info.get("title", "Unknown")
            author = info.get("author", "Unknown")
            print(f"  • {author} - {title} ({asin})")

    # Show failed
    failed = state.get("failed", {})
    if failed:
        print("\n⚠️  Failed releases:")
        for _asin, info in list(failed.items())[:5]:
            title = info.get("title", "Unknown")
            error = info.get("error", "Unknown error")
            print(f"  • {title}: {error}")

    return 0


def cmd_config(args: argparse.Namespace) -> int:
    """Print loaded configuration."""
    from mamfast.config import reload_settings

    try:
        settings = reload_settings(config_file=args.config)
        print("✅ Configuration loaded successfully\n")

        print("=== Environment ===")
        print(f"  Libation container: {settings.libation_container}")
        print(f"  Docker binary: {settings.docker_bin}")
        print(f"  Target UID:GID: {settings.target_uid}:{settings.target_gid}")
        print(f"  Environment: {settings.env}")
        print(f"  Log level: {settings.log_level}")

        print("\n=== Paths ===")
        print(f"  Libation library: {settings.paths.libation_library_root}")
        print(f"  Staging root: {settings.paths.staging_root}")
        print(f"  Torrent output: {settings.paths.torrent_output}")
        print(f"  Seed root: {settings.paths.seed_root}")

        print("\n=== mkbrr ===")
        print(f"  Image: {settings.mkbrr.image}")
        print(f"  Preset: {settings.mkbrr.preset}")
        print(f"  Host data root: {settings.mkbrr.host_data_root}")

        print("\n=== qBittorrent ===")
        print(f"  Host: {settings.qbittorrent.host}")
        print(f"  Category: {settings.qbittorrent.category}")
        print(f"  Tags: {settings.qbittorrent.tags}")

        print("\n=== MAM ===")
        print(f"  Max filename length: {settings.mam.max_filename_length}")
        print(f"  Allowed extensions: {settings.mam.allowed_extensions}")

        return 0

    except FileNotFoundError as e:
        print(f"❌ Config file not found: {e}")
        return 1
    except Exception as e:
        print(f"❌ Error loading config: {e}")
        return 1


def main() -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args()

    # Setup logging
    from mamfast.logging_setup import setup_logging

    log_level = "DEBUG" if args.verbose else "INFO"
    setup_logging(log_level=log_level)

    # No command given - show help
    if args.command is None:
        parser.print_help()
        return 0

    # Run the command
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
