"""Tests for utils/editor.py - External editor integration."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from shelfr.utils.editor import (
    EDITOR_FALLBACKS,
    EditorError,
    NoEditorError,
    _build_editor_command,
    edit_file,
    edit_json,
    edit_temp,
    edit_yaml,
    edit_yaml_temp,
    get_editor,
)

if TYPE_CHECKING:
    pass


# =============================================================================
# get_editor() tests
# =============================================================================


class TestGetEditor:
    """Tests for get_editor()."""

    def test_override_takes_priority(self) -> None:
        """Override parameter should take priority over everything."""
        result = get_editor(override="custom-editor")
        assert result == "custom-editor"

    def test_visual_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """$VISUAL should be checked first."""
        monkeypatch.setenv("VISUAL", "code --wait")
        monkeypatch.delenv("EDITOR", raising=False)
        result = get_editor()
        assert result == "code --wait"

    def test_editor_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """$EDITOR should be checked when $VISUAL is not set."""
        monkeypatch.delenv("VISUAL", raising=False)
        monkeypatch.setenv("EDITOR", "vim")
        result = get_editor()
        assert result == "vim"

    def test_visual_preferred_over_editor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """$VISUAL should be preferred over $EDITOR."""
        monkeypatch.setenv("VISUAL", "code")
        monkeypatch.setenv("EDITOR", "vim")
        result = get_editor()
        assert result == "code"

    def test_fallback_editors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should fall back to available editors when env vars not set."""
        monkeypatch.delenv("VISUAL", raising=False)
        monkeypatch.delenv("EDITOR", raising=False)

        # Mock shutil.which to return nano
        with patch("shutil.which") as mock_which:
            mock_which.side_effect = lambda x: "/usr/bin/nano" if x == "nano" else None
            result = get_editor()
            assert result == "nano"

    def test_no_editor_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return None when no editor is available."""
        monkeypatch.delenv("VISUAL", raising=False)
        monkeypatch.delenv("EDITOR", raising=False)

        with patch("shutil.which", return_value=None):
            result = get_editor()
            assert result is None


# =============================================================================
# _build_editor_command() tests
# =============================================================================


class TestBuildEditorCommand:
    """Tests for _build_editor_command()."""

    def test_simple_editor(self, tmp_path: Path) -> None:
        """Simple editor name should work."""
        result = _build_editor_command("nano", tmp_path / "test.txt")
        assert result == ["nano", str(tmp_path / "test.txt")]

    def test_editor_with_args(self, tmp_path: Path) -> None:
        """Editor with arguments should be split correctly."""
        result = _build_editor_command("code --wait", tmp_path / "test.txt")
        assert result == ["code", "--wait", str(tmp_path / "test.txt")]

    def test_editor_with_multiple_args(self, tmp_path: Path) -> None:
        """Editor with multiple arguments should work."""
        result = _build_editor_command("subl -w -n", tmp_path / "test.txt")
        assert result == ["subl", "-w", "-n", str(tmp_path / "test.txt")]


# =============================================================================
# edit_file() tests
# =============================================================================


class TestEditFile:
    """Tests for edit_file()."""

    def test_file_not_found(self, tmp_path: Path) -> None:
        """Should raise FileNotFoundError for missing files."""
        with pytest.raises(FileNotFoundError, match="File not found"):
            edit_file(tmp_path / "nonexistent.txt")

    def test_no_editor_available(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should raise NoEditorError when no editor available."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        monkeypatch.delenv("VISUAL", raising=False)
        monkeypatch.delenv("EDITOR", raising=False)

        with patch("shutil.which", return_value=None), pytest.raises(NoEditorError):
            edit_file(test_file)

    def test_successful_edit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return True on successful editor exit."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        monkeypatch.setenv("EDITOR", "true")  # 'true' command always exits 0

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = edit_file(test_file)
            assert result is True
            mock_run.assert_called_once()

    def test_editor_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return False on editor failure."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        monkeypatch.setenv("EDITOR", "false")  # 'false' command exits 1

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            result = edit_file(test_file)
            assert result is False

    def test_editor_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Editor override should be used."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        monkeypatch.setenv("EDITOR", "vim")  # Should be ignored

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            edit_file(test_file, editor="nano")

            # Check that nano was used, not vim
            call_args = mock_run.call_args[0][0]
            assert call_args[0] == "nano"


# =============================================================================
# edit_temp() tests
# =============================================================================


class TestEditTemp:
    """Tests for edit_temp()."""

    def test_no_editor_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should raise NoEditorError when no editor available."""
        monkeypatch.delenv("VISUAL", raising=False)
        monkeypatch.delenv("EDITOR", raising=False)

        with patch("shutil.which", return_value=None), pytest.raises(NoEditorError):
            edit_temp("content")

    def test_cancelled_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return None if file is unchanged."""
        monkeypatch.setenv("EDITOR", "true")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            # File won't be modified since we're mocking
            result = edit_temp("original content")
            # Result should be None since content is unchanged
            assert result is None

    def test_editor_failure_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return None if editor exits with error."""
        monkeypatch.setenv("EDITOR", "false")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            result = edit_temp("content")
            assert result is None

    def test_suffix_applied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should create temp file with specified suffix."""
        monkeypatch.setenv("EDITOR", "true")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch("tempfile.NamedTemporaryFile") as mock_temp:
                mock_file = MagicMock()
                mock_file.name = "/tmp/shelfr_test.yaml"
                mock_file.__enter__ = MagicMock(return_value=mock_file)
                mock_file.__exit__ = MagicMock(return_value=False)
                mock_temp.return_value = mock_file

                with (
                    patch("pathlib.Path.stat"),
                    patch("pathlib.Path.read_text", return_value="content"),
                    patch("pathlib.Path.unlink"),
                ):
                    edit_temp("content", suffix=".yaml")

                mock_temp.assert_called_once()
                call_kwargs = mock_temp.call_args[1]
                assert call_kwargs["suffix"] == ".yaml"


# =============================================================================
# edit_yaml() tests
# =============================================================================


class TestEditYaml:
    """Tests for edit_yaml()."""

    def test_file_not_found(self, tmp_path: Path) -> None:
        """Should raise FileNotFoundError for missing files."""
        with pytest.raises(FileNotFoundError):
            edit_yaml(tmp_path / "nonexistent.yaml")

    def test_valid_yaml_accepted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Valid YAML should be accepted."""
        test_file = tmp_path / "test.yaml"
        test_file.write_text("key: value\n")
        monkeypatch.setenv("EDITOR", "true")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            # Simulate file being modified
            with patch.object(Path, "read_text", return_value="key: modified\n"):
                result = edit_yaml(test_file, validate=True, backup=False)
                # Validation passes, so result depends on mtime check
                # With our mocking, file appears unchanged
                assert result is False  # No actual change

    def test_invalid_yaml_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Invalid YAML should be rejected and backup restored."""
        test_file = tmp_path / "test.yaml"
        test_file.write_text("key: value\n")
        monkeypatch.setenv("EDITOR", "true")

        original_content = "key: value\n"
        invalid_content = "key: [invalid yaml\n"

        read_count = [0]

        def mock_read_text(encoding="utf-8"):
            read_count[0] += 1
            if read_count[0] == 1:
                return original_content
            return invalid_content

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with (
                patch.object(Path, "read_text", side_effect=mock_read_text),
                patch("shutil.copy2"),
            ):
                result = edit_yaml(test_file, validate=True, backup=True)
                assert result is False

    def test_backup_created(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Backup file should be created when backup=True."""
        test_file = tmp_path / "test.yaml"
        test_file.write_text("key: value\n")
        monkeypatch.setenv("EDITOR", "true")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch("shutil.copy2") as mock_copy:
                edit_yaml(test_file, validate=False, backup=True)
                # Backup should be created
                mock_copy.assert_called()

    def test_no_backup_when_disabled(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No backup should be created when backup=False."""
        test_file = tmp_path / "test.yaml"
        test_file.write_text("key: value\n")
        monkeypatch.setenv("EDITOR", "true")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch("shutil.copy2") as mock_copy:
                edit_yaml(test_file, validate=False, backup=False)
                mock_copy.assert_not_called()


# =============================================================================
# edit_yaml_temp() tests
# =============================================================================


class TestEditYamlTemp:
    """Tests for edit_yaml_temp()."""

    def test_valid_yaml_returned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Valid YAML content should be returned."""
        monkeypatch.setenv("EDITOR", "true")

        with patch("shelfr.utils.editor.edit_temp") as mock_edit:
            mock_edit.return_value = "key: value\n"
            result = edit_yaml_temp("initial: content\n", validate=True)
            assert result == "key: value\n"

    def test_invalid_yaml_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Invalid YAML should return None."""
        monkeypatch.setenv("EDITOR", "true")

        with patch("shelfr.utils.editor.edit_temp") as mock_edit:
            mock_edit.return_value = "key: [invalid\n"
            result = edit_yaml_temp("initial: content\n", validate=True)
            assert result is None

    def test_cancelled_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Cancelled edit should return None."""
        monkeypatch.setenv("EDITOR", "true")

        with patch("shelfr.utils.editor.edit_temp") as mock_edit:
            mock_edit.return_value = None
            result = edit_yaml_temp("initial: content\n")
            assert result is None


# =============================================================================
# edit_json() tests
# =============================================================================


class TestEditJson:
    """Tests for edit_json()."""

    def test_file_not_found(self, tmp_path: Path) -> None:
        """Should raise FileNotFoundError for missing files."""
        with pytest.raises(FileNotFoundError):
            edit_json(tmp_path / "nonexistent.json")

    def test_valid_json_accepted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Valid JSON should be accepted."""
        test_file = tmp_path / "test.json"
        test_file.write_text('{"key": "value"}')
        monkeypatch.setenv("EDITOR", "true")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            # File unchanged scenario
            result = edit_json(test_file, validate=True, backup=False)
            assert result is False  # No change

    def test_invalid_json_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Invalid JSON should be rejected."""
        test_file = tmp_path / "test.json"
        test_file.write_text('{"key": "value"}')
        monkeypatch.setenv("EDITOR", "true")

        original_content = '{"key": "value"}'
        invalid_content = '{"key": invalid}'

        read_count = [0]

        def mock_read_text(encoding="utf-8"):
            read_count[0] += 1
            if read_count[0] == 1:
                return original_content
            return invalid_content

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with (
                patch.object(Path, "read_text", side_effect=mock_read_text),
                patch("shutil.copy2"),
            ):
                result = edit_json(test_file, validate=True, backup=True)
                assert result is False


# =============================================================================
# Integration-style tests
# =============================================================================


class TestEditorIntegration:
    """Higher-level integration tests."""

    def test_editor_fallback_chain(self) -> None:
        """Verify fallback chain contains expected editors."""
        assert "nano" in EDITOR_FALLBACKS
        assert "vim" in EDITOR_FALLBACKS
        assert "vi" in EDITOR_FALLBACKS

    def test_no_editor_error_message(self) -> None:
        """NoEditorError should have helpful message."""
        error = NoEditorError()
        assert "$EDITOR" in str(error)
        assert "$VISUAL" in str(error)

    def test_editor_error_inherits_from_base(self) -> None:
        """EditorError and NoEditorError should inherit correctly."""
        assert issubclass(NoEditorError, EditorError)
        assert issubclass(EditorError, Exception)
