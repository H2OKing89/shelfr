"""MAM sub-app commands.

Commands for MAM tracker workflows:
- mam bbcode: Output raw BBCode description (copyable)
- mam render: Render BBCode visually in terminal
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer

logger = logging.getLogger(__name__)


def register_mam_commands(mam_app: typer.Typer) -> None:
    """Register mam commands on the mam sub-app."""

    @mam_app.callback(invoke_without_command=True)
    def mam_callback(ctx: typer.Context) -> None:
        """📤 MAM tracker workflows.

        [bold]Commands:[/]
          shelfr mam bbcode <path>   Output raw BBCode (copyable)
          shelfr mam render <path>   Render BBCode visually

        Running [cyan]shelfr mam[/] without a command shows this help.
        """
        if ctx.invoked_subcommand is None:
            from shelfr.console import console

            console.print(ctx.get_help())
            raise typer.Exit(0)

    @mam_app.command("bbcode")
    def mam_bbcode(
        ctx: typer.Context,
        path: Annotated[
            Path,
            typer.Argument(
                help="Path to release folder or audio file.",
                exists=True,
            ),
        ],
    ) -> None:
        """🔤 Output raw BBCode description for a release.

        Outputs the MAM BBCode description as plain text for easy copying.
        Use this when you need the raw BBCode to paste into MAM.

        [bold]Examples:[/]
          shelfr mam bbcode /path/to/release/folder
          shelfr mam bbcode /path/to/book.m4b

        [bold]What it does:[/]
          1. Extracts ASIN from folder/file name
          2. Fetches Audnex metadata
          3. Outputs raw BBCode to terminal (copyable)

        [dim]💡 For visual preview, use 'shelfr mam render' instead.[/]
        """
        from shelfr.cli._helpers import get_args
        from shelfr.commands.mam import cmd_mam_bbcode

        args = get_args(ctx, path=path, command="mam-bbcode")
        result = cmd_mam_bbcode(args)
        raise typer.Exit(result)

    @mam_app.command("render")
    def mam_render(
        ctx: typer.Context,
        path: Annotated[
            Path,
            typer.Argument(
                help="Path to release folder or audio file.",
                exists=True,
            ),
        ],
    ) -> None:
        """🖼️  Render BBCode visually in terminal.

        Renders the MAM BBCode description using Rich formatting,
        showing approximately how it will appear on MAM.

        [bold]Examples:[/]
          shelfr mam render /path/to/release/folder
          shelfr mam render /path/to/book.m4b

        [bold]What it does:[/]
          1. Extracts ASIN from folder/file name
          2. Fetches Audnex metadata
          3. Renders BBCode visually with colors and formatting

        [dim]⚠️  Note: MAM's upload page renderer has a bug that shows ASCII art[/]
        [dim]   crooked. The actual torrent page will render correctly.[/]

        [dim]💡 For raw BBCode to copy, use 'shelfr mam bbcode' instead.[/]
        """
        from shelfr.cli._helpers import get_args
        from shelfr.commands.mam import cmd_mam_render

        args = get_args(ctx, path=path, command="mam-render")
        result = cmd_mam_render(args)
        raise typer.Exit(result)
