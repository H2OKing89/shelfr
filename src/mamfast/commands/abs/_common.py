"""Shared utilities for ABS command handlers.

This module contains helpers used across multiple ABS commands.
"""

from __future__ import annotations

import fnmatch
import logging
from typing import TYPE_CHECKING

from mamfast.console import (
    confirm,
    console,
    fatal_error,
    print_dry_run,
    print_error,
    print_header,
    print_info,
    print_step,
    print_success,
    print_warning,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def should_ignore(filename: str, ignore_patterns: list[str]) -> bool:
    """Check if filename matches any ignore pattern.

    Supports two types of patterns:
    - Glob patterns (containing '*'): matched using fnmatch
    - Extension patterns (starting with '.'): simple suffix matching

    Args:
        filename: The filename to check
        ignore_patterns: List of patterns to match against

    Returns:
        True if filename matches any pattern, False otherwise
    """
    if not ignore_patterns:
        return False

    filename_lower = filename.lower()
    for pattern in ignore_patterns:
        pattern_lower = pattern.lower()
        is_glob_match = "*" in pattern and fnmatch.fnmatch(filename_lower, pattern_lower)
        is_ext_match = pattern.startswith(".") and filename_lower.endswith(pattern_lower)
        if is_glob_match or is_ext_match:
            return True
    return False


__all__ = [
    # Console helpers (re-exported for convenience)
    "confirm",
    "console",
    "fatal_error",
    "print_dry_run",
    "print_error",
    "print_header",
    "print_info",
    "print_step",
    "print_success",
    "print_warning",
    # Local helpers
    "logger",
    "should_ignore",
]
