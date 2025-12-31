"""Textual TUI for shelfr.

This package provides a full-screen terminal user interface for editing
configuration files, previewing content, and managing shelfr settings.

Requires optional dependency: pip install shelfr[tui]
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def check_available() -> bool:
    """Check if Textual TUI is available."""
    try:
        import textual  # noqa: F401

        return True
    except ImportError:
        return False


class TUINotAvailableError(ImportError):
    """Raised when TUI dependencies are not installed."""

    def __init__(self) -> None:
        super().__init__("Textual TUI not available. Install with: pip install shelfr[tui]")


__all__ = [
    "check_available",
    "TUINotAvailableError",
]
