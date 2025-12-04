"""Path mapping utilities for Audiobookshelf Docker containers.

Handles translation between container paths (what ABS sees) and host paths
(what MAMFast sees on the filesystem).
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def abs_path_to_host(
    abs_path: str | Path,
    container_prefix: str,
    host_prefix: str,
) -> Path:
    """Convert an Audiobookshelf container path to a host path.

    Args:
        abs_path: Path as reported by Audiobookshelf (container path)
        container_prefix: Container path prefix (e.g., "/audiobooks")
        host_prefix: Host path prefix (e.g., "/mnt/user/data/audio/audiobooks")

    Returns:
        Path on the host filesystem

    Raises:
        ValueError: If abs_path doesn't start with container_prefix

    Example:
        >>> abs_path_to_host(
        ...     "/audiobooks/Author/Book",
        ...     "/audiobooks",
        ...     "/mnt/user/data/audio/audiobooks"
        ... )
        PosixPath('/mnt/user/data/audio/audiobooks/Author/Book')
    """
    abs_path_str = str(abs_path)

    # Normalize prefixes (remove trailing slashes)
    container_prefix = container_prefix.rstrip("/")
    host_prefix = host_prefix.rstrip("/")

    # Check for exact match OR path with separator (prevents /audiobooks2 matching /audiobooks)
    if abs_path_str != container_prefix and not abs_path_str.startswith(
        container_prefix + "/"
    ):
        raise ValueError(
            f"Path '{abs_path_str}' does not start with container prefix '{container_prefix}'"
        )

    # Get the relative portion after the container prefix
    relative = abs_path_str[len(container_prefix) :]

    # Handle edge case where abs_path equals container_prefix exactly
    if not relative:
        return Path(host_prefix)

    # relative starts with "/" - join it properly
    return Path(host_prefix + relative)


def host_path_to_abs(
    host_path: str | Path,
    container_prefix: str,
    host_prefix: str,
) -> str:
    """Convert a host path to an Audiobookshelf container path.

    Args:
        host_path: Path on the host filesystem
        container_prefix: Container path prefix (e.g., "/audiobooks")
        host_prefix: Host path prefix (e.g., "/mnt/user/data/audio/audiobooks")

    Returns:
        Path as Audiobookshelf would see it (container path)

    Raises:
        ValueError: If host_path doesn't start with host_prefix

    Example:
        >>> host_path_to_abs(
        ...     "/mnt/user/data/audio/audiobooks/Author/Book",
        ...     "/audiobooks",
        ...     "/mnt/user/data/audio/audiobooks"
        ... )
        '/audiobooks/Author/Book'
    """
    host_path_str = str(host_path)

    # Normalize prefixes (remove trailing slashes)
    container_prefix = container_prefix.rstrip("/")
    host_prefix = host_prefix.rstrip("/")

    # Check for exact match OR path with separator (prevents /mnt/data2 matching /mnt/data)
    if host_path_str != host_prefix and not host_path_str.startswith(host_prefix + "/"):
        raise ValueError(
            f"Path '{host_path_str}' does not start with host prefix '{host_prefix}'"
        )

    # Get the relative portion after the host prefix
    relative = host_path_str[len(host_prefix) :]

    # Handle edge case where host_path equals host_prefix exactly
    if not relative:
        return container_prefix

    # relative starts with "/" - join it properly
    return container_prefix + relative


class PathMapper:
    """Convenience class for path mapping with stored config.

    Use when you need to map many paths with the same prefix configuration.
    """

    def __init__(self, container_prefix: str, host_prefix: str) -> None:
        """Initialize with container and host prefixes.

        Args:
            container_prefix: Container path prefix (e.g., "/audiobooks")
            host_prefix: Host path prefix (e.g., "/mnt/user/data/audio/audiobooks")
        """
        self.container_prefix = container_prefix.rstrip("/")
        self.host_prefix = host_prefix.rstrip("/")

    def to_host(self, abs_path: str | Path) -> Path:
        """Convert container path to host path."""
        return abs_path_to_host(abs_path, self.container_prefix, self.host_prefix)

    def to_container(self, host_path: str | Path) -> str:
        """Convert host path to container path."""
        return host_path_to_abs(host_path, self.container_prefix, self.host_prefix)

    def is_under_container(self, path: str | Path) -> bool:
        """Check if a path is under the container prefix."""
        path_str = str(path)
        return (
            path_str == self.container_prefix
            or path_str.startswith(self.container_prefix + "/")
        )

    def is_under_host(self, path: str | Path) -> bool:
        """Check if a path is under the host prefix."""
        path_str = str(path)
        return (
            path_str == self.host_prefix or path_str.startswith(self.host_prefix + "/")
        )
