"""
MAM category mapping and genre inference.

Maps Audnex genres to MAM audiobook categories and infers fiction/nonfiction
classification.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
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


# =============================================================================
# Category Resolver (Signal Scoring)
# =============================================================================

# Signal weights for category scoring
SIGNAL_WEIGHTS: dict[str, float] = {
    "audnex_genre": 1.0,
    "hardcover_genre": 0.8,
    "hardcover_mood": 0.3,
}

# Penalty multiplier for generic/vague terms
GENERIC_PENALTY: float = 0.5

# Terms that provide little category signal (normalized lowercase)
GENERIC_TERMS: frozenset[str] = frozenset(
    {
        "fiction",
        "general fiction",
        "contemporary",
        "nonfiction",
        "non-fiction",
        "general nonfiction",
        "general non-fiction",
        "general",
        "literature",
        "literature & fiction",
    }
)

# Mood → candidate categories (moods can only reinforce, not create)
MOOD_CATEGORY_HINTS: dict[str, list[str]] = {
    "dark": ["Audiobooks - Horror", "Audiobooks - Crime/Thriller"],
    "mysterious": ["Audiobooks - Crime/Thriller", "Audiobooks - Mystery"],
    "tense": ["Audiobooks - Crime/Thriller", "Audiobooks - Thriller/Suspense"],
    "romantic": ["Audiobooks - Romance"],
    "funny": ["Audiobooks - General Fiction", "Audiobooks - Comedy"],
    "lighthearted": ["Audiobooks - General Fiction", "Audiobooks - Romance"],
    "adventurous": ["Audiobooks - Action/Adventure", "Audiobooks - Fantasy"],
    "hopeful": ["Audiobooks - Romance", "Audiobooks - General Fiction"],
    "sad": ["Audiobooks - Literary Classics", "Audiobooks - Drama/Plays"],
    "emotional": ["Audiobooks - Romance", "Audiobooks - Drama/Plays"],
    "informative": ["Audiobooks - General Non-Fic", "Audiobooks - Self-Help"],
    "inspiring": ["Audiobooks - Self-Help", "Audiobooks - Biographical"],
    "challenging": ["Audiobooks - Literary Classics", "Audiobooks - Literary Fiction"],
    "reflective": ["Audiobooks - Literary Fiction", "Audiobooks - Self-Help"],
}


@dataclass(frozen=True)
class Signal:
    """A single genre or mood signal from a metadata source."""

    source: str  # "audnex_genre" | "hardcover_genre" | "hardcover_mood"
    term: str  # The genre/mood string


@dataclass(frozen=True)
class Contribution:
    """A signal's contribution to a category score."""

    category: str
    source: str
    term: str
    delta: float


@dataclass
class Resolution:
    """Result of category resolution with scores and provenance."""

    category: str
    scores: dict[str, float] = field(default_factory=dict)
    contributions: list[Contribution] = field(default_factory=list)
    is_fiction: bool = True


class CategoryResolver:
    """
    Resolves MAM audiobook category from multiple metadata sources using signal scoring.

    Combines genres from Audnex and Hardcover, plus Hardcover moods, to determine
    the best MAM category. Uses weighted scoring with:
    - Audnex genres: weight 1.0 (primary source)
    - Hardcover genres: weight 0.8 (strong fallback)
    - Hardcover moods: weight 0.3 (tie-breaker hints)

    Generic terms (e.g., "Fiction", "Contemporary") receive a penalty.
    Moods can only reinforce categories that already have genre support.
    Ties are broken deterministically: Audnex-backed > Hardcover-backed > alphabetical.
    """

    def __init__(self, category_keywords: dict[str, list[str]] | None = None):
        """
        Initialize resolver with category keyword mappings.

        Args:
            category_keywords: Map of MAM category → list of matching keywords.
                If None, loads from config/audiobook_categories.json.
        """
        if category_keywords is not None:
            self.category_keywords = {
                cat: [self._norm(k) for k in keys] for cat, keys in category_keywords.items()
            }
        else:
            # Load from config
            self.category_keywords = self._load_category_keywords()

    def _load_category_keywords(self) -> dict[str, list[str]]:
        """Load category keywords from config, inverting the map."""
        try:
            settings = get_settings()
            categories = settings.categories

            # Combine fiction and nonfiction maps, inverting keyword→category
            # to category→keywords
            result: dict[str, list[str]] = {}

            for keyword, category in categories.audiobook_fiction_map.items():
                result.setdefault(category, []).append(self._norm(keyword))

            for keyword, category in categories.audiobook_nonfiction_map.items():
                result.setdefault(category, []).append(self._norm(keyword))

            return result
        except Exception:
            logger.debug("Failed to load category keywords from config")
            return {}

    def resolve(
        self,
        audnex_genres: Iterable[str] | None = None,
        hardcover_genres: Iterable[str] | None = None,
        hardcover_moods: Iterable[str] | None = None,
        is_fiction: bool = True,
    ) -> Resolution:
        """
        Resolve the best MAM category from available signals.

        Args:
            audnex_genres: Genre names from Audnex API
            hardcover_genres: Genre names from Hardcover API
            hardcover_moods: Mood names from Hardcover API
            is_fiction: Whether the book is fiction (affects default)

        Returns:
            Resolution with category, scores, and contributions
        """
        default_category = (
            "Audiobooks - General Fiction" if is_fiction else "Audiobooks - General Non-Fic"
        )

        # Build signals list
        signals: list[Signal] = []
        for g in audnex_genres or []:
            signals.append(Signal("audnex_genre", g))
        for g in hardcover_genres or []:
            signals.append(Signal("hardcover_genre", g))
        for m in hardcover_moods or []:
            signals.append(Signal("hardcover_mood", m))

        if not signals:
            return Resolution(default_category, {}, [], is_fiction)

        scores: dict[str, float] = {}
        contribs: list[Contribution] = []

        # First pass: find categories backed by genre signals (not moods)
        genre_backed: set[str] = set()
        for s in signals:
            if s.source.endswith("_genre"):
                for cat in self._match_categories(s.term):
                    genre_backed.add(cat)

        # Second pass: score all signals
        for s in signals:
            weight = SIGNAL_WEIGHTS.get(s.source, 0.0)
            if weight <= 0:
                continue

            term_n = self._norm(s.term)
            penalty = GENERIC_PENALTY if term_n in GENERIC_TERMS else 1.0

            matched = self._match_categories(s.term)

            # Mood rule: only reinforce existing genre-backed categories
            if s.source == "hardcover_mood" and genre_backed:
                matched = [c for c in matched if c in genre_backed]
                # If no genre backing, moods can still suggest categories
                # but with reduced weight (already lower at 0.3)

            for cat in matched:
                delta = weight * penalty
                scores[cat] = scores.get(cat, 0.0) + delta
                contribs.append(Contribution(cat, s.source, s.term, delta))

        if not scores:
            return Resolution(default_category, {}, [], is_fiction)

        best = self._pick_best_category(scores, contribs)
        top_contribs = self._top_contributions(best, contribs)

        return Resolution(best, scores, top_contribs, is_fiction)

    def format_reason(self, res: Resolution, max_items: int = 3) -> str:
        """
        Format resolution contributions as a human-readable reason string.

        Args:
            res: Resolution to format
            max_items: Maximum contributions to include

        Returns:
            String like "audnex_genre:Fantasy=1.00, hardcover_mood:dark=0.30"
        """
        if not res.contributions:
            return "default"

        parts = []
        sorted_contribs = sorted(res.contributions, key=lambda x: x.delta, reverse=True)
        for c in sorted_contribs[:max_items]:
            parts.append(f"{c.source}:{c.term}={c.delta:.2f}")
        return ", ".join(parts)

    def _pick_best_category(self, scores: dict[str, float], contribs: list[Contribution]) -> str:
        """
        Pick best category with deterministic tie-breaking.

        Priority: highest score > Audnex-backed > Hardcover-backed > alphabetical
        """
        audnex_cats = {c.category for c in contribs if c.source == "audnex_genre"}
        hardcover_cats = {c.category for c in contribs if c.source.startswith("hardcover")}

        def sort_key(cat: str) -> tuple[float, int, int, str]:
            return (
                scores[cat],
                1 if cat in audnex_cats else 0,
                1 if cat in hardcover_cats else 0,
                cat,  # Alphabetical for final tie-break
            )

        return max(scores.keys(), key=sort_key)

    def _top_contributions(self, category: str, contribs: list[Contribution]) -> list[Contribution]:
        """Get contributions for the selected category, sorted by delta."""
        cs = [c for c in contribs if c.category == category]
        cs.sort(key=lambda x: x.delta, reverse=True)
        return cs

    def _match_categories(self, term: str) -> list[str]:
        """Find categories that match the given term."""
        t = self._norm(term)
        hits: list[str] = []

        # Check keyword-based matching from config
        for cat, keys in self.category_keywords.items():
            if t in keys or any(re.search(rf"\b{re.escape(k)}\b", t) for k in keys if len(k) >= 4):
                hits.append(cat)

        # Check mood hints if this looks like a mood
        if t in MOOD_CATEGORY_HINTS:
            hits.extend(MOOD_CATEGORY_HINTS[t])

        return list(set(hits))  # Dedupe

    @staticmethod
    def _norm(s: str) -> str:
        """Normalize a term for matching (lowercase, collapse whitespace)."""
        return " ".join(s.strip().lower().split())


# Singleton resolver instance (lazy-loaded)
_resolver: CategoryResolver | None = None


def get_category_resolver() -> CategoryResolver:
    """Get or create the singleton CategoryResolver instance."""
    global _resolver
    if _resolver is None:
        _resolver = CategoryResolver()
    return _resolver


def resolve_audiobook_category(
    audnex_data: dict[str, Any] | None = None,
    hardcover_genres: list[str] | None = None,
    hardcover_moods: list[str] | None = None,
    is_fiction: bool | None = None,
) -> Resolution:
    """
    Resolve MAM audiobook category using signal scoring.

    Convenience function that extracts genres from audnex_data and calls
    the CategoryResolver.

    Args:
        audnex_data: Audnex API response (genres extracted from 'genres' key)
        hardcover_genres: Genre names from Hardcover API
        hardcover_moods: Mood names from Hardcover API
        is_fiction: Override fiction/nonfiction. If None, inferred from audnex_data.

    Returns:
        Resolution with category, scores, and contributions
    """
    resolver = get_category_resolver()

    # Extract Audnex genres
    audnex_genres: list[str] = []
    if audnex_data:
        for g in audnex_data.get("genres", []):
            name = g.get("name", "")
            if name:
                audnex_genres.append(name)

    # Infer fiction/nonfiction if not provided
    if is_fiction is None:
        is_fiction = _infer_fiction_or_nonfiction(audnex_data) == 1 if audnex_data else True

    return resolver.resolve(
        audnex_genres=audnex_genres,
        hardcover_genres=hardcover_genres,
        hardcover_moods=hardcover_moods,
        is_fiction=is_fiction,
    )
