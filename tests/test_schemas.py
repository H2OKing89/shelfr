"""Tests for Pydantic schema validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shelfr.schemas.naming import (
    validate_naming_json,
)


class TestNamingSchemaValidation:
    """Tests for NamingSchema validation."""

    def test_valid_minimal_config(self):
        """Test that a minimal valid config passes validation."""
        data = {"_version": "1.0.0"}
        schema = validate_naming_json(data)
        assert schema.version == "1.0.0"

    def test_valid_full_config(self):
        """Test that a full valid config passes validation."""
        data = {
            "_version": "1.5.0",
            "title_subtitle_normalization": {"enabled": True, "log_swaps": True},
            "format_indicators": {
                "match_mode": "phrase",
                "case_sensitive": False,
                "phrases": ["(Light Novel)", "Unabridged"],
            },
            "genre_tags": {
                "match_mode": "phrase",
                "phrases": ["A LitRPG Adventure"],
            },
            "series_suffixes": {
                "match_mode": "regex",
                "patterns": [r"[\s—-]?[Ss]eries$", r"[\s—-]?[Tt]rilogy$"],
            },
            "publisher_tags": {"phrases": ["[Yen Audio]"]},
            "subtitle_patterns": {
                "remove_if_matches_series": True,
                "remove_patterns": [r"^[Ll]ight [Nn]ovel$"],
                "keep_patterns": [r".*[Aa]ria.*"],
            },
            "subtitle_redundancy_rules": {
                "enabled": True,
                "rules": [
                    {
                        "id": "series_book",
                        "description": "Subtitle is just 'Series, Book N'",
                        "pattern_template": r"^{{series}},?\s*Book\s*\d+$",
                        "action": "drop_subtitle",
                    }
                ],
            },
            "preserve_exact": {"case_sensitive": True, "titles": ["Re:ZERO"]},
            "author_map": {"猫子": "Necoco"},
            "author_roles": {"roles": ["translator", "illustrator"]},
        }
        schema = validate_naming_json(data)
        assert schema.version == "1.5.0"
        assert len(schema.format_indicators.phrases) == 2
        assert len(schema.series_suffixes.patterns) == 2
        assert schema.subtitle_redundancy_rules.enabled is True

    def test_invalid_version_format(self):
        """Test that invalid version format is rejected."""
        data = {"_version": "1.0"}  # Missing patch version
        with pytest.raises(ValidationError) as exc_info:
            validate_naming_json(data)
        assert "version" in str(exc_info.value)

    def test_missing_version_uses_default(self):
        """Test that missing version uses default value."""
        data = {"format_indicators": {"phrases": ["test"]}}
        schema = validate_naming_json(data)
        assert schema.version == "0.0.0"  # Default value


class TestRegexPatternValidation:
    """Tests for regex pattern validation."""

    def test_valid_regex_patterns(self):
        """Test that valid regex patterns pass validation."""
        data = {
            "_version": "1.0.0",
            "series_suffixes": {
                "match_mode": "regex",
                "patterns": [
                    r"[\s—-]?[Ss]eries$",
                    r"\s*\([Ll]ight [Nn]ovel\)$",
                    r"^Book\s+\d+$",
                ],
            },
        }
        schema = validate_naming_json(data)
        assert len(schema.series_suffixes.patterns) == 3

    def test_invalid_regex_unterminated_bracket(self):
        """Test that unterminated character class is caught."""
        data = {
            "_version": "1.0.0",
            "series_suffixes": {"patterns": ["[invalid"]},
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_naming_json(data)
        assert "Invalid regex pattern" in str(exc_info.value)

    def test_invalid_regex_unbalanced_parens(self):
        """Test that unbalanced parentheses are caught."""
        data = {
            "_version": "1.0.0",
            "series_suffixes": {"patterns": ["(unbalanced"]},
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_naming_json(data)
        assert "Invalid regex pattern" in str(exc_info.value)

    def test_subtitle_remove_pattern_validation(self):
        """Test that subtitle remove patterns are validated."""
        data = {
            "_version": "1.0.0",
            "subtitle_patterns": {"remove_patterns": ["[bad"]},
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_naming_json(data)
        assert "Invalid regex pattern" in str(exc_info.value)

    def test_subtitle_keep_pattern_validation(self):
        """Test that subtitle keep patterns are validated."""
        data = {
            "_version": "1.0.0",
            "subtitle_patterns": {"keep_patterns": ["(bad"]},
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_naming_json(data)
        assert "Invalid regex pattern" in str(exc_info.value)


class TestSubtitleRedundancyRules:
    """Tests for subtitle redundancy rule validation."""

    def test_valid_redundancy_rule(self):
        """Test that valid redundancy rules pass validation."""
        data = {
            "_version": "1.0.0",
            "subtitle_redundancy_rules": {
                "enabled": True,
                "rules": [
                    {
                        "id": "test_rule",
                        "description": "Test rule description",
                        "pattern_template": r"^{{series}},?\s*Book\s*\d+$",
                        "action": "drop_subtitle",
                    },
                    {
                        "id": "strip_rule",
                        "description": "Strip match rule",
                        "pattern_template": r"\({{title}}\)$",
                        "action": "strip_match",
                    },
                ],
            },
        }
        schema = validate_naming_json(data)
        assert len(schema.subtitle_redundancy_rules.rules) == 2
        assert schema.subtitle_redundancy_rules.rules[0].action == "drop_subtitle"

    def test_invalid_action_type(self):
        """Test that invalid action type is rejected."""
        data = {
            "_version": "1.0.0",
            "subtitle_redundancy_rules": {
                "rules": [
                    {
                        "id": "bad_rule",
                        "description": "Bad action",
                        "pattern_template": "^test$",
                        "action": "invalid_action",
                    }
                ]
            },
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_naming_json(data)
        assert "action" in str(exc_info.value)

    def test_invalid_pattern_template(self):
        """Test that invalid regex in pattern_template is caught."""
        data = {
            "_version": "1.0.0",
            "subtitle_redundancy_rules": {
                "rules": [
                    {
                        "id": "bad_pattern",
                        "description": "Bad pattern template",
                        "pattern_template": "[unclosed",
                        "action": "drop_subtitle",
                    }
                ]
            },
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_naming_json(data)
        assert "Invalid regex template" in str(exc_info.value)

    def test_missing_required_fields(self):
        """Test that missing required fields are caught."""
        data = {
            "_version": "1.0.0",
            "subtitle_redundancy_rules": {
                "rules": [
                    {
                        "id": "incomplete_rule",
                        # Missing description, pattern_template, action
                    }
                ]
            },
        }
        with pytest.raises(ValidationError):
            validate_naming_json(data)


class TestAuthorMapValidation:
    """Tests for author map validation."""

    def test_valid_author_map(self):
        """Test that valid author map passes validation."""
        data = {
            "_version": "1.0.0",
            "author_map": {
                "猫子": "Necoco",
                "川原 礫": "Reki Kawahara",
            },
        }
        schema = validate_naming_json(data)
        assert len(schema.author_map) == 2
        assert schema.author_map["猫子"] == "Necoco"

    def test_comment_keys_filtered(self):
        """Test that comment keys starting with underscore are filtered."""
        data = {
            "_version": "1.0.0",
            "author_map": {
                "_comment": "This is a comment",
                "猫子": "Necoco",
            },
        }
        schema = validate_naming_json(data)
        assert "_comment" not in schema.author_map
        assert len(schema.author_map) == 1


class TestExtraFieldsRejected:
    """Tests that extra/unknown fields are rejected."""

    def test_unknown_top_level_field(self):
        """Test that unknown top-level fields are rejected."""
        data = {
            "_version": "1.0.0",
            "unknown_field": "should fail",
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_naming_json(data)
        assert "extra" in str(exc_info.value).lower() or "unknown_field" in str(exc_info.value)


class TestCommentFiltering:
    """Tests for comment field filtering."""

    def test_top_level_comments_filtered(self):
        """Test that top-level _comment fields are filtered before validation."""
        data = {
            "_comment": "This is a top-level comment",
            "_version": "1.0.0",
            "format_indicators": {"phrases": []},
        }
        # Should not raise - _comment should be filtered
        schema = validate_naming_json(data)
        assert schema.version == "1.0.0"


class TestIntegrationWithRealConfig:
    """Integration tests using real config file structure."""

    def test_full_naming_json_structure(self):
        """Test validation of a config matching the real naming.json structure."""
        data = {
            "_comment": "Naming rules for MAMFast.",
            "_version": "1.5.0",
            "title_subtitle_normalization": {
                "_comment": "Fix Audible's inconsistent title/subtitle swaps.",
                "enabled": True,
                "log_swaps": True,
            },
            "author_roles": {
                "_comment": "Non-author roles to filter.",
                "match_mode": "suffix",
                "case_sensitive": False,
                "roles": ["translator", "illustrator"],
                "credit_roles": ["afterword", "foreword"],
            },
            "format_indicators": {
                "_comment": "Remove from titles.",
                "match_mode": "phrase",
                "case_sensitive": False,
                "phrases": ["(Light Novel)", "Unabridged"],
            },
            "genre_tags": {
                "match_mode": "phrase",
                "case_sensitive": False,
                "phrases": ["A LitRPG Adventure"],
            },
            "series_suffixes": {
                "match_mode": "regex",
                "case_sensitive": False,
                "patterns": [r"[\s—-]?[Ss]eries$"],
            },
            "publisher_tags": {
                "match_mode": "phrase",
                "phrases": ["[Yen Audio]"],
            },
            "subtitle_patterns": {
                "remove_if_matches_series": True,
                "remove_patterns": [r"^[Ll]ight [Nn]ovel$"],
                "keep_patterns": [r".*[Aa]ria.*"],
            },
            "subtitle_redundancy_rules": {
                "enabled": True,
                "rules": [
                    {
                        "id": "series_book",
                        "description": "Subtitle is just 'Series, Book N'",
                        "pattern_template": r"^{{series}},?\s*Book\s*\d+$",
                        "action": "drop_subtitle",
                    }
                ],
            },
            "preserve_exact": {
                "case_sensitive": True,
                "titles": ["Re:ZERO"],
            },
            "author_map": {
                "_comment": "Foreign name -> Romanized name.",
                "猫子": "Necoco",
            },
            "preserve_in_json": {
                "volume_patterns": [r"Vol\. \d+"],
            },
        }
        schema = validate_naming_json(data)
        assert schema.version == "1.5.0"
        assert schema.title_subtitle_normalization.enabled is True
        assert "translator" in schema.author_roles.roles
        assert len(schema.format_indicators.phrases) == 2
        assert schema.subtitle_redundancy_rules.enabled is True
