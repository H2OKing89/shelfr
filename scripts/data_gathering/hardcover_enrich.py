#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                  HARDCOVER API BOOK DATA ENRICHMENT TOOL                     ║
║                                                                              ║
║  Production-grade script to enrich book metadata with Hardcover API data    ║
║  Features stunning Rich console output, live dashboards, and animations     ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import random
import re
import ssl
import sys
import uuid

import sh
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx
import typer
from dotenv import load_dotenv
from rapidfuzz import fuzz
from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.logging import RichHandler
from rich.padding import Padding
from rich.panel import Panel
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
from rich.rule import Rule
from rich.style import Style
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

# Import from mamfast package (requires: pip install -e . from repo root)
try:
    from mamfast.utils.circuit_breaker import CircuitOpenError, hardcover_breaker
except ImportError as e:
    raise ImportError(
        "Cannot import from mamfast package. Please install in editable mode:\n"
        "  cd /path/to/mam_tool && pip install -e .\n"
        "Or ensure the package is installed and PYTHONPATH is set correctly."
    ) from e

# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                         🎨 THEME & STYLING                                   ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# Custom color palette - Cyberpunk/Neon aesthetic
COLORS = {
    "primary": "#7C3AED",  # Electric Purple
    "secondary": "#06B6D4",  # Neon Cyan
    "success": "#10B981",  # Emerald Green
    "warning": "#F59E0B",  # Amber
    "error": "#EF4444",  # Red
    "info": "#3B82F6",  # Blue
    "muted": "#6B7280",  # Gray
    "accent": "#EC4899",  # Hot Pink
    "gold": "#FFD700",  # Gold
    "silver": "#C0C0C0",  # Silver
    "neon_green": "#39FF14",  # Neon Green
    "neon_blue": "#00FFFF",  # Neon Blue
    "neon_pink": "#FF10F0",  # Neon Pink
    "neon_orange": "#FF6600",  # Neon Orange
}

# Application version for provenance
APP_VERSION = "2.0.0"

# Gradient color sequences
GRADIENT_PURPLE_CYAN = ["#7C3AED", "#9D4EDD", "#B47EDE", "#C19EE0", "#06B6D4"]
GRADIENT_RAINBOW = ["#FF0000", "#FF7F00", "#FFFF00", "#00FF00", "#0000FF", "#4B0082", "#9400D3"]

# Custom styles for different elements
STYLES = {
    "title": Style(color=COLORS["primary"], bold=True),
    "subtitle": Style(color=COLORS["secondary"], italic=True),
    "success": Style(color=COLORS["success"], bold=True),
    "warning": Style(color=COLORS["warning"]),
    "error": Style(color=COLORS["error"], bold=True),
    "info": Style(color=COLORS["info"]),
    "muted": Style(color=COLORS["muted"], dim=True),
    "highlight": Style(color=COLORS["accent"], bold=True),
    "gold": Style(color=COLORS["gold"], bold=True),
    "neon": Style(color=COLORS["neon_green"], bold=True),
}

# Rich console with full color support
console = Console(
    force_terminal=True,
    color_system="truecolor",
    highlight=True,
    record=True,
)

# Configure logging with Rich handler for beautiful logs + file handler
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
log_file = log_dir / "hardcover_enrichment.log"

# Create file handler for detailed logging
file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(
    logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
)

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[
        RichHandler(
            console=console,
            rich_tracebacks=True,
            tracebacks_show_locals=True,
            show_time=True,
            show_path=False,
            markup=True,
        ),
        file_handler,
    ],
)
logger = logging.getLogger(__name__)
logger.info(f"Logging to file: {log_file.absolute()}")

# Load environment from config/.env
load_dotenv(Path(__file__).parent.parent.parent / "config" / ".env")


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                    🎭 ASCII ART & VISUAL ELEMENTS                            ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

BANNER_ART = """[bold #7C3AED]
╔═══════════════════════════════════════════════════════════════════════════════════╗
║                                                                                   ║
║  [bold #FF10F0]██╗  ██╗ █████╗ ██████╗ ██████╗  ██████╗ ██████╗ ██╗   ██╗███████╗██████╗ [/]       ║
║  [bold #EC4899]██║  ██║██╔══██╗██╔══██╗██╔══██╗██╔════╝██╔═══██╗██║   ██║██╔════╝██╔══██╗[/]       ║
║  [bold #C19EE0]███████║███████║██████╔╝██║  ██║██║     ██║   ██║██║   ██║█████╗  ██████╔╝[/]       ║
║  [bold #9D4EDD]██╔══██║██╔══██║██╔══██╗██║  ██║██║     ██║   ██║╚██╗ ██╔╝██╔══╝  ██╔══██╗[/]       ║
║  [bold #7C3AED]██║  ██║██║  ██║██║  ██║██████╔╝╚██████╗╚██████╔╝ ╚████╔╝ ███████╗██║  ██║[/]       ║
║  [bold #6D28D9]╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝  ╚═════╝ ╚═════╝   ╚═══╝  ╚══════╝╚═╝  ╚═╝[/]       ║
║                                                                                   ║
║               [bold #06B6D4]Book Data Enrichment Tool - Powered by Hardcover API[/]                ║
║                                                                                   ║
╚═══════════════════════════════════════════════════════════════════════════════════╝
[/]"""  # noqa: E501

# Emoji collections for visual variety
BOOK_EMOJIS = ["📖", "📚", "📕", "📗", "📘", "📙", "📓", "📔", "📒", "📝", "🔖", "📜"]
SUCCESS_EMOJIS = ["✨", "🌟", "⭐", "💫", "🎉", "🎊", "🏆", "👑", "💎", "🔮", "🌈", "💖"]
PROGRESS_EMOJIS = ["🔍", "🔎", "📡", "🛰️", "📶", "⚡", "🚀", "💨", "🌊", "🔥", "💫", "🌀"]
STATUS_EMOJIS = {
    "searching": "🔍",
    "found": "✅",
    "cached": "📦",
    "failed": "❌",
    "enriching": "🔮",
    "complete": "🎉",
    "api": "📡",
    "save": "💾",
    "load": "📂",
}

# Spinner styles for different operations
SPINNERS = {
    "default": "dots",
    "fast": "dots2",
    "slow": "dots3",
    "aesthetic": "aesthetic",
    "moon": "moon",
    "earth": "earth",
    "clock": "clock",
    "bounce": "bouncingBall",
    "christmas": "christmas",
    "dots12": "dots12",
}


def get_random_emoji(emoji_list: list[str]) -> str:
    """Get a random emoji from a list for visual variety."""
    return random.choice(emoji_list)


def create_gradient_text(text: str, colors: list[str] | None = None) -> Text:
    """Create text with a gradient color effect."""
    if colors is None:
        colors = GRADIENT_PURPLE_CYAN
    result = Text()
    for i, char in enumerate(text):
        color = colors[i % len(colors)]
        result.append(char, style=Style(color=color, bold=True))
    return result


def create_sparkle_text(text: str) -> Text:
    """Create text with sparkle decorations."""
    sparkles = ["✨", "⭐", "💫", "🌟"]
    prefix = random.choice(sparkles)
    suffix = random.choice(sparkles)
    return Text.from_markup(f"{prefix} [bold #FFD700]{text}[/] {suffix}")


def create_neon_box(content: str, title: str = "", color: str = "#7C3AED") -> Panel:
    """Create a neon-styled box panel."""
    return Panel(
        content,
        title=f"[bold {color}]{title}[/]" if title else None,
        border_style=Style(color=color, bold=True),
        box=box.DOUBLE_EDGE,
        padding=(1, 2),
    )


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                           ⚙️ SETTINGS                                        ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


class Settings:
    """All configurable settings for the enrichment tool."""

    # API Configuration
    API_ENDPOINT = "https://api.hardcover.app/v1/graphql"
    SEARCH_ENDPOINT = "https://api.hardcover.app/v1/search"  # Dedicated search endpoint
    API_KEY = os.getenv("HARDCOVER_API_KEY", "")
    API_TIMEOUT = 30.0  # Hardcover API max timeout
    API_RETRIES = 3

    # Rate Limiting & Gating
    MAX_CONCURRENT_REQUESTS = 5
    REQUEST_RATE_LIMIT = 60  # Hardcover API limit: 60 requests/minute
    MIN_REQUEST_INTERVAL = 60.0 / REQUEST_RATE_LIMIT
    REQUEST_TIMEOUT_BACKOFF = 2.0
    REQUEST_TIMEOUT_MAX = 60.0

    # Connection Pooling
    CONNECTION_POOL_SIZE = 10
    KEEPALIVE_EXPIRY = 30.0

    # File Paths
    COMBINED_METADATA_FILE = Path("data/combined_metadata.json")
    ENRICHED_DATA_FILE = Path("data/hardcover_enriched_run.json")
    ENRICHED_BOOKS_FILE = Path("data/hardcover_enriched_books.jsonl")
    ENRICHED_VOCAB_FILE = Path("data/hardcover_keywords.json")
    SEARCH_CACHE_FILE = Path("data/hardcover_search_cache.json")

    # Processing
    BATCH_SIZE = 50
    FUZZ_MATCH_THRESHOLD = 0.70
    CACHE_ENABLED = True

    # Output
    SAMPLE_BOOKS_TO_SHOW = 5
    MAX_ERRORS_TO_LOG = 10
    VERBOSE_LOGGING = False


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                           📊 DATA CLASSES                                    ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


@dataclass
class ExecutionStats:
    """Statistics about the enrichment run with live tracking."""

    total_books: int = 0
    books_searched: int = 0
    books_cached: int = 0
    books_failed: int = 0
    api_calls: int = 0
    api_errors: int = 0
    total_request_time: float = 0.0
    start_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    end_time: datetime | None = None
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)
    current_book: str = ""

    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        total = self.books_searched + self.books_cached + self.books_failed
        if total == 0:
            return 0.0
        return ((self.books_searched + self.books_cached) / total) * 100

    @property
    def avg_request_time(self) -> float:
        """Calculate average request time."""
        if self.api_calls == 0:
            return 0.0
        return self.total_request_time / self.api_calls

    @property
    def elapsed_time(self) -> float:
        """Get elapsed time since start."""
        return (datetime.now(UTC) - self.start_time).total_seconds()

    @property
    def books_per_second(self) -> float:
        """Calculate processing speed."""
        elapsed = self.elapsed_time
        if elapsed == 0:
            return 0.0
        processed = self.books_searched + self.books_cached + self.books_failed
        return processed / elapsed

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "total_books": self.total_books,
            "books_searched": self.books_searched,
            "books_cached": self.books_cached,
            "books_failed": self.books_failed,
            "api_calls": self.api_calls,
            "api_errors": self.api_errors,
            "total_request_time": f"{self.total_request_time:.2f}s",
            "avg_request_time": f"{self.avg_request_time:.2f}s",
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": f"{self.duration_seconds:.2f}s",
            "success_rate": f"{self.success_rate:.1f}%",
            "error_count": len(self.errors),
            "errors": self.errors[: Settings.MAX_ERRORS_TO_LOG],
        }


@dataclass
class NormalizedBookInfo:
    """
    Normalized book metadata extracted from inconsistent Audible/ABS data.

    Handles common issues like:
    - Volume numbers in title ("Solo Leveling, Vol. 8")
    - Series name in title ("Percy Jackson and the Olympians: The Lightning Thief")
    - Series info in subtitle ("Jack Reacher, Book 15")
    - Omnibus editions ("System Reborn Vol 5, 6, 7")
    """

    title: str  # Clean title without volume/series cruft
    subtitle: str | None  # Actual subtitle (not series info)
    series_name: str | None  # Series name from best available source
    series_position: str | None  # Position (can be "1", "1-3", "5-7", etc.)
    authors: list[str]
    asin: str
    isbn: str
    original_title: str  # Unmodified title for reference
    is_omnibus: bool = False  # Multi-volume collection
    source: str = "unknown"  # Which source had best series info: "audnex", "abs", "parsed"

    @property
    def display_title(self) -> str:
        """Get clean display title."""
        if self.subtitle:
            return f"{self.title}: {self.subtitle}"
        return self.title

    @property
    def series_display(self) -> str | None:
        """Get formatted series display like 'Series Name #5'."""
        if not self.series_name:
            return None
        if self.series_position:
            return f"{self.series_name} #{self.series_position}"
        return self.series_name

    @property
    def search_title(self) -> str:
        """
        Get optimized title for search APIs.

        Removes volume numbers and series prefixes that hurt search matching.
        """
        return self.title

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "series_name": self.series_name,
            "series_position": self.series_position,
            "authors": self.authors,
            "asin": self.asin,
            "isbn": self.isbn,
            "original_title": self.original_title,
            "is_omnibus": self.is_omnibus,
            "source": self.source,
            "display_title": self.display_title,
            "series_display": self.series_display,
        }


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                      📖 TITLE/SERIES PARSING HELPERS                         ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# Regex patterns for extracting volume/book numbers from titles and subtitles

# Pattern: "Vol. 8", "Vol 8", "Volume 8", "Volume: 8"
VOLUME_PATTERN = re.compile(
    r",?\s*(?:Vol(?:ume)?\.?\s*:?\s*)(\d+(?:[,-]\s*\d+)*)",
    re.IGNORECASE,
)

# Pattern: "Book 8", "Book: 8", ", Book 8"
BOOK_PATTERN = re.compile(
    r",?\s*(?:Book\s*:?\s*)(\d+)",
    re.IGNORECASE,
)

# Pattern: "Books 1-3", "Books 1, 2, 3"
BOOKS_RANGE_PATTERN = re.compile(
    r",?\s*(?:Books?\s*:?\s*)(\d+(?:\s*[-,&]\s*\d+)+)",
    re.IGNORECASE,
)

# Pattern for series position in subtitle: "Series Name, Book 5" or "Series Name 5"
SUBTITLE_SERIES_PATTERN = re.compile(
    r"^(.+?),?\s*(?:Book\s*)?(\d+)$",
    re.IGNORECASE,
)

# Pattern: Title followed by colon and possible series
# (e.g., "Percy Jackson and the Olympians: The Lightning Thief")
TITLE_SERIES_PREFIX_PATTERN = re.compile(
    r"^(.+?):\s+(.+)$",
)

# abs.series pattern: "Series Name #5" or "Series Name #1-3"
ABS_SERIES_PATTERN = re.compile(
    r"^(.+?)\s*#\s*(\d+(?:\.\d+)?(?:\s*[-,]\s*\d+(?:\.\d+)?)*)$",
)

# Omnibus detection patterns
OMNIBUS_INDICATORS = [
    r"vol\s*\d+\s*[-,&]\s*\d+",  # Vol 1-3, Vol 1, 2
    r"books?\s*\d+\s*[-,&]\s*\d+",  # Books 1-3, Book 1 & 2
    r"\d+\s*[-&]\s*\d+",  # Standalone range like 1-3
]
OMNIBUS_PATTERN = re.compile("|".join(OMNIBUS_INDICATORS), re.IGNORECASE)


def parse_abs_series(series_str: str | None) -> tuple[str | None, str | None]:
    """
    Parse ABS series format like "Jack Reacher #15" or "The Path of Ascension #1-3.5".

    Returns: (series_name, position)
    """
    if not series_str or not series_str.strip():
        return None, None

    match = ABS_SERIES_PATTERN.match(series_str.strip())
    if match:
        return match.group(1).strip(), match.group(2).strip()

    # If no position marker, the whole string might be the series name
    return series_str.strip(), None


def clean_title_from_volume(title: str) -> tuple[str, str | None, bool]:
    """
    Remove volume/book numbers from title.

    Returns: (clean_title, position, is_omnibus)

    Examples:
        "Solo Leveling, Vol. 8" -> ("Solo Leveling", "8", False)
        "System Reborn Vol 5, 6, 7" -> ("System Reborn", "5-7", True)
        "The Path of Ascension book 5" -> ("The Path of Ascension", "5", False)
    """
    is_omnibus = bool(OMNIBUS_PATTERN.search(title))
    position = None
    clean = title

    # Try volume patterns first
    vol_match = VOLUME_PATTERN.search(title)
    if vol_match:
        position = vol_match.group(1).replace(" ", "").replace(",", "-")
        clean = VOLUME_PATTERN.sub("", title).strip()
        clean = clean.rstrip(",").strip()

    # Try book patterns
    if not position:
        book_match = BOOKS_RANGE_PATTERN.search(title) or BOOK_PATTERN.search(title)
        if book_match:
            position = book_match.group(1).replace(" ", "").replace(",", "-")
            pattern = BOOKS_RANGE_PATTERN if BOOKS_RANGE_PATTERN.search(title) else BOOK_PATTERN
            clean = pattern.sub("", title).strip()
            clean = clean.rstrip(",").strip()

    return clean.rstrip(":").strip(), position, is_omnibus


def extract_series_from_subtitle(subtitle: str | None) -> tuple[str | None, str | None, str | None]:
    """
    Extract series info when subtitle contains "Series Name, Book N" format.

    Returns: (series_name, position, actual_subtitle_if_different)

    Examples:
        "Jack Reacher, Book 15" -> ("Jack Reacher", "15", None)
        "Jack Reacher 8" -> ("Jack Reacher", "8", None)
        "The Demon Lord Rises (Black Summoner, Book 5)" ->
            ("Black Summoner", "5", "The Demon Lord Rises")
        "A LitRPG Adventure" -> (None, None, "A LitRPG Adventure")
    """
    if not subtitle:
        return None, None, None

    # Check for parenthetical series info: "The Demon Lord Rises (Black Summoner, Book 5)"
    # Improved pattern to properly capture "Series Name, Book N" or just "Series Name N"
    paren_match = re.search(r"^(.+?)\s*\(([^,)]+)(?:,\s*|\s+)(?:Book\s*)?(\d+)\)$", subtitle)
    if paren_match:
        actual_subtitle = paren_match.group(1).strip()
        series = paren_match.group(2).strip()
        pos = paren_match.group(3)
        return series, pos, actual_subtitle

    # Check for "Series Name, Book N" format
    match = SUBTITLE_SERIES_PATTERN.match(subtitle)
    if match:
        potential_series = match.group(1).strip()
        position = match.group(2)

        # Heuristic: if it looks like an actual subtitle (descriptive), keep it
        # Series names tend to be shorter or contain certain keywords
        descriptive_indicators = [
            "adventure",
            "novel",
            "story",
            "tale",
            "saga",
            "journey",
            "mystery",
            "romance",
            "thriller",
            "fantasy",
            "sci-fi",
        ]
        if any(ind in potential_series.lower() for ind in descriptive_indicators):
            return None, None, subtitle

        return potential_series, position, None

    # No series info found, return as actual subtitle
    return None, None, subtitle


def split_title_on_series_prefix(
    title: str, known_series: str | None = None
) -> tuple[str, str | None]:
    """
    Handle titles like "Percy Jackson and the Olympians: The Lightning Thief".

    If the text before the colon matches a known series, split it out.

    Returns: (clean_title, detected_series)
    """
    match = TITLE_SERIES_PREFIX_PATTERN.match(title)
    if not match:
        return title, None

    prefix = match.group(1).strip()
    suffix = match.group(2).strip()

    if known_series and fuzz.ratio(prefix.lower(), known_series.lower()) > 85:
        return suffix, prefix

    # Heuristic: long prefixes with colons are often series names
    # But short ones like "Batman: Resurrection" are actual titles
    if len(prefix) > 15 and ":" not in suffix:
        return suffix, prefix

    return title, None


def extract_normalized_book_info(book_data: dict[str, Any]) -> NormalizedBookInfo:
    """
    Extract and normalize book metadata from combined ABS + Audnex data.

    This function resolves inconsistencies between different sources and
    cleans up titles that have volume numbers, series prefixes, etc.

    Priority for series info:
    1. audnex.seriesPrimary (most reliable when present)
    2. abs.series (parsed format like "Series #5")
    3. Parsed from subtitle
    4. Parsed from title
    """
    abs_data = book_data.get("abs", {}) or {}
    audnex_data = book_data.get("audnex", {}) or {}

    # Get raw values
    original_title = abs_data.get("title", "") or audnex_data.get("title", "") or ""
    abs_subtitle = abs_data.get("subtitle")
    audnex_subtitle = audnex_data.get("subtitle")
    abs_series = abs_data.get("series", "")
    authors = abs_data.get("authors", []) or []
    asin = abs_data.get("asin", "") or audnex_data.get("asin", "") or ""
    isbn = abs_data.get("isbn", "") or audnex_data.get("isbn", "") or ""

    # Get audnex series info (most reliable when present)
    audnex_series_info = audnex_data.get("seriesPrimary", {}) or {}
    audnex_series_name = audnex_series_info.get("name") if audnex_series_info else None
    audnex_series_pos = audnex_series_info.get("position") if audnex_series_info else None

    # Initialize result values
    series_name: str | None = None
    series_position: str | None = None
    actual_subtitle: str | None = None
    source = "unknown"
    is_omnibus = False

    # Step 1: Clean volume/book numbers from title
    clean_title, title_position, is_omnibus = clean_title_from_volume(original_title)

    # Step 2: Determine series info from best source
    if audnex_series_name:
        # Audnex has explicit series info - most reliable
        series_name = audnex_series_name
        series_position = audnex_series_pos
        source = "audnex"
    elif abs_series:
        # Parse ABS series format
        parsed_name, parsed_pos = parse_abs_series(abs_series)
        if parsed_name:
            series_name = parsed_name
            series_position = parsed_pos
            source = "abs"

    # Step 3: Extract series from subtitle if not found elsewhere
    subtitle_to_check = audnex_subtitle or abs_subtitle
    sub_series, sub_pos, remaining_subtitle = extract_series_from_subtitle(subtitle_to_check)

    if not series_name and sub_series:
        series_name = sub_series
        series_position = sub_pos
        source = "subtitle"
        actual_subtitle = remaining_subtitle
    elif remaining_subtitle:
        actual_subtitle = remaining_subtitle
    elif subtitle_to_check and not sub_series:
        # Subtitle exists but doesn't contain series info
        actual_subtitle = subtitle_to_check

    # Step 4: If still no position, use one parsed from title
    if series_name and not series_position and title_position:
        series_position = title_position
        if source == "unknown":
            source = "title"

    # Step 5: Handle series prefix in title (e.g., "Percy Jackson: The Lightning Thief")
    if series_name:
        final_title, detected_series = split_title_on_series_prefix(clean_title, series_name)
        if detected_series:
            clean_title = final_title

    # Determine omnibus status from position pattern
    if series_position and "-" in series_position:
        is_omnibus = True

    return NormalizedBookInfo(
        title=clean_title.strip(),
        subtitle=actual_subtitle.strip() if actual_subtitle else None,
        series_name=series_name,
        series_position=str(series_position) if series_position else None,
        authors=authors,
        asin=asin,
        isbn=isbn,
        original_title=original_title,
        is_omnibus=is_omnibus,
        source=source,
    )


def normalize_keyword_list(values: list[str]) -> tuple[list[str], list[str]]:
    """Return (raw, normalized_unique) keyword lists."""
    raw_values: list[str] = []
    normalized: list[str] = []
    seen: set[str] = set()

    for val in values or []:
        if not val:
            continue
        raw_values.append(val)
        cleaned = " ".join(val.split()).strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(cleaned)

    return raw_values, normalized


@dataclass
class BookKeywords:
    """Keywords associated with a book (raw + normalized)."""

    raw_genres: list[str] = field(default_factory=list)
    raw_moods: list[str] = field(default_factory=list)
    raw_content_warnings: list[str] = field(default_factory=list)
    raw_tags: list[str] = field(default_factory=list)

    genres: list[str] = field(default_factory=list)
    moods: list[str] = field(default_factory=list)
    content_warnings: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    @property
    def total_count(self) -> int:
        """Get total keyword count."""
        return len(self.genres) + len(self.moods) + len(self.content_warnings) + len(self.tags)

    def has_keywords(self) -> bool:
        """Check if any keywords exist."""
        return self.total_count > 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize raw and normalized keyword sets."""
        return {
            "raw": {
                "genres": self.raw_genres,
                "moods": self.raw_moods,
                "content_warnings": self.raw_content_warnings,
                "tags": self.raw_tags,
            },
            "normalized": {
                "genres": self.genres,
                "moods": self.moods,
                "content_warnings": self.content_warnings,
                "tags": self.tags,
            },
        }


@dataclass
class SearchResult:
    """Result of searching for a book with normalized metadata."""

    title: str  # Clean title (may be normalized)
    authors: list[str]
    asin: str
    isbn: str
    # Normalized metadata fields
    subtitle: str | None = None
    series_name: str | None = None
    series_position: str | None = None
    original_title: str | None = None  # Unmodified title for reference
    is_omnibus: bool = False
    metadata_source: str = "unknown"  # Where series info came from
    # Hardcover enrichment data
    hardcover_id: str | None = None
    hardcover_rating: float | None = None
    hardcover_rating_count: int | None = None
    keywords: BookKeywords = field(default_factory=BookKeywords)
    search_query: str = ""
    search_match_score: float = 0.0
    searched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    cached: bool = False

    @property
    def display_name(self) -> str:
        """Get display name for the book."""
        author = self.authors[0] if self.authors else "Unknown"
        return f"{self.title} by {author}"

    @property
    def series_display(self) -> str | None:
        """Get formatted series display like 'Series Name #5'."""
        if not self.series_name:
            return None
        if self.series_position:
            return f"{self.series_name} #{self.series_position}"
        return self.series_name

    @property
    def status_emoji(self) -> str:
        """Get status emoji based on result."""
        if self.cached:
            return STATUS_EMOJIS["cached"]
        if self.search_match_score > 0:
            return STATUS_EMOJIS["found"]
        return STATUS_EMOJIS["failed"]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "series_name": self.series_name,
            "series_position": self.series_position,
            "series_display": self.series_display,
            "original_title": self.original_title,
            "is_omnibus": self.is_omnibus,
            "metadata_source": self.metadata_source,
            "authors": self.authors,
            "asin": self.asin,
            "isbn": self.isbn,
            "hardcover_id": self.hardcover_id,
            "hardcover_rating": self.hardcover_rating,
            "hardcover_rating_count": self.hardcover_rating_count,
            "keywords": self.keywords.to_dict(),
            "search_query": self.search_query,
            "search_match_score": self.search_match_score,
            "searched_at": self.searched_at.isoformat(),
            "cached": self.cached,
        }


@dataclass
class EnrichedDataSchema:
    """Complete schema for enriched book data."""

    version: str = "2.0.0"
    schema_created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    run_metadata: dict[str, Any] = field(default_factory=dict)
    execution_stats: ExecutionStats = field(default_factory=ExecutionStats)
    books: list[SearchResult] = field(default_factory=list)
    keywords_summary: dict[str, int] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    settings_used: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self, include_books: bool = False) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        data = {
            "metadata": {
                "version": self.version,
                "schema_created_at": self.schema_created_at.isoformat(),
                "description": "Book data enriched with Hardcover API keywords",
                **self.run_metadata,
            },
            "execution_stats": self.execution_stats.to_dict(),
            "summary": self.summary,
            "keywords_summary": self.keywords_summary,
            "settings_used": self.settings_used,
            "error_count": len(self.errors),
            "errors": self.errors[: Settings.MAX_ERRORS_TO_LOG],
        }

        if include_books:
            data["books"] = [book.to_dict() for book in self.books]

        return data


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                        🎯 RATE LIMITER                                       ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


class RateLimiter:
    """Smart rate limiter for API requests."""

    def __init__(self, max_concurrent: int, min_interval: float):
        """Initialize rate limiter."""
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.min_interval = min_interval
        self.last_request_time = 0.0
        self.lock = asyncio.Lock()

    async def __aenter__(self):
        """Async context manager entry."""
        await self.semaphore.acquire()
        async with self.lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            wait_time = max(0, self.min_interval - (now - self.last_request_time))
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            self.last_request_time = loop.time()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        self.semaphore.release()


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                      🖼️ LIVE DASHBOARD COMPONENTS                            ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


class LiveDashboard:
    """Beautiful live dashboard for monitoring enrichment progress."""

    def __init__(self, stats: ExecutionStats, total_books: int):
        """Initialize the dashboard."""
        self.stats = stats
        self.total_books = total_books
        self.recent_books: list[tuple[str, str]] = []  # (title, status)
        self.max_recent = 5

        # Create progress bar once and reuse it
        self.progress_bar = Progress(
            SpinnerColumn("dots12", style=f"bold {COLORS['accent']}"),
            TextColumn("[bold #7C3AED]{task.description}"),
            BarColumn(
                bar_width=40,
                style=COLORS["muted"],
                complete_style=COLORS["success"],
                finished_style=COLORS["gold"],
            ),
            TaskProgressColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TextColumn("•"),
            TimeRemainingColumn(),
        )
        self.progress_task = self.progress_bar.add_task(
            "Processing", total=self.total_books, completed=0
        )

    def add_recent_book(self, title: str, status: str) -> None:
        """Add a recently processed book."""
        self.recent_books.insert(0, (title[:40] + "..." if len(title) > 40 else title, status))
        if len(self.recent_books) > self.max_recent:
            self.recent_books.pop()

    def create_header_panel(self) -> Panel:
        """Create the header panel with logo and status."""
        header_text = Text()
        header_text.append("📚 ", style="bold")
        header_text.append("HARDCOVER ", style=f"bold {COLORS['primary']}")
        header_text.append("ENRICHMENT ", style=f"bold {COLORS['accent']}")
        header_text.append("ENGINE ", style=f"bold {COLORS['secondary']}")
        header_text.append("v2.0", style=f"dim {COLORS['muted']}")

        mode_text = Text()
        mode_text.append("⚡ ", style="bold yellow")
        mode_text.append("LIVE ", style="bold green")
        mode_text.append("MODE", style="bold green")

        content = Columns([header_text, mode_text], expand=True)

        return Panel(
            Align.center(content),
            border_style=Style(color=COLORS["primary"]),
            box=box.DOUBLE,
        )

    def create_stats_panel(self) -> Panel:
        """Create the main statistics panel."""
        # Update progress bar with current stats
        processed = self.stats.books_searched + self.stats.books_cached + self.stats.books_failed
        self.progress_bar.update(self.progress_task, completed=processed)

        # Stats grid
        stats_table = Table(
            show_header=False,
            box=box.SIMPLE,
            padding=(0, 2),
            expand=True,
        )
        stats_table.add_column("Metric", style=f"bold {COLORS['secondary']}")
        stats_table.add_column("Value", style=f"bold {COLORS['success']}")
        stats_table.add_column("Metric", style=f"bold {COLORS['secondary']}")
        stats_table.add_column("Value", style=f"bold {COLORS['success']}")

        stats_table.add_row(
            "📊 Searched",
            str(self.stats.books_searched),
            "📦 Cached",
            str(self.stats.books_cached),
        )
        stats_table.add_row(
            "❌ Failed",
            f"[red]{self.stats.books_failed}[/]",
            "📡 API Calls",
            str(self.stats.api_calls),
        )
        stats_table.add_row(
            "⚡ Speed",
            f"{self.stats.books_per_second:.2f}/s",
            "⏱️ Elapsed",
            f"{self.stats.elapsed_time:.1f}s",
        )
        stats_table.add_row(
            "✅ Success",
            f"[green]{self.stats.success_rate:.1f}%[/]",
            "⚠️ Errors",
            f"[yellow]{self.stats.api_errors}[/]",
        )

        # Combine elements
        content = Group(
            self.progress_bar,
            Text(),
            stats_table,
        )

        return Panel(
            content,
            title="[bold #7C3AED]📈 LIVE STATISTICS[/]",
            border_style=Style(color=COLORS["primary"]),
            box=box.ROUNDED,
        )

    def create_recent_panel(self) -> Panel:
        """Create the recent activity panel."""
        if not self.recent_books:
            content = Text("Waiting for first book...", style="dim italic")
        else:
            table = Table(show_header=False, box=None, padding=(0, 1))
            table.add_column("Status", width=3)
            table.add_column("Title")

            for title, status in self.recent_books:
                emoji = {"found": "✅", "cached": "📦", "failed": "❌"}.get(status, "🔍")
                style = {"found": "green", "cached": "cyan", "failed": "red"}.get(status, "white")
                table.add_row(emoji, Text(title, style=style))

            content = table

        return Panel(
            content,
            title="[bold #EC4899]🔄 RECENT ACTIVITY[/]",
            border_style=Style(color=COLORS["accent"]),
            box=box.ROUNDED,
        )

    def create_current_book_panel(self) -> Panel:
        """Create panel showing current book being processed."""
        if self.stats.current_book:
            content = Group(
                Text("🔮 Currently enriching:", style=f"dim {COLORS['muted']}"),
                Text(),
                Text(self.stats.current_book, style=f"bold {COLORS['secondary']}"),
            )
        else:
            content = Align.center(
                Text("⏳ Waiting for next book...", style=f"dim italic {COLORS['muted']}")
            )

        return Panel(
            content,
            title="[bold #06B6D4]🎯 CURRENT TASK[/]",
            border_style=Style(color=COLORS["secondary"]),
            box=box.ROUNDED,
        )

    def create_api_health_panel(self) -> Panel:
        """Create API health indicator panel."""
        # Health indicators
        error_rate = (
            (self.stats.api_errors / max(self.stats.api_calls, 1)) * 100
            if self.stats.api_calls > 0
            else 0
        )

        if error_rate < 5:
            health_status = Text("● HEALTHY", style="bold green")
            health_color = COLORS["success"]
        elif error_rate < 15:
            health_status = Text("● DEGRADED", style="bold yellow")
            health_color = COLORS["warning"]
        else:
            health_status = Text("● CRITICAL", style="bold red")
            health_color = COLORS["error"]

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Label", style="dim")
        table.add_column("Value", style="bold")

        table.add_row("Status", health_status)
        table.add_row("Avg Latency", f"{self.stats.avg_request_time * 1000:.0f}ms")
        table.add_row("Error Rate", f"{error_rate:.1f}%")

        return Panel(
            table,
            title="[bold #10B981]🏥 API HEALTH[/]",
            border_style=Style(color=health_color),
            box=box.ROUNDED,
        )

    def generate_layout(self) -> Layout:
        """Generate the complete dashboard layout."""
        layout = Layout()

        layout.split(
            Layout(name="header", size=3),
            Layout(name="main", ratio=1),
            Layout(name="footer", size=8),
        )

        layout["header"].update(self.create_header_panel())

        layout["main"].split_row(
            Layout(name="stats", ratio=3),
            Layout(name="sidebar", ratio=1),
        )

        layout["stats"].update(self.create_stats_panel())

        layout["sidebar"].split(
            Layout(name="current", size=6),
            Layout(name="health", ratio=1),
        )

        layout["sidebar"]["current"].update(self.create_current_book_panel())
        layout["sidebar"]["health"].update(self.create_api_health_panel())

        layout["footer"].update(self.create_recent_panel())

        return layout


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                      🔮 MAIN ENRICHER CLASS                                  ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


class HardcoverEnricher:
    """Enriches book metadata with Hardcover API data - with stunning visuals!"""

    def __init__(self, dry_run: bool = False):
        """Initialize enricher with beautiful startup."""
        self.dry_run = dry_run
        self.stats = ExecutionStats()
        self.search_cache: dict[str, SearchResult] = {}
        self.enriched_schema = EnrichedDataSchema()
        self._keyword_counters: dict[str, Counter] = {}
        self.run_id = (
            f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_hardcover_{uuid.uuid4().hex[:8]}"
        )
        self.rate_limiter = RateLimiter(
            Settings.MAX_CONCURRENT_REQUESTS,
            Settings.MIN_REQUEST_INTERVAL,
        )
        self.ssl_context = self._create_ssl_context()
        self.http_client: httpx.AsyncClient | None = None
        self.dashboard: LiveDashboard | None = None

    @staticmethod
    def _create_ssl_context() -> ssl.SSLContext:
        """Create SSL context for secure connections."""
        context = ssl.create_default_context()
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        return context

    async def get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with connection pooling."""
        if self.http_client is None:
            limits = httpx.Limits(
                max_connections=Settings.CONNECTION_POOL_SIZE,
                max_keepalive_connections=Settings.CONNECTION_POOL_SIZE,
                keepalive_expiry=Settings.KEEPALIVE_EXPIRY,
            )
            self.http_client = httpx.AsyncClient(
                verify=self.ssl_context,
                timeout=Settings.API_TIMEOUT,
                limits=limits,
            )
        return self.http_client

    async def close_http_client(self) -> None:
        """Close HTTP client."""
        if self.http_client is not None:
            await self.http_client.aclose()
            self.http_client = None

    def load_combined_metadata(self) -> list[dict[str, Any]]:
        """Load combined metadata from file with beautiful output."""
        console.print()

        # Create loading panel
        loading_panel = Panel(
            Group(
                Align.center(Text("📂 LOADING METADATA", style=f"bold {COLORS['primary']}")),
                Text(),
                Align.center(
                    Text(str(Settings.COMBINED_METADATA_FILE), style=f"dim {COLORS['secondary']}")
                ),
            ),
            border_style=Style(color=COLORS["primary"]),
            box=box.DOUBLE_EDGE,
        )
        console.print(loading_panel)

        if not Settings.COMBINED_METADATA_FILE.exists():
            error_panel = Panel(
                Group(
                    Text("❌ FILE NOT FOUND", style="bold red"),
                    Text(),
                    Text(str(Settings.COMBINED_METADATA_FILE), style="dim"),
                ),
                border_style="red",
                box=box.HEAVY,
            )
            console.print(error_panel)
            raise FileNotFoundError(f"{Settings.COMBINED_METADATA_FILE} not found")

        with (
            console.status("[bold #7C3AED]Reading file...[/]", spinner="dots12"),
            open(Settings.COMBINED_METADATA_FILE, encoding="utf-8") as f,
        ):
            data = json.load(f)

        success_text = Text()
        success_text.append("✅ ", style="bold green")
        success_text.append("Successfully loaded ", style="green")
        success_text.append(f"{len(data):,}", style=f"bold {COLORS['gold']}")
        success_text.append(" books", style="green")

        console.print(Padding(success_text, (1, 0)))
        return data

    def load_search_cache(self) -> None:
        """Load previously searched books from cache with visual feedback."""
        if not Settings.CACHE_ENABLED or not Settings.SEARCH_CACHE_FILE.exists():
            console.print(
                Padding(
                    Text("📦 Cache: Not available or disabled", style=f"dim {COLORS['muted']}"),
                    (0, 0, 1, 0),
                )
            )
            return

        cache_panel = Panel(
            Text("📦 Loading search cache...", style=f"bold {COLORS['secondary']}"),
            border_style=Style(color=COLORS["secondary"]),
            box=box.ROUNDED,
        )
        console.print(cache_panel)

        try:
            with console.status(
                f"[bold {COLORS['secondary']}]Reading cache file...[/]", spinner="moon"
            ):
                with open(Settings.SEARCH_CACHE_FILE, encoding="utf-8") as f:
                    cache_data = json.load(f)

                # Reconstruct SearchResult objects
                for book_data in cache_data.get("books", []):
                    key = f"{book_data['title']}:{book_data['asin']}"
                    # Extract keywords from nested structure (raw or normalized)
                    kw_data = book_data.get("keywords", {})
                    kw_raw = kw_data.get("raw", {})
                    kw_norm = kw_data.get("normalized", {})
                    result = SearchResult(
                        title=book_data["title"],
                        authors=book_data["authors"],
                        asin=book_data["asin"],
                        isbn=book_data["isbn"],
                        hardcover_id=book_data.get("hardcover_id"),
                        hardcover_rating=book_data.get("hardcover_rating"),
                        hardcover_rating_count=book_data.get("hardcover_rating_count"),
                        keywords=BookKeywords(
                            raw_genres=kw_raw.get("genres", []),
                            raw_moods=kw_raw.get("moods", []),
                            raw_content_warnings=kw_raw.get("content_warnings", []),
                            raw_tags=kw_raw.get("tags", []),
                            genres=kw_norm.get("genres", []),
                            moods=kw_norm.get("moods", []),
                            content_warnings=kw_norm.get("content_warnings", []),
                            tags=kw_norm.get("tags", []),
                        ),
                        search_query=book_data.get("search_query", ""),
                        search_match_score=book_data.get("search_match_score", 0.0),
                        cached=True,
                    )
                    self.search_cache[key] = result

            # Success message with stats
            cache_text = Text()
            cache_text.append("✅ ", style="bold green")
            cache_text.append("Cache loaded: ", style="green")
            cache_text.append(f"{len(self.search_cache):,}", style=f"bold {COLORS['gold']}")
            cache_text.append(" books ready", style="green")
            console.print(Padding(cache_text, (0, 0, 1, 2)))

        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")
            console.print(
                Padding(
                    Text(f"⚠️ Cache load failed: {e}", style=f"dim {COLORS['warning']}"),
                    (0, 0, 1, 2),
                )
            )

    def save_search_cache(self) -> None:
        """Save search cache with visual feedback."""
        if not Settings.CACHE_ENABLED:
            return

        Settings.SEARCH_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

        cache_data = {
            "metadata": {
                "version": "2.0.0",
                "last_updated": datetime.now(UTC).isoformat(),
                "description": "Cache of previously searched books to avoid redundant API calls",
            },
            "books": [book.to_dict() for book in self.search_cache.values()],
        }

        # Atomic write to prevent corruption
        import tempfile
        Settings.SEARCH_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with console.status(f"[bold {COLORS['secondary']}]💾 Saving cache...[/]", spinner="dots"):
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=Settings.SEARCH_CACHE_FILE.parent,
                delete=False,
                encoding="utf-8",
                suffix=".tmp",
            ) as tmp:
                json.dump(cache_data, tmp, indent=2)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp.name, Settings.SEARCH_CACHE_FILE)

        save_text = Text()
        save_text.append("💾 ", style="bold")
        save_text.append("Cache saved: ", style=f"{COLORS['success']}")
        save_text.append(f"{len(self.search_cache):,}", style=f"bold {COLORS['gold']}")
        save_text.append(" books", style=f"{COLORS['success']}")
        console.print(save_text)

    async def search_book_hardcover(self, title: str, author: str) -> dict[str, Any] | None:
        """Search for book on Hardcover API with retry logic using the dedicated search endpoint.

        Uses the /v1/search endpoint as documented in the Hardcover API Search guide.
        This endpoint uses Typesense for fast, relevant results.

        Reference: docs/hardcover/api/guides/Searching.mdx
        """
        search_query = f"{title} {author}".strip()

        logger.debug(f"Searching Hardcover API: title='{title}', author='{author}'")

        # Use GraphQL query with search as documented in API
        # The search query returns Typesense results via GraphQL
        query_payload = {
            "query": """
            query SearchBooks($query: String!, $queryType: String!, $perPage: Int!) {
              search(query: $query, query_type: $queryType, per_page: $perPage) {
                results
              }
            }
            """,
            "variables": {
                "query": search_query,
                "queryType": "book",  # lowercase per docs
                "perPage": 5,
            },
        }

        for attempt in range(Settings.API_RETRIES):
            try:
                # Check circuit breaker before attempting request
                with hardcover_breaker:
                    async with self.rate_limiter:
                        client = await self.get_http_client()
                        headers = {
                            "authorization": f"Bearer {Settings.API_KEY}",
                            "content-type": "application/json",
                            "user-agent": "MAMFast-Hardcover-Enrichment/2.0.0",  # noqa: E501
                        }

                        loop = asyncio.get_running_loop()
                        start_time = loop.time()
                        response = await client.post(
                            Settings.API_ENDPOINT,
                            json=query_payload,
                            headers=headers,
                        )
                        request_time = loop.time() - start_time
                        self.stats.total_request_time += request_time

                    logger.debug(
                        f"API Response Status: {response.status_code}, Time: {request_time:.2f}s"
                    )

                    if response.status_code == 200:
                        data = response.json()
                        logger.debug(f"API Response Data: {json.dumps(data, indent=2)[:1000]}...")

                        # Check for GraphQL errors
                        if "errors" in data:
                            logger.error(f"GraphQL errors for '{search_query}': {data['errors']}")
                            return None

                        # Get the results - may be a dict or JSON string
                        results = data.get("data", {}).get("search", {}).get("results")

                        if results:
                            try:
                                # If results is a string, parse it; if dict, use directly
                                if isinstance(results, str):
                                    results = json.loads(results)

                                hits = results.get("hits", [])

                                if hits:
                                    logger.debug(f"Found {len(hits)} books for '{search_query}'")
                                    # Get the first hit's document
                                    doc = hits[0].get("document", {})
                                    # Search API returns arrays, not nested objects
                                    # Ref: docs/hardcover/api/guides/Searching.mdx

                                    # Transform to expected format
                                    return {
                                        "id": doc.get("id"),
                                        "title": doc.get("title"),
                                        "authors": [
                                            {"name": name}
                                            for name in (doc.get("author_names") or [])
                                        ],
                                        "rating": doc.get("rating"),
                                        "rating_count": doc.get("ratings_count"),
                                        "genres": [
                                            {"name": genre} for genre in (doc.get("genres") or [])
                                        ],
                                        "moods": [
                                            {"name": mood} for mood in (doc.get("moods") or [])
                                        ],
                                        "tags": [{"name": tag} for tag in (doc.get("tags") or [])],
                                        "content_warnings": [
                                            {"name": warning}
                                            for warning in (doc.get("content_warnings") or [])
                                        ],
                                    }
                                else:
                                    logger.debug(f"No hits in results for '{search_query}'")
                            except (json.JSONDecodeError, AttributeError, TypeError, KeyError) as e:
                                logger.error(
                                    f"Failed to parse Typesense results for '{search_query}': {e}"
                                )
                                logger.debug(
                                    f"Results type: {type(results)}, value: {str(results)[:500]}"
                                )
                        else:
                            logger.debug(f"Empty results for '{search_query}'")
                        return None

                    elif response.status_code == 401:
                        logger.error(
                            "Hardcover API authentication failed - token expired or invalid"
                        )
                        return None
                    elif response.status_code == 403:
                        logger.error(f"API forbidden for '{search_query}' - check permissions")
                        return None
                    elif response.status_code == 404:
                        logger.debug(f"Resource not found for '{search_query}'")
                        return None
                    elif response.status_code == 429:
                        wait_time = int(response.headers.get("retry-after", 60))
                        logger.warning(f"Rate limited (60/min). Waiting {wait_time}s before retry")
                        await asyncio.sleep(wait_time)
                        continue
                    elif response.status_code == 500:
                        self.stats.api_errors += 1
                        if attempt < Settings.API_RETRIES - 1:
                            logger.warning(f"Server error (500) for '{search_query}', retrying...")
                            await asyncio.sleep(2.0 * (attempt + 1))
                            continue
                        else:
                            logger.error(f"Server error persists for '{search_query}'")
                            return None
                    else:
                        if Settings.VERBOSE_LOGGING:
                            logger.warning(
                                f"API returned status {response.status_code} for '{search_query}'"
                            )
                        return None

            except CircuitOpenError as e:
                # Circuit breaker is open, fail fast without retrying
                logger.warning(
                    f"Circuit breaker open for Hardcover API: {e.service_name}. "
                    f"Retry after {e.retry_after:.1f}s"
                )
                self.stats.api_errors += 1
                return None

            except (httpx.TimeoutException, TimeoutError):
                self.stats.api_errors += 1
                if attempt < Settings.API_RETRIES - 1:
                    backoff = min(Settings.REQUEST_TIMEOUT_MAX, Settings.API_TIMEOUT * (2**attempt))
                    logger.debug(f"Timeout on '{search_query}', retrying in {backoff}s")
                    await asyncio.sleep(backoff)
                    continue
                else:
                    logger.warning(f"Timeout exhausted for '{search_query}'")
                    return None

            except (httpx.ConnectError, httpx.RemoteProtocolError) as e:
                self.stats.api_errors += 1
                if attempt < Settings.API_RETRIES - 1:
                    logger.debug(f"Connection error for '{search_query}', retrying: {e}")
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue
                else:
                    logger.warning(f"Connection failed for '{search_query}': {e}")
                    return None

            except Exception as e:
                self.stats.api_errors += 1
                logger.error(f"Error searching for '{search_query}': {e}")
                return None

        return None

    def extract_keywords(self, book_data: dict[str, Any]) -> BookKeywords:
        """Extract keywords from Hardcover book data."""
        keywords = BookKeywords()

        if not book_data:
            return keywords

        if isinstance(book_data.get("genres"), list):
            raw_genres = [g.get("name", "") for g in book_data["genres"] if isinstance(g, dict)]
            keywords.raw_genres, keywords.genres = normalize_keyword_list(raw_genres)

        if isinstance(book_data.get("moods"), list):
            raw_moods = [m.get("name", "") for m in book_data["moods"] if isinstance(m, dict)]
            keywords.raw_moods, keywords.moods = normalize_keyword_list(raw_moods)

        if isinstance(book_data.get("content_warnings"), list):
            raw_warnings = [
                w.get("name", "") for w in book_data["content_warnings"] if isinstance(w, dict)
            ]
            keywords.raw_content_warnings, keywords.content_warnings = normalize_keyword_list(
                raw_warnings
            )

        if isinstance(book_data.get("tags"), list):
            raw_tags = [t.get("name", "") for t in book_data["tags"] if isinstance(t, dict)]
            keywords.raw_tags, keywords.tags = normalize_keyword_list(raw_tags)

        return keywords

    def calculate_match_score(
        self, query_title: str, query_author: str, result: dict[str, Any]
    ) -> float:
        """Calculate fuzzy match score between query and result."""
        if not result:
            return 0.0

        result_title = result.get("title", "")
        result_authors = result.get("authors", [])
        result_author_names = [
            a.get("name", "") if isinstance(a, dict) else str(a) for a in result_authors
        ]

        title_score = fuzz.token_set_ratio(query_title.lower(), result_title.lower()) / 100.0

        author_score = 0.0
        for result_author in result_author_names:
            score = fuzz.token_set_ratio(query_author.lower(), result_author.lower()) / 100.0
            author_score = max(author_score, score)

        final_score = (title_score * 0.7) + (author_score * 0.3)

        return final_score if final_score >= Settings.FUZZ_MATCH_THRESHOLD else 0.0

    async def enrich_book(self, book_data: dict[str, Any]) -> SearchResult | None:
        """
        Enrich a single book with Hardcover data.

        Uses normalized book info extraction to get clean titles, series, and subtitles
        from the inconsistent ABS/Audnex data before searching Hardcover.
        """
        try:
            # Extract and normalize book metadata
            normalized = extract_normalized_book_info(book_data)

            if not normalized.title or not normalized.asin:
                return None

            author = normalized.authors[0] if normalized.authors else "Unknown"

            # Update dashboard with original title for display
            display_title = normalized.original_title or normalized.title
            self.stats.current_book = (
                f"{display_title[:50]}..." if len(display_title) > 50 else display_title
            )

            # Use normalized title + asin for cache key (more consistent)
            cache_key = f"{normalized.title}:{normalized.asin}"
            if cache_key in self.search_cache:
                self.stats.books_cached += 1
                cached_result = self.search_cache[cache_key]
                cached_result.cached = True
                if self.dashboard:
                    self.dashboard.add_recent_book(display_title, "cached")
                return cached_result

            self.stats.api_calls += 1

            # Use clean search title (without volume numbers, series prefixes)
            search_title = normalized.search_title
            hardcover_data = await self.search_book_hardcover(search_title, author)

            # Create result with normalized metadata
            result = SearchResult(
                title=normalized.title,
                subtitle=normalized.subtitle,
                series_name=normalized.series_name,
                series_position=normalized.series_position,
                original_title=normalized.original_title,
                is_omnibus=normalized.is_omnibus,
                metadata_source=normalized.source,
                authors=normalized.authors,
                asin=normalized.asin,
                isbn=normalized.isbn,
                search_query=f"{search_title} {author}",
            )

            if hardcover_data:
                result.hardcover_id = hardcover_data.get("id")
                result.hardcover_rating = hardcover_data.get("rating")
                result.hardcover_rating_count = hardcover_data.get("rating_count")
                result.keywords = self.extract_keywords(hardcover_data)
                result.search_match_score = self.calculate_match_score(
                    search_title, author, hardcover_data
                )

                if result.search_match_score > 0:
                    self.search_cache[cache_key] = result
                    self.stats.books_searched += 1
                    if self.dashboard:
                        self.dashboard.add_recent_book(display_title, "found")
                else:
                    self.stats.books_failed += 1
                    if self.dashboard:
                        self.dashboard.add_recent_book(display_title, "failed")
            else:
                self.stats.books_failed += 1
                if self.dashboard:
                    self.dashboard.add_recent_book(display_title, "failed")

            return result

        except Exception as e:
            logger.error(f"Error enriching book: {e}")
            self.stats.errors.append(str(e))
            self.stats.books_failed += 1
            return None

    async def enrich_all_books(self, books: list[dict[str, Any]]) -> None:
        """Enrich all books with live dashboard display."""
        self.stats.total_books = len(books)
        self.dashboard = LiveDashboard(self.stats, len(books))

        console.print()
        console.print(
            Rule("[bold #7C3AED]🚀 STARTING ENRICHMENT ENGINE[/]", style=COLORS["primary"])
        )
        console.print()

        with Live(self.dashboard.generate_layout(), refresh_per_second=4, console=console) as live:
            for i in range(0, len(books), Settings.BATCH_SIZE):
                batch = books[i : i + Settings.BATCH_SIZE]

                if self.dry_run:
                    for book_data in batch:
                        abs_data = book_data.get("abs", {})
                        result = SearchResult(
                            title=abs_data.get("title", ""),
                            authors=abs_data.get("authors", []),
                            asin=abs_data.get("asin", ""),
                            isbn=abs_data.get("isbn", ""),
                        )
                        if result.title and result.asin:
                            self.enriched_schema.books.append(result)
                            self.stats.books_searched += 1
                            self.dashboard.add_recent_book(result.title, "found")
                        live.update(self.dashboard.generate_layout())
                        await asyncio.sleep(0.05)  # Simulate processing
                else:
                    tasks = [self.enrich_book(book) for book in batch]
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    for idx, result in enumerate(results):
                        if isinstance(result, SearchResult):
                            self.enriched_schema.books.append(result)
                        elif isinstance(result, Exception):
                            # Log exception with context
                            book_ctx = batch[idx] if idx < len(batch) else {"title": "unknown"}
                            logger.error(
                                f"Failed to enrich book '{book_ctx.get('abs', {}).get('title', 'unknown')}': {result}"
                            )
                            self.stats.api_errors += 1
                        live.update(self.dashboard.generate_layout())

        self.stats.current_book = ""

    def build_keywords_summary(self) -> None:
        """Build keyword summary, distribution stats, and overall summary."""

        keyword_counts: dict[str, int] = {
            "total_genres": 0,
            "total_moods": 0,
            "total_content_warnings": 0,
            "total_tags": 0,
            "unique_genres": 0,
            "unique_moods": 0,
            "unique_content_warnings": 0,
            "unique_tags": 0,
        }

        counters = {
            "genres": Counter(),
            "moods": Counter(),
            "content_warnings": Counter(),
            "tags": Counter(),
        }

        books_with_any_keywords = 0
        books_with_content_warnings = 0
        match_scores: list[float] = []

        for book in self.enriched_schema.books:
            kw = book.keywords

            keyword_counts["total_genres"] += len(kw.genres)
            keyword_counts["total_moods"] += len(kw.moods)
            keyword_counts["total_content_warnings"] += len(kw.content_warnings)
            keyword_counts["total_tags"] += len(kw.tags)

            counters["genres"].update(kw.genres)
            counters["moods"].update(kw.moods)
            counters["content_warnings"].update(kw.content_warnings)
            counters["tags"].update(kw.tags)

            if kw.genres or kw.moods or kw.content_warnings or kw.tags:
                books_with_any_keywords += 1
            if kw.content_warnings:
                books_with_content_warnings += 1

            if book.search_match_score:
                match_scores.append(book.search_match_score)

        keyword_counts["unique_genres"] = len(counters["genres"])
        keyword_counts["unique_moods"] = len(counters["moods"])
        keyword_counts["unique_content_warnings"] = len(counters["content_warnings"])
        keyword_counts["unique_tags"] = len(counters["tags"])

        def percentile(values: list[float], pct: float) -> float | None:
            if not values:
                return None
            ordered = sorted(values)
            k = (len(ordered) - 1) * pct
            f = int(k)
            c = min(f + 1, len(ordered) - 1)
            if f == c:
                return ordered[f]
            return ordered[f] + (ordered[c] - ordered[f]) * (k - f)

        match_stats = {
            "count": len(match_scores),
            "min": min(match_scores) if match_scores else None,
            "max": max(match_scores) if match_scores else None,
            "p50": percentile(match_scores, 0.50),
            "p90": percentile(match_scores, 0.90),
            "mean": sum(match_scores) / len(match_scores) if match_scores else None,
        }

        top_n = 10
        top_keywords = {key: counters[key].most_common(top_n) for key in counters}

        self.enriched_schema.keywords_summary = keyword_counts
        self.enriched_schema.summary = {
            "matches": {
                "found": self.stats.books_searched,
                "cached": self.stats.books_cached,
                "failed": self.stats.books_failed,
            },
            "match_score": match_stats,
            "keyword_counts": {
                "unique_genres": keyword_counts["unique_genres"],
                "unique_moods": keyword_counts["unique_moods"],
                "unique_content_warnings": keyword_counts["unique_content_warnings"],
                "unique_tags": keyword_counts["unique_tags"],
            },
            "top_keywords": top_keywords,
            "warnings": {
                "books_with_warnings": books_with_content_warnings,
                "warnings_distribution": dict(counters["content_warnings"]),
                "coverage_pct": (books_with_content_warnings / self.stats.total_books * 100)
                if self.stats.total_books
                else 0,
            },
            "books_with_keywords": books_with_any_keywords,
        }

        # Persist counters for vocab output
        self._keyword_counters = counters

    @staticmethod
    def _file_sha256(path: Path) -> str | None:
        """Compute sha256 of a file if it exists."""
        if not path.exists():
            return None
        hasher = sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def _git_commit() -> str | None:
        """Return short git commit if available."""
        try:
            result = sh.git("rev-parse", "--short", "HEAD", _ok_code=[0])
            # sh library returns a result object; convert to string
            commit = str(result).strip()
            return commit if commit else None
        except (sh.ErrorReturnCode, sh.CommandNotFound, Exception):
            return None

    def save_enriched_data(self) -> None:
        """Save run metadata, JSONL books, and vocab with visual feedback."""
        Settings.ENRICHED_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        Settings.ENRICHED_BOOKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        Settings.ENRICHED_VOCAB_FILE.parent.mkdir(parents=True, exist_ok=True)

        now = datetime.now(UTC)

        self.enriched_schema.execution_stats = self.stats
        self.enriched_schema.execution_stats.end_time = now
        self.enriched_schema.execution_stats.duration_seconds = (
            self.enriched_schema.execution_stats.end_time
            - self.enriched_schema.execution_stats.start_time
        ).total_seconds()

        self.enriched_schema.settings_used = {
            "max_concurrent_requests": Settings.MAX_CONCURRENT_REQUESTS,
            "request_rate_limit": Settings.REQUEST_RATE_LIMIT,
            "api_timeout": Settings.API_TIMEOUT,
            "api_retries": Settings.API_RETRIES,
            "connection_pool_size": Settings.CONNECTION_POOL_SIZE,
            "batch_size": Settings.BATCH_SIZE,
            "fuzz_match_threshold": Settings.FUZZ_MATCH_THRESHOLD,
        }

        run_metadata = {
            "run_id": self.run_id,
            "generated_at": now.isoformat(),
            "script_version": APP_VERSION,
            "git_commit": self._git_commit(),
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "input": {
                "path": str(Settings.COMBINED_METADATA_FILE),
                "sha256": self._file_sha256(Settings.COMBINED_METADATA_FILE),
                "book_count": self.stats.total_books,
            },
            "api": {
                "endpoint": Settings.API_ENDPOINT,
                "rate_limit_per_min": Settings.REQUEST_RATE_LIMIT,
                "max_concurrent": Settings.MAX_CONCURRENT_REQUESTS,
                "timeout_s": Settings.API_TIMEOUT,
                "retries": Settings.API_RETRIES,
            },
            "args": {
                "dry_run": self.dry_run,
                "verbose": Settings.VERBOSE_LOGGING,
            },
            "outputs": {
                "run": str(Settings.ENRICHED_DATA_FILE),
                "books_jsonl": str(Settings.ENRICHED_BOOKS_FILE),
                "vocab": str(Settings.ENRICHED_VOCAB_FILE),
            },
        }

        self.enriched_schema.run_metadata = run_metadata

        output_data = self.enriched_schema.to_dict(include_books=False)

        # Atomic writes to prevent corruption
        import tempfile
        with console.status(
            f"[bold {COLORS['gold']}]💾 Writing enriched data...[/]", spinner="dots12"
        ):
            # Write main enriched data atomically
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=Settings.ENRICHED_DATA_FILE.parent,
                delete=False,
                encoding="utf-8",
                suffix=".tmp",
            ) as tmp:
                json.dump(output_data, tmp, indent=2)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp.name, Settings.ENRICHED_DATA_FILE)

            # Write JSONL books atomically
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=Settings.ENRICHED_BOOKS_FILE.parent,
                delete=False,
                encoding="utf-8",
                suffix=".tmp",
            ) as tmp:
                for book in self.enriched_schema.books:
                    tmp.write(json.dumps(book.to_dict()) + "\n")
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp.name, Settings.ENRICHED_BOOKS_FILE)

            # Write vocab data atomically
            vocab_counters = getattr(self, "_keyword_counters", {}) or {}
            vocab_payload = {
                "run_id": self.run_id,
                "generated_at": now.isoformat(),
                "keyword_counts": self.enriched_schema.keywords_summary,
                "top_keywords": {
                    k: vocab_counters.get(k, Counter()).most_common(100)
                    for k in ["genres", "moods", "content_warnings", "tags"]
                },
                "warnings_distribution": dict(vocab_counters.get("content_warnings", Counter())),
            }
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=Settings.ENRICHED_VOCAB_FILE.parent,
                delete=False,
                encoding="utf-8",
                suffix=".tmp",
            ) as tmp:
                json.dump(vocab_payload, tmp, indent=2)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp.name, Settings.ENRICHED_VOCAB_FILE)

        run_file_size = Settings.ENRICHED_DATA_FILE.stat().st_size / 1024
        books_file_size = Settings.ENRICHED_BOOKS_FILE.stat().st_size / 1024
        vocab_file_size = Settings.ENRICHED_VOCAB_FILE.stat().st_size / 1024

        save_panel = Panel(
            Group(
                Text.from_markup(f"[bold {COLORS['success']}]💾 DATA SAVED SUCCESSFULLY[/]"),
                Text(),
                Text.from_markup(
                    f"📁 Run: [cyan]{Settings.ENRICHED_DATA_FILE}[/] ({run_file_size:.1f} KB)"
                ),
                Text.from_markup(
                    f"📁 JSONL: [cyan]{Settings.ENRICHED_BOOKS_FILE}[/] ({books_file_size:.1f} KB)"
                ),
                Text.from_markup(
                    f"📁 Vocab: [cyan]{Settings.ENRICHED_VOCAB_FILE}[/] ({vocab_file_size:.1f} KB)"
                ),
                Text.from_markup(f"📚 Books: [green]{len(self.enriched_schema.books):,}[/]"),
            ),
            border_style=Style(color=COLORS["success"]),
            box=box.DOUBLE,
        )
        console.print(save_panel)

    def print_summary(self) -> None:
        """Print a stunning visual summary of the enrichment."""
        console.print()
        console.print(Rule("[bold #FFD700]✨ ENRICHMENT COMPLETE ✨[/]", style=COLORS["gold"]))
        console.print()

        # Create spectacular summary layout
        layout = Layout()
        layout.split_row(
            Layout(name="left", ratio=1),
            Layout(name="right", ratio=1),
        )

        # ═══════════════════════════════════════════════════════════════════
        # LEFT SIDE: Execution Statistics
        # ═══════════════════════════════════════════════════════════════════

        stats_table = Table(
            title="[bold #7C3AED]📊 EXECUTION STATISTICS[/]",
            show_header=True,
            header_style=f"bold {COLORS['primary']}",
            box=box.DOUBLE_EDGE,
            border_style=COLORS["primary"],
            title_justify="center",
            expand=True,
        )
        stats_table.add_column("Metric", style=f"bold {COLORS['secondary']}", justify="left")
        stats_table.add_column("Value", style=f"bold {COLORS['success']}", justify="right")
        stats_table.add_column("", width=3)  # For emojis

        stats_table.add_row("Total Books", f"{self.stats.total_books:,}", "📚")
        stats_table.add_row("Books Searched", f"{self.stats.books_searched:,}", "🔍")
        stats_table.add_row("Books Cached", f"{self.stats.books_cached:,}", "📦")
        stats_table.add_row(
            "Books Failed",
            Text(
                f"{self.stats.books_failed:,}",
                style="red" if self.stats.books_failed > 0 else "green",
            ),
            "❌" if self.stats.books_failed > 0 else "✅",
        )
        stats_table.add_row("", "", "")
        stats_table.add_row("API Calls", f"{self.stats.api_calls:,}", "📡")
        stats_table.add_row(
            "API Errors",
            Text(
                f"{self.stats.api_errors:,}",
                style="yellow" if self.stats.api_errors > 0 else "green",
            ),
            "⚠️" if self.stats.api_errors > 0 else "✅",
        )
        stats_table.add_row("Success Rate", f"{self.stats.success_rate:.1f}%", "📈")
        stats_table.add_row("", "", "")
        stats_table.add_row("Duration", f"{self.stats.duration_seconds:.2f}s", "⏱️")
        stats_table.add_row("Avg Request", f"{self.stats.avg_request_time * 1000:.0f}ms", "⚡")

        console.print(stats_table)
        console.print()

        # ═══════════════════════════════════════════════════════════════════
        # RATE LIMITING INFO
        # ═══════════════════════════════════════════════════════════════════

        rate_table = Table(
            title="[bold #EC4899]⚙️ RATE LIMITING CONFIG[/]",
            show_header=True,
            header_style=f"bold {COLORS['accent']}",
            box=box.ROUNDED,
            border_style=COLORS["accent"],
            expand=True,
        )
        rate_table.add_column("Setting", style=f"bold {COLORS['secondary']}")
        rate_table.add_column("Value", style=f"bold {COLORS['gold']}", justify="right")

        rate_table.add_row("Max Concurrent", str(Settings.MAX_CONCURRENT_REQUESTS))
        rate_table.add_row("Rate Limit", f"{Settings.REQUEST_RATE_LIMIT}/min")
        rate_table.add_row("Min Interval", f"{Settings.MIN_REQUEST_INTERVAL:.3f}s")
        rate_table.add_row("API Timeout", f"{Settings.API_TIMEOUT}s")
        rate_table.add_row("Connection Pool", str(Settings.CONNECTION_POOL_SIZE))

        console.print(rate_table)
        console.print()

        # ═══════════════════════════════════════════════════════════════════
        # KEYWORDS SUMMARY
        # ═══════════════════════════════════════════════════════════════════

        if self.enriched_schema.keywords_summary:
            keywords_table = Table(
                title="[bold #06B6D4]🏷️ KEYWORDS HARVESTED[/]",
                show_header=True,
                header_style=f"bold {COLORS['secondary']}",
                box=box.DOUBLE,
                border_style=COLORS["secondary"],
                expand=True,
            )
            keywords_table.add_column("Type", style=f"bold {COLORS['primary']}")
            keywords_table.add_column("Total", style=f"{COLORS['warning']}", justify="right")
            keywords_table.add_column("Unique", style=f"bold {COLORS['success']}", justify="right")
            keywords_table.add_column("", width=3)

            keyword_icons = {
                "genres": "🎭",
                "moods": "💭",
                "content_warnings": "⚠️",
                "tags": "🔖",
            }

            for key_type in ["genres", "moods", "content_warnings", "tags"]:
                total = self.enriched_schema.keywords_summary.get(f"total_{key_type}", 0)
                unique = self.enriched_schema.keywords_summary.get(f"unique_{key_type}", 0)
                icon = keyword_icons.get(key_type, "📌")
                keywords_table.add_row(
                    key_type.replace("_", " ").title(), f"{total:,}", f"{unique:,}", icon
                )

            console.print(keywords_table)
            console.print()

        # ═══════════════════════════════════════════════════════════════════
        # SAMPLE BOOKS TREE
        # ═══════════════════════════════════════════════════════════════════

        if self.enriched_schema.books:
            tree_title = Text()
            tree_title.append("📚 ", style="bold")
            tree_title.append("SAMPLE ENRICHED BOOKS", style=f"bold {COLORS['primary']}")
            tree_title.append(
                f" ({Settings.SAMPLE_BOOKS_TO_SHOW} of {len(self.enriched_schema.books):,})",
                style=f"dim {COLORS['muted']}",
            )

            books_tree = Tree(tree_title)

            for _i, book in enumerate(self.enriched_schema.books[: Settings.SAMPLE_BOOKS_TO_SHOW]):
                emoji = get_random_emoji(BOOK_EMOJIS)
                book_label = Text()
                book_label.append(f"{emoji} ", style="bold")
                book_label.append(book.title, style=f"bold {COLORS['secondary']}")
                book_label.append(" by ", style="dim")
                book_label.append(
                    ", ".join(book.authors) if book.authors else "Unknown",
                    style=f"italic {COLORS['accent']}",
                )

                book_branch = books_tree.add(book_label)

                # Match score with color coding
                score_color = (
                    COLORS["success"]
                    if book.search_match_score > 0.85
                    else (COLORS["warning"] if book.search_match_score > 0.70 else COLORS["error"])
                )
                book_branch.add(
                    Text.from_markup(
                        f"[{score_color}]📊 Match Score: {book.search_match_score:.0%}[/]"
                    )
                )

                # Rating
                if book.hardcover_rating:
                    stars = "⭐" * min(5, int(book.hardcover_rating))
                    book_branch.add(
                        Text.from_markup(
                            f"[{COLORS['gold']}]{stars} Rating: {book.hardcover_rating:.2f}[/]"
                            f"[dim] ({book.hardcover_rating_count or 0:,} votes)[/]"
                        )
                    )
                else:
                    book_branch.add(Text("📊 Rating: N/A", style="dim"))

                # Keywords summary
                kw = book.keywords
                keywords_text = Text()
                keywords_text.append("🏷️ Keywords: ", style="bold")
                keywords_text.append(f"🎭{len(kw.genres)} ", style=COLORS["primary"])
                keywords_text.append(f"💭{len(kw.moods)} ", style=COLORS["accent"])
                keywords_text.append(f"⚠️{len(kw.content_warnings)} ", style=COLORS["warning"])
                keywords_text.append(f"🔖{len(kw.tags)}", style=COLORS["secondary"])
                book_branch.add(keywords_text)

                # Cache status
                cache_text = Text()
                if book.cached:
                    cache_text.append("📦 ", style="bold")
                    cache_text.append("Cached", style=f"bold {COLORS['secondary']}")
                else:
                    cache_text.append("🔍 ", style="bold")
                    cache_text.append("Fresh Search", style=f"bold {COLORS['success']}")
                book_branch.add(cache_text)

            tree_panel = Panel(
                books_tree,
                border_style=Style(color=COLORS["primary"]),
                box=box.ROUNDED,
            )
            console.print(tree_panel)
            console.print()

        # ═══════════════════════════════════════════════════════════════════
        # FINAL CELEBRATION
        # ═══════════════════════════════════════════════════════════════════

        celebration = Panel(
            Align.center(
                Group(
                    Text("🎉 " * 10, justify="center"),
                    Text(),
                    create_gradient_text("ENRICHMENT COMPLETE!"),
                    Text(),
                    Text.from_markup(
                        f"[bold {COLORS['success']}]Successfully processed "
                        f"[{COLORS['gold']}]{len(self.enriched_schema.books):,}[/] books![/]"
                    ),
                    Text(),
                    Text("🎉 " * 10, justify="center"),
                )
            ),
            border_style=Style(color=COLORS["gold"]),
            box=box.DOUBLE,
            padding=(1, 2),
        )
        console.print(celebration)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                          🚀 MAIN EXECUTION                                   ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


def print_startup_banner(dry_run: bool) -> None:
    """Print the stunning startup banner."""
    console.print(BANNER_ART)
    console.print()

    # Version and mode info
    info_table = Table(show_header=False, box=None, padding=(0, 2))
    info_table.add_column("", style=f"bold {COLORS['primary']}")
    info_table.add_column("", style=f"bold {COLORS['secondary']}")

    info_table.add_row("📆 Timestamp", datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"))
    info_table.add_row("🔧 Version", "2.0.0")
    info_table.add_row(
        "🎮 Mode",
        Text("DRY-RUN (No API calls)", style=f"bold {COLORS['warning']}")
        if dry_run
        else Text("PRODUCTION", style=f"bold {COLORS['success']}"),
    )
    info_table.add_row("🔗 API", Settings.API_ENDPOINT)

    info_panel = Panel(
        info_table,
        border_style=Style(color=COLORS["secondary"]),
        box=box.ROUNDED,
        title="[bold #06B6D4]ℹ️ SESSION INFO[/]",
    )
    console.print(info_panel)
    console.print()


def print_api_key_error() -> None:
    """Print a beautiful API key error message."""
    error_content = Group(
        Text("❌ AUTHENTICATION ERROR", style=f"bold {COLORS['error']}", justify="center"),
        Text(),
        Text("HARDCOVER_API_KEY not set in environment!", style="bold"),
        Text(),
        Text("To fix this:", style=f"dim {COLORS['muted']}"),
        Text("  1. Get your API key from hardcover.app", style=f"{COLORS['secondary']}"),
        Text("  2. Add to your .env file:", style=f"{COLORS['secondary']}"),
        Text("     HARDCOVER_API_KEY=your_key_here", style=f"bold {COLORS['gold']}"),
        Text(),
        Text("Or run with --dry-run to test without API", style=f"dim {COLORS['muted']}"),
    )

    error_panel = Panel(
        Align.center(error_content),
        border_style=Style(color=COLORS["error"]),
        box=box.HEAVY,
        padding=(1, 4),
    )
    console.print(error_panel)


async def run_enrichment(dry_run: bool = False) -> int:
    """Run the enrichment process with full visual experience."""
    # Print stunning startup banner
    print_startup_banner(dry_run)

    # Check API key
    if not Settings.API_KEY and not dry_run:
        print_api_key_error()
        return 1

    try:
        # Initialize enricher with visual confirmation
        with console.status(
            f"[bold {COLORS['primary']}]🔮 Initializing enrichment engine...[/]",
            spinner="aesthetic",
        ):
            enricher = HardcoverEnricher(dry_run=dry_run)

        console.print(Text("✅ Engine initialized", style=f"bold {COLORS['success']}"))
        console.print()

        # Load metadata
        books = enricher.load_combined_metadata()

        # Load search cache
        enricher.load_search_cache()

        # Run enrichment with live dashboard
        await enricher.enrich_all_books(books)

        # Build summary
        with console.status(
            f"[bold {COLORS['secondary']}]📊 Building keywords summary...[/]", spinner="dots"
        ):
            enricher.build_keywords_summary()

        console.print()

        # Save data
        enricher.save_enriched_data()
        enricher.save_search_cache()

        # Print spectacular summary
        enricher.print_summary()

        # Close HTTP client
        await enricher.close_http_client()

        return 0

    except KeyboardInterrupt:
        console.print()
        console.print(
            Panel(
                Text("⚠️ Operation cancelled by user", style=f"bold {COLORS['warning']}"),
                border_style=COLORS["warning"],
                box=box.HEAVY,
            )
        )
        return 130

    except Exception as e:
        console.print()
        error_panel = Panel(
            Group(
                Text("❌ FATAL ERROR", style=f"bold {COLORS['error']}", justify="center"),
                Text(),
                Text(str(e), style="bold"),
            ),
            border_style=Style(color=COLORS["error"]),
            box=box.HEAVY,
        )
        console.print(error_panel)
        logger.exception("Unhandled exception")
        return 1


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                           🎮 CLI INTERFACE                                   ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

app = typer.Typer(
    name="hardcover-enrichment",
    help="📚 Enrich book metadata with Hardcover API keywords - with stunning visuals!",
    add_completion=False,
    rich_markup_mode="rich",
)


@app.command()
def main(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="🧪 Don't call API, just test locally",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="🔊 Enable verbose logging",
    ),
) -> int:
    """
    🚀 [bold #7C3AED]Hardcover Book Enrichment Tool[/]

    Enriches book metadata from combined_metadata.json with rich keyword data
    from the Hardcover API, including genres, moods, content warnings, and tags.

    [bold #06B6D4]Features:[/]
    • ⚡ Async API calls with smart rate limiting
    • 📦 Persistent search cache to avoid redundant requests
    • 🎨 Stunning live dashboard with real-time statistics
    • 📊 Comprehensive JSON output with detailed metadata

    [bold #EC4899]Examples:[/]
        $ python hardcover_enrichment.py
        $ python hardcover_enrichment.py --dry-run
        $ python hardcover_enrichment.py --verbose
    """
    Settings.VERBOSE_LOGGING = verbose
    return asyncio.run(run_enrichment(dry_run=dry_run))


if __name__ == "__main__":
    sys.exit(app())
