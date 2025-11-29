"""Path mapping utilities for host ↔ container conversions."""

from __future__ import annotations

import os
from pathlib import Path

from mamfast.config import get_settings


def host_to_container_data_path(path: str | Path) -> str:
    """
    Convert a host path under the data root to the container's path.

    Example:
        /mnt/user/data/audio/book.m4b → /data/audio/book.m4b

    If the path is already a container path, returns it unchanged.
    If the path is not under the data root, returns it unchanged.
    """
    settings = get_settings()
    host_root = settings.mkbrr.host_data_root
    container_root = settings.mkbrr.container_data_root

    path_str = str(path).strip()

    # Already a container path
    if path_str.startswith(container_root + "/") or path_str == container_root:
        return path_str

    # Normalize to absolute
    abs_path = os.path.abspath(path_str)

    # Map host path to container path
    if abs_path.startswith(host_root):
        suffix = abs_path[len(host_root) :]
        return container_root + suffix

    # Not under data root - return as-is (mkbrr will error if invalid)
    return path_str


def host_to_container_torrent_path(path: str | Path) -> str:
    """
    Convert a host .torrent path to the container's torrentfiles path.

    Example:
        /mnt/user/data/downloads/torrents/torrentfiles/book.torrent
        → /torrentfiles/book.torrent

    If already a container path, returns unchanged.
    """
    settings = get_settings()
    host_output = settings.mkbrr.host_output_dir
    container_output = settings.mkbrr.container_output_dir

    path_str = str(path).strip()

    # Already container path
    if path_str.startswith(container_output + "/") or path_str == container_output:
        return path_str

    abs_path = os.path.abspath(path_str)

    # Map host output path to container output path
    if abs_path.startswith(host_output):
        suffix = abs_path[len(host_output) :]
        return container_output + suffix

    # Not under output dir - return as-is
    return path_str


def container_to_host_data_path(path: str | Path) -> str:
    """
    Convert a container path back to host path.

    Example:
        /data/audio/book.m4b → /mnt/user/data/audio/book.m4b
    """
    settings = get_settings()
    host_root = settings.mkbrr.host_data_root
    container_root = settings.mkbrr.container_data_root

    path_str = str(path).strip()

    # Already a host path
    if path_str.startswith(host_root + "/") or path_str == host_root:
        return path_str

    # Map container path to host path
    if path_str.startswith(container_root + "/") or path_str == container_root:
        suffix = path_str[len(container_root) :]
        return host_root + suffix

    return path_str


def container_to_host_torrent_path(path: str | Path) -> str:
    """
    Convert a container torrent path back to host path.

    Example:
        /torrentfiles/book.torrent
        → /mnt/user/data/downloads/torrents/torrentfiles/book.torrent
    """
    settings = get_settings()
    host_output = settings.mkbrr.host_output_dir
    container_output = settings.mkbrr.container_output_dir

    path_str = str(path).strip()

    # Already a host path
    if path_str.startswith(host_output + "/") or path_str == host_output:
        return path_str

    # Map container path to host path
    if path_str.startswith(container_output + "/") or path_str == container_output:
        suffix = path_str[len(container_output) :]
        return host_output + suffix

    return path_str


def ensure_dir(path: Path) -> Path:
    """Create directory if it doesn't exist, return the path."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def path_exists_on_host(path: str | Path) -> bool:
    """Check if a host path exists."""
    return os.path.exists(str(path))
