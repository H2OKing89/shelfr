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

# ASIN validation: 10 chars - either B + 9 alphanumeric, or 10 digits
# Audible ASINs are typically B0XXXXXXXX or 10-digit ISBNs
ASIN_VALID_PATTERN = re.compile(r"^(?:B[0-9A-Z]{9}|[0-9]{10})$")

# Regex to parse folder name components
# Pattern: Title vol_XX (Year) (Author) {ASIN.XXX} [Source]
# Also handles [ASIN.XXX] style and [Year] [Author] style
# Volume can be " - vol_XX" or " vol_XX" (both captured in same group)
FOLDER_PATTERN = re.compile(
    r"^(?P<title>.+?)"
    r"(?:\s+(?:-\s+)?vol_(?P<volume>[\d.]+))?"  # "vol_XX" or " - vol_XX" style
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


def is_valid_asin(asin: str | None) -> bool:
    """
    Validate ASIN format.

    Valid ASINs are 10 characters:
    - B + 9 alphanumeric (e.g., B09GHD1R2R) - Audible format
    - 10 digits (e.g., 1774248182) - ISBN-10 format

    Args:
        asin: The ASIN string to validate

    Returns:
        True if valid ASIN format, False otherwise
    """
    if not asin:
        return False
    return bool(ASIN_VALID_PATTERN.match(asin))


def extract_asin_from_name(name: str) -> str | None:
    """
    Extract ASIN from a folder or file name.

    Examples:
        "He Who Fights with Monsters vol_01 (2021) (Shirtaloon) {ASIN.1774248182}"
        → "1774248182"
        "The Weakest Tamer vol_01 (2025) (Honobonoru500) [ASIN.B0DSM1KYJ2]"
        → "B0DSM1KYJ2"

    Returns:
        The extracted ASIN if found and valid, None otherwise.
        Logs a warning if ASIN is found but has invalid format.
    """
    match = ASIN_PATTERN.search(name)
    if match:
        asin = match.group(1)
        if is_valid_asin(asin):
            return asin
        else:
            logger.warning(f"Found ASIN with invalid format: {asin} in '{name}'")
            # Still return it - might be a new format we don't know about
            return asin
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


def find_metadata_file(audiobook_dir: Path) -> Path | None:
    """
    Find the *.metadata.json file in an audiobook directory.

    Libation creates files like: "BookTitle (Year) (Author) {ASIN.XXX}.metadata.json"

    Returns:
        Path to metadata file if found, None otherwise.
    """
    metadata_files = list(audiobook_dir.glob("*.metadata.json"))
    if metadata_files:
        # Usually only one, but take the first if multiple
        return metadata_files[0]
    return None


def load_metadata_json(metadata_path: Path) -> LibationMetadata | None:
    """
    Load and parse Libation's *.metadata.json file.

    The file contains the full Audible API response with fields like:
    - asin, title, authors, narrators
    - release_date, runtime_length_min
    - publisher_name, publisher_summary
    - category_ladders, ChapterInfo

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

        # Year / Release date (Libation uses release_date: "2025-04-16")
        year = data.get("release_date") or data.get("issue_date") or data.get("year")
        if year:
            # Extract year from date string like "2025-04-16"
            metadata.year = str(year)[:4] if len(str(year)) >= 4 else str(year)

        # Other fields
        # Libation uses publisher_summary (HTML) and merchandising_summary (plain text)
        metadata.description = (
            data.get("publisher_summary")
            or data.get("merchandising_summary")
            or data.get("description")
        )
        metadata.publisher = data.get("publisher_name") or data.get("publisher")
        metadata.language = data.get("language")  # lowercase in Libation: "english"

        # Runtime (Libation uses runtime_length_min)
        runtime = data.get("runtime_length_min") or data.get("runtime_minutes")
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

    Metadata priority:
    1. *.metadata.json (Libation's Audible API cache) - primary source
    2. Folder name parsing - fallback for ASIN, title, year

    Args:
        audiobook_dir: Path to the audiobook directory containing .m4b files

    Returns:
        AudiobookRelease with extracted metadata
    """
    settings = get_settings()

    # Parse folder name for fallback values
    folder_info = parse_folder_name(audiobook_dir.name)

    # Find and load *.metadata.json (e.g., "BookTitle {ASIN.XXX}.metadata.json")
    metadata_path = find_metadata_file(audiobook_dir)
    libation_meta = load_metadata_json(metadata_path) if metadata_path else None

    if libation_meta:
        logger.debug(f"Loaded metadata from: {metadata_path.name if metadata_path else 'N/A'}")
    else:
        logger.warning(f"No *.metadata.json found in {audiobook_dir.name}, using folder name only")

    # Build the release
    release = AudiobookRelease()
    release.source_dir = audiobook_dir
    release.discovered_at = datetime.now()
    release.status = ReleaseStatus.DISCOVERED

    # ASIN (critical identifier) - prefer metadata, fallback to folder
    release.asin = (libation_meta.asin if libation_meta else None) or folder_info.get("asin")

    # Title - prefer metadata, fallback to folder
    release.title = (
        (libation_meta.title if libation_meta else None)
        or folder_info.get("title")
        or audiobook_dir.name
    )

    # Author - prefer metadata, fallback to folder name
    if libation_meta and libation_meta.authors:
        release.author = libation_meta.authors[0]  # Primary author
    else:
        release.author = folder_info.get("author") or ""

    # Narrator - from metadata only (not in folder name)
    if libation_meta and libation_meta.narrators:
        release.narrator = ", ".join(libation_meta.narrators)

    # Series - prefer metadata, fallback to folder volume number
    # Note: Audible sometimes misses series info, especially for new releases
    if libation_meta and libation_meta.series_name:
        release.series = libation_meta.series_name
        release.series_position = libation_meta.series_position
    elif folder_info.get("volume"):
        # No series name from metadata, but folder has vol_XX
        # Series name will need to be added manually or from Audnex later
        release.series_position = folder_info["volume"]

    # Year - prefer metadata, fallback to folder
    release.year = (libation_meta.year if libation_meta else None) or folder_info.get("year")

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
        library_root = settings.paths.library_root

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
