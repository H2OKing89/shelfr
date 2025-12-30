"""Utility modules for MAMFast."""

from shelfr.utils.fuzzy import (
    ChangeAnalysis,
    DuplicatePair,
    analyze_change,
    find_best_match,
    find_duplicates,
    find_duplicates_in_groups,
    find_matches,
    group_similar_series,
    is_suspicious_change,
    match_name,
    normalize_author_name,
    normalize_series_name,
    partial_ratio,
    similarity_ratio,
    weighted_ratio,
)
from shelfr.utils.paths import safe_dirname, safe_filename, safe_filepath

__all__ = [
    "safe_dirname",
    "safe_filename",
    "safe_filepath",
    # Fuzzy matching utilities
    "ChangeAnalysis",
    "DuplicatePair",
    "analyze_change",
    "find_best_match",
    "find_duplicates",
    "find_duplicates_in_groups",
    "find_matches",
    "group_similar_series",
    "is_suspicious_change",
    "match_name",
    "normalize_author_name",
    "normalize_series_name",
    "partial_ratio",
    "similarity_ratio",
    "weighted_ratio",
]
