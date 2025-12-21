"""
String utilities for filename processing.

Provides low-level string manipulation functions:
- Transliteration of foreign text (especially Japanese)
- Filename truncation with hash suffixes
- Whitespace and punctuation cleanup
"""

from __future__ import annotations

import functools
import hashlib
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mamfast.config import FiltersConfig

from mamfast.utils.naming.constants import (
    DOUBLE_DASH_PATTERN,
    EMPTY_BRACKETS_PATTERN,
    EMPTY_PARENS_PATTERN,
    LEADING_DASH_PATTERN,
    LEADING_PUNCT_PATTERN,
    NON_ASCII_PATTERN,
    SPACE_BEFORE_PUNCT_PATTERN,
    TRAILING_DASH_PATTERN,
    TRAILING_PUNCT_PATTERN,
    WHITESPACE_PATTERN,
)

logger = logging.getLogger(__name__)


def cleanup_string(text: str) -> str:
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
    result = WHITESPACE_PATTERN.sub(" ", result)  # Collapse multiple spaces
    result = DOUBLE_DASH_PATTERN.sub(" - ", result)  # Fix double dashes
    result = LEADING_DASH_PATTERN.sub("", result)  # Remove leading dash
    result = TRAILING_DASH_PATTERN.sub("", result)  # Remove trailing dash
    result = EMPTY_PARENS_PATTERN.sub("", result)  # Remove empty parens
    result = EMPTY_BRACKETS_PATTERN.sub("", result)  # Remove empty brackets
    result = SPACE_BEFORE_PUNCT_PATTERN.sub(r"\1", result)  # Fix "word ," -> "word,"
    result = TRAILING_PUNCT_PATTERN.sub("", result)  # Remove trailing comma/colon
    result = LEADING_PUNCT_PATTERN.sub("", result)  # Remove leading comma/colon
    # Re-collapse spaces after punctuation fixes
    result = WHITESPACE_PATTERN.sub(" ", result)
    result = result.strip()
    return result


# Alias for internal use (matches old naming)
_cleanup_string = cleanup_string


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
            result = NON_ASCII_PATTERN.sub(transliterate_segment, result)

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
