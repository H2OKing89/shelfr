"""Import audiobooks from staging to Audiobookshelf library.

Handles the final step of the MAM workflow: moving staged audiobooks
to the ABS library structure while preserving hardlinks to seed folder.

Uses in-memory ASIN index (from ABS API) for duplicate detection instead
of SQLite for simplicity and always-fresh data.

See docs/UNKNOWN_ASIN_HANDLING.md for unknown ASIN handling design (Phase 1+).
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from mamfast.abs.asin import (
    AsinEntry,
    asin_exists,
    extract_asin,
    normalize_asin_to_preferred_region,
    resolve_asin_from_folder_with_mediainfo,
    resolve_asin_via_abs_search,
)
from mamfast.abs.cleanup import (
    CLEANUP_ELIGIBLE_STATUSES,
    CleanupPrefs,
    CleanupResult,
    CleanupStrategy,
    cleanup_source,
)
from mamfast.abs.paths import PathMapper
from mamfast.abs.trumping import (
    TrumpDecision,
    TrumpPrefs,
    adjust_for_aggressiveness,
    archive_existing,
    decide_trump,
    extract_trumpable_meta,
    is_multi_file_layout,
)
from mamfast.config import ConfigurationError
from mamfast.metadata import fetch_audnex_book
from mamfast.utils.naming import build_mam_file_name, build_mam_folder_name, clean_series_name

if TYPE_CHECKING:
    from mamfast.abs.client import AbsClient


# ─────────────────────────────────────────────────────────────────────────────
# Module-level cache for format indicators loaded from naming.json
# ─────────────────────────────────────────────────────────────────────────────
_FORMAT_INDICATORS: list[str] | None = None

# Fallback format indicators if naming.json is not available
_DEFAULT_FORMAT_INDICATORS = [
    "(Light Novel)",
    "(light novel)",
    "Light Novel",
    "(Manga)",
    "(Graphic Novel)",
    "(Unabridged)",
    "Unabridged",
    "(Audiobook)",
    "Audiobook",
]


def _get_format_indicators() -> list[str]:
    """Load format indicators from naming.json (cached).

    Reads the format_indicators.phrases from config/naming.json.
    Falls back to hardcoded defaults if naming.json is unavailable.
    """
    global _FORMAT_INDICATORS
    if _FORMAT_INDICATORS is not None:
        return _FORMAT_INDICATORS

    indicators: list[str] = []
    try:
        # Try to find naming.json relative to this file
        config_dir = Path(__file__).parent.parent.parent.parent / "config"
        naming_path = config_dir / "naming.json"

        if naming_path.exists():
            with open(naming_path, encoding="utf-8") as f:
                data = json.load(f)
            phrases = data.get("format_indicators", {}).get("phrases", [])
            if phrases:
                indicators = phrases
    except Exception:
        pass  # Fall through to defaults

    if not indicators:
        indicators = _DEFAULT_FORMAT_INDICATORS.copy()

    _FORMAT_INDICATORS = indicators
    return _FORMAT_INDICATORS


logger = logging.getLogger(__name__)

# Audio extensions recognized by the importer
AUDIO_EXTENSIONS = frozenset({".m4b", ".m4a", ".mp3", ".ogg", ".flac", ".opus", ".wav"})


class UnknownAsinPolicy(str, Enum):
    """Policy for handling audiobooks without ASIN."""

    IMPORT = "import"  # Default - import to Unknown/ or Author/ (homebrew)
    QUARANTINE = "quarantine"  # Move to quarantine folder for manual review
    SKIP = "skip"  # Leave in staging, log warning only


class UnknownAsinContentType(str, Enum):
    """Classification of why ASIN is unknown."""

    MISSING_ASIN = "missing_asin"  # Likely Audible content, ASIN just not found yet
    HOMEBREW = "homebrew"  # No ASIN expected (self-pub, personal rips, podcasts)


class ImportError(Exception):
    """Error during import operation."""


class FilesystemMismatchError(ImportError):
    """Staging and library are on different filesystems."""


class DuplicateError(ImportError):
    """Book already exists in library."""

    def __init__(self, asin: str, existing_path: str) -> None:
        self.asin = asin
        self.existing_path = existing_path
        super().__init__(f"ASIN {asin} already exists at {existing_path}")


@dataclass
class ImportResult:
    """Result of a single import operation."""

    staging_path: Path
    target_path: Path | None
    asin: str | None
    status: str  # "success", "skipped", "failed", "duplicate"
    error: str | None = None
    parsed: ParsedFolderName | None = None  # Enriched parsed data for display
    cleanup: CleanupResult | None = None  # Post-import cleanup result


@dataclass
class BatchImportResult:
    """Result of a batch import operation."""

    results: list[ImportResult] = field(default_factory=list)
    success_count: int = 0
    skipped_count: int = 0
    duplicate_count: int = 0
    failed_count: int = 0
    # Trumping statistics
    trump_replaced_count: int = 0  # Existing archived, new imported
    trump_kept_existing_count: int = 0  # No improvement, kept existing
    trump_rejected_count: int = 0  # Incoming was worse
    # Cleanup statistics
    cleanup_success_count: int = 0
    cleanup_skipped_count: int = 0
    cleanup_failed_count: int = 0

    def add(self, result: ImportResult) -> None:
        """Add a result and update counts."""
        self.results.append(result)
        if result.status == "success":
            self.success_count += 1
        elif result.status == "skipped":
            self.skipped_count += 1
        elif result.status == "duplicate":
            self.duplicate_count += 1
        elif result.status == "failed":
            self.failed_count += 1
        elif result.status == "trump_replaced":
            self.trump_replaced_count += 1
            self.success_count += 1  # Also count as success
        elif result.status == "trump_kept_existing":
            self.trump_kept_existing_count += 1
            self.skipped_count += 1  # Also count as skipped
        elif result.status == "trump_rejected":
            self.trump_rejected_count += 1
            self.skipped_count += 1  # Also count as skipped

        # Track cleanup statistics
        if result.cleanup is not None:
            if result.cleanup.status == "success":
                self.cleanup_success_count += 1
            elif result.cleanup.status == "skipped":
                self.cleanup_skipped_count += 1
            elif result.cleanup.status == "failed":
                self.cleanup_failed_count += 1


@dataclass
class UnknownAsinContext:
    """Context for handling audiobooks without ASIN.

    Captures both the content type (why is ASIN unknown?) and structural
    information (how many files?) for routing decisions.
    """

    folder: Path
    parsed: ParsedFolderName
    content_type: UnknownAsinContentType
    file_count: int
    original_folder_name: str  # For collision-safe destination naming

    @property
    def is_multi_file(self) -> bool:
        """True if folder contains multiple audio files."""
        return self.file_count > 1


@dataclass
class ParsedFolderName:
    """Parsed components from MAM-style folder name."""

    author: str
    title: str
    series: str | None
    series_position: str | None
    asin: str | None
    year: str | None
    narrator: str | None
    ripper_tag: str | None
    is_standalone: bool  # True if no series info


def parse_mam_folder_name(folder_name: str) -> ParsedFolderName:
    """Parse MAM-compliant folder name into components.

    Expected formats:
    - Series: "Author - Series vol_NN - Title (YYYY) (Narrator) {ripper_tag} [ASIN.B0xxx]"
    - Standalone: "Author - Title (YYYY) (Narrator) {ripper_tag} [ASIN.B0xxx]"

    Args:
        folder_name: Folder name to parse

    Returns:
        ParsedFolderName with extracted components

    Note:
        This function is lenient and will always return a ParsedFolderName,
        even if parsing fails (fields may be set to "Unknown" or None).
    """
    # Try to extract ASIN first (multiple formats supported)
    asin = extract_asin(folder_name)

    # Strip format indicators BEFORE parsing to avoid "(Light Novel)" etc. being
    # misidentified as author in Libation-style folder names
    # Format indicators are loaded from naming.json (cached) with fallback defaults
    clean_folder = folder_name
    for indicator in _get_format_indicators():
        clean_folder = clean_folder.replace(indicator, "").strip()
    # Collapse multiple spaces
    clean_folder = re.sub(r"\s{2,}", " ", clean_folder).strip()

    # Extract components using patterns
    # Pattern parts:
    # - Author at start (before first " - ")
    # - Optional series with vol_XX or #XX
    # - Title
    # - Optional year in parentheses
    # - Optional narrator in parentheses
    # - Optional ripper tag in braces
    # - Optional ASIN in brackets

    # Strip ASIN markers from ANYWHERE in the string (not just end)
    # This handles cases like "Title {ASIN.B0xxx} [RipperTag]" where
    # ripper tag comes after ASIN
    clean_name = re.sub(r"\s*\{ASIN\.[A-Z0-9]+\}\s*", " ", clean_folder)
    clean_name = re.sub(r"\s*\[ASIN\.[A-Z0-9]+\]\s*", " ", clean_name)
    clean_name = re.sub(r"\s*\[B0[A-Z0-9]{8,9}\]\s*", " ", clean_name)
    # Collapse multiple spaces after ASIN removal
    clean_name = re.sub(r"\s{2,}", " ", clean_name).strip()

    # Extract ripper tag if present - can be [Tag] or {Tag} format
    ripper_match = re.search(r"\[([^\]]+)\]\s*$", clean_name)
    if not ripper_match:
        ripper_match = re.search(r"\{([^}]+)\}\s*$", clean_name)
    ripper_tag = ripper_match.group(1) if ripper_match else None
    if ripper_match:
        clean_name = clean_name[: ripper_match.start()].strip()

    # Extract narrator if present (e.g., (Narrator Name))
    # This is typically the last parenthetical that's not a year
    narrator = None
    year = None

    # Find all parentheticals from the end
    paren_matches = list(re.finditer(r"\(([^)]+)\)", clean_name))
    for match in reversed(paren_matches):
        content = match.group(1)
        if re.match(r"^\d{4}$", content):
            year = content
        elif narrator is None and not re.match(r"^\d{4}$", content):
            narrator = content
        if year and narrator:
            break

    # Remove specific parentheticals by position (from end to preserve indices)
    # Only remove the last occurrence of each to avoid unintended replacements
    remove_spans: list[tuple[int, int]] = []
    if narrator:
        for match in reversed(paren_matches):
            if match.group(1) == narrator:
                remove_spans.append((match.start(), match.end()))
                break
    if year:
        for match in reversed(paren_matches):
            if match.group(1) == year:
                remove_spans.append((match.start(), match.end()))
                break
    # Remove spans from the string (sort by start, process from end to preserve indices)
    if remove_spans:
        remove_spans.sort(reverse=True)  # Process from end first
        for start, end in remove_spans:
            clean_name = clean_name[:start] + clean_name[end:]
        clean_name = clean_name.strip()

    # Split by " - " to get author and rest
    parts = clean_name.split(" - ", 1)
    if len(parts) < 2:
        # No separator found - this is likely Libation format: "Title vol_XX ... "
        # Try to extract series/volume from the title
        title = clean_name

        # Look for vol_XX or vol.XX pattern in title
        vol_match = re.search(r"\bvol[_.]?\s*(\d+)\b", title, re.IGNORECASE)
        if vol_match:
            series_position = vol_match.group(1)
            # Extract series name (everything before vol_XX pattern)
            vol_pattern_match = re.search(
                r"^(.+?)\s+(?:Vol\.?\s*\d+\s+)?vol[_.]?\s*\d+", title, re.IGNORECASE
            )
            if vol_pattern_match:
                series = vol_pattern_match.group(1).strip()
                # Clean "Vol. X" from series name if present
                series = re.sub(r"\s+Vol\.?\s*\d+\s*$", "", series, flags=re.IGNORECASE)
            else:
                series = None
            is_standalone = False
        else:
            series = None
            series_position = None
            is_standalone = True

        # narrator field actually contains the author in Libation format
        author = narrator if narrator else "Unknown"
        narrator = None  # Reset narrator since it was misidentified

        return ParsedFolderName(
            author=author,
            title=title,
            series=series,
            series_position=series_position,
            asin=asin,
            year=year,
            narrator=narrator,
            ripper_tag=ripper_tag,
            is_standalone=is_standalone,
        )

    author = parts[0].strip()
    rest = parts[1].strip()

    # Check for series pattern: "Series vol_XX - Title" or "Series #XX - Title"
    series_match = re.match(
        r"^(.+?)\s+(?:vol[_.]?|#)\s*(\d+(?:\.\d+)?)\s+-\s+(.+)$",
        rest,
        re.IGNORECASE,
    )

    if series_match:
        series = series_match.group(1).strip()
        series_position = series_match.group(2)
        title = series_match.group(3).strip()
        is_standalone = False
    else:
        # No series pattern - treat rest as title
        series = None
        series_position = None
        title = rest
        is_standalone = True

    return ParsedFolderName(
        author=author,
        title=title,
        series=series,
        series_position=series_position,
        asin=asin,
        year=year,
        narrator=narrator,
        ripper_tag=ripper_tag,
        is_standalone=is_standalone,
    )


def enrich_from_audnex(
    parsed: ParsedFolderName, asin: str
) -> tuple[ParsedFolderName, dict[str, Any] | None, str | None]:
    """Enrich parsed folder data with Audnex metadata.

    When we resolve an ASIN (from mediainfo or folder), fetch Audnex metadata
    to fill in missing author/series/position. This provides accurate metadata
    even for poorly-named folders.

    Uses normalize_audnex_book() from naming.py for consistent series extraction
    across all pipelines. That function handles:
    - seriesPrimary (source of truth)
    - Subtitle fallback ("Series Name, Book 5")
    - Title fallback ("A Most Unlikely Hero, Volume 8")
    - Series name cleaning (removes " Series" suffix, etc.)

    Args:
        parsed: ParsedFolderName from parse_mam_folder_name()
        asin: Resolved ASIN to look up

    Returns:
        Tuple of (ParsedFolderName with enriched data, Audnex data dict, region).
        Audnex data and region are None if Audnex lookup failed.
    """
    from mamfast.utils.naming import normalize_audnex_book

    try:
        audnex_data, audnex_region = fetch_audnex_book(asin)
    except Exception as e:
        logger.debug("Failed to fetch Audnex data for %s: %s", asin, e)
        return parsed, None, None  # Return None for audnex_data and region on error

    if not audnex_data:
        logger.debug("No Audnex data found for ASIN %s", asin)
        return parsed, None, None  # Return None for audnex_data and region when not found

    # Use the naming module's normalizer for consistent series extraction
    normalized = normalize_audnex_book(audnex_data)

    # Extract author from Audnex - ALWAYS prefer Audnex author over parsed author
    # This handles Libation format where title/author are swapped ("Title - Author")
    # versus MAM format ("Author - Title")
    authors = audnex_data.get("authors", [])
    if authors:
        first_author = authors[0].get("name", "")
        if first_author and first_author != parsed.author:
            logger.info(
                "Enriched author from Audnex: %s%s",
                first_author,
                (
                    f" (was: {parsed.author})"
                    if parsed.author and parsed.author != "Unknown"
                    else ""
                ),
            )
            parsed.author = first_author

    # Apply series info from normalized data
    # ALWAYS prefer Audnex series over parsed series - Audnex is authoritative
    # Parsed series may be incorrect (e.g., "The Rising of the Shield Hero Volume 04"
    # instead of "Rising of the Shield Hero")
    if normalized.series_name:
        if parsed.series != normalized.series_name:
            logger.info(
                "Enriched series from Audnex: %s%s",
                normalized.series_name,
                f" (was: {parsed.series})" if parsed.series else "",
            )
        parsed.series = normalized.series_name
        parsed.is_standalone = False

    if normalized.series_position:
        if parsed.series_position != normalized.series_position:
            logger.info(
                "Enriched series position from Audnex: %s%s",
                normalized.series_position,
                f" (was: {parsed.series_position})" if parsed.series_position else "",
            )
        parsed.series_position = normalized.series_position

    # Apply title from normalized data - ALWAYS prefer Audnex title
    # This handles Libation format where title/author are swapped
    if normalized.display_title and normalized.display_title != parsed.title:
        logger.info(
            "Enriched title from Audnex: %s%s",
            normalized.display_title,
            (
                f" (was: {parsed.title})"
                if parsed.title and parsed.title not in ("Unknown", "")
                else ""
            ),
        )
        parsed.title = normalized.display_title

    # Extract year from release date if missing
    release_date = audnex_data.get("releaseDate")
    if release_date and not parsed.year:
        # Format: "2025-11-25T00:00:00.000Z" → "2025"
        year = release_date[:4] if len(release_date) >= 4 else None
        if year and year.isdigit():
            parsed.year = year
            logger.info("Enriched year from Audnex: %s", year)

    return parsed, audnex_data, audnex_region


# No path length limit for ABS imports (only applies to MAM uploads)
ABS_NO_PATH_LIMIT = 10000


def build_clean_folder_name(parsed: ParsedFolderName) -> str:
    """Build a clean folder name from parsed components.

    Uses the naming module's build_mam_folder_name() to apply all cleaning:
    - Volume normalization (Vol. 7 → vol_07)
    - Series suffix removal
    - Phrase filtering
    - Sanitization

    Note: No path length limit is applied for ABS imports (personal library).
    The MAM 225-char limit only applies to `mamfast run` uploads.

    Args:
        parsed: ParsedFolderName from parse_mam_folder_name()

    Returns:
        Clean folder name following naming convention
    """
    return build_mam_folder_name(
        series=parsed.series,
        title=parsed.title,
        volume_number=parsed.series_position,
        arc=None,  # Arc is part of title for now
        year=parsed.year,
        author=parsed.narrator or parsed.author,  # Use narrator if available
        asin=parsed.asin,
        ripper_tag=parsed.ripper_tag,
        max_length=ABS_NO_PATH_LIMIT,  # No limit for personal library
    )


def build_clean_file_name(parsed: ParsedFolderName, extension: str = ".m4b") -> str:
    """Build a clean file name from parsed components.

    Uses the naming module's build_mam_file_name() which:
    - Applies same cleaning as folder name
    - Excludes ripper tag (tag is folder-only)
    - Includes file extension

    Note: No path length limit is applied for ABS imports (personal library).
    The MAM 225-char limit only applies to `mamfast run` uploads.

    Args:
        parsed: ParsedFolderName from parse_mam_folder_name()
        extension: File extension (default: ".m4b")

    Returns:
        Clean filename following naming convention
    """
    return build_mam_file_name(
        series=parsed.series,
        title=parsed.title,
        volume_number=parsed.series_position,
        arc=None,  # Arc is part of title for now
        year=parsed.year,
        author=parsed.narrator or parsed.author,  # Use narrator if available
        asin=parsed.asin,
        extension=extension,
        max_length=ABS_NO_PATH_LIMIT,  # No limit for personal library
    )


def rename_files_in_folder(
    folder_path: Path,
    parsed: ParsedFolderName,
    *,
    dry_run: bool = False,
) -> list[tuple[str, str]]:
    """Rename files in folder to match clean MAM naming convention.

    Renames audio files (.m4b, .mp3, etc.), cue sheets, cover images,
    and metadata files to use the clean base name.

    Special handling:
    - cover.jpg is kept as-is (standard ABS naming)
    - Files already matching clean name are skipped
    - Compound extensions like .metadata.json are preserved
    - Multi-file books: preserve track suffix (e.g., " - 01", " - 02")

    Args:
        folder_path: Path to folder containing files
        parsed: ParsedFolderName with extracted metadata
        dry_run: If True, only log what would happen

    Returns:
        List of (old_name, new_name) tuples for renamed files
    """
    renamed: list[tuple[str, str]] = []

    # Audio extensions for multi-file detection
    audio_extensions = {".m4b", ".m4a", ".mp3", ".ogg", ".flac", ".opus"}

    # Count audio files to detect multi-file books
    audio_files = sorted(
        [f for f in folder_path.iterdir() if f.is_file() and f.suffix.lower() in audio_extensions]
    )
    is_multi_file = len(audio_files) > 1

    # Extensions to rename (audio, cue, images, metadata)
    rename_extensions = {
        ".m4b",
        ".m4a",
        ".mp3",
        ".ogg",
        ".flac",
        ".opus",  # Audio
        ".cue",  # Cue sheets
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",  # Images
        ".json",  # Metadata
        ".pdf",
    }

    # Compound extensions to check first (order matters)
    compound_extensions = [".metadata.json"]

    # Files to skip renaming (keep original names)
    skip_names = {"cover.jpg", "cover.jpeg", "cover.png", "folder.jpg", "folder.png"}

    for file_path in folder_path.iterdir():
        if not file_path.is_file():
            continue

        # Skip special files
        if file_path.name.lower() in skip_names:
            continue

        # Check for compound extensions first
        ext = None
        for compound_ext in compound_extensions:
            if file_path.name.lower().endswith(compound_ext):
                ext = compound_ext
                break

        # Fall back to simple extension
        if ext is None:
            ext = file_path.suffix.lower()
            if ext not in rename_extensions:
                continue

        # Build the clean filename (without extension for multi-file handling)
        base_clean_name = build_clean_file_name(parsed, extension="")

        # For multi-file audio books, extract and preserve track suffix
        track_suffix = ""
        if is_multi_file and ext in audio_extensions:
            # Try to extract track number from original filename
            # Common patterns: " - 01", " - 1", "_01", " 01", "Part 1", etc.
            stem = file_path.stem
            track_match = re.search(r"[\s_-]+(\d{1,3})$", stem)
            if track_match:
                track_num = track_match.group(1)
                # Pad to 2 digits for consistent sorting
                track_suffix = f" - {int(track_num):02d}"
            else:
                # No track number found - preserve original filename to be safe
                logger.debug(
                    "Multi-file book: no track number found in '%s', preserving original",
                    file_path.name,
                )
                continue

        # Build final filename
        new_name = f"{base_clean_name}{track_suffix}{ext}"

        # Skip if already has the correct name
        if file_path.name == new_name:
            continue

        new_path = file_path.parent / new_name

        # Safety check: don't overwrite existing files
        if new_path.exists() and new_path != file_path:
            logger.warning(
                "Target file already exists, skipping rename: %s → %s",
                file_path.name,
                new_name,
            )
            continue

        if dry_run:
            logger.info("[DRY RUN] Would rename: %s → %s", file_path.name, new_name)
        else:
            try:
                file_path.rename(new_path)
                logger.info("Renamed: %s → %s", file_path.name, new_name)
            except OSError as e:
                logger.warning("Failed to rename %s: %s", file_path.name, e)
                continue

        renamed.append((file_path.name, new_name))

    return renamed


def remove_ignored_files(
    folder_path: Path,
    ignore_patterns: list[str],
    *,
    dry_run: bool = False,
) -> list[str]:
    """Remove files matching ignore patterns from a folder.

    Supports two pattern types:
    - Simple extension: ".json" matches any file ending in .json
    - Glob pattern: "*.metadata.json" matches files ending in .metadata.json

    Args:
        folder_path: Path to folder to clean
        ignore_patterns: List of patterns (e.g., [".json", "*.metadata.json"])
        dry_run: If True, only log what would happen

    Returns:
        List of removed filenames
    """
    if not ignore_patterns:
        return []

    removed: list[str] = []

    for file_path in folder_path.iterdir():
        if not file_path.is_file():
            continue

        filename = file_path.name
        filename_lower = filename.lower()
        should_remove = False

        for pattern in ignore_patterns:
            pattern_lower = pattern.lower()
            # Glob pattern (contains *) or simple extension match
            if ("*" in pattern and fnmatch.fnmatch(filename_lower, pattern_lower)) or (
                pattern.startswith(".") and filename_lower.endswith(pattern_lower)
            ):
                should_remove = True
                break

        if should_remove:
            if dry_run:
                logger.info("[DRY RUN] Would remove ignored file: %s", file_path)
            else:
                try:
                    file_path.unlink()
                    logger.info("Removed ignored file: %s", filename)
                except OSError as e:
                    logger.warning("Failed to remove %s: %s", filename, e)
                    continue
            removed.append(filename)

    return removed


# =============================================================================
# Phase 2: Unknown ASIN Policy Handling
# =============================================================================


def matches_homebrew_pattern(folder_name: str, parsed: ParsedFolderName) -> bool:
    """Detect 'Author - Title' pattern suggesting homebrew/self-pub content.

    Homebrew content typically follows the simple pattern "Author - Title" without
    the metadata markers (year, ASIN, ripper tag) that MAM-compliant folders have.

    Args:
        folder_name: Original folder name
        parsed: ParsedFolderName from parsing

    Returns:
        True if folder matches homebrew pattern
    """
    # Explicit author AND no ASIN AND no year suggests homebrew
    # These often come from personal rips: "Joe Smith - My Podcast"
    if parsed.author and not parsed.asin and not parsed.year:
        # Simple heuristic: folder starts with "Author - " or "Author_-_"
        normalized = folder_name.replace("_", " ").strip()
        author_prefix = f"{parsed.author.lower()} - "
        return normalized.lower().startswith(author_prefix)
    return False


def classify_unknown_asin(
    folder: Path,
    parsed: ParsedFolderName,
) -> UnknownAsinContext:
    """Classify an unknown-ASIN folder for routing decisions.

    Determines:
    - Content type: MISSING_ASIN (likely Audible) vs HOMEBREW (no ASIN expected)
    - File count: For multi-file protection decisions

    Args:
        folder: Path to the audiobook folder
        parsed: ParsedFolderName from parse_mam_folder_name()

    Returns:
        UnknownAsinContext with classification and metadata
    """
    # Count audio files (handle I/O errors gracefully)
    try:
        audio_files = [
            f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
        ]
    except (OSError, PermissionError) as e:
        logger.warning("Failed to list files in folder '%s': %s", folder, e)
        audio_files = []
    file_count = len(audio_files)

    # Classify content type using homebrew heuristic
    if matches_homebrew_pattern(folder.name, parsed):
        content_type = UnknownAsinContentType.HOMEBREW
    else:
        content_type = UnknownAsinContentType.MISSING_ASIN

    return UnknownAsinContext(
        folder=folder,
        parsed=parsed,
        content_type=content_type,
        file_count=file_count,
        original_folder_name=folder.name,
    )


def get_unique_destination(base_path: Path) -> Path:
    """Get a unique destination path, appending suffix if needed.

    Prevents collision when two books have similar names.

    Args:
        base_path: Desired destination path

    Returns:
        base_path if it doesn't exist, otherwise base_path with _N suffix

    Raises:
        RuntimeError: If no unique path found after 1000 attempts
    """
    if not base_path.exists():
        return base_path

    # Append suffix: "My Book (2020)" → "My Book (2020)_2"
    counter = 2
    max_attempts = 1000
    while counter <= max_attempts:
        candidate = base_path.parent / f"{base_path.name}_{counter}"
        if not candidate.exists():
            return candidate
        counter += 1

    logger.error(
        "Failed to find unique destination for %s after %d attempts",
        base_path,
        max_attempts,
    )
    raise RuntimeError(
        f"Could not find unique destination for {base_path} after {max_attempts} attempts"
    )


def build_unknown_target_path(
    library_root: Path,
    ctx: UnknownAsinContext,
) -> Path:
    """Build target path for unknown-ASIN content.

    Routing:
    - MISSING_ASIN → Unknown/<OriginalFolderName>/
    - HOMEBREW → <Author>/<Title (Author)>/

    Args:
        library_root: ABS library root
        ctx: Unknown ASIN context with classification

    Returns:
        Target path for the audiobook
    """
    if ctx.content_type == UnknownAsinContentType.HOMEBREW:
        # Homebrew: route to Author/Title structure
        author = ctx.parsed.author or "Unknown"
        title = ctx.parsed.title or ctx.original_folder_name

        # Build folder name: "Title (Author)" format
        folder_name = f"{title} ({author})"
        base_path = library_root / author / folder_name
    else:
        # Missing ASIN: route to Unknown/<OriginalFolderName>
        base_path = library_root / "Unknown" / ctx.original_folder_name

    return get_unique_destination(base_path)


def write_unknown_asin_sidecar(
    dst_folder: Path,
    ctx: UnknownAsinContext,
    policy: str,
) -> Path | None:
    """Write metadata sidecar for unknown-ASIN import.

    Creates _mamfast_unknown_asin.json with import metadata for future
    batch resolution tools.

    Args:
        dst_folder: Destination folder (after move)
        ctx: Unknown ASIN context
        policy: Policy used ("import" or "quarantine")

    Returns:
        Path to sidecar file, or None if write failed
    """
    sidecar_path = dst_folder / "_mamfast_unknown_asin.json"

    payload = {
        "content_type": ctx.content_type.value,
        "is_multi_file": ctx.is_multi_file,
        "original_folder": ctx.original_folder_name,
        "file_count": ctx.file_count,
        "imported_at": datetime.now(UTC).isoformat(),
        "policy": policy,
        "parsed": {
            "author": ctx.parsed.author,
            "title": ctx.parsed.title,
            "series": ctx.parsed.series,
            "year": ctx.parsed.year,
        },
    }

    try:
        sidecar_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        logger.debug("Wrote unknown ASIN sidecar: %s", sidecar_path)
        return sidecar_path
    except OSError as e:
        logger.warning("Failed to write sidecar %s: %s", sidecar_path, e)
        return None


def handle_unknown_asin(
    ctx: UnknownAsinContext,
    library_root: Path,
    *,
    unknown_asin_policy: UnknownAsinPolicy = UnknownAsinPolicy.IMPORT,
    quarantine_path: Path | None = None,
    dry_run: bool = False,
) -> ImportResult:
    """Handle import of audiobook without ASIN.

    Behavior depends on policy:
    - IMPORT: Move to Unknown/ or Author/ (homebrew), create sidecar
    - QUARANTINE: Move to quarantine folder, no renames
    - SKIP: Leave in staging, return skipped result

    Args:
        ctx: Unknown ASIN context with classification
        library_root: ABS library root
        unknown_asin_policy: How to handle (import/quarantine/skip)
        quarantine_path: Path for quarantine (required if policy=QUARANTINE)
        dry_run: If True, don't actually move files

    Returns:
        ImportResult with status and details
    """
    if unknown_asin_policy == UnknownAsinPolicy.SKIP:
        logger.warning(
            "Skipping import for unknown ASIN (policy=skip): %s (type=%s, files=%d)",
            ctx.folder.name,
            ctx.content_type.value,
            ctx.file_count,
        )
        return ImportResult(
            staging_path=ctx.folder,
            target_path=None,
            asin=None,
            status="skipped",
            error="Unknown ASIN (policy=skip)",
            parsed=ctx.parsed,
        )

    if unknown_asin_policy == UnknownAsinPolicy.QUARANTINE:
        if not quarantine_path:
            return ImportResult(
                staging_path=ctx.folder,
                target_path=None,
                asin=None,
                status="failed",
                error="Quarantine policy requires quarantine_path",
                parsed=ctx.parsed,
            )
        target_path = get_unique_destination(quarantine_path / ctx.original_folder_name)
    else:
        # Default: IMPORT
        target_path = build_unknown_target_path(library_root, ctx)

    if dry_run:
        logger.info(
            "[DRY RUN] Would import unknown ASIN (%s): %s → %s",
            ctx.content_type.value,
            ctx.folder.name,
            target_path,
        )
        return ImportResult(
            staging_path=ctx.folder,
            target_path=target_path,
            asin=None,
            status="success",
            parsed=ctx.parsed,
        )

    # Create parent directories
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return ImportResult(
            staging_path=ctx.folder,
            target_path=target_path,
            asin=None,
            status="failed",
            error=f"Failed to create directories: {e}",
            parsed=ctx.parsed,
        )

    # Atomic move
    try:
        ctx.folder.rename(target_path)
        logger.info(
            "Imported unknown ASIN (%s): %s → %s",
            ctx.content_type.value,
            ctx.original_folder_name,
            target_path,
        )
    except OSError as e:
        return ImportResult(
            staging_path=ctx.folder,
            target_path=target_path,
            asin=None,
            status="failed",
            error=f"Move failed: {e}",
            parsed=ctx.parsed,
        )

    # Rename files (respects multi-file protection from Phase 1)
    rename_files_in_folder(target_path, ctx.parsed)

    # Write sidecar for future resolution
    policy_str = "quarantine" if unknown_asin_policy == UnknownAsinPolicy.QUARANTINE else "import"
    write_unknown_asin_sidecar(target_path, ctx, policy_str)

    return ImportResult(
        staging_path=ctx.folder,
        target_path=target_path,
        asin=None,
        status="success",
        parsed=ctx.parsed,
    )


def _normalize_for_comparison(name: str) -> str:
    """Normalize a name for case-insensitive comparison.

    Used to match folder names that may differ only in case, punctuation,
    or whitespace. Does NOT remove semantic suffixes like "Series" -
    use clean_series_name() for that before calling this.

    Args:
        name: Name to normalize (already cleaned of semantic suffixes)

    Returns:
        Lowercase, punctuation-stripped, whitespace-collapsed string
    """
    result = name.lower()
    # Replace punctuation with spaces
    result = re.sub(r"[.,;:/\-_]+", " ", result)
    # Collapse whitespace
    result = re.sub(r"\s+", " ", result)
    return result.strip()


def _find_matching_author_folder(library_root: Path, author: str) -> Path | None:
    """Find existing author folder with case-insensitive/normalized matching.

    Args:
        library_root: ABS library root
        author: Author name to match

    Returns:
        Path to existing author folder if found, else None
    """
    if not library_root.exists():
        return None

    normalized_author = _normalize_for_comparison(author)
    for folder in library_root.iterdir():
        if not folder.is_dir():
            continue
        if _normalize_for_comparison(folder.name) == normalized_author:
            logger.debug("Matched author '%s' to existing folder '%s'", author, folder.name)
            return folder
    return None


def _find_matching_series_folder(
    author_folder: Path, series: str, book_title: str | None = None
) -> tuple[Path | None, str | None]:
    """Find existing series folder with normalized matching.

    Handles:
    - Case-insensitive matching
    - " Series" suffix differences (e.g., "A Most Unlikely Hero" vs "A Most Unlikely Hero Series")
    - Cleaned series name matching

    Args:
        author_folder: Author folder to search in
        series: Series name to match
        book_title: Optional book title for " The" prefix inheritance

    Returns:
        Tuple of (path to existing series folder if found, canonical cleaned name)
        The canonical name is returned so callers can decide whether to rename
    """
    if not author_folder.exists():
        return None, None

    # Clean and normalize the input series name
    cleaned_series = clean_series_name(series, book_title) or series
    normalized_series = _normalize_for_comparison(cleaned_series)

    for folder in author_folder.iterdir():
        if not folder.is_dir():
            continue
        # Try normalized match against cleaned folder name
        folder_cleaned = clean_series_name(folder.name) or folder.name
        if _normalize_for_comparison(folder_cleaned) == normalized_series:
            logger.debug("Matched series '%s' to existing folder '%s'", series, folder.name)
            return folder, cleaned_series
    return None, cleaned_series


def _same_filesystem(path1: Path, path2: Path) -> bool:
    """Check if two paths are on the same filesystem.

    Args:
        path1: First path (must exist)
        path2: Second path (must exist)

    Returns:
        True if same filesystem (same st_dev)
    """
    try:
        stat1 = path1.stat()
        stat2 = path2.stat()
        return stat1.st_dev == stat2.st_dev
    except OSError:
        return False


def validate_import_prerequisites(
    staging_root: Path,
    library_root: Path,
) -> list[str]:
    """Validate prerequisites for import operations.

    Checks:
    1. Staging directory exists and is accessible
    2. Library root exists and is writable
    3. Both are on the same filesystem (for atomic moves)

    Args:
        staging_root: Staging directory (seed_root)
        library_root: ABS library root

    Returns:
        List of error messages (empty if all checks pass)
    """
    errors: list[str] = []

    # Check staging exists
    if not staging_root.exists():
        errors.append(f"Staging directory does not exist: {staging_root}")
    elif not staging_root.is_dir():
        errors.append(f"Staging path is not a directory: {staging_root}")

    # Check library root exists and is writable
    if not library_root.exists():
        errors.append(f"Library root does not exist: {library_root}")
    elif not library_root.is_dir():
        errors.append(f"Library path is not a directory: {library_root}")
    elif not os.access(library_root, os.W_OK):
        errors.append(f"Library root is not writable: {library_root}")

    # Check same filesystem (only if both exist)
    if (
        staging_root.exists()
        and library_root.exists()
        and not _same_filesystem(staging_root, library_root)
    ):
        errors.append(
            f"Staging ({staging_root}) and library ({library_root}) "
            "are on different filesystems. Atomic move requires same filesystem "
            "to preserve hardlinks."
        )

    return errors


def build_target_path(
    library_root: Path,
    parsed: ParsedFolderName,
    staging_folder: Path,
    staging_root: Path | None = None,
) -> Path:
    """Build the target path in ABS library structure.

    Matches existing author/series folders to avoid creating duplicates.
    Cleans series names (removes " Series" suffix) before matching.

    Structure:
    - Series: Library/Author/Series/FolderName/
    - Standalone: Library/Author/FolderName/

    Args:
        library_root: ABS library root path
        parsed: Parsed folder name components
        staging_folder: Original staging folder (for folder name)
        staging_root: Root of staging directory (to extract author/series from path)

    Returns:
        Target path for the audiobook
    """
    # Extract author and series from staging path structure if available
    staging_author = None
    staging_series = None

    if staging_root and staging_folder != staging_root:
        try:
            relative_path = staging_folder.relative_to(staging_root)
            parts = relative_path.parts
            # Structure: Author/Series/Book or Author/Book
            if len(parts) >= 3:
                staging_author = parts[0]
                staging_series = parts[1]
            elif len(parts) == 2:
                staging_author = parts[0]
        except ValueError:
            pass

    # Determine author - prefer staging path, fall back to parsed
    author_name = staging_author or parsed.author

    # Find existing author folder or use author name
    existing_author = _find_matching_author_folder(library_root, author_name)
    author_folder = existing_author or (library_root / author_name)

    # Determine series - PREFER parsed (enriched from Audnex) over staging path
    # Staging path may have incorrect/duplicate series names (e.g., "Black Summoner Black Summoner")
    # while Audnex data is authoritative
    series_name = parsed.series or staging_series

    # Use series folder if we have a series name from parsed (Audnex-enriched)
    # OR from staging path (fallback)
    has_series = (parsed.series and not parsed.is_standalone) or staging_series

    # Build clean folder name using naming module
    clean_folder_name = build_clean_folder_name(parsed)

    if has_series and series_name:
        # Clean the series name (remove " Series" suffix, etc.)
        cleaned_series = clean_series_name(series_name, parsed.title) or series_name

        # Find existing series folder
        existing_series, canonical_series = _find_matching_series_folder(
            author_folder if existing_author else library_root / author_name,
            cleaned_series,
            parsed.title,
        )

        # Use canonical name (may differ from existing folder name)
        final_series_name = canonical_series or cleaned_series

        if existing_series:
            # Check if existing folder name differs from canonical
            if existing_series.name != final_series_name:
                logger.info(
                    "Using existing series folder '%s' (canonical: '%s')",
                    existing_series.name,
                    final_series_name,
                )
            series_folder = existing_series
        else:
            # Create new folder with canonical (cleaned) name
            series_folder = author_folder / final_series_name

        return series_folder / clean_folder_name
    else:
        # Standalone: Author/Title (using cleaned folder name)
        return author_folder / clean_folder_name


def _handle_duplicate(
    staging_folder: Path,
    asin: str,
    existing_path: str | None,
    duplicate_policy: str,
    parsed: ParsedFolderName,
    *,
    context: str = "",
) -> ImportResult | None:
    """Handle duplicate ASIN based on policy.

    Args:
        staging_folder: Staging folder path
        asin: ASIN that is duplicate
        existing_path: Path where ASIN already exists (may be None)
        duplicate_policy: "skip", "warn", or "overwrite"
        parsed: Parsed folder name data
        context: Optional context string (e.g., "Normalized ") for log messages

    Returns:
        ImportResult if duplicate should stop import (skip/warn)
        None if import should continue (overwrite)
    """
    # Handle None gracefully - shouldn't happen but be defensive
    path_str = existing_path or "unknown location"

    if duplicate_policy == "skip":
        error_msg = (
            f"{context}ASIN already exists at {path_str}"
            if context
            else f"Already exists at {path_str}"
        )
        return ImportResult(
            staging_path=staging_folder,
            target_path=None,
            asin=asin,
            status="duplicate",
            error=error_msg,
            parsed=parsed,
        )
    elif duplicate_policy == "warn":
        log_msg = (
            f"{context}ASIN %s exists at %s, skipping"
            if context
            else "Duplicate ASIN %s exists at %s, skipping"
        )
        logger.warning(log_msg, asin, path_str)
        error_msg = (
            f"{context}ASIN already exists at {path_str}"
            if context
            else f"Already exists at {path_str}"
        )
        return ImportResult(
            staging_path=staging_folder,
            target_path=None,
            asin=asin,
            status="duplicate",
            error=error_msg,
            parsed=parsed,
        )
    elif duplicate_policy == "overwrite":
        # For overwrite, we proceed but note the existing path
        log_msg = (
            f"{context}ASIN %s exists, will overwrite at %s"
            if context
            else "Duplicate ASIN %s, will overwrite at %s"
        )
        logger.info(log_msg, asin, path_str)
        return None  # Continue with import
    else:
        # Shouldn't happen if config validation works, but be defensive
        return ImportResult(
            staging_path=staging_folder,
            target_path=None,
            asin=asin,
            status="failed",
            error=f"Invalid duplicate_policy: {duplicate_policy}",
            parsed=parsed,
        )


def import_single(
    staging_folder: Path,
    library_root: Path,
    asin_index: dict[str, AsinEntry],
    *,
    abs_client: AbsClient | None = None,
    abs_search_confidence: float = 0.75,
    staging_root: Path | None = None,
    duplicate_policy: str = "skip",
    unknown_asin_policy: UnknownAsinPolicy = UnknownAsinPolicy.IMPORT,
    quarantine_path: Path | None = None,
    ignore_patterns: list[str] | None = None,
    trump_prefs: TrumpPrefs | None = None,
    path_mapper: PathMapper | None = None,
    cleanup_prefs: CleanupPrefs | None = None,
    source_path: Path | None = None,
    seed_root: Path | None = None,
    preferred_asin_region: str | None = None,
    generate_metadata_json: bool = True,
    metadata_json_fallback: bool = True,
    dry_run: bool = False,
) -> ImportResult:
    """Import a single audiobook from staging to library.

    Args:
        staging_folder: Path to staged audiobook folder
        library_root: ABS library root
        asin_index: In-memory ASIN index from build_asin_index()
        abs_client: Optional AbsClient for ABS search fallback (Phase 5)
        abs_search_confidence: Minimum confidence for ABS search matches (0.0-1.0)
        staging_root: Root of staging directory (to preserve nested structure)
        duplicate_policy: "skip", "warn", or "overwrite"
        unknown_asin_policy: How to handle books without ASIN
        quarantine_path: Path for quarantine (required if policy=QUARANTINE)
        ignore_patterns: File patterns to remove before import (e.g., [".json", "*.metadata.json"])
        trump_prefs: Trumping preferences (None = disabled)
        path_mapper: Optional path mapper for container↔host conversion
        cleanup_prefs: Post-import cleanup preferences (None = disabled)
        source_path: Original Libation source path (for cleanup, if different from staging)
        seed_root: Seed/staging root path (for cleanup hardlink verification)
        preferred_asin_region: Preferred ASIN region code (e.g., "us"). If set and
            audnex returns a different region, normalizes to preferred region via ABS search.
        generate_metadata_json: If True, generate metadata.json for ABS (default True)
        metadata_json_fallback: If True, generate metadata.json even without ASIN (default True)
        dry_run: If True, don't actually move files

    Returns:
        ImportResult with status and details
    """
    folder_name = staging_folder.name

    # Parse folder name
    try:
        parsed = parse_mam_folder_name(folder_name)
    except ValueError as e:
        return ImportResult(
            staging_path=staging_folder,
            target_path=None,
            asin=None,
            status="failed",
            error=f"Failed to parse folder name: {e}",
        )

    asin = parsed.asin

    # Phase 3+4: Enhanced ASIN resolution - try multiple sources before giving up
    # Includes mediainfo probe for embedded ASIN (Phase 4)
    if not asin:
        resolution = resolve_asin_from_folder_with_mediainfo(staging_folder, parsed_asin=None)
        if resolution.found:
            asin = resolution.asin
            # Update parsed object so downstream functions (build_target_path, rename_files)
            # have access to the resolved ASIN for naming
            parsed.asin = asin
            logger.info(
                "Resolved ASIN %s from %s (%s)",
                asin,
                resolution.source,
                resolution.source_detail or "N/A",
            )

    # Phase 5: ABS Metadata Search - search Audiobookshelf's Audible provider
    # as final resolution step before marking as unknown
    if not asin and abs_client is not None:
        search_title = parsed.title or folder_name
        search_author = parsed.author
        logger.debug(
            "Attempting ABS search for title=%r author=%r confidence=%.0f%%",
            search_title,
            search_author,
            abs_search_confidence * 100,
        )
        resolution = resolve_asin_via_abs_search(
            abs_client, search_title, search_author, abs_search_confidence
        )
        if resolution.found:
            asin = resolution.asin
            parsed.asin = asin
            # Update author from search result if we don't have one
            # (e.g., Libation folder without author in name)
            if resolution.resolved_author and (not parsed.author or parsed.author == "Unknown"):
                parsed.author = resolution.resolved_author
                logger.debug("Updated author from ABS search: %s", resolution.resolved_author)
            logger.info(
                "Resolved ASIN %s from %s (%s)",
                asin,
                resolution.source,
                resolution.source_detail or "N/A",
            )

    # Still no ASIN → delegate to unknown ASIN handler
    if not asin:
        ctx = classify_unknown_asin(staging_folder, parsed)
        return handle_unknown_asin(
            ctx,
            library_root,
            unknown_asin_policy=unknown_asin_policy,
            quarantine_path=quarantine_path,
            dry_run=dry_run,
        )

    # Check for duplicates (we have ASIN) - do this BEFORE Audnex enrichment
    # to avoid unnecessary network calls for books we'll skip anyway
    is_dup, existing_path = asin_exists(asin_index, asin)

    # Guard against stale ABS index entries pointing to missing folders
    existing_folder_for_index: Path | None = None
    if is_dup and existing_path:
        existing_folder_for_index = (
            path_mapper.to_host(existing_path) if path_mapper else Path(existing_path)
        )

        if not existing_folder_for_index.exists():
            logger.warning(
                "ABS index has ASIN %s at %s but folder is missing; "
                "skipping duplicate/trump checks. Trigger an ABS rescan to clear stale entries.",
                asin,
                existing_folder_for_index,
            )
            is_dup = False
            existing_folder_for_index = None

    # ─────────────────────────────────────────────────────────────────────
    # Trumping: Quality-based replacement check (runs BEFORE duplicate_policy)
    # ─────────────────────────────────────────────────────────────────────
    trump_decision: TrumpDecision | None = None
    trump_reason: str | None = None

    if is_dup and trump_prefs and trump_prefs.enabled:
        existing_entry = asin_index[asin]
        # Convert container path to host path if path_mapper provided
        existing_folder = (
            existing_folder_for_index
            if existing_folder_for_index is not None
            else (
                path_mapper.to_host(existing_entry.path)
                if path_mapper
                else Path(existing_entry.path)
            )
        )

        # v1: Skip trumping entirely for multi-file layouts
        # Fall through to duplicate_policy handling instead
        if is_multi_file_layout(staging_folder) or is_multi_file_layout(existing_folder):
            logger.debug(
                "Multi-file layout detected - skipping trumping, "
                "falling back to duplicate_policy=%s",
                duplicate_policy,
            )
            # trump_decision stays None → fall through to duplicate handling
        else:
            # Single-file layout - proceed with trumping comparison
            existing_meta = extract_trumpable_meta(existing_folder, asin)
            incoming_meta = extract_trumpable_meta(staging_folder, asin)

            trump_decision, trump_reason = decide_trump(existing_meta, incoming_meta, trump_prefs)
            trump_decision, trump_reason = adjust_for_aggressiveness(
                trump_decision, trump_reason, trump_prefs
            )

            # Log with context (ASIN and title) for easier log review
            short_title = parsed.title[:50] + "..." if len(parsed.title) > 50 else parsed.title
            logger.info(
                "Trump decision: %s - %s (ASIN=%s, title=%s)",
                trump_decision.name,
                trump_reason,
                asin,
                short_title,
            )

            match trump_decision:
                case TrumpDecision.REPLACE_WITH_NEW:
                    # Archive existing, then import new (continue with normal flow)
                    archive_existing(
                        existing_folder,
                        existing_meta,
                        incoming_meta,
                        trump_decision,
                        trump_reason,
                        trump_prefs,
                        dry_run=dry_run,
                    )
                    # Remove from index so duplicate check below doesn't trigger
                    # (the existing folder is now archived)
                    if not dry_run:
                        del asin_index[asin]
                    # Mark as no longer duplicate so we proceed with import
                    is_dup = False
                    # Continue with normal import flow below

                case TrumpDecision.KEEP_EXISTING:
                    return ImportResult(
                        staging_path=staging_folder,
                        target_path=None,
                        asin=asin,
                        status="trump_kept_existing",
                        error=f"Trumping: {trump_reason}",
                        parsed=parsed,
                    )

                case TrumpDecision.REJECT_NEW:
                    return ImportResult(
                        staging_path=staging_folder,
                        target_path=None,
                        asin=asin,
                        status="trump_rejected",
                        error=f"Rejected: {trump_reason}",
                        parsed=parsed,
                    )

                case TrumpDecision.KEEP_BOTH:
                    # Fall through to existing duplicate_policy handling
                    logger.info("Trumping inconclusive: %s", trump_reason)
                    # trump_decision stays KEEP_BOTH → duplicate handling applies

    # ─────────────────────────────────────────────────────────────────────
    # Standard duplicate handling (trumping may have already handled this)
    # ─────────────────────────────────────────────────────────────────────
    if is_dup:
        result = _handle_duplicate(staging_folder, asin, existing_path, duplicate_policy, parsed)
        if result is not None:
            return result

    # Phase 5: Enrich parsed data from Audnex when we have ASIN
    # This fills in author/series/position for poorly-named folders
    # Done after duplicate check to avoid network calls for skipped books
    # Also captures audnex_data for metadata.json generation
    parsed, audnex_data, audnex_region = enrich_from_audnex(parsed, asin)

    # Phase 6: ASIN region normalization - convert non-preferred region ASINs
    # to preferred region ASINs using ABS search (requires ABS client)
    if (
        preferred_asin_region
        and audnex_region
        and audnex_region.lower() != preferred_asin_region.lower()
        and abs_client is not None
    ):
        # Attempt to normalize ASIN to preferred region
        norm_result = normalize_asin_to_preferred_region(
            abs_client,
            asin,
            audnex_region,
            preferred_asin_region,
            title=parsed.title or folder_name,
            author=parsed.author,
            confidence_threshold=0.85,  # Higher threshold for ASIN replacement
        )
        if norm_result.was_normalized:
            # Update ASIN to the normalized (preferred region) version
            old_asin = asin
            asin = norm_result.normalized_asin
            parsed.asin = asin
            logger.info(
                "Using normalized ASIN %s (was %s from %s region)",
                asin,
                old_asin,
                audnex_region,
            )

            # Re-check for duplicates with the normalized ASIN
            # The original duplicate check used the pre-normalization ASIN
            is_dup_normalized, existing_path_normalized = asin_exists(asin_index, asin)
            if is_dup_normalized:
                result = _handle_duplicate(
                    staging_folder,
                    asin,
                    existing_path_normalized,
                    duplicate_policy,
                    parsed,
                    context="Normalized ",
                )
                if result is not None:
                    return result

    # Build target path (preserves nested structure if present)
    target_path = build_target_path(library_root, parsed, staging_folder, staging_root)

    # Check if target already exists on disk
    if target_path.exists():
        if duplicate_policy == "overwrite":
            if not dry_run:
                import shutil

                try:
                    shutil.rmtree(target_path)
                    logger.info("Removed existing target: %s", target_path)
                except Exception as e:
                    logger.error("Failed to remove existing target %s: %s", target_path, e)
                    return ImportResult(
                        staging_path=staging_folder,
                        target_path=target_path,
                        asin=asin,
                        status="failed",
                        error=f"Failed to remove existing target: {e}",
                    )
        else:
            return ImportResult(
                staging_path=staging_folder,
                target_path=target_path,
                asin=asin,
                status="duplicate",
                error=f"Target path already exists: {target_path}",
                parsed=parsed,
            )

    # Remove ignored files before moving (e.g., .metadata.json)
    if ignore_patterns:
        remove_ignored_files(staging_folder, ignore_patterns, dry_run=dry_run)

    if dry_run:
        logger.info("[DRY RUN] Would move %s → %s", staging_folder, target_path)
        # Preview file renames
        rename_files_in_folder(staging_folder, parsed, dry_run=True)

        # Preview cleanup (dry_run mode)
        cleanup_result: CleanupResult | None = None
        if (
            cleanup_prefs is not None
            and cleanup_prefs.strategy != CleanupStrategy.NONE
            and source_path is not None
        ):
            cleanup_result = cleanup_source(
                source_path=source_path,
                prefs=cleanup_prefs,
                seed_root=seed_root,
                asin=asin,
                dry_run=True,
            )

        return ImportResult(
            staging_path=staging_folder,
            target_path=target_path,
            asin=asin,
            status="success",
            parsed=parsed,
            cleanup=cleanup_result,
        )

    # Create parent directories
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return ImportResult(
            staging_path=staging_folder,
            target_path=target_path,
            asin=asin,
            status="failed",
            error=f"Failed to create directories: {e}",
        )

    # Atomic move (rename) - preserves hardlinks
    try:
        staging_folder.rename(target_path)
        logger.info("Moved: %s → %s", staging_folder.name, target_path)
    except OSError as e:
        return ImportResult(
            staging_path=staging_folder,
            target_path=target_path,
            asin=asin,
            status="failed",
            error=f"Move failed: {e}",
        )

    # Rename files to match clean MAM naming convention
    rename_files_in_folder(target_path, parsed)

    # ─────────────────────────────────────────────────────────────────────
    # Generate metadata.json for Audiobookshelf
    # ─────────────────────────────────────────────────────────────────────
    if generate_metadata_json:
        from mamfast.abs.metadata_builder import (
            build_abs_metadata_fallback,
            build_abs_metadata_from_audnex,
            write_abs_metadata_json,
        )
        from mamfast.metadata import fetch_audnex_chapters

        if audnex_data:
            # Full metadata from Audnex
            # fetch_audnex_chapters returns None on HTTP errors internally,
            # but we catch config/network exceptions that may propagate
            try:
                audnex_chapters = fetch_audnex_chapters(asin)
            except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
                logger.debug("Network error fetching chapters for %s: %s", asin, e)
                audnex_chapters = None
            except ConfigurationError as e:
                logger.warning("Config error fetching chapters for %s: %s", asin, e)
                audnex_chapters = None

            abs_metadata = build_abs_metadata_from_audnex(audnex_data, audnex_chapters)
            metadata_path = write_abs_metadata_json(target_path, abs_metadata, dry_run=dry_run)
            if metadata_path:
                logger.info("Generated metadata.json: %s", metadata_path.name)
        elif metadata_json_fallback:
            # Fallback: generate minimal metadata from parsed folder name
            abs_metadata = build_abs_metadata_fallback(parsed)
            metadata_path = write_abs_metadata_json(target_path, abs_metadata, dry_run=dry_run)
            if metadata_path:
                logger.info("Generated metadata.json (fallback): %s", metadata_path.name)

    # Determine status based on whether trumping was involved
    if trump_decision == TrumpDecision.REPLACE_WITH_NEW:
        final_status = "trump_replaced"
    else:
        final_status = "success"

    # ─────────────────────────────────────────────────────────────────────
    # Post-import cleanup of Libation source files
    # ─────────────────────────────────────────────────────────────────────
    cleanup_result = None

    if (
        cleanup_prefs is not None
        and cleanup_prefs.strategy != CleanupStrategy.NONE
        and final_status in CLEANUP_ELIGIBLE_STATUSES
        and source_path is not None
    ):
        logger.debug(
            "Running post-import cleanup (strategy=%s) for: %s",
            cleanup_prefs.strategy.value,
            source_path,
        )
        cleanup_result = cleanup_source(
            source_path=source_path,
            prefs=cleanup_prefs,
            seed_root=seed_root,
            asin=asin,
            dry_run=dry_run,
        )
        if cleanup_result.status == "success":
            logger.info(
                "Cleanup (%s) completed for: %s",
                cleanup_prefs.strategy.value,
                source_path,
            )
        elif cleanup_result.status == "failed":
            logger.warning(
                "Cleanup failed for %s: %s",
                source_path,
                cleanup_result.error,
            )

    return ImportResult(
        staging_path=staging_folder,
        target_path=target_path,
        asin=asin,
        status=final_status,
        parsed=parsed,
        cleanup=cleanup_result,
    )


def import_batch(
    staging_folders: list[Path],
    library_root: Path,
    asin_index: dict[str, AsinEntry],
    *,
    abs_client: AbsClient | None = None,
    abs_search_confidence: float = 0.75,
    staging_root: Path | None = None,
    duplicate_policy: str = "skip",
    unknown_asin_policy: UnknownAsinPolicy = UnknownAsinPolicy.IMPORT,
    quarantine_path: Path | None = None,
    ignore_patterns: list[str] | None = None,
    trump_prefs: TrumpPrefs | None = None,
    path_mapper: PathMapper | None = None,
    cleanup_prefs: CleanupPrefs | None = None,
    source_paths: dict[Path, Path] | None = None,
    seed_root: Path | None = None,
    preferred_asin_region: str | None = None,
    generate_metadata_json: bool = True,
    metadata_json_fallback: bool = True,
    progress_callback: Callable[[int, int, Path], None] | None = None,
    dry_run: bool = False,
) -> BatchImportResult:
    """Import multiple audiobooks from staging to library.

    Args:
        staging_folders: List of staging folders to import
        library_root: ABS library root
        asin_index: In-memory ASIN index from build_asin_index()
        abs_client: Optional ABS client for metadata search resolution
        abs_search_confidence: Minimum confidence for ABS search matches (0.0-1.0)
        staging_root: Root staging directory (for resolving author from path)
        duplicate_policy: "skip", "warn", or "overwrite"
        unknown_asin_policy: How to handle books without ASIN
        quarantine_path: Path for quarantine (required if policy=QUARANTINE)
        ignore_patterns: File patterns to remove before import (e.g., [".json", "*.metadata.json"])
        trump_prefs: Trumping preferences (None = disabled)
        path_mapper: Optional path mapper for container↔host conversion
        cleanup_prefs: Post-import cleanup preferences (None = disabled)
        source_paths: Mapping of staging_folder → original source path (for cleanup)
        seed_root: Seed/staging root path (for cleanup hardlink verification)
        preferred_asin_region: Preferred ASIN region code (e.g., "us"). If set and
            audnex returns a different region, normalizes to preferred region via ABS search.
        generate_metadata_json: If True, generate metadata.json for ABS (default True)
        metadata_json_fallback: If True, generate metadata.json even without ASIN (default True)
        progress_callback: Optional callback(current, total, folder) for progress updates
        dry_run: If True, don't actually move files

    Returns:
        BatchImportResult with all results and counts
    """
    batch_result = BatchImportResult()
    total = len(staging_folders)

    for i, folder in enumerate(staging_folders):
        # Call progress callback before processing each folder
        if progress_callback:
            progress_callback(i, total, folder)

        # Get source path for cleanup if mapping provided
        source_path = source_paths.get(folder) if source_paths else None

        result = import_single(
            staging_folder=folder,
            library_root=library_root,
            asin_index=asin_index,
            abs_client=abs_client,
            abs_search_confidence=abs_search_confidence,
            staging_root=staging_root,
            duplicate_policy=duplicate_policy,
            unknown_asin_policy=unknown_asin_policy,
            quarantine_path=quarantine_path,
            ignore_patterns=ignore_patterns,
            trump_prefs=trump_prefs,
            path_mapper=path_mapper,
            cleanup_prefs=cleanup_prefs,
            source_path=source_path,
            seed_root=seed_root,
            preferred_asin_region=preferred_asin_region,
            generate_metadata_json=generate_metadata_json,
            metadata_json_fallback=metadata_json_fallback,
            dry_run=dry_run,
        )
        batch_result.add(result)

    return batch_result


def trigger_scan_safe(client: AbsClient, library_id: str) -> bool:
    """Trigger ABS library scan, returning False on failure.

    Safe wrapper that doesn't raise on errors - import already succeeded,
    ABS will pick up files on its next scheduled scan anyway.

    Args:
        client: AbsClient instance
        library_id: Library to scan

    Returns:
        True if scan triggered, False if failed
    """
    try:
        client.scan_library(library_id)
        logger.info("Triggered ABS scan for library %s", library_id)
        return True
    except Exception as e:
        logger.warning("Failed to trigger ABS scan: %s", e)
        return False


def discover_staged_books(staging_root: Path, *, recursive: bool = True) -> list[Path]:
    """Discover audiobook folders in staging directory.

    Finds directories that directly contain audio files (leaf audiobook folders).
    By default searches recursively through the directory tree.

    Args:
        staging_root: Root staging directory
        recursive: If True, search recursively for audiobook folders.
                  If False, only check immediate children.

    Returns:
        List of audiobook folder paths (folders that contain audio files)
    """
    if not staging_root.exists() or not staging_root.is_dir():
        return []

    staged: list[Path] = []

    # Audio extensions to look for
    audio_exts = {".m4b", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".wav"}

    def has_audio_files(directory: Path) -> bool:
        """Check if directory directly contains audio files."""
        try:
            for child in directory.iterdir():
                if child.is_file() and child.suffix.lower() in audio_exts:
                    return True
        except PermissionError:
            pass
        return False

    def search_directory(directory: Path) -> None:
        """Recursively search for audiobook folders."""
        try:
            for item in directory.iterdir():
                if not item.is_dir():
                    continue

                # If this directory has audio files, it's an audiobook folder
                if has_audio_files(item):
                    staged.append(item)
                elif recursive:
                    # Otherwise, search deeper
                    search_directory(item)
        except PermissionError:
            pass

    search_directory(staging_root)
    return sorted(staged)
