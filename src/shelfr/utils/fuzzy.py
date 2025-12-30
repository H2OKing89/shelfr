"""Fuzzy string matching utilities using RapidFuzz.

Provides fuzzy matching for:
- Suspicious title change detection
- Duplicate release detection
- Author name matching
- Series name grouping
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)


# =============================================================================
# Core Similarity Functions
# =============================================================================


def similarity_ratio(a: str, b: str) -> float:
    """
    Get similarity ratio between two strings (0-100).

    Uses token_sort_ratio which handles word reordering well:
    - "Reki Kawahara" vs "Kawahara, Reki" -> high similarity
    - "Sword Art Online" vs "SAO" -> low similarity

    Args:
        a: First string
        b: Second string

    Returns:
        Similarity score from 0 (completely different) to 100 (identical)
    """
    if not a or not b:
        return 0.0
    return fuzz.token_sort_ratio(a.lower(), b.lower())


def partial_ratio(a: str, b: str) -> float:
    """
    Get partial similarity ratio (0-100).

    Good for finding substrings:
    - "Overlord" in "Overlord, Vol. 14" -> high score
    - "Re:Zero" in "Re:Zero kara..." -> high score

    Args:
        a: First string (typically shorter)
        b: Second string (typically longer)

    Returns:
        Partial similarity score from 0 to 100
    """
    if not a or not b:
        return 0.0
    return fuzz.partial_ratio(a.lower(), b.lower())


def weighted_ratio(a: str, b: str) -> float:
    """
    Get weighted similarity using multiple algorithms.

    Combines multiple fuzzy algorithms for best overall matching.
    Good for general-purpose similarity detection.

    Args:
        a: First string
        b: Second string

    Returns:
        Weighted similarity score from 0 to 100
    """
    if not a or not b:
        return 0.0
    return fuzz.WRatio(a.lower(), b.lower())


# =============================================================================
# Suspicious Change Detection
# =============================================================================


def is_suspicious_change(
    before: str,
    after: str,
    threshold: int = 50,
) -> bool:
    """
    Check if a title change is suspiciously large.

    Uses fuzzy ratio which handles:
    - Character transpositions
    - Partial removals
    - Japanese -> romaji changes

    Args:
        before: Original string
        after: Transformed string
        threshold: Minimum similarity required (default 50%)

    Returns:
        True if the change is suspicious (similarity below threshold)
    """
    if not before.strip():
        return False
    if not after.strip():
        return True  # Completely empty output is always suspicious

    ratio = similarity_ratio(before, after)
    is_suspicious = ratio < threshold

    if is_suspicious:
        logger.debug(
            f"Suspicious change detected: '{before}' -> '{after}' (similarity: {ratio:.1f}%)"
        )

    return is_suspicious


@dataclass
class ChangeAnalysis:
    """Analysis of a string transformation."""

    before: str
    after: str
    similarity: float
    is_suspicious: bool
    change_type: str  # "minor", "moderate", "major", "empty"


def analyze_change(
    before: str,
    after: str,
    threshold: int = 50,
) -> ChangeAnalysis:
    """
    Analyze a string transformation in detail.

    Args:
        before: Original string
        after: Transformed string
        threshold: Suspicion threshold

    Returns:
        ChangeAnalysis with detailed breakdown
    """
    if not after.strip():
        return ChangeAnalysis(
            before=before,
            after=after,
            similarity=0.0,
            is_suspicious=True,
            change_type="empty",
        )

    sim = similarity_ratio(before, after)

    if sim >= 90:
        change_type = "minor"
    elif sim >= 70:
        change_type = "moderate"
    else:
        change_type = "major"

    return ChangeAnalysis(
        before=before,
        after=after,
        similarity=sim,
        is_suspicious=sim < threshold,
        change_type=change_type,
    )


# =============================================================================
# Best Match Finding
# =============================================================================


def find_best_match(
    query: str,
    choices: list[str],
    threshold: int = 80,
) -> str | None:
    """
    Find best matching string from choices.

    Args:
        query: String to match
        choices: List of candidate strings
        threshold: Minimum score required (0-100)

    Returns:
        Best matching string, or None if no match above threshold
    """
    if not choices or not query:
        return None

    result = process.extractOne(
        query,
        choices,
        scorer=fuzz.WRatio,
        score_cutoff=threshold,
    )

    if result:
        return result[0]
    return None


def find_matches(
    query: str,
    choices: list[str],
    threshold: int = 70,
    limit: int = 5,
) -> list[tuple[str, float]]:
    """
    Find all matches above threshold.

    Args:
        query: String to match
        choices: List of candidate strings
        threshold: Minimum score required
        limit: Maximum number of results

    Returns:
        List of (match, score) tuples sorted by score descending
    """
    if not choices or not query:
        return []

    results = process.extract(
        query,
        choices,
        scorer=fuzz.WRatio,
        score_cutoff=threshold,
        limit=limit,
    )

    return [(match, score) for match, score, _ in results]


# =============================================================================
# Duplicate Detection
# =============================================================================


@dataclass
class DuplicatePair:
    """A pair of potential duplicates."""

    item1: str
    item2: str
    similarity: float
    index1: int = -1
    index2: int = -1


def find_duplicates(
    items: list[str],
    threshold: int = 85,
) -> list[DuplicatePair]:
    """
    Find near-duplicate strings in a list.

    Uses optimized pairwise comparison with early termination.

    Args:
        items: List of strings to check
        threshold: Minimum similarity to consider duplicate (0-100)

    Returns:
        List of DuplicatePair for items above threshold
    """
    duplicates: list[DuplicatePair] = []

    for i, item1 in enumerate(items):
        if not item1:
            continue

        for j, item2 in enumerate(items[i + 1 :], start=i + 1):
            if not item2:
                continue

            ratio = similarity_ratio(item1, item2)
            if ratio >= threshold:
                duplicates.append(
                    DuplicatePair(
                        item1=item1,
                        item2=item2,
                        similarity=ratio,
                        index1=i,
                        index2=j,
                    )
                )

    # Sort by similarity descending
    duplicates.sort(key=lambda d: d.similarity, reverse=True)
    return duplicates


def find_duplicates_in_groups(
    groups: dict[str, list[str]],
    threshold: int = 85,
) -> dict[str, list[DuplicatePair]]:
    """
    Find duplicates within named groups.

    Useful for checking duplicates within series, authors, etc.

    Args:
        groups: Dict mapping group name to list of items
        threshold: Minimum similarity threshold

    Returns:
        Dict mapping group name to list of duplicate pairs
    """
    results: dict[str, list[DuplicatePair]] = {}

    for group_name, items in groups.items():
        dups = find_duplicates(items, threshold)
        if dups:
            results[group_name] = dups

    return results


# =============================================================================
# Author/Name Matching
# =============================================================================


def match_name(
    name: str,
    known_names: dict[str, str],
    threshold: int = 85,
) -> str:
    """
    Match a name to known mappings using fuzzy matching.

    Handles variations like:
    - "Reki Kawahara" -> "Reki Kawahara"
    - "Kawahara, Reki" -> "Reki Kawahara"
    - "R. Kawahara" -> "Reki Kawahara" (if close enough)

    Args:
        name: Name to match
        known_names: Dict mapping variations to canonical names
        threshold: Minimum similarity required

    Returns:
        Canonical name if matched, otherwise original name
    """
    if not name:
        return name

    # Exact match first (fast path)
    if name in known_names:
        return known_names[name]

    # Fuzzy match against known variations
    match = find_best_match(name, list(known_names.keys()), threshold)
    if match:
        canonical = known_names[match]
        logger.debug(f"Fuzzy matched '{name}' -> '{match}' -> canonical '{canonical}'")
        return canonical

    return name


def normalize_author_name(name: str) -> str:
    """
    Normalize author name format.

    Handles common variations:
    - "Last, First" -> "First Last"
    - "LAST, FIRST" -> "First Last"
    - Extra whitespace cleanup

    Args:
        name: Author name in any format

    Returns:
        Normalized author name
    """
    if not name:
        return name

    name = name.strip()

    # Handle "Last, First" format
    if ", " in name:
        parts = name.split(", ", 1)
        if len(parts) == 2:
            name = f"{parts[1]} {parts[0]}"

    # Title case (handles ALL CAPS)
    # But preserve intentional caps like "J.K."
    words = name.split()
    normalized_words = []
    for word in words:
        if word.isupper() and len(word) > 2:
            word = word.title()
        normalized_words.append(word)

    return " ".join(normalized_words)


# =============================================================================
# Series Grouping
# =============================================================================


def normalize_series_name(
    series: str,
    known_series: list[str],
    threshold: int = 85,
) -> str:
    """
    Normalize series name to match existing series in library.

    Groups variations like:
    - "Re:Zero" / "Re: Zero" / "ReZero"
    - "Sword Art Online" / "S.A.O."

    Args:
        series: Series name to normalize
        known_series: List of existing series names
        threshold: Minimum similarity to use existing name

    Returns:
        Existing series name if matched, otherwise original
    """
    if not series or not known_series:
        return series

    # Exact match first
    if series in known_series:
        return series

    # Fuzzy match
    match = find_best_match(series, known_series, threshold)
    if match:
        logger.debug(f"Series normalized: '{series}' -> '{match}'")
        return match

    return series


def group_similar_series(
    series_list: list[str],
    threshold: int = 85,
) -> dict[str, list[str]]:
    """
    Group similar series names together.

    Args:
        series_list: List of all series names
        threshold: Similarity threshold for grouping

    Returns:
        Dict mapping canonical name to list of variations
    """
    groups: dict[str, list[str]] = {}
    assigned: set[str] = set()

    # Sort by length (longer names are usually more canonical)
    sorted_series = sorted(set(series_list), key=len, reverse=True)

    for series in sorted_series:
        if series in assigned:
            continue

        # Find all similar series not yet assigned
        variations = [series]
        for other in sorted_series:
            if other in assigned or other == series:
                continue

            if similarity_ratio(series, other) >= threshold:
                variations.append(other)
                assigned.add(other)

        assigned.add(series)
        groups[series] = variations

    return groups
