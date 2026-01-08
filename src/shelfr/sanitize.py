"""
Audio file metadata sanitization.

Strips unwanted metadata tags (like AUDIBLE_ACR) from audiobook files
before staging. Uses ffmpeg via Docker for lossless stream copy.

Safety features:
- Writes to temp file first, atomic rename on success
- Verifies chapter count preserved
- Verifies file size within tolerance
- Original file untouched until verification passes
"""

from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shelfr.config import get_settings
from shelfr.console import print_dry_run, print_info, print_success, print_warning
from shelfr.ffmpeg import (
    FFmpegResult,
    copy_audio,
    get_audio_tags,
    get_chapters,
)
from shelfr.ffmpeg import (
    is_available as ffmpeg_available,
)
from shelfr.models import AudiobookRelease

logger = logging.getLogger(__name__)


@dataclass
class SanitizeResult:
    """Result of sanitization operation."""

    success: bool
    files_checked: int = 0
    files_modified: int = 0
    files_skipped: int = 0
    tags_stripped: dict[Path, list[str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    skipped_reason: str | None = None


def check_unwanted_tags(
    file_path: Path,
    unwanted_tags: tuple[str, ...] | None = None,
) -> list[str]:
    """
    Check if a file contains any unwanted metadata tags.

    Args:
        file_path: Path to audio file
        unwanted_tags: Tuple of tag names to check (lowercase, from config).
            If None, reads from settings.workflow.upload.sanitize.tags.

    Returns:
        List of unwanted tag names found (empty if none)
    """
    # Get tags from config if not provided
    if unwanted_tags is None:
        settings = get_settings()
        unwanted_tags = settings.workflow.upload.sanitize.tags

    if not unwanted_tags:
        return []

    file_tags = get_audio_tags(file_path)
    if file_tags is None:
        logger.warning("Could not read tags from %s", file_path)
        return []

    # Tags in config are already lowercase for case-insensitive matching
    unwanted_set = set(unwanted_tags)
    found = []
    for key in file_tags:
        if key.lower() in unwanted_set:
            found.append(key)

    return found


def preview_sanitization(release: AudiobookRelease) -> dict[Path, list[str]]:
    """
    Preview what tags would be stripped from a release (for dry-run mode).

    This only probes files - it does NOT modify anything.

    Args:
        release: AudiobookRelease to check

    Returns:
        Dict mapping file paths to lists of tags that would be stripped.
        Empty dict if nothing to strip, disabled, or FFmpeg unavailable.
    """
    settings = get_settings()
    sanitize_config = settings.workflow.upload.sanitize

    # Check if sanitization is enabled
    if not sanitize_config.enabled:
        return {}

    # Check if any tags configured
    if not sanitize_config.tags:
        logger.debug("Sanitize enabled but no tags configured - nothing to preview")
        return {}

    # Check if FFmpeg is available
    if not settings.ffmpeg.enabled:
        return {}

    if not ffmpeg_available():
        return {}

    if release.source_dir is None:
        return {}

    result: dict[Path, list[str]] = {}
    for m4b_path in release.source_dir.glob("*.m4b"):
        found_tags = check_unwanted_tags(m4b_path, sanitize_config.tags)
        if found_tags:
            result[m4b_path] = found_tags

    return result


def _verify_sanitized_file(
    original: Path,
    sanitized: Path,
    original_chapters: list[dict[str, Any]] | None,
    expected_stripped_tags: tuple[str, ...],
) -> tuple[bool, str | None]:
    """
    Verify the sanitized file is valid.

    Checks:
    - File exists and has content
    - File size within tolerance (stream copy should be ~same size)
    - Chapter count preserved
    - Specified tags actually removed

    Args:
        original: Original file path
        sanitized: Sanitized temp file path
        original_chapters: Chapters from original file
        expected_stripped_tags: Tags that should have been removed (lowercase)

    Returns:
        Tuple of (success, error_message)
    """
    # Check file exists
    if not sanitized.exists():
        return False, "Sanitized file was not created"

    # Check file size (should be very close for stream copy)
    orig_size = original.stat().st_size
    new_size = sanitized.stat().st_size

    # Handle empty files (corrupt or test files)
    if orig_size == 0:
        if new_size > 0:
            return False, "Sanitized file has content but original was empty"
        # Both empty - continue to other checks
    else:
        # Allow 1% tolerance (metadata changes shouldn't be more)
        size_diff_percent = abs(orig_size - new_size) / orig_size * 100
        if size_diff_percent > 1.0:
            return False, f"File size changed by {size_diff_percent:.1f}% (expected <1%)"

    # Verify chapters preserved
    if original_chapters:
        new_chapters = get_chapters(sanitized)
        if new_chapters is None:
            return False, "Could not read chapters from sanitized file"

        if len(new_chapters) != len(original_chapters):
            return (
                False,
                f"Chapter count mismatch: {len(original_chapters)} → {len(new_chapters)}",
            )

    # Verify unwanted tags actually removed
    remaining_tags = check_unwanted_tags(sanitized, expected_stripped_tags)
    if remaining_tags:
        return False, f"Tags not removed: {remaining_tags}"

    return True, None


def sanitize_file(
    file_path: Path,
    *,
    unwanted_tags: tuple[str, ...] | None = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> tuple[bool, list[str], str | None]:
    """
    Sanitize a single audio file by removing unwanted tags.

    Uses safe approach:
    1. Check for unwanted tags
    2. If found, copy to temp with tags stripped
    3. Verify temp file integrity
    4. Atomic rename temp → original

    Args:
        file_path: Path to audio file to sanitize
        unwanted_tags: Tags to strip (lowercase, from config). If None, reads from config.
        dry_run: If True, only check and report (don't modify)
        verbose: If True, log extra details

    Returns:
        Tuple of (modified, tags_stripped, error_message)
    """
    # Get tags from config if not provided
    if unwanted_tags is None:
        settings = get_settings()
        unwanted_tags = settings.workflow.upload.sanitize.tags

    # Check for unwanted tags
    found_tags = check_unwanted_tags(file_path, unwanted_tags)

    if not found_tags:
        if verbose:
            logger.debug("No unwanted tags in %s", file_path.name)
        return False, [], None

    # Found unwanted tags
    logger.info("Found unwanted tags in %s: %s", file_path.name, found_tags)

    if dry_run:
        print_dry_run(f"Would strip tags from {file_path.name}: {found_tags}")
        return False, found_tags, None

    # Get original chapters for verification
    original_chapters = get_chapters(file_path)

    # Create temp file in same directory (for atomic rename on same filesystem)
    # Use timestamp in suffix to avoid collisions with user files
    temp_suffix = f".sanitizing.{int(time.time() * 1000000)}"
    temp_path = file_path.with_suffix(f"{file_path.suffix}{temp_suffix}")

    try:
        # Strip tags using ffmpeg copy
        result: FFmpegResult = copy_audio(
            file_path,
            temp_path,
            strip_tags=found_tags,
            preserve_chapters=True,
            preserve_cover=True,
            overwrite=True,
        )

        if not result.success:
            error = f"FFmpeg failed: {result.error or 'unknown error'}"
            logger.error(error)
            # Clean up temp file
            if temp_path.exists():
                temp_path.unlink()
            return False, [], error

        # Verify the sanitized file
        valid, verify_error = _verify_sanitized_file(
            file_path, temp_path, original_chapters, unwanted_tags
        )

        if not valid:
            logger.error("Verification failed: %s", verify_error)
            # Clean up temp file
            if temp_path.exists():
                temp_path.unlink()
            return False, [], f"Verification failed: {verify_error}"

        # All good - atomic rename
        # First backup original (in case something goes wrong)
        backup_path = file_path.with_suffix(f"{file_path.suffix}.backup")
        shutil.move(str(file_path), str(backup_path))

        try:
            shutil.move(str(temp_path), str(file_path))
            # Success - remove backup
            backup_path.unlink()
            logger.info("Successfully sanitized %s (removed: %s)", file_path.name, found_tags)
            return True, found_tags, None

        except Exception as e:
            # Restore from backup
            logger.error("Failed to replace file, restoring backup: %s", e)
            shutil.move(str(backup_path), str(file_path))
            if temp_path.exists():
                temp_path.unlink()
            return False, [], f"Failed to replace file: {e}"

    except Exception as e:
        logger.exception("Unexpected error during sanitization")
        # Clean up temp file
        if temp_path.exists():
            temp_path.unlink()
        return False, [], f"Unexpected error: {e}"


def sanitize_release(
    release: AudiobookRelease,
    *,
    dry_run: bool = False,
    verbose: bool = False,
) -> SanitizeResult:
    """
    Sanitize all audio files in a release.

    Checks each .m4b file for unwanted tags and strips them if found.
    Safe operation - only modifies files that need it.

    Args:
        release: AudiobookRelease to sanitize
        dry_run: If True, only report what would be done
        verbose: If True, print extra details

    Returns:
        SanitizeResult with operation summary
    """
    settings = get_settings()
    sanitize_config = settings.workflow.upload.sanitize

    # Check if sanitization is enabled
    if not sanitize_config.enabled:
        logger.debug("Sanitization disabled in config")
        return SanitizeResult(
            success=True,
            skipped_reason="Sanitization disabled in config",
        )

    # Check if any tags configured
    if not sanitize_config.tags:
        logger.debug("Sanitize enabled but no tags configured - nothing to do")
        return SanitizeResult(
            success=True,
            skipped_reason="No tags configured to strip",
        )

    # Check if FFmpeg is available
    if not settings.ffmpeg.enabled:
        logger.debug("FFmpeg disabled in config, skipping sanitization")
        return SanitizeResult(
            success=True,
            skipped_reason="FFmpeg disabled in config",
        )

    if not ffmpeg_available():
        logger.warning("FFmpeg/Docker not available, skipping sanitization")
        print_warning("FFmpeg not available - skipping metadata sanitization")
        return SanitizeResult(
            success=True,
            skipped_reason="FFmpeg/Docker not available",
        )

    if release.source_dir is None:
        return SanitizeResult(
            success=False,
            errors=["Release has no source_dir"],
        )

    # Find all m4b files
    m4b_files = list(release.source_dir.glob("*.m4b"))

    if not m4b_files:
        logger.debug("No m4b files found in %s", release.source_dir)
        return SanitizeResult(success=True)

    result = SanitizeResult(success=True, files_checked=len(m4b_files))

    if verbose:
        print_info(f"Checking {len(m4b_files)} audio file(s) for unwanted tags...")

    # Pass configured tags to sanitize_file
    for m4b_path in m4b_files:
        modified, tags, error = sanitize_file(
            m4b_path,
            unwanted_tags=sanitize_config.tags,
            dry_run=dry_run,
            verbose=verbose,
        )

        if error:
            result.errors.append(f"{m4b_path.name}: {error}")
            result.success = False
        elif modified:
            result.files_modified += 1
            result.tags_stripped[m4b_path] = tags
            print_success(f"Stripped {tags} from {m4b_path.name}")
        elif tags:
            # dry_run - tags found but not modified
            result.tags_stripped[m4b_path] = tags
        else:
            result.files_skipped += 1

    return result
