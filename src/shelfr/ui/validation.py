"""Validation output components for MAMFast UI.

These components display validation results and health check output.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from rich.table import Table

from shelfr.ui.core import console

if TYPE_CHECKING:
    from shelfr.validation import ValidationResult


@dataclass
class RuleTrace:
    """Record of a naming rule application."""

    field: str
    before: str
    after: str
    rule_id: str | None = None
    rule_type: str | None = None


def print_validation_report(result: ValidationResult, title: str = "Validation Results") -> None:
    """Print validation results as a Rich table.

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
    """Print a one-line summary of validation results.

    Args:
        result: ValidationResult object
    """
    parts = []
    if result.passed_count > 0:
        parts.append(f"[success]{result.passed_count} passed[/]")
    if result.error_count > 0:
        error_word = "error" if result.error_count == 1 else "errors"
        parts.append(f"[error]{result.error_count} {error_word}[/]")
    if result.warning_count > 0:
        warning_word = "warning" if result.warning_count == 1 else "warnings"
        parts.append(f"[warning]{result.warning_count} {warning_word}[/]")

    status_icon = "[success]✓[/]" if result.passed else "[error]✗[/]"
    summary = ", ".join(parts) if parts else "[dim]No checks[/]"
    console.print(f"{status_icon} {summary}")


def print_check_category(
    result: ValidationResult,
    category: Any,  # CheckCategory, but avoiding circular import
    title: str | None = None,
) -> None:
    """Print validation checks for a specific category.

    Args:
        result: ValidationResult object
        category: CheckCategory enum value
        title: Optional override title
    """
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


def log_title_transform(
    field: str,
    before: str,
    after: str,
    rule_id: str | None = None,
    verbose: bool = False,
) -> None:
    """Log a title transformation with optional rule trace.

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
    """Print a table of rule applications for debugging.

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


def print_change_analysis(
    asin: str | None,
    original: str,
    cleaned: str,
    similarity: float,
    is_suspicious: bool,
) -> None:
    """Print detailed analysis of a single title change.

    Args:
        asin: Release ASIN
        original: Original title
        cleaned: Cleaned title
        similarity: Similarity percentage
        is_suspicious: Whether the change is flagged as suspicious
    """
    status_icon = "[warning]⚠[/]" if is_suspicious else "[success]✓[/]"
    status_text = "SUSPICIOUS" if is_suspicious else "OK"

    console.print(f"\n{status_icon} [{status_text}] Change Analysis")
    console.print(f"  [dim]ASIN:[/] {asin or 'N/A'}")
    console.print(f"  [dim]Original:[/] [red]{original}[/]")
    console.print(f"  [dim]Cleaned:[/]  [green]{cleaned}[/]")
    console.print(f"  [dim]Similarity:[/] {similarity:.1f}%")

    if is_suspicious:
        console.print()
        console.print(
            "  [warning]The cleaned title is significantly different from the original.[/]"
        )
        console.print("  [hint]This may indicate over-aggressive rule matching.[/]")
