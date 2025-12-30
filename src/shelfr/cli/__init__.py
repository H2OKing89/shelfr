"""MAMFast CLI - Beautiful command-line interface built with Typer and Rich.

This package provides a modern, user-friendly CLI for audiobook upload automation.
Built with Typer for clean command structure and Rich for beautiful output.

The CLI is organized into sub-apps:
- Core pipeline commands (run, status, config)
- Audiobookshelf commands (abs init, abs import, abs cleanup, etc.)
- State management (state list, state prune, state retry, etc.)
- Libation integration (libation scan, libation liberate, etc.)
- Tools (tools prepare, tools mamff, tools bbcode)

Individual step commands (scan, discover, torrent, upload) have been moved
to internal workflow - use `mamfast run` for full pipeline.
"""

from __future__ import annotations

import sys

# Re-export key components for backward compatibility
from shelfr.cli._app import (
    ABS_COMMANDS,
    CORE_COMMANDS,
    DIAG_COMMANDS,
    STATE_COMMANDS,
    TOOLS_COMMANDS,
    AsinArg,
    BooksFormat,
    BookStatus,
    CleanupStrategy,
    DuplicatePolicy,
    ExportFormat,
    SearchFormat,
    SetStatusValue,
    TrumpAggressiveness,
    create_main_callback,
    make_abs_app,
    make_app,
    make_libation_app,
    make_state_app,
    make_tools_app,
    validate_asin_callback,
)
from shelfr.cli._context import RuntimeContext, get_runtime_context
from shelfr.cli._helpers import ArgsNamespace, get_args

# Create main app and sub-apps
app = make_app()
state_app = make_state_app()
libation_app = make_libation_app()
tools_app = make_tools_app()
abs_app = make_abs_app()

# Register sub-apps
app.add_typer(state_app, name="state", rich_help_panel=STATE_COMMANDS)
app.add_typer(libation_app, name="libation")
app.add_typer(tools_app, name="tools", rich_help_panel=TOOLS_COMMANDS)
app.add_typer(abs_app, name="abs", rich_help_panel=ABS_COMMANDS)

# Register main callback (handles --version, --verbose, --config, --dry-run)
create_main_callback(app)


# =============================================================================
# Register Commands
# =============================================================================
# Import command registration functions and call them with the apps.
# This avoids circular import issues while keeping command definitions in
# separate files.

from shelfr.cli.abs import (  # noqa: E402
    register_abs_commands,
    register_abs_deprecated_aliases,
)
from shelfr.cli.core import register_core_commands  # noqa: E402
from shelfr.cli.diagnostics import register_diagnostics_commands  # noqa: E402
from shelfr.cli.libation import register_libation_commands  # noqa: E402
from shelfr.cli.state import register_state_commands  # noqa: E402
from shelfr.cli.tools import register_tools_commands  # noqa: E402

register_core_commands(app)
register_diagnostics_commands(app)
register_state_commands(state_app)
register_abs_commands(abs_app)  # Register on sub-app now
register_abs_deprecated_aliases(app)  # Deprecated aliases on main app
register_libation_commands(libation_app)
register_tools_commands(tools_app)


# =============================================================================
# Entry Point
# =============================================================================


def main() -> int:
    """Main entry point for the CLI."""
    try:
        app()
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 0


# =============================================================================
# Backwards-Compatible Exports
# =============================================================================

# Re-export argparse parser for tests
from shelfr.cli_argparse import build_parser  # noqa: E402

# Re-export ABS command handlers for external callers
from shelfr.commands.abs import (  # noqa: E402
    cmd_abs_check_duplicate,
    cmd_abs_cleanup,
    cmd_abs_import,
    cmd_abs_init,
    cmd_abs_resolve_asins,
    cmd_abs_restore,
    cmd_abs_trump_check,
)

__all__ = [
    # App instances
    "app",
    "state_app",
    "libation_app",
    "tools_app",
    # Entry point
    "main",
    # Context
    "RuntimeContext",
    "get_runtime_context",
    # Legacy helpers (deprecated)
    "ArgsNamespace",
    "get_args",
    # Enums
    "DuplicatePolicy",
    "TrumpAggressiveness",
    "CleanupStrategy",
    "SearchFormat",
    "ExportFormat",
    "BookStatus",
    "BooksFormat",
    "SetStatusValue",
    # Type aliases
    "AsinArg",
    # Validators
    "validate_asin_callback",
    # Constants
    "CORE_COMMANDS",
    "ABS_COMMANDS",
    "STATE_COMMANDS",
    "DIAG_COMMANDS",
    "TOOLS_COMMANDS",
    # Backward compatibility
    "build_parser",
    "cmd_abs_init",
    "cmd_abs_import",
    "cmd_abs_cleanup",
    "cmd_abs_check_duplicate",
    "cmd_abs_resolve_asins",
    "cmd_abs_trump_check",
    "cmd_abs_restore",
]

if __name__ == "__main__":
    sys.exit(main())
