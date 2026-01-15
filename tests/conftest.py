"""Shared pytest fixtures and helpers for shelfr tests."""

from __future__ import annotations

import logging

import pytest

from shelfr.utils.cmd import CmdResult


@pytest.fixture(autouse=True)
def _disable_file_logging(monkeypatch):
    """Prevent tests from writing to the production log file.

    This fixture runs automatically for ALL tests and:
    1. Removes any existing FileHandler from the shelfr logger
    2. Patches setup_logging to never create a FileHandler

    This prevents test output from polluting the production logs/shelfr.log file.
    """
    logger = logging.getLogger("shelfr")

    # Remove all file handlers before the test
    file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
    for handler in file_handlers:
        logger.removeHandler(handler)
        handler.close()

    # Patch setup_logging to always pass log_file=None
    original_setup_logging = None
    try:
        from shelfr import logging_setup

        original_setup_logging = logging_setup.setup_logging

        def patched_setup_logging(
            log_level: str = "INFO",
            log_file=None,  # Ignore any log_file argument
            rich_console: bool = True,
            quiet_console: bool = False,
        ):
            # Always call with log_file=None to prevent file handler creation
            return original_setup_logging(
                log_level=log_level,
                log_file=None,  # Force no file logging
                rich_console=rich_console,
                quiet_console=quiet_console,
            )

        monkeypatch.setattr(logging_setup, "setup_logging", patched_setup_logging)

        # Also patch the CLI's _setup_logging import
        try:
            from shelfr.cli import _app

            monkeypatch.setattr(_app, "_setup_logging", patched_setup_logging)
        except (ImportError, AttributeError):
            pass

    except ImportError:
        pass

    yield

    # Clean up any file handlers that were added during the test
    file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
    for handler in file_handlers:
        logger.removeHandler(handler)
        handler.close()


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
