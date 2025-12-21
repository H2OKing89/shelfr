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
from mamfast.models import AudiobookRelease, MamPath
from mamfast.utils.naming import (
    build_mam_path,
    extract_volume_number,
    resolve_series,
)
from mamfast.utils.permissions import fix_directory_ownership

logger = logging.getLogger(__name__)


def compute_staging_path(release: AudiobookRelease) -> MamPath:
    """
    Compute the MAM-compliant staging path for a release (without side effects).

    This is a pure function that computes what the staging path would be,
    used by both stage_release() and dry-run mode.

    Args:
        release: AudiobookRelease to compute path for

    Returns:
        MamPath with folder and filename

    Raises:
        ValueError: If release has no source_dir or ASIN
    """
    settings = get_settings()

    if release.source_dir is None:
        raise ValueError("Release has no source_dir set")

    if not release.asin:
        raise ValueError(f"Release '{release.display_name}' has no ASIN - required for MAM staging")

    # Extract volume number from series_position or filename
    volume_number = extract_volume_number(release.title, series_position=release.series_position)

    # Resolve series info from multiple sources if not already set
    # This handles new releases where Audible/Libation didn't have series metadata
    # Priority: release.series (from Libation) → resolve_series (Libation path → title heuristics)
    series_name = release.series
    if not series_name:
        series_info = resolve_series(
            audnex_data=None,  # Not available at staging time
            libation_path=release.source_dir,
            title=release.title,
        )
        if series_info:
            series_name = series_info.name
            # Also use resolved volume number if we didn't have one
            if not volume_number and series_info.position:
                volume_number = series_info.position
            logger.debug(
                "Resolved series from %s: %s #%s",
                series_info.source.value,
                series_name,
                volume_number or "N/A",
            )

    # Count how many audio files we have (for multi-part budget calculation)
    # Use glob (not rglob) since we only process files in this folder, not recursive
    m4b_count = sum(1 for f in release.source_dir.glob("*.m4b"))
    part_count = max(1, m4b_count)

    # Build MAM-compliant path using the new Phase 8 function
    # This ensures folder + filename combined fit within 225 chars
    mam_path = build_mam_path(
        series=series_name,
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

    return mam_path


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

    # Compute MAM-compliant path (validates ASIN, resolves series, etc.)
    mam_path = compute_staging_path(release)

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
            base_without_ext = mam_path.filename.removesuffix(".m4b")
            dst_name = f"{base_without_ext}{src_file.suffix}"

            # Check if non-.m4b extension exceeds budget (e.g., .jpeg > .m4b)
            max_path_len = settings.mam.max_filename_length
            full_ancillary_path = f"{mam_path.folder}/{dst_name}"
            original_len = len(full_ancillary_path)
            if original_len > max_path_len:
                # Truncate base and verify the full path fits; loop if needed
                truncated_base = base_without_ext
                while len(f"{mam_path.folder}/{truncated_base}{src_file.suffix}") > max_path_len:
                    if len(truncated_base) <= 1:
                        break  # Safety: don't truncate to empty
                    truncated_base = truncated_base[:-1]
                dst_name = f"{truncated_base}{src_file.suffix}"
                new_len = len(f"{mam_path.folder}/{dst_name}")
                logger.debug(
                    f"  Truncated ancillary filename for {src_file.suffix}: "
                    f"{original_len} -> {new_len} chars"
                )

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

    # Fix ownership on staged directory and files
    fix_staging_permissions(staging_dir)

    logger.info(f"  Staged {len(staged_files)} files to {staging_dir}")

    return staging_dir


def fix_staging_permissions(staging_dir: Path) -> int:
    """
    Fix ownership on staged directory and all files within.

    Sets UID:GID to configured values (default 99:100 for Unraid).

    Args:
        staging_dir: Directory to fix ownership on

    Returns:
        Number of items (directory + files) with ownership changed
    """
    settings = get_settings()
    return fix_directory_ownership(
        staging_dir,
        settings.target_uid,
        settings.target_gid,
        recursive=False,  # Staging dirs are flat
    )


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
