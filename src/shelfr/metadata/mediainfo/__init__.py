"""
MediaInfo extraction module.

Provides functions to run MediaInfo on audio files and parse the results,
including audio format detection (Dolby Atmos, xHE-AAC, etc.) and chapter extraction.
"""

from __future__ import annotations

from .extractor import (
    AudioFormat,
    _extract_audio_info,
    _format_chapter_time,
    _parse_chapters_from_mediainfo,
    detect_audio_format,
    detect_audio_format_from_file,
    run_mediainfo,
    save_mediainfo_json,
)

__all__ = [
    "AudioFormat",
    "detect_audio_format",
    "detect_audio_format_from_file",
    "run_mediainfo",
    "save_mediainfo_json",
    # Internal helpers (exposed for cross-module use within metadata package)
    "_extract_audio_info",
    "_format_chapter_time",
    "_parse_chapters_from_mediainfo",
]
