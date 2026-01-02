"""Rename audiobook folders in Audiobookshelf library to match MAM schema.

This module handles renaming existing ABS library folders to follow
the MAM naming convention for consistency and better organization.

See docs/audiobookshelf/ABS_RENAME_TOOL.md for full design documentation.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import ValidationError

from shelfr.abs.asin import (
    is_valid_asin,
    resolve_asin_from_folder_with_mediainfo,
    resolve_asin_via_abs_search,
)
from shelfr.abs.importer import ParsedFolderName, parse_mam_folder_name
from shelfr.console import (
    confirm,
    print_dry_run,
    print_step,
    print_success,
    print_warning,
    progress_context,
)
from shelfr.schemas.abs_metadata import AbsMetadataJson
from shelfr.utils.fuzzy import is_suspicious_change, similarity_ratio
from shelfr.utils.naming import build_mam_folder_name, format_volume_number
from shelfr.utils.paths import safe_dirname

if TYPE_CHECKING:
    from shelfr.abs.client import AbsClient
    from shelfr.config import NamingConfig
    from shelfr.models import NormalizedBook

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

# Audio extensions (shared with asin.py)
AUDIO_EXTS = frozenset({".m4b", ".mp3", ".m4a", ".flac", ".ogg", ".opus"})

# Edition flags to detect and preserve
EDITION_FLAGS = [
    "Full-Cast",
    "Full Cast",
    "Dolby Atmos",
    "Atmos",
    "Unabridged",
    "Abridged",
    "Dramatized",
    "Graphic Audio",
    "Publisher's Pack",
    "Publishers Pack",
]

# Patterns for edition flag extraction (case-insensitive)
_EDITION_FLAG_PATTERN = re.compile(
    r"\((" + "|".join(re.escape(f) for f in EDITION_FLAGS) + r")\)",
    re.IGNORECASE,
)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class AbsMetadata:
    """Parsed ABS metadata.json (post-validation)."""

    title: str | None = None
    authors: list[str] | None = None
    series: str | None = None
    series_position: str | None = None  # String to preserve "1.5", "1-3", "1p1"
    year: int | None = None
    asin: str | None = None
    narrators: list[str] | None = None


# Rename status type
RenameStatus = Literal[
    "needs_rename",  # Folder name differs from target
    "up_to_date",  # Already matches target schema
    "missing_asin",  # No ASIN found, cannot rename
    "duplicate_asin",  # Same ASIN in multiple folders (conflict)
    "target_exists",  # Target folder name already exists
    "error",  # Parse or other error
]


@dataclass
class RenameCandidate:
    """A folder that may need renaming."""

    source_path: Path
    current_name: str
    parsed: ParsedFolderName | None = None
    target_name: str | None = None
    status: RenameStatus = "needs_rename"
    abs_metadata: AbsMetadata | None = None
    normalized_book: NormalizedBook | None = None
    edition_flags: list[str] = field(default_factory=list)
    asin_source: str | None = None
    error_message: str | None = None


@dataclass
class RenameResult:
    """Result of a rename operation."""

    source_path: Path
    target_path: Path | None
    status: Literal["success", "skipped", "failed", "dry_run"]
    files_renamed: list[str] | None = None
    error: str | None = None


@dataclass
class RenameSummary:
    """Summary of rename operations."""

    total_candidates: int = 0
    renamed: int = 0
    skipped_up_to_date: int = 0
    skipped_missing_asin: int = 0
    skipped_duplicate_asin: int = 0
    skipped_target_exists: int = 0
    errors: int = 0


# =============================================================================
# Discovery Functions
# =============================================================================


def has_audio_files(path: Path) -> bool:
    """Check if directory contains audio files.

    Args:
        path: Directory to check

    Returns:
        True if directory contains at least one audio file
    """
    try:
        return any(p.is_file() and p.suffix.lower() in AUDIO_EXTS for p in path.iterdir())
    except PermissionError:
        return False


def discover_rename_candidates(
    source_dir: Path,
    pattern: str = "*",
) -> list[Path]:
    """Find leaf folders that contain audio files.

    A leaf folder has audio files AND no subdirectory with audio files.
    This preserves Author/Series hierarchy while only targeting book folders.

    Args:
        source_dir: Root directory to scan
        pattern: Glob pattern to filter folder names

    Returns:
        Sorted list of leaf folder paths with audio files
    """
    import fnmatch

    candidates: list[Path] = []

    for root, dirs, _files in os.walk(source_dir):
        root_path = Path(root)

        # Only consider dirs that match pattern
        if pattern != "*" and not fnmatch.fnmatch(root_path.name, pattern):
            continue

        # Must have audio files
        if not has_audio_files(root_path):
            continue

        # Skip if any subdir also has audio (not a leaf)
        if any(has_audio_files(root_path / d) for d in dirs):
            continue

        candidates.append(root_path)

    return sorted(candidates)


# =============================================================================
# Metadata Parsing
# =============================================================================


def parse_abs_metadata(folder: Path) -> AbsMetadata | None:
    """Parse and validate ABS metadata.json if present.

    Args:
        folder: Folder path that may contain metadata.json

    Returns:
        AbsMetadata with parsed fields, or None if not present/invalid
    """
    meta_path = folder / "metadata.json"
    if not meta_path.exists():
        return None

    try:
        with open(meta_path, encoding="utf-8") as f:
            data = json.load(f)

        # Validate with Pydantic (using unified schema from schemas/)
        schema = AbsMetadataJson.model_validate(data)

        # Parse series from "Series Name #N" format
        series_name = None
        series_pos = None
        if schema.series:
            series_str = schema.series[0]
            if "#" in series_str:
                parts = series_str.rsplit("#", 1)
                series_name = parts[0].strip()
                pos_str = parts[1].strip()
                # Keep as string to preserve decimal/part/range notation
                series_pos = pos_str
            else:
                series_name = series_str

        # Parse year (can be int or string via published_year alias)
        year = None
        if schema.published_year:
            with contextlib.suppress(ValueError, TypeError):
                year = int(schema.published_year)

        return AbsMetadata(
            title=schema.title,
            authors=schema.authors or None,
            series=series_name,
            series_position=series_pos,
            year=year,
            asin=schema.asin,
            narrators=schema.narrators or None,
        )
    except (json.JSONDecodeError, ValidationError) as e:
        logger.debug(f"Failed to parse ABS metadata.json in {folder}: {e}")
        return None
    except Exception as e:
        logger.debug(f"Unexpected error parsing ABS metadata.json in {folder}: {e}")
        return None


def detect_edition_flags(name: str) -> list[str]:
    """Detect edition flags in folder name.

    Args:
        name: Folder name to check

    Returns:
        List of detected edition flags (e.g., ["Full-Cast", "Dolby Atmos"])
    """
    flags: list[str] = []
    # Check for flags in parentheses
    for match in _EDITION_FLAG_PATTERN.finditer(name):
        flag = match.group(1)
        # Normalize some variants
        if flag.lower() == "full cast":
            flag = "Full-Cast"
        elif flag.lower() == "atmos":
            flag = "Dolby Atmos"
        elif flag.lower() == "publishers pack":
            flag = "Publisher's Pack"
        flags.append(flag)
    return flags


# =============================================================================
# Candidate Processing
# =============================================================================


def parse_candidate(folder: Path) -> RenameCandidate:
    """Parse folder name and create a RenameCandidate.

    Args:
        folder: Path to the folder

    Returns:
        RenameCandidate with parsed information
    """
    name = folder.name

    # Parse folder name using existing parser
    parsed = parse_mam_folder_name(name)

    # Detect edition flags
    flags = detect_edition_flags(name)

    return RenameCandidate(
        source_path=folder,
        current_name=name,
        parsed=parsed,
        edition_flags=flags,
    )


def enrich_from_abs_metadata(candidate: RenameCandidate) -> RenameCandidate:
    """Enrich candidate with ABS metadata.json if available.

    This is Stage 2.5 of the pipeline - ABS metadata is authoritative.

    Args:
        candidate: Candidate to enrich

    Returns:
        Updated candidate with ABS metadata
    """
    abs_meta = parse_abs_metadata(candidate.source_path)
    if not abs_meta:
        return candidate

    candidate = dataclasses.replace(candidate, abs_metadata=abs_meta)

    # If we have ASIN from metadata.json and candidate doesn't have one, use it
    if (
        abs_meta.asin
        and is_valid_asin(abs_meta.asin)
        and candidate.parsed
        and not candidate.parsed.asin
    ):
        # Update parsed with ASIN from metadata.json
        candidate.parsed = dataclasses.replace(candidate.parsed, asin=abs_meta.asin)
        candidate = dataclasses.replace(candidate, asin_source="abs_metadata.json")

    return candidate


def resolve_asin_cascade(
    candidate: RenameCandidate,
    abs_client: AbsClient | None = None,
    abs_search_confidence: float = 0.75,
) -> RenameCandidate:
    """Resolve ASIN using cascade: folder → files → metadata → mediainfo → ABS search.

    Args:
        candidate: Candidate needing ASIN resolution
        abs_client: Optional ABS client for search fallback
        abs_search_confidence: Minimum confidence for ABS search matches

    Returns:
        Updated candidate with resolved ASIN (or missing_asin status)
    """
    # If we already have ASIN from folder parse or ABS metadata, skip cascade
    if candidate.parsed and candidate.parsed.asin:
        if not candidate.asin_source:
            candidate = dataclasses.replace(candidate, asin_source="folder_name")
        return candidate

    # Phase 3+4: Local resolution (folder name, filenames, metadata.json, mediainfo)
    resolution = resolve_asin_from_folder_with_mediainfo(
        candidate.source_path,
        parsed_asin=candidate.parsed.asin if candidate.parsed else None,
    )

    if resolution.found and resolution.asin:
        # Update parsed with resolved ASIN
        if candidate.parsed:
            candidate.parsed = dataclasses.replace(candidate.parsed, asin=resolution.asin)
        return dataclasses.replace(candidate, asin_source=resolution.source)

    # Phase 5: ABS search (opt-in, requires abs_client)
    if abs_client and candidate.parsed:
        title = candidate.abs_metadata.title if candidate.abs_metadata else candidate.parsed.title
        author = None
        if candidate.abs_metadata and candidate.abs_metadata.authors:
            author = candidate.abs_metadata.authors[0]
        elif candidate.parsed.author:
            author = candidate.parsed.author

        if title:
            search_result = resolve_asin_via_abs_search(
                client=abs_client,
                title=title,
                author=author,
                confidence_threshold=abs_search_confidence,
            )
            if search_result.found and search_result.asin:
                candidate.parsed = dataclasses.replace(candidate.parsed, asin=search_result.asin)
                return dataclasses.replace(candidate, asin_source="abs_search")

    # No ASIN found
    return dataclasses.replace(candidate, status="missing_asin")


def detect_duplicates(candidates: list[RenameCandidate]) -> list[RenameCandidate]:
    """Mark candidates with duplicate ASINs.

    Args:
        candidates: List of candidates to check

    Returns:
        Updated list with duplicate_asin status on conflicts
    """
    # Group by ASIN
    asin_to_candidates: dict[str, list[int]] = {}
    for i, c in enumerate(candidates):
        if c.parsed and c.parsed.asin:
            asin = c.parsed.asin
            if asin not in asin_to_candidates:
                asin_to_candidates[asin] = []
            asin_to_candidates[asin].append(i)

    # Mark duplicates
    result = list(candidates)
    for asin, indices in asin_to_candidates.items():
        if len(indices) > 1:
            for idx in indices:
                result[idx] = dataclasses.replace(result[idx], status="duplicate_asin")
            logger.warning(
                f"Duplicate ASIN {asin} found in {len(indices)} folders: "
                f"{[candidates[i].current_name for i in indices]}"
            )

    return result


# =============================================================================
# Target Name Building
# =============================================================================


def compute_target_name(
    candidate: RenameCandidate,
    naming_config: NamingConfig | None = None,
) -> RenameCandidate:
    """Compute the target folder name using MAM naming schema.

    Args:
        candidate: Candidate to compute target for
        naming_config: Optional naming configuration

    Returns:
        Updated candidate with target_name set
    """
    # Skip if already processed (error, missing ASIN, etc.)
    if candidate.status not in ("needs_rename", "up_to_date"):
        return candidate

    # Need either parsed data or ABS metadata
    parsed = candidate.parsed
    abs_meta = candidate.abs_metadata

    if not parsed:
        return dataclasses.replace(
            candidate,
            status="error",
            error_message="Failed to parse folder name",
        )

    # Get ASIN (required)
    asin = parsed.asin
    if not asin:
        return dataclasses.replace(candidate, status="missing_asin")

    # Gather metadata - prefer ABS metadata, fallback to parsed
    series = abs_meta.series if abs_meta and abs_meta.series else parsed.series
    title = abs_meta.title if abs_meta and abs_meta.title else parsed.title
    year = str(abs_meta.year) if abs_meta and abs_meta.year else parsed.year

    # Author - prefer ABS metadata
    author = None
    if abs_meta and abs_meta.authors:
        author = abs_meta.authors[0]
    elif parsed.author:
        author = parsed.author

    # Volume number
    vol_num = None
    if abs_meta and abs_meta.series_position:
        vol_num = abs_meta.series_position
    elif parsed.series_position:
        vol_num = parsed.series_position

    # Format volume number
    vol_str = format_volume_number(vol_num) if vol_num else None

    # Ripper tag - preserve from original if present
    ripper_tag = parsed.ripper_tag

    # Build edition flags string
    edition_str = None
    if candidate.edition_flags:
        edition_str = ", ".join(candidate.edition_flags)

    # Build target name using existing function
    # Note: build_mam_folder_name doesn't support edition flags in middle,
    # so we'll need to inject them manually after author
    target = build_mam_folder_name(
        series=series,
        title=title,
        volume_number=vol_str.replace("vol_", "") if vol_str else None,
        year=year,
        author=author,
        asin=asin,
        ripper_tag=ripper_tag,
        naming_config=naming_config,
    )

    # Inject edition flags between author and ASIN if present
    if edition_str:
        # Find ASIN position and insert before it
        asin_pos = target.find("{ASIN.")
        if asin_pos > 0:
            # Insert edition flags before ASIN
            target = f"{target[:asin_pos]}({edition_str}) {target[asin_pos:]}"

    # Apply pathvalidate safety
    target = safe_dirname(target)

    # Check if rename is needed
    if target == candidate.current_name:
        return dataclasses.replace(candidate, target_name=target, status="up_to_date")

    # Check for suspicious changes (too different)
    if is_suspicious_change(candidate.current_name, target, threshold=30):
        logger.warning(
            f"Large change detected for {candidate.current_name}: "
            f"similarity={similarity_ratio(candidate.current_name, target):.1f}%"
        )

    return dataclasses.replace(candidate, target_name=target)


def check_target_exists(
    candidates: list[RenameCandidate],
) -> list[RenameCandidate]:
    """Check if any target names already exist (name collision).

    Args:
        candidates: List of candidates with computed target names

    Returns:
        Updated list with target_exists status on collisions
    """
    result = list(candidates)

    for i, c in enumerate(result):
        if c.status != "needs_rename" or not c.target_name:
            continue

        target_path = c.source_path.parent / c.target_name

        # Check if target path exists and is different from source
        if target_path.exists() and target_path != c.source_path:
            result[i] = dataclasses.replace(c, status="target_exists")

    return result


# =============================================================================
# Rename Execution
# =============================================================================

# Files to skip when renaming files inside folder
SKIP_FILES = frozenset({"cover.jpg", "cover.png", "metadata.json", "desc.txt", "reader.txt"})


def _rename_files_inside(target_path: Path, new_stem: str) -> list[str]:
    """Rename media files inside folder to match new folder name.

    Preserves cover.jpg, metadata.json and other sidecar files.
    For multi-file layouts (multiple audio files), appends a numeric suffix
    to prevent collisions.

    Args:
        target_path: The renamed folder path
        new_stem: New filename stem (folder name)

    Returns:
        List of original filenames that were renamed
    """
    renamed: list[str] = []

    try:
        # Collect all media files (non-sidecar files)
        media_files = [
            f for f in target_path.iterdir() if f.is_file() and f.name.lower() not in SKIP_FILES
        ]

        # Sort by name for deterministic ordering
        media_files.sort(key=lambda f: f.name)

        # Count actual audio files to determine if multi-file layout
        audio_file_count = sum(1 for f in media_files if f.suffix.lower() in AUDIO_EXTS)

        # Use suffix only for true multi-file audiobooks (multiple audio files)
        use_suffix = audio_file_count > 1

        for idx, f in enumerate(media_files, start=1):
            if use_suffix:
                # Multi-file: "Folder Name - Part 01.m4b", "Folder Name - Part 02.m4b"
                new_name = f"{new_stem} - Part {idx:02d}{f.suffix}"
            else:
                # Single file: "Folder Name.m4b"
                new_name = f"{new_stem}{f.suffix}"

            # Skip if already named correctly
            if f.name == new_name:
                continue

            try:
                f.rename(f.with_name(new_name))
                renamed.append(f.name)
                logger.debug(f"Renamed file: {f.name} → {new_name}")
            except OSError as e:
                logger.warning(f"Failed to rename file {f.name}: {e}")
    except PermissionError as e:
        logger.warning(f"Cannot read folder {target_path}: {e}")

    return renamed


def rename_folder(
    candidate: RenameCandidate,
    dry_run: bool = False,
    force: bool = False,
) -> RenameResult:
    """Execute folder rename.

    Media files inside the folder are automatically renamed to match the new
    folder name. Sidecar files (cover.jpg, metadata.json, etc.) are preserved.

    Args:
        candidate: Candidate to rename
        dry_run: If True, don't actually rename
        force: If True, rename files inside even when folder is up-to-date

    Returns:
        RenameResult with operation status
    """
    # Special handling for force mode with up-to-date folders
    if force and candidate.status == "up_to_date" and candidate.target_name:
        # Folder is already correct, but force rename files inside
        if dry_run:
            return RenameResult(
                source_path=candidate.source_path,
                target_path=candidate.source_path,
                status="dry_run",
            )

        try:
            # Rename files inside using current folder name
            files_renamed = _rename_files_inside(candidate.source_path, candidate.target_name)
            return RenameResult(
                source_path=candidate.source_path,
                target_path=candidate.source_path,
                status="success",
                files_renamed=files_renamed if files_renamed else None,
            )
        except OSError as e:
            return RenameResult(
                source_path=candidate.source_path,
                target_path=candidate.source_path,
                status="failed",
                error=str(e),
            )

    if candidate.status != "needs_rename":
        return RenameResult(
            source_path=candidate.source_path,
            target_path=None,
            status="skipped",
            error=f"Status: {candidate.status}",
        )

    if not candidate.target_name:
        return RenameResult(
            source_path=candidate.source_path,
            target_path=None,
            status="failed",
            error="No target name computed",
        )

    target_path = candidate.source_path.parent / candidate.target_name

    if dry_run:
        return RenameResult(
            source_path=candidate.source_path,
            target_path=target_path,
            status="dry_run",
        )

    try:
        candidate.source_path.rename(target_path)

        # Always rename media files inside the folder to match new folder name
        files_renamed = _rename_files_inside(target_path, candidate.target_name)

        return RenameResult(
            source_path=candidate.source_path,
            target_path=target_path,
            status="success",
            files_renamed=files_renamed if files_renamed else None,
        )
    except OSError as e:
        return RenameResult(
            source_path=candidate.source_path,
            target_path=target_path,
            status="failed",
            error=str(e),
        )


# =============================================================================
# Pipeline Orchestration
# =============================================================================


def run_rename_pipeline(
    source_dir: Path,
    *,
    pattern: str = "*",
    fetch_metadata: bool = False,  # Reserved for future Audnex integration
    abs_client: AbsClient | None = None,
    abs_search_confidence: float = 0.75,
    naming_config: NamingConfig | None = None,
    dry_run: bool = False,
    interactive: bool = False,
    force: bool = False,
) -> tuple[list[RenameResult], RenameSummary, list[RenameCandidate]]:
    """Run the full rename pipeline.

    Media files inside renamed folders are automatically renamed to match the
    new folder name. Sidecar files (cover.jpg, metadata.json, etc.) are preserved.

    Args:
        source_dir: Directory to scan for folders to rename
        pattern: Glob pattern to filter folders
        fetch_metadata: Reserved for future Audnex metadata integration (not yet implemented)
        abs_client: Optional ABS client for search fallback
        abs_search_confidence: Minimum confidence for ABS search
        naming_config: Optional naming configuration
        dry_run: If True, don't actually rename
        interactive: If True, prompt for each rename
        force: If True, rename files inside even when folder names are up-to-date

    Returns:
        Tuple of (list of results, summary, list of candidates)
    """
    # Note: fetch_metadata is reserved for future Audnex integration
    _ = fetch_metadata  # Suppress unused parameter warning

    results: list[RenameResult] = []
    summary = RenameSummary()

    # Stage 1: Discovery (use spinner - count unknown during walk)
    print_step(1, 6, "Discovering folders")
    with progress_context("Scanning directories", total=None) as (progress, task):
        folders = discover_rename_candidates(source_dir, pattern)
        progress.update(task, description=f"Found {len(folders)} folders")
    summary.total_candidates = len(folders)
    logger.info(f"Found {len(folders)} folders to process")

    if not folders:
        return results, summary, []

    # Determine worker count (I/O bound, so more workers help)
    max_workers = min(32, (os.cpu_count() or 4) * 4)

    # Stage 2: Parse existing names (parallel - fast but many items)
    print_step(2, 6, "Parsing folder names")
    candidates: list[RenameCandidate] = []
    with (
        progress_context("Parsing names", total=len(folders)) as (progress, task),
        ThreadPoolExecutor(max_workers=max_workers) as executor,
    ):
        futures = {executor.submit(parse_candidate, f): i for i, f in enumerate(folders)}
        results_map: dict[int, RenameCandidate] = {}
        for future in as_completed(futures):
            idx = futures[future]
            results_map[idx] = future.result()
            progress.update(task, advance=1)
        candidates = [results_map[i] for i in range(len(folders))]

    # Stage 2.5: Enrich with ABS metadata (parallel - reads metadata.json)
    print_step(3, 6, "Reading ABS metadata")
    with (
        progress_context("Reading metadata", total=len(candidates)) as (progress, task),
        ThreadPoolExecutor(max_workers=max_workers) as executor,
    ):
        futures = {
            executor.submit(enrich_from_abs_metadata, c): i for i, c in enumerate(candidates)
        }
        results_map = {}
        for future in as_completed(futures):
            idx = futures[future]
            results_map[idx] = future.result()
            progress.update(task, advance=1)
        candidates = [results_map[i] for i in range(len(candidates))]

    # Stage 3: ASIN resolution (parallel - may call mediainfo subprocess)
    print_step(4, 6, "Resolving ASINs")

    def resolve_one(c: RenameCandidate) -> RenameCandidate:
        return resolve_asin_cascade(c, abs_client, abs_search_confidence)

    with (
        progress_context("Resolving ASINs", total=len(candidates)) as (progress, task),
        ThreadPoolExecutor(max_workers=max_workers) as executor,
    ):
        futures = {executor.submit(resolve_one, c): i for i, c in enumerate(candidates)}
        results_map = {}
        for future in as_completed(futures):
            idx = futures[future]
            results_map[idx] = future.result()
            progress.update(task, advance=1)
        candidates = [results_map[i] for i in range(len(candidates))]

    # Stage 4: Duplicate detection
    candidates = detect_duplicates(candidates)

    # Stage 5: Build target names
    print_step(5, 6, "Computing target names")
    candidates = [compute_target_name(c, naming_config) for c in candidates]
    candidates = check_target_exists(candidates)

    # Stage 6: Execute renames
    print_step(6, 6, "Renaming folders" if not dry_run else "Previewing renames")

    for candidate in candidates:
        # Interactive mode
        should_prompt = interactive and (
            (candidate.status == "needs_rename" and candidate.target_name)
            or (force and candidate.status == "up_to_date" and candidate.target_name)
        )

        if should_prompt:
            if candidate.status == "up_to_date":
                print(f"\n{candidate.current_name}")
                print("  → (rename files inside only)")
            else:
                print(f"\n{candidate.current_name}")
                print(f"  → {candidate.target_name}")

            if not confirm("Rename this folder?"):
                result = RenameResult(
                    source_path=candidate.source_path,
                    target_path=None,
                    status="skipped",
                    error="User declined",
                )
                results.append(result)
                continue

        result = rename_folder(candidate, dry_run=dry_run, force=force)
        results.append(result)

        # Update summary
        match result.status:
            case "success" | "dry_run":
                summary.renamed += 1
            case "skipped":
                if candidate.status == "up_to_date":
                    summary.skipped_up_to_date += 1
                elif candidate.status == "missing_asin":
                    summary.skipped_missing_asin += 1
                elif candidate.status == "duplicate_asin":
                    summary.skipped_duplicate_asin += 1
                elif candidate.status == "target_exists":
                    summary.skipped_target_exists += 1
            case "failed":
                summary.errors += 1

    # Print summary
    if dry_run:
        print_dry_run(f"Would rename {summary.renamed} folders")
    else:
        print_success(f"Renamed {summary.renamed} folders")

    if summary.skipped_up_to_date:
        logger.info(f"Already up-to-date: {summary.skipped_up_to_date}")
    if summary.skipped_missing_asin:
        print_warning(f"Missing ASIN: {summary.skipped_missing_asin}")
    if summary.skipped_duplicate_asin:
        print_warning(f"Duplicate ASIN conflicts: {summary.skipped_duplicate_asin}")
    if summary.skipped_target_exists:
        print_warning(f"Target exists: {summary.skipped_target_exists}")
    if summary.errors:
        print_warning(f"Errors: {summary.errors}")

    return results, summary, candidates


# =============================================================================
# Report Generation
# =============================================================================


def generate_report(
    results: list[RenameResult],
    candidates: list[RenameCandidate],
    summary: RenameSummary,
    output_path: Path,
    *,
    source_dir: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Generate JSON report of rename operations.

    Args:
        results: List of rename results
        candidates: List of candidates (for ASIN info)
        summary: Summary statistics
        output_path: Path to write JSON report
        source_dir: Source directory scanned
        dry_run: Whether this was a dry run
    """
    from datetime import UTC, datetime

    # Collect duplicate ASIN groups for debugging
    asin_to_folders: dict[str, list[str]] = {}
    for candidate in candidates:
        if candidate.parsed and candidate.parsed.asin:
            asin = candidate.parsed.asin
            if asin not in asin_to_folders:
                asin_to_folders[asin] = []
            asin_to_folders[asin].append(candidate.current_name)
    duplicate_groups = {k: v for k, v in asin_to_folders.items() if len(v) > 1}

    # Build results with full candidate info for debugging
    result_items = []
    for result, candidate in zip(results, candidates, strict=False):
        # Calculate similarity if we have both names
        # similarity_ratio already returns 0-100
        sim_score = None
        if candidate.target_name and candidate.current_name:
            sim_score = round(similarity_ratio(candidate.current_name, candidate.target_name), 1)

        item: dict[str, object] = {
            "source_path": str(result.source_path),
            "source_name": result.source_path.name,
            "target_name": result.target_path.name if result.target_path else None,
            "target_path": str(result.target_path) if result.target_path else None,
            "status": result.status,
            "error": result.error,
            "files_renamed": result.files_renamed,
            # ASIN info
            "asin": candidate.parsed.asin if candidate.parsed else None,
            "asin_source": candidate.asin_source,
            # Parsed metadata for debugging
            "parsed": {
                "author": candidate.parsed.author if candidate.parsed else None,
                "series": candidate.parsed.series if candidate.parsed else None,
                "series_position": candidate.parsed.series_position if candidate.parsed else None,
                "title": candidate.parsed.title if candidate.parsed else None,
                "year": candidate.parsed.year if candidate.parsed else None,
            }
            if candidate.parsed
            else None,
            # ABS metadata if available
            "abs_metadata": {
                "title": candidate.abs_metadata.title if candidate.abs_metadata else None,
                "authors": candidate.abs_metadata.authors if candidate.abs_metadata else None,
                "series": candidate.abs_metadata.series if candidate.abs_metadata else None,
            }
            if candidate.abs_metadata
            else None,
            # Warnings for debugging
            "similarity_percent": sim_score,
            "is_suspicious_change": sim_score is not None and sim_score < 30,
        }
        result_items.append(item)

    # Separate results by status for easier review
    by_status: dict[str, list[dict[str, object]]] = {}
    for item in result_items:
        status = str(item["status"])
        if status not in by_status:
            by_status[status] = []
        by_status[status].append(item)

    # Find suspicious changes (low similarity)
    suspicious = [r for r in result_items if r.get("is_suspicious_change")]

    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "source_dir": str(source_dir) if source_dir else None,
        "dry_run": dry_run,
        "summary": {
            "total": summary.total_candidates,
            "renamed": summary.renamed,
            "skipped_up_to_date": summary.skipped_up_to_date,
            "skipped_missing_asin": summary.skipped_missing_asin,
            "skipped_duplicate_asin": summary.skipped_duplicate_asin,
            "skipped_target_exists": summary.skipped_target_exists,
            "errors": summary.errors,
        },
        # Debugging sections
        "warnings": {
            "suspicious_changes_count": len(suspicious),
            "suspicious_changes": suspicious,
            "duplicate_asin_groups": duplicate_groups,
        },
        # Results grouped by status
        "by_status": by_status,
        # Full results list
        "results": result_items,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    logger.info(f"Report written to {output_path}")

    return report


def generate_html_report(
    report_data: dict[str, Any],
    output_path: Path,
) -> None:
    """Generate an HTML report from the JSON report data.

    Uses Jinja2 templating to create a visually appealing HTML report
    with collapsible sections, search/filter, and status indicators.

    Args:
        report_data: The report dictionary (from generate_report)
        output_path: Path to write HTML report
    """
    from importlib.resources import files

    try:
        from jinja2 import Environment, FileSystemLoader
    except ImportError:
        logger.warning("jinja2 not installed, skipping HTML report generation")
        return

    # Load template
    template_dir = files("shelfr.templates")
    # Get the actual path for FileSystemLoader
    template_path = Path(str(template_dir))

    if not template_path.exists():
        # Fallback: try relative to this file
        template_path = Path(__file__).parent.parent / "templates"

    if not template_path.exists():
        logger.warning(f"Template directory not found: {template_path}")
        return

    env = Environment(
        loader=FileSystemLoader(str(template_path)),
        autoescape=True,
    )

    # Add custom filter to classify duplicate types
    def classify_duplicate(folders: list[str]) -> dict[str, str]:
        """Classify the type of duplicate ASIN."""
        if any("xHE" in f or "[126]" in f for f in folders):
            return {"class": "codec", "label": "Codec Variant"}
        if any("Dolby Atmos" in f for f in folders):
            return {"class": "edition", "label": "Edition Variant"}
        if any("[H2OKing]" in f for f in folders) and any("[H2OKing]" not in f for f in folders):
            return {"class": "ripper-tag", "label": "Ripper Tag"}
        # Check for different volume numbers (wrong ASIN)
        vol_numbers = set()
        for f in folders:
            match = re.search(r"vol[_\s]*(\d+)", f, re.IGNORECASE)
            if match:
                vol_numbers.add(match.group(1))
        if len(vol_numbers) > 1:
            return {"class": "wrong-asin", "label": "WRONG ASIN"}
        return {"class": "", "label": "Duplicate"}

    env.globals["classify_duplicate"] = classify_duplicate  # pyright: ignore[reportArgumentType]

    try:
        template = env.get_template("rename_report.html")
    except Exception as e:
        logger.warning(f"Failed to load HTML template: {e}")
        return

    # Render template
    html_content = template.render(
        timestamp=report_data.get("timestamp", ""),
        source_dir=report_data.get("source_dir", ""),
        dry_run=report_data.get("dry_run", False),
        summary=report_data.get("summary", {}),
        warnings=report_data.get("warnings", {}),
        by_status=report_data.get("by_status", {}),
        results=report_data.get("results", []),
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    logger.info(f"HTML report written to {output_path}")
