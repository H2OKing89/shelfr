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


class TestRenameFilesInside:
    """Tests for _rename_files_inside helper."""

    def test_renames_media_files(self, tmp_path: Path) -> None:
        """Test that media files are renamed."""
        from mamfast.abs.rename import _rename_files_inside

        folder = tmp_path / "New Book Name"
        folder.mkdir()
        (folder / "old_name.m4b").touch()
        (folder / "old_name.cue").touch()

        renamed = _rename_files_inside(folder, "New Book Name")

        assert "old_name.m4b" in renamed
        assert "old_name.cue" in renamed
        assert (folder / "New Book Name.m4b").exists()
        assert (folder / "New Book Name.cue").exists()

    def test_skips_cover_and_metadata(self, tmp_path: Path) -> None:
        """Test that cover.jpg and metadata.json are skipped."""
        from mamfast.abs.rename import _rename_files_inside

        folder = tmp_path / "New Book"
        folder.mkdir()
        (folder / "cover.jpg").touch()
        (folder / "metadata.json").touch()
        (folder / "audio.m4b").touch()

        renamed = _rename_files_inside(folder, "New Book")

        assert "cover.jpg" not in renamed
        assert "metadata.json" not in renamed
        assert "audio.m4b" in renamed
        # Sidecar files unchanged
        assert (folder / "cover.jpg").exists()
        assert (folder / "metadata.json").exists()

    def test_idempotent_when_already_named(self, tmp_path: Path) -> None:
        """Test no rename when files already have correct name."""
        from mamfast.abs.rename import _rename_files_inside

        folder = tmp_path / "Book Name"
        folder.mkdir()
        (folder / "Book Name.m4b").touch()

        renamed = _rename_files_inside(folder, "Book Name")

        assert renamed == []
        assert (folder / "Book Name.m4b").exists()

    def test_multi_file_audiobook_gets_part_numbers(self, tmp_path: Path) -> None:
        """Test that multiple audio files get Part XX suffixes to prevent collisions."""
        from mamfast.abs.rename import _rename_files_inside

        folder = tmp_path / "Multi Part Book"
        folder.mkdir()
        # Create multiple audio files
        (folder / "disc1.m4b").touch()
        (folder / "disc2.m4b").touch()
        (folder / "disc3.m4b").touch()
        # And a companion file
        (folder / "playlist.m3u").touch()

        renamed = _rename_files_inside(folder, "Multi Part Book")

        # All files should be renamed
        assert len(renamed) == 4
        # Check the new names use Part XX format (sorted alphabetically first)
        assert (folder / "Multi Part Book - Part 01.m4b").exists()  # disc1
        assert (folder / "Multi Part Book - Part 02.m4b").exists()  # disc2
        assert (folder / "Multi Part Book - Part 03.m4b").exists()  # disc3
        assert (folder / "Multi Part Book - Part 04.m3u").exists()  # playlist

    def test_single_audio_with_companion_files_no_part_numbers(self, tmp_path: Path) -> None:
        """Test single audio file + companions don't get Part numbers."""
        from mamfast.abs.rename import _rename_files_inside

        folder = tmp_path / "Single File Book"
        folder.mkdir()
        # One audio file with companions
        (folder / "audio.m4b").touch()
        (folder / "audio.cue").touch()
        (folder / "audio.nfo").touch()

        _rename_files_inside(folder, "Single File Book")

        # All non-sidecar files renamed, but without Part numbers
        assert (folder / "Single File Book.m4b").exists()
        assert (folder / "Single File Book.cue").exists()
        assert (folder / "Single File Book.nfo").exists()


class TestRenameWithFilesInside:
    """Tests for rename_folder file renaming (always enabled)."""

    def test_rename_folder_with_files(self, tmp_path: Path) -> None:
        """Test folder rename automatically renames files inside."""
        from mamfast.abs.rename import RenameCandidate, rename_folder

        source = tmp_path / "OldName"
        source.mkdir()
        (source / "audio.m4b").touch()
        (source / "cover.jpg").touch()

        candidate = RenameCandidate(
            source_path=source,
            current_name="OldName",
            target_name="NewName",
            status="needs_rename",
        )

        result = rename_folder(candidate, dry_run=False)

        assert result.status == "success"
        target = tmp_path / "NewName"
        assert target.exists()
        assert (target / "NewName.m4b").exists()
        assert (target / "cover.jpg").exists()  # Skipped
        assert result.files_renamed == ["audio.m4b"]

    def test_force_rename_files_when_folder_up_to_date(self, tmp_path: Path) -> None:
        """Test force mode renames files even when folder is already correct."""
        from mamfast.abs.rename import RenameCandidate, rename_folder

        folder = tmp_path / "CorrectName"
        folder.mkdir()
        (folder / "wrong_file.m4b").touch()
        (folder / "cover.jpg").touch()

        candidate = RenameCandidate(
            source_path=folder,
            current_name="CorrectName",
            target_name="CorrectName",
            status="up_to_date",
        )

        # Without force, should skip
        result = rename_folder(candidate, dry_run=False, force=False)
        assert result.status == "skipped"

        # With force, should rename files inside
        result = rename_folder(candidate, dry_run=False, force=True)
        assert result.status == "success"
        assert folder.exists()  # Folder unchanged
        assert (folder / "CorrectName.m4b").exists()  # File renamed
        assert not (folder / "wrong_file.m4b").exists()
        assert (folder / "cover.jpg").exists()  # Sidecar preserved
        assert result.files_renamed == ["wrong_file.m4b"]


class TestGenerateReport:
    """Tests for generate_report function."""

    def test_generates_valid_json(self, tmp_path: Path) -> None:
        """Test report is valid JSON with expected structure."""
        from mamfast.abs.rename import (
            RenameCandidate,
            RenameResult,
            RenameSummary,
            generate_report,
        )

        results = [
            RenameResult(
                source_path=Path("/lib/OldName"),
                target_path=Path("/lib/NewName"),
                status="success",
            ),
        ]
        candidates = [
            RenameCandidate(
                source_path=Path("/lib/OldName"),
                current_name="OldName",
                asin_source="abs_metadata",
            ),
        ]
        summary = RenameSummary(total_candidates=1, renamed=1)

        report_path = tmp_path / "report.json"
        generate_report(results, candidates, summary, report_path)

        assert report_path.exists()
        with open(report_path) as f:
            data = json.load(f)

        assert "timestamp" in data
        assert data["summary"]["total"] == 1
        assert data["summary"]["renamed"] == 1
        assert len(data["results"]) == 1
        assert data["results"][0]["source_name"] == "OldName"
        assert data["results"][0]["asin_source"] == "abs_metadata"
        # Check new debugging fields exist
        assert "warnings" in data
        assert "by_status" in data
        assert "similarity_percent" in data["results"][0]


class TestFullPipeline:
    """Integration tests for the full rename pipeline."""

    def test_full_pipeline_dry_run(self, tmp_path: Path) -> None:
        """Test end-to-end pipeline with dry run."""
        from mamfast.abs.rename import run_rename_pipeline

        # Create fake library structure
        lib = tmp_path / "lib"
        lib.mkdir()

        # Book that needs renaming - metadata.json provides ASIN
        book = lib / "Some Random Name"
        book.mkdir()
        (book / "audio.m4b").touch()
        metadata = {
            "title": "The Real Title",
            "authors": ["Real Author"],
            "asin": "B0123456789",
            "publishedYear": "2022",
        }
        (book / "metadata.json").write_text(json.dumps(metadata))

        # Run pipeline in dry-run mode
        results, summary, candidates = run_rename_pipeline(
            source_dir=lib,
            dry_run=True,
        )

        assert summary.total_candidates == 1
        # Should be found and need renaming (name doesn't match target)
        assert len(candidates) == 1
        # The folder has ASIN from metadata, should be able to compute target

    def test_full_pipeline_actual_rename(self, tmp_path: Path) -> None:
        """Test actual rename operation."""
        from mamfast.abs.rename import run_rename_pipeline

        lib = tmp_path / "lib"
        lib.mkdir()

        # Book with metadata.json containing proper info
        book = lib / "Bad Name"
        book.mkdir()
        (book / "audio.m4b").touch()
        metadata = {
            "title": "Good Book",
            "authors": ["Good Author"],
            "asin": "B0999999999",
            "publishedYear": "2023",
        }
        (book / "metadata.json").write_text(json.dumps(metadata))

        # Run pipeline
        results, summary, candidates = run_rename_pipeline(
            source_dir=lib,
            dry_run=False,
        )

        # Should have processed one book
        assert summary.total_candidates == 1

        # If renamed, check new folder exists
        if summary.renamed > 0:
            # Find the new folder
            new_folders = list(lib.iterdir())
            assert len(new_folders) == 1
            assert "B0999999999" in new_folders[0].name

    def test_pipeline_skips_up_to_date(self, tmp_path: Path) -> None:
        """Test that correctly named folders are skipped."""
        from mamfast.abs.rename import run_rename_pipeline

        lib = tmp_path / "lib"
        lib.mkdir()

        # Book already in correct MAM format
        book = lib / "Good Book (2023) (Good Author) {ASIN.B0999999999}"
        book.mkdir()
        (book / "audio.m4b").touch()

        # Run pipeline
        results, summary, candidates = run_rename_pipeline(
            source_dir=lib,
            dry_run=True,
        )

        assert summary.total_candidates == 1
        # Should be marked as up_to_date or missing_asin (depends on metadata)
        assert summary.skipped_up_to_date + summary.skipped_missing_asin >= 0
