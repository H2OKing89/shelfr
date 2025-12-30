"""
MAM path building with truncation.

Provides functions to build MAM-compliant folder and file names:
- build_mam_folder_name: Build folder name with truncation
- build_mam_file_name: Build filename with extension
- build_mam_path: Build complete path (folder + filename)

The 225-char limit applies to the FULL RELATIVE PATH (folder/filename),
not individual components. The base name appears TWICE in the path,
so every character saved from the base saves ~2 characters total.
"""

from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shelfr.config import NamingConfig
    from shelfr.models import MamPath

from shelfr.utils.naming.constants import (
    MAM_MAX_FILENAME_LENGTH,
    MAM_MAX_PATH_LENGTH,
    MIN_SERIES_LENGTH,
)
from shelfr.utils.naming.filters import (
    filter_series,
    filter_title,
    inherit_the_prefix,
    sanitize_filename,
)
from shelfr.utils.naming.volume_parsing import format_volume_number

logger = logging.getLogger(__name__)


# =============================================================================
# Path Truncation Budget Formula
# =============================================================================
# The 225-char limit applies to the FULL RELATIVE PATH (folder/filename),
# not individual components. The base name appears TWICE in the path,
# so every character saved from the base saves ~2 characters total.
#
# Path structure: "{base} [{tag}]/{base}{ext}"
#
# Budget formula (with tag):
#   Total = len(base) + 3 + len(tag) + 1 + len(base) + len(ext)
#         = 2*len(base) + len(tag) + len(ext) + 4
#
#   To fit in 225: max_base = (225 - len(tag) - len(ext) - 4) // 2
#
# Budget formula (no tag):
#   Total = len(base) + 1 + len(base) + len(ext)
#         = 2*len(base) + len(ext) + 1
#
#   To fit in 225: max_base = (225 - len(ext) - 1) // 2
#
# Examples with ".m4b" (4 chars):
#   With "H2OKing" (7 chars): max_base = (225 - 7 - 4 - 4) // 2 = 105 chars
#   With no tag:              max_base = (225 - 4 - 1) // 2     = 110 chars
#
# Multi-file adjustment for " - Part XX.m4b" (14 chars worst case):
#   With "H2OKing": max_base = (225 - 7 - 14 - 4) // 2 = 100 chars
#   With no tag:    max_base = (225 - 14 - 1) // 2     = 105 chars
# =============================================================================


@functools.lru_cache(maxsize=1)
def _get_mam_path_class() -> type[MamPath]:
    """Lazy import of MamPath to avoid circular imports."""
    from shelfr.models import MamPath as MamPathClass

    return MamPathClass


def _calculate_max_base_length(
    *,
    ripper_tag: str | None,
    extension: str,
    part_count: int,
    max_path_length: int,
) -> int:
    """
    Calculate the maximum base name length given the path constraints.

    The base name appears TWICE in the path (folder + filename), so:
        path_length = 2*base + overhead

    Args:
        ripper_tag: Optional ripper tag (e.g., "H2OKing")
        extension: File extension including dot (e.g., ".m4b")
        part_count: Number of parts (>1 means multi-file)
        max_path_length: Maximum total path length (default: 225)

    Returns:
        Maximum allowed base name length
    """
    # Determine extension length (worst case for multi-file)
    # Using if/else to preserve the explanatory comment
    if part_count > 1:  # noqa: SIM108
        # " - Part XX.m4b" = 14 chars worst case
        ext_len = 14
    else:
        ext_len = len(extension)

    # Calculate overhead based on whether we have a tag
    # Using if/else to preserve the detailed math comments
    if ripper_tag:  # noqa: SIM108
        # With tag: folder = "{base} [{tag}]", filename = "{base}{ext}"
        # Total = len(base) + 1 + 1 + len(tag) + 1 + 1 + len(base) + ext_len
        #       = 2*len(base) + len(tag) + ext_len + 4
        tag_overhead = len(ripper_tag) + 4  # " [" + tag + "]" + "/"
    else:
        # No tag: folder = "{base}", filename = "{base}{ext}"
        # Total = len(base) + 1 + len(base) + ext_len
        #       = 2*len(base) + ext_len + 1
        tag_overhead = 1  # Just the "/" separator

    overhead = tag_overhead + ext_len
    max_base = (max_path_length - overhead) // 2

    return max_base


def _build_truncated_base_name(
    *,
    series: str | None,
    title: str,
    vol_str: str | None,
    arc: str | None,
    year: str | None,
    author: str | None,
    asin_str: str,
    max_length: int,
    naming_config: NamingConfig | None = None,
) -> tuple[str, bool, list[str]]:
    """
    Build a base name that fits within max_length, dropping components as needed.

    Drop priority is configurable via naming_config.path_drop_priority.
    Default order: ["arc", "author", "year"]

    {Series}, vol_{NN}, and {ASIN} are NEVER dropped (identity components).

    Args:
        series: Series name (cleaned)
        title: Book title (used for standalone books)
        vol_str: Formatted volume string (e.g., "vol_01") or None
        arc: Arc/subtitle name (optional)
        year: Release year (4 digits)
        author: Author name (cleaned)
        asin_str: Formatted ASIN string (e.g., "{ASIN.B0123}") or empty string
        max_length: Maximum allowed base name length
        naming_config: NamingConfig with path_drop_priority

    Returns:
        Tuple of (base_name, truncated, dropped_components)
    """
    dropped: list[str] = []

    # Get drop priority from config or use default
    drop_order = (
        naming_config.path_drop_priority
        if naming_config and naming_config.path_drop_priority
        else ["arc", "author", "year"]
    )

    # Determine if this is a series or standalone book
    is_series = bool(series and vol_str)

    # Track which optional components we have
    use_arc = bool(arc)
    use_year = bool(year)
    use_author = bool(author)

    def build_base(
        include_arc: bool = True,
        include_author: bool = True,
        include_year: bool = True,
        series_override: str | None = None,
    ) -> str:
        """Assemble base name from current components."""
        if is_series:
            current_series = series_override if series_override is not None else series
            parts = [f"{current_series} {vol_str}"]
        else:
            parts = [series_override if series_override is not None else title]

        if include_arc and arc:
            parts.append(arc)
        if include_year and year:
            parts.append(f"({year})")
        if include_author and author:
            parts.append(f"({author})")

        if asin_str:
            parts.append(asin_str)
        return " ".join(parts)

    # Try with all components
    base = build_base(include_arc=use_arc, include_author=use_author, include_year=use_year)
    if len(base) <= max_length:
        return base, False, dropped

    # Drop components in configured priority order
    for drop_label in drop_order:
        if drop_label == "arc" and use_arc:
            use_arc = False
            dropped.append("arc")
        elif drop_label == "author" and use_author:
            use_author = False
            dropped.append("author")
        elif drop_label == "year" and use_year:
            use_year = False
            dropped.append("year")
        else:
            continue

        base = build_base(include_arc=use_arc, include_author=use_author, include_year=use_year)
        if len(base) <= max_length:
            return base, True, dropped

    # Last resort: truncate series/title with "..."
    # Base without optionals: "{series} {vol_str} {asin_str}" or "{title} {asin_str}"
    if is_series:
        suffix_parts: list[str] = []
        if vol_str:
            suffix_parts.append(vol_str)
        if asin_str:
            suffix_parts.append(asin_str)
        suffix = " " + " ".join(suffix_parts) if suffix_parts else ""
        identity_to_truncate = series  # We know series is not None when is_series is True
    else:
        suffix = f" {asin_str}" if asin_str else ""
        identity_to_truncate = title

    # At this point identity_to_truncate is guaranteed to be a string
    assert identity_to_truncate is not None

    available_for_identity = max_length - len(suffix) - 3  # 3 for "..."

    if available_for_identity >= MIN_SERIES_LENGTH:
        dropped.append("series_truncated")
        truncated_identity = identity_to_truncate[:available_for_identity] + "..."
        if is_series:
            # vol_str is guaranteed to be not None when is_series is True
            assert vol_str is not None
            parts: list[str] = [truncated_identity, vol_str]
            if asin_str:
                parts.append(asin_str)
            base = " ".join(parts)
        else:
            base = f"{truncated_identity} {asin_str}" if asin_str else truncated_identity

        logger.warning(
            "Series/title truncation triggered for %s: '%s' -> '%s...' (%d chars available)",
            asin_str or "no-asin",
            identity_to_truncate,
            identity_to_truncate[:available_for_identity],
            available_for_identity,
        )
        return base, True, dropped

    # Absolute minimum fallback (should never happen with real data)
    logger.error(
        "Cannot fit base name in %d chars for %s - returning truncated identity",
        max_length,
        asin_str or "no-asin",
    )
    dropped.append("emergency_truncation")
    if asin_str:
        # Ensure non-negative slice: need space for "... " (4 chars) + asin_str
        available = max(0, max_length - len(asin_str) - 4)
        if available > 0:
            base = f"{identity_to_truncate[:available]}... {asin_str}"[:max_length]
        elif max_length >= len(asin_str):
            # No room for identity, just return ASIN truncated to max_length
            base = asin_str[:max_length]
        else:
            # max_length is smaller than ASIN itself - return last max_length chars of ASIN
            base = asin_str[-max_length:] if max_length > 0 else ""
        return (base, True, dropped)
    else:
        available = max(0, max_length - 3)
        if available > 0:
            base = f"{identity_to_truncate[:available]}..."[:max_length]
        else:
            # No room for "...", just hard truncate
            base = identity_to_truncate[:max_length] if max_length > 0 else ""
        return (base, True, dropped)


def build_mam_path(
    *,
    series: str | None = None,
    title: str,
    volume_number: str | None = None,
    arc: str | None = None,
    year: str | None = None,
    author: str | None = None,
    asin: str | None = None,
    ripper_tag: str | None = None,
    extension: str = ".m4b",
    part_count: int = 1,
    naming_config: NamingConfig | None = None,
    max_path_length: int = MAM_MAX_PATH_LENGTH,
    folder_max_length: int | None = None,
) -> MamPath:
    """
    Build folder and filename ensuring combined path ≤ max_path_length.

    This is the CORRECT way to generate MAM paths. The 225-char limit applies
    to the full relative path (folder/filename), not individual components.

    Path structure: "{base} [{tag}]/{base}{ext}"

    The base name appears TWICE, so every character saved from base saves ~2
    characters from the total path length.

    Args:
        series: Series name (cleaned). If None, treated as standalone.
        title: Book title (used for standalone books or fallback)
        volume_number: Volume/book number (e.g., "3", "12")
        arc: Arc/subtitle name (optional, e.g., "Aincrad")
        year: Release year (4 digits)
        author: Primary author name (cleaned)
        asin: Amazon ASIN (optional - if None, ASIN component is omitted from path)
        ripper_tag: Optional ripper tag (e.g., "H2OKing")
        extension: File extension (default: ".m4b")
        part_count: Number of parts (>1 adjusts budget for " - Part XX")
        naming_config: NamingConfig for cleaning rules
        max_path_length: Maximum path length (default: 225 for MAM)
        folder_max_length: Optional constraint on folder length only (for legacy callers)

    Returns:
        MamPath with folder, filename, and truncation metadata
    """
    mam_path_cls = _get_mam_path_class()

    # Ensure extension starts with dot
    if extension and not extension.startswith("."):
        extension = f".{extension}"

    # Clean inputs - use filter_series() for series to apply series-specific patterns
    # (e.g., remove " Series", " Trilogy", "[publication order]" suffixes)
    clean_series = filter_series(series, naming_config=naming_config) if series else None
    clean_title = (
        filter_title(title, naming_config=naming_config, keep_volume=False) if title else ""
    )

    # Inherit "The" prefix from title to series if series lacks it
    # (e.g., title="The Great Cleric", series="Great Cleric" -> series="The Great Cleric")
    clean_series = inherit_the_prefix(clean_series, clean_title)

    clean_arc = filter_title(arc, naming_config=naming_config, keep_volume=False) if arc else None
    clean_author = sanitize_filename(author) if author else None

    # Format volume
    vol_str = format_volume_number(volume_number)

    # Format ASIN (optional - if None, omit ASIN component)
    # Pre-sanitize ASIN to ensure it doesn't introduce characters needing expansion later
    clean_asin = sanitize_filename(asin) if asin else None
    asin_str = f"{{ASIN.{clean_asin}}}" if clean_asin else ""

    # Calculate max base length
    # If folder_max_length is set, use min(folder constraint, path constraint)
    # This ensures both folder AND full path stay within their respective limits
    if folder_max_length is not None:
        # Folder = "{base} [{tag}]" or just "{base}"
        tag_overhead = len(f" [{ripper_tag}]") if ripper_tag else 0
        base_from_folder = folder_max_length - tag_overhead

        # Also calculate path budget to ensure full path stays within limit
        base_from_path = _calculate_max_base_length(
            ripper_tag=ripper_tag,
            extension=extension,
            part_count=part_count,
            max_path_length=max_path_length,
        )

        # Use the stricter of the two constraints
        max_base_len = min(base_from_folder, base_from_path)
    else:
        # Use path budget formula only
        max_base_len = _calculate_max_base_length(
            ripper_tag=ripper_tag,
            extension=extension,
            part_count=part_count,
            max_path_length=max_path_length,
        )

    # Build the base name (with truncation if needed)
    base_name, truncated, dropped = _build_truncated_base_name(
        series=clean_series,
        title=clean_title,
        vol_str=vol_str,
        arc=clean_arc,
        year=year,
        author=clean_author,
        asin_str=asin_str,
        max_length=max_base_len,
        naming_config=naming_config,
    )

    # Sanitize the base name (can increase length: e.g., ':' -> ' -')
    base_name = sanitize_filename(base_name)

    # Re-check length after sanitization - truncate if sanitization expanded it
    if len(base_name) > max_base_len:
        # Capture original length before truncation for logging
        original_len = len(base_name)
        # Truncate to fit, preserving the ASIN at the end
        asin_idx = base_name.rfind("{ASIN.")
        if asin_idx > 0:
            # Keep ASIN intact, truncate before it
            available = max_base_len - (len(base_name) - asin_idx) - 4  # 4 for "... "
            if available > 3:
                base_name = base_name[:available] + "... " + base_name[asin_idx:]
                if not truncated:
                    truncated = True
                    dropped.append("sanitization_expansion")
            else:
                # Emergency: just hard truncate
                base_name = base_name[:max_base_len]
        else:
            base_name = base_name[:max_base_len]
        logger.debug(
            "Post-sanitization truncation for %s: base exceeded budget by %d chars",
            asin,
            max(0, original_len - max_base_len),
        )

    # Check if tag was dropped during truncation (not yet implemented in _build_truncated_base_name)
    # For now, tag is always included if provided - it's handled by the budget formula

    # Sanitize ripper_tag to protect against special characters
    clean_tag = sanitize_filename(ripper_tag) if ripper_tag else None

    # Build folder and filename
    folder = f"{base_name} [{clean_tag}]" if clean_tag else base_name

    filename = f"{base_name}{extension}"
    full_path = f"{folder}/{filename}"

    # Log if truncation occurred
    if truncated:
        logger.debug(
            "Truncated MAM path for %s: %d chars, dropped: %s",
            asin,
            len(full_path),
            dropped,
        )

    return mam_path_cls(
        folder=folder,
        filename=filename,
        full_path=full_path,
        length=len(full_path),
        truncated=truncated,
        dropped_components=dropped,
    )


def build_mam_folder_name(
    *,
    series: str | None = None,
    title: str,
    volume_number: str | None = None,
    arc: str | None = None,
    year: str | None = None,
    author: str | None = None,
    asin: str | None = None,
    ripper_tag: str | None = None,
    naming_config: NamingConfig | None = None,
    max_length: int = MAM_MAX_FILENAME_LENGTH,
) -> str:
    """
    Build a MAM-compliant folder name for staging.

    This is a convenience wrapper around build_mam_path() that returns just the folder name.
    For full path control (folder + filename), use build_mam_path() directly.

    Note: When max_length is less than 225, this function uses folder-only mode
    where max_length is the maximum folder length (not the full path budget).

    Schema for series books:
        {Series} vol_{NN} {Arc} ({Year}) ({Author}) {ASIN.xxxxx} [{Tag}]

    Schema for standalone books:
        {Title} ({Year}) ({Author}) {ASIN.xxxxx} [{Tag}]

    Args:
        series: Series name (cleaned). If None, treated as standalone.
        title: Book title (used for standalone books or fallback)
        volume_number: Volume/book number (e.g., "3", "12")
        arc: Arc/subtitle name (optional, e.g., "Aincrad")
        year: Release year (4 digits)
        author: Primary author name (cleaned)
        asin: Amazon ASIN (optional - if None, ASIN component is omitted)
        ripper_tag: Optional ripper tag (e.g., "H2OKing")
        naming_config: NamingConfig for cleaning rules
        max_length: Maximum folder length (default: 225 for MAM)

    Returns:
        Sanitized folder name within length limit
    """
    # Delegate to build_mam_path for centralized logic
    # Use folder_max_length for folder-specific truncation
    # For max_path_length: use the larger of max_length or MAM_MAX_PATH_LENGTH
    # This allows callers (like ABS importer) to disable truncation by passing
    # a very large max_length, while keeping default MAM behavior for normal calls
    mam_path = build_mam_path(
        series=series,
        title=title,
        volume_number=volume_number,
        arc=arc,
        year=year,
        author=author,
        asin=asin,
        ripper_tag=ripper_tag,
        naming_config=naming_config,
        max_path_length=max(max_length, MAM_MAX_PATH_LENGTH),  # Never stricter than 225
        folder_max_length=max_length,  # But constrain folder to caller's limit
    )
    return mam_path.folder


def build_mam_file_name(
    *,
    series: str | None = None,
    title: str,
    volume_number: str | None = None,
    arc: str | None = None,
    year: str | None = None,
    author: str | None = None,
    asin: str | None = None,
    extension: str = ".m4b",
    naming_config: NamingConfig | None = None,
    max_length: int = MAM_MAX_FILENAME_LENGTH,
) -> str:
    """
    Build a MAM-compliant file name (without ripper tag).

    This is a convenience wrapper around build_mam_path() that returns just the filename.
    For full path control (folder + filename), use build_mam_path() directly.

    Same schema as folder name but:
    - No ripper tag (only on folder)
    - Includes file extension

    Note: max_length is treated as the full path budget (folder + filename combined),
    not the raw filename length. Because the base name is shared between folder and
    filename, the actual filename will be approximately half of max_length. This
    ensures MAM's 225-char path limit is respected when folder and file are combined.

    Args:
        series: Series name (cleaned)
        title: Book title
        volume_number: Volume/book number
        arc: Arc/subtitle name
        year: Release year
        author: Primary author name
        asin: Amazon ASIN (optional - if None, ASIN component is omitted)
        extension: File extension (default: ".m4b")
        naming_config: NamingConfig for cleaning rules
        max_length: Path budget for truncation (not raw filename length).
                    The base name is truncated so folder + filename fit within this limit.

    Returns:
        Sanitized filename with extension within path budget
    """
    # Ensure extension starts with dot
    if extension and not extension.startswith("."):
        extension = f".{extension}"

    # Delegate to build_mam_path for centralized logic (no ripper tag for filename)
    mam_path = build_mam_path(
        series=series,
        title=title,
        volume_number=volume_number,
        arc=arc,
        year=year,
        author=author,
        asin=asin,
        ripper_tag=None,  # No tag on filename
        extension=extension,
        naming_config=naming_config,
        max_path_length=max_length,
    )
    return mam_path.filename
