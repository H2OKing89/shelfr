"""Shared pytest fixtures and helpers for shelfr tests."""

from __future__ import annotations

from shelfr.utils.cmd import CmdResult


def make_cmd_result(
    stdout: str = "",
    stderr: str = "",
    exit_code: int = 0,
    argv: tuple[str, ...] = ("docker",),
) -> CmdResult:
    """Create a CmdResult for mocking run()/docker() calls in tests.

    Args:
        stdout: Command stdout output.
        stderr: Command stderr output.
        exit_code: Command exit code.
        argv: Command arguments tuple.

    Returns:
        CmdResult with the specified values.
    """
    return CmdResult(argv=argv, stdout=stdout, stderr=stderr, exit_code=exit_code)
