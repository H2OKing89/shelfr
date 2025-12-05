"""Tests for abs/importer.py - Audiobookshelf import functionality."""

from __future__ import annotations

from pathlib import Path

import pytest

from mamfast.abs.asin import AsinEntry
from mamfast.abs.importer import (
    BatchImportResult,
    ImportResult,
    ParsedFolderName,
    build_target_path,
    discover_staged_books,
    import_batch,
    import_single,
    parse_mam_folder_name,
    validate_import_prerequisites,
)

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def temp_staging(tmp_path: Path) -> Path:
    """Create a temporary staging directory with test audiobooks."""
    staging = tmp_path / "staging"
    staging.mkdir()
    return staging


@pytest.fixture
def temp_library(tmp_path: Path) -> Path:
    """Create a temporary library root."""
    library = tmp_path / "audiobooks"
    library.mkdir()
    return library


@pytest.fixture
def empty_asin_index() -> dict[str, AsinEntry]:
    """Create an empty ASIN index for tests."""
    return {}


@pytest.fixture
def mock_asin_index() -> dict[str, AsinEntry]:
    """Create an ASIN index with some existing entries for duplicate testing."""
    return {
        "B08G9PRS1K": AsinEntry(
            asin="B08G9PRS1K",
            path="/audiobooks/Andy Weir/Project Hail Mary",
            library_item_id="li_existing1",
            title="Project Hail Mary",
            author="Andy Weir",
        ),
    }


def create_audiobook_folder(staging: Path, name: str, *, with_audio: bool = True) -> Path:
    """Create a test audiobook folder."""
    folder = staging / name
    folder.mkdir()
    if with_audio:
        (folder / "audiobook.m4b").write_text("fake audio content")
        (folder / "cover.jpg").write_bytes(b"fake image")
    return folder


# =============================================================================
# Tests: parse_mam_folder_name
# =============================================================================


class TestParseMamFolderName:
    """Tests for folder name parsing."""

    def test_series_book_with_all_components(self) -> None:
        """Parse series book with all metadata."""
        folder = (
            "Brandon Sanderson - Mistborn vol_01 - The Final Empire "
            "(2006) (Narrator) {H2OKing} [ASIN.B0C1234567]"
        )
        result = parse_mam_folder_name(folder)
        assert result.author == "Brandon Sanderson"
        assert result.series == "Mistborn"
        assert result.series_position == "01"
        assert result.title == "The Final Empire"
        assert result.year == "2006"
        assert result.narrator == "Narrator"
        assert result.ripper_tag == "H2OKing"
        assert result.asin == "B0C1234567"
        assert result.is_standalone is False

    def test_series_book_minimal(self) -> None:
        """Parse series book with minimal metadata."""
        result = parse_mam_folder_name("Author - Series vol_1 - Title")
        assert result.author == "Author"
        assert result.series == "Series"
        assert result.series_position == "1"
        assert result.title == "Title"
        assert result.is_standalone is False

    def test_standalone_book(self) -> None:
        """Parse standalone book (no series)."""
        result = parse_mam_folder_name(
            "Andy Weir - Project Hail Mary (2021) (Ray Porter) {H2OKing} [ASIN.B08G9PRS1K]"
        )
        assert result.author == "Andy Weir"
        assert result.title == "Project Hail Mary"
        assert result.series is None
        assert result.series_position is None
        assert result.year == "2021"
        assert result.narrator == "Ray Porter"
        assert result.asin == "B08G9PRS1K"
        assert result.is_standalone is True

    def test_series_with_hash_notation(self) -> None:
        """Parse series with # notation."""
        result = parse_mam_folder_name("Author - Series #5 - Title")
        assert result.series == "Series"
        assert result.series_position == "5"

    def test_series_with_decimal_position(self) -> None:
        """Parse series with decimal position (novella)."""
        result = parse_mam_folder_name("Author - Series vol_1.5 - Novella Title")
        assert result.series_position == "1.5"

    def test_asin_with_braces(self) -> None:
        """Parse ASIN in {ASIN.xxx} format."""
        result = parse_mam_folder_name("Author - Title {ASIN.B012345678}")
        assert result.asin == "B012345678"

    def test_asin_with_brackets(self) -> None:
        """Parse ASIN in [B0xxx] format."""
        result = parse_mam_folder_name("Author - Title [B012345678]")
        assert result.asin == "B012345678"

    def test_no_author_separator(self) -> None:
        """Handle folder name without author separator."""
        result = parse_mam_folder_name("Just A Title")
        assert result.author == "Unknown"
        assert result.title == "Just A Title"
        assert result.is_standalone is True

    def test_japanese_author(self) -> None:
        """Parse folder with Japanese author name."""
        folder = (
            "Reki Kawahara - Sword Art Online vol_16 - Alicization Exploding "
            "(2020) {H2OKing} [ASIN.B0DK9TS6D9]"
        )
        result = parse_mam_folder_name(folder)
        assert result.author == "Reki Kawahara"
        assert result.series == "Sword Art Online"
        assert result.series_position == "16"
        assert result.asin == "B0DK9TS6D9"

    def test_multiple_parentheticals(self) -> None:
        """Parse folder with multiple parentheticals."""
        result = parse_mam_folder_name("Author - Title (Part One) (2020) (Narrator Name)")
        assert result.year == "2020"
        assert result.narrator == "Narrator Name"
        # Title should include "(Part One)"
        assert "Part One" in result.title or result.title == "Title (Part One)"


# =============================================================================
# Tests: build_target_path
# =============================================================================


class TestBuildTargetPath:
    """Tests for target path building."""

    def test_series_book_path(self, temp_library: Path) -> None:
        """Build path for series book: Author/Series/CleanedFolderName."""
        parsed = ParsedFolderName(
            author="Brandon Sanderson",
            title="The Final Empire",
            series="Mistborn",
            series_position="1",
            asin="B0123456789",
            year="2006",
            narrator="Michael Kramer",
            ripper_tag="H2OKing",
            is_standalone=False,
        )
        staging_folder = Path("/staging/Brandon Sanderson - Mistborn vol_01 - The Final Empire")

        target = build_target_path(temp_library, parsed, staging_folder)

        # Folder name is cleaned using build_mam_folder_name()
        # Expected: Mistborn vol_01 (2006) (Michael Kramer) {ASIN.B0123456789} [H2OKing]
        assert target.parent == temp_library / "Brandon Sanderson" / "Mistborn"
        assert "Mistborn vol_01" in target.name
        assert "{ASIN.B0123456789}" in target.name
        assert "[H2OKing]" in target.name

    def test_standalone_book_path(self, temp_library: Path) -> None:
        """Build path for standalone book: Author/CleanedFolderName."""
        parsed = ParsedFolderName(
            author="Andy Weir",
            title="Project Hail Mary",
            series=None,
            series_position=None,
            asin="B08G9PRS1K",
            year="2021",
            narrator="Ray Porter",
            ripper_tag="H2OKing",
            is_standalone=True,
        )
        staging_folder = Path("/staging/Andy Weir - Project Hail Mary")

        target = build_target_path(temp_library, parsed, staging_folder)

        # Standalone uses title-based naming
        assert target.parent == temp_library / "Andy Weir"
        assert "Project Hail Mary" in target.name
        assert "{ASIN.B08G9PRS1K}" in target.name


# =============================================================================
# Tests: validate_import_prerequisites
# =============================================================================


class TestValidateImportPrerequisites:
    """Tests for prerequisite validation."""

    def test_all_valid(self, temp_staging: Path, temp_library: Path) -> None:
        """No errors when all prerequisites met."""
        errors = validate_import_prerequisites(temp_staging, temp_library)
        assert errors == []

    def test_staging_not_exists(self, tmp_path: Path, temp_library: Path) -> None:
        """Error when staging doesn't exist."""
        nonexistent = tmp_path / "nonexistent"

        errors = validate_import_prerequisites(nonexistent, temp_library)

        assert len(errors) >= 1
        assert any("staging" in e.lower() or "does not exist" in e.lower() for e in errors)

    def test_library_not_exists(self, temp_staging: Path, tmp_path: Path) -> None:
        """Error when library doesn't exist."""
        nonexistent = tmp_path / "nonexistent"

        errors = validate_import_prerequisites(temp_staging, nonexistent)

        assert len(errors) >= 1
        assert any("library" in e.lower() or "does not exist" in e.lower() for e in errors)

    def test_multiple_errors(self, tmp_path: Path) -> None:
        """Collect multiple errors at once."""
        nonexistent_staging = tmp_path / "no_staging"
        nonexistent_library = tmp_path / "no_library"

        errors = validate_import_prerequisites(nonexistent_staging, nonexistent_library)

        # At least staging and library errors
        assert len(errors) >= 2


# =============================================================================
# Tests: discover_staged_books
# =============================================================================


class TestDiscoverStagedBooks:
    """Tests for staging directory discovery."""

    def test_discover_with_m4b(self, temp_staging: Path) -> None:
        """Discover folder with .m4b file."""
        create_audiobook_folder(temp_staging, "Book 1", with_audio=True)

        found = discover_staged_books(temp_staging)

        assert len(found) == 1
        assert found[0].name == "Book 1"

    def test_discover_multiple(self, temp_staging: Path) -> None:
        """Discover multiple audiobook folders."""
        create_audiobook_folder(temp_staging, "Book 1")
        create_audiobook_folder(temp_staging, "Book 2")
        create_audiobook_folder(temp_staging, "Book 3")

        found = discover_staged_books(temp_staging)

        assert len(found) == 3

    def test_ignore_non_audio_folders(self, temp_staging: Path) -> None:
        """Ignore folders without audio files."""
        create_audiobook_folder(temp_staging, "Real Book", with_audio=True)
        # Create folder with no audio
        no_audio = temp_staging / "No Audio"
        no_audio.mkdir()
        (no_audio / "readme.txt").write_text("text file")

        found = discover_staged_books(temp_staging)

        assert len(found) == 1
        assert found[0].name == "Real Book"

    def test_ignore_regular_files(self, temp_staging: Path) -> None:
        """Ignore regular files in staging root."""
        create_audiobook_folder(temp_staging, "Book")
        (temp_staging / "random.txt").write_text("not a book")

        found = discover_staged_books(temp_staging)

        assert len(found) == 1

    def test_nonexistent_staging(self, tmp_path: Path) -> None:
        """Return empty list for nonexistent staging."""
        nonexistent = tmp_path / "nonexistent"

        found = discover_staged_books(nonexistent)

        assert found == []

    def test_sorted_by_name(self, temp_staging: Path) -> None:
        """Results should be sorted by name."""
        create_audiobook_folder(temp_staging, "Zebra Book")
        create_audiobook_folder(temp_staging, "Alpha Book")
        create_audiobook_folder(temp_staging, "Middle Book")

        found = discover_staged_books(temp_staging)

        names = [f.name for f in found]
        assert names == sorted(names)

    def test_various_audio_extensions(self, temp_staging: Path) -> None:
        """Recognize various audio file extensions."""
        extensions = [".m4b", ".mp3", ".m4a", ".flac", ".ogg", ".opus"]
        for i, ext in enumerate(extensions):
            folder = temp_staging / f"Book {i}"
            folder.mkdir()
            (folder / f"audio{ext}").write_text("fake")

        found = discover_staged_books(temp_staging)

        assert len(found) == len(extensions)


# =============================================================================
# Tests: import_single
# =============================================================================


class TestImportSingle:
    """Tests for single book import."""

    def test_successful_import(
        self, temp_staging: Path, temp_library: Path, empty_asin_index: dict[str, AsinEntry]
    ) -> None:
        """Successfully import a book."""
        folder_name = "Andy Weir - Project Hail Mary (2021) [ASIN.B08G9PRS1K]"
        staging_folder = create_audiobook_folder(temp_staging, folder_name)

        result = import_single(
            staging_folder=staging_folder,
            library_root=temp_library,
            asin_index=empty_asin_index,
        )

        assert result.status == "success"
        assert result.asin == "B08G9PRS1K"
        assert result.target_path is not None
        assert result.target_path.exists()
        assert not staging_folder.exists()  # Was moved

    def test_dry_run_no_move(
        self, temp_staging: Path, temp_library: Path, empty_asin_index: dict[str, AsinEntry]
    ) -> None:
        """Dry run doesn't move files."""
        folder_name = "Andy Weir - Project Hail Mary [B08G9PRS1K]"
        staging_folder = create_audiobook_folder(temp_staging, folder_name)

        result = import_single(
            staging_folder=staging_folder,
            library_root=temp_library,
            asin_index=empty_asin_index,
            dry_run=True,
        )

        assert result.status == "success"
        assert staging_folder.exists()  # Not moved
        assert result.target_path is not None
        assert not result.target_path.exists()  # Target not created

    def test_duplicate_skip(
        self, temp_staging: Path, temp_library: Path, mock_asin_index: dict[str, AsinEntry]
    ) -> None:
        """Skip when ASIN already in index."""
        # Add existing book to index
        mock_asin_index["B08G9PRS1K"] = AsinEntry(
            asin="B08G9PRS1K",
            path="/existing/path",
            library_item_id="li_existing",
            title="Existing Book",
            author="Author",
        )

        folder_name = "Author - New Book [B08G9PRS1K]"
        staging_folder = create_audiobook_folder(temp_staging, folder_name)

        result = import_single(
            staging_folder=staging_folder,
            library_root=temp_library,
            asin_index=mock_asin_index,
            duplicate_policy="skip",
        )

        assert result.status == "duplicate"
        assert staging_folder.exists()  # Not moved

    def test_duplicate_overwrite(
        self, temp_staging: Path, temp_library: Path, mock_asin_index: dict[str, AsinEntry]
    ) -> None:
        """Overwrite when duplicate policy is overwrite."""
        # Create existing target
        target = temp_library / "Author" / "Author - Old Book [B08G9PRS1K]"
        target.mkdir(parents=True)
        (target / "old.m4b").write_text("old content")

        # Add to index
        mock_asin_index["B08G9PRS1K"] = AsinEntry(
            asin="B08G9PRS1K",
            path=str(target),
            library_item_id="li_old",
            title="Old Book",
            author="Author",
        )

        folder_name = "Author - New Book [B08G9PRS1K]"
        staging_folder = create_audiobook_folder(temp_staging, folder_name)

        result = import_single(
            staging_folder=staging_folder,
            library_root=temp_library,
            asin_index=mock_asin_index,
            duplicate_policy="overwrite",
        )

        assert result.status == "success"
        assert not staging_folder.exists()

    def test_no_asin_warning(
        self,
        temp_staging: Path,
        temp_library: Path,
        empty_asin_index: dict[str, AsinEntry],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Warn when no ASIN in folder name."""
        import logging

        caplog.set_level(logging.WARNING)

        folder_name = "Author - Book Without ASIN"
        staging_folder = create_audiobook_folder(temp_staging, folder_name)

        result = import_single(
            staging_folder=staging_folder,
            library_root=temp_library,
            asin_index=empty_asin_index,
        )

        assert result.status == "success"
        assert result.asin is None
        assert "No ASIN" in caplog.text


# =============================================================================
# Tests: import_batch
# =============================================================================


class TestImportBatch:
    """Tests for batch import."""

    def test_batch_import_multiple(
        self, temp_staging: Path, temp_library: Path, empty_asin_index: dict[str, AsinEntry]
    ) -> None:
        """Import multiple books in batch."""
        # Use valid ASIN format (10 chars starting with B0)
        folders = [
            create_audiobook_folder(temp_staging, f"Author - Book {i} [B0ABC{i:05d}]")
            for i in range(1, 4)
        ]

        result = import_batch(
            staging_folders=folders,
            library_root=temp_library,
            asin_index=empty_asin_index,
        )

        assert result.success_count == 3
        assert result.duplicate_count == 0
        assert result.failed_count == 0
        assert len(result.results) == 3

    def test_batch_with_duplicates(
        self, temp_staging: Path, temp_library: Path, mock_asin_index: dict[str, AsinEntry]
    ) -> None:
        """Batch handles duplicates correctly."""
        # Add one existing book to index
        mock_asin_index["B000000002"] = AsinEntry(
            asin="B000000002",
            path="/path",
            library_item_id="li_dup",
            title="Existing",
            author="Author",
        )

        folders = [
            create_audiobook_folder(temp_staging, "Author - Book 1 [B000000001]"),
            create_audiobook_folder(temp_staging, "Author - Book 2 [B000000002]"),  # Duplicate
            create_audiobook_folder(temp_staging, "Author - Book 3 [B000000003]"),
        ]

        result = import_batch(
            staging_folders=folders,
            library_root=temp_library,
            asin_index=mock_asin_index,
        )

        assert result.success_count == 2
        assert result.duplicate_count == 1

    def test_batch_dry_run(
        self, temp_staging: Path, temp_library: Path, empty_asin_index: dict[str, AsinEntry]
    ) -> None:
        """Batch dry run doesn't move files."""
        folders = [
            create_audiobook_folder(temp_staging, f"Author - Book {i} [B0{i:09d}]")
            for i in range(1, 3)
        ]

        result = import_batch(
            staging_folders=folders,
            library_root=temp_library,
            asin_index=empty_asin_index,
            dry_run=True,
        )

        assert result.success_count == 2
        # Folders should still exist
        for folder in folders:
            assert folder.exists()


# =============================================================================
# Tests: BatchImportResult
# =============================================================================


class TestBatchImportResult:
    """Tests for BatchImportResult dataclass."""

    def test_add_success(self) -> None:
        """Add success result updates count."""
        batch = BatchImportResult()
        batch.add(ImportResult(Path("/a"), Path("/b"), "B0123", "success"))

        assert batch.success_count == 1
        assert batch.failed_count == 0

    def test_add_duplicate(self) -> None:
        """Add duplicate result updates count."""
        batch = BatchImportResult()
        batch.add(ImportResult(Path("/a"), None, "B0123", "duplicate", "exists"))

        assert batch.duplicate_count == 1

    def test_add_failed(self) -> None:
        """Add failed result updates count."""
        batch = BatchImportResult()
        batch.add(ImportResult(Path("/a"), None, None, "failed", "error"))

        assert batch.failed_count == 1

    def test_tracks_all_results(self) -> None:
        """All results are stored in list."""
        batch = BatchImportResult()
        for i in range(5):
            batch.add(ImportResult(Path(f"/{i}"), Path(f"/t{i}"), f"B0{i}", "success"))

        assert len(batch.results) == 5


# =============================================================================
# Tests: Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_target_path_already_exists(
        self, temp_staging: Path, temp_library: Path, empty_asin_index: dict[str, AsinEntry]
    ) -> None:
        """Handle target path already existing on disk."""
        # Use valid ASIN format (B0 + 8 alphanumeric chars)
        folder_name = "Author - Title {ASIN.B0ABCDEFGH}"
        staging_folder = create_audiobook_folder(temp_staging, folder_name)

        # Create target path with cleaned name (what build_clean_folder_name returns)
        # For standalone: "Title (Author) {ASIN.xxx}"
        clean_name = "Title (Author) {ASIN.B0ABCDEFGH}"
        target = temp_library / "Author" / clean_name
        target.mkdir(parents=True)
        (target / "existing.m4b").write_text("existing")

        result = import_single(
            staging_folder=staging_folder,
            library_root=temp_library,
            asin_index=empty_asin_index,
            duplicate_policy="skip",
        )

        assert result.status == "duplicate"
        assert staging_folder.exists()

    def test_special_characters_in_author(
        self, temp_staging: Path, temp_library: Path, empty_asin_index: dict[str, AsinEntry]
    ) -> None:
        """Handle special characters in author name."""
        folder_name = "O'Brien & Sons - Book {ASIN.B0ABCDEFGH}"
        staging_folder = create_audiobook_folder(temp_staging, folder_name)

        result = import_single(
            staging_folder=staging_folder,
            library_root=temp_library,
            asin_index=empty_asin_index,
        )

        assert result.status == "success"

    def test_very_long_folder_name(
        self, temp_staging: Path, temp_library: Path, empty_asin_index: dict[str, AsinEntry]
    ) -> None:
        """Handle long folder names."""
        long_title = "A" * 100
        folder_name = f"Author - {long_title} {{ASIN.B0ABCDEFGH}}"
        staging_folder = create_audiobook_folder(temp_staging, folder_name)

        result = import_single(
            staging_folder=staging_folder,
            library_root=temp_library,
            asin_index=empty_asin_index,
        )

        assert result.status == "success"
