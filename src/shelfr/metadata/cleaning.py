"""
Metadata cleaning facade.

Re-exports cleaning functions from shelfr.utils.naming for metadata module
consumers. This provides a single import point for normalization and filtering.

Design:
- This is a FACADE, not a duplicate - all logic lives in utils.naming
- Metadata consumers import from here instead of utils.naming directly
- Allows future migration of cleaning logic without breaking imports

Usage:
    from shelfr.metadata.cleaning import filter_title, filter_series

    clean_title = filter_title(raw_title, naming_config=cfg)
"""

from __future__ import annotations

# Re-export cleaning functions from utils.naming
# These are the functions most commonly used by metadata code
from shelfr.utils.naming import (
    # Normalization
    clean_series_name,
    # String utilities
    cleanup_string,
    # MediaInfo extraction
    extract_non_authors_from_mediainfo,
    extract_translators_from_mediainfo,
    # Author filtering
    filter_author,
    filter_authors,
    filter_authors_with_mediainfo,
    # Text filtering
    filter_series,
    filter_subtitle,
    filter_title,
    normalize_audnex_book,
    normalize_position,
    # Series resolution
    parse_series_from_libation_path,
    parse_series_from_title,
    resolve_series,
    sanitize_filename,
    transliterate_text,
    truncate_filename,
)

__all__ = [
    # Normalization
    "clean_series_name",
    # String utilities
    "cleanup_string",
    # MediaInfo extraction
    "extract_non_authors_from_mediainfo",
    "extract_translators_from_mediainfo",
    # Author filtering
    "filter_author",
    "filter_authors",
    "filter_authors_with_mediainfo",
    # Text filtering
    "filter_series",
    "filter_subtitle",
    "filter_title",
    "normalize_audnex_book",
    "normalize_position",
    # Series resolution
    "parse_series_from_libation_path",
    "parse_series_from_title",
    "resolve_series",
    "sanitize_filename",
    "transliterate_text",
    "truncate_filename",
]
