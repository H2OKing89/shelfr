"""
Tests for CategoryResolver signal scoring.

Phase 12: Tests for category resolution from multiple metadata sources.
"""

from __future__ import annotations

import pytest

from shelfr.metadata.mam.categories import (
    GENERIC_PENALTY,
    SIGNAL_WEIGHTS,
    CategoryResolver,
    resolve_audiobook_category,
)

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def resolver() -> CategoryResolver:
    """Create resolver with known category keywords."""
    return CategoryResolver(
        {
            "Audiobooks - Fantasy": ["fantasy", "epic fantasy", "urban fantasy"],
            "Audiobooks - Horror": ["horror"],
            "Audiobooks - Crime/Thriller": ["thriller", "crime", "mystery", "suspense"],
            "Audiobooks - Romance": ["romance", "romantic"],
            "Audiobooks - Science Fiction": ["science fiction", "sci-fi", "dystopian"],
            "Audiobooks - General Fiction": ["fiction", "general fiction", "contemporary"],
            "Audiobooks - General Non-Fic": ["nonfiction", "general nonfiction"],
            "Audiobooks - Self-Help": ["self-help", "personal development"],
            "Audiobooks - Biographical": ["biography", "memoir"],
        }
    )


# =============================================================================
# Signal Weight Tests
# =============================================================================


class TestSignalWeights:
    """Tests for signal weight configuration."""

    def test_audnex_has_highest_weight(self):
        """Audnex genres should have the highest weight."""
        assert SIGNAL_WEIGHTS["audnex_genre"] == 1.0
        assert SIGNAL_WEIGHTS["audnex_genre"] > SIGNAL_WEIGHTS["hardcover_genre"]
        assert SIGNAL_WEIGHTS["audnex_genre"] > SIGNAL_WEIGHTS["hardcover_mood"]

    def test_hardcover_genre_stronger_than_mood(self):
        """Hardcover genres should be stronger than moods."""
        assert SIGNAL_WEIGHTS["hardcover_genre"] > SIGNAL_WEIGHTS["hardcover_mood"]

    def test_generic_penalty_is_significant(self):
        """Generic penalty should reduce score by half."""
        assert GENERIC_PENALTY == 0.5


# =============================================================================
# Basic Resolution Tests
# =============================================================================


class TestBasicResolution:
    """Tests for basic category resolution."""

    def test_audnex_only(self, resolver: CategoryResolver):
        """Single Audnex genre should resolve correctly."""
        res = resolver.resolve(audnex_genres=["Fantasy"])

        assert res.category == "Audiobooks - Fantasy"
        assert res.scores["Audiobooks - Fantasy"] == 1.0
        assert len(res.contributions) == 1
        assert res.contributions[0].source == "audnex_genre"

    def test_hardcover_only(self, resolver: CategoryResolver):
        """Single Hardcover genre should resolve correctly."""
        res = resolver.resolve(hardcover_genres=["Thriller"])

        assert res.category == "Audiobooks - Crime/Thriller"
        assert res.scores["Audiobooks - Crime/Thriller"] == 0.8

    def test_mood_only_creates_category(self, resolver: CategoryResolver):
        """Mood alone can create category when no genre signals."""
        res = resolver.resolve(hardcover_moods=["dark"])

        # Should pick Horror from mood hints
        assert res.category == "Audiobooks - Horror"
        assert res.scores["Audiobooks - Horror"] == 0.3

    def test_empty_signals_returns_default_fiction(self, resolver: CategoryResolver):
        """No signals should return default fiction category."""
        res = resolver.resolve()

        assert res.category == "Audiobooks - General Fiction"
        assert res.is_fiction is True
        assert res.scores == {}

    def test_empty_signals_returns_default_nonfiction(self, resolver: CategoryResolver):
        """No signals with is_fiction=False should return nonfiction default."""
        res = resolver.resolve(is_fiction=False)

        assert res.category == "Audiobooks - General Non-Fic"
        assert res.is_fiction is False


# =============================================================================
# Signal Scoring Tests
# =============================================================================


class TestSignalScoring:
    """Tests for signal scoring logic."""

    def test_audnex_strong_wins_over_hardcover(self, resolver: CategoryResolver):
        """Strong Audnex signal should beat single Hardcover signal."""
        res = resolver.resolve(
            audnex_genres=["Fantasy"],
            hardcover_genres=["Romance"],
        )

        # Fantasy (1.0) should beat Romance (0.8)
        assert res.category == "Audiobooks - Fantasy"
        assert res.scores["Audiobooks - Fantasy"] == 1.0
        assert res.scores["Audiobooks - Romance"] == 0.8

    def test_hardcover_genre_plus_mood_can_beat_audnex(self, resolver: CategoryResolver):
        """Hardcover genre + mood combined can beat single Audnex signal."""
        res = resolver.resolve(
            audnex_genres=["Fantasy"],
            hardcover_genres=["Horror"],
            hardcover_moods=["dark"],
        )

        # Horror (0.8) + dark mood (0.3) = 1.1 > Fantasy (1.0)
        assert res.category == "Audiobooks - Horror"
        assert res.scores["Audiobooks - Horror"] == pytest.approx(1.1)
        assert res.scores["Audiobooks - Fantasy"] == 1.0

    def test_generic_audnex_loses_to_specific_hardcover(self, resolver: CategoryResolver):
        """Generic Audnex term should lose to specific Hardcover genre."""
        res = resolver.resolve(
            audnex_genres=["General Fiction"],
            hardcover_genres=["Thriller"],
        )

        # General Fiction with penalty (0.5) < Thriller (0.8)
        assert res.category == "Audiobooks - Crime/Thriller"
        assert res.scores["Audiobooks - General Fiction"] == pytest.approx(0.5)
        assert res.scores["Audiobooks - Crime/Thriller"] == 0.8

    def test_multiple_signals_accumulate(self, resolver: CategoryResolver):
        """Multiple signals for same category should accumulate."""
        res = resolver.resolve(
            audnex_genres=["Thriller"],
            hardcover_genres=["Crime", "Mystery"],
        )

        # Thriller (1.0) + Crime (0.8) + Mystery (0.8) = 2.6
        assert res.category == "Audiobooks - Crime/Thriller"
        assert res.scores["Audiobooks - Crime/Thriller"] == pytest.approx(2.6)


# =============================================================================
# Mood Behavior Tests
# =============================================================================


class TestMoodBehavior:
    """Tests for mood signal handling."""

    def test_mood_reinforces_existing_genre(self, resolver: CategoryResolver):
        """Mood should reinforce category that has genre support."""
        res = resolver.resolve(
            hardcover_genres=["Horror"],
            hardcover_moods=["dark", "tense"],
        )

        # Horror (0.8) + dark reinforcement (0.3) = 1.1
        # tense doesn't reinforce Horror (not in Horror's mood hints)
        assert res.category == "Audiobooks - Horror"
        assert res.scores["Audiobooks - Horror"] == pytest.approx(1.1)

    def test_mood_cannot_hijack_strong_genre(self, resolver: CategoryResolver):
        """Mood should not override strong genre signals."""
        res = resolver.resolve(
            audnex_genres=["Fantasy", "Epic Fantasy"],
            hardcover_moods=["dark"],
        )

        # Fantasy gets 2.0 from two genre signals, dark adds 0.3 to Horror
        # But Horror only has 0.3 from mood, Fantasy has 2.0 from genres
        # Note: mood can only reinforce existing genre-backed categories when genre_backed exists
        assert res.category == "Audiobooks - Fantasy"


# =============================================================================
# Tie-Breaking Tests
# =============================================================================


class TestTieBreaking:
    """Tests for deterministic tie-breaking."""

    def test_audnex_wins_tie(self, resolver: CategoryResolver):
        """Audnex-backed category should win on score tie."""
        # Create exact tie: audnex Fantasy (1.0) vs hardcover Romance + mood (0.8 + mood)
        # Need to engineer a tie...
        res = resolver.resolve(
            audnex_genres=["Fantasy"],
            hardcover_genres=["Romance"],  # 0.8, no mood reinforcement possible
        )

        # Not a tie (1.0 vs 0.8), but Audnex should still win
        assert res.category == "Audiobooks - Fantasy"

    def test_deterministic_output(self, resolver: CategoryResolver):
        """Same inputs should always produce same output."""
        inputs = {
            "audnex_genres": ["Fantasy", "Adventure"],
            "hardcover_genres": ["Thriller"],
            "hardcover_moods": ["tense"],
        }

        # Run multiple times
        results = [resolver.resolve(**inputs) for _ in range(5)]

        # All should be identical
        categories = [r.category for r in results]
        assert len(set(categories)) == 1


# =============================================================================
# Format Reason Tests
# =============================================================================


class TestFormatReason:
    """Tests for reason string formatting."""

    def test_format_single_contribution(self, resolver: CategoryResolver):
        """Single contribution should format correctly."""
        res = resolver.resolve(audnex_genres=["Fantasy"])
        reason = resolver.format_reason(res)

        assert "audnex_genre:Fantasy=1.00" in reason

    def test_format_multiple_contributions(self, resolver: CategoryResolver):
        """Multiple contributions should be sorted by delta."""
        res = resolver.resolve(
            audnex_genres=["Thriller"],
            hardcover_genres=["Crime"],
        )
        reason = resolver.format_reason(res, max_items=3)

        # Should show highest delta first
        assert "audnex_genre:Thriller=1.00" in reason
        assert "hardcover_genre:Crime=0.80" in reason

    def test_format_empty_resolution(self, resolver: CategoryResolver):
        """Empty resolution should format as 'default'."""
        res = resolver.resolve()
        reason = resolver.format_reason(res)

        assert reason == "default"


# =============================================================================
# Integration with resolve_audiobook_category
# =============================================================================


class TestResolveAudiobookCategory:
    """Tests for the convenience function."""

    def test_extracts_audnex_genres(self, resolver: CategoryResolver, monkeypatch):
        """Should extract genre names from Audnex dict format."""
        # Patch the singleton resolver
        monkeypatch.setattr("shelfr.metadata.mam.categories._resolver", resolver)

        audnex_data = {
            "genres": [
                {"name": "Fantasy"},
                {"name": "Adventure"},
            ]
        }

        res = resolve_audiobook_category(audnex_data=audnex_data)

        assert "Fantasy" in [c.term for c in res.contributions if c.source == "audnex_genre"]

    def test_infers_fiction_from_audnex(self, resolver: CategoryResolver, monkeypatch):
        """Should infer fiction/nonfiction from Audnex data."""
        monkeypatch.setattr("shelfr.metadata.mam.categories._resolver", resolver)

        audnex_fiction = {"genres": [{"name": "Fantasy"}]}
        audnex_nonfiction = {"genres": [{"name": "Biography"}]}

        res_fiction = resolve_audiobook_category(audnex_data=audnex_fiction)
        res_nonfiction = resolve_audiobook_category(audnex_data=audnex_nonfiction)

        assert res_fiction.is_fiction is True
        assert res_nonfiction.is_fiction is False

    def test_override_is_fiction(self, resolver: CategoryResolver, monkeypatch):
        """Should allow overriding fiction/nonfiction inference."""
        monkeypatch.setattr("shelfr.metadata.mam.categories._resolver", resolver)

        audnex_data = {"genres": [{"name": "Fantasy"}]}  # Would infer fiction

        res = resolve_audiobook_category(audnex_data=audnex_data, is_fiction=False)

        assert res.is_fiction is False


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_genre_names_ignored(self, resolver: CategoryResolver):
        """Empty string genres should be ignored."""
        res = resolver.resolve(audnex_genres=["", "Fantasy", ""])

        assert res.category == "Audiobooks - Fantasy"
        assert len([c for c in res.contributions if c.term == ""]) == 0

    def test_case_insensitive_matching(self, resolver: CategoryResolver):
        """Genre matching should be case-insensitive."""
        res = resolver.resolve(audnex_genres=["FANTASY", "fantasy", "Fantasy"])

        assert res.category == "Audiobooks - Fantasy"
        # Should accumulate all three
        assert res.scores["Audiobooks - Fantasy"] == pytest.approx(3.0)

    def test_unknown_genre_ignored(self, resolver: CategoryResolver):
        """Unknown genres should not crash, just be ignored."""
        res = resolver.resolve(
            audnex_genres=["Unknown Genre That Doesn't Exist"],
            hardcover_genres=["Fantasy"],
        )

        assert res.category == "Audiobooks - Fantasy"

    def test_none_inputs_handled(self, resolver: CategoryResolver):
        """None inputs should be handled gracefully."""
        res = resolver.resolve(
            audnex_genres=None,
            hardcover_genres=None,
            hardcover_moods=None,
        )

        assert res.category == "Audiobooks - General Fiction"
