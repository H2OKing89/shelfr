"""Cross-platform path handling using platformdirs.

Provides XDG-compliant paths with environment variable overrides for flexibility.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal

from platformdirs import user_cache_dir, user_data_dir, user_log_dir

logger = logging.getLogger(__name__)

APP_NAME = "shelfr"
APPAUTHOR: Literal[False] = False  # Avoid "CompanyName/AppName" nesting on Windows


def _env_override(env_var: str) -> Path | None:
    """Check for environment variable override.

    Args:
        env_var: Environment variable name to check

    Returns:
        Path from environment variable if set, None otherwise
    """
    v = os.environ.get(env_var)
    return Path(v).expanduser() if v else None


def data_dir(*, ensure: bool = True) -> Path:
    """Get application data directory.

    Linux: ~/.local/share/shelfr
    macOS: ~/Library/Application Support/shelfr
    Windows: C:\\Users\\<user>\\AppData\\Local\\shelfr

    Override with SHELFR_DATA_DIR env var (MAMFAST_DATA_DIR also supported).

    Args:
        ensure: Create directory if it doesn't exist

    Returns:
        Path to data directory
    """
    d = (
        _env_override("SHELFR_DATA_DIR")
        or _env_override("MAMFAST_DATA_DIR")
        or Path(user_data_dir(APP_NAME, APPAUTHOR))
    )
    if ensure:
        d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir(*, ensure: bool = True) -> Path:
    """Get application cache directory.

    Linux: ~/.cache/shelfr
    macOS: ~/Library/Caches/shelfr
    Windows: C:\\Users\\<user>\\AppData\\Local\\shelfr\\Cache

    Override with SHELFR_CACHE_DIR env var (MAMFAST_CACHE_DIR also supported).

    Args:
        ensure: Create directory if it doesn't exist

    Returns:
        Path to cache directory
    """
    d = (
        _env_override("SHELFR_CACHE_DIR")
        or _env_override("MAMFAST_CACHE_DIR")
        or Path(user_cache_dir(APP_NAME, APPAUTHOR))
    )
    if ensure:
        d.mkdir(parents=True, exist_ok=True)
    return d


def log_dir(*, ensure: bool = True) -> Path:
    """Get application log directory.

    Linux: ~/.local/state/shelfr/log
    macOS: ~/Library/Logs/shelfr
    Windows: C:\\Users\\<user>\\AppData\\Local\\shelfr\\Logs

    Override with SHELFR_LOG_DIR env var (MAMFAST_LOG_DIR also supported).

    Args:
        ensure: Create directory if it doesn't exist

    Returns:
        Path to log directory
    """
    d = (
        _env_override("SHELFR_LOG_DIR")
        or _env_override("MAMFAST_LOG_DIR")
        or Path(user_log_dir(APP_NAME, APPAUTHOR))
    )
    if ensure:
        d.mkdir(parents=True, exist_ok=True)
    return d


def config_dir() -> Path:
    """Get the project config directory.

    Returns config/ directory relative to package location.
    This is where user-specific files like config.yaml and templates go.

    Override with SHELFR_CONFIG_DIR env var (MAMFAST_CONFIG_DIR also supported).

    Returns:
        Path to config directory (does NOT auto-create)
    """
    # Support both old and new env var names
    override = _env_override("SHELFR_CONFIG_DIR") or _env_override("MAMFAST_CONFIG_DIR")
    if override:
        return override

    # Default: assume we're in src/shelfr/, go up to project root
    # This works for both installed packages and development
    package_dir = Path(__file__).parent
    project_root = package_dir.parent.parent  # src/shelfr -> src -> project_root
    return project_root / "config"
