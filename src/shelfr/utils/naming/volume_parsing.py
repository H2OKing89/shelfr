"""
Volume notation parsing and formatting.

Handles parsing and formatting of volume numbers in various formats:
- Simple: vol_01, vol_12
- Decimal (novellas): vol_01.5
- Ranges (Publisher Packs): vol_01-03
- Parts (Graphic Audio): vol_01p1
"""

from __future__ import annotations

import logging
import re

from shelfr.utils.naming.authors import VolumeInfo
from shelfr.utils.naming.constants import (
    VOL_EXTRACT_PATTERNS,
    VOL_NOTATION_PATTERN,
    VOLUME_ALIASES,
)

logger = logging.getLogger(__name__)


def parse_volume_notation(vol_str: str) -> VolumeInfo | None:
    """Parse an existing vol_XX notation into components.

    Parses volume notations like:
    - vol_01     → VolumeInfo(base=1.0)
    - vol_01.5   → VolumeInfo(base=1.5)
    - vol_01-03  → VolumeInfo(base=1.0, range_end=3.0)
    - vol_01p1   → VolumeInfo(base=1.0, part=1)

    Args:
        vol_str: Volume string to parse (e.g., "vol_01", "vol_01p1")

    Returns:
        VolumeInfo dict with parsed components, or None if not a valid notation
    """
    match = VOL_NOTATION_PATTERN.search(vol_str)
    if not match:
        return None

    base_str = match.group("base")
    range_end_str = match.group("range_end")
    part_str = match.group("part")

    result: VolumeInfo = {"base": float(base_str)}

    if range_end_str:
        result["range_end"] = float(range_end_str)

    if part_str:
        result["part"] = int(part_str)

    return result


def normalize_position(position: str) -> str:
    """Normalize series position to vol_XX format.

    Handles multiple input formats:
    - Simple numbers: "1" → "vol_01"
    - Decimals (novellas): "1.5" → "vol_01.5"
    - Ranges (Publisher Packs): "1-3" → "vol_01-03"
    - Parts (Graphic Audio): "1p1", "1 Part 1" → "vol_01p1"
    - Named positions: "Prequel" → "vol_00"
    - Omnibus: "Omnibus" → "" (empty, no volume)

    Args:
        position: Series position string to normalize

    Returns:
        Formatted volume string like "vol_01", "vol_01p1", or empty string
    """
    if not position:
        return ""

    position = position.strip()

    # Handle aliases (prequel, prologue, etc.)
    lower_pos = position.lower()
    if lower_pos in VOLUME_ALIASES:
        mapped = VOLUME_ALIASES[lower_pos]
        if mapped is None:
            return ""  # Omnibus - no volume number
        position = mapped

    # Check for part notation: "1p1", "1 part 1", "1_01", "Vol 1 Part 1"
    part_match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:p|[,:\s]+part\s*|_)(\d+)",
        position,
        re.IGNORECASE,
    )
    if part_match:
        main = float(part_match.group(1))
        part = int(part_match.group(2))
        return f"vol_{int(main):02d}p{part}"

    # Check for range notation: "1-3", "01-03", "Books 1-3"
    range_match = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", position)
    if range_match:
        start = float(range_match.group(1))
        end = float(range_match.group(2))
        # Only treat as range if end > start (not a part)
        if end > start:
            # Format with proper zero-padding
            if start == int(start) and end == int(end):
                return f"vol_{int(start):02d}-{int(end):02d}"
            # Handle decimal ranges (rare but possible)
            return f"vol_{start:05.2f}-{end:05.2f}".replace(".00", "")

    # Standard number extraction (handles "3", "12", "1.5")
    num_match = re.search(r"(\d+(?:\.\d+)?)", position)
    if not num_match:
        return ""

    number_str = num_match.group(1)

    # Handle decimal volumes (novellas): "1.5" → "vol_01.5"
    if "." in number_str:
        integer_part, decimal_part = number_str.split(".", 1)
        return f"vol_{int(integer_part):02d}.{decimal_part}"

    # Integer volumes: "3" → "vol_03"
    return f"vol_{int(number_str):02d}"


def extract_volume_number(title: str, series_position: str | None = None) -> str | None:
    """
    Extract volume/book number from title or series_position.

    Enhanced to handle parts, ranges, and decimals:
    - Simple: "Vol. 3" → "3"
    - Decimal: "Vol. 3.5" → "3.5"
    - Part: "Vol. 3 Part 1" → "3p1"
    - Range: "Books 1-3" → "1-3"

    Priority:
    1. series_position if provided and valid
    2. Vol/Volume/Book number from title (with part/range support)
    3. Trailing number from title

    Args:
        title: Title string that may contain volume info
        series_position: Explicit series position if available

    Returns:
        Volume number as string (e.g., "3", "12", "3.5", "3p1", "1-3"), or None if not found
    """
    # Priority 1: Use explicit series_position if it's valid
    if series_position:
        clean_pos = series_position.strip()
        if clean_pos:
            # Handle decimals, parts, and ranges
            # Patterns: "1", "1.5", "1p1", "1-3"
            if re.match(r"^\d+(?:\.\d+)?(?:p\d+|-\d+)?$", clean_pos, re.IGNORECASE):
                return clean_pos
            # Handle "Part 1" in position
            part_match = re.match(r"^(\d+)\s*(?:part|p)\s*(\d+)$", clean_pos, re.IGNORECASE)
            if part_match:
                return f"{part_match.group(1)}p{part_match.group(2)}"

    # Priority 2: Extract from title using patterns
    for pattern in VOL_EXTRACT_PATTERNS:
        match = pattern.search(title)
        if match:
            groups = match.groups()
            # Check if we have a range pattern (two capture groups, both numeric)
            if len(groups) >= 2 and groups[1] and groups[0].isdigit() and groups[1].isdigit():
                num1, num2 = int(groups[0]), int(groups[1])
                # Distinguish range from part: if second > first, it's a range
                if num2 > num1:
                    return f"{num1}-{num2}"  # Range: "1-3"
                return f"{num1}p{num2}"  # Part: "3p1" (Vol 3 Part 1)
            # Single capture group (ensure groups is not empty)
            if groups and groups[0]:
                return groups[0]

    return None


def format_volume_number(
    vol_num: str | VolumeInfo | None,
    zero_pad: bool = True,
) -> str:
    """
    Format volume number for folder/file naming.

    Supports multiple input formats:
    - String: "3", "12", "1.5", "1p1", "1-3"
    - VolumeInfo dict: {"base": 1.0, "part": 1} or {"base": 1.0, "range_end": 3.0}

    Output formats:
    - Simple: "vol_03", "vol_12"
    - Decimal (novella): "vol_01.5"
    - Part (Graphic Audio): "vol_01p1"
    - Range (Publisher Pack): "vol_01-03"

    Args:
        vol_num: Volume number string or VolumeInfo dict
        zero_pad: Whether to zero-pad to 2 digits

    Returns:
        Formatted string like "vol_03", "vol_01p1", "vol_01-03", or empty string
    """
    if not vol_num:
        return ""

    # Handle VolumeInfo dict
    if isinstance(vol_num, dict):
        base = vol_num.get("base")
        if base is None:
            return ""

        range_end = vol_num.get("range_end")
        part = vol_num.get("part")

        # Format base number
        if base == int(base):
            base_str = f"{int(base):02d}" if zero_pad else str(int(base))
        else:
            int_part = int(base)
            dec_part = str(base).split(".")[1]
            base_str = f"{int_part:02d}.{dec_part}" if zero_pad else f"{int_part}.{dec_part}"

        # Part notation: vol_01p1
        if part is not None:
            return f"vol_{base_str}p{part}"

        # Range notation: vol_01-03
        if range_end is not None:
            if range_end == int(range_end):
                end_str = f"{int(range_end):02d}" if zero_pad else str(int(range_end))
            else:
                int_part = int(range_end)
                dec_part = str(range_end).split(".")[1]
                end_str = f"{int_part:02d}.{dec_part}" if zero_pad else f"{int_part}.{dec_part}"
            return f"vol_{base_str}-{end_str}"

        # Simple volume: vol_01
        return f"vol_{base_str}"

    # Handle string input
    vol_str = str(vol_num).strip()
    if not vol_str:
        return ""

    # Check if it's already formatted (vol_XX)
    if vol_str.lower().startswith("vol_"):
        # Normalize to lowercase and validate format
        normalized = vol_str.lower()
        if not VOL_NOTATION_PATTERN.fullmatch(normalized):
            raise ValueError(
                f"Invalid volume notation format: {vol_str!r}. "
                f"Expected format: vol_NN, vol_NN.N, vol_NN-MM, or vol_NNpP"
            )
        return normalized

    # Check for part notation: "1p1" or "3p2"
    part_match = re.match(r"^(\d+)p(\d+)$", vol_str, re.IGNORECASE)
    if part_match:
        main = int(part_match.group(1))
        part = int(part_match.group(2))
        if zero_pad:
            return f"vol_{main:02d}p{part}"
        return f"vol_{main}p{part}"

    # Check for range notation: "1-3"
    range_match = re.match(r"^(\d+)-(\d+)$", vol_str)
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        if zero_pad:
            return f"vol_{start:02d}-{end:02d}"
        return f"vol_{start}-{end}"

    # Handle decimal volumes (e.g., "1.5" -> "vol_01.5")
    if "." in vol_str:
        parts = vol_str.split(".")
        if parts[0].isdigit():
            if zero_pad:
                parts[0] = parts[0].zfill(2)
            return f"vol_{'.'.join(parts)}"

    # Integer volumes
    if vol_str.isdigit():
        if zero_pad:
            return f"vol_{vol_str.zfill(2)}"
        return f"vol_{vol_str}"

    return ""
