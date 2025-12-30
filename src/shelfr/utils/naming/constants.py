"""
Constants used across naming modules.

Contains patterns, maps, and configuration values used for:
- Filename sanitization
- MAM path length limits
- Volume notation parsing
- Pattern matching
"""

from __future__ import annotations

import re

# =============================================================================
# MAM Path Limits
# =============================================================================

# MAM filename limit (full path)
MAM_MAX_FILENAME_LENGTH = 225

# Default MAM path length limit
MAM_MAX_PATH_LENGTH = 225

# Minimum series length before we give up and just truncate
MIN_SERIES_LENGTH = 3

# =============================================================================
# Volume Aliases
# =============================================================================

# Volume aliases: map named positions to numbers
VOLUME_ALIASES: dict[str, str | None] = {
    "prequel": "0",
    "prologue": "0",
    "prelude": "0",
    "origin": "0",
    "origins": "0",
    "introduction": "0",
    "omnibus": None,  # No volume number for omnibus without range
}

# =============================================================================
# Filename Sanitization
# =============================================================================

# Characters to normalize (replace with space or dash)
# Applied FIRST before removing illegal characters
NORMALIZE_MAP = {
    "/": "-",
    "\\": "-",
    ":": " -",
    "|": "-",
    '"': "'",
    "<": "",
    ">": "",
    "?": "",
    "*": "",
}

# Characters not allowed in filenames (cross-platform safe)
# Applied AFTER normalization to remove truly illegal characters
# Note: ":" is NOT included here as it's normalized to " -" by NORMALIZE_MAP
ILLEGAL_CHARS_PATTERN = re.compile(r'[<>"/\\|?*]')

# =============================================================================
# Pre-compiled Patterns
# =============================================================================

# Base patterns: always removed from titles
COMPILED_REMOVE_PATTERNS: list[re.Pattern[str]] = [
    # "Book 12", "Book XII", "Book: 12" etc - we keep vol_XX instead
    re.compile(r"\bBook\s*[:\s]*\d+\b", re.IGNORECASE),
    re.compile(r"\bBook\s*[:\s]*[IVXLCDM]+\b", re.IGNORECASE),
    # Extra whitespace patterns
    re.compile(r"\s*-\s*-\s*"),  # Double dashes
    re.compile(r"\s*,\s*,\s*"),  # Double commas
]

# Volume patterns: removed for folder/file names, kept for MAM JSON
COMPILED_VOLUME_PATTERNS: list[re.Pattern[str]] = [
    # "Vol. 12" or "Volume 12" (but NOT vol_12 which is Libation format)
    re.compile(r"\bVol\.\s*\d+\b", re.IGNORECASE),
    re.compile(r"\bVolume\s*\d+\b", re.IGNORECASE),
]

# Pre-compiled cleanup patterns
WHITESPACE_PATTERN = re.compile(r"\s+")
DOUBLE_DASH_PATTERN = re.compile(r"\s*-\s*-\s*")
LEADING_DASH_PATTERN = re.compile(r"^\s*-\s*")
TRAILING_DASH_PATTERN = re.compile(r"\s*-\s*$")
EMPTY_PARENS_PATTERN = re.compile(r"\(\s*\)")
EMPTY_BRACKETS_PATTERN = re.compile(r"\[\s*\]")
DUPLICATE_VOL_PATTERN = re.compile(r"\b(\d+)\s+vol_\1\b")
NON_ASCII_PATTERN = re.compile(r"[^\x00-\x7F]+")

# Dangling punctuation patterns
TRAILING_PUNCT_PATTERN = re.compile(r"\s*[,:;]\s*$")  # Trailing comma, colon, semicolon
LEADING_PUNCT_PATTERN = re.compile(r"^\s*[,:;]\s*")  # Leading comma, colon, semicolon
SPACE_BEFORE_PUNCT_PATTERN = re.compile(r"\s+([,:;])")  # Space before punctuation

# Volume/Book number extraction patterns for folder naming
# Enhanced to support parts (vol_01p1), ranges (vol_01-03), and novellas (vol_01.5)
VOL_EXTRACT_PATTERNS: list[re.Pattern[str]] = [
    # Part notation: "Vol. 3 Part 1", "Volume 3, Part 2"
    re.compile(r",?\s*Vol(?:ume)?\.?\s*(\d+)(?:\s*[,:]?\s*Part\s*(\d+))?", re.IGNORECASE),
    # Range notation: "Books 1-3", "Volumes 1-3"
    re.compile(r",?\s*(?:Books?|Vol(?:ume)?s?)\.?\s*(\d+)\s*-\s*(\d+)", re.IGNORECASE),
    # Simple volume with optional decimal: "Vol. 3.5", "Volume 3"
    re.compile(r",?\s*Vol(?:ume)?\.?\s*(\d+(?:\.\d+)?)", re.IGNORECASE),
    # Book number: "Book 3"
    re.compile(r",?\s*Book\s+(\d+(?:\.\d+)?)", re.IGNORECASE),
    # Trailing number "Title 3"
    re.compile(r"\s+(\d+(?:\.\d+)?)$"),
]

# Volume notation regex for parsing existing vol_XX patterns
# Supports: vol_01, vol_01.5, vol_01-03, vol_01p1
VOL_NOTATION_PATTERN = re.compile(
    r"vol_(?P<base>\d+(?:\.\d+)?)" r"(?:-(?P<range_end>\d+(?:\.\d+)?)|p(?P<part>\d+))?",
    re.IGNORECASE,
)

# Pattern to extract vol_XX from folder/file name
VOL_FROM_NAME_PATTERN = re.compile(r"vol_(\d+(?:\.\d+)?)", re.IGNORECASE)

# =============================================================================
# Author Role Patterns
# =============================================================================

# Default author role words (fallback if config not available)
DEFAULT_ROLE_WORDS = ["translator", "illustrator", "editor", "adapter", "contributor", "compiler"]
DEFAULT_CREDIT_WORDS = ["afterword", "foreword", "introduction", "cover design", "cover art"]

# =============================================================================
# Series Patterns
# =============================================================================

# Pre-compiled patterns for extracting series from title
# Order matters: more specific patterns first
#
# Patterns allow optional trailing content after the volume number:
# - Parenthetical content: "(Light Novel)", "(Unabridged)"
# - Subtitles after colon/dash: ": A Subtitle", "– The Continuation"
#
# Examples that will match:
# - "I'm the Evil Lord of an Intergalactic Empire!, Vol. 5 (Light Novel)"
# - "Black Summoner, Volume 4: The Legend Continues"
# - "Some Series, Vol. 3 – A Subtitle"
# - "Series Name Volume 5 (Unabridged)"
SERIES_FROM_TITLE_PATTERNS: list[re.Pattern[str]] = [
    # "Series Name, Vol. 5" or "Series Name, Volume 5" (with optional trailing content)
    re.compile(
        r"^(?P<series>.+?),\s*(?:Vol\.?|Volume)\s*(?P<num>\d+(?:\.\d+)?)"
        r"(?:\s*\([^)]*\))?(?:\s*[:\-–—].+)?$",
        re.IGNORECASE,
    ),
    # "Series Name: Volume 5" or "Series Name: Vol. 5" (with optional trailing content)
    re.compile(
        r"^(?P<series>.+?):\s*(?:Vol\.?|Volume)\s*(?P<num>\d+(?:\.\d+)?)"
        r"(?:\s*\([^)]*\))?(?:\s*[:\-–—].+)?$",
        re.IGNORECASE,
    ),
    # "Series Name, Book 5" (with optional trailing content)
    re.compile(
        r"^(?P<series>.+?),\s*Book\s*(?P<num>\d+(?:\.\d+)?)" r"(?:\s*\([^)]*\))?(?:\s*[:\-–—].+)?$",
        re.IGNORECASE,
    ),
    # "Series Name: Book 5" (with optional trailing content)
    re.compile(
        r"^(?P<series>.+?):\s*Book\s*(?P<num>\d+(?:\.\d+)?)" r"(?:\s*\([^)]*\))?(?:\s*[:\-–—].+)?$",
        re.IGNORECASE,
    ),
    # "Series Name Vol. 5" (no comma/colon, with optional trailing content)
    re.compile(
        r"^(?P<series>.+?)\s+(?:Vol\.?|Volume)\s*(?P<num>\d+(?:\.\d+)?)"
        r"(?:\s*\([^)]*\))?(?:\s*[:\-–—].+)?$",
        re.IGNORECASE,
    ),
    # "Series Name Book 5" (no comma/colon, with optional trailing content)
    re.compile(
        r"^(?P<series>.+?)\s+Book\s*(?P<num>\d+(?:\.\d+)?)" r"(?:\s*\([^)]*\))?(?:\s*[:\-–—].+)?$",
        re.IGNORECASE,
    ),
    # "Series Name 5" (just trailing number) - low confidence
    # Requires series to have at least 2 words to avoid matching "Fahrenheit 451", "1984", etc.
    re.compile(
        r"^(?P<series>(?:\S+\s+)+\S+)\s+(?P<num>\d+)$",
    ),
]
