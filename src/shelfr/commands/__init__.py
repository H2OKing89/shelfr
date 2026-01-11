"""Command implementations for shelfr CLI.

This package organizes CLI commands into logical modules:
- core: Main workflow commands (run, prepare) - individual steps handled by workflow.py
- utility: Status and diagnostic commands (status, check, validate, config)
- diagnostics: Analysis commands (check_duplicates, check_suspicious, preview_naming)
- state: State management commands (list, prune, retry, clear)
- abs: Audiobookshelf integration commands
- libation: Libation audiobook manager wrapper commands

NOTE: scan, discover, torrent, upload are now internal to workflow.py.
Use `shelfr run` for full pipeline, or `shelfr libation` subcommands.
"""

from __future__ import annotations

from shelfr.commands.abs import (
    cmd_abs_check_duplicate,
    cmd_abs_cleanup,
    cmd_abs_import,
    cmd_abs_init,
    cmd_abs_orphans,
    cmd_abs_rename,
    cmd_abs_resolve_asins,
    cmd_abs_restore,
    cmd_abs_trump_check,
)
from shelfr.commands.core import (
    cmd_prepare,
    cmd_run,
)
from shelfr.commands.diagnostics import (
    cmd_check_duplicates,
    cmd_check_suspicious,
    cmd_preview_naming,
)
from shelfr.commands.libation import (
    add_libation_parser,
    cmd_libation,
)
from shelfr.commands.state import cmd_state
from shelfr.commands.utility import (
    cmd_check,
    cmd_config,
    cmd_status,
    cmd_validate,
    cmd_validate_config,
)

__all__ = [
    "add_libation_parser",
    "cmd_abs_check_duplicate",
    "cmd_abs_cleanup",
    "cmd_abs_import",
    # ABS
    "cmd_abs_init",
    "cmd_abs_orphans",
    "cmd_abs_rename",
    "cmd_abs_resolve_asins",
    "cmd_abs_restore",
    "cmd_abs_trump_check",
    "cmd_check",
    "cmd_check_duplicates",
    "cmd_check_suspicious",
    "cmd_config",
    # Libation
    "cmd_libation",
    # Core workflow
    "cmd_prepare",  # Also available as `shelfr tools prepare`
    # Diagnostics
    "cmd_preview_naming",
    "cmd_run",
    # State management
    "cmd_state",
    # Utility
    "cmd_status",
    "cmd_validate",
    "cmd_validate_config",
]
