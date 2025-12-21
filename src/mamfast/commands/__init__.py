"""Command implementations for MAMFast CLI.

This package organizes CLI commands into logical modules:
- core: Main workflow commands (scan, discover, prepare, metadata, torrent, upload, run)
- utility: Status and diagnostic commands (status, check, validate, config)
- diagnostics: Analysis commands (check_duplicates, check_suspicious, dry_run)
- abs: Audiobookshelf integration commands
"""

from __future__ import annotations

from mamfast.commands.abs import (
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
from mamfast.commands.core import (
    cmd_discover,
    cmd_metadata,
    cmd_prepare,
    cmd_run,
    cmd_scan,
    cmd_torrent,
    cmd_upload,
)
from mamfast.commands.diagnostics import (
    cmd_check_duplicates,
    cmd_check_suspicious,
    cmd_dry_run,
)
from mamfast.commands.utility import (
    cmd_check,
    cmd_config,
    cmd_status,
    cmd_validate,
    cmd_validate_config,
)

__all__ = [
    # Core workflow
    "cmd_scan",
    "cmd_discover",
    "cmd_prepare",
    "cmd_metadata",
    "cmd_torrent",
    "cmd_upload",
    "cmd_run",
    # Utility
    "cmd_status",
    "cmd_check",
    "cmd_validate",
    "cmd_validate_config",
    "cmd_config",
    # Diagnostics
    "cmd_dry_run",
    "cmd_check_duplicates",
    "cmd_check_suspicious",
    # ABS
    "cmd_abs_init",
    "cmd_abs_import",
    "cmd_abs_check_duplicate",
    "cmd_abs_trump_check",
    "cmd_abs_restore",
    "cmd_abs_cleanup",
    "cmd_abs_rename",
    "cmd_abs_orphans",
    "cmd_abs_resolve_asins",
]
