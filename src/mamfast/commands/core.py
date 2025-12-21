"""Core workflow commands for MAMFast CLI.

These commands handle the main audiobook processing pipeline:
scan → discover → prepare → metadata → torrent → upload → run
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from mamfast.console import (
    console,
    fatal_error,
    print_dry_run,
    print_error,
    print_header,
    print_info,
    print_release_table,
    print_step,
    print_success,
    print_summary,
    print_warning,
    render_libation_status,
)

logger = logging.getLogger(__name__)


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
    staged_dirs: list[Path]
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
    from mamfast.logging_setup import set_console_quiet
    from mamfast.qbittorrent import test_connection, upload_torrent

    print_header("Upload Torrents", dry_run=args.dry_run)

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    # Quiet mode for clean Rich UI
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
        upload_success, _ = result

        if upload_success:
            print_success("Uploaded")
            success += 1
        else:
            print_error("Failed to upload")
            failed += 1

    set_console_quiet(False)
    print_summary(success, failed)
    return 0 if failed == 0 else 1


def cmd_run(args: argparse.Namespace) -> int:
    """Run full pipeline with run lock protection."""
    from mamfast.config import reload_settings
    from mamfast.exceptions import StateLockError
    from mamfast.logging_setup import set_console_quiet
    from mamfast.utils.state import run_lock
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

    # Run lock to prevent concurrent instances
    try:
        with run_lock(force=args.no_run_lock):
            result = full_run(
                skip_scan=args.skip_scan,
                skip_metadata=args.skip_metadata,
                dry_run=args.dry_run,
            )
    except StateLockError as e:
        set_console_quiet(False)
        fatal_error(str(e), "Another instance is running")
        return 1

    set_console_quiet(False)

    if result.failed > 0:
        return 1
    return 0
