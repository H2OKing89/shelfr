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
from mamfast.utils.naming import truncate_filename

logger = logging.getLogger(__name__)


def stage_release(release: AudiobookRelease) -> Path:
    """
    Create staging directory and hardlink files for a release.

    1. Create directory under staging_root with MAM-compliant name
    2. Find all allowed file types in source_dir
    3. Hardlink each file (with truncated name if needed)
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

    staging_name = release.safe_dirname
    staging_name = truncate_filename(staging_name, settings.mam.max_filename_length)
    staging_dir = seed_root / staging_name

    logger.info(f"Staging release: {release.display_name}")
    logger.debug(f"  Source: {release.source_dir}")
    logger.debug(f"  Seed dir: {staging_dir}")

    staging_dir.mkdir(parents=True, exist_ok=True)

    # Find and hardlink allowed files
    staged_files = []
    for src_file in find_allowed_files(release.source_dir):
        dst_name = truncate_filename(src_file.name, settings.mam.max_filename_length)
        dst_file = staging_dir / dst_name

        hardlink_file(src_file, dst_file)
        staged_files.append(dst_file)
        logger.debug(f"  Hardlinked: {src_file.name} → {dst_name}")

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
    """
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
