"""
Tool commands for troubleshooting and testing.

This module provides CLI tools for debugging and testing MAM upload functionality:
- mamff: Generate MAM fast-fill JSON for a release
- bbcode: Test HTML to BBCode conversion
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from rich.markup import escape
from rich.panel import Panel

from shelfr.console import console, print_error, print_info, print_success
from shelfr.metadata import _html_to_bbcode

logger = logging.getLogger(__name__)

# Audio file extensions to look for
AUDIO_EXTENSIONS = {".m4b", ".mp3", ".m4a", ".flac", ".ogg"}


def _find_audio_file(path: Path) -> Path | None:
    """Find audio file from a path (file or folder)."""
    if path.is_file():
        if path.suffix.lower() in AUDIO_EXTENSIONS:
            return path
        return None

    # Search folder for audio files (prefer m4b)
    for ext in [".m4b", ".mp3", ".m4a", ".flac", ".ogg"]:
        files = sorted(path.glob(f"*{ext}"))
        if files:
            return files[0]

    return None


def _extract_asin(path: Path) -> str | None:
    """Extract ASIN from path name."""
    from shelfr.discovery import extract_asin_from_name

    # Try folder name first
    asin = extract_asin_from_name(path.name)
    if asin:
        return asin

    # Try parent folder if path is a file
    if path.is_file():
        asin = extract_asin_from_name(path.parent.name)
        if asin:
            return asin

    return None


def cmd_tools_mamff(args: argparse.Namespace) -> int:
    """Generate MAM fast-fill JSON for a release folder.

    This tool:
    1. Extracts ASIN from folder/file name
    2. Fetches Audnex metadata
    3. Fetches Audnex chapter data
    4. Runs MediaInfo on the audio file
    5. Generates the MAM JSON with BBCode description

    Args:
        args: Namespace with 'path' and optional 'output'

    Returns:
        Exit code (0 for success)
    """
    from shelfr.metadata import (
        build_mam_json,
        fetch_all_metadata,
        save_mam_json,
    )
    from shelfr.models import AudiobookRelease

    path: Path = args.path.resolve()
    output_path: Path | None = args.output

    console.print(Panel.fit("📝 MAM Fast-Fill JSON Generator", style="bold blue"))
    console.print()

    # Determine folder and find audio file
    if path.is_file():
        folder = path.parent
        audio_file = path if path.suffix.lower() in AUDIO_EXTENSIONS else None
    else:
        folder = path
        audio_file = _find_audio_file(path)

    console.print(f"[bold]Folder:[/] {escape(str(folder))}")

    if audio_file:
        console.print(f"[bold]Audio:[/]  {escape(audio_file.name)}")
    else:
        print_error("No audio file found (.m4b, .mp3, .m4a, .flac, .ogg)")
        return 1

    # Extract ASIN
    asin = _extract_asin(audio_file) or _extract_asin(folder)
    if asin:
        console.print(f"[bold]ASIN:[/]   {asin}")
    else:
        print_error("Could not extract ASIN from folder or file name")
        print_info("Expected format: {ASIN_B0XXXXXXXXX} in name")
        return 1

    console.print()

    # Fetch metadata
    console.print("[dim]Fetching metadata...[/]")
    audnex_data, mediainfo_data, audnex_chapters = fetch_all_metadata(
        asin=asin,
        m4b_path=audio_file,
        output_dir=folder,
        save_intermediate=False,
    )

    if audnex_data:
        title = audnex_data.get("title", "Unknown")
        print_success(f"Audnex: {escape(str(title))}")
    else:
        print_error("Audnex metadata not found")
        return 1

    if audnex_chapters:
        chapter_count = len(audnex_chapters.get("chapters", []))
        print_success(f"Chapters: {chapter_count}")
    else:
        print_info("Chapters: not available")

    if mediainfo_data:
        print_success("MediaInfo: extracted")
    else:
        print_error("MediaInfo: failed")
        return 1

    console.print()

    # Build MAM JSON
    release = AudiobookRelease(
        asin=asin,
        staging_dir=folder,
        main_m4b=audio_file,
        audnex_metadata=audnex_data,
        mediainfo_data=mediainfo_data,
        audnex_chapters=audnex_chapters,
    )

    # audnex_chapters already on release; use it from there
    mam_data = build_mam_json(release)

    if not mam_data.get("title"):
        print_error("Failed to generate MAM JSON (no title)")
        return 1

    # Determine output path
    if output_path is None:
        output_path = folder / f"{folder.name}.json"

    # Save JSON
    save_mam_json(mam_data, output_path)
    print_success(f"Saved: {escape(str(output_path))}")

    console.print()

    # Show BBCode description preview
    description = mam_data.get("description", "")
    if description:
        console.print(
            Panel(
                escape(description),
                title="[bold]BBCode Description Preview[/]",
                border_style="cyan",
            )
        )

    return 0


def cmd_tools_bbcode(args: argparse.Namespace) -> int:
    """Test HTML to BBCode conversion.

    Debug tool for testing synopsis conversion.

    Args:
        args: Namespace with optional 'asin' or 'html'

    Returns:
        Exit code (0 for success)
    """
    asin: str | None = args.asin
    html_input: str | None = args.html

    console.print(Panel.fit("🔤 HTML → BBCode Converter", style="bold blue"))
    console.print()

    if not asin and not html_input:
        print_error("Provide --asin or --html")
        print_info("Example: shelfr tools bbcode --asin B073PG4DX8")
        print_info("Example: shelfr tools bbcode --html '<p><b>Bold</b></p>'")
        return 1

    original_html: str = ""

    if asin:
        # Fetch from Audnex
        console.print(f"[bold]ASIN:[/] {asin}")
        console.print("[dim]Fetching from Audnex...[/]")

        from shelfr.metadata import fetch_audnex_book

        audnex_result = fetch_audnex_book(asin)
        audnex_data, _region = audnex_result
        if not audnex_data:
            print_error(f"No data found for ASIN: {asin}")
            return 1

        original_html = audnex_data.get("summary", "")
        if not original_html:
            print_error("No summary field in Audnex data")
            return 1

        print_success(f"Fetched: {audnex_data.get('title', 'Unknown')}")
        console.print()

    elif html_input:
        original_html = html_input

    # Show original HTML
    console.print(
        Panel(
            escape(original_html),
            title="[bold]Original HTML[/]",
            border_style="yellow",
        )
    )
    console.print()

    # Convert to BBCode
    bbcode = _html_to_bbcode(original_html)

    # Show BBCode output (escaped so Rich doesn't interpret it)
    console.print(
        Panel(
            escape(bbcode),
            title="[bold]BBCode Output[/]",
            border_style="green",
        )
    )

    return 0
