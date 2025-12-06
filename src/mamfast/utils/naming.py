"""
Filename sanitization and truncation for MAM compliance.

MAM has a 225-character limit on filenames/paths.
"""

from __future__ import annotations

import functools
import hashlib
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mamfast.config import FiltersConfig, NamingConfig
    from mamfast.models import MamPath, NormalizedBook

logger = logging.getLogger(__name__)

# Characters not allowed in filenames (cross-platform safe)
ILLEGAL_CHARS_PATTERN = re.compile(r'[<>:"/\\|?*]')

# Characters to normalize (replace with space or dash)
NORMALIZE_MAP = {
    "/": "-",
    "\\": "-",
    ":": " -",
    "|": "-",
    '"': "'",
    "<": "",
    ">": "",
    "?": "",
    "*": "",
}

# Pre-compiled patterns for title filtering (better performance than re-compiling each call)
# Base patterns: always removed from titles
_COMPILED_REMOVE_PATTERNS: list[re.Pattern[str]] = [
    # "Book 12", "Book XII", "Book: 12" etc - we keep vol_XX instead
    re.compile(r"\bBook\s*[:\s]*\d+\b", re.IGNORECASE),
    re.compile(r"\bBook\s*[:\s]*[IVXLCDM]+\b", re.IGNORECASE),
    # Extra whitespace patterns
    re.compile(r"\s*-\s*-\s*"),  # Double dashes
    re.compile(r"\s*,\s*,\s*"),  # Double commas
]

# Volume patterns: removed for folder/file names, kept for MAM JSON
_COMPILED_VOLUME_PATTERNS: list[re.Pattern[str]] = [
    # "Vol. 12" or "Volume 12" (but NOT vol_12 which is Libation format)
    re.compile(r"\bVol\.\s*\d+\b", re.IGNORECASE),
    re.compile(r"\bVolume\s*\d+\b", re.IGNORECASE),
]

# Pre-compiled cleanup patterns
_WHITESPACE_PATTERN = re.compile(r"\s+")
_DOUBLE_DASH_PATTERN = re.compile(r"\s*-\s*-\s*")
_LEADING_DASH_PATTERN = re.compile(r"^\s*-\s*")
_TRAILING_DASH_PATTERN = re.compile(r"\s*-\s*$")
_EMPTY_PARENS_PATTERN = re.compile(r"\(\s*\)")
_EMPTY_BRACKETS_PATTERN = re.compile(r"\[\s*\]")
_DUPLICATE_VOL_PATTERN = re.compile(r"\b(\d+)\s+vol_\1\b")
_NON_ASCII_PATTERN = re.compile(r"[^\x00-\x7F]+")
# Dangling punctuation patterns
_TRAILING_PUNCT_PATTERN = re.compile(r"\s*[,:;]\s*$")  # Trailing comma, colon, semicolon
_LEADING_PUNCT_PATTERN = re.compile(r"^\s*[,:;]\s*")  # Leading comma, colon, semicolon
_SPACE_BEFORE_PUNCT_PATTERN = re.compile(r"\s+([,:;])")  # Space before punctuation

# Volume/Book number extraction patterns for folder naming
_VOL_EXTRACT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r",?\s*Vol\.?\s*(\d+)", re.IGNORECASE),  # ", Vol. 3" or "Vol 3"
    re.compile(r",?\s*Volume\s+(\d+)", re.IGNORECASE),  # ", Volume 3"
    re.compile(r",?\s*Book\s+(\d+)", re.IGNORECASE),  # ", Book 3"
    re.compile(r"\s+(\d+)$"),  # Trailing number "Title 3"
]

# MAM filename limit
MAM_MAX_FILENAME_LENGTH = 225

# Default author role words (fallback if config not available)
_DEFAULT_ROLE_WORDS = ["translator", "illustrator", "editor", "adapter", "contributor", "compiler"]
_DEFAULT_CREDIT_WORDS = ["afterword", "foreword", "introduction", "cover design", "cover art"]


def _build_author_role_pattern(
    role_words: list[str] | None = None,
    credit_words: list[str] | None = None,
) -> re.Pattern[str]:
    """
    Build the author role detection pattern from config lists.

    Args:
        role_words: List of role words (translator, illustrator, etc.)
        credit_words: List of credit words (afterword, foreword, etc.)

    Returns:
        Compiled regex pattern
    """
    # Use explicit None check to allow empty list to disable roles
    roles = _DEFAULT_ROLE_WORDS if role_words is None else role_words
    credits = _DEFAULT_CREDIT_WORDS if credit_words is None else credit_words

    # Build alternation patterns
    role_pattern = "|".join(re.escape(r) for r in roles)
    credit_pattern = "|".join(re.escape(c) for c in credits)

    return re.compile(
        rf"""
        (?:
            \s*-\s*(?:{role_pattern})s?\s*$  |           # "- translator" at end
            \s*\(\s*(?:{role_pattern})s?\s*\)  |         # "(translator)"
            \s*,\s*(?:{role_pattern})s?\s*$  |           # ", translator" at end
            ^\s*(?:{credit_pattern})\s+by\s  |           # "Foreword by ..."
            \s*\(\s*(?:{credit_pattern})\s*\)  |         # "(foreword)"
            \s*-\s*(?:{credit_pattern})\s*$  |           # "- foreword" at end
            ^with\s                                      # "with John Smith" at start
        )
        """,
        re.IGNORECASE | re.VERBOSE,
    )


# Default pattern (used when config not available)
_AUTHOR_ROLE_PATTERN = _build_author_role_pattern()


def _get_author_role_pattern() -> re.Pattern[str]:
    """
    Get the author role pattern, loading from config if available.

    Returns:
        Compiled regex pattern for author role detection
    """
    try:
        from mamfast.config import get_settings

        settings = get_settings()
        if settings.filters and settings.filters.naming:
            naming = settings.filters.naming
            if naming.author_roles or naming.credit_roles:
                return _build_author_role_pattern(
                    role_words=naming.author_roles,
                    credit_words=naming.credit_roles,
                )
    except Exception as e:
        # Config not available or invalid; fall back to default pattern
        logger.debug("Failed to load author role pattern from config, using default: %r", e)
    return _AUTHOR_ROLE_PATTERN


def is_author_role(name: str) -> bool:
    """
    Check if a name string indicates a non-author role.

    Uses word-boundary matching to avoid false positives like "John Translator Smith".
    Only matches patterns like:
    - "Name - translator"
    - "Name (illustrator)"
    - "Name, editor"
    - "with Name"
    - "Foreword by Name"

    Args:
        name: Author name string (e.g., "Jasmine Bernhardt - translator")

    Returns:
        True if this is a translator/illustrator/etc., False if primary author
    """
    pattern = _get_author_role_pattern()
    return bool(pattern.search(name))


def filter_authors(authors: list[dict[str, str]]) -> list[dict[str, str]]:
    """
    Filter out translators, illustrators, etc. from author list.

    Args:
        authors: List of author dicts with 'name' key

    Returns:
        Filtered list containing only primary authors
    """
    return [a for a in authors if not is_author_role(a.get("name", ""))]


def extract_translator(authors: list[dict[str, str]]) -> str | None:
    """
    Extract translator name from author list.

    Args:
        authors: List of author dicts with 'name' key

    Returns:
        Translator name if found, None otherwise
    """
    for author in authors:
        name = author.get("name", "")
        name_lower = name.lower()
        if "translator" in name_lower:
            # Clean up the name - remove " - translator" suffix
            cleaned = re.sub(r"\s*-?\s*translator[s]?\s*$", "", name, flags=re.IGNORECASE)
            return cleaned.strip()
    return None


# =============================================================================
# Audnex Normalization (Title/Subtitle Swap Detection)
# =============================================================================


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


def normalize_audnex_book(
    audnex_data: dict[str, Any],
) -> NormalizedBook:
    """
    Normalize Audnex book data to fix title/subtitle inconsistencies.

    This is the main entry point for Audnex normalization. It:
    1. Extracts series info from seriesPrimary (source of truth)
    2. Cleans series name (removes suffixes, inherits "The" prefix)
    3. Detects and fixes title/subtitle swaps
    4. Extracts arc name from the appropriate field
    5. Returns a NormalizedBook with canonical values

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


def _build_mediainfo_role_pattern(
    role_words: list[str] | None = None,
    credit_words: list[str] | None = None,
) -> re.Pattern[str]:
    """
    Build pattern for extracting non-author roles from MediaInfo.

    Args:
        role_words: List of role words (translator, illustrator, etc.)
        credit_words: List of credit words (afterword, foreword, etc.)

    Returns:
        Compiled regex pattern matching "- role" suffix
    """
    # Use explicit None check to allow empty list to disable roles
    roles = _DEFAULT_ROLE_WORDS if role_words is None else role_words
    credits = _DEFAULT_CREDIT_WORDS if credit_words is None else credit_words

    # Combine all roles, escaping special regex chars and handling multi-word
    all_roles = roles + credits
    # For multi-word roles like "cover design", convert space to \s+
    role_patterns = [re.escape(r).replace(r"\ ", r"\s+") for r in all_roles]
    combined = "|".join(role_patterns)

    return re.compile(
        rf"\s*-?\s*(?:{combined})s?\s*$",
        re.IGNORECASE,
    )


def extract_non_authors_from_mediainfo(mediainfo_data: dict[str, Any] | None) -> set[str]:
    """
    Extract non-author names (translators, illustrators, etc.) from MediaInfo metadata.

    The M4B file often has role info in Album_Performer field like:
    "Bokuto Uno; Ruria Miyuki; Andrew Cunningham - translator"

    This extracts names with role markers that Audnex API doesn't provide,
    matching the same roles as is_author_role(): translator, illustrator,
    editor, adapter, contributor, compiler, cover design, etc.

    Args:
        mediainfo_data: MediaInfo JSON data

    Returns:
        Set of non-author names (without the role suffix)
    """
    if not mediainfo_data:
        return set()

    non_authors: set[str] = set()

    # Try to load roles from config, fall back to defaults
    try:
        from mamfast.config import get_settings

        settings = get_settings()
        if settings.filters and settings.filters.naming:
            naming = settings.filters.naming
            role_pattern = _build_mediainfo_role_pattern(
                role_words=naming.author_roles,
                credit_words=naming.credit_roles,
            )
        else:
            role_pattern = _build_mediainfo_role_pattern()
    except Exception as e:
        # Config not available; fall back to default pattern
        logger.debug("Failed to load mediainfo role pattern from config: %r", e)
        role_pattern = _build_mediainfo_role_pattern()

    try:
        media = mediainfo_data.get("media", {})
        tracks = media.get("track", [])

        for track in tracks:
            if track.get("@type") == "General":
                # Check Album_Performer and Performer fields
                for field in ["Album_Performer", "Performer"]:
                    performer = track.get(field, "")
                    if performer:
                        # Split by semicolon (common separator)
                        parts = performer.split(";")
                        for part in parts:
                            part = part.strip()
                            # Check if this person has a role marker
                            if role_pattern.search(part):
                                # Extract name without role suffix
                                cleaned = role_pattern.sub("", part).strip()
                                if cleaned:
                                    non_authors.add(cleaned)
                break

    except (TypeError, KeyError) as e:
        # Failed to parse expected fields from MediaInfo; returning what we have
        logger.debug("Error extracting non-authors from MediaInfo: %s", e)

    return non_authors


# Keep old name as alias for backward compatibility
extract_translators_from_mediainfo = extract_non_authors_from_mediainfo


def filter_authors_with_mediainfo(
    authors: list[dict[str, str]], mediainfo_data: dict[str, Any] | None = None
) -> list[dict[str, str]]:
    """
    Filter out translators, illustrators, etc. from author list.

    Enhanced version that also checks MediaInfo metadata for translator info,
    since Audnex API doesn't always include role information.

    Args:
        authors: List of author dicts with 'name' key
        mediainfo_data: Optional MediaInfo JSON to extract translator info

    Returns:
        Filtered list containing only primary authors
    """
    # First use the standard filter (catches "- translator" in name)
    filtered = filter_authors(authors)

    # Then filter out translators identified from MediaInfo
    if mediainfo_data:
        mediainfo_translators = extract_translators_from_mediainfo(mediainfo_data)
        if mediainfo_translators:
            # Normalize names for comparison (lowercase, strip whitespace)
            translator_names_lower = {t.lower().strip() for t in mediainfo_translators}
            filtered = [
                a
                for a in filtered
                if a.get("name", "").lower().strip() not in translator_names_lower
            ]

    return filtered


def sanitize_filename(name: str) -> str:
    """
    Remove or replace characters that are problematic in filenames.

    - Removes: < > ? *
    - Replaces: / \\ : | " with safer alternatives
    - Collapses multiple spaces
    - Strips leading/trailing whitespace and dots
    """
    result = name

    for char, replacement in NORMALIZE_MAP.items():
        result = result.replace(char, replacement)

    # Remove any remaining illegal characters (using pre-compiled pattern)
    result = ILLEGAL_CHARS_PATTERN.sub("", result)

    # Collapse multiple spaces (using pre-compiled pattern)
    result = _WHITESPACE_PATTERN.sub(" ", result)

    # Strip leading/trailing whitespace and dots
    result = result.strip(". ")

    return result


def filter_title(
    name: str,
    remove_phrases: list[str] | None = None,
    *,
    naming_config: NamingConfig | None = None,
    verbose: bool = False,
    keep_volume: bool = False,
) -> str:
    """
    Remove unwanted phrases from a title/folder name.

    Applies in order:
    1. Check preserve_exact - skip ALL cleaning if exact or prefix match
       - Exact match: input == preserved
       - Prefix match: input starts with preserved + separator (, /Vol/Book/()
    2. Hardcoded patterns (Book XX, etc.)
    3. Volume patterns (Vol. XX, Volume XX) - unless keep_volume=True
    4. Config patterns: format_indicators, genre_tags, publisher_tags
    5. Legacy remove_phrases (for backward compatibility)
    6. Collapse whitespace
    7. Duplicate number before vol_XX cleanup
    8. Final whitespace cleanup

    Args:
        name: Original name
        remove_phrases: Legacy list of phrases to remove (case-insensitive)
        naming_config: NamingConfig with format_indicators, genre_tags, etc.
        verbose: If True, log each transformation with rule IDs
        keep_volume: If True, keep "Vol. X" and "Volume X" (for MAM JSON).
                     If False, remove them (for folder/file names).

    Returns:
        Filtered name with unwanted phrases removed
    """
    result = name
    transformations: list[tuple[str, str, str]] = []  # (before, after, rule_id)

    # Step 1: Check preserve_exact - skip ALL cleaning if title matches
    # Two modes:
    #   1. Exact equality: name == preserved
    #   2. Prefix match: name starts with preserved + separator (, or space before Vol/Book)
    # This handles "86--EIGHTY-SIX, Vol. 1" matching preserve_exact=["86--EIGHTY-SIX"]
    if naming_config and naming_config.preserve_exact:
        for preserved in naming_config.preserve_exact:
            # Check exact match first
            if name == preserved:
                if verbose:
                    logger.debug(f"[filter_title] '{name}' -> '{name}' (preserved via exact match)")
                return name
            # Check prefix match with common separators (comma, space+Vol, space+Book)
            # This preserves "Title, Vol. 1" when "Title" is in preserve_exact
            if name.startswith(preserved):
                suffix = name[len(preserved) :]
                # Valid separators: ", " or " Vol" or " Book" or " (" (for annotations)
                if suffix.startswith((", ", " Vol", " Book", " (")):
                    if verbose:
                        logger.debug(
                            f"[filter_title] '{name}' -> '{name}' (preserved via prefix match)"
                        )
                    return name

    # Step 2: Apply pre-compiled hardcoded patterns (always applied)
    for pattern in _COMPILED_REMOVE_PATTERNS:
        before = result
        result = pattern.sub("", result)
        if before != result and verbose:
            transformations.append((before, result, "hardcoded_patterns"))

    # Step 3: Apply volume patterns (only if keep_volume=False)
    if not keep_volume:
        for pattern in _COMPILED_VOLUME_PATTERNS:
            before = result
            result = pattern.sub("", result)
            if before != result and verbose:
                transformations.append((before, result, "volume_patterns"))

    # Step 4: Apply naming config patterns (format_indicators, genre_tags, publisher_tags)
    if naming_config:
        # Format indicators (case-insensitive phrase matching)
        for phrase in naming_config.format_indicators or []:
            before = result
            escaped = re.escape(phrase)
            result = re.sub(escaped, "", result, flags=re.IGNORECASE)
            if before != result and verbose:
                transformations.append((before, result, f"format_indicators:{phrase}"))

        # Genre tags (case-insensitive phrase matching)
        for phrase in naming_config.genre_tags or []:
            before = result
            escaped = re.escape(phrase)
            result = re.sub(escaped, "", result, flags=re.IGNORECASE)
            if before != result and verbose:
                transformations.append((before, result, f"genre_tags:{phrase}"))

        # Publisher tags (case-insensitive phrase matching)
        for phrase in naming_config.publisher_tags or []:
            before = result
            escaped = re.escape(phrase)
            result = re.sub(escaped, "", result, flags=re.IGNORECASE)
            if before != result and verbose:
                transformations.append((before, result, f"publisher_tags:{phrase}"))

    # Step 5: Apply legacy user-configured phrases (backward compatibility)
    if remove_phrases:
        for phrase in remove_phrases:
            before = result
            escaped = re.escape(phrase)
            result = re.sub(escaped, "", result, flags=re.IGNORECASE)
            if before != result and verbose:
                transformations.append((before, result, f"remove_phrases:{phrase}"))

    # Step 6: Collapse whitespace before duplicate check
    result = _WHITESPACE_PATTERN.sub(" ", result)

    # Step 7: Remove duplicate number before vol_XX (e.g., "Title 12 vol_12" -> "Title vol_12")
    before = result
    result = _DUPLICATE_VOL_PATTERN.sub(r"vol_\1", result)
    if before != result and verbose:
        transformations.append((before, result, "duplicate_vol_cleanup"))

    # Step 8: Clean up whitespace artifacts
    result = _cleanup_string(result)

    # Log all transformations if verbose
    if verbose and transformations:
        logger.debug(f"[filter_title] '{name}' -> '{result}'")
        for before, after, rule_id in transformations:
            logger.debug(f"  - [{rule_id}] '{before}' -> '{after}'")

    return result


def filter_series(
    name: str,
    remove_phrases: list[str] | None = None,
    *,
    naming_config: NamingConfig | None = None,
    verbose: bool = False,
    keep_volume: bool = False,
) -> str:
    """
    Remove unwanted phrases from a series name.

    Like filter_title() but also applies series_suffixes regex patterns
    (e.g., " Series", " Trilogy", " Light Novel").

    Note on preserve_exact: This function delegates to filter_title() first,
    which handles preserve_exact for base cleaning (format indicators, genre tags,
    etc.). The preserve_exact check here only controls whether series_suffixes
    are applied - it prevents stripping " Series"/" Light Novel" suffixes from
    entries that match preserve_exact.

    Series names in MAM JSON should NOT have volume indicators, so
    keep_volume=False is typically correct even for JSON output.

    Args:
        name: Original series name
        remove_phrases: Legacy list of phrases to remove (case-insensitive)
        naming_config: NamingConfig with series_suffixes patterns
        verbose: If True, log each transformation with rule IDs
        keep_volume: If True, keep "Vol. X" (passed to filter_title)

    Returns:
        Filtered series name
    """
    # First apply standard title filtering
    result = filter_title(
        name,
        remove_phrases=remove_phrases,
        naming_config=naming_config,
        verbose=verbose,
        keep_volume=keep_volume,
    )

    # Check if original name was preserved (exact or prefix match)
    if naming_config and naming_config.preserve_exact:
        for preserved in naming_config.preserve_exact:
            if name == preserved:
                return result  # Already preserved
            if name.startswith(preserved):
                suffix = name[len(preserved) :]
                if suffix.startswith((", ", " Vol", " Book", " (", " Series")):
                    return result  # Already preserved

    transformations: list[tuple[str, str, str]] = []

    # Apply series suffix patterns (regex, case-insensitive, end-anchored)
    if naming_config and naming_config.series_suffixes:
        for pattern_str in naming_config.series_suffixes or []:
            try:
                pattern = re.compile(pattern_str, re.IGNORECASE)
                before = result
                result = pattern.sub("", result)
                if before != result and verbose:
                    transformations.append((before, result, f"series_suffixes:{pattern_str}"))
            except re.error as e:
                logger.warning(f"Invalid series_suffix regex '{pattern_str}': {e}")

    # Final cleanup
    result = _cleanup_string(result)

    # Log series-specific transformations
    if verbose and transformations:
        logger.debug("[filter_series] additional transformations:")
        for before, after, rule_id in transformations:
            logger.debug(f"  - [{rule_id}] '{before}' -> '{after}'")

    return result


def filter_subtitle(
    subtitle: str,
    *,
    title: str | None = None,
    series: str | None = None,
    naming_config: NamingConfig | None = None,
    verbose: bool = False,
) -> str | None:
    """
    Filter a subtitle using two-tier strategy and redundancy rules.

    Processing order:
    1. Check preserve_exact - skip ALL cleaning if matched
    2. If matches keep_patterns -> return as-is (preserve subtitle, whitelist)
    3. If matches remove_patterns -> return None (drop subtitle)
    4. If matches series name (and enabled) -> return None (drop subtitle)
    5. Apply subtitle_redundancy_rules:
       - Replace {{series}} with series name (skip rule if series empty)
       - Replace {{title}} with title name
       - If action="drop_subtitle" and pattern matches -> return None
       - If action="strip_match" and pattern matches -> remove matched portion
    6. Otherwise -> return cleaned subtitle

    Args:
        subtitle: Subtitle text to filter
        title: Title for {{title}} template substitution
        series: Series name for {{series}} template substitution
        naming_config: NamingConfig with subtitle patterns and rules
        verbose: If True, log each transformation

    Returns:
        Filtered subtitle string, or None if subtitle should be dropped entirely
    """
    if not subtitle or not subtitle.strip():
        return None

    result = subtitle.strip()
    transformations: list[tuple[str, str, str]] = []

    # Step 1: Check preserve_exact - skip ALL cleaning if subtitle matches
    # Uses exact match only for subtitles (no prefix matching like titles)
    if naming_config and naming_config.preserve_exact and subtitle in naming_config.preserve_exact:
        if verbose:
            logger.debug(
                f"[filter_subtitle] '{subtitle}' -> '{subtitle}' " "(preserved via preserve_exact)"
            )
        return subtitle

    # Step 2: Check keep_patterns FIRST - whitelist to preserve special subtitles
    if naming_config and naming_config.subtitle_keep_patterns:
        for pattern_str in naming_config.subtitle_keep_patterns or []:
            try:
                pattern = re.compile(pattern_str, re.IGNORECASE)
                if pattern.search(result):
                    if verbose:
                        logger.debug(
                            f"[filter_subtitle] '{subtitle}' -> '{result}' "
                            f"(preserved via keep_pattern: {pattern_str})"
                        )
                    return _cleanup_string(result)
            except re.error as e:
                logger.warning(f"Invalid subtitle_keep_pattern regex '{pattern_str}': {e}")

    # Step 3: Check remove_patterns - if matches, drop subtitle entirely
    if naming_config and naming_config.subtitle_remove_patterns:
        for pattern_str in naming_config.subtitle_remove_patterns or []:
            try:
                pattern = re.compile(pattern_str, re.IGNORECASE)
                if pattern.search(result):
                    if verbose:
                        logger.debug(
                            f"[filter_subtitle] '{subtitle}' -> None "
                            f"(matched remove_pattern: {pattern_str})"
                        )
                    return None
            except re.error as e:
                logger.warning(f"Invalid subtitle_remove_pattern regex '{pattern_str}': {e}")

    # Step 4: Check if subtitle matches series name (drop if enabled)
    if naming_config and naming_config.remove_subtitle_if_matches_series and series:
        # Normalize both for comparison
        series_normalized = series.strip().lower()
        subtitle_normalized = result.strip().lower()
        if subtitle_normalized == series_normalized:
            if verbose:
                logger.debug(f"[filter_subtitle] '{subtitle}' -> None (matches series name)")
            return None

    # Step 5: Apply subtitle_redundancy_rules
    if (
        naming_config
        and naming_config.subtitle_redundancy_enabled
        and naming_config.subtitle_redundancy_rules
    ):
        for rule in naming_config.subtitle_redundancy_rules or []:
            pattern_template = rule.get("pattern_template", "")
            action = rule.get("action", "drop_subtitle")
            rule_id = rule.get("id", "unknown")

            # Skip rules with {{series}} if series is empty
            if "{{series}}" in pattern_template and not series:
                continue

            # Build the actual pattern by substituting placeholders
            actual_pattern = pattern_template
            if series:
                actual_pattern = actual_pattern.replace("{{series}}", re.escape(series))
            if title:
                actual_pattern = actual_pattern.replace("{{title}}", re.escape(title))

            try:
                pattern = re.compile(actual_pattern, re.IGNORECASE)
                match = pattern.search(result)
                if match:
                    if action == "drop_subtitle":
                        # Full match -> drop the entire subtitle
                        if verbose:
                            logger.debug(
                                f"[filter_subtitle] '{subtitle}' -> None "
                                f"(redundancy rule '{rule_id}': drop_subtitle)"
                            )
                        return None
                    elif action == "strip_match":
                        # Remove only the matched portion
                        before = result
                        result = pattern.sub("", result)
                        result = _cleanup_string(result)
                        if before != result and verbose:
                            transformations.append(
                                (before, result, f"redundancy:{rule_id}:strip_match")
                            )
                        # If stripping left nothing, drop subtitle
                        if not result:
                            if verbose:
                                logger.debug(
                                    f"[filter_subtitle] '{subtitle}' -> None "
                                    f"(redundancy rule '{rule_id}': strip_match left empty)"
                                )
                            return None
            except re.error as e:
                logger.warning(
                    f"Invalid redundancy rule pattern '{pattern_template}' "
                    f"(resolved: '{actual_pattern}'): {e}"
                )

    # Step 6: Final cleanup
    result = _cleanup_string(result)

    # Log transformations if verbose
    if verbose and transformations:
        logger.debug(f"[filter_subtitle] '{subtitle}' -> '{result}'")
        for before, after, rule_id in transformations:
            logger.debug(f"  - [{rule_id}] '{before}' -> '{after}'")

    return result if result else None


def inherit_the_prefix(series: str | None, title: str | None) -> str | None:
    """
    Inherit "The" prefix from title to series if series lacks it.

    Some audiobooks (especially light novels) have inconsistent API data where
    the title includes "The" but the series name doesn't. For example:
    - Title: "The Great Cleric: Volume 1"
    - Series (API): "Great Cleric"
    - Series (desired): "The Great Cleric"

    This function checks if the title starts with "The {series}" and if so,
    adds "The " prefix to the series name.

    Args:
        series: Series name (may be None for standalone books)
        title: Book title

    Returns:
        Series name with "The" prefix added if inherited, otherwise unchanged
    """
    if not series or not title:
        return series

    # Check if title starts with "The " followed by the series name
    # Case-insensitive comparison
    title_lower = title.lower()
    series_lower = series.lower()

    # Already has "The" prefix
    if series_lower.startswith("the "):
        return series

    # Check if title starts with "The {series}"
    the_prefix = "the "
    if title_lower.startswith(the_prefix):
        # Extract potential series portion from title
        title_without_the = title_lower[len(the_prefix) :]

        # Check if title (without "The") starts with the series name
        if title_without_the.startswith(series_lower):
            # The title starts with "The {series}", so inherit the prefix
            return f"The {series}"

    return series


def _cleanup_string(text: str) -> str:
    """
    Clean up whitespace and punctuation artifacts from string.

    - Collapse multiple spaces
    - Fix double dashes
    - Remove leading/trailing dashes
    - Remove empty parentheses/brackets
    - Remove dangling punctuation (trailing colon, comma, semicolon)
    - Fix space before punctuation
    - Strip whitespace
    """
    result = text
    result = _WHITESPACE_PATTERN.sub(" ", result)  # Collapse multiple spaces
    result = _DOUBLE_DASH_PATTERN.sub(" - ", result)  # Fix double dashes
    result = _LEADING_DASH_PATTERN.sub("", result)  # Remove leading dash
    result = _TRAILING_DASH_PATTERN.sub("", result)  # Remove trailing dash
    result = _EMPTY_PARENS_PATTERN.sub("", result)  # Remove empty parens
    result = _EMPTY_BRACKETS_PATTERN.sub("", result)  # Remove empty brackets
    result = _SPACE_BEFORE_PUNCT_PATTERN.sub(r"\1", result)  # Fix "word ," -> "word,"
    result = _TRAILING_PUNCT_PATTERN.sub("", result)  # Remove trailing comma/colon
    result = _LEADING_PUNCT_PATTERN.sub("", result)  # Remove leading comma/colon
    # Re-collapse spaces after punctuation fixes
    result = _WHITESPACE_PATTERN.sub(" ", result)
    result = result.strip()
    return result


@functools.lru_cache(maxsize=1)
def _get_kakasi() -> Any:
    """
    Get cached pykakasi instance.

    Returns None if pykakasi is not installed.
    Caches the instance to avoid repeated imports and initialization.
    """
    try:
        import pykakasi

        # pykakasi has no type stubs, suppress mypy error
        kks = pykakasi.kakasi()  # type: ignore[no-untyped-call]
        return kks
    except ImportError:
        logger.debug("pykakasi not installed, Japanese transliteration unavailable")
        return None


def transliterate_text(
    text: str,
    filters: FiltersConfig | None = None,
) -> str:
    """
    Transliterate foreign text (especially Japanese) to ASCII.

    Priority:
    1. Check author_map for exact matches
    2. Use pykakasi for Japanese characters (if enabled)
    3. Leave other text unchanged

    Args:
        text: Text that may contain foreign characters
        filters: Filter config with author_map and transliterate settings

    Returns:
        Transliterated text (ASCII-safe)
    """
    if filters is None:
        return text

    result = text

    # Try fuzzy matching first against the original text for full replacements
    if filters.author_map and not text.isascii():
        from mamfast.utils.fuzzy import find_best_match

        fuzzy_match = find_best_match(text, list(filters.author_map.keys()), threshold=85)
        if fuzzy_match:
            result = filters.author_map[fuzzy_match]
            logger.debug(f"Fuzzy author match: '{text}' → '{result}' (via '{fuzzy_match}')")
            return result  # Early return if fuzzy match found

    # If no fuzzy match, apply exact substring matches
    if filters.author_map:
        for foreign, romanized in filters.author_map.items():
            if foreign in result:
                result = result.replace(foreign, romanized)

    # Check if there are any remaining non-ASCII characters
    if result.isascii():
        return result

    # Try Japanese transliteration if enabled
    if filters.transliterate_japanese:
        kks = _get_kakasi()
        if kks is not None:
            # Find non-ASCII segments and transliterate them
            def transliterate_segment(match: re.Match[str]) -> str:
                segment = match.group(0)
                # Check author_map first (already done above, but for safety)
                if filters.author_map and segment in filters.author_map:
                    return filters.author_map[segment]
                # Use pykakasi
                converted = kks.convert(segment)
                romaji = " ".join([item["hepburn"] for item in converted])
                # Title case for names
                return romaji.title()

            # Match sequences of non-ASCII characters (using pre-compiled pattern)
            result = _NON_ASCII_PATTERN.sub(transliterate_segment, result)

    return result


def truncate_filename(
    name: str,
    max_length: int = 225,
    preserve_extension: bool = True,
) -> str:
    """
    Truncate filename to max_length while preserving readability.

    **WARNING**: This function is NOT MAM path-aware. It truncates individual
    filenames without considering the full path budget (folder + filename must
    be ≤225 chars together). For MAM-compliant paths, use `build_mam_path()`
    instead, which handles the combined length budget correctly.

    This function is suitable for:
    - Generic filesystem operations outside MAM context
    - Single component truncation where path budget isn't a concern
    - Legacy compatibility

    Strategy:
    1. If name fits, return as-is
    2. Preserve file extension
    3. Truncate base name, add hash suffix for uniqueness
    4. Try to break at word boundaries

    Args:
        name: Original filename
        max_length: Maximum allowed length
        preserve_extension: Keep file extension intact

    Returns:
        Truncated filename ≤ max_length characters
    """
    if len(name) <= max_length:
        return name

    path = Path(name)
    extension = path.suffix if preserve_extension else ""
    base = path.stem if preserve_extension else name

    # Reserve space for extension + hash suffix
    # Hash format: "...[abc123]" = 11 chars (3 dots + 1 open bracket + 6 hash + 1 close bracket)
    hash_suffix_len = 11
    available = max_length - len(extension) - hash_suffix_len

    if available <= 0:
        # Edge case: extension itself is too long
        # Just truncate everything
        return name[:max_length]

    # Generate short hash for uniqueness
    name_hash = hashlib.md5(name.encode()).hexdigest()[:6]

    # Truncate base name
    truncated_base = base[:available].rstrip()

    # Try to break at a word boundary
    if " " in truncated_base:
        last_space = truncated_base.rfind(" ")
        if last_space > available // 2:  # Only if we keep at least half
            truncated_base = truncated_base[:last_space]

    return f"{truncated_base}...[{name_hash}]{extension}"


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


def extract_volume_number(title: str, series_position: str | None = None) -> str | None:
    """
    Extract volume/book number from title or series_position.

    Priority:
    1. series_position if provided and numeric
    2. Vol/Volume/Book number from title
    3. Trailing number from title

    Args:
        title: Title string that may contain volume info
        series_position: Explicit series position if available

    Returns:
        Volume number as string (e.g., "3", "12"), or None if not found
    """
    # Priority 1: Use explicit series_position if it's numeric
    if series_position:
        # Handle "1.5", "2", etc. - validate proper decimal format
        clean_pos = series_position.strip()
        if clean_pos and re.match(r"^\d+(\.\d+)?$", clean_pos):
            return clean_pos

    # Priority 2-4: Extract from title using patterns
    for pattern in _VOL_EXTRACT_PATTERNS:
        match = pattern.search(title)
        if match:
            return match.group(1)

    return None


def format_volume_number(vol_num: str | None, zero_pad: bool = True) -> str:
    """
    Format volume number for folder/file naming.

    Args:
        vol_num: Volume number string (e.g., "3", "12", "1.5")
        zero_pad: Whether to zero-pad to 2 digits

    Returns:
        Formatted string like "vol_03" or "vol_12", empty string if no volume
    """
    if not vol_num:
        return ""

    # Handle decimal volumes (e.g., "1.5" -> "01.5")
    if "." in vol_num:
        parts = vol_num.split(".")
        if zero_pad and parts[0].isdigit():
            parts[0] = parts[0].zfill(2)
        return f"vol_{'.'.join(parts)}"

    # Integer volumes
    if vol_num.isdigit():
        if zero_pad:
            return f"vol_{vol_num.zfill(2)}"
        return f"vol_{vol_num}"

    return ""


def build_mam_folder_name(
    *,
    series: str | None = None,
    title: str,
    volume_number: str | None = None,
    arc: str | None = None,
    year: str | None = None,
    author: str | None = None,
    asin: str | None = None,
    ripper_tag: str | None = None,
    naming_config: NamingConfig | None = None,
    max_length: int = MAM_MAX_FILENAME_LENGTH,
) -> str:
    """
    Build a MAM-compliant folder name for staging.

    This is a convenience wrapper around build_mam_path() that returns just the folder name.
    For full path control (folder + filename), use build_mam_path() directly.

    Note: When max_length is less than 225, this function uses folder-only mode
    where max_length is the maximum folder length (not the full path budget).

    Schema for series books:
        {Series} vol_{NN} {Arc} ({Year}) ({Author}) {ASIN.xxxxx} [{Tag}]

    Schema for standalone books:
        {Title} ({Year}) ({Author}) {ASIN.xxxxx} [{Tag}]

    Args:
        series: Series name (cleaned). If None, treated as standalone.
        title: Book title (used for standalone books or fallback)
        volume_number: Volume/book number (e.g., "3", "12")
        arc: Arc/subtitle name (optional, e.g., "Aincrad")
        year: Release year (4 digits)
        author: Primary author name (cleaned)
        asin: Amazon ASIN (optional - if None, ASIN component is omitted)
        ripper_tag: Optional ripper tag (e.g., "H2OKing")
        naming_config: NamingConfig for cleaning rules
        max_length: Maximum folder length (default: 225 for MAM)

    Returns:
        Sanitized folder name within length limit
    """
    # Delegate to build_mam_path for centralized logic
    # Use folder_max_length for folder-only truncation
    mam_path = build_mam_path(
        series=series,
        title=title,
        volume_number=volume_number,
        arc=arc,
        year=year,
        author=author,
        asin=asin,
        ripper_tag=ripper_tag,
        naming_config=naming_config,
        max_path_length=MAM_MAX_PATH_LENGTH,  # Always use full budget
        folder_max_length=max_length,  # But constrain folder separately
    )
    return mam_path.folder


def _build_series_folder_name(
    *,
    series: str,
    vol_str: str,
    arc: str | None,
    year: str | None,
    author: str | None,
    asin_str: str,
    tag_str: str,
    max_length: int,
) -> str:
    """
    Build folder name for series book with truncation.

    Components in priority order (lowest priority dropped first):
    1. {Series} + vol_{NN} (identity - never truncate)
    2. {ASIN} (lookup key - never truncate)
    3. [{Tag}] (ripper credit)
    4. ({Year}) (sorting)
    5. ({Author}) (can truncate)
    6. {Arc} (can truncate or omit)
    """
    # Start with full name
    parts = [series, vol_str]

    # Optional components (will be dropped in reverse order if too long)
    optional_parts: list[tuple[str, str]] = []  # (component, label)

    if arc:
        optional_parts.append((arc, "arc"))
    if year:
        optional_parts.append((f"({year})", "year"))
    if author:
        optional_parts.append((f"({author})", "author"))

    # Required suffix (ASIN + tag)
    suffix_parts = []
    if asin_str:
        suffix_parts.append(asin_str)
    if tag_str:
        suffix_parts.append(tag_str)
    suffix = " ".join(suffix_parts)

    # Build name with all components
    def build_name(include_optional: list[tuple[str, str]]) -> str:
        result_parts = parts.copy()
        for comp, _ in include_optional:
            result_parts.append(comp)
        if suffix:
            result_parts.append(suffix)
        return " ".join(result_parts)

    # Try full name first
    full_name = build_name(optional_parts)
    if len(full_name) <= max_length:
        return full_name

    # Drop components from lowest priority (end of list) until it fits
    # Priority for dropping: arc -> author -> year -> tag
    drop_order = ["arc", "author", "year"]

    current_optional = optional_parts.copy()
    for drop_label in drop_order:
        # Remove this component
        current_optional = [
            (comp, label) for comp, label in current_optional if label != drop_label
        ]
        name = build_name(current_optional)
        if len(name) <= max_length:
            return name

    # Still too long? Try without tag
    if tag_str and suffix:
        suffix = asin_str
        name = " ".join(parts + [suffix]) if suffix else " ".join(parts)
        if len(name) <= max_length:
            return name

    # Last resort: truncate series name with "..."
    # Keep: series... vol_XX {ASIN}
    min_suffix_len = len(f" {vol_str} {asin_str}")
    available_for_series = max_length - min_suffix_len - 3  # "..."

    if available_for_series > 10:  # Reasonable minimum
        truncated_series = series[:available_for_series] + "..."
        return f"{truncated_series} {vol_str} {asin_str}"

    # Absolute fallback
    return f"{series[:50]}... {vol_str} {asin_str}"[:max_length]


def _build_standalone_folder_name(
    *,
    title: str,
    year: str | None,
    author: str | None,
    asin_str: str,
    tag_str: str,
    max_length: int,
) -> str:
    """
    Build folder name for standalone book with truncation.

    Schema: {Title} ({Year}) ({Author}) {ASIN} [{Tag}]

    Components in priority order (lowest priority dropped first):
    1. {Title} (identity - can truncate with ...)
    2. {ASIN} (lookup key - never truncate)
    3. [{Tag}] (ripper credit)
    4. ({Year}) (sorting)
    5. ({Author}) (can truncate)
    """
    parts = [title]

    # Optional components
    optional_parts: list[tuple[str, str]] = []
    if year:
        optional_parts.append((f"({year})", "year"))
    if author:
        optional_parts.append((f"({author})", "author"))

    # Required suffix
    suffix_parts = []
    if asin_str:
        suffix_parts.append(asin_str)
    if tag_str:
        suffix_parts.append(tag_str)
    suffix = " ".join(suffix_parts)

    def build_name(include_optional: list[tuple[str, str]]) -> str:
        result_parts = parts.copy()
        for comp, _ in include_optional:
            result_parts.append(comp)
        if suffix:
            result_parts.append(suffix)
        return " ".join(result_parts)

    # Try full name first
    full_name = build_name(optional_parts)
    if len(full_name) <= max_length:
        return full_name

    # Drop components
    drop_order = ["author", "year"]
    current_optional = optional_parts.copy()
    for drop_label in drop_order:
        current_optional = [
            (comp, label) for comp, label in current_optional if label != drop_label
        ]
        name = build_name(current_optional)
        if len(name) <= max_length:
            return name

    # Try without tag
    if tag_str:
        suffix = asin_str
        name = f"{title} {suffix}" if suffix else title
        if len(name) <= max_length:
            return name

    # Truncate title
    min_suffix_len = len(f" {asin_str}") if asin_str else 0
    available_for_title = max_length - min_suffix_len - 3

    if available_for_title > 10:
        truncated_title = title[:available_for_title] + "..."
        return f"{truncated_title} {asin_str}" if asin_str else truncated_title

    return f"{title[:50]}... {asin_str}"[:max_length] if asin_str else title[:max_length]


def build_mam_file_name(
    *,
    series: str | None = None,
    title: str,
    volume_number: str | None = None,
    arc: str | None = None,
    year: str | None = None,
    author: str | None = None,
    asin: str | None = None,
    extension: str = ".m4b",
    naming_config: NamingConfig | None = None,
    max_length: int = MAM_MAX_FILENAME_LENGTH,
) -> str:
    """
    Build a MAM-compliant file name (without ripper tag).

    This is a convenience wrapper around build_mam_path() that returns just the filename.
    For full path control (folder + filename), use build_mam_path() directly.

    Same schema as folder name but:
    - No ripper tag (only on folder)
    - Includes file extension

    Note: max_length is treated as the full path budget (folder + filename combined),
    not the raw filename length. Because the base name is shared between folder and
    filename, the actual filename will be approximately half of max_length. This
    ensures MAM's 225-char path limit is respected when folder and file are combined.

    Args:
        series: Series name (cleaned)
        title: Book title
        volume_number: Volume/book number
        arc: Arc/subtitle name
        year: Release year
        author: Primary author name
        asin: Amazon ASIN (optional - if None, ASIN component is omitted)
        extension: File extension (default: ".m4b")
        naming_config: NamingConfig for cleaning rules
        max_length: Path budget for truncation (not raw filename length).
                    The base name is truncated so folder + filename fit within this limit.

    Returns:
        Sanitized filename with extension within path budget
    """
    # Ensure extension starts with dot
    if extension and not extension.startswith("."):
        extension = f".{extension}"

    # Delegate to build_mam_path for centralized logic (no ripper tag for filename)
    mam_path = build_mam_path(
        series=series,
        title=title,
        volume_number=volume_number,
        arc=arc,
        year=year,
        author=author,
        asin=asin,
        ripper_tag=None,  # No tag on filename
        extension=extension,
        naming_config=naming_config,
        max_path_length=max_length,
    )
    return mam_path.filename


# =============================================================================
# PHASE 8: Full Path Truncation
# =============================================================================
# The 225-char limit applies to the FULL RELATIVE PATH (folder/filename),
# not individual components. The base name appears TWICE in the path,
# so every character saved from the base saves ~2 characters total.
#
# Path structure: "{base} [{tag}]/{base}{ext}"
#
# Budget formula (with tag):
#   Total = len(base) + 3 + len(tag) + 1 + len(base) + len(ext)
#         = 2*len(base) + len(tag) + len(ext) + 4
#
#   To fit in 225: max_base = (225 - len(tag) - len(ext) - 4) // 2
#
# Budget formula (no tag):
#   Total = len(base) + 1 + len(base) + len(ext)
#         = 2*len(base) + len(ext) + 1
#
#   To fit in 225: max_base = (225 - len(ext) - 1) // 2
#
# Examples with ".m4b" (4 chars):
#   With "H2OKing" (7 chars): max_base = (225 - 7 - 4 - 4) // 2 = 105 chars
#   With no tag:              max_base = (225 - 4 - 1) // 2     = 110 chars
#
# Multi-file adjustment for " - Part XX.m4b" (14 chars worst case):
#   With "H2OKing": max_base = (225 - 7 - 14 - 4) // 2 = 100 chars
#   With no tag:    max_base = (225 - 14 - 1) // 2     = 105 chars
# =============================================================================

# Minimum series length before we give up and just truncate
MIN_SERIES_LENGTH = 3

# Default MAM path length limit
MAM_MAX_PATH_LENGTH = 225


@functools.lru_cache(maxsize=1)
def _get_mam_path_class() -> type[MamPath]:
    """Lazy import of MamPath to avoid circular imports."""
    from mamfast.models import MamPath as MamPathClass

    return MamPathClass


def _calculate_max_base_length(
    *,
    ripper_tag: str | None,
    extension: str,
    part_count: int,
    max_path_length: int,
) -> int:
    """
    Calculate the maximum base name length given the path constraints.

    The base name appears TWICE in the path (folder + filename), so:
        path_length = 2*base + overhead

    Args:
        ripper_tag: Optional ripper tag (e.g., "H2OKing")
        extension: File extension including dot (e.g., ".m4b")
        part_count: Number of parts (>1 means multi-file)
        max_path_length: Maximum total path length (default: 225)

    Returns:
        Maximum allowed base name length
    """
    # Determine extension length (worst case for multi-file)
    # Using if/else to preserve the explanatory comment
    if part_count > 1:  # noqa: SIM108
        # " - Part XX.m4b" = 14 chars worst case
        ext_len = 14
    else:
        ext_len = len(extension)

    # Calculate overhead based on whether we have a tag
    # Using if/else to preserve the detailed math comments
    if ripper_tag:  # noqa: SIM108
        # With tag: folder = "{base} [{tag}]", filename = "{base}{ext}"
        # Total = len(base) + 1 + 1 + len(tag) + 1 + 1 + len(base) + ext_len
        #       = 2*len(base) + len(tag) + ext_len + 4
        tag_overhead = len(ripper_tag) + 4  # " [" + tag + "]" + "/"
    else:
        # No tag: folder = "{base}", filename = "{base}{ext}"
        # Total = len(base) + 1 + len(base) + ext_len
        #       = 2*len(base) + ext_len + 1
        tag_overhead = 1  # Just the "/" separator

    overhead = tag_overhead + ext_len
    max_base = (max_path_length - overhead) // 2

    return max_base


def _build_truncated_base_name(
    *,
    series: str | None,
    title: str,
    vol_str: str | None,
    arc: str | None,
    year: str | None,
    author: str | None,
    asin_str: str,
    max_length: int,
    naming_config: NamingConfig | None = None,
) -> tuple[str, bool, list[str]]:
    """
    Build a base name that fits within max_length, dropping components as needed.

    Drop priority is configurable via naming_config.path_drop_priority.
    Default order: ["arc", "author", "year"]

    {Series}, vol_{NN}, and {ASIN} are NEVER dropped (identity components).

    Args:
        series: Series name (cleaned)
        title: Book title (used for standalone books)
        vol_str: Formatted volume string (e.g., "vol_01") or None
        arc: Arc/subtitle name (optional)
        year: Release year (4 digits)
        author: Author name (cleaned)
        asin_str: Formatted ASIN string (e.g., "{ASIN.B0123}") or empty string
        max_length: Maximum allowed base name length
        naming_config: NamingConfig with path_drop_priority

    Returns:
        Tuple of (base_name, truncated, dropped_components)
    """
    dropped: list[str] = []

    # Get drop priority from config or use default
    drop_order = (
        naming_config.path_drop_priority
        if naming_config and naming_config.path_drop_priority
        else ["arc", "author", "year"]
    )

    # Determine if this is a series or standalone book
    is_series = bool(series and vol_str)

    # Track which optional components we have
    use_arc = bool(arc)
    use_year = bool(year)
    use_author = bool(author)

    def build_base(
        include_arc: bool = True,
        include_author: bool = True,
        include_year: bool = True,
        series_override: str | None = None,
    ) -> str:
        """Assemble base name from current components."""
        if is_series:
            current_series = series_override if series_override is not None else series
            parts = [f"{current_series} {vol_str}"]
        else:
            parts = [series_override if series_override is not None else title]

        if include_arc and arc:
            parts.append(arc)
        if include_year and year:
            parts.append(f"({year})")
        if include_author and author:
            parts.append(f"({author})")

        if asin_str:
            parts.append(asin_str)
        return " ".join(parts)

    # Try with all components
    base = build_base(include_arc=use_arc, include_author=use_author, include_year=use_year)
    if len(base) <= max_length:
        return base, False, dropped

    # Drop components in configured priority order
    for drop_label in drop_order:
        if drop_label == "arc" and use_arc:
            use_arc = False
            dropped.append("arc")
        elif drop_label == "author" and use_author:
            use_author = False
            dropped.append("author")
        elif drop_label == "year" and use_year:
            use_year = False
            dropped.append("year")
        else:
            continue

        base = build_base(include_arc=use_arc, include_author=use_author, include_year=use_year)
        if len(base) <= max_length:
            return base, True, dropped

    # Last resort: truncate series/title with "..."
    # Base without optionals: "{series} {vol_str} {asin_str}" or "{title} {asin_str}"
    if is_series:
        suffix_parts: list[str] = []
        if vol_str:
            suffix_parts.append(vol_str)
        if asin_str:
            suffix_parts.append(asin_str)
        suffix = " " + " ".join(suffix_parts) if suffix_parts else ""
        identity_to_truncate = series  # We know series is not None when is_series is True
    else:
        suffix = f" {asin_str}" if asin_str else ""
        identity_to_truncate = title

    # At this point identity_to_truncate is guaranteed to be a string
    assert identity_to_truncate is not None

    available_for_identity = max_length - len(suffix) - 3  # 3 for "..."

    if available_for_identity >= MIN_SERIES_LENGTH:
        dropped.append("series_truncated")
        truncated_identity = identity_to_truncate[:available_for_identity] + "..."
        if is_series:
            # vol_str is guaranteed to be not None when is_series is True
            assert vol_str is not None
            parts: list[str] = [truncated_identity, vol_str]
            if asin_str:
                parts.append(asin_str)
            base = " ".join(parts)
        else:
            base = f"{truncated_identity} {asin_str}" if asin_str else truncated_identity

        logger.warning(
            "Series/title truncation triggered for %s: '%s' -> '%s...' (%d chars available)",
            asin_str or "no-asin",
            identity_to_truncate,
            identity_to_truncate[:available_for_identity],
            available_for_identity,
        )
        return base, True, dropped

    # Absolute minimum fallback (should never happen with real data)
    logger.error(
        "Cannot fit base name in %d chars for %s - returning truncated identity",
        max_length,
        asin_str or "no-asin",
    )
    dropped.append("emergency_truncation")
    if asin_str:
        return (
            f"{identity_to_truncate[: max_length - len(asin_str) - 4]}... {asin_str}"[:max_length],
            True,
            dropped,
        )
    else:
        return (
            f"{identity_to_truncate[: max_length - 3]}..."[:max_length],
            True,
            dropped,
        )


def build_mam_path(
    *,
    series: str | None = None,
    title: str,
    volume_number: str | None = None,
    arc: str | None = None,
    year: str | None = None,
    author: str | None = None,
    asin: str | None = None,
    ripper_tag: str | None = None,
    extension: str = ".m4b",
    part_count: int = 1,
    naming_config: NamingConfig | None = None,
    max_path_length: int = MAM_MAX_PATH_LENGTH,
    folder_max_length: int | None = None,
) -> MamPath:
    """
    Build folder and filename ensuring combined path ≤ max_path_length.

    This is the CORRECT way to generate MAM paths. The 225-char limit applies
    to the full relative path (folder/filename), not individual components.

    Path structure: "{base} [{tag}]/{base}{ext}"

    The base name appears TWICE, so every character saved from base saves ~2
    characters from the total path length.

    Args:
        series: Series name (cleaned). If None, treated as standalone.
        title: Book title (used for standalone books or fallback)
        volume_number: Volume/book number (e.g., "3", "12")
        arc: Arc/subtitle name (optional, e.g., "Aincrad")
        year: Release year (4 digits)
        author: Primary author name (cleaned)
        asin: Amazon ASIN (optional - if None, ASIN component is omitted from path)
        ripper_tag: Optional ripper tag (e.g., "H2OKing")
        extension: File extension (default: ".m4b")
        part_count: Number of parts (>1 adjusts budget for " - Part XX")
        naming_config: NamingConfig for cleaning rules
        max_path_length: Maximum path length (default: 225 for MAM)
        folder_max_length: Optional constraint on folder length only (for legacy callers)

    Returns:
        MamPath with folder, filename, and truncation metadata
    """
    mam_path_cls = _get_mam_path_class()

    # Ensure extension starts with dot
    if extension and not extension.startswith("."):
        extension = f".{extension}"

    # Clean inputs - use filter_series() for series to apply series-specific patterns
    # (e.g., remove " Series", " Trilogy", "[publication order]" suffixes)
    clean_series = filter_series(series, naming_config=naming_config) if series else None
    clean_title = (
        filter_title(title, naming_config=naming_config, keep_volume=False) if title else ""
    )

    # Inherit "The" prefix from title to series if series lacks it
    # (e.g., title="The Great Cleric", series="Great Cleric" -> series="The Great Cleric")
    clean_series = inherit_the_prefix(clean_series, clean_title)

    clean_arc = filter_title(arc, naming_config=naming_config, keep_volume=False) if arc else None
    clean_author = sanitize_filename(author) if author else None

    # Format volume
    vol_str = format_volume_number(volume_number)

    # Format ASIN (optional - if None, omit ASIN component)
    # Pre-sanitize ASIN to ensure it doesn't introduce characters needing expansion later
    clean_asin = sanitize_filename(asin) if asin else None
    asin_str = f"{{ASIN.{clean_asin}}}" if clean_asin else ""

    # Calculate max base length
    # If folder_max_length is set, use min(folder constraint, path constraint)
    # This ensures both folder AND full path stay within their respective limits
    if folder_max_length is not None:
        # Folder = "{base} [{tag}]" or just "{base}"
        tag_overhead = len(f" [{ripper_tag}]") if ripper_tag else 0
        base_from_folder = folder_max_length - tag_overhead

        # Also calculate path budget to ensure full path stays within limit
        base_from_path = _calculate_max_base_length(
            ripper_tag=ripper_tag,
            extension=extension,
            part_count=part_count,
            max_path_length=max_path_length,
        )

        # Use the stricter of the two constraints
        max_base_len = min(base_from_folder, base_from_path)
    else:
        # Use path budget formula only
        max_base_len = _calculate_max_base_length(
            ripper_tag=ripper_tag,
            extension=extension,
            part_count=part_count,
            max_path_length=max_path_length,
        )

    # Build the base name (with truncation if needed)
    base_name, truncated, dropped = _build_truncated_base_name(
        series=clean_series,
        title=clean_title,
        vol_str=vol_str,
        arc=clean_arc,
        year=year,
        author=clean_author,
        asin_str=asin_str,
        max_length=max_base_len,
        naming_config=naming_config,
    )

    # Sanitize the base name (can increase length: e.g., ':' -> ' -')
    base_name = sanitize_filename(base_name)

    # Re-check length after sanitization - truncate if sanitization expanded it
    if len(base_name) > max_base_len:
        # Truncate to fit, preserving the ASIN at the end
        asin_idx = base_name.rfind("{ASIN.")
        if asin_idx > 0:
            # Keep ASIN intact, truncate before it
            available = max_base_len - (len(base_name) - asin_idx) - 4  # 4 for "... "
            if available > 3:
                base_name = base_name[:available] + "... " + base_name[asin_idx:]
                if not truncated:
                    truncated = True
                    dropped.append("sanitization_expansion")
            else:
                # Emergency: just hard truncate
                base_name = base_name[:max_base_len]
        else:
            base_name = base_name[:max_base_len]
        logger.debug(
            "Post-sanitization truncation for %s: base exceeded budget by %d chars",
            asin,
            len(base_name) - max_base_len,
        )

    # Check if tag was dropped during truncation (not yet implemented in _build_truncated_base_name)
    # For now, tag is always included if provided - it's handled by the budget formula

    # Sanitize ripper_tag to protect against special characters
    clean_tag = sanitize_filename(ripper_tag) if ripper_tag else None

    # Build folder and filename
    folder = f"{base_name} [{clean_tag}]" if clean_tag else base_name

    filename = f"{base_name}{extension}"
    full_path = f"{folder}/{filename}"

    # Log if truncation occurred
    if truncated:
        logger.debug(
            "Truncated MAM path for %s: %d chars, dropped: %s",
            asin,
            len(full_path),
            dropped,
        )

    return mam_path_cls(
        folder=folder,
        filename=filename,
        full_path=full_path,
        length=len(full_path),
        truncated=truncated,
        dropped_components=dropped,
    )


# =============================================================================
# Series Resolution (Multi-Source Fallback)
# =============================================================================

# Pre-compiled patterns for extracting series from title
# Order matters: more specific patterns first
#
# Patterns allow optional trailing content after the volume number:
# - Parenthetical content: "(Light Novel)", "(Unabridged)"
# - Subtitles after colon/dash: ": A Subtitle", "– The Continuation"
#
# Examples that will match:
# - "I'm the Evil Lord of an Intergalactic Empire!, Vol. 5 (Light Novel)"
# - "Black Summoner, Volume 4: The Legend Continues"
# - "Some Series, Vol. 3 – A Subtitle"
# - "Series Name Volume 5 (Unabridged)"
_SERIES_FROM_TITLE_PATTERNS: list[re.Pattern[str]] = [
    # "Series Name, Vol. 5" or "Series Name, Volume 5" (with optional trailing content)
    re.compile(
        r"^(?P<series>.+?),\s*(?:Vol\.?|Volume)\s*(?P<num>\d+(?:\.\d+)?)"
        r"(?:\s*\([^)]*\))?(?:\s*[:\-–—].+)?$",
        re.IGNORECASE,
    ),
    # "Series Name: Volume 5" or "Series Name: Vol. 5" (with optional trailing content)
    re.compile(
        r"^(?P<series>.+?):\s*(?:Vol\.?|Volume)\s*(?P<num>\d+(?:\.\d+)?)"
        r"(?:\s*\([^)]*\))?(?:\s*[:\-–—].+)?$",
        re.IGNORECASE,
    ),
    # "Series Name, Book 5" (with optional trailing content)
    re.compile(
        r"^(?P<series>.+?),\s*Book\s*(?P<num>\d+(?:\.\d+)?)" r"(?:\s*\([^)]*\))?(?:\s*[:\-–—].+)?$",
        re.IGNORECASE,
    ),
    # "Series Name: Book 5" (with optional trailing content)
    re.compile(
        r"^(?P<series>.+?):\s*Book\s*(?P<num>\d+(?:\.\d+)?)" r"(?:\s*\([^)]*\))?(?:\s*[:\-–—].+)?$",
        re.IGNORECASE,
    ),
    # "Series Name Vol. 5" (no comma/colon, with optional trailing content)
    re.compile(
        r"^(?P<series>.+?)\s+(?:Vol\.?|Volume)\s*(?P<num>\d+(?:\.\d+)?)"
        r"(?:\s*\([^)]*\))?(?:\s*[:\-–—].+)?$",
        re.IGNORECASE,
    ),
    # "Series Name Book 5" (no comma/colon, with optional trailing content)
    re.compile(
        r"^(?P<series>.+?)\s+Book\s*(?P<num>\d+(?:\.\d+)?)" r"(?:\s*\([^)]*\))?(?:\s*[:\-–—].+)?$",
        re.IGNORECASE,
    ),
    # "Series Name 5" (just trailing number) - low confidence
    # Requires series to have at least 2 words to avoid matching "Fahrenheit 451", "1984", etc.
    re.compile(
        r"^(?P<series>(?:\S+\s+)+\S+)\s+(?P<num>\d+)$",
    ),
]

# Pattern to extract vol_XX from folder/file name
_VOL_FROM_NAME_PATTERN = re.compile(r"vol_(\d+(?:\.\d+)?)", re.IGNORECASE)


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

    for pattern in _SERIES_FROM_TITLE_PATTERNS:
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
            vol_match = _VOL_FROM_NAME_PATTERN.search(book_folder)
            if vol_match:
                position = vol_match.group(1)

            return (series_name, position)

    return None


# Keep original simple logic as fallback (used internally for testing)
def _parse_series_from_libation_path_simple(
    libation_path: Path | None,
    book_folder_name: str | None = None,
) -> tuple[str, str | None] | None:
    """
    Simple/original series extraction from Libation path.

    Only checks immediate parent folder (parts[-2]).
    Kept for backwards compatibility and testing.
    """
    if not libation_path:
        return None

    parts = libation_path.parts
    if len(parts) < 3:
        return None

    book_folder = book_folder_name or parts[-1]
    potential_series = parts[-2]

    series_indicators = [
        "{ASIN." not in potential_series,
        "[ASIN." not in potential_series,
        not re.search(r"\(\d{4}\)", potential_series),
        "vol_" not in potential_series.lower(),
    ]

    author_pattern = re.compile(
        rf"\({re.escape(potential_series)}\)",
        re.IGNORECASE,
    )
    is_author_folder = bool(author_pattern.search(book_folder))

    if all(series_indicators) and not is_author_folder:
        series_name = potential_series.strip()
        position = None
        vol_match = _VOL_FROM_NAME_PATTERN.search(book_folder)
        if vol_match:
            position = vol_match.group(1)

        return (series_name, position)

    return None


def resolve_series(
    audnex_data: dict[str, Any] | None = None,
    libation_path: Path | None = None,
    title: str | None = None,
) -> Any:
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
            series_name = series_primary.get("name")
            if series_name:
                # Clean the series name
                cleaned_name = clean_series_name(series_name, title)
                if cleaned_name:
                    position = series_primary.get("position")
                    # If Audnex has no position, try to fill from other sources
                    if not position:
                        position = get_libation_position() or get_title_position()
                    return SeriesInfo(
                        name=cleaned_name,
                        position=str(position) if position else None,
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
