"""App configuration, callbacks, and shared types for CLI.

This module contains the core Typer application factory, main callback,
shared enums, and type aliases used across all CLI commands.
"""

from __future__ import annotations

import argparse
import logging
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer
import yaml

from shelfr.console import console as shelfr_console
from shelfr.utils.validation import validate_asin

logger = logging.getLogger(__name__)

# =============================================================================
# Help Panel Names
# =============================================================================

CORE_COMMANDS = "Core Pipeline"
ABS_COMMANDS = "Audiobookshelf"
STATE_COMMANDS = "State Management"
DIAG_COMMANDS = "Diagnostics"
TOOLS_COMMANDS = "Tools"


# =============================================================================
# Shared Enums
# =============================================================================


class DuplicatePolicy(str, Enum):
    """Duplicate handling policy options."""

    skip = "skip"
    warn = "warn"
    overwrite = "overwrite"


class TrumpAggressiveness(str, Enum):
    """Trump aggressiveness level options."""

    conservative = "conservative"
    balanced = "balanced"
    aggressive = "aggressive"


class CleanupStrategy(str, Enum):
    """Cleanup strategy options."""

    none = "none"
    hide = "hide"
    move = "move"
    delete = "delete"


class SearchFormat(str, Enum):
    """Search output format options."""

    table = "table"
    simple = "simple"
    json = "json"


class ExportFormat(str, Enum):
    """Export format options."""

    json = "json"
    csv = "csv"


class BookStatus(str, Enum):
    """Book status filter options."""

    all = "all"
    downloaded = "downloaded"
    not_downloaded = "not_downloaded"
    error = "error"


class BooksFormat(str, Enum):
    """Books output format options."""

    table = "table"
    simple = "simple"
    json = "json"


class SetStatusValue(str, Enum):
    """Available status values for set-status command."""

    downloaded = "Downloaded"
    not_downloaded = "NotDownloaded"


# =============================================================================
# Version Callback
# =============================================================================


def version_callback(value: bool) -> None:
    """Print version with banner and exit."""
    if value:
        from shelfr.ui.banner import print_banner

        print_banner(shelfr_console)
        raise typer.Exit()


# =============================================================================
# ASIN Validation
# =============================================================================


def validate_asin_callback(value: str | None) -> str | None:
    """Validate ASIN format for Typer."""
    if value is None:
        return None

    try:
        return validate_asin(value)
    except argparse.ArgumentTypeError as e:
        raise typer.BadParameter(str(e)) from e


# Type alias for ASIN arguments
AsinArg = Annotated[
    str | None,
    typer.Option(
        "--asin",
        "-a",
        callback=validate_asin_callback,
        help="Process specific release by ASIN (format: B0XXXXXXXXX).",
    ),
]


# =============================================================================
# App Factory
# =============================================================================


# Epilog shown at bottom of main --help
MAIN_EPILOG = """
[bold cyan]Quick Start Workflow:[/]
  [dim]1.[/] shelfr check           [dim]# Verify setup[/]
  [dim]2.[/] shelfr libation scan   [dim]# Check for new books[/]
  [dim]3.[/] shelfr --dry-run run   [dim]# Preview pipeline[/]
  [dim]4.[/] shelfr run             [dim]# Upload to MAM[/]

[bold cyan]Tips:[/]
  - Use [green]--dry-run[/] before any command to preview changes
  - Run [green]shelfr check[/] first to verify your configuration
  - Global flags like [green]--dry-run[/] go [bold]BEFORE[/] the command

[dim]Documentation: https://github.com/H2OKing89/shelfr[/]
"""


def make_app() -> typer.Typer:
    """Create and configure the main Typer application."""
    return typer.Typer(
        name="shelfr",
        help="Audiobook library automation - staging, metadata, uploads",
        epilog=MAIN_EPILOG,
        rich_markup_mode="rich",
        pretty_exceptions_enable=True,
        pretty_exceptions_show_locals=False,
        no_args_is_help=True,
        add_completion=True,
        context_settings={"help_option_names": ["-h", "--help"]},
    )


STATE_EPILOG = """
[bold cyan]Common Tasks:[/]
  shelfr state list            [dim]# View all tracked releases[/]
  shelfr state prune           [dim]# Remove stale entries[/]
  shelfr state retry --asin X  [dim]# Retry a failed upload[/]

[dim]The state file tracks which audiobooks have been processed.[/]
"""


def make_state_app() -> typer.Typer:
    """Create the state management sub-app."""
    return typer.Typer(
        name="state",
        help="Manage processed.json state tracking",
        epilog=STATE_EPILOG,
        rich_markup_mode="rich",
        no_args_is_help=True,
    )


LIBATION_EPILOG = """
[bold cyan]Typical Workflow:[/]
  shelfr libation scan        [dim]# Check Audible for new purchases[/]
  shelfr libation liberate    [dim]# Download pending audiobooks[/]
  shelfr libation books       [dim]# List your library[/]

[dim]Libation downloads and decrypts Audible audiobooks automatically.[/]
[dim]Run 'shelfr libation guide' for detailed setup instructions.[/]
"""


def make_libation_app() -> typer.Typer:
    """Create the Libation sub-app."""
    return typer.Typer(
        name="libation",
        help="Libation audiobook manager integration",
        epilog=LIBATION_EPILOG,
        rich_markup_mode="rich",
        no_args_is_help=False,  # Default to status
    )


TOOLS_EPILOG = """
[bold cyan]Available Tools:[/]
  shelfr tools prepare       [dim]# Stage releases for upload[/]
  shelfr tools mkbrr         [dim]# Create torrent files[/]

[dim]These tools are for advanced troubleshooting and manual operations.[/]
[dim]For BBCode tools, see 'shelfr mam --help'.[/]
"""


def make_tools_app() -> typer.Typer:
    """Create the tools sub-app."""
    return typer.Typer(
        name="tools",
        help="Troubleshooting and utility tools",
        epilog=TOOLS_EPILOG,
        rich_markup_mode="rich",
        no_args_is_help=True,
    )


MAM_EPILOG = """
[bold cyan]BBCode Tools:[/]
  shelfr mam bbcode <path>   [dim]# Output raw BBCode (copyable)[/]
  shelfr mam render <path>   [dim]# Preview BBCode visually[/]

[dim]Note: MAM's upload page preview has a rendering bug for ASCII art.[/]
[dim]The actual torrent page will display correctly.[/]
"""


def make_mam_app() -> typer.Typer:
    """Create the MAM sub-app."""
    return typer.Typer(
        name="mam",
        help="MAM tracker workflows and BBCode tools",
        epilog=MAM_EPILOG,
        rich_markup_mode="rich",
        no_args_is_help=True,
    )


ABS_EPILOG = """
[bold cyan]Typical Workflow:[/]
  shelfr abs init            [dim]# Test connection to ABS[/]
  shelfr abs import          [dim]# Import staged books to library[/]
  shelfr abs cleanup         [dim]# Clean up source files after import[/]

[bold cyan]Maintenance:[/]
  shelfr abs orphans         [dim]# Find folders not in ABS library[/]
  shelfr abs rename          [dim]# Fix folder naming[/]
  shelfr abs resolve-asins   [dim]# Resolve missing ASINs[/]

[dim]Run 'shelfr abs init' first to verify your connection.[/]
"""


def make_abs_app() -> typer.Typer:
    """Create the Audiobookshelf sub-app."""
    return typer.Typer(
        name="abs",
        help="Audiobookshelf library management",
        epilog=ABS_EPILOG,
        rich_markup_mode="rich",
        no_args_is_help=True,
    )


# =============================================================================
# Logging Setup Helper
# =============================================================================


def setup_logging(verbose: bool, config_path: Path) -> None:
    """Configure logging based on options."""
    from shelfr.config import reload_settings
    from shelfr.logging_setup import setup_logging as _setup_logging

    log_level = "DEBUG" if verbose else "INFO"
    log_file = None

    try:
        settings = reload_settings(config_file=config_path)
        log_file = settings.paths.log_file
    except FileNotFoundError:
        pass  # Config may not exist yet, use defaults
    except PermissionError as e:
        logger.warning("Config file not accessible: %s", e)
        raise
    except yaml.YAMLError as e:
        logger.error("Invalid config.yaml: %s", e)
        raise

    _setup_logging(
        log_level=log_level,
        log_file=log_file,
        rich_console=True,
        quiet_console=not verbose,
    )


# =============================================================================
# Main Callback Factory
# =============================================================================


def create_main_callback(app: typer.Typer) -> None:
    """Register the main callback on the app."""

    @app.callback(invoke_without_command=True)
    def main_callback(
        ctx: typer.Context,
        version: Annotated[
            bool,
            typer.Option(
                "--version",
                "-V",
                callback=version_callback,
                is_eager=True,
                help="Show version and exit.",
            ),
        ] = False,
        verbose: Annotated[
            bool,
            typer.Option(
                "--verbose",
                "-v",
                help="Enable verbose (DEBUG) logging.",
            ),
        ] = False,
        config: Annotated[
            Path,
            typer.Option(
                "--config",
                "-c",
                help="Path to config.yaml.",
                exists=False,  # Don't require existence at parse time
            ),
        ] = Path("config/config.yaml"),
        dry_run: Annotated[
            bool,
            typer.Option(
                "--dry-run",
                help="Show what would happen without making changes.",
            ),
        ] = False,
    ) -> None:
        """Fast MAM audiobook upload automation tool.

        MAMFast automates the audiobook upload workflow:
        [cyan]Libation → Staging → Metadata → Torrent → Upload[/]

        [bold]Quick Start:[/]
          mamfast scan              Scan for new audiobooks
          mamfast run               Run full pipeline
          mamfast libation guide    Learn about Libation integration
        """
        # Show banner when no command is invoked (help will be shown after)
        if ctx.invoked_subcommand is None:
            from shelfr.ui.banner import print_banner

            print_banner(shelfr_console)

        # Store global options in context for commands to access
        # Using dict for backward compatibility during migration
        ctx.ensure_object(dict)
        ctx.obj["verbose"] = verbose
        ctx.obj["config"] = config
        ctx.obj["dry_run"] = dry_run

        # Setup logging
        setup_logging(verbose, config)
