"""Rich preview utilities for edited content.

Display content with syntax highlighting, diffs, and formatted previews
using Rich console output.

Example:
    >>> from shelfr.utils.preview import preview_yaml, preview_diff
    >>> preview_yaml("key: value\\nlist:\\n  - item")
    >>> preview_diff("old content", "new content")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from typing import Any

logger = logging.getLogger(__name__)


def preview_yaml(
    content: str,
    *,
    title: str = "YAML Preview",
    line_numbers: bool = True,
    theme: str = "monokai",
    console: Console | None = None,
) -> None:
    """
    Display YAML content with syntax highlighting.

    Args:
        content: YAML content to display.
        title: Panel title.
        line_numbers: Whether to show line numbers.
        theme: Pygments theme name.
        console: Rich Console instance (default: new console).

    Example:
        >>> preview_yaml("key: value\\nlist:\\n  - item1\\n  - item2")
    """
    if console is None:
        console = Console()

    syntax = Syntax(
        content,
        "yaml",
        theme=theme,
        line_numbers=line_numbers,
        word_wrap=True,
    )
    console.print(Panel(syntax, title=title, border_style="blue"))


def preview_json(
    content: str,
    *,
    title: str = "JSON Preview",
    line_numbers: bool = True,
    theme: str = "monokai",
    console: Console | None = None,
) -> None:
    """
    Display JSON content with syntax highlighting.

    Args:
        content: JSON content to display.
        title: Panel title.
        line_numbers: Whether to show line numbers.
        theme: Pygments theme name.
        console: Rich Console instance.

    Example:
        >>> preview_json('{"key": "value", "list": [1, 2, 3]}')
    """
    if console is None:
        console = Console()

    syntax = Syntax(
        content,
        "json",
        theme=theme,
        line_numbers=line_numbers,
        word_wrap=True,
    )
    console.print(Panel(syntax, title=title, border_style="green"))


def preview_markdown(
    content: str,
    *,
    title: str = "Markdown Preview",
    console: Console | None = None,
) -> None:
    """
    Display Markdown content with Rich rendering.

    Args:
        content: Markdown content to display.
        title: Panel title.
        console: Rich Console instance.

    Example:
        >>> preview_markdown("# Title\\n\\nSome **bold** text")
    """
    if console is None:
        console = Console()

    from rich.markdown import Markdown

    md = Markdown(content)
    console.print(Panel(md, title=title, border_style="cyan"))


def preview_diff(
    before: str,
    after: str,
    *,
    title: str = "Changes",
    context_lines: int = 3,
    console: Console | None = None,
) -> bool:
    """
    Show unified diff between two versions.

    Args:
        before: Original content.
        after: Modified content.
        title: Panel title.
        context_lines: Number of context lines around changes.
        console: Rich Console instance.

    Returns:
        True if there were differences, False if identical.

    Example:
        >>> preview_diff("line1\\nline2", "line1\\nline2 modified")
    """
    import difflib

    if console is None:
        console = Console()

    # Generate unified diff
    diff_lines = list(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile="before",
            tofile="after",
            n=context_lines,
        )
    )

    if not diff_lines:
        console.print("[dim]No changes[/]")
        return False

    diff_text = "".join(diff_lines)
    syntax = Syntax(diff_text, "diff", theme="monokai", word_wrap=True)
    console.print(Panel(syntax, title=title, border_style="yellow"))
    return True


def preview_side_by_side(
    before: str,
    after: str,
    *,
    title_before: str = "Before",
    title_after: str = "After",
    syntax: str | None = None,
    console: Console | None = None,
) -> None:
    """
    Show before/after content side by side.

    Args:
        before: Original content.
        after: Modified content.
        title_before: Title for before panel.
        title_after: Title for after panel.
        syntax: Syntax highlighting language (e.g., "yaml").
        console: Rich Console instance.

    Example:
        >>> preview_side_by_side("old", "new", syntax="yaml")
    """
    if console is None:
        console = Console()

    from rich.columns import Columns

    # Create syntax-highlighted content if syntax specified
    if syntax:
        before_display = Syntax(before, syntax, theme="monokai", word_wrap=True)
        after_display = Syntax(after, syntax, theme="monokai", word_wrap=True)
    else:
        before_display = Text(before)
        after_display = Text(after)

    # Create panels
    before_panel = Panel(before_display, title=title_before, border_style="red")
    after_panel = Panel(after_display, title=title_after, border_style="green")

    console.print(Columns([before_panel, after_panel], equal=True))


def preview_file(
    file_path: Path | str,
    *,
    title: str | None = None,
    max_lines: int | None = 50,
    console: Console | None = None,
) -> None:
    """
    Preview a file with automatic syntax detection.

    Args:
        file_path: Path to file to preview.
        title: Panel title (default: filename).
        max_lines: Maximum lines to show (None for all).
        console: Rich Console instance.

    Example:
        >>> preview_file("config/config.yaml")
    """
    if console is None:
        console = Console()

    file_path = Path(file_path)

    if not file_path.exists():
        console.print(f"[red]File not found:[/] {file_path}")
        return

    content = file_path.read_text(encoding="utf-8")

    # Truncate if needed
    lines = content.splitlines()
    truncated = False
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        truncated = True
        content = "\n".join(lines)

    # Detect syntax from extension
    suffix = file_path.suffix.lower()
    SYNTAX_MAP = {
        ".yaml": "yaml",
        ".yml": "yaml",
        ".json": "json",
        ".md": "markdown",
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".j2": "jinja2",
        ".html": "html",
        ".css": "css",
        ".toml": "toml",
        ".ini": "ini",
        ".sh": "bash",
        ".bash": "bash",
    }
    syntax_lang = SYNTAX_MAP.get(suffix, "text")

    # Build title
    display_title = title or file_path.name
    if truncated:
        display_title += f" [dim](showing {max_lines}/{len(lines) + (len(content.splitlines()) - max_lines)} lines)[/]"

    syntax = Syntax(
        content,
        syntax_lang,
        theme="monokai",
        line_numbers=True,
        word_wrap=True,
    )
    console.print(Panel(syntax, title=display_title, border_style="blue"))


def preview_yaml_structure(
    content: str,
    *,
    title: str = "YAML Structure",
    max_depth: int = 3,
    console: Console | None = None,
) -> None:
    """
    Preview YAML as a tree structure showing keys and types.

    Args:
        content: YAML content to analyze.
        title: Panel title.
        max_depth: Maximum tree depth to show.
        console: Rich Console instance.

    Example:
        >>> preview_yaml_structure("root:\\n  child: value\\n  list:\\n    - item")
    """
    import yaml

    if console is None:
        console = Console()

    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        console.print(f"[red]Invalid YAML:[/] {e}")
        return

    from rich.tree import Tree

    def add_to_tree(tree: Tree, obj: Any, depth: int = 0) -> None:
        """Recursively add items to tree."""
        if depth >= max_depth:
            tree.add("[dim]...[/]")
            return

        if isinstance(obj, dict):
            for key, value in obj.items():
                if isinstance(value, dict):
                    branch = tree.add(f"[cyan]{key}[/] [dim](dict)[/]")
                    add_to_tree(branch, value, depth + 1)
                elif isinstance(value, list):
                    branch = tree.add(f"[cyan]{key}[/] [dim](list, {len(value)} items)[/]")
                    add_to_tree(branch, value, depth + 1)
                else:
                    tree.add(f"[cyan]{key}[/]: [green]{repr(value)}[/]")
        elif isinstance(obj, list):
            for i, item in enumerate(obj[:5]):  # Show first 5
                if isinstance(item, (dict, list)):
                    branch = tree.add(f"[dim][{i}][/]")
                    add_to_tree(branch, item, depth + 1)
                else:
                    tree.add(f"[dim][{i}][/] [green]{repr(item)}[/]")
            if len(obj) > 5:
                tree.add(f"[dim]... and {len(obj) - 5} more[/]")

    tree = Tree(f"[bold]{title}[/]")
    add_to_tree(tree, data)
    console.print(tree)


def preview_validation_result(
    content: str,
    file_type: str = "yaml",
    *,
    console: Console | None = None,
) -> bool:
    """
    Validate and preview content with status indicator.

    Args:
        content: Content to validate.
        file_type: Type of content ("yaml" or "json").
        console: Rich Console instance.

    Returns:
        True if valid, False if invalid.

    Example:
        >>> if preview_validation_result("key: value", "yaml"):
        ...     print("Valid!")
    """
    import json
    import yaml

    if console is None:
        console = Console()

    try:
        if file_type == "yaml":
            yaml.safe_load(content)
        elif file_type == "json":
            json.loads(content)
        else:
            console.print(f"[yellow]Unknown file type: {file_type}[/]")
            return True

        console.print(f"[green]✓ Valid {file_type.upper()}[/]")
        return True

    except (yaml.YAMLError, json.JSONDecodeError) as e:
        console.print(f"[red]✗ Invalid {file_type.upper()}:[/] {e}")
        return False


def preview_bbcode(
    content: str,
    *,
    title: str = "BBCode Preview",
    console: Console | None = None,
) -> None:
    """
    Display BBCode content with basic visual preview.

    Note: This is a simplified preview. Full BBCode rendering
    would require a proper parser.

    Args:
        content: BBCode content to display.
        title: Panel title.
        console: Rich Console instance.

    Example:
        >>> preview_bbcode("[b]Bold[/b] and [i]italic[/i]")
    """
    if console is None:
        console = Console()

    # Simple BBCode to Rich markup conversion (basic tags only)
    text = content

    # Very basic conversion for common tags
    replacements = [
        ("[b]", "[bold]"),
        ("[/b]", "[/bold]"),
        ("[i]", "[italic]"),
        ("[/i]", "[/italic]"),
        ("[u]", "[underline]"),
        ("[/u]", "[/underline]"),
        ("[s]", "[strike]"),
        ("[/s]", "[/strike]"),
        ("[code]", "[cyan]"),
        ("[/code]", "[/cyan]"),
    ]

    for old, new in replacements:
        text = text.replace(old, new)

    # Remove other BBCode tags for display
    import re

    text = re.sub(r"\[/?[a-z]+(?:=[^\]]+)?\]", "", text, flags=re.IGNORECASE)

    console.print(Panel(text, title=title, border_style="magenta"))


def preview_comparison_table(
    items: list[tuple[str, str, str]],
    *,
    title: str = "Comparison",
    headers: tuple[str, str, str] = ("Item", "Before", "After"),
    console: Console | None = None,
) -> None:
    """
    Display a comparison table of changes.

    Args:
        items: List of (name, before_value, after_value) tuples.
        title: Table title.
        headers: Column headers.
        console: Rich Console instance.

    Example:
        >>> items = [("key1", "old1", "new1"), ("key2", "old2", "new2")]
        >>> preview_comparison_table(items)
    """
    if console is None:
        console = Console()

    table = Table(title=title)
    table.add_column(headers[0], style="cyan")
    table.add_column(headers[1], style="red")
    table.add_column(headers[2], style="green")

    for name, before, after in items:
        # Highlight if changed
        if before != after:
            table.add_row(name, before, f"[bold]{after}[/bold]")
        else:
            table.add_row(name, before, after)

    console.print(table)
