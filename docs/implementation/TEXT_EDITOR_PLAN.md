# Text Editor Integration Plan

> **Branch:** `feature/mkbrr-wrapper`
> **Status:** ✅ Complete (All 3 Tiers)
> **Created:** 2024-12-30

## Overview

Add text editing capabilities to shelfr for editing YAML configs, templates, and BBCode content. Three-tiered approach from simple `$EDITOR` integration to full Textual TUI.

### Implementation Status

| Tier | Feature | Status | Files |
|------|---------|--------|-------|
| 1 | $EDITOR integration | ✅ Complete | `utils/editor.py` |
| 2 | prompt_toolkit mini-editor | ✅ Complete | `utils/mini_editor.py`, `utils/preview.py` |
| 3 | Textual TUI | ✅ Complete | `tui/app.py` |

### Tests

- **Tier 1:** 32 tests (`tests/test_editor.py`)
- **Tier 2:** 31 tests (`tests/test_mini_editor.py`)
- **Tier 3:** 20 tests (`tests/test_tui.py`)
- **Total:** 83 tests passing

---

## Use Cases

| File Type | Examples | Edit Frequency | Complexity |
|-----------|----------|----------------|------------|
| mkbrr YAML | `presets.yaml`, `batch.yaml` | Medium | Low-Medium |
| shelfr config | `config.yaml` | Low | Medium |
| BBCode templates | `signature.j2`, descriptions | High | Medium |
| Torrent descriptions | Per-upload text | High | Low |

---

## Tier 1: `$EDITOR` Integration (✅ Complete)

### Description

Launch user's preferred editor (`$EDITOR`, `$VISUAL`, or fallback) for file editing. Zero UI complexity, maximum compatibility.

### Implementation

```python
# src/shelfr/utils/editor.py
"""External editor integration."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Editor fallback chain
EDITOR_FALLBACKS = ["nano", "vim", "vi", "notepad"]


def get_editor() -> str | None:
    """
    Get the user's preferred editor.

    Priority:
        1. $VISUAL (GUI-friendly)
        2. $EDITOR (traditional)
        3. First available fallback

    Returns:
        Editor command string or None if none found.
    """
    # Check environment variables
    for env_var in ("VISUAL", "EDITOR"):
        if editor := os.environ.get(env_var):
            return editor

    # Try fallbacks
    for fallback in EDITOR_FALLBACKS:
        if shutil.which(fallback):
            return fallback

    return None


def edit_file(
    file_path: Path | str,
    *,
    wait: bool = True,
    editor: str | None = None,
) -> bool:
    """
    Open a file in the user's editor.

    Args:
        file_path: Path to file to edit.
        wait: Wait for editor to close before returning.
        editor: Override editor command.

    Returns:
        True if editor exited successfully.

    Raises:
        FileNotFoundError: If file doesn't exist.
        RuntimeError: If no editor available.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    editor_cmd = editor or get_editor()
    if not editor_cmd:
        raise RuntimeError(
            "No editor found. Set $EDITOR or $VISUAL environment variable."
        )

    logger.debug("Opening %s with %s", file_path, editor_cmd)

    try:
        result = subprocess.run(
            [editor_cmd, str(file_path)],
            check=False,
        )
        return result.returncode == 0
    except Exception as e:
        logger.exception("Editor failed: %s", e)
        return False


def edit_temp(
    content: str = "",
    *,
    suffix: str = ".txt",
    prefix: str = "shelfr_",
    editor: str | None = None,
) -> str | None:
    """
    Edit content in a temporary file.

    Creates a temp file with initial content, opens editor,
    returns modified content after editor closes.

    Args:
        content: Initial content for the file.
        suffix: File extension (e.g., ".yaml", ".md").
        prefix: Temp file prefix.
        editor: Override editor command.

    Returns:
        Modified content string, or None if cancelled/failed.
    """
    editor_cmd = editor or get_editor()
    if not editor_cmd:
        raise RuntimeError(
            "No editor found. Set $EDITOR or $VISUAL environment variable."
        )

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=suffix,
        prefix=prefix,
        delete=False,
    ) as f:
        f.write(content)
        temp_path = Path(f.name)

    try:
        original_mtime = temp_path.stat().st_mtime
        result = subprocess.run([editor_cmd, str(temp_path)], check=False)

        if result.returncode != 0:
            logger.warning("Editor exited with code %d", result.returncode)
            return None

        # Check if file was modified
        if temp_path.stat().st_mtime == original_mtime:
            logger.debug("File unchanged, treating as cancel")
            return None

        return temp_path.read_text()

    finally:
        temp_path.unlink(missing_ok=True)


def edit_yaml(
    file_path: Path | str,
    *,
    validate: bool = True,
    editor: str | None = None,
) -> bool:
    """
    Edit a YAML file with validation.

    Opens file in editor, validates YAML syntax after save.
    Re-opens if validation fails (with user confirmation).

    Args:
        file_path: Path to YAML file.
        validate: Whether to validate YAML after editing.
        editor: Override editor command.

    Returns:
        True if file was saved and valid.
    """
    import yaml  # Late import

    file_path = Path(file_path)

    while True:
        if not edit_file(file_path, editor=editor):
            return False

        if not validate:
            return True

        # Validate YAML
        try:
            content = file_path.read_text()
            yaml.safe_load(content)
            return True
        except yaml.YAMLError as e:
            logger.error("Invalid YAML: %s", e)
            # Could prompt to re-edit here
            return False
```

### CLI Commands

```python
# In src/shelfr/cli/tools.py or new src/shelfr/cli/edit.py

@app.command()
def edit(
    file: Annotated[Path, typer.Argument(help="File to edit")],
    editor: Annotated[str | None, typer.Option("--editor", "-e")] = None,
) -> None:
    """Open a file in your default editor."""
    from shelfr.utils.editor import edit_file

    if not file.exists():
        print_error(f"File not found: {file}")
        raise typer.Exit(1)

    if not edit_file(file, editor=editor):
        print_error("Editor exited with error")
        raise typer.Exit(1)


# Convenience commands
@app.command("edit-config")
def edit_config() -> None:
    """Edit shelfr config.yaml."""
    from shelfr.config import get_config_path
    from shelfr.utils.editor import edit_yaml

    config_path = get_config_path()
    if edit_yaml(config_path):
        print_success(f"Saved: {config_path}")
    else:
        print_error("Edit cancelled or validation failed")


@app.command("edit-presets")
def edit_presets() -> None:
    """Edit mkbrr presets.yaml."""
    from shelfr.config import config
    from shelfr.utils.editor import edit_yaml

    presets_path = Path(config.mkbrr.host_config_dir) / "presets.yaml"
    if edit_yaml(presets_path):
        print_success(f"Saved: {presets_path}")
```

### Pros/Cons

| Pros | Cons |
|------|------|
| ✅ Zero dependencies | ❌ Leaves terminal (jarring UX) |
| ✅ User's familiar editor | ❌ No in-app preview |
| ✅ Full editor features | ❌ Can't guide user |
| ✅ Works everywhere | ❌ No validation during edit |

---

## Tier 2: prompt_toolkit Mini-Editor

### Description

Embedded multiline editor using `prompt_toolkit`. Stays in terminal, supports syntax highlighting, pairs with Rich for preview.

### Dependencies

```toml
# pyproject.toml
[project.optional-dependencies]
tui = [
    "prompt_toolkit>=3.0.0",
    "pygments>=2.0.0",  # For syntax highlighting
]
```

### Implementation

```python
# src/shelfr/utils/mini_editor.py
"""Embedded mini-editor using prompt_toolkit."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.lexers import PygmentsLexer
from prompt_toolkit.styles import Style
from pygments.lexers import YamlLexer, MarkdownLexer

if TYPE_CHECKING:
    from pygments.lexer import Lexer

logger = logging.getLogger(__name__)

# Keybinding help
HELP_TEXT = """
[Ctrl+D] Save and exit
[Ctrl+C] Cancel
[Ctrl+S] Save (continue editing)
[Esc, Enter] New line (or just Enter in multiline mode)
"""

# Editor style (cyberpunk vibes 🎨)
EDITOR_STYLE = Style.from_dict({
    "": "#ffffff",
    "prompt": "#00ff00 bold",
    "bottom-toolbar": "#333333 bg:#00ff00",
})


def get_lexer_for_suffix(suffix: str) -> type[Lexer] | None:
    """Get Pygments lexer for file extension."""
    LEXER_MAP = {
        ".yaml": YamlLexer,
        ".yml": YamlLexer,
        ".md": MarkdownLexer,
        ".j2": None,  # Jinja2 - could use Jinja2Lexer
    }
    return LEXER_MAP.get(suffix.lower())


def mini_edit(
    initial_content: str = "",
    *,
    suffix: str = ".txt",
    prompt_text: str = "Edit",
    show_help: bool = True,
) -> str | None:
    """
    Open an embedded mini-editor.

    Args:
        initial_content: Starting content.
        suffix: File type for syntax highlighting.
        prompt_text: Label shown above editor.
        show_help: Show keybinding help.

    Returns:
        Edited content, or None if cancelled.
    """
    from rich.console import Console
    from rich.panel import Panel

    console = Console()

    if show_help:
        console.print(Panel(HELP_TEXT.strip(), title="Editor Help", border_style="dim"))

    # Set up lexer for syntax highlighting
    lexer_class = get_lexer_for_suffix(suffix)
    lexer = PygmentsLexer(lexer_class) if lexer_class else None

    # Create keybindings
    bindings = KeyBindings()

    @bindings.add("c-d")
    def save_exit(event):
        """Save and exit."""
        event.app.exit(result=event.app.current_buffer.text)

    @bindings.add("c-c")
    def cancel(event):
        """Cancel editing."""
        event.app.exit(result=None)

    # Create session
    session: PromptSession[str] = PromptSession(
        message=f"{prompt_text}:\n",
        multiline=True,
        lexer=lexer,
        style=EDITOR_STYLE,
        key_bindings=bindings,
        bottom_toolbar="[Ctrl+D] Save  [Ctrl+C] Cancel",
    )

    try:
        result = session.prompt(default=initial_content)
        return result
    except (EOFError, KeyboardInterrupt):
        return None


def edit_yaml_inline(
    content: str,
    *,
    title: str = "YAML Editor",
    validate: bool = True,
) -> str | None:
    """
    Edit YAML content with validation and preview.

    Args:
        content: Initial YAML content.
        title: Editor title.
        validate: Validate YAML before accepting.

    Returns:
        Valid YAML content, or None if cancelled.
    """
    import yaml
    from rich.console import Console
    from rich.syntax import Syntax

    console = Console()

    while True:
        result = mini_edit(content, suffix=".yaml", prompt_text=title)

        if result is None:
            console.print("[yellow]Cancelled[/]")
            return None

        if not validate:
            return result

        # Validate
        try:
            yaml.safe_load(result)
            console.print("[green]✓ Valid YAML[/]")
            return result
        except yaml.YAMLError as e:
            console.print(f"[red]Invalid YAML:[/] {e}")
            console.print()
            # Show the problematic content
            console.print(Syntax(result, "yaml", line_numbers=True))
            console.print()

            if not console.input("[yellow]Re-edit? [Y/n]:[/] ").lower().startswith("n"):
                content = result  # Keep their changes
                continue
            return None
```

### Rich Preview Integration

```python
# src/shelfr/utils/preview.py
"""Rich preview utilities for edited content."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table


def preview_yaml(content: str, title: str = "Preview") -> None:
    """Display YAML content with syntax highlighting."""
    console = Console()
    syntax = Syntax(content, "yaml", theme="monokai", line_numbers=True)
    console.print(Panel(syntax, title=title, border_style="blue"))


def preview_bbcode(bbcode: str, title: str = "BBCode Preview") -> None:
    """Display BBCode with basic formatting preview."""
    console = Console()
    # Could parse BBCode and render with Rich markup
    console.print(Panel(bbcode, title=title, border_style="green"))


def preview_diff(before: str, after: str, title: str = "Changes") -> None:
    """Show diff between two versions."""
    import difflib

    console = Console()
    diff = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile="before",
        tofile="after",
    )
    diff_text = "".join(diff)

    if not diff_text:
        console.print("[dim]No changes[/]")
        return

    syntax = Syntax(diff_text, "diff", theme="monokai")
    console.print(Panel(syntax, title=title, border_style="yellow"))
```

### Pros/Cons

| Pros | Cons |
|------|------|
| ✅ Stays in terminal | ❌ Learning curve (keybindings) |
| ✅ Syntax highlighting | ❌ Limited vs real editor |
| ✅ Inline validation | ❌ Extra dependency |
| ✅ Rich preview integration | ❌ No mouse support |
| ✅ Scriptable / automatable | |

---

## Tier 3: Full Textual TUI

### Description

Complete terminal UI application with multiple panes, widgets, and a proper editor component. The "endgame" for shelfr's terminal experience.

### Dependencies

```toml
# pyproject.toml
[project.optional-dependencies]
tui = [
    "textual>=0.47.0",
    "textual-dev>=1.0.0",  # For development/debugging
]
```

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  shelfr TUI                                            [?] Help │
├─────────────────────────────────────────────────────────────────┤
│ ┌─────────────────────────┐ ┌─────────────────────────────────┐ │
│ │ Files                   │ │ Editor                          │ │
│ │ ┌─────────────────────┐ │ │ ┌─────────────────────────────┐ │ │
│ │ │ 📁 config/          │ │ │ │ version: 1                  │ │ │
│ │ │   📄 config.yaml    │ │ │ │ presets:                    │ │ │
│ │ │   📄 presets.yaml ← │ │ │ │   mam:                      │ │ │
│ │ │   📄 batch.yaml     │ │ │ │     trackers:               │ │ │
│ │ │ 📁 templates/       │ │ │ │       - https://...         │ │ │
│ │ │   📄 signature.j2   │ │ │ │     private: true           │ │ │
│ │ └─────────────────────┘ │ │ │     source: "MAM"           │ │ │
│ └─────────────────────────┘ │ └─────────────────────────────┘ │ │
│                             └─────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ Preview / Output                                            │ │
│ │ ┌─────────────────────────────────────────────────────────┐ │ │
│ │ │ ✓ Valid YAML                                            │ │ │
│ │ │ Presets: mam, public, cross-seed                        │ │ │
│ │ │ Tracker: tracker.example.com                            │ │ │
│ │ └─────────────────────────────────────────────────────────┘ │ │
│ └─────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────┤
│ [F1] Help  [F2] Save  [F3] Preview  [Ctrl+Q] Quit              │
└─────────────────────────────────────────────────────────────────┘
```

### Implementation Sketch

```python
# src/shelfr/tui/app.py
"""Textual TUI application for shelfr."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import (
    DirectoryTree,
    Footer,
    Header,
    Static,
    TextArea,
)


class ShelfrEditor(App):
    """Full-featured shelfr TUI editor."""

    CSS = """
    Screen {
        layout: grid;
        grid-size: 2 2;
        grid-columns: 1fr 2fr;
        grid-rows: 3fr 1fr;
    }

    #file-tree {
        column-span: 1;
        row-span: 1;
        border: solid green;
    }

    #editor {
        column-span: 1;
        row-span: 1;
        border: solid blue;
    }

    #preview {
        column-span: 2;
        row-span: 1;
        border: solid yellow;
    }

    TextArea {
        height: 100%;
    }
    """

    BINDINGS = [
        Binding("f1", "help", "Help"),
        Binding("f2", "save", "Save"),
        Binding("f3", "preview", "Preview"),
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+o", "open", "Open"),
    ]

    def __init__(self, start_path: Path | None = None):
        super().__init__()
        self.start_path = start_path or Path.cwd()
        self.current_file: Path | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            DirectoryTree(str(self.start_path), id="file-tree"),
            TextArea(id="editor", language="yaml"),
            Static("Preview will appear here", id="preview"),
        )
        yield Footer()

    def on_directory_tree_file_selected(
        self, event: DirectoryTree.FileSelected
    ) -> None:
        """Handle file selection from tree."""
        path = Path(event.path)
        if path.suffix in (".yaml", ".yml", ".j2", ".md", ".txt"):
            self.load_file(path)

    def load_file(self, path: Path) -> None:
        """Load a file into the editor."""
        self.current_file = path
        content = path.read_text()
        editor = self.query_one("#editor", TextArea)
        editor.text = content

        # Set language based on extension
        lang_map = {".yaml": "yaml", ".yml": "yaml", ".md": "markdown", ".j2": "jinja2"}
        editor.language = lang_map.get(path.suffix, "text")

        self.title = f"shelfr - {path.name}"

    def action_save(self) -> None:
        """Save current file."""
        if self.current_file:
            editor = self.query_one("#editor", TextArea)
            self.current_file.write_text(editor.text)
            self.notify(f"Saved: {self.current_file.name}")

    def action_preview(self) -> None:
        """Update preview pane."""
        editor = self.query_one("#editor", TextArea)
        preview = self.query_one("#preview", Static)

        # Validate and preview
        if self.current_file and self.current_file.suffix in (".yaml", ".yml"):
            import yaml

            try:
                data = yaml.safe_load(editor.text)
                preview.update(f"✓ Valid YAML\n\nKeys: {list(data.keys()) if data else 'empty'}")
            except yaml.YAMLError as e:
                preview.update(f"✗ Invalid YAML\n\n{e}")
        else:
            preview.update(editor.text[:500] + "..." if len(editor.text) > 500 else editor.text)

    def action_help(self) -> None:
        """Show help."""
        self.notify("F2=Save, F3=Preview, Ctrl+Q=Quit")


def run_editor(path: Path | None = None) -> None:
    """Launch the TUI editor."""
    app = ShelfrEditor(start_path=path)
    app.run()


# Entry point
if __name__ == "__main__":
    run_editor()
```

### CLI Integration

```python
# In src/shelfr/cli/main.py or cli/tui.py

@app.command()
def tui(
    path: Annotated[Path | None, typer.Argument()] = None,
) -> None:
    """Launch full-screen TUI editor."""
    try:
        from shelfr.tui.app import run_editor
    except ImportError:
        print_error("TUI not installed. Run: pip install shelfr[tui]")
        raise typer.Exit(1)

    run_editor(path)
```

### Pros/Cons

| Pros | Cons |
|------|------|
| ✅ Full terminal app experience | ❌ Significant complexity |
| ✅ Multiple panes / widgets | ❌ Learning curve (Textual) |
| ✅ Real-time preview | ❌ Heavier dependency |
| ✅ Mouse support | ❌ More maintenance |
| ✅ Keyboard shortcuts | ❌ Overkill for simple edits |
| ✅ Theming / CSS styling | |
| ✅ Future-proof for dashboard | |

---

## Recommended Approach

### Phase 1: Tier 1 + Tier 2 (Immediate)

1. **Implement `$EDITOR` integration** (`utils/editor.py`)
   - `edit_file()`, `edit_temp()`, `edit_yaml()`
   - CLI commands: `shelfr edit`, `shelfr edit-config`, `shelfr edit-presets`

2. **Add prompt_toolkit mini-editor** (optional dependency)
   - `mini_edit()` for inline editing
   - Use for: template editing, BBCode, quick YAML tweaks
   - Rich preview integration

### Phase 2: Tier 3 (Future)

3. **Full Textual TUI** (when shelfr grows)
   - Dashboard mode with torrent info, logs, preview
   - File browser + editor
   - Real-time validation

---

## File Structure

```
src/shelfr/
├── utils/
│   ├── editor.py          # Tier 1: $EDITOR integration
│   ├── mini_editor.py     # Tier 2: prompt_toolkit (optional)
│   └── preview.py         # Rich preview utilities
├── tui/                   # Tier 3: Textual (optional)
│   ├── __init__.py
│   ├── app.py             # Main TUI app
│   ├── widgets/           # Custom widgets
│   │   ├── editor.py
│   │   ├── file_tree.py
│   │   └── preview.py
│   └── styles.css         # Textual CSS
└── cli/
    ├── edit.py            # Edit commands
    └── main.py            # Register 'tui' command
```

---

## Configuration

```yaml
# config.yaml
editor:
  # Preferred editor (overrides $EDITOR)
  command: null  # e.g., "code --wait", "nano", "vim"

  # Use inline editor when available (prompt_toolkit)
  prefer_inline: false

  # Validate YAML after editing
  validate_yaml: true

  # TUI settings
  tui:
    theme: "cyberpunk"  # monokai, dracula, cyberpunk
    show_line_numbers: true
    auto_save: false
```

---

## Implementation Order

| Step | Task | Tier | Est. Effort |
|------|------|------|-------------|
| 1 | Create `utils/editor.py` | 1 | Small |
| 2 | Add CLI edit commands | 1 | Small |
| 3 | Add `mini_editor.py` (optional dep) | 2 | Medium |
| 4 | Rich preview utilities | 2 | Small |
| 5 | Create `tui/` package skeleton | 3 | Medium |
| 6 | Implement basic TUI app | 3 | Large |
| 7 | Add custom widgets | 3 | Large |
| 8 | Theming / polish | 3 | Medium |

---

## References

- [Textual Documentation](https://textual.textualize.io/)
- [prompt_toolkit Documentation](https://python-prompt-toolkit.readthedocs.io/)
- [Rich Documentation](https://rich.readthedocs.io/)
- [Pygments Lexers](https://pygments.org/docs/lexers/)

---

## Changelog

| Date | Change |
|------|--------|
| 2024-12-30 | Initial planning document |
