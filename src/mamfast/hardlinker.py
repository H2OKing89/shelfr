"""
Hardlink audiobook files to staging directory for MAM upload.

Handles:
- Creating staging directory with MAM-compliant naming
- Hardlinking allowed file types (.m4b, .jpg, .pdf, .cue)
- Truncating filenames to ≤225 characters for MAM compliance
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from mamfast.config import get_settings
from mamfast.models import AudiobookRelease
from mamfast.utils.naming import (
    build_mam_path,
    extract_volume_number,
)

logger = logging.getLogger(__name__)


def stage_release(release: AudiobookRelease) -> Path:
    """
    Create staging directory and hardlink files for a release.

    1. Create directory under seed_root with MAM-compliant naming
    2. Find all allowed file types in source_dir
    3. Hardlink each file with cleaned names
    4. Update release.staging_dir and return the path

    Args:
        release: AudiobookRelease to stage

    Returns:
        Path to the staging directory

    Raises:
        ValueError: If release has no source_dir
        OSError: If hardlink fails and copy fallback also fails
    """
    settings = get_settings()

    if release.source_dir is None:
        raise ValueError("Release has no source_dir set")

    # Build seed directory path (hardlink destination for qBittorrent seeding)
    seed_root = settings.paths.seed_root
    seed_root.mkdir(parents=True, exist_ok=True)

    # Extract volume number from series_position or filename
    volume_number = extract_volume_number(release.title, series_position=release.series_position)

    # Count how many audio files we have (for multi-part budget calculation)
    m4b_count = sum(1 for f in release.source_dir.rglob("*.m4b"))
    part_count = max(1, m4b_count)

    # ASIN is required for MAM-compliant paths
    if not release.asin:
        raise ValueError(f"Release '{release.display_name}' has no ASIN - required for MAM staging")

    # Build MAM-compliant path using the new Phase 8 function
    # This ensures folder + filename combined fit within 225 chars
    mam_path = build_mam_path(
        series=release.series,
        title=release.title,
        volume_number=volume_number,
        arc=None,  # Arc extraction not yet implemented
        year=release.year,
        author=release.author,
        asin=release.asin,
        ripper_tag=settings.naming.ripper_tag if settings.naming else None,
        part_count=part_count,
        naming_config=settings.naming,
        max_path_length=settings.mam.max_filename_length,
    )

    # Log truncation info if any
    if mam_path.truncated:
        logger.info(
            f"Path truncated for {release.asin}: dropped {mam_path.dropped_components}, "
            f"final length {mam_path.length} chars"
        )

    staging_dir = seed_root / mam_path.folder

    logger.info(f"Staging release: {release.display_name}")
    logger.debug(f"  Source: {release.source_dir}")
    logger.debug(f"  Seed dir: {staging_dir}")
    logger.debug(f"  Path length: {mam_path.length} chars")

    staging_dir.mkdir(parents=True, exist_ok=True)

    # Find and hardlink allowed files (not recursive - just files in this folder)
    staged_files = []
    for src_file in find_allowed_files(release.source_dir):
        # Use the base filename from mam_path, but with this file's extension
        # For the main .m4b, use the computed filename directly
        # For other extensions, replace the extension
        if src_file.suffix.lower() == ".m4b":
            dst_name = mam_path.filename
        else:
            # Strip .m4b and add this file's extension
            base_without_ext = mam_path.filename.rsplit(".m4b", 1)[0]
            dst_name = f"{base_without_ext}{src_file.suffix}"

        dst_file = staging_dir / dst_name

        hardlink_file(src_file, dst_file)
        staged_files.append(dst_file)
        if src_file.name != dst_name:
            logger.debug(f"  Hardlinked: {src_file.name} -> {dst_name}")
        else:
            logger.debug(f"  Hardlinked: {src_file.name}")

    # Update release
    release.staging_dir = staging_dir
    release.files = staged_files

    # Find the main m4b
    m4b_files = [f for f in staged_files if f.suffix.lower() == ".m4b"]
    if m4b_files:
        release.main_m4b = m4b_files[0]

    logger.info(f"  Staged {len(staged_files)} files to {staging_dir}")

    return staging_dir


def find_allowed_files(source_dir: Path) -> list[Path]:
    """
    Find all files with allowed extensions in source directory.

    Searches recursively but returns flat list.
    """
    settings = get_settings()
    allowed_exts = {ext.lower() for ext in settings.mam.allowed_extensions}

    allowed_files = []
    for path in source_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in allowed_exts:
            allowed_files.append(path)

    return allowed_files


def hardlink_file(src: Path, dst: Path) -> None:
    """
    Create a hardlink from src to dst.

    If hardlink fails (e.g., cross-device), falls back to copy.

    Args:
        src: Source file to link from
        dst: Destination path for the hardlink

    Raises:
        FileNotFoundError: If source file does not exist
    """
    if not src.exists():
        raise FileNotFoundError(f"Source file does not exist: {src}")

    if dst.exists():
        logger.debug(f"  Destination exists, skipping: {dst.name}")
        return

    try:
        os.link(src, dst)
    except OSError as e:
        if e.errno == 18:  # EXDEV: Cross-device link
            logger.warning(f"Cross-device link, copying instead: {src.name}")
            import shutil

            shutil.copy2(src, dst)
        else:
            raise


def should_include_file(path: Path) -> bool:
    """Check if a file should be included based on extension."""
    settings = get_settings()
    allowed_exts = {ext.lower() for ext in settings.mam.allowed_extensions}
    return path.suffix.lower() in allowed_exts
