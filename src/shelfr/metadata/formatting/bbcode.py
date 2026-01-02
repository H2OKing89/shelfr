"""
BBCode description rendering for MAM uploads.

Uses Jinja2 templates to generate MAM-compatible BBCode descriptions
from Audnex and MediaInfo metadata.
"""

from __future__ import annotations

import functools
import logging
import re
from datetime import datetime
from typing import Any

from jinja2 import BaseLoader, ChoiceLoader, Environment, FileSystemLoader, PackageLoader

from shelfr.config import get_settings
from shelfr.metadata.formatting.html import html_to_bbcode
from shelfr.metadata.mediainfo import (
    _extract_audio_info,
    _format_chapter_time,
    _parse_chapters_from_mediainfo,
)
from shelfr.metadata.models import Chapter
from shelfr.paths import config_dir
from shelfr.utils.naming import (
    extract_translators_from_mediainfo,
    filter_authors,
    filter_subtitle,
    filter_title,
    transliterate_text,
)

logger = logging.getLogger(__name__)

__all__ = [
    "render_bbcode_description",
]


# =============================================================================
# BBCode Description Template
# =============================================================================


@functools.lru_cache(maxsize=1)
def _get_jinja_env() -> Environment:
    """Get Jinja2 environment with template loader (cached).

    Loads templates from:
    1. config/templates/ (user overrides, gitignored)
    2. Shelfr/templates/ (package defaults)
    """
    user_templates = config_dir() / "templates"
    loaders: list[BaseLoader] = []

    # User templates take priority if directory exists
    if user_templates.is_dir():
        loaders.append(FileSystemLoader(str(user_templates)))

    # Package templates as fallback
    loaders.append(PackageLoader("shelfr", "templates"))

    return Environment(
        loader=ChoiceLoader(loaders),
        autoescape=False,  # BBCode, not HTML
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _format_release_date(date_str: str) -> str:
    """
    Format release date to human readable format (e.g., 'January 1, 2016').

    Args:
        date_str: Date string in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)

    Returns:
        Formatted date string like 'January 1, 2016', or original if parsing fails
    """
    if not date_str:
        return ""
    try:
        # Handle both YYYY-MM-DD and YYYY-MM-DDTHH:MM:SS formats
        date_part = date_str[:10] if len(date_str) >= 10 else date_str
        dt = datetime.strptime(date_part, "%Y-%m-%d")
        # Format: January 1, 2016 (no leading zero on day)
        # Use f-string with dt.day to avoid %-d which breaks on Windows
        return f"{dt:%B} {dt.day}, {dt:%Y}"
    except (ValueError, IndexError):
        return date_str


def _parse_chapters_from_audnex(chapters_data: dict[str, Any]) -> list[Chapter]:
    """
    Convert Audnex chapters API response to list of Chapter objects.

    Args:
        chapters_data: Audnex chapters API response

    Returns:
        List of Chapter objects with formatted timestamps
    """
    chapters: list[Chapter] = []

    try:
        raw_chapters = chapters_data.get("chapters", [])
        for ch in raw_chapters:
            start_seconds = ch.get("startOffsetSec", 0)
            title = ch.get("title", "")
            if title:
                chapters.append(
                    Chapter(
                        start=_format_chapter_time(float(start_seconds)),
                        title=title,
                    )
                )
    except (KeyError, TypeError, ValueError) as e:
        logger.warning(f"Failed to parse chapters from Audnex: {e}")

    return chapters


def render_bbcode_description(
    audnex_data: dict[str, Any],
    mediainfo_data: dict[str, Any] | None = None,
    asin: str | None = None,
    audnex_chapters: dict[str, Any] | None = None,
) -> str:
    """
    Render BBCode description from Audnex and MediaInfo data.

    Uses Jinja2 template for the formatting.

    Args:
        audnex_data: Audnex API response
        mediainfo_data: MediaInfo JSON (optional)
        asin: ASIN override (uses audnex_data.asin if not provided)
        audnex_chapters: Audnex chapters API response (preferred over mediainfo)

    Returns:
        Rendered BBCode description string
    """
    env = _get_jinja_env()
    template = env.get_template("mam_description.j2")

    # Get settings for transliteration and naming config
    settings = None
    filters = None
    naming_config = None
    try:
        settings = get_settings()
        filters = settings.filters
        naming_config = settings.naming
    except (AttributeError, KeyError, FileNotFoundError) as e:
        logger.debug(f"Settings unavailable, using defaults: {e}")

    # Extract and clean title from Audnex
    # Apply same filter_title() used for JSON title field for consistency
    raw_title = audnex_data.get("title", "Unknown Title")
    title = filter_title(raw_title, naming_config=naming_config, keep_volume=True)
    subtitle = audnex_data.get("subtitle")

    # Only add subtitle if it adds new info (not just "Series, Book N")
    # Skip if subtitle is like "Series Name, Book N" pattern
    # Also filter the subtitle before appending
    if subtitle:
        # Check if subtitle is just "Book N" or "Series, Book N" which is redundant
        subtitle_lower = subtitle.lower()
        is_book_pattern = ", book " in subtitle_lower or subtitle_lower.startswith("book ")
        # Also check if the core series name is already in the title
        if not is_book_pattern and subtitle not in title:
            # Filter the subtitle too (removes "Light Novel", etc.)
            cleaned_subtitle = filter_subtitle(
                subtitle,
                title=title,
                series=None,  # Don't have series context here
                naming_config=naming_config,
            )
            if cleaned_subtitle and cleaned_subtitle not in title:
                title = f"{title}: {cleaned_subtitle}"

    synopsis = html_to_bbcode(audnex_data.get("summary", ""))

    authors_raw = audnex_data.get("authors", [])
    authors_filtered = filter_authors(authors_raw)

    # Also filter out translators detected from MediaInfo
    # (Audnex doesn't include "- translator" suffix, but MediaInfo does)
    mediainfo_translators = extract_translators_from_mediainfo(mediainfo_data)
    if mediainfo_translators:
        logger.debug(f"Filtering translators from MediaInfo: {mediainfo_translators}")
        authors_filtered = [
            a for a in authors_filtered if a.get("name", "") not in mediainfo_translators
        ]

    authors = [
        transliterate_text(a.get("name", ""), filters) for a in authors_filtered if a.get("name")
    ]
    narrators = [
        transliterate_text(n.get("name", ""), filters)
        for n in audnex_data.get("narrators", [])
        if n.get("name")
    ]

    # Translator detection (look for "translator" in author/narrator names or roles)
    # First check MediaInfo (more reliable), then fall back to Audnex author names
    translator = None
    if mediainfo_translators:
        translator = next(iter(mediainfo_translators))  # Use first translator found
    else:
        for author in authors_raw:
            name = author.get("name", "")
            if "translator" in name.lower():
                translator = name
                break

    publisher = audnex_data.get("publisherName", "")
    release_date = _format_release_date(audnex_data.get("releaseDate", ""))

    genres = [g.get("name", "") for g in audnex_data.get("genres", []) if g.get("name")]
    language = audnex_data.get("language", "English")
    if language:
        language = language.capitalize()

    book_asin = asin or audnex_data.get("asin", "")

    # Audio info from MediaInfo
    audio_info = {}
    if mediainfo_data:
        audio_info = _extract_audio_info(mediainfo_data)

    # Chapters: prefer Audnex API data over mediainfo (Audnex is authoritative)
    chapters: list[Chapter] = []
    if audnex_chapters:
        chapters = _parse_chapters_from_audnex(audnex_chapters)
        logger.debug(f"Using {len(chapters)} chapters from Audnex API")
    elif mediainfo_data:
        chapters = _parse_chapters_from_mediainfo(mediainfo_data)
        logger.debug(f"Using {len(chapters)} chapters from mediainfo (Audnex not available)")

    # Get signature setting from config (reuse settings from above)
    show_signature = True  # Default
    if settings is not None:
        try:
            if settings.mam and settings.mam.description:
                show_signature = settings.mam.description.show_signature
        except (AttributeError, KeyError):
            pass  # Use default if config structure differs

    # Render template
    description = template.render(
        title=title,
        synopsis=synopsis,
        authors=authors or ["Unknown"],
        narrators=narrators or ["Unknown"],
        translator=translator,
        publisher=publisher,
        release_date=release_date,
        genres=genres or ["Audiobook"],
        language=language,
        asin=book_asin,
        container=audio_info.get("container", "M4B"),
        codec=audio_info.get("codec", "AAC LC"),
        sample_rate=audio_info.get("sample_rate", "44.1 kHz"),
        channels=audio_info.get("channels", "2"),
        duration_human=audio_info.get("duration_human", "Unknown"),
        chapters=chapters,
        show_signature=show_signature,
    )

    # MAM fast-fill imports JSON and puts description into a textarea.
    # - Inside [pre] blocks: convert newlines to [br] tags (for ASCII art)
    # - Outside [pre] blocks: remove newlines (template already uses [br])
    result = str(description).strip()
    result = _convert_newlines_for_mam(result)
    return result


def _convert_newlines_for_mam(text: str) -> str:
    """Convert text for MAM fast-fill import.

    Inside [pre] blocks:
      - Convert actual newlines to [br] tags
      - Convert regular spaces to non-breaking spaces (\\u00a0) to prevent
        MAM from collapsing consecutive spaces during import

    Outside [pre] blocks:
      - Remove newlines (BBCode uses [br] tags)

    This allows templates to remain readable (multiline) while
    producing single-line output that MAM can import correctly.
    """
    # Non-breaking space character - prevents MAM from collapsing spaces
    nbsp = "\u00a0"

    # Pattern to split while keeping delimiters
    parts = re.split(r"(\[pre\]|\[/pre\])", text, flags=re.IGNORECASE)

    result_parts: list[str] = []
    inside_pre = False

    for part in parts:
        if part.lower() == "[pre]":
            inside_pre = True
            result_parts.append(part)
        elif part.lower() == "[/pre]":
            inside_pre = False
            result_parts.append(part)
        elif inside_pre:
            # Convert actual newlines to [br] tags inside [pre] blocks
            # Convert regular spaces to non-breaking spaces to preserve alignment
            converted = part.replace("\n", "[br]").replace(" ", nbsp)
            result_parts.append(converted)
        else:
            # Remove newlines outside [pre] blocks
            result_parts.append(part.replace("\n", ""))

    return "".join(result_parts)
