"""Trumping output components for MAMFast UI.

These components display trumping decisions and quality comparisons.
"""

from __future__ import annotations

from rich.table import Table

from shelfr.ui.core import console


def _format_duration(seconds: int | None) -> str:
    """Format duration in human-readable form."""
    if seconds is None:
        return "?"
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def print_trump_decision(
    decision_name: str,
    reason: str,
    existing_format: str | None = None,
    incoming_format: str | None = None,
    existing_bitrate: int | None = None,
    incoming_bitrate: int | None = None,
) -> None:
    """Display trump decision with optional quality comparison.

    Args:
        decision_name: Name of the TrumpDecision enum value
        reason: Human-readable reason string
        existing_format: Existing file format (optional)
        incoming_format: Incoming file format (optional)
        existing_bitrate: Existing bitrate in kbps (optional)
        incoming_bitrate: Incoming bitrate in kbps (optional)
    """
    icons = {
        "KEEP_EXISTING": "⏭️",
        "KEEP_BOTH": "📁",
        "REPLACE_WITH_NEW": "🔄",
        "REJECT_NEW": "❌",
    }
    icon = icons.get(decision_name, "❓")

    console.print(f"  {icon} [bold]{decision_name}[/]: {reason}")

    # Show brief quality comparison for REPLACE_WITH_NEW
    if decision_name == "REPLACE_WITH_NEW":
        existing = f"{existing_format or '?'}"
        if existing_bitrate:
            existing += f" @ {existing_bitrate}kbps"
        incoming = f"{incoming_format or '?'}"
        if incoming_bitrate:
            incoming += f" @ {incoming_bitrate}kbps"
        console.print(f"    [dim]{existing}[/] → [green]{incoming}[/]")


def print_trump_comparison_table(
    existing_format: str | None,
    incoming_format: str | None,
    existing_bitrate: int | None,
    incoming_bitrate: int | None,
    existing_sample_rate: int | None,
    incoming_sample_rate: int | None,
    existing_duration: int | None,
    incoming_duration: int | None,
    existing_chapters: bool,
    incoming_chapters: bool,
    existing_stereo: bool,
    incoming_stereo: bool,
) -> None:
    """Display detailed quality comparison table for trumping.

    Shows existing vs incoming quality metrics in a table format.
    """
    table = Table(title="Quality Comparison", show_header=True, header_style="bold cyan")
    table.add_column("Metric", style="cyan")
    table.add_column("Existing", style="red")
    table.add_column("Incoming", style="green")

    table.add_row("Format", existing_format or "?", incoming_format or "?")
    table.add_row(
        "Bitrate",
        f"{existing_bitrate} kbps" if existing_bitrate else "?",
        f"{incoming_bitrate} kbps" if incoming_bitrate else "?",
    )
    table.add_row(
        "Sample Rate",
        f"{existing_sample_rate} Hz" if existing_sample_rate else "?",
        f"{incoming_sample_rate} Hz" if incoming_sample_rate else "?",
    )
    table.add_row(
        "Duration",
        _format_duration(existing_duration),
        _format_duration(incoming_duration),
    )
    table.add_row(
        "Chapters",
        "[green]✓[/]" if existing_chapters else "[dim]✗[/]",
        "[green]✓[/]" if incoming_chapters else "[dim]✗[/]",
    )
    table.add_row(
        "Stereo",
        "[green]✓[/]" if existing_stereo else "[dim]✗[/]",
        "[green]✓[/]" if incoming_stereo else "[dim]✗[/]",
    )

    console.print(table)


def print_trump_summary(
    replaced: int,
    kept_existing: int,
    rejected: int,
) -> None:
    """Print summary of trumping statistics.

    Args:
        replaced: Count of books where existing was archived and new imported
        kept_existing: Count of books where existing was kept (no improvement)
        rejected: Count of books where incoming was rejected (worse quality)
    """
    total = replaced + kept_existing + rejected
    if total == 0:
        return

    console.print()
    console.print("[bold]Trumping Summary[/]")
    if replaced > 0:
        console.print(f"  🔄 Replaced: [green]{replaced}[/]")
    if kept_existing > 0:
        console.print(f"  ⏭️  Kept existing: [dim]{kept_existing}[/]")
    if rejected > 0:
        console.print(f"  ❌ Rejected: [warning]{rejected}[/]")
