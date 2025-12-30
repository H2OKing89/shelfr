"""Libation commands (sub-app).

Commands: libation scan, libation liberate, libation status, libation search,
          libation export, libation settings, libation books, libation redownload,
          libation set-status, libation convert, libation guide
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from shelfr.cli._app import (
    BooksFormat,
    BookStatus,
    ExportFormat,
    SearchFormat,
    SetStatusValue,
    validate_asin_callback,
)
from shelfr.cli._helpers import get_args


def register_libation_commands(libation_app: typer.Typer) -> None:
    """Register Libation commands on the libation sub-app."""

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
            from shelfr.commands.libation import cmd_libation_status

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
        from shelfr.commands.libation import cmd_libation_scan

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
        from shelfr.commands.libation import cmd_libation_liberate

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
        from shelfr.commands.libation import cmd_libation_status

        args = get_args(ctx, refresh=refresh, command="libation")
        result = cmd_libation_status(args)
        raise typer.Exit(result)

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
        from shelfr.commands.libation import cmd_libation_search

        args = get_args(ctx, query=query, limit=limit, format=format_.value, command="libation")
        result = cmd_libation_search(args)
        raise typer.Exit(result)

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
        from shelfr.commands.libation import cmd_libation_export

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
        from shelfr.commands.libation import cmd_libation_settings

        args = get_args(ctx, raw=raw, command="libation")
        result = cmd_libation_settings(args)
        raise typer.Exit(result)

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
        from shelfr.commands.libation import cmd_libation_books

        # Map enum to handler's expected filter values
        status_mapping = {
            BookStatus.all: None,
            BookStatus.downloaded: "downloaded",
            BookStatus.not_downloaded: "pending",
            BookStatus.error: "error",
        }
        status_value = status_mapping.get(status)
        args = get_args(
            ctx, status=status_value, format=format_.value, limit=limit, command="libation"
        )
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
        from shelfr.commands.libation import cmd_libation_redownload

        # Handler expects asins as a list
        args = get_args(ctx, asins=[asin], yes=yes, command="libation")
        result = cmd_libation_redownload(args)
        raise typer.Exit(result)

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
        from shelfr.commands.libation import cmd_libation_set_status

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
            typer.Option(
                "--asin", callback=validate_asin_callback, help="Convert specific ASIN only."
            ),
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
        from shelfr.commands.libation import cmd_libation_convert

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
        from shelfr.commands.libation import cmd_libation_guide

        args = get_args(ctx, section=section, command="libation")
        result = cmd_libation_guide(args)
        raise typer.Exit(result)
