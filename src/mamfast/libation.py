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
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field

from mamfast.config import get_settings
from mamfast.utils.cmd import CmdError, docker

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """Result of a Libation scan."""

    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def success(self) -> bool:
        return self.returncode == 0


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
        books = json.loads(read_result.stdout)

        if not isinstance(books, list):
            raise RuntimeError(f"Expected list from export, got {type(books).__name__}")

        # Count BookStatus values
        status_counts: Counter[str] = Counter()
        for book in books:
            status = book.get("BookStatus", "Unknown")
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
        raise RuntimeError(f"Failed to parse Libation export JSON: {e}") from e

    except CmdError as e:
        raise RuntimeError(f"Docker command failed: {e}") from e

    except Exception as e:
        if isinstance(e, RuntimeError):
            raise
        raise RuntimeError(f"Error getting Libation status: {e}") from e

    finally:
        # Cleanup: remove temp file from container (best effort)
        try:
            docker("exec", settings.libation_container, "rm", "-f", container_export_path)
        except CmdError:
            pass  # Cleanup failure is not critical


def run_scan(interactive: bool = False) -> ScanResult:
    """
    Run libationcli scan inside the Libation Docker container.

    Args:
        interactive: If True, use -it flags for interactive output.

    Returns:
        ScanResult with return code and output.
    """
    settings = get_settings()

    logger.info(f"Running Libation scan in container: {settings.libation_container}")

    try:
        if interactive:
            # Interactive mode - use docker -it
            result = docker(
                "exec",
                "-it",
                settings.libation_container,
                "/libation/LibationCli",
                "scan",
                ok_codes=(0, 1),  # Allow non-zero for partial success
            )
            return ScanResult(
                returncode=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        else:
            # Non-interactive - capture output
            result = docker(
                "exec",
                settings.libation_container,
                "/libation/LibationCli",
                "scan",
                ok_codes=(0, 1),  # Allow non-zero for partial success
            )
            return ScanResult(
                returncode=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
            )

    except CmdError as e:
        logger.error(f"Libation scan failed: {e}")
        return ScanResult(returncode=e.exit_code, stderr=e.stderr)

    except Exception as e:
        logger.exception(f"Error running Libation scan: {e}")
        return ScanResult(returncode=-1, stderr=str(e))


def run_liberate(asin: str | None = None) -> ScanResult:
    """
    Run liberate command to download and decrypt books.

    Args:
        asin: Optional specific ASIN to liberate. If None, liberates all.

    Returns:
        ScanResult with return code and output.
    """
    settings = get_settings()

    logger.info(f"Running Libation liberate{f' for {asin}' if asin else ''}...")

    try:
        args = ["exec", settings.libation_container, "/libation/LibationCli", "liberate"]
        if asin:
            args.append(asin)

        result = docker(*args, ok_codes=(0, 1))  # Allow non-zero for partial success
        return ScanResult(
            returncode=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    except CmdError as e:
        logger.error(f"Libation liberate failed: {e}")
        return ScanResult(returncode=e.exit_code, stderr=e.stderr)

    except Exception as e:
        logger.exception(f"Error running Libation liberate: {e}")
        return ScanResult(returncode=-1, stderr=str(e))


def check_container_running() -> bool:
    """Check if the Libation container is running."""
    settings = get_settings()

    try:
        result = docker(
            "container",
            "inspect",
            "-f",
            "{{.State.Running}}",
            settings.libation_container,
        )
        return result.stdout.strip().lower() == "true"

    except CmdError:
        return False
    except Exception:
        return False
