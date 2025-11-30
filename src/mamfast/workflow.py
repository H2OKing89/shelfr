"""
Workflow orchestration for the MAMFast pipeline.

Coordinates all processing steps:
1. Libation scan
2. Discovery
3. Staging (hardlink + rename)
4. Metadata (Audnex + MediaInfo)
5. Torrent creation (mkbrr)
6. Upload (qBittorrent)
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from mamfast.config import get_settings
from mamfast.hardlinker import stage_release
from mamfast.libation import run_liberate, run_scan
from mamfast.metadata import fetch_all_metadata
from mamfast.mkbrr import create_torrent
from mamfast.models import AudiobookRelease, ProcessingResult, ReleaseStatus
from mamfast.qbittorrent import upload_torrent
from mamfast.utils.retry import NETWORK_EXCEPTIONS, retry_with_backoff
from mamfast.utils.state import is_processed, mark_failed, mark_processed

logger = logging.getLogger(__name__)


# =============================================================================
# Progress Callback Types
# =============================================================================


class ProgressStage(Enum):
    """Pipeline stages for progress reporting."""

    SCAN = "scan"
    DISCOVERY = "discovery"
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
    output_dir: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Fetch metadata with retry logic for network failures."""
    return fetch_all_metadata(asin=asin, m4b_path=m4b_path, output_dir=output_dir)


@retry_with_backoff(
    max_attempts=3,
    base_delay=1.0,
    max_delay=15.0,
    exceptions=NETWORK_EXCEPTIONS,
)
def _upload_torrent_with_retry(
    torrent_path: Path,
    save_path: Path,
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

    logger.info(f"Processing: {release.display_name}")

    try:
        # ---------------------------------------------------------------------
        # 1. Stage
        # ---------------------------------------------------------------------
        notify(ProgressStage.STAGING, "Creating hardlinks...")
        logger.debug("Step 1: Staging release")
        staging_dir = stage_release(release)
        release.status = ReleaseStatus.STAGED

        # ---------------------------------------------------------------------
        # 2. Metadata (optional)
        # ---------------------------------------------------------------------
        if not skip_metadata:
            notify(ProgressStage.METADATA, "Fetching Audnex + MediaInfo...")
            logger.debug("Step 2: Fetching metadata")
            audnex_data, mediainfo_data = _fetch_metadata_with_retry(
                asin=release.asin,
                m4b_path=release.main_m4b,
                output_dir=staging_dir,
            )
            release.audnex_metadata = audnex_data
            release.mediainfo_data = mediainfo_data
            release.status = ReleaseStatus.METADATA_FETCHED

        # ---------------------------------------------------------------------
        # 3. Create torrent
        # ---------------------------------------------------------------------
        notify(ProgressStage.TORRENT, "Creating torrent file...")
        logger.debug("Step 3: Creating torrent")
        mkbrr_result = create_torrent(
            content_path=staging_dir,
            preset=preset or settings.mkbrr.preset,
        )

        if not mkbrr_result.success:
            raise RuntimeError(
                f"Torrent creation failed for '{staging_dir.name}'\n"
                f"Error: {mkbrr_result.error}\n"
                f"\nTroubleshooting:\n"
                f"  1. Verify mkbrr Docker image is available: {settings.mkbrr.image}\n"
                f"     Run: docker pull {settings.mkbrr.image}\n"
                f"  2. Check preset '{settings.mkbrr.preset}' exists in {settings.mkbrr.host_config_dir}/presets.yaml\n"
                f"  3. Verify path mappings in config.yaml:\n"
                f"     - host_data_root: {settings.mkbrr.host_data_root}\n"
                f"     - container_data_root: {settings.mkbrr.container_data_root}\n"
                f"  4. Check Docker logs: docker logs $(docker ps -lq)"
            )

        release.torrent_path = mkbrr_result.torrent_path
        release.status = ReleaseStatus.TORRENT_CREATED

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

        success = _upload_torrent_with_retry(
            torrent_path=release.torrent_path,
            save_path=staging_dir,
        )

        if not success:
            raise RuntimeError(
                f"Failed to upload torrent to qBittorrent\n"
                f"Torrent: {release.torrent_path}\n"
                f"Save path: {staging_dir}\n"
                f"\nTroubleshooting:\n"
                f"  1. Verify qBittorrent is running and accessible at {settings.qbittorrent.host}\n"
                f"  2. Check credentials in config/.env:\n"
                f"     - QB_USERNAME: {settings.qbittorrent.username}\n"
                f"     - QB_PASSWORD: (check it's correct)\n"
                f"  3. Verify WebUI is enabled in qBittorrent preferences\n"
                f"  4. Check qBittorrent logs for errors\n"
                f"  5. Test connection: curl -u username:password {settings.qbittorrent.host}/api/v2/app/version"
            )

        release.status = ReleaseStatus.UPLOADED

        # ---------------------------------------------------------------------
        # 5. Mark as complete
        # ---------------------------------------------------------------------
        release.status = ReleaseStatus.COMPLETE
        mark_processed(release)

        duration = time.time() - start_time
        notify(ProgressStage.COMPLETE, f"Completed in {duration:.1f}s")
        logger.info(f"✅ Completed: {release.display_name} ({duration:.1f}s)")

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
        logger.error(f"❌ Failed: {release.display_name} - {error_msg}")

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
        logger.info("Step 1: Running Libation scan...")
        if not dry_run:
            scan_result = run_scan()
            if not scan_result.success:
                logger.warning(f"Libation scan returned non-zero: {scan_result.returncode}")

            # Run liberate to download new books
            logger.info("Step 1b: Running Libation liberate (downloading new books)...")
            liberate_result = run_liberate()
            if not liberate_result.success:
                logger.warning(f"Libation liberate returned non-zero: {liberate_result.returncode}")
        else:
            logger.info("  [DRY RUN] Would run Libation scan + liberate")

    # -------------------------------------------------------------------------
    # 2. Discover new releases
    # -------------------------------------------------------------------------
    notify(ProgressStage.DISCOVERY, "Discovering new releases...")
    logger.info("Step 2: Discovering new releases...")

    # TODO: Replace with actual discovery once implemented
    # For now, return empty results
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
        logger.info("No new releases found")
        return PipelineResult(
            total=0,
            successful=0,
            failed=0,
            skipped=0,
            results=[],
            duration_seconds=time.time() - start_time,
        )

    logger.info(f"Found {len(releases)} new release(s)")

    # -------------------------------------------------------------------------
    # 3. Process each release
    # -------------------------------------------------------------------------
    results = []
    skipped = 0
    settings = get_settings()

    # Create progress bar for processing releases
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("({task.completed}/{task.total})"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        transient=False,
    ) as progress:
        task = progress.add_task(
            "[cyan]Processing releases...", total=len(releases), visible=not dry_run
        )

        for i, release in enumerate(releases, 1):
            # Update progress description
            progress.update(
                task, description=f"[cyan]{release.display_name[:50]}...", visible=not dry_run
            )

            logger.info(f"[{i}/{len(releases)}] {release.display_name}")

            # Check if already processed
            identifier = release.asin or str(release.source_dir)
            if identifier and is_processed(identifier):
                logger.info("  Skipping (already processed)")
                skipped += 1
                progress.advance(task)
                continue

            if dry_run:
                # Show detailed dry-run info for each step
                logger.info("  [DRY RUN] Steps that would be performed:")

                # Step 1: Stage
                if release.source_dir:
                    staging_name = release.source_dir.name
                    seed_root = settings.paths.seed_root
                    logger.info(f"    1. STAGE: Hardlink to {seed_root / staging_name}")

                # Step 2: Metadata
                if not skip_metadata:
                    if release.asin:
                        logger.info(f"    2. METADATA: Fetch Audnex for ASIN {release.asin}")
                    if release.main_m4b:
                        logger.info(f"    2. METADATA: Run MediaInfo on {release.main_m4b.name}")
                    logger.info(
                        f"    2. METADATA: Generate MAM JSON to {settings.paths.torrent_output}"
                    )
                else:
                    logger.info("    2. METADATA: [SKIPPED]")

                # Step 3: Torrent
                logger.info(f"    3. TORRENT: Create with preset '{settings.mkbrr.preset}'")
                logger.info(f"    3. TORRENT: Output to {settings.paths.torrent_output}")

                # Step 4: Upload
                logger.info(f"    4. UPLOAD: Add to qBittorrent at {settings.qbittorrent.host}")
                logger.info(f"    4. UPLOAD: Category '{settings.qbittorrent.category}'")

                # Step 5: Mark processed
                logger.info(f"    5. STATE: Mark {identifier} as processed")
                progress.advance(task)
                continue

            result = process_single_release(
                release,
                skip_metadata=skip_metadata,
                progress_callback=progress_callback,
                release_index=i,
                release_total=len(releases),
            )
            results.append(result)
            progress.advance(task)

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

    logger.info("=" * 50)
    logger.info(f"Pipeline complete in {duration:.1f}s")
    logger.info(f"  Total: {len(releases)}")
    logger.info(f"  Successful: {successful}")
    logger.info(f"  Failed: {failed}")
    logger.info(f"  Skipped: {skipped}")

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

    Returns list of staging directories created.
    """
    logger.info("Discovering and staging releases...")

    # TODO: Implement when discovery is ready
    raise NotImplementedError("Waiting for discovery implementation")


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
        # Determine save path from torrent name
        # Convention: torrent name matches staging dir name
        staging_name = torrent_path.stem
        save_path = settings.paths.library_root / staging_name

        if not save_path.exists():
            # Try seed root as fallback
            save_path = settings.paths.seed_root / staging_name

        logger.info(f"Uploading: {torrent_path.name}")

        success = upload_torrent(
            torrent_path=torrent_path,
            save_path=save_path,
        )

        if success:
            uploaded += 1

    logger.info(f"Uploaded {uploaded}/{len(torrent_paths)} torrent(s)")
    return uploaded
