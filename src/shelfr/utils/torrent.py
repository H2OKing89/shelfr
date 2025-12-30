"""
Torrent file utilities for extracting metadata.

Simple bencode decoder and infohash extraction without external dependencies.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _decode_int(data: bytes, start: int) -> tuple[int, int]:
    """Decode bencoded integer. Format: i<number>e"""
    end = data.index(b"e", start)
    return int(data[start:end]), end + 1


def _decode_bytes(data: bytes, start: int) -> tuple[bytes, int]:
    """Decode bencoded string. Format: <length>:<string>"""
    colon = data.index(b":", start)
    length = int(data[start:colon])
    start = colon + 1
    return data[start : start + length], start + length


def _decode_list(data: bytes, start: int) -> tuple[list[Any], int]:
    """Decode bencoded list. Format: l<items>e"""
    items = []
    start += 1  # Skip 'l'
    while data[start : start + 1] != b"e":
        item, start = _decode_value(data, start)
        items.append(item)
    return items, start + 1  # Skip 'e'


def _decode_dict(data: bytes, start: int) -> tuple[dict[bytes, Any], int]:
    """Decode bencoded dict. Format: d<key><value>...e"""
    items = {}
    start += 1  # Skip 'd'
    while data[start : start + 1] != b"e":
        key, start = _decode_bytes(data, start)
        value, start = _decode_value(data, start)
        items[key] = value
    return items, start + 1  # Skip 'e'


def _decode_value(data: bytes, start: int) -> tuple[Any, int]:
    """Decode a bencoded value (int, bytes, list, or dict)."""
    prefix = data[start : start + 1]

    if prefix == b"i":
        return _decode_int(data, start + 1)
    elif prefix == b"l":
        return _decode_list(data, start)
    elif prefix == b"d":
        return _decode_dict(data, start)
    elif prefix.isdigit():
        return _decode_bytes(data, start)
    else:
        raise ValueError(f"Invalid bencode at position {start}: {prefix!r}")


def bdecode(data: bytes) -> Any:
    """
    Decode bencoded data.

    Args:
        data: Raw bencoded bytes

    Returns:
        Decoded Python object (dict, list, int, or bytes)
    """
    value, _ = _decode_value(data, 0)
    return value


def bencode(obj: Any) -> bytes:
    """
    Encode Python object to bencode format.

    Used for re-encoding the info dict to compute infohash.
    """
    if isinstance(obj, int):
        return b"i" + str(obj).encode() + b"e"
    elif isinstance(obj, bytes):
        return str(len(obj)).encode() + b":" + obj
    elif isinstance(obj, str):
        return bencode(obj.encode("utf-8"))
    elif isinstance(obj, list):
        return b"l" + b"".join(bencode(item) for item in obj) + b"e"
    elif isinstance(obj, dict):
        items = []
        # Dict keys must be sorted for canonical bencode
        for key in sorted(obj.keys()):
            items.append(bencode(key))
            items.append(bencode(obj[key]))
        return b"d" + b"".join(items) + b"e"
    else:
        raise TypeError(f"Cannot bencode type {type(obj)}")


def extract_infohash(torrent_path: Path) -> str | None:
    """
    Extract the infohash (SHA1 of bencoded info dict) from a torrent file.

    The infohash is the canonical identifier for a torrent and is used by
    BitTorrent clients to identify duplicate torrents.

    Args:
        torrent_path: Path to .torrent file

    Returns:
        40-character hex string (lowercase) or None on error

    Example:
        >>> infohash = extract_infohash(Path("release.torrent"))
        >>> print(infohash)
        'a1b2c3d4e5f6...'
    """
    try:
        with open(torrent_path, "rb") as f:
            torrent_data = f.read()

        # Decode torrent file
        metadata = bdecode(torrent_data)

        if not isinstance(metadata, dict):
            logger.error(f"Invalid torrent file (not a dict): {torrent_path}")
            return None

        # Extract 'info' dict
        info = metadata.get(b"info")
        if not info:
            logger.error(f"Torrent file missing 'info' dict: {torrent_path}")
            return None

        # Re-encode info dict and compute SHA1
        info_bencoded = bencode(info)
        infohash = hashlib.sha1(info_bencoded).hexdigest()

        logger.debug(f"Extracted infohash from {torrent_path.name}: {infohash}")
        return infohash

    except Exception as e:
        logger.error(f"Failed to extract infohash from {torrent_path}: {e}")
        return None


def get_torrent_name(torrent_path: Path) -> str | None:
    """
    Extract the torrent name from a torrent file.

    Args:
        torrent_path: Path to .torrent file

    Returns:
        Torrent name string or None on error
    """
    try:
        with open(torrent_path, "rb") as f:
            torrent_data = f.read()

        metadata = bdecode(torrent_data)

        if not isinstance(metadata, dict):
            return None

        info = metadata.get(b"info")
        if not info:
            return None

        name = info.get(b"name")
        if name and isinstance(name, bytes):
            decoded: str = name.decode("utf-8", errors="replace")
            return decoded

        return None

    except Exception as e:
        logger.error(f"Failed to extract name from {torrent_path}: {e}")
        return None
