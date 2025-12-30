"""App configuration, callbacks, and shared types for CLI.

This module contains the core Typer application factory, main callback,
shared enums, and type aliases used across all CLI commands.
"""

from __future__ import annotations

import argparse
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.panel import Panel

from mamfast import __version__
from mamfast.console import console as mamfast_console

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
    """Print version and exit."""
    if value:
        mamfast_console.print(
            Panel(
                f"[bold cyan]MAMFast[/] [dim]v{__version__}[/]\n"
                "[dim]Fast MAM audiobook upload automation[/]",
                border_style="cyan",
            )
        )
        raise typer.Exit()


# =============================================================================
# ASIN Validation
# =============================================================================


def validate_asin_callback(value: str | None) -> str | None:
    """Validate ASIN format for Typer."""
    if value is None:
        return None

    from mamfast.utils.validation import validate_asin

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


def make_app() -> typer.Typer:
    """Create and configure the main Typer application."""
    return typer.Typer(
        name="mamfast",
        help="🎧 Fast MAM audiobook upload automation tool",
        rich_markup_mode="rich",
        pretty_exceptions_enable=True,
        pretty_exceptions_show_locals=False,
        no_args_is_help=True,
        add_completion=True,
        context_settings={"help_option_names": ["-h", "--help"]},
    )


def make_state_app() -> typer.Typer:
    """Create the state management sub-app."""
    return typer.Typer(
        name="state",
        help="📋 Manage processed.json state",
        rich_markup_mode="rich",
        no_args_is_help=True,
    )


def make_libation_app() -> typer.Typer:
    """Create the Libation sub-app."""
    return typer.Typer(
        name="libation",
        help="📚 Libation audiobook manager integration",
        rich_markup_mode="rich",
        no_args_is_help=False,  # Default to status
    )


def make_tools_app() -> typer.Typer:
    """Create the tools sub-app."""
    return typer.Typer(
        name="tools",
        help="🔧 Troubleshooting and utility tools",
        rich_markup_mode="rich",
        no_args_is_help=True,
    )


def make_abs_app() -> typer.Typer:
    """Create the Audiobookshelf sub-app."""
    return typer.Typer(
        name="abs",
        help="📚 Audiobookshelf library management",
        rich_markup_mode="rich",
        no_args_is_help=True,
    )


# =============================================================================
# Logging Setup Helper
# =============================================================================


def setup_logging(verbose: bool, config_path: Path) -> None:
    """Configure logging based on options."""
    from mamfast.config import reload_settings
    from mamfast.logging_setup import setup_logging as _setup_logging

    log_level = "DEBUG" if verbose else "INFO"
    log_file = None

    try:
        settings = reload_settings(config_file=config_path)
        log_file = settings.paths.log_file
    except FileNotFoundError:
        pass  # Config may not exist yet, use defaults
    except PermissionError as e:
        import logging

        logging.getLogger(__name__).warning("Config file not accessible: %s", e)
        raise
    except yaml.YAMLError as e:
        import logging

        logging.getLogger(__name__).error("Invalid config.yaml: %s", e)
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

    @app.callback()
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
        """🎧 Fast MAM audiobook upload automation tool.

        MAMFast automates the audiobook upload workflow:
        [cyan]Libation → Staging → Metadata → Torrent → Upload[/]

        [bold]Quick Start:[/]
          mamfast scan              Scan for new audiobooks
          mamfast run               Run full pipeline
          mamfast libation guide    Learn about Libation integration
        """
        # Store global options in context for commands to access
        # Using dict for backward compatibility during migration
        ctx.ensure_object(dict)
        ctx.obj["verbose"] = verbose
        ctx.obj["config"] = config
        ctx.obj["dry_run"] = dry_run

        # Setup logging
        setup_logging(verbose, config)
