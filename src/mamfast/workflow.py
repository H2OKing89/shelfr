"""
Workflow orchestration for the MAMFast pipeline.

Coordinates all processing steps:
1. Libation scan
2. Discovery (+ validation)
3. Staging (hardlink + rename)
4. Metadata (Audnex + MediaInfo) (+ validation)
5. Torrent creation (mkbrr)
6. Pre-upload validation
7. Upload (qBittorrent)
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from mamfast.config import get_settings
from mamfast.console import (
    console,
    print_dry_run,
    print_error,
    print_info,
    print_step,
    print_success,
    print_summary,
    print_warning,
)
from mamfast.hardlinker import stage_release
from mamfast.libation import run_liberate, run_scan
from mamfast.metadata import fetch_metadata, generate_mam_json_for_release
from mamfast.mkbrr import create_torrent
from mamfast.models import AudiobookRelease, ProcessingResult, ReleaseStatus
from mamfast.qbittorrent import upload_torrent
from mamfast.utils.retry import NETWORK_EXCEPTIONS, retry_with_backoff
from mamfast.utils.state import is_processed, mark_failed, mark_processed
from mamfast.validation import (
    ChapterIntegrityChecker,
    DiscoveryValidation,
    MetadataValidation,
    PreUploadValidation,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Progress Callback Types
# =============================================================================


class ProgressStage(Enum):
    """Pipeline stages for progress reporting."""

    SCAN = "scan"
    DISCOVERY = "discovery"
    VALIDATION = "validation"
    STAGING = "staging"
    METADATA = "metadata"
    TORRENT = "torrent"
    UPLOAD = "upload"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class ProgressInfo:
    """Progress information passed to callbacks."""

    stage: ProgressStage
    release_index: int = 0  # Current release (1-based)
    release_total: int = 0  # Total releases
    release_name: str = ""
    message: str = ""
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


# Type alias for progress callback
ProgressCallback = Callable[[ProgressInfo], None]


@dataclass
class PipelineResult:
    """Result of running the full pipeline."""

    total: int
    successful: int
    failed: int
    skipped: int
    results: list[ProcessingResult]
    duration_seconds: float


# =============================================================================
# Retry-wrapped operations
# =============================================================================


@retry_with_backoff(
    max_attempts=3,
    base_delay=2.0,
    max_delay=30.0,
    exceptions=NETWORK_EXCEPTIONS,
)
def _fetch_metadata_with_retry(
    asin: str | None,
    m4b_path: Path | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    """Fetch metadata with retry logic for network failures."""
    return fetch_metadata(asin=asin, m4b_path=m4b_path)


@retry_with_backoff(
    max_attempts=3,
    base_delay=1.0,
    max_delay=15.0,
    exceptions=NETWORK_EXCEPTIONS,
)
def _upload_torrent_with_retry(
    torrent_path: Path,
    save_path: Path | None = None,
) -> bool:
    """Upload torrent with retry logic for network failures."""
    return upload_torrent(torrent_path=torrent_path, save_path=save_path)


# =============================================================================
# Single Release Processing
# =============================================================================


def process_single_release(
    release: AudiobookRelease,
    skip_metadata: bool = False,
    preset: str | None = None,
    progress_callback: ProgressCallback | None = None,
    release_index: int = 0,
    release_total: int = 0,
) -> ProcessingResult:
    """
    Process a single release through the full pipeline.

    Steps:
    1. Stage (hardlink + rename)
    2. Fetch metadata (optional)
    3. Create torrent
    4. Upload to qBittorrent
    5. Mark as processed

    Args:
        release: AudiobookRelease to process
        skip_metadata: Skip Audnex/MediaInfo fetching
        preset: Override mkbrr preset
        progress_callback: Optional callback for progress updates
        release_index: Current release number (1-based) for progress
        release_total: Total releases being processed

    Returns:
        ProcessingResult with success/failure info
    """
    settings = get_settings()
    start_time = time.time()

    def notify(stage: ProgressStage, message: str = "", **extra: Any) -> None:
        """Helper to send progress updates."""
        if progress_callback:
            progress_callback(
                ProgressInfo(
                    stage=stage,
                    release_index=release_index,
                    release_total=release_total,
                    release_name=release.display_name,
                    message=message,
                    extra=extra,
                )
            )

    logger.debug(f"Processing: {release.display_name}")

    try:
        # ---------------------------------------------------------------------
        # 0. Discovery Validation (pre-flight checks)
        # ---------------------------------------------------------------------
        notify(ProgressStage.VALIDATION, "Validating release...")
        logger.debug("Step 0: Discovery validation")

        discovery_validator = DiscoveryValidation()
        discovery_result = discovery_validator.validate(release)

        # Log validation results
        for check in discovery_result.checks:
            if check.passed:
                logger.debug(f"  {check.icon} {check.name}: {check.message}")
            elif check.severity == "warning":
                print_warning(f"Validation: {check.message}")
            else:
                logger.warning(f"  {check.icon} {check.name}: {check.message}")

        # Fail on errors (but allow warnings)
        if not discovery_result.passed:
            failed_checks = [
                c for c in discovery_result.checks if not c.passed and c.severity == "error"
            ]
            error_msgs = [c.message for c in failed_checks]
            raise RuntimeError("Discovery validation failed:\n  - " + "\n  - ".join(error_msgs))

        if discovery_result.warning_count > 0:
            print_warning(f"Validation passed with {discovery_result.warning_count} warning(s)")
        else:
            print_success("Validation passed")

        # ---------------------------------------------------------------------
        # 1. Stage
        # ---------------------------------------------------------------------
        notify(ProgressStage.STAGING, "Creating hardlinks...")
        logger.debug("Step 1: Staging release")
        staging_dir = stage_release(release)
        print_success(f"Staged to {staging_dir.name}")
        release.status = ReleaseStatus.STAGED

        # ---------------------------------------------------------------------
        # 2. Metadata (optional)
        # ---------------------------------------------------------------------
        if not skip_metadata:
            notify(ProgressStage.METADATA, "Fetching Audnex + MediaInfo...")
            logger.debug("Step 2: Fetching metadata")
            audnex_data, mediainfo_data, audnex_chapters = _fetch_metadata_with_retry(
                asin=release.asin,
                m4b_path=release.main_m4b,
            )
            release.audnex_metadata = audnex_data
            release.mediainfo_data = mediainfo_data
            release.audnex_chapters = audnex_chapters
            if audnex_data:
                print_success(f"Audnex metadata for {release.asin}")
            if audnex_chapters:
                chapter_count = len(audnex_chapters.get("chapters", []))
                print_success(f"Audnex chapters: {chapter_count} chapters")
            if mediainfo_data:
                print_success("MediaInfo extracted")
            release.status = ReleaseStatus.METADATA_FETCHED

            # -----------------------------------------------------------------
            # 2b. Metadata Validation
            # -----------------------------------------------------------------
            logger.debug("Step 2b: Metadata validation")
            metadata_validator = MetadataValidation()
            metadata_result = metadata_validator.validate(
                release, audnex_data=audnex_data, mediainfo_data=mediainfo_data
            )

            for check in metadata_result.checks:
                if not check.passed and check.severity == "warning":
                    print_warning(f"Metadata: {check.message}")

            # -----------------------------------------------------------------
            # 2c. Chapter Integrity Check
            # -----------------------------------------------------------------
            if audnex_chapters:
                logger.debug("Step 2c: Chapter integrity check")
                chapter_checker = ChapterIntegrityChecker()
                chapter_result = chapter_checker.validate(release, audnex_chapters)

                for check in chapter_result.checks:
                    if not check.passed:
                        if check.severity == "warning":
                            print_warning(f"Chapters: {check.message}")
                        else:
                            print_error(f"Chapters: {check.message}")

        # ---------------------------------------------------------------------
        # 3. Create torrent
        # ---------------------------------------------------------------------
        notify(ProgressStage.TORRENT, "Creating torrent file...")
        logger.debug("Step 3: Creating torrent")

        # Create per-release output subfolder for torrent + JSON
        release_output_dir = settings.paths.torrent_output / staging_dir.name
        release_output_dir.mkdir(parents=True, exist_ok=True)

        mkbrr_result = create_torrent(
            content_path=staging_dir,
            output_dir=release_output_dir,
            preset=preset or settings.mkbrr.preset,
        )

        if not mkbrr_result.success:
            raise RuntimeError(
                f"Torrent creation failed for '{staging_dir.name}'\n"
                f"Error: {mkbrr_result.error}\n"
                f"\nTroubleshooting:\n"
                f"  1. Verify mkbrr Docker image is available: {settings.mkbrr.image}\n"
                f"     Run: docker pull {settings.mkbrr.image}\n"
                f"  2. Check preset '{settings.mkbrr.preset}' exists in "
                f"{settings.mkbrr.host_config_dir}/presets.yaml\n"
                f"  3. Verify path mappings in config.yaml:\n"
                f"     - host_data_root: {settings.mkbrr.host_data_root}\n"
                f"     - container_data_root: {settings.mkbrr.container_data_root}\n"
                f"  4. Check Docker logs: docker logs $(docker ps -lq)"
            )

        release.torrent_path = mkbrr_result.torrent_path
        release.status = ReleaseStatus.TORRENT_CREATED
        if mkbrr_result.torrent_path:
            print_success(f"Torrent: {mkbrr_result.torrent_path.name}")

        # ---------------------------------------------------------------------
        # 3b. Generate MAM fast-upload JSON (saved with torrent file)
        # ---------------------------------------------------------------------
        if not skip_metadata and (release.audnex_metadata or release.mediainfo_data):
            logger.debug("Step 3b: Generating MAM fast-upload JSON")
            mam_json_path = generate_mam_json_for_release(release, output_dir=release_output_dir)
            if mam_json_path:
                print_success(f"MAM JSON: {mam_json_path.name}")

        # ---------------------------------------------------------------------
        # 3c. Pre-Upload Validation
        # ---------------------------------------------------------------------
        logger.debug("Step 3c: Pre-upload validation")
        pre_upload_validator = PreUploadValidation(settings)
        pre_upload_result = pre_upload_validator.validate(release)

        for check in pre_upload_result.checks:
            if not check.passed:
                if check.severity == "error":
                    raise RuntimeError(f"Pre-upload validation failed: {check.message}")
                elif check.severity == "warning":
                    print_warning(f"Pre-upload: {check.message}")

        # ---------------------------------------------------------------------
        # 4. Upload to qBittorrent
        # ---------------------------------------------------------------------
        notify(ProgressStage.UPLOAD, "Uploading to qBittorrent...")
        logger.debug("Step 4: Uploading to qBittorrent")

        if release.torrent_path is None:
            raise RuntimeError(
                "Internal error: No torrent path after successful mkbrr creation\n"
                f"This is a bug. Please report with:\n"
                f"  - Release: {release.display_name}\n"
                f"  - mkbrr result: {mkbrr_result}"
            )

        # Use configured save_path (container path) + release folder name
        # Only needed when auto_tmm is disabled
        if settings.qbittorrent.auto_tmm:
            # Auto TMM: qBittorrent manages save path via category
            qb_save_path = None
        elif settings.qbittorrent.save_path:
            # Manual: build save path from config + release folder
            qb_save_path = Path(settings.qbittorrent.save_path) / staging_dir.name
        else:
            # No save_path configured - let qBittorrent use its default
            qb_save_path = None

        success = _upload_torrent_with_retry(
            torrent_path=release.torrent_path,
            save_path=qb_save_path,
        )

        if not success:
            qb_host = settings.qbittorrent.host
            raise RuntimeError(
                f"Failed to upload torrent to qBittorrent\n"
                f"Torrent: {release.torrent_path}\n"
                f"Save path: {staging_dir}\n"
                f"\nTroubleshooting:\n"
                f"  1. Verify qBittorrent is running and accessible at {qb_host}\n"
                f"  2. Check credentials in config/.env:\n"
                f"     - QB_USERNAME: {settings.qbittorrent.username}\n"
                f"     - QB_PASSWORD: (check it's correct)\n"
                f"  3. Verify WebUI is enabled in qBittorrent preferences\n"
                f"  4. Check qBittorrent logs for errors\n"
                f"  5. Test connection: curl -u username:password "
                f"{qb_host}/api/v2/app/version"
            )

        release.status = ReleaseStatus.UPLOADED
        print_success("Uploaded to qBittorrent")

        # ---------------------------------------------------------------------
        # 5. Mark as complete
        # ---------------------------------------------------------------------
        release.status = ReleaseStatus.COMPLETE
        mark_processed(release)

        duration = time.time() - start_time
        notify(ProgressStage.COMPLETE, f"Completed in {duration:.1f}s")

        return ProcessingResult(
            release=release,
            success=True,
            torrent_path=release.torrent_path,
            duration_seconds=duration,
        )

    except Exception as e:
        duration = time.time() - start_time
        error_msg = str(e)

        notify(ProgressStage.FAILED, error_msg, error=error_msg)
        print_error(f"Failed: {error_msg}")
        logger.debug(f"Full error for {release.display_name}: {error_msg}")

        release.status = ReleaseStatus.FAILED
        release.error = error_msg
        mark_failed(release, error_msg)

        return ProcessingResult(
            release=release,
            success=False,
            error=error_msg,
            duration_seconds=duration,
        )


# =============================================================================
# Full Pipeline
# =============================================================================


def full_run(
    skip_scan: bool = False,
    skip_metadata: bool = False,
    dry_run: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> PipelineResult:
    """
    Run the complete pipeline from Libation scan to qBittorrent upload.

    Args:
        skip_scan: Skip Libation scan step
        skip_metadata: Skip metadata fetching
        dry_run: Show what would happen without making changes
        progress_callback: Optional callback for progress updates

    Returns:
        PipelineResult with statistics
    """
    start_time = time.time()

    def notify(stage: ProgressStage, message: str = "", **extra: Any) -> None:
        """Helper to send progress updates."""
        if progress_callback:
            progress_callback(
                ProgressInfo(
                    stage=stage,
                    message=message,
                    extra=extra,
                )
            )

    # -------------------------------------------------------------------------
    # 1. Libation scan + liberate (optional)
    # -------------------------------------------------------------------------
    if not skip_scan:
        notify(ProgressStage.SCAN, "Running Libation scan...")
        print_step(1, 4, "Libation Scan")
        if not dry_run:
            scan_result = run_scan()
            if not scan_result.success:
                print_warning(f"Libation scan returned non-zero: {scan_result.returncode}")

            print_info("Running liberate (downloading new books)...")
            liberate_result = run_liberate()
            if not liberate_result.success:
                print_warning(f"Libation liberate returned non-zero: {liberate_result.returncode}")
            else:
                print_success("Libation scan complete")
        else:
            print_dry_run("Would run Libation scan + liberate")

    # -------------------------------------------------------------------------
    # 2. Discover new releases
    # -------------------------------------------------------------------------
    notify(ProgressStage.DISCOVERY, "Discovering new releases...")
    step_num = 1 if skip_scan else 2
    print_step(step_num, 4 if not skip_scan else 3, "Discovering Releases")

    from mamfast.discovery import get_new_releases

    try:
        settings = get_settings()
        releases = get_new_releases(
            settings.paths.library_root,
            settings.paths.state_file,
        )
    except NotImplementedError:
        logger.warning("Discovery not yet implemented - no releases to process")
        releases = []

    if not releases:
        console.print("[dim]No new releases found[/]")
        return PipelineResult(
            total=0,
            successful=0,
            failed=0,
            skipped=0,
            results=[],
            duration_seconds=time.time() - start_time,
        )

    console.print(f"Found [highlight]{len(releases)}[/] new release(s)\n")

    # -------------------------------------------------------------------------
    # 3. Process each release
    # -------------------------------------------------------------------------
    results = []
    skipped = 0
    settings = get_settings()

    # Process each release
    for i, release in enumerate(releases, 1):
        console.print(f"\n[bold cyan][{i}/{len(releases)}][/] {release.display_name}")

        # Check if already processed
        identifier = release.asin or str(release.source_dir)
        if identifier and is_processed(identifier):
            print_info("Skipping (already processed)")
            skipped += 1
            continue

        if dry_run:
            # Show detailed dry-run info for each step
            print_dry_run("Steps that would be performed:")

            # Step 1: Stage
            if release.source_dir:
                staging_name = release.source_dir.name
                seed_root = settings.paths.seed_root
                print_dry_run(f"STAGE → {seed_root / staging_name}")

            # Step 2: Metadata
            if not skip_metadata:
                if release.asin:
                    print_dry_run(f"METADATA → Fetch Audnex for {release.asin}")
                if release.main_m4b:
                    print_dry_run(f"METADATA → MediaInfo on {release.main_m4b.name}")
            else:
                print_dry_run("METADATA → [SKIPPED]")

            # Step 3: Torrent
            print_dry_run(f"TORRENT → Create with preset '{settings.mkbrr.preset}'")

            # Step 4: Upload
            print_dry_run(f"UPLOAD → Add to qBittorrent ({settings.qbittorrent.category})")

            # Step 5: Mark processed
            print_dry_run(f"STATE → Mark {identifier} as processed")
            continue

        result = process_single_release(
            release,
            skip_metadata=skip_metadata,
            progress_callback=progress_callback,
            release_index=i,
            release_total=len(releases),
        )
        results.append(result)

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------
    duration = time.time() - start_time
    successful = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success)

    notify(
        ProgressStage.COMPLETE,
        f"Pipeline complete: {successful} succeeded, {failed} failed, {skipped} skipped",
        successful=successful,
        failed=failed,
        skipped=skipped,
    )

    print_summary(successful, failed, skipped, duration)

    return PipelineResult(
        total=len(releases),
        successful=successful,
        failed=failed,
        skipped=skipped,
        results=results,
        duration_seconds=duration,
    )


def prepare_only(dry_run: bool = False) -> list[Path]:
    """
    Discover and stage releases without creating torrents.

    Args:
        dry_run: If True, don't actually stage releases, just report what would happen.

    Returns:
        List of staging directories created (or would be created if dry_run).
    """
    from mamfast.discovery import get_new_releases

    logger.info("Discovering and staging releases...")

    settings = get_settings()
    releases = get_new_releases(
        settings.paths.library_root,
        settings.paths.state_file,
    )

    if not releases:
        logger.info("No new releases found")
        return []

    staged_dirs: list[Path] = []
    for release in releases:
        if release.source_dir is None:
            logger.warning(f"Skipping release without source_dir: {release.title}")
            continue

        if dry_run:
            logger.info(f"[DRY RUN] Would stage: {release.title}")
            # For dry run, just track what would be staged
            staged_dirs.append(release.source_dir)
        else:
            logger.info(f"Staging: {release.title}")
            # The release source_dir is the staged location
            staged_dirs.append(release.source_dir)

    logger.info(f"Prepared {len(staged_dirs)} release(s)")
    return staged_dirs


def create_torrents_only(
    staging_dirs: list[Path] | None = None,
    preset: str | None = None,
) -> list[Path]:
    """
    Create torrents for staged releases.

    Args:
        staging_dirs: Specific dirs to process (None = find all staged)
        preset: mkbrr preset to use

    Returns:
        List of created .torrent paths
    """
    settings = get_settings()

    if staging_dirs is None:
        # Find all directories in library root
        library_root = settings.paths.library_root
        if not library_root.exists():
            logger.warning(f"Library root does not exist: {library_root}")
            return []

        staging_dirs = [d for d in library_root.iterdir() if d.is_dir()]

    created = []

    for staging_dir in staging_dirs:
        logger.info(f"Creating torrent for: {staging_dir.name}")

        result = create_torrent(
            content_path=staging_dir,
            preset=preset or settings.mkbrr.preset,
        )

        if result.success and result.torrent_path:
            created.append(result.torrent_path)
        else:
            logger.error(f"Failed: {result.error}")

    logger.info(f"Created {len(created)} torrent(s)")
    return created


def upload_only(torrent_paths: list[Path] | None = None) -> int:
    """
    Upload torrents to qBittorrent.

    Args:
        torrent_paths: Specific torrents to upload (None = find all in output dir)

    Returns:
        Number of successfully uploaded torrents
    """
    settings = get_settings()

    if torrent_paths is None:
        # Find all .torrent files in output directory
        output_dir = settings.paths.torrent_output
        if not output_dir.exists():
            logger.warning(f"Torrent output dir does not exist: {output_dir}")
            return 0

        torrent_paths = list(output_dir.glob("*.torrent"))

    uploaded = 0

    for torrent_path in torrent_paths:
        # Determine save_path only if auto_tmm is disabled
        if settings.qbittorrent.auto_tmm:
            # Auto TMM: qBittorrent manages save path via category
            qb_save_path = None
        elif settings.qbittorrent.save_path:
            # Manual: build save path from config + release folder name
            # Strip mkbrr preset prefix from torrent name if present
            staging_name = torrent_path.stem
            preset_prefix = settings.mkbrr.preset
            if preset_prefix and staging_name.startswith(f"{preset_prefix}_"):
                staging_name = staging_name[len(preset_prefix) + 1 :]

            qb_save_path = Path(settings.qbittorrent.save_path) / staging_name
        else:
            # No save_path configured - let qBittorrent use its default
            qb_save_path = None

        logger.info(f"Uploading: {torrent_path.name}")

        success = upload_torrent(
            torrent_path=torrent_path,
            save_path=qb_save_path,
        )

        if success:
            uploaded += 1

    logger.info(f"Uploaded {uploaded}/{len(torrent_paths)} torrent(s)")
    return uploaded
