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

# Author role detection patterns - use word boundaries to avoid false positives
# e.g., "translator" should match but "John Translator Smith" should NOT match
# Pattern matches: "- translator", "(translator)", "translator" at end, standalone "translator"
_ROLE_WORDS = r"translator|illustrator|editor|adapter|contributor|compiler"
_CREDIT_WORDS = r"afterword|foreword|introduction"
_AUTHOR_ROLE_PATTERN = re.compile(
    rf"""
    (?:
        \s*-\s*(?:{_ROLE_WORDS})s?\s*$  |           # "- translator" at end
        \s*\(\s*(?:{_ROLE_WORDS})s?\s*\)  |         # "(translator)"
        \s*,\s*(?:{_ROLE_WORDS})s?\s*$  |           # ", translator" at end
        ^\s*(?:{_CREDIT_WORDS})\s+by\s  |           # "Foreword by ..."
        \s*\(\s*(?:{_CREDIT_WORDS})\s*\)  |         # "(foreword)"
        \s*-\s*(?:{_CREDIT_WORDS})\s*$  |           # "- foreword" at end
        \s*-\s*(?:cover\s+design|cover\s+art)\s*$  |  # "- cover design" at end
        ^with\s                                     # "with John Smith" at start
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


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
    return bool(_AUTHOR_ROLE_PATTERN.search(name))


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
    1. Check preserve_exact - skip ALL cleaning if matched
    2. Hardcoded patterns (Book XX, etc.)
    3. Volume patterns (Vol. XX, Volume XX) - unless keep_volume=True
    4. Config patterns: format_indicators, genre_tags, publisher_tags
    5. Legacy remove_phrases (for backward compatibility)
    6. Duplicate number before vol_XX cleanup

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

    # Step 1: Check preserve_exact - skip ALL cleaning if matched
    if naming_config and naming_config.preserve_exact:
        for preserved in naming_config.preserve_exact:
            if name == preserved or preserved in name:
                if verbose:
                    logger.debug(
                        f"[filter_title] '{name}' -> '{name}' (preserved via preserve_exact)"
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

    # Step 3: Apply naming config patterns (format_indicators, genre_tags, publisher_tags)
    if naming_config:
        # Format indicators (case-insensitive phrase matching)
        for phrase in naming_config.format_indicators:
            before = result
            escaped = re.escape(phrase)
            result = re.sub(escaped, "", result, flags=re.IGNORECASE)
            if before != result and verbose:
                transformations.append((before, result, f"format_indicators:{phrase}"))

        # Genre tags (case-insensitive phrase matching)
        for phrase in naming_config.genre_tags:
            before = result
            escaped = re.escape(phrase)
            result = re.sub(escaped, "", result, flags=re.IGNORECASE)
            if before != result and verbose:
                transformations.append((before, result, f"genre_tags:{phrase}"))

        # Publisher tags (case-insensitive phrase matching)
        for phrase in naming_config.publisher_tags:
            before = result
            escaped = re.escape(phrase)
            result = re.sub(escaped, "", result, flags=re.IGNORECASE)
            if before != result and verbose:
                transformations.append((before, result, f"publisher_tags:{phrase}"))

    # Step 4: Apply legacy user-configured phrases (backward compatibility)
    if remove_phrases:
        for phrase in remove_phrases:
            before = result
            escaped = re.escape(phrase)
            result = re.sub(escaped, "", result, flags=re.IGNORECASE)
            if before != result and verbose:
                transformations.append((before, result, f"remove_phrases:{phrase}"))

    # Step 5: Collapse whitespace before duplicate check
    result = _WHITESPACE_PATTERN.sub(" ", result)

    # Step 6: Remove duplicate number before vol_XX (e.g., "Title 12 vol_12" -> "Title vol_12")
    before = result
    result = _DUPLICATE_VOL_PATTERN.sub(r"vol_\1", result)
    if before != result and verbose:
        transformations.append((before, result, "duplicate_vol_cleanup"))

    # Step 7: Clean up whitespace artifacts
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

    # Check if preserved (already handled in filter_title, but double-check)
    if naming_config and naming_config.preserve_exact:
        for preserved in naming_config.preserve_exact:
            if name == preserved or preserved in name:
                return result  # Already preserved

    transformations: list[tuple[str, str, str]] = []

    # Apply series suffix patterns (regex, case-insensitive, end-anchored)
    if naming_config and naming_config.series_suffixes:
        for pattern_str in naming_config.series_suffixes:
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

    # Step 1: Check preserve_exact - skip ALL cleaning if matched
    if naming_config and naming_config.preserve_exact:
        for preserved in naming_config.preserve_exact:
            if subtitle == preserved or preserved in subtitle:
                if verbose:
                    logger.debug(
                        f"[filter_subtitle] '{subtitle}' -> '{subtitle}' "
                        "(preserved via preserve_exact)"
                    )
                return subtitle

    # Step 2: Check keep_patterns FIRST - whitelist to preserve special subtitles
    if naming_config and naming_config.subtitle_keep_patterns:
        for pattern_str in naming_config.subtitle_keep_patterns:
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
        for pattern_str in naming_config.subtitle_remove_patterns:
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
        for rule in naming_config.subtitle_redundancy_rules:
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

    # First, apply author_map for exact substring matches
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
