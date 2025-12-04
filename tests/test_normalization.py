"""Tests for Audnex title/subtitle normalization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mamfast.models import NormalizedBook
from mamfast.utils.naming import (
    clean_series_name,
    detect_swapped_title_subtitle,
    extract_arc_name,
    normalize_audnex_book,
)

# Load test fixtures
FIXTURES_PATH = Path(__file__).parent / "fixtures" / "audnex_normalization_samples.json"


@pytest.fixture
def normalization_samples() -> dict[str, Any]:
    """Load normalization test fixtures."""
    with open(FIXTURES_PATH, encoding="utf-8") as f:
        return json.load(f)


class TestCleanSeriesName:
    """Tests for clean_series_name function."""

    def test_none_input(self) -> None:
        """None input returns None."""
        assert clean_series_name(None) is None

    def test_empty_string(self) -> None:
        """Empty string returns None."""
        assert clean_series_name("") is None
        assert clean_series_name("   ") is None

    def test_no_cleaning_needed(self) -> None:
        """Series name without patterns passes through."""
        assert clean_series_name("Sword Art Online") == "Sword Art Online"
        assert clean_series_name("The Hunger Games") == "The Hunger Games"

    def test_strips_series_suffix(self) -> None:
        """Removes ' Series' suffix."""
        assert clean_series_name("Holes Series") == "Holes"
        assert clean_series_name("Solo Leveling Series") == "Solo Leveling"
        assert clean_series_name("Hell Divers Series") == "Hell Divers"

    def test_strips_light_novel_parens(self) -> None:
        """Removes '(Light Novel)' suffix with parens."""
        assert clean_series_name("Rascal Does Not Dream (light novel)") == "Rascal Does Not Dream"
        assert (
            clean_series_name("So I'm a Spider, So What? (Light Novel)")
            == "So I'm a Spider, So What?"
        )

    def test_strips_light_novel_no_parens(self) -> None:
        """Removes ' Light Novel' suffix without parens."""
        assert clean_series_name("Kuma Kuma Kuma Bear Light Novel") == "Kuma Kuma Kuma Bear"

    def test_strips_bracket_tags(self) -> None:
        """Removes bracket tags like [publication order]."""
        assert clean_series_name("Ascend Online [publication order]") == "Ascend Online"
        assert clean_series_name("Dresden Files [reading order]") == "Dresden Files"

    def test_strips_trilogy_saga(self) -> None:
        """Removes Trilogy and Saga suffixes."""
        assert clean_series_name("Lord of the Rings Trilogy") == "Lord of the Rings"
        assert clean_series_name("Star Wars Saga") == "Star Wars"

    def test_inherits_the_prefix(self) -> None:
        """Inherits 'The' prefix from title when series lacks it."""
        assert (
            clean_series_name(
                "Rising of the Shield Hero", title="The Rising of the Shield Hero, Volume 1"
            )
            == "The Rising of the Shield Hero"
        )

    def test_no_the_inheritance_when_already_has_the(self) -> None:
        """Doesn't double 'The' prefix."""
        assert clean_series_name("The Hunger Games", title="The Hunger Games") == "The Hunger Games"

    def test_no_the_inheritance_when_title_missing(self) -> None:
        """No inheritance when title is None."""
        assert clean_series_name("Rising of the Shield Hero") == "Rising of the Shield Hero"

    def test_no_the_inheritance_when_series_not_in_title(self) -> None:
        """No inheritance when series name isn't in title."""
        # "Witcher" isn't in "The Hunger Games" so no The inheritance
        assert clean_series_name("Witcher", title="The Hunger Games") == "Witcher"

    def test_combined_cleaning(self) -> None:
        """Multiple patterns cleaned in one pass."""
        # Series suffix + The inheritance
        assert (
            clean_series_name("Terminal List Series", title="The Terminal List")
            == "The Terminal List"
        )

        # Bracket tag removal
        assert (
            clean_series_name("Ascend Online [publication order]", title="Hell to Pay")
            == "Ascend Online"
        )


class TestDetectSwappedTitleSubtitle:
    """Tests for detect_swapped_title_subtitle function."""

    def test_no_subtitle_returns_unchanged(self) -> None:
        """Without subtitle, title is unchanged and no swap detected."""
        title, subtitle, swapped = detect_swapped_title_subtitle(
            "The Book Title", None, "Some Series", "1"
        )
        assert title == "The Book Title"
        assert subtitle is None
        assert swapped is False

    def test_no_series_returns_unchanged(self) -> None:
        """Without series name, cannot detect swap."""
        title, subtitle, swapped = detect_swapped_title_subtitle(
            "The Book Title", "A Subtitle", None, "1"
        )
        assert title == "The Book Title"
        assert subtitle == "A Subtitle"
        assert swapped is False

    def test_correct_mapping_not_swapped(self) -> None:
        """Title has series name, subtitle has arc - no swap needed."""
        title, subtitle, swapped = detect_swapped_title_subtitle(
            "Sword Art Online 7", "Mother's Rosary", "Sword Art Online", "7"
        )
        assert title == "Sword Art Online 7"
        assert subtitle == "Mother's Rosary"
        assert swapped is False

    def test_swapped_series_in_subtitle(self) -> None:
        """Subtitle has series name, title doesn't - swap detected."""
        title, subtitle, swapped = detect_swapped_title_subtitle(
            "Alicization Exploding", "Sword Art Online 16", "Sword Art Online", "16"
        )
        assert title == "Sword Art Online 16"
        assert subtitle == "Alicization Exploding"
        assert swapped is True

    def test_swapped_with_position_in_subtitle(self) -> None:
        """Subtitle has series position number - swap detected."""
        title, subtitle, swapped = detect_swapped_title_subtitle(
            "Early Years", "The Beginning After the End, Book 1", "The Beginning After the End", "1"
        )
        assert title == "The Beginning After the End, Book 1"
        assert subtitle == "Early Years"
        assert swapped is True

    def test_both_have_series_not_swapped(self) -> None:
        """Both title and subtitle have series name - no swap."""
        title, subtitle, swapped = detect_swapped_title_subtitle(
            "Sword Art Online: Aincrad", "Sword Art Online, Book 1", "Sword Art Online", "1"
        )
        # Both have series - leave as-is (cleaning rules will handle)
        assert swapped is False


class TestExtractArcName:
    """Tests for extract_arc_name function."""

    def test_no_series_subtitle_is_arc(self) -> None:
        """Without series, subtitle becomes arc."""
        arc = extract_arc_name("The Title", "Cool Subtitle", None)
        assert arc == "Cool Subtitle"

    def test_no_series_no_subtitle_no_arc(self) -> None:
        """Without series or subtitle, no arc."""
        arc = extract_arc_name("The Title", None, None)
        assert arc is None

    def test_subtitle_is_arc_when_no_series_in_subtitle(self) -> None:
        """Subtitle without series name is the arc."""
        arc = extract_arc_name("Sword Art Online 7", "Mother's Rosary", "Sword Art Online")
        assert arc == "Mother's Rosary"

    def test_subtitle_with_series_not_arc(self) -> None:
        """Subtitle containing series name is not the arc."""
        arc = extract_arc_name("Sword Art Online 7", "Sword Art Online, Vol. 7", "Sword Art Online")
        assert arc is None

    def test_generic_subtitle_not_arc(self) -> None:
        """Generic subtitles like 'Light Novel' are not arcs."""
        arc = extract_arc_name(
            "Mushoku Tensei: Jobless Reincarnation, Vol. 1", "Light Novel", "Mushoku Tensei"
        )
        assert arc is None

    def test_title_is_arc_when_no_series_in_title(self) -> None:
        """Title without series name could be the arc (edge case)."""
        arc = extract_arc_name("Aincrad", "Sword Art Online 1", "Sword Art Online")
        # Title doesn't have series but subtitle does - title might be arc
        assert arc == "Aincrad"


class TestNormalizeAudnexBook:
    """Tests for normalize_audnex_book function."""

    def test_basic_correct_mapping(self) -> None:
        """Book with correct mapping is normalized without swap."""
        data = {
            "asin": "B0BHLHRMJH",
            "title": "Sword Art Online 7",
            "subtitle": "Mother's Rosary",
            "seriesPrimary": {"name": "Sword Art Online", "position": "7"},
        }
        result = normalize_audnex_book(data)

        assert isinstance(result, NormalizedBook)
        assert result.asin == "B0BHLHRMJH"
        assert result.raw_title == "Sword Art Online 7"
        assert result.raw_subtitle == "Mother's Rosary"
        assert result.series_name == "Sword Art Online"
        assert result.series_position == "7"
        assert result.arc_name == "Mother's Rosary"
        assert result.display_title == "Sword Art Online 7"
        assert result.display_subtitle == "Mother's Rosary"
        assert result.was_swapped is False

    def test_swapped_mapping_is_fixed(self) -> None:
        """Book with swapped mapping is corrected."""
        data = {
            "asin": "B0DK9TS6D9",
            "title": "Alicization Exploding",
            "subtitle": "Sword Art Online 16",
            "seriesPrimary": {"name": "Sword Art Online", "position": "16"},
        }
        result = normalize_audnex_book(data)

        assert result.asin == "B0DK9TS6D9"
        assert result.raw_title == "Alicization Exploding"
        assert result.raw_subtitle == "Sword Art Online 16"
        assert result.series_name == "Sword Art Online"
        assert result.series_position == "16"
        assert result.arc_name == "Alicization Exploding"
        assert result.display_title == "Sword Art Online 16"
        assert result.display_subtitle == "Alicization Exploding"
        assert result.was_swapped is True

    def test_no_series_passthrough(self) -> None:
        """Book without series passes through unchanged."""
        data = {
            "asin": "B_STANDALONE",
            "title": "The Standalone Book",
            "subtitle": "A Great Adventure",
        }
        result = normalize_audnex_book(data)

        assert result.raw_title == "The Standalone Book"
        assert result.raw_subtitle == "A Great Adventure"
        assert result.series_name is None
        assert result.series_position is None
        assert result.arc_name == "A Great Adventure"
        assert result.display_title == "The Standalone Book"
        assert result.was_swapped is False

    def test_position_as_integer(self) -> None:
        """Series position can be integer, gets converted to string."""
        data = {
            "asin": "TEST",
            "title": "Series Title 5",
            "subtitle": "Arc Name",
            "seriesPrimary": {"name": "Series Title", "position": 5},
        }
        result = normalize_audnex_book(data)

        assert result.series_position == "5"


class TestNormalizationFixtures:
    """Golden tests using fixture data from samples."""

    def test_correct_mapping_samples(self, normalization_samples: dict[str, Any]) -> None:
        """All correct_mapping samples should not be swapped."""
        for sample in normalization_samples["correct_mapping"]:
            data = {
                "asin": sample["asin"],
                "title": sample["title"],
                "subtitle": sample["subtitle"],
                "seriesPrimary": sample["seriesPrimary"],
            }
            expected = sample["expected"]
            result = normalize_audnex_book(data)

            assert result.was_swapped == expected["was_swapped"], (
                f"ASIN {sample['asin']}: expected was_swapped={expected['was_swapped']}, "
                f"got {result.was_swapped}"
            )
            assert result.series_name == expected["series_name"]
            assert result.series_position == expected["position"]
            assert result.arc_name == expected["arc"]

    def test_swapped_mapping_samples(self, normalization_samples: dict[str, Any]) -> None:
        """All swapped_mapping samples should be detected and fixed."""
        for sample in normalization_samples["swapped_mapping"]:
            data = {
                "asin": sample["asin"],
                "title": sample["title"],
                "subtitle": sample["subtitle"],
                "seriesPrimary": sample["seriesPrimary"],
            }
            expected = sample["expected"]
            result = normalize_audnex_book(data)

            assert result.was_swapped == expected["was_swapped"], (
                f"ASIN {sample['asin']}: expected was_swapped={expected['was_swapped']}, "
                f"got {result.was_swapped}"
            )
            assert result.display_title == expected["title"], (
                f"ASIN {sample['asin']}: expected title={expected['title']!r}, "
                f"got {result.display_title!r}"
            )
            assert result.arc_name == expected["arc"], (
                f"ASIN {sample['asin']}: expected arc={expected['arc']!r}, "
                f"got {result.arc_name!r}"
            )

    def test_no_series_samples(self, normalization_samples: dict[str, Any]) -> None:
        """Books without series should pass through unchanged."""
        for sample in normalization_samples["no_series"]:
            data = {
                "asin": sample["asin"],
                "title": sample["title"],
                "subtitle": sample["subtitle"],
                "seriesPrimary": sample["seriesPrimary"],
            }
            expected = sample["expected"]
            result = normalize_audnex_book(data)

            assert result.was_swapped is False
            assert result.series_name == expected["series_name"]
            assert result.display_title == expected["title"]

    def test_edge_case_samples(self, normalization_samples: dict[str, Any]) -> None:
        """Edge case samples should be handled correctly."""
        for sample in normalization_samples["edge_cases"]:
            data = {
                "asin": sample["asin"],
                "title": sample["title"],
                "subtitle": sample["subtitle"],
                "seriesPrimary": sample["seriesPrimary"],
            }
            expected = sample["expected"]
            result = normalize_audnex_book(data)

            assert result.was_swapped == expected["was_swapped"], (
                f"ASIN {sample['asin']}: expected was_swapped={expected['was_swapped']}, "
                f"got {result.was_swapped}. Desc: {sample.get('_description', '')}"
            )
