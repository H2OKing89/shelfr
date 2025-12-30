"""Input validation utilities for CLI and API arguments.

This module provides validation functions for common input types like ASINs.
These validators can be used with argparse's `type=` parameter for immediate
validation at parse time, providing clear error messages to users.
"""

from __future__ import annotations

import argparse
import re

# Audible ASIN pattern: 'B' followed by 9 alphanumeric chars
# Examples: B0DK9T5P28, B017V4IM1G
ASIN_PATTERN = re.compile(r"^B[0-9A-Z]{9}$")


def validate_asin(value: str) -> str:
    """Validate Audible ASIN format for argparse.

    Audible ASINs are 10 characters: 'B' followed by 9 alphanumeric chars.
    Examples: B0DK9T5P28, B017V4IM1G

    Args:
        value: The ASIN string to validate.

    Returns:
        The validated ASIN (uppercase, trimmed).

    Raises:
        argparse.ArgumentTypeError: If ASIN format is invalid.
    """
    value = value.upper().strip()
    if not ASIN_PATTERN.match(value):
        raise argparse.ArgumentTypeError(
            f"Invalid ASIN format: '{value}'. "
            "ASINs are 10 characters starting with 'B' (e.g., B0DK9T5P28)"
        )
    return value


def validate_asin_list(value: str) -> str:
    """Validate ASIN for use in nargs='+' arguments.

    This is a convenience alias that ensures consistent validation
    when ASINs are collected as a list (nargs='+').
    """
    return validate_asin(value)


def is_valid_asin(value: str) -> bool:
    """Check if a string is a valid ASIN format without raising.

    This is useful for code paths that want to check validity
    without using argparse error handling.

    Args:
        value: The string to check.

    Returns:
        True if the string matches ASIN format, False otherwise.
    """
    if not value:
        return False
    return bool(ASIN_PATTERN.match(value.upper().strip()))
