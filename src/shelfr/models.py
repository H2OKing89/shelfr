"""Data models for MAMFast."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any


class ReleaseStatus(Enum):
    """Processing status of an audiobook release."""

    DISCOVERED = auto()  # Found in Libation library
    STAGED = auto()  # Files hardlinked to staging dir
    METADATA_FETCHED = auto()  # Audnex + MediaInfo complete
    TORRENT_CREATED = auto()  # .torrent file generated
    UPLOADED = auto()  # Added to qBittorrent
    COMPLETE = auto()  # Fully processed
    FAILED = auto()  # Processing failed


class SeriesSource(Enum):
    """Source of series information for resolution tracking."""

    AUDNEX = "audnex"  # From Audnex API seriesPrimary (authoritative)
    LIBATION = "libation"  # Parsed from Libation folder structure
    TITLE_HEURISTIC = "title_heuristic"  # Extracted from title via regex


@dataclass
class SeriesInfo:
    """
    Resolved series information from multiple sources.

    Series data can come from:
    1. Audnex seriesPrimary (authoritative, confidence=1.0)
    2. Libation folder structure (reliable, confidence=0.9)
    3. Title heuristics via regex (fallback, confidence=0.5)

    Used by naming and metadata modules to ensure consistent series handling
    even when Audnex metadata is incomplete (e.g., new releases).

    See docs/naming/NAMING_FOLDER_FILE_SCHEMAS.md for resolution strategy.
    """

    name: str  # Series name, e.g., "I'm the Evil Lord of an Intergalactic Empire!"
    position: str | None = None  # Volume/book number, e.g., "5", "01.5", "0" for prequel
    source: SeriesSource = SeriesSource.AUDNEX
    confidence: float = 1.0  # 1.0 = authoritative, 0.9 = libation, 0.5 = heuristic

    @property
    def formatted_position(self) -> str | None:
        """Format position for vol_XX style (zero-padded if numeric)."""
        if not self.position:
            return None
        # Try to format as zero-padded number
        try:
            num = float(self.position)
            if num == int(num):
                return f"{int(num):02d}"
            else:
                # Decimal like 1.5, 0.5, 10.5
                # Split into whole and fractional parts for proper formatting
                whole, frac = str(num).split(".")
                return f"{int(whole):02d}.{frac.ljust(2, '0')[:2]}"
        except ValueError:
            # Non-numeric position (rare)
            return self.position


@dataclass
class NormalizedBook:
    """
    Canonical book metadata after Audnex normalization.

    Fixes Audible's inconsistent title/subtitle swapping by using seriesPrimary
    as the source of truth. See docs/NAMING_PLAN.md for details.

    Example (swapped input):
        Raw: title="Alicization Exploding", subtitle="Sword Art Online 16"
        Series: "Sword Art Online #16"

        Normalized:
            series_name="Sword Art Online"
            series_position="16"
            arc_name="Alicization Exploding"
            display_title="Sword Art Online 16"
            display_subtitle="Alicization Exploding"
            was_swapped=True
    """

    asin: str

    # Raw values (preserved for debugging)
    raw_title: str
    raw_subtitle: str | None

    # Canonical values from seriesPrimary (source of truth)
    series_name: str | None = None
    series_position: str | None = None

    # Extracted arc name (e.g., "Alicization Exploding", "Mother's Rosary")
    arc_name: str | None = None

    # Constructed display values
    display_title: str = ""  # "{Series} {N}" or raw_title if no series
    display_subtitle: str | None = None  # Arc name if exists, else None

    # Tracking
    was_swapped: bool = False

    def __post_init__(self) -> None:
        """Set display_title to raw_title if not explicitly set."""
        if not self.display_title:
            self.display_title = self.raw_title


@dataclass
class AudiobookRelease:
    """
    Represents a single audiobook ready for processing.

    This is the core data structure passed through the pipeline.
    """

    # -------------------------------------------------------------------------
    # Identity (from Libation / folder structure)
    # -------------------------------------------------------------------------
    asin: str | None = None  # Audible ASIN (primary identifier)
    title: str = ""
    author: str = ""
    narrator: str | None = None
    series: str | None = None
    series_position: str | None = None
    year: str | None = None

    # -------------------------------------------------------------------------
    # Paths
    # -------------------------------------------------------------------------
    source_dir: Path | None = None  # Original Libation directory
    staging_dir: Path | None = None  # Hardlinked upload workspace
    main_m4b: Path | None = None  # Primary audiobook file

    # -------------------------------------------------------------------------
    # Files
    # -------------------------------------------------------------------------
    files: list[Path] = field(default_factory=list)  # All relevant files found

    # -------------------------------------------------------------------------
    # Processing State
    # -------------------------------------------------------------------------
    status: ReleaseStatus = ReleaseStatus.DISCOVERED
    torrent_path: Path | None = None
    error: str | None = None

    # -------------------------------------------------------------------------
    # Metadata (populated during processing)
    # -------------------------------------------------------------------------
    audnex_metadata: dict[str, Any] | None = None
    mediainfo_data: dict[str, Any] | None = None
    audnex_chapters: dict[str, Any] | None = None  # Audnex chapters API response

    # -------------------------------------------------------------------------
    # Timestamps
    # -------------------------------------------------------------------------
    discovered_at: datetime | None = None
    processed_at: datetime | None = None

    @property
    def display_name(self) -> str:
        """Human-readable name for logging."""
        if self.author and self.title:
            return f"{self.author} - {self.title}"
        if self.title:
            return self.title
        if self.source_dir:
            return self.source_dir.name
        return "Unknown Release"

    @property
    def safe_dirname(self) -> str:
        """
        Generate a filesystem-safe directory name for staging.

        Format: "Author - Title" or "Author - Title (Year)" if year available.
        """
        parts = []

        if self.author:
            parts.append(sanitize_for_filename(self.author))

        if self.title:
            title_part = sanitize_for_filename(self.title)
            if self.year:
                title_part += f" ({self.year})"
            parts.append(title_part)

        if not parts:
            # Fallback to source directory name
            if self.source_dir:
                return sanitize_for_filename(self.source_dir.name)
            return "unknown_release"

        return " - ".join(parts)


@dataclass
class ProcessingResult:
    """Result of processing a single release through the pipeline."""

    release: AudiobookRelease
    success: bool
    error: str | None = None
    torrent_path: Path | None = None
    duration_seconds: float = 0.0

    @property
    def status_emoji(self) -> str:
        """Icon for status display."""
        return "✓" if self.success else "✗"


@dataclass
class MamPath:
    """
    Result of MAM path generation with truncation metadata.

    The MAM path limit is 225 characters for the **full relative path**
    (folder/filename combined). This dataclass tracks what was generated
    and what truncation occurred.

    Path structure: "{base} [{tag}]/{base}{ext}"

    Budget formula (with tag):
        2*len(base) + len(tag) + len(ext) + 4 ≤ max_path_length
        max_base = (max_path_length - len(tag) - len(ext) - 4) // 2

    Budget formula (no tag):
        2*len(base) + len(ext) + 1 ≤ max_path_length
        max_base = (max_path_length - len(ext) - 1) // 2

    Examples with max_path_length=225 and ".m4b" (4 chars):
        With "H2OKing" (7 chars): max_base ≤ 105 chars
        With no tag:              max_base ≤ 110 chars

    See docs/NAMING_PLAN.md Phase 8 for full details.
    """

    folder: str  # e.g., "Series vol_01 ... [H2OKing]"
    filename: str  # e.g., "Series vol_01 ....m4b"
    full_path: str  # folder + "/" + filename
    length: int  # len(full_path)
    truncated: bool  # True if any truncation occurred
    dropped_components: list[str]  # e.g., ["arc", "author"] for logging

    @property
    def over_limit(self) -> bool:
        """Check if path exceeds MAM's 225-char limit."""
        return self.length > 225


@dataclass
class ProcessedState:
    """
    Persistent state tracking for processed releases.

    Stored in processed.json to prevent re-processing.
    """

    asin: str
    title: str
    author: str
    processed_at: str  # ISO format datetime
    staging_dir: str
    torrent_path: str | None
    status: str  # ReleaseStatus name


def sanitize_for_filename(text: str) -> str:
    """
    Remove or replace characters that are problematic in filenames.

    Handles: / \\ : * ? " < > |
    Also collapses multiple spaces.
    """
    # Characters not allowed in filenames
    replacements = {
        "/": "-",
        "\\": "-",
        ":": " -",
        "*": "",
        "?": "",
        '"': "'",
        "<": "",
        ">": "",
        "|": "-",
    }

    result = text
    for char, replacement in replacements.items():
        result = result.replace(char, replacement)

    # Collapse multiple spaces
    while "  " in result:
        result = result.replace("  ", " ")

    # Strip leading/trailing whitespace and dots
    result = result.strip(". ")

    return result
