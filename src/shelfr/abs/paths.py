"""Path mapping utilities for Audiobookshelf Docker containers.

Handles translation between container paths (what ABS sees) and host paths
(what Shelfr sees on the filesystem).
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
    if abs_path_str != container_prefix and not abs_path_str.startswith(container_prefix + "/"):
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
        raise ValueError(f"Path '{host_path_str}' does not start with host prefix '{host_prefix}'")

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
    Supports single or multiple path mappings.
    """

    def __init__(
        self,
        container_prefix: str | None = None,
        host_prefix: str | None = None,
        *,
        mappings: list[dict[str, str]] | None = None,
    ) -> None:
        """Initialize with container and host prefixes.

        Can be initialized with either:
        - Single mapping: PathMapper("/audiobooks", "/mnt/user/data/audio")
        - Multiple mappings: PathMapper(mappings=[{"container": "/a", "host": "/b"}])

        Args:
            container_prefix: Container path prefix (e.g., "/audiobooks")
            host_prefix: Host path prefix (e.g., "/mnt/user/data/audio/audiobooks")
            mappings: List of dicts with "container" and "host" keys
        """
        self._mappings: list[tuple[str, str]] = []

        if mappings:
            # Multiple mappings mode - validate required keys and non-empty values
            for i, m in enumerate(mappings):
                if "container" not in m or "host" not in m:
                    raise ValueError(
                        f"Mapping at index {i} missing required 'container' or 'host' key: {m}"
                    )
                if not m["container"] or not m["host"]:
                    raise ValueError(
                        f"Mapping at index {i} has empty 'container' or 'host' value: {m}"
                    )
            for m in mappings:
                self._mappings.append((m["container"].rstrip("/"), m["host"].rstrip("/")))
            # Sort by container prefix length (longest first) for best match
            self._mappings.sort(key=lambda x: len(x[0]), reverse=True)
        elif container_prefix is not None and host_prefix is not None:
            # Single mapping mode (backwards compatible)
            self._mappings = [(container_prefix.rstrip("/"), host_prefix.rstrip("/"))]
        # Empty mappings is allowed - paths pass through unchanged

        # For backwards compatibility, expose first mapping's prefixes
        if self._mappings:
            self.container_prefix = self._mappings[0][0]
            self.host_prefix = self._mappings[0][1]
        else:
            self.container_prefix = ""
            self.host_prefix = ""

    def to_host(self, abs_path: str | Path) -> Path:
        """Convert container path to host path."""
        abs_path_str = str(abs_path)

        # Try each mapping (sorted by longest prefix first)
        for container_prefix, host_prefix in self._mappings:
            if abs_path_str == container_prefix or abs_path_str.startswith(container_prefix + "/"):
                return abs_path_to_host(abs_path_str, container_prefix, host_prefix)

        # No mapping matched - return path as-is
        logger.debug("No mapping matched for path: %s", abs_path_str)
        return Path(abs_path_str)

    def to_container(self, host_path: str | Path) -> str:
        """Convert host path to container path."""
        host_path_str = str(host_path)

        # Try each mapping (need to sort by host prefix length)
        sorted_by_host = sorted(self._mappings, key=lambda x: len(x[1]), reverse=True)
        for container_prefix, host_prefix in sorted_by_host:
            if host_path_str == host_prefix or host_path_str.startswith(host_prefix + "/"):
                return host_path_to_abs(host_path_str, container_prefix, host_prefix)

        # No mapping matched - return path as-is
        logger.debug("No mapping matched for path: %s", host_path_str)
        return host_path_str

    def is_under_container(self, path: str | Path) -> bool:
        """Check if a path is under any container prefix."""
        path_str = str(path)
        for container_prefix, _ in self._mappings:
            if path_str == container_prefix or path_str.startswith(container_prefix + "/"):
                return True
        return False

    def is_under_host(self, path: str | Path) -> bool:
        """Check if a path is under any host prefix."""
        path_str = str(path)
        for _, host_prefix in self._mappings:
            if path_str == host_prefix or path_str.startswith(host_prefix + "/"):
                return True
        return False
