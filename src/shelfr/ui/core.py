"""Core console configuration and theme for MAMFast UI.

This module provides the foundational Rich console instances and theme
that all other UI modules build upon.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console
from rich.theme import Theme

# =============================================================================
# Theme Configuration
# =============================================================================

MAMFAST_THEME = Theme(
    {
        # Status colors
        "info": "cyan",
        "success": "green",
        "warning": "yellow",
        "error": "red bold",
        # Text styles
        "step": "bold cyan",
        "title": "bold white",
        "dim": "dim",
        "highlight": "bold magenta",
        "accent": "bold blue",
        # Additional semantic styles
        "path": "cyan",
        "asin": "yellow",
        "author": "cyan",
        "series": "magenta",
        "duration": "green",
        "bitrate": "yellow",
        "command": "bold green",
        "option": "cyan",
        "hint": "dim italic",
    }
)

# =============================================================================
# Console Instances
# =============================================================================

# Primary console for normal output
console = Console(theme=MAMFAST_THEME, stderr=False)

# Error console for stderr output
err_console = Console(theme=MAMFAST_THEME, stderr=True)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class StepResult:
    """Result of a pipeline step."""

    success: bool
    message: str = ""
    details: list[str] | None = None
