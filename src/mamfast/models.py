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
        """Emoji for status display."""
        return "✅" if self.success else "❌"


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
