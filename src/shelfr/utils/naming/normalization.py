"""
Audnex normalization utilities.

Handles title/subtitle swap detection and series name cleaning:
- Detect when Audible metadata has swapped title/subtitle
- Clean series names by removing suffixes
- Extract arc names from corrected metadata
- Normalize full Audnex book data

The key insight is that Audible metadata is inconsistent - the same series
can have different title/subtitle arrangements across volumes.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from shelfr.models import NormalizedBook

logger = logging.getLogger(__name__)


def clean_series_name(series_name: str | None, title: str | None = None) -> str | None:
    """
    Clean up series name by removing common suffixes and tags.

    Handles:
    - " Series" suffix (e.g., "Holes Series" -> "Holes")
    - " (Light Novel)" / " (light novel)" suffix
    - " Light Novel" suffix (without parens)
    - " [publication order]" and similar bracket tags
    - " Trilogy", " Saga" suffixes
    - "The" prefix inheritance from title

    Args:
        series_name: Raw series name from Audnex
        title: Book title (used for "The" prefix inheritance)

    Returns:
        Cleaned series name, or None if input was None/empty
    """
    if not series_name:
        return None

    cleaned = series_name.strip()

    # Remove bracket tags like "[publication order]", "[reading order]"
    cleaned = re.sub(r"\s*\[[^\]]*\]\s*$", "", cleaned)

    # Remove "(Light Novel)" / "(light novel)" suffix
    cleaned = re.sub(r"\s*\([Ll]ight [Nn]ovel\)\s*$", "", cleaned)

    # Remove " Light Novel" suffix (without parens) - but not if it's the whole name
    cleaned = re.sub(r"\s+[Ll]ight [Nn]ovels?\s*$", "", cleaned)

    # Remove common series type suffixes
    cleaned = re.sub(r"[\s—-]+[Ss]eries\s*$", "", cleaned)
    cleaned = re.sub(r"[\s—-]+[Tt]rilogy\s*$", "", cleaned)
    cleaned = re.sub(r"[\s—-]+[Ss]aga\s*$", "", cleaned)

    # Handle "The" prefix inheritance
    # If title starts with "The " but series doesn't, inherit it
    if title:
        title_lower = title.lower()
        cleaned_lower = cleaned.lower()

        # Check if title starts with "The " and series doesn't, and series appears in title
        # e.g., "The Rising of the Shield Hero" title with "Rising of the Shield Hero" series
        if (
            title_lower.startswith("the ")
            and not cleaned_lower.startswith("the ")
            and cleaned_lower in title_lower
        ):
            cleaned = f"The {cleaned}"

    return cleaned.strip() if cleaned else None


def detect_swapped_title_subtitle(
    title: str,
    subtitle: str | None,
    series_name: str | None,
    series_position: str | None,
) -> tuple[str, str | None, bool]:
    """
    Detect and fix swapped title/subtitle using series data as ground truth.

    MAM RULE: "Series info must NOT be in the Title field."

    This means we should NEVER swap to put "Series N" in the title. The title
    should always be the book's actual name, not series+number.

    Patterns handled:
    - Subtitle is "Series N" or "Series, Book N" → keep original title (meaningful name)
    - Title is "Series N" and subtitle has meaningful name → swap to use meaningful name
    - Title is "Series N" and subtitle is a reading line → keep original (no good alternative)

    Examples:
    - Title="The Enemy", Subtitle="Jack Reacher 8" → Title="The Enemy" ✓
    - Title="Alicization Exploding", Subtitle="SAO 16" → Title="Alicization Exploding" ✓
    - Title="Mockingjay", Subtitle="The Hunger Games, Book 3" → Title="Mockingjay" ✓
    - Title="SAO 7", Subtitle="Mother's Rosary" → Title="Mother's Rosary" ✓ (swap!)
    - Title="Primal Hunter 2", Subtitle="A LitRPG Adventure" → keep title (no swap)

    Args:
        title: Raw title from Audnex
        subtitle: Raw subtitle from Audnex
        series_name: Series name from seriesPrimary.name
        series_position: Position from seriesPrimary.position

    Returns:
        Tuple of (corrected_title, corrected_subtitle, was_swapped)
    """
    # Can't detect swap without subtitle or series data
    if not subtitle or not series_name:
        return title, subtitle, False

    title_lower = title.lower()
    subtitle_lower = subtitle.lower()
    series_lower = series_name.lower()

    # Check if series name appears in title vs subtitle
    title_has_series = series_lower in title_lower
    subtitle_has_series = series_lower in subtitle_lower

    # Check if TITLE is just series + number pattern (series info that shouldn't be title)
    # Multiple patterns to catch various formats:
    # - "Series Name 10" (bare number)
    # - "Series Name, Vol. 10" / "Series Name, Vol 10"
    # - "Series Name: Volume 10"
    # - "Series Name, Book 10"
    # - "Series Name, Part 1"
    series_number_patterns = [
        rf"^{re.escape(series_lower)}\s+\d+(\.\d+)?$",  # "Series 10" or "Series 10.5"
        rf"^{re.escape(series_lower)},?\s*vol\.?\s*\d+(\.\d+)?$",  # "Series, Vol. 10"
        rf"^{re.escape(series_lower)}:?\s*volume\s*\d+(\.\d+)?$",  # "Series: Volume 10"
        rf"^{re.escape(series_lower)},?\s*book\s*\d+(\.\d+)?$",  # "Series, Book 10"
        rf"^{re.escape(series_lower)},?\s*part\s*\d+(\.\d+)?$",  # "Series, Part 1"
    ]
    title_is_series_number = any(
        re.match(pat, title_lower, re.IGNORECASE) for pat in series_number_patterns
    )

    # Reading lines / generic subtitles that shouldn't become titles
    # These are NOT meaningful book names - they're genre descriptors
    # Pattern uses "an?\s+" to match both "A " and "An "
    reading_line_patterns = [
        # LitRPG/GameLit patterns
        r"^an?\s+[\w-]*lit\s*rpg",  # "A LitRPG", "An H-LitRPG", "A Lit RPG"
        r"^an?\s+.*\s+lit\s*rpg",  # "An Isekai LitRPG", "A Fantasy LitRPG"
        r"^an?\s+.*gamelit",  # "A Gamelit Thriller"
        # Isekai patterns (very common in this genre)
        r"^an?\s+isekai\b",  # "An Isekai Epic", "An Isekai Fantasy Adventure"
        r".*\bisekai\b.*\b(story|romance|fantasy|adventure|novel)$",  # "Spicy Isekai Romance"
        # Dungeon Core patterns
        r"^an?\s+dungeon\s+core\b",  # "A Dungeon Core LitRPG Tale"
        r"^an?\s+.*dungeon\s+core",  # "A Dungeon Core Experience"
        # Generic genre patterns
        r"^novel$",  # Just "Novel" - a format descriptor, not a title
        r"^an?\s+.*novel$",  # "A Novel", "A Light Novel"
        r"^light\s+novel$",
        r"^an?\s+.*story$",  # "A Fantasy Story"
        r"^an?\s+slice\s+of\s+life",  # "A Slice of Life Harem LitRPG"
        r"^an?\s+.*cultivation",  # "A Cultivation Novel"
        r"^an?\s+.*progression",  # "A Progression Fantasy"
        r"^an?\s+.*adventure$",  # "An Urban Fantasy Adventure"
        r"^an?\s+.*fantasy$",  # "An Isekai Fantasy"
        r"^an?\s+.*thriller$",  # "A Gamelit Thriller"
        r"^an?\s+.*romance$",  # "An Isekai Romance"
        r"^an?\s+.*epic$",  # "An Isekai Epic"
        r"^an?\s+.*tale$",  # "A Dungeon Core LitRPG Tale"
        r"^an?\s+.*harem$",  # "An Isekai Fantasy Harem"
        r"^an?\s+.*experience$",  # "A Dungeon Core Experience"
        # Long descriptive subtitles with multiple genre keywords (not starting with A/An)
        r".*\b(isekai|litrpg|gamelit)\b.*\b(story|romance|fantasy|adventure|novel|short\s+story)$",
        # Genre descriptors without "A/An" prefix
        r"^an?\s+space\s+opera$",  # "A Space Opera"
        r"^space\s+opera$",  # "Space Opera"
        # "Light Novel (Series, Book N)" format - NOT a book name
        r"^light\s+novel\s*\(",  # "Light Novel (Classroom of the Elite, Book 26)"
        # Subtitles containing LitRPG/genre in parentheses (e.g., "Mana Cultivation (A LitRP...)")
        r".*\(.*\blit\s*rp",  # "(A LitRPG...)" anywhere
        r".*\(.*\bgamelit\b",  # "(A Gamelit...)" anywhere
        r".*\(.*\bprogression\b",  # "(A Progression...)" anywhere
    ]
    subtitle_is_reading_line = any(
        re.match(pattern, subtitle_lower, re.IGNORECASE) for pattern in reading_line_patterns
    )

    # If title IS series+number and subtitle is a meaningful name (not reading line), swap!
    if title_is_series_number and not subtitle_has_series and not subtitle_is_reading_line:
        logger.debug(
            "[normalize] Title is series+number, swapping to meaningful subtitle: "
            "title=%r, subtitle=%r, series=%r",
            title,
            subtitle,
            series_name,
        )
        return subtitle, title, True

    # If title is series+number but subtitle is a reading line, keep original
    # (no good alternative - series+number is better than a reading line)
    if title_is_series_number and subtitle_is_reading_line:
        logger.debug(
            "[normalize] Title is series+number but subtitle is reading line, keeping title: "
            "title=%r, subtitle=%r, series=%r",
            title,
            subtitle,
            series_name,
        )
        return title, subtitle, False

    # If title has series but is NOT just "Series N", and subtitle doesn't have series
    # → title might be "Series Name: Arc Title" format, keep it
    if title_has_series and not title_is_series_number:
        return title, subtitle, False

    # If subtitle has series (any pattern), keep the original title
    # This handles: "Series N", "Series, Book N", "Series (Light Novel), Vol. N"
    # The original title is the meaningful book name
    if subtitle_has_series:
        logger.debug(
            "[normalize] Subtitle has series info, keeping original title: "
            "title=%r, subtitle=%r, series=%r",
            title,
            subtitle,
            series_name,
        )
        return title, subtitle, False

    # Default: no swap needed
    return title, subtitle, False


def extract_arc_name(
    title: str,
    subtitle: str | None,
    series_name: str | None,
) -> str | None:
    """
    Determine which field contains the arc name (e.g., "Alicization Exploding").

    The arc name is the descriptive subtitle that isn't just series+number.
    For example:
    - "Mother's Rosary" (SAO Vol 7)
    - "Alicization Exploding" (SAO Vol 16)
    - "Early Years" (TBATE Vol 1)

    Args:
        title: Corrected title (after swap detection)
        subtitle: Corrected subtitle (after swap detection)
        series_name: Series name from seriesPrimary

    Returns:
        Arc name if found, None otherwise
    """
    if not series_name:
        # No series → subtitle is arc (if any)
        return subtitle if subtitle else None

    series_lower = series_name.lower()

    # If subtitle exists and doesn't contain series name, it's the arc
    if subtitle:
        subtitle_lower = subtitle.lower()
        # Also filter out generic subtitles like "Light Novel"
        if series_lower not in subtitle_lower and subtitle_lower not in (
            "light novel",
            "novel",
            "a novel",
        ):
            return subtitle

    # Check if title has the arc (uncommon, but possible if we didn't swap)
    # This happens when title is like "Aincrad" but subtitle is "Sword Art Online 1"
    title_lower = title.lower()
    # Title doesn't have series name - it might be the arc itself
    # But only if it's not empty/generic
    if series_lower not in title_lower and title and title_lower not in ("light novel", "novel"):
        return title

    return None


def extract_series_from_title(title: str) -> tuple[str | None, str | None]:
    """
    Extract series name and position from title when seriesPrimary is missing.

    Some Audnex entries have no seriesPrimary but encode series info in the title:
    - "A Most Unlikely Hero, Volume 8" → ("A Most Unlikely Hero", "8")
    - "Black Summoner: Volume 1" → ("Black Summoner", "1")
    - "Reborn as a Space Mercenary Vol. 3" → ("Reborn as a Space Mercenary", "3")

    Args:
        title: Raw title from Audnex

    Returns:
        Tuple of (series_name, series_position) or (None, None) if no pattern matches
    """
    if not title:
        return None, None

    # Pattern: "Series Name, Volume N" or "Series Name: Volume N" or "Series Name Volume N"
    # Also handles Vol., Book, Part variants
    match = re.match(
        r"^(.+?)[,:\s]+(?:Volume|Vol\.?|Book|Part)\s*(\d+)$",
        title,
        re.IGNORECASE,
    )
    if match:
        series_name = match.group(1).strip()
        series_position = match.group(2)
        if series_name:
            logger.debug(
                "[normalize] Extracted series from title: %r -> series=%r, position=%r",
                title,
                series_name,
                series_position,
            )
            return series_name, series_position

    return None, None


def normalize_audnex_book(
    audnex_data: dict[str, Any],
) -> NormalizedBook:
    """
    Normalize Audnex book data to fix title/subtitle inconsistencies.

    This is the main entry point for Audnex normalization. It:
    1. Extracts series info from seriesPrimary (source of truth)
    2. Falls back to parsing subtitle or title for series patterns
    3. Cleans series name (removes suffixes, inherits "The" prefix)
    4. Detects and fixes title/subtitle swaps
    5. Extracts arc name from the appropriate field
    6. Returns a NormalizedBook with canonical values

    Args:
        audnex_data: Raw Audnex API response for a book

    Returns:
        NormalizedBook with corrected/canonical metadata
    """
    from shelfr.models import NormalizedBook

    asin = audnex_data.get("asin", "")
    raw_title = audnex_data.get("title", "")
    raw_subtitle = audnex_data.get("subtitle")

    # Extract series info (source of truth)
    series_primary = audnex_data.get("seriesPrimary") or {}
    raw_series_name = series_primary.get("name", "").strip() or None
    series_position = series_primary.get("position")
    if series_position is not None:
        series_position = str(series_position)

    # Fallback 1: Parse series from subtitle if seriesPrimary not available
    # Subtitle patterns: "Series Name, Book 5" or "Series Name, Volume 3"
    if not raw_series_name and raw_subtitle:
        subtitle_match = re.match(
            r"^(.+?),\s*(?:Book|Volume|Vol\.?|Part)\s*(\d+)$",
            raw_subtitle,
            re.IGNORECASE,
        )
        if subtitle_match:
            raw_series_name = subtitle_match.group(1).strip()
            if not series_position:
                series_position = subtitle_match.group(2)
            logger.debug(
                "[normalize] %s: Extracted series from subtitle: %r -> series=%r, position=%r",
                asin,
                raw_subtitle,
                raw_series_name,
                series_position,
            )

    # Fallback 2: Parse series from title if still missing
    # Title patterns: "A Most Unlikely Hero, Volume 8"
    if not raw_series_name:
        title_series, title_position = extract_series_from_title(raw_title)
        if title_series:
            raw_series_name = title_series
            if not series_position:
                series_position = title_position

    # Clean series name (remove suffixes, inherit "The" prefix)
    series_name = clean_series_name(raw_series_name, raw_title)

    # Log if series was cleaned
    if raw_series_name and series_name and raw_series_name != series_name:
        logger.debug(
            "[normalize] %s: Cleaned series name: %r -> %r",
            asin,
            raw_series_name,
            series_name,
        )

    # Detect and fix swapped title/subtitle (use cleaned series name)
    corrected_title, corrected_subtitle, was_swapped = detect_swapped_title_subtitle(
        raw_title, raw_subtitle, series_name, series_position
    )

    # Extract arc name (use cleaned series name)
    arc_name = extract_arc_name(corrected_title, corrected_subtitle, series_name)

    # Build display values
    display_title = corrected_title
    display_subtitle = arc_name

    if was_swapped:
        logger.info(
            "[normalize] %s: Fixed swapped title/subtitle\n"
            "  Raw: title=%r, subtitle=%r\n"
            "  Series: %r #%s\n"
            "  Fixed: title=%r, subtitle=%r\n"
            "  Arc: %r",
            asin,
            raw_title,
            raw_subtitle,
            series_name,
            series_position,
            display_title,
            display_subtitle,
            arc_name,
        )

    return NormalizedBook(
        asin=asin,
        raw_title=raw_title,
        raw_subtitle=raw_subtitle,
        series_name=series_name,
        series_position=series_position,
        arc_name=arc_name,
        display_title=display_title,
        display_subtitle=display_subtitle,
        was_swapped=was_swapped,
    )
