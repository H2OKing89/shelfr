"""Tests for ABS metadata.json builder."""

from __future__ import annotations

import json
from pathlib import Path

from mamfast.abs.metadata_builder import (
    build_abs_metadata_fallback,
    build_abs_metadata_from_audnex,
    write_abs_metadata_json,
)
from mamfast.schemas.abs_metadata import AbsMetadataJson


class TestBuildAbsMetadataFromAudnex:
    """Tests for building metadata from Audnex data."""

    def test_basic_book(self) -> None:
        """Test basic book without series."""
        audnex_data = {
            "asin": "B0CJWTXLPJ",
            "title": "Test Book",
            "subtitle": "A Subtitle",
            "authors": [{"name": "Author One"}],
            "narrators": [{"name": "Narrator One"}],
            "genres": [{"name": "Fantasy"}],
            "language": "english",
            "releaseDate": "2023-05-15T00:00:00.000Z",
            "publisherName": "Test Publisher",
            "summary": "<p>Book description.</p>",
        }

        result = build_abs_metadata_from_audnex(audnex_data)

        assert result.title == "Test Book"
        assert result.subtitle == "A Subtitle"
        assert result.authors == ["Author One"]
        assert result.narrators == ["Narrator One"]
        assert result.genres == ["Fantasy"]
        assert result.asin == "B0CJWTXLPJ"
        assert result.published_year == "2023"
        assert result.published_date == "2023-05-15"
        assert result.language == "English"
        assert result.publisher == "Test Publisher"
        assert result.description == "<p>Book description.</p>"
        assert result.explicit is False
        assert result.abridged is False

    def test_with_primary_series(self) -> None:
        """Test book with primary series."""
        audnex_data = {
            "asin": "B0TEST",
            "title": "Series Book",
            "authors": [{"name": "Author"}],
            "seriesPrimary": {"name": "Test Series", "position": "5"},
        }

        result = build_abs_metadata_from_audnex(audnex_data)

        assert result.series == ["Test Series #5"]

    def test_with_secondary_series(self) -> None:
        """Test book with both primary and secondary series."""
        audnex_data = {
            "asin": "B0TEST",
            "title": "Multi-Series Book",
            "authors": [{"name": "Author"}],
            "seriesPrimary": {"name": "Main Series", "position": "3"},
            "seriesSecondary": {"name": "Arc Series", "position": "1"},
        }

        result = build_abs_metadata_from_audnex(audnex_data)

        assert len(result.series) == 2
        assert "Main Series #3" in result.series
        assert "Arc Series #1" in result.series

    def test_series_without_position(self) -> None:
        """Test series without position number."""
        audnex_data = {
            "asin": "B0TEST",
            "title": "Standalone in Series",
            "authors": [],
            "seriesPrimary": {"name": "Test Series"},  # No position
        }

        result = build_abs_metadata_from_audnex(audnex_data)

        assert result.series == ["Test Series"]

    def test_with_chapters(self) -> None:
        """Test book with chapters from Audnex."""
        audnex_data = {
            "asin": "B0TEST",
            "title": "Chaptered Book",
            "authors": [],
        }
        audnex_chapters = {
            "asin": "B0TEST",
            "chapters": [
                {"title": "Chapter 1", "startOffsetSec": 0, "lengthMs": 60000},
                {"title": "Chapter 2", "startOffsetSec": 60, "lengthMs": 120000},
            ],
        }

        result = build_abs_metadata_from_audnex(audnex_data, audnex_chapters)

        assert len(result.chapters) == 2
        assert result.chapters[0].id == 0
        assert result.chapters[0].title == "Chapter 1"
        assert result.chapters[0].start == 0.0
        assert result.chapters[0].end == 60.0
        assert result.chapters[1].id == 1
        assert result.chapters[1].title == "Chapter 2"
        assert result.chapters[1].start == 60.0
        assert result.chapters[1].end == 180.0  # 60 + 120000ms = 60 + 120s

    def test_abridged_detection(self) -> None:
        """Test abridged format detection."""
        audnex_data = {
            "asin": "B0TEST",
            "title": "Abridged Book",
            "authors": [],
            "formatType": "abridged",
        }

        result = build_abs_metadata_from_audnex(audnex_data)

        assert result.abridged is True

    def test_unabridged_detection(self) -> None:
        """Test unabridged format detection."""
        audnex_data = {
            "asin": "B0TEST",
            "title": "Full Book",
            "authors": [],
            "formatType": "Unabridged",  # Test case insensitivity
        }

        result = build_abs_metadata_from_audnex(audnex_data)

        assert result.abridged is False

    def test_explicit_content(self) -> None:
        """Test explicit content flag."""
        audnex_data = {
            "asin": "B0TEST",
            "title": "Adult Book",
            "authors": [],
            "isAdult": True,
        }

        result = build_abs_metadata_from_audnex(audnex_data)

        assert result.explicit is True

    def test_multiple_authors_and_narrators(self) -> None:
        """Test book with multiple authors and narrators."""
        audnex_data = {
            "asin": "B0TEST",
            "title": "Collaboration",
            "authors": [
                {"name": "Author One"},
                {"name": "Author Two"},
                {"name": "Author Three"},
            ],
            "narrators": [
                {"name": "Narrator A"},
                {"name": "Narrator B"},
            ],
        }

        result = build_abs_metadata_from_audnex(audnex_data)

        assert result.authors == ["Author One", "Author Two", "Author Three"]
        assert result.narrators == ["Narrator A", "Narrator B"]

    def test_tags_populated_from_genres(self) -> None:
        """Test that tags are populated from genres."""
        audnex_data = {
            "asin": "B0TEST",
            "title": "Genre Test",
            "authors": [],
            "genres": [
                {"name": "Science Fiction"},
                {"name": "Fantasy"},
            ],
        }

        result = build_abs_metadata_from_audnex(audnex_data)

        assert result.genres == ["Science Fiction", "Fantasy"]
        assert result.tags == ["Science Fiction", "Fantasy"]

    def test_missing_fields_use_defaults(self) -> None:
        """Test that missing fields use sensible defaults."""
        audnex_data = {
            "asin": "B0MINIMAL",
            "title": "Minimal Book",
        }

        result = build_abs_metadata_from_audnex(audnex_data)

        assert result.title == "Minimal Book"
        assert result.asin == "B0MINIMAL"
        assert result.subtitle is None
        assert result.authors == []
        assert result.narrators == []
        assert result.series == []
        assert result.genres == []
        assert result.chapters == []
        assert result.explicit is False
        assert result.abridged is False

    def test_none_format_type(self) -> None:
        """Test handling of None formatType."""
        audnex_data = {
            "asin": "B0TEST",
            "title": "Book",
            "authors": [],
            "formatType": None,
        }

        result = build_abs_metadata_from_audnex(audnex_data)

        assert result.abridged is False


class TestBuildAbsMetadataFallback:
    """Tests for fallback metadata from parsed folder name."""

    def test_basic_fallback(self) -> None:
        """Test fallback with minimal data."""
        # Import here to avoid circular import issues in tests
        from mamfast.abs.importer import ParsedFolderName

        parsed = ParsedFolderName(
            author="Test Author",
            title="Test Title",
            series=None,
            series_position=None,
            asin=None,
            year="2023",
            narrator="Test Narrator",
            ripper_tag="H2OKing",
            is_standalone=True,
        )

        result = build_abs_metadata_fallback(parsed)

        assert result.title == "Test Title"
        assert result.authors == ["Test Author"]
        assert result.narrators == ["Test Narrator"]
        assert result.published_year == "2023"
        assert result.series == []
        assert result.asin is None

    def test_fallback_with_series(self) -> None:
        """Test fallback with series data."""
        from mamfast.abs.importer import ParsedFolderName

        parsed = ParsedFolderName(
            author="Author",
            title="Book 5",
            series="Epic Series",
            series_position="5",
            asin=None,
            year=None,
            narrator=None,
            ripper_tag=None,
            is_standalone=False,
        )

        result = build_abs_metadata_fallback(parsed)

        assert result.series == ["Epic Series #5"]

    def test_fallback_series_without_position(self) -> None:
        """Test fallback with series but no position."""
        from mamfast.abs.importer import ParsedFolderName

        parsed = ParsedFolderName(
            author="Author",
            title="Standalone",
            series="Loose Series",
            series_position=None,
            asin=None,
            year=None,
            narrator=None,
            ripper_tag=None,
            is_standalone=False,
        )

        result = build_abs_metadata_fallback(parsed)

        assert result.series == ["Loose Series"]

    def test_fallback_with_asin(self) -> None:
        """Test fallback preserves ASIN when available."""
        from mamfast.abs.importer import ParsedFolderName

        parsed = ParsedFolderName(
            author="Author",
            title="Book with ASIN",
            series=None,
            series_position=None,
            asin="B0TESTASIN",
            year="2024",
            narrator=None,
            ripper_tag=None,
            is_standalone=True,
        )

        result = build_abs_metadata_fallback(parsed)

        assert result.asin == "B0TESTASIN"

    def test_fallback_empty_narrator(self) -> None:
        """Test fallback with no narrator."""
        from mamfast.abs.importer import ParsedFolderName

        parsed = ParsedFolderName(
            author="Author",
            title="Book",
            series=None,
            series_position=None,
            asin=None,
            year=None,
            narrator=None,
            ripper_tag=None,
            is_standalone=True,
        )

        result = build_abs_metadata_fallback(parsed)

        assert result.narrators == []


class TestWriteAbsMetadataJson:
    """Tests for writing metadata.json file."""

    def test_write_success(self, tmp_path: Path) -> None:
        """Test successful write."""
        metadata = AbsMetadataJson(
            title="Test Book",
            authors=["Author"],
            asin="B0TEST123",
        )

        result = write_abs_metadata_json(tmp_path, metadata)

        assert result is not None
        assert result.exists()
        assert result.name == "metadata.json"

        # Verify content
        content = json.loads(result.read_text())
        assert content["title"] == "Test Book"
        assert content["asin"] == "B0TEST123"
        assert content["authors"] == ["Author"]

    def test_write_uses_camel_case(self, tmp_path: Path) -> None:
        """Test that output uses camelCase for ABS compatibility."""
        metadata = AbsMetadataJson(
            title="Test",
            authors=[],
            published_year="2023",
            published_date="2023-05-15",
        )

        result = write_abs_metadata_json(tmp_path, metadata)
        assert result is not None

        content = json.loads(result.read_text())
        assert "publishedYear" in content
        assert "publishedDate" in content
        assert "published_year" not in content
        assert "published_date" not in content

    def test_write_excludes_none(self, tmp_path: Path) -> None:
        """Test that None values are excluded from output."""
        metadata = AbsMetadataJson(
            title="Test",
            authors=[],
            subtitle=None,
            publisher=None,
        )

        result = write_abs_metadata_json(tmp_path, metadata)
        assert result is not None

        content = json.loads(result.read_text())
        assert "subtitle" not in content
        assert "publisher" not in content

    def test_dry_run_no_write(self, tmp_path: Path) -> None:
        """Test dry run does not write file."""
        metadata = AbsMetadataJson(title="Test", authors=[])

        result = write_abs_metadata_json(tmp_path, metadata, dry_run=True)

        assert result is None
        assert not (tmp_path / "metadata.json").exists()

    def test_write_with_chapters(self, tmp_path: Path) -> None:
        """Test writing metadata with chapters."""
        from mamfast.schemas.abs_metadata import AbsChapter

        metadata = AbsMetadataJson(
            title="Chaptered Book",
            authors=["Author"],
            chapters=[
                AbsChapter(id=0, start=0.0, end=60.0, title="Chapter 1"),
                AbsChapter(id=1, start=60.0, end=180.0, title="Chapter 2"),
            ],
        )

        result = write_abs_metadata_json(tmp_path, metadata)
        assert result is not None

        content = json.loads(result.read_text())
        assert len(content["chapters"]) == 2
        assert content["chapters"][0]["id"] == 0
        assert content["chapters"][0]["title"] == "Chapter 1"
        assert content["chapters"][0]["start"] == 0.0
        assert content["chapters"][0]["end"] == 60.0


class TestAbsMetadataJsonSchema:
    """Tests for the Pydantic schema validation."""

    def test_minimal_valid(self) -> None:
        """Test minimal valid metadata."""
        metadata = AbsMetadataJson(title="Test", authors=[])

        assert metadata.title == "Test"
        assert metadata.authors == []

    def test_full_metadata(self) -> None:
        """Test full metadata with all fields."""
        from mamfast.schemas.abs_metadata import AbsChapter

        metadata = AbsMetadataJson(
            title="Full Book",
            subtitle="Complete Edition",
            authors=["Author One", "Author Two"],
            narrators=["Narrator"],
            series=["Series #1"],
            genres=["Fantasy", "Adventure"],
            tags=["epic", "magic"],
            chapters=[AbsChapter(id=0, start=0, end=100, title="Intro")],
            published_year="2023",
            published_date="2023-05-15",
            publisher="Publisher",
            description="A great book",
            isbn="1234567890",
            asin="B0TEST",
            language="English",
            explicit=True,
            abridged=False,
        )

        assert metadata.title == "Full Book"
        assert metadata.subtitle == "Complete Edition"
        assert len(metadata.authors) == 2
        assert len(metadata.chapters) == 1
        assert metadata.explicit is True

    def test_model_dump_by_alias(self) -> None:
        """Test model_dump produces camelCase keys."""
        metadata = AbsMetadataJson(
            title="Test",
            authors=[],
            published_year="2023",
        )

        dumped = metadata.model_dump(by_alias=True, exclude_none=True)

        assert "publishedYear" in dumped
        assert dumped["publishedYear"] == "2023"
