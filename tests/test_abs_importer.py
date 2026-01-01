"""Tests for abs/importer.py - Audiobookshelf import functionality."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from shelfr.abs.asin import AsinEntry
from shelfr.abs.importer import (
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
    remove_ignored_files,
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

        from shelfr.abs.importer import enrich_from_audnex

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
                "name": "Epic Adventure",
                "position": 5,  # int, not string!
            },
        }

        with patch("shelfr.abs.importer.fetch_audnex_book", return_value=(mock_audnex_data, "us")):
            result, _, region = enrich_from_audnex(parsed, "B0TEST1234")

        assert result.series == "Epic Adventure"
        assert result.series_position == "5"  # Must be string
        assert isinstance(result.series_position, str)
        assert region == "us"

    def test_series_position_float_coerced_to_string(self) -> None:
        """Handle float position like 1.5 (sub-books)."""
        from unittest.mock import patch

        from shelfr.abs.importer import enrich_from_audnex

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
                "name": "Epic Adventure",
                "position": 1.5,  # float
            },
        }

        with patch("shelfr.abs.importer.fetch_audnex_book", return_value=(mock_audnex_data, "us")):
            result, _, region = enrich_from_audnex(parsed, "B0TEST1234")

        assert result.series == "Epic Adventure"
        assert result.series_position == "1.5"
        assert isinstance(result.series_position, str)
        assert region == "us"

    def test_series_position_none_handled(self) -> None:
        """Handle None position gracefully."""
        from unittest.mock import patch

        from shelfr.abs.importer import enrich_from_audnex

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
                "name": "Epic Adventure",
                "position": None,  # explicitly None
            },
        }

        with patch("shelfr.abs.importer.fetch_audnex_book", return_value=(mock_audnex_data, "us")):
            result, _, region = enrich_from_audnex(parsed, "B0TEST1234")

        assert result.series == "Epic Adventure"
        assert result.series_position is None  # Should remain None
        assert region == "us"

    def test_subtitle_series_position_coerced(self) -> None:
        """Subtitle fallback also coerces position to string."""
        from unittest.mock import patch

        from shelfr.abs.importer import enrich_from_audnex

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
            "title": "Test Book",
            "subtitle": "Epic Adventure, Book 3",
        }

        with patch("shelfr.abs.importer.fetch_audnex_book", return_value=(mock_audnex_data, "us")):
            result, _, region = enrich_from_audnex(parsed, "B0TEST1234")

        assert result.series == "Epic Adventure"
        assert result.series_position == "3"
        assert isinstance(result.series_position, str)
        assert region == "us"

    def test_series_extracted_from_title_pattern(self) -> None:
        """Extract series from title when no seriesPrimary or subtitle available.

        Bug fix: "A Most Unlikely Hero, Volume 8" should extract series from title.
        """
        from unittest.mock import patch

        from shelfr.abs.importer import enrich_from_audnex

        parsed = ParsedFolderName(
            author="Unknown",
            title="A Most Unlikely Hero, Volume 8",
            series=None,
            series_position=None,
            asin="B0FZLQ9LQD",
            year=None,
            narrator=None,
            ripper_tag=None,
            is_standalone=True,
        )

        # Real-world case: Audnex has title but no seriesPrimary
        mock_audnex_data = {
            "title": "A Most Unlikely Hero, Volume 8",
            "authors": [{"name": "Brandon Varnell"}],
            "releaseDate": "2025-11-04T00:00:00.000Z",
            # No seriesPrimary, no parseable subtitle
        }

        with patch("shelfr.abs.importer.fetch_audnex_book", return_value=(mock_audnex_data, "us")):
            result, _, region = enrich_from_audnex(parsed, "B0FZLQ9LQD")

        assert result.author == "Brandon Varnell"
        assert result.series == "A Most Unlikely Hero"
        assert result.series_position == "8"
        assert result.is_standalone is False
        assert region == "us"

    def test_series_extracted_from_title_vol_dot_pattern(self) -> None:
        """Extract series from title with 'Vol.' notation."""
        from unittest.mock import patch

        from shelfr.abs.importer import enrich_from_audnex

        parsed = ParsedFolderName(
            author="Unknown",
            title="Epic Adventure Vol. 5",
            series=None,
            series_position=None,
            asin="B012345678",
            year=None,
            narrator=None,
            ripper_tag=None,
            is_standalone=True,
        )

        mock_audnex_data = {
            "title": "Epic Adventure Vol. 5",
            "authors": [{"name": "Author Name"}],
        }

        with patch("shelfr.abs.importer.fetch_audnex_book", return_value=(mock_audnex_data, "us")):
            result, _, region = enrich_from_audnex(parsed, "B012345678")

        assert result.series == "Epic Adventure"
        assert result.series_position == "5"
        assert region == "us"

    def test_series_not_extracted_when_series_primary_exists(self) -> None:
        """Don't extract from title if seriesPrimary already provided series."""
        from unittest.mock import patch

        from shelfr.abs.importer import enrich_from_audnex

        parsed = ParsedFolderName(
            author="Unknown",
            title="Book Title Volume 3",
            series=None,
            series_position=None,
            asin="B012345678",
            year=None,
            narrator=None,
            ripper_tag=None,
            is_standalone=True,
        )

        # seriesPrimary takes precedence - don't re-extract from title
        mock_audnex_data = {
            "title": "Book Title Volume 3",
            "seriesPrimary": {
                "name": "Actual Series Name",
                "position": 3,
            },
        }

        with patch("shelfr.abs.importer.fetch_audnex_book", return_value=(mock_audnex_data, "us")):
            result, _, region = enrich_from_audnex(parsed, "B012345678")

        # Should use seriesPrimary, NOT extract from title
        assert result.series == "Actual Series Name"
        assert result.series_position == "3"
        assert region == "us"

    def test_audnex_series_overrides_incorrect_parsed_series(self) -> None:
        """Audnex series should override incorrectly parsed series from folder name.

        Bug fix: Folder names like "The Rising of the Shield Hero Volume 04 vol_04"
        incorrectly parse series as "The Rising of the Shield Hero Volume 04".
        Audnex data with correct series "Rising of the Shield Hero" should override.
        """
        from unittest.mock import patch

        from shelfr.abs.importer import enrich_from_audnex

        parsed = ParsedFolderName(
            author="Aneko Yusagi",
            title="The Rising of the Shield Hero Volume 04",
            series="The Rising of the Shield Hero Volume 04",  # Incorrectly includes Volume
            series_position="04",
            asin="B0BN2GGTCK",
            year="2022",
            narrator=None,
            ripper_tag="H2OKing",
            is_standalone=False,
        )

        # Audnex has the correct series name without "Volume 04"
        mock_audnex_data = {
            "title": "The Rising of the Shield Hero, Volume 04",
            "seriesPrimary": {
                "name": "Rising of the Shield Hero",  # Correct!
                "position": "4",
            },
        }

        with patch("shelfr.abs.importer.fetch_audnex_book", return_value=(mock_audnex_data, "us")):
            result, _, region = enrich_from_audnex(parsed, "B0BN2GGTCK")

        # Audnex should override the incorrect parsed series
        assert result.series == "The Rising of the Shield Hero"  # "The" inherited
        assert result.series_position == "4"
        assert result.is_standalone is False
        assert region == "us"


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

    def test_audnex_series_preferred_over_staging_path(self, temp_library: Path) -> None:
        """Audnex-enriched series should be preferred over staging path series.

        Bug fix: "Black Summoner Black Summoner" in staging path should not
        override the correct "Black Summoner" from Audnex.
        """
        # Parsed data has been enriched from Audnex with correct series
        parsed = ParsedFolderName(
            author="Doufu Mayoi",
            title="The False Champions",
            series="Black Summoner",  # Correct from Audnex
            series_position="2",
            asin="B0C5NSRFWC",
            year="2023",
            narrator=None,
            ripper_tag="H2OKing",
            is_standalone=False,
        )

        # Staging path has incorrect doubled series name
        staging_folder = Path(
            "/staging/Doufu Mayoi/Black Summoner Black Summoner/The False Champions vol_02"
        )
        staging_root = Path("/staging")

        target = build_target_path(temp_library, parsed, staging_folder, staging_root=staging_root)

        # Should use Audnex series "Black Summoner", not staging "Black Summoner Black Summoner"
        assert target.parent == temp_library / "Doufu Mayoi" / "Black Summoner"
        assert "Black Summoner Black Summoner" not in str(target)
        assert "The False Champions" in target.name or "Black Summoner vol_02" in target.name

    def test_staging_series_used_as_fallback(self, temp_library: Path) -> None:
        """Staging path series should be used when parsed.series is None."""
        parsed = ParsedFolderName(
            author="Author Name",
            title="Book Title",
            series=None,  # No series from Audnex
            series_position=None,
            asin="B012345678",
            year="2024",
            narrator=None,
            ripper_tag=None,
            is_standalone=True,
        )

        # Staging path has series structure
        # Note: avoid using "My Series" as clean_series_name() would strip "Series" suffix
        staging_folder = Path("/staging/Author Name/Epic Adventure/Book Title vol_01")
        staging_root = Path("/staging")

        target = build_target_path(temp_library, parsed, staging_folder, staging_root=staging_root)

        # Should use staging series as fallback
        assert target.parent == temp_library / "Author Name" / "Epic Adventure"


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
        # Add existing book to index with a real folder to avoid stale-path skip
        existing = temp_library / "Author" / "Existing Book [B08G9PRS1K]"
        existing.mkdir(parents=True)
        (existing / "existing.m4b").write_text("old")

        mock_asin_index["B08G9PRS1K"] = AsinEntry(
            asin="B08G9PRS1K",
            path=str(existing),
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
        # Add one existing book to index with a real folder
        existing = temp_library / "Author" / "Book 2 [B000000002]"
        existing.mkdir(parents=True)
        (existing / "existing.m4b").write_text("old")

        mock_asin_index["B000000002"] = AsinEntry(
            asin="B000000002",
            path=str(existing),
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

    def test_batch_progress_callback(
        self, temp_staging: Path, temp_library: Path, empty_asin_index: dict[str, AsinEntry]
    ) -> None:
        """Progress callback is called for each book."""
        folders = [
            create_audiobook_folder(temp_staging, f"Author - Book {i} [B0ABC{i:05d}]")
            for i in range(1, 4)
        ]

        progress_calls: list[tuple[int, int, Path]] = []

        def track_progress(current: int, total: int, folder: Path) -> None:
            progress_calls.append((current, total, folder))

        result = import_batch(
            staging_folders=folders,
            library_root=temp_library,
            asin_index=empty_asin_index,
            progress_callback=track_progress,
        )

        assert result.success_count == 3
        assert len(progress_calls) == 3
        # Check progress values
        assert progress_calls[0] == (0, 3, folders[0])
        assert progress_calls[1] == (1, 3, folders[1])
        assert progress_calls[2] == (2, 3, folders[2])

    def test_batch_progress_callback_none(
        self, temp_staging: Path, temp_library: Path, empty_asin_index: dict[str, AsinEntry]
    ) -> None:
        """Batch works without progress callback (backward compatible)."""
        folders = [create_audiobook_folder(temp_staging, "Author - Book [B0TESTBOOK1]")]

        # Should not raise when callback is None
        result = import_batch(
            staging_folders=folders,
            library_root=temp_library,
            asin_index=empty_asin_index,
            progress_callback=None,
        )

        assert result.success_count == 1


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
        from shelfr.abs.importer import DuplicateError

        err = DuplicateError("B0123456789", "/path/to/existing")
        assert err.asin == "B0123456789"
        assert err.existing_path == "/path/to/existing"
        assert "B0123456789" in str(err)
        assert "/path/to/existing" in str(err)

    def test_filesystem_mismatch_error(self) -> None:
        """Test FilesystemMismatchError can be raised."""
        from shelfr.abs.importer import FilesystemMismatchError

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

    def test_multi_file_with_track_numbers_renames_safely(self, tmp_path: Path) -> None:
        """Multi-file book with track numbers gets renamed with track suffix preserved."""
        from shelfr.abs.importer import parse_mam_folder_name, rename_files_in_folder

        folder = tmp_path / "Unknown Multi-Part Book"
        folder.mkdir()

        # Create multiple audio files with track numbers
        (folder / "Book - 01.m4b").touch()
        (folder / "Book - 02.m4b").touch()
        (folder / "Book - 03.m4b").touch()
        (folder / "cover.jpg").touch()

        parsed = parse_mam_folder_name(folder.name)
        assert parsed.asin is None  # No ASIN in name

        renamed = rename_files_in_folder(folder, parsed)

        # Multi-file books WITH track numbers get renamed (track suffix preserved)
        assert len(renamed) == 3
        new_names = sorted([r[1] for r in renamed])
        assert " - 01.m4b" in new_names[0]
        assert " - 02.m4b" in new_names[1]
        assert " - 03.m4b" in new_names[2]

    def test_single_file_no_asin_can_rename(self, tmp_path: Path) -> None:
        """Single-file book without ASIN can still be renamed safely."""
        from shelfr.abs.importer import parse_mam_folder_name, rename_files_in_folder

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

    def test_multi_file_with_track_numbers_renamed(self, tmp_path: Path) -> None:
        """Multi-file book with track numbers gets renamed with track suffix preserved."""
        from shelfr.abs.importer import parse_mam_folder_name, rename_files_in_folder

        folder = tmp_path / "Known Book (2024) (Author) {ASIN.B0ABCDEFGH}"
        folder.mkdir()

        # Multiple audio files with track numbers
        (folder / "Old Name - 01.m4b").touch()
        (folder / "Old Name - 02.m4b").touch()
        (folder / "Old Name - 03.m4b").touch()

        parsed = parse_mam_folder_name(folder.name)
        assert parsed.asin == "B0ABCDEFGH"

        renamed = rename_files_in_folder(folder, parsed)

        # Multi-file books with track numbers get renamed with track suffix preserved
        assert len(renamed) == 3
        # Check that track numbers are preserved and padded
        new_names = sorted([r[1] for r in renamed])
        assert " - 01.m4b" in new_names[0]
        assert " - 02.m4b" in new_names[1]
        assert " - 03.m4b" in new_names[2]

    def test_multi_file_without_track_numbers_preserved(self, tmp_path: Path) -> None:
        """Multi-file book without track numbers preserves original filenames."""
        from shelfr.abs.importer import parse_mam_folder_name, rename_files_in_folder

        folder = tmp_path / "Known Book (2024) (Author) {ASIN.B0ABCDEFGH}"
        folder.mkdir()

        # Multiple audio files WITHOUT track numbers - can't safely rename
        (folder / "Part One.m4b").touch()
        (folder / "Part Two.m4b").touch()

        parsed = parse_mam_folder_name(folder.name)

        renamed = rename_files_in_folder(folder, parsed)

        # No track numbers found - files preserved to prevent data loss
        assert renamed == []

    def test_multi_file_dry_run_shows_renames(self, tmp_path: Path) -> None:
        """Dry-run mode shows planned renames for multi-file books with track numbers."""
        from shelfr.abs.importer import parse_mam_folder_name, rename_files_in_folder

        folder = tmp_path / "Unknown Multi-Part"
        folder.mkdir()
        (folder / "Track 01.m4b").touch()
        (folder / "Track 02.m4b").touch()

        parsed = parse_mam_folder_name(folder.name)

        renamed = rename_files_in_folder(folder, parsed, dry_run=True)

        # Dry-run shows what would be renamed (track numbers preserved)
        assert len(renamed) == 2


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
        assert sidecar_path.name == "_shelfr_unknown_asin.json"

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
        assert result.error is not None
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
        assert result.target_path is not None
        assert result.target_path == quarantine / "Unknown Book vol_01 (2024)"
        assert not staging_folder.exists()  # Moved
        assert result.target_path.exists()  # Target folder exists
        # Has audio file (may be renamed)
        audio_files = list(result.target_path.glob("*.m4b"))
        assert len(audio_files) == 1
        # Sidecar written
        assert (result.target_path / "_shelfr_unknown_asin.json").exists()

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
        assert result.error is not None
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
        assert result.target_path is not None
        assert result.target_path == library_root / "Unknown" / "Unknown Book vol_01 (2024)"
        assert not staging_folder.exists()  # Moved
        assert result.target_path.exists()  # Target folder exists
        # Has audio file (may be renamed)
        audio_files = list(result.target_path.glob("*.m4b"))
        assert len(audio_files) == 1
        # Sidecar written
        assert (result.target_path / "_shelfr_unknown_asin.json").exists()

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
        assert result.target_path is not None
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


# =============================================================================
# Tests: Trumping Integration
# =============================================================================


class TestImportSingleWithTrumping:
    """Tests for import_single with trumping enabled."""

    def test_trumping_disabled_by_default(
        self, temp_staging: Path, temp_library: Path, mock_asin_index: dict[str, AsinEntry]
    ) -> None:
        """Trumping does not run when trump_prefs is None."""
        # Create incoming book with same ASIN as existing
        existing = temp_library / "Andy Weir" / "Project Hail Mary"
        existing.mkdir(parents=True)
        (existing / "existing.m4b").write_text("old")

        mock_asin_index["B08G9PRS1K"] = AsinEntry(
            asin="B08G9PRS1K",
            path=str(existing),
            library_item_id="li_existing1",
            title="Project Hail Mary",
            author="Andy Weir",
        )

        folder = create_audiobook_folder(
            temp_staging,
            "Andy Weir - Project Hail Mary (2021) {ASIN.B08G9PRS1K}",
        )

        result = import_single(
            staging_folder=folder,
            library_root=temp_library,
            asin_index=mock_asin_index,
            duplicate_policy="skip",
            trump_prefs=None,  # Disabled
            dry_run=True,
        )

        # Should be duplicate, not trumped
        assert result.status == "duplicate"

    def test_trumping_enabled_but_disabled_in_prefs(
        self, temp_staging: Path, temp_library: Path, mock_asin_index: dict[str, AsinEntry]
    ) -> None:
        """Trumping does not run when TrumpPrefs.enabled is False."""
        from shelfr.abs.trumping import TrumpPrefs

        existing = temp_library / "Andy Weir" / "Project Hail Mary"
        existing.mkdir(parents=True)
        (existing / "existing.m4b").write_text("old")

        mock_asin_index["B08G9PRS1K"] = AsinEntry(
            asin="B08G9PRS1K",
            path=str(existing),
            library_item_id="li_existing1",
            title="Project Hail Mary",
            author="Andy Weir",
        )

        folder = create_audiobook_folder(
            temp_staging,
            "Andy Weir - Project Hail Mary (2021) {ASIN.B08G9PRS1K}",
        )

        prefs = TrumpPrefs(enabled=False)
        result = import_single(
            staging_folder=folder,
            library_root=temp_library,
            asin_index=mock_asin_index,
            duplicate_policy="skip",
            trump_prefs=prefs,
            dry_run=True,
        )

        # Should be duplicate, not trumped
        assert result.status == "duplicate"

    def test_trumping_skip_for_non_duplicate(
        self, temp_staging: Path, temp_library: Path, empty_asin_index: dict[str, AsinEntry]
    ) -> None:
        """Trumping is not triggered for new books (no existing duplicate)."""
        from shelfr.abs.trumping import TrumpPrefs

        folder = create_audiobook_folder(
            temp_staging,
            "New Author - New Book (2024) {ASIN.B0NEWBOOK1}",
        )

        prefs = TrumpPrefs(enabled=True, archive_root=Path("/archive"))
        result = import_single(
            staging_folder=folder,
            library_root=temp_library,
            asin_index=empty_asin_index,
            duplicate_policy="skip",
            trump_prefs=prefs,
            dry_run=True,
        )

        # Should succeed normally, no trumping involved
        assert result.status == "success"

    def test_trumping_multi_file_skips_to_duplicate_policy(
        self, temp_staging: Path, temp_library: Path, tmp_path: Path
    ) -> None:
        """Multi-file layouts skip trumping and fall through to duplicate_policy."""
        from shelfr.abs.trumping import TrumpPrefs

        # Create existing multi-file book
        existing_folder = tmp_path / "existing_audiobooks" / "Andy Weir" / "Project Hail Mary"
        existing_folder.mkdir(parents=True)
        (existing_folder / "cd1.mp3").touch()
        (existing_folder / "cd2.mp3").touch()

        asin_index = {
            "B08G9PRS1K": AsinEntry(
                asin="B08G9PRS1K",
                path=str(existing_folder),
                library_item_id="li_multi",
                title="Project Hail Mary",
                author="Andy Weir",
            ),
        }

        # Create incoming single-file book with same ASIN
        folder = create_audiobook_folder(
            temp_staging,
            "Andy Weir - Project Hail Mary (2021) {ASIN.B08G9PRS1K}",
        )

        prefs = TrumpPrefs(enabled=True, archive_root=Path("/archive"))
        result = import_single(
            staging_folder=folder,
            library_root=temp_library,
            asin_index=asin_index,
            duplicate_policy="skip",
            trump_prefs=prefs,
            dry_run=True,
        )

        # Multi-file existing → trumping skipped → duplicate_policy=skip
        assert result.status == "duplicate"

    def test_trumping_stale_index_missing_folder_skips_trump(
        self,
        temp_staging: Path,
        temp_library: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Stale ABS index entry should warn and proceed instead of crashing."""
        from shelfr.abs.trumping import TrumpPrefs

        missing_path = temp_library / "Ghost Author" / "Missing Book"

        asin_index = {
            "B0MISSING1": AsinEntry(
                asin="B0MISSING1",
                path=str(missing_path),
                library_item_id="li_missing",
                title="Missing Book",
                author="Ghost Author",
            ),
        }

        folder = create_audiobook_folder(
            temp_staging,
            "Ghost Author - The Return (2024) {ASIN.B0MISSING1}",
        )

        prefs = TrumpPrefs(enabled=True, archive_root=Path("/archive"))

        with caplog.at_level(logging.WARNING):
            result = import_single(
                staging_folder=folder,
                library_root=temp_library,
                asin_index=asin_index,
                duplicate_policy="skip",
                trump_prefs=prefs,
                dry_run=True,
            )

        assert result.status == "success"
        assert "folder is missing" in caplog.text


class TestBatchImportResultTrumpCounts:
    """Tests for BatchImportResult trumping statistics."""

    def test_trump_replaced_count(self) -> None:
        """trump_replaced status updates both trump_replaced_count and success_count."""
        batch = BatchImportResult()
        result = ImportResult(
            staging_path=Path("/staging/book"),
            target_path=Path("/lib/book"),
            asin="B0TEST",
            status="trump_replaced",
        )
        batch.add(result)

        assert batch.trump_replaced_count == 1
        assert batch.success_count == 1  # Also counts as success

    def test_trump_kept_existing_count(self) -> None:
        """trump_kept_existing status updates trump_kept_existing_count and skipped_count."""
        batch = BatchImportResult()
        result = ImportResult(
            staging_path=Path("/staging/book"),
            target_path=None,
            asin="B0TEST",
            status="trump_kept_existing",
        )
        batch.add(result)

        assert batch.trump_kept_existing_count == 1
        assert batch.skipped_count == 1  # Also counts as skipped

    def test_trump_rejected_count(self) -> None:
        """trump_rejected status updates trump_rejected_count and skipped_count."""
        batch = BatchImportResult()
        result = ImportResult(
            staging_path=Path("/staging/book"),
            target_path=None,
            asin="B0TEST",
            status="trump_rejected",
        )
        batch.add(result)

        assert batch.trump_rejected_count == 1
        assert batch.skipped_count == 1  # Also counts as skipped

    def test_mixed_results_with_trumping(self) -> None:
        """Mixed batch with trumping and non-trumping results."""
        batch = BatchImportResult()

        # Normal success
        batch.add(ImportResult(Path("/s/1"), Path("/l/1"), "A1", "success"))
        # Trump replaced
        batch.add(ImportResult(Path("/s/2"), Path("/l/2"), "A2", "trump_replaced"))
        # Trump kept existing
        batch.add(ImportResult(Path("/s/3"), None, "A3", "trump_kept_existing"))
        # Normal duplicate
        batch.add(ImportResult(Path("/s/4"), None, "A4", "duplicate"))
        # Trump rejected
        batch.add(ImportResult(Path("/s/5"), None, "A5", "trump_rejected"))

        assert batch.success_count == 2  # 1 normal + 1 trump_replaced
        assert batch.skipped_count == 2  # trump_kept_existing + trump_rejected
        assert batch.duplicate_count == 1
        assert batch.trump_replaced_count == 1
        assert batch.trump_kept_existing_count == 1
        assert batch.trump_rejected_count == 1


# =============================================================================
# Tests for remove_ignored_files
# =============================================================================


class TestRemoveIgnoredFiles:
    """Tests for remove_ignored_files function."""

    def test_empty_patterns_does_nothing(self, tmp_path: Path) -> None:
        """Empty pattern list doesn't remove anything."""
        folder = tmp_path / "book"
        folder.mkdir()
        (folder / "audio.m4b").touch()
        (folder / "metadata.json").touch()

        removed = remove_ignored_files(folder, [])
        assert removed == []
        assert (folder / "audio.m4b").exists()
        assert (folder / "metadata.json").exists()

    def test_simple_extension_match(self, tmp_path: Path) -> None:
        """Simple extension '.json' matches all .json files."""
        folder = tmp_path / "book"
        folder.mkdir()
        (folder / "audio.m4b").touch()
        (folder / "metadata.json").touch()
        (folder / "cover.jpg").touch()

        removed = remove_ignored_files(folder, [".json"])
        assert "metadata.json" in removed
        assert len(removed) == 1
        assert (folder / "audio.m4b").exists()
        assert not (folder / "metadata.json").exists()
        assert (folder / "cover.jpg").exists()

    def test_glob_pattern_match(self, tmp_path: Path) -> None:
        """Glob pattern '*.metadata.json' only matches that suffix."""
        folder = tmp_path / "book"
        folder.mkdir()
        (folder / "audio.m4b").touch()
        (folder / "Title.metadata.json").touch()
        (folder / "config.json").touch()

        removed = remove_ignored_files(folder, ["*.metadata.json"])
        assert "Title.metadata.json" in removed
        assert len(removed) == 1
        assert (folder / "audio.m4b").exists()
        assert not (folder / "Title.metadata.json").exists()
        assert (folder / "config.json").exists()  # Regular .json not matched

    def test_multiple_patterns(self, tmp_path: Path) -> None:
        """Multiple patterns can be combined."""
        folder = tmp_path / "book"
        folder.mkdir()
        (folder / "audio.m4b").touch()
        (folder / "Title.metadata.json").touch()
        (folder / "config.json").touch()
        (folder / "notes.txt").touch()

        removed = remove_ignored_files(folder, ["*.metadata.json", ".txt"])
        assert "Title.metadata.json" in removed
        assert "notes.txt" in removed
        assert len(removed) == 2

    def test_case_insensitive_matching(self, tmp_path: Path) -> None:
        """Pattern matching is case-insensitive."""
        folder = tmp_path / "book"
        folder.mkdir()
        (folder / "Title.METADATA.JSON").touch()
        (folder / "Config.Json").touch()

        removed = remove_ignored_files(folder, ["*.metadata.json", ".json"])
        assert len(removed) == 2

    def test_dry_run_doesnt_remove(self, tmp_path: Path) -> None:
        """Dry run returns files but doesn't actually remove them."""
        folder = tmp_path / "book"
        folder.mkdir()
        (folder / "metadata.json").touch()

        removed = remove_ignored_files(folder, [".json"], dry_run=True)
        assert "metadata.json" in removed
        assert (folder / "metadata.json").exists()  # Still there

    def test_skips_directories(self, tmp_path: Path) -> None:
        """Directories are not matched/removed even if name matches."""
        folder = tmp_path / "book"
        folder.mkdir()
        subdir = folder / "subdir.json"
        subdir.mkdir()
        (folder / "file.json").touch()

        removed = remove_ignored_files(folder, [".json"])
        assert "file.json" in removed
        assert len(removed) == 1
        assert subdir.exists()  # Directory not removed

    def test_real_world_metadata_json(self, tmp_path: Path) -> None:
        """Real-world scenario: remove .metadata.json but keep other .json."""
        folder = (
            tmp_path / "By the Grace of the Gods vol_02 (2023) (Roy) {ASIN.B0C9RS445X} [H2OKing]"
        )
        folder.mkdir()

        # Create files matching real folder structure
        (folder / "By the Grace of the Gods vol_02 (2023) (Roy) {ASIN.B0C9RS445X}.cue").touch()
        (folder / "By the Grace of the Gods vol_02 (2023) (Roy) {ASIN.B0C9RS445X}.jpg").touch()
        (folder / "By the Grace of the Gods vol_02 (2023) (Roy) {ASIN.B0C9RS445X}.m4b").touch()
        (
            folder / "By the Grace of the Gods vol_02 (2023) (Roy) {ASIN.B0C9RS445X}.metadata.json"
        ).touch()

        # This is the config from the user's config.yaml
        removed = remove_ignored_files(folder, ["*.metadata.json"])

        assert len(removed) == 1
        assert (
            "By the Grace of the Gods vol_02 (2023) (Roy) {ASIN.B0C9RS445X}.metadata.json"
            in removed
        )
        # Other files preserved
        assert (
            folder / "By the Grace of the Gods vol_02 (2023) (Roy) {ASIN.B0C9RS445X}.m4b"
        ).exists()
        assert (
            folder / "By the Grace of the Gods vol_02 (2023) (Roy) {ASIN.B0C9RS445X}.jpg"
        ).exists()
        assert (
            folder / "By the Grace of the Gods vol_02 (2023) (Roy) {ASIN.B0C9RS445X}.cue"
        ).exists()


# =============================================================================
# Tests: Cleanup Integration
# =============================================================================


class TestImportSingleWithCleanup:
    """Tests for import_single with cleanup integration."""

    def test_cleanup_disabled_by_default(self, tmp_path: Path) -> None:
        """Test that cleanup is disabled when cleanup_prefs is None."""
        staging = tmp_path / "staging"
        library = tmp_path / "library"
        staging.mkdir()
        library.mkdir()

        # Create staged audiobook
        folder_name = "Author Name - Book Title (2023) (Narrator) {ASIN.B012345678}"
        book_folder = staging / folder_name
        book_folder.mkdir()
        (book_folder / "book.m4b").write_text("audio content")

        result = import_single(
            staging_folder=book_folder,
            library_root=library,
            asin_index={},
            # cleanup_prefs=None (default)
        )

        assert result.status == "success"
        assert result.cleanup is None

    def test_cleanup_runs_on_success(self, tmp_path: Path) -> None:
        """Test that cleanup runs after successful import."""
        import os

        from shelfr.abs.cleanup import CleanupPrefs, CleanupStrategy

        staging = tmp_path / "staging"
        library = tmp_path / "library"
        source = tmp_path / "source"
        staging.mkdir()
        library.mkdir()
        source.mkdir()

        # Create source folder (Libation original)
        source_folder = source / "Author Name" / "Book Title"
        source_folder.mkdir(parents=True)
        source_m4b = source_folder / "book.m4b"
        source_m4b.write_text("audio content")
        (source_folder / "book.metadata.json").write_text("{}")

        # Create staged audiobook (hardlinked from source)
        folder_name = "Author Name - Book Title (2023) (Narrator) {ASIN.B012345678}"
        book_folder = staging / folder_name
        book_folder.mkdir()
        staged_m4b = book_folder / "book.m4b"
        os.link(str(source_m4b), str(staged_m4b))

        cleanup_prefs = CleanupPrefs(
            strategy=CleanupStrategy.HIDE,
            require_seed_exists=False,  # Skip seed check for test
        )

        result = import_single(
            staging_folder=book_folder,
            library_root=library,
            asin_index={},
            cleanup_prefs=cleanup_prefs,
            source_path=source_folder,
        )

        assert result.status == "success"
        assert result.cleanup is not None
        assert result.cleanup.status == "success"
        assert result.cleanup.strategy == CleanupStrategy.HIDE
        # Marker file should exist
        assert (source_folder / ".shelfr_imported").exists()

    def test_cleanup_not_run_when_source_path_not_provided(self, tmp_path: Path) -> None:
        """Test that cleanup does not run when source_path is None."""
        from shelfr.abs.cleanup import CleanupPrefs, CleanupStrategy

        staging = tmp_path / "staging"
        library = tmp_path / "library"
        staging.mkdir()
        library.mkdir()

        folder_name = "Author Name - Book Title (2023) (Narrator) {ASIN.B012345678}"
        book_folder = staging / folder_name
        book_folder.mkdir()
        (book_folder / "book.m4b").write_text("audio content")

        cleanup_prefs = CleanupPrefs(
            strategy=CleanupStrategy.DELETE,  # Would delete if ran
            require_seed_exists=False,
        )

        result = import_single(
            staging_folder=book_folder,
            library_root=library,
            asin_index={},
            cleanup_prefs=cleanup_prefs,
            source_path=None,  # No source path provided
        )

        # Import should succeed
        assert result.status == "success"
        # But cleanup should not have run (no source_path)
        assert result.cleanup is None

    def test_cleanup_skipped_on_duplicate(self, tmp_path: Path) -> None:
        """Test that cleanup does NOT run when book is duplicate."""
        from shelfr.abs.cleanup import CleanupPrefs, CleanupStrategy

        staging = tmp_path / "staging"
        library = tmp_path / "library"
        source = tmp_path / "source"
        staging.mkdir()
        library.mkdir()
        source.mkdir()

        source_folder = source / "book"
        source_folder.mkdir()
        (source_folder / "book.m4b").touch()

        # Create staged audiobook
        folder_name = "Author Name - Book Title (2023) (Narrator) {ASIN.B012345678}"
        book_folder = staging / folder_name
        book_folder.mkdir()
        (book_folder / "book.m4b").write_text("audio")

        # ASIN already exists in index with an on-disk folder
        existing = library / "Author Name" / "Book Title {ASIN.B012345678}"
        existing.mkdir(parents=True)
        (existing / "existing.m4b").touch()

        asin_index = {
            "B012345678": AsinEntry(
                asin="B012345678",
                path=str(existing),
                library_item_id="li_123",
                title="Book Title",
                author="Author Name",
            )
        }

        cleanup_prefs = CleanupPrefs(
            strategy=CleanupStrategy.DELETE,
            require_seed_exists=False,
        )

        result = import_single(
            staging_folder=book_folder,
            library_root=library,
            asin_index=asin_index,
            duplicate_policy="skip",
            cleanup_prefs=cleanup_prefs,
            source_path=source_folder,
        )

        assert result.status == "duplicate"
        assert result.cleanup is None
        assert source_folder.exists()

    def test_cleanup_dry_run(self, tmp_path: Path) -> None:
        """Test cleanup respects dry_run flag."""
        from shelfr.abs.cleanup import CleanupPrefs, CleanupStrategy

        staging = tmp_path / "staging"
        library = tmp_path / "library"
        source = tmp_path / "source"
        staging.mkdir()
        library.mkdir()
        source.mkdir()

        source_folder = source / "book"
        source_folder.mkdir()
        (source_folder / "book.m4b").touch()

        folder_name = "Author Name - Book Title (2023) (Narrator) {ASIN.B012345678}"
        book_folder = staging / folder_name
        book_folder.mkdir()
        (book_folder / "book.m4b").write_text("audio")

        cleanup_prefs = CleanupPrefs(
            strategy=CleanupStrategy.DELETE,
            require_seed_exists=False,
        )

        result = import_single(
            staging_folder=book_folder,
            library_root=library,
            asin_index={},
            cleanup_prefs=cleanup_prefs,
            source_path=source_folder,
            dry_run=True,
        )

        assert result.status == "success"
        assert result.cleanup is not None
        assert result.cleanup.status == "dry_run"
        # Source should still exist (dry run)
        assert source_folder.exists()


class TestBatchImportWithCleanup:
    """Tests for import_batch with cleanup integration."""

    def test_batch_cleanup_counts(self, tmp_path: Path) -> None:
        """Test batch import tracks cleanup statistics."""
        from shelfr.abs.cleanup import CleanupPrefs, CleanupStrategy

        staging = tmp_path / "staging"
        library = tmp_path / "library"
        source = tmp_path / "source"
        staging.mkdir()
        library.mkdir()
        source.mkdir()

        # Create multiple source and staging folders
        source_paths: dict[Path, Path] = {}
        staging_folders: list[Path] = []

        for i in range(3):
            src = source / f"book{i}"
            src.mkdir()
            (src / "book.m4b").touch()

            folder_name = f"Author - Book{i} (2023) (Narrator) {{ASIN.B01234567{i}}}"
            stg = staging / folder_name
            stg.mkdir()
            (stg / "book.m4b").write_text(f"audio{i}")

            source_paths[stg] = src
            staging_folders.append(stg)

        cleanup_prefs = CleanupPrefs(
            strategy=CleanupStrategy.HIDE,
            require_seed_exists=False,
        )

        result = import_batch(
            staging_folders=staging_folders,
            library_root=library,
            asin_index={},
            cleanup_prefs=cleanup_prefs,
            source_paths=source_paths,
        )

        assert result.success_count == 3
        assert result.cleanup_success_count == 3
        assert result.cleanup_failed_count == 0
        assert result.cleanup_skipped_count == 0

        # All markers should exist
        for src in source_paths.values():
            assert (src / ".shelfr_imported").exists()

    def test_batch_mixed_cleanup_results(self, tmp_path: Path) -> None:
        """Test batch with mixed cleanup results (some skipped)."""
        from shelfr.abs.cleanup import CleanupPrefs, CleanupStrategy

        staging = tmp_path / "staging"
        library = tmp_path / "library"
        source = tmp_path / "source"
        seed_root = tmp_path / "seed"
        staging.mkdir()
        library.mkdir()
        source.mkdir()
        seed_root.mkdir()

        source_paths: dict[Path, Path] = {}
        staging_folders: list[Path] = []

        # Book 1: Has seed (cleanup should succeed)
        src1 = source / "book1"
        src1.mkdir()
        (src1 / "book.m4b").write_text("audio1")

        folder_name1 = "Author - Book1 (2023) (Narrator) {ASIN.B012345671}"
        stg1 = staging / folder_name1
        stg1.mkdir()
        (stg1 / "book.m4b").write_text("audio1")

        # Create seed with hardlink
        seed1 = seed_root / folder_name1
        seed1.mkdir()
        import os

        os.link(str(src1 / "book.m4b"), str(seed1 / "book.m4b"))

        source_paths[stg1] = src1
        staging_folders.append(stg1)

        # Book 2: No seed (cleanup should be skipped with require_seed_exists)
        src2 = source / "book2"
        src2.mkdir()
        (src2 / "book.m4b").write_text("audio2")

        folder_name2 = "Author - Book2 (2023) (Narrator) {ASIN.B012345672}"
        stg2 = staging / folder_name2
        stg2.mkdir()
        (stg2 / "book.m4b").write_text("audio2")

        source_paths[stg2] = src2
        staging_folders.append(stg2)

        cleanup_prefs = CleanupPrefs(
            strategy=CleanupStrategy.HIDE,
            require_seed_exists=True,  # Will skip book2 because no seed
        )

        result = import_batch(
            staging_folders=staging_folders,
            library_root=library,
            asin_index={},
            cleanup_prefs=cleanup_prefs,
            source_paths=source_paths,
            seed_root=seed_root,
        )

        assert result.success_count == 2
        assert result.cleanup_success_count == 1  # Only book1
        assert result.cleanup_skipped_count == 1  # book2 skipped (no seed)

        # Book1 marker exists
        assert (src1 / ".shelfr_imported").exists()
        # Book2 marker does not exist
        assert not (src2 / ".shelfr_imported").exists()


# =============================================================================
# Tests: OPF Sidecar Generation
# =============================================================================


class TestOPFSidecarGeneration:
    """Tests for metadata.opf sidecar generation during import."""

    def test_opf_sidecar_generated_when_enabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OPF sidecar is generated when generate_opf_sidecar=True and audnex data available."""
        staging = tmp_path / "staging"
        staging.mkdir()
        library = tmp_path / "library"
        library.mkdir()

        folder_name = (
            "Shirtaloon - He Who Fights with Monsters vol_01 "
            "(2021) (Heath Miller) {ASIN.B08WJ59784}"
        )
        folder = staging / folder_name
        folder.mkdir()
        (folder / "audiobook.m4b").write_text("fake audio")

        # Mock audnex response
        mock_audnex_data = {
            "asin": "B08WJ59784",
            "title": "He Who Fights with Monsters",
            "authors": [{"name": "Shirtaloon"}],
            "narrators": [{"name": "Heath Miller"}],
            "publisherName": "Podium Audio",
            "releaseDate": "2021-03-09T00:00:00.000Z",
            "language": "english",
            "description": "Test description",
            "seriesPrimary": {"name": "He Who Fights with Monsters", "position": "1"},
        }

        def mock_fetch_audnex_book(asin: str):
            return mock_audnex_data, "us"  # Returns (data, region) tuple

        monkeypatch.setattr(
            "shelfr.abs.importer.fetch_audnex_book",
            mock_fetch_audnex_book,
        )

        result = import_single(
            staging_folder=folder,
            library_root=library,
            asin_index={},
            generate_metadata_json=False,  # Disable JSON to isolate OPF test
            generate_opf_sidecar=True,
        )

        assert result.status == "success"
        assert result.target_path is not None

        # Check OPF file was generated
        opf_path = result.target_path / "metadata.opf"
        assert opf_path.exists(), "metadata.opf should be generated"

        # Verify OPF content
        content = opf_path.read_text()
        assert "He Who Fights with Monsters" in content
        assert "Shirtaloon" in content
        assert 'opf:role="aut"' in content
        assert 'opf:role="nrt"' in content
        assert "calibre:series" in content

    def test_opf_sidecar_not_generated_when_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OPF sidecar is NOT generated when generate_opf_sidecar=False (default)."""
        staging = tmp_path / "staging"
        staging.mkdir()
        library = tmp_path / "library"
        library.mkdir()

        folder_name = "Author - Title (2023) (Narrator) {ASIN.B012345678}"
        folder = staging / folder_name
        folder.mkdir()
        (folder / "audiobook.m4b").write_text("fake audio")

        mock_audnex_data = {
            "asin": "B012345678",
            "title": "Title",
            "authors": [{"name": "Author"}],
            "narrators": [{"name": "Narrator"}],
            "language": "english",
        }

        def mock_fetch_audnex_book(asin: str):
            return mock_audnex_data, "us"  # Returns (data, region) tuple

        monkeypatch.setattr(
            "shelfr.abs.importer.fetch_audnex_book",
            mock_fetch_audnex_book,
        )

        result = import_single(
            staging_folder=folder,
            library_root=library,
            asin_index={},
            generate_metadata_json=False,
            generate_opf_sidecar=False,  # Explicitly disabled
        )

        assert result.status == "success"
        assert result.target_path is not None

        # OPF should NOT exist
        opf_path = result.target_path / "metadata.opf"
        assert not opf_path.exists(), "metadata.opf should NOT be generated when disabled"

    def test_opf_sidecar_skipped_without_audnex_data(self, tmp_path: Path) -> None:
        """OPF sidecar is skipped when no audnex data available (no ASIN)."""
        staging = tmp_path / "staging"
        staging.mkdir()
        library = tmp_path / "library"
        library.mkdir()

        # Folder without ASIN - no audnex data will be available
        folder_name = "Unknown Author - Unknown Book (2023)"
        folder = staging / folder_name
        folder.mkdir()
        (folder / "audiobook.m4b").write_text("fake audio")

        result = import_single(
            staging_folder=folder,
            library_root=library,
            asin_index={},
            generate_metadata_json=False,
            generate_opf_sidecar=True,  # Enabled but won't generate without audnex
            unknown_asin_policy=UnknownAsinPolicy.IMPORT,
        )

        assert result.status == "success"
        assert result.target_path is not None

        # OPF should NOT exist (no audnex data)
        opf_path = result.target_path / "metadata.opf"
        assert not opf_path.exists(), "metadata.opf requires audnex data"

    def test_opf_sidecar_dry_run(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """OPF sidecar generation respects dry_run mode."""
        staging = tmp_path / "staging"
        staging.mkdir()
        library = tmp_path / "library"
        library.mkdir()

        folder_name = "Author - Title (2023) (Narrator) {ASIN.B012345678}"
        folder = staging / folder_name
        folder.mkdir()
        (folder / "audiobook.m4b").write_text("fake audio")

        mock_audnex_data = {
            "asin": "B012345678",
            "title": "Title",
            "authors": [{"name": "Author"}],
            "language": "english",
        }

        def mock_fetch_audnex_book(asin: str):
            return mock_audnex_data, "us"  # Returns (data, region) tuple

        monkeypatch.setattr(
            "shelfr.abs.importer.fetch_audnex_book",
            mock_fetch_audnex_book,
        )

        result = import_single(
            staging_folder=folder,
            library_root=library,
            asin_index={},
            generate_metadata_json=False,
            generate_opf_sidecar=True,
            dry_run=True,
        )

        assert result.status == "success"

        # In dry_run, nothing should be moved/created
        # The target_path exists but files aren't actually there
        assert folder.exists(), "Staging folder should still exist in dry_run"
