"""Embedded mini-editor using prompt_toolkit.

Provides an inline multiline editor that stays in the terminal,
with syntax highlighting and Rich preview integration.

Requires optional dependency: pip install shelfr[tui]

Example:
    >>> from shelfr.utils.mini_editor import mini_edit, edit_yaml_inline
    >>> content = mini_edit("initial text", suffix=".yaml")
    >>> if content:
    ...     print("User saved:", content)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Check if prompt_toolkit is available
try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.styles import Style

    PROMPT_TOOLKIT_AVAILABLE = True
except ImportError:
    PROMPT_TOOLKIT_AVAILABLE = False
    PromptSession: Any = None
    KeyBindings: Any = None
    Style: Any = None

# Check if pygments is available for syntax highlighting
try:
    from prompt_toolkit.lexers import PygmentsLexer
    from pygments.lexers import (
        JsonLexer,
        MarkdownLexer,
        YamlLexer,
    )

    PYGMENTS_AVAILABLE = True
except ImportError:
    PYGMENTS_AVAILABLE = False
    PygmentsLexer: Any = None
    YamlLexer: Any = None
    JsonLexer: Any = None
    MarkdownLexer: Any = None


class MiniEditorError(Exception):
    """Raised when mini-editor operations fail."""

    pass


class MiniEditorNotAvailableError(MiniEditorError):
    """Raised when prompt_toolkit is not installed."""

    def __init__(self) -> None:
        super().__init__(
            "Mini-editor requires prompt_toolkit. Install with: pip install shelfr[tui]"
        )


def check_available() -> bool:
    """Check if mini-editor dependencies are available."""
    return PROMPT_TOOLKIT_AVAILABLE


def _get_lexer_for_suffix(suffix: str) -> Any | None:
    """Get Pygments lexer for file extension.

    Args:
        suffix: File extension (e.g., ".yaml", ".json").

    Returns:
        PygmentsLexer instance or None if not available.
    """
    if not PYGMENTS_AVAILABLE or PygmentsLexer is None:
        return None

    lexer_map = {
        ".yaml": YamlLexer,
        ".yml": YamlLexer,
        ".json": JsonLexer,
        ".md": MarkdownLexer,
        ".markdown": MarkdownLexer,
    }

    lexer_class = lexer_map.get(suffix.lower())
    if lexer_class:
        return PygmentsLexer(lexer_class)
    return None


# Keybinding help text
HELP_TEXT = """
╭─ Mini-Editor Keybindings ─╮
│ [Ctrl+D]  Save and exit   │
│ [Ctrl+C]  Cancel          │
│ [Enter]   New line        │
│ [Tab]     Insert spaces   │
╰───────────────────────────╯
"""

# Editor style (cyberpunk theme )
EDITOR_STYLE_DICT = {
    "": "#ffffff",
    "prompt": "#00ff00 bold",
    "bottom-toolbar": "#000000 bg:#00ff00",
    "bottom-toolbar.text": "#000000",
}


def mini_edit(
    initial_content: str = "",
    *,
    suffix: str = ".txt",
    prompt_text: str = "Edit",
    show_help: bool = True,
    bottom_toolbar: str | None = None,
) -> str | None:
    """
    Open an embedded mini-editor.

    Uses prompt_toolkit for multiline editing with optional syntax
    highlighting based on file extension.

    Args:
        initial_content: Starting content for the editor.
        suffix: File type for syntax highlighting (e.g., ".yaml", ".json").
        prompt_text: Label shown above the editor area.
        show_help: Whether to show keybinding help before editing.
        bottom_toolbar: Custom toolbar text (default: keybinding hints).

    Returns:
        Edited content string, or None if cancelled (Ctrl+C).

    Raises:
        MiniEditorNotAvailableError: If prompt_toolkit is not installed.

    Example:
        >>> content = mini_edit("key: value", suffix=".yaml")
        >>> if content is not None:
        ...     print("Saved:", content)
        ... else:
        ...     print("Cancelled")
    """
    if not PROMPT_TOOLKIT_AVAILABLE:
        raise MiniEditorNotAvailableError()

    from rich.console import Console
    from rich.panel import Panel

    console = Console()

    # Show help if requested
    if show_help:
        console.print(Panel(HELP_TEXT.strip(), border_style="dim"))

    # Set up syntax highlighting
    lexer = _get_lexer_for_suffix(suffix)

    # Create style
    style = Style.from_dict(EDITOR_STYLE_DICT)

    # Create keybindings
    bindings = KeyBindings()

    @bindings.add("c-d")
    def save_exit(event: Any) -> None:
        """Save and exit."""
        event.app.exit(result=event.app.current_buffer.text)

    @bindings.add("c-c")
    def cancel(event: Any) -> None:
        """Cancel editing."""
        event.app.exit(result=None)

    # Default toolbar
    if bottom_toolbar is None:
        bottom_toolbar = " [Ctrl+D] Save  [Ctrl+C] Cancel "

    # Create session
    session: PromptSession[str] = PromptSession(
        message=f"{prompt_text}:\n",
        multiline=True,
        lexer=lexer,
        style=style,
        key_bindings=bindings,
        bottom_toolbar=bottom_toolbar,
        enable_history_search=False,
    )

    try:
        result: str | None = session.prompt(default=initial_content)
        return result
    except (EOFError, KeyboardInterrupt):
        return None


def edit_yaml_inline(
    content: str = "",
    *,
    title: str = "YAML Editor",
    validate: bool = True,
    show_help: bool = True,
) -> str | None:
    """
    Edit YAML content with inline validation and preview.

    Opens mini-editor, validates YAML after save, shows error and
    offers re-edit if invalid.

    Args:
        content: Initial YAML content.
        title: Editor title/prompt.
        validate: Whether to validate YAML before accepting.
        show_help: Whether to show keybinding help.

    Returns:
        Valid YAML content string, or None if cancelled.

    Example:
        >>> yaml_content = "key: value\\nlist:\\n  - item1"
        >>> result = edit_yaml_inline(yaml_content)
        >>> if result:
        ...     Path("output.yaml").write_text(result)
    """
    if not PROMPT_TOOLKIT_AVAILABLE:
        raise MiniEditorNotAvailableError()

    import yaml
    from rich.console import Console
    from rich.syntax import Syntax

    console = Console()
    current_content = content

    while True:
        result = mini_edit(
            current_content,
            suffix=".yaml",
            prompt_text=title,
            show_help=show_help,
        )

        if result is None:
            console.print("[yellow]Cancelled[/]")
            return None

        if not validate:
            return result

        # Validate YAML
        try:
            parsed = yaml.safe_load(result)
            console.print("[green]✓ Valid YAML[/]")

            # Show a brief preview of the structure
            if isinstance(parsed, dict):
                keys = list(parsed.keys())[:5]
                console.print(f"[dim]Keys: {keys}{'...' if len(parsed) > 5 else ''}[/]")

            return result

        except yaml.YAMLError as e:
            console.print(f"[red]✗ Invalid YAML:[/] {e}")
            console.print()

            # Show the problematic content with line numbers
            console.print(Syntax(result, "yaml", line_numbers=True, theme="monokai"))
            console.print()

            # Ask if user wants to re-edit
            try:
                response = console.input("[yellow]Re-edit? [Y/n]:[/] ")
                if response.lower().startswith("n"):
                    return None
                current_content = result  # Keep their changes for re-editing
                show_help = False  # Don't show help again
            except (EOFError, KeyboardInterrupt):
                return None


def edit_json_inline(
    content: str = "",
    *,
    title: str = "JSON Editor",
    validate: bool = True,
    show_help: bool = True,
    pretty: bool = True,
) -> str | None:
    """
    Edit JSON content with inline validation.

    Opens mini-editor, validates JSON after save, optionally
    pretty-prints the result.

    Args:
        content: Initial JSON content.
        title: Editor title/prompt.
        validate: Whether to validate JSON before accepting.
        show_help: Whether to show keybinding help.
        pretty: Whether to pretty-print valid JSON result.

    Returns:
        Valid JSON content string, or None if cancelled.

    Example:
        >>> json_content = '{"key": "value"}'
        >>> result = edit_json_inline(json_content, pretty=True)
    """
    if not PROMPT_TOOLKIT_AVAILABLE:
        raise MiniEditorNotAvailableError()

    import json

    from rich.console import Console
    from rich.syntax import Syntax

    console = Console()
    current_content = content

    while True:
        result = mini_edit(
            current_content,
            suffix=".json",
            prompt_text=title,
            show_help=show_help,
        )

        if result is None:
            console.print("[yellow]Cancelled[/]")
            return None

        if not validate:
            return result

        # Validate JSON
        try:
            parsed = json.loads(result)
            console.print("[green]✓ Valid JSON[/]")

            # Optionally pretty-print
            if pretty:
                result = json.dumps(parsed, indent=2, ensure_ascii=False)

            return result

        except json.JSONDecodeError as e:
            console.print(f"[red]✗ Invalid JSON:[/] {e}")
            console.print()

            # Show the problematic content
            console.print(Syntax(result, "json", line_numbers=True, theme="monokai"))
            console.print()

            # Ask if user wants to re-edit
            try:
                response = console.input("[yellow]Re-edit? [Y/n]:[/] ")
                if response.lower().startswith("n"):
                    return None
                current_content = result
                show_help = False
            except (EOFError, KeyboardInterrupt):
                return None


def edit_text_inline(
    content: str = "",
    *,
    title: str = "Text Editor",
    suffix: str = ".txt",
    show_help: bool = True,
) -> str | None:
    """
    Edit plain text or markdown content.

    Simple wrapper around mini_edit for general text editing.

    Args:
        content: Initial text content.
        title: Editor title/prompt.
        suffix: File suffix for syntax highlighting (e.g., ".md").
        show_help: Whether to show keybinding help.

    Returns:
        Edited content string, or None if cancelled.

    Example:
        >>> markdown = "# Title\\n\\nSome content"
        >>> result = edit_text_inline(markdown, suffix=".md")
    """
    if not PROMPT_TOOLKIT_AVAILABLE:
        raise MiniEditorNotAvailableError()

    return mini_edit(
        content,
        suffix=suffix,
        prompt_text=title,
        show_help=show_help,
    )


def edit_file_inline(
    file_path: Path | str,
    *,
    validate: bool = True,
    backup: bool = True,
    show_help: bool = True,
) -> bool:
    """
    Edit a file using the inline mini-editor.

    Opens the file content in mini-editor, validates if YAML/JSON,
    saves back to the file on success.

    Args:
        file_path: Path to file to edit.
        validate: Whether to validate YAML/JSON files.
        backup: Whether to create a .bak backup before saving.
        show_help: Whether to show keybinding help.

    Returns:
        True if file was modified and saved, False otherwise.

    Raises:
        FileNotFoundError: If file doesn't exist.
        MiniEditorNotAvailableError: If prompt_toolkit not installed.

    Example:
        >>> if edit_file_inline("config.yaml"):
        ...     print("Config updated!")
    """
    if not PROMPT_TOOLKIT_AVAILABLE:
        raise MiniEditorNotAvailableError()

    import shutil

    from rich.console import Console

    console = Console()
    file_path = Path(file_path).resolve()

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Read current content
    original_content = file_path.read_text(encoding="utf-8")
    suffix = file_path.suffix.lower()

    # Edit based on file type
    if suffix in (".yaml", ".yml"):
        result = edit_yaml_inline(
            original_content,
            title=f"Editing {file_path.name}",
            validate=validate,
            show_help=show_help,
        )
    elif suffix == ".json":
        result = edit_json_inline(
            original_content,
            title=f"Editing {file_path.name}",
            validate=validate,
            show_help=show_help,
        )
    else:
        result = edit_text_inline(
            original_content,
            title=f"Editing {file_path.name}",
            suffix=suffix,
            show_help=show_help,
        )

    if result is None:
        return False

    # Check if content actually changed
    if result == original_content:
        console.print("[dim]No changes made[/]")
        return False

    # Create backup if requested
    if backup:
        backup_path = file_path.with_suffix(file_path.suffix + ".bak")
        try:
            shutil.copy2(file_path, backup_path)
            logger.debug("Created backup: %s", backup_path)
        except OSError as e:
            logger.warning("Failed to create backup: %s", e)

    # Save the file
    file_path.write_text(result, encoding="utf-8")
    console.print(f"[green]✓ Saved:[/] {file_path}")

    return True
