"""ABS command handlers package.

This package contains the split command handlers for Audiobookshelf integration.

Each module contains a single command handler:
- init.py: cmd_abs_init - verify ABS connection
- import_.py: cmd_abs_import - import staged books to ABS library
- check.py: cmd_abs_check_duplicate - check for duplicate ASINs
- trump.py: cmd_abs_trump_check - preview trumping decisions
- restore.py: cmd_abs_restore - restore archived books
- cleanup.py: cmd_abs_cleanup - cleanup source files after import
- rename.py: cmd_abs_rename - rename folders to MAM naming schema
- orphans.py: cmd_abs_orphans - find and cleanup orphaned folders
- resolve.py: cmd_abs_resolve_asins - resolve ASINs for Unknown/ books

The _common.py module contains shared utilities and console helpers.
"""

from __future__ import annotations

from shelfr.commands.abs._common import should_ignore
from shelfr.commands.abs.check import cmd_abs_check_duplicate
from shelfr.commands.abs.cleanup import cmd_abs_cleanup
from shelfr.commands.abs.import_ import cmd_abs_import
from shelfr.commands.abs.init import cmd_abs_init
from shelfr.commands.abs.orphans import cmd_abs_orphans
from shelfr.commands.abs.rename import cmd_abs_rename
from shelfr.commands.abs.resolve import cmd_abs_resolve_asins
from shelfr.commands.abs.restore import cmd_abs_restore
from shelfr.commands.abs.trump import cmd_abs_trump_check

__all__ = [
    # Handlers
    "cmd_abs_check_duplicate",
    "cmd_abs_cleanup",
    "cmd_abs_import",
    "cmd_abs_init",
    "cmd_abs_orphans",
    "cmd_abs_rename",
    "cmd_abs_resolve_asins",
    "cmd_abs_restore",
    "cmd_abs_trump_check",
    # Utilities
    "should_ignore",
]
