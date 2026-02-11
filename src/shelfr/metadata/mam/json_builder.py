"""
MAM JSON builder for audiobook uploads.

Builds MAM fast-fillout JSON payloads from AudiobookRelease metadata,
combining Audnex API data, MediaInfo technical metadata, and BBCode descriptions.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from shelfr.config import get_settings
from shelfr.metadata.formatting import render_bbcode_description
from shelfr.metadata.formatting.bbcode import _format_release_date
from shelfr.metadata.mam.categories import (
    _get_audiobook_category,
    _infer_fiction_or_nonfiction,
    _map_genres_to_categories,
    get_language_id,
    resolve_audiobook_category,
    validate_categories,
)
from shelfr.metadata.mediainfo import _extract_audio_info, _parse_chapters_from_mediainfo
from shelfr.models import NormalizedBook
from shelfr.utils.audible_urls import build_audible_url
from shelfr.utils.naming import (
    extract_translators_from_mediainfo,
    filter_authors,
    filter_series,
    filter_subtitle,
    filter_title,
    mla_title_case,
    normalize_audnex_book,
    resolve_series,
    transliterate_text,
)
from shelfr.utils.permissions import fix_ownership

if TYPE_CHECKING:
    from shelfr.models import AudiobookRelease

logger = logging.getLogger(__name__)


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
                # MAM requires MLA title case for series names
                cleaned_name = mla_title_case(cleaned_name)
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
                # MAM requires MLA title case for series names
                cleaned_name = mla_title_case(cleaned_name)
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
    *,
    audible_region: str | None = None,
) -> dict[str, Any]:
    """
    Build MAM fast-fillout JSON from release metadata.

    Args:
        release: AudiobookRelease object with metadata
        audnex_data: Optional Audnex API response (uses release.audnex_metadata if None)
        mediainfo_data: Optional MediaInfo JSON (uses release.mediainfo_data if None)
        audnex_chapters: Optional Audnex chapters API response (for accurate chapter data)
        audible_region: Optional Audible region code (e.g., "uk", "us") for source URL

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
        logger.debug("Failed to load settings for MAM JSON, using defaults")
        filters = None
        naming_config = None

    # Normalize Audnex data first to fix title/subtitle swaps
    # This uses seriesPrimary as the source of truth
    # Default to enabled if no config available
    normalized: NormalizedBook | None = None
    should_normalize = naming_config.normalize_title_subtitle if naming_config is not None else True
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
        # MAM requires MLA title case for English titles
        mam_json["title"] = mla_title_case(cleaned_title)

    # Authors (filter out translators, illustrators, etc. and transliterate Japanese names)
    authors = audnex.get("authors", [])
    if authors:
        filtered_authors = filter_authors(authors)
        # Also filter out translators detected from MediaInfo
        mediainfo_translators = extract_translators_from_mediainfo(mediainfo)
        if mediainfo_translators:
            logger.debug(
                "Filtering translators from MediaInfo in MAM JSON: %s",
                mediainfo_translators,
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
        # Build source_url using the region where ASIN was found
        source_url = None
        if release.asin:
            try:
                source_url = build_audible_url(release.asin, audible_region or "us")
            except ValueError as e:
                logger.warning(
                    "Invalid ASIN format '%s' for release '%s': %s. "
                    "Template will fall back to hardcoded audible.com.",
                    release.asin,
                    release.display_name,
                    e,
                )
                # source_url remains None, template will use fallback

        bbcode_description = render_bbcode_description(
            audnex_data=audnex,
            mediainfo_data=mediainfo,
            asin=release.asin,
            audnex_chapters=audnex_chapters,
            source_url=source_url,
            source_id=release.asin,
            source_id_type="ASIN" if release.asin else None,
        )
        if bbcode_description:
            mam_json["description"] = bbcode_description

    # Series - resolve from multiple sources with smart fallback and gap-filling
    # Priority:
    #   1) Normalized book (from swap detection) + secondary series from Audnex
    #   2) Audnex via _build_series_list (preserves primary + secondary series)
    #   3) Release.series (from Libation metadata.json - preserves proper punctuation)
    #   4) resolve_series() fallback (Libation path → Title heuristics)
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
        # MAM requires MLA title case for series names
        cleaned_series = mla_title_case(cleaned_series)
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
                # MAM requires MLA title case for series names
                secondary_name = mla_title_case(secondary_name)
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

    # Step 3: Use release.series (from Libation metadata.json)
    # This preserves proper punctuation that gets stripped from folder names
    # Only use if we don't have series from Audnex yet
    if not series_entries and release.series:
        cleaned_series = filter_series(
            release.series,
            naming_config=naming_config,
        )
        # MAM requires MLA title case for series names
        cleaned_series = mla_title_case(cleaned_series)
        series_entries = [
            {
                "name": cleaned_series,
                "number": release.series_position or "",
            }
        ]
        logger.debug(
            "Series from Libation metadata: %s #%s",
            cleaned_series,
            release.series_position or "N/A",
        )

    # Step 4: Use resolve_series() as enhancer or fallback
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
        # MAM requires MLA title case for series names
        resolved_name = mla_title_case(resolved_name)
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

    # Commit series to MAM JSON
    if series_entries:
        mam_json["series"] = series_entries

    # Subtitle - use normalized arc_name (from swap detection) or filter raw subtitle
    # Arc name is the meaningful subtitle (e.g., "Alicization Exploding", "Mother's Rosary")
    #
    # IMPORTANT: When a title/subtitle swap occurs, the arc_name becomes the title.
    # In this case, don't set subtitle to arc_name - it would duplicate the title.
    # Example: "Unnamed Memory, Vol. 1" / "The Witch of the Azure Moon..." swaps to:
    #   title="The Witch of the Azure Moon..." (meaningful name)
    #   arc_name="The Witch of the Azure Moon..." (same as title)
    # We should NOT set subtitle to the same value as title.
    if normalized and normalized.arc_name:
        # Skip if arc_name equals the display_title (they both became the meaningful name)
        arc_matches_title = (
            normalized.arc_name.strip().lower() == (normalized.display_title or "").strip().lower()
        )
        if not arc_matches_title:
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

    # Flags - prefer content_flags if available, otherwise infer from legacy fields
    flags = []

    # Check if we have explicit content_flags (from CanonicalMetadata or manual override)
    explicit_flags = getattr(release, "content_flags", None)
    if explicit_flags:
        # Use explicit flags directly
        flags = list(explicit_flags)
    else:
        # Legacy inference from is_adult and format_type
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
    # Uses signal scoring from Audnex genres + Hardcover genres/moods
    is_fiction = main_cat == 1

    # Get Hardcover genres/moods from release if available
    hardcover_genres = getattr(release, "hardcover_genres", None)
    hardcover_moods = getattr(release, "hardcover_moods", None)

    # Use is not None check to distinguish "consulted but empty" from "not consulted"
    # This ensures the resolver runs whenever Hardcover was attempted, even with empty results
    if hardcover_genres is not None or hardcover_moods is not None:
        # Use CategoryResolver for signal scoring
        resolution = resolve_audiobook_category(
            audnex_data=audnex,
            hardcover_genres=hardcover_genres,
            hardcover_moods=hardcover_moods,
            is_fiction=is_fiction,
        )
        mam_json["category"] = resolution.category
        logger.debug(
            "Category resolved: %s (scores: %s)",
            resolution.category,
            {k: f"{v:.2f}" for k, v in resolution.scores.items()}
            if resolution.scores
            else "default",
        )
    else:
        # Fallback to legacy method (Audnex only)
        mam_json["category"] = _get_audiobook_category(audnex, is_fiction)

    # Validate categories against MAM schema (sibling rules, media/main type compat)
    raw_categories = mam_json.get("categories", [])
    if raw_categories:
        validated = validate_categories(
            raw_categories,
            media_type=mam_json.get("mediaType", 1),
            main_type=main_cat,
        )
        if validated != raw_categories:
            logger.debug(
                "Categories adjusted by validation: %s -> %s",
                raw_categories,
                validated,
            )
        mam_json["categories"] = validated

    # Resolve language to MAM language ID when possible
    lang_str = mam_json.get("language")
    if isinstance(lang_str, str):
        lang_id = get_language_id(lang_str)
        if lang_id is not None:
            mam_json["language_id"] = lang_id

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
    try:
        settings = get_settings()
        fix_ownership(output_path, settings.target_uid, settings.target_gid)
    except Exception:
        logger.debug("Failed to fix ownership for %s", output_path)

    logger.info("Saved MAM JSON: %s", output_path)


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
    try:
        settings = get_settings()
    except Exception as e:
        logger.debug("Failed to load settings for MAM JSON generation: %s", e)
        return None

    # Determine output directory
    if output_dir is None:
        output_dir = settings.paths.torrent_output

    # Ensure output directory exists (may be per-release subfolder)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build filename: same as torrent but .json extension
    # Format: "Author - Title.json"
    if release.staging_dir:
        json_name = f"{release.staging_dir.name}.json"
    else:
        json_name = f"{release.display_name}.json"

    output_path = output_dir / json_name

    # Build and save (pass audnex_chapters from release if available)
    mam_data = build_mam_json(release, audnex_chapters=release.audnex_chapters)

    if not mam_data.get("title"):
        logger.warning("No title for MAM JSON: %s", release.display_name)
        return None

    save_mam_json(mam_data, output_path)
    return output_path
