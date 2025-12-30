"""Table formatting components for MAMFast UI.

These components provide Rich table displays for releases, status, and other data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.panel import Panel
from rich.table import Table

from shelfr.ui.core import console

if TYPE_CHECKING:
    from shelfr.libation import LibationStatus


def print_release_table(
    releases: list[Any],
    title: str = "Releases",
    show_status: bool = False,
) -> None:
    """Print a table of releases.

    Args:
        releases: List of AudiobookRelease objects
        title: Table title
        show_status: Whether to show status column

    Example:
        >>> print_release_table(releases, "New Releases", show_status=True)
        ┏━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┓
        ┃ #  ┃ Author    ┃ Title          ┃ ASIN        ┃
        ┡━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━┩
        │ 1  │ King      │ The Shining    │ B0DK9T5P28  │
        └────┴───────────┴────────────────┴─────────────┘
    """
    if not releases:
        console.print(f"[dim]No {title.lower()} found[/]")
        return

    table = Table(title=title, show_header=True, header_style="bold")
    table.add_column("#", style="dim", width=4)
    table.add_column("Author", style="author")
    table.add_column("Title")
    table.add_column("ASIN", style="asin")

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


def print_status_table(
    processed: dict[str, Any],
    failed: dict[str, Any] | None = None,
    limit: int = 10,
) -> None:
    """Print status tables for processed and failed releases.

    Args:
        processed: Dict of processed releases by ASIN
        failed: Optional dict of failed releases
        limit: Maximum items to show per table
    """
    if processed:
        table = Table(title="Recently Processed", show_header=True, header_style="bold")
        table.add_column("ASIN", style="asin")
        table.add_column("Author", style="author")
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
        table.add_column("ASIN", style="asin")
        table.add_column("Title")
        table.add_column("Error", style="error")

        for asin, info in list(failed.items())[:limit]:
            table.add_row(
                asin,
                info.get("title", "Unknown"),
                info.get("error", "Unknown error")[:50],
            )

        console.print(table)


def render_libation_status(
    status: LibationStatus,
    title: str = "Libation Status",
) -> None:
    """Render a Rich table describing Libation book statuses.

    Args:
        status: LibationStatus object with book counts
        title: Panel title
    """
    table = Table(
        show_header=True,
        header_style="bold cyan",
        show_edge=False,
        box=None,
        pad_edge=False,
    )
    table.add_column("Status", style="bold")
    table.add_column("Count", justify="right")
    table.add_column("Meaning", overflow="fold")

    def _add_row(label: str, count: int, meaning: str) -> None:
        table.add_row(label, f"{count:,}", meaning)

    _add_row("Liberated", status.liberated, "Downloaded and decrypted")
    _add_row(
        "NotLiberated",
        status.not_liberated,
        "Indexed but not yet downloaded (staged for download)",
    )
    _add_row("Error", status.error, "Failed to download")

    if status.other_statuses:
        for label, count in sorted(status.other_statuses.items()):
            meaning = "Additional status reported by Libation"
            _add_row(label, count, meaning)

    _add_row("Total", status.total, "All books tracked by Libation")

    panel = Panel(
        table,
        title=f"[b]{title}[/b]",
        border_style="blue",
        padding=(0, 1),
    )
    console.print(panel)


def print_workflow_summary(stats: dict[str, int], duration: float | None = None) -> None:
    """Print workflow completion summary as a table.

    Args:
        stats: Dict with keys like "discovered", "staged", "metadata", etc.
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
    """Print detailed release info in a panel.

    Args:
        release: AudiobookRelease object
        verbose: Show additional fields if True
    """
    lines = []

    if hasattr(release, "asin") and release.asin:
        lines.append(f"[asin]ASIN:[/] {release.asin}")

    if hasattr(release, "title") and release.title:
        lines.append(f"[cyan]Title:[/] {release.title}")

    if hasattr(release, "subtitle") and release.subtitle:
        lines.append(f"[cyan]Subtitle:[/] {release.subtitle}")

    if hasattr(release, "series") and release.series:
        lines.append(f"[series]Series:[/] {release.series}")

    if hasattr(release, "author") and release.author:
        lines.append(f"[author]Author:[/] {release.author}")
    elif hasattr(release, "authors") and release.authors:
        author_names = [
            a.get("name", "") if isinstance(a, dict) else str(a) for a in release.authors[:3]
        ]
        lines.append(f"[author]Authors:[/] {', '.join(author_names)}")

    if hasattr(release, "folder_name") and release.folder_name:
        lines.append(f"[path]Folder:[/] {release.folder_name}")

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


def print_duplicate_pairs(
    duplicates: list[tuple[str, str, float]],
    title: str = "Potential Duplicates",
    limit: int = 20,
) -> None:
    """Print a table of potential duplicate pairs.

    Args:
        duplicates: List of (item1, item2, similarity) tuples
        title: Table title
        limit: Maximum pairs to show
    """
    if not duplicates:
        console.print("[success]✓ No potential duplicates found[/]")
        return

    shown = duplicates[:limit]

    table = Table(
        title=f"[warning]{title} ({len(duplicates)} pairs)[/]",
        show_header=True,
        header_style="bold",
    )
    table.add_column("Item 1", style="cyan", overflow="fold", ratio=1)
    table.add_column("Item 2", style="cyan", overflow="fold", ratio=1)
    table.add_column("Similarity", style="yellow", justify="right", width=10)

    for item1, item2, similarity in shown:
        t1 = item1[:50] + "..." if len(item1) > 50 else item1
        t2 = item2[:50] + "..." if len(item2) > 50 else item2
        table.add_row(t1, t2, f"{similarity:.0f}%")

    console.print(table)

    if len(duplicates) > limit:
        console.print(f"\n[dim]Showing {limit} of {len(duplicates)} pairs[/]")


def print_suspicious_changes(
    changes: list[tuple[str, str, str, float]],
    title: str = "Suspicious Title Changes",
) -> None:
    """Print a table of suspicious title transformations.

    Args:
        changes: List of (asin, original, cleaned, similarity) tuples
        title: Table title
    """
    if not changes:
        console.print("[success]✓ No suspicious title changes detected[/]")
        return

    table = Table(
        title=f"[warning]{title}[/]",
        show_header=True,
        header_style="bold",
    )
    table.add_column("ASIN", style="asin", width=12)
    table.add_column("Original", style="red", overflow="fold", ratio=1)
    table.add_column("Cleaned", style="green", overflow="fold", ratio=1)
    table.add_column("Similarity", style="yellow", justify="right", width=10)

    for asin, original, cleaned, similarity in changes:
        table.add_row(
            asin or "-",
            original[:40] + "..." if len(original) > 40 else original,
            cleaned[:40] + "..." if len(cleaned) > 40 else cleaned,
            f"{similarity:.0f}%",
        )

    console.print(table)
    console.print()
    console.print(
        "[hint]Tip: Low similarity may indicate over-aggressive title cleaning. "
        "Review naming.json rules if needed.[/]"
    )
