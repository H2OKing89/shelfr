#!/usr/bin/env python3
"""Scan ABS library and export structure to JSON for edge case analysis.

Features:
- Recursive folder scanning with component detection
- Mediainfo extraction (codec, bitrate, duration)
- Async processing with configurable workers
- Rich progress display
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

console = Console()

# Audio file extensions to detect "leaf" folders
AUDIO_EXTENSIONS = {".m4b", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".aac"}

# Patterns to extract components
ASIN_PATTERNS = [
    re.compile(r"\{ASIN[.:](B[A-Z0-9]{9})\}"),  # {ASIN.xxx} or {ASIN:xxx}
    re.compile(r"\[(B[A-Z0-9]{9})\]"),  # [Bxxxxxxxxx] legacy
]
YEAR_PATTERN = re.compile(r"\((\d{4})\)")
RIPPER_TAG_PATTERN = re.compile(r"\[([A-Za-z0-9_-]+)\]$")
VOLUME_PATTERN = re.compile(r"vol[_.]?(\d+(?:\.\d+)?)", re.IGNORECASE)

# Edition flags to detect
EDITION_FLAGS = [
    "Full-Cast",
    "Full Cast",
    "Full-Cast Edition",
    "Dolby Atmos",
    "Atmos",
    "Unabridged",
    "Abridged",
    "Dramatized",
    "Dramatized Adaptation",
    "Graphic Audio",
    "GraphicAudio",
]


@dataclass
class MediaInfo:
    """Media information for audio files in a folder."""

    codec: str | None = None
    bitrate_kbps: int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    duration_seconds: float | None = None
    file_count: int = 0
    total_size_mb: float = 0.0
    is_multi_file: bool = False
    files: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class FolderInfo:
    """Information about a folder in the library."""

    path: str
    name: str
    depth: int
    is_leaf: bool  # Contains audio files
    has_children_with_audio: bool  # Has subfolders with audio
    audio_files: list[str]
    other_files: list[str]
    subfolders: list[str]
    # Parsed components
    detected_asin: str | None
    detected_year: str | None
    detected_ripper_tag: str | None
    detected_volume: str | None
    detected_edition_flags: list[str]
    # Format analysis
    uses_braces_asin: bool  # {ASIN.xxx}
    uses_bracket_asin: bool  # [Bxxxxxxxxx]
    uses_parens: bool  # (Year) (Author)
    uses_brackets: bool  # [Year] [Author]
    # Media info
    mediainfo: MediaInfo | None = None


def get_mediainfo_json(file_path: Path) -> dict[str, Any] | None:
    """Get mediainfo for a single file as JSON."""
    try:
        result = subprocess.run(
            ["mediainfo", "--Output=JSON", str(file_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            data: dict[str, Any] = json.loads(result.stdout)
            return data
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass  # Skip files with mediainfo errors - missing tool or invalid output
    return None


def parse_mediainfo(mi_json: dict[str, Any]) -> dict[str, Any]:
    """Parse mediainfo JSON into simplified dict."""
    result: dict[str, Any] = {
        "codec": None,
        "bitrate_kbps": None,
        "sample_rate": None,
        "channels": None,
        "duration_seconds": None,
        "size_bytes": None,
    }

    if not mi_json or "media" not in mi_json:
        return result

    tracks = mi_json.get("media", {}).get("track", [])

    for track in tracks:
        track_type = track.get("@type", "")

        if track_type == "General":
            # Duration in seconds
            if "Duration" in track:
                with contextlib.suppress(ValueError, TypeError):
                    result["duration_seconds"] = float(track["Duration"])
            # File size
            if "FileSize" in track:
                with contextlib.suppress(ValueError, TypeError):
                    result["size_bytes"] = int(track["FileSize"])

        elif track_type == "Audio":
            # Codec
            if "Format" in track:
                codec = track["Format"]
                # Add profile for AAC variants
                if codec == "AAC" and "Format_Profile" in track:
                    profile = track["Format_Profile"]
                    if "HE-AAC" in profile or "xHE" in profile.upper():
                        codec = "xHE-AAC" if "xHE" in profile.upper() else "HE-AAC"
                    elif "LC" in profile:
                        codec = "AAC LC"
                result["codec"] = codec

            # Bitrate (prefer BitRate, fall back to BitRate_Nominal)
            for br_key in ["BitRate", "BitRate_Nominal"]:
                if br_key in track:
                    try:
                        result["bitrate_kbps"] = int(float(track[br_key]) / 1000)
                        break
                    except (ValueError, TypeError):
                        pass  # Skip malformed bitrate value, try next key

            # Sample rate
            if "SamplingRate" in track:
                with contextlib.suppress(ValueError, TypeError):
                    result["sample_rate"] = int(float(track["SamplingRate"]))

            # Channels
            if "Channels" in track:
                with contextlib.suppress(ValueError, TypeError):
                    result["channels"] = int(track["Channels"])

    return result


def get_folder_mediainfo(folder: Path, audio_files: list[str]) -> MediaInfo:
    """Get aggregated mediainfo for all audio files in a folder."""
    info = MediaInfo()
    info.file_count = len(audio_files)
    info.is_multi_file = len(audio_files) > 1

    if not audio_files:
        return info

    total_duration = 0.0
    total_size = 0
    total_bitrate = 0
    bitrate_count = 0
    codecs = set()
    sample_rates = set()
    channels_set = set()
    file_details = []

    for audio_file in audio_files:
        file_path = folder / audio_file
        if not file_path.exists():
            continue

        mi_json = get_mediainfo_json(file_path)
        if mi_json is None:
            continue
        parsed = parse_mediainfo(mi_json)

        file_info = {"name": audio_file}

        if parsed["duration_seconds"]:
            total_duration += parsed["duration_seconds"]
            file_info["duration_seconds"] = parsed["duration_seconds"]

        if parsed["size_bytes"]:
            total_size += parsed["size_bytes"]

        if parsed["bitrate_kbps"]:
            total_bitrate += parsed["bitrate_kbps"]
            bitrate_count += 1
            file_info["bitrate_kbps"] = parsed["bitrate_kbps"]

        if parsed["codec"]:
            codecs.add(parsed["codec"])
            file_info["codec"] = parsed["codec"]

        if parsed["sample_rate"]:
            sample_rates.add(parsed["sample_rate"])

        if parsed["channels"]:
            channels_set.add(parsed["channels"])

        file_details.append(file_info)

    # Aggregate results
    info.duration_seconds = total_duration if total_duration > 0 else None
    info.total_size_mb = round(total_size / (1024 * 1024), 2) if total_size > 0 else 0.0
    info.bitrate_kbps = round(total_bitrate / bitrate_count) if bitrate_count > 0 else None

    # Use most common codec, or list if mixed
    if len(codecs) == 1:
        info.codec = codecs.pop()
    elif len(codecs) > 1:
        info.codec = "/".join(sorted(codecs))

    # Use most common sample rate
    if sample_rates:
        info.sample_rate = max(sample_rates)  # Use highest

    # Use most common channels
    if channels_set:
        info.channels = max(channels_set)

    # Only include file details if multi-file
    if info.is_multi_file:
        info.files = file_details

    return info


def detect_asin(name: str) -> tuple[str | None, bool, bool]:
    """Detect ASIN and format used."""
    for i, pattern in enumerate(ASIN_PATTERNS):
        match = pattern.search(name)
        if match:
            asin = match.group(1)
            uses_braces = i == 0
            uses_brackets = i == 1
            return asin, uses_braces, uses_brackets
    return None, False, False


def detect_edition_flags(name: str) -> list[str]:
    """Detect edition flags in folder name."""
    found = []
    name_lower = name.lower()
    for flag in EDITION_FLAGS:
        if flag.lower() in name_lower:
            found.append(flag)
    return found


def scan_folder(folder: Path, base_path: Path) -> FolderInfo:
    """Scan a single folder and extract info (without mediainfo)."""
    rel_path = folder.relative_to(base_path)
    depth = len(rel_path.parts)

    audio_files = []
    other_files = []
    subfolders = []

    for item in folder.iterdir():
        if item.is_file():
            if item.suffix.lower() in AUDIO_EXTENSIONS:
                audio_files.append(item.name)
            else:
                other_files.append(item.name)
        elif item.is_dir():
            subfolders.append(item.name)

    # Detect components
    name = folder.name
    asin, uses_braces, uses_bracket_asin = detect_asin(name)

    year_match = YEAR_PATTERN.search(name)
    year = year_match.group(1) if year_match else None

    # Ripper tag is [xxx] at end, but not if it's an ASIN
    ripper_tag = None
    tag_match = RIPPER_TAG_PATTERN.search(name)
    if tag_match:
        tag = tag_match.group(1)
        # Not a ripper tag if it looks like ASIN or year
        if not (tag.startswith("B") and len(tag) == 10) and not tag.isdigit():
            ripper_tag = tag

    vol_match = VOLUME_PATTERN.search(name)
    volume = vol_match.group(1) if vol_match else None

    edition_flags = detect_edition_flags(name)

    # Format detection
    uses_parens = "(" in name and ")" in name
    uses_brackets = "[" in name and "]" in name

    return FolderInfo(
        path=str(rel_path),
        name=name,
        depth=depth,
        is_leaf=len(audio_files) > 0,
        has_children_with_audio=False,  # Set later
        audio_files=audio_files,
        other_files=other_files,
        subfolders=subfolders,
        detected_asin=asin,
        detected_year=year,
        detected_ripper_tag=ripper_tag,
        detected_volume=volume,
        detected_edition_flags=edition_flags,
        uses_braces_asin=uses_braces,
        uses_bracket_asin=uses_bracket_asin,
        uses_parens=uses_parens,
        uses_brackets=uses_brackets,
    )


def process_mediainfo_for_folder(folder_info: FolderInfo, library_path: Path) -> FolderInfo:
    """Add mediainfo to a folder (called from worker thread)."""
    if folder_info.is_leaf and folder_info.audio_files:
        folder_path = library_path / folder_info.path
        folder_info.mediainfo = get_folder_mediainfo(folder_path, folder_info.audio_files)
    return folder_info


async def scan_library_async(
    library_path: Path,
    workers: int = 10,
    skip_mediainfo: bool = False,
) -> dict[str, Any]:
    """Scan entire library with async mediainfo processing."""
    folders: list[FolderInfo] = []

    # Phase 1: Quick folder scan (synchronous, fast)
    console.print("[bold blue]Phase 1:[/] Scanning folder structure...")

    def scan_recursive(folder: Path) -> None:
        if not folder.is_dir():
            return

        info = scan_folder(folder, library_path)
        folders.append(info)

        for subfolder in folder.iterdir():
            if subfolder.is_dir():
                scan_recursive(subfolder)

    # Start scanning (skip the root itself)
    for item in library_path.iterdir():
        if item.is_dir():
            scan_recursive(item)

    console.print(f"  Found [green]{len(folders)}[/] folders")

    # Mark folders that have children with audio
    folder_by_path = {f.path: f for f in folders}
    for folder in folders:
        if folder.is_leaf:
            # Mark all ancestors
            parts = Path(folder.path).parts
            for i in range(len(parts) - 1):
                ancestor_path = str(Path(*parts[: i + 1]))
                if ancestor_path in folder_by_path:
                    folder_by_path[ancestor_path].has_children_with_audio = True

    leaf_folders = [f for f in folders if f.is_leaf]
    console.print(f"  Found [green]{len(leaf_folders)}[/] leaf folders (with audio)")

    # Phase 2: Mediainfo extraction (parallel)
    if not skip_mediainfo and leaf_folders:
        console.print(f"\n[bold blue]Phase 2:[/] Extracting mediainfo ({workers} workers)...")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            with (
                ThreadPoolExecutor(max_workers=workers) as executor,
                Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    MofNCompleteColumn(),
                    TimeElapsedColumn(),
                    TimeRemainingColumn(),
                    console=console,
                ) as progress,
            ):
                task = progress.add_task("Processing", total=len(leaf_folders))

                async def process_one(folder_info: FolderInfo) -> FolderInfo:
                    result = await loop.run_in_executor(
                        executor,
                        process_mediainfo_for_folder,
                        folder_info,
                        library_path,
                    )
                    progress.advance(task)
                    return result

                # Process all leaf folders
                tasks = [process_one(f) for f in leaf_folders]
                await asyncio.gather(*tasks)
        finally:
            loop.close()

    # Compute statistics
    stats: dict[str, Any] = {
        "total_folders": len(folders),
        "leaf_folders": len(leaf_folders),
        "with_asin": len([f for f in leaf_folders if f.detected_asin]),
        "without_asin": len([f for f in leaf_folders if not f.detected_asin]),
        "with_braces_asin": len([f for f in leaf_folders if f.uses_braces_asin]),
        "with_bracket_asin": len([f for f in leaf_folders if f.uses_bracket_asin]),
        "with_year": len([f for f in leaf_folders if f.detected_year]),
        "with_ripper_tag": len([f for f in leaf_folders if f.detected_ripper_tag]),
        "with_volume": len([f for f in leaf_folders if f.detected_volume]),
        "with_edition_flags": len([f for f in leaf_folders if f.detected_edition_flags]),
        "unique_asins": len({f.detected_asin for f in leaf_folders if f.detected_asin}),
        "duplicate_asins": [],
    }

    # Mediainfo stats
    if not skip_mediainfo:
        codecs: dict[str, int] = {}
        multi_file_count = 0
        total_duration_hours = 0.0

        for f in leaf_folders:
            if f.mediainfo:
                if f.mediainfo.codec:
                    codecs[f.mediainfo.codec] = codecs.get(f.mediainfo.codec, 0) + 1
                if f.mediainfo.is_multi_file:
                    multi_file_count += 1
                if f.mediainfo.duration_seconds:
                    total_duration_hours += f.mediainfo.duration_seconds / 3600

        stats["mediainfo"] = {
            "codecs": codecs,
            "multi_file_folders": multi_file_count,
            "total_duration_hours": round(total_duration_hours, 1),
        }

    # Find duplicate ASINs
    asin_counts: dict[str, list[str]] = {}
    for f in leaf_folders:
        if f.detected_asin:
            asin_counts.setdefault(f.detected_asin, []).append(f.path)
    stats["duplicate_asins"] = [
        {"asin": asin, "count": len(paths), "paths": paths}
        for asin, paths in asin_counts.items()
        if len(paths) > 1
    ]

    # Find folders without ASIN
    stats["missing_asin_folders"] = [f.path for f in leaf_folders if not f.detected_asin]

    # Find legacy format folders (brackets instead of braces/parens)
    stats["legacy_format_folders"] = [
        f.path
        for f in leaf_folders
        if f.uses_bracket_asin or (f.uses_brackets and not f.uses_parens)
    ]

    # Find folders with edition flags
    stats["edition_flag_folders"] = [
        {"path": f.path, "flags": f.detected_edition_flags}
        for f in leaf_folders
        if f.detected_edition_flags
    ]

    return {
        "scan_timestamp": datetime.now().isoformat(),
        "library_path": str(library_path),
        "stats": stats,
        "folders": [asdict(f) for f in folders],
    }


def scan_library(
    library_path: Path, workers: int = 10, skip_mediainfo: bool = False
) -> dict[str, Any]:
    """Synchronous wrapper for async scan."""
    return asyncio.run(scan_library_async(library_path, workers, skip_mediainfo))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scan ABS library for edge case analysis")
    parser.add_argument(
        "library_path",
        nargs="?",
        default="/mnt/user/data/audio/audiobooks",
        help="Path to ABS library",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="samples/abs_library_scan.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=10,
        help="Number of parallel workers for mediainfo (default: 10)",
    )
    parser.add_argument(
        "--no-mediainfo",
        action="store_true",
        help="Skip mediainfo extraction (faster)",
    )
    args = parser.parse_args()

    library_path = Path(args.library_path)
    output_path = Path(args.output)

    console.print("\n[bold]ABS Library Scanner[/]")
    console.print(f"Library: [cyan]{library_path}[/]")
    console.print(f"Workers: [cyan]{args.workers}[/]")
    console.print(f"Mediainfo: [cyan]{'disabled' if args.no_mediainfo else 'enabled'}[/]\n")

    result = scan_library(library_path, args.workers, args.no_mediainfo)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    console.print(f"\n[bold green]✓[/] Saved to: [cyan]{output_path}[/]")
    console.print("\n[bold]Statistics:[/]")

    for key, value in result["stats"].items():
        if isinstance(value, list):
            console.print(f"  {key}: [yellow]{len(value)}[/] items")
        elif isinstance(value, dict):
            console.print(f"  {key}:")
            for k, v in value.items():
                console.print(f"    {k}: [yellow]{v}[/]")
        else:
            console.print(f"  {key}: [yellow]{value}[/]")
