"""State management commands.

Commands: state list, state prune, state retry, state clear, state export
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from shelfr.cli._helpers import get_args


def register_state_commands(state_app: typer.Typer) -> None:
    """Register state management commands on the state sub-app."""

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
        """List state entries.

        Shows processed and/or failed entries from the state file.

        [bold]Examples:[/]
          mamfast state list            # All entries
          mamfast state list --failed   # Only failed
          mamfast state list --json     # JSON output
        """
        from shelfr.commands import cmd_state

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
        """Remove stale entries with missing paths.

        Cleans up state entries whose files no longer exist.

        [bold]Tip:[/] Use [cyan]mamfast --dry-run state prune[/] to preview.
        """
        from shelfr.commands import cmd_state

        args = get_args(ctx, state_command="prune", command="state")
        result = cmd_state(args)
        raise typer.Exit(result)

    @state_app.command("retry")
    def state_retry(
        ctx: typer.Context,
        asin: Annotated[
            str, typer.Argument(metavar="ASIN", help="ASIN to clear from failed state.")
        ],
    ) -> None:
        """Clear a failed entry to allow re-processing.

        Removes the ASIN from failed state so it can be processed again.

        [bold]Example:[/]
          mamfast state retry B0DK9T5P28
        """
        from shelfr.commands import cmd_state

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
        """Clear a processed entry to force re-run.

        Removes the ASIN from processed state for full re-processing.

        [bold]Example:[/]
          mamfast state clear B0DK9T5P28
        """
        from shelfr.commands import cmd_state

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
        """Export state to JSON file.

        Exports the current state to a JSON file for backup or analysis.

        [bold]Examples:[/]
          mamfast state export                # Print to stdout
          mamfast state export -o backup.json # Save to file
        """
        from shelfr.commands import cmd_state

        args = get_args(ctx, state_command="export", output=output, command="state")
        result = cmd_state(args)
        raise typer.Exit(result)
