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
    from mamfast.config import FiltersConfig

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
# These patterns are always removed from titles
_COMPILED_REMOVE_PATTERNS: list[re.Pattern[str]] = [
    # "Book 12", "Book XII", "Book: 12" etc - we keep vol_XX instead
    re.compile(r"\bBook\s*[:\s]*\d+\b", re.IGNORECASE),
    re.compile(r"\bBook\s*[:\s]*[IVXLCDM]+\b", re.IGNORECASE),
    # "Vol. 12" or "Volume 12" (but NOT vol_12 which is Libation format)
    re.compile(r"\bVol\.\s*\d+\b", re.IGNORECASE),
    re.compile(r"\bVolume\s*\d+\b", re.IGNORECASE),
    # Extra whitespace patterns
    re.compile(r"\s*-\s*-\s*"),  # Double dashes
    re.compile(r"\s*,\s*,\s*"),  # Double commas
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


def filter_title(name: str, remove_phrases: list[str] | None = None) -> str:
    """
    Remove unwanted phrases from a title/folder name.

    Applies:
    1. Hardcoded patterns (Book XX, Vol. XX, etc.)
    2. User-configured phrases from config.yaml
    3. Duplicate number before vol_XX (e.g., "Title 12 vol_12" -> "Title vol_12")

    Args:
        name: Original name
        remove_phrases: List of phrases to remove (case-insensitive)

    Returns:
        Filtered name with unwanted phrases removed
    """
    result = name

    # Apply pre-compiled hardcoded patterns
    for pattern in _COMPILED_REMOVE_PATTERNS:
        result = pattern.sub("", result)

    # Apply user-configured phrases (case-insensitive)
    if remove_phrases:
        for phrase in remove_phrases:
            # Escape regex special chars and make case-insensitive
            escaped = re.escape(phrase)
            result = re.sub(escaped, "", result, flags=re.IGNORECASE)

    # Collapse whitespace before duplicate check
    result = _WHITESPACE_PATTERN.sub(" ", result)

    # Remove duplicate number before vol_XX (e.g., "Title 12 vol_12" -> "Title vol_12")
    # Must happen AFTER phrase removal so "12 <phrase> vol_12" -> "12 vol_12" -> "vol_12"
    result = _DUPLICATE_VOL_PATTERN.sub(r"vol_\1", result)

    # Clean up whitespace artifacts using pre-compiled patterns
    result = _WHITESPACE_PATTERN.sub(" ", result)  # Collapse multiple spaces
    result = _DOUBLE_DASH_PATTERN.sub(" - ", result)  # Fix double dashes
    result = _LEADING_DASH_PATTERN.sub("", result)  # Remove leading dash
    result = _TRAILING_DASH_PATTERN.sub("", result)  # Remove trailing dash
    result = _EMPTY_PARENS_PATTERN.sub("", result)  # Remove empty parens
    result = _EMPTY_BRACKETS_PATTERN.sub("", result)  # Remove empty brackets
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

        return pykakasi.kakasi()
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
