"""Tests for abs/rename.py module."""

from __future__ import annotations

import json
from pathlib import Path


class TestAbsMetadataSchema:
    """Tests for AbsMetadataSchema Pydantic model."""

    def test_basic_parsing(self) -> None:
        """Test parsing basic metadata."""
        from mamfast.abs.rename import AbsMetadataSchema

        data = {
            "title": "Project Hail Mary",
            "authors": ["Andy Weir"],
            "narrators": ["Ray Porter"],
            "asin": "B08G9PRS1K",
            "publishedYear": "2021",
        }
        schema = AbsMetadataSchema.model_validate(data)
        assert schema.title == "Project Hail Mary"
        assert schema.authors == ["Andy Weir"]
        assert schema.asin == "B08G9PRS1K"

    def test_series_parsing(self) -> None:
        """Test parsing series info."""
        from mamfast.abs.rename import AbsMetadataSchema

        data = {
            "title": "The Way of Kings",
            "series": ["The Stormlight Archive #1"],
            "asin": "B003ZWFO7E",
        }
        schema = AbsMetadataSchema.model_validate(data)
        assert "The Stormlight Archive #1" in schema.series

    def test_missing_optional_fields(self) -> None:
        """Test that missing optional fields get defaults."""
        from mamfast.abs.rename import AbsMetadataSchema

        data = {"title": "Some Book"}
        schema = AbsMetadataSchema.model_validate(data)
        assert schema.asin is None
        assert schema.authors == []
        assert schema.series == []

    def test_published_year_int(self) -> None:
        """Test publishedYear as int."""
        from mamfast.abs.rename import AbsMetadataSchema

        data = {"title": "Book", "publishedYear": 2021}
        schema = AbsMetadataSchema.model_validate(data)
        assert schema.publishedYear == 2021


class TestParseAbsMetadata:
    """Tests for parse_abs_metadata function."""

    def test_valid_metadata(self, tmp_path: Path) -> None:
        """Test parsing valid metadata.json file."""
        from mamfast.abs.rename import parse_abs_metadata

        folder = tmp_path / "book_folder"
        folder.mkdir()
        metadata_file = folder / "metadata.json"
        metadata_file.write_text(
            json.dumps(
                {
                    "title": "Test Book",
                    "authors": ["Test Author"],
                    "asin": "B0123456789",
                    "series": ["Test Series #5"],
                    "publishedYear": "2023",
                }
            )
        )

        result = parse_abs_metadata(folder)
        assert result is not None
        assert result.title == "Test Book"
        assert result.asin == "B0123456789"
        assert result.series == "Test Series"
        assert result.series_position == "5"
        assert result.year == 2023

    def test_no_metadata_file(self, tmp_path: Path) -> None:
        """Test returns None when no metadata.json exists."""
        from mamfast.abs.rename import parse_abs_metadata

        folder = tmp_path / "book_folder"
        folder.mkdir()

        result = parse_abs_metadata(folder)
        assert result is None

    def test_invalid_json(self, tmp_path: Path) -> None:
        """Test returns None for invalid JSON."""
        from mamfast.abs.rename import parse_abs_metadata

        folder = tmp_path / "book_folder"
        folder.mkdir()
        metadata_file = folder / "metadata.json"
        metadata_file.write_text("not valid json")

        result = parse_abs_metadata(folder)
        assert result is None

    def test_series_position_decimal(self, tmp_path: Path) -> None:
        """Test parsing decimal series positions (novellas)."""
        from mamfast.abs.rename import parse_abs_metadata

        folder = tmp_path / "book_folder"
        folder.mkdir()
        metadata_file = folder / "metadata.json"
        metadata_file.write_text(
            json.dumps(
                {
                    "title": "Novella",
                    "series": ["Old Man's War #1.5"],
                }
            )
        )

        result = parse_abs_metadata(folder)
        assert result is not None
        assert result.series == "Old Man's War"
        assert result.series_position == "1.5"


class TestHasAudioFiles:
    """Tests for has_audio_files function."""

    def test_with_m4b(self, tmp_path: Path) -> None:
        """Test folder with .m4b file."""
        from mamfast.abs.rename import has_audio_files

        folder = tmp_path / "book"
        folder.mkdir()
        (folder / "audiobook.m4b").touch()

        assert has_audio_files(folder) is True

    def test_with_mp3(self, tmp_path: Path) -> None:
        """Test folder with .mp3 files."""
        from mamfast.abs.rename import has_audio_files

        folder = tmp_path / "book"
        folder.mkdir()
        (folder / "chapter01.mp3").touch()
        (folder / "chapter02.mp3").touch()

        assert has_audio_files(folder) is True

    def test_no_audio(self, tmp_path: Path) -> None:
        """Test folder without audio files."""
        from mamfast.abs.rename import has_audio_files

        folder = tmp_path / "book"
        folder.mkdir()
        (folder / "cover.jpg").touch()
        (folder / "metadata.json").touch()

        assert has_audio_files(folder) is False

    def test_empty_folder(self, tmp_path: Path) -> None:
        """Test empty folder."""
        from mamfast.abs.rename import has_audio_files

        folder = tmp_path / "book"
        folder.mkdir()

        assert has_audio_files(folder) is False


class TestDetectEditionFlags:
    """Tests for detect_edition_flags function."""

    def test_full_cast(self) -> None:
        """Test detecting Full-Cast edition."""
        from mamfast.abs.rename import detect_edition_flags

        flags = detect_edition_flags("Book Title (Full-Cast)")
        assert "Full-Cast" in flags

    def test_graphic_audio(self) -> None:
        """Test detecting Graphic Audio edition."""
        from mamfast.abs.rename import detect_edition_flags

        flags = detect_edition_flags("Book Title (Graphic Audio)")
        assert "Graphic Audio" in flags

    def test_publishers_pack(self) -> None:
        """Test detecting Publisher's Pack."""
        from mamfast.abs.rename import detect_edition_flags

        flags = detect_edition_flags("Series vol_01-03 (Publisher's Pack)")
        assert "Publisher's Pack" in flags

    def test_multiple_flags(self) -> None:
        """Test detecting multiple flags."""
        from mamfast.abs.rename import detect_edition_flags

        flags = detect_edition_flags("Title (Dolby Atmos) (Unabridged)")
        assert "Dolby Atmos" in flags
        assert "Unabridged" in flags

    def test_no_flags(self) -> None:
        """Test no flags returns empty list."""
        from mamfast.abs.rename import detect_edition_flags

        flags = detect_edition_flags("Just a Normal Title")
        assert flags == []


class TestDiscoverRenameCandidates:
    """Tests for discover_rename_candidates function."""

    def test_finds_leaf_folders(self, tmp_path: Path) -> None:
        """Test discovering leaf folders with audio."""
        from mamfast.abs.rename import discover_rename_candidates

        # Create structure: author/series/book
        book_folder = tmp_path / "Author" / "Series" / "Book vol_01"
        book_folder.mkdir(parents=True)
        (book_folder / "audiobook.m4b").touch()

        candidates = discover_rename_candidates(tmp_path)
        assert len(candidates) == 1
        assert candidates[0] == book_folder

    def test_skips_folders_without_audio(self, tmp_path: Path) -> None:
        """Test skips folders without audio files."""
        from mamfast.abs.rename import discover_rename_candidates

        folder = tmp_path / "NoAudio"
        folder.mkdir()
        (folder / "readme.txt").touch()

        candidates = discover_rename_candidates(tmp_path)
        assert len(candidates) == 0

    def test_multiple_books(self, tmp_path: Path) -> None:
        """Test discovering multiple book folders."""
        from mamfast.abs.rename import discover_rename_candidates

        for i in range(3):
            folder = tmp_path / f"Book{i}"
            folder.mkdir()
            (folder / "audio.m4b").touch()

        candidates = discover_rename_candidates(tmp_path)
        assert len(candidates) == 3


class TestRenameCandidate:
    """Tests for RenameCandidate dataclass."""

    def test_creation(self) -> None:
        """Test creating a RenameCandidate."""
        from mamfast.abs.rename import RenameCandidate

        candidate = RenameCandidate(
            source_path=Path("/a/Book"),
            current_name="Book",
        )
        assert candidate.current_name == "Book"
        assert candidate.status == "needs_rename"
        assert candidate.parsed is None
        assert candidate.target_name is None

    def test_with_optional_fields(self) -> None:
        """Test RenameCandidate with optional fields."""
        from mamfast.abs.rename import RenameCandidate

        candidate = RenameCandidate(
            source_path=Path("/a/Book"),
            current_name="Book",
            target_name="New Book Name",
            edition_flags=["Full-Cast"],
        )
        assert candidate.target_name == "New Book Name"
        assert "Full-Cast" in candidate.edition_flags


class TestComputeTargetName:
    """Tests for compute_target_name function."""

    def test_requires_parsed_data(self) -> None:
        """Test that compute_target_name requires parsed folder data."""
        from mamfast.abs.rename import RenameCandidate, compute_target_name

        # Without parsed data, should return error status
        candidate = RenameCandidate(
            source_path=Path("/a/Book"),
            current_name="Book",
        )

        result = compute_target_name(candidate)
        assert result.status == "error"


class TestRenameFolder:
    """Tests for rename_folder function."""

    def test_dry_run(self, tmp_path: Path) -> None:
        """Test dry run doesn't actually rename."""
        from mamfast.abs.rename import RenameCandidate, rename_folder

        source = tmp_path / "OriginalName"
        source.mkdir()
        (source / "audio.m4b").touch()

        candidate = RenameCandidate(
            source_path=source,
            current_name="OriginalName",
            target_name="NewName",
            status="needs_rename",
        )

        result = rename_folder(candidate, dry_run=True)
        assert result.status == "dry_run"
        assert source.exists()  # Original still exists
        assert not (tmp_path / "NewName").exists()

    def test_actual_rename(self, tmp_path: Path) -> None:
        """Test actual rename operation."""
        from mamfast.abs.rename import RenameCandidate, rename_folder

        source = tmp_path / "OriginalName"
        source.mkdir()
        (source / "audio.m4b").touch()

        candidate = RenameCandidate(
            source_path=source,
            current_name="OriginalName",
            target_name="NewName",
            status="needs_rename",
        )

        result = rename_folder(candidate, dry_run=False)
        assert result.status == "success"
        assert not source.exists()  # Original no longer exists
        assert (tmp_path / "NewName").exists()

    def test_skipped_if_wrong_status(self) -> None:
        """Test skips when status is not needs_rename."""
        from mamfast.abs.rename import RenameCandidate, rename_folder

        candidate = RenameCandidate(
            source_path=Path("/a/SameName"),
            current_name="SameName",
            target_name="NewName",
            status="up_to_date",  # Not needs_rename
        )

        result = rename_folder(candidate, dry_run=False)
        assert result.status == "skipped"

    def test_failed_no_target(self) -> None:
        """Test fails when no target name."""
        from mamfast.abs.rename import RenameCandidate, rename_folder

        candidate = RenameCandidate(
            source_path=Path("/a/Name"),
            current_name="Name",
            target_name=None,  # No target
            status="needs_rename",
        )

        result = rename_folder(candidate, dry_run=False)
        assert result.status == "failed"


class TestRenameResult:
    """Tests for RenameResult dataclass."""

    def test_success_result(self) -> None:
        """Test successful rename result."""
        from mamfast.abs.rename import RenameResult

        result = RenameResult(
            source_path=Path("/a/Original"),
            target_path=Path("/a/Target"),
            status="success",
        )
        assert result.status == "success"
        assert result.error is None

    def test_error_result(self) -> None:
        """Test error result."""
        from mamfast.abs.rename import RenameResult

        result = RenameResult(
            source_path=Path("/a/Original"),
            target_path=None,
            status="failed",
            error="Something went wrong",
        )
        assert result.status == "failed"
        assert result.error is not None
        assert "wrong" in result.error


class TestRenameSummary:
    """Tests for RenameSummary dataclass."""

    def test_default_values(self) -> None:
        """Test default summary values."""
        from mamfast.abs.rename import RenameSummary

        summary = RenameSummary()
        assert summary.total_candidates == 0
        assert summary.renamed == 0
        assert summary.errors == 0

    def test_custom_values(self) -> None:
        """Test summary with custom values."""
        from mamfast.abs.rename import RenameSummary

        summary = RenameSummary(
            total_candidates=10,
            renamed=8,
            skipped_up_to_date=1,
            errors=1,
        )
        assert summary.total_candidates == 10
        assert summary.renamed == 8


class TestParseCandidate:
    """Tests for parse_candidate function."""

    def test_basic_parse(self, tmp_path: Path) -> None:
        """Test basic folder name parsing."""
        from mamfast.abs.rename import parse_candidate

        folder = tmp_path / "Brandon Sanderson - Mistborn vol_01 (2023) {ASIN.B001234567}"
        folder.mkdir()

        candidate = parse_candidate(folder)
        assert candidate.current_name == folder.name
        assert candidate.source_path == folder
        # Parsed should be set (may or may not extract data depending on parser)
        assert candidate.parsed is not None

    def test_detects_edition_flags(self, tmp_path: Path) -> None:
        """Test that edition flags are detected."""
        from mamfast.abs.rename import parse_candidate

        folder = tmp_path / "Title (Full-Cast) (Dolby Atmos)"
        folder.mkdir()

        candidate = parse_candidate(folder)
        assert "Full-Cast" in candidate.edition_flags
        assert "Dolby Atmos" in candidate.edition_flags
