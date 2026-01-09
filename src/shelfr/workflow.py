"""
Workflow orchestration for the shelfr pipeline.

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

from shelfr.config import get_settings
from shelfr.console import (
    console,
    format_mediainfo_stats,
    print_dry_run,
    print_error,
    print_info,
    print_step,
    print_success,
    print_warning,
    print_workflow_summary,
    render_libation_status,
    truncate_path,
)
from shelfr.exceptions import (
    DiscoveryValidationError,
    PreUploadValidationError,
    StagingError,
    TorrentError,
    UploadError,
)
from shelfr.hardlinker import compute_staging_path, preview_staging, stage_release
from shelfr.libation import (
    get_libation_status,
    run_liberate,
    run_liberate_with_progress,
    run_scan,
)
from shelfr.metadata import fetch_metadata, generate_mam_json_for_release
from shelfr.metadata.providers import HardcoverProvider
from shelfr.mkbrr import create_torrent
from shelfr.models import AudiobookRelease, ProcessingResult, ReleaseStatus
from shelfr.qbittorrent import upload_torrent
from shelfr.sanitize import preview_sanitization, sanitize_release
from shelfr.utils.retry import NETWORK_EXCEPTIONS, retry_with_backoff
from shelfr.utils.state import (
    checkpoint_stage,
    get_processed_identifiers,
    is_processed,
    mark_failed,
    mark_processed,
    should_skip_stage,
)
from shelfr.validation import (
    ChapterIntegrityChecker,
    DiscoveryValidation,
    MetadataValidation,
    PreflightValidation,
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
    SANITIZE = "sanitize"
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
    *,
    use_cache: bool = True,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None, str | None]:
    """Fetch metadata with retry logic for network failures.

    Args:
        asin: Audible ASIN for Audnex lookup (None to skip Audnex)
        m4b_path: Path to m4b file for MediaInfo extraction (None to skip)
        use_cache: Use provider-backed caching with rate limiting (default: True).
            When True, uses AudnexProvider which caches responses for 30 days.
            Set to False to force fresh API calls (e.g., --no-cache CLI flag).

    Returns:
        Tuple of (audnex_data, mediainfo_data, audnex_chapters, region).
        Each element may be None if lookup failed or was skipped.
    """
    return fetch_metadata(asin=asin, m4b_path=m4b_path, use_cache=use_cache)


@retry_with_backoff(
    max_attempts=3,
    base_delay=1.0,
    max_delay=15.0,
    exceptions=NETWORK_EXCEPTIONS,
)
def _upload_torrent_with_retry(
    torrent_path: Path,
    save_path: Path | None = None,
) -> tuple[bool, str | None]:
    """Upload torrent with retry logic for network failures.

    Returns:
        Tuple of (success: bool, infohash: str | None)
    """
    return upload_torrent(torrent_path=torrent_path, save_path=save_path)


@dataclass
class HardcoverResult:
    """Result from Hardcover API fetch."""

    content_flags: list[str] | None = None
    genres: list[str] | None = None
    moods: list[str] | None = None


async def _fetch_hardcover_data_async(
    asin: str,
    title: str,
    author: str,
) -> HardcoverResult:
    """Fetch content warnings, genres, and moods from Hardcover asynchronously.

    Args:
        asin: ASIN for cache keying
        title: Book title for search
        author: Author name for search

    Returns:
        HardcoverResult with content_flags, genres, and moods
    """
    from shelfr.metadata.providers.types import LookupContext

    settings = get_settings()
    if not settings.hardcover.enabled:
        logger.debug("Hardcover disabled in config, skipping")
        return HardcoverResult()

    # Wire config values to provider
    hc_config = settings.hardcover
    provider = HardcoverProvider(
        cache_ttl_seconds=hc_config.cache_ttl_days * 24 * 3600,
        match_threshold=hc_config.match_threshold,
    )
    try:
        await provider.startup()
        ctx = LookupContext(
            ids={"asin": asin},
            existing_abs_json={"title": title, "authors": [{"name": author}] if author else []},
        )
        result = await provider.fetch(ctx, id_type="asin")
        if result.success and result.fields:
            # Extract genres as list of strings
            genres_raw = result.fields.get("genres", [])
            genres: list[str] = []
            for g in genres_raw:
                name = g.get("name") if isinstance(g, dict) else g
                if name and isinstance(name, str):
                    genres.append(name)

            # Get moods safely - it's not a standard MetadataFields key
            # Use raw_data which stores the complete Hardcover response
            moods: list[str] | None = None
            if result.raw_data:
                raw_moods = result.raw_data.get("moods")
                if isinstance(raw_moods, list):
                    moods = [m for m in raw_moods if isinstance(m, str)]
                    moods = moods if moods else None

            return HardcoverResult(
                content_flags=result.fields.get("content_flags"),
                genres=genres if genres else None,
                moods=moods,
            )
        return HardcoverResult()
    except Exception as e:
        logger.warning("Hardcover fetch failed: %s", e)
        return HardcoverResult()
    finally:
        await provider.shutdown()


def _fetch_hardcover_data(asin: str, title: str, author: str) -> HardcoverResult:
    """Sync wrapper for Hardcover data fetch.

    Uses asyncio.run() to execute the async provider call from sync context.
    """
    import asyncio

    try:
        return asyncio.run(_fetch_hardcover_data_async(asin, title, author))
    except Exception as e:
        logger.warning("Hardcover fetch error: %s", e)
        return HardcoverResult()


# Legacy wrapper for backwards compatibility
def _fetch_content_warnings(asin: str, title: str, author: str) -> list[str] | None:
    """Fetch content warnings from Hardcover (legacy wrapper)."""
    result = _fetch_hardcover_data(asin, title, author)
    return result.content_flags


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
    *,
    use_cache: bool = True,
    verbose: bool = False,
) -> ProcessingResult:
    """
    Process a single release through the full pipeline.

    Steps:
    1. Sanitize (strip unwanted metadata tags)
    2. Stage (hardlink + rename)
    3. Fetch metadata (optional)
    4. Create torrent
    5. Upload to qBittorrent
    6. Mark as processed

    Args:
        release: AudiobookRelease to process
        skip_metadata: Skip Audnex/MediaInfo fetching
        preset: Override mkbrr preset
        progress_callback: Optional callback for progress updates
        release_index: Current release number (1-based) for progress
        release_total: Total releases being processed
        use_cache: Use metadata caching (default: True)

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

        # Load processed identifiers for duplicate detection
        processed_ids = get_processed_identifiers()
        discovery_validator = DiscoveryValidation(processed_identifiers=processed_ids)
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
            raise DiscoveryValidationError(
                "Discovery validation failed:\n  - " + "\n  - ".join(error_msgs),
                errors=error_msgs,
            )

        if discovery_result.warning_count > 0:
            print_warning(f"Validation passed with {discovery_result.warning_count} warning(s)")
        else:
            print_success("Validation passed")

        # ---------------------------------------------------------------------
        # 0b. Sanitize (strip unwanted metadata tags)
        # ---------------------------------------------------------------------
        if should_skip_stage(release, "sanitized"):
            logger.info("Skipping sanitization (already completed)")
        else:
            notify(ProgressStage.SANITIZE, "Checking for unwanted metadata tags...")
            logger.debug("Step 0b: Sanitize release")
            sanitize_result = sanitize_release(release, verbose=verbose)

            if sanitize_result.skipped_reason:
                # Show warning if sanitize is enabled but ffmpeg disabled (config issue)
                if "FFmpeg disabled" in sanitize_result.skipped_reason:
                    print_warning(f"Sanitization skipped: {sanitize_result.skipped_reason}")
                    print_info("  → Add 'ffmpeg: enabled: true' to config.yaml to enable")
                else:
                    logger.debug("Sanitization skipped: %s", sanitize_result.skipped_reason)
            elif sanitize_result.files_modified > 0:
                print_success(
                    f"Sanitized {sanitize_result.files_modified} file(s) "
                    f"(stripped unwanted tags)"
                )
                checkpoint_stage(release, "sanitized")
            elif sanitize_result.errors:
                # Log errors but don't fail - continue with workflow
                for error in sanitize_result.errors:
                    print_warning(f"Sanitize warning: {error}")
            else:
                logger.debug("No unwanted tags found - nothing to sanitize")
                checkpoint_stage(release, "sanitized")

        # ---------------------------------------------------------------------
        # 1. Stage
        # ---------------------------------------------------------------------
        if should_skip_stage(release, "staged"):
            logger.info("Skipping staging (already completed)")
            # Load staging_dir from checkpoint - it must exist for resume to work
            if not release.staging_dir:
                raise StagingError(
                    f"Cannot resume: staging_dir not found for {release.display_name}",
                    details={"asin": release.asin, "source_dir": str(release.source_dir)},
                )
            staging_dir = release.staging_dir
            if not staging_dir.exists():
                raise StagingError(
                    f"Cannot resume: staging directory missing: {staging_dir}",
                    details={"staging_dir": str(staging_dir)},
                )
            release.status = ReleaseStatus.STAGED
        else:
            # Determine packaging mode from config
            audio_only = settings.workflow.upload.packaging == "audio_only"
            mode_display = "audio_only" if audio_only else "folder"
            notify(ProgressStage.STAGING, f"Creating hardlinks ({mode_display})...")
            logger.debug("Step 1: Staging release (packaging=%s)", mode_display)
            staging_dir = stage_release(release, audio_only=audio_only)
            # Show truncated path - full path available in logs via --verbose
            display_path = truncate_path(str(staging_dir), max_length=60)
            print_success(f"Staged → {display_path}")
            release.status = ReleaseStatus.STAGED
            checkpoint_stage(release, "staged")

        # ---------------------------------------------------------------------
        # 2. Metadata (optional)
        # ---------------------------------------------------------------------
        if not skip_metadata:
            if should_skip_stage(release, "metadata"):
                logger.info("Skipping metadata (already completed)")
                release.status = ReleaseStatus.METADATA_FETCHED
            else:
                notify(ProgressStage.METADATA, "Fetching Audnex + MediaInfo...")
                logger.debug("Step 2: Fetching metadata")
                audnex_data, mediainfo_data, audnex_chapters, _ = _fetch_metadata_with_retry(
                    asin=release.asin,
                    m4b_path=release.main_m4b,
                    use_cache=use_cache,
                )
                release.audnex_metadata = audnex_data
                release.mediainfo_data = mediainfo_data
                release.audnex_chapters = audnex_chapters
                if audnex_data:
                    print_success(f"Audnex metadata for {release.asin}")

                    # Check if Audnex title differs significantly from Libation title
                    from shelfr.utils.fuzzy import similarity_ratio

                    audnex_title = audnex_data.get("title", "")
                    libation_title = release.title or ""
                    if audnex_title and libation_title:
                        title_similarity = similarity_ratio(audnex_title, libation_title)
                        if title_similarity < 70:
                            print_warning(
                                f"Title mismatch: Libation='{libation_title}' vs "
                                f"Audnex='{audnex_title}' ({title_similarity:.0f}% similar)"
                            )

                if audnex_chapters:
                    chapter_count = len(audnex_chapters.get("chapters", []))
                    print_success(f"Audnex chapters: {chapter_count} chapters")
                if mediainfo_data:
                    stats = format_mediainfo_stats(mediainfo_data)
                    if stats:
                        print_success(f"MediaInfo: {stats}")
                    else:
                        print_success("MediaInfo extracted")
                release.status = ReleaseStatus.METADATA_FETCHED
                checkpoint_stage(release, "metadata")

            # -----------------------------------------------------------------
            # 2a. Hardcover Data (Content Warnings, Genres, Moods)
            # -----------------------------------------------------------------
            if settings.workflow.upload.content_warnings.enabled:
                logger.debug("Step 2a: Fetching Hardcover data")
                title = release.title or ""
                author = release.author or ""
                if release.asin and title:
                    if verbose:
                        print_info(f"Fetching Hardcover data for '{title}' by '{author}'")
                    hardcover_result = _fetch_hardcover_data(release.asin, title, author)

                    # Store content flags
                    if hardcover_result.content_flags:
                        release.content_flags = hardcover_result.content_flags
                        flags_str = ", ".join(hardcover_result.content_flags)
                        print_success(f"Content warnings: {flags_str}")

                    # Store genres and moods for category resolution
                    if hardcover_result.genres:
                        release.hardcover_genres = hardcover_result.genres
                        if verbose:
                            print_info(
                                f"Hardcover genres: {', '.join(hardcover_result.genres[:5])}"
                            )
                    if hardcover_result.moods:
                        release.hardcover_moods = hardcover_result.moods
                        if verbose:
                            print_info(f"Hardcover moods: {', '.join(hardcover_result.moods[:5])}")

                    if not hardcover_result.content_flags and verbose:
                        print_info("No content warnings found on Hardcover")
                    elif not hardcover_result.content_flags:
                        logger.debug("No content warnings found for '%s'", title)
                else:
                    if verbose:
                        print_info("Skipping Hardcover: missing ASIN or title")
                    else:
                        logger.debug("Skipping Hardcover: missing ASIN or title")

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
        # Create per-release output subfolder for torrent + JSON
        release_output_dir = settings.paths.torrent_output / staging_dir.name
        release_output_dir.mkdir(parents=True, exist_ok=True)

        if should_skip_stage(release, "torrent"):
            logger.info("Skipping torrent creation (already completed)")
            # Verify torrent exists when resuming
            if not release.torrent_path or not release.torrent_path.exists():
                raise TorrentError(
                    f"Cannot resume: torrent file missing for {release.display_name}",
                    release_asin=release.asin,
                    release_title=release.display_name,
                )
            release.status = ReleaseStatus.TORRENT_CREATED
        else:
            notify(ProgressStage.TORRENT, "Creating torrent file...")
            logger.debug("Step 3: Creating torrent")

            # Determine torrent target based on packaging mode
            audio_only = settings.workflow.upload.packaging == "audio_only"
            if audio_only and release.main_m4b:
                # audio_only mode: torrent targets the file directly
                torrent_target = release.main_m4b
                logger.debug("Torrent target (audio_only): %s", torrent_target)
            else:
                # folder mode: torrent targets the directory
                torrent_target = staging_dir
                logger.debug("Torrent target (folder): %s", torrent_target)

            mkbrr_result = create_torrent(
                content_path=torrent_target,
                output_dir=release_output_dir,
                preset=preset or settings.mkbrr.preset,
            )

            if not mkbrr_result.success:
                raise TorrentError(
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
                    f"  4. Check Docker logs: docker logs $(docker ps -lq)",
                    release_asin=release.asin,
                    release_title=release.display_name,
                )

            release.torrent_path = mkbrr_result.torrent_path
            release.status = ReleaseStatus.TORRENT_CREATED
            if mkbrr_result.torrent_path:
                print_success(f"Torrent: {mkbrr_result.torrent_path.name}")

                # Extract and checkpoint infohash for idempotent upload checks
                from shelfr.utils.torrent import extract_infohash

                infohash = extract_infohash(mkbrr_result.torrent_path)
                checkpoint_stage(release, "torrent", infohash=infohash)

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
                    raise PreUploadValidationError(
                        f"Pre-upload validation failed: {check.message}",
                        errors=[check.message],
                    )
                elif check.severity == "warning":
                    print_warning(f"Pre-upload: {check.message}")

        # ---------------------------------------------------------------------
        # 4. Upload to qBittorrent
        # ---------------------------------------------------------------------
        notify(ProgressStage.UPLOAD, "Uploading to qBittorrent...")
        logger.debug("Step 4: Uploading to qBittorrent")

        if release.torrent_path is None:
            raise TorrentError(
                "Internal error: No torrent path after successful mkbrr creation\n"
                f"This is a bug. Please report with:\n"
                f"  - Release: {release.display_name}",
                release_asin=release.asin,
                release_title=release.display_name,
            )

        # Use configured save_path (container path)
        # Only needed when auto_tmm is disabled
        if settings.qbittorrent.auto_tmm:
            # Auto TMM: qBittorrent manages save path via category
            qb_save_path = None
        elif settings.qbittorrent.save_path:
            # Manual: build save path from config
            audio_only = settings.workflow.upload.packaging == "audio_only"
            if audio_only:
                # audio_only: torrent is for file inside staging_dir
                # save_path = container path to staging_dir (where file lives)
                qb_save_path = Path(settings.qbittorrent.save_path) / staging_dir.name
            else:
                # folder mode: torrent is for staging_dir folder itself
                # save_path = container path to parent (seed_root)
                qb_save_path = Path(settings.qbittorrent.save_path)
        else:
            # No save_path configured - let qBittorrent use its default
            qb_save_path = None

        success, infohash = _upload_torrent_with_retry(
            torrent_path=release.torrent_path,
            save_path=qb_save_path,
        )

        if not success:
            qb_host = settings.qbittorrent.host
            raise UploadError(
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
                f"{qb_host}/api/v2/app/version",
                release_asin=release.asin,
                release_title=release.display_name,
                infohash=infohash,
            )

        release.status = ReleaseStatus.UPLOADED
        # Format the qBittorrent success message with explicit labels
        qb_category = settings.qbittorrent.category or "audiobooks"
        hash_short = infohash[:8] + "…" + infohash[-4:] if infohash else "?"
        print_success(f"Uploaded to qBittorrent (category={qb_category}, hash={hash_short})")

        # ---------------------------------------------------------------------
        # 5. Mark as complete
        # ---------------------------------------------------------------------
        release.status = ReleaseStatus.COMPLETE
        mark_processed(release, infohash=infohash)

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
    verbose: bool = False,
    progress_callback: ProgressCallback | None = None,
    *,
    use_cache: bool = True,
) -> PipelineResult:
    """
    Run the complete pipeline from Libation scan to qBittorrent upload.

    Args:
        skip_scan: Skip Libation scan step
        skip_metadata: Skip metadata fetching
        dry_run: Show what would happen without making changes
        verbose: Enable verbose mode (pass through Libation progress if on TTY)
        progress_callback: Optional callback for progress updates
        use_cache: Use metadata caching (default: True)

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
    # 0. Pre-flight validation (disk space, permissions)
    # -------------------------------------------------------------------------
    settings = get_settings()
    preflight = PreflightValidation(settings)
    preflight_result = preflight.validate()

    # Log any preflight issues
    for check in preflight_result.checks:
        if not check.passed:
            if check.severity == "error":
                print_error(f"Preflight: {check.message}")
            elif check.severity == "warning":
                print_warning(f"Preflight: {check.message}")

    if not preflight_result.passed:
        print_error("Preflight validation failed. Fix issues above before continuing.")
        return PipelineResult(
            total=0,
            successful=0,
            failed=0,
            skipped=0,
            results=[],
            duration_seconds=time.time() - start_time,
        )

    # -------------------------------------------------------------------------
    # 1. Libation scan + conditional liberate
    # -------------------------------------------------------------------------
    # Libation has a two-stage model:
    #   - scan: Index NEW books from Audible → BookStatus=NotLiberated
    #   - liberate: Download ALL books with BookStatus=NotLiberated
    #
    # Key insight: "New: 0" from scan does NOT mean nothing to download.
    # There may be NotLiberated books from previous scans waiting.
    # We check status AFTER scan to decide whether to run liberate.
    # -------------------------------------------------------------------------
    if not skip_scan:
        notify(ProgressStage.SCAN, "Running Libation scan...")
        print_step(1, 4, "Libation Scan")
        if not dry_run:
            # Step 1a: Run scan to index new books from Audible
            scan_result = run_scan()
            if not scan_result.success:
                print_warning(f"Libation scan returned non-zero: {scan_result.returncode}")
            else:
                print_success("Scan complete (indexed new books from Audible)")

            # Step 1b: Check how many books are pending download
            try:
                status = get_libation_status()
                render_libation_status(status)

                # Step 1c: Only run liberate if there are pending books
                if status.has_pending:
                    # Use progress-aware liberate function
                    # - Normal mode: Rich spinner, logs to file
                    # - Verbose + TTY: Pass through Libation's native progress bar
                    liberate_result = run_liberate_with_progress(
                        pending_count=status.not_liberated,
                        console=console,
                        verbose=verbose,
                    )
                    if not liberate_result.success:
                        print_warning(
                            f"Libation liberate returned non-zero: {liberate_result.returncode}"
                        )
                        if liberate_result.error_message:
                            logger.debug(liberate_result.error_message)
                    else:
                        # Show success with log path for debugging
                        if liberate_result.log_path:
                            print_success(
                                f"Liberate complete (log: {liberate_result.log_path.name})"
                            )
                        else:
                            print_success("Liberate complete")

                        # Check if any individual books failed (even though command succeeded)
                        if liberate_result.has_book_errors:
                            print_warning(
                                f"Some books failed to download "
                                f"({liberate_result.skipped_count} skipped)"
                            )
                            # Show the error message to user
                            if liberate_result.error_message:
                                # Clean up and truncate error message for display
                                error_lines = liberate_result.error_message.splitlines()
                                for line in error_lines[:2]:  # Show first 2 lines
                                    print_warning(f"  → {line.strip()}")
                            if liberate_result.log_path:
                                print_info(f"  Full details in: {liberate_result.log_path.name}")

                        # Optional: Show updated status after liberate (only if something changed)
                        try:
                            new_status = get_libation_status()
                            if new_status.liberated > status.liberated:
                                downloaded = new_status.liberated - status.liberated
                                print_success(f"Downloaded {downloaded} new book(s)")
                                render_libation_status(
                                    new_status,
                                    title="Libation Status (Post-Liberate)",
                                )
                        except Exception:
                            pass  # Non-critical, don't fail if post-check fails
                else:
                    print_info(
                        "No audiobooks staged for download (NotLiberated=0). Skipping liberate."
                    )

            except Exception as e:
                # Status check failed - fall back to always running liberate
                print_warning(f"Could not check Libation status: {e}")
                print_info("Running liberate anyway (fallback)...")
                fallback_result = run_liberate()
                if not fallback_result.success:
                    print_warning(
                        f"Libation liberate returned non-zero: {fallback_result.returncode}"
                    )
        else:
            print_dry_run("Would run Libation scan")
            print_dry_run("Would check library status (NotLiberated count)")
            print_dry_run("Would run liberate if NotLiberated > 0")

    # -------------------------------------------------------------------------
    # 2. Discover new releases
    # -------------------------------------------------------------------------
    notify(ProgressStage.DISCOVERY, "Discovering new releases...")
    step_num = 1 if skip_scan else 2
    print_step(step_num, 4 if not skip_scan else 3, "Discovering Releases")

    from shelfr.discovery import get_new_releases

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

    console.print(f"Found [highlight]{len(releases)}[/] new release(s)")

    # -------------------------------------------------------------------------
    # 3. Process each release
    # -------------------------------------------------------------------------
    results = []
    skipped = 0

    # Process each release
    for i, release in enumerate(releases, 1):
        console.print()  # Blank line before each release header
        console.print(f"[bold cyan]── [{i}/{len(releases)}] {release.display_name} ──[/]")

        # Check if already processed
        identifier = release.asin or str(release.source_dir)
        if identifier and is_processed(identifier):
            print_info("Skipping (already processed)")
            skipped += 1
            continue

        # Run validation (even in dry-run mode to show warnings)
        processed_ids = get_processed_identifiers()
        discovery_validator = DiscoveryValidation(processed_identifiers=processed_ids)
        discovery_result = discovery_validator.validate(release)

        # Log validation results
        for check in discovery_result.checks:
            if not check.passed and check.severity == "warning":
                print_warning(f"Validation: {check.message}")

        if not discovery_result.passed:
            failed_checks = [
                c for c in discovery_result.checks if not c.passed and c.severity == "error"
            ]
            error_msgs = [c.message for c in failed_checks]
            print_error("Validation failed: " + ", ".join(error_msgs))
            skipped += 1
            continue

        if discovery_result.warning_count > 0:
            print_warning(f"Validation passed with {discovery_result.warning_count} warning(s)")

        if dry_run:
            # Show detailed dry-run info for each step
            print_dry_run("Steps that would be performed:")

            # Determine packaging mode for path calculation
            audio_only = settings.workflow.upload.packaging == "audio_only"

            # Step 0b: Sanitize - check for unwanted metadata tags
            tags_to_strip = preview_sanitization(release)
            if tags_to_strip:
                for file_path, tags in tags_to_strip.items():
                    print_dry_run(f"SANITIZE → Strip {tags} from {file_path.name}")
            else:
                print_dry_run("SANITIZE → No unwanted tags found")

            # Step 1: Stage - compute actual staging path (same logic as real run)
            if release.source_dir:
                seed_root = settings.paths.seed_root
                try:
                    mam_path = compute_staging_path(release, audio_only=audio_only)
                    staging_dir = seed_root / mam_path.folder
                    print_dry_run(f"STAGE → {staging_dir}")
                    if mam_path.truncated:
                        print_dry_run(f"  (truncated: dropped {mam_path.dropped_components})")

                    # Show file renames
                    try:
                        renames = preview_staging(release, audio_only=audio_only)
                        for src_name, dst_name in renames:
                            if src_name != dst_name:
                                print_dry_run(f"  RENAME: {src_name} → {dst_name}")
                            else:
                                print_dry_run(f"  HARDLINK: {src_name}")
                    except ValueError:
                        pass  # Already handled above
                except ValueError as e:
                    # Missing ASIN or source_dir
                    print_dry_run(f"STAGE → Error: {e}")

            # Step 2: Metadata
            if not skip_metadata:
                if release.asin:
                    print_dry_run(f"METADATA → Fetch Audnex for {release.asin}")
                if release.main_m4b:
                    print_dry_run(f"METADATA → MediaInfo on {release.main_m4b.name}")
                # Step 2a: Hardcover data (content warnings, genres, moods)
                # Only check content_warnings.enabled here - the internal fetch
                # handles hardcover.enabled
                if settings.workflow.upload.content_warnings.enabled:
                    title = release.title or "unknown"
                    print_dry_run(
                        f"HARDCOVER → Fetch content warnings, genres, moods for '{title}'"
                    )
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
            use_cache=use_cache,
            verbose=verbose,
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

    # Print workflow summary table (includes duration)
    print_workflow_summary(
        {
            "discovered": len(releases),
            "staged": successful,
            "metadata": successful if not skip_metadata else 0,
            "torrents": successful,
            "uploaded": successful,
            "skipped": skipped,
            "errors": failed,
        },
        duration=duration,
    )

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
    from shelfr.discovery import get_new_releases

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

        success, _ = upload_torrent(
            torrent_path=torrent_path,
            save_path=qb_save_path,
        )

        if success:
            uploaded += 1

    logger.info(f"Uploaded {uploaded}/{len(torrent_paths)} torrent(s)")
    return uploaded
