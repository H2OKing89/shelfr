"""Simple message printing helpers for MAMFast UI.

These are the most commonly used output functions for quick status messages.
"""

from __future__ import annotations

from shelfr.ui.core import console, err_console


def print_step(step_num: int, total_steps: int, title: str) -> None:
    """Print a step header.

    Example:
        >>> print_step(1, 5, "Scanning library")
        Step 1/5: Scanning library
    """
    console.print(f"[step]Step {step_num}/{total_steps}:[/] {title}")


def print_substep(message: str, style: str = "dim") -> None:
    """Print an indented substep message.

    Example:
        >>> print_substep("Processing file.m4b")
          • Processing file.m4b
    """
    console.print(f"  [{style}]•[/] {message}")


def print_success(message: str) -> None:
    """Print a success message with checkmark.

    Example:
        >>> print_success("Upload complete")
          ✓ Upload complete
    """
    console.print(f"  [success]✓[/] {message}")


def print_error(message: str) -> None:
    """Print an error message with X.

    Example:
        >>> print_error("Connection failed")
          ✗ Connection failed
    """
    console.print(f"  [error]✗[/] {message}")


def print_warning(message: str) -> None:
    """Print a warning message.

    Example:
        >>> print_warning("File already exists")
          ! File already exists
    """
    console.print(f"  [warning]![/] {message}")


def print_info(message: str) -> None:
    """Print an info message.

    Example:
        >>> print_info("Found 5 new releases")
          → Found 5 new releases
    """
    console.print(f"  [info]→[/] {message}")


def print_dry_run(message: str) -> None:
    """Print a dry-run message.

    Example:
        >>> print_dry_run("Would create torrent")
          [DRY RUN] Would create torrent
    """
    console.print(f"  [warning][DRY RUN][/] {message}")


def status(message: str, style: str = "info") -> None:
    """Print a simple status message.

    Example:
        >>> status("Connected to server")
        Connected to server
    """
    console.print(f"[{style}]{message}[/]")


def confirm(message: str, default: bool = False) -> bool:
    """Ask for user confirmation.

    Args:
        message: The question to ask
        default: Default answer if user presses Enter

    Returns:
        True if user confirmed, False otherwise

    Example:
        >>> if confirm("Delete files?"):
        ...     delete_files()
    """
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
    """Print a fatal error and exit hint.

    Args:
        message: The error message
        hint: Optional hint for resolution

    Example:
        >>> fatal_error("Config not found", "Run 'mamfast check' for diagnostics")
    """
    err_console.print(f"\n[error]Error:[/] {message}")
    if hint:
        err_console.print(f"[dim]Hint: {hint}[/]")
