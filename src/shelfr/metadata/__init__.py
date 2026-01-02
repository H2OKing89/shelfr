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

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from shelfr.config import get_settings
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
from shelfr.models import NormalizedBook
from shelfr.utils.naming import (
    extract_translators_from_mediainfo,
    filter_authors,
    filter_series,
    filter_subtitle,
    filter_title,
    normalize_audnex_book,
    resolve_series,
    transliterate_text,
)
from shelfr.utils.permissions import fix_ownership

if TYPE_CHECKING:
    from shelfr.models import AudiobookRelease

# Backward compatibility alias (internal code used underscore prefix)
_html_to_bbcode = html_to_bbcode

logger = logging.getLogger(__name__)


# =============================================================================
# Combined Operations
# =============================================================================


def fetch_metadata(
    asin: str | None = None,
    m4b_path: Path | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    """
    Fetch Audnex book metadata, chapters, and MediaInfo without saving.

    Args:
        asin: Audible ASIN (None to skip Audnex)
        m4b_path: Path to m4b file (None to skip MediaInfo)

    Returns:
        Tuple of (audnex_data, mediainfo_data, audnex_chapters), any may be None on error.
    """
    audnex_data = None
    mediainfo_data = None
    audnex_chapters = None

    if asin:
        audnex_data, _ = fetch_audnex_book(asin)  # Region not needed here
        # Also fetch chapter data from Audnex (authoritative source)
        audnex_chapters = fetch_audnex_chapters(asin)

    if m4b_path and m4b_path.exists():
        mediainfo_data = run_mediainfo(m4b_path)

    return audnex_data, mediainfo_data, audnex_chapters


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
    output_dir.mkdir(parents=True, exist_ok=True)

    if audnex_data:
        save_audnex_json(audnex_data, output_dir / "audnex.json")

    if mediainfo_data:
        save_mediainfo_json(mediainfo_data, output_dir / "mediainfo.json")


def fetch_all_metadata(
    asin: str | None,
    m4b_path: Path | None,
    output_dir: Path | None = None,
    *,
    save_intermediate: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    """
    Fetch Audnex book data, chapters, and MediaInfo, optionally saving intermediate files.

    By default, this function only fetches metadata without saving files.
    Set save_intermediate=True to write audnex.json and mediainfo.json to output_dir.

    Args:
        asin: Audible ASIN (None to skip Audnex)
        m4b_path: Path to m4b file (None to skip MediaInfo)
        output_dir: Directory to save JSON files (only used if save_intermediate=True)
        save_intermediate: If True, save audnex.json and mediainfo.json files

    Returns:
        Tuple of (audnex_data, mediainfo_data, audnex_chapters), any may be None on error.
    """
    audnex_data, mediainfo_data, audnex_chapters = fetch_metadata(asin=asin, m4b_path=m4b_path)

    if save_intermediate and output_dir:
        save_metadata_files(output_dir, audnex_data=audnex_data, mediainfo_data=mediainfo_data)

    return audnex_data, mediainfo_data, audnex_chapters


# =============================================================================
# MAM JSON Export
# =============================================================================

# Genre keywords that indicate Fiction (case-insensitive matching)
FICTION_GENRE_KEYWORDS = frozenset(
    [
        "fantasy",
        "fiction",
        "mystery",
        "thriller",
        "suspense",
        "romance",
        "horror",
        "sci-fi",
        "science fiction",
        "adventure",
        "detective",
        "crime",
        "western",
        "humor",
        "comedy",
        "drama",
        "erotica",
        "paranormal",
        "urban",
        "epic",
        "literary",
        "classics",
        "historical fiction",
        "contemporary",
        "dystopian",
        "fairy tales",
        "mythology",
        "legends",
        "anthologies",
        "short stories",
    ]
)

# Genre keywords that indicate Non-Fiction (case-insensitive matching)
NONFICTION_GENRE_KEYWORDS = frozenset(
    [
        "biography",
        "biographies",
        "memoir",
        "self-help",
        "business",
        "history",
        "science",
        "politics",
        "religion",
        "spirituality",
        "philosophy",
        "psychology",
        "health",
        "fitness",
        "cooking",
        "travel",
        "true crime",
        "education",
        "reference",
        "how-to",
        "guide",
        "self development",
        "personal development",
        "finance",
        "economics",
        "journalism",
        "essays",
        "nature",
        "technology",
        "computers",
    ]
)


def _infer_fiction_or_nonfiction(audnex_data: dict[str, Any]) -> int:
    """
    Infer whether a book is Fiction (1) or Non-Fiction (2).

    Audnex literatureType is unreliable, so we check genres first.
    Fiction keywords take priority since genre keywords like "fantasy"
    are unambiguous, while non-fiction keywords may appear in fiction
    (e.g., "historical fiction").

    Args:
        audnex_data: Audnex API response

    Returns:
        1 for Fiction, 2 for Non-Fiction
    """
    genres = audnex_data.get("genres", [])
    genre_names_lower = [g.get("name", "").lower() for g in genres]
    all_genre_text = " ".join(genre_names_lower)

    # Check for fiction indicators first (higher priority)
    # Use word boundary matching to avoid false positives (e.g., "urban" in "Suburban")
    for keyword in FICTION_GENRE_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", all_genre_text):
            return 1  # Fiction

    # Check for non-fiction indicators
    for keyword in NONFICTION_GENRE_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", all_genre_text):
            return 2  # Non-Fiction

    # Fallback to literatureType if genres don't give a clear signal
    lit_type = audnex_data.get("literatureType", "").lower()
    if lit_type == "fiction":
        return 1
    if lit_type in ("non-fiction", "nonfiction"):
        return 2

    # Default to Fiction (most audiobooks are fiction)
    return 1


def _get_audiobook_category(audnex_data: dict[str, Any], is_fiction: bool) -> str:
    """
    Determine the MAM audiobook category string from genres.

    Uses config/audiobook_categories.json mappings. Checks genre keywords
    against the appropriate map (fiction or nonfiction) and returns the
    first match. Falls back to default category if no match found.

    Note: Order of keywords in the JSON file matters (first match wins).
    This relies on Python 3.7+ dict insertion order preservation.
    More specific keywords (e.g., "urban fantasy") should appear before
    general ones (e.g., "fantasy") in the JSON file.

    Args:
        audnex_data: Audnex API response
        is_fiction: Whether the book is fiction (from _infer_fiction_or_nonfiction)

    Returns:
        MAM audiobook category string (e.g., "Audiobooks - Fantasy")
    """
    # Default fallback
    default_category = (
        "Audiobooks - General Fiction" if is_fiction else "Audiobooks - General Non-Fic"
    )

    try:
        settings = get_settings()
        categories = settings.categories
    except Exception:
        return default_category

    # Select the appropriate map based on fiction/nonfiction
    if is_fiction:
        category_map = categories.audiobook_fiction_map
        default_key = "fiction"
    else:
        category_map = categories.audiobook_nonfiction_map
        default_key = "nonfiction"

    # Get default from config
    default_category = categories.audiobook_defaults.get(default_key, default_category)

    # If no map loaded, return default
    if not category_map:
        return default_category

    # Build genre text for matching
    genres = audnex_data.get("genres", [])
    genre_names_lower = [g.get("name", "").lower() for g in genres]
    all_genre_text = " ".join(genre_names_lower)

    # Check each keyword in the map (order matters - first match wins)
    # Use word boundary matching to avoid false positives (e.g., "art" in "martial")
    for keyword, category in category_map.items():
        if re.search(rf"\b{re.escape(keyword)}\b", all_genre_text):
            return category

    return default_category


def _map_genres_to_categories(genres: list[dict[str, Any]]) -> list[int]:
    """
    Map Audnex genres to MAM category IDs.

    Handles compound genres like "Science Fiction & Fantasy" by:
    1. First trying exact match for the full compound string
    2. Then splitting on " & " and ", " to match individual components

    Args:
        genres: List of genre dicts from Audnex (with 'name' key)

    Returns:
        List of unique MAM category IDs
    """
    try:
        settings = get_settings()
        category_map = settings.categories.genre_map
    except Exception:
        return []

    categories: set[int] = set()

    for genre in genres:
        name = genre.get("name", "").lower().strip()
        if not name:
            continue

        # First try exact match for the full string
        if name in category_map:
            categories.add(category_map[name])
            continue

        # Split compound genres on " & " and ", " to match individual parts
        # e.g., "Science Fiction & Fantasy" -> ["science fiction", "fantasy"]
        # e.g., "Literature & Fiction, Fantasy" -> ["literature", "fiction", "fantasy"]
        parts = []
        for part in name.replace(" & ", ", ").split(", "):
            part = part.strip()
            if part:
                parts.append(part)

        # Try to match each part
        matched = False
        for part in parts:
            if part in category_map:
                categories.add(category_map[part])
                matched = True

        # Fallback: partial matching if no parts matched
        if not matched:
            for key, cat_id in category_map.items():
                if key in name or name in key:
                    categories.add(cat_id)
                    break

    return sorted(categories)


def _build_series_list(
    audnex_data: dict[str, Any],
    naming_config: Any = None,
) -> list[dict[str, Any]]:
    """
    Build series list for MAM JSON from Audnex data.

    Applies filter_series to clean series names (removes format indicators,
    series suffixes like " Series", " Trilogy", "[publication order]", etc.)

    Deduplicates series that become identical after cleaning (e.g., when
    seriesPrimary="Ascend Online [publication order]" and
    seriesSecondary="Ascend Online [chronological order]" both clean to
    "Ascend Online"). Primary series takes precedence.

    Args:
        audnex_data: Audnex book metadata
        naming_config: NamingConfig for cleaning rules (optional)

    Returns:
        List of series dicts with 'name' and 'number' keys (deduplicated)
    """
    series_list: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    # Primary series (takes precedence)
    primary = audnex_data.get("seriesPrimary")
    if primary:
        name = primary.get("name", "")
        if name:
            cleaned_name = filter_series(name, naming_config=naming_config)
            if cleaned_name:
                seen_names.add(cleaned_name.lower())
                series_list.append(
                    {
                        "name": cleaned_name,
                        "number": primary.get("position", ""),
                    }
                )

    # Secondary series (if any, skip if duplicate of primary after cleaning)
    secondary = audnex_data.get("seriesSecondary")
    if secondary:
        name = secondary.get("name", "")
        if name:
            cleaned_name = filter_series(name, naming_config=naming_config)
            # Only add if distinct from primary (case-insensitive)
            if cleaned_name and cleaned_name.lower() not in seen_names:
                series_list.append(
                    {
                        "name": cleaned_name,
                        "number": secondary.get("position", ""),
                    }
                )

    return series_list


def _get_mediainfo_string(mediainfo_data: dict[str, Any] | None) -> str | None:
    """
    Convert mediainfo JSON to a string for MAM.

    MAM expects the mediainfo JSON as a string in the mediaInfo field.
    """
    if not mediainfo_data:
        return None
    return json.dumps(mediainfo_data, ensure_ascii=False)


def build_mam_json(
    release: AudiobookRelease,
    audnex_data: dict[str, Any] | None = None,
    mediainfo_data: dict[str, Any] | None = None,
    audnex_chapters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build MAM fast-fillout JSON from release metadata.

    Args:
        release: AudiobookRelease object with metadata
        audnex_data: Optional Audnex API response (uses release.audnex_metadata if None)
        mediainfo_data: Optional MediaInfo JSON (uses release.mediainfo_data if None)
        audnex_chapters: Optional Audnex chapters API response (for accurate chapter data)

    Returns:
        Dict ready to be serialized as MAM JSON
    """
    # Use release metadata if not provided
    audnex = audnex_data or release.audnex_metadata or {}
    mediainfo = mediainfo_data or release.mediainfo_data

    mam_json: dict[str, Any] = {}

    # Get settings for transliteration and naming config
    try:
        settings = get_settings()
        filters = settings.filters
        naming_config = settings.naming
    except Exception:
        filters = None
        naming_config = None

    # Normalize Audnex data first to fix title/subtitle swaps
    # This uses seriesPrimary as the source of truth
    # Default to enabled if no config available
    normalized: NormalizedBook | None = None
    should_normalize = (
        naming_config.normalize_title_subtitle
        if naming_config is not None
        else True  # Default to enabled
    )
    if audnex and should_normalize:
        normalized = normalize_audnex_book(audnex)

    # Title - use normalized title if available, else Audnex title or fallback to release title
    # Apply filter_title to remove format indicators, genre tags, etc.
    # keep_volume=True to preserve "Vol. X" for human-readable JSON
    cleaned_title: str | None = None
    title = normalized.display_title if normalized else audnex.get("title") or release.title
    if title:
        cleaned_title = filter_title(
            title,
            naming_config=naming_config,
            keep_volume=True,
        )
        mam_json["title"] = cleaned_title

    # Authors (filter out translators, illustrators, etc. and transliterate Japanese names)
    authors = audnex.get("authors", [])
    if authors:
        filtered_authors = filter_authors(authors)
        # Also filter out translators detected from MediaInfo
        mediainfo_translators = extract_translators_from_mediainfo(mediainfo)
        if mediainfo_translators:
            logger.debug(
                f"Filtering translators from MediaInfo in MAM JSON: {mediainfo_translators}"
            )
            filtered_authors = [
                a for a in filtered_authors if a.get("name", "") not in mediainfo_translators
            ]
        author_names = [a.get("name", "") for a in filtered_authors if a.get("name")]
        # Transliterate Japanese/foreign names
        mam_json["authors"] = [transliterate_text(name, filters) for name in author_names]
    elif release.author:
        mam_json["authors"] = [transliterate_text(release.author, filters)]

    # Narrators (also transliterate)
    narrators = audnex.get("narrators", [])
    if narrators:
        narrator_names = [n.get("name", "") for n in narrators if n.get("name")]
        mam_json["narrators"] = [transliterate_text(name, filters) for name in narrator_names]
    elif release.narrator:
        mam_json["narrators"] = [transliterate_text(release.narrator, filters)]

    # Description - render BBCode using Jinja2 template
    if audnex:
        bbcode_description = render_bbcode_description(
            audnex_data=audnex,
            mediainfo_data=mediainfo,
            asin=release.asin,
            audnex_chapters=audnex_chapters,
        )
        if bbcode_description:
            mam_json["description"] = bbcode_description

    # Series - resolve from multiple sources with smart fallback and gap-filling
    # Priority:
    #   1) Normalized book (from swap detection) + secondary series from Audnex
    #   2) Audnex via _build_series_list (preserves primary + secondary series)
    #   3) resolve_series() fallback (Libation path → Title heuristics)
    #
    # Key principle: resolve_series() is an ENHANCER, not a bulldozer.
    # It fills gaps (missing position) but doesn't overwrite existing multi-series data.
    series_entries: list[dict[str, str]] = []
    cleaned_series: str | None = None  # For subtitle filtering

    # Step 1: Try normalized book (from swap detection)
    if normalized and normalized.series_name:
        cleaned_series = filter_series(
            normalized.series_name,
            naming_config=naming_config,
        )
        series_number = (
            normalized.series_position
            or release.series_position
            or (
                str(audnex.get("seriesPrimary", {}).get("position"))
                if audnex.get("seriesPrimary")
                else ""
            )
        )
        series_entries = [
            {
                "name": cleaned_series,
                "number": series_number,
            }
        ]
        # Also add secondary series if present (normalized only handles primary)
        # but skip if it's a duplicate after cleaning (e.g., chronological vs publication order)
        secondary = audnex.get("seriesSecondary")
        if secondary and secondary.get("name"):
            secondary_name = filter_series(secondary.get("name", ""), naming_config=naming_config)
            # Only add if distinct from primary (case-insensitive)
            if secondary_name and secondary_name.lower() != cleaned_series.lower():
                series_entries.append(
                    {
                        "name": secondary_name,
                        "number": secondary.get("position", ""),
                    }
                )
        logger.debug(
            "Series from normalized book: %s",
            [s.get("name") for s in series_entries],
        )
    else:
        # Step 2: Try _build_series_list() to preserve primary + secondary series
        series_list = _build_series_list(audnex, naming_config=naming_config)
        if series_list:
            series_entries = series_list
            cleaned_series = series_list[0].get("name")
            logger.debug(
                "Series from Audnex (primary + secondary): %s",
                [s.get("name") for s in series_list],
            )

    # Step 3: Use resolve_series() as enhancer or fallback
    # - If no series yet: use as primary source (Libation → Title heuristics)
    # - If we have exactly one series with missing info: fill gaps
    title_for_heuristic = cleaned_title or audnex.get("title") or release.title
    series_info = resolve_series(
        audnex_data=audnex,
        libation_path=release.source_dir,
        title=title_for_heuristic,
    )

    if series_info:
        resolved_name = filter_series(
            series_info.name,
            naming_config=naming_config,
        )
        # Always use resolved name for subtitle filtering (it's the cleaned version)
        cleaned_series = resolved_name

        if not series_entries:
            # No series yet → use resolver as primary source
            series_entries = [
                {
                    "name": resolved_name,
                    "number": series_info.position or "",
                }
            ]
            logger.debug(
                "Series from %s (confidence=%.1f): %s #%s",
                series_info.source.value,
                series_info.confidence,
                resolved_name,
                series_info.position or "N/A",
            )
        elif len(series_entries) == 1:
            # We have one series entry; let resolver fill gaps but not overwrite
            entry = series_entries[0]
            if not entry.get("name"):
                entry["name"] = resolved_name
            if not entry.get("number") and series_info.position:
                entry["number"] = series_info.position
                logger.debug(
                    "Filled series position from %s: %s #%s",
                    series_info.source.value,
                    entry.get("name"),
                    series_info.position,
                )
        # else: multiple series entries from Audnex - don't touch them

    # Step 4: Last-ditch fallback - release.series (only if still nothing)
    if not series_entries and release.series:
        cleaned_series = filter_series(
            release.series,
            naming_config=naming_config,
        )
        series_entries = [
            {
                "name": cleaned_series,
                "number": release.series_position or "",
            }
        ]
        logger.debug(
            "Series from release fallback: %s #%s",
            cleaned_series,
            release.series_position or "N/A",
        )

    # Commit series to MAM JSON
    if series_entries:
        mam_json["series"] = series_entries

    # Subtitle - use normalized arc_name (from swap detection) or filter raw subtitle
    # Arc name is the meaningful subtitle (e.g., "Alicization Exploding", "Mother's Rosary")
    if normalized and normalized.arc_name:
        # Use arc name directly as subtitle (it's already the "good" part)
        cleaned_subtitle = filter_subtitle(
            normalized.arc_name,
            title=cleaned_title,
            series=cleaned_series if mam_json.get("series") else None,
            naming_config=naming_config,
        )
        if cleaned_subtitle:
            mam_json["subtitle"] = cleaned_subtitle
    else:
        # Fallback: apply filter_subtitle with full redundancy checking
        subtitle = audnex.get("subtitle")
        if subtitle:
            cleaned_subtitle = filter_subtitle(
                subtitle,
                title=cleaned_title,
                series=cleaned_series if mam_json.get("series") else None,
                naming_config=naming_config,
            )
            if cleaned_subtitle:  # Only add if non-empty after cleaning
                mam_json["subtitle"] = cleaned_subtitle

    # Thumbnail (cover image URL)
    image = audnex.get("image")
    if image:
        mam_json["thumbnail"] = image

    # Language
    language = audnex.get("language")
    if language:
        # Capitalize first letter
        mam_json["language"] = language.capitalize()

    # Categories - map genres to MAM category IDs
    genres = audnex.get("genres", [])
    if genres:
        categories = _map_genres_to_categories(genres)
        if categories:
            mam_json["categories"] = categories

    # Media type - always Audiobook (1)
    mam_json["mediaType"] = 1

    # Tags - build audio info string
    # Format: Length: Xh Xm | Release date: January 1, 2016 | Format: M4B, codec | Chapterized |
    tag_parts = []

    # Get audio info from mediainfo
    if mediainfo:
        audio_info = _extract_audio_info(mediainfo)
        chapters = _parse_chapters_from_mediainfo(mediainfo)

        # Length
        duration = audio_info.get("duration_human", "")
        if duration and duration != "Unknown":
            tag_parts.append(f"Length: {duration}")

        # Release date from Audnex
        release_date = _format_release_date(audnex.get("releaseDate", ""))
        if release_date:
            tag_parts.append(f"Release date: {release_date}")

        # Format
        container = audio_info.get("container", "M4B")
        codec = audio_info.get("codec", "AAC LC")
        tag_parts.append(f"Format: {container}, {codec}")

        # Chapterized
        if chapters:
            tag_parts.append("Chapterized")

    mam_json["tags"] = " | ".join(tag_parts) + " |" if tag_parts else ""

    # MediaInfo - as JSON string
    mediainfo_str = _get_mediainfo_string(mediainfo)
    if mediainfo_str:
        mam_json["mediaInfo"] = mediainfo_str

    # ISBN - use ASIN format for audiobooks: ASIN:<asin>
    asin = release.asin or audnex.get("asin", "")
    if asin:
        mam_json["isbn"] = f"ASIN:{asin}"

    # Flags
    flags = []
    if audnex.get("isAdult"):
        flags.append("eSex")
    format_type = audnex.get("formatType", "").lower()
    if format_type == "abridged":
        flags.append("abridged")
    if flags:
        mam_json["flags"] = flags

    # Main category (Fiction=1, Non-Fiction=2)
    # Audnex literatureType is unreliable, so we infer from genres first
    main_cat = _infer_fiction_or_nonfiction(audnex)
    mam_json["main_cat"] = main_cat

    # Category string (e.g., "Audiobooks - Fantasy")
    # Uses audiobook_categories.json mapping based on genres
    is_fiction = main_cat == 1
    mam_json["category"] = _get_audiobook_category(audnex, is_fiction)

    return mam_json


def save_mam_json(
    mam_data: dict[str, Any],
    output_path: Path,
) -> None:
    """
    Write MAM JSON to file.

    Args:
        mam_data: MAM JSON dict
        output_path: Where to write the JSON file
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(mam_data, f, indent=2, ensure_ascii=False)

    # Fix ownership to target UID:GID (e.g., Unraid's nobody:users)
    # This ensures JSON files have same permissions as torrent files
    settings = get_settings()
    fix_ownership(output_path, settings.target_uid, settings.target_gid)

    logger.info(f"Saved MAM JSON: {output_path}")


def generate_mam_json_for_release(
    release: AudiobookRelease,
    output_dir: Path | None = None,
) -> Path | None:
    """
    Generate MAM JSON file for a release.

    Uses release.audnex_metadata, release.mediainfo_data, and release.audnex_chapters
    if available, or fetches them if not.

    Args:
        release: AudiobookRelease with metadata populated
        output_dir: Directory to write JSON (defaults to torrent_output from config)

    Returns:
        Path to generated JSON file, or None on failure
    """
    settings = get_settings()

    # Determine output directory
    if output_dir is None:
        output_dir = settings.paths.torrent_output

    # Ensure output directory exists (may be per-release subfolder)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Build filename: same as torrent but .json extension
    # Format: "Author - Title.json"
    if release.staging_dir:
        json_name = f"{release.staging_dir.name}.json"
    else:
        json_name = f"{release.display_name}.json"

    output_path = Path(output_dir) / json_name

    # Build and save (pass audnex_chapters from release if available)
    mam_data = build_mam_json(release, audnex_chapters=release.audnex_chapters)

    if not mam_data.get("title"):
        logger.warning(f"No title for MAM JSON: {release.display_name}")
        return None

    save_mam_json(mam_data, output_path)
    return output_path
