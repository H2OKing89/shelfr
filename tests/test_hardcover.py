"""
Tests for Hardcover metadata provider.

Phase 12: Tests for HardcoverAsyncClient, schemas, and HardcoverProvider.
"""

from __future__ import annotations

import pytest

from shelfr.metadata.hardcover.schemas import (
    HardcoverBook,
    HardcoverSearchResult,
)
from shelfr.metadata.providers.hardcover import (
    HARDCOVER_TO_MAM_FLAGS,
    HardcoverProvider,
)
from shelfr.metadata.providers.types import LookupContext

# =============================================================================
# Schema Tests
# =============================================================================


class TestHardcoverBook:
    """Tests for HardcoverBook schema."""

    def test_from_search_hit_basic(self):
        """Test creating HardcoverBook from basic search hit."""
        doc = {
            "id": 12345,
            "title": "Test Book",
            "author_names": ["Test Author"],
            "genres": ["Fantasy", "Adventure"],
            "moods": ["dark", "mysterious"],
            "tags": ["magic system"],
            "content_warnings": ["Violence", "Gore"],
            "rating": 4.5,
            "ratings_count": 100,
        }

        book = HardcoverBook.from_search_hit(doc)

        assert book.id == 12345
        assert book.title == "Test Book"
        assert book.author_names == ["Test Author"]
        assert book.genre_names == ["Fantasy", "Adventure"]
        assert book.mood_names == ["dark", "mysterious"]
        assert book.tag_names == ["magic system"]
        assert book.warning_names == ["Violence", "Gore"]
        assert book.rating == 4.5
        assert book.rating_count == 100

    def test_from_search_hit_empty_fields(self):
        """Test creating HardcoverBook with missing/empty fields."""
        doc = {
            "id": 12345,
            "title": "Minimal Book",
        }

        book = HardcoverBook.from_search_hit(doc)

        assert book.id == 12345
        assert book.title == "Minimal Book"
        assert book.author_names == []
        assert book.genre_names == []
        assert book.warning_names == []
        assert book.rating is None

    def test_from_search_hit_none_fields(self):
        """Test creating HardcoverBook with None values."""
        doc = {
            "id": 12345,
            "title": "Book with Nones",
            "author_names": None,
            "genres": None,
            "content_warnings": None,
        }

        book = HardcoverBook.from_search_hit(doc)

        assert book.author_names == []
        assert book.genre_names == []
        assert book.warning_names == []


class TestHardcoverSearchResult:
    """Tests for HardcoverSearchResult."""

    def test_is_confident_match_above_threshold(self):
        """Test confident match detection above threshold."""
        book = HardcoverBook(id=1, title="Test")
        result = HardcoverSearchResult(
            book=book,
            match_score=0.85,
            search_query="test query",
        )

        assert result.is_confident_match is True

    def test_is_confident_match_at_threshold(self):
        """Test confident match detection at threshold."""
        book = HardcoverBook(id=1, title="Test")
        result = HardcoverSearchResult(
            book=book,
            match_score=0.70,
            search_query="test query",
        )

        assert result.is_confident_match is True

    def test_is_confident_match_below_threshold(self):
        """Test confident match detection below threshold."""
        book = HardcoverBook(id=1, title="Test")
        result = HardcoverSearchResult(
            book=book,
            match_score=0.69,
            search_query="test query",
        )

        assert result.is_confident_match is False


# =============================================================================
# Content Flag Mapping Tests
# =============================================================================


class TestContentFlagMapping:
    """Tests for content warning to MAM flag mapping."""

    def test_violence_warnings_map_to_vio(self):
        """Test that violence-related warnings map to vio flag."""
        violence_warnings = ["Violence", "Gore", "murder", "war", "Torture", "Blood"]
        provider = HardcoverProvider()

        flags = provider._map_content_warnings(violence_warnings)

        assert "vio" in flags

    def test_language_warnings_map_to_clang(self):
        """Test that language warnings map to cLang flag."""
        language_warnings = ["Strong language", "Cursing"]
        provider = HardcoverProvider()

        flags = provider._map_content_warnings(language_warnings)

        assert "cLang" in flags

    def test_suggestive_sexual_maps_to_ssex(self):
        """Test that suggestive sexual content maps to sSex."""
        suggestive_warnings = ["Sexual content", "Spicy"]
        provider = HardcoverProvider()

        flags = provider._map_content_warnings(suggestive_warnings)

        assert "sSex" in flags
        assert "eSex" not in flags

    def test_explicit_sexual_maps_to_esex(self):
        """Test that explicit sexual content maps to eSex."""
        explicit_warnings = ["Rape", "Sexual assault", "Sexual violence"]
        provider = HardcoverProvider()

        flags = provider._map_content_warnings(explicit_warnings)

        assert "eSex" in flags

    def test_lgbt_warnings_map_to_lgbt(self):
        """Test that LGBTQ+ warnings map to lgbt flag."""
        lgbt_warnings = ["LGBTQ+", "LGBT", "queer"]
        provider = HardcoverProvider()

        flags = provider._map_content_warnings(lgbt_warnings)

        assert "lgbt" in flags

    def test_multiple_flags_from_mixed_warnings(self):
        """Test that mixed warnings produce multiple flags."""
        mixed_warnings = ["Violence", "Strong language", "Sexual content", "LGBT"]
        provider = HardcoverProvider()

        flags = provider._map_content_warnings(mixed_warnings)

        assert set(flags) == {"vio", "cLang", "sSex", "lgbt"}

    def test_case_insensitive_matching(self):
        """Test that warning matching is case-insensitive."""
        warnings = ["VIOLENCE", "strong LANGUAGE", "Sexual Content"]
        provider = HardcoverProvider()

        flags = provider._map_content_warnings(warnings)

        assert "vio" in flags
        assert "cLang" in flags
        assert "sSex" in flags

    def test_empty_warnings_returns_empty_list(self):
        """Test that empty warnings list returns empty flags."""
        provider = HardcoverProvider()

        flags = provider._map_content_warnings([])

        assert flags == []

    def test_unknown_warnings_handled_gracefully(self):
        """Test that unknown warnings don't cause errors."""
        unknown_warnings = ["Unknown Warning", "Another Unknown"]
        provider = HardcoverProvider()

        flags = provider._map_content_warnings(unknown_warnings)

        # Should return empty list, not error
        assert isinstance(flags, list)

    def test_substring_matching_for_violence(self):
        """Test substring matching for violence-related terms."""
        warnings = ["graphic violence", "bloody scenes", "death"]
        provider = HardcoverProvider()

        flags = provider._map_content_warnings(warnings)

        assert "vio" in flags

    def test_flags_are_sorted(self):
        """Test that returned flags are sorted alphabetically."""
        warnings = ["Violence", "LGBTQ+", "Strong language", "Sexual content"]
        provider = HardcoverProvider()

        flags = provider._map_content_warnings(warnings)

        assert flags == sorted(flags)

    def test_flags_are_deduplicated(self):
        """Test that duplicate mappings are deduplicated."""
        # Multiple warnings that all map to vio
        warnings = ["Violence", "Gore", "murder", "Blood"]
        provider = HardcoverProvider()

        flags = provider._map_content_warnings(warnings)

        assert flags.count("vio") == 1


# =============================================================================
# Provider Tests
# =============================================================================


class TestHardcoverProvider:
    """Tests for HardcoverProvider."""

    def test_provider_attributes(self):
        """Test provider has correct attributes."""
        provider = HardcoverProvider()

        assert provider.name == "hardcover"
        assert provider.priority == 60
        assert provider.kind == "network"
        assert provider.is_override is False

    def test_can_lookup_requires_asin(self):
        """Test that can_lookup requires ASIN."""
        provider = HardcoverProvider()
        ctx = LookupContext(ids={"asin": "B01H0IE2RQ"})

        assert provider.can_lookup(ctx, "asin") is True

    def test_can_lookup_rejects_no_asin(self):
        """Test that can_lookup rejects context without ASIN."""
        provider = HardcoverProvider()
        ctx = LookupContext(ids={})

        assert provider.can_lookup(ctx, "asin") is False

    def test_can_lookup_rejects_non_asin_id_type(self):
        """Test that can_lookup rejects non-ASIN id types."""
        provider = HardcoverProvider()
        ctx = LookupContext(ids={"asin": "B01H0IE2RQ"})

        assert provider.can_lookup(ctx, "isbn") is False

    def test_not_started_by_default(self):
        """Test that provider is not started by default."""
        provider = HardcoverProvider()

        assert provider.is_started is False

    def test_extract_title_author_from_abs_json(self):
        """Test extracting title and author from existing_abs_json."""
        provider = HardcoverProvider()
        ctx = LookupContext(
            ids={"asin": "B01H0IE2RQ"},
            existing_abs_json={
                "title": "It",
                "authors": [{"name": "Stephen King"}],
            },
        )

        title, author = provider._extract_title_author(ctx)

        assert title == "It"
        assert author == "Stephen King"

    def test_extract_title_author_from_string_authors(self):
        """Test extracting author when authors is list of strings."""
        provider = HardcoverProvider()
        ctx = LookupContext(
            ids={"asin": "B01H0IE2RQ"},
            existing_abs_json={
                "title": "Test Book",
                "authors": ["Author One", "Author Two"],
            },
        )

        title, author = provider._extract_title_author(ctx)

        assert title == "Test Book"
        assert author == "Author One"

    def test_extract_title_author_missing_data(self):
        """Test extracting title/author when data is missing."""
        provider = HardcoverProvider()
        ctx = LookupContext(ids={"asin": "B01H0IE2RQ"})

        title, author = provider._extract_title_author(ctx)

        assert title is None
        assert author == ""


# =============================================================================
# Mapping Configuration Tests
# =============================================================================


class TestMappingConfiguration:
    """Tests for the HARDCOVER_TO_MAM_FLAGS mapping."""

    def test_mapping_has_all_mam_flags(self):
        """Test that mapping covers all MAM flag types."""
        expected_flags = {"vio", "cLang", "sSex", "eSex", "lgbt"}
        actual_flags = set(HARDCOVER_TO_MAM_FLAGS.values())

        # All expected flags should be present as values
        assert expected_flags.issubset(actual_flags)

    def test_explicit_warnings_map_to_esex_not_ssex(self):
        """Test that explicit warnings ONLY map to eSex, not sSex."""
        explicit_mappings = ["Rape", "Sexual assault", "Sexual violence", "sexual harassment"]

        for warning in explicit_mappings:
            if warning in HARDCOVER_TO_MAM_FLAGS:
                assert (
                    HARDCOVER_TO_MAM_FLAGS[warning] == "eSex"
                ), f"'{warning}' should map to eSex, not {HARDCOVER_TO_MAM_FLAGS[warning]}"

    def test_suggestive_warnings_map_to_ssex(self):
        """Test that suggestive warnings map to sSex."""
        suggestive_mappings = ["Sexual content", "Spicy"]

        for warning in suggestive_mappings:
            if warning in HARDCOVER_TO_MAM_FLAGS:
                assert HARDCOVER_TO_MAM_FLAGS[warning] == "sSex", f"'{warning}' should map to sSex"


# =============================================================================
# Workflow Integration Tests
# =============================================================================


class TestWorkflowContentWarnings:
    """Tests for content warnings workflow integration."""

    def test_fetch_content_warnings_helper_exists(self):
        """Test that workflow helper function exists."""
        from shelfr.workflow import _fetch_content_warnings

        # Helper should be callable
        assert callable(_fetch_content_warnings)

    def test_fetch_hardcover_data_returns_empty_when_disabled(self, monkeypatch):
        """Test helper returns empty result when Hardcover is disabled."""
        from shelfr.workflow import _fetch_hardcover_data_async

        # Mock settings to disable Hardcover
        mock_settings = type(
            "Settings",
            (),
            {"hardcover": type("HardcoverConfig", (), {"enabled": False})()},
        )()

        import asyncio

        async def run_test():
            with pytest.MonkeyPatch.context() as m:
                m.setattr("shelfr.workflow.get_settings", lambda: mock_settings)
                result = await _fetch_hardcover_data_async("B123", "Test", "Author")
                return result

        result = asyncio.run(run_test())
        assert result.content_flags is None
        assert result.genres is None
        assert result.moods is None

    def test_release_content_flags_field(self):
        """Test AudiobookRelease has content_flags field."""
        from shelfr.models import AudiobookRelease

        release = AudiobookRelease()

        # Field should exist and default to None
        assert hasattr(release, "content_flags")
        assert release.content_flags is None

        # Should be settable
        release.content_flags = ["vio", "cLang"]
        assert release.content_flags == ["vio", "cLang"]

    def test_release_hardcover_genres_moods_fields(self):
        """Test AudiobookRelease has hardcover_genres and hardcover_moods fields."""
        from shelfr.models import AudiobookRelease

        release = AudiobookRelease()

        # Fields should exist and default to None
        assert hasattr(release, "hardcover_genres")
        assert hasattr(release, "hardcover_moods")
        assert release.hardcover_genres is None
        assert release.hardcover_moods is None

        # Should be settable
        release.hardcover_genres = ["Horror", "Thriller"]
        release.hardcover_moods = ["dark", "tense"]
        assert release.hardcover_genres == ["Horror", "Thriller"]
        assert release.hardcover_moods == ["dark", "tense"]

    def test_release_content_flags_settable(self):
        """Test that content_flags field is settable on AudiobookRelease."""
        from shelfr.models import AudiobookRelease

        release = AudiobookRelease(
            asin="B12345",
            title="Test Book",
            author="Test Author",
            content_flags=["vio", "eSex"],
        )

        # Check field is set correctly
        assert release.content_flags == ["vio", "eSex"]
