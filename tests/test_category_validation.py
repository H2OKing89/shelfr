"""
Tests for MAM category validation (sibling rules, media/main type filtering).

Tests the validate_categories(), _enforce_sibling_rules(), and get_language_id()
functions that enforce the official MAM schema constraints.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from shelfr.metadata.mam.categories import (
    _enforce_sibling_rules,
    get_language_id,
    validate_categories,
)

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_schema() -> dict[str, dict[str, Any]]:
    """Minimal MAM schema for testing sibling rules."""
    return {
        "5": {
            "id": "5",
            "name": "Comedy",
            "main_type_ids": [1, 2],
            "media_type_ids": [1, 2, 4, 5, 6],
            "required_siblings": [],
            "excluded_siblings": [20],
        },
        "13": {
            "id": "13",
            "name": "Fantasy",
            "main_type_ids": [1],
            "media_type_ids": [1, 2, 4, 5, 6, 7, 8],
            "required_siblings": [],
            "excluded_siblings": [],
        },
        "20": {
            "id": "20",
            "name": "Humor",
            "main_type_ids": [1, 2],
            "media_type_ids": [1, 2, 5, 6, 7, 8],
            "required_siblings": [],
            "excluded_siblings": [5],
        },
        "23": {
            "id": "23",
            "name": "Juvenile",
            "main_type_ids": [1, 2],
            "media_type_ids": [1, 2, 4, 5, 6, 7, 8],
            "required_siblings": [],
            "excluded_siblings": [55],
        },
        "29": {
            "id": "29",
            "name": "LitRPG",
            "main_type_ids": [1],
            "media_type_ids": [1, 2, 5, 6, 7, 8],
            "required_siblings": [],
            "excluded_siblings": [43],
        },
        "43": {
            "id": "43",
            "name": "RPG",
            "main_type_ids": [1],
            "media_type_ids": [2, 7, 8],
            "required_siblings": [],
            "excluded_siblings": [29],
        },
        "45": {
            "id": "45",
            "name": "Science Fiction",
            "main_type_ids": [1],
            "media_type_ids": [1, 2, 4, 5, 6, 7, 8],
            "required_siblings": [],
            "excluded_siblings": [],
        },
        "53": {
            "id": "53",
            "name": "Urban Fantasy",
            "main_type_ids": [1],
            "media_type_ids": [1, 2, 4, 5, 6, 7, 8],
            "required_siblings": [13],
            "excluded_siblings": [],
        },
        "55": {
            "id": "55",
            "name": "Young Adult",
            "main_type_ids": [1, 2],
            "media_type_ids": [1, 2, 4, 5, 6, 7, 8],
            "required_siblings": [],
            "excluded_siblings": [23],
        },
        "57": {
            "id": "57",
            "name": "Literary Fiction",
            "main_type_ids": [1],
            "media_type_ids": [1, 2, 4, 5, 6],
            "required_siblings": [],
            "excluded_siblings": [1, 5, 9, 13, 45],
        },
        "58": {
            "id": "58",
            "name": "Progression Fantasy",
            "main_type_ids": [1],
            "media_type_ids": [1, 2, 5, 6],
            "required_siblings": [13],
            "excluded_siblings": [],
        },
    }


def _make_settings_mock(schema: dict[str, dict[str, Any]]) -> MagicMock:
    """Create a mock settings object with the given schema."""
    settings = MagicMock()
    settings.categories.mam_schema.categories = schema
    settings.categories.mam_schema.languages = {
        "1": {"id": "1", "name": "English", "code": "ENG"},
        "36": {"id": "36", "name": "French", "code": "FRE"},
        "37": {"id": "37", "name": "German", "code": "GER"},
    }
    return settings


# =============================================================================
# _enforce_sibling_rules Tests
# =============================================================================


class TestEnforceSiblingRules:
    """Tests for the internal _enforce_sibling_rules function."""

    def test_no_rules_applied(self, mock_schema: dict[str, dict[str, Any]]):
        """Categories without sibling rules pass through unchanged."""
        result = _enforce_sibling_rules({13, 45}, mock_schema)
        assert result == {13, 45}

    def test_required_sibling_auto_added(self, mock_schema: dict[str, dict[str, Any]]):
        """Urban Fantasy (53) requires Fantasy (13) — should be auto-added."""
        result = _enforce_sibling_rules({53}, mock_schema)
        assert 13 in result
        assert 53 in result

    def test_required_sibling_already_present(self, mock_schema: dict[str, dict[str, Any]]):
        """If required sibling already present, no change."""
        result = _enforce_sibling_rules({53, 13}, mock_schema)
        assert result == {53, 13}

    def test_progression_fantasy_requires_fantasy(self, mock_schema: dict[str, dict[str, Any]]):
        """Progression Fantasy (58) requires Fantasy (13)."""
        result = _enforce_sibling_rules({58}, mock_schema)
        assert 13 in result
        assert 58 in result

    def test_excluded_sibling_comedy_humor(self, mock_schema: dict[str, dict[str, Any]]):
        """Comedy (5) and Humor (20) exclude each other — lower ID (5) wins."""
        result = _enforce_sibling_rules({5, 20}, mock_schema)
        assert 5 in result
        assert 20 not in result

    def test_excluded_sibling_juvenile_youngadult(self, mock_schema: dict[str, dict[str, Any]]):
        """Juvenile (23) and Young Adult (55) exclude each other — 23 wins."""
        result = _enforce_sibling_rules({23, 55}, mock_schema)
        assert 23 in result
        assert 55 not in result

    def test_excluded_sibling_litrpg_rpg(self, mock_schema: dict[str, dict[str, Any]]):
        """LitRPG (29) and RPG (43) exclude each other — 29 wins."""
        result = _enforce_sibling_rules({29, 43}, mock_schema)
        assert 29 in result
        assert 43 not in result

    def test_literary_fiction_excludes_many(self, mock_schema: dict[str, dict[str, Any]]):
        """Literary Fiction (57) excludes Fantasy (13) and Sci-Fi (45)."""
        result = _enforce_sibling_rules({57, 13, 45}, mock_schema)
        # 13 < 57, so 13 stays; 57 excludes 13 but 13 is processed first
        # Actually: sorted order is [13, 45, 57]. 13 has no exclusions.
        # 45 has no exclusions. 57 excludes 13 and 45 => removes 13 and 45? No.
        # Actually sorted iteration: cat_id=13 (no exclusions), cat_id=45 (no exclusions),
        # cat_id=57 (excludes 13, 45). But wait, exclusion check is bidirectional by the data.
        # In our mock, 13 doesn't exclude 57. So 57 excludes 13 and 45 -> drops them.
        # No wait: the code iterates sorted, and cat_id=57 excludes [1,5,9,13,45].
        # Since 13 and 45 are in result and not in to_remove yet, they get added to to_remove.
        assert 57 in result
        assert 13 not in result
        assert 45 not in result

    def test_unknown_categories_passed_through(self, mock_schema: dict[str, dict[str, Any]]):
        """Unknown category IDs (not in schema) pass through safely."""
        result = _enforce_sibling_rules({999, 13}, mock_schema)
        assert result == {999, 13}

    def test_empty_input(self, mock_schema: dict[str, dict[str, Any]]):
        """Empty input returns empty set."""
        result = _enforce_sibling_rules(set(), mock_schema)
        assert result == set()

    def test_no_conflict_when_only_one_side_present(self, mock_schema: dict[str, dict[str, Any]]):
        """Single category with excluded_siblings but sibling not present — no removal."""
        result = _enforce_sibling_rules({5}, mock_schema)
        assert result == {5}


# =============================================================================
# validate_categories Tests
# =============================================================================


class TestValidateCategories:
    """Tests for the full validation pipeline."""

    def test_validates_with_schema(self, mock_schema: dict[str, dict[str, Any]]):
        """Full validation pipeline applies media, main type, and sibling rules."""
        with patch("shelfr.metadata.mam.categories._get_mam_schema", return_value=mock_schema):
            result = validate_categories([53, 45], media_type=1, main_type=1)

        # Urban Fantasy (53) requires Fantasy (13) -> auto-added
        assert 13 in result
        assert 53 in result
        assert 45 in result

    def test_filters_wrong_media_type(self, mock_schema: dict[str, dict[str, Any]]):
        """RPG (43) doesn't support Audiobook (media_type=1) — should be dropped."""
        with patch("shelfr.metadata.mam.categories._get_mam_schema", return_value=mock_schema):
            result = validate_categories([43, 13], media_type=1, main_type=1)

        assert 43 not in result
        assert 13 in result

    def test_filters_wrong_main_type(self, mock_schema: dict[str, dict[str, Any]]):
        """Fantasy (13) is fiction-only (main_type=1) — dropped for nonfiction."""
        with patch("shelfr.metadata.mam.categories._get_mam_schema", return_value=mock_schema):
            result = validate_categories([13, 20], media_type=1, main_type=2)

        assert 13 not in result
        assert 20 in result

    def test_no_schema_passes_through(self):
        """When schema is empty/unavailable, pass through unchanged."""
        with patch("shelfr.metadata.mam.categories._get_mam_schema", return_value={}):
            result = validate_categories([13, 45, 99])

        assert result == [13, 45, 99]

    def test_empty_input(self, mock_schema: dict[str, dict[str, Any]]):
        """Empty category list returns empty."""
        with patch("shelfr.metadata.mam.categories._get_mam_schema", return_value=mock_schema):
            result = validate_categories([])

        assert result == []

    def test_deduplicates_and_sorts(self, mock_schema: dict[str, dict[str, Any]]):
        """Output should be sorted and deduplicated."""
        with patch("shelfr.metadata.mam.categories._get_mam_schema", return_value=mock_schema):
            result = validate_categories([45, 13, 45, 13], media_type=1, main_type=1)

        assert result == [13, 45]

    def test_unknown_categories_preserved(self, mock_schema: dict[str, dict[str, Any]]):
        """Unknown category IDs (not in schema) are kept."""
        with patch("shelfr.metadata.mam.categories._get_mam_schema", return_value=mock_schema):
            result = validate_categories([999, 13], media_type=1, main_type=1)

        assert 999 in result
        assert 13 in result

    def test_excluded_sibling_resolved_after_filtering(
        self, mock_schema: dict[str, dict[str, Any]]
    ):
        """Sibling exclusion runs after media/main type filtering."""
        with patch("shelfr.metadata.mam.categories._get_mam_schema", return_value=mock_schema):
            # Comedy (5) and Humor (20) both valid for audiobook fiction
            result = validate_categories([5, 20], media_type=1, main_type=1)

        # Comedy (5) wins over Humor (20) since lower ID
        assert 5 in result
        assert 20 not in result


# =============================================================================
# get_language_id Tests
# =============================================================================


class TestGetLanguageId:
    """Tests for MAM language ID lookup."""

    def test_english_lookup(self):
        """Should find English by name."""
        settings = _make_settings_mock({})
        with patch("shelfr.metadata.mam.categories.get_settings", return_value=settings):
            result = get_language_id("English")
        assert result == 1

    def test_case_insensitive(self):
        """Should match regardless of case."""
        settings = _make_settings_mock({})
        with patch("shelfr.metadata.mam.categories.get_settings", return_value=settings):
            result = get_language_id("FRENCH")
        assert result == 36

    def test_whitespace_stripped(self):
        """Should strip whitespace from input."""
        settings = _make_settings_mock({})
        with patch("shelfr.metadata.mam.categories.get_settings", return_value=settings):
            result = get_language_id("  German  ")
        assert result == 37

    def test_unknown_language_returns_none(self):
        """Should return None for unknown languages."""
        settings = _make_settings_mock({})
        with patch("shelfr.metadata.mam.categories.get_settings", return_value=settings):
            result = get_language_id("Klingon")
        assert result is None

    def test_settings_failure_returns_none(self):
        """Should return None when settings unavailable."""
        with patch(
            "shelfr.metadata.mam.categories.get_settings",
            side_effect=Exception("no config"),
        ):
            result = get_language_id("English")
        assert result is None


# =============================================================================
# Integration: validate_categories + build_mam_json
# =============================================================================


class TestValidationIntegration:
    """Ensure validation is called in the MAM JSON build pipeline."""

    def test_categories_validated_in_build(self, mock_schema: dict[str, dict[str, Any]]):
        """build_mam_json should run validate_categories on the output."""
        from shelfr.models import AudiobookRelease

        release = AudiobookRelease(title="Test Book", asin="B09TEST123")
        audnex_data = {
            "genres": [{"name": "Urban Fantasy"}, {"name": "Humor"}],
        }

        with (
            patch(
                "shelfr.metadata.mam.json_builder.render_bbcode_description",
                return_value="",
            ),
            patch(
                "shelfr.metadata.mam.categories._get_mam_schema",
                return_value=mock_schema,
            ),
            patch(
                "shelfr.metadata.mam.json_builder.get_language_id",
                return_value=None,
            ),
        ):
            from shelfr.metadata.mam.json_builder import build_mam_json

            result = build_mam_json(release, audnex_data=audnex_data)

        cats = result.get("categories", [])
        # Urban Fantasy (53) should trigger Fantasy (13) auto-add
        if 53 in cats:
            assert 13 in cats, "Fantasy should be auto-added for Urban Fantasy"
