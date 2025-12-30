"""Progress bar and spinner components for MAMFast UI.

These components provide visual feedback for long-running operations.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from shelfr.ui.core import console


def print_pipeline_progress(
    stage: str,
    current: int,
    total: int,
    release_name: str | None = None,
) -> None:
    """Print a single-line pipeline progress update.

    Args:
        stage: Current stage name (e.g., "Staging", "Metadata")
        current: Current item number (1-based)
        total: Total items
        release_name: Optional release name to display

    Example:
        >>> print_pipeline_progress("Staging", 3, 10, "The Shining")
        Staging [3/10] The Shining
    """
    progress = f"[{current}/{total}]"
    name = (
        f" {release_name[:40]}..."
        if release_name and len(release_name) > 40
        else (f" {release_name}" if release_name else "")
    )
    console.print(f"[step]{stage}[/] {progress}{name}")


@contextmanager
def progress_context(
    description: str = "Processing",
    total: int | None = None,
) -> Generator[tuple[Progress, TaskID], None, None]:
    """Context manager for Rich progress bar.

    Args:
        description: Initial description for the progress bar
        total: Total number of items (None for indeterminate spinner)

    Yields:
        Tuple of (Progress instance, TaskID) for updates

    Example:
        >>> with progress_context("Processing releases", total=10) as (progress, task):
        ...     for item in items:
        ...         # do work
        ...         progress.update(task, advance=1, description=f"Processing {item.name}")
    """
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    )

    with progress:
        task = progress.add_task(f"[cyan]{description}[/]", total=total)
        yield progress, task


def create_pipeline_progress() -> Progress:
    """Create a Progress instance for pipeline steps.

    Returns a Progress object that can be used as a context manager.

    Example:
        >>> with create_pipeline_progress() as progress:
        ...     scan_task = progress.add_task("[cyan]Scanning...", total=1)
        ...     # do scan
        ...     progress.update(scan_task, completed=1)
        ...
        ...     process_task = progress.add_task("[cyan]Processing...", total=len(releases))
        ...     for release in releases:
        ...         # process
        ...         progress.update(process_task, advance=1)
    """
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
        transient=False,  # Keep completed tasks visible
    )


def create_download_progress() -> Progress:
    """Create a Progress instance for download operations.

    Includes time remaining estimate suitable for downloads.

    Returns:
        Progress instance configured for downloads
    """
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        "•",
        TimeRemainingColumn(),
        console=console,
        transient=False,
    )


def create_spinner() -> Progress:
    """Create a simple spinner for indeterminate operations.

    Returns:
        Progress instance with just spinner and description
    """
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    )
