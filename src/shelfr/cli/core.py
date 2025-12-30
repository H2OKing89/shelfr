"""Core pipeline commands.

Commands: run, status, config
"""

from __future__ import annotations

from typing import Annotated

import typer

from shelfr.cli._app import CORE_COMMANDS
from shelfr.cli._helpers import get_args


def register_core_commands(app: typer.Typer) -> None:
    """Register core pipeline commands on the app."""

    # NOTE: scan, discover removed - use `mamfast libation scan/liberate/books` instead
    # NOTE: prepare moved to `mamfast tools prepare`
    # NOTE: torrent, upload removed - workflow handles these; future mkbrr/qbit wrappers planned

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
          mamfast run               [dim]# Full pipeline[/]
          mamfast --dry-run run     [dim]# Preview without changes[/]
          mamfast run --skip-scan   [dim]# Skip Libation scan[/]

        [bold cyan]💡 Tips:[/]
          • Always run [green]mamfast check[/] first to verify your setup
          • Use [green]--dry-run[/] to preview what will happen
          • Check [green]mamfast status[/] to see pending releases
        """
        from shelfr.console import console

        # Handle misplaced --dry-run flag
        if dry_run_hint:
            console.print(
                "[yellow]⚠️  --dry-run must come BEFORE the subcommand:[/]\n\n"
                "    [green]mamfast --dry-run run[/]  ✓\n"
                "    [red]mamfast run --dry-run[/]  ✗\n"
            )
            raise typer.Exit(2)

        from shelfr.commands import cmd_run

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

        Displays a summary of discovered, staged, and processed releases
        with their current status in the pipeline.

        [bold]What you'll see:[/]
          • Pending releases waiting to be processed
          • Staged releases ready for upload
          • Recently uploaded releases
          • Any failed releases that need attention
        """
        from shelfr.commands import cmd_status

        args = get_args(ctx, command="status")
        result = cmd_status(args)
        raise typer.Exit(result)

    @app.command(rich_help_panel=CORE_COMMANDS)
    def config(ctx: typer.Context) -> None:
        """⚙️  Print loaded configuration.

        Shows the current configuration values for debugging.
        Useful for verifying paths and settings are correct.

        [bold cyan]💡 Tip:[/] Run [green]mamfast check[/] for a more thorough
        configuration validation with health checks.
        """
        from shelfr.commands import cmd_config

        args = get_args(ctx, command="config")
        result = cmd_config(args)
        raise typer.Exit(result)
