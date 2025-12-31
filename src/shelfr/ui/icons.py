"""
Standardized icon system for CLI output.

This module provides consistent icons across the codebase, avoiding emoji
alignment issues in Rich tables/panels while maintaining visual polish.

Usage:
    from shelfr.ui.icons import icons

    # In output
    print_success(f"{icons.ok} Operation completed")
    print_error(f"{icons.fail} Operation failed")

    # In tables (use fixed-width tokens for alignment)
    table.add_row(icons.status_ok, "Item passed")
    table.add_row(icons.status_fail, "Item failed")

Icon modes:
    - unicode (default): Clean Unicode symbols (✓ ✗ • →)
    - ascii: Maximum compatibility ([OK] [X] * ->)
    - emoji: Colorful but alignment-unsafe (✅ ❌ 📦)

Note:
    Emoji mode should ONLY be used in non-aligned output (banners, plain text).
    For tables, panels, and progress bars, always use unicode or ascii mode.

    Icon mode is global per-process. Not thread-safe if used in multi-threaded
    contexts. For CLI usage (single-threaded), this is acceptable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

IconMode = Literal["unicode", "ascii", "emoji", "auto"]


@dataclass(frozen=True)
class Icons:
    """Icon set for CLI output."""

    # Status indicators
    ok: str
    fail: str
    warn: str
    info: str
    skip: str

    # Bullets and flow
    bullet: str
    arrow: str
    ellipsis: str

    # Fixed-width status tokens (for table alignment)
    status_ok: str
    status_fail: str
    status_warn: str
    status_skip: str

    # Action indicators
    create: str
    inspect: str
    check: str
    modify: str
    delete: str
    update: str
    search: str
    export: str
    list_: str  # 'list' is reserved

    # Domain-specific
    file: str
    folder: str
    torrent: str
    audio: str
    book: str
    tip: str
    run: str
    edit: str


# Unicode icons - clean, monospace-safe, widely supported
UNICODE_ICONS = Icons(
    # Status
    ok="✓",
    fail="✗",
    warn="!",
    info="i",
    skip="-",
    # Flow
    bullet="•",
    arrow="→",
    ellipsis="…",
    # Fixed-width tokens
    status_ok="OK",
    status_fail="FAIL",
    status_warn="WARN",
    status_skip="SKIP",
    # Actions
    create="+",
    inspect="?",
    check="✓",
    modify="~",
    delete="x",
    update="↻",
    search="?",
    export=">",
    list_="≡",
    # Domain
    file="·",
    folder="/",
    torrent="◉",
    audio="♪",
    book="§",
    tip="*",
    run=">",
    edit="~",
)

# ASCII icons - maximum terminal compatibility
ASCII_ICONS = Icons(
    # Status
    ok="[OK]",
    fail="[X]",
    warn="[!]",
    info="[i]",
    skip="[-]",
    # Flow
    bullet="*",
    arrow="->",
    ellipsis="...",
    # Fixed-width tokens
    status_ok="OK",
    status_fail="FAIL",
    status_warn="WARN",
    status_skip="SKIP",
    # Actions
    create="[+]",
    inspect="[?]",
    check="[v]",
    modify="[~]",
    delete="[x]",
    update="[^]",
    search="[?]",
    export="[>]",
    list_="[=]",
    # Domain
    file=".",
    folder="/",
    torrent="(T)",
    audio="(A)",
    book="(B)",
    tip="*",
    run=">",
    edit="~",
)

# Emoji icons - pretty but alignment-unsafe (use sparingly!)
EMOJI_ICONS = Icons(
    # Status
    ok="✅",
    fail="❌",
    warn="⚠️",
    info="ℹ️",
    skip="⏭️",
    # Flow
    bullet="•",
    arrow="➡️",
    ellipsis="…",
    # Fixed-width tokens (still use text for alignment)
    status_ok="OK",
    status_fail="FAIL",
    status_warn="WARN",
    status_skip="SKIP",
    # Actions
    create="📦",
    inspect="🔍",
    check="✅",
    modify="✏️",
    delete="🗑️",
    update="🔄",
    search="🔍",
    export="💾",
    list_="📋",
    # Domain
    file="📄",
    folder="📁",
    torrent="🧲",
    audio="🎵",
    book="📖",
    tip="💡",
    run="🚀",
    edit="📝",
)

# Module-level icon instance (configured at import time)
_current_mode: IconMode = "unicode"
_icons: Icons = UNICODE_ICONS


def get_icon_mode() -> IconMode:
    """Get the current icon mode."""
    return _current_mode


def set_icon_mode(mode: IconMode) -> None:
    """
    Set the icon mode globally.

    Args:
        mode: One of 'unicode', 'ascii', 'emoji', or 'auto'.
              'auto' selects based on terminal capabilities.
    """
    global _current_mode, _icons

    if mode == "auto":
        # Check for dumb terminal or NO_COLOR
        term = os.environ.get("TERM", "")
        no_color = os.environ.get("NO_COLOR", "")
        mode = "ascii" if term in ("dumb", "") or no_color else "unicode"

    _current_mode = mode

    if mode == "ascii":
        _icons = ASCII_ICONS
    elif mode == "emoji":
        _icons = EMOJI_ICONS
    else:
        _icons = UNICODE_ICONS


def get_icons() -> Icons:
    """Get the current icon set."""
    return _icons


# NOTE: Use get_icons() to access the current icon set dynamically.
# The icons object below is a static reference to UNICODE_ICONS that does NOT
# reflect runtime mode changes made by set_icon_mode(). Always prefer get_icons().
icons = UNICODE_ICONS


def _init_icons() -> None:
    """Initialize icons based on environment (called at module load)."""
    # Check for explicit override
    mode = os.environ.get("SHELFR_ICONS", "auto")
    if mode in ("unicode", "ascii", "emoji", "auto"):
        set_icon_mode(mode)  # type: ignore[arg-type]


# Initialize on import
_init_icons()

# Re-export for convenience
__all__ = [
    "Icons",
    "IconMode",
    "icons",
    "get_icons",
    "set_icon_mode",
    "get_icon_mode",
    "UNICODE_ICONS",
    "ASCII_ICONS",
    "EMOJI_ICONS",
]
