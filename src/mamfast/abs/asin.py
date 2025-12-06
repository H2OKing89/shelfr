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

Phase 4 adds mediainfo probe to extract ASIN from embedded file metadata.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mamfast.config import get_settings

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

        # 5. Check for _mamfast_resolved_asin.json (from abs-resolve-asins Phase 5)
        resolved_sidecar = folder / "_mamfast_resolved_asin.json"
        if resolved_sidecar.exists():
            asin = _extract_asin_from_metadata_file(resolved_sidecar)
            if asin:
                logger.debug("Resolved ASIN %s from _mamfast_resolved_asin.json", asin)
                return AsinResolution(
                    asin=asin,
                    source="resolved_sidecar",
                    source_detail="_mamfast_resolved_asin.json",
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
# Phase 4: mediainfo Probe for Embedded ASIN
# =============================================================================
# See docs/audiobookshelf/UNKNOWN_ASIN_HANDLING.md Phase 4 for design details.
#
# Audible files often have ASIN embedded in file metadata (atom tags).
# Common fields: asin, CDEK (which often equals ASIN)


def _get_mediainfo_binary() -> str | None:
    """Get mediainfo binary path from config, checking availability.

    Uses the configured mediainfo.binary from settings. Returns the binary
    path if available (either in PATH or as absolute path), None otherwise.

    Falls back to checking for "mediainfo" in PATH if config is unavailable.

    Returns:
        Binary path if available, None if not found
    """
    # Try to get binary name from config, fall back to default
    binary = "mediainfo"
    try:
        settings = get_settings()
        binary = settings.mediainfo.binary
    except Exception:
        # Config unavailable (e.g., in tests without config file)
        # Fall back to default binary name
        logger.debug("Config unavailable, using default mediainfo binary")

    # If it's an absolute path, check it exists
    if Path(binary).is_absolute():
        if Path(binary).exists():
            return binary
        logger.debug("Configured mediainfo binary not found: %s", binary)
        return None

    # Otherwise check if it's in PATH
    found = shutil.which(binary)
    if found:
        return found

    logger.debug("mediainfo binary '%s' not found in PATH", binary)
    return None


def extract_asin_from_mediainfo(
    audio_file: Path,
    binary: str | None = None,
    timeout: int = 30,
) -> str | None:
    """Extract ASIN from audio file metadata using mediainfo.

    Audible audiobooks embed ASIN in various metadata fields:
    - "asin" tag (direct)
    - "CDEK" tag (often equals ASIN)

    Args:
        audio_file: Path to audio file to probe
        binary: Mediainfo binary path (uses config if not provided)
        timeout: Timeout in seconds (default: 30)

    Returns:
        ASIN if found and valid, None otherwise
    """
    if not audio_file.exists() or not audio_file.is_file():
        return None

    # Get binary from config if not provided
    if binary is None:
        binary = _get_mediainfo_binary()
        if binary is None:
            return None

    try:
        result = subprocess.run(
            [binary, "--Output=JSON", str(audio_file)],
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        )
        data = json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        logger.warning("mediainfo timed out for: %s", audio_file.name)
        return None
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as e:
        logger.debug("Failed to run mediainfo on %s: %s", audio_file.name, e)
        return None

    # mediainfo JSON structure: {"media": {"track": [...]}}
    # General track contains metadata fields
    # ASIN can be at track level OR nested in track.extra dict
    media = data.get("media", {})
    tracks = media.get("track", [])

    # Normalize tracks to list - mediainfo sometimes returns single dict instead of list
    if tracks is None:
        tracks = []
    elif isinstance(tracks, dict):
        tracks = [tracks]
    elif not isinstance(tracks, list):
        logger.debug("Unexpected tracks type %s in mediainfo output", type(tracks).__name__)
        tracks = []

    for track in tracks:
        # Skip non-dict entries (defensive)
        if not isinstance(track, dict):
            continue

        # Check direct "asin" field (lowercase)
        # Check direct "asin" field (lowercase)
        asin = track.get("asin")
        if asin and isinstance(asin, str) and is_valid_asin(asin):
            return str(asin)  # Explicit cast for mypy

        # Check "CDEK" field (Audible internal, often equals ASIN)
        cdek = track.get("CDEK")
        if cdek and isinstance(cdek, str) and is_valid_asin(cdek):
            return str(cdek)  # Explicit cast for mypy

        # Check nested "extra" dict (common in m4b files)
        extra = track.get("extra")
        if isinstance(extra, dict):
            extra_asin = extra.get("asin")
            if extra_asin and isinstance(extra_asin, str) and is_valid_asin(extra_asin):
                logger.debug("Found ASIN in extra.asin: %s", extra_asin)
                return str(extra_asin)

            extra_cdek = extra.get("CDEK")
            if extra_cdek and isinstance(extra_cdek, str) and is_valid_asin(extra_cdek):
                logger.debug("Found ASIN in extra.CDEK: %s", extra_cdek)
                return str(extra_cdek)

        # Fallback: search all string values for ASIN pattern
        # This catches ASINs in unusual fields
        for key, value in track.items():
            if (
                isinstance(value, str)
                and value.startswith("B0")
                and len(value) == 10
                and is_valid_asin(value)
            ):
                logger.debug(
                    "Found ASIN in unexpected field '%s': %s",
                    key,
                    value,
                )
                return value

    return None


def resolve_asin_from_folder_with_mediainfo(
    folder: Path,
    parsed_asin: str | None = None,
) -> AsinResolution:
    """Enhanced ASIN resolution including mediainfo probe.

    This is Phase 4 - extends Phase 3 by also checking embedded file metadata.

    Resolution cascade (stops at first match):
        1. Folder name - use parsed ASIN if provided, else re-extract
        2. File names - check audio file names for embedded ASIN
        3. metadata.json - check sidecar files for ASIN field
        4. mediainfo - probe audio files for embedded metadata (if available)

    Args:
        folder: Path to the folder to search
        parsed_asin: ASIN already parsed from folder name (optimization)

    Returns:
        AsinResolution with ASIN and source info, or source="unknown" if not found
    """
    # First try Phase 3 resolution (fast, no subprocess)
    result = resolve_asin_from_folder(folder, parsed_asin)
    if result.found:
        return result

    # Phase 4: Try mediainfo probe as last resort
    # Get configured binary once to avoid repeated lookups
    mediainfo_binary = _get_mediainfo_binary()
    if mediainfo_binary is None:
        logger.debug("mediainfo not available, skipping probe")
        return result

    if not folder.is_dir():
        return result

    # Probe audio files for embedded ASIN
    for f in folder.iterdir():
        if not f.is_file():
            continue
        if f.suffix.lower() not in AUDIO_EXTENSIONS:
            continue

        asin = extract_asin_from_mediainfo(f, binary=mediainfo_binary)
        if asin:
            logger.info(
                "Resolved ASIN %s from embedded metadata: %s",
                asin,
                f.name,
            )
            return AsinResolution(
                asin=asin,
                source="mediainfo",
                source_detail=f.name,
            )

    return AsinResolution(asin=None, source="unknown")


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


# =============================================================================
# Phase 5: ABS Metadata Search for ASIN Resolution
# =============================================================================


@dataclass
class SearchMatch:
    """Result of matching a search result against folder metadata."""

    asin: str
    title: str
    author: str | None
    confidence: float  # 0.0 to 1.0
    language: str | None
    series: str | None
    sequence: str | None


def _normalize_for_matching(s: str) -> str:
    """Normalize a string for fuzzy matching.

    Removes common noise like volume numbers, punctuation, etc.
    """
    if not s:
        return ""

    result = s.lower()

    # Remove volume/book indicators
    result = re.sub(r"\b(vol\.?|volume|book|part)\s*\d+\b", "", result, flags=re.IGNORECASE)

    # Remove series suffixes like ", Book 1" from subtitle
    result = re.sub(r",\s*(book|vol\.?|volume)\s*\d+$", "", result, flags=re.IGNORECASE)

    # Remove punctuation except hyphens (important for titles like "Re:Zero")
    result = re.sub(r"[^\w\s-]", " ", result)

    # Collapse whitespace
    result = re.sub(r"\s+", " ", result).strip()

    return result


def match_search_results(
    results: list[dict[str, Any]],
    folder_title: str,
    folder_author: str | None = None,
    confidence_threshold: float = 0.75,
    prefer_english: bool = True,
) -> SearchMatch | None:
    """Find the best matching search result for a folder.

    Uses fuzzy matching to compare folder metadata against search results
    and returns the best match above the confidence threshold.

    Args:
        results: Search results from AbsClient.search_books()
        folder_title: Title extracted from folder name
        folder_author: Author extracted from folder name (optional)
        confidence_threshold: Minimum confidence (0-1) to accept a match
        prefer_english: If True, prefer English results over translations

    Returns:
        SearchMatch if a good match found, None otherwise
    """
    from mamfast.utils.fuzzy import similarity_ratio

    if not results:
        return None

    folder_title_norm = _normalize_for_matching(folder_title)
    folder_author_norm = _normalize_for_matching(folder_author or "")

    best_match: SearchMatch | None = None
    best_score = 0.0

    for result in results:
        result_title = result.get("title", "")
        result_author = result.get("author", "")
        result_asin = result.get("asin", "")
        result_language = result.get("language", "")

        # Skip results without valid ASIN
        if not result_asin or not is_valid_asin(result_asin):
            continue

        # Calculate title similarity
        result_title_norm = _normalize_for_matching(result_title)
        title_score = similarity_ratio(folder_title_norm, result_title_norm) / 100.0

        # Calculate author similarity (if we have author to compare)
        author_score = 1.0  # Default to perfect if no author to compare
        if folder_author_norm:
            result_author_norm = _normalize_for_matching(result_author)
            author_score = similarity_ratio(folder_author_norm, result_author_norm) / 100.0

        # Combined score (title weighted more heavily)
        combined_score = (title_score * 0.7) + (author_score * 0.3)

        # Bonus for English (if preferred)
        if prefer_english and result_language and result_language.lower() == "english":
            combined_score *= 1.05  # 5% bonus
            combined_score = min(combined_score, 1.0)  # Cap at 1.0

        # Penalty for non-English (to avoid Spanish translations, etc.)
        if prefer_english and result_language and result_language.lower() not in ("english", ""):
            combined_score *= 0.8  # 20% penalty

        logger.debug(
            f"Match candidate: {result_title!r} by {result_author!r} "
            f"(ASIN={result_asin}, lang={result_language}, score={combined_score:.2f})"
        )

        if combined_score > best_score:
            best_score = combined_score

            # Extract series info
            series_name = None
            series_seq = None
            series_list = result.get("series")
            if series_list and isinstance(series_list, list) and len(series_list) > 0:
                first_series = series_list[0]
                if isinstance(first_series, dict):
                    series_name = first_series.get("series")
                    series_seq = first_series.get("sequence")

            best_match = SearchMatch(
                asin=result_asin,
                title=result_title,
                author=result_author,
                confidence=combined_score,
                language=result_language,
                series=series_name,
                sequence=series_seq,
            )

    # Only return if above threshold
    if best_match and best_match.confidence >= confidence_threshold:
        logger.info(
            f"Best match: {best_match.title!r} (ASIN={best_match.asin}, "
            f"confidence={best_match.confidence:.2f})"
        )
        return best_match

    if best_match:
        logger.debug(
            f"Best match below threshold: {best_match.title!r} "
            f"(confidence={best_match.confidence:.2f} < {confidence_threshold})"
        )

    return None


def resolve_asin_via_abs_search(
    client: AbsClient,
    title: str,
    author: str | None = None,
    confidence_threshold: float = 0.75,
) -> AsinResolution:
    """Resolve ASIN by searching ABS metadata providers.

    This is a last-resort ASIN resolution method that queries Audible
    (via ABS) to find matching books. Makes a network call per invocation.

    Performance note: This function is opt-in for imports via --abs-search flag.
    By default, abs-import does NOT call this to avoid API rate limiting on
    large batches. For batch resolution of Unknown/ books, consider using
    the standalone abs-resolve-asins command with --write-sidecar.

    Args:
        client: AbsClient instance
        title: Book title to search for
        author: Author name (improves match accuracy)
        confidence_threshold: Minimum confidence (0-1) to accept a match

    Returns:
        AsinResolution with ASIN if found, source="abs_search"
    """
    try:
        results = client.search_books(title=title, author=author, provider="audible")
    except Exception as e:
        logger.warning(f"ABS search failed for {title!r}: {e}")
        return AsinResolution(asin=None, source="unknown")

    match = match_search_results(
        results,
        folder_title=title,
        folder_author=author,
        confidence_threshold=confidence_threshold,
    )

    if match:
        return AsinResolution(
            asin=match.asin,
            source="abs_search",
            source_detail=f"{match.title} (confidence={match.confidence:.0%})",
        )

    return AsinResolution(asin=None, source="unknown")
