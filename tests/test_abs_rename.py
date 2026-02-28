"""Tests for abs/rename.py module."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any


class TestAbsMetadataJson:
    """Tests for AbsMetadataJson Pydantic model (used by rename module)."""

    def test_basic_parsing(self) -> None:
        """Test parsing basic metadata."""
        from shelfr.schemas.abs_metadata import AbsMetadataJson

        data = {
            "title": "Project Hail Mary",
            "authors": ["Andy Weir"],
            "narrators": ["Ray Porter"],
            "asin": "B08G9PRS1K",
            "publishedYear": "2021",
        }
        schema = AbsMetadataJson.model_validate(data)
        assert schema.title == "Project Hail Mary"
        assert schema.authors == ["Andy Weir"]
        assert schema.asin == "B08G9PRS1K"

    def test_series_parsing(self) -> None:
        """Test parsing series info."""
        from shelfr.schemas.abs_metadata import AbsMetadataJson

        data = {
            "title": "The Way of Kings",
            "series": ["The Stormlight Archive #1"],
            "asin": "B003ZWFO7E",
        }
        schema = AbsMetadataJson.model_validate(data)
        assert "The Stormlight Archive #1" in schema.series

    def test_missing_optional_fields(self) -> None:
        """Test that missing optional fields get defaults."""
        from shelfr.schemas.abs_metadata import AbsMetadataJson

        data = {"title": "Some Book"}
        schema = AbsMetadataJson.model_validate(data)
        assert schema.asin is None
        assert schema.authors == []
        assert schema.series == []

    def test_published_year_int(self) -> None:
        """Test publishedYear as int."""
        from shelfr.schemas.abs_metadata import AbsMetadataJson

        data = {"title": "Book", "publishedYear": 2021}
        schema = AbsMetadataJson.model_validate(data)
        assert schema.published_year == 2021

    def test_missing_title_allowed_for_read(self) -> None:
        """Test that missing title is allowed when reading existing metadata."""
        from shelfr.schemas.abs_metadata import AbsMetadataJson

        data = {"authors": ["Some Author"], "asin": "B0123456789"}
        schema = AbsMetadataJson.model_validate(data)
        assert schema.title is None
        assert schema.authors == ["Some Author"]


class TestParseAbsMetadata:
    """Tests for parse_abs_metadata function."""

    def test_valid_metadata(self, tmp_path: Path) -> None:
        """Test parsing valid metadata.json file."""
        from shelfr.abs.rename import parse_abs_metadata

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
        from shelfr.abs.rename import parse_abs_metadata

        folder = tmp_path / "book_folder"
        folder.mkdir()

        result = parse_abs_metadata(folder)
        assert result is None

    def test_invalid_json(self, tmp_path: Path) -> None:
        """Test returns None for invalid JSON."""
        from shelfr.abs.rename import parse_abs_metadata

        folder = tmp_path / "book_folder"
        folder.mkdir()
        metadata_file = folder / "metadata.json"
        metadata_file.write_text("not valid json")

        result = parse_abs_metadata(folder)
        assert result is None

    def test_series_position_decimal(self, tmp_path: Path) -> None:
        """Test parsing decimal series positions (novellas)."""
        from shelfr.abs.rename import parse_abs_metadata

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

    def test_multi_series_entries(self, tmp_path: Path) -> None:
        """Test parsing metadata with multiple series entries.

        ABS can list a spin-off under both the parent franchise and its
        own sub-series (e.g. Mushoku Tensei Redundant Reincarnation is
        listed as Jobless Reincarnation #29 AND Redundant Reincarnation #1).
        All entries should be stored in ``all_series``.
        """
        from shelfr.abs.rename import parse_abs_metadata

        folder = tmp_path / "book_folder"
        folder.mkdir()
        metadata_file = folder / "metadata.json"
        metadata_file.write_text(
            json.dumps(
                {
                    "title": "Mushoku Tensei: Redundant Reincarnation, Vol. 1",
                    "authors": ["Rifujin na Magonote"],
                    "asin": "B0DNNS1S9Y",
                    "series": [
                        "Mushoku Tensei: Jobless Reincarnation #29",
                        "Mushoku Tensei: Redundant Reincarnation #1",
                    ],
                    "publishedYear": "2025",
                }
            )
        )

        result = parse_abs_metadata(folder)
        assert result is not None
        # Primary (series[0]) is Jobless Reincarnation #29
        assert result.series == "Mushoku Tensei: Jobless Reincarnation"
        assert result.series_position == "29"
        # But all_series has both entries
        assert len(result.all_series) == 2
        assert result.all_series[0] == ("Mushoku Tensei: Jobless Reincarnation", "29")
        assert result.all_series[1] == ("Mushoku Tensei: Redundant Reincarnation", "1")

    def test_position_for_series_picks_matching_entry(self) -> None:
        """position_for_series returns the position from the entry matching the resolved series."""
        from shelfr.abs.rename import AbsMetadata

        meta = AbsMetadata(
            title="Redundant Reincarnation Vol. 1",
            series="Mushoku Tensei: Jobless Reincarnation",
            series_position="29",
            all_series=[
                ("Mushoku Tensei: Jobless Reincarnation", "29"),
                ("Mushoku Tensei: Redundant Reincarnation", "1"),
            ],
        )

        # When resolved series matches the sub-series, get sub-series position
        assert meta.position_for_series("Mushoku Tensei - Redundant Reincarnation") == "1"
        # When resolved series matches the parent, get parent position
        assert meta.position_for_series("Mushoku Tensei - Jobless Reincarnation") == "29"

    def test_position_for_series_single_entry_fallback(self) -> None:
        """position_for_series falls back to series_position with a single entry."""
        from shelfr.abs.rename import AbsMetadata

        meta = AbsMetadata(
            series="Test Series",
            series_position="5",
            all_series=[("Test Series", "5")],
        )

        assert meta.position_for_series("Test Series") == "5"
        assert meta.position_for_series("Other Series") == "5"  # single entry fallback

    def test_position_for_series_no_resolved(self) -> None:
        """position_for_series returns series_position when resolved_series is None."""
        from shelfr.abs.rename import AbsMetadata

        meta = AbsMetadata(
            series="Test Series",
            series_position="3",
            all_series=[
                ("Test Series", "3"),
                ("Other Series", "10"),
            ],
        )

        assert meta.position_for_series(None) == "3"


class TestHasAudioFiles:
    """Tests for has_audio_files function."""

    def test_with_m4b(self, tmp_path: Path) -> None:
        """Test folder with .m4b file."""
        from shelfr.abs.rename import has_audio_files

        folder = tmp_path / "book"
        folder.mkdir()
        (folder / "audiobook.m4b").touch()

        assert has_audio_files(folder) is True

    def test_with_mp3(self, tmp_path: Path) -> None:
        """Test folder with .mp3 files."""
        from shelfr.abs.rename import has_audio_files

        folder = tmp_path / "book"
        folder.mkdir()
        (folder / "chapter01.mp3").touch()
        (folder / "chapter02.mp3").touch()

        assert has_audio_files(folder) is True

    def test_no_audio(self, tmp_path: Path) -> None:
        """Test folder without audio files."""
        from shelfr.abs.rename import has_audio_files

        folder = tmp_path / "book"
        folder.mkdir()
        (folder / "cover.jpg").touch()
        (folder / "metadata.json").touch()

        assert has_audio_files(folder) is False

    def test_empty_folder(self, tmp_path: Path) -> None:
        """Test empty folder."""
        from shelfr.abs.rename import has_audio_files

        folder = tmp_path / "book"
        folder.mkdir()

        assert has_audio_files(folder) is False


class TestDetectEditionFlags:
    """Tests for detect_edition_flags function."""

    def test_full_cast(self) -> None:
        """Test detecting Full-Cast edition."""
        from shelfr.abs.rename import detect_edition_flags

        flags = detect_edition_flags("Book Title (Full-Cast)")
        assert "Full-Cast" in flags

    def test_graphic_audio(self) -> None:
        """Test detecting Graphic Audio edition."""
        from shelfr.abs.rename import detect_edition_flags

        flags = detect_edition_flags("Book Title (Graphic Audio)")
        assert "Graphic Audio" in flags

    def test_publishers_pack(self) -> None:
        """Test detecting Publisher's Pack."""
        from shelfr.abs.rename import detect_edition_flags

        flags = detect_edition_flags("Series vol_01-03 (Publisher's Pack)")
        assert "Publisher's Pack" in flags

    def test_multiple_flags(self) -> None:
        """Test detecting multiple flags."""
        from shelfr.abs.rename import detect_edition_flags

        flags = detect_edition_flags("Title (Dolby Atmos) (Full-Cast)")
        assert "Dolby Atmos" in flags
        assert "Full-Cast" in flags

    def test_no_flags(self) -> None:
        """Test no flags returns empty list."""
        from shelfr.abs.rename import detect_edition_flags

        flags = detect_edition_flags("Just a Normal Title")
        assert flags == []

    def test_ait_lowercase(self) -> None:
        """Test detecting (ait) as AIT edition flag."""
        from shelfr.abs.rename import detect_edition_flags

        flags = detect_edition_flags("Dungeon Crawler Carl - vol_01 [2021] (ait) [Matt Dinniman]")
        assert flags == ["AIT"]

    def test_ait_uppercase(self) -> None:
        """Test detecting (AIT) as AIT edition flag."""
        from shelfr.abs.rename import detect_edition_flags

        flags = detect_edition_flags("Dungeon Crawler Carl - vol_01 [2021] (AIT) [Matt Dinniman]")
        assert flags == ["AIT"]


class TestDiscoverRenameCandidates:
    """Tests for discover_rename_candidates function."""

    def test_finds_leaf_folders(self, tmp_path: Path) -> None:
        """Test discovering leaf folders with audio."""
        from shelfr.abs.rename import discover_rename_candidates

        # Create structure: author/series/book
        book_folder = tmp_path / "Author" / "Series" / "Book vol_01"
        book_folder.mkdir(parents=True)
        (book_folder / "audiobook.m4b").touch()

        candidates = discover_rename_candidates(tmp_path)
        assert len(candidates) == 1
        assert candidates[0] == book_folder

    def test_skips_folders_without_audio(self, tmp_path: Path) -> None:
        """Test skips folders without audio files."""
        from shelfr.abs.rename import discover_rename_candidates

        folder = tmp_path / "NoAudio"
        folder.mkdir()
        (folder / "readme.txt").touch()

        candidates = discover_rename_candidates(tmp_path)
        assert len(candidates) == 0

    def test_multiple_books(self, tmp_path: Path) -> None:
        """Test discovering multiple book folders."""
        from shelfr.abs.rename import discover_rename_candidates

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
        from shelfr.abs.rename import RenameCandidate

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
        from shelfr.abs.rename import RenameCandidate

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
        from shelfr.abs.rename import RenameCandidate, compute_target_name

        # Without parsed data, should return error status
        candidate = RenameCandidate(
            source_path=Path("/a/Book"),
            current_name="Book",
        )

        result = compute_target_name(candidate)
        assert result.status == "error"


class TestParenAuthorExtraction:
    """Tests that the parser correctly extracts the parenthetical author
    from MAM-format folders.  The parenthetical name is ALWAYS the author
    (never the narrator) per the MAM naming schema.
    """

    def test_paren_author_used_for_series_folder(self, tmp_path: Path) -> None:
        """Parenthetical author extracted correctly for series folder."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import AbsMetadata, RenameCandidate, compute_target_name

        source_dir = tmp_path / "lib"
        source_dir.mkdir()
        series_dir = source_dir / "Mushoku Tensei - Jobless Reincarnation"
        series_dir.mkdir()
        folder = (
            "Mushoku Tensei - Jobless Reincarnation vol_01 "
            "(2023) (Rifujin na Magonote) {ASIN.B0CJWTXLPJ} [H2OKing]"
        )
        source = series_dir / folder
        source.mkdir()

        parsed = ParsedFolderName(
            author="Rifujin na Magonote",
            title="Jobless Reincarnation",
            series="Mushoku Tensei - Jobless Reincarnation",
            series_position="01",
            asin="B0CJWTXLPJ",
            year="2023",
            ripper_tag="H2OKing",
            is_standalone=False,
        )
        candidate = RenameCandidate(
            source_path=source,
            current_name=folder,
            parsed=parsed,
            abs_metadata=AbsMetadata(
                authors=["Rifujin na Magonote"],
                series="Mushoku Tensei: Jobless Reincarnation",
                series_position="1",
                year=2023,
                asin="B0CJWTXLPJ",
            ),
        )
        result = compute_target_name(candidate, source_dir=source_dir)
        assert result.components is not None
        assert result.components["author"] == "Rifujin na Magonote"

    def test_paren_author_without_abs_metadata(self, tmp_path: Path) -> None:
        """Parenthetical author works even without ABS metadata."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import RenameCandidate, compute_target_name

        source_dir = tmp_path / "lib"
        source_dir.mkdir()
        series_dir = source_dir / "Trapped in a Dating Sim"
        series_dir.mkdir()
        folder = (
            "Trapped in a Dating Sim - The World of Otome Games "
            "Is Tough for Mobs vol_01 (2024) (Yomu Mishima) {ASIN.B0DK27WWT8}"
        )
        source = series_dir / folder
        source.mkdir()

        parsed = ParsedFolderName(
            author="Yomu Mishima",
            title="The World of Otome Games Is Tough for Mobs",
            series="Trapped in a Dating Sim - The World of Otome Games Is Tough for Mobs",
            series_position="01",
            asin="B0DK27WWT8",
            year="2024",
            ripper_tag=None,
            is_standalone=False,
        )
        candidate = RenameCandidate(
            source_path=source,
            current_name=folder,
            parsed=parsed,
            abs_metadata=None,
        )
        result = compute_target_name(candidate, source_dir=source_dir)
        assert result.components is not None
        assert result.components["author"] == "Yomu Mishima"

    def test_paren_author_for_standalone_book(self, tmp_path: Path) -> None:
        """Parenthetical author extracted correctly for standalone book."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import AbsMetadata, RenameCandidate, compute_target_name

        source_dir = tmp_path / "lib"
        source_dir.mkdir()
        folder = "A Christmas Carol (2010) (Charles Dickens) {ASIN.B002ZEEDAW} [H2OKing]"
        source = source_dir / folder
        source.mkdir()

        parsed = ParsedFolderName(
            author="Charles Dickens",
            title="A Christmas Carol",
            series=None,
            series_position=None,
            asin="B002ZEEDAW",
            year="2010",
            ripper_tag="H2OKing",
            is_standalone=True,
        )
        candidate = RenameCandidate(
            source_path=source,
            current_name=folder,
            parsed=parsed,
            abs_metadata=AbsMetadata(
                authors=["Charles Dickens"],
                title="A Christmas Carol",
                year=2010,
                asin="B002ZEEDAW",
            ),
        )
        result = compute_target_name(candidate, source_dir=source_dir)
        assert result.components is not None
        assert result.components["author"] == "Charles Dickens"

    def test_paren_author_collides_with_series_uses_abs(self, tmp_path: Path) -> None:
        """If paren author matches series name, fall back to ABS author."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import AbsMetadata, RenameCandidate, compute_target_name

        source_dir = tmp_path / "lib"
        source_dir.mkdir()
        folder = "SeriesName vol_01 (2020) (SeriesName) {ASIN.B012345678}"
        source = source_dir / folder
        source.mkdir()

        parsed = ParsedFolderName(
            author="SeriesName",
            title="SeriesName",
            series="SeriesName",
            series_position="01",
            asin="B012345678",
            year="2020",
            ripper_tag=None,
            is_standalone=False,
        )
        candidate = RenameCandidate(
            source_path=source,
            current_name=folder,
            parsed=parsed,
            abs_metadata=AbsMetadata(
                authors=["Real Author"],
                series="SeriesName",
                series_position="1",
                year=2020,
                asin="B012345678",
            ),
        )
        result = compute_target_name(candidate, source_dir=source_dir)
        assert result.components is not None
        # Should use ABS author since parsed author collides with series
        assert result.components["author"] == "Real Author"


class TestRenameFolder:
    """Tests for rename_folder function."""

    def test_dry_run(self, tmp_path: Path) -> None:
        """Test dry run doesn't actually rename."""
        from shelfr.abs.rename import RenameCandidate, rename_folder

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
        from shelfr.abs.rename import RenameCandidate, rename_folder

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
        from shelfr.abs.rename import RenameCandidate, rename_folder

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
        from shelfr.abs.rename import RenameCandidate, rename_folder

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
        from shelfr.abs.rename import RenameResult

        result = RenameResult(
            source_path=Path("/a/Original"),
            target_path=Path("/a/Target"),
            status="success",
        )
        assert result.status == "success"
        assert result.error is None

    def test_error_result(self) -> None:
        """Test error result."""
        from shelfr.abs.rename import RenameResult

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
        from shelfr.abs.rename import RenameSummary

        summary = RenameSummary()
        assert summary.total_candidates == 0
        assert summary.renamed == 0
        assert summary.errors == 0

    def test_custom_values(self) -> None:
        """Test summary with custom values."""
        from shelfr.abs.rename import RenameSummary

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
        from shelfr.abs.rename import parse_candidate

        folder = tmp_path / "Brandon Sanderson - Mistborn vol_01 (2023) {ASIN.B001234567}"
        folder.mkdir()

        candidate = parse_candidate(folder)
        assert candidate.current_name == folder.name
        assert candidate.source_path == folder
        # Parsed should be set (may or may not extract data depending on parser)
        assert candidate.parsed is not None

    def test_detects_edition_flags(self, tmp_path: Path) -> None:
        """Test that edition flags are detected."""
        from shelfr.abs.rename import parse_candidate

        folder = tmp_path / "Title (Full-Cast) (Dolby Atmos)"
        folder.mkdir()

        candidate = parse_candidate(folder)
        assert "Full-Cast" in candidate.edition_flags
        assert "Dolby Atmos" in candidate.edition_flags


class TestRenameFilesInside:
    """Tests for _rename_files_inside helper."""

    def test_renames_media_files(self, tmp_path: Path) -> None:
        """Test that media files are renamed."""
        from shelfr.abs.rename import _rename_files_inside

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
        from shelfr.abs.rename import _rename_files_inside

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
        from shelfr.abs.rename import _rename_files_inside

        folder = tmp_path / "Book Name"
        folder.mkdir()
        (folder / "Book Name.m4b").touch()

        renamed = _rename_files_inside(folder, "Book Name")

        assert renamed == []
        assert (folder / "Book Name.m4b").exists()

    def test_multi_file_audiobook_gets_part_numbers(self, tmp_path: Path) -> None:
        """Test that multiple audio files get Part XX suffixes to prevent collisions."""
        from shelfr.abs.rename import _rename_files_inside

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
        from shelfr.abs.rename import _rename_files_inside

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
        from shelfr.abs.rename import RenameCandidate, rename_folder

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
        from shelfr.abs.rename import RenameCandidate, rename_folder

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
        from shelfr.abs.rename import (
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
        from shelfr.abs.rename import run_rename_pipeline

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
        _results, summary, candidates = run_rename_pipeline(
            source_dir=lib,
            dry_run=True,
        )

        assert summary.total_candidates == 1
        # Should be found and need renaming (name doesn't match target)
        assert len(candidates) == 1
        # The folder has ASIN from metadata, should be able to compute target

    def test_full_pipeline_actual_rename(self, tmp_path: Path) -> None:
        """Test actual rename operation."""
        from shelfr.abs.rename import run_rename_pipeline

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
        _results, summary, _candidates = run_rename_pipeline(
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
        from shelfr.abs.rename import run_rename_pipeline

        lib = tmp_path / "lib"
        lib.mkdir()

        # Book already in correct MAM format
        book = lib / "Good Book (2023) (Good Author) {ASIN.B0999999999}"
        book.mkdir()
        (book / "audio.m4b").touch()

        # Run pipeline
        _results, summary, _candidates = run_rename_pipeline(
            source_dir=lib,
            dry_run=True,
        )

        assert summary.total_candidates == 1
        # Should be marked as up_to_date or missing_asin (depends on metadata)
        # At least one of the skip counters should be positive
        assert summary.skipped_up_to_date + summary.skipped_missing_asin > 0


class TestPolicyLockedRules:
    """Coverage for locked sao_gold naming rules."""

    def test_arc_omitted_when_missing(self, tmp_path: Path) -> None:
        """Arc should remain empty when no reliable subtitle exists."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import (
            AbsMetadata,
            RenameCandidate,
            compute_target_name,
            resolve_rename_policy,
        )

        source_dir = tmp_path / "lib"
        source_dir.mkdir()
        source = source_dir / "Messy Folder"
        source.mkdir()
        (source / "audio.m4b").touch()

        parsed = ParsedFolderName(
            author="Reki Kawahara",
            title="Sword Art Online",
            series="Sword Art Online",
            series_position="1",
            asin="B012345678",
            year="2012",
            ripper_tag=None,
            is_standalone=False,
        )
        candidate = RenameCandidate(
            source_path=source,
            current_name=source.name,
            parsed=parsed,
            abs_metadata=AbsMetadata(
                title="Sword Art Online",
                subtitle=None,
                authors=["Reki Kawahara"],
                series="Sword Art Online",
                series_position="1",
                year=2012,
                asin="B012345678",
            ),
        )

        result = compute_target_name(
            candidate,
            source_dir=source_dir,
            policy=resolve_rename_policy(policy_profile="sao_gold"),
        )
        assert result.components["arc"] is None

    def test_preserves_h2oking_tag(self, tmp_path: Path) -> None:
        """sao_gold should preserve [H2OKing] when present."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import RenameCandidate, compute_target_name, resolve_rename_policy

        source_dir = tmp_path / "lib"
        source_dir.mkdir()
        source = source_dir / "Old"
        source.mkdir()

        parsed = ParsedFolderName(
            author="Author Name",
            title="Book Title",
            series=None,
            series_position=None,
            asin="B012345678",
            year="2024",
            ripper_tag="H2OKing",
            is_standalone=True,
        )
        candidate = RenameCandidate(source_path=source, current_name=source.name, parsed=parsed)

        result = compute_target_name(
            candidate,
            source_dir=source_dir,
            policy=resolve_rename_policy(policy_profile="sao_gold"),
        )
        assert result.components["ripper_tag"] == "H2OKing"
        assert result.target_name is not None
        assert "[H2OKing]" in result.target_name

    def test_drops_non_allowlisted_trailing_tag(self, tmp_path: Path) -> None:
        """sao_gold should drop non-allowlisted trailing tags."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import RenameCandidate, compute_target_name, resolve_rename_policy

        source_dir = tmp_path / "lib"
        source_dir.mkdir()
        source = source_dir / "Old"
        source.mkdir()

        parsed = ParsedFolderName(
            author="Author Name",
            title="Book Title",
            series=None,
            series_position=None,
            asin="B012345678",
            year="2024",
            ripper_tag="NotAllowedTag",
            is_standalone=True,
        )
        candidate = RenameCandidate(source_path=source, current_name=source.name, parsed=parsed)

        result = compute_target_name(
            candidate,
            source_dir=source_dir,
            policy=resolve_rename_policy(policy_profile="sao_gold"),
        )
        assert result.components["ripper_tag"] is None
        assert result.target_name is not None
        assert "[NotAllowedTag]" not in result.target_name

    def test_never_injects_tag_on_untagged_folder(self, tmp_path: Path) -> None:
        """CRITICAL: Folders without [H2OKing] must NEVER get the tag added.

        Rename organizes existing library folders. If you didn't rip it,
        the tag must not appear. Only the import pipeline adds tags.
        """
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import RenameCandidate, compute_target_name, resolve_rename_policy

        source_dir = tmp_path / "lib"
        source_dir.mkdir()
        source = source_dir / "Old"
        source.mkdir()

        parsed = ParsedFolderName(
            author="Reki Kawahara",
            title="Sword Art Online 1",
            series="Sword Art Online",
            series_position="1",
            asin="1975337182",
            year="2021",
            ripper_tag=None,  # No tag on source folder
            is_standalone=False,
        )
        candidate = RenameCandidate(source_path=source, current_name=source.name, parsed=parsed)

        result = compute_target_name(
            candidate,
            source_dir=source_dir,
            policy=resolve_rename_policy(policy_profile="sao_gold"),
        )
        # Tag must NOT be injected
        assert result.components["ripper_tag"] is None
        assert result.target_name is not None
        assert "[H2OKing]" not in result.target_name

    def test_never_injects_tag_even_with_import_ripper_tag_arg(self, tmp_path: Path) -> None:
        """Even if import_ripper_tag is passed, preserve_if_in_allowlist must not inject."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import RenameCandidate, compute_target_name, resolve_rename_policy

        source_dir = tmp_path / "lib"
        source_dir.mkdir()
        source = source_dir / "Old"
        source.mkdir()

        parsed = ParsedFolderName(
            author="Author Name",
            title="Some Book",
            series=None,
            series_position=None,
            asin="B012345678",
            year="2024",
            ripper_tag=None,  # No tag on source folder
            is_standalone=True,
        )
        candidate = RenameCandidate(source_path=source, current_name=source.name, parsed=parsed)

        # Even if someone passes import_ripper_tag, preserve_if_in_allowlist ignores it
        result = compute_target_name(
            candidate,
            import_ripper_tag="H2OKing",
            source_dir=source_dir,
            policy=resolve_rename_policy(policy_profile="sao_gold"),
        )
        assert result.components["ripper_tag"] is None
        assert result.target_name is not None
        assert "[H2OKing]" not in result.target_name

    def test_default_policy_never_injects_tag(self, tmp_path: Path) -> None:
        """Default policy (no profile) must also never inject tags."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import RenameCandidate, compute_target_name, resolve_rename_policy

        source_dir = tmp_path / "lib"
        source_dir.mkdir()
        source = source_dir / "Old"
        source.mkdir()

        parsed = ParsedFolderName(
            author="Author Name",
            title="Book Title",
            series=None,
            series_position=None,
            asin="B012345678",
            year="2024",
            ripper_tag=None,  # No tag
            is_standalone=True,
        )
        candidate = RenameCandidate(source_path=source, current_name=source.name, parsed=parsed)

        result = compute_target_name(
            candidate,
            source_dir=source_dir,
            policy=resolve_rename_policy(),  # Default policy
        )
        assert result.components["ripper_tag"] is None
        assert result.target_name is not None
        assert "[H2OKing]" not in result.target_name

    def test_preserves_numeric_asin_verbatim(self, tmp_path: Path) -> None:
        """Numeric ASIN values should be preserved exactly when trusted."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import RenameCandidate, compute_target_name, resolve_rename_policy

        source_dir = tmp_path / "lib"
        source_dir.mkdir()
        source = source_dir / "Old"
        source.mkdir()

        parsed = ParsedFolderName(
            author="Author Name",
            title="Book Title",
            series=None,
            series_position=None,
            asin="1234567890",
            year="2024",
            ripper_tag=None,
            is_standalone=True,
        )
        candidate = RenameCandidate(source_path=source, current_name=source.name, parsed=parsed)

        result = compute_target_name(
            candidate,
            source_dir=source_dir,
            policy=resolve_rename_policy(policy_profile="sao_gold"),
        )
        assert result.target_name is not None
        assert "{ASIN.1234567890}" in result.target_name


class TestHierarchyAndDiscovery:
    """Hierarchy and discovery behavior for full-library organization."""

    def test_series_target_uses_author_series_book(self, tmp_path: Path) -> None:
        """Series targets should be nested as Author/Series/Book.

        Uses abs_first policy so ABS series name is used for hierarchy
        verification (preserve_existing would lock to "OldSeries").
        """
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import (
            RenameCandidate,
            RenamePolicy,
            compute_target_name,
        )

        source_dir = tmp_path / "lib"
        source_dir.mkdir()
        # Place item at depth 3 so source_dir is recognized as library root
        source = source_dir / "OldAuthor" / "OldSeries" / "Incoming Name"
        source.mkdir(parents=True)

        parsed = ParsedFolderName(
            author="Reki Kawahara",
            title="Aincrad",
            series="Sword Art Online",
            series_position=None,
            asin="B012345678",
            year="2012",
            ripper_tag=None,
            is_standalone=False,
        )
        candidate = RenameCandidate(source_path=source, current_name=source.name, parsed=parsed)

        result = compute_target_name(
            candidate,
            source_dir=source_dir,
            policy=RenamePolicy(
                profile="sao_gold",
                hierarchy_mode="author_series_book",
                series_source="abs_first",
            ),
        )
        assert result.target_path is not None
        assert result.target_path.parent == source_dir / "Reki Kawahara" / "Sword Art Online"

    def test_standalone_target_uses_author_book(self, tmp_path: Path) -> None:
        """Standalone targets should be nested as Author/Book."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import RenameCandidate, compute_target_name, resolve_rename_policy

        source_dir = tmp_path / "lib"
        source_dir.mkdir()
        # Place item at depth 2 so source_dir is recognized as library root
        source = source_dir / "OldAuthor" / "Incoming Name"
        source.mkdir(parents=True)

        parsed = ParsedFolderName(
            author="Andy Weir",
            title="Project Hail Mary",
            series=None,
            series_position=None,
            asin="B08G9PRS1K",
            year="2021",
            ripper_tag=None,
            is_standalone=True,
        )
        candidate = RenameCandidate(source_path=source, current_name=source.name, parsed=parsed)

        result = compute_target_name(
            candidate,
            source_dir=source_dir,
            policy=resolve_rename_policy(policy_profile="sao_gold"),
        )
        assert result.target_path is not None
        assert result.target_path.parent == source_dir / "Andy Weir"

    def test_author_dir_scope_does_not_double_author(self, tmp_path: Path) -> None:
        """When --source is an author dir, hierarchy must NOT insert an extra author level."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import RenameCandidate, compute_target_name, resolve_rename_policy

        # source_dir IS the author directory (like --source /audiobooks/Reki Kawahara)
        source_dir = tmp_path / "Reki Kawahara"
        source_dir.mkdir()
        # Items are at depth 2 (Series/Book) under the author dir
        source = source_dir / "Sword Art Online" / "Old Folder Name"
        source.mkdir(parents=True)

        parsed = ParsedFolderName(
            author="Reki Kawahara",
            title="Aincrad",
            series="Sword Art Online",
            series_position="1",
            asin="B012345678",
            year="2012",
            ripper_tag=None,
            is_standalone=False,
        )
        candidate = RenameCandidate(source_path=source, current_name=source.name, parsed=parsed)

        result = compute_target_name(
            candidate,
            source_dir=source_dir,
            policy=resolve_rename_policy(policy_profile="sao_gold"),
        )
        assert result.target_path is not None
        # Should be AuthorDir/Series/Book, NOT AuthorDir/Author/Series/Book
        assert result.target_path.parent == source_dir / "Sword Art Online"
        # The target should NOT have a doubled author path
        parts = result.target_path.relative_to(source_dir).parts
        assert parts[0] == "Sword Art Online"  # series first, no extra author

    def test_flat_series_book_stays_flat_under_preserve_existing(self, tmp_path: Path) -> None:
        """A series book sitting flat under the author dir stays flat under preserve_existing.

        Under preserve_existing policy, books without an existing series
        subfolder are not promoted into one — they stay where the user
        put them.
        """
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import RenameCandidate, compute_target_name, resolve_rename_policy

        # source_dir IS the author directory
        source_dir = tmp_path / "J.K. Rowling"
        source_dir.mkdir()
        # Book sits FLAT under author dir (no series subdir yet) — depth 1
        source = source_dir / "Fantastic Beasts [2017] [J.K. Rowling] [B01N4S7VVP]"
        source.mkdir()

        parsed = ParsedFolderName(
            author="J.K. Rowling",
            title="Fantastic Beasts and Where to Find Them",
            series="Hogwarts Library Books",
            series_position=None,
            asin="B01N4S7VVP",
            year="2017",
            ripper_tag=None,
            is_standalone=False,
        )
        candidate = RenameCandidate(source_path=source, current_name=source.name, parsed=parsed)

        result = compute_target_name(
            candidate,
            source_dir=source_dir,
            policy=resolve_rename_policy(policy_profile="sao_gold"),
        )
        assert result.target_path is not None
        # preserve_existing: no existing series dir → stays flat under author
        assert result.target_path.parent == source_dir
        assert "Hogwarts Library Books" not in str(result.target_path)

    def test_discovery_collapses_deep_episode_subfolders(self, tmp_path: Path) -> None:
        """Metadata root should win over nested E01/E02 audio subfolders."""
        from shelfr.abs.rename import discover_rename_candidates

        book_root = tmp_path / "Author" / "Series" / "Book Folder"
        (book_root / "E01").mkdir(parents=True)
        (book_root / "E02").mkdir(parents=True)
        (book_root / "metadata.json").write_text("{}")
        (book_root / "E01" / "part01.mp3").touch()
        (book_root / "E02" / "part02.mp3").touch()

        candidates = discover_rename_candidates(tmp_path)
        assert candidates == [book_root]

    def test_discovery_collapses_episode_siblings_without_metadata(self, tmp_path: Path) -> None:
        """AIT-style: episode subfolders without metadata.json should collapse to parent."""
        from shelfr.abs.rename import discover_rename_candidates

        ait_root = (
            tmp_path / "Author" / "Series" / "Series - vol_02 - Subtitle (2026) (ait) (Author)"
        )
        (ait_root / "E01 Episode One").mkdir(parents=True)
        (ait_root / "E02 Episode Two").mkdir(parents=True)
        (ait_root / "E03 Episode Three").mkdir(parents=True)
        # Audio lives inside episodes, no metadata.json at ait_root
        (ait_root / "E01 Episode One" / "episode01.m4b").touch()
        (ait_root / "E02 Episode Two" / "episode02.m4b").touch()
        (ait_root / "E03 Episode Three" / "episode03.m4b").touch()

        candidates = discover_rename_candidates(tmp_path)
        assert candidates == [ait_root]

    def test_discovery_does_not_collapse_non_episode_siblings(self, tmp_path: Path) -> None:
        """Non-episode sibling folders should remain separate candidates."""
        from shelfr.abs.rename import discover_rename_candidates

        parent = tmp_path / "Author"
        book_a = parent / "Book One"
        book_b = parent / "Book Two"
        book_a.mkdir(parents=True)
        book_b.mkdir(parents=True)
        (book_a / "audio.m4b").touch()
        (book_b / "audio.m4b").touch()

        candidates = discover_rename_candidates(tmp_path)
        assert sorted(candidates) == sorted([book_a, book_b])

    def test_discovery_episode_and_normal_sibling_mixed(self, tmp_path: Path) -> None:
        """Mixed episode + normal siblings: collapse if ≥50% are episodes."""
        from shelfr.abs.rename import discover_rename_candidates

        ait_root = tmp_path / "Author" / "Series" / "AIT Release"
        (ait_root / "E01 Intro").mkdir(parents=True)
        (ait_root / "E02 Main").mkdir(parents=True)
        (ait_root / "Bonus Content").mkdir(parents=True)
        (ait_root / "E01 Intro" / "e01.m4b").touch()
        (ait_root / "E02 Main" / "e02.m4b").touch()
        (ait_root / "Bonus Content" / "bonus.m4b").touch()

        candidates = discover_rename_candidates(tmp_path)
        # 2/3 are episodes ≥ 50%, so collapse to parent
        assert candidates == [ait_root]

    def test_discovery_collapses_nested_episode_dir(self, tmp_path: Path) -> None:
        """Nested E03/E03/audio.m4b should also collapse to the AIT root."""
        from shelfr.abs.rename import discover_rename_candidates

        ait_root = tmp_path / "Author" / "Series" / "AIT Release"
        (ait_root / "E01").mkdir(parents=True)
        (ait_root / "E02").mkdir(parents=True)
        # E03 has a doubled nested directory (filesystem hygiene issue)
        (ait_root / "E03 Extra" / "E03 Extra").mkdir(parents=True)

        (ait_root / "E01" / "e01.m4b").touch()
        (ait_root / "E02" / "e02.m4b").touch()
        (ait_root / "E03 Extra" / "E03 Extra" / "e03.m4b").touch()

        candidates = discover_rename_candidates(tmp_path)
        # All three episodes should collapse to the AIT root
        assert candidates == [ait_root]


class TestPlanApplyTransactions:
    """Plan/apply reliability checks: preflight drift/conflicts + rollback."""

    def test_apply_refuses_stale_manifest_on_fingerprint_drift(self, tmp_path: Path) -> None:
        """Apply should fail preflight when source fingerprint changed."""
        from shelfr.abs.rename import RenamePolicy, _compute_path_fingerprint, apply_rename_plan

        source = tmp_path / "Book A"
        target = tmp_path / "Book B"
        source.mkdir()
        (source / "audio.m4b").write_text("v1")
        fingerprint = _compute_path_fingerprint(source)
        assert fingerprint is not None

        # Drift source fingerprint after plan capture.
        (source / "audio.m4b").write_text("version-two-with-size-change")

        plan_payload = {
            "version": "RenamePlanV1",
            "generated_at": "2026-02-15T00:00:00+00:00",
            "source_dir": str(tmp_path),
            "policy": RenamePolicy(
                profile="sao_gold",
                transaction_backup_root=tmp_path / "backups",
            ).as_dict(),
            "summary": {},
            "conflicts": {},
            "items": [
                {
                    "source_path": str(source),
                    "target_path": str(target),
                    "status": "needs_rename",
                    "risk_flags": [],
                    "reasons": ["canonicalization_required"],
                    "fingerprint": fingerprint,
                    "components": {},
                }
            ],
        }
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(plan_payload))

        report = apply_rename_plan(plan_path)
        assert report["summary"]["failed"] == 1
        assert report["results"][0]["error"] == "fingerprint_mismatch"
        assert source.exists()
        assert not target.exists()

    def test_conflict_preflight_leaves_filesystem_unchanged(self, tmp_path: Path) -> None:
        """Existing target conflict should stop apply before any move."""
        from shelfr.abs.rename import RenamePolicy, _compute_path_fingerprint, apply_rename_plan

        source = tmp_path / "Source"
        target = tmp_path / "Target"
        source.mkdir()
        target.mkdir()
        (source / "audio.m4b").touch()
        (target / "audio.m4b").touch()
        fingerprint = _compute_path_fingerprint(source)
        assert fingerprint is not None

        plan_payload = {
            "version": "RenamePlanV1",
            "generated_at": "2026-02-15T00:00:00+00:00",
            "source_dir": str(tmp_path),
            "policy": RenamePolicy(
                profile="sao_gold",
                transaction_backup_root=tmp_path / "backups",
            ).as_dict(),
            "summary": {},
            "conflicts": {},
            "items": [
                {
                    "source_path": str(source),
                    "target_path": str(target),
                    "status": "needs_rename",
                    "risk_flags": [],
                    "reasons": ["canonicalization_required"],
                    "fingerprint": fingerprint,
                    "components": {},
                }
            ],
        }
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(plan_payload))

        report = apply_rename_plan(plan_path)
        assert report["summary"]["failed"] == 1
        assert report["results"][0]["error"] == "target_conflict"
        assert source.exists()
        assert target.exists()

    def test_move_failure_rolls_back_source(self, tmp_path: Path, monkeypatch) -> None:
        """Mid-transaction failure should rollback source folder location."""
        from shelfr.abs import rename as rename_mod
        from shelfr.abs.rename import RenamePolicy, _compute_path_fingerprint, apply_rename_plan

        source = tmp_path / "Source"
        target = tmp_path / "Target"
        source.mkdir()
        (source / "audio.m4b").touch()
        fingerprint = _compute_path_fingerprint(source)
        assert fingerprint is not None

        plan_payload = {
            "version": "RenamePlanV1",
            "generated_at": "2026-02-15T00:00:00+00:00",
            "source_dir": str(tmp_path),
            "policy": RenamePolicy(
                profile="sao_gold",
                transaction_backup_root=tmp_path / "backups",
            ).as_dict(),
            "summary": {},
            "conflicts": {},
            "items": [
                {
                    "source_path": str(source),
                    "target_path": str(target),
                    "status": "needs_rename",
                    "risk_flags": [],
                    "reasons": ["canonicalization_required"],
                    "fingerprint": fingerprint,
                    "components": {},
                }
            ],
        }
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(plan_payload))

        def fail_after_move(_target_path: Path, _new_stem: str) -> list[str]:
            raise OSError("simulated rename failure")

        monkeypatch.setattr(rename_mod, "_rename_files_inside", fail_after_move)

        report = apply_rename_plan(plan_path)
        assert report["summary"]["failed"] == 1
        assert report["results"][0]["rollback_ok"] is True
        assert source.exists()
        assert not target.exists()


class TestResolvePolicyWithConfig:
    """Verify resolve_rename_policy doesn't let config defaults clobber profiles."""

    def test_sao_gold_not_clobbered_by_config_schema_defaults(self) -> None:
        """When sao_gold is requested and config has only schema defaults,
        the profile's preserve_if_in_allowlist must win over schema's import_override."""
        from shelfr.abs.rename import resolve_rename_policy
        from shelfr.schemas.config import AudiobookshelfRenameSchema

        # Simulate config_policy with all schema defaults (user didn't set anything)
        config_policy = AudiobookshelfRenameSchema()

        policy = resolve_rename_policy(
            policy_profile="sao_gold",
            config_policy=config_policy,
        )
        assert policy.ripper_tag_policy == "preserve_if_in_allowlist"
        assert "H2OKing" in policy.allowed_ripper_tags
        assert policy.non_allowlisted_tag_action == "drop"

    def test_explicit_config_override_wins_over_profile(self) -> None:
        """When user explicitly sets a non-default value in config, it should win."""
        from shelfr.abs.rename import resolve_rename_policy
        from shelfr.schemas.config import AudiobookshelfRenameSchema

        config_policy = AudiobookshelfRenameSchema(ripper_tag_policy="strip_all")

        policy = resolve_rename_policy(
            policy_profile="sao_gold",
            config_policy=config_policy,
        )
        # User explicitly set strip_all, which differs from schema default
        assert policy.ripper_tag_policy == "strip_all"

    def test_default_profile_uses_safe_defaults(self) -> None:
        """Default profile (no profile specified) should never inject tags."""
        from shelfr.abs.rename import resolve_rename_policy

        policy = resolve_rename_policy()
        assert policy.ripper_tag_policy == "preserve_if_in_allowlist"
        assert policy.non_allowlisted_tag_action == "drop"


class TestConformance:
    """Conformance scoring for locked SAO policy."""

    def test_sao_like_target_conforms(self, tmp_path: Path) -> None:
        """A SAO-like candidate should pass token and hierarchy checks."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import (
            AbsMetadata,
            RenameCandidate,
            compute_target_name,
            resolve_rename_policy,
        )

        source_dir = tmp_path / "lib"
        source_dir.mkdir()
        # Place item at depth 3 so source_dir is recognized as library root
        source = source_dir / "OldAuthor" / "OldSeries" / "Random Old Name"
        source.mkdir(parents=True)

        parsed = ParsedFolderName(
            author="Reki Kawahara",
            title="Aincrad",
            series="Sword Art Online",
            series_position="1",
            asin="B012345678",
            year="2012",
            ripper_tag="H2OKing",
            is_standalone=False,
        )
        candidate = RenameCandidate(
            source_path=source,
            current_name=source.name,
            parsed=parsed,
            abs_metadata=AbsMetadata(
                title="Aincrad",
                subtitle=None,
                authors=["Reki Kawahara"],
                series="Sword Art Online",
                series_position="1",
                year=2012,
                asin="B012345678",
            ),
        )

        result = compute_target_name(
            candidate,
            source_dir=source_dir,
            policy=resolve_rename_policy(policy_profile="sao_gold"),
        )
        conformance = result.components["conformance"]
        assert conformance["checks"]["token_order"] is True
        assert conformance["checks"]["asin_placement"] is True
        assert conformance["checks"]["tag_policy"] is True
        assert conformance["checks"]["hierarchy"] is True


# =============================================================================
# Series Source / Preserve-Existing Tests
# =============================================================================


class TestDetectSeriesRoot:
    """Tests for _detect_series_root()."""

    def test_depth_3_returns_series_dir(self) -> None:
        """At depth 3 (Author/Series/Book), returns the series dir."""
        from shelfr.abs.rename import _detect_series_root

        source_dir = Path("/lib")
        source_path = Path("/lib/J.K. Rowling/Harry Potter/Book One")
        assert _detect_series_root(source_path, source_dir) == "Harry Potter"

    def test_depth_2_returns_parent_as_series(self) -> None:
        """At depth 2 (Series/Book under author dir), returns the series dir."""
        from shelfr.abs.rename import _detect_series_root

        source_dir = Path("/lib/Author")
        source_path = Path("/lib/Author/Harry Potter/BookFolder")
        assert _detect_series_root(source_path, source_dir) == "Harry Potter"

    def test_depth_2_library_root_returns_author(self) -> None:
        """At depth 2 from library root (Author/Book), the detected 'root'
        is the author dir.  _resolve_series guards against using this
        erroneously for standalone books."""
        from shelfr.abs.rename import _detect_series_root

        source_dir = Path("/lib")
        source_path = Path("/lib/Author/BookFolder")
        # Raw detection returns the parent — caller (_resolve_series) must
        # validate this against metadata before trusting it.
        assert _detect_series_root(source_path, source_dir) == "Author"

    def test_depth_1_returns_none(self) -> None:
        """At depth 1 (Book only), no series root exists."""
        from shelfr.abs.rename import _detect_series_root

        source_dir = Path("/lib/Author")
        source_path = Path("/lib/Author/BookFolder")
        assert _detect_series_root(source_path, source_dir) is None

    def test_none_source_dir(self) -> None:
        """Returns None when source_dir is None."""
        from shelfr.abs.rename import _detect_series_root

        assert _detect_series_root(Path("/a/b/c"), None) is None


class TestResolveSeriesPreserveExisting:
    """Tests for _resolve_series() with preserve_existing policy."""

    def _make_policy(self, series_source: str = "preserve_existing") -> object:
        from shelfr.abs.rename import RenamePolicy

        return RenamePolicy(series_source=series_source)

    def test_preserve_existing_locks_to_parent_folder(self) -> None:
        """When book is in Author/Harry Potter/Book, series stays 'Harry Potter'
        even when ABS says 'Wizarding World Collection'."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import AbsMetadata, _resolve_series

        source_dir = Path("/lib")
        source_path = Path("/lib/J.K. Rowling/Harry Potter/Book One")

        parsed = ParsedFolderName(
            author="J.K. Rowling",
            title="Book One",
            series="Harry Potter",
            series_position="1",
            asin="B0000HP001",
            year="1997",
            ripper_tag=None,
            is_standalone=False,
        )
        abs_meta = AbsMetadata(
            title="Harry Potter and the Philosopher's Stone",
            subtitle=None,
            authors=["J.K. Rowling"],
            series="Wizarding World Collection",  # ABS disagrees!
            series_position="1",
            year=1997,
            asin="B0000HP001",
        )
        series, changed = _resolve_series(
            parsed=parsed,
            abs_meta=abs_meta,
            source_path=source_path,
            source_dir=source_dir,
            policy=self._make_policy("preserve_existing"),
        )
        assert series == "Harry Potter"
        assert changed is True  # ABS wanted to move it

    def test_preserve_existing_no_root_falls_through(self) -> None:
        """When book is at depth 1 (no parent above it), preserve_existing keeps it flat."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import AbsMetadata, _resolve_series

        source_dir = Path("/lib/Author")
        source_path = Path("/lib/Author/BookFolder")

        parsed = ParsedFolderName(
            author="Author",
            title="Book",
            series="Parsed Series",
            series_position="1",
            asin="B000000001",
            year="2020",
            ripper_tag=None,
            is_standalone=False,
        )
        abs_meta = AbsMetadata(
            title="Book",
            subtitle=None,
            authors=["Author"],
            series="ABS Series",
            series_position="1",
            year=2020,
            asin="B000000001",
        )
        series, changed = _resolve_series(
            parsed=parsed,
            abs_meta=abs_meta,
            source_path=source_path,
            source_dir=source_dir,
            policy=self._make_policy("preserve_existing"),
        )
        # preserve_existing: no existing root → stay flat (None)
        assert series is None
        assert changed is False

    def test_abs_first_uses_abs_over_existing_root(self) -> None:
        """abs_first policy ignores existing folder structure."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import AbsMetadata, _resolve_series

        source_dir = Path("/lib")
        source_path = Path("/lib/Author/Harry Potter/Book One")

        parsed = ParsedFolderName(
            author="Author",
            title="Book One",
            series="Harry Potter",
            series_position="1",
            asin="B000000001",
            year="2020",
            ripper_tag=None,
            is_standalone=False,
        )
        abs_meta = AbsMetadata(
            title="Book One",
            subtitle=None,
            authors=["Author"],
            series="Wizarding World Collection",
            series_position="1",
            year=2020,
            asin="B000000001",
        )
        series, changed = _resolve_series(
            parsed=parsed,
            abs_meta=abs_meta,
            source_path=source_path,
            source_dir=source_dir,
            policy=self._make_policy("abs_first"),
        )
        assert series == "Wizarding World Collection"
        assert changed is True  # different from existing root

    def test_folder_first_prefers_parsed_over_abs(self) -> None:
        """folder_first policy uses parsed series before ABS."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import AbsMetadata, _resolve_series

        source_dir = Path("/lib")
        source_path = Path("/lib/Author/BookFolder")

        parsed = ParsedFolderName(
            author="Author",
            title="Book",
            series="Parsed Series",
            series_position="1",
            asin="B000000001",
            year="2020",
            ripper_tag=None,
            is_standalone=False,
        )
        abs_meta = AbsMetadata(
            title="Book",
            subtitle=None,
            authors=["Author"],
            series="ABS Series",
            series_position="1",
            year=2020,
            asin="B000000001",
        )
        series, _changed = _resolve_series(
            parsed=parsed,
            abs_meta=abs_meta,
            source_path=source_path,
            source_dir=source_dir,
            policy=self._make_policy("folder_first"),
        )
        assert series == "Parsed Series"

    def test_standalone_at_depth2_ignores_author_as_root(self) -> None:
        """A standalone book at library_root/Author/Book must NOT treat
        the author directory as a series root."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import AbsMetadata, _resolve_series

        source_dir = Path("/lib")
        source_path = Path("/lib/Author/StandaloneBook")

        parsed = ParsedFolderName(
            author="Author",
            title="Standalone Book",
            series=None,
            series_position=None,
            asin="B000000001",
            year="2020",
            ripper_tag=None,
            is_standalone=True,
        )
        abs_meta = AbsMetadata(
            title="Standalone Book",
            subtitle=None,
            authors=["Author"],
            series=None,
            series_position=None,
            year=2020,
            asin="B000000001",
        )
        series, changed = _resolve_series(
            parsed=parsed,
            abs_meta=abs_meta,
            source_path=source_path,
            source_dir=source_dir,
            policy=self._make_policy("preserve_existing"),
        )
        # Must be None — "Author" is not a series
        assert series is None
        assert changed is False

    def test_article_consolidation_uses_abs_name(self) -> None:
        """When existing_root='The Rising of the Shield Hero' and ABS says
        'Rising of the Shield Hero', preserve_existing keeps the folder name."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import AbsMetadata, _resolve_series

        source_dir = Path("/lib")
        source_path = Path("/lib/Aneko Yusagi/The Rising of the Shield Hero/vol_05")

        parsed = ParsedFolderName(
            author="Aneko Yusagi",
            title="vol_05",
            series="The Rising of the Shield Hero",
            series_position="5",
            asin="B000SHIELD5",
            year="2019",
            ripper_tag=None,
            is_standalone=False,
        )
        abs_meta = AbsMetadata(
            title="The Rising of the Shield Hero Volume 05",
            subtitle=None,
            authors=["Aneko Yusagi"],
            series="Rising of the Shield Hero",  # No "The"
            series_position="5",
            year=2019,
            asin="B000SHIELD5",
        )
        series, changed = _resolve_series(
            parsed=parsed,
            abs_meta=abs_meta,
            source_path=source_path,
            source_dir=source_dir,
            policy=self._make_policy("preserve_existing"),
        )
        # preserve_existing keeps the existing folder name
        assert series == "The Rising of the Shield Hero"
        # Not flagged as a risky move — just article normalisation
        assert changed is False

    def test_article_consolidation_reverse_direction(self) -> None:
        """ABS has 'The' but folder doesn't — preserve_existing keeps folder name."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import AbsMetadata, _resolve_series

        source_dir = Path("/lib")
        source_path = Path("/lib/Author/Rising of the Shield Hero/vol_01")

        parsed = ParsedFolderName(
            author="Author",
            title="vol_01",
            series="Rising of the Shield Hero",
            series_position="1",
            asin="B000SHIELD1",
            year="2018",
            ripper_tag=None,
            is_standalone=False,
        )
        abs_meta = AbsMetadata(
            title="The Rising of the Shield Hero Volume 01",
            subtitle=None,
            authors=["Author"],
            series="The Rising of the Shield Hero",  # ABS has "The"
            series_position="1",
            year=2018,
            asin="B000SHIELD1",
        )
        series, changed = _resolve_series(
            parsed=parsed,
            abs_meta=abs_meta,
            source_path=source_path,
            source_dir=source_dir,
            policy=self._make_policy("preserve_existing"),
        )
        # preserve_existing keeps the existing folder name
        assert series == "Rising of the Shield Hero"
        assert changed is False

    def test_no_article_consolidation_when_genuinely_different(self) -> None:
        """Series names differing by more than an article stay locked."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import AbsMetadata, _resolve_series

        source_dir = Path("/lib")
        source_path = Path("/lib/Author/Harry Potter/vol_01")

        parsed = ParsedFolderName(
            author="Author",
            title="vol_01",
            series="Harry Potter",
            series_position="1",
            asin="B0000HP001",
            year="1997",
            ripper_tag=None,
            is_standalone=False,
        )
        abs_meta = AbsMetadata(
            title="Philosopher's Stone",
            subtitle=None,
            authors=["Author"],
            series="Wizarding World Collection",  # Genuinely different
            series_position="1",
            year=1997,
            asin="B0000HP001",
        )
        series, changed = _resolve_series(
            parsed=parsed,
            abs_meta=abs_meta,
            source_path=source_path,
            source_dir=source_dir,
            policy=self._make_policy("preserve_existing"),
        )
        # Must lock to existing folder, NOT adopt ABS
        assert series == "Harry Potter"
        assert changed is True  # flagged as ABS disagreement

    def test_article_consolidation_only_in_preserve_existing(self) -> None:
        """abs_first policy doesn't special-case articles — normal behavior."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import AbsMetadata, _resolve_series

        source_dir = Path("/lib")
        source_path = Path("/lib/Author/The Rising of the Shield Hero/vol_05")

        parsed = ParsedFolderName(
            author="Author",
            title="vol_05",
            series="The Rising of the Shield Hero",
            series_position="5",
            asin="B000SHIELD5",
            year="2019",
            ripper_tag=None,
            is_standalone=False,
        )
        abs_meta = AbsMetadata(
            title="Volume 05",
            subtitle=None,
            authors=["Author"],
            series="Rising of the Shield Hero",
            series_position="5",
            year=2019,
            asin="B000SHIELD5",
        )
        series, changed = _resolve_series(
            parsed=parsed,
            abs_meta=abs_meta,
            source_path=source_path,
            source_dir=source_dir,
            policy=self._make_policy("abs_first"),
        )
        # abs_first always uses ABS, no special article logic
        assert series == "Rising of the Shield Hero"
        assert changed is True  # it IS different from existing root

    def test_article_a_prefix_consolidation(self) -> None:
        """Consolidation works with 'A' article prefix."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import AbsMetadata, _resolve_series

        source_dir = Path("/lib")
        source_path = Path("/lib/Author/A Court of Thorns and Roses/vol_01")

        parsed = ParsedFolderName(
            author="Author",
            title="vol_01",
            series="A Court of Thorns and Roses",
            series_position="1",
            asin="B000ACOTAR1",
            year="2020",
            ripper_tag=None,
            is_standalone=False,
        )
        abs_meta = AbsMetadata(
            title="A Court of Thorns and Roses",
            subtitle=None,
            authors=["Author"],
            series="Court of Thorns and Roses",  # No "A"
            series_position="1",
            year=2020,
            asin="B000ACOTAR1",
        )
        series, changed = _resolve_series(
            parsed=parsed,
            abs_meta=abs_meta,
            source_path=source_path,
            source_dir=source_dir,
            policy=self._make_policy("preserve_existing"),
        )
        # preserve_existing keeps the existing folder name
        assert series == "A Court of Thorns and Roses"
        assert changed is False


class TestSeriesSourceIntegration:
    """End-to-end tests: compute_target_name with series_source policies."""

    def test_hp_preserve_existing_keeps_series_root(self, tmp_path: Path) -> None:
        """Harry Potter stays in 'Harry Potter/' even when ABS metadata
        reports 'Wizarding World Collection' as seriesPrimary."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import (
            AbsMetadata,
            RenameCandidate,
            RenamePolicy,
            compute_target_name,
        )

        # Setup: Author/Harry Potter/BookFolder
        source_dir = tmp_path / "lib"
        hp_dir = source_dir / "J.K. Rowling" / "Harry Potter"
        hp_dir.mkdir(parents=True)
        book = (
            hp_dir / "HP vol_01 Philosophers Stone (1997) (J.K. Rowling)"
            " {ASIN.B0000HP001} [H2OKing]"
        )
        book.mkdir()
        (book / "audio.m4b").touch()

        parsed = ParsedFolderName(
            author="J.K. Rowling",
            title="Philosophers Stone",
            series="Harry Potter",
            series_position="1",
            asin="B0000HP001",
            year="1997",
            ripper_tag="H2OKing",
            is_standalone=False,
        )
        abs_meta = AbsMetadata(
            title="Harry Potter and the Philosopher's Stone",
            subtitle=None,
            authors=["J.K. Rowling"],
            series="Wizarding World Collection",  # ABS disagrees!
            series_position="1",
            year=1997,
            asin="B0000HP001",
        )
        candidate = RenameCandidate(
            source_path=book,
            current_name=book.name,
            parsed=parsed,
            abs_metadata=abs_meta,
        )

        policy = RenamePolicy(
            hierarchy_mode="author_series_book",
            series_source="preserve_existing",
        )
        result = compute_target_name(
            candidate,
            source_dir=source_dir,
            policy=policy,
        )

        # Series must stay "Harry Potter", NOT "Wizarding World Collection"
        assert result.components["series"] == "Harry Potter"
        assert result.target_path is not None
        assert "Harry Potter" in str(result.target_path)
        assert "Wizarding World" not in str(result.target_path)
        # Should flag the series root change risk
        assert result.components.get("series_root_changed") is True

    def test_abs_first_would_change_series_root(self, tmp_path: Path) -> None:
        """abs_first policy DOES move books to ABS-reported series."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import (
            AbsMetadata,
            RenameCandidate,
            RenamePolicy,
            compute_target_name,
        )

        source_dir = tmp_path / "lib"
        hp_dir = source_dir / "J.K. Rowling" / "Harry Potter"
        hp_dir.mkdir(parents=True)
        book = hp_dir / "OldFolder"
        book.mkdir()
        (book / "audio.m4b").touch()

        parsed = ParsedFolderName(
            author="J.K. Rowling",
            title="Philosophers Stone",
            series="Harry Potter",
            series_position="1",
            asin="B0000HP001",
            year="1997",
            ripper_tag=None,
            is_standalone=False,
        )
        abs_meta = AbsMetadata(
            title="Harry Potter and the Philosopher's Stone",
            subtitle=None,
            authors=["J.K. Rowling"],
            series="Wizarding World Collection",
            series_position="1",
            year=1997,
            asin="B0000HP001",
        )
        candidate = RenameCandidate(
            source_path=book,
            current_name=book.name,
            parsed=parsed,
            abs_metadata=abs_meta,
        )

        policy = RenamePolicy(
            hierarchy_mode="author_series_book",
            series_source="abs_first",
        )
        result = compute_target_name(
            candidate,
            source_dir=source_dir,
            policy=policy,
        )

        # abs_first lets ABS metadata win
        assert result.components["series"] == "Wizarding World Collection"

    def test_folder_first_title_resolution(self, tmp_path: Path) -> None:
        """folder_first uses parsed title over ABS title."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import (
            AbsMetadata,
            RenameCandidate,
            RenamePolicy,
            compute_target_name,
        )

        source_dir = tmp_path / "lib"
        author_dir = source_dir / "Author"
        author_dir.mkdir(parents=True)
        book = author_dir / "OldFolder"
        book.mkdir()

        parsed = ParsedFolderName(
            author="Author",
            title="Parsed Title",
            series=None,
            series_position=None,
            asin="B000000001",
            year="2020",
            ripper_tag=None,
            is_standalone=True,
        )
        abs_meta = AbsMetadata(
            title="ABS Title",
            subtitle=None,
            authors=["Author"],
            series=None,
            series_position=None,
            year=2021,
            asin="B000000001",
        )
        candidate = RenameCandidate(
            source_path=book,
            current_name=book.name,
            parsed=parsed,
            abs_metadata=abs_meta,
        )

        policy = RenamePolicy(series_source="folder_first")
        result = compute_target_name(
            candidate,
            source_dir=source_dir,
            policy=policy,
        )

        # folder_first: parsed title and year win
        assert result.components["title"] == "Parsed Title"
        assert result.components["year"] == "2020"


class TestSeriesRootChangeRiskFlag:
    """Tests for series_root_change risk flag in plan output."""

    def test_risk_flag_in_derive_risk_flags(self) -> None:
        """series_root_changed in components produces series_root_change flag
        only when the target parent directory actually differs from source."""
        from shelfr.abs.rename import RenameCandidate, _derive_risk_flags

        candidate = RenameCandidate(
            source_path=Path("/lib/Author/OldSeries/Book"),
            current_name="Book",
            target_name="NewBook",
            target_path=Path("/lib/Author/NewSeries/NewBook"),
            components={"series_root_changed": True},
        )
        flags = _derive_risk_flags(candidate)
        assert "series_root_change" in flags

    def test_no_risk_flag_when_same_parent(self) -> None:
        """No series_root_change flag when parent directory is unchanged,
        even if components.series_root_changed is True (metadata noise)."""
        from shelfr.abs.rename import RenameCandidate, _derive_risk_flags

        candidate = RenameCandidate(
            source_path=Path("/lib/Author/Series/Book"),
            current_name="Book",
            target_name="NewBook",
            target_path=Path("/lib/Author/Series/NewBook"),
            components={"series_root_changed": True},
        )
        flags = _derive_risk_flags(candidate)
        assert "series_root_change" not in flags

    def test_no_risk_flag_when_no_change(self) -> None:
        """No series_root_change flag when series root is preserved."""
        from shelfr.abs.rename import RenameCandidate, _derive_risk_flags

        candidate = RenameCandidate(
            source_path=Path("/lib/Author/Series/Book"),
            current_name="Book",
            target_name="NewBook",
            components={},
        )
        flags = _derive_risk_flags(candidate)
        assert "series_root_change" not in flags


class TestRenamePolicySeriesSource:
    """Tests for series_source field on RenamePolicy."""

    def test_default_is_preserve_existing(self) -> None:
        from shelfr.abs.rename import RenamePolicy

        policy = RenamePolicy()
        assert policy.series_source == "preserve_existing"

    def test_sao_gold_has_preserve_existing(self) -> None:
        from shelfr.abs.rename import resolve_rename_policy

        policy = resolve_rename_policy(policy_profile="sao_gold")
        assert policy.series_source == "preserve_existing"

    def test_round_trip_serialization(self) -> None:
        from shelfr.abs.rename import RenamePolicy

        policy = RenamePolicy(series_source="folder_first")
        data = policy.as_dict()
        assert data["series_source"] == "folder_first"

        restored = RenamePolicy.from_dict(data)
        assert restored.series_source == "folder_first"


class TestArcEditionTagStripping:
    """Tests for edition tag stripping in _resolve_arc_name."""

    def test_strip_full_cast_from_parsed_title(self, tmp_path: Path) -> None:
        """Edition tags like (Full-Cast) should be stripped from arc."""
        from shelfr.abs.rename import _strip_edition_tags

        assert _strip_edition_tags("Philosophers Stone (Full-Cast)") == "Philosophers Stone"
        assert _strip_edition_tags("Book (Dolby Atmos)") == "Book"
        assert _strip_edition_tags("Clean Title") == "Clean Title"
        assert _strip_edition_tags("(Abridged) Title (Dolby Atmos)") == "Title"


class TestConfigSchemaSeriesSource:
    """Tests for series_source in AudiobookshelfRenameSchema."""

    def test_valid_values(self) -> None:
        from shelfr.schemas.config import AudiobookshelfRenameSchema

        for val in ("preserve_existing", "folder_first", "abs_first"):
            schema = AudiobookshelfRenameSchema(series_source=val)
            assert schema.series_source == val

    def test_invalid_value_rejected(self) -> None:
        import pytest

        from shelfr.schemas.config import AudiobookshelfRenameSchema

        with pytest.raises(Exception):  # noqa: B017
            AudiobookshelfRenameSchema(series_source="invalid")

    def test_default_is_preserve_existing(self) -> None:
        from shelfr.schemas.config import AudiobookshelfRenameSchema

        schema = AudiobookshelfRenameSchema()
        assert schema.series_source == "preserve_existing"


class TestExtractArcFromLibationTitle:
    """Tests for _extract_arc_from_libation_title helper."""

    def test_strips_series_and_volume_prefix(self) -> None:
        from shelfr.abs.rename import _extract_arc_from_libation_title

        result = _extract_arc_from_libation_title(
            "Harry Potter vol_01 and the Philosopher's Stone",
            "Harry Potter",
            "01",
        )
        assert result == "and the Philosopher's Stone"

    def test_strips_trailing_author_parenthetical(self) -> None:
        from shelfr.abs.rename import _extract_arc_from_libation_title

        result = _extract_arc_from_libation_title(
            "Harry Potter vol_01 and the Philosopher's Stone (J.K. Rowling)",
            "Harry Potter",
            "01",
        )
        assert result == "and the Philosopher's Stone"

    def test_no_arc_portion(self) -> None:
        from shelfr.abs.rename import _extract_arc_from_libation_title

        result = _extract_arc_from_libation_title(
            "Harry Potter vol_01",
            "Harry Potter",
            "01",
        )
        assert result == ""

    def test_no_arc_with_trailing_author(self) -> None:
        from shelfr.abs.rename import _extract_arc_from_libation_title

        result = _extract_arc_from_libation_title(
            "Harry Potter vol_01 (J.K. Rowling)",
            "Harry Potter",
            "01",
        )
        assert result == ""

    def test_vol_dot_format(self) -> None:
        from shelfr.abs.rename import _extract_arc_from_libation_title

        result = _extract_arc_from_libation_title(
            "My Series vol.3 The Arc Name",
            "My Series",
            "3",
        )
        assert result == "The Arc Name"

    def test_decimal_volume(self) -> None:
        from shelfr.abs.rename import _extract_arc_from_libation_title

        result = _extract_arc_from_libation_title(
            "Series vol_05.5 Side Story",
            "Series",
            "05.5",
        )
        assert result == "Side Story"

    def test_case_insensitive_series_match(self) -> None:
        from shelfr.abs.rename import _extract_arc_from_libation_title

        result = _extract_arc_from_libation_title(
            "harry potter vol_01 Some Arc",
            "Harry Potter",
            "01",
        )
        assert result == "Some Arc"


class TestLibationArcResolves:
    """Integration: folder-first arc resolves correctly for Libation-format folders.

    Verifies that Bug 1 (title stripping) and Bug 2 (name doubling) are
    fixed by ensuring the arc is extracted cleanly from Libation-format
    parsed titles before being passed to build_mam_folder_name.
    """

    def _make_candidate(
        self,
        source_path: Path,
        parsed_title: str,
        parsed_series: str,
        parsed_position: str,
        abs_title: str | None = None,
        abs_subtitle: str | None = None,
        abs_series: str | None = None,
        abs_position: str | None = None,
    ) -> Any:
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import AbsMetadata, RenameCandidate

        parsed = ParsedFolderName(
            author="J.K. Rowling",
            title=parsed_title,
            series=parsed_series,
            series_position=parsed_position,
            asin="B0D1CSXB3Z",
            year="2024",
            ripper_tag=None,
            is_standalone=False,
        )
        abs_meta = None
        if abs_title:
            abs_meta = AbsMetadata(
                title=abs_title,
                subtitle=abs_subtitle,
                authors=["J.K. Rowling"],
                series=abs_series,
                series_position=abs_position,
                year=2024,
            )
        return RenameCandidate(
            source_path=source_path,
            current_name=source_path.name,
            parsed=parsed,
            abs_metadata=abs_meta,
        )

    def test_series_book_arc_preserved_not_stripped(self) -> None:
        """Bug 1 fix: arc like 'and the Philosopher's Stone' must survive."""
        from shelfr.abs.rename import RenamePolicy, compute_target_name

        source = Path(
            "/lib/Author/Harry Potter/"
            "Harry Potter vol_01 and the Philosopher's Stone (2024) "
            "(J.K. Rowling) (Stephen Fry) {ASIN.B0D1CSXB3Z}"
        )
        c = self._make_candidate(
            source_path=source,
            parsed_title="Harry Potter vol_01 and the Philosopher's Stone (J.K. Rowling)",
            parsed_series="Harry Potter",
            parsed_position="01",
            abs_title="Harry Potter and the Philosopher's Stone",
            abs_series="Harry Potter",
            abs_position="1",
        )
        policy = RenamePolicy(series_source="preserve_existing")
        result = compute_target_name(c, source_dir=Path("/lib/Author"), policy=policy)
        assert result.target_name is not None
        # The arc portion must appear in the target name
        assert "Philosopher" in result.target_name

    def test_series_book_no_doubling(self) -> None:
        """Bug 2 fix: no series+vol duplication when arc contains series prefix."""
        from shelfr.abs.rename import RenamePolicy, compute_target_name

        source = Path(
            "/lib/Author/Harry Potter/"
            "Harry Potter vol_04 and the Goblet of Fire (2026) "
            "(Full-Cast) {ASIN.B0F14PB6WN}"
        )
        c = self._make_candidate(
            source_path=source,
            parsed_title="Harry Potter vol_04 and the Goblet of Fire",
            parsed_series="Harry Potter",
            parsed_position="04",
            abs_title="Harry Potter and the Goblet of Fire",
            abs_series="Harry Potter",
            abs_position="4",
        )
        c = dataclasses.replace(c, parsed=dataclasses.replace(c.parsed, asin="B0F14PB6WN"))
        policy = RenamePolicy(series_source="preserve_existing")
        result = compute_target_name(c, source_dir=Path("/lib/Author"), policy=policy)
        assert result.target_name is not None
        # Must NOT have doubled series+vol
        assert result.target_name.count("Harry Potter vol_04") == 1
        # The arc portion must appear
        assert "Goblet" in result.target_name


class TestComputeTargetNameBugFixes:
    """Regression tests for specific compute_target_name bug fixes."""

    def test_standalone_vol_00_suppressed(self, tmp_path: Path) -> None:
        """Bug 6: standalone book with ABS series_position=0 should NOT get vol_00."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import (
            AbsMetadata,
            RenameCandidate,
            RenamePolicy,
            compute_target_name,
        )

        source_dir = tmp_path / "lib"
        source_dir.mkdir()
        author_dir = source_dir / "Yoru Sumino"
        author_dir.mkdir()
        source = author_dir / "I Had That Same Dream Again"
        source.mkdir()
        (source / "audio.m4b").touch()

        parsed = ParsedFolderName(
            author="Yoru Sumino",
            title="I Had That Same Dream Again",
            series=None,
            series_position=None,
            asin="B0D1234567",
            year="2020",
            ripper_tag="H2OKing",
            is_standalone=True,
        )
        candidate = RenameCandidate(
            source_path=source,
            current_name=source.name,
            parsed=parsed,
            abs_metadata=AbsMetadata(
                title="I Had That Same Dream Again",
                subtitle=None,
                authors=["Yoru Sumino"],
                series=None,
                series_position="0",
                year=2020,
                asin="B0D1234567",
            ),
        )

        policy = RenamePolicy(series_source="preserve_existing")
        result = compute_target_name(candidate, source_dir=source_dir, policy=policy)
        assert result.target_name is not None
        assert "vol_00" not in result.target_name
        assert "vol_0" not in result.target_name.split()

    def test_standalone_vol_00_suppressed_pseudo_series(self, tmp_path: Path) -> None:
        """Bug 6b: ABS pseudo-series (series == title) with pos=0 → no vol_00."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import (
            AbsMetadata,
            RenameCandidate,
            RenamePolicy,
            compute_target_name,
        )

        # source_dir should be the *author* directory (as CLI passes it
        # via --source), NOT the library root.  When source_dir is the
        # library root, _detect_series_root mis-identifies the author dir
        # as a series root for depth-2 paths.
        source_dir = tmp_path / "lib" / "Yoru Sumino"
        source_dir.mkdir(parents=True)
        source = source_dir / "I Had That Same Dream Again (2024)"
        source.mkdir()
        (source / "audio.m4b").touch()

        parsed = ParsedFolderName(
            author="Yoru Sumino",
            title="I Had That Same Dream Again",
            series=None,
            series_position=None,
            asin="B0D3G9F94G",
            year="2024",
            ripper_tag="H2OKing",
            is_standalone=True,
        )
        candidate = RenameCandidate(
            source_path=source,
            current_name=source.name,
            parsed=parsed,
            abs_metadata=AbsMetadata(
                title="I Had That Same Dream Again",
                subtitle=None,
                authors=["Yoru Sumino"],
                # ABS assigns series = title (pseudo-series)
                series="I Had That Same Dream Again",
                series_position="0",
                year=2024,
                asin="B0D3G9F94G",
            ),
        )

        policy = RenamePolicy(series_source="preserve_existing")
        result = compute_target_name(candidate, source_dir=source_dir, policy=policy)
        assert result.target_name is not None
        assert "vol_00" not in result.target_name
        # Should be treated as standalone — no series folder
        assert result.components.get("series") is None or result.components["series"] == ""

    def test_bracket_year_stripped_from_title(self, tmp_path: Path) -> None:
        """Bug 3: [YYYY] in title should not cause doubled year."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import (
            AbsMetadata,
            RenameCandidate,
            RenamePolicy,
            compute_target_name,
        )

        source_dir = tmp_path / "lib"
        source_dir.mkdir()
        source = source_dir / "I Have a Secret [2025]"
        source.mkdir()
        (source / "audio.m4b").touch()

        parsed = ParsedFolderName(
            author="Yoru Sumino",
            title="I Have a Secret [2025]",
            series=None,
            series_position=None,
            asin="B0D9876543",
            year="2025",
            ripper_tag=None,
            is_standalone=True,
        )
        candidate = RenameCandidate(
            source_path=source,
            current_name=source.name,
            parsed=parsed,
            abs_metadata=AbsMetadata(
                title="I Have a Secret",
                subtitle=None,
                authors=["Yoru Sumino"],
                series=None,
                series_position=None,
                year=2025,
                asin="B0D9876543",
            ),
        )

        policy = RenamePolicy(series_source="preserve_existing")
        result = compute_target_name(candidate, source_dir=source_dir, policy=policy)
        assert result.target_name is not None
        # Must have year exactly once, not "[2025] (2025)"
        assert "[2025]" not in result.target_name
        assert result.target_name.count("(2025)") == 1

    def test_arc_extracted_from_vol_prefixed_title(self, tmp_path: Path) -> None:
        """Issue #2: DCC-style 'vol_02 - Carl's Doomsday Scenario' should populate arc."""
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import (
            AbsMetadata,
            RenameCandidate,
            RenamePolicy,
            compute_target_name,
        )

        source_dir = tmp_path / "lib" / "Matt Dinniman"
        series_dir = source_dir / "Dungeon Crawler Carl"
        series_dir.mkdir(parents=True)
        source = series_dir / "Dungeon Crawler Carl - vol_02 - Carl's Doomsday Scenario [2021]"
        source.mkdir()
        (source / "audio.m4b").touch()

        parsed = ParsedFolderName(
            author="Dungeon Crawler Carl",
            title="vol_02 - Carl's Doomsday Scenario",
            series="Dungeon Crawler Carl",
            series_position="02",
            asin="B0934GTSGT",
            year="2021",
            ripper_tag=None,
            is_standalone=False,
        )
        candidate = RenameCandidate(
            source_path=source,
            current_name=source.name,
            parsed=parsed,
            abs_metadata=AbsMetadata(
                title="Carl's Doomsday Scenario",
                subtitle=None,
                authors=["Matt Dinniman"],
                series="Dungeon Crawler Carl",
                series_position="2",
                year=2021,
                asin="B0934GTSGT",
            ),
        )

        policy = RenamePolicy(series_source="preserve_existing")
        result = compute_target_name(candidate, source_dir=source_dir, policy=policy)
        assert result.target_name is not None
        # The subtitle "Carl's Doomsday Scenario" should appear as arc
        assert "Doomsday Scenario" in result.target_name
        # Volume prefix must NOT appear doubled
        assert result.target_name.count("vol_02") == 1
        # Arc should be in the components
        assert result.components.get("arc") is not None

    def test_arc_extracted_when_parsed_series_is_none(self, tmp_path: Path) -> None:
        """DCC real-world: parser returns series=None when folder is 'Author - vol_XX - Subtitle'.

        The resolved series comes from ABS metadata; the arc should still be
        extracted from parsed.title via the vol-prefix stripping path.
        """
        from shelfr.abs.importer import ParsedFolderName
        from shelfr.abs.rename import (
            AbsMetadata,
            RenameCandidate,
            RenamePolicy,
            compute_target_name,
        )

        source_dir = tmp_path / "lib" / "Matt Dinniman"
        series_dir = source_dir / "Dungeon Crawler Carl"
        series_dir.mkdir(parents=True)
        source = series_dir / (
            "Dungeon Crawler Carl - vol_02 - Carl's Doomsday Scenario"
            " [2021] [Matt Dinniman] [ASIN.B0934GTSGT]"
        )
        source.mkdir()
        (source / "audio.m4b").touch()

        # Real-world: parse_mam_folder_name returns series=None for this format
        parsed = ParsedFolderName(
            author="Dungeon Crawler Carl",
            title="vol_02 - Carl's Doomsday Scenario",
            series=None,
            series_position=None,
            asin="B0934GTSGT",
            year="2021",
            ripper_tag="Matt Dinniman",
            is_standalone=True,
        )
        candidate = RenameCandidate(
            source_path=source,
            current_name=source.name,
            parsed=parsed,
            abs_metadata=AbsMetadata(
                title="Carl's Doomsday Scenario",
                subtitle="Dungeon Crawler Carl, Book 2",
                authors=["Matt Dinniman"],
                series="Dungeon Crawler Carl",
                series_position="2",
                year=2021,
                asin="B0934GTSGT",
            ),
        )

        policy = RenamePolicy(series_source="preserve_existing")
        result = compute_target_name(candidate, source_dir=source_dir, policy=policy)
        assert result.target_name is not None
        # Arc must be populated from parsed.title vol-prefix stripping
        assert result.components.get("arc") is not None
        assert "Doomsday Scenario" in (result.components["arc"] or "")
        # Ensure it's not the series name masquerading as arc
        assert "Dungeon Crawler Carl" not in (result.components["arc"] or "")
