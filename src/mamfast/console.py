"""Rich console output for MAMFast CLI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

# Custom theme for MAMFast
MAMFAST_THEME = Theme(
    {
        "info": "cyan",
        "success": "green",
        "warning": "yellow",
        "error": "red bold",
        "step": "bold cyan",
        "title": "bold white",
        "dim": "dim",
        "highlight": "bold magenta",
    }
)

# Global console instance
console = Console(theme=MAMFAST_THEME, stderr=False)
err_console = Console(theme=MAMFAST_THEME, stderr=True)


@dataclass
class StepResult:
    """Result of a pipeline step."""

    success: bool
    message: str = ""
    details: list[str] | None = None


def print_header(title: str, subtitle: str | None = None, dry_run: bool = False) -> None:
    """Print a styled header panel."""
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


def print_step(step_num: int, total_steps: int, title: str) -> None:
    """Print a step header."""
    console.print(f"[step]Step {step_num}/{total_steps}:[/] {title}")


def print_substep(message: str, style: str = "dim") -> None:
    """Print an indented substep message."""
    console.print(f"  [{style}]•[/] {message}")


def print_success(message: str) -> None:
    """Print a success message with checkmark."""
    console.print(f"  [success]✓[/] {message}")


def print_error(message: str) -> None:
    """Print an error message with X."""
    console.print(f"  [error]✗[/] {message}")


def print_warning(message: str) -> None:
    """Print a warning message."""
    console.print(f"  [warning]![/] {message}")


def print_info(message: str) -> None:
    """Print an info message."""
    console.print(f"  [info]→[/] {message}")


def print_dry_run(message: str) -> None:
    """Print a dry-run message."""
    console.print(f"  [warning][DRY RUN][/] {message}")


def print_divider() -> None:
    """Print a horizontal divider."""
    console.print("─" * min(60, console.width), style="dim")


def print_summary(
    successful: int,
    failed: int,
    skipped: int = 0,
    duration: float | None = None,
) -> None:
    """Print a pipeline summary."""
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


def print_release_table(
    releases: list[Any],
    title: str = "Releases",
    show_status: bool = False,
) -> None:
    """Print a table of releases."""
    if not releases:
        console.print(f"[dim]No {title.lower()} found[/]")
        return

    table = Table(title=title, show_header=True, header_style="bold")
    table.add_column("#", style="dim", width=4)
    table.add_column("Author", style="cyan")
    table.add_column("Title")
    table.add_column("ASIN", style="dim")

    if show_status:
        table.add_column("Status", justify="center")

    for i, release in enumerate(releases, 1):
        row = [
            str(i),
            release.author or "Unknown",
            release.title or "Unknown",
            release.asin or "-",
        ]
        if show_status:
            status = getattr(release, "status", None)
            if status:
                row.append(f"[dim]{status.value}[/]")
            else:
                row.append("-")
        table.add_row(*row)

    console.print(table)


def print_config_section(title: str, items: dict[str, Any]) -> None:
    """Print a configuration section."""
    console.print(f"\n[title]{title}[/]")
    for key, value in items.items():
        console.print(f"  [dim]{key}:[/] {value}")


def print_status_table(
    processed: dict[str, Any],
    failed: dict[str, Any] | None = None,
    limit: int = 10,
) -> None:
    """Print status tables for processed and failed releases."""
    if processed:
        table = Table(title="Recently Processed", show_header=True, header_style="bold")
        table.add_column("ASIN", style="dim")
        table.add_column("Author", style="cyan")
        table.add_column("Title")
        table.add_column("Processed", style="dim")

        # Sort by processed_at, show last N
        items = sorted(
            processed.items(),
            key=lambda x: x[1].get("processed_at", ""),
            reverse=True,
        )[:limit]

        for asin, info in items:
            table.add_row(
                asin,
                info.get("author", "Unknown"),
                info.get("title", "Unknown"),
                info.get("processed_at", "-")[:10],  # Just date
            )

        console.print(table)

    if failed:
        console.print()
        table = Table(title="[error]Failed Releases[/]", show_header=True, header_style="bold")
        table.add_column("ASIN", style="dim")
        table.add_column("Title")
        table.add_column("Error", style="error")

        for asin, info in list(failed.items())[:limit]:
            table.add_row(
                asin,
                info.get("title", "Unknown"),
                info.get("error", "Unknown error")[:50],
            )

        console.print(table)


def print_directory_status(name: str, path: Any, exists: bool, count: int | None = None) -> None:
    """Print directory status line."""
    if exists:
        count_str = f" ({count} items)" if count is not None else ""
        console.print(f"  [success]✓[/] {name}: {path}{count_str}")
    else:
        console.print(f"  [error]✗[/] {name}: {path} [dim](not found)[/]")


def confirm(message: str, default: bool = False) -> bool:
    """Ask for user confirmation."""
    suffix = " [Y/n]" if default else " [y/N]"
    try:
        response = console.input(f"[warning]?[/] {message}{suffix} ")
        if not response:
            return default
        return response.lower() in ("y", "yes")
    except (KeyboardInterrupt, EOFError):
        console.print()
        return False


def fatal_error(message: str, hint: str | None = None) -> None:
    """Print a fatal error and exit hint."""
    err_console.print(f"\n[error]Error:[/] {message}")
    if hint:
        err_console.print(f"[dim]Hint: {hint}[/]")


# Convenience function for quick messages
def status(message: str, style: str = "info") -> None:
    """Print a simple status message."""
    console.print(f"[{style}]{message}[/]")
