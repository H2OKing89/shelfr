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
from dataclasses import dataclass
from pathlib import Path

from mamfast.config import get_settings
from mamfast.hardlinker import stage_release
from mamfast.libation import run_liberate, run_scan
from mamfast.metadata import fetch_all_metadata
from mamfast.mkbrr import create_torrent
from mamfast.models import AudiobookRelease, ProcessingResult, ReleaseStatus
from mamfast.qbittorrent import upload_torrent
from mamfast.utils.state import is_processed, mark_failed, mark_processed

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Result of running the full pipeline."""

    total: int
    successful: int
    failed: int
    skipped: int
    results: list[ProcessingResult]
    duration_seconds: float


def process_single_release(
    release: AudiobookRelease,
    skip_metadata: bool = False,
    preset: str | None = None,
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

    Returns:
        ProcessingResult with success/failure info
    """
    settings = get_settings()
    start_time = time.time()

    logger.info(f"Processing: {release.display_name}")

    try:
        # ---------------------------------------------------------------------
        # 1. Stage
        # ---------------------------------------------------------------------
        logger.debug("Step 1: Staging release")
        staging_dir = stage_release(release)
        release.status = ReleaseStatus.STAGED

        # ---------------------------------------------------------------------
        # 2. Metadata (optional)
        # ---------------------------------------------------------------------
        if not skip_metadata:
            logger.debug("Step 2: Fetching metadata")
            audnex_data, mediainfo_data = fetch_all_metadata(
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
        logger.debug("Step 3: Creating torrent")
        mkbrr_result = create_torrent(
            content_path=staging_dir,
            preset=preset or settings.mkbrr.preset,
        )

        if not mkbrr_result.success:
            raise RuntimeError(f"mkbrr failed: {mkbrr_result.error}")

        release.torrent_path = mkbrr_result.torrent_path
        release.status = ReleaseStatus.TORRENT_CREATED

        # ---------------------------------------------------------------------
        # 4. Upload to qBittorrent
        # ---------------------------------------------------------------------
        logger.debug("Step 4: Uploading to qBittorrent")

        if release.torrent_path is None:
            raise RuntimeError("No torrent path after mkbrr")

        success = upload_torrent(
            torrent_path=release.torrent_path,
            save_path=staging_dir,
        )

        if not success:
            raise RuntimeError("Failed to upload torrent to qBittorrent")

        release.status = ReleaseStatus.UPLOADED

        # ---------------------------------------------------------------------
        # 5. Mark as complete
        # ---------------------------------------------------------------------
        release.status = ReleaseStatus.COMPLETE
        mark_processed(release)

        duration = time.time() - start_time
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


def full_run(
    skip_scan: bool = False,
    skip_metadata: bool = False,
    dry_run: bool = False,
) -> PipelineResult:
    """
    Run the complete pipeline from Libation scan to qBittorrent upload.

    Args:
        skip_scan: Skip Libation scan step
        skip_metadata: Skip metadata fetching
        dry_run: Show what would happen without making changes

    Returns:
        PipelineResult with statistics
    """
    start_time = time.time()

    # -------------------------------------------------------------------------
    # 1. Libation scan + liberate (optional)
    # -------------------------------------------------------------------------
    if not skip_scan:
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
    logger.info("Step 2: Discovering new releases...")

    # TODO: Replace with actual discovery once implemented
    # For now, return empty results
    from mamfast.discovery import get_new_releases

    try:
        settings = get_settings()
        releases = get_new_releases(
            settings.paths.libation_library_root,
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

    for i, release in enumerate(releases, 1):
        logger.info(f"[{i}/{len(releases)}] {release.display_name}")

        # Check if already processed
        identifier = release.asin or str(release.source_dir)
        if identifier and is_processed(identifier):
            logger.info("  Skipping (already processed)")
            skipped += 1
            continue

        if dry_run:
            logger.info("  [DRY RUN] Would process release")
            continue

        result = process_single_release(
            release,
            skip_metadata=skip_metadata,
        )
        results.append(result)

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------
    duration = time.time() - start_time
    successful = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success)

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
        # Find all directories in staging root
        staging_root = settings.paths.staging_root
        if not staging_root.exists():
            logger.warning(f"Staging root does not exist: {staging_root}")
            return []

        staging_dirs = [d for d in staging_root.iterdir() if d.is_dir()]

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
        save_path = settings.paths.staging_root / staging_name

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
