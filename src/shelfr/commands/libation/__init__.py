"""Libation command package.

This package contains commands for interacting with Libation audiobook manager.
"""

from __future__ import annotations

# Re-export all command handlers and shared utilities
from ._common import LibationCommandResult, export_library, get_library_status, run_libation_cmd
from ._parser import add_libation_parser, cmd_libation
from ._ui import (
    print_book_table,
    print_command_help,
    print_hint_box,
    print_libation_header,
    print_status_dashboard,
)
from .core import cmd_libation_liberate, cmd_libation_scan, cmd_libation_status
from .export_ import cmd_libation_export
from .guide import cmd_libation_guide
from .management import cmd_libation_convert, cmd_libation_redownload, cmd_libation_set_status
from .search import cmd_libation_books, cmd_libation_search
from .settings import cmd_libation_settings

__all__ = [
    # Shared utilities
    "LibationCommandResult",
    # Parser
    "add_libation_parser",
    "cmd_libation",
    # Search commands
    "cmd_libation_books",
    # Management commands
    "cmd_libation_convert",
    # Export command
    "cmd_libation_export",
    # Guide command
    "cmd_libation_guide",
    # Core commands
    "cmd_libation_liberate",
    "cmd_libation_redownload",
    "cmd_libation_scan",
    "cmd_libation_search",
    "cmd_libation_set_status",
    # Settings command
    "cmd_libation_settings",
    "cmd_libation_status",
    "export_library",
    "get_library_status",
    # UI helpers
    "print_book_table",
    "print_command_help",
    "print_hint_box",
    "print_libation_header",
    "print_status_dashboard",
    "run_libation_cmd",
]
