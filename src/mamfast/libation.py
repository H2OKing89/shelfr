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
import subprocess
from collections import Counter
from dataclasses import dataclass, field

from mamfast.config import get_settings

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

    # Step 1: Run export command
    export_cmd = [
        settings.docker_bin,
        "exec",
        settings.libation_container,
        "/libation/LibationCli",
        "export",
        "-p",
        container_export_path,
        "-j",  # JSON format
    ]

    logger.debug(f"Running Libation export: {' '.join(export_cmd)}")

    try:
        export_result = subprocess.run(
            export_cmd,
            capture_output=True,
            text=True,
            check=False,
        )

        if export_result.returncode != 0:
            raise RuntimeError(
                f"Libation export failed (code {export_result.returncode}): "
                f"{export_result.stderr or export_result.stdout}"
            )

        # Step 2: Read the exported JSON from container
        read_cmd = [
            settings.docker_bin,
            "exec",
            settings.libation_container,
            "cat",
            container_export_path,
        ]

        read_result = subprocess.run(
            read_cmd,
            capture_output=True,
            text=True,
            check=False,
        )

        if read_result.returncode != 0:
            raise RuntimeError(
                f"Failed to read export file: {read_result.stderr}"
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

    except FileNotFoundError as e:
        raise RuntimeError(f"Docker binary not found: {settings.docker_bin}") from e

    except Exception as e:
        if isinstance(e, RuntimeError):
            raise
        raise RuntimeError(f"Error getting Libation status: {e}") from e

    finally:
        # Cleanup: remove temp file from container (best effort)
        cleanup_cmd = [
            settings.docker_bin,
            "exec",
            settings.libation_container,
            "rm",
            "-f",
            container_export_path,
        ]
        subprocess.run(cleanup_cmd, capture_output=True, check=False)


def run_scan(interactive: bool = False) -> ScanResult:
    """
    Run libationcli scan inside the Libation Docker container.

    Args:
        interactive: If True, use -it flags for interactive output.

    Returns:
        ScanResult with return code and output.
    """
    settings = get_settings()

    cmd = [
        settings.docker_bin,
        "exec",
    ]

    if interactive:
        cmd.extend(["-it"])

    cmd.extend(
        [
            settings.libation_container,
            "/libation/LibationCli",  # Full path, proper case
            "scan",
        ]
    )

    logger.info(f"Running Libation scan in container: {settings.libation_container}")
    logger.debug(f"Command: {' '.join(cmd)}")

    try:
        if interactive:
            # Interactive mode - don't capture output
            result = subprocess.run(cmd, check=False, text=True)
            return ScanResult(
                returncode=result.returncode,
            )
        else:
            # Non-interactive - capture output
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
            return ScanResult(
                returncode=result.returncode,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
            )

    except FileNotFoundError:
        logger.error(f"Docker binary not found: {settings.docker_bin}")
        return ScanResult(returncode=-1, stderr="Docker binary not found")

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

    cmd = [
        settings.docker_bin,
        "exec",
        settings.libation_container,
        "/libation/LibationCli",
        "liberate",
    ]

    if asin:
        cmd.append(asin)

    logger.info("Running Libation liberate...")
    logger.debug(f"Command: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        return ScanResult(
            returncode=result.returncode,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
        )

    except Exception as e:
        logger.exception(f"Error running Libation liberate: {e}")
        return ScanResult(returncode=-1, stderr=str(e))


def check_container_running() -> bool:
    """Check if the Libation container is running."""
    settings = get_settings()

    cmd = [
        settings.docker_bin,
        "container",
        "inspect",
        "-f",
        "{{.State.Running}}",
        settings.libation_container,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0 and result.stdout.strip().lower() == "true"

    except Exception:
        return False
