"""
Filename filtering and sanitization.

Provides functions to clean up filenames and titles:
- sanitize_filename: Remove illegal characters
- filter_title: Remove unwanted phrases from titles
- filter_series: Clean series names with suffix removal
- filter_subtitle: Two-tier subtitle filtering
- filter_author: Clean author names
- inherit_the_prefix: Inherit "The" prefix from title to series
"""

from __future__ import annotations

import functools
import logging
import re
from typing import TYPE_CHECKING, Any

from pathvalidate import sanitize_filename as pv_sanitize_filename

if TYPE_CHECKING:
    from mamfast.config import NamingConfig

from mamfast.utils.naming.authors import (
    filter_authors,
)
from mamfast.utils.naming.constants import (
    COMPILED_REMOVE_PATTERNS,
    COMPILED_VOLUME_PATTERNS,
    DEFAULT_CREDIT_WORDS,
    DEFAULT_ROLE_WORDS,
    DUPLICATE_VOL_PATTERN,
    NORMALIZE_MAP,
    WHITESPACE_PATTERN,
)
from mamfast.utils.naming.string_utils import cleanup_string

# Alias for internal use
_cleanup_string = cleanup_string

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=256)
def _compile_phrase_pattern(phrase: str) -> re.Pattern[str]:
    """
    Compile a case-insensitive pattern for phrase removal.

    Caches compiled patterns to avoid recompilation on every call.
    """
    escaped = re.escape(phrase)
    return re.compile(escaped, re.IGNORECASE)


def sanitize_filename(name: str) -> str:
    """
    Remove or replace characters that are problematic in filenames.

    Uses pathvalidate library for cross-platform MAM compliance with
    225-character limit and universal platform compatibility. Additional
    normalization applies character replacements and whitespace cleanup.
    """
    # Apply character normalization before pathvalidate
    result = name
    for char, replacement in NORMALIZE_MAP.items():
        result = result.replace(char, replacement)

    # Collapse multiple spaces (using pre-compiled pattern)
    result = WHITESPACE_PATTERN.sub(" ", result)

    # Strip leading/trailing whitespace and dots
    result = result.strip(". ")

    # Delegate to pathvalidate for cross-platform filename validation
    return pv_sanitize_filename(result, platform="universal", max_len=225)


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
    for pattern in COMPILED_REMOVE_PATTERNS:
        before = result
        result = pattern.sub("", result)
        if before != result and verbose:
            transformations.append((before, result, "hardcoded_patterns"))

    # Step 3: Apply volume patterns (only if keep_volume=False)
    if not keep_volume:
        for pattern in COMPILED_VOLUME_PATTERNS:
            before = result
            result = pattern.sub("", result)
            if before != result and verbose:
                transformations.append((before, result, "volume_patterns"))

    # Step 4: Apply naming config patterns (format_indicators, genre_tags, publisher_tags)
    if naming_config:
        # Format indicators (case-insensitive phrase matching)
        for phrase in naming_config.format_indicators or []:
            before = result
            pattern = _compile_phrase_pattern(phrase)
            result = pattern.sub("", result)
            if before != result and verbose:
                transformations.append((before, result, f"format_indicators:{phrase}"))

        # Genre tags (case-insensitive phrase matching)
        for phrase in naming_config.genre_tags or []:
            before = result
            pattern = _compile_phrase_pattern(phrase)
            result = pattern.sub("", result)
            if before != result and verbose:
                transformations.append((before, result, f"genre_tags:{phrase}"))

        # Publisher tags (case-insensitive phrase matching)
        for phrase in naming_config.publisher_tags or []:
            before = result
            pattern = _compile_phrase_pattern(phrase)
            result = pattern.sub("", result)
            if before != result and verbose:
                transformations.append((before, result, f"publisher_tags:{phrase}"))

    # Step 5: Apply legacy user-configured phrases (backward compatibility)
    if remove_phrases:
        for phrase in remove_phrases:
            before = result
            pattern = _compile_phrase_pattern(phrase)
            result = pattern.sub("", result)
            if before != result and verbose:
                transformations.append((before, result, f"remove_phrases:{phrase}"))

    # Step 6: Collapse whitespace before duplicate check
    result = WHITESPACE_PATTERN.sub(" ", result)

    # Step 7: Remove duplicate number before vol_XX (e.g., "Title 12 vol_12" -> "Title vol_12")
    before = result
    result = DUPLICATE_VOL_PATTERN.sub(r"vol_\1", result)
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
                f"[filter_subtitle] '{subtitle}' -> '{subtitle}' (preserved via preserve_exact)"
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


def filter_author(
    name: str,
    *,
    naming_config: NamingConfig | None = None,
) -> str:
    """
    Filter and clean an author name.

    - Sanitizes the filename (removes illegal characters)
    - Applies transliteration if configured

    Args:
        name: Original author name
        naming_config: NamingConfig with transliteration settings

    Returns:
        Cleaned author name
    """
    result = sanitize_filename(name)

    # Apply transliteration if configured
    if naming_config:
        try:
            from mamfast.config import get_settings

            settings = get_settings()
            if settings.filters:
                from mamfast.utils.naming.string_utils import transliterate_text

                result = transliterate_text(result, settings.filters)
        except Exception as e:
            logger.debug("Failed to apply transliteration: %r", e)

    return result


# =============================================================================
# MediaInfo Integration
# =============================================================================


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
    roles = DEFAULT_ROLE_WORDS if role_words is None else role_words
    credits = DEFAULT_CREDIT_WORDS if credit_words is None else credit_words

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
