"""ASIN extraction and in-memory index for duplicate detection.

Handles multiple naming conventions from different eras of the library:
- Current MAMFast: {ASIN.B0xxx}
- Older bracket: [ASIN.B0xxx]
- Bare bracket: [B0xxxxxxxx]
- Bare ASIN: B0xxxxxxxx (word boundary)

Also extracts ASINs from ABS metadata when available and provides
in-memory ASIN indexing for fast duplicate detection without SQLite.

Phase 3 (UNKNOWN_ASIN_HANDLING.md) adds resolve_asin_from_folder() which
tries multiple sources before giving up on finding an ASIN.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mamfast.abs.client import AbsClient

logger = logging.getLogger(__name__)

# Supported audio file extensions for ASIN extraction from filenames
AUDIO_EXTENSIONS = (".m4b", ".mp3", ".m4a", ".opus", ".flac")

# Pattern cascade for ASIN extraction (most specific → least specific)
ASIN_PATTERNS = [
    # NEW: {ASIN.B0xxx} - current MAMFast format
    re.compile(r"\{ASIN\.([A-Z0-9]{10})\}"),
    # OLD: [ASIN.B0xxx] - older bracket format
    re.compile(r"\[ASIN\.([A-Z0-9]{10})\]"),
    # OLD: [B0xxxxxxxx] - bare ASIN in brackets (no prefix)
    # NOTE: B0 is literal "B0", not character class [B0]
    re.compile(r"\[(B0[A-Z0-9]{8})\]"),
    # FALLBACK: bare ASIN anywhere with word boundaries
    re.compile(r"(?<![A-Z0-9])(B0[A-Z0-9]{8})(?![A-Z0-9])"),
]

# ASIN validation pattern
ASIN_REGEX = re.compile(r"^[A-Z0-9]{10}$")


@dataclass
class AsinSource:
    """Tracks where an ASIN was found."""

    asin: str
    source: str  # "metadata", "folder_name", "file_name", "audnex"
    pattern_index: int | None = None  # Which pattern matched (for folder/file)


def is_valid_asin(asin: str | None) -> bool:
    """Check if a string is a valid ASIN format.

    ASINs are 10 alphanumeric characters.
    Most audiobook ASINs start with B0.
    """
    if not asin:
        return False
    return bool(ASIN_REGEX.match(asin))


def extract_asin(text: str) -> str | None:
    """Extract ASIN from any naming format.

    Tries patterns in order of specificity. Returns first match.

    Args:
        text: Folder name, file name, or other text to search

    Returns:
        ASIN string if found, None otherwise

    Examples:
        >>> extract_asin("Book {ASIN.B0DK9TS6D9}")
        'B0DK9TS6D9'
        >>> extract_asin("Book [ASIN.B0CNTY7LVH]")
        'B0CNTY7LVH'
        >>> extract_asin("Book [B0DMQ2WP9F]")
        'B0DMQ2WP9F'
        >>> extract_asin("Book B0ABC12345 extra")
        'B0ABC12345'
    """
    if not text:
        return None
    for pattern in ASIN_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None


def extract_asin_with_source(text: str, source_type: str) -> AsinSource | None:
    """Extract ASIN and track which pattern matched.

    Args:
        text: Text to search for ASIN
        source_type: Label for the source ("folder_name", "file_name", etc.)

    Returns:
        AsinSource with ASIN and pattern info, or None
    """
    if not text:
        return None
    for i, pattern in enumerate(ASIN_PATTERNS):
        match = pattern.search(text)
        if match:
            return AsinSource(
                asin=match.group(1),
                source=source_type,
                pattern_index=i,
            )
    return None


def extract_asin_from_abs_item(item: dict[str, Any]) -> AsinSource | None:
    """Extract ASIN from an ABS library item response.

    Checks multiple sources in priority order:
    1. media.metadata.asin - Direct ASIN from ABS metadata
    2. Folder path - Parse from folder name
    3. File names - Parse from audio file names

    Args:
        item: ABS library item dict from API

    Returns:
        AsinSource if found, None otherwise
    """
    # 1. Check ABS metadata first (most reliable)
    metadata = item.get("media", {}).get("metadata", {})
    asin = metadata.get("asin")
    if asin and is_valid_asin(asin):
        return AsinSource(asin=asin, source="metadata")

    # 2. Try folder path
    folder_path = item.get("path", "")
    if folder_path:
        # Get just the folder name (last component)
        folder_name = folder_path.rstrip("/").split("/")[-1]
        result = extract_asin_with_source(folder_name, "folder_name")
        if result:
            return result

    # 3. Try library files (audio file names)
    library_files = item.get("libraryFiles", [])
    for lf in library_files:
        file_name = lf.get("metadata", {}).get("filename", "")
        if not file_name:
            continue
        # Only check audio files
        if file_name.lower().endswith(AUDIO_EXTENSIONS):
            result = extract_asin_with_source(file_name, "file_name")
            if result:
                return result

    return None


def extract_all_asins(text: str) -> list[str]:
    """Extract all ASINs from text (for duplicate detection).

    Unlike extract_asin() which returns first match, this finds all.
    Useful for detecting multiple ASINs in a path or description.

    Args:
        text: Text to search

    Returns:
        List of unique ASINs found (preserves order of first occurrence)
    """
    if not text:
        return []

    seen: set[str] = set()
    results: list[str] = []

    for pattern in ASIN_PATTERNS:
        for match in pattern.finditer(text):
            asin = match.group(1)
            if asin not in seen:
                seen.add(asin)
                results.append(asin)

    return results


# =============================================================================
# Phase 3: Enhanced ASIN Resolution
# =============================================================================
# See docs/audiobookshelf/UNKNOWN_ASIN_HANDLING.md Phase 3 for design details.
#
# Resolution cascade (priority order):
#   1. Folder name - already parsed by caller, but try again with patterns
#   2. File names - check audio file names within the folder
#   3. metadata.json - check sidecar files for ASIN field


@dataclass
class AsinResolution:
    """Result of ASIN resolution from multiple sources.

    Attributes:
        asin: Resolved ASIN or None if not found
        source: Where the ASIN was found ("folder", "filename", "metadata", "unknown")
        source_detail: Additional detail (e.g., which file contained the ASIN)
    """

    asin: str | None
    source: str
    source_detail: str | None = None

    @property
    def found(self) -> bool:
        """Whether an ASIN was successfully resolved."""
        return self.asin is not None


def resolve_asin_from_folder(
    folder: Path,
    parsed_asin: str | None = None,
) -> AsinResolution:
    """Try to resolve ASIN from multiple sources within a folder.

    This is Phase 3 of the unknown ASIN handling - we try harder to find
    an ASIN before giving up and classifying as unknown.

    Resolution cascade (stops at first match):
        1. Folder name - use parsed ASIN if provided, else re-extract
        2. File names - check audio file names for embedded ASIN
        3. metadata.json - check sidecar files for ASIN field

    Args:
        folder: Path to the folder to search
        parsed_asin: ASIN already parsed from folder name (optimization)

    Returns:
        AsinResolution with ASIN and source info, or source="unknown" if not found

    Examples:
        >>> resolve_asin_from_folder(Path("/staging/Book {ASIN.B0123456789}"))
        AsinResolution(asin='B0123456789', source='folder', ...)

        >>> resolve_asin_from_folder(Path("/staging/Book"))  # has B0123456789.m4b inside
        AsinResolution(asin='B0123456789', source='filename', source_detail='B0123456789.m4b')
    """
    # 1. Check parsed ASIN from folder name (fastest path)
    if parsed_asin and is_valid_asin(parsed_asin):
        return AsinResolution(asin=parsed_asin, source="folder", source_detail=folder.name)

    # 2. Try extracting from folder name again (in case parse missed it)
    folder_asin = extract_asin(folder.name)
    if folder_asin:
        return AsinResolution(asin=folder_asin, source="folder", source_detail=folder.name)

    # 3. Check file names within folder
    if folder.is_dir():
        for f in folder.iterdir():
            if not f.is_file():
                continue

            # Only check audio files for ASIN in filename
            if f.suffix.lower() in AUDIO_EXTENSIONS:
                file_asin = extract_asin(f.name)
                if file_asin:
                    logger.debug(
                        "Resolved ASIN %s from filename: %s",
                        file_asin,
                        f.name,
                    )
                    return AsinResolution(
                        asin=file_asin,
                        source="filename",
                        source_detail=f.name,
                    )

        # 4. Check metadata.json sidecars
        for meta_file in folder.glob("*.metadata.json"):
            asin = _extract_asin_from_metadata_file(meta_file)
            if asin:
                logger.debug(
                    "Resolved ASIN %s from metadata file: %s",
                    asin,
                    meta_file.name,
                )
                return AsinResolution(
                    asin=asin,
                    source="metadata",
                    source_detail=meta_file.name,
                )

        # Also check for plain "metadata.json" (common pattern)
        plain_metadata = folder / "metadata.json"
        if plain_metadata.exists():
            asin = _extract_asin_from_metadata_file(plain_metadata)
            if asin:
                logger.debug("Resolved ASIN %s from metadata.json", asin)
                return AsinResolution(
                    asin=asin,
                    source="metadata",
                    source_detail="metadata.json",
                )

    # No ASIN found anywhere
    return AsinResolution(asin=None, source="unknown")


def _extract_asin_from_metadata_file(meta_file: Path) -> str | None:
    """Extract ASIN from a metadata JSON file.

    Checks common field names: asin, audible_asin, ASIN, audibleAsin

    Args:
        meta_file: Path to JSON metadata file

    Returns:
        ASIN if found and valid, None otherwise
    """
    try:
        data = json.loads(meta_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        logger.debug("Failed to read metadata file %s: %s", meta_file, e)
        return None

    # Check common ASIN field names
    for field in ("asin", "audible_asin", "ASIN", "audibleAsin", "audible"):
        value = data.get(field)
        if value and isinstance(value, str) and is_valid_asin(value):
            return str(value)  # Explicit str() for mypy

    # Also check nested structures (e.g., {"audible": {"asin": "..."}})
    audible_data = data.get("audible")
    if isinstance(audible_data, dict):
        asin = audible_data.get("asin")
        if asin and isinstance(asin, str) and is_valid_asin(asin):
            return str(asin)  # Explicit str() for mypy

    return None


# =============================================================================
# In-memory ASIN index for duplicate detection
# =============================================================================


@dataclass
class AsinEntry:
    """Entry in the in-memory ASIN index."""

    asin: str
    path: str  # Host path to the book folder
    library_item_id: str
    title: str
    author: str | None


def build_asin_index(
    client: AbsClient,
    library_id: str,
) -> dict[str, AsinEntry]:
    """Build in-memory ASIN index from ABS library.

    Fetches all items from ABS (cached per session) and builds a dict
    for O(1) ASIN lookups. This replaces SQLite for duplicate detection.

    Args:
        client: AbsClient instance (will use cached items if available)
        library_id: ABS library ID to index

    Returns:
        Dict mapping ASIN to AsinEntry for all books with ASINs
    """
    items = client.get_library_items_cached(library_id)
    index: dict[str, AsinEntry] = {}
    no_asin_count = 0

    for item in items:
        # Get ASIN from the item (metadata, folder name, or file name)
        asin = item.asin  # AbsLibraryItem already has this parsed

        # If not in metadata, try extracting from path
        if not asin:
            asin = extract_asin(item.path)

        if not asin:
            no_asin_count += 1
            continue

        # Skip if we've seen this ASIN (keep first occurrence)
        if asin in index:
            logger.debug(f"Duplicate ASIN {asin} found, keeping first at {index[asin].path}")
            continue

        index[asin] = AsinEntry(
            asin=asin,
            path=item.path,
            library_item_id=item.id,
            title=item.title,
            author=item.author_name,
        )

    logger.info(f"Built ASIN index: {len(index)} books with ASIN, {no_asin_count} without")
    return index


def asin_exists(
    asin_index: dict[str, AsinEntry],
    asin: str,
) -> tuple[bool, str | None]:
    """Check if ASIN exists in the index.

    Args:
        asin_index: Pre-built ASIN index from build_asin_index()
        asin: ASIN to look up

    Returns:
        Tuple of (exists: bool, path: str | None)
    """
    entry = asin_index.get(asin)
    if entry:
        return True, entry.path
    return False, None
