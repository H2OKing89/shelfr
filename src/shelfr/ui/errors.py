"""Error formatting components for MAMFast UI.

These components provide rich formatting for exceptions and error output.
"""

from __future__ import annotations

from typing import Any

from rich.table import Table
from rich.traceback import Traceback

from shelfr.ui.core import err_console


def print_exception(
    error: Exception,
    title: str = "Error",
    context: dict[str, Any] | None = None,
    show_traceback: bool = True,
) -> None:
    """Print a formatted exception with context.

    Args:
        error: The exception to display
        title: Error title/header
        context: Optional dict of contextual info to display
        show_traceback: Whether to show full traceback (default True)

    Example:
        >>> try:
        ...     do_something()
        ... except ValueError as e:
        ...     print_exception(e, "Validation Error", {"field": "title"})
    """
    err_console.print(f"\n[error]❌ {title}[/]")
    err_console.print(f"[error]{type(error).__name__}:[/] {error}")

    if context:
        err_console.print()
        for key, value in context.items():
            err_console.print(f"  [dim]{key}:[/] {value}")

    if show_traceback:
        err_console.print()
        err_console.print(
            Traceback.from_exception(
                type(error),
                error,
                error.__traceback__,
                show_locals=False,
                max_frames=10,
            )
        )


def print_error_summary(errors: list[tuple[str, Exception]], title: str = "Errors") -> None:
    """Print a summary table of multiple errors.

    Args:
        errors: List of (context, exception) tuples
        title: Table title

    Example:
        >>> errors = [("file1.m4b", ValueError("Bad format")), ("file2.m4b", IOError("Not found"))]
        >>> print_error_summary(errors)
    """
    if not errors:
        return

    table = Table(title=f"[error]{title}[/]", show_header=True, header_style="bold")
    table.add_column("Context", style="cyan")
    table.add_column("Error Type", style="yellow")
    table.add_column("Message", style="red", overflow="fold")

    for context, error in errors:
        table.add_row(
            context[:30] + "..." if len(context) > 30 else context,
            type(error).__name__,
            str(error)[:60] + "..." if len(str(error)) > 60 else str(error),
        )

    err_console.print(table)


def print_error_panel(
    message: str,
    details: list[str] | None = None,
    hints: list[str] | None = None,
) -> None:
    """Print an error message with optional details and hints.

    Args:
        message: Main error message
        details: Optional list of detail lines
        hints: Optional list of hint/fix suggestions

    Example:
        >>> print_error_panel(
        ...     "Connection failed",
        ...     details=["Host: localhost:8080", "Timeout: 30s"],
        ...     hints=["Check if the server is running", "Verify the port number"]
        ... )
    """
    from rich.panel import Panel
    from rich.text import Text

    content = Text()
    content.append("❌ ", style="error")
    content.append(message, style="error")

    if details:
        content.append("\n")
        for detail in details:
            content.append(f"\n  • {detail}", style="dim")

    if hints:
        content.append("\n\n")
        content.append("💡 ", style="info")
        content.append("Suggestions:", style="info")
        for hint in hints:
            content.append(f"\n  → {hint}", style="hint")

    err_console.print(
        Panel(
            content,
            title="[error]Error[/]",
            border_style="red",
            padding=(0, 2),
        )
    )
