"""Post-import cleanup for Libation source files.

Handles cleanup of original Libation source files after successful import
to Audiobookshelf library. Supports multiple strategies with safety guardrails.

See docs/audiobookshelf/CLEANUP_PLAN.md for full design documentation.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from mamfast.abs.asin import extract_asin, is_valid_asin

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

# Type alias for cleanup result status
CleanupStatus = Literal["success", "skipped", "failed", "dry_run"]

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# Import statuses that are eligible for cleanup
# Note: "trump_replaced" is NOT included because shutil.move() already removed
# the staging files - only "success" (hardlink) imports leave files to clean up
CLEANUP_ELIGIBLE_STATUSES = frozenset({"success"})

# Default marker file name for hide strategy
DEFAULT_HIDE_MARKER = ".mamfast_imported"


# ─────────────────────────────────────────────────────────────────────────────
# Enums and Dataclasses
# ─────────────────────────────────────────────────────────────────────────────


class CleanupStrategy(str, Enum):
    """Strategy for cleaning up source files after import.

    - NONE: Leave source files in place (default, safest)
    - HIDE: Add marker file to prevent Libation re-download detection
    - MOVE: Move to cleanup_path for later review/deletion
    - DELETE: Remove source files (DANGEROUS - data loss if seeding fails)
    """

    NONE = "none"
    HIDE = "hide"
    MOVE = "move"
    DELETE = "delete"


@dataclass
class CleanupPrefs:
    """Cleanup preferences from config.

    Attributes:
        strategy: Cleanup strategy to apply
        cleanup_path: Destination for move strategy (required if strategy=MOVE)
        require_seed_exists: Only cleanup if seed hardlinks exist
        verify_in_abs: Query ABS API to confirm book exists before cleanup
        hide_marker: Filename for hide strategy marker
        min_age_days: Only cleanup sources older than N days (0 = disabled)
        ignore_dirs: Directory names to always skip during standalone cleanup
        ignore_glob: Glob patterns to skip during standalone cleanup
        prune_empty_dirs: Remove empty directories from staging after import
    """

    strategy: CleanupStrategy = CleanupStrategy.NONE
    cleanup_path: Path | None = None
    require_seed_exists: bool = True
    verify_in_abs: bool = False
    hide_marker: str = DEFAULT_HIDE_MARKER
    min_age_days: int = 0
    ignore_dirs: tuple[str, ...] = ("__import_test", ".git", ".venv")
    ignore_glob: tuple[str, ...] = ("*/__*", "*/.#*")
    prune_empty_dirs: bool = False  # Default off - opt-in to avoid surprises


@dataclass
class CleanupResult:
    """Result of a cleanup operation.

    Attributes:
        source_path: Original source folder that was cleaned up
        status: Result status (success, skipped, failed, dry_run)
        strategy: Strategy that was applied
        error: Error message if status is "failed"
        destination: New location if strategy was MOVE
    """

    source_path: Path
    status: CleanupStatus
    strategy: CleanupStrategy
    error: str | None = None
    destination: Path | None = None  # For move strategy


class CleanupError(Exception):
    """Error during cleanup operation."""


# ─────────────────────────────────────────────────────────────────────────────
# Eligibility Checks
# ─────────────────────────────────────────────────────────────────────────────


def is_cleanup_eligible(folder: Path, *, require_metadata: bool = True) -> bool:
    """Check if a folder is eligible for cleanup.

    A folder is eligible if it:
    1. Contains at least one .m4b file
    2. AND has either:
       - A .metadata.json file (Libation+mamfast style)
       - OR {ASIN.XXXXXXXXXX} pattern in folder name

    This ensures we only clean up folders that have been processed by mamfast,
    not raw Libation folders or other content.

    Args:
        folder: Path to check for eligibility
        require_metadata: If True, require .metadata.json OR ASIN in folder name

    Returns:
        True if folder is eligible for cleanup
    """
    if not folder.is_dir():
        return False

    # Check for at least one .m4b file
    has_m4b = any(folder.glob("*.m4b"))
    if not has_m4b:
        return False

    if not require_metadata:
        return True

    # Check for .metadata.json file
    has_metadata = any(folder.glob("*.metadata.json"))
    if has_metadata:
        return True

    # Check for ASIN in folder name
    asin = extract_asin(folder.name)
    return bool(is_valid_asin(asin))


def should_ignore_folder(
    folder: Path,
    *,
    ignore_dirs: Sequence[str] = (),
    ignore_glob: Sequence[str] = (),
) -> bool:
    """Check if a folder should be ignored during cleanup.

    Args:
        folder: Path to check
        ignore_dirs: Directory names to ignore (exact match)
        ignore_glob: Glob patterns to ignore

    Returns:
        True if folder should be skipped
    """
    folder_name = folder.name

    # Check exact directory name matches
    if folder_name in ignore_dirs:
        return True

    # Check if any parent directory matches ignore_dirs
    for parent in folder.parents:
        if parent.name in ignore_dirs:
            return True

    # Check glob patterns
    # Note: We check against the full path for glob patterns
    folder_str = str(folder)
    for pattern in ignore_glob:
        # Simple glob-style matching
        import fnmatch

        if fnmatch.fnmatch(folder_str, pattern):
            return True
        if fnmatch.fnmatch(folder_name, pattern):
            return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# Seed Verification
# ─────────────────────────────────────────────────────────────────────────────


def verify_seed_exists(
    source_path: Path,
    seed_root: Path,
    *,
    asin: str | None = None,
) -> tuple[bool, Path | None]:
    """Check that seed hardlinks exist for source files.

    Verifies that the seeding copy in seed_root still exists and has
    hardlinked files matching the source. This prevents data loss if
    the torrent was removed from qBittorrent.

    Args:
        source_path: Original source folder (under library_root)
        seed_root: Seed/staging root folder
        asin: Optional ASIN to help locate seed folder

    Returns:
        Tuple of (exists: bool, seed_path: Path | None)
        - exists: True if at least one hardlinked file was found
        - seed_path: Path to the seed folder if found
    """
    # Strategy 1: Look for folder with same name under seed_root
    folder_name = source_path.name
    direct_match = seed_root / folder_name

    if direct_match.is_dir() and _has_hardlinked_files(source_path, direct_match):
        return True, direct_match

    # Strategy 2: If ASIN provided, search for folder containing ASIN
    if asin and is_valid_asin(asin):
        for candidate in seed_root.iterdir():
            if not candidate.is_dir():
                continue
            if asin in candidate.name and _has_hardlinked_files(source_path, candidate):
                return True, candidate

    # Strategy 3: Search all seed folders for hardlink matches
    # This is expensive but catches renamed folders
    for candidate in seed_root.iterdir():
        if not candidate.is_dir():
            continue
        if _has_hardlinked_files(source_path, candidate):
            return True, candidate

    return False, None


def _has_hardlinked_files(source_dir: Path, seed_dir: Path) -> bool:
    """Check if source and seed directories share hardlinked files.

    Two files are hardlinked if they share the same inode number on the
    same filesystem.

    Args:
        source_dir: Original source directory
        seed_dir: Potential seed directory

    Returns:
        True if at least one file in source has a hardlink in seed
    """
    # Get all .m4b files in source
    source_m4b = list(source_dir.glob("*.m4b"))
    if not source_m4b:
        return False

    # Get inodes of source files
    source_inodes: set[int] = set()
    for f in source_m4b:
        try:
            source_inodes.add(os.stat(f).st_ino)
        except OSError:
            # File may have been moved/deleted between listing and stat - skip it
            continue

    if not source_inodes:
        return False

    # Check if any seed files have matching inodes
    for seed_file in seed_dir.glob("*.m4b"):
        try:
            if os.stat(seed_file).st_ino in source_inodes:
                return True
        except OSError:
            # Seed file may have been moved/deleted - skip it
            continue

    return False


# ─────────────────────────────────────────────────────────────────────────────
# Cleanup Actions
# ─────────────────────────────────────────────────────────────────────────────


def _cleanup_hide(source_path: Path, marker_name: str, *, dry_run: bool) -> CleanupResult:
    """Apply hide strategy: create marker file.

    Creates a hidden marker file in the source folder. This can be used
    to prevent Libation from detecting the folder for re-download.

    Args:
        source_path: Source folder to mark
        marker_name: Name of the marker file
        dry_run: If True, don't actually create the file

    Returns:
        CleanupResult with status
    """
    marker_path = source_path / marker_name

    if dry_run:
        logger.info("[DRY RUN] Would create marker: %s", marker_path)
        return CleanupResult(
            source_path=source_path,
            status="dry_run",
            strategy=CleanupStrategy.HIDE,
        )

    try:
        marker_path.touch()
        logger.info("Created cleanup marker: %s", marker_path)
        return CleanupResult(
            source_path=source_path,
            status="success",
            strategy=CleanupStrategy.HIDE,
        )
    except OSError as e:
        error_msg = f"Failed to create marker {marker_path}: {e}"
        logger.error(error_msg)
        return CleanupResult(
            source_path=source_path,
            status="failed",
            strategy=CleanupStrategy.HIDE,
            error=error_msg,
        )


def _cleanup_move(
    source_path: Path,
    cleanup_path: Path,
    *,
    dry_run: bool,
) -> CleanupResult:
    """Apply move strategy: relocate folder to cleanup path.

    Moves the entire source folder to cleanup_path, preserving the folder
    name. Uses a collision-safe destination name if needed.

    Args:
        source_path: Source folder to move
        cleanup_path: Base destination path
        dry_run: If True, don't actually move

    Returns:
        CleanupResult with status and destination
    """
    # Create destination path
    dest_path = cleanup_path / source_path.name

    # Handle collision
    if dest_path.exists():
        # Add numeric suffix
        counter = 1
        while True:
            new_name = f"{source_path.name}_{counter}"
            dest_path = cleanup_path / new_name
            if not dest_path.exists():
                break
            counter += 1

    if dry_run:
        logger.info("[DRY RUN] Would move: %s -> %s", source_path, dest_path)
        return CleanupResult(
            source_path=source_path,
            status="dry_run",
            strategy=CleanupStrategy.MOVE,
            destination=dest_path,
        )

    try:
        # Ensure cleanup_path exists
        cleanup_path.mkdir(parents=True, exist_ok=True)

        # Move the folder
        shutil.move(str(source_path), str(dest_path))
        logger.info("Moved source: %s -> %s", source_path, dest_path)
        return CleanupResult(
            source_path=source_path,
            status="success",
            strategy=CleanupStrategy.MOVE,
            destination=dest_path,
        )
    except OSError as e:
        error_msg = f"Failed to move {source_path} to {dest_path}: {e}"
        logger.error(error_msg)
        return CleanupResult(
            source_path=source_path,
            status="failed",
            strategy=CleanupStrategy.MOVE,
            error=error_msg,
        )


def _cleanup_delete(source_path: Path, *, dry_run: bool) -> CleanupResult:
    """Apply delete strategy: remove folder entirely.

    WARNING: This permanently deletes the source folder and all contents.
    Only use when you're confident the seed copy and ABS copy exist.

    Args:
        source_path: Source folder to delete
        dry_run: If True, don't actually delete

    Returns:
        CleanupResult with status
    """
    if dry_run:
        logger.info("[DRY RUN] Would delete: %s", source_path)
        return CleanupResult(
            source_path=source_path,
            status="dry_run",
            strategy=CleanupStrategy.DELETE,
        )

    try:
        shutil.rmtree(source_path)
        logger.info("Deleted source: %s", source_path)
        return CleanupResult(
            source_path=source_path,
            status="success",
            strategy=CleanupStrategy.DELETE,
        )
    except OSError as e:
        error_msg = f"Failed to delete {source_path}: {e}"
        logger.error(error_msg)
        return CleanupResult(
            source_path=source_path,
            status="failed",
            strategy=CleanupStrategy.DELETE,
            error=error_msg,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Main Cleanup Function
# ─────────────────────────────────────────────────────────────────────────────


def cleanup_source(
    source_path: Path,
    prefs: CleanupPrefs,
    *,
    seed_root: Path | None = None,
    asin: str | None = None,
    dry_run: bool = False,
) -> CleanupResult:
    """Execute cleanup on source folder.

    Applies the configured cleanup strategy to the source folder after
    performing safety checks.

    Args:
        source_path: Path to source folder to clean up
        prefs: Cleanup preferences (strategy, paths, etc.)
        seed_root: Seed root for hardlink verification (required if require_seed_exists)
        asin: ASIN for the book (helps locate seed folder)
        dry_run: If True, don't actually modify files

    Returns:
        CleanupResult with status and details

    Raises:
        CleanupError: If attempting to cleanup a path under seed_root
    """
    strategy = prefs.strategy

    # Strategy NONE is a no-op
    if strategy == CleanupStrategy.NONE:
        logger.debug("Cleanup strategy is NONE, skipping: %s", source_path)
        return CleanupResult(
            source_path=source_path,
            status="skipped",
            strategy=strategy,
        )

    # Safety check: never cleanup anything under seed_root
    if seed_root and source_path.is_relative_to(seed_root):
        raise CleanupError(f"Refusing to cleanup path under seed_root: {source_path}")

    # Verify source exists
    if not source_path.exists():
        logger.warning("Source path does not exist, skipping cleanup: %s", source_path)
        return CleanupResult(
            source_path=source_path,
            status="skipped",
            strategy=strategy,
            error="Source path does not exist",
        )

    # Verify seed exists (if required)
    if prefs.require_seed_exists:
        if not seed_root:
            logger.warning(
                "require_seed_exists is True but no seed_root provided, skipping: %s",
                source_path,
            )
            return CleanupResult(
                source_path=source_path,
                status="skipped",
                strategy=strategy,
                error="No seed_root provided for verification",
            )

        seed_exists, seed_path = verify_seed_exists(source_path, seed_root, asin=asin)
        if not seed_exists:
            logger.warning(
                "Seed not found for source, skipping cleanup: %s",
                source_path,
            )
            return CleanupResult(
                source_path=source_path,
                status="skipped",
                strategy=strategy,
                error="Seed copy not found",
            )
        logger.debug("Verified seed exists at: %s", seed_path)

    # Apply strategy
    if strategy == CleanupStrategy.HIDE:
        return _cleanup_hide(source_path, prefs.hide_marker, dry_run=dry_run)

    elif strategy == CleanupStrategy.MOVE:
        if not prefs.cleanup_path:
            error_msg = "cleanup_path is required for MOVE strategy"
            logger.error(error_msg)
            return CleanupResult(
                source_path=source_path,
                status="failed",
                strategy=strategy,
                error=error_msg,
            )
        return _cleanup_move(source_path, prefs.cleanup_path, dry_run=dry_run)

    elif strategy == CleanupStrategy.DELETE:
        return _cleanup_delete(source_path, dry_run=dry_run)

    else:
        # Should not reach here
        error_msg = f"Unknown cleanup strategy: {strategy}"
        logger.error(error_msg)
        return CleanupResult(
            source_path=source_path,
            status="failed",
            strategy=strategy,
            error=error_msg,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Empty Directory Pruning
# ─────────────────────────────────────────────────────────────────────────────


def prune_empty_dirs(root: Path, *, dry_run: bool = False) -> int:
    """Remove empty directories under root (but never root itself).

    This is useful after import with trumping, where shutil.move() removes
    staging files but leaves empty author/series directory structures behind.

    Uses bottom-up traversal to handle nested empty directories correctly.
    Safe to run multiple times - idempotent.

    Args:
        root: Root directory to prune (this directory itself is never removed)
        dry_run: If True, don't actually remove directories, just count

    Returns:
        Number of directories removed (or that would be removed in dry_run)
    """
    removed = 0
    root = root.resolve()

    if not root.exists():
        logger.debug("Prune root does not exist: %s", root)
        return 0

    if not root.is_dir():
        logger.warning("Prune root is not a directory: %s", root)
        return 0

    # Track directories "removed" in dry-run mode to handle nested empties
    dry_run_removed: set[Path] = set()

    # Walk bottom-up so we remove leaf directories first
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        path = Path(dirpath)

        # Never remove the root directory itself
        if path == root:
            continue

        # Skip if directory has files
        if filenames:
            continue

        # Skip if directory still has subdirectories
        # (may have been emptied during this walk but not yet processed)
        if dirnames:
            # Check if any subdirs actually exist (they may have been removed)
            # In dry-run mode, also check our simulated removal set
            remaining_dirs = [
                d for d in dirnames if (path / d).exists() and (path / d) not in dry_run_removed
            ]
            if remaining_dirs:
                continue

        # Directory is empty (or only had subdirs that were already removed)
        # Double-check by listing directory contents
        # In dry-run mode, filter out dirs we've already "removed"
        try:
            contents = [c for c in path.iterdir() if c not in dry_run_removed]
            if contents:
                # Not actually empty, skip
                continue
        except OSError as e:
            logger.debug("Cannot list directory %s: %s", path, e)
            continue

        # Directory is empty - remove it
        if dry_run:
            logger.debug("[DRY RUN] Would remove empty directory: %s", path)
            dry_run_removed.add(path)
            removed += 1
        else:
            try:
                path.rmdir()
                logger.debug("Removed empty directory: %s", path)
                removed += 1
            except OSError as e:
                # Race condition or permissions issue - ignore and continue
                logger.debug("Failed to remove empty directory %s: %s", path, e)

    return removed


# ─────────────────────────────────────────────────────────────────────────────
# Orphaned Folder Detection and Cleanup
# ─────────────────────────────────────────────────────────────────────────────

AUDIO_EXTENSIONS = frozenset({".m4b", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".wav", ".aac"})


@dataclass
class OrphanedFolder:
    """An orphaned folder with metadata but no audio files.

    Attributes:
        path: Full path to the orphaned folder
        files: List of files in the folder (metadata.json, cover.jpg, etc.)
        matching_folder: Path to a matching folder with audio (if found)
        match_score: Similarity score to matching folder (0-1)
    """

    path: Path
    files: list[str]
    matching_folder: Path | None = None
    match_score: float = 0.0


@dataclass
class OrphanScanResult:
    """Results from scanning for orphaned folders.

    Attributes:
        orphaned_with_match: Orphans that have a matching audio folder
        orphaned_no_match: Orphans with no matching folder found
        total_metadata_folders: Total folders with metadata.json
        total_audio_folders: Folders with both metadata and audio
    """

    orphaned_with_match: list[OrphanedFolder]
    orphaned_no_match: list[OrphanedFolder]
    total_metadata_folders: int
    total_audio_folders: int


def _has_audio_files(path: Path) -> bool:
    """Check if directory contains audio files."""
    try:
        return any(f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS for f in path.iterdir())
    except (PermissionError, OSError):
        return False


def _similarity(a: str, b: str) -> float:
    """Calculate string similarity ratio (0-1)."""
    from difflib import SequenceMatcher

    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def scan_orphaned_folders(
    library_root: Path,
    min_match_score: float = 0.5,
    progress_callback: Callable[[str, int | None], None] | None = None,
) -> OrphanScanResult:
    """Scan ABS library for orphaned folders.

    An orphaned folder has metadata.json but no audio files, typically
    created by ABS when it creates duplicate library entries.

    Args:
        library_root: Root of ABS library to scan
        min_match_score: Minimum similarity score to consider a match
        progress_callback: Optional callback(description, advance) for progress updates

    Returns:
        OrphanScanResult with categorized orphaned folders
    """
    orphaned: list[Path] = []
    has_audio: list[Path] = []

    def _progress(desc: str, advance: int | None = None) -> None:
        if progress_callback:
            progress_callback(desc, advance)

    # First pass: find all folders with metadata.json (spinner - count unknown)
    _progress("Scanning directories...")
    folder_count = 0
    for root, _dirs, files in os.walk(library_root):
        root_path = Path(root)
        folder_count += 1

        # Update progress every 100 folders
        if folder_count % 100 == 0:
            _progress(f"Scanned {folder_count} directories...")

        if "metadata.json" not in files:
            continue

        if _has_audio_files(root_path):
            has_audio.append(root_path)
        else:
            orphaned.append(root_path)

    _progress(f"Found {len(orphaned) + len(has_audio)} folders with metadata")

    logger.info(
        "Found %d folders with metadata.json (%d with audio, %d orphaned)",
        len(orphaned) + len(has_audio),
        len(has_audio),
        len(orphaned),
    )

    # Build index of audio folders by parent directory
    audio_by_parent: dict[Path, list[Path]] = {}
    for p in has_audio:
        parent = p.parent
        if parent not in audio_by_parent:
            audio_by_parent[parent] = []
        audio_by_parent[parent].append(p)

    # Check each orphaned folder for a matching sibling with audio
    orphaned_with_match: list[OrphanedFolder] = []
    orphaned_no_match: list[OrphanedFolder] = []

    _progress("Matching orphaned folders...")
    for i, orphan_path in enumerate(orphaned):
        if i % 10 == 0:
            _progress(f"Matching {i}/{len(orphaned)}...")

        parent = orphan_path.parent
        siblings = audio_by_parent.get(parent, [])

        # Find best matching sibling
        best_match: Path | None = None
        best_score = 0.0

        for sibling in siblings:
            score = _similarity(orphan_path.name, sibling.name)
            if score > best_score:
                best_score = score
                best_match = sibling

        # Get files in orphaned folder
        try:
            files = [f.name for f in orphan_path.iterdir() if f.is_file()]
        except (PermissionError, OSError):
            files = []

        orphan = OrphanedFolder(
            path=orphan_path,
            files=files,
            matching_folder=best_match if best_score >= min_match_score else None,
            match_score=best_score if best_score >= min_match_score else 0.0,
        )

        if orphan.matching_folder:
            orphaned_with_match.append(orphan)
        else:
            orphaned_no_match.append(orphan)

    _progress(f"Complete: {len(orphaned)} orphans analyzed")

    return OrphanScanResult(
        orphaned_with_match=orphaned_with_match,
        orphaned_no_match=orphaned_no_match,
        total_metadata_folders=len(orphaned) + len(has_audio),
        total_audio_folders=len(has_audio),
    )


@dataclass
class OrphanCleanupResult:
    """Result of orphan cleanup operation.

    Attributes:
        removed: Number of orphaned folders removed
        skipped: Number skipped (no match or user declined)
        failed: Number that failed to remove
        dry_run: Whether this was a dry run
    """

    removed: int = 0
    skipped: int = 0
    failed: int = 0
    dry_run: bool = False


def cleanup_orphaned_folders(
    orphans: list[OrphanedFolder],
    *,
    dry_run: bool = False,
    require_match: bool = True,
) -> OrphanCleanupResult:
    """Remove orphaned folders.

    Args:
        orphans: List of orphaned folders to clean up
        dry_run: If True, don't actually delete anything
        require_match: If True, only remove orphans with matching audio folders

    Returns:
        OrphanCleanupResult with counts
    """
    result = OrphanCleanupResult(dry_run=dry_run)

    for orphan in orphans:
        # Skip if no match and we require one
        if require_match and not orphan.matching_folder:
            logger.debug("Skipping %s - no matching folder", orphan.path.name)
            result.skipped += 1
            continue

        if dry_run:
            logger.info("[DRY RUN] Would remove: %s", orphan.path)
            result.removed += 1
            continue

        try:
            shutil.rmtree(orphan.path)
            logger.info("Removed orphaned folder: %s", orphan.path)
            result.removed += 1
        except OSError as e:
            logger.error("Failed to remove %s: %s", orphan.path, e)
            result.failed += 1

    return result
