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
    from mamfast.models import NormalizedBook

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

    Audible metadata is inconsistent - the same series can have different
    title/subtitle arrangements. For example:
    - SAO Vol 7: Title="Sword Art Online 7", Subtitle="Mother's Rosary" ✓
    - SAO Vol 16: Title="Alicization Exploding", Subtitle="Sword Art Online 16" ✗

    Uses seriesPrimary as the source of truth to detect when title/subtitle
    are swapped.

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
    subtitle_has_series = series_lower in subtitle_lower
    title_has_series = series_lower in title_lower

    # Heuristic 1: subtitle has series name, title doesn't → swapped
    if subtitle_has_series and not title_has_series:
        logger.debug(
            "[normalize] Detected swap (series in subtitle): title=%r, subtitle=%r, series=%r",
            title,
            subtitle,
            series_name,
        )
        return subtitle, title, True

    # Heuristic 2: subtitle ends with series number, title doesn't have series
    # This catches patterns like "Sword Art Online 16" as subtitle
    if (
        series_position
        and not title_has_series
        and re.search(rf"\b{re.escape(series_position)}\b", subtitle_lower)
    ):
        logger.debug(
            "[normalize] Detected swap (position in subtitle): title=%r, subtitle=%r, position=%r",
            title,
            subtitle,
            series_position,
        )
        return subtitle, title, True

    # No swap detected
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
    from mamfast.models import NormalizedBook

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
