"""Tests for abs/importer.py - Audiobookshelf import functionality."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mamfast.abs.asin import AsinEntry
from mamfast.abs.importer import (
    BatchImportResult,
    ImportResult,
    ParsedFolderName,
    UnknownAsinContentType,
    UnknownAsinContext,
    UnknownAsinPolicy,
    build_target_path,
    build_unknown_target_path,
    classify_unknown_asin,
    discover_staged_books,
    get_unique_destination,
    handle_unknown_asin,
    import_batch,
    import_single,
    matches_homebrew_pattern,
    parse_mam_folder_name,
    validate_import_prerequisites,
    write_unknown_asin_sidecar,
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
# Tests: enrich_from_audnex
# =============================================================================


class TestEnrichFromAudnex:
    """Tests for Audnex metadata enrichment."""

    def test_series_position_int_coerced_to_string(self) -> None:
        """Audnex sometimes returns series_position as int - must be coerced to string."""
        from unittest.mock import patch

        from mamfast.abs.importer import enrich_from_audnex

        parsed = ParsedFolderName(
            author="Unknown",
            title="Test Book",
            series=None,
            series_position=None,
            asin="B0TEST1234",
            year=None,
            narrator=None,
            ripper_tag=None,
            is_standalone=True,
        )

        # Mock Audnex returning position as int (common case)
        mock_audnex_data = {
            "title": "Test Book",
            "authors": [{"name": "Test Author"}],
            "seriesPrimary": {
                "name": "Test Series",
                "position": 5,  # int, not string!
            },
        }

        with patch("mamfast.abs.importer.fetch_audnex_book", return_value=mock_audnex_data):
            result = enrich_from_audnex(parsed, "B0TEST1234")

        assert result.series == "Test Series"
        assert result.series_position == "5"  # Must be string
        assert isinstance(result.series_position, str)

    def test_series_position_float_coerced_to_string(self) -> None:
        """Handle float position like 1.5 (sub-books)."""
        from unittest.mock import patch

        from mamfast.abs.importer import enrich_from_audnex

        parsed = ParsedFolderName(
            author="Unknown",
            title="Test Book",
            series=None,
            series_position=None,
            asin="B0TEST1234",
            year=None,
            narrator=None,
            ripper_tag=None,
            is_standalone=True,
        )

        mock_audnex_data = {
            "seriesPrimary": {
                "name": "Test Series",
                "position": 1.5,  # float
            },
        }

        with patch("mamfast.abs.importer.fetch_audnex_book", return_value=mock_audnex_data):
            result = enrich_from_audnex(parsed, "B0TEST1234")

        assert result.series_position == "1.5"
        assert isinstance(result.series_position, str)

    def test_series_position_none_handled(self) -> None:
        """Handle None position gracefully."""
        from unittest.mock import patch

        from mamfast.abs.importer import enrich_from_audnex

        parsed = ParsedFolderName(
            author="Unknown",
            title="Test Book",
            series=None,
            series_position=None,
            asin="B0TEST1234",
            year=None,
            narrator=None,
            ripper_tag=None,
            is_standalone=True,
        )

        mock_audnex_data = {
            "seriesPrimary": {
                "name": "Test Series",
                "position": None,  # explicitly None
            },
        }

        with patch("mamfast.abs.importer.fetch_audnex_book", return_value=mock_audnex_data):
            result = enrich_from_audnex(parsed, "B0TEST1234")

        assert result.series == "Test Series"
        assert result.series_position is None  # Should remain None

    def test_subtitle_series_position_coerced(self) -> None:
        """Subtitle fallback also coerces position to string."""
        from unittest.mock import patch

        from mamfast.abs.importer import enrich_from_audnex

        parsed = ParsedFolderName(
            author="Test Author",
            title="Test Book",
            series=None,
            series_position=None,
            asin="B0TEST1234",
            year=None,
            narrator=None,
            ripper_tag=None,
            is_standalone=True,
        )

        # No seriesPrimary, but subtitle has series info
        mock_audnex_data = {
            "subtitle": "My Series, Book 3",
        }

        with patch("mamfast.abs.importer.fetch_audnex_book", return_value=mock_audnex_data):
            result = enrich_from_audnex(parsed, "B0TEST1234")

        assert result.series == "My Series"
        assert result.series_position == "3"
        assert isinstance(result.series_position, str)


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

    def test_no_asin_homebrew_imports_to_author(
        self,
        temp_staging: Path,
        temp_library: Path,
        empty_asin_index: dict[str, AsinEntry],
    ) -> None:
        """Books with homebrew pattern (Author - Title, no ASIN) go to Author/."""
        folder_name = "Author - Book Without ASIN"
        staging_folder = create_audiobook_folder(temp_staging, folder_name)

        result = import_single(
            staging_folder=staging_folder,
            library_root=temp_library,
            asin_index=empty_asin_index,
        )

        # Homebrew pattern routes to Author/ folder
        assert result.status == "success"
        assert result.asin is None
        assert "Author" in str(result.target_path)
        assert "Unknown" not in str(result.target_path)


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

    def test_add_skipped(self) -> None:
        """Add skipped result updates count."""
        batch = BatchImportResult()
        batch.add(ImportResult(Path("/a"), None, None, "skipped", "user skipped"))

        assert batch.skipped_count == 1
        assert batch.success_count == 0
        assert batch.failed_count == 0

    def test_tracks_all_results(self) -> None:
        """All results are stored in list."""
        batch = BatchImportResult()
        for i in range(5):
            batch.add(ImportResult(Path(f"/{i}"), Path(f"/t{i}"), f"B0{i}", "success"))

        assert len(batch.results) == 5


class TestErrorClasses:
    """Tests for custom error classes."""

    def test_duplicate_error(self) -> None:
        """Test DuplicateError has expected attributes."""
        from mamfast.abs.importer import DuplicateError

        err = DuplicateError("B0123456789", "/path/to/existing")
        assert err.asin == "B0123456789"
        assert err.existing_path == "/path/to/existing"
        assert "B0123456789" in str(err)
        assert "/path/to/existing" in str(err)

    def test_filesystem_mismatch_error(self) -> None:
        """Test FilesystemMismatchError can be raised."""
        from mamfast.abs.importer import FilesystemMismatchError

        err = FilesystemMismatchError("Staging and library are on different filesystems")
        assert isinstance(err, Exception)
        assert "filesystem" in str(err).lower() or "Staging" in str(err)


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


# =============================================================================
# Multi-File Protection Tests
# =============================================================================


class TestMultiFileProtection:
    """Tests for multi-file book data protection."""

    def test_multi_file_no_asin_preserves_filenames(self, tmp_path: Path) -> None:
        """Multi-file book without ASIN keeps original filenames to prevent data loss."""
        from mamfast.abs.importer import parse_mam_folder_name, rename_files_in_folder

        folder = tmp_path / "Unknown Multi-Part Book"
        folder.mkdir()

        # Create multiple audio files (simulating a multi-file audiobook)
        (folder / "Book - 01.m4b").touch()
        (folder / "Book - 02.m4b").touch()
        (folder / "Book - 03.m4b").touch()
        (folder / "cover.jpg").touch()

        parsed = parse_mam_folder_name(folder.name)
        assert parsed.asin is None  # No ASIN in name

        renamed = rename_files_in_folder(folder, parsed)

        # Should NOT rename any files - protects against data loss
        assert renamed == []
        # All original files should still exist
        assert (folder / "Book - 01.m4b").exists()
        assert (folder / "Book - 02.m4b").exists()
        assert (folder / "Book - 03.m4b").exists()

    def test_single_file_no_asin_can_rename(self, tmp_path: Path) -> None:
        """Single-file book without ASIN can still be renamed safely."""
        from mamfast.abs.importer import parse_mam_folder_name, rename_files_in_folder

        folder = tmp_path / "Unknown Single Book (2024) (Author)"
        folder.mkdir()

        # Single audio file is safe to rename
        (folder / "Original Name.m4b").touch()
        (folder / "cover.jpg").touch()

        parsed = parse_mam_folder_name(folder.name)
        assert parsed.asin is None  # No ASIN

        renamed = rename_files_in_folder(folder, parsed)

        # Single file can be renamed (no data loss risk)
        assert len(renamed) == 1
        assert renamed[0][0] == "Original Name.m4b"

    def test_multi_file_with_asin_can_rename(self, tmp_path: Path) -> None:
        """Multi-file book WITH ASIN can still rename (has unique identifier)."""
        from mamfast.abs.importer import parse_mam_folder_name, rename_files_in_folder

        folder = tmp_path / "Known Book (2024) (Author) {ASIN.B0ABCDEFGH}"
        folder.mkdir()

        # Multiple audio files but we have ASIN
        (folder / "Part 1.m4b").touch()
        (folder / "Part 2.m4b").touch()

        parsed = parse_mam_folder_name(folder.name)
        assert parsed.asin == "B0ABCDEFGH"

        renamed = rename_files_in_folder(folder, parsed)

        # With ASIN, normal rename logic applies
        # (Note: both files would get same name - but ASIN is the identifier)
        assert len(renamed) >= 1

    def test_multi_file_no_asin_dry_run_still_protects(self, tmp_path: Path) -> None:
        """Dry-run mode also protects multi-file books without ASIN."""
        from mamfast.abs.importer import parse_mam_folder_name, rename_files_in_folder

        folder = tmp_path / "Unknown Multi-Part"
        folder.mkdir()
        (folder / "Track 01.m4b").touch()
        (folder / "Track 02.m4b").touch()

        parsed = parse_mam_folder_name(folder.name)

        renamed = rename_files_in_folder(folder, parsed, dry_run=True)

        # Even in dry-run, should recognize this is unsafe
        assert renamed == []


# =============================================================================
# Phase 2: Unknown ASIN Policy Tests
# =============================================================================


class TestUnknownAsinClassification:
    """Tests for unknown ASIN classification logic."""

    def test_matches_homebrew_pattern_basic(self) -> None:
        """'Author - Title' pattern is detected as homebrew."""
        parsed = ParsedFolderName(
            author="Joe Smith",
            title="My Podcast",
            series=None,
            series_position=None,
            asin=None,
            year=None,
            narrator=None,
            ripper_tag=None,
            is_standalone=True,
        )
        assert matches_homebrew_pattern("Joe Smith - My Podcast", parsed) is True

    def test_matches_homebrew_pattern_with_underscore(self) -> None:
        """Homebrew pattern with underscores is detected."""
        parsed = ParsedFolderName(
            author="Joe Smith",
            title="My Podcast",
            series=None,
            series_position=None,
            asin=None,
            year=None,
            narrator=None,
            ripper_tag=None,
            is_standalone=True,
        )
        assert matches_homebrew_pattern("Joe_Smith_-_My_Podcast", parsed) is True

    def test_not_homebrew_with_asin(self) -> None:
        """Folder with ASIN is not homebrew even if pattern matches."""
        parsed = ParsedFolderName(
            author="Joe Smith",
            title="My Book",
            series=None,
            series_position=None,
            asin="B0123456789",
            year=None,
            narrator=None,
            ripper_tag=None,
            is_standalone=True,
        )
        assert matches_homebrew_pattern("Joe Smith - My Book", parsed) is False

    def test_not_homebrew_with_year(self) -> None:
        """Folder with year is not homebrew (likely MAM-style)."""
        parsed = ParsedFolderName(
            author="Joe Smith",
            title="My Book",
            series=None,
            series_position=None,
            asin=None,
            year="2024",
            narrator=None,
            ripper_tag=None,
            is_standalone=True,
        )
        assert matches_homebrew_pattern("Joe Smith - My Book (2024)", parsed) is False

    def test_classify_single_file_missing_asin(self, tmp_path: Path) -> None:
        """Single-file without ASIN is classified as MISSING_ASIN."""
        folder = tmp_path / "Unknown Book (2024)"
        folder.mkdir()
        (folder / "book.m4b").touch()

        parsed = parse_mam_folder_name(folder.name)
        ctx = classify_unknown_asin(folder, parsed)

        assert ctx.content_type == UnknownAsinContentType.MISSING_ASIN
        assert ctx.file_count == 1
        assert ctx.is_multi_file is False

    def test_classify_multi_file_missing_asin(self, tmp_path: Path) -> None:
        """Multi-file without ASIN is classified as MISSING_ASIN."""
        folder = tmp_path / "Unknown Book (2024)"
        folder.mkdir()
        (folder / "part1.m4b").touch()
        (folder / "part2.m4b").touch()
        (folder / "part3.m4b").touch()

        parsed = parse_mam_folder_name(folder.name)
        ctx = classify_unknown_asin(folder, parsed)

        assert ctx.content_type == UnknownAsinContentType.MISSING_ASIN
        assert ctx.file_count == 3
        assert ctx.is_multi_file is True

    def test_classify_homebrew_pattern(self, tmp_path: Path) -> None:
        """Homebrew pattern is classified as HOMEBREW."""
        folder = tmp_path / "Joe Smith - My Podcast"
        folder.mkdir()
        (folder / "episode1.mp3").touch()

        parsed = parse_mam_folder_name(folder.name)
        ctx = classify_unknown_asin(folder, parsed)

        assert ctx.content_type == UnknownAsinContentType.HOMEBREW
        assert ctx.file_count == 1


class TestUnknownAsinTargetPath:
    """Tests for unknown ASIN target path building."""

    def test_missing_asin_routes_to_unknown(self, tmp_path: Path) -> None:
        """MISSING_ASIN content routes to Unknown/ folder."""
        library_root = tmp_path / "library"
        library_root.mkdir()

        ctx = UnknownAsinContext(
            folder=tmp_path / "My Book (2024)",
            parsed=ParsedFolderName(
                author="Unknown",
                title="My Book",
                series=None,
                series_position=None,
                asin=None,
                year="2024",
                narrator=None,
                ripper_tag=None,
                is_standalone=True,
            ),
            content_type=UnknownAsinContentType.MISSING_ASIN,
            file_count=1,
            original_folder_name="My Book (2024)",
        )

        target = build_unknown_target_path(library_root, ctx)
        assert target == library_root / "Unknown" / "My Book (2024)"

    def test_homebrew_routes_to_author(self, tmp_path: Path) -> None:
        """HOMEBREW content routes to Author/Title (Author)."""
        library_root = tmp_path / "library"
        library_root.mkdir()

        ctx = UnknownAsinContext(
            folder=tmp_path / "Joe Smith - My Podcast",
            parsed=ParsedFolderName(
                author="Joe Smith",
                title="My Podcast",
                series=None,
                series_position=None,
                asin=None,
                year=None,
                narrator=None,
                ripper_tag=None,
                is_standalone=True,
            ),
            content_type=UnknownAsinContentType.HOMEBREW,
            file_count=1,
            original_folder_name="Joe Smith - My Podcast",
        )

        target = build_unknown_target_path(library_root, ctx)
        assert target == library_root / "Joe Smith" / "My Podcast (Joe Smith)"

    def test_unique_destination_no_collision(self, tmp_path: Path) -> None:
        """get_unique_destination returns same path when no collision."""
        path = tmp_path / "My Book"
        assert get_unique_destination(path) == path

    def test_unique_destination_with_collision(self, tmp_path: Path) -> None:
        """get_unique_destination appends suffix on collision."""
        (tmp_path / "My Book").mkdir()
        path = tmp_path / "My Book"

        unique = get_unique_destination(path)
        assert unique == tmp_path / "My Book_2"

    def test_unique_destination_multiple_collisions(self, tmp_path: Path) -> None:
        """get_unique_destination increments suffix."""
        (tmp_path / "My Book").mkdir()
        (tmp_path / "My Book_2").mkdir()
        (tmp_path / "My Book_3").mkdir()

        path = tmp_path / "My Book"
        unique = get_unique_destination(path)
        assert unique == tmp_path / "My Book_4"


class TestUnknownAsinSidecar:
    """Tests for unknown ASIN sidecar writing."""

    def test_sidecar_written_correctly(self, tmp_path: Path) -> None:
        """Sidecar is written with correct fields."""
        folder = tmp_path / "My Book"
        folder.mkdir()

        ctx = UnknownAsinContext(
            folder=tmp_path / "staging" / "My Book (2024)",
            parsed=ParsedFolderName(
                author="Test Author",
                title="My Book",
                series="My Series",
                series_position="1",
                asin=None,
                year="2024",
                narrator="Test Narrator",
                ripper_tag=None,
                is_standalone=False,
            ),
            content_type=UnknownAsinContentType.MISSING_ASIN,
            file_count=3,
            original_folder_name="My Book (2024)",
        )

        sidecar_path = write_unknown_asin_sidecar(folder, ctx, "import")

        assert sidecar_path is not None
        assert sidecar_path.exists()
        assert sidecar_path.name == "_mamfast_unknown_asin.json"

        data = json.loads(sidecar_path.read_text())
        assert data["content_type"] == "missing_asin"
        assert data["is_multi_file"] is True
        assert data["original_folder"] == "My Book (2024)"
        assert data["file_count"] == 3
        assert data["policy"] == "import"
        assert "imported_at" in data
        assert data["parsed"]["author"] == "Test Author"
        assert data["parsed"]["title"] == "My Book"
        assert data["parsed"]["series"] == "My Series"


class TestUnknownAsinPolicyHandler:
    """Tests for handle_unknown_asin with different policies."""

    def test_policy_skip_returns_skipped(self, tmp_path: Path) -> None:
        """Policy SKIP leaves folder in place and returns skipped."""
        staging_folder = tmp_path / "staging" / "Unknown Book"
        staging_folder.mkdir(parents=True)
        (staging_folder / "book.m4b").touch()

        library_root = tmp_path / "library"
        library_root.mkdir()

        ctx = classify_unknown_asin(staging_folder, parse_mam_folder_name(staging_folder.name))

        result = handle_unknown_asin(
            ctx,
            library_root,
            unknown_asin_policy=UnknownAsinPolicy.SKIP,
        )

        assert result.status == "skipped"
        assert "policy=skip" in result.error
        assert staging_folder.exists()  # Not moved

    def test_policy_quarantine_moves_to_quarantine_path(self, tmp_path: Path) -> None:
        """Policy QUARANTINE moves to quarantine path."""
        # Use a folder name that won't match homebrew pattern
        staging_folder = tmp_path / "staging" / "Unknown Book vol_01 (2024)"
        staging_folder.mkdir(parents=True)
        (staging_folder / "book.m4b").touch()

        library_root = tmp_path / "library"
        library_root.mkdir()

        quarantine = tmp_path / "quarantine"
        quarantine.mkdir()

        ctx = classify_unknown_asin(staging_folder, parse_mam_folder_name(staging_folder.name))

        result = handle_unknown_asin(
            ctx,
            library_root,
            unknown_asin_policy=UnknownAsinPolicy.QUARANTINE,
            quarantine_path=quarantine,
        )

        assert result.status == "success"
        assert result.target_path == quarantine / "Unknown Book vol_01 (2024)"
        assert not staging_folder.exists()  # Moved
        assert result.target_path.exists()  # Target folder exists
        # Has audio file (may be renamed)
        audio_files = list(result.target_path.glob("*.m4b"))
        assert len(audio_files) == 1
        # Sidecar written
        assert (result.target_path / "_mamfast_unknown_asin.json").exists()

    def test_policy_quarantine_requires_path(self, tmp_path: Path) -> None:
        """Policy QUARANTINE fails without quarantine_path."""
        staging_folder = tmp_path / "staging" / "Unknown Book"
        staging_folder.mkdir(parents=True)
        (staging_folder / "book.m4b").touch()

        library_root = tmp_path / "library"
        library_root.mkdir()

        ctx = classify_unknown_asin(staging_folder, parse_mam_folder_name(staging_folder.name))

        result = handle_unknown_asin(
            ctx,
            library_root,
            unknown_asin_policy=UnknownAsinPolicy.QUARANTINE,
            quarantine_path=None,  # Missing!
        )

        assert result.status == "failed"
        assert "quarantine_path" in result.error

    def test_policy_import_missing_asin_to_unknown(self, tmp_path: Path) -> None:
        """Policy IMPORT routes MISSING_ASIN to Unknown/."""
        # Use a folder name that won't match homebrew pattern (has year)
        staging_folder = tmp_path / "staging" / "Unknown Book vol_01 (2024)"
        staging_folder.mkdir(parents=True)
        (staging_folder / "book.m4b").touch()

        library_root = tmp_path / "library"
        library_root.mkdir()

        ctx = classify_unknown_asin(staging_folder, parse_mam_folder_name(staging_folder.name))

        result = handle_unknown_asin(
            ctx,
            library_root,
            unknown_asin_policy=UnknownAsinPolicy.IMPORT,
        )

        assert result.status == "success"
        assert result.target_path == library_root / "Unknown" / "Unknown Book vol_01 (2024)"
        assert not staging_folder.exists()  # Moved
        assert result.target_path.exists()  # Target folder exists
        # Has audio file (may be renamed)
        audio_files = list(result.target_path.glob("*.m4b"))
        assert len(audio_files) == 1
        # Sidecar written
        assert (result.target_path / "_mamfast_unknown_asin.json").exists()

    def test_policy_import_homebrew_to_author(self, tmp_path: Path) -> None:
        """Policy IMPORT routes HOMEBREW to Author/."""
        staging_folder = tmp_path / "staging" / "Joe Smith - My Podcast"
        staging_folder.mkdir(parents=True)
        (staging_folder / "episode.mp3").touch()

        library_root = tmp_path / "library"
        library_root.mkdir()

        ctx = classify_unknown_asin(staging_folder, parse_mam_folder_name(staging_folder.name))

        result = handle_unknown_asin(
            ctx,
            library_root,
            unknown_asin_policy=UnknownAsinPolicy.IMPORT,
        )

        assert result.status == "success"
        assert "Joe Smith" in str(result.target_path)
        assert not staging_folder.exists()  # Moved

    def test_dry_run_does_not_move(self, tmp_path: Path) -> None:
        """Dry-run mode does not actually move files."""
        staging_folder = tmp_path / "staging" / "Unknown Book"
        staging_folder.mkdir(parents=True)
        (staging_folder / "book.m4b").touch()

        library_root = tmp_path / "library"
        library_root.mkdir()

        ctx = classify_unknown_asin(staging_folder, parse_mam_folder_name(staging_folder.name))

        result = handle_unknown_asin(
            ctx,
            library_root,
            unknown_asin_policy=UnknownAsinPolicy.IMPORT,
            dry_run=True,
        )

        assert result.status == "success"
        assert staging_folder.exists()  # Still there!
        assert not result.target_path.exists()


class TestImportSingleWithUnknownAsinPolicy:
    """Tests for import_single integration with unknown ASIN policy."""

    def test_import_single_no_asin_uses_policy(self, tmp_path: Path) -> None:
        """import_single delegates to unknown ASIN handler when no ASIN."""
        staging_folder = tmp_path / "staging" / "Unknown Book (2024)"
        staging_folder.mkdir(parents=True)
        (staging_folder / "book.m4b").touch()

        library_root = tmp_path / "library"
        library_root.mkdir()

        result = import_single(
            staging_folder=staging_folder,
            library_root=library_root,
            asin_index={},
            unknown_asin_policy=UnknownAsinPolicy.IMPORT,
        )

        assert result.status == "success"
        assert result.asin is None
        assert "Unknown" in str(result.target_path)

    def test_import_single_no_asin_skip_policy(self, tmp_path: Path) -> None:
        """import_single respects SKIP policy."""
        staging_folder = tmp_path / "staging" / "Unknown Book"
        staging_folder.mkdir(parents=True)
        (staging_folder / "book.m4b").touch()

        library_root = tmp_path / "library"
        library_root.mkdir()

        result = import_single(
            staging_folder=staging_folder,
            library_root=library_root,
            asin_index={},
            unknown_asin_policy=UnknownAsinPolicy.SKIP,
        )

        assert result.status == "skipped"
        assert staging_folder.exists()  # Not moved

    def test_import_single_with_asin_ignores_unknown_policy(self, tmp_path: Path) -> None:
        """import_single uses normal path when ASIN is present."""
        # Use valid 10-char ASIN format (B0 + 8 alphanumeric)
        staging_folder = tmp_path / "staging" / "Author - My Book (2024) {ASIN.B0ABCD1234}"
        staging_folder.mkdir(parents=True)
        (staging_folder / "book.m4b").touch()

        library_root = tmp_path / "library"
        library_root.mkdir()

        result = import_single(
            staging_folder=staging_folder,
            library_root=library_root,
            asin_index={},  # No duplicate
            unknown_asin_policy=UnknownAsinPolicy.SKIP,  # Should be ignored
        )

        assert result.status == "success"
        assert result.asin == "B0ABCD1234"
        assert "Unknown" not in str(result.target_path)  # Normal path, not Unknown/


class TestZeroAudioFiles:
    """Tests for edge case: folder with zero audio files."""

    def test_classify_zero_audio_files(self, tmp_path: Path) -> None:
        """Folder with only sidecars has file_count=0."""
        folder = tmp_path / "Empty Book"
        folder.mkdir()
        (folder / "cover.jpg").touch()
        (folder / "notes.pdf").touch()

        parsed = parse_mam_folder_name(folder.name)
        ctx = classify_unknown_asin(folder, parsed)

        assert ctx.file_count == 0
        assert ctx.is_multi_file is False


class TestMixedAudioFormats:
    """Tests for folders with mixed audio formats."""

    def test_mixed_formats_counted_as_multi_file(self, tmp_path: Path) -> None:
        """Different audio formats all count toward file_count."""
        folder = tmp_path / "Mixed Format Book"
        folder.mkdir()
        (folder / "part1.m4b").touch()
        (folder / "part2.mp3").touch()
        (folder / "part3.flac").touch()

        parsed = parse_mam_folder_name(folder.name)
        ctx = classify_unknown_asin(folder, parsed)

        assert ctx.file_count == 3
        assert ctx.is_multi_file is True


class TestGetUniqueDestinationBounded:
    """Tests for bounded loop in get_unique_destination."""

    def test_unique_destination_finds_available_suffix(self, tmp_path: Path) -> None:
        """get_unique_destination finds next available suffix."""
        base = tmp_path / "My Book"
        base.mkdir()
        (tmp_path / "My Book_2").mkdir()
        (tmp_path / "My Book_3").mkdir()

        result = get_unique_destination(base)

        assert result == tmp_path / "My Book_4"

    def test_unique_destination_returns_base_if_no_collision(self, tmp_path: Path) -> None:
        """get_unique_destination returns base path if it doesn't exist."""
        base = tmp_path / "New Book"

        result = get_unique_destination(base)

        assert result == base


class TestClassifyUnknownAsinErrorHandling:
    """Tests for error handling in classify_unknown_asin."""

    def test_classify_deleted_folder_returns_zero_files(self, tmp_path: Path) -> None:
        """Deleted folder during classification returns file_count=0."""
        folder = tmp_path / "Deleted Book"
        folder.mkdir()
        (folder / "book.m4b").touch()

        parsed = parse_mam_folder_name(folder.name)

        # Delete folder after parsing but before classify
        import shutil

        shutil.rmtree(folder)

        # Should not raise, returns 0 files
        ctx = classify_unknown_asin(folder, parsed)
        assert ctx.file_count == 0
