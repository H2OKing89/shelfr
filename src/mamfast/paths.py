"""Cross-platform path handling using platformdirs.

Provides XDG-compliant paths with environment variable overrides for flexibility.
"""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_cache_dir, user_data_dir, user_log_dir

APP_NAME = "mamfast"
APPAUTHOR = False  # Avoid "CompanyName/AppName" nesting on Windows


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

    Linux: ~/.local/share/mamfast
    macOS: ~/Library/Application Support/mamfast
    Windows: C:\\Users\\<user>\\AppData\\Local\\mamfast

    Override with MAMFAST_DATA_DIR env var.

    Args:
        ensure: Create directory if it doesn't exist

    Returns:
        Path to data directory
    """
    d = _env_override("MAMFAST_DATA_DIR") or Path(user_data_dir(APP_NAME, APPAUTHOR))
    if ensure:
        d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir(*, ensure: bool = True) -> Path:
    """Get application cache directory.

    Linux: ~/.cache/mamfast
    macOS: ~/Library/Caches/mamfast
    Windows: C:\\Users\\<user>\\AppData\\Local\\mamfast\\Cache

    Override with MAMFAST_CACHE_DIR env var.

    Args:
        ensure: Create directory if it doesn't exist

    Returns:
        Path to cache directory
    """
    d = _env_override("MAMFAST_CACHE_DIR") or Path(user_cache_dir(APP_NAME, APPAUTHOR))
    if ensure:
        d.mkdir(parents=True, exist_ok=True)
    return d


def log_dir(*, ensure: bool = True) -> Path:
    """Get application log directory.

    Linux: ~/.local/state/mamfast (or ~/.cache/mamfast if not available)
    macOS: ~/Library/Logs/mamfast
    Windows: C:\\Users\\<user>\\AppData\\Local\\mamfast\\Logs

    Override with MAMFAST_LOG_DIR env var.

    Args:
        ensure: Create directory if it doesn't exist

    Returns:
        Path to log directory
    """
    d = _env_override("MAMFAST_LOG_DIR") or Path(user_log_dir(APP_NAME, APPAUTHOR))
    if ensure:
        d.mkdir(parents=True, exist_ok=True)
    return d
