"""
Shared types for metadata module.

These are small dataclasses used across multiple submodules to avoid
circular imports (e.g., formatting depends on chapters, mediainfo produces chapters).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Chapter:
    """Chapter info for BBCode template and metadata exports.

    Attributes:
        start: Chapter start time in HH:MM:SS format (e.g., "00:55:52" or "1:30:45")
        title: Chapter title (e.g., "Chapter 2: Wandering Goblin Slayer")
    """

    start: str
    title: str
