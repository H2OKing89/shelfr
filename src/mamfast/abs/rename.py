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
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, ValidationError

from mamfast.abs.asin import (
    is_valid_asin,
    resolve_asin_from_folder_with_mediainfo,
    resolve_asin_via_abs_search,
)
from mamfast.abs.importer import ParsedFolderName, parse_mam_folder_name
from mamfast.console import (
    confirm,
    print_dry_run,
    print_step,
    print_success,
    print_warning,
)
from mamfast.utils.fuzzy import is_suspicious_change, similarity_ratio
from mamfast.utils.naming import build_mam_folder_name, format_volume_number
from mamfast.utils.paths import safe_dirname

if TYPE_CHECKING:
    from mamfast.abs.client import AbsClient
    from mamfast.config import NamingConfig
    from mamfast.models import NormalizedBook

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
# Pydantic Schemas
# =============================================================================


class AbsMetadataSchema(BaseModel):
    """Pydantic schema for ABS metadata.json validation.

    Audiobookshelf stores a metadata.json sidecar in each book folder
    with authoritative metadata including ASIN even when not in folder name.
    """

    title: str | None = None
    subtitle: str | None = None
    authors: list[str] = Field(default_factory=list)
    narrators: list[str] = Field(default_factory=list)
    series: list[str] = Field(default_factory=list)  # ["Series Name #N"]
    genres: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    publishedYear: int | str | None = None  # noqa: N815 - ABS uses camelCase
    publisher: str | None = None
    asin: str | None = None
    isbn: str | None = None
    language: str | None = None
    explicit: bool = False
    abridged: bool = False
    description: str | None = None

    model_config = {"extra": "ignore"}  # ABS may add new fields


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

        # Validate with Pydantic
        schema = AbsMetadataSchema.model_validate(data)

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

        # Parse year (can be int or string)
        year = None
        if schema.publishedYear:
            with contextlib.suppress(ValueError, TypeError):
                year = int(schema.publishedYear)

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


def rename_folder(
    candidate: RenameCandidate,
    dry_run: bool = False,
) -> RenameResult:
    """Execute folder rename.

    Args:
        candidate: Candidate to rename
        dry_run: If True, don't actually rename

    Returns:
        RenameResult with operation status
    """
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
        return RenameResult(
            source_path=candidate.source_path,
            target_path=target_path,
            status="success",
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
    fetch_metadata: bool = False,
    abs_client: AbsClient | None = None,
    abs_search_confidence: float = 0.75,
    naming_config: NamingConfig | None = None,
    dry_run: bool = False,
    interactive: bool = False,
) -> tuple[list[RenameResult], RenameSummary]:
    """Run the full rename pipeline.

    Args:
        source_dir: Directory to scan for folders to rename
        pattern: Glob pattern to filter folders
        fetch_metadata: Whether to fetch metadata from Audnex
        abs_client: Optional ABS client for search fallback
        abs_search_confidence: Minimum confidence for ABS search
        naming_config: Optional naming configuration
        dry_run: If True, don't actually rename
        interactive: If True, prompt for each rename

    Returns:
        Tuple of (list of results, summary)
    """
    results: list[RenameResult] = []
    summary = RenameSummary()

    # Stage 1: Discovery
    print_step(1, 6, "Discovering folders")
    folders = discover_rename_candidates(source_dir, pattern)
    summary.total_candidates = len(folders)
    logger.info(f"Found {len(folders)} folders to process")

    if not folders:
        return results, summary

    # Stage 2: Parse existing names
    print_step(2, 6, "Parsing folder names")
    candidates = [parse_candidate(f) for f in folders]

    # Stage 2.5: Enrich with ABS metadata
    print_step(3, 6, "Reading ABS metadata")
    candidates = [enrich_from_abs_metadata(c) for c in candidates]

    # Stage 3: ASIN resolution
    print_step(4, 6, "Resolving ASINs")
    candidates = [resolve_asin_cascade(c, abs_client, abs_search_confidence) for c in candidates]

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
        if interactive and candidate.status == "needs_rename" and candidate.target_name:
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

        result = rename_folder(candidate, dry_run=dry_run)
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

    return results, summary


# =============================================================================
# Report Generation
# =============================================================================


def generate_report(
    results: list[RenameResult],
    summary: RenameSummary,
    output_path: Path,
) -> None:
    """Generate JSON report of rename operations.

    Args:
        results: List of rename results
        summary: Summary statistics
        output_path: Path to write JSON report
    """
    report = {
        "summary": {
            "total": summary.total_candidates,
            "renamed": summary.renamed,
            "skipped_up_to_date": summary.skipped_up_to_date,
            "skipped_missing_asin": summary.skipped_missing_asin,
            "skipped_duplicate_asin": summary.skipped_duplicate_asin,
            "skipped_target_exists": summary.skipped_target_exists,
            "errors": summary.errors,
        },
        "results": [
            {
                "source": str(r.source_path),
                "target": str(r.target_path) if r.target_path else None,
                "status": r.status,
                "error": r.error,
            }
            for r in results
        ],
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    logger.info(f"Report written to {output_path}")
