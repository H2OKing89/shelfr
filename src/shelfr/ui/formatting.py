"""MediaInfo formatting helpers for MAMFast UI.

These components format audio file metadata for display.
"""

from __future__ import annotations

from contextlib import suppress
from typing import Any


def format_mediainfo_stats(mediainfo_data: dict[str, Any] | None) -> str | None:
    """Format MediaInfo data as a compact stats line.

    Args:
        mediainfo_data: MediaInfo JSON data from mediainfo --Output=JSON

    Returns:
        Formatted string like "10h 42m • M4B • AAC • 64 kbps • 2ch" or None

    Example:
        >>> format_mediainfo_stats(mediainfo_json)
        '10h 42m • M4B • AAC • 64 kbps • 2ch'
    """
    if not mediainfo_data:
        return None

    media = mediainfo_data.get("media")
    if not media:
        return None

    tracks = media.get("track", [])
    if not tracks:
        return None

    # Extract from General track
    duration_seconds: float | None = None
    file_format: str | None = None
    for track in tracks:
        if track.get("@type") == "General":
            # Duration
            dur = track.get("Duration")
            if dur:
                with suppress(ValueError, TypeError):
                    duration_seconds = float(dur)
            # Format (e.g., "MPEG-4" -> "M4B" for audiobooks)
            fmt = track.get("Format")
            if fmt:
                file_format = fmt.upper()
                # Friendlier names
                if file_format in ("MPEG-4", "MPEG-4 AUDIO"):
                    file_format = "M4B"
                elif file_format == "MATROSKA":
                    file_format = "MKA"

    # Extract from Audio track
    codec: str | None = None
    bitrate_kbps: int | None = None
    channels: int | None = None
    for track in tracks:
        if track.get("@type") == "Audio":
            # Codec
            fmt = track.get("Format")
            if fmt:
                codec = fmt.upper()
            # Bitrate
            br = track.get("BitRate")
            if br:
                with suppress(ValueError, TypeError):
                    bitrate_kbps = int(float(br)) // 1000
            # Channels
            ch = track.get("Channels")
            if ch:
                with suppress(ValueError, TypeError):
                    channels = int(ch)
            break  # Use first audio track

    # Build parts
    parts: list[str] = []

    if duration_seconds is not None:
        hours, remainder = divmod(int(duration_seconds), 3600)
        minutes = remainder // 60
        if hours > 0:
            parts.append(f"{hours}h {minutes:02d}m")
        else:
            parts.append(f"{minutes}m")

    if file_format:
        parts.append(file_format)

    if codec:
        parts.append(codec)

    if bitrate_kbps is not None:
        parts.append(f"{bitrate_kbps} kbps")

    if channels is not None:
        parts.append(f"{channels}ch")

    if not parts:
        return None

    return " • ".join(parts)


def truncate_path(path: str, max_length: int = 50) -> str:
    """Truncate a path for display, keeping the end visible.

    Args:
        path: Full path to truncate
        max_length: Maximum display length

    Returns:
        Truncated path like "…/Author - Title (2024)"

    Example:
        >>> truncate_path("/very/long/path/to/Author - Title (2024)", max_length=30)
        '…/Author - Title (2024)'
    """
    if len(path) <= max_length:
        return path

    # Reserve one character for the leading ellipsis and keep the last
    # ``max_length - 1`` characters of the path
    keep_chars = max_length - 1
    return "…" + path[-keep_chars:]


def format_duration(seconds: int | float | None) -> str:
    """Format duration in human-readable form.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted string like "2h 15m" or "45m"

    Example:
        >>> format_duration(8100)
        '2h 15m'
    """
    if seconds is None:
        return "?"
    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def format_bitrate(bitrate: int | None) -> str:
    """Format bitrate for display.

    Args:
        bitrate: Bitrate in kbps

    Returns:
        Formatted string like "128 kbps"
    """
    if bitrate is None:
        return "?"
    return f"{bitrate} kbps"


def format_file_size(size_bytes: int | None) -> str:
    """Format file size in human-readable form.

    Args:
        size_bytes: Size in bytes

    Returns:
        Formatted string like "1.5 GB" or "256 MB"
    """
    if size_bytes is None:
        return "?"

    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024  # type: ignore[assignment]

    return f"{size_bytes:.1f} PB"
