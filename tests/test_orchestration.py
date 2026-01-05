"""Tests for metadata orchestration functions."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shelfr.metadata.aggregator import AggregatedResult
from shelfr.metadata.orchestration import (
    export_metadata_async,
    fetch_all_metadata_legacy,
    fetch_metadata_async,
    fetch_metadata_legacy,
    save_metadata_files_legacy,
)
from shelfr.metadata.providers.types import LookupContext


class TestFetchMetadataLegacy:
    """Tests for fetch_metadata_legacy function."""

    def test_fetch_with_asin_only(self) -> None:
        """Test fetching with only ASIN provided (bypassing cache)."""
        mock_audnex = {"asin": "B08G9PRS1K", "title": "Test Book"}
        mock_chapters = [{"title": "Chapter 1", "startTime": 0}]

        with (
            patch(
                "shelfr.metadata.orchestration.fetch_audnex_book",
                return_value=(mock_audnex, "us"),
            ),
            patch(
                "shelfr.metadata.orchestration.fetch_audnex_chapters",
                return_value=mock_chapters,
            ),
        ):
            audnex, mediainfo, chapters = fetch_metadata_legacy(asin="B08G9PRS1K", use_cache=False)

            assert audnex == mock_audnex
            assert mediainfo is None
            assert chapters == mock_chapters

    def test_fetch_with_m4b_only(self, tmp_path: Path) -> None:
        """Test fetching with only m4b path provided."""
        m4b_file = tmp_path / "test.m4b"
        m4b_file.touch()

        mock_mediainfo = {"container": "m4a", "bitrate": 128000}

        with patch(
            "shelfr.metadata.orchestration.run_mediainfo",
            return_value=mock_mediainfo,
        ):
            audnex, mediainfo, chapters = fetch_metadata_legacy(m4b_path=m4b_file)

            assert audnex is None
            assert mediainfo == mock_mediainfo
            assert chapters is None

    def test_fetch_with_both(self, tmp_path: Path) -> None:
        """Test fetching with both ASIN and m4b path (bypassing cache)."""
        m4b_file = tmp_path / "test.m4b"
        m4b_file.touch()

        mock_audnex = {"asin": "B08G9PRS1K", "title": "Test Book"}
        mock_chapters = [{"title": "Chapter 1"}]
        mock_mediainfo = {"container": "m4a"}

        with (
            patch(
                "shelfr.metadata.orchestration.fetch_audnex_book",
                return_value=(mock_audnex, "us"),
            ),
            patch(
                "shelfr.metadata.orchestration.fetch_audnex_chapters",
                return_value=mock_chapters,
            ),
            patch(
                "shelfr.metadata.orchestration.run_mediainfo",
                return_value=mock_mediainfo,
            ),
        ):
            audnex, mediainfo, chapters = fetch_metadata_legacy(
                asin="B08G9PRS1K", m4b_path=m4b_file, use_cache=False
            )

            assert audnex == mock_audnex
            assert mediainfo == mock_mediainfo
            assert chapters == mock_chapters

    def test_fetch_with_nonexistent_m4b(self, tmp_path: Path) -> None:
        """Test fetching with nonexistent m4b path."""
        m4b_file = tmp_path / "nonexistent.m4b"

        audnex, mediainfo, chapters = fetch_metadata_legacy(m4b_path=m4b_file)

        assert audnex is None
        assert mediainfo is None
        assert chapters is None

    def test_fetch_with_none_inputs(self) -> None:
        """Test fetching with no inputs."""
        audnex, mediainfo, chapters = fetch_metadata_legacy()

        assert audnex is None
        assert mediainfo is None
        assert chapters is None


class TestSaveMetadataFilesLegacy:
    """Tests for save_metadata_files_legacy function."""

    def test_save_both_files(self, tmp_path: Path) -> None:
        """Test saving both audnex and mediainfo files."""
        audnex_data = {"asin": "B08G9PRS1K", "title": "Test"}
        mediainfo_data = {"container": "m4a"}

        with (
            patch("shelfr.metadata.orchestration.save_audnex_json") as mock_audnex,
            patch("shelfr.metadata.orchestration.save_mediainfo_json") as mock_mediainfo,
        ):
            save_metadata_files_legacy(
                tmp_path,
                audnex_data=audnex_data,
                mediainfo_data=mediainfo_data,
            )

            mock_audnex.assert_called_once_with(audnex_data, tmp_path / "audnex.json")
            mock_mediainfo.assert_called_once_with(mediainfo_data, tmp_path / "mediainfo.json")

    def test_save_audnex_only(self, tmp_path: Path) -> None:
        """Test saving only audnex file."""
        audnex_data = {"asin": "B08G9PRS1K"}

        with (
            patch("shelfr.metadata.orchestration.save_audnex_json") as mock_audnex,
            patch("shelfr.metadata.orchestration.save_mediainfo_json") as mock_mediainfo,
        ):
            save_metadata_files_legacy(tmp_path, audnex_data=audnex_data)

            mock_audnex.assert_called_once()
            mock_mediainfo.assert_not_called()

    def test_creates_output_directory(self, tmp_path: Path) -> None:
        """Test that output directory is created if needed."""
        output_dir = tmp_path / "subdir" / "nested"

        with (
            patch("shelfr.metadata.orchestration.save_audnex_json"),
            patch("shelfr.metadata.orchestration.save_mediainfo_json"),
        ):
            save_metadata_files_legacy(output_dir, audnex_data={"asin": "test"})

            assert output_dir.exists()


class TestFetchAllMetadataLegacy:
    """Tests for fetch_all_metadata_legacy function."""

    def test_fetch_without_save(self, tmp_path: Path) -> None:
        """Test fetching without saving intermediate files (bypassing cache)."""
        m4b_file = tmp_path / "test.m4b"
        m4b_file.touch()

        mock_audnex = {"asin": "B08G9PRS1K", "title": "Test"}
        mock_chapters = [{"title": "Ch 1"}]
        mock_mediainfo = {"container": "m4a"}

        with (
            patch(
                "shelfr.metadata.orchestration.fetch_audnex_book",
                return_value=(mock_audnex, "us"),
            ),
            patch(
                "shelfr.metadata.orchestration.fetch_audnex_chapters",
                return_value=mock_chapters,
            ),
            patch(
                "shelfr.metadata.orchestration.run_mediainfo",
                return_value=mock_mediainfo,
            ),
            patch("shelfr.metadata.orchestration.save_audnex_json") as mock_save_audnex,
            patch("shelfr.metadata.orchestration.save_mediainfo_json") as mock_save_mi,
        ):
            result = fetch_all_metadata_legacy(
                asin="B08G9PRS1K",
                m4b_path=m4b_file,
                output_dir=tmp_path,
                save_intermediate=False,
                use_cache=False,
            )

            assert result == (mock_audnex, mock_mediainfo, mock_chapters)
            mock_save_audnex.assert_not_called()
            mock_save_mi.assert_not_called()

    def test_fetch_with_save(self, tmp_path: Path) -> None:
        """Test fetching with saving intermediate files (bypassing cache)."""
        m4b_file = tmp_path / "test.m4b"
        m4b_file.touch()

        mock_audnex = {"asin": "B08G9PRS1K", "title": "Test"}
        mock_chapters = [{"title": "Ch 1"}]
        mock_mediainfo = {"container": "m4a"}

        with (
            patch(
                "shelfr.metadata.orchestration.fetch_audnex_book",
                return_value=(mock_audnex, "us"),
            ),
            patch(
                "shelfr.metadata.orchestration.fetch_audnex_chapters",
                return_value=mock_chapters,
            ),
            patch(
                "shelfr.metadata.orchestration.run_mediainfo",
                return_value=mock_mediainfo,
            ),
            patch("shelfr.metadata.orchestration.save_audnex_json") as mock_save_audnex,
            patch("shelfr.metadata.orchestration.save_mediainfo_json") as mock_save_mi,
        ):
            result = fetch_all_metadata_legacy(
                asin="B08G9PRS1K",
                m4b_path=m4b_file,
                output_dir=tmp_path,
                save_intermediate=True,
                use_cache=False,
            )

            assert result == (mock_audnex, mock_mediainfo, mock_chapters)
            mock_save_audnex.assert_called_once()
            mock_save_mi.assert_called_once()


class TestFetchMetadataAsync:
    """Tests for fetch_metadata_async function."""

    @pytest.mark.asyncio
    async def test_fetch_metadata_async_basic(self) -> None:
        """Test async metadata fetch."""
        ctx = LookupContext.from_asin(asin="B08G9PRS1K")

        mock_result = AggregatedResult(
            fields={"title": "Test Book", "authors": ["Test Author"]},
            sources={"title": "audnex", "authors": "audnex"},
        )

        with patch("shelfr.metadata.aggregator.MetadataAggregator") as mock_aggregator_cls:
            mock_aggregator = MagicMock()
            mock_aggregator.fetch_all = AsyncMock(return_value=mock_result)
            mock_aggregator_cls.return_value = mock_aggregator

            result = await fetch_metadata_async(ctx)

            assert result.fields["title"] == "Test Book"
            mock_aggregator.fetch_all.assert_called_once()


class TestExportMetadataAsync:
    """Tests for export_metadata_async function."""

    @pytest.mark.asyncio
    async def test_export_json_format(self, tmp_path: Path) -> None:
        """Test exporting to JSON format."""
        result = AggregatedResult(
            fields={
                "title": "Test Book",
                "authors": [{"name": "Author One"}],
                "description": "A test description",
            },
            sources={"title": "audnex"},
        )

        files = await export_metadata_async(result, tmp_path, formats=["json"])

        assert "json" in files
        assert files["json"].exists()

        # Verify content
        content = json.loads(files["json"].read_text())
        assert content["title"] == "Test Book"

    @pytest.mark.asyncio
    async def test_export_unknown_format(self, tmp_path: Path) -> None:
        """Test exporting with unknown format logs warning."""
        result = AggregatedResult(fields={"title": "Test"})

        files = await export_metadata_async(result, tmp_path, formats=["unknown_fmt"])

        assert "unknown_fmt" not in files

    @pytest.mark.asyncio
    async def test_export_creates_output_directory(self, tmp_path: Path) -> None:
        """Test that output directory is created."""
        result = AggregatedResult(fields={"title": "Test"})
        output_dir = tmp_path / "new" / "nested"

        await export_metadata_async(result, output_dir, formats=["json"])

        assert output_dir.exists()

    @pytest.mark.asyncio
    async def test_export_default_format(self, tmp_path: Path) -> None:
        """Test default format is JSON."""
        result = AggregatedResult(fields={"title": "Test"})

        files = await export_metadata_async(result, tmp_path)

        assert "json" in files
