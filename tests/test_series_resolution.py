"""Tests for SeriesInfo model and series resolution functions."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from shelfr.models import AudiobookRelease, SeriesInfo, SeriesSource
from shelfr.utils.naming import (
    parse_series_from_libation_path,
    parse_series_from_title,
    resolve_series,
)


class TestSeriesInfo:
    """Tests for SeriesInfo dataclass."""

    def test_basic_creation(self) -> None:
        """Test basic SeriesInfo creation."""
        info = SeriesInfo(
            name="Sword Art Online",
            position="7",
            source=SeriesSource.AUDNEX,
            confidence=1.0,
        )
        assert info.name == "Sword Art Online"
        assert info.position == "7"
        assert info.source == SeriesSource.AUDNEX
        assert info.confidence == 1.0

    def test_default_values(self) -> None:
        """Test SeriesInfo defaults."""
        info = SeriesInfo(name="Test Series")
        assert info.position is None
        assert info.source == SeriesSource.AUDNEX
        assert info.confidence == 1.0

    def test_formatted_position_integer(self) -> None:
        """Test formatted_position with integer position."""
        info = SeriesInfo(name="Test", position="5")
        assert info.formatted_position == "05"

    def test_formatted_position_decimal(self) -> None:
        """Test formatted_position with decimal position."""
        info = SeriesInfo(name="Test", position="1.5")
        assert info.formatted_position == "01.50"

    def test_formatted_position_decimal_less_than_one(self) -> None:
        """Test formatted_position with decimal less than 1 (e.g., 0.5)."""
        info = SeriesInfo(name="Test", position="0.5")
        assert info.formatted_position == "00.50"

    def test_formatted_position_decimal_double_digit(self) -> None:
        """Test formatted_position with double-digit decimal."""
        info = SeriesInfo(name="Test", position="10.5")
        assert info.formatted_position == "10.50"

    def test_formatted_position_two_digit(self) -> None:
        """Test formatted_position with two-digit position."""
        info = SeriesInfo(name="Test", position="12")
        assert info.formatted_position == "12"

    def test_formatted_position_none(self) -> None:
        """Test formatted_position with no position."""
        info = SeriesInfo(name="Test", position=None)
        assert info.formatted_position is None

    def test_formatted_position_prequel(self) -> None:
        """Test formatted_position with prequel (0)."""
        info = SeriesInfo(name="Test", position="0")
        assert info.formatted_position == "00"


class TestParseSeriesFromTitle:
    """Tests for parse_series_from_title function."""

    @pytest.mark.parametrize(
        "title,expected",
        [
            # Vol./Volume patterns with comma
            (
                "I'm the Evil Lord of an Intergalactic Empire!, Vol. 5",
                ("I'm the Evil Lord of an Intergalactic Empire!", "5"),
            ),
            ("Black Summoner, Vol. 4", ("Black Summoner", "4")),
            ("Some Series, Volume 12", ("Some Series", "12")),
            # Colon separator
            ("Some Light Novel: Volume 3.5", ("Some Light Novel", "3.5")),
            ("Fantasy Series: Vol. 1", ("Fantasy Series", "1")),
            # Book pattern
            ("Epic Fantasy, Book 3", ("Epic Fantasy", "3")),
            ("Adventure Series: Book 10", ("Adventure Series", "10")),
            # Space separator (no comma/colon)
            ("Magic Academy Vol. 2", ("Magic Academy", "2")),
            ("Dragon Quest Volume 8", ("Dragon Quest", "8")),
            ("Hero's Journey Book 5", ("Hero's Journey", "5")),
            # Trailing number (requires at least 2 words in series)
            ("Overlord Light Novel 14", ("Overlord Light Novel", "14")),
            ("My Hero 5", ("My Hero", "5")),
        ],
    )
    def test_successful_extraction(self, title: str, expected: tuple[str, str]) -> None:
        """Test successful series extraction from various title formats."""
        result = parse_series_from_title(title)
        assert result is not None
        assert result == expected

    @pytest.mark.parametrize(
        "title",
        [
            # No series pattern
            "Project Hail Mary",
            "The Martian",
            "A Standalone Novel",
            # Famous books with trailing numbers - should NOT match as series
            "Fahrenheit 451",
            "Catch-22",
            "1984",
            "Area 51",
            # Single word + number - should NOT match (requires 2+ words)
            "Overlord 14",
        ],
    )
    def test_no_series_found(self, title: str) -> None:
        """Test titles that should not extract series."""
        result = parse_series_from_title(title)
        assert result is None

    def test_short_series_name_filtered_out(self) -> None:
        """Single-letter 'series' names are discarded as noise.

        The implementation has a len(series) < 2 guard to filter out
        garbage matches like 'A' from 'A, Vol. 1'. We use a title with
        trailing content to prevent fallback to the greedy trailing-number pattern.
        """
        # Trailing content prevents the "Series Name N" fallback pattern
        result = parse_series_from_title("A, Vol. 1: The Beginning")
        # Single character series names are filtered out
        assert result is None

    def test_the_book_pattern(self) -> None:
        """Test 'The Book N' pattern - now matches with 2+ word series."""
        # "The Book 5" -> ("The Book", "5") - 2 words, so it matches
        result = parse_series_from_title("The Book 5")
        assert result is not None
        assert result == ("The Book", "5")

    def test_empty_title(self) -> None:
        """Test empty title returns None."""
        assert parse_series_from_title("") is None
        assert parse_series_from_title("   ") is None


class TestParseSeriesFromLibationPath:
    """Tests for parse_series_from_libation_path function."""

    def test_three_level_structure(self) -> None:
        """Test Author/Series/Book structure."""
        path = Path(
            "/library/Brandon Sanderson/Stormlight Archive"
            "/The Way of Kings vol_01 (2010) {ASIN.XXX}"
        )
        result = parse_series_from_libation_path(path)
        assert result is not None
        series_name, position = result
        assert series_name == "Stormlight Archive"
        assert position == "01"

    def test_no_vol_in_book_folder(self) -> None:
        """Test extraction when book folder has no vol_XX.

        'Standalone' is a common grouping folder name (meaning 'not in a series')
        and is filtered out by common_roots.

        Note: Uses realistic Libation format with (Author) in book folder name,
        which prevents the author folder from being detected as series.
        """
        path = Path("/library/Andy Weir/Standalone/Project Hail Mary (2021) (Andy Weir) {ASIN.XXX}")
        result = parse_series_from_libation_path(path)
        # "Standalone" is filtered as a common root, "Andy Weir" is detected as
        # author due to (Andy Weir) in book folder, so no series detected
        assert result is None

    def test_two_level_structure_no_series(self) -> None:
        """Test Author/Book structure (no series folder)."""
        # When the parent folder doesn't look like a series folder,
        # parse_series_from_libation_path still returns it (caller decides)
        # This is because we can't always tell author from series
        path = Path("/library/Andy Weir/Project Hail Mary (2021) {ASIN.XXX}")
        result = parse_series_from_libation_path(path)
        # The function returns "Andy Weir" as potential series since it
        # doesn't have ASIN/year/vol_ markers. Caller must validate further.
        assert result is not None
        series_name, position = result
        assert series_name == "Andy Weir"
        assert position is None

    def test_series_folder_with_year(self) -> None:
        """Test that folders with (Year) are skipped, but scan continues upward."""
        path = Path("/library/Author/Series Name (2020)/Book Title {ASIN.XXX}")
        result = parse_series_from_libation_path(path)
        # Parent has (2020), so it's skipped as a book folder
        # But scan continues upward and finds "Author" as potential series
        # (This is actually reasonable for "Author/Universe/Book" structures)
        assert result is not None
        assert result[0] == "Author"

    def test_short_path(self) -> None:
        """Test path with only 2 parts skips library root folder."""
        path = Path("/library/BookFolder")
        result = parse_series_from_libation_path(path)
        # With 2 parts, "library" is skipped as a common root folder name
        # This prevents false positives for shallow paths
        assert result is None

    def test_none_path(self) -> None:
        """Test None path returns None."""
        result = parse_series_from_libation_path(None)
        assert result is None

    def test_mnt_user_path_no_series_folder(self) -> None:
        """Test that /mnt/user/... mount paths don't get picked up as series.

        This is a regression test for an issue where books directly under an
        import folder (no series folder) would incorrectly pick up 'user' from
        the mount path /mnt/user/data/... as the series name.
        """
        path = Path(
            "/mnt/user/data/audio/audiobook-import"
            "/The Beginning After the End vol_11 Providence (2025) (TurtleMe) {ASIN.B0DJPYFJ2K}"
        )
        result = parse_series_from_libation_path(path)
        # Should return None because:
        # - "audiobook-import" contains "audiobook" -> skipped
        # - "audio" is in common_roots -> skipped
        # - "data" is in common_roots -> skipped
        # - "user" is in common_roots -> skipped
        # - "mnt" is in common_roots -> skipped
        assert result is None

    def test_common_mount_paths_skipped(self) -> None:
        """Test that common mount paths are skipped as potential series."""
        # Various mount patterns that should all return None
        test_paths = [
            "/mnt/cache/audiobooks/BookFolder (2024) {ASIN.XXX}",
            "/home/user/audiobooks/BookFolder (2024) {ASIN.XXX}",
            "/share/media/audiobooks/BookFolder (2024) {ASIN.XXX}",
            "/volume/data/audiobooks/BookFolder (2024) {ASIN.XXX}",
        ]
        for path_str in test_paths:
            path = Path(path_str)
            result = parse_series_from_libation_path(path)
            # All should return None - no false series from mount paths
            assert result is None, f"Unexpected series detected for {path_str}"


class TestResolveSeries:
    """Tests for resolve_series function."""

    def test_audnex_primary(self) -> None:
        """Test Audnex seriesPrimary takes priority."""
        audnex = {
            "seriesPrimary": {"name": "Sword Art Online", "position": "7"},
        }
        result = resolve_series(
            audnex_data=audnex,
            libation_path=Path("/lib/Author/Different Series/Book vol_01"),
            title="Some Title, Vol. 99",
        )
        assert result is not None
        assert result.name == "Sword Art Online"
        assert result.position == "7"
        assert result.source == SeriesSource.AUDNEX
        assert result.confidence == 1.0

    def test_libation_fallback(self) -> None:
        """Test Libation path fallback when Audnex has no series."""
        path = Path("/lib/Author/My Great Series/Book vol_03 (2020) {ASIN.XXX}")
        result = resolve_series(
            audnex_data={},  # No seriesPrimary
            libation_path=path,
            title="Some Title Without Series Pattern",
        )
        assert result is not None
        # Note: "Series" suffix is removed by clean_series_name
        assert result.name == "My Great"
        assert result.position == "03"
        assert result.source == SeriesSource.LIBATION
        assert result.confidence == 0.9

    def test_title_heuristic_fallback(self) -> None:
        """Test title heuristic when Audnex and Libation fail."""
        result = resolve_series(
            audnex_data={},
            libation_path=None,
            title="I'm the Evil Lord of an Intergalactic Empire!, Vol. 5",
        )
        assert result is not None
        assert result.name == "I'm the Evil Lord of an Intergalactic Empire!"
        assert result.position == "5"
        assert result.source == SeriesSource.TITLE_HEURISTIC
        assert result.confidence == 0.5

    def test_no_series_found(self) -> None:
        """Test when no source provides series."""
        result = resolve_series(
            audnex_data={},
            libation_path=None,
            title="A Completely Standalone Book",
        )
        assert result is None

    def test_audnex_with_series_suffix_cleaned(self) -> None:
        """Test that 'Series' suffix is cleaned from Audnex series name."""
        audnex = {
            "seriesPrimary": {"name": "Test Series", "position": "1"},
        }
        result = resolve_series(audnex_data=audnex)
        assert result is not None
        assert result.name == "Test"  # " Series" suffix removed

    def test_empty_audnex_series_primary(self) -> None:
        """Test Audnex with empty seriesPrimary falls back."""
        audnex = {
            "seriesPrimary": {"name": "", "position": ""},  # Empty
        }
        result = resolve_series(
            audnex_data=audnex,
            title="Black Summoner, Vol. 4",
        )
        assert result is not None
        assert result.name == "Black Summoner"
        assert result.source == SeriesSource.TITLE_HEURISTIC

    def test_none_audnex(self) -> None:
        """Test with None Audnex data."""
        result = resolve_series(
            audnex_data=None,
            title="Fantasy Series, Vol. 1",
        )
        assert result is not None
        assert result.name == "Fantasy"  # "Series" removed by clean_series_name
        assert result.source == SeriesSource.TITLE_HEURISTIC


class TestSeriesSourceEnum:
    """Tests for SeriesSource enum."""

    def test_values(self) -> None:
        """Test SeriesSource enum values."""
        assert SeriesSource.AUDNEX.value == "audnex"
        assert SeriesSource.LIBATION.value == "libation"
        assert SeriesSource.TITLE_HEURISTIC.value == "title_heuristic"

    def test_all_sources(self) -> None:
        """Test all sources are defined."""
        sources = list(SeriesSource)
        assert len(sources) == 3


class TestBuildMamJsonSeriesIntegration:
    """Integration tests for series handling in build_mam_json."""

    def test_preserves_primary_and_secondary_series(self) -> None:
        """Test that primary + secondary series from Audnex are both preserved."""
        from shelfr.metadata import build_mam_json

        release = AudiobookRelease(
            title="Test Book",
            asin="B09TEST123",
        )
        audnex = {
            "title": "Test Book",
            "seriesPrimary": {"name": "Sword Art Online", "position": "5"},
            "seriesSecondary": {"name": "Progressive", "position": "10"},
        }

        with patch("shelfr.metadata.render_bbcode_description", return_value=""):
            result = build_mam_json(release, audnex_data=audnex)

        assert len(result["series"]) == 2
        assert result["series"][0]["name"] == "Sword Art Online"
        assert result["series"][0]["number"] == "5"
        assert result["series"][1]["name"] == "Progressive"
        assert result["series"][1]["number"] == "10"

    def test_no_audnex_uses_libation_path(self) -> None:
        """Test that missing Audnex series falls back to Libation path."""
        from shelfr.metadata import build_mam_json

        release = AudiobookRelease(
            title="Test Book vol_05",
            asin="B09TEST123",
            source_dir=Path("/library/Author/Epic Fantasy/Test Book vol_05"),
        )
        audnex = {
            "title": "Test Book",
            # No seriesPrimary!
        }

        with patch("shelfr.metadata.render_bbcode_description", return_value=""):
            result = build_mam_json(release, audnex_data=audnex)

        assert "series" in result
        assert len(result["series"]) == 1
        assert result["series"][0]["name"] == "Epic Fantasy"
        assert result["series"][0]["number"] == "05"

    def test_no_audnex_no_libation_uses_title_heuristics(self) -> None:
        """Test title heuristics as last resort when Audnex and Libation fail."""
        from shelfr.metadata import build_mam_json

        release = AudiobookRelease(
            title="Black Summoner, Vol. 4",
            asin="B09TEST123",
            # No source_dir (or source_dir doesn't have series folder)
        )
        audnex = {
            "title": "Black Summoner, Vol. 4",
            # No seriesPrimary!
        }

        with patch("shelfr.metadata.render_bbcode_description", return_value=""):
            result = build_mam_json(release, audnex_data=audnex)

        assert "series" in result
        assert len(result["series"]) == 1
        assert result["series"][0]["name"] == "Black Summoner"
        assert result["series"][0]["number"] == "4"

    def test_fills_missing_position_from_libation(self) -> None:
        """Test that resolver fills missing position without overwriting name."""
        from shelfr.metadata import build_mam_json

        release = AudiobookRelease(
            title="Test Book",
            asin="B09TEST123",
            source_dir=Path("/library/Author/Epic Fantasy/Test Book vol_07"),
        )
        # Audnex has series name but NO position
        audnex = {
            "title": "Test Book",
            "seriesPrimary": {"name": "Epic Fantasy", "position": ""},
        }

        with patch("shelfr.metadata.render_bbcode_description", return_value=""):
            result = build_mam_json(release, audnex_data=audnex)

        assert "series" in result
        assert len(result["series"]) == 1
        assert result["series"][0]["name"] == "Epic Fantasy"
        # Position should be filled from Libation path
        assert result["series"][0]["number"] == "07"

    def test_does_not_overwrite_multiple_series_with_resolver(self) -> None:
        """Test that resolve_series doesn't bulldoze multiple Audnex series."""
        from shelfr.metadata import build_mam_json

        release = AudiobookRelease(
            title="Test Book",
            asin="B09TEST123",
            source_dir=Path("/library/Author/Different Thing/Test Book vol_99"),
        )
        audnex = {
            "title": "Test Book",
            "seriesPrimary": {"name": "Sword Art Online", "position": "1"},
            "seriesSecondary": {"name": "Progressive", "position": "2"},
        }

        with patch("shelfr.metadata.render_bbcode_description", return_value=""):
            result = build_mam_json(release, audnex_data=audnex)

        # Should still have both Audnex series, not replaced by Libation's "Different Thing"
        assert len(result["series"]) == 2
        assert result["series"][0]["name"] == "Sword Art Online"
        assert result["series"][0]["number"] == "1"
        assert result["series"][1]["name"] == "Progressive"
        assert result["series"][1]["number"] == "2"

    def test_release_series_fallback(self) -> None:
        """Test fallback to release.series when all other sources fail."""
        from shelfr.metadata import build_mam_json

        release = AudiobookRelease(
            title="Standalone Title",
            asin="B09TEST123",
            series="Fallback Adventure",
            series_position="3",
        )
        audnex = {
            "title": "Standalone Title",
            # No series data
        }

        with patch("shelfr.metadata.render_bbcode_description", return_value=""):
            result = build_mam_json(release, audnex_data=audnex)

        assert "series" in result
        assert result["series"][0]["name"] == "Fallback Adventure"
        assert result["series"][0]["number"] == "3"
