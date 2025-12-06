"""Tests for SeriesInfo model and series resolution functions."""

from __future__ import annotations

from pathlib import Path

import pytest

from mamfast.models import SeriesInfo, SeriesSource
from mamfast.utils.naming import (
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
        assert info.formatted_position == "1.50"

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
            # Trailing number (lowest confidence pattern)
            ("Overlord 14", ("Overlord", "14")),
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
        ],
    )
    def test_no_series_found(self, title: str) -> None:
        """Test titles that should not extract series."""
        result = parse_series_from_title(title)
        assert result is None

    def test_short_series_name_still_matches(self) -> None:
        """Test short series names still match (edge case)."""
        # "A, Vol. 1" -> ("A,", "1") - the pattern matches but series name is dubious
        # This is acceptable behavior - downstream can filter if needed
        result = parse_series_from_title("A, Vol. 1")
        # Pattern matches technically, but series name validation should catch this
        # For now, the pattern does match
        assert result is not None

    def test_the_book_pattern(self) -> None:
        """Test 'The Book N' pattern - matches as series."""
        # "The Book 5" -> ("The Book", "5")
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
        """Test extraction when book folder has no vol_XX."""
        path = Path("/library/Andy Weir/Standalone/Project Hail Mary (2021) {ASIN.XXX}")
        result = parse_series_from_libation_path(path)
        assert result is not None
        series_name, position = result
        assert series_name == "Standalone"
        assert position is None

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
        """Test that folders with (Year) are detected as book folders, not series."""
        path = Path("/library/Author/Series Name (2020)/Book Title {ASIN.XXX}")
        result = parse_series_from_libation_path(path)
        # Parent has (2020), so it looks like a book folder, not series
        assert result is None

    def test_short_path(self) -> None:
        """Test path with only 2 parts still returns potential series."""
        path = Path("/library/BookFolder")
        result = parse_series_from_libation_path(path)
        # With 2 parts, "library" is returned as potential series
        # This is a limitation - caller should validate
        assert result is not None
        assert result[0] == "library"

    def test_none_path(self) -> None:
        """Test None path returns None."""
        result = parse_series_from_libation_path(None)  # type: ignore[arg-type]
        assert result is None


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
