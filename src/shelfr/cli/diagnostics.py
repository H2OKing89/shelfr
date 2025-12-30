"""Diagnostics commands.

Commands: check, validate, validate-config, preview-naming, check-duplicates, check-suspicious
"""

from __future__ import annotations

from typing import Annotated

import typer

from shelfr.cli._app import DIAG_COMMANDS, AsinArg
from shelfr.cli._helpers import get_args


def register_diagnostics_commands(app: typer.Typer) -> None:
    """Register diagnostics commands on the app."""

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
        [bold cyan]Run this first[/] before using other commands!

        [bold]Checks performed:[/]
          • Configuration file syntax and values
          • Required paths exist and are writable
          • Service connections (qBittorrent, ABS, Audnex)

        [bold]Examples:[/]
          mamfast check                [dim]# Run all checks[/]
          mamfast check --config-only  [dim]# Configuration only[/]
          mamfast check --services-only [dim]# Test service connections[/]

        [bold cyan]💡 Tip:[/] Run this after any configuration changes!
        """
        from shelfr.commands import cmd_check

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
        Useful for catching issues before running the full pipeline.

        [bold]What gets validated:[/]
          • Metadata completeness (author, title, ASIN)
          • Folder naming correctness
          • Audio file presence and format

        [bold]Examples:[/]
          mamfast validate               [dim]# Validate all[/]
          mamfast validate -a B0DK9T5P28 [dim]# Validate specific ASIN[/]
          mamfast validate --json        [dim]# JSON output[/]
        """
        from shelfr.commands import cmd_validate

        args = get_args(ctx, asin=asin, json=json_output, command="validate")
        result = cmd_validate(args)
        raise typer.Exit(result)

    @app.command("validate-config", rich_help_panel=DIAG_COMMANDS)
    def validate_config(ctx: typer.Context) -> None:
        """📝 Validate configuration files.

        Checks naming.json, config.yaml, and other config files for errors.

        [bold cyan]💡 Tip:[/] Run this after editing any config files to catch
        syntax errors or invalid values before they cause problems.
        """
        from shelfr.commands import cmd_validate_config

        args = get_args(ctx, command="validate-config")
        result = cmd_validate_config(args)
        raise typer.Exit(result)

    @app.command("preview-naming", rich_help_panel=DIAG_COMMANDS)
    def preview_naming_cmd(
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
        without making any changes. Great for testing naming rules!

        [bold]Examples:[/]
          mamfast preview-naming               [dim]# Preview first 20[/]
          mamfast preview-naming -n 50         [dim]# Preview 50 releases[/]
          mamfast preview-naming -a B0DK9T5P28 [dim]# Preview specific ASIN[/]

        [bold cyan]💡 Tip:[/] Use this to verify naming.json rules work correctly
        before running the full pipeline.
        """
        from shelfr.commands import cmd_preview_naming

        args = get_args(ctx, limit=limit, asin=asin, json=json_output, command="preview-naming")
        result = cmd_preview_naming(args)
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
        Helps avoid uploading the same audiobook twice!

        [bold]Examples:[/]
          mamfast check-duplicates          [dim]# Default 85% threshold[/]
          mamfast check-duplicates -t 90    [dim]# Stricter matching[/]
          mamfast check-duplicates --json   [dim]# JSON output[/]

        [bold cyan]💡 Tip:[/] Higher threshold = stricter matching.
        Use 90%+ for more exact matches, 80% for looser detection.
        """
        from shelfr.commands import cmd_check_duplicates

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
        from shelfr.commands import cmd_check_suspicious

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

    # Command Aliases
    app.command("dupes", hidden=True)(check_duplicates)
    app.command("suspicious", hidden=True)(check_suspicious)
    app.command("lint", hidden=True)(validate_config)
    app.command("doctor", hidden=True)(check)
