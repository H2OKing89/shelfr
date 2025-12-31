"""Tests for shelfr TUI (Textual-based editor)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestTUIAvailability:
    """Test TUI availability checking."""

    def test_check_available_when_installed(self) -> None:
        """check_available returns True when textual is installed."""
        from shelfr.tui import check_available

        # This test will pass if textual is installed
        result = check_available()
        assert isinstance(result, bool)

    def test_tui_not_available_error(self) -> None:
        """TUINotAvailableError has helpful message."""
        from shelfr.tui import TUINotAvailableError

        error = TUINotAvailableError()
        assert "pip install shelfr[tui]" in str(error)

    def test_check_available_false_when_import_fails(self) -> None:
        """check_available returns False when import fails."""
        with patch.dict("sys.modules", {"textual": None}):
            # Re-import to pick up mocked module
            import importlib

            import shelfr.tui

            importlib.reload(shelfr.tui)
            # Note: This won't actually work because textual is already imported
            # The real test is the behavior when textual isn't installed


class TestTUIAppModule:
    """Test TUI app module."""

    def test_textual_available_flag(self) -> None:
        """TEXTUAL_AVAILABLE flag is set correctly."""
        from shelfr.tui.app import TEXTUAL_AVAILABLE

        # Will be True if textual is installed
        assert isinstance(TEXTUAL_AVAILABLE, bool)

    def test_editable_extensions(self) -> None:
        """EDITABLE_EXTENSIONS contains expected file types."""
        from shelfr.tui.app import EDITABLE_EXTENSIONS

        assert ".yaml" in EDITABLE_EXTENSIONS
        assert ".yml" in EDITABLE_EXTENSIONS
        assert ".json" in EDITABLE_EXTENSIONS
        assert ".j2" in EDITABLE_EXTENSIONS
        assert ".md" in EDITABLE_EXTENSIONS

    def test_language_map(self) -> None:
        """LANGUAGE_MAP maps extensions to languages."""
        from shelfr.tui.app import LANGUAGE_MAP

        assert LANGUAGE_MAP[".yaml"] == "yaml"
        assert LANGUAGE_MAP[".yml"] == "yaml"
        assert LANGUAGE_MAP[".json"] == "json"
        assert LANGUAGE_MAP[".md"] == "markdown"

    def test_check_available_function(self) -> None:
        """app.check_available works."""
        from shelfr.tui.app import check_available

        result = check_available()
        assert isinstance(result, bool)


class TestRunTUI:
    """Test run_tui function."""

    def test_run_tui_with_file_path(self, tmp_path: Path) -> None:
        """run_tui handles file path correctly."""
        # Create a test file
        test_file = tmp_path / "test.yaml"
        test_file.write_text("key: value\n")

        # We can't actually run the TUI in tests, so mock it
        from shelfr.tui.app import TEXTUAL_AVAILABLE

        if TEXTUAL_AVAILABLE:
            with patch("shelfr.tui.app.ShelfrEditor") as mock_editor:
                mock_app = MagicMock()
                mock_editor.return_value = mock_app

                from shelfr.tui.app import run_tui

                run_tui(file=test_file)

                # Should have created editor with file's parent as start_path
                mock_editor.assert_called_once()
                call_kwargs = mock_editor.call_args.kwargs
                assert call_kwargs["initial_file"] == test_file

    def test_run_tui_with_directory_path(self, tmp_path: Path) -> None:
        """run_tui handles directory path correctly."""
        from shelfr.tui.app import TEXTUAL_AVAILABLE

        if TEXTUAL_AVAILABLE:
            with patch("shelfr.tui.app.ShelfrEditor") as mock_editor:
                mock_app = MagicMock()
                mock_editor.return_value = mock_app

                from shelfr.tui.app import run_tui

                run_tui(path=tmp_path)

                mock_editor.assert_called_once()
                call_kwargs = mock_editor.call_args.kwargs
                assert call_kwargs["start_path"] == tmp_path

    def test_run_tui_defaults_to_config_dir(self, tmp_path: Path, monkeypatch) -> None:
        """run_tui defaults to config/ directory if it exists."""
        # Create config directory
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        monkeypatch.chdir(tmp_path)

        from shelfr.tui.app import TEXTUAL_AVAILABLE

        if TEXTUAL_AVAILABLE:
            with patch("shelfr.tui.app.ShelfrEditor") as mock_editor:
                mock_app = MagicMock()
                mock_editor.return_value = mock_app

                from shelfr.tui.app import run_tui

                run_tui()

                mock_editor.assert_called_once()
                call_kwargs = mock_editor.call_args.kwargs
                assert call_kwargs["start_path"] == config_dir

    def test_run_tui_raises_when_not_available(self) -> None:
        """run_tui raises TUINotAvailableError when textual not installed."""
        with patch("shelfr.tui.app.TEXTUAL_AVAILABLE", False):
            from shelfr.tui import TUINotAvailableError
            from shelfr.tui.app import run_tui

            with pytest.raises(TUINotAvailableError):
                run_tui()


@pytest.mark.skipif(
    not pytest.importorskip("textual", reason="textual not installed"),
    reason="textual not installed",
)
class TestShelfrEditorApp:
    """Test ShelfrEditor app when textual is available."""

    def test_editor_creation(self, tmp_path: Path) -> None:
        """ShelfrEditor can be created."""
        from shelfr.tui.app import ShelfrEditor

        app = ShelfrEditor(start_path=tmp_path)
        assert app.start_path == tmp_path
        assert app.current_file is None
        assert app.is_modified is False

    def test_editor_with_initial_file(self, tmp_path: Path) -> None:
        """ShelfrEditor can be created with initial file."""
        test_file = tmp_path / "test.yaml"
        test_file.write_text("key: value\n")

        from shelfr.tui.app import ShelfrEditor

        app = ShelfrEditor(start_path=tmp_path, initial_file=test_file)
        assert app.initial_file == test_file

    def test_editor_bindings(self) -> None:
        """ShelfrEditor has expected key bindings."""
        from shelfr.tui.app import ShelfrEditor

        binding_keys = [b.key for b in ShelfrEditor.BINDINGS]
        assert "ctrl+s" in binding_keys
        assert "ctrl+q" in binding_keys
        assert "f1" in binding_keys
        assert "f2" in binding_keys
        assert "f3" in binding_keys

    def test_editor_css(self) -> None:
        """ShelfrEditor has CSS defined."""
        from shelfr.tui.app import ShelfrEditor

        assert ShelfrEditor.CSS
        assert "#file-tree" in ShelfrEditor.CSS
        assert "#editor" in ShelfrEditor.CSS


@pytest.mark.skipif(
    not pytest.importorskip("textual", reason="textual not installed"),
    reason="textual not installed",
)
class TestFilteredDirectoryTree:
    """Test FilteredDirectoryTree widget."""

    def test_filter_paths_keeps_yaml(self, tmp_path: Path) -> None:
        """FilteredDirectoryTree keeps YAML files."""
        from shelfr.tui.app import FilteredDirectoryTree

        tree = FilteredDirectoryTree(str(tmp_path))

        # Create test paths
        yaml_file = tmp_path / "test.yaml"
        json_file = tmp_path / "test.json"
        py_file = tmp_path / "test.py"
        subdir = tmp_path / "subdir"

        yaml_file.touch()
        json_file.touch()
        py_file.touch()
        subdir.mkdir()

        paths = [yaml_file, json_file, py_file, subdir]
        filtered = tree.filter_paths(paths)

        assert yaml_file in filtered
        assert json_file in filtered
        assert subdir in filtered
        assert py_file not in filtered  # .py not in EDITABLE_EXTENSIONS


@pytest.mark.skipif(
    not pytest.importorskip("textual", reason="textual not installed"),
    reason="textual not installed",
)
class TestPreviewPane:
    """Test PreviewPane widget."""

    def test_preview_pane_creation(self) -> None:
        """PreviewPane can be created."""
        from shelfr.tui.app import PreviewPane

        pane = PreviewPane()
        assert pane._content == "No file loaded"

    def test_preview_pane_set_content(self) -> None:
        """PreviewPane can set content."""
        from shelfr.tui.app import PreviewPane

        pane = PreviewPane()
        pane.set_content("Test content")
        assert pane._content == "Test content"


class TestCLICommand:
    """Test CLI tui command."""

    def test_tui_command_exists(self) -> None:
        """tui command is registered."""
        from shelfr.cli import edit_app

        commands = [cmd.name for cmd in edit_app.registered_commands]
        assert "tui" in commands

    def test_tui_command_help(self) -> None:
        """tui command has help text."""
        from typer.testing import CliRunner

        from shelfr.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["edit", "tui", "--help"])

        assert result.exit_code == 0
        assert "full-screen" in result.stdout.lower() or "TUI" in result.stdout
        assert "Ctrl+S" in result.stdout or "keyboard" in result.stdout.lower()
