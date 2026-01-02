"""
Helper utilities for OPF generation.

Centralizes common operations like config loading and name cleaning.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shelfr.config import NamingConfig

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_naming_config() -> NamingConfig | None:
    """
    Get naming config for OPF generation.

    Uses LRU cache to avoid repeated file reads. Config is loaded
    directly from naming.json to avoid global settings cache issues
    that can cause test pollution.

    Returns:
        NamingConfig if found, None otherwise
    """
    from shelfr.config import _load_naming_config

    try:
        # Try common config locations
        for config_dir in [Path.cwd(), Path(__file__).parent.parent.parent.parent]:
            if (config_dir / "config" / "naming.json").exists():
                return _load_naming_config(config_dir)
    except (OSError, ValueError, KeyError) as e:
        logger.debug("Failed to load naming config: %s", e)
    return None


def clear_naming_config_cache() -> None:
    """Clear the naming config cache. Useful for testing."""
    get_naming_config.cache_clear()


def clean_role_from_name(name: str, role: str) -> str:
    """
    Remove role suffix from a person's name.

    Args:
        name: Full name with possible role suffix (e.g., "John Smith - translator")
        role: Role to remove (e.g., "translator")

    Returns:
        Cleaned name without role suffix
    """
    pattern = rf"\s*-?\s*{re.escape(role)}s?\s*$"
    return re.sub(pattern, "", name, flags=re.IGNORECASE).strip()


def detect_role_from_name(name: str) -> tuple[str, str]:
    """
    Detect MARC role from name suffix.

    Args:
        name: Person name that may contain role suffix

    Returns:
        Tuple of (clean_name, marc_role)
    """
    name_lower = name.lower()

    role_map = {
        "translator": "trl",
        "illustrator": "ill",
        "editor": "edt",
        "adapter": "adp",
        "contributor": "ctb",
        "compiler": "com",
    }

    for role_name, marc_code in role_map.items():
        if role_name in name_lower:
            return clean_role_from_name(name, role_name), marc_code

    return name, "ctb"  # Default to contributor


def name_to_file_as(name: str) -> str | None:
    """
    Convert author name to "Last, First" filing format.

    Simple heuristic: assumes last word is surname.
    Returns None for single-word names or names with special patterns.

    Args:
        name: Author name (e.g., "Brandon Sanderson")

    Returns:
        Filing format (e.g., "Sanderson, Brandon") or None

    Examples:
        >>> name_to_file_as("Brandon Sanderson")
        'Sanderson, Brandon'
        >>> name_to_file_as("Shirtaloon")
        None
    """
    parts = name.strip().split()

    # Skip single-word names or names with special characters
    if len(parts) < 2:
        return None

    # Skip names that already have "Last, First" format
    if "," in name:
        return None

    # Simple heuristic: last word is surname
    surname = parts[-1]
    given = " ".join(parts[:-1])

    return f"{surname}, {given}"
