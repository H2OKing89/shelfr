"""MAM command handlers.

Handlers for MAM-related CLI commands:
- cmd_mam_bbcode: Output raw BBCode
- cmd_mam_render: Render BBCode visually
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from shelfr.console import console, print_error, print_info

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


def _fetch_metadata_for_path(
    path: Path,
) -> tuple[Path | None, str | None, dict | None, dict | None, dict | None]:
    """Fetch metadata for a given path.

    Returns:
        Tuple of (audio_file, asin, audnex_data, mediainfo_data, audnex_chapters)
    """
    from shelfr.metadata import fetch_all_metadata

    # Determine folder and find audio file
    if path.is_file():
        folder = path.parent
        audio_file = path if path.suffix.lower() in AUDIO_EXTENSIONS else None
    else:
        folder = path
        audio_file = _find_audio_file(path)

    if not audio_file:
        return None, None, None, None, None

    # Extract ASIN
    asin = _extract_asin(audio_file) or _extract_asin(folder)
    if not asin:
        return audio_file, None, None, None, None

    # Fetch metadata
    audnex_data, mediainfo_data, audnex_chapters = fetch_all_metadata(
        asin=asin,
        m4b_path=audio_file,
        output_dir=folder,
        save_intermediate=False,
    )

    return audio_file, asin, audnex_data, mediainfo_data, audnex_chapters


def cmd_mam_bbcode(args: argparse.Namespace) -> int:
    """Output raw BBCode description for a release.

    Args:
        args: Namespace with 'path'

    Returns:
        Exit code (0 for success)
    """
    from shelfr.metadata import render_bbcode_description

    path: Path = args.path.resolve()

    audio_file, asin, audnex_data, mediainfo_data, audnex_chapters = (
        _fetch_metadata_for_path(path)
    )

    if not audio_file:
        print_error("No audio file found (.m4b, .mp3, .m4a, .flac, .ogg)")
        return 1

    if not asin:
        print_error("Could not extract ASIN from folder or file name")
        print_info("Expected format: {ASIN_B0XXXXXXXXX} in name")
        return 1

    if not audnex_data:
        print_error("Audnex metadata not found")
        return 1

    if not mediainfo_data:
        print_error("MediaInfo extraction failed")
        return 1

    # Generate BBCode description
    bbcode_description = render_bbcode_description(
        audnex_data=audnex_data,
        mediainfo_data=mediainfo_data,
        asin=asin,
        audnex_chapters=audnex_chapters,
    )

    if not bbcode_description:
        print_error("Failed to generate BBCode description")
        return 1

    # Output plain text (not wrapped in Rich formatting) for easy copying
    print(bbcode_description)

    return 0


def cmd_mam_render(args: argparse.Namespace) -> int:
    """Render BBCode description visually.

    Args:
        args: Namespace with 'path'

    Returns:
        Exit code (0 for success)
    """
    from shelfr.metadata import render_bbcode_description
    from shelfr.utils.bbcode_renderer import render_bbcode_preview

    path: Path = args.path.resolve()

    audio_file, asin, audnex_data, mediainfo_data, audnex_chapters = (
        _fetch_metadata_for_path(path)
    )

    if not audio_file:
        print_error("No audio file found (.m4b, .mp3, .m4a, .flac, .ogg)")
        return 1

    if not asin:
        print_error("Could not extract ASIN from folder or file name")
        print_info("Expected format: {ASIN_B0XXXXXXXXX} in name")
        return 1

    if not audnex_data:
        print_error("Audnex metadata not found")
        return 1

    if not mediainfo_data:
        print_error("MediaInfo extraction failed")
        return 1

    # Generate BBCode description
    bbcode_description = render_bbcode_description(
        audnex_data=audnex_data,
        mediainfo_data=mediainfo_data,
        asin=asin,
        audnex_chapters=audnex_chapters,
    )

    if not bbcode_description:
        print_error("Failed to generate BBCode description")
        return 1

    # Render visually
    title = audnex_data.get("title", "BBCode Preview")
    render_bbcode_preview(bbcode_description, console, title=f"📖 {title}")

    return 0
