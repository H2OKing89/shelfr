"""Tests for utils/mini_editor.py - Inline terminal editor."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

# Import availability flags first
from shelfr.utils.mini_editor import (
    PROMPT_TOOLKIT_AVAILABLE,
    PYGMENTS_AVAILABLE,
    MiniEditorError,
    MiniEditorNotAvailable,
    check_available,
)

if TYPE_CHECKING:
    pass


# =============================================================================
# Availability Tests
# =============================================================================


class TestAvailability:
    """Tests for dependency availability checking."""

    def test_check_available_returns_bool(self) -> None:
        """check_available() should return a boolean."""
        result = check_available()
        assert isinstance(result, bool)

    def test_prompt_toolkit_flag_is_bool(self) -> None:
        """PROMPT_TOOLKIT_AVAILABLE should be a boolean."""
        assert isinstance(PROMPT_TOOLKIT_AVAILABLE, bool)

    def test_pygments_flag_is_bool(self) -> None:
        """PYGMENTS_AVAILABLE should be a boolean."""
        assert isinstance(PYGMENTS_AVAILABLE, bool)


# =============================================================================
# Error Classes Tests
# =============================================================================


class TestErrors:
    """Tests for error classes."""

    def test_mini_editor_error_is_exception(self) -> None:
        """MiniEditorError should inherit from Exception."""
        assert issubclass(MiniEditorError, Exception)

    def test_mini_editor_not_available_message(self) -> None:
        """MiniEditorNotAvailable should have helpful message."""
        error = MiniEditorNotAvailable()
        assert "prompt_toolkit" in str(error)
        assert "pip install" in str(error)

    def test_mini_editor_not_available_inherits(self) -> None:
        """MiniEditorNotAvailable should inherit from MiniEditorError."""
        assert issubclass(MiniEditorNotAvailable, MiniEditorError)


# =============================================================================
# Tests that require prompt_toolkit
# =============================================================================


@pytest.mark.skipif(
    not PROMPT_TOOLKIT_AVAILABLE,
    reason="prompt_toolkit not installed",
)
class TestMiniEdit:
    """Tests for mini_edit() function."""

    def test_import_functions(self) -> None:
        """Should be able to import editing functions."""
        from shelfr.utils.mini_editor import (
            edit_file_inline,
            edit_json_inline,
            edit_text_inline,
            edit_yaml_inline,
            mini_edit,
        )

        assert callable(mini_edit)
        assert callable(edit_yaml_inline)
        assert callable(edit_json_inline)
        assert callable(edit_text_inline)
        assert callable(edit_file_inline)


@pytest.mark.skipif(
    not PROMPT_TOOLKIT_AVAILABLE,
    reason="prompt_toolkit not installed",
)
class TestGetLexer:
    """Tests for _get_lexer_for_suffix()."""

    def test_yaml_lexer(self) -> None:
        """Should return lexer for YAML files."""
        from shelfr.utils.mini_editor import _get_lexer_for_suffix

        lexer = _get_lexer_for_suffix(".yaml")
        if PYGMENTS_AVAILABLE:
            assert lexer is not None
        else:
            assert lexer is None

    def test_yml_lexer(self) -> None:
        """Should return lexer for .yml files."""
        from shelfr.utils.mini_editor import _get_lexer_for_suffix

        lexer = _get_lexer_for_suffix(".yml")
        if PYGMENTS_AVAILABLE:
            assert lexer is not None

    def test_json_lexer(self) -> None:
        """Should return lexer for JSON files."""
        from shelfr.utils.mini_editor import _get_lexer_for_suffix

        lexer = _get_lexer_for_suffix(".json")
        if PYGMENTS_AVAILABLE:
            assert lexer is not None

    def test_unknown_suffix(self) -> None:
        """Should return None for unknown suffixes."""
        from shelfr.utils.mini_editor import _get_lexer_for_suffix

        lexer = _get_lexer_for_suffix(".xyz")
        assert lexer is None

    def test_case_insensitive(self) -> None:
        """Should be case-insensitive."""
        from shelfr.utils.mini_editor import _get_lexer_for_suffix

        lexer1 = _get_lexer_for_suffix(".YAML")
        lexer2 = _get_lexer_for_suffix(".yaml")
        # Both should return same type (or None if pygments unavailable)
        assert type(lexer1) == type(lexer2)


# =============================================================================
# Tests without prompt_toolkit (mock unavailability)
# =============================================================================


class TestWithoutPromptToolkit:
    """Tests when prompt_toolkit is not available."""

    def test_mini_edit_raises_when_unavailable(self) -> None:
        """mini_edit should raise MiniEditorNotAvailable when deps missing."""
        with patch("shelfr.utils.mini_editor.PROMPT_TOOLKIT_AVAILABLE", False):
            # Re-import to get the patched version behavior
            # Actually, we need to test the actual function
            from shelfr.utils.mini_editor import mini_edit

            # The function checks the flag at runtime
            if not PROMPT_TOOLKIT_AVAILABLE:
                with pytest.raises(MiniEditorNotAvailable):
                    mini_edit("test")


# =============================================================================
# Preview Module Tests
# =============================================================================


class TestPreviewModule:
    """Tests for utils/preview.py."""

    def test_preview_yaml(self, capsys: pytest.CaptureFixture) -> None:
        """preview_yaml should display YAML content."""
        from shelfr.utils.preview import preview_yaml

        preview_yaml("key: value\nlist:\n  - item1")
        # Just verify it doesn't crash - output goes to rich console

    def test_preview_json(self, capsys: pytest.CaptureFixture) -> None:
        """preview_json should display JSON content."""
        from shelfr.utils.preview import preview_json

        preview_json('{"key": "value"}')

    def test_preview_markdown(self) -> None:
        """preview_markdown should display markdown."""
        from shelfr.utils.preview import preview_markdown

        preview_markdown("# Title\n\nSome **bold** text")

    def test_preview_diff_with_changes(self) -> None:
        """preview_diff should return True when there are changes."""
        from shelfr.utils.preview import preview_diff

        result = preview_diff("line1\nline2", "line1\nline2 modified")
        assert result is True

    def test_preview_diff_no_changes(self) -> None:
        """preview_diff should return False when content is identical."""
        from shelfr.utils.preview import preview_diff

        result = preview_diff("same content", "same content")
        assert result is False

    def test_preview_file(self, tmp_path: Path) -> None:
        """preview_file should display file content."""
        from shelfr.utils.preview import preview_file

        test_file = tmp_path / "test.yaml"
        test_file.write_text("key: value\n")

        # Should not raise
        preview_file(test_file)

    def test_preview_file_not_found(self, tmp_path: Path) -> None:
        """preview_file should handle missing files gracefully."""
        from shelfr.utils.preview import preview_file

        # Should print error, not raise
        preview_file(tmp_path / "nonexistent.yaml")

    def test_preview_yaml_structure(self) -> None:
        """preview_yaml_structure should show tree."""
        from shelfr.utils.preview import preview_yaml_structure

        content = "root:\n  child: value\n  list:\n    - item1\n    - item2"
        # Should not raise
        preview_yaml_structure(content)

    def test_preview_yaml_structure_invalid(self) -> None:
        """preview_yaml_structure should handle invalid YAML."""
        from shelfr.utils.preview import preview_yaml_structure

        # Should print error, not raise
        preview_yaml_structure("invalid: [yaml")

    def test_preview_validation_result_valid_yaml(self) -> None:
        """preview_validation_result should return True for valid YAML."""
        from shelfr.utils.preview import preview_validation_result

        result = preview_validation_result("key: value", "yaml")
        assert result is True

    def test_preview_validation_result_invalid_yaml(self) -> None:
        """preview_validation_result should return False for invalid YAML."""
        from shelfr.utils.preview import preview_validation_result

        result = preview_validation_result("key: [invalid", "yaml")
        assert result is False

    def test_preview_validation_result_valid_json(self) -> None:
        """preview_validation_result should return True for valid JSON."""
        from shelfr.utils.preview import preview_validation_result

        result = preview_validation_result('{"key": "value"}', "json")
        assert result is True

    def test_preview_validation_result_invalid_json(self) -> None:
        """preview_validation_result should return False for invalid JSON."""
        from shelfr.utils.preview import preview_validation_result

        result = preview_validation_result('{"key": invalid}', "json")
        assert result is False

    def test_preview_bbcode(self) -> None:
        """preview_bbcode should display BBCode content."""
        from shelfr.utils.preview import preview_bbcode

        # Should not raise
        preview_bbcode("[b]Bold[/b] and [i]italic[/i]")

    def test_preview_comparison_table(self) -> None:
        """preview_comparison_table should display table."""
        from shelfr.utils.preview import preview_comparison_table

        items = [
            ("key1", "old1", "new1"),
            ("key2", "same", "same"),
        ]
        # Should not raise
        preview_comparison_table(items)

    def test_preview_side_by_side(self) -> None:
        """preview_side_by_side should display two panels."""
        from shelfr.utils.preview import preview_side_by_side

        # Should not raise
        preview_side_by_side("before", "after", syntax="yaml")


# =============================================================================
# Integration-style Tests
# =============================================================================


class TestIntegration:
    """Higher-level integration tests."""

    def test_help_text_defined(self) -> None:
        """HELP_TEXT should be defined."""
        from shelfr.utils.mini_editor import HELP_TEXT

        assert "Ctrl+D" in HELP_TEXT
        assert "Save" in HELP_TEXT

    def test_style_dict_defined(self) -> None:
        """EDITOR_STYLE_DICT should be defined."""
        from shelfr.utils.mini_editor import EDITOR_STYLE_DICT

        assert isinstance(EDITOR_STYLE_DICT, dict)
        assert "" in EDITOR_STYLE_DICT  # Default style
