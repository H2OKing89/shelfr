"""
Author role detection and filtering.

Provides utilities to:
- Detect non-author roles (translator, illustrator, editor, etc.)
- Filter author lists to exclude non-primary authors
- Extract translator names from author lists
"""

from __future__ import annotations

import logging
import re
from typing import TypedDict

from mamfast.utils.naming.constants import (
    DEFAULT_CREDIT_WORDS,
    DEFAULT_ROLE_WORDS,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Volume Info TypedDict
# =============================================================================


class VolumeInfo(TypedDict, total=False):
    """Parsed volume information with support for parts and ranges.

    Volume Notation Reference:
        - vol_01      → Single volume (base=1)
        - vol_01.5    → Novella/side story (base=1.5)
        - vol_01-03   → Range/Publisher Pack (base=1, range_end=3)
        - vol_01p1    → Split part/Graphic Audio (base=1, part=1)

    See docs/naming/NAMING_FOLDER_FILE_SCHEMAS.md#volume-notation for details.
    """

    base: float  # Required: Main volume number (e.g., 1, 1.5, 12)
    range_end: float | None  # Optional: End of range for omnibus (e.g., 3 for vol_01-03)
    part: int | None  # Optional: Part number for GA splits (e.g., 1 for vol_01p1)


# =============================================================================
# Author Role Pattern Building
# =============================================================================


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
    roles = DEFAULT_ROLE_WORDS if role_words is None else role_words
    credits = DEFAULT_CREDIT_WORDS if credit_words is None else credit_words

    # Build alternation patterns (use never-matching pattern if empty)
    role_pattern = "|".join(re.escape(r) for r in roles) if roles else "(?!)"
    credit_pattern = "|".join(re.escape(c) for c in credits) if credits else "(?!)"

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
    except ImportError as e:
        # Config module not available
        logger.debug("Failed to import config module, using default pattern: %r", e)
    except FileNotFoundError as e:
        # Config file missing
        logger.debug("Config file not found, using default pattern: %r", e)
    except Exception as e:
        # Pydantic validation or other config errors - use default
        logger.debug("Failed to load author role pattern from config, using default: %r", e)
    return _AUTHOR_ROLE_PATTERN


# =============================================================================
# Public Functions
# =============================================================================


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
