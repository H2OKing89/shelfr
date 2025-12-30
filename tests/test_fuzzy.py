"""Tests for fuzzy string matching utilities."""

from __future__ import annotations

from shelfr.utils.fuzzy import (
    ChangeAnalysis,
    analyze_change,
    find_best_match,
    find_duplicates,
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

# =============================================================================
# Core Similarity Functions Tests
# =============================================================================


class TestSimilarityRatio:
    """Test similarity_ratio function."""

    def test_identical_strings(self):
        """Identical strings should return 100."""
        assert similarity_ratio("hello", "hello") == 100.0

    def test_completely_different(self):
        """Completely different strings should return low score."""
        assert similarity_ratio("abc", "xyz") < 50

    def test_case_insensitive(self):
        """Comparison should be case insensitive."""
        assert similarity_ratio("Hello", "HELLO") == 100.0

    def test_word_reordering(self):
        """Word reordering should still score high."""
        score = similarity_ratio("Reki Kawahara", "Kawahara Reki")
        assert score >= 90

    def test_empty_strings(self):
        """Empty strings should return 0."""
        assert similarity_ratio("", "test") == 0.0
        assert similarity_ratio("test", "") == 0.0
        assert similarity_ratio("", "") == 0.0

    def test_partial_match(self):
        """Partial matches should score moderately."""
        score = similarity_ratio("Overlord", "Overlord Vol 14")
        assert 50 < score < 100


class TestPartialRatio:
    """Test partial_ratio function."""

    def test_substring_match(self):
        """Substring should score high with partial ratio."""
        score = partial_ratio("Overlord", "Overlord, Vol. 14")
        assert score >= 90

    def test_prefix_match(self):
        """Prefix should score high."""
        score = partial_ratio("Re:Zero", "Re:Zero kara Hajimeru Isekai Seikatsu")
        assert score >= 90

    def test_empty_strings(self):
        """Empty strings should return 0."""
        assert partial_ratio("", "test") == 0.0


class TestWeightedRatio:
    """Test weighted_ratio function."""

    def test_identical(self):
        """Identical strings should score 100."""
        assert weighted_ratio("test", "test") == 100.0

    def test_similar_strings(self):
        """Similar strings should score high."""
        score = weighted_ratio("Sword Art Online", "Sword Art Online Vol 1")
        assert score >= 80

    def test_empty_strings(self):
        """Empty strings should return 0."""
        assert weighted_ratio("", "test") == 0.0


# =============================================================================
# Suspicious Change Detection Tests
# =============================================================================


class TestIsSuspiciousChange:
    """Test is_suspicious_change function."""

    def test_minor_change_not_suspicious(self):
        """Minor changes should not be flagged."""
        assert not is_suspicious_change(
            "Overlord (Light Novel)",
            "Overlord",
            threshold=50,
        )

    def test_major_change_is_suspicious(self):
        """Major changes should be flagged."""
        assert is_suspicious_change(
            "転生したらスライムだった件",
            "Slime",
            threshold=50,
        )

    def test_empty_result_is_suspicious(self):
        """Empty result should always be suspicious."""
        assert is_suspicious_change("Some Title", "")
        assert is_suspicious_change("Some Title", "   ")

    def test_empty_input_not_suspicious(self):
        """Empty input should not be suspicious."""
        assert not is_suspicious_change("", "Some Result")
        assert not is_suspicious_change("   ", "Some Result")

    def test_threshold_boundary(self):
        """Test threshold boundary conditions."""
        # "test" vs "test123" should be similar enough
        assert not is_suspicious_change("test", "test123", threshold=60)


class TestAnalyzeChange:
    """Test analyze_change function."""

    def test_minor_change(self):
        """Minor changes should be categorized correctly."""
        result = analyze_change("Overlord Vol 14", "Overlord Vol. 14")
        assert isinstance(result, ChangeAnalysis)
        assert result.change_type == "minor"
        assert not result.is_suspicious

    def test_major_change(self):
        """Major changes should be categorized correctly."""
        result = analyze_change("完全な日本語タイトル", "English Title")
        assert result.change_type == "major"

    def test_empty_result(self):
        """Empty result should be flagged."""
        result = analyze_change("Some Title", "")
        assert result.change_type == "empty"
        assert result.is_suspicious


# =============================================================================
# Best Match Finding Tests
# =============================================================================


class TestFindBestMatch:
    """Test find_best_match function."""

    def test_exact_match(self):
        """Exact match should be found."""
        choices = ["Apple", "Banana", "Cherry"]
        assert find_best_match("Apple", choices) == "Apple"

    def test_fuzzy_match(self):
        """Fuzzy match should work."""
        choices = ["Sword Art Online", "Re:Zero", "Overlord"]
        result = find_best_match("Sword Art Onlin", choices, threshold=80)
        assert result == "Sword Art Online"

    def test_no_match_below_threshold(self):
        """Should return None if no match above threshold."""
        choices = ["Apple", "Banana"]
        assert find_best_match("Zebra", choices, threshold=80) is None

    def test_empty_choices(self):
        """Empty choices should return None."""
        assert find_best_match("test", []) is None

    def test_empty_query(self):
        """Empty query should return None."""
        assert find_best_match("", ["test"]) is None


class TestFindMatches:
    """Test find_matches function."""

    def test_returns_multiple_matches(self):
        """Should return multiple matches sorted by score."""
        choices = ["Overlord 1", "Overlord 2", "Overlord 3", "Something Else"]
        results = find_matches("Overlord", choices, threshold=70)
        assert len(results) >= 3
        # Should be sorted by score descending
        scores = [score for _, score in results]
        assert scores == sorted(scores, reverse=True)

    def test_limit_parameter(self):
        """Limit parameter should restrict results."""
        choices = ["A1", "A2", "A3", "A4", "A5"]
        results = find_matches("A", choices, threshold=50, limit=2)
        assert len(results) <= 2


# =============================================================================
# Duplicate Detection Tests
# =============================================================================


class TestFindDuplicates:
    """Test find_duplicates function."""

    def test_finds_exact_duplicates(self):
        """Should find exact duplicates."""
        items = ["Overlord", "Re:Zero", "Overlord"]
        dups = find_duplicates(items, threshold=100)
        assert len(dups) == 1
        assert dups[0].item1 == "Overlord"
        assert dups[0].item2 == "Overlord"

    def test_finds_near_duplicates(self):
        """Should find near duplicates."""
        items = ["Overlord Vol 14", "Overlord, Vol. 14", "Re:Zero"]
        dups = find_duplicates(items, threshold=85)
        assert len(dups) == 1
        assert dups[0].similarity >= 85

    def test_no_duplicates(self):
        """Should return empty for no duplicates."""
        items = ["Apple", "Banana", "Cherry"]
        dups = find_duplicates(items, threshold=90)
        assert len(dups) == 0

    def test_returns_indices(self):
        """Should include indices in results."""
        items = ["A", "B", "A"]
        dups = find_duplicates(items, threshold=100)
        assert dups[0].index1 == 0
        assert dups[0].index2 == 2

    def test_sorted_by_similarity(self):
        """Results should be sorted by similarity descending."""
        items = ["Test1", "Test2", "Test1", "Completely Different"]
        dups = find_duplicates(items, threshold=70)
        if len(dups) > 1:
            assert dups[0].similarity >= dups[-1].similarity

    def test_skips_empty_strings(self):
        """Should skip empty strings."""
        items = ["Test", "", "Test"]
        dups = find_duplicates(items, threshold=100)
        assert len(dups) == 1


# =============================================================================
# Author/Name Matching Tests
# =============================================================================


class TestMatchName:
    """Test match_name function."""

    def test_exact_match(self):
        """Exact match should use mapping."""
        known = {"Reki Kawahara": "Reki Kawahara"}
        assert match_name("Reki Kawahara", known) == "Reki Kawahara"

    def test_fuzzy_match(self):
        """Fuzzy match should find close names."""
        known = {"Reki Kawahara": "Reki Kawahara", "Hajime Isayama": "Hajime Isayama"}
        result = match_name("Kawahara, Reki", known, threshold=80)
        # Should fuzzy match to Reki Kawahara
        assert "Kawahara" in result

    def test_no_match_returns_original(self):
        """No match should return original."""
        known = {"John Smith": "John Smith"}
        assert match_name("Completely Different", known) == "Completely Different"

    def test_empty_name(self):
        """Empty name should return empty."""
        assert match_name("", {"test": "test"}) == ""


class TestNormalizeAuthorName:
    """Test normalize_author_name function."""

    def test_last_first_format(self):
        """Should convert 'Last, First' to 'First Last'."""
        assert normalize_author_name("Kawahara, Reki") == "Reki Kawahara"

    def test_all_caps(self):
        """Should handle ALL CAPS names."""
        result = normalize_author_name("JOHN SMITH")
        assert result == "John Smith"

    def test_preserves_initials(self):
        """Should preserve short uppercase like initials."""
        result = normalize_author_name("J.K. Rowling")
        assert "J.K." in result

    def test_strips_whitespace(self):
        """Should strip extra whitespace."""
        assert normalize_author_name("  John Smith  ") == "John Smith"

    def test_empty_string(self):
        """Should handle empty string."""
        assert normalize_author_name("") == ""


# =============================================================================
# Series Grouping Tests
# =============================================================================


class TestNormalizeSeriesName:
    """Test normalize_series_name function."""

    def test_exact_match(self):
        """Exact match should return as-is."""
        known = ["Overlord", "Re:Zero"]
        assert normalize_series_name("Overlord", known) == "Overlord"

    def test_fuzzy_match(self):
        """Fuzzy match should find similar series."""
        known = ["Re:Zero", "Overlord"]
        result = normalize_series_name("Re: Zero", known, threshold=85)
        assert result == "Re:Zero"

    def test_no_match(self):
        """No match should return original."""
        known = ["Overlord"]
        assert normalize_series_name("Something Else", known) == "Something Else"

    def test_empty_series(self):
        """Empty series should return empty."""
        assert normalize_series_name("", ["test"]) == ""

    def test_empty_known_list(self):
        """Empty known list should return original."""
        assert normalize_series_name("Test", []) == "Test"


class TestGroupSimilarSeries:
    """Test group_similar_series function."""

    def test_groups_variations(self):
        """Should group similar series names."""
        series = ["Re:Zero", "Re: Zero", "ReZero", "Overlord"]
        groups = group_similar_series(series, threshold=80)

        # Should have fewer groups than input
        assert len(groups) < len(series)

        # Overlord should be separate
        overlord_found = any("Overlord" in variations for variations in groups.values())
        assert overlord_found

    def test_no_grouping_for_different(self):
        """Different series should not be grouped."""
        series = ["Apple", "Banana", "Cherry"]
        groups = group_similar_series(series, threshold=90)
        assert len(groups) == 3

    def test_empty_list(self):
        """Empty list should return empty groups."""
        groups = group_similar_series([])
        assert groups == {}

    def test_longer_names_preferred(self):
        """Longer names should be preferred as canonical."""
        series = ["SAO", "Sword Art Online"]
        groups = group_similar_series(series, threshold=50)
        # The longer name should be the key
        assert "Sword Art Online" in groups or len(groups) == 2


# =============================================================================
# Edge Cases and Integration
# =============================================================================


class TestEdgeCases:
    """Test edge cases across all functions."""

    def test_unicode_handling(self):
        """Should handle Unicode characters."""
        score = similarity_ratio("日本語", "日本語")
        assert score == 100.0

    def test_special_characters(self):
        """Should handle special characters."""
        score = similarity_ratio("Re:Zero", "Re:Zero")
        assert score == 100.0

    def test_numbers_in_strings(self):
        """Should handle numbers correctly."""
        score = similarity_ratio("Vol 14", "Vol 15")
        assert score > 70  # Similar but not identical

    def test_very_long_strings(self):
        """Should handle very long strings."""
        long1 = "A" * 1000
        long2 = "A" * 999 + "B"
        score = similarity_ratio(long1, long2)
        assert score > 90  # Should be very similar
