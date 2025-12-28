"""
Libation Docker wrapper for running audiobook scans and status checks.

Libation has a two-stage model:
1. `scan` - Indexes NEW books from Audible into DB (BookStatus=NotLiberated)
2. `liberate` - Downloads ALL books with BookStatus=NotLiberated

Key insight: scan and liberate are INDEPENDENT operations.
- "New: 0" from scan does NOT mean nothing to download
- There may be NotLiberated books from previous scans waiting

This module provides:
- run_scan() - Index new books from Audible
- get_libation_status() - Check how many books need liberation
- run_liberate() - Download NotLiberated books
- run_liberate_with_progress() - Download with Rich spinner or TTY passthrough
"""

from __future__ import annotations

import contextlib
import json
import logging
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mamfast.config import get_settings
from mamfast.exceptions import LibationError
from mamfast.paths import log_dir
from mamfast.utils.cmd import CmdError, docker, run

if TYPE_CHECKING:
    from rich.console import Console

logger = logging.getLogger(__name__)


@dataclass
class LibationResult:
    """Result of a Libation command (scan, liberate, etc.)."""

    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def success(self) -> bool:
        return self.returncode == 0


# Backwards compatibility alias
ScanResult = LibationResult


@dataclass
class LibationStatus:
    """
    Status of books in Libation's database.

    BookStatus values in Libation:
    - Liberated: Downloaded and decrypted
    - NotLiberated: Indexed but not yet downloaded (pending)
    - Error: Failed to download
    """

    total: int
    liberated: int
    not_liberated: int
    error: int = 0
    other_statuses: dict[str, int] = field(default_factory=dict)

    @property
    def has_pending(self) -> bool:
        """True if there are books waiting to be downloaded."""
        return self.not_liberated > 0


def get_libation_status() -> LibationStatus:
    """
    Get current book status distribution from Libation.

    Runs `libationcli export` to JSON and parses BookStatus counts.
    This tells us how many books are:
    - Liberated: Already downloaded
    - NotLiberated: Waiting to be downloaded (pending)
    - Error: Failed downloads

    Returns:
        LibationStatus with counts for each status.

    Raises:
        RuntimeError: If export fails or JSON parsing fails.

    Example:
        >>> status = get_libation_status()
        >>> print(f"Pending: {status.not_liberated}")
        Pending: 20
        >>> if status.has_pending:
        ...     run_liberate()
    """
    settings = get_settings()

    # Use a temp file inside the container for the export
    container_export_path = "/tmp/mamfast_libation_export.json"

    logger.debug(f"Running Libation export to {container_export_path}")

    try:
        # Step 1: Run export command
        docker(
            "exec",
            settings.libation_container,
            "/libation/LibationCli",
            "export",
            "-p",
            container_export_path,
            "-j",  # JSON format
        )

        # Step 2: Read the exported JSON from container
        read_result = docker(
            "exec",
            settings.libation_container,
            "cat",
            container_export_path,
        )

        # Step 3: Parse JSON and count statuses
        parsed = json.loads(read_result.stdout)
        if not isinstance(parsed, list):
            raise LibationError(
                f"Expected list from export, got {type(parsed).__name__}",
                return_code=1,
            )
        books: list[dict[str, Any]] = parsed

        # Count BookStatus values
        status_counts: Counter[str] = Counter()
        for book in books:
            status: str = book.get("BookStatus", "Unknown")
            status_counts[status] += 1

        # Extract known statuses
        liberated = status_counts.pop("Liberated", 0)
        not_liberated = status_counts.pop("NotLiberated", 0)
        error_count = status_counts.pop("Error", 0)

        # Anything else goes to other_statuses
        other = dict(status_counts) if status_counts else {}

        result = LibationStatus(
            total=len(books),
            liberated=liberated,
            not_liberated=not_liberated,
            error=error_count,
            other_statuses=other,
        )

        logger.info(
            f"Libation status: {result.total} total, "
            f"{result.liberated} liberated, "
            f"{result.not_liberated} pending"
        )

        return result

    except json.JSONDecodeError as e:
        raise LibationError(
            f"Failed to parse Libation export JSON: {e}",
            return_code=1,
        ) from e

    except CmdError as e:
        raise LibationError(
            f"Docker command failed: {e}",
            return_code=e.exit_code,
        ) from e

    except Exception as e:
        if isinstance(e, LibationError):
            raise
        raise LibationError(
            f"Error getting Libation status: {e}",
            return_code=1,
        ) from e

    finally:
        # Cleanup: remove temp file from container (best effort)
        with contextlib.suppress(CmdError):
            docker("exec", settings.libation_container, "rm", "-f", container_export_path)


def run_scan(interactive: bool = False) -> LibationResult:
    """
    Run libationcli scan inside the Libation Docker container.

    Args:
        interactive: If True, use -it flags for interactive output.

    Returns:
        LibationResult with return code and output.
    """
    settings = get_settings()

    logger.info(f"Running Libation scan in container: {settings.libation_container}")

    try:
        # Build docker exec arguments
        docker_args = ["docker", "exec"]
        if interactive:
            docker_args.append("-i")  # Interactive mode
        docker_args.extend(
            [
                settings.libation_container,
                "/libation/LibationCli",
                "scan",
            ]
        )

        # Execute docker with TTY allocation if interactive
        result = run(
            docker_args,
            ok_codes=(0, 1),  # Allow non-zero for partial success
            _tty=interactive,  # Allocate TTY for interactive mode
        )
        return LibationResult(
            returncode=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    except CmdError as e:
        logger.error(f"Libation scan failed: {e}")
        return LibationResult(returncode=e.exit_code, stderr=e.stderr)

    except Exception as e:
        logger.exception(f"Error running Libation scan: {e}")
        return LibationResult(returncode=-1, stderr=str(e))


def run_liberate(asin: str | None = None) -> LibationResult:
    """
    Run liberate command to download and decrypt books.

    Args:
        asin: Optional specific ASIN to liberate. If None, liberates all.

    Returns:
        LibationResult with return code and output.
    """
    settings = get_settings()

    logger.info(f"Running Libation liberate{f' for {asin}' if asin else ''}...")

    try:
        args = ["exec", settings.libation_container, "/libation/LibationCli", "liberate"]
        if asin:
            args.append(asin)

        result = docker(*args, ok_codes=(0, 1))  # Allow non-zero for partial success
        return LibationResult(
            returncode=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    except CmdError as e:
        logger.error(f"Libation liberate failed: {e}")
        return LibationResult(returncode=e.exit_code, stderr=e.stderr)

    except Exception as e:
        logger.exception(f"Error running Libation liberate: {e}")
        return LibationResult(returncode=-1, stderr=str(e))


def check_container_running() -> bool:
    """Check if the Libation container is running.

    Returns:
        True if the container is running, False otherwise.

    Note:
        Failures are logged at debug level to help diagnose issues
        without cluttering normal output.
    """
    settings = get_settings()
    container_name = settings.libation_container

    try:
        result = docker(
            "container",
            "inspect",
            "-f",
            "{{.State.Running}}",
            container_name,
        )
        is_running = result.stdout.strip().lower() == "true"
        if not is_running:
            logger.debug(f"Container '{container_name}' exists but is not running")
        return is_running

    except CmdError as e:
        logger.debug(
            f"Container check failed for '{container_name}': "
            f"exit_code={e.exit_code}, stderr={e.stderr[:100] if e.stderr else 'none'}"
        )
        return False
    except Exception as e:
        logger.debug(f"Unexpected error checking container '{container_name}': {e}")
        return False


@dataclass
class LiberateProgressResult:
    """Result of a liberate operation with progress tracking."""

    success: bool
    returncode: int
    downloaded_count: int = 0
    skipped_count: int = 0  # Books that failed/were skipped
    log_path: Path | None = None
    error_message: str = ""
    has_book_errors: bool = False  # True if individual books failed (even if exit 0)


def _is_tty() -> bool:
    """Check if we're running in a TTY (interactive terminal)."""
    return sys.stdout.isatty() and sys.stderr.isatty()


def _parse_libation_output(stdout: str, stderr: str) -> dict[str, Any]:
    """Parse Libation output for book processing results.

    Libation can return exit code 0 even when individual books fail.
    This function parses stdout/stderr to detect:
    - Successfully downloaded books
    - Skipped/errored books

    Returns:
        Dict with:
        - completed: List of completed book identifiers
        - errors: List of error messages
        - has_book_errors: True if any books failed
    """
    completed: list[str] = []
    errors: list[str] = []

    # Parse stdout for completed books
    # Format: "DownloadDecryptBook Completed: MM/DD/YYYY [ASIN] Title"
    for line in stdout.splitlines():
        if "Completed:" in line:
            # Extract book info
            completed.append(line.strip())

    # Parse stderr for error messages
    # Only extract individual error lines to avoid duplicates
    # (Don't append full stderr AND individual lines)
    if stderr:
        error_keywords = ["error", "failed", "skipping"]
        for line in stderr.splitlines():
            line_stripped = line.strip()
            has_error_keyword = any(kw in line_stripped.lower() for kw in error_keywords)
            if line_stripped and line_stripped not in errors and has_error_keyword:
                errors.append(line_stripped)

    return {
        "completed": completed,
        "errors": errors,
        "has_book_errors": len(errors) > 0,
    }


def run_liberate_with_progress(
    pending_count: int,
    console: Console,
    *,
    verbose: bool = False,
    asin: str | None = None,
) -> LiberateProgressResult:
    """Run liberate with smart progress display.

    In normal mode (default):
        - Shows a Rich spinner with elapsed time
        - Captures Libation output to a log file
        - Keeps console output clean and consistent

    In verbose mode (-v) with TTY:
        - Passes through Libation's native progress bar
        - Allocates TTY for docker exec so progress renders correctly

    Args:
        pending_count: Number of books to download (for display)
        console: Rich console instance
        verbose: If True and on TTY, passthrough Libation's progress bar
        asin: Optional specific ASIN to liberate

    Returns:
        LiberateProgressResult with success status and log path
    """
    settings = get_settings()
    is_tty = _is_tty()

    # Build docker command
    cmd = ["docker", "exec"]

    # Verbose + TTY = passthrough mode with TTY allocation
    passthrough_mode = verbose and is_tty
    if passthrough_mode:
        cmd.append("-t")  # Allocate TTY for Libation's progress bar

    cmd.extend([settings.libation_container, "/libation/LibationCli", "liberate"])
    if asin:
        cmd.append(asin)

    # -------------------------------------------
    # Passthrough mode: Let Libation draw its own progress
    # -------------------------------------------
    if passthrough_mode:
        console.print(
            f"  → Downloading {pending_count} pending audiobook(s)... (Libation progress)"
        )
        try:
            # Run with inherited stdio so Libation's progress bar shows
            # 1 hour timeout to prevent indefinite hangs
            proc = subprocess.run(cmd, check=False, text=True, timeout=3600)
            return LiberateProgressResult(
                success=proc.returncode == 0,
                returncode=proc.returncode,
            )
        except subprocess.TimeoutExpired:
            return LiberateProgressResult(
                success=False,
                returncode=-1,
                error_message="Libation timed out after 1 hour",
            )
        except Exception as e:
            return LiberateProgressResult(
                success=False,
                returncode=-1,
                error_message=str(e),
            )

    # -------------------------------------------
    # Spinner mode: Clean output with background capture
    # -------------------------------------------
    # Prepare log file
    libation_log_dir = log_dir() / "libation"
    libation_log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = libation_log_dir / f"liberate_{timestamp}.log"

    try:
        with console.status(
            f"  → Downloading {pending_count} pending audiobook(s)...",
            spinner="dots",
        ):
            # 1 hour timeout to prevent indefinite hangs
            proc = subprocess.run(
                cmd,
                text=True,
                capture_output=True,
                check=False,
                timeout=3600,
            )

        # Write log file (always, for debugging)
        log_content = f"Command: {' '.join(cmd)}\n"
        log_content += f"Exit code: {proc.returncode}\n"
        log_content += f"Timestamp: {datetime.now().isoformat()}\n"
        log_content += "\n--- STDOUT ---\n"
        log_content += proc.stdout or "(empty)"
        log_content += "\n\n--- STDERR ---\n"
        log_content += proc.stderr or "(empty)"
        log_path.write_text(log_content)

        # Parse output for book-level errors (Libation returns exit 0 even when books fail)
        parsed = _parse_libation_output(proc.stdout or "", proc.stderr or "")

        if proc.returncode != 0:
            # Extract tail of stderr for error message
            stderr_lines = (proc.stderr or "").strip().splitlines()
            tail = "\n".join(stderr_lines[-10:]) if stderr_lines else "(no output)"
            return LiberateProgressResult(
                success=False,
                returncode=proc.returncode,
                log_path=log_path,
                error_message=f"Last output:\n{tail}",
                has_book_errors=True,
            )

        # Exit code was 0, but check if any individual books failed
        if parsed["has_book_errors"]:
            error_summary = "\n".join(parsed["errors"][:3])  # First 3 errors
            return LiberateProgressResult(
                success=True,  # Command succeeded overall
                returncode=proc.returncode,
                downloaded_count=len(parsed["completed"]),
                skipped_count=len(parsed["errors"]),
                log_path=log_path,
                error_message=error_summary,
                has_book_errors=True,
            )

        return LiberateProgressResult(
            success=True,
            returncode=proc.returncode,
            downloaded_count=len(parsed["completed"]),
            log_path=log_path,
        )

    except subprocess.TimeoutExpired:
        logger.error("Libation timed out after 1 hour")
        return LiberateProgressResult(
            success=False,
            returncode=-1,
            error_message="Libation timed out after 1 hour",
        )
    except Exception as e:
        logger.exception("Error running liberate with progress")
        return LiberateProgressResult(
            success=False,
            returncode=-1,
            error_message=str(e),
        )
