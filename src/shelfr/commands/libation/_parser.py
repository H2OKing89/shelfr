"""Argparse parser setup for Libation commands.

This module provides the argparse subparser configuration (deprecated, kept for compat).
"""

from __future__ import annotations

import argparse
import logging
from typing import Any

from shelfr.utils.validation import validate_asin

from .core import cmd_libation_liberate, cmd_libation_scan, cmd_libation_status
from .export_ import cmd_libation_export
from .guide import cmd_libation_guide
from .management import cmd_libation_convert, cmd_libation_redownload, cmd_libation_set_status
from .search import cmd_libation_books, cmd_libation_search
from .settings import cmd_libation_settings

logger = logging.getLogger(__name__)


def cmd_libation(args: argparse.Namespace) -> int:
    """Dispatcher for libation subcommands (default: status)."""
    from shelfr.console import console

    from ._ui import print_command_help

    libation_func = getattr(args, "libation_func", None)
    if libation_func:
        return int(libation_func(args))

    # No subcommand given - show status by default
    # But if --help was used, show command overview
    console.print("[bold cyan]Libation Integration[/]\n")
    console.print("Manage your Audible audiobook library through Libation.\n")

    print_command_help(
        "shelfr libation",
        "Wrapper for Libation CLI commands",
        [
            ("shelfr libation", "Show library status (default)"),
            ("shelfr libation scan", "Check for new Audible purchases"),
            ("shelfr libation scan --liberate", "Scan and download in one step"),
            ("shelfr libation liberate", "Download all pending audiobooks"),
            ("shelfr libation search 'query'", "Search your library"),
            ("shelfr libation guide", "Show detailed tutorial"),
        ],
    )

    # Show status as default action
    return cmd_libation_status(args)


def _validate_override(value: str) -> str:
    """Validate and normalize a Libation setting override (KEY=VALUE format).

    Args:
        value: Override string in KEY=VALUE format (e.g., FileDownloadQuality=Normal)

    Returns:
        The validated override string.

    Raises:
        argparse.ArgumentTypeError: If format is invalid.
    """
    if "=" not in value:
        raise argparse.ArgumentTypeError(
            f"Invalid override format: '{value}'. Use KEY=VALUE (e.g., FileDownloadQuality=Normal)"
        )
    key, _, val = value.partition("=")
    if not key.strip():
        raise argparse.ArgumentTypeError(f"Override key cannot be empty: '{value}'")
    return value


def add_libation_parser(subparsers: Any) -> None:
    """Add the libation command group to the CLI parser."""
    # Main libation parser
    libation_parser = subparsers.add_parser(
        "libation",
        help="Libation audiobook manager integration",
        description="Manage your Audible audiobook library through Libation",
        epilog="""
Examples:
  shelfr libation                    Show library status (default)
  shelfr libation scan               Check Audible for new purchases
  shelfr libation scan --liberate    Scan and download new books
  shelfr libation liberate           Download all pending audiobooks
  shelfr libation search "Sanderson" Search your library
  shelfr libation export -o lib.json Export library to JSON
  shelfr libation guide              Show detailed integration guide

Tip: Use 'shelfr --dry-run libation <cmd>' to preview without changes.
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    libation_parser.set_defaults(func=cmd_libation, libation_func=None)

    # Libation subcommands
    libation_sub = libation_parser.add_subparsers(
        dest="libation_cmd",
        title="commands",
        metavar="<command>",
    )

    # -------------------------------------------------------------------------
    # scan: Scan Audible library
    # -------------------------------------------------------------------------
    scan_parser = libation_sub.add_parser(
        "scan",
        help="Scan Audible library for new purchases",
        description=(
            "Check your Audible account for new book purchases and add them to Libation's database."
        ),
        epilog="""
What this does:
  1. Connects to Audible API via your saved credentials
  2. Compares your purchases against Libation's database
  3. NEW books are added with status 'NotLiberated' (pending download)

Note: This does NOT download any books. Use 'liberate' or '--liberate' for that.

Examples:
  shelfr libation scan              Scan only
  shelfr libation scan --liberate   Scan and download new books
""",
    )
    scan_parser.add_argument(
        "--liberate",
        action="store_true",
        help="Also download new books after scanning",
    )
    scan_parser.add_argument(
        "-o",
        "--override",
        action="append",
        type=_validate_override,
        metavar="KEY=VALUE",
        dest="overrides",
        help="Override Libation setting (can be used multiple times). "
        "Example: -o FileDownloadQuality=Normal -o UseWidevine=true",
    )
    scan_parser.set_defaults(libation_func=cmd_libation_scan)

    # -------------------------------------------------------------------------
    # liberate: Download audiobooks
    # -------------------------------------------------------------------------
    liberate_parser = libation_sub.add_parser(
        "liberate",
        help="Download and decrypt pending audiobooks",
        description="Download all audiobooks marked as 'NotLiberated' from your Audible library.",
        epilog="""
What this does:
  1. Finds all books with status 'NotLiberated'
  2. Downloads encrypted audio from Audible
  3. Decrypts to M4B format
  4. Saves to your configured Books folder

Examples:
  shelfr libation liberate                    Download all pending
  shelfr libation liberate --asin B0DK9T5P28  Download specific book
  shelfr libation liberate --force            Re-download existing books
""",
    )
    liberate_parser.add_argument(
        "--asin",
        type=validate_asin,
        metavar="ASIN",
        help="Download only this specific book (Audible ASIN, e.g., B0DK9T5P28)",
    )
    liberate_parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force re-download even if already liberated",
    )
    liberate_parser.add_argument(
        "--pdf",
        "-p",
        action="store_true",
        help="Only download PDFs (skip audiobook files)",
    )
    liberate_parser.add_argument(
        "-o",
        "--override",
        action="append",
        type=_validate_override,
        metavar="KEY=VALUE",
        dest="overrides",
        help="Override Libation setting (can be used multiple times). "
        "Example: -o FileDownloadQuality=Normal -o UseWidevine=true",
    )
    liberate_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    liberate_parser.set_defaults(libation_func=cmd_libation_liberate)

    # -------------------------------------------------------------------------
    # status: Show library status
    # -------------------------------------------------------------------------
    status_parser = libation_sub.add_parser(
        "status",
        help="Show library status and statistics",
        description="Display a dashboard of your Libation library status.",
    )
    status_parser.set_defaults(libation_func=cmd_libation_status)

    # -------------------------------------------------------------------------
    # search: Search library
    # -------------------------------------------------------------------------
    search_parser = libation_sub.add_parser(
        "search",
        help="Search your audiobook library",
        description="Search for books in your Libation library using Lucene query syntax.",
        epilog="""
Search syntax (Lucene):
  title:Mistborn          Search by title
  author:Sanderson        Search by author
  "exact phrase"          Exact phrase match
  fantasy AND epic        Boolean operators

Examples:
  shelfr libation search "Brandon Sanderson"
  shelfr libation search "title:Way of Kings"
  shelfr libation search "author:Reki" --limit 50
""",
    )
    search_parser.add_argument(
        "query",
        type=str,
        help="Search query (Lucene syntax supported)",
    )
    search_parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=20,
        help="Maximum results to show (default: 20)",
    )
    search_parser.set_defaults(libation_func=cmd_libation_search)

    # -------------------------------------------------------------------------
    # export: Export library data
    # -------------------------------------------------------------------------
    export_parser = libation_sub.add_parser(
        "export",
        help="Export library data to file",
        description="Export your Libation library to JSON, CSV, or Excel format.",
    )
    export_parser.add_argument(
        "-o",
        "--output",
        type=str,
        required=True,
        metavar="PATH",
        help="Output file path",
    )
    export_parser.add_argument(
        "--format",
        "-f",
        choices=["json", "csv", "xlsx"],
        default="json",
        help="Export format (default: json)",
    )
    export_parser.set_defaults(libation_func=cmd_libation_export)

    # -------------------------------------------------------------------------
    # settings: View settings
    # -------------------------------------------------------------------------
    settings_parser = libation_sub.add_parser(
        "settings",
        help="View Libation configuration settings",
        description="Display current Libation settings and configuration.",
    )
    settings_parser.add_argument(
        "setting",
        nargs="?",
        type=str,
        help="Specific setting name to view (optional)",
    )
    settings_parser.add_argument(
        "--list-enum",
        "-l",
        action="store_true",
        help="Show all possible values for enum settings",
    )
    settings_parser.set_defaults(libation_func=cmd_libation_settings)

    # -------------------------------------------------------------------------
    # books: List audiobooks with filtering
    # -------------------------------------------------------------------------
    books_parser = libation_sub.add_parser(
        "books",
        help="List audiobooks in your library",
        description="Display your audiobook library with optional filtering by status or author.",
        epilog="""
Status filter options:
  liberated / downloaded   Books that have been downloaded
  pending / notliberated   Books waiting to be downloaded
  error / failed           Books that failed to download

Examples:
  shelfr libation books                        List all books
  shelfr libation books --status pending       Show only pending downloads
  shelfr libation books --author "Sanderson"   Filter by author name
  shelfr libation books --limit 100            Show more results
  shelfr libation books --show-asin            Include ASIN column
""",
    )
    books_parser.add_argument(
        "--status",
        "-s",
        type=str,
        choices=["liberated", "downloaded", "pending", "notliberated", "error", "failed"],
        help="Filter by book status",
    )
    books_parser.add_argument(
        "--author",
        "-a",
        type=str,
        help="Filter by author name (partial match)",
    )
    books_parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=50,
        help="Maximum books to display (default: 50)",
    )
    books_parser.add_argument(
        "--show-asin",
        action="store_true",
        help="Show ASIN column in output",
    )
    books_parser.set_defaults(libation_func=cmd_libation_books)

    # -------------------------------------------------------------------------
    # redownload: Re-download specific books
    # -------------------------------------------------------------------------
    redownload_parser = libation_sub.add_parser(
        "redownload",
        help="Re-download specific audiobook(s)",
        description=(
            "Mark audiobook(s) as 'Not Downloaded' and then liberate them again. "
            "Useful when files are corrupted or you want a fresh download."
        ),
        epilog="""
This performs two steps:
  1. Marks the book as 'Not Downloaded' (set-status -n -f)
  2. Liberates (downloads) the book

Examples:
  shelfr libation redownload B0DK9T5P28
  shelfr libation redownload B0DK9T5P28 B0ABC1234X
  shelfr --dry-run libation redownload B0DK9T5P28
""",
    )
    redownload_parser.add_argument(
        "asins",
        nargs="+",
        type=validate_asin,
        metavar="ASIN",
        help="One or more book ASINs to re-download (e.g., B0DK9T5P28)",
    )
    redownload_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    redownload_parser.set_defaults(libation_func=cmd_libation_redownload)

    # -------------------------------------------------------------------------
    # set-status: Set download status for books
    # -------------------------------------------------------------------------
    set_status_parser = libation_sub.add_parser(
        "set-status",
        help="Set download status for books",
        description=(
            "Update download status based on whether audio files exist. "
            "Useful for syncing Libation's database with actual file state."
        ),
        epilog="""
Examples:
  shelfr libation set-status -d              Mark existing files as Downloaded
  shelfr libation set-status -n              Mark missing files as Not Downloaded
  shelfr libation set-status -d -n           Both operations
  shelfr libation set-status -n -f B0DK9T5P28   Force mark specific book
""",
    )
    set_status_parser.add_argument(
        "-d",
        "--downloaded",
        action="store_true",
        help="Mark books WITH audio files as 'Downloaded'",
    )
    set_status_parser.add_argument(
        "-n",
        "--not-downloaded",
        action="store_true",
        help="Mark books WITHOUT audio files as 'Not Downloaded'",
    )
    set_status_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force set status regardless of file existence",
    )
    set_status_parser.add_argument(
        "asins",
        nargs="*",
        type=validate_asin,
        metavar="ASIN",
        help="Specific book ASINs (optional, default: all books)",
    )
    set_status_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    set_status_parser.set_defaults(libation_func=cmd_libation_set_status)

    # -------------------------------------------------------------------------
    # convert: Convert M4B to MP3
    # -------------------------------------------------------------------------
    convert_parser = libation_sub.add_parser(
        "convert",
        help="Convert M4B audiobooks to MP3",
        description="Convert M4B (AAC) audiobook files to MP3 format.",
        epilog="""
Conversion settings (bitrate, mono/stereo, etc.) are configured in Libation.
Use 'shelfr libation settings' to view current settings.

Examples:
  shelfr libation convert                    Convert all books
  shelfr libation convert B0DK9T5P28         Convert specific book
""",
    )
    convert_parser.add_argument(
        "asins",
        nargs="*",
        type=validate_asin,
        metavar="ASIN",
        help="Specific book ASINs to convert (optional, default: all)",
    )
    convert_parser.set_defaults(libation_func=cmd_libation_convert)

    # -------------------------------------------------------------------------
    # guide: Detailed tutorial/guide
    # -------------------------------------------------------------------------
    guide_parser = libation_sub.add_parser(
        "guide",
        help="Show detailed tutorial and integration guide",
        description="Comprehensive guide to using Libation with MAMFast.",
    )
    guide_parser.set_defaults(libation_func=cmd_libation_guide)


__all__ = ["add_libation_parser", "cmd_libation"]
