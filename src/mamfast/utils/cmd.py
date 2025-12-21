"""Command execution utilities using sh library.

Provides a cleaner interface for running external commands with better
error handling and output management than raw subprocess.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import sh
from sh import ErrorReturnCode

logger = logging.getLogger(__name__)


@dataclass
class CmdResult:
    """Result of a command execution."""

    argv: tuple[str, ...]
    stdout: str
    stderr: str
    exit_code: int

    @property
    def ok(self) -> bool:
        """True if command succeeded (exit code 0)."""
        return self.exit_code == 0


class CmdError(Exception):
    """Raised when a command fails."""

    def __init__(
        self,
        *,
        argv: Sequence[str],
        exit_code: int,
        stdout: str | bytes,
        stderr: str | bytes,
    ) -> None:
        self.argv = tuple(argv)
        self.exit_code = exit_code
        self.stdout = _to_text(stdout)
        self.stderr = _to_text(stderr)

        # Build helpful error message
        cmd_str = " ".join(argv)
        msg = f"Command failed with exit code {exit_code}: {cmd_str}"
        if self.stderr:
            msg += f"\nStderr: {self.stderr[:500]}"  # Truncate long errors
        super().__init__(msg)


def _to_text(data: str | bytes | Any) -> str:
    """Convert sh output to text string."""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    if isinstance(data, str):
        return data
    # sh command objects have stdout property
    if hasattr(data, "stdout"):
        return _to_text(data.stdout)
    return str(data)


def run(
    argv: Sequence[str],
    *,
    timeout: float | int | None = None,
    ok_codes: Iterable[int] = (0,),
    capture_output: bool = True,
    **kwargs: Any,
) -> CmdResult:
    """Run external command via sh with better error handling.

    Args:
        argv: Command and arguments as list (e.g., ["docker", "ps", "-a"])
        timeout: Optional timeout in seconds
        ok_codes: Exit codes considered successful (default: (0,))
        capture_output: If True, capture stdout/stderr (default: True)
        **kwargs: Additional arguments passed to sh.Command

    Returns:
        CmdResult with stdout, stderr, and exit code

    Raises:
        CmdError: If command fails (exit code not in ok_codes)

    Example:
        result = run(["docker", "ps", "-a"])
        print(result.stdout)

        # Allow multiple exit codes
        result = run(["grep", "pattern", "file.txt"], ok_codes=(0, 1))
    """
    if not argv:
        raise ValueError("argv cannot be empty")

    cmd_name = argv[0]
    cmd_args = argv[1:]

    # Prepare sh kwargs
    sh_kwargs: dict[str, Any] = {
        "_ok_code": list(ok_codes),
        **kwargs,
    }

    if timeout is not None:
        sh_kwargs["_timeout"] = timeout

    if capture_output:
        sh_kwargs["_return_cmd"] = True

    try:
        # Get the sh Command object
        cmd = sh.Command(cmd_name)

        # Execute with args
        result = cmd(*cmd_args, **sh_kwargs)

        # Extract output
        stdout_text = _to_text(result) if result else ""
        stderr_text = _to_text(getattr(result, "stderr", ""))

        return CmdResult(
            argv=tuple(argv),
            stdout=stdout_text,
            stderr=stderr_text,
            exit_code=getattr(result, "exit_code", 0),
        )

    except ErrorReturnCode as e:
        # Command failed with non-ok exit code
        raise CmdError(
            argv=argv,
            exit_code=e.exit_code,
            stdout=e.stdout,
            stderr=e.stderr,
        ) from e
    except sh.TimeoutException as e:
        # Command timed out
        raise CmdError(
            argv=argv,
            exit_code=-1,
            stdout=b"",
            stderr=f"Command timed out after {timeout}s".encode(),
        ) from e
    except Exception as e:
        # Other errors (command not found, etc.)
        raise CmdError(
            argv=argv,
            exit_code=-1,
            stdout=b"",
            stderr=str(e).encode(),
        ) from e


def run_quiet(
    argv: Sequence[str],
    *,
    timeout: float | int | None = None,
    ok_codes: Iterable[int] = (0,),
) -> bool:
    """Run command and return True if successful, False otherwise.

    Like run() but doesn't raise exceptions - useful for existence checks.

    Args:
        argv: Command and arguments
        timeout: Optional timeout in seconds
        ok_codes: Exit codes considered successful

    Returns:
        True if command succeeded, False otherwise

    Example:
        if run_quiet(["which", "docker"]):
            print("Docker is installed")
    """
    try:
        run(argv, timeout=timeout, ok_codes=ok_codes)
        return True
    except CmdError:
        return False


def docker(
    *args: str,
    timeout: float | int | None = None,
    ok_codes: Iterable[int] = (0,),
) -> CmdResult:
    """Run docker command with better error handling.

    Convenience wrapper around run() for docker commands.

    Args:
        *args: Docker command arguments
        timeout: Optional timeout in seconds
        ok_codes: Exit codes considered successful

    Returns:
        CmdResult with output

    Example:
        result = docker("ps", "-a")
        result = docker("exec", container_name, "ls", "-la")
    """
    return run(["docker", *args], timeout=timeout, ok_codes=ok_codes)
