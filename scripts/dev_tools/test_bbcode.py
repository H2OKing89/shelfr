#!/usr/bin/env python3
"""Quick CLI tool to test BBCode generation from Audnex data.

Usage:
    python scripts/test_bbcode.py B073PG4DX8    # Test with ASIN
    python scripts/test_bbcode.py --json path/to/audnex.json  # Test with local JSON
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.markup import escape

from mamfast.console import console
from mamfast.metadata import (
    _html_to_bbcode,
    fetch_audnex_book,
    render_bbcode_description,
)
from mamfast.utils.validation import validate_asin


def test_html_to_bbcode(html: str) -> None:
    """Test HTML to BBCode conversion."""
    console.print("\n[bold cyan]═══ HTML to BBCode Conversion ═══[/bold cyan]")
    console.print("\n[dim]Input HTML:[/dim]")
    # Escape BBCode-like brackets for Rich display
    console.print(escape(html[:500] + "..." if len(html) > 500 else html))

    result = _html_to_bbcode(html)
    console.print("\n[dim]Output BBCode:[/dim]")
    # Escape BBCode brackets so they display literally instead of being interpreted as Rich markup
    console.print(escape(result))


def test_full_render(asin: str, audnex_data: dict | None = None) -> None:
    """Test full BBCode description rendering."""
    console.print(f"\n[bold cyan]═══ Full BBCode Render for {asin} ═══[/bold cyan]")

    if audnex_data is None:
        console.print(f"\n[dim]Fetching Audnex data for {asin}...[/dim]")
        audnex_data, _region = fetch_audnex_book(asin)
        if not audnex_data:
            console.print(f"[red]Failed to fetch Audnex data for {asin}[/red]")
            return

    console.print(f"\n[dim]Title:[/dim] {audnex_data.get('title', 'Unknown')}")
    console.print(f"[dim]Summary HTML length:[/dim] {len(audnex_data.get('summary', ''))}")

    # Test synopsis conversion
    summary = audnex_data.get("summary", "")
    if summary:
        console.print("\n[bold yellow]── Synopsis HTML ──[/bold yellow]")
        console.print(escape(summary[:300] + "..." if len(summary) > 300 else summary))

        console.print("\n[bold yellow]── Synopsis BBCode ──[/bold yellow]")
        bbcode_synopsis = _html_to_bbcode(summary)
        console.print(escape(bbcode_synopsis))

    # Test full render
    console.print("\n[bold green]── Full BBCode Description ──[/bold green]")
    result = render_bbcode_description(
        audnex_data=audnex_data,
        mediainfo_data=None,
        asin=asin,
        audnex_chapters=None,
    )
    console.print(escape(result))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test BBCode generation from Audnex data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/test_bbcode.py B073PG4DX8
    python scripts/test_bbcode.py --json path/to/audnex.json
    python scripts/test_bbcode.py --html "<p><b>Bold</b> and <i>italic</i></p>"
        """,
    )

    parser.add_argument(
        "asin",
        nargs="?",
        type=validate_asin,
        help="ASIN to fetch and test",
    )
    parser.add_argument(
        "--json",
        type=Path,
        help="Path to local Audnex JSON file",
    )
    parser.add_argument(
        "--html",
        type=str,
        help="Test HTML to BBCode conversion directly",
    )

    args = parser.parse_args()

    if args.html:
        test_html_to_bbcode(args.html)
        return 0

    if args.json:
        if not args.json.exists():
            console.print(f"[red]File not found: {args.json}[/red]")
            return 1
        with open(args.json, encoding="utf-8") as f:
            audnex_data = json.load(f)
        asin = audnex_data.get("asin", "UNKNOWN")
        test_full_render(asin, audnex_data)
        return 0

    if args.asin:
        test_full_render(args.asin)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
