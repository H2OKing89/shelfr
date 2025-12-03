"""Golden tests for naming functions.

These tests use predefined input/expected pairs to detect regressions
in the naming/cleaning logic. They provide a safety net when updating
naming rules.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mamfast.config import NamingConfig
from mamfast.utils.naming import filter_series, filter_subtitle, filter_title

# Load golden test data
GOLDEN_DIR = Path(__file__).parent / "golden"


@pytest.fixture(scope="module")
def golden_inputs() -> dict:
    """Load golden test inputs."""
    with open(GOLDEN_DIR / "naming_inputs.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def golden_expected() -> dict:
    """Load golden test expected outputs."""
    with open(GOLDEN_DIR / "naming_expected.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def naming_config() -> NamingConfig:
    """Create a NamingConfig matching the production config for testing."""
    return NamingConfig(
        format_indicators=[
            "(Light Novel)",
            "Light Novel",
            "(Unabridged)",
            "Unabridged",
            "(Manga)",
            "(Graphic Novel)",
            "(Audiobook)",
        ],
        genre_tags=[
            "A LitRPG Adventure",
            "LitRPG Adventure",
            "A Progression Fantasy",
            "A Fantasy Adventure",
            ": A LitRPG Adventure",
        ],
        publisher_tags=[
            "[Yen Audio]",
            "[J-Novel Club]",
            "(Yen Audio)",
        ],
        series_suffixes=[
            r"\s+[Ss]eries$",
            r"\s+[Tt]rilogy$",
            r"\s+[Ss]aga$",
            r"\s+[Cc]hronicles$",
            r"\s*\([Ll]ight [Nn]ovel\)$",
            r"\s+[Ll]ight [Nn]ovel$",
        ],
        # Subtitle patterns (for filter_subtitle)
        subtitle_remove_patterns=[
            r"^[Ll]ight [Nn]ovel$",
            r"^[Uu]nabridged$",
            r"^[Aa] LitRPG(?: Adventure)?$",
            r"^[Aa] Progression(?: Fantasy)?$",
        ],
        subtitle_keep_patterns=[
            r".*[Aa]incrad.*",
            r".*[Aa]ria.*",
            r".*[Cc]hronicle.*",
            r".*[Pp]rogressive.*",
        ],
        remove_subtitle_if_matches_series=True,
        subtitle_redundancy_enabled=True,
        subtitle_redundancy_rules=[
            {
                "id": "series_book",
                "pattern_template": r"^{{series}},?\s*Book\s*\d+$",
                "action": "drop_subtitle",
            },
            {
                "id": "series_in_parens",
                "pattern_template": r"\({{series}},?\s*Book\s*\d+\)$",
                "action": "strip_match",
            },
        ],
        preserve_exact=[
            "Re:ZERO",
            "Re:ZERO -Starting Life in Another World-",
            "86--EIGHTY-SIX",
            "Sword Art Online: Progressive",
        ],
    )


def _get_test_case(inputs: dict, expected: dict, test_id: str) -> tuple[dict, dict]:
    """Get matching input and expected for a test ID."""
    input_case = next(
        (tc for tc in inputs["test_cases"] if tc["id"] == test_id),
        None,
    )
    expected_case = next(
        (tc for tc in expected["expected"] if tc["id"] == test_id),
        None,
    )
    assert input_case is not None, f"Test case {test_id} not found in inputs"
    assert expected_case is not None, f"Test case {test_id} not found in expected"
    return input_case, expected_case


class TestGoldenTitleCleaning:
    """Golden tests for title cleaning (filter_title)."""

    @pytest.mark.parametrize(
        "test_id",
        [
            "light_novel_title_1",
            "light_novel_title_2",
            "litrpg_genre_tag",
            "series_suffix",
            "trilogy_suffix",
            "preserve_exact_rezero",
            "preserve_exact_86",
            "publisher_tag",
            "multiple_indicators",
            "progression_fantasy",
            "book_number_format",
            "volume_full_word",
            "clean_title",
            "unabridged_in_title",
            "double_dash_cleanup",
        ],
    )
    def test_title_json_output(
        self,
        golden_inputs: dict,
        golden_expected: dict,
        naming_config: NamingConfig,
        test_id: str,
    ):
        """Test title cleaning for JSON output (keep_volume=True)."""
        input_case, expected_case = _get_test_case(golden_inputs, golden_expected, test_id)

        title = input_case["title"]
        result = filter_title(title, naming_config=naming_config, keep_volume=True)

        assert result == expected_case["title_json"], (
            f"[{test_id}] Title JSON mismatch:\n"
            f"  Input:    {title!r}\n"
            f"  Expected: {expected_case['title_json']!r}\n"
            f"  Got:      {result!r}"
        )

    @pytest.mark.parametrize(
        "test_id",
        [
            "light_novel_title_1",
            "light_novel_title_2",
            "litrpg_genre_tag",
            "series_suffix",
            "preserve_exact_rezero",
            "preserve_exact_86",
            "publisher_tag",
            "multiple_indicators",
            "progression_fantasy",
            "book_number_format",
            "volume_full_word",
            "clean_title",
            "unabridged_in_title",
        ],
    )
    def test_title_folder_output(
        self,
        golden_inputs: dict,
        golden_expected: dict,
        naming_config: NamingConfig,
        test_id: str,
    ):
        """Test title cleaning for folder names (keep_volume=False)."""
        input_case, expected_case = _get_test_case(golden_inputs, golden_expected, test_id)

        title = input_case["title"]
        result = filter_title(title, naming_config=naming_config, keep_volume=False)

        assert result == expected_case["title_folder"], (
            f"[{test_id}] Title folder mismatch:\n"
            f"  Input:    {title!r}\n"
            f"  Expected: {expected_case['title_folder']!r}\n"
            f"  Got:      {result!r}"
        )


class TestGoldenSeriesCleaning:
    """Golden tests for series name cleaning (filter_series)."""

    @pytest.mark.parametrize(
        "test_id",
        [
            "light_novel_title_1",
            "light_novel_title_2",
            "litrpg_genre_tag",
            "series_suffix",
            "trilogy_suffix",
            "preserve_exact_rezero",
            "preserve_exact_86",
            "publisher_tag",
            "multiple_indicators",
            "progression_fantasy",
            "book_number_format",
            "volume_full_word",
            "meaningful_subtitle",
            "unabridged_in_title",
            "saga_suffix",
            "chronicles_suffix",
        ],
    )
    def test_series_cleaning(
        self,
        golden_inputs: dict,
        golden_expected: dict,
        naming_config: NamingConfig,
        test_id: str,
    ):
        """Test series name cleaning."""
        input_case, expected_case = _get_test_case(golden_inputs, golden_expected, test_id)

        series = input_case.get("series")
        if series is None:
            pytest.skip("No series in test case")

        result = filter_series(series, naming_config=naming_config)

        assert result == expected_case["series"], (
            f"[{test_id}] Series mismatch:\n"
            f"  Input:    {series!r}\n"
            f"  Expected: {expected_case['series']!r}\n"
            f"  Got:      {result!r}"
        )


class TestGoldenPreserveExact:
    """Golden tests specifically for preserve_exact functionality."""

    def test_preserve_exact_drift_check(
        self,
        naming_config: NamingConfig,
    ):
        """Verify that preserve_exact entries are never modified.

        This is a critical safety check - if any entry in preserve_exact
        is modified by filter_title or filter_series, it's a bug.
        """
        for entry in naming_config.preserve_exact:
            # Test with keep_volume=True (JSON context)
            result_json = filter_title(entry, naming_config=naming_config, keep_volume=True)
            assert result_json == entry, (
                f"Preserve-exact drift detected!\n"
                f"  Entry:    {entry!r}\n"
                f"  Result:   {result_json!r}\n"
                f"  Context:  JSON (keep_volume=True)"
            )

            # Test with keep_volume=False (folder context)
            result_folder = filter_title(entry, naming_config=naming_config, keep_volume=False)
            assert result_folder == entry, (
                f"Preserve-exact drift detected!\n"
                f"  Entry:    {entry!r}\n"
                f"  Result:   {result_folder!r}\n"
                f"  Context:  Folder (keep_volume=False)"
            )

            # Test filter_series
            result_series = filter_series(entry, naming_config=naming_config)
            assert result_series == entry, (
                f"Preserve-exact drift detected!\n"
                f"  Entry:    {entry!r}\n"
                f"  Result:   {result_series!r}\n"
                f"  Context:  Series"
            )

    @pytest.mark.parametrize(
        "title,expected_preserved",
        [
            ("Re:ZERO -Starting Life in Another World-, Vol. 1", True),
            ("86--EIGHTY-SIX, Vol. 1", True),
            ("Normal Title (Light Novel)", False),
            ("Overlord, Vol. 3", False),
        ],
    )
    def test_preserve_exact_detection(
        self,
        naming_config: NamingConfig,
        title: str,
        expected_preserved: bool,
    ):
        """Test that preserve_exact correctly identifies titles to preserve."""
        result = filter_title(title, naming_config=naming_config, keep_volume=True)

        if expected_preserved:
            # Title should be unchanged
            assert result == title, (
                f"Expected title to be preserved:\n"
                f"  Input:  {title!r}\n"
                f"  Result: {result!r}"
            )
        else:
            # Title may be changed (or not, depending on content)
            # Just verify the function runs without error
            assert isinstance(result, str)


class TestGoldenSubtitleCleaning:
    """Golden tests for subtitle cleaning (filter_subtitle)."""

    @pytest.mark.parametrize(
        "test_id",
        [
            "light_novel_title_1",
            "light_novel_title_2",
            "meaningful_subtitle",
            "redundant_subtitle",
            "progression_fantasy",
        ],
    )
    def test_subtitle_output(
        self,
        golden_inputs: dict,
        golden_expected: dict,
        naming_config: NamingConfig,
        test_id: str,
    ):
        """Test subtitle filtering matches expected output."""
        input_case, expected_case = _get_test_case(golden_inputs, golden_expected, test_id)

        subtitle = input_case.get("subtitle")
        if subtitle is None:
            pytest.skip("No subtitle in this test case")

        series = input_case.get("series")
        title = input_case.get("title")

        result = filter_subtitle(
            subtitle,
            title=title,
            series=series,
            naming_config=naming_config,
        )

        expected_subtitle = expected_case.get("subtitle")
        # Expected can be None, "", or a string
        if expected_subtitle in (None, ""):
            assert result in (None, ""), (
                f"Test {test_id} failed!\n"
                f"  Input subtitle: {subtitle!r}\n"
                f"  Expected:       {expected_subtitle!r}\n"
                f"  Got:            {result!r}"
            )
        else:
            assert result == expected_subtitle, (
                f"Test {test_id} failed!\n"
                f"  Input subtitle: {subtitle!r}\n"
                f"  Expected:       {expected_subtitle!r}\n"
                f"  Got:            {result!r}"
            )

    @pytest.mark.parametrize(
        "subtitle,expected",
        [
            # Remove patterns
            ("Light Novel", None),
            ("light novel", None),
            ("Unabridged", None),
            ("A LitRPG Adventure", None),
            ("A Progression Fantasy", None),
            # Keep patterns (whitelist)
            ("Aincrad", "Aincrad"),
            ("The Aria Chronicles", "The Aria Chronicles"),
            ("Progressive", "Progressive"),
            # Normal subtitle (no patterns match)
            ("A Tale of Two Cities", "A Tale of Two Cities"),
        ],
    )
    def test_subtitle_pattern_matching(
        self,
        naming_config: NamingConfig,
        subtitle: str,
        expected: str | None,
    ):
        """Test subtitle pattern matching behavior."""
        result = filter_subtitle(subtitle, naming_config=naming_config)
        assert result == expected, (
            f"Subtitle pattern test failed!\n"
            f"  Subtitle: {subtitle!r}\n"
            f"  Expected: {expected!r}\n"
            f"  Got:      {result!r}"
        )

    @pytest.mark.parametrize(
        "subtitle,series,expected",
        [
            # Redundancy rules: series+book -> drop
            ("Overlord, Book 3", "Overlord", None),
            ("Test Series, Book 12", "Test Series", None),
            # Redundancy rules: series in parens -> strip
            ("A Great Adventure (Overlord, Book 3)", "Overlord", "A Great Adventure"),
            # Series match -> drop
            ("The Wandering Inn", "The Wandering Inn", None),
            # No series -> rule skipped
            ("Unknown Series, Book 1", None, "Unknown Series, Book 1"),
        ],
    )
    def test_subtitle_redundancy_rules(
        self,
        naming_config: NamingConfig,
        subtitle: str,
        series: str | None,
        expected: str | None,
    ):
        """Test subtitle redundancy rule behavior."""
        result = filter_subtitle(
            subtitle,
            series=series,
            naming_config=naming_config,
        )
        assert result == expected, (
            f"Redundancy rule test failed!\n"
            f"  Subtitle: {subtitle!r}\n"
            f"  Series:   {series!r}\n"
            f"  Expected: {expected!r}\n"
            f"  Got:      {result!r}"
        )
