"""Textual TUI application for shelfr configuration editing.

A full-screen terminal UI with file browser, editor, and preview panes.
Supports YAML, JSON, Jinja2, and Markdown files.

Usage:
    shelfr edit tui              # Open at config/
    shelfr edit tui /path/to     # Open at specific directory
    shelfr edit tui file.yaml    # Open specific file
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any, ClassVar

logger = logging.getLogger(__name__)

# Lazy imports for optional textual dependency
try:
    from textual import on
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Vertical
    from textual.reactive import reactive
    from textual.widgets import (
        DirectoryTree,
        Footer,
        Header,
        Static,
        TextArea,
    )

    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False
    # Stubs for when textual is not installed
    App: Any = object
    on: Any = None
    ComposeResult: Any = None
    Binding: Any = None
    Vertical: Any = None
    reactive: Any = None
    DirectoryTree: Any = None
    Footer: Any = None
    Header: Any = None
    Static: Any = None
    TextArea: Any = None


# File extensions we support editing
EDITABLE_EXTENSIONS = {
    ".yaml",
    ".yml",
    ".json",
    ".j2",
    ".jinja2",
    ".md",
    ".txt",
    ".toml",
}

# Language mapping for syntax highlighting
LANGUAGE_MAP = {
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".j2": "jinja2",
    ".jinja2": "jinja2",
    ".md": "markdown",
    ".txt": None,
    ".toml": "toml",
}


def check_available() -> bool:
    """Check if Textual is available."""
    return TEXTUAL_AVAILABLE


if TEXTUAL_AVAILABLE:

    class FilteredDirectoryTree(DirectoryTree):
        """Directory tree that only shows editable files."""

        def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
            """Filter to show only directories and editable files."""
            return [
                path
                for path in paths
                if path.is_dir()
                or path.suffix.lower() in EDITABLE_EXTENSIONS
                # Always show common config files
                or path.name in {"Makefile", "Dockerfile", ".env.example"}
            ]

    class PreviewPane(Static):
        """Preview pane showing validation results and file info."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._content = "No file loaded"

        def set_content(self, content: str) -> None:
            """Update preview content."""
            self._content = content
            self.update(content)

        def show_validation(self, valid: bool, message: str) -> None:
            """Show validation result."""
            icon = "✓" if valid else "✗"
            color = "green" if valid else "red"
            self.update(f"[{color}]{icon}[/] {message}")

        def show_file_info(self, path: Path, content: str) -> None:
            """Show file information."""
            lines = content.count("\n") + 1
            size = len(content.encode("utf-8"))
            info = f"[bold]{path.name}[/]\n"
            info += f"   Lines: {lines}\n"
            info += f"   Size: {size:,} bytes\n"
            info += f"   Type: {path.suffix or 'unknown'}"
            self.update(info)

    class ShelfrEditor(App[None]):
        """Full-screen TUI editor for shelfr configuration files."""

        TITLE = "shelfr Editor"
        SUB_TITLE = "Edit configuration files"

        CSS: ClassVar[str] = """
        Screen {
            layout: grid;
            grid-size: 3 2;
            grid-columns: 1fr 2fr 1fr;
            grid-rows: 3fr 1fr;
        }

        #file-tree {
            column-span: 1;
            row-span: 2;
            border: solid $primary;
            border-title-color: $primary;
            background: $surface;
        }

        #editor-container {
            column-span: 1;
            row-span: 1;
            border: solid $secondary;
            border-title-color: $secondary;
        }

        #editor {
            height: 100%;
            width: 100%;
        }

        #info-pane {
            column-span: 1;
            row-span: 2;
            border: solid $accent;
            border-title-color: $accent;
            background: $surface;
            padding: 1;
        }

        #status-bar {
            column-span: 2;
            row-span: 1;
            border: solid $warning;
            border-title-color: $warning;
            padding: 0 1;
        }

        .modified {
            border: solid $error;
        }

        TextArea {
            height: 100%;
        }

        TextArea:focus {
            border: double $secondary;
        }

        DirectoryTree {
            scrollbar-gutter: stable;
        }

        DirectoryTree:focus {
            border: double $primary;
        }
        """

        BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
            Binding("ctrl+s", "save", "Save", priority=True),
            Binding("ctrl+q", "quit", "Quit", priority=True),
            Binding("f1", "help", "Help"),
            Binding("f2", "save", "Save"),
            Binding("f3", "validate", "Validate"),
            Binding("f5", "reload", "Reload"),
            Binding("ctrl+o", "focus_tree", "Files"),
            Binding("ctrl+e", "focus_editor", "Editor"),
            Binding("escape", "unfocus", "Unfocus"),
        ]

        # Reactive state
        current_file: reactive[Path | None] = reactive(None)
        is_modified: reactive[bool] = reactive(False)

        def __init__(
            self,
            start_path: Path | None = None,
            initial_file: Path | None = None,
        ) -> None:
            """Initialize the editor.

            Args:
                start_path: Directory to show in file tree.
                initial_file: File to open initially.
            """
            super().__init__()
            self.start_path = start_path or Path.cwd()
            self.initial_file = initial_file
            self._original_content: str = ""

        def compose(self) -> ComposeResult:
            """Compose the application UI."""
            yield Header()

            # File tree (left)
            tree = FilteredDirectoryTree(
                str(self.start_path),
                id="file-tree",
            )
            tree.border_title = "Files"
            yield tree

            # Editor (center)
            with Vertical(id="editor-container"):
                editor = TextArea(id="editor", language="yaml")
                editor.border_title = "Editor"
                yield editor

            # Info pane (right)
            info = PreviewPane(id="info-pane")
            info.border_title = "Info"
            yield info

            # Status bar (bottom)
            status = Static(id="status-bar")
            status.border_title = "Status"
            yield status

            yield Footer()

        def on_mount(self) -> None:
            """Handle app mount - load initial file if specified."""
            self._update_status("Ready. Press F1 for help.")

            # Focus the file tree initially
            self.query_one("#file-tree").focus()

            # Load initial file if specified
            if self.initial_file and self.initial_file.exists():
                self.load_file(self.initial_file)

        @on(DirectoryTree.FileSelected)
        def handle_file_selected(self, event: DirectoryTree.FileSelected) -> None:
            """Handle file selection from tree."""
            path = Path(event.path)
            if path.suffix.lower() in EDITABLE_EXTENSIONS or path.name in {
                "Makefile",
                "Dockerfile",
                ".env.example",
            }:
                self.load_file(path)

        @on(TextArea.Changed)
        def handle_text_changed(self, event: TextArea.Changed) -> None:
            """Handle text changes in editor."""
            editor = self.query_one("#editor", TextArea)
            self.is_modified = editor.text != self._original_content

            # Update border to show modified state
            container = self.query_one("#editor-container")
            if self.is_modified:
                container.add_class("modified")
                container.border_title = "Editor [modified]"
            else:
                container.remove_class("modified")
                container.border_title = "Editor"

        def watch_current_file(self, path: Path | None) -> None:
            """React to current file changes."""
            if path:
                self.sub_title = str(path.name)
            else:
                self.sub_title = "Edit configuration files"

        def load_file(self, path: Path) -> None:
            """Load a file into the editor."""
            try:
                content = path.read_text(encoding="utf-8")
            except Exception as e:
                self.notify(f"Error loading file: {e}", severity="error")
                return

            self.current_file = path
            self._original_content = content

            # Update editor
            editor = self.query_one("#editor", TextArea)
            editor.text = content

            # Set language for syntax highlighting
            lang = LANGUAGE_MAP.get(path.suffix.lower())
            if lang:
                editor.language = lang

            # Update info pane
            info = self.query_one("#info-pane", PreviewPane)
            info.show_file_info(path, content)

            # Validate if applicable
            self._validate_content(content, path)

            self.is_modified = False
            self._update_status(f"Loaded: {path.name}")

            # Focus editor
            editor.focus()

        def _validate_content(self, content: str, path: Path) -> None:
            """Validate file content based on type."""
            info = self.query_one("#info-pane", PreviewPane)
            suffix = path.suffix.lower()

            if suffix in (".yaml", ".yml"):
                self._validate_yaml(content, info)
            elif suffix == ".json":
                self._validate_json(content, info)
            else:
                info.show_file_info(path, content)

        def _validate_yaml(self, content: str, info: PreviewPane) -> None:
            """Validate YAML content."""
            import yaml

            try:
                data = yaml.safe_load(content)
                if isinstance(data, dict):
                    keys = list(data.keys())[:5]
                    msg = f"Valid YAML\nTop keys: {', '.join(keys)}"
                    if len(data) > 5:
                        msg += f"\n... and {len(data) - 5} more"
                else:
                    msg = f"Valid YAML ({type(data).__name__})"
                info.show_validation(True, msg)
            except yaml.YAMLError as e:
                info.show_validation(False, f"Invalid YAML:\n{e}")

        def _validate_json(self, content: str, info: PreviewPane) -> None:
            """Validate JSON content."""
            try:
                data = json.loads(content)
                if isinstance(data, dict):
                    keys = list(data.keys())[:5]
                    msg = f"Valid JSON\nTop keys: {', '.join(keys)}"
                elif isinstance(data, list):
                    msg = f"Valid JSON (array with {len(data)} items)"
                else:
                    msg = f"Valid JSON ({type(data).__name__})"
                info.show_validation(True, msg)
            except json.JSONDecodeError as e:
                info.show_validation(False, f"Invalid JSON:\n{e}")

        def _update_status(self, message: str) -> None:
            """Update status bar."""
            status = self.query_one("#status-bar", Static)
            file_info = ""
            if self.current_file:
                mod = " [modified]" if self.is_modified else ""
                file_info = f" | {self.current_file.name}{mod}"
            status.update(f"{message}{file_info}")

        # Actions

        def action_save(self) -> None:
            """Save the current file."""
            if not self.current_file:
                self.notify("No file to save", severity="warning")
                return

            editor = self.query_one("#editor", TextArea)
            content = editor.text

            try:
                # Create backup
                backup_path = self.current_file.with_suffix(self.current_file.suffix + ".bak")
                if self.current_file.exists():
                    backup_path.write_text(
                        self.current_file.read_text(encoding="utf-8"),
                        encoding="utf-8",
                    )

                # Write file
                self.current_file.write_text(content, encoding="utf-8")
                self._original_content = content
                self.is_modified = False

                # Re-validate
                self._validate_content(content, self.current_file)

                self.notify(f"Saved: {self.current_file.name}")
                self._update_status(f"Saved: {self.current_file.name}")

            except Exception as e:
                self.notify(f"Error saving: {e}", severity="error")

        def action_validate(self) -> None:
            """Validate current content."""
            if not self.current_file:
                self.notify("No file loaded", severity="warning")
                return

            editor = self.query_one("#editor", TextArea)
            self._validate_content(editor.text, self.current_file)
            self._update_status("Validated")

        def action_reload(self) -> None:
            """Reload current file from disk."""
            if not self.current_file:
                self.notify("No file to reload", severity="warning")
                return

            if self.is_modified:
                # Could add confirmation dialog here
                pass

            self.load_file(self.current_file)
            self.notify(f"Reloaded: {self.current_file.name}")

        def action_help(self) -> None:
            """Show help."""
            help_text = (
                "Keyboard Shortcuts:\n"
                "  Ctrl+S / F2  - Save file\n"
                "  F3           - Validate content\n"
                "  F5           - Reload from disk\n"
                "  Ctrl+O       - Focus file tree\n"
                "  Ctrl+E       - Focus editor\n"
                "  Ctrl+Q       - Quit\n"
                "  Escape       - Unfocus current pane"
            )
            self.notify(help_text, title="Help", timeout=10)

        def action_focus_tree(self) -> None:
            """Focus the file tree."""
            self.query_one("#file-tree").focus()

        def action_focus_editor(self) -> None:
            """Focus the editor."""
            self.query_one("#editor").focus()

        def action_unfocus(self) -> None:
            """Remove focus from current widget."""
            self.screen.focus_next()

        async def action_quit(self) -> None:
            """Quit the application."""
            if self.is_modified:
                self.notify(
                    "Unsaved changes! Press Ctrl+S to save or Ctrl+Q again to quit.",
                    severity="warning",
                )
                # Second quit will exit
                self.is_modified = False
            else:
                self.exit()


def run_tui(
    path: Path | None = None,
    file: Path | None = None,
) -> None:
    """Launch the TUI editor.

    Args:
        path: Directory to open file tree at.
        file: Specific file to open initially.
    """
    if not TEXTUAL_AVAILABLE:
        from shelfr.tui import TUINotAvailableError

        raise TUINotAvailableError()

    # Determine start path and initial file
    start_path = path or Path.cwd()
    initial_file = file

    # If path is a file, use its parent as start_path
    if start_path.is_file():
        initial_file = start_path
        start_path = start_path.parent

    # Default to config/ if it exists and no path specified
    if path is None:
        config_dir = Path.cwd() / "config"
        if config_dir.is_dir():
            start_path = config_dir

    app = ShelfrEditor(start_path=start_path, initial_file=initial_file)
    app.run()


# Allow running directly: python -m shelfr.tui.app
if __name__ == "__main__":
    run_tui()
