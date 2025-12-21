"""
Series resolution and parsing from multiple sources.

Provides functions to extract series information from:
- Audnex API seriesPrimary data (highest confidence)
- Libation folder structure (reliable)
- Title heuristics (fallback)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mamfast.models import SeriesInfo

from mamfast.utils.naming.constants import (
    SERIES_FROM_TITLE_PATTERNS,
    VOL_FROM_NAME_PATTERN,
)
from mamfast.utils.naming.normalization import clean_series_name

logger = logging.getLogger(__name__)


def parse_series_from_title(title: str) -> tuple[str, str] | None:
    """
    Extract series name and position from a title using heuristics.

    Tries patterns like:
    - "I'm the Evil Lord of an Intergalactic Empire!, Vol. 5"
    - "Black Summoner, Vol. 4"
    - "Some Light Novel: Volume 3.5"
    - "Series Name Book 7"

    Args:
        title: The book title to parse

    Returns:
        Tuple of (series_name, position) if found, None otherwise
    """
    if not title:
        return None

    title = title.strip()

    for pattern in SERIES_FROM_TITLE_PATTERNS:
        match = pattern.match(title)
        if match:
            series = match.group("series").strip().rstrip(",.:;")
            num = match.group("num")

            # Basic validation: series should be meaningful
            if len(series) < 2:
                continue

            # Don't match if "series" is just a common word
            if series.lower() in ("the", "a", "an", "book", "volume", "vol"):
                continue

            return (series, num)

    return None


def parse_series_from_libation_path(
    libation_path: Path | None,
    book_folder_name: str | None = None,
) -> tuple[str, str | None] | None:
    """
    Extract series info from Libation's folder structure.

    Libation organizes books as:
        Author/Series/BookTitle vol_XX (Year) (Author) {ASIN.XXX} [Source]/

    If there's no series folder, the structure is:
        Author/BookTitle (Year) (Author) {ASIN.XXX} [Source]/

    This function scans upward from the book folder, checking each parent
    to see if it looks like a series folder. This handles potential future
    structures like "Author/Universe/Series/Book".

    Args:
        libation_path: Full path to the book folder
        book_folder_name: The innermost folder name (optional, extracted from path if not provided)

    Returns:
        Tuple of (series_name, position) if series folder exists, None otherwise
    """
    if not libation_path:
        return None

    # Get path parts
    parts = list(libation_path.parts)

    # We need at least Author/Book (2 levels) to have any series detection
    if len(parts) < 2:
        return None

    # The innermost folder is the book folder
    book_folder = book_folder_name or parts[-1]

    def is_series_folder(candidate: str) -> bool:
        """Check if a folder name looks like a series folder (not book or author)."""
        # Series folders typically:
        # - Don't have ASIN tags
        # - Don't have year in parens
        # - Don't have vol_XX
        # - Don't appear as the author in the book folder name
        series_indicators = [
            "{ASIN." not in candidate,
            "[ASIN." not in candidate,
            not re.search(r"\(\d{4}\)", candidate),  # No (Year)
            "vol_" not in candidate.lower(),
        ]

        # Check if candidate is the author folder
        # Libation format includes "(Author)" in book folder name
        author_pattern = re.compile(
            rf"\({re.escape(candidate)}\)",
            re.IGNORECASE,
        )
        is_author = bool(author_pattern.search(book_folder))

        return all(series_indicators) and not is_author

    # Scan upward from parent toward root, find first series-like folder
    # Start at parent (index -2) and scan up at most 3 levels, but never below index 0
    # This avoids accidentally including the book folder itself (index -1)
    start_idx = len(parts) - 2  # Parent folder
    end_idx = max(len(parts) - 5, 0)  # At most 3 levels up, but not below 0

    for idx in range(start_idx, end_idx - 1, -1):
        candidate = parts[idx]

        # Skip very short names (likely mount points or root dirs)
        if len(candidate) < 2:
            continue

        # Skip common library root folder names and patterns
        # Use lowercase for comparison
        lower_candidate = candidate.lower()

        # Exact matches for common root/library folders
        # Also includes common grouping folders that aren't series names
        common_roots = {
            "audiobooks",
            "audiobook",
            "library",
            "books",
            "media",
            "audio",
            "data",
            "libation",
            "import",
            "incoming",
            "downloads",
            "completed",
            "staging",
            "upload",
            # Common grouping folders that could be mistaken for series
            "light novels",
            "light novel",
            "fiction",
            "non-fiction",
            "nonfiction",
            "single books",
            "standalone",
            "series",
            "collections",
            "complete",
        }
        if lower_candidate in common_roots:
            continue

        # Pattern matches for compound folder names
        # Skip folders containing these as part of their name
        skip_patterns = (
            "audiobook",  # matches "audiobook-import", "audiobooks_new", etc.
            "library",
            "import",
            "download",
            "staging",
            "incoming",
        )
        if any(pattern in lower_candidate for pattern in skip_patterns):
            continue

        if is_series_folder(candidate):
            series_name = candidate.strip()

            # Try to extract volume from book folder name
            position = None
            vol_match = VOL_FROM_NAME_PATTERN.search(book_folder)
            if vol_match:
                position = vol_match.group(1)

            return (series_name, position)

    return None


def resolve_series(
    audnex_data: dict[str, Any] | None = None,
    libation_path: Path | None = None,
    title: str | None = None,
) -> SeriesInfo | None:
    """
    Resolve series information from multiple sources with fallback.

    Resolution order (highest to lowest trust):
    1. Audnex seriesPrimary (authoritative, confidence=1.0)
    2. Libation folder structure (reliable, confidence=0.9)
    3. Title heuristics (fallback, confidence=0.5)

    If Audnex provides series name but no position, lower-confidence sources
    are checked to fill in the missing position.

    Args:
        audnex_data: Audnex API response dict (may contain seriesPrimary)
        libation_path: Path to the book folder in Libation library
        title: Book title for heuristic extraction

    Returns:
        SeriesInfo object if series resolved, None if no source provides series
    """
    # Import here to avoid circular imports
    from mamfast.models import SeriesInfo, SeriesSource

    # Helper to get position from Libation
    def get_libation_position() -> str | None:
        if libation_path:
            libation_result = parse_series_from_libation_path(libation_path)
            if libation_result:
                return libation_result[1]  # position
        return None

    # Helper to get position from title heuristics
    def get_title_position() -> str | None:
        if title:
            title_result = parse_series_from_title(title)
            if title_result:
                return title_result[1]  # position
        return None

    # 1. Try Audnex seriesPrimary (authoritative)
    if audnex_data:
        series_primary = audnex_data.get("seriesPrimary")
        if series_primary and isinstance(series_primary, dict):
            series_dict: dict[str, object] = series_primary
            name_value = series_dict.get("name")
            if name_value and isinstance(name_value, str):
                # Clean the series name
                cleaned_name = clean_series_name(name_value, title)
                if cleaned_name:
                    position_value = series_dict.get("position")
                    position: str | None = str(position_value) if position_value else None
                    # If Audnex has no position, try to fill from other sources
                    if not position:
                        position = get_libation_position() or get_title_position()
                    return SeriesInfo(
                        name=cleaned_name,
                        position=position,
                        source=SeriesSource.AUDNEX,
                        confidence=1.0,
                    )

    # 2. Try Libation folder structure
    if libation_path:
        libation_result = parse_series_from_libation_path(libation_path)
        if libation_result:
            series_name, position = libation_result
            # Clean the series name
            cleaned_name = clean_series_name(series_name, title)
            if cleaned_name:
                return SeriesInfo(
                    name=cleaned_name,
                    position=position,
                    source=SeriesSource.LIBATION,
                    confidence=0.9,
                )

    # 3. Try title heuristics (last resort)
    if title:
        title_result = parse_series_from_title(title)
        if title_result:
            series_name, position = title_result
            # Clean the series name
            cleaned_name = clean_series_name(series_name, title)
            if cleaned_name:
                return SeriesInfo(
                    name=cleaned_name,
                    position=position,
                    source=SeriesSource.TITLE_HEURISTIC,
                    confidence=0.5,
                )

    # No series found from any source
    return None
