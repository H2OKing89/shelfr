"""Golden tests for NormalizedBook using real Audnex samples.

These tests validate the normalize_audnex_book function against real-world
data from the user's Audiobookshelf library, fetched via Audnex API.

Categories tested:
- correct_mapping: Title/subtitle already in correct order
- swapped_mapping: Subtitle has series, title has arc (should swap)
- series_suffix: Series name has "Series" suffix (e.g., "Holes Series" -> "Holes")
- sorting_tag: Series has sorting tag (e.g., "[publication order]")
- the_prefix: Title has "The" but series doesn't (should inherit)
- standalone: No series info (pass-through)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from shelfr.models import NormalizedBook
from shelfr.utils.naming import normalize_audnex_book

# Path to generated golden samples
GOLDEN_SAMPLES_PATH = Path(__file__).parent / "fixtures" / "golden_samples_generated.json"


@pytest.fixture(scope="module")
def golden_samples() -> dict[str, Any]:
    """Load golden test samples from generated fixture file."""
    if not GOLDEN_SAMPLES_PATH.exists():
        pytest.skip(
            f"Golden samples not found at {GOLDEN_SAMPLES_PATH}. "
            "Run: python scripts/build_golden_samples.py"
        )
    with open(GOLDEN_SAMPLES_PATH, encoding="utf-8") as f:
        data = json.load(f)
        # tests expect a mapping of categories -> list[dict]. json.load() returns
        # Any so cast it to the declared return type and assert at runtime to
        # keep mypy happy while still failing loudly if the fixture is bad.
        assert isinstance(data, dict), "golden samples file must be an object/dict"
        return cast(dict[str, Any], data)


def build_audnex_data(sample: dict[str, Any]) -> dict[str, Any]:
    """Convert golden sample to Audnex-style input dict."""
    return {
        "asin": sample["asin"],
        "title": sample["title"],
        "subtitle": sample.get("subtitle"),
        "seriesPrimary": sample.get("seriesPrimary"),
        "authors": sample.get("authors", []),
    }


class TestCorrectMappingSamples:
    """Test samples where title/subtitle are already in correct order."""

    def test_correct_mapping_not_swapped(self, golden_samples: dict[str, Any]) -> None:
        """All correct_mapping samples should NOT be swapped."""
        samples = golden_samples.get("correct_mapping", [])
        assert len(samples) > 0, "No correct_mapping samples found"

        failures: list[str] = []
        for sample in samples:
            data = build_audnex_data(sample)
            result = normalize_audnex_book(data)
            expected = sample["expected"]

            if result.was_swapped != expected["was_swapped"]:
                failures.append(
                    f"ASIN {sample['asin']} ({sample.get('_description', '')}): "
                    f"expected was_swapped={expected['was_swapped']}, got {result.was_swapped}"
                )

        assert not failures, "Failures:\n" + "\n".join(failures)

    def test_correct_mapping_series_extracted(self, golden_samples: dict[str, Any]) -> None:
        """Series info should be correctly extracted."""
        samples = golden_samples.get("correct_mapping", [])

        failures: list[str] = []
        for sample in samples:
            data = build_audnex_data(sample)
            result = normalize_audnex_book(data)
            expected = sample["expected"]

            if result.series_name != expected["series_name"]:
                failures.append(
                    f"ASIN {sample['asin']}: series_name expected={expected['series_name']!r}, "
                    f"got {result.series_name!r}"
                )
            if result.series_position != expected["series_position"]:
                exp_pos = expected["series_position"]
                failures.append(
                    f"ASIN {sample['asin']}: series_position expected={exp_pos!r}, "
                    f"got {result.series_position!r}"
                )

        assert not failures, "Failures:\n" + "\n".join(failures)


class TestSwappedMappingSamples:
    """Test samples where subtitle has series and title has arc (needs swap)."""

    def test_swapped_mapping_detected(self, golden_samples: dict[str, Any]) -> None:
        """All swapped_mapping samples should be detected as swapped."""
        samples = golden_samples.get("swapped_mapping", [])
        assert len(samples) > 0, "No swapped_mapping samples found"

        failures: list[str] = []
        for sample in samples:
            data = build_audnex_data(sample)
            result = normalize_audnex_book(data)
            expected = sample["expected"]

            if result.was_swapped != expected["was_swapped"]:
                failures.append(
                    f"ASIN {sample['asin']} ({sample.get('_description', '')}): "
                    f"title={sample['title']!r}, subtitle={sample.get('subtitle')!r}, "
                    f"series={sample.get('seriesPrimary', {}).get('name')!r} - "
                    f"expected was_swapped={expected['was_swapped']}, got {result.was_swapped}"
                )

        assert not failures, "Failures:\n" + "\n".join(failures)

    def test_swapped_mapping_display_title(self, golden_samples: dict[str, Any]) -> None:
        """Display title should be constructed correctly after swap."""
        samples = golden_samples.get("swapped_mapping", [])

        failures: list[str] = []
        for sample in samples:
            data = build_audnex_data(sample)
            result = normalize_audnex_book(data)
            expected = sample["expected"]

            if result.display_title != expected["display_title"]:
                failures.append(
                    f"ASIN {sample['asin']}: display_title expected={expected['display_title']!r}, "
                    f"got {result.display_title!r}"
                )

        assert not failures, "Failures:\n" + "\n".join(failures)


class TestSeriesSuffixSamples:
    """Test samples where series has 'Series' suffix (e.g., 'Holes Series' -> 'Holes')."""

    def test_series_suffix_stripped(self, golden_samples: dict[str, Any]) -> None:
        """Series suffix should be removed from series_name."""
        samples = golden_samples.get("series_suffix", [])
        if not samples:
            pytest.skip("No series_suffix samples in golden data")

        failures: list[str] = []
        for sample in samples:
            data = build_audnex_data(sample)
            result = normalize_audnex_book(data)
            expected = sample["expected"]

            if result.series_name != expected["series_name"]:
                raw_series = sample.get("seriesPrimary", {}).get("name", "")
                failures.append(
                    f"ASIN {sample['asin']} ({sample.get('_description', '')}): "
                    f"raw series={raw_series!r}, "
                    f"expected series_name={expected['series_name']!r}, "
                    f"got {result.series_name!r}"
                )

        assert not failures, "Failures:\n" + "\n".join(failures)


class TestSortingTagSamples:
    """Test samples where series has sorting tag (e.g., '[publication order]')."""

    def test_sorting_tag_stripped(self, golden_samples: dict[str, Any]) -> None:
        """Sorting tags should be removed from series_name."""
        samples = golden_samples.get("sorting_tag", [])
        if not samples:
            pytest.skip("No sorting_tag samples in golden data")

        failures: list[str] = []
        for sample in samples:
            data = build_audnex_data(sample)
            result = normalize_audnex_book(data)
            expected = sample["expected"]

            if result.series_name != expected["series_name"]:
                raw_series = sample.get("seriesPrimary", {}).get("name", "")
                failures.append(
                    f"ASIN {sample['asin']} ({sample.get('_description', '')}): "
                    f"raw series={raw_series!r}, "
                    f"expected series_name={expected['series_name']!r}, "
                    f"got {result.series_name!r}"
                )

        assert not failures, "Failures:\n" + "\n".join(failures)


class TestThePrefixSamples:
    """Test samples where title has 'The' but series doesn't."""

    def test_the_prefix_inheritance(self, golden_samples: dict[str, Any]) -> None:
        """Series should inherit 'The' prefix from title when appropriate."""
        samples = golden_samples.get("the_prefix", [])
        if not samples:
            pytest.skip("No the_prefix samples in golden data")

        failures: list[str] = []
        for sample in samples:
            data = build_audnex_data(sample)
            result = normalize_audnex_book(data)
            expected = sample["expected"]

            if result.series_name != expected["series_name"]:
                raw_series = sample.get("seriesPrimary", {}).get("name", "")
                failures.append(
                    f"ASIN {sample['asin']} ({sample.get('_description', '')}): "
                    f"title={sample['title']!r}, raw series={raw_series!r}, "
                    f"expected series_name={expected['series_name']!r}, "
                    f"got {result.series_name!r}"
                )

        assert not failures, "Failures:\n" + "\n".join(failures)


class TestStandaloneSamples:
    """Test samples without series info.

    Note: With the title/subtitle-fallback feature, books with volume patterns
    in their title or subtitle (e.g., "Series Name, Vol. 6" or "Series, Book 1")
    will now correctly extract series info even when seriesPrimary is missing.
    This is an improvement over the old behavior where such books were treated
    as standalone.
    """

    def test_standalone_passthrough(self, golden_samples: dict[str, Any]) -> None:
        """Standalone books should pass through unchanged.

        For books where series was extracted from title/subtitle pattern, we
        allow series_name to be non-None (this is an enhancement).
        """
        import re

        samples = golden_samples.get("standalone", [])
        if not samples:
            pytest.skip("No standalone samples in golden data")

        # Pattern that indicates series info might be extracted from title or subtitle
        volume_pattern = re.compile(r"[,:\s]+(?:Volume|Vol\.?|Book|Part)\s*\d+", re.IGNORECASE)

        failures: list[str] = []
        for sample in samples:
            data = build_audnex_data(sample)
            result = normalize_audnex_book(data)
            expected = sample["expected"]

            title = sample.get("title", "")
            subtitle = sample.get("subtitle") or ""

            # If title OR subtitle has volume pattern, series extraction is expected
            has_volume_pattern = volume_pattern.search(title) or volume_pattern.search(subtitle)

            # Check was_swapped - allow difference if volume pattern found
            if result.was_swapped != expected["was_swapped"] and not has_volume_pattern:
                failures.append(
                    f"ASIN {sample['asin']}: was_swapped "
                    f"expected={expected['was_swapped']!r}, got {result.was_swapped!r}"
                )

            # Check series_name - allow extraction from title/subtitle pattern
            if result.series_name != expected["series_name"] and not has_volume_pattern:
                failures.append(
                    f"ASIN {sample['asin']}: series_name "
                    f"expected={expected['series_name']!r}, got {result.series_name!r}"
                )

            # Check display_title - may differ if series was extracted and swapped
            if result.display_title != expected["display_title"] and not has_volume_pattern:
                failures.append(
                    f"ASIN {sample['asin']}: display_title "
                    f"expected={expected['display_title']!r}, got {result.display_title!r}"
                )

        assert not failures, "Failures:\n" + "\n".join(failures)


class TestGoldenSamplesCoverage:
    """Meta-tests to ensure we have good sample coverage."""

    def test_minimum_sample_counts(self, golden_samples: dict[str, Any]) -> None:
        """Ensure we have minimum samples per category."""
        min_counts = {
            "correct_mapping": 10,
            "swapped_mapping": 10,
            "series_suffix": 1,
            "standalone": 1,
        }

        for category, min_count in min_counts.items():
            samples = golden_samples.get(category, [])
            assert len(samples) >= min_count, (
                f"Category '{category}' has only {len(samples)} samples, "
                f"expected at least {min_count}"
            )

    def test_sample_metadata_complete(self, golden_samples: dict[str, Any]) -> None:
        """Verify all samples have required fields."""
        required_fields = {"asin", "title", "expected"}
        expected_fields = {"display_title", "series_name", "was_swapped"}

        errors: list[str] = []
        for category, samples in golden_samples.items():
            if category.startswith("_"):
                continue

            for i, sample in enumerate(samples):
                missing = required_fields - set(sample.keys())
                if missing:
                    errors.append(f"{category}[{i}]: missing {missing}")

                if "expected" in sample:
                    exp_missing = expected_fields - set(sample["expected"].keys())
                    if exp_missing:
                        errors.append(f"{category}[{i}].expected: missing {exp_missing}")

        assert not errors, "Schema errors:\n" + "\n".join(errors[:20])


class TestNormalizedBookOutput:
    """Test that NormalizedBook instances are correctly populated."""

    def test_normalized_book_structure(self, golden_samples: dict[str, Any]) -> None:
        """Verify NormalizedBook has all expected attributes."""
        # Get first sample from any category
        sample = None
        for category in ["correct_mapping", "swapped_mapping", "standalone"]:
            if golden_samples.get(category):
                sample = golden_samples[category][0]
                break

        assert sample is not None, "No samples found"

        data = build_audnex_data(sample)
        result = normalize_audnex_book(data)

        # Check it's the right type
        assert isinstance(result, NormalizedBook)

        # Check all expected attributes exist
        attrs = [
            "asin",
            "raw_title",
            "raw_subtitle",
            "series_name",
            "series_position",
            "arc_name",
            "display_title",
            "display_subtitle",
            "was_swapped",
        ]
        for attr in attrs:
            assert hasattr(result, attr), f"NormalizedBook missing attribute: {attr}"

    @pytest.mark.parametrize(
        "category",
        [
            "correct_mapping",
            "swapped_mapping",
            "series_suffix",
            "sorting_tag",
            "the_prefix",
            "standalone",
        ],
    )
    def test_category_samples_normalize(
        self, golden_samples: dict[str, Any], category: str
    ) -> None:
        """Each category's samples should normalize without errors."""
        samples = golden_samples.get(category, [])
        if not samples:
            pytest.skip(f"No {category} samples")

        for sample in samples[:10]:  # Test first 10 per category
            data = build_audnex_data(sample)
            result = normalize_audnex_book(data)
            assert result.asin == sample["asin"]
            assert isinstance(result, NormalizedBook)
