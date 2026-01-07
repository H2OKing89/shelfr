"""
Metadata fetching from Audnex API and MediaInfo.

Audnex API: https://api.audnex.us
- GET /books/{asin} - Get book metadata by ASIN
- GET /authors/{asin} - Get author info

MediaInfo: Command-line tool for technical metadata
- mediainfo --Output=JSON <file>

MAM JSON: Fast fillout format for MAM uploads
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

# Provider system - pluggable metadata providers
from shelfr.metadata.aggregator import (
    AggregatedResult as AggregatedResult,
)
from shelfr.metadata.aggregator import (
    FieldConflict as FieldConflict,
)
from shelfr.metadata.aggregator import (
    MetadataAggregator as MetadataAggregator,
)
from shelfr.metadata.audnex import (
    _fetch_audnex_book_region as _fetch_audnex_book_region,
)
from shelfr.metadata.audnex import (
    _fetch_audnex_chapters_region as _fetch_audnex_chapters_region,
)

# Audnex API client - book, author, and chapter metadata
from shelfr.metadata.audnex import (
    fetch_audnex_author as fetch_audnex_author,
)
from shelfr.metadata.audnex import (
    fetch_audnex_book as fetch_audnex_book,
)
from shelfr.metadata.audnex import (
    fetch_audnex_chapters as fetch_audnex_chapters,
)
from shelfr.metadata.audnex import (
    save_audnex_json as save_audnex_json,
)

# Cache - metadata caching layer
from shelfr.metadata.cache import (
    CachedResult as CachedResult,
)
from shelfr.metadata.cache import (
    CacheUnavailableError as CacheUnavailableError,
)
from shelfr.metadata.cache import (
    FileCache as FileCache,
)
from shelfr.metadata.cache import (
    MetadataCache as MetadataCache,
)
from shelfr.metadata.cache import (
    NoOpCache as NoOpCache,
)
from shelfr.metadata.cache import (
    get_default_cache as get_default_cache,
)
from shelfr.metadata.cache import (
    make_cache_key as make_cache_key,
)

# Cleaning facade - re-exports from utils.naming
from shelfr.metadata.cleaning import (
    filter_author as filter_author,
)
from shelfr.metadata.cleaning import (
    filter_authors as filter_authors,
)
from shelfr.metadata.cleaning import (
    filter_series as filter_series,
)
from shelfr.metadata.cleaning import (
    filter_subtitle as filter_subtitle,
)
from shelfr.metadata.cleaning import (
    filter_title as filter_title,
)
from shelfr.metadata.cleaning import (
    normalize_audnex_book as normalize_audnex_book,
)
from shelfr.metadata.cleaning import (
    resolve_series as resolve_series,
)
from shelfr.metadata.cleaning import (
    transliterate_text as transliterate_text,
)

# Exporters - convert aggregated metadata to output formats
from shelfr.metadata.exporters import (
    JsonExporter as JsonExporter,
)
from shelfr.metadata.exporters import (
    MetadataExporter as MetadataExporter,
)
from shelfr.metadata.exporters import (
    get_exporter as get_exporter,
)
from shelfr.metadata.exporters import (
    list_exporters as list_exporters,
)

# Formatting - BBCode and HTML conversion
from shelfr.metadata.formatting import (
    render_bbcode_description as render_bbcode_description,
)
from shelfr.metadata.formatting.bbcode import (
    _convert_newlines_for_mam as _convert_newlines_for_mam,
)
from shelfr.metadata.formatting.bbcode import (
    _format_release_date as _format_release_date,
)
from shelfr.metadata.formatting.bbcode import (
    _parse_chapters_from_audnex as _parse_chapters_from_audnex,
)
from shelfr.metadata.formatting.html import (
    _clean_html as _clean_html,
)
from shelfr.metadata.formatting.html import (
    html_to_bbcode as html_to_bbcode,
)

# MAM categories - genre keyword sets and category inference
from shelfr.metadata.mam.categories import (
    FICTION_GENRE_KEYWORDS as FICTION_GENRE_KEYWORDS,
)
from shelfr.metadata.mam.categories import (
    NONFICTION_GENRE_KEYWORDS as NONFICTION_GENRE_KEYWORDS,
)
from shelfr.metadata.mam.categories import (
    _get_audiobook_category as _get_audiobook_category,
)
from shelfr.metadata.mam.categories import (
    _infer_fiction_or_nonfiction as _infer_fiction_or_nonfiction,
)
from shelfr.metadata.mam.categories import (
    _map_genres_to_categories as _map_genres_to_categories,
)

# MAM JSON builder - build and save MAM fast-fillout JSON
from shelfr.metadata.mam.json_builder import (
    _build_series_list as _build_series_list,
)
from shelfr.metadata.mam.json_builder import (
    _get_mediainfo_string as _get_mediainfo_string,
)
from shelfr.metadata.mam.json_builder import (
    build_mam_json as build_mam_json,
)
from shelfr.metadata.mam.json_builder import (
    generate_mam_json_for_release as generate_mam_json_for_release,
)
from shelfr.metadata.mam.json_builder import (
    save_mam_json as save_mam_json,
)

# Re-exports from submodules (maintains backward compatibility)
# MediaInfo extraction - technical metadata, audio format detection
from shelfr.metadata.mediainfo import (
    AudioFormat as AudioFormat,
)
from shelfr.metadata.mediainfo import (
    detect_audio_format as detect_audio_format,
)
from shelfr.metadata.mediainfo import (
    detect_audio_format_from_file as detect_audio_format_from_file,
)
from shelfr.metadata.mediainfo import (
    run_mediainfo as run_mediainfo,
)
from shelfr.metadata.mediainfo import (
    save_mediainfo_json as save_mediainfo_json,
)
from shelfr.metadata.mediainfo.extractor import (
    _extract_audio_info as _extract_audio_info,
)
from shelfr.metadata.mediainfo.extractor import (
    _format_chapter_time as _format_chapter_time,
)
from shelfr.metadata.mediainfo.extractor import (
    _format_duration as _format_duration,
)
from shelfr.metadata.mediainfo.extractor import (
    _parse_chapters_from_mediainfo as _parse_chapters_from_mediainfo,
)

# Shared types
from shelfr.metadata.models import Chapter as Chapter

# Orchestration - high-level fetch and export functions
from shelfr.metadata.orchestration import (
    export_metadata_async as export_metadata_async,
)
from shelfr.metadata.orchestration import (
    fetch_all_metadata_legacy as fetch_all_metadata_legacy,
)
from shelfr.metadata.orchestration import (
    fetch_metadata_async as fetch_metadata_async,
)
from shelfr.metadata.orchestration import (
    fetch_metadata_legacy as fetch_metadata_legacy,
)
from shelfr.metadata.orchestration import (
    save_metadata_files_legacy as save_metadata_files_legacy,
)
from shelfr.metadata.providers import (
    AudnexProvider as AudnexProvider,
)
from shelfr.metadata.providers import (
    FieldName as FieldName,
)
from shelfr.metadata.providers import (
    IdType as IdType,
)
from shelfr.metadata.providers import (
    LookupContext as LookupContext,
)
from shelfr.metadata.providers import (
    MetadataProvider as MetadataProvider,
)
from shelfr.metadata.providers import (
    MockProvider as MockProvider,
)
from shelfr.metadata.providers import (
    ProviderKind as ProviderKind,
)
from shelfr.metadata.providers import (
    ProviderRegistry as ProviderRegistry,
)
from shelfr.metadata.providers import (
    ProviderResult as ProviderResult,
)
from shelfr.metadata.providers import (
    default_registry as default_registry,
)

# Canonical schemas - unified metadata types
from shelfr.metadata.schemas import (
    CanonicalMetadata as CanonicalMetadata,
)
from shelfr.metadata.schemas import (
    Genre as Genre,
)
from shelfr.metadata.schemas import (
    Person as Person,
)
from shelfr.metadata.schemas import (
    Series as Series,
)

# Backward compatibility alias (internal code used underscore prefix)
_html_to_bbcode = html_to_bbcode

logger = logging.getLogger(__name__)


# =============================================================================
# Combined Operations (Delegate to orchestration.py)
# =============================================================================


def fetch_metadata(
    asin: str | None = None,
    m4b_path: Path | None = None,
    *,
    use_cache: bool = True,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None, str | None]:
    """
    Fetch Audnex book metadata, chapters, and MediaInfo without saving.

    Uses AudnexProvider with caching by default for faster repeated lookups
    and rate limiting to avoid API abuse.

    Args:
        asin: Audible ASIN (None to skip Audnex)
        m4b_path: Path to m4b file (None to skip MediaInfo)
        use_cache: If True, use cached provider (default: True)

    Returns:
        Tuple of (audnex_data, mediainfo_data, audnex_chapters, region).
        Any may be None on error. Region is the Audible region where ASIN was found.
    """
    return fetch_metadata_legacy(asin=asin, m4b_path=m4b_path, use_cache=use_cache)


def save_metadata_files(
    output_dir: Path,
    audnex_data: dict[str, Any] | None = None,
    mediainfo_data: dict[str, Any] | None = None,
) -> None:
    """
    Save metadata to JSON files in output directory.

    Args:
        output_dir: Directory to save JSON files
        audnex_data: Audnex data to save (skipped if None)
        mediainfo_data: MediaInfo data to save (skipped if None)
    """
    save_metadata_files_legacy(output_dir, audnex_data=audnex_data, mediainfo_data=mediainfo_data)


def fetch_all_metadata(
    asin: str | None,
    m4b_path: Path | None,
    output_dir: Path | None = None,
    *,
    save_intermediate: bool = False,
    use_cache: bool = True,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None, str | None]:
    """
    Fetch Audnex book data, chapters, and MediaInfo, optionally saving intermediate files.

    By default, this function only fetches metadata without saving files.
    Set save_intermediate=True to write audnex.json and mediainfo.json to output_dir.

    Args:
        asin: Audible ASIN (None to skip Audnex)
        m4b_path: Path to m4b file (None to skip MediaInfo)
        output_dir: Directory to save JSON files (only used if save_intermediate=True)
        save_intermediate: If True, save audnex.json and mediainfo.json files
        use_cache: If True, use cached provider (default: True)

    Returns:
        Tuple of (audnex_data, mediainfo_data, audnex_chapters, region).
        Any may be None on error. Region is the Audible region where ASIN was found.
    """
    return fetch_all_metadata_legacy(
        asin=asin,
        m4b_path=m4b_path,
        output_dir=output_dir,
        save_intermediate=save_intermediate,
        use_cache=use_cache,
    )
