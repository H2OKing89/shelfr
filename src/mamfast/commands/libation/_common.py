"""Shared utilities for Libation commands.

This module contains helpers used across multiple Libation commands.
"""

from __future__ import annotations

import contextlib
import json
import logging
from dataclasses import dataclass
from typing import Any

from mamfast.console import console
from mamfast.exceptions import LibationError
from mamfast.utils.cmd import CmdError, docker

logger = logging.getLogger(__name__)


@dataclass
class LibationCommandResult:
    """Result from running a Libation command."""

    success: bool
    returncode: int
    stdout: str = ""
    stderr: str = ""
    parsed_data: Any = None
    error_message: str = ""


def run_libation_cmd(
    container: str,
    *args: str,
    timeout: int = 300,
    ok_codes: tuple[int, ...] = (0,),
) -> LibationCommandResult:
    """Run a LibationCli command in the container."""
    try:
        result = docker(
            "exec",
            container,
            "/libation/LibationCli",
            *args,
            timeout=timeout,
            ok_codes=ok_codes,
        )

        # If we get here, exit code was in ok_codes
        return LibationCommandResult(
            success=True,
            returncode=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    except CmdError as e:
        # docker() raises CmdError when exit code not in ok_codes or on timeout
        return LibationCommandResult(
            success=False,
            returncode=e.exit_code,
            stdout=e.stdout,
            stderr=e.stderr,
            error_message=str(e) if not e.timed_out else f"Command timed out after {timeout}s",
        )
    except Exception as e:
        # Catch any other unexpected errors
        return LibationCommandResult(
            success=False,
            returncode=-1,
            error_message=str(e),
        )


def export_library(container: str) -> list[dict[str, Any]]:
    """Export library data from Libation as JSON."""
    import os

    export_path = f"/tmp/mamfast_export_{os.getpid()}.json"

    # Run export command
    result = run_libation_cmd(container, "export", "-p", export_path, "-j")
    if not result.success:
        raise LibationError(
            f"Export failed: {result.error_message or result.stderr}",
            return_code=result.returncode,
        )

    # Read the exported JSON
    try:
        read_result = docker("exec", container, "cat", export_path, timeout=30)
        try:
            books = json.loads(read_result.stdout)
        except json.JSONDecodeError as e:
            raise LibationError(
                f"Invalid JSON in export from {container}: {e}",
                return_code=-1,
            ) from e
        return list(books) if isinstance(books, list) else []
    finally:
        # Cleanup
        with contextlib.suppress(CmdError):
            docker("exec", container, "rm", "-f", export_path, timeout=10)


def get_library_status(books: list[dict[str, Any]]) -> dict[str, int]:
    """Get status counts from library export."""
    status_counts: dict[str, int] = {}
    for book in books:
        status = book.get("BookStatus", "Unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    return status_counts


__all__ = [
    "LibationCommandResult",
    "console",
    "export_library",
    "get_library_status",
    "logger",
    "run_libation_cmd",
]
