"""
Audiobook discovery from Libation library.

Parses Libation's folder structure to find audiobook releases:
    Author/
    └── Series/
        └── Title vol_XX (Year) (Author) {ASIN.XXXXXXXXXX} [Source]/
            ├── *.m4b
            ├── *.cue (optional)
            ├── *.pdf (optional)
            ├── cover.jpg
            └── metadata.json

ASIN is extracted from folder name pattern: {ASIN.XXXXXXXXXX}
Additional metadata comes from metadata.json if present.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from mamfast.config import get_settings
from mamfast.models import AudiobookRelease, ReleaseStatus
from mamfast.utils.state import get_processed_identifiers

logger = logging.getLogger(__name__)

# Regex to extract ASIN from folder/file name
# Matches: {ASIN.B09GHD1R2R} or [ASIN.1774248182] (both bracket styles)
ASIN_PATTERN = re.compile(r"[\[{]ASIN\.([^\]}]+)[\]}]")

# Regex to parse folder name components
# Pattern: Title vol_XX (Year) (Author) {ASIN.XXX} [Source]
# Also handles [ASIN.XXX] style and [Year] [Author] style
FOLDER_PATTERN = re.compile(
    r"^(?P<title>.+?)"
    r"(?:\s+-\s+vol_(?P<volume>[\d.]+))?"  # " - vol_XX" style
    r"(?:\s+vol_(?P<volume2>[\d.]+))?"  # "vol_XX" style (fallback)
    r"(?:\s+[\[(](?P<year>\d{4})[\])])?"  # (Year) or [Year]
    r"(?:\s+[\[(](?P<author>[^\])]+)[\])])?"  # (Author) or [Author]
    r"(?:\s+[\[{]ASIN\.(?P<asin>[^\]}]+)[\]}])?"  # {ASIN.XXX} or [ASIN.XXX]
    r"(?:\s+\[(?P<source>[^\]]+)\])?$"  # [Source]
)


@dataclass
class LibationMetadata:
    """Parsed metadata from Libation's metadata.json."""

    asin: str | None = None
    title: str | None = None
    authors: list[str] | None = None
    narrators: list[str] | None = None
    series_name: str | None = None
    series_position: str | None = None
    year: str | None = None
    description: str | None = None
    publisher: str | None = None
    language: str | None = None
    runtime_minutes: int | None = None

    # Raw data for reference
    raw: dict[str, Any] | None = None


def extract_asin_from_name(name: str) -> str | None:
    """
    Extract ASIN from a folder or file name.

    Examples:
        "He Who Fights with Monsters vol_01 (2021) (Shirtaloon) {ASIN.1774248182}"
        → "1774248182"
        "The Weakest Tamer vol_01 (2025) (Honobonoru500) [ASIN.B0DSM1KYJ2]"
        → "B0DSM1KYJ2"
    """
    # ASIN_PATTERN matches both {ASIN.xxx} and [ASIN.xxx] styles
    match = ASIN_PATTERN.search(name)
    if match:
        return match.group(1)
    return None


def parse_folder_name(name: str) -> dict[str, str | None]:
    """
    Parse components from a Libation folder name.

    Returns dict with keys: title, volume, year, author, asin, source
    """
    match = FOLDER_PATTERN.match(name)
    if match:
        return match.groupdict()

    # Fallback: at least try to get ASIN
    return {
        "title": name,
        "volume": None,
        "year": None,
        "author": None,
        "asin": extract_asin_from_name(name),
        "source": None,
    }


def load_metadata_json(metadata_path: Path) -> LibationMetadata | None:
    """
    Load and parse Libation's metadata.json file.

    Returns LibationMetadata object or None if file doesn't exist/is invalid.
    """
    if not metadata_path.exists():
        return None

    try:
        with open(metadata_path, encoding="utf-8") as f:
            data = json.load(f)

        # Parse common fields - Libation's format may vary
        # Try different possible field names
        metadata = LibationMetadata(raw=data)

        # ASIN
        metadata.asin = data.get("asin") or data.get("Asin") or data.get("id")

        # Title
        metadata.title = data.get("title") or data.get("Title")

        # Authors (may be string or list)
        authors = data.get("authors") or data.get("Authors") or data.get("author")
        if isinstance(authors, str):
            metadata.authors = [authors]
        elif isinstance(authors, list):
            # Could be list of strings or list of dicts with 'name' key
            metadata.authors = []
            for a in authors:
                if isinstance(a, str):
                    metadata.authors.append(a)
                elif isinstance(a, dict):
                    metadata.authors.append(a.get("name", str(a)))

        # Narrators
        narrators = data.get("narrators") or data.get("Narrators") or data.get("narrator")
        if isinstance(narrators, str):
            metadata.narrators = [narrators]
        elif isinstance(narrators, list):
            metadata.narrators = []
            for n in narrators:
                if isinstance(n, str):
                    metadata.narrators.append(n)
                elif isinstance(n, dict):
                    metadata.narrators.append(n.get("name", str(n)))

        # Series
        series = data.get("series") or data.get("Series")
        if isinstance(series, str):
            metadata.series_name = series
        elif isinstance(series, list) and series:
            # Take first series
            s = series[0]
            if isinstance(s, dict):
                metadata.series_name = s.get("name") or s.get("title")
                metadata.series_position = str(s.get("position") or s.get("sequence") or "")
            else:
                metadata.series_name = str(s)
        elif isinstance(series, dict):
            metadata.series_name = series.get("name") or series.get("title")
            metadata.series_position = str(series.get("position") or series.get("sequence") or "")

        # Year / Release date
        year = data.get("year") or data.get("releaseDate") or data.get("release_date")
        if year:
            # Could be full date or just year
            metadata.year = str(year)[:4] if len(str(year)) >= 4 else str(year)

        # Other fields
        metadata.description = data.get("description") or data.get("summary")
        metadata.publisher = data.get("publisher") or data.get("Publisher")
        metadata.language = data.get("language") or data.get("Language")

        runtime = (
            data.get("runtimeLengthMin")
            or data.get("runtime_minutes")
            or data.get("duration")
        )
        if runtime:
            with contextlib.suppress(ValueError, TypeError):
                metadata.runtime_minutes = int(runtime)

        return metadata

    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON in {metadata_path}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Error reading {metadata_path}: {e}")
        return None


def is_audiobook_dir(path: Path) -> bool:
    """
    Check if a directory contains audiobook files.

    An audiobook directory must have at least one .m4b file.
    """
    if not path.is_dir():
        return False

    return any(item.is_file() and item.suffix.lower() == ".m4b" for item in path.iterdir())


def find_audiobook_dirs(library_root: Path) -> list[Path]:
    """
    Find all directories containing audiobooks in the library.

    Walks the tree and returns paths to directories containing .m4b files.
    """
    audiobook_dirs = []

    if not library_root.exists():
        logger.error(f"Library root does not exist: {library_root}")
        return []

    # Walk the tree to find audiobook directories
    # Structure: Author/Series/Book or Author/Book
    for author_dir in library_root.iterdir():
        if not author_dir.is_dir():
            continue

        # Check if this level has audiobooks (no series subfolder)
        if is_audiobook_dir(author_dir):
            audiobook_dirs.append(author_dir)
            continue

        # Look one level deeper (series or book level)
        for series_or_book_dir in author_dir.iterdir():
            if not series_or_book_dir.is_dir():
                continue

            if is_audiobook_dir(series_or_book_dir):
                audiobook_dirs.append(series_or_book_dir)
                continue

            # Look one more level (book level under series)
            for book_dir in series_or_book_dir.iterdir():
                if is_audiobook_dir(book_dir):
                    audiobook_dirs.append(book_dir)

    logger.debug(f"Found {len(audiobook_dirs)} audiobook directories")
    return audiobook_dirs


def build_release_from_dir(audiobook_dir: Path) -> AudiobookRelease:
    """
    Build an AudiobookRelease from an audiobook directory.

    Extracts metadata from:
    1. metadata.json (if present) - preferred
    2. Folder name parsing - fallback
    """
    settings = get_settings()

    # Start with folder name parsing
    folder_info = parse_folder_name(audiobook_dir.name)

    # Try to load metadata.json
    metadata_path = audiobook_dir / "metadata.json"
    libation_meta = load_metadata_json(metadata_path)

    # Build the release, preferring metadata.json values
    release = AudiobookRelease()
    release.source_dir = audiobook_dir
    release.discovered_at = datetime.now()
    release.status = ReleaseStatus.DISCOVERED

    # ASIN (critical identifier)
    if libation_meta and libation_meta.asin:
        release.asin = libation_meta.asin
    else:
        release.asin = folder_info.get("asin")

    # Title
    if libation_meta and libation_meta.title:
        release.title = libation_meta.title
    else:
        release.title = folder_info.get("title") or audiobook_dir.name

    # Author
    if libation_meta and libation_meta.authors:
        release.author = libation_meta.authors[0]  # Primary author
    else:
        release.author = folder_info.get("author") or ""
        # If no author from folder, try parent directory name
        if not release.author:
            # Go up to find author dir (skip series dir if present)
            parent = audiobook_dir.parent
            grandparent = parent.parent
            library_root = settings.paths.libation_library_root

            if grandparent != library_root and parent != library_root:
                # We're in Author/Series/Book structure
                release.author = grandparent.name
            elif parent != library_root:
                # We're in Author/Book structure
                release.author = parent.name

    # Narrator
    if libation_meta and libation_meta.narrators:
        release.narrator = ", ".join(libation_meta.narrators)

    # Series
    if libation_meta and libation_meta.series_name:
        release.series = libation_meta.series_name
        release.series_position = libation_meta.series_position
    else:
        # Try to get series from parent folder name
        parent = audiobook_dir.parent
        library_root = settings.paths.libation_library_root
        if parent != library_root and parent.parent != library_root:
            # Parent might be series folder
            release.series = parent.name

        # Volume from folder name
        if folder_info.get("volume"):
            release.series_position = folder_info["volume"]

    # Year
    if libation_meta and libation_meta.year:
        release.year = libation_meta.year
    else:
        release.year = folder_info.get("year")

    # Find files
    allowed_exts = {ext.lower() for ext in settings.mam.allowed_extensions}

    release.files = [
        item
        for item in audiobook_dir.iterdir()
        if item.is_file()
        and (item.suffix.lower() in allowed_exts or item.name.lower() == "cover.jpg")
    ]

    # Find main m4b
    m4b_files = [f for f in release.files if f.suffix.lower() == ".m4b"]
    if m4b_files:
        release.main_m4b = m4b_files[0]

    return release


def scan_library(library_root: Path | None = None) -> list[AudiobookRelease]:
    """
    Scan Libation library and return all audiobook releases found.

    Args:
        library_root: Path to library root. Uses config default if None.

    Returns:
        List of AudiobookRelease objects for all found audiobooks.
    """
    if library_root is None:
        settings = get_settings()
        library_root = settings.paths.libation_library_root

    logger.info(f"Scanning library: {library_root}")

    audiobook_dirs = find_audiobook_dirs(library_root)

    releases = []
    for audiobook_dir in audiobook_dirs:
        try:
            release = build_release_from_dir(audiobook_dir)
            releases.append(release)
            logger.debug(f"Found: {release.display_name} (ASIN: {release.asin})")
        except Exception as e:
            logger.warning(f"Error processing {audiobook_dir}: {e}")

    logger.info(f"Found {len(releases)} audiobook(s) in library")
    return releases


def get_new_releases(
    library_root: Path | None = None,
    state_file: Path | None = None,
) -> list[AudiobookRelease]:
    """
    Get releases that haven't been processed yet.

    Compares library contents against processed state file.

    Args:
        library_root: Path to library root. Uses config default if None.
        state_file: Path to state file. Uses config default if None.

    Returns:
        List of unprocessed AudiobookRelease objects.
    """
    # Get all releases
    all_releases = scan_library(library_root)

    # Get already processed identifiers
    processed = get_processed_identifiers()

    # Filter to new releases
    new_releases = []
    for release in all_releases:
        # Check by ASIN (preferred) or source_dir path
        identifier = release.asin or str(release.source_dir)

        if identifier in processed:
            logger.debug(f"Skipping (already processed): {release.display_name}")
            continue

        # Also check by path in case ASIN changed
        if str(release.source_dir) in processed:
            logger.debug(f"Skipping (path already processed): {release.display_name}")
            continue

        new_releases.append(release)

    logger.info(f"Found {len(new_releases)} new (unprocessed) release(s)")
    return new_releases


def get_release_by_asin(asin: str, library_root: Path | None = None) -> AudiobookRelease | None:
    """
    Find a specific release by ASIN.

    Args:
        asin: ASIN to search for
        library_root: Path to library root

    Returns:
        AudiobookRelease if found, None otherwise
    """
    all_releases = scan_library(library_root)

    for release in all_releases:
        if release.asin == asin:
            return release

    return None


def print_release_summary(releases: list[AudiobookRelease]) -> None:
    """Print a summary of releases to console."""
    if not releases:
        print("No releases found.")
        return

    print(f"\nFound {len(releases)} release(s):\n")

    for i, release in enumerate(releases, 1):
        status = "✓" if release.asin else "?"
        asin_display = release.asin or "NO ASIN"

        print(f"  [{status}] {i}. {release.display_name}")
        print(f"       ASIN: {asin_display}")

        if release.series:
            series_info = release.series
            if release.series_position:
                series_info += f" #{release.series_position}"
            print(f"       Series: {series_info}")

        print(f"       Files: {len(release.files)}")
        print()
