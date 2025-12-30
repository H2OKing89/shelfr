"""
Filename sanitization and truncation for MAM compliance.

MAM has a 225-character limit on filenames/paths.

This module provides a unified API for all naming operations:
- Author role detection and filtering
- Title/series normalization (including Audnex swap detection)
- Filename filtering and sanitization
- MAM path building with truncation
- Series parsing from various sources

All public functions are re-exported from submodules for backward compatibility.
"""

from __future__ import annotations

from pathlib import Path

# Re-export all public symbols from submodules
from shelfr.utils.naming.authors import (
    VolumeInfo,
    extract_translator,
    filter_authors,
    is_author_role,
)
from shelfr.utils.naming.constants import (
    ILLEGAL_CHARS_PATTERN,
    MAM_MAX_FILENAME_LENGTH,
    MAM_MAX_PATH_LENGTH,
    MIN_SERIES_LENGTH,
    NORMALIZE_MAP,
    VOLUME_ALIASES,
)
from shelfr.utils.naming.filters import (
    extract_non_authors_from_mediainfo,
    extract_translators_from_mediainfo,
    filter_author,
    filter_authors_with_mediainfo,
    filter_series,
    filter_subtitle,
    filter_title,
    inherit_the_prefix,
    sanitize_filename,
)
from shelfr.utils.naming.mam_paths import (
    build_mam_file_name,
    build_mam_folder_name,
    build_mam_path,
)
from shelfr.utils.naming.normalization import (
    clean_series_name,
    detect_swapped_title_subtitle,
    extract_arc_name,
    extract_series_from_title,
    normalize_audnex_book,
)
from shelfr.utils.naming.series_parsing import (
    parse_series_from_libation_path,
    parse_series_from_title,
    resolve_series,
)
from shelfr.utils.naming.string_utils import (
    cleanup_string,
    transliterate_text,
    truncate_filename,
)
from shelfr.utils.naming.volume_parsing import (
    extract_volume_number,
    format_volume_number,
    normalize_position,
    parse_volume_notation,
)

# =============================================================================
# Utility Functions (kept at top level for compatibility)
# =============================================================================


def build_release_dirname(
    author: str | None,
    title: str,
    year: str | None = None,
    series: str | None = None,
    series_position: str | None = None,
) -> str:
    """
    Build a standardized directory name for a release.

    Format options (in order of completeness):
    - "Author - Series #N - Title (Year)"
    - "Author - Title (Year)"
    - "Author - Title"
    - "Title"
    """
    parts = []

    # Author
    if author:
        parts.append(sanitize_filename(author))

    # Series info
    if series and series_position:
        series_part = f"{sanitize_filename(series)} #{series_position}"
        parts.append(series_part)
    elif series:
        parts.append(sanitize_filename(series))

    # Title (possibly with year)
    if title:
        title_clean = sanitize_filename(title)
        if year:
            title_clean = f"{title_clean} ({year})"
        parts.append(title_clean)

    if not parts:
        return "unknown_release"

    return " - ".join(parts)


def ensure_unique_name(name: str, existing: set[str]) -> str:
    """
    Ensure name is unique by appending counter if needed.

    Args:
        name: Proposed name
        existing: Set of already-used names

    Returns:
        Unique name (possibly with " (2)", " (3)", etc. suffix)
    """
    if name not in existing:
        return name

    path = Path(name)
    base = path.stem
    ext = path.suffix

    counter = 2
    while True:
        new_name = f"{base} ({counter}){ext}"
        if new_name not in existing:
            return new_name
        counter += 1


__all__ = [
    # Authors module
    "VolumeInfo",
    "extract_translator",
    "filter_authors",
    "is_author_role",
    # Constants module
    "ILLEGAL_CHARS_PATTERN",
    "MAM_MAX_FILENAME_LENGTH",
    "MAM_MAX_PATH_LENGTH",
    "MIN_SERIES_LENGTH",
    "NORMALIZE_MAP",
    "VOLUME_ALIASES",
    # Filters module
    "extract_non_authors_from_mediainfo",
    "extract_translators_from_mediainfo",
    "filter_author",
    "filter_authors_with_mediainfo",
    "filter_series",
    "filter_subtitle",
    "filter_title",
    "inherit_the_prefix",
    "sanitize_filename",
    # MAM paths module
    "build_mam_file_name",
    "build_mam_folder_name",
    "build_mam_path",
    # Normalization module
    "clean_series_name",
    "detect_swapped_title_subtitle",
    "extract_arc_name",
    "extract_series_from_title",
    "normalize_audnex_book",
    # Series parsing module
    "parse_series_from_libation_path",
    "parse_series_from_title",
    "resolve_series",
    # String utils module
    "cleanup_string",
    "transliterate_text",
    "truncate_filename",
    # Volume parsing module
    "extract_volume_number",
    "format_volume_number",
    "normalize_position",
    "parse_volume_notation",
    # Utility functions
    "build_release_dirname",
    "ensure_unique_name",
]
