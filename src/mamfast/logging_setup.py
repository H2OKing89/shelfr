"""Logging configuration for MAMFast."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler


def setup_logging(
    log_level: str = "INFO",
    log_file: Path | str | None = None,
    rich_console: bool = True,
) -> logging.Logger:
    """
    Configure logging for MAMFast.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional file path for log output
        rich_console: Use rich handler for pretty console output

    Returns:
        Root logger instance
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Root logger for mamfast
    logger = logging.getLogger("mamfast")
    logger.setLevel(level)
    logger.handlers.clear()

    # Format for file logging
    file_format = logging.Formatter(
        "%(asctime)s | %(levelname)-5s | [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler: logging.Handler
    if rich_console:
        console = Console(stderr=True)
        console_handler = RichHandler(
            console=console,
            show_time=True,
            show_path=False,
            rich_tracebacks=True,
            markup=True,
        )
        console_handler.setLevel(level)
    else:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(level)
        console_handler.setFormatter(
            logging.Formatter("%(levelname)s: %(message)s")
        )

    logger.addHandler(console_handler)

    # File handler (if specified)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # Always log DEBUG to file
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a child logger under the mamfast namespace."""
    return logging.getLogger(f"mamfast.{name}")
