"""Panel and header components for MAMFast UI.

These components provide styled containers for content display.
"""

from __future__ import annotations

from typing import Any

from rich.panel import Panel
from rich.text import Text

from shelfr.ui.core import console


def print_header(title: str, subtitle: str | None = None, dry_run: bool = False) -> None:
    """Print a styled header panel.

    Args:
        title: Main header title
        subtitle: Optional subtitle text
        dry_run: Whether to show dry-run indicator

    Example:
        >>> print_header("Full Pipeline", subtitle="Processing 5 releases", dry_run=True)
        ╭──────────────────────────────────────╮
        │             MAMFast                  │
        │         Full Pipeline                │
        │     Processing 5 releases            │
        │           [DRY RUN]                  │
        ╰──────────────────────────────────────╯
    """
    content = Text()
    content.append(title, style="title")
    if subtitle:
        content.append(f"\n{subtitle}", style="dim")
    if dry_run:
        content.append("\n[DRY RUN]", style="warning")

    console.print(
        Panel(
            content,
            title="[bold cyan]MAMFast[/]",
            border_style="cyan",
            padding=(0, 2),
        )
    )
    console.print()


def print_divider() -> None:
    """Print a horizontal divider.

    Example:
        >>> print_divider()
        ────────────────────────────────────────
    """
    console.print("─" * min(60, console.width), style="dim")


def print_summary(
    successful: int,
    failed: int,
    skipped: int = 0,
    duration: float | None = None,
) -> None:
    """Print a pipeline summary.

    Args:
        successful: Number of successful operations
        failed: Number of failed operations
        skipped: Number of skipped operations
        duration: Optional duration in seconds

    Example:
        >>> print_summary(5, 1, 2, duration=12.5)
        ────────────────────────────────
        Summary: 5 successful, 1 failed, 2 skipped (12.5s)
    """
    console.print()
    print_divider()

    parts = []
    if successful > 0:
        parts.append(f"[success]{successful} successful[/]")
    if failed > 0:
        parts.append(f"[error]{failed} failed[/]")
    if skipped > 0:
        parts.append(f"[dim]{skipped} skipped[/]")

    summary = ", ".join(parts) if parts else "[dim]No releases processed[/]"

    if duration is not None:
        summary += f" [dim]({duration:.1f}s)[/]"

    console.print(f"[title]Summary:[/] {summary}")


def print_config_section(title: str, items: dict[str, Any]) -> None:
    """Print a configuration section.

    Args:
        title: Section title
        items: Dict of config key-value pairs

    Example:
        >>> print_config_section("Paths", {"library": "/mnt/books", "staging": "/tmp"})

        Paths
          library: /mnt/books
          staging: /tmp
    """
    console.print(f"\n[title]{title}[/]")
    for key, value in items.items():
        console.print(f"  [dim]{key}:[/] {value}")


def print_directory_status(name: str, path: Any, exists: bool, count: int | None = None) -> None:
    """Print directory status line.

    Args:
        name: Directory name/label
        path: Directory path
        exists: Whether directory exists
        count: Optional item count

    Example:
        >>> print_directory_status("Library", "/mnt/books", True, count=42)
          ✓ Library: /mnt/books (42 items)
    """
    if exists:
        count_str = f" ({count} items)" if count is not None else ""
        console.print(f"  [success]✓[/] {name}: {path}{count_str}")
    else:
        console.print(f"  [error]✗[/] {name}: {path} [dim](not found)[/]")


def print_hint_panel(hints: list[str], title: str = "💡 Tips") -> None:
    """Print a panel with helpful hints.

    Args:
        hints: List of hint strings
        title: Panel title

    Example:
        >>> print_hint_panel(["Use --dry-run first", "Check logs for details"])
        ╭─────────── 💡 Tips ───────────╮
        │ • Use --dry-run first         │
        │ • Check logs for details      │
        ╰───────────────────────────────╯
    """
    if not hints:
        return

    content = Text()
    for i, hint in enumerate(hints):
        if i > 0:
            content.append("\n")
        content.append("• ", style="cyan")
        content.append(hint, style="dim")

    console.print(
        Panel(
            content,
            title=f"[cyan]{title}[/]",
            border_style="dim cyan",
            padding=(0, 1),
        )
    )
    console.print()


def print_box(
    content: str,
    title: str | None = None,
    border_style: str = "cyan",
    padding: tuple[int, int] = (0, 2),
) -> None:
    """Print content in a styled box/panel.

    Args:
        content: Content to display
        title: Optional box title
        border_style: Rich style for border
        padding: Vertical and horizontal padding

    Example:
        >>> print_box("Important message!", title="Notice", border_style="yellow")
    """
    console.print(
        Panel(
            content,
            title=f"[bold]{title}[/]" if title else None,
            border_style=border_style,
            padding=padding,
        )
    )
