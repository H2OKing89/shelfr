"""
Filename sanitization and truncation for MAM compliance.

MAM has a 225-character limit on filenames/paths.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mamfast.config import FiltersConfig

# Characters not allowed in filenames (cross-platform safe)
ILLEGAL_CHARS = r'[<>:"/\\|?*]'

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

# Hardcoded patterns to always remove (regex patterns)
HARDCODED_REMOVE_PATTERNS = [
    # "Book 12", "Book XII", "Book: 12" etc - we keep vol_XX instead
    r"\bBook\s*[:\s]*\d+\b",
    r"\bBook\s*[:\s]*[IVXLCDM]+\b",
    # "Vol. 12" or "Volume 12" (but NOT vol_12 which is Libation format)
    r"\bVol\.\s*\d+\b",
    r"\bVolume\s*\d+\b",
    # Extra whitespace patterns
    r"\s*-\s*-\s*",  # Double dashes
    r"\s*,\s*,\s*",  # Double commas
]

# Roles to filter out from author lists (case-insensitive matching)
# These indicate the person is not the primary author
AUTHOR_ROLE_FILTERS = [
    "translator",
    "illustrator",
    "editor",
    "adapter",
    "contributor",
    "compiler",
    "afterword",
    "foreword",
    "introduction",
    "cover design",
    "cover art",
    "with ",  # "with John Smith"
]


def is_author_role(name: str) -> bool:
    """
    Check if a name string indicates a non-author role.

    Args:
        name: Author name string (e.g., "Jasmine Bernhardt - translator")

    Returns:
        True if this is a translator/illustrator/etc., False if primary author
    """
    name_lower = name.lower()
    return any(role in name_lower for role in AUTHOR_ROLE_FILTERS)


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

    # Remove any remaining illegal characters
    result = re.sub(ILLEGAL_CHARS, "", result)

    # Collapse multiple spaces
    result = re.sub(r"\s+", " ", result)

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

    # Apply hardcoded regex patterns
    for pattern in HARDCODED_REMOVE_PATTERNS:
        result = re.sub(pattern, "", result, flags=re.IGNORECASE)

    # Apply user-configured phrases (case-insensitive)
    if remove_phrases:
        for phrase in remove_phrases:
            # Escape regex special chars and make case-insensitive
            escaped = re.escape(phrase)
            result = re.sub(escaped, "", result, flags=re.IGNORECASE)

    # Collapse whitespace before duplicate check
    result = re.sub(r"\s+", " ", result)

    # Remove duplicate number before vol_XX (e.g., "Title 12 vol_12" -> "Title vol_12")
    # Must happen AFTER phrase removal so "12 <phrase> vol_12" -> "12 vol_12" -> "vol_12"
    result = re.sub(r"\b(\d+)\s+vol_\1\b", r"vol_\1", result)

    # Clean up whitespace artifacts
    result = re.sub(r"\s+", " ", result)  # Collapse multiple spaces
    result = re.sub(r"\s*-\s*-\s*", " - ", result)  # Fix double dashes
    result = re.sub(r"^\s*-\s*", "", result)  # Remove leading dash
    result = re.sub(r"\s*-\s*$", "", result)  # Remove trailing dash
    result = re.sub(r"\(\s*\)", "", result)  # Remove empty parens
    result = re.sub(r"\[\s*\]", "", result)  # Remove empty brackets
    result = result.strip()

    return result


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
        try:
            import pykakasi

            kks = pykakasi.kakasi()

            # Find non-ASCII segments and transliterate them
            def transliterate_segment(match: re.Match[str]) -> str:
                segment = match.group(0)
                # Check author_map first (already done above, but for safety)
                if segment in filters.author_map:
                    return filters.author_map[segment]
                # Use pykakasi
                converted = kks.convert(segment)
                romaji = " ".join([item["hepburn"] for item in converted])
                # Title case for names
                return romaji.title()

            # Match sequences of non-ASCII characters
            result = re.sub(r"[^\x00-\x7F]+", transliterate_segment, result)

        except ImportError:
            # pykakasi not installed, leave as-is
            pass

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
