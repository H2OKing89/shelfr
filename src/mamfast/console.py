"""Rich console output for MAMFast CLI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme
from rich.traceback import Traceback

if TYPE_CHECKING:
    from mamfast.validation import ValidationResult

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


# =============================================================================
# Rule Trace Tables (Phase 3)
# =============================================================================


@dataclass
class RuleTrace:
    """Record of a naming rule application."""

    field: str
    before: str
    after: str
    rule_id: str | None = None
    rule_type: str | None = None


def log_title_transform(
    field: str,
    before: str,
    after: str,
    rule_id: str | None = None,
    verbose: bool = False,
) -> None:
    """
    Log a title transformation with optional rule trace.

    Args:
        field: Which field was transformed (e.g., "title", "subtitle", "series")
        before: Original value
        after: Transformed value
        rule_id: Optional identifier for the rule that made the change
        verbose: Only print if verbose mode is enabled
    """
    if not verbose or before == after:
        return

    table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1))
    table.add_column("Field", style="dim", width=12)
    table.add_column("Before", style="red", overflow="fold")
    table.add_column("After", style="green", overflow="fold")
    table.add_row(field, before, after)
    console.print(table)

    if rule_id:
        console.print(f"  [dim]rule:[/] [yellow]{rule_id}[/yellow]")


def print_rule_trace(traces: list[RuleTrace], title: str = "Rule Applications") -> None:
    """
    Print a table of rule applications for debugging.

    Args:
        traces: List of RuleTrace objects showing what each rule did
        title: Table title
    """
    if not traces:
        console.print(f"[dim]No {title.lower()} to display[/]")
        return

    # Filter to only show changes
    changes = [t for t in traces if t.before != t.after]
    if not changes:
        console.print(f"[dim]No changes made ({len(traces)} rules checked)[/]")
        return

    table = Table(title=title, show_header=True, header_style="bold")
    table.add_column("Field", style="cyan", width=10)
    table.add_column("Rule", style="yellow", width=20)
    table.add_column("Before", style="red", overflow="fold")
    table.add_column("After", style="green", overflow="fold")

    for trace in changes:
        rule_name = trace.rule_id or trace.rule_type or "-"
        table.add_row(
            trace.field,
            rule_name,
            trace.before[:50] + "..." if len(trace.before) > 50 else trace.before,
            trace.after[:50] + "..." if len(trace.after) > 50 else trace.after,
        )

    console.print(table)
    console.print(f"[dim]{len(changes)} changes from {len(traces)} rules checked[/]")


# =============================================================================
# Validation Report Tables (Phase 3)
# =============================================================================


def print_validation_report(result: ValidationResult, title: str = "Validation Results") -> None:
    """
    Print validation results as a Rich table.

    Args:
        result: ValidationResult object containing checks
        title: Table title
    """
    if not result.checks:
        console.print("[dim]No validation checks to display[/]")
        return

    table = Table(title=title, show_header=True, header_style="bold")
    table.add_column("", width=3)  # Status icon
    table.add_column("Check", style="cyan")
    table.add_column("Category", style="dim")
    table.add_column("Message")

    for check in result.checks:
        icon = check.icon
        style = "green" if check.passed else ("red" if check.severity == "error" else "yellow")
        table.add_row(
            icon,
            check.name,
            check.category.value,
            f"[{style}]{check.message}[/{style}]",
        )

    console.print(table)
    print_validation_summary(result)


def print_validation_summary(result: ValidationResult) -> None:
    """Print a one-line summary of validation results."""
    parts = []
    if result.passed_count > 0:
        parts.append(f"[success]{result.passed_count} passed[/]")
    if result.error_count > 0:
        parts.append(f"[error]{result.error_count} errors[/]")
    if result.warning_count > 0:
        parts.append(f"[warning]{result.warning_count} warnings[/]")

    status_icon = "[success]✓[/]" if result.passed else "[error]✗[/]"
    summary = ", ".join(parts) if parts else "[dim]No checks[/]"
    console.print(f"{status_icon} {summary}")


def print_check_category(
    result: ValidationResult,
    category: Any,  # CheckCategory, but avoiding circular import
    title: str | None = None,
) -> None:
    """Print validation checks for a specific category."""
    checks = result.by_category(category)
    if not checks:
        return

    display_title = title or category.value
    console.print(f"\n[title]{display_title}[/]")

    for check in checks:
        if check.passed:
            console.print(f"  [success]✓[/] {check.message}")
        elif check.severity == "error":
            console.print(f"  [error]✗[/] {check.message}")
        else:
            console.print(f"  [warning]![/] {check.message}")


# =============================================================================
# Workflow Progress Helpers (Phase 3)
# =============================================================================


def print_workflow_summary(stats: dict[str, int], duration: float | None = None) -> None:
    """
    Print workflow completion summary as a table.

    Args:
        stats: Dict with keys like "discovered", "staged", "metadata",
            "torrents", "uploaded", "skipped", "errors"
        duration: Optional total duration in seconds
    """
    table = Table(title="Workflow Summary", show_header=True, header_style="bold")
    table.add_column("Stage", style="cyan")
    table.add_column("Count", justify="right")

    stage_order = [
        ("discovered", "Discovered"),
        ("staged", "Staged"),
        ("metadata", "Metadata Fetched"),
        ("torrents", "Torrents Created"),
        ("uploaded", "Uploaded"),
        ("skipped", "Skipped"),
        ("errors", "Errors"),
    ]

    for key, label in stage_order:
        count = stats.get(key, 0)
        if count > 0 or key in ("discovered", "errors"):
            style = "error" if key == "errors" and count > 0 else "white"
            table.add_row(label, f"[{style}]{count}[/{style}]")

    console.print(table)

    if duration is not None:
        console.print(f"[dim]Completed in {duration:.1f}s[/]")


def print_release_details(release: Any, verbose: bool = False) -> None:
    """
    Print detailed release info in a panel.

    Args:
        release: AudiobookRelease object
        verbose: Show additional fields if True
    """
    # Build content lines
    lines = []

    if hasattr(release, "asin") and release.asin:
        lines.append(f"[cyan]ASIN:[/] {release.asin}")

    if hasattr(release, "title") and release.title:
        lines.append(f"[cyan]Title:[/] {release.title}")

    if hasattr(release, "subtitle") and release.subtitle:
        lines.append(f"[cyan]Subtitle:[/] {release.subtitle}")

    if hasattr(release, "series") and release.series:
        lines.append(f"[cyan]Series:[/] {release.series}")

    if hasattr(release, "author") and release.author:
        lines.append(f"[cyan]Author:[/] {release.author}")
    elif hasattr(release, "authors") and release.authors:
        author_names = [
            a.get("name", "") if isinstance(a, dict) else str(a) for a in release.authors[:3]
        ]
        lines.append(f"[cyan]Authors:[/] {', '.join(author_names)}")

    if hasattr(release, "folder_name") and release.folder_name:
        lines.append(f"[cyan]Folder:[/] {release.folder_name}")

    if hasattr(release, "status"):
        status_val = (
            release.status.value if hasattr(release.status, "value") else str(release.status)
        )
        lines.append(f"[cyan]Status:[/] {status_val}")

    if verbose:
        if hasattr(release, "source_dir") and release.source_dir:
            lines.append(f"[dim]Source:[/] {release.source_dir}")
        if hasattr(release, "staged_dir") and release.staged_dir:
            lines.append(f"[dim]Staged:[/] {release.staged_dir}")
        if hasattr(release, "torrent_path") and release.torrent_path:
            lines.append(f"[dim]Torrent:[/] {release.torrent_path}")

    if not lines:
        lines.append("[dim]No release details available[/]")

    content = "\n".join(lines)
    title = release.title[:50] if hasattr(release, "title") and release.title else "Release"

    console.print(Panel(content, title=title, expand=False, border_style="cyan"))


def print_pipeline_progress(
    stage: str,
    current: int,
    total: int,
    release_name: str | None = None,
) -> None:
    """
    Print a single-line pipeline progress update.

    Args:
        stage: Current stage name (e.g., "Staging", "Metadata")
        current: Current item number (1-based)
        total: Total items
        release_name: Optional release name to display
    """
    progress = f"[{current}/{total}]"
    name = (
        f" {release_name[:40]}..."
        if release_name and len(release_name) > 40
        else (f" {release_name}" if release_name else "")
    )
    console.print(f"[step]{stage}[/] {progress}{name}")


# =============================================================================
# Error Formatting (Phase 3)
# =============================================================================


def print_exception(
    error: Exception,
    title: str = "Error",
    context: dict[str, Any] | None = None,
    show_traceback: bool = True,
) -> None:
    """
    Print a formatted exception with context.

    Args:
        error: The exception to display
        title: Error title/header
        context: Optional dict of contextual info to display
        show_traceback: Whether to show full traceback (default True)
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
    """
    Print a summary table of multiple errors.

    Args:
        errors: List of (context, exception) tuples
        title: Table title
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


# Convenience function for quick messages


# Convenience function for quick messages
def status(message: str, style: str = "info") -> None:
    """Print a simple status message."""
    console.print(f"[{style}]{message}[/]")
