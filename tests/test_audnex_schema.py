"""Tests for Audnex API schema validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mamfast.schemas.audnex import (
    AudnexAuthor,
    AudnexChapter,
    AudnexSeries,
    validate_audnex_book,
    validate_audnex_chapters,
)


class TestAudnexAuthor:
    """Tests for AudnexAuthor schema."""

    def test_valid_author_with_asin(self) -> None:
        """Test valid author with ASIN."""
        author = AudnexAuthor(asin="B000APZGGS", name="Reki Kawahara")
        assert author.asin == "B000APZGGS"
        assert author.name == "Reki Kawahara"

    def test_valid_author_without_asin(self) -> None:
        """Test valid author without ASIN (optional)."""
        author = AudnexAuthor(name="Unknown Author")
        assert author.asin is None
        assert author.name == "Unknown Author"

    def test_missing_name_rejected(self) -> None:
        """Test that missing name is rejected."""
        # Use model_validate with dict to avoid static type checker complaining
        with pytest.raises(ValidationError):
            AudnexAuthor.model_validate({"asin": "B000APZGGS"})


class TestAudnexSeries:
    """Tests for AudnexSeries schema."""

    def test_valid_series(self) -> None:
        """Test valid series with all fields."""
        series = AudnexSeries(asin="B08XXX", name="Sword Art Online", position="16")
        assert series.asin == "B08XXX"
        assert series.name == "Sword Art Online"
        assert series.position == "16"

    def test_series_without_position(self) -> None:
        """Test series without position (optional)."""
        series = AudnexSeries(name="Standalone Series")
        assert series.position is None

    def test_missing_name_rejected(self) -> None:
        """Test that missing name is rejected."""
        with pytest.raises(ValidationError):
            AudnexSeries.model_validate({"asin": "B08XXX", "position": "1"})


class TestAudnexBook:
    """Tests for AudnexBook schema."""

    def test_valid_book_minimal(self) -> None:
        """Test valid book with minimal fields."""
        book = validate_audnex_book(
            {
                "asin": "B0BHLHRMJH",
                "title": "Sword Art Online 7",
            }
        )
        assert book.asin == "B0BHLHRMJH"
        assert book.title == "Sword Art Online 7"
        assert book.subtitle is None
        assert book.authors == []

    def test_valid_book_full(self) -> None:
        """Test valid book with all common fields."""
        data = {
            "asin": "B0BHLHRMJH",
            "title": "Sword Art Online 7",
            "subtitle": "Mother's Rosary",
            "authors": [{"asin": "B000APZGGS", "name": "Reki Kawahara"}],
            "narrators": [{"name": "Bryce Papenbrook"}],
            "seriesPrimary": {"name": "Sword Art Online", "position": "7"},
            "genres": [{"name": "Science Fiction & Fantasy", "type": "genre"}],
            "releaseDate": "2023-06-15",
            "publisherName": "Yen Audio",
            "summary": "A great book...",
            "lengthMin": 420,
            "language": "english",
        }
        book = validate_audnex_book(data)
        assert book.asin == "B0BHLHRMJH"
        assert book.title == "Sword Art Online 7"
        assert book.subtitle == "Mother's Rosary"
        assert len(book.authors) == 1
        assert book.authors[0].name == "Reki Kawahara"
        assert book.series_primary is not None
        assert book.series_primary.name == "Sword Art Online"
        assert book.series_primary.position == "7"
        assert book.publisher_name == "Yen Audio"

    def test_missing_asin_rejected(self) -> None:
        """Test that missing ASIN is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            validate_audnex_book({"title": "Some Book"})
        assert "asin" in str(exc_info.value)

    def test_missing_title_rejected(self) -> None:
        """Test that missing title is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            validate_audnex_book({"asin": "B0BHLHRMJH"})
        assert "title" in str(exc_info.value)

    def test_extra_fields_ignored(self) -> None:
        """Test that extra fields are ignored (API may add new fields)."""
        book = validate_audnex_book(
            {
                "asin": "B0BHLHRMJH",
                "title": "Sword Art Online 7",
                "unknown_field": "should be ignored",
                "another_new_field": {"nested": "data"},
            }
        )
        assert book.asin == "B0BHLHRMJH"
        # Should not raise, extra fields ignored

    def test_swapped_title_subtitle(self) -> None:
        """Test a book where Audible swapped title/subtitle."""
        # This is the SAO vol 16 case from the test fixtures
        book = validate_audnex_book(
            {
                "asin": "B0DK9TS6D9",
                "title": "Alicization Exploding",
                "subtitle": "Sword Art Online 16",
                "seriesPrimary": {"name": "Sword Art Online", "position": "16"},
            }
        )
        # Schema should accept this - it's the raw API response
        # The normalization happens elsewhere
        assert book.title == "Alicization Exploding"
        assert book.subtitle == "Sword Art Online 16"


class TestAudnexChaptersResponse:
    """Tests for AudnexChaptersResponse schema."""

    def test_valid_chapters_response(self) -> None:
        """Test valid chapters response."""
        data = {
            "asin": "B0BHLHRMJH",
            "brandIntroDurationMs": 2000,
            "brandOutroDurationMs": 5000,
            "chapters": [
                {"lengthMs": 180000, "startOffsetMs": 0, "startOffsetSec": 0, "title": "Opening"},
                {
                    "lengthMs": 900000,
                    "startOffsetMs": 180000,
                    "startOffsetSec": 180,
                    "title": "Chapter 1",
                },
            ],
            "isAccurate": True,
            "runtimeLengthMs": 1080000,
            "runtimeLengthSec": 1080,
        }
        response = validate_audnex_chapters(data)
        assert response.asin == "B0BHLHRMJH"
        assert len(response.chapters) == 2
        assert response.chapters[0].title == "Opening"
        assert response.chapters[1].start_offset_sec == 180

    def test_chapters_response_minimal(self) -> None:
        """Test chapters response with minimal fields."""
        data = {
            "asin": "B0BHLHRMJH",
            "chapters": [],
        }
        response = validate_audnex_chapters(data)
        assert response.asin == "B0BHLHRMJH"
        assert response.chapters == []
        assert response.brand_intro_duration_ms == 0  # Default

    def test_missing_asin_rejected(self) -> None:
        """Test that missing ASIN is rejected."""
        with pytest.raises(ValidationError):
            validate_audnex_chapters({"chapters": []})


class TestAudnexChapter:
    """Tests for AudnexChapter schema."""

    def test_valid_chapter(self) -> None:
        """Test valid chapter via validation from API-style data."""
        chapter = AudnexChapter.model_validate(
            {
                "lengthMs": 180000,
                "startOffsetMs": 0,
                "startOffsetSec": 0,
                "title": "Opening Credits",
            }
        )
        assert chapter.length_ms == 180000
        assert chapter.title == "Opening Credits"

    def test_missing_fields_rejected(self) -> None:
        """Test that missing required fields are rejected."""
        with pytest.raises(ValidationError):
            AudnexChapter.model_validate(
                {"lengthMs": 180000, "startOffsetMs": 0}
            )  # Missing startOffsetSec, title


class TestRealWorldSamples:
    """Test with real-world API response patterns from fixtures."""

    def test_correct_mapping_sample(self) -> None:
        """Test a correctly mapped book (title has series+num)."""
        # SAO vol 7 - Title has series+num, subtitle has arc (CORRECT)
        book = validate_audnex_book(
            {
                "asin": "B0BHLHRMJH",
                "title": "Sword Art Online 7",
                "subtitle": "Mother's Rosary",
                "seriesPrimary": {"name": "Sword Art Online", "position": "7"},
            }
        )
        assert book.title == "Sword Art Online 7"
        assert book.subtitle == "Mother's Rosary"

    def test_swapped_mapping_sample(self) -> None:
        """Test a swapped book (title has arc, subtitle has series+num)."""
        # SAO vol 16 - SWAPPED
        book = validate_audnex_book(
            {
                "asin": "B0DK9TS6D9",
                "title": "Alicization Exploding",
                "subtitle": "Sword Art Online 16",
                "seriesPrimary": {"name": "Sword Art Online", "position": "16"},
            }
        )
        # Schema accepts raw API response
        assert book.title == "Alicization Exploding"
        assert book.subtitle == "Sword Art Online 16"

    def test_standalone_book_sample(self) -> None:
        """Test a standalone book (no series)."""
        book = validate_audnex_book(
            {
                "asin": "B0F56G77WS",
                "title": "Reincarnated in a Fantasy World with Murderous Intent",
                "authors": [{"name": "Neil Hartley"}],
            }
        )
        assert book.series_primary is None
        assert book.title == "Reincarnated in a Fantasy World with Murderous Intent"
