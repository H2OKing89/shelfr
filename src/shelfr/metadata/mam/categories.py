"""
MAM category mapping and genre inference.

Maps Audnex genres to MAM audiobook categories and infers fiction/nonfiction
classification.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from shelfr.config import get_settings

logger = logging.getLogger(__name__)

# Genre keywords that indicate Fiction (case-insensitive matching)
FICTION_GENRE_KEYWORDS = frozenset(
    [
        "fantasy",
        "fiction",
        "mystery",
        "thriller",
        "suspense",
        "romance",
        "horror",
        "sci-fi",
        "science fiction",
        "adventure",
        "detective",
        "crime",
        "western",
        "humor",
        "comedy",
        "drama",
        "erotica",
        "paranormal",
        "urban",
        "epic",
        "literary",
        "classics",
        "historical fiction",
        "contemporary",
        "dystopian",
        "fairy tales",
        "mythology",
        "legends",
        "anthologies",
        "short stories",
    ]
)

# Genre keywords that indicate Non-Fiction (case-insensitive matching)
NONFICTION_GENRE_KEYWORDS = frozenset(
    [
        "biography",
        "biographies",
        "memoir",
        "self-help",
        "business",
        "history",
        "science",
        "politics",
        "religion",
        "spirituality",
        "philosophy",
        "psychology",
        "health",
        "fitness",
        "cooking",
        "travel",
        "true crime",
        "education",
        "reference",
        "how-to",
        "guide",
        "self development",
        "personal development",
        "finance",
        "economics",
        "journalism",
        "essays",
        "nature",
        "technology",
        "computers",
    ]
)


def _infer_fiction_or_nonfiction(audnex_data: dict[str, Any]) -> int:
    """
    Infer whether a book is Fiction (1) or Non-Fiction (2).

    Audnex literatureType is unreliable, so we check genres first.
    Fiction keywords take priority since genre keywords like "fantasy"
    are unambiguous, while non-fiction keywords may appear in fiction
    (e.g., "historical fiction").

    Args:
        audnex_data: Audnex API response

    Returns:
        1 for Fiction, 2 for Non-Fiction
    """
    genres = audnex_data.get("genres", [])
    genre_names_lower = [g.get("name", "").lower() for g in genres]
    all_genre_text = " ".join(genre_names_lower)

    # Check for fiction indicators first (higher priority)
    # Use word boundary matching to avoid false positives (e.g., "urban" in "Suburban")
    for keyword in FICTION_GENRE_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", all_genre_text):
            return 1  # Fiction

    # Check for non-fiction indicators
    for keyword in NONFICTION_GENRE_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", all_genre_text):
            return 2  # Non-Fiction

    # Fallback to literatureType if genres don't give a clear signal
    lit_type = audnex_data.get("literatureType", "").lower()
    if lit_type == "fiction":
        return 1
    if lit_type in ("non-fiction", "nonfiction"):
        return 2

    # Default to Fiction (most audiobooks are fiction)
    return 1


def _get_audiobook_category(audnex_data: dict[str, Any], is_fiction: bool) -> str:
    """
    Determine the MAM audiobook category string from genres.

    Uses config/audiobook_categories.json mappings. Checks genre keywords
    against the appropriate map (fiction or nonfiction) and returns the
    first match. Falls back to default category if no match found.

    Note: Order of keywords in the JSON file matters (first match wins).
    This relies on Python 3.7+ dict insertion order preservation.
    More specific keywords (e.g., "urban fantasy") should appear before
    general ones (e.g., "fantasy") in the JSON file.

    Args:
        audnex_data: Audnex API response
        is_fiction: Whether the book is fiction (from _infer_fiction_or_nonfiction)

    Returns:
        MAM audiobook category string (e.g., "Audiobooks - Fantasy")
    """
    # Default fallback
    default_category = (
        "Audiobooks - General Fiction" if is_fiction else "Audiobooks - General Non-Fic"
    )

    try:
        settings = get_settings()
        categories = settings.categories
    except Exception:
        logger.debug("Failed to load category settings, using default: %s", default_category)
        return default_category

    # Select the appropriate map based on fiction/nonfiction
    if is_fiction:
        category_map = categories.audiobook_fiction_map
        default_key = "fiction"
    else:
        category_map = categories.audiobook_nonfiction_map
        default_key = "nonfiction"

    # Get default from config
    default_category = categories.audiobook_defaults.get(default_key, default_category)

    # If no map loaded, return default
    if not category_map:
        return default_category

    # Build genre text for matching
    genres = audnex_data.get("genres", [])
    genre_names_lower = [g.get("name", "").lower() for g in genres]
    all_genre_text = " ".join(genre_names_lower)

    # Check each keyword in the map (order matters - first match wins)
    # Use word boundary matching to avoid false positives (e.g., "art" in "martial")
    for keyword, category in category_map.items():
        if re.search(rf"\b{re.escape(keyword)}\b", all_genre_text):
            return category

    return default_category


def _map_genres_to_categories(genres: list[dict[str, Any]]) -> list[int]:
    """
    Map Audnex genres to MAM category IDs.

    Handles compound genres like "Science Fiction & Fantasy" by:
    1. First trying exact match for the full compound string
    2. Then splitting on " & " and ", " to match individual components

    Args:
        genres: List of genre dicts from Audnex (with 'name' key)

    Returns:
        List of unique MAM category IDs
    """
    try:
        settings = get_settings()
        category_map = settings.categories.genre_map
    except Exception:
        logger.debug("Failed to load genre map settings, returning empty categories")
        return []

    categories: set[int] = set()

    for genre in genres:
        name = genre.get("name", "").lower().strip()
        if not name:
            continue

        # First try exact match for the full string
        if name in category_map:
            categories.add(category_map[name])
            continue

        # Split compound genres on " & " and ", " to match individual parts
        # e.g., "Science Fiction & Fantasy" -> ["science fiction", "fantasy"]
        # e.g., "Literature & Fiction, Fantasy" -> ["literature", "fiction", "fantasy"]
        parts = []
        for part in name.replace(" & ", ", ").split(", "):
            part = part.strip()
            if part:
                parts.append(part)

        # Try to match each part
        matched = False
        for part in parts:
            if part in category_map:
                categories.add(category_map[part])
                matched = True

        # Fallback: word-boundary matching if no parts matched
        # Use regex with word boundaries to avoid false positives
        # (e.g., "art" matching "artificial intelligence")
        # Only try keys with 4+ characters to reduce collision risk
        if not matched:
            for key, cat_id in category_map.items():
                if len(key) >= 4 and re.search(rf"\b{re.escape(key)}\b", name):
                    categories.add(cat_id)
                    break

    return sorted(categories)
