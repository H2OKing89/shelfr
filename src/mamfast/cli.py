"""MAMFast CLI - Beautiful command-line interface built with Typer and Rich.

This module provides a modern, user-friendly CLI for audiobook upload automation.
Built with Typer for clean command structure and Rich for beautiful output.
"""

from __future__ import annotations

import argparse
import sys
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel

from mamfast import __version__
from mamfast.console import console as mamfast_console

# =============================================================================
# App Configuration
# =============================================================================

# Custom help panel names for better organization
CORE_COMMANDS = "Core Pipeline"
ABS_COMMANDS = "Audiobookshelf"
STATE_COMMANDS = "State Management"
DIAG_COMMANDS = "Diagnostics"
TOOLS_COMMANDS = "Tools"


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


# Main app instance
app = make_app()

# Sub-apps for command groups
state_app = typer.Typer(
    name="state",
    help="📋 Manage processed.json state",
    rich_markup_mode="rich",
    no_args_is_help=True,
)
app.add_typer(state_app, name="state", rich_help_panel=STATE_COMMANDS)

libation_app = typer.Typer(
    name="libation",
    help="📚 Libation audiobook manager integration",
    rich_markup_mode="rich",
    no_args_is_help=False,  # Default to status
)
app.add_typer(libation_app, name="libation")

tools_app = typer.Typer(
    name="tools",
    help="🔧 Troubleshooting and utility tools",
    rich_markup_mode="rich",
    no_args_is_help=True,
)
app.add_typer(tools_app, name="tools", rich_help_panel=TOOLS_COMMANDS)


# =============================================================================
# Global Options Callback
# =============================================================================


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
    [cyan]Libation[/] → [cyan]Staging[/] → [cyan]Metadata[/] → [cyan]Torrent[/] → [cyan]Upload[/]

    [bold]Quick Start:[/]
      mamfast scan              Scan for new audiobooks
      mamfast run               Run full pipeline
      mamfast libation guide    Learn about Libation integration
    """
    # Store global options in context for commands to access
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["config"] = config
    ctx.obj["dry_run"] = dry_run

    # Setup logging
    _setup_logging(verbose, config)


def _setup_logging(verbose: bool, config_path: Path) -> None:
    """Configure logging based on options."""
    from mamfast.config import reload_settings
    from mamfast.logging_setup import setup_logging

    log_level = "DEBUG" if verbose else "INFO"
    log_file = None

    try:
        settings = reload_settings(config_file=config_path)
        log_file = settings.paths.log_file
    except Exception:
        pass  # Config may not exist yet

    setup_logging(
        log_level=log_level,
        log_file=log_file,
        rich_console=True,
        quiet_console=not verbose,
    )


# =============================================================================
# ASIN Type for Validation
# =============================================================================


def validate_asin_callback(value: str | None) -> str | None:
    """Validate ASIN format for Typer."""
    if value is None:
        return None

    import argparse

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
# Helper to Create Args Namespace (for backward compatibility)
# =============================================================================


class ArgsNamespace(argparse.Namespace):
    """Namespace compatible with argparse for existing command handlers."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)


def get_args(ctx: typer.Context, **kwargs: object) -> ArgsNamespace:
    """Create args namespace from context and keyword arguments."""
    args = ArgsNamespace(
        verbose=ctx.obj.get("verbose", False),
        config=ctx.obj.get("config", Path("config/config.yaml")),
        dry_run=ctx.obj.get("dry_run", False),
        **kwargs,
    )
    return args


# =============================================================================
# Core Pipeline Commands
# =============================================================================


@app.command(rich_help_panel=CORE_COMMANDS)
def scan(
    ctx: typer.Context,
    liberate: Annotated[
        bool,
        typer.Option(
            "--liberate",
            help="Also download new books after scanning.",
        ),
    ] = False,
) -> None:
    """🔍 Scan Audible library for new audiobooks.

    Runs libationcli scan in the Libation Docker container to check
    for new purchases in your Audible library.

    [bold]Examples:[/]
      mamfast scan              # Just scan for new books
      mamfast scan --liberate   # Scan and download new books
    """
    from mamfast.commands import cmd_scan

    args = get_args(ctx, liberate=liberate, command="scan")
    result = cmd_scan(args)
    raise typer.Exit(result)


@app.command(rich_help_panel=CORE_COMMANDS)
def discover(
    ctx: typer.Context,
    all_books: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Show all audiobooks, not just unprocessed.",
        ),
    ] = False,
) -> None:
    """📖 List new audiobooks found in Libation library.

    Discovers unprocessed audiobooks that are ready to be staged
    for upload to MAM.

    [bold]Examples:[/]
      mamfast discover       # Show unprocessed books
      mamfast discover --all # Show all books

    [dim]Tip: Scans Libation output directory for new audiobooks.[/]
    """
    from mamfast.commands import cmd_discover

    args = get_args(ctx, all=all_books, command="discover")
    result = cmd_discover(args)
    raise typer.Exit(result)


@app.command(rich_help_panel=CORE_COMMANDS)
def prepare(
    ctx: typer.Context,
    asin: AsinArg = None,
    dry_run_hint: Annotated[
        bool,
        typer.Option("--dry-run", hidden=True),
    ] = False,
) -> None:
    """📦 Stage audiobooks for upload.

    Creates hardlinks and renames files to MAM-compliant naming format
    in the staging directory.

    [bold]Examples:[/]
      mamfast prepare              # Prepare all discovered books
      mamfast prepare -a B0DK9T5P28  # Prepare specific book

    [dim]Tip: Stages release for upload by hardlinking files and validating structure.[/]
    """
    from mamfast.console import console

    if dry_run_hint:
        console.print(
            "[yellow]⚠️  --dry-run must come BEFORE the subcommand:[/]\n\n"
            "    [green]mamfast --dry-run prepare[/]  ✓\n"
            "    [red]mamfast prepare --dry-run[/]  ✗\n"
        )
        raise typer.Exit(2)

    from mamfast.commands import cmd_prepare

    args = get_args(ctx, asin=asin, command="prepare")
    result = cmd_prepare(args)
    raise typer.Exit(result)


@app.command(rich_help_panel=CORE_COMMANDS)
def metadata(
    ctx: typer.Context,
    path: Annotated[
        Path | None,
        typer.Argument(help="Path to specific audiobook directory."),
    ] = None,
    asin: AsinArg = None,
) -> None:
    """📋 Fetch metadata for staged releases.

    Retrieves metadata from Audnex API and MediaInfo for staged
    audiobook releases.

    [bold]Examples:[/]
      mamfast metadata                    # All staged releases
      mamfast metadata -a B0DK9T5P28      # Specific ASIN
      mamfast metadata /path/to/audiobook # Specific path

    [dim]Tip: Fetches from Audnex API and extracts MediaInfo from audio files.[/]
    """
    from mamfast.commands import cmd_metadata

    args = get_args(ctx, path=path, asin=asin, command="metadata")
    result = cmd_metadata(args)
    raise typer.Exit(result)


@app.command(rich_help_panel=CORE_COMMANDS)
def torrent(
    ctx: typer.Context,
    path: Annotated[
        Path | None,
        typer.Argument(help="Path to specific audiobook directory."),
    ] = None,
    preset: Annotated[
        str | None,
        typer.Option(help="Override mkbrr preset (default from config)."),
    ] = None,
    asin: AsinArg = None,
) -> None:
    """🧲 Create .torrent files for staged releases.

    Uses mkbrr in Docker to create .torrent files for upload.

    [bold]Examples:[/]
      mamfast torrent                     # All staged releases
      mamfast torrent -a B0DK9T5P28       # Specific ASIN
      mamfast torrent --preset custom     # Use custom preset

    [dim]Tip: Creates .torrent file using mkbrr in Docker container.[/]
    """
    from mamfast.commands import cmd_torrent

    args = get_args(ctx, path=path, preset=preset, asin=asin, command="torrent")
    result = cmd_torrent(args)
    raise typer.Exit(result)


@app.command(rich_help_panel=CORE_COMMANDS)
def upload(
    ctx: typer.Context,
    paused: Annotated[
        bool,
        typer.Option(help="Add torrents in paused state."),
    ] = False,
    dry_run_hint: Annotated[
        bool,
        typer.Option("--dry-run", hidden=True),
    ] = False,
) -> None:
    """⬆️  Upload .torrent files to qBittorrent.

    Adds created torrent files to qBittorrent for seeding.

    [bold]Examples:[/]
      mamfast upload           # Upload all ready torrents
      mamfast upload --paused  # Upload but don't start seeding

    [dim]Tip: Submits torrent and metadata to MAM tracker.[/]
    """
    from mamfast.console import console

    if dry_run_hint:
        console.print(
            "[yellow]⚠️  --dry-run must come BEFORE the subcommand:[/]\n\n"
            "    [green]mamfast --dry-run upload[/]  ✓\n"
            "    [red]mamfast upload --dry-run[/]  ✗\n"
        )
        raise typer.Exit(2)

    from mamfast.commands import cmd_upload

    args = get_args(ctx, paused=paused, command="upload")
    result = cmd_upload(args)
    raise typer.Exit(result)


@app.command(rich_help_panel=CORE_COMMANDS)
def run(
    ctx: typer.Context,
    skip_scan: Annotated[
        bool,
        typer.Option("--skip-scan", help="Skip Libation scan step."),
    ] = False,
    skip_metadata: Annotated[
        bool,
        typer.Option("--skip-metadata", help="Skip metadata fetching step."),
    ] = False,
    no_run_lock: Annotated[
        bool,
        typer.Option(
            "--no-run-lock",
            help="[red]DANGEROUS:[/] Bypass run lock (can cause data corruption).",
        ),
    ] = False,
    dry_run_hint: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            hidden=True,
            help="(Use 'mamfast --dry-run run' instead)",
        ),
    ] = False,
) -> None:
    """🚀 Run the full upload pipeline.

    Executes all steps: [cyan]scan → discover → prepare → metadata → torrent → upload[/]

    [bold]Examples:[/]
      mamfast run               # Full pipeline
      mamfast --dry-run run     # Preview without changes
      mamfast run --skip-scan   # Skip Libation scan
    """
    from mamfast.console import console

    # Handle misplaced --dry-run flag
    if dry_run_hint:
        console.print(
            "[yellow]⚠️  --dry-run must come BEFORE the subcommand:[/]\n\n"
            "    [green]mamfast --dry-run run[/]  ✓\n"
            "    [red]mamfast run --dry-run[/]  ✗\n"
        )
        raise typer.Exit(2)

    from mamfast.commands import cmd_run

    args = get_args(
        ctx,
        skip_scan=skip_scan,
        skip_metadata=skip_metadata,
        no_run_lock=no_run_lock,
        command="run",
    )
    result = cmd_run(args)
    raise typer.Exit(result)


@app.command(rich_help_panel=CORE_COMMANDS)
def status(ctx: typer.Context) -> None:
    """📊 Show processing status of all releases.

    Displays a summary of discovered, staged, and processed releases.
    """
    from mamfast.commands import cmd_status

    args = get_args(ctx, command="status")
    result = cmd_status(args)
    raise typer.Exit(result)


@app.command(rich_help_panel=CORE_COMMANDS)
def config(ctx: typer.Context) -> None:
    """⚙️  Print loaded configuration.

    Shows the current configuration values for debugging.
    """
    from mamfast.commands import cmd_config

    args = get_args(ctx, command="config")
    result = cmd_config(args)
    raise typer.Exit(result)


# =============================================================================
# Diagnostics Commands
# =============================================================================


@app.command(rich_help_panel=DIAG_COMMANDS)
def check(
    ctx: typer.Context,
    config_only: Annotated[
        bool,
        typer.Option("--config-only", help="Run configuration checks only."),
    ] = False,
    paths_only: Annotated[
        bool,
        typer.Option("--paths-only", help="Run path checks only."),
    ] = False,
    services_only: Annotated[
        bool,
        typer.Option("--services-only", help="Run service connectivity checks only."),
    ] = False,
) -> None:
    """🩺 Run health checks to verify environment setup.

    Validates configuration, paths, and service connectivity.

    [bold]Examples:[/]
      mamfast check               # Run all checks
      mamfast check --config-only # Configuration only
      mamfast check --services-only # Test services
    """
    from mamfast.commands import cmd_check

    args = get_args(
        ctx,
        config_only=config_only,
        paths_only=paths_only,
        services_only=services_only,
        command="check",
    )
    result = cmd_check(args)
    raise typer.Exit(result)


@app.command(rich_help_panel=DIAG_COMMANDS)
def validate(
    ctx: typer.Context,
    asin: AsinArg = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output validation report as JSON."),
    ] = False,
) -> None:
    """✅ Validate discovered releases.

    Runs validation checks on all discovered releases without processing.

    [bold]Examples:[/]
      mamfast validate              # Validate all
      mamfast validate -a B0DK9T5P28 # Validate specific ASIN
      mamfast validate --json       # JSON output
    """
    from mamfast.commands import cmd_validate

    args = get_args(ctx, asin=asin, json=json_output, command="validate")
    result = cmd_validate(args)
    raise typer.Exit(result)


@app.command("validate-config", rich_help_panel=DIAG_COMMANDS)
def validate_config(ctx: typer.Context) -> None:
    """📝 Validate configuration files.

    Checks naming.json, config.yaml, and other config files for errors.
    """
    from mamfast.commands import cmd_validate_config

    args = get_args(ctx, command="validate-config")
    result = cmd_validate_config(args)
    raise typer.Exit(result)


@app.command("dry-run", rich_help_panel=DIAG_COMMANDS)
def dry_run_cmd(
    ctx: typer.Context,
    limit: Annotated[
        int,
        typer.Option("--limit", "-n", help="Maximum releases to preview."),
    ] = 20,
    asin: AsinArg = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output results as JSON."),
    ] = False,
) -> None:
    """👀 Preview naming transformations.

    Shows before/after for title filtering and folder renaming
    without making any changes.

    [bold]Examples:[/]
      mamfast dry-run              # Preview first 20 releases
      mamfast dry-run -n 50        # Preview 50 releases
      mamfast dry-run -a B0DK9T5P28 # Preview specific ASIN
      mamfast dry-run --json       # JSON output
    """
    from mamfast.commands import cmd_dry_run

    args = get_args(ctx, limit=limit, asin=asin, json=json_output, command="dry-run")
    result = cmd_dry_run(args)
    raise typer.Exit(result)


@app.command("check-duplicates", rich_help_panel=DIAG_COMMANDS)
def check_duplicates(
    ctx: typer.Context,
    threshold: Annotated[
        int,
        typer.Option("--threshold", "-t", help="Minimum similarity % (default: 85)."),
    ] = 85,
    limit: Annotated[
        int,
        typer.Option("--limit", "-n", help="Maximum duplicate pairs to show."),
    ] = 20,
    include_processed: Annotated[
        bool,
        typer.Option("--include-processed", help="Include already processed releases."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output results as JSON."),
    ] = False,
) -> None:
    """🔎 Find potential duplicate releases.

    Uses fuzzy matching to find near-duplicate titles in your library.

    [bold]Examples:[/]
      mamfast check-duplicates         # Default 85% threshold
      mamfast check-duplicates -t 90   # Stricter matching
      mamfast check-duplicates --json  # JSON output
    """
    from mamfast.commands import cmd_check_duplicates

    args = get_args(
        ctx,
        threshold=threshold,
        limit=limit,
        include_processed=include_processed,
        json=json_output,
        command="check-duplicates",
    )
    result = cmd_check_duplicates(args)
    raise typer.Exit(result)


@app.command("check-suspicious", rich_help_panel=DIAG_COMMANDS)
def check_suspicious(
    ctx: typer.Context,
    threshold: Annotated[
        int,
        typer.Option("--threshold", "-t", help="Max similarity below which is suspicious."),
    ] = 50,
    asin: AsinArg = None,
    include_processed: Annotated[
        bool,
        typer.Option("--include-processed", help="Include already processed releases."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output results as JSON."),
    ] = False,
) -> None:
    """🔍 Check for over-aggressive title cleaning.

    Compares original titles to cleaned versions and flags significant changes.

    [bold]Examples:[/]
      mamfast check-suspicious       # Default threshold
      mamfast check-suspicious -t 40 # More aggressive detection
    """
    from mamfast.commands import cmd_check_suspicious

    args = get_args(
        ctx,
        threshold=threshold,
        asin=asin,
        include_processed=include_processed,
        json=json_output,
        command="check-suspicious",
    )
    result = cmd_check_suspicious(args)
    raise typer.Exit(result)


# =============================================================================
# State Management Commands
# =============================================================================


@state_app.command("list")
def state_list(
    ctx: typer.Context,
    processed: Annotated[
        bool,
        typer.Option("--processed", help="Show only processed entries."),
    ] = False,
    failed: Annotated[
        bool,
        typer.Option("--failed", help="Show only failed entries."),
    ] = False,
    limit: Annotated[
        int,
        typer.Option("--limit", "-n", help="Maximum entries to show."),
    ] = 20,
    json_output: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output as JSON."),
    ] = False,
) -> None:
    """📋 List state entries.

    Shows processed and/or failed entries from the state file.

    [bold]Examples:[/]
      mamfast state list            # All entries
      mamfast state list --failed   # Only failed
      mamfast state list --json     # JSON output
    """
    from mamfast.commands import cmd_state

    args = get_args(
        ctx,
        state_command="list",
        processed=processed,
        failed=failed,
        limit=limit,
        json=json_output,
        command="state",
    )
    result = cmd_state(args)
    raise typer.Exit(result)


@state_app.command("prune")
def state_prune(ctx: typer.Context) -> None:
    """🧹 Remove stale entries with missing paths.

    Cleans up state entries whose files no longer exist.

    [bold]Tip:[/] Use [cyan]mamfast --dry-run state prune[/] to preview.
    """
    from mamfast.commands import cmd_state

    args = get_args(ctx, state_command="prune", command="state")
    result = cmd_state(args)
    raise typer.Exit(result)


@state_app.command("retry")
def state_retry(
    ctx: typer.Context,
    asin: Annotated[str, typer.Argument(metavar="ASIN", help="ASIN to clear from failed state.")],
) -> None:
    """🔄 Clear a failed entry to allow re-processing.

    Removes the ASIN from failed state so it can be processed again.

    [bold]Example:[/]
      mamfast state retry B0DK9T5P28
    """
    from mamfast.commands import cmd_state

    args = get_args(ctx, state_command="retry", asin=asin, command="state")
    result = cmd_state(args)
    raise typer.Exit(result)


@state_app.command("clear")
def state_clear(
    ctx: typer.Context,
    asin: Annotated[
        str, typer.Argument(metavar="ASIN", help="ASIN to clear from processed state.")
    ],
) -> None:
    """🗑️  Clear a processed entry to force re-run.

    Removes the ASIN from processed state for full re-processing.

    [bold]Example:[/]
      mamfast state clear B0DK9T5P28
    """
    from mamfast.commands import cmd_state

    args = get_args(ctx, state_command="clear", asin=asin, command="state")
    result = cmd_state(args)
    raise typer.Exit(result)


@state_app.command("export")
def state_export(
    ctx: typer.Context,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output file path (default: stdout)."),
    ] = None,
) -> None:
    """💾 Export state to JSON file.

    Exports the current state to a JSON file for backup or analysis.

    [bold]Examples:[/]
      mamfast state export                # Print to stdout
      mamfast state export -o backup.json # Save to file
    """
    from mamfast.commands import cmd_state

    args = get_args(ctx, state_command="export", output=output, command="state")
    result = cmd_state(args)
    raise typer.Exit(result)


# =============================================================================
# Audiobookshelf Commands
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


@app.command("abs-init", rich_help_panel=ABS_COMMANDS)
def abs_init(ctx: typer.Context) -> None:
    """🔌 Initialize Audiobookshelf connection.

    Tests ABS API connection and discovers available libraries.
    """
    from mamfast.commands import cmd_abs_init

    args = get_args(ctx, command="abs-init")
    result = cmd_abs_init(args)
    raise typer.Exit(result)


@app.command("abs-import", rich_help_panel=ABS_COMMANDS)
def abs_import(
    ctx: typer.Context,
    paths: Annotated[
        list[Path] | None,
        typer.Argument(help="Specific folder(s) to import."),
    ] = None,
    duplicate_policy: Annotated[
        DuplicatePolicy | None,
        typer.Option("-d", "--duplicate-policy", help="Duplicate handling policy."),
    ] = None,
    no_scan: Annotated[
        bool,
        typer.Option("--no-scan", help="Don't trigger ABS library scan after import."),
    ] = False,
    no_abs_search: Annotated[
        bool,
        typer.Option("--no-abs-search", help="Disable ABS metadata search for missing ASINs."),
    ] = False,
    confidence: Annotated[
        float | None,
        typer.Option(help="Minimum confidence (0.0-1.0) for ABS search matches."),
    ] = None,
    no_trump: Annotated[
        bool,
        typer.Option("--no-trump", help="Disable trumping for this run."),
    ] = False,
    trump_aggressiveness: Annotated[
        TrumpAggressiveness | None,
        typer.Option(help="Override trumping aggressiveness."),
    ] = None,
    cleanup_strategy: Annotated[
        CleanupStrategy | None,
        typer.Option(help="Override cleanup strategy."),
    ] = None,
    cleanup_path: Annotated[
        Path | None,
        typer.Option(help="Override cleanup path for 'move' strategy."),
    ] = None,
    no_cleanup: Annotated[
        bool,
        typer.Option("--no-cleanup", help="Disable post-import cleanup."),
    ] = False,
    no_metadata: Annotated[
        bool,
        typer.Option("--no-metadata", help="Disable metadata.json generation."),
    ] = False,
) -> None:
    """📥 Import staged audiobooks to Audiobookshelf.

    Moves staged books to ABS library structure with duplicate detection.

    [bold]Examples:[/]
      mamfast abs-import                    # Import all staged
      mamfast abs-import /path/to/book      # Import specific folder
      mamfast abs-import -d skip            # Skip duplicates
    """
    from mamfast.commands import cmd_abs_import

    args = get_args(
        ctx,
        paths=paths or [],
        duplicate_policy=duplicate_policy.value if duplicate_policy else None,
        no_scan=no_scan,
        no_abs_search=no_abs_search,
        confidence=confidence,
        no_trump=no_trump,
        trump_aggressiveness=trump_aggressiveness.value if trump_aggressiveness else None,
        cleanup_strategy=cleanup_strategy.value if cleanup_strategy else None,
        cleanup_path=cleanup_path,
        no_cleanup=no_cleanup,
        no_metadata=no_metadata,
        command="abs-import",
    )
    result = cmd_abs_import(args)
    raise typer.Exit(result)


@app.command("abs-check-duplicate", rich_help_panel=ABS_COMMANDS)
def abs_check_duplicate(
    ctx: typer.Context,
    asin: Annotated[str, typer.Argument(metavar="ASIN", help="ASIN to check (e.g., B0DK27WWT8).")],
) -> None:
    """🔍 Check if ASIN exists in library.

    Quick lookup to check for duplicates before importing.

    [bold]Example:[/]
      mamfast abs-check-duplicate B0DK9T5P28
    """
    from mamfast.commands import cmd_abs_check_duplicate

    args = get_args(ctx, asin=asin, command="abs-check-duplicate")
    result = cmd_abs_check_duplicate(args)
    raise typer.Exit(result)


@app.command("abs-trump-check", rich_help_panel=ABS_COMMANDS)
def abs_trump_check(
    ctx: typer.Context,
    paths: Annotated[
        list[Path] | None,
        typer.Argument(help="Specific folder(s) to check."),
    ] = None,
    detailed: Annotated[
        bool,
        typer.Option("--detailed", help="Show detailed quality comparison tables."),
    ] = False,
) -> None:
    """⚔️  Preview trumping decisions for staged folders.

    Shows what would be replaced, kept, or rejected based on quality comparison.
    """
    from mamfast.commands import cmd_abs_trump_check

    args = get_args(ctx, paths=paths or [], detailed=detailed, command="abs-trump-check")
    result = cmd_abs_trump_check(args)
    raise typer.Exit(result)


@app.command("abs-restore", rich_help_panel=ABS_COMMANDS)
def abs_restore(
    ctx: typer.Context,
    archive_path: Annotated[
        Path | None,
        typer.Argument(help="Specific archive folder to restore."),
    ] = None,
    asin: AsinArg = None,
    list_archives: Annotated[
        bool,
        typer.Option("--list", help="List available archives without restoring."),
    ] = False,
) -> None:
    """♻️  Restore archived books to library.

    Restore books that were archived by trumping back to the library.

    [bold]Examples:[/]
      mamfast abs-restore --list            # List archives
      mamfast abs-restore -a B0DK9T5P28     # Filter by ASIN
      mamfast abs-restore /path/to/archive  # Restore specific
    """
    from mamfast.commands import cmd_abs_restore

    args = get_args(
        ctx,
        archive_path=archive_path,
        asin=asin,
        list=list_archives,
        command="abs-restore",
    )
    result = cmd_abs_restore(args)
    raise typer.Exit(result)


@app.command("abs-cleanup", rich_help_panel=ABS_COMMANDS)
def abs_cleanup(
    ctx: typer.Context,
    paths: Annotated[
        list[Path] | None,
        typer.Argument(help="Specific folder(s) to cleanup."),
    ] = None,
    strategy: Annotated[
        CleanupStrategy | None,
        typer.Option(help="Cleanup strategy."),
    ] = None,
    cleanup_path: Annotated[
        Path | None,
        typer.Option(help="Destination for 'move' strategy."),
    ] = None,
    no_verify_seed: Annotated[
        bool,
        typer.Option(
            "--no-verify-seed",
            help=("[red]DANGEROUS:[/] Skip seed hardlink verification."),
        ),
    ] = False,
    min_age_days: Annotated[
        int | None,
        typer.Option(help="Only cleanup sources older than N days."),
    ] = None,
) -> None:
    """🧹 Cleanup Libation source files after import.

    Standalone cleanup of Libation source folders that have been imported.
    Supports strategies: hide (add marker), move, or delete.
    """
    from mamfast.commands import cmd_abs_cleanup

    args = get_args(
        ctx,
        paths=paths or [],
        strategy=strategy.value if strategy else None,
        cleanup_path=cleanup_path,
        no_verify_seed=no_verify_seed,
        min_age_days=min_age_days,
        command="abs-cleanup",
    )
    result = cmd_abs_cleanup(args)
    raise typer.Exit(result)


@app.command("abs-rename", rich_help_panel=ABS_COMMANDS)
def abs_rename(
    ctx: typer.Context,
    source: Annotated[
        Path | None,
        typer.Option(help="Directory to scan (default: ABS library from config)."),
    ] = None,
    pattern: Annotated[
        str,
        typer.Option(help="Glob pattern to filter folders."),
    ] = "*",
    fetch_metadata: Annotated[
        bool,
        typer.Option("--fetch-metadata", help="Fetch missing metadata from Audnex API."),
    ] = False,
    abs_search: Annotated[
        bool,
        typer.Option("--abs-search", help="Use ABS Audible search for ASIN resolution."),
    ] = False,
    abs_search_confidence: Annotated[
        float,
        typer.Option(help="Minimum confidence for ABS search matches."),
    ] = 0.75,
    interactive: Annotated[
        bool,
        typer.Option("--interactive", help="Prompt for confirmation on each rename."),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Rename files even when folder names are correct."),
    ] = False,
    report: Annotated[
        Path | None,
        typer.Option(help="Output JSON report of changes to file."),
    ] = None,
) -> None:
    """✏️  Rename folders to match MAM naming schema.

    Normalizes folder names in your Audiobookshelf library to follow
    the MAM naming convention for consistency.
    """
    from mamfast.commands import cmd_abs_rename

    args = get_args(
        ctx,
        source=source,
        pattern=pattern,
        fetch_metadata=fetch_metadata,
        abs_search=abs_search,
        abs_search_confidence=abs_search_confidence,
        interactive=interactive,
        force=force,
        report=report,
        command="abs-rename",
    )
    result = cmd_abs_rename(args)
    raise typer.Exit(result)


@app.command("abs-orphans", rich_help_panel=ABS_COMMANDS)
def abs_orphans(
    ctx: typer.Context,
    source: Annotated[
        Path | None,
        typer.Option(help="Directory to scan (default: ABS library from config)."),
    ] = None,
    cleanup: Annotated[
        bool,
        typer.Option("--cleanup", help="Remove orphaned folders (with matching audio folder)."),
    ] = False,
    cleanup_all: Annotated[
        bool,
        typer.Option("--cleanup-all", help="[red]DANGEROUS:[/] Remove ALL orphaned folders."),
    ] = False,
    min_match_score: Annotated[
        float,
        typer.Option(help="Minimum similarity score to consider a match."),
    ] = 0.5,
    report: Annotated[
        Path | None,
        typer.Option(help="Output JSON report of orphaned folders."),
    ] = None,
) -> None:
    """🔎 Find and clean up orphaned folders.

    Finds orphaned folders that have metadata.json but no audio files.
    These are often created by ABS when it creates duplicate library entries.
    """
    from mamfast.commands import cmd_abs_orphans

    args = get_args(
        ctx,
        source=source,
        cleanup=cleanup,
        cleanup_all=cleanup_all,
        min_match_score=min_match_score,
        report=report,
        command="abs-orphans",
    )
    result = cmd_abs_orphans(args)
    raise typer.Exit(result)


@app.command("abs-resolve-asins", rich_help_panel=ABS_COMMANDS)
def abs_resolve_asins(
    ctx: typer.Context,
    path: Annotated[
        Path | None,
        typer.Option(help="Specific folder to resolve (default: scan Unknown/)."),
    ] = None,
    confidence: Annotated[
        float,
        typer.Option(help="Minimum confidence threshold (0-1)."),
    ] = 0.75,
    write_sidecar: Annotated[
        bool,
        typer.Option("--write-sidecar", help="Write resolved ASINs to sidecar JSON files."),
    ] = False,
) -> None:
    """🔍 Resolve ASINs for Unknown/ books via ABS search.

    Searches Audible via ABS to find ASINs for books in Unknown/.
    """
    from mamfast.commands import cmd_abs_resolve_asins

    args = get_args(
        ctx,
        path=path,
        confidence=confidence,
        write_sidecar=write_sidecar,
        command="abs-resolve-asins",
    )
    result = cmd_abs_resolve_asins(args)
    raise typer.Exit(result)


# =============================================================================
# Libation Commands (Sub-app)
# =============================================================================


@libation_app.callback(invoke_without_command=True)
def libation_callback(ctx: typer.Context) -> None:
    """📚 Libation audiobook manager integration.

    Manage your Audible audiobook library through Libation.

    [bold]Commands:[/]
      mamfast libation scan        Scan for new purchases
      mamfast libation liberate    Download pending audiobooks
      mamfast libation status      Show library status
      mamfast libation search      Search your library
      mamfast libation guide       Show integration guide

    Running [cyan]mamfast libation[/] without a command shows library status.
    """
    if ctx.invoked_subcommand is None:
        # Default to status when no subcommand
        from mamfast.commands.libation import cmd_libation_status

        args = get_args(ctx, refresh=False, command="libation")
        result = cmd_libation_status(args)
        raise typer.Exit(result)


@libation_app.command("scan")
def libation_scan(
    ctx: typer.Context,
    liberate: Annotated[
        bool,
        typer.Option("--liberate", help="Also download new books after scanning."),
    ] = False,
) -> None:
    """🔍 Scan Audible library for new purchases.

    Checks your Audible account for new audiobook purchases.

    [bold]Examples:[/]
      mamfast libation scan              # Just scan
      mamfast libation scan --liberate   # Scan and download
    """
    from mamfast.commands.libation import cmd_libation_scan

    args = get_args(ctx, liberate=liberate, command="libation")
    result = cmd_libation_scan(args)
    raise typer.Exit(result)


@libation_app.command("liberate")
def libation_liberate(
    ctx: typer.Context,
    asin: Annotated[
        str | None,
        typer.Option(
            "--asin",
            callback=validate_asin_callback,
            help="Download specific ASIN only.",
        ),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompts."),
    ] = False,
) -> None:
    """📥 Download and decrypt pending audiobooks.

    Downloads all books with 'NotDownloaded' status from your library.

    [bold]Examples:[/]
      mamfast libation liberate            # Download all pending
      mamfast libation liberate --asin B0DK9T5P28  # Specific book
    """
    from mamfast.commands.libation import cmd_libation_liberate

    args = get_args(ctx, asin=asin, yes=yes, command="libation")
    result = cmd_libation_liberate(args)
    raise typer.Exit(result)


@libation_app.command("status")
def libation_status(
    ctx: typer.Context,
    refresh: Annotated[
        bool,
        typer.Option("--refresh", help="Force refresh library data."),
    ] = False,
) -> None:
    """📊 Show library status and statistics.

    Displays a summary of your audiobook library status.
    """
    from mamfast.commands.libation import cmd_libation_status

    args = get_args(ctx, refresh=refresh, command="libation")
    result = cmd_libation_status(args)
    raise typer.Exit(result)


class SearchFormat(str, Enum):
    """Search output format options."""

    table = "table"
    simple = "simple"
    json = "json"


@libation_app.command("search")
def libation_search(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Search query.")],
    limit: Annotated[
        int,
        typer.Option("--limit", "-n", help="Maximum results to show."),
    ] = 20,
    format_: Annotated[
        SearchFormat,
        typer.Option("--format", "-f", help="Output format."),
    ] = SearchFormat.table,
) -> None:
    """🔎 Search your audiobook library.

    Search for books by title, author, or ASIN.

    [bold]Examples:[/]
      mamfast libation search "Brandon Sanderson"
      mamfast libation search "Mistborn" --format json
    """
    from mamfast.commands.libation import cmd_libation_search

    args = get_args(ctx, query=query, limit=limit, format=format_.value, command="libation")
    result = cmd_libation_search(args)
    raise typer.Exit(result)


class ExportFormat(str, Enum):
    """Export format options."""

    json = "json"
    csv = "csv"


@libation_app.command("export")
def libation_export(
    ctx: typer.Context,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output file path."),
    ] = None,
    format_: Annotated[
        ExportFormat,
        typer.Option("--format", "-f", help="Export format."),
    ] = ExportFormat.json,
) -> None:
    """💾 Export library data to file.

    Export your library data to JSON or CSV format.

    [bold]Examples:[/]
      mamfast libation export -o library.json
      mamfast libation export -f csv -o library.csv
    """
    from mamfast.commands.libation import cmd_libation_export

    args = get_args(ctx, output=output, format=format_.value, command="libation")
    result = cmd_libation_export(args)
    raise typer.Exit(result)


@libation_app.command("settings")
def libation_settings(
    ctx: typer.Context,
    raw: Annotated[
        bool,
        typer.Option("--raw", help="Show raw settings output."),
    ] = False,
) -> None:
    """⚙️  View Libation configuration settings.

    Displays current Libation configuration.
    """
    from mamfast.commands.libation import cmd_libation_settings

    args = get_args(ctx, raw=raw, command="libation")
    result = cmd_libation_settings(args)
    raise typer.Exit(result)


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


@libation_app.command("books")
def libation_books(
    ctx: typer.Context,
    status: Annotated[
        BookStatus,
        typer.Option("--status", "-s", help="Filter by download status."),
    ] = BookStatus.all,
    format_: Annotated[
        BooksFormat,
        typer.Option("--format", "-f", help="Output format."),
    ] = BooksFormat.table,
    limit: Annotated[
        int,
        typer.Option("--limit", "-n", help="Maximum books to show."),
    ] = 50,
) -> None:
    """📚 List audiobooks in your library.

    Shows books with optional status filtering.

    [bold]Examples:[/]
      mamfast libation books
      mamfast libation books --status not_downloaded
      mamfast libation books --format json
    """
    from mamfast.commands.libation import cmd_libation_books

    # Map enum to handler's expected filter values
    status_mapping = {
        BookStatus.all: None,
        BookStatus.downloaded: "downloaded",
        BookStatus.not_downloaded: "pending",
        BookStatus.error: "error",
    }
    status_value = status_mapping.get(status)
    args = get_args(ctx, status=status_value, format=format_.value, limit=limit, command="libation")
    result = cmd_libation_books(args)
    raise typer.Exit(result)


@libation_app.command("redownload")
def libation_redownload(
    ctx: typer.Context,
    asin: Annotated[
        str,
        typer.Argument(
            metavar="ASIN", callback=validate_asin_callback, help="ASIN of book to redownload."
        ),
    ],
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt."),
    ] = False,
) -> None:
    """🔄 Re-download specific audiobook(s).

    Forces re-download of a specific audiobook by ASIN.

    [bold]Example:[/]
      mamfast libation redownload B0DK9T5P28
    """
    from mamfast.commands.libation import cmd_libation_redownload

    # Handler expects asins as a list
    args = get_args(ctx, asins=[asin], yes=yes, command="libation")
    result = cmd_libation_redownload(args)
    raise typer.Exit(result)


class SetStatusValue(str, Enum):
    """Available status values for set-status command."""

    downloaded = "Downloaded"
    not_downloaded = "NotDownloaded"


@libation_app.command("set-status")
def libation_set_status(
    ctx: typer.Context,
    asin: Annotated[
        str,
        typer.Argument(metavar="ASIN", callback=validate_asin_callback, help="ASIN of book."),
    ],
    status: Annotated[SetStatusValue, typer.Argument(help="New status.")],
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt."),
    ] = False,
) -> None:
    """📝 Set download status for books.

    Change the download status of a specific audiobook.

    [bold]Example:[/]
      mamfast libation set-status B0DK9T5P28 Downloaded
    """
    from mamfast.commands.libation import cmd_libation_set_status

    # Map status enum to handler's expected flags
    downloaded = status == SetStatusValue.downloaded
    not_downloaded = status == SetStatusValue.not_downloaded
    args = get_args(
        ctx,
        asins=[asin],
        downloaded=downloaded,
        not_downloaded=not_downloaded,
        yes=yes,
        command="libation",
    )
    result = cmd_libation_set_status(args)
    raise typer.Exit(result)


@libation_app.command("convert")
def libation_convert(
    ctx: typer.Context,
    asin: Annotated[
        str | None,
        typer.Option("--asin", callback=validate_asin_callback, help="Convert specific ASIN only."),
    ] = None,
    quality: Annotated[
        str | None,
        typer.Option("--quality", help="MP3 quality setting."),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt."),
    ] = False,
) -> None:
    """🔄 Convert M4B audiobooks to MP3.

    Converts audiobooks from M4B to MP3 format.

    [bold]Examples:[/]
      mamfast libation convert
      mamfast libation convert --asin B0DK9T5P28
    """
    from mamfast.commands.libation import cmd_libation_convert

    # Handler expects asins as a list
    asins = [asin] if asin else []
    args = get_args(ctx, asins=asins, quality=quality, yes=yes, command="libation")
    result = cmd_libation_convert(args)
    raise typer.Exit(result)


@libation_app.command("guide")
def libation_guide(
    ctx: typer.Context,
    section: Annotated[
        str | None,
        typer.Option("--section", "-s", help="Show specific section only."),
    ] = None,
) -> None:
    """📖 Show detailed integration guide.

    Comprehensive tutorial on using Libation with MAMFast.

    [bold]Sections:[/]
      overview, scanning, liberating, statuses, tips, troubleshooting
    """
    from mamfast.commands.libation import cmd_libation_guide

    args = get_args(ctx, section=section, command="libation")
    result = cmd_libation_guide(args)
    raise typer.Exit(result)


# =============================================================================
# Tools Commands
# =============================================================================


@tools_app.command("mamff")
def tools_mamff(
    ctx: typer.Context,
    path: Annotated[
        Path,
        typer.Argument(
            help="Path to release folder or audio file.",
            exists=True,
        ),
    ],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Output JSON path (default: same folder as audio file).",
        ),
    ] = None,
) -> None:
    """📝 Generate MAM fast-fill JSON for a release folder.

    Creates the JSON file used by MAM's fast-fill upload feature.
    Fetches metadata from Audnex and extracts info from MediaInfo.

    [bold]Examples:[/]
      mamfast tools mamff /path/to/release/folder
      mamfast tools mamff /path/to/book.m4b
      mamfast tools mamff ./folder --output ./custom.json

    [bold]What it does:[/]
      1. Extracts ASIN from folder/file name
      2. Fetches Audnex metadata (title, author, etc.)
      3. Fetches Audnex chapter data
      4. Runs MediaInfo on the audio file
      5. Generates the MAM JSON with BBCode description
    """
    from mamfast.commands.tools import cmd_tools_mamff

    args = get_args(ctx, path=path, output=output)
    result = cmd_tools_mamff(args)
    raise typer.Exit(result)


@tools_app.command("bbcode")
def tools_bbcode(
    ctx: typer.Context,
    asin: Annotated[
        str | None,
        typer.Option(
            "--asin",
            "-a",
            callback=validate_asin_callback,
            help="ASIN to fetch and convert.",
        ),
    ] = None,
    html: Annotated[
        str | None,
        typer.Option("--html", help="Raw HTML to convert to BBCode."),
    ] = None,
) -> None:
    """🔤 Test HTML to BBCode conversion.

    Debug tool for testing synopsis HTML to BBCode conversion.

    [bold]Examples:[/]
      mamfast tools bbcode --asin B073PG4DX8
      mamfast tools bbcode --html "<p><b>Bold</b> and <i>italic</i></p>"
    """
    from mamfast.commands.tools import cmd_tools_bbcode

    args = get_args(ctx, asin=asin, html=html)
    result = cmd_tools_bbcode(args)
    raise typer.Exit(result)


# =============================================================================
# Command Aliases (Shortcuts)
# =============================================================================

# Hidden aliases for common commands - show up in completion but not main help
app.command("dupes", hidden=True)(check_duplicates)
app.command("suspicious", hidden=True)(check_suspicious)
app.command("abs-dup", hidden=True)(abs_check_duplicate)
app.command("lint", hidden=True)(validate_config)


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
# Backwards-Compatible Exports (argparse tests + external callers)
# =============================================================================

# Many unit tests (and possibly downstream scripts) historically imported these
# symbols from `mamfast.cli`. The Typer CLI remains the entrypoint, but we
# re-export argparse parser + ABS command handlers to preserve compatibility.
from mamfast.cli_argparse import build_parser as build_parser  # noqa: E402
from mamfast.commands.abs import (  # noqa: E402,F401
    cmd_abs_check_duplicate,
    cmd_abs_cleanup,
    cmd_abs_import,
    cmd_abs_init,
    cmd_abs_resolve_asins,
    cmd_abs_restore,
    cmd_abs_trump_check,
)

__all__ = [
    "app",
    "main",
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
