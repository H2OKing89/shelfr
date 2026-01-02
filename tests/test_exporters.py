"""Tests for metadata exporters."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from shelfr.exceptions import ExportError
from shelfr.metadata.aggregator import AggregatedResult
from shelfr.metadata.exporters import (
    JsonExporter,
    OpfExporter,
    get_exporter,
    list_exporters,
    register_exporter,
)
from shelfr.metadata.exporters.base import MetadataExporter


class TestExporterRegistry:
    """Tests for exporter registry functions."""

    def test_get_exporter_json(self) -> None:
        """Test getting JSON exporter."""
        exporter = get_exporter("json")
        assert isinstance(exporter, JsonExporter)
        assert exporter.name == "json"

    def test_get_exporter_unknown(self) -> None:
        """Test getting unknown exporter raises error."""
        with pytest.raises(ValueError, match="Unknown export format"):
            get_exporter("nonexistent")

    def test_list_exporters(self) -> None:
        """Test listing available exporters."""
        exporters = list_exporters()
        assert "json" in exporters
        assert isinstance(exporters, list)
        assert exporters == sorted(exporters)  # Should be sorted

    def test_register_custom_exporter(self) -> None:
        """Test registering a custom exporter."""

        class CustomExporter:
            name = "custom"
            file_extension = ".custom"
            description = "Custom format"

            async def export(self, result: AggregatedResult, output_dir: Path) -> Path:
                return output_dir / "custom.txt"

        register_exporter("custom_test", CustomExporter)
        assert "custom_test" in list_exporters()

        exporter = get_exporter("custom_test")
        assert exporter.name == "custom"


class TestJsonExporter:
    """Tests for JsonExporter."""

    @pytest.fixture
    def exporter(self) -> JsonExporter:
        """Create a JsonExporter instance."""
        return JsonExporter()

    @pytest.mark.asyncio
    async def test_export_basic(self, exporter: JsonExporter, tmp_path: Path) -> None:
        """Test basic export functionality."""
        result = AggregatedResult(
            fields={
                "title": "Test Book",
                "subtitle": "A Subtitle",
            }
        )

        output_file = await exporter.export(result, tmp_path)

        assert output_file.exists()
        assert output_file.name == "metadata.json"

        content = json.loads(output_file.read_text())
        assert content["title"] == "Test Book"
        assert content["subtitle"] == "A Subtitle"

    @pytest.mark.asyncio
    async def test_export_authors_as_strings(self, exporter: JsonExporter, tmp_path: Path) -> None:
        """Test exporting authors when they're plain strings."""
        result = AggregatedResult(
            fields={
                "title": "Test",
                "authors": ["Author One", "Author Two"],
            }
        )

        output_file = await exporter.export(result, tmp_path)
        content = json.loads(output_file.read_text())

        assert content["authors"] == ["Author One", "Author Two"]

    @pytest.mark.asyncio
    async def test_export_authors_as_person_objects(
        self, exporter: JsonExporter, tmp_path: Path
    ) -> None:
        """Test exporting authors when they're Person-like objects."""

        @dataclass
        class Person:
            name: str
            asin: str | None = None

        result = AggregatedResult(
            fields={
                "title": "Test",
                "authors": [Person("Author One", "B001"), Person("Author Two")],
            }
        )

        output_file = await exporter.export(result, tmp_path)
        content = json.loads(output_file.read_text())

        assert content["authors"] == ["Author One", "Author Two"]

    @pytest.mark.asyncio
    async def test_export_authors_as_dicts(self, exporter: JsonExporter, tmp_path: Path) -> None:
        """Test exporting authors when they're dicts."""
        result = AggregatedResult(
            fields={
                "title": "Test",
                "authors": [
                    {"name": "Author One", "asin": "B001"},
                    {"name": "Author Two"},
                ],
            }
        )

        output_file = await exporter.export(result, tmp_path)
        content = json.loads(output_file.read_text())

        assert content["authors"] == ["Author One", "Author Two"]

    @pytest.mark.asyncio
    async def test_export_series_with_position(
        self, exporter: JsonExporter, tmp_path: Path
    ) -> None:
        """Test exporting series with position."""
        result = AggregatedResult(
            fields={
                "title": "Test",
                "series_name": "The Series",
                "series_position": "2",
            }
        )

        output_file = await exporter.export(result, tmp_path)
        content = json.loads(output_file.read_text())

        assert content["series"] == ["The Series #2"]

    @pytest.mark.asyncio
    async def test_export_series_without_position(
        self, exporter: JsonExporter, tmp_path: Path
    ) -> None:
        """Test exporting series without position."""
        result = AggregatedResult(
            fields={
                "title": "Test",
                "series_name": "The Series",
            }
        )

        output_file = await exporter.export(result, tmp_path)
        content = json.loads(output_file.read_text())

        assert content["series"] == ["The Series"]

    @pytest.mark.asyncio
    async def test_export_release_date_string(self, exporter: JsonExporter, tmp_path: Path) -> None:
        """Test exporting release date as string."""
        result = AggregatedResult(
            fields={
                "title": "Test",
                "release_date": "2024-05-15",
            }
        )

        output_file = await exporter.export(result, tmp_path)
        content = json.loads(output_file.read_text())

        assert content["publishedYear"] == "2024"
        assert content["publishedDate"] == "2024-05-15"

    @pytest.mark.asyncio
    async def test_export_release_date_datetime(
        self, exporter: JsonExporter, tmp_path: Path
    ) -> None:
        """Test exporting release date as datetime."""
        result = AggregatedResult(
            fields={
                "title": "Test",
                "release_date": datetime(2024, 5, 15),
            }
        )

        output_file = await exporter.export(result, tmp_path)
        content = json.loads(output_file.read_text())

        assert content["publishedYear"] == "2024"

    @pytest.mark.asyncio
    async def test_export_explicit_flag(self, exporter: JsonExporter, tmp_path: Path) -> None:
        """Test exporting is_adult as explicit."""
        result = AggregatedResult(
            fields={
                "title": "Test",
                "is_adult": True,
            }
        )

        output_file = await exporter.export(result, tmp_path)
        content = json.loads(output_file.read_text())

        assert content["explicit"] is True

    @pytest.mark.asyncio
    async def test_export_chapters(self, exporter: JsonExporter, tmp_path: Path) -> None:
        """Test exporting chapters."""
        result = AggregatedResult(
            fields={
                "title": "Test",
                "chapters": [
                    {"id": 0, "start": 0.0, "end": 300.0, "title": "Opening Credits"},
                    {"id": 1, "start": 300.0, "end": 1800.0, "title": "Chapter 1"},
                ],
            }
        )

        output_file = await exporter.export(result, tmp_path)
        content = json.loads(output_file.read_text())

        assert len(content["chapters"]) == 2
        assert content["chapters"][0]["title"] == "Opening Credits"
        assert content["chapters"][1]["start"] == 300.0

    @pytest.mark.asyncio
    async def test_export_missing_title_uses_placeholder(
        self, exporter: JsonExporter, tmp_path: Path
    ) -> None:
        """Test that missing title uses 'Unknown' placeholder."""
        result = AggregatedResult(fields={})

        output_file = await exporter.export(result, tmp_path)
        content = json.loads(output_file.read_text())

        assert content["title"] == "Unknown"

    @pytest.mark.asyncio
    async def test_export_genres(self, exporter: JsonExporter, tmp_path: Path) -> None:
        """Test exporting genres."""

        @dataclass
        class Genre:
            name: str
            asin: str | None = None

        result = AggregatedResult(
            fields={
                "title": "Test",
                "genres": [Genre("Science Fiction"), Genre("Fantasy")],
            }
        )

        output_file = await exporter.export(result, tmp_path)
        content = json.loads(output_file.read_text())

        assert content["genres"] == ["Science Fiction", "Fantasy"]

    @pytest.mark.asyncio
    async def test_export_asin(self, exporter: JsonExporter, tmp_path: Path) -> None:
        """Test exporting ASIN."""
        result = AggregatedResult(
            fields={
                "title": "Test",
                "asin": "B08G9PRS1K",
            }
        )

        output_file = await exporter.export(result, tmp_path)
        content = json.loads(output_file.read_text())

        assert content["asin"] == "B08G9PRS1K"

    @pytest.mark.asyncio
    async def test_export_full_metadata(self, exporter: JsonExporter, tmp_path: Path) -> None:
        """Test exporting comprehensive metadata."""
        result = AggregatedResult(
            fields={
                "title": "The Way of Kings",
                "subtitle": "Book One of The Stormlight Archive",
                "authors": [{"name": "Brandon Sanderson", "asin": "B001IGFHW6"}],
                "narrators": [{"name": "Michael Kramer"}, {"name": "Kate Reading"}],
                "series_name": "The Stormlight Archive",
                "series_position": "1",
                "genres": [{"name": "Fantasy"}, {"name": "Epic Fantasy"}],
                "description": "<p>A great book.</p>",
                "release_date": "2010-08-31",
                "publisher": "Tor Books",
                "language": "english",
                "isbn": "9780765326355",
                "asin": "B003P2WO5E",
            }
        )

        output_file = await exporter.export(result, tmp_path)
        content = json.loads(output_file.read_text())

        assert content["title"] == "The Way of Kings"
        assert content["subtitle"] == "Book One of The Stormlight Archive"
        assert content["authors"] == ["Brandon Sanderson"]
        assert content["narrators"] == ["Michael Kramer", "Kate Reading"]
        assert content["series"] == ["The Stormlight Archive #1"]
        assert content["genres"] == ["Fantasy", "Epic Fantasy"]
        assert content["description"] == "<p>A great book.</p>"
        assert content["publishedYear"] == "2010"
        assert content["publishedDate"] == "2010-08-31"
        assert content["publisher"] == "Tor Books"
        assert content["language"] == "english"
        assert content["isbn"] == "9780765326355"
        assert content["asin"] == "B003P2WO5E"


class TestJsonExporterChapterFormats:
    """Tests for JsonExporter chapter format handling."""

    @pytest.fixture
    def exporter(self) -> JsonExporter:
        return JsonExporter()

    @pytest.mark.asyncio
    async def test_chapters_with_start_time_key(
        self, exporter: JsonExporter, tmp_path: Path
    ) -> None:
        """Test chapters with start_time/end_time keys."""
        result = AggregatedResult(
            fields={
                "title": "Test",
                "chapters": [
                    {"start_time": 0.0, "end_time": 300.0, "title": "Chapter 1"},
                ],
            }
        )

        output_file = await exporter.export(result, tmp_path)
        content = json.loads(output_file.read_text())

        assert content["chapters"][0]["start"] == 0.0
        assert content["chapters"][0]["end"] == 300.0

    @pytest.mark.asyncio
    async def test_chapters_as_dataclass(self, exporter: JsonExporter, tmp_path: Path) -> None:
        """Test chapters as dataclass objects."""

        @dataclass
        class Chapter:
            title: str
            start_time: float
            end_time: float | None = None

        result = AggregatedResult(
            fields={
                "title": "Test",
                "chapters": [
                    Chapter("Chapter 1", 0.0, 300.0),
                    Chapter("Chapter 2", 300.0, 600.0),
                ],
            }
        )

        output_file = await exporter.export(result, tmp_path)
        content = json.loads(output_file.read_text())

        assert len(content["chapters"]) == 2
        assert content["chapters"][0]["title"] == "Chapter 1"
        assert content["chapters"][0]["start"] == 0.0


class TestMetadataExporterProtocol:
    """Tests for MetadataExporter protocol conformance."""

    def test_json_exporter_implements_protocol(self) -> None:
        """Test JsonExporter implements the protocol."""
        exporter = JsonExporter()

        # Check protocol attributes exist
        assert hasattr(exporter, "name")
        assert hasattr(exporter, "file_extension")
        assert hasattr(exporter, "description")
        assert hasattr(exporter, "export")

        # Check values
        assert exporter.name == "json"
        assert exporter.file_extension == ".json"
        assert isinstance(exporter.description, str)

    def test_is_runtime_checkable(self) -> None:
        """Test protocol is runtime checkable."""
        exporter = JsonExporter()
        assert isinstance(exporter, MetadataExporter)


class TestExportError:
    """Tests for ExportError handling in exporters."""

    @pytest.fixture
    def exporter(self) -> JsonExporter:
        """Create a JsonExporter instance."""
        return JsonExporter()

    @pytest.mark.asyncio
    async def test_export_raises_export_error_on_write_failure(
        self, exporter: JsonExporter, tmp_path: Path
    ) -> None:
        """Test that write failures raise ExportError."""
        result = AggregatedResult(fields={"title": "Test"})

        with patch.object(Path, "write_text", side_effect=OSError("Disk full")):
            with pytest.raises(ExportError) as exc_info:
                await exporter.export(result, tmp_path)

            assert "Failed to write metadata.json" in str(exc_info.value)
            assert exc_info.value.format_name == "json"

    @pytest.mark.asyncio
    async def test_export_raises_export_error_on_permission_denied(
        self, exporter: JsonExporter, tmp_path: Path
    ) -> None:
        """Test that permission errors raise ExportError."""
        result = AggregatedResult(fields={"title": "Test"})

        with patch.object(Path, "write_text", side_effect=PermissionError("Permission denied")):
            with pytest.raises(ExportError) as exc_info:
                await exporter.export(result, tmp_path)

            assert "Permission denied" in str(exc_info.value)
            assert exc_info.value.format_name == "json"
            # Check that it wraps the original error
            assert exc_info.value.__cause__ is not None


class TestOpfExporter:
    """Tests for OpfExporter."""

    @pytest.fixture
    def exporter(self) -> OpfExporter:
        """Create an OpfExporter instance."""
        return OpfExporter()

    def test_exporter_attributes(self, exporter: OpfExporter) -> None:
        """Test exporter has correct attributes."""
        assert exporter.name == "opf"
        assert exporter.file_extension == ".opf"
        assert "OPF" in exporter.description

    @pytest.mark.asyncio
    async def test_export_basic(self, exporter: OpfExporter, tmp_path: Path) -> None:
        """Test basic OPF export functionality."""
        result = AggregatedResult(
            fields={
                "title": "Test Book",
                "subtitle": "A Subtitle",
                "language": "English",
            }
        )

        output_file = await exporter.export(result, tmp_path)

        assert output_file.exists()
        assert output_file.name == "metadata.opf"

        content = output_file.read_text()
        assert "<dc:title>Test Book</dc:title>" in content
        assert "<dc:subtitle>A Subtitle</dc:subtitle>" in content

    @pytest.mark.asyncio
    async def test_export_with_authors(self, exporter: OpfExporter, tmp_path: Path) -> None:
        """Test OPF export with authors."""
        result = AggregatedResult(
            fields={
                "title": "Test",
                "authors": [{"name": "Author One"}, {"name": "Author Two"}],
                "language": "English",
            }
        )

        output_file = await exporter.export(result, tmp_path)
        content = output_file.read_text()

        assert 'opf:role="aut"' in content
        assert "Author One" in content
        assert "Author Two" in content

    @pytest.mark.asyncio
    async def test_export_with_narrators(self, exporter: OpfExporter, tmp_path: Path) -> None:
        """Test OPF export with narrators."""
        result = AggregatedResult(
            fields={
                "title": "Test",
                "narrators": ["Narrator One"],
                "language": "English",
            }
        )

        output_file = await exporter.export(result, tmp_path)
        content = output_file.read_text()

        assert 'opf:role="nrt"' in content
        assert "Narrator One" in content

    @pytest.mark.asyncio
    async def test_export_with_identifiers(self, exporter: OpfExporter, tmp_path: Path) -> None:
        """Test OPF export with ASIN and ISBN."""
        result = AggregatedResult(
            fields={
                "title": "Test",
                "asin": "B08G9PRS1K",
                "isbn": "9780765365286",
                "language": "English",
            }
        )

        output_file = await exporter.export(result, tmp_path)
        content = output_file.read_text()

        assert 'opf:scheme="ASIN"' in content
        assert "B08G9PRS1K" in content
        assert 'opf:scheme="ISBN"' in content
        assert "9780765365286" in content

    @pytest.mark.asyncio
    async def test_export_with_series(self, exporter: OpfExporter, tmp_path: Path) -> None:
        """Test OPF export with series information."""
        result = AggregatedResult(
            fields={
                "title": "Test",
                "series_name": "The Stormlight Archive",
                "series_position": "1",
                "language": "English",
            }
        )

        output_file = await exporter.export(result, tmp_path)
        content = output_file.read_text()

        assert 'name="calibre:series"' in content
        assert "The Stormlight Archive" in content
        assert 'name="calibre:series_index"' in content

    @pytest.mark.asyncio
    async def test_export_with_genres(self, exporter: OpfExporter, tmp_path: Path) -> None:
        """Test OPF export with genres as subjects."""
        result = AggregatedResult(
            fields={
                "title": "Test",
                "genres": [{"name": "Fantasy"}, {"name": "Epic"}],
                "language": "English",
            }
        )

        output_file = await exporter.export(result, tmp_path)
        content = output_file.read_text()

        assert "<dc:subject>Fantasy</dc:subject>" in content
        assert "<dc:subject>Epic</dc:subject>" in content

    @pytest.mark.asyncio
    async def test_export_language_conversion(self, exporter: OpfExporter, tmp_path: Path) -> None:
        """Test that language is converted to ISO format."""
        result = AggregatedResult(
            fields={
                "title": "Test",
                "language": "English",
            }
        )

        output_file = await exporter.export(result, tmp_path)
        content = output_file.read_text()

        # English should be converted to "eng" ISO code
        assert "<dc:language>eng</dc:language>" in content

    @pytest.mark.asyncio
    async def test_export_raises_export_error_on_write_failure(
        self, exporter: OpfExporter, tmp_path: Path
    ) -> None:
        """Test that write failures raise ExportError."""
        result = AggregatedResult(fields={"title": "Test", "language": "English"})

        with patch.object(Path, "write_text", side_effect=OSError("Disk full")):
            with pytest.raises(ExportError) as exc_info:
                await exporter.export(result, tmp_path)

            assert "Failed to write metadata.opf" in str(exc_info.value)
            assert exc_info.value.format_name == "opf"
            # Verify original exception is preserved as __cause__
            assert exc_info.value.__cause__ is not None
            assert isinstance(exc_info.value.__cause__, OSError)

    @pytest.mark.asyncio
    async def test_export_raises_export_error_on_validation_failure(
        self, exporter: OpfExporter, tmp_path: Path
    ) -> None:
        """Test that ValidationError during metadata conversion raises ExportError."""
        from pydantic import ValidationError

        result = AggregatedResult(fields={"title": "Test"})

        # Mock _convert_to_opf_metadata to raise ValidationError
        with patch.object(
            exporter,
            "_convert_to_opf_metadata",
            side_effect=ValidationError.from_exception_data(
                "OPFMetadata", [{"type": "missing", "loc": ("title",), "msg": "Field required"}]
            ),
        ):
            with pytest.raises(ExportError) as exc_info:
                await exporter.export(result, tmp_path)

            assert "Invalid metadata for OPF export" in str(exc_info.value)
            assert exc_info.value.format_name == "opf"
            assert exc_info.value.__cause__ is not None
            assert isinstance(exc_info.value.__cause__, ValidationError)


class TestOpfExporterRegistry:
    """Tests for exporter registry with OPF."""

    def test_get_opf_exporter(self) -> None:
        """Test getting OPF exporter from registry."""
        exporter = get_exporter("opf")
        assert isinstance(exporter, OpfExporter)
        assert exporter.name == "opf"

    def test_list_exporters_includes_opf(self) -> None:
        """Test that list_exporters includes opf."""
        exporters = list_exporters()
        assert "opf" in exporters
        assert "json" in exporters
