"""
MediaInfo extractor for audiobook technical metadata.

This module handles running MediaInfo on audio files and parsing the JSON output
to extract technical metadata (codec, bitrate, channels) and chapter information.

Key functions:
    - run_mediainfo(): Execute MediaInfo CLI and parse JSON output
    - detect_audio_format(): Parse MediaInfo data to detect Dolby Atmos, xHE-AAC, etc.
    - save_mediainfo_json(): Persist MediaInfo output to disk
"""

from __future__ import annotations

import contextlib
import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from shelfr.config import get_settings
from shelfr.utils.permissions import fix_ownership
from shelfr.utils.retry import SUBPROCESS_EXCEPTIONS, retry_with_backoff

if TYPE_CHECKING:
    from shelfr.metadata.models import Chapter

logger = logging.getLogger(__name__)


# =============================================================================
# Audio Format Detection
# =============================================================================


@dataclass
class AudioFormat:
    """Audio format information extracted from MediaInfo.

    Used for detecting Dolby Atmos, high-bitrate editions, etc.
    to disambiguate files with the same ASIN.

    Codec names:
        - AAC: Advanced Audio Coding (standard Audible format)
        - USAC: Unified Speech and Audio Coding (xHE-AAC, high efficiency)
        - E-AC-3: Enhanced AC-3 (Dolby Digital Plus, used for Atmos)
        - MP3: MPEG Audio Layer III
    """

    codec: str  # "AAC", "USAC", "E-AC-3", "MP3"
    codec_id: str  # "mp4a-40-2", "ec-3", "mp4a-40-42" (xHE-AAC)
    bitrate: int  # bits per second (e.g., 128000, 768000)
    bitrate_mode: str  # "VBR", "CBR"
    channels: int  # 2 (stereo), 6 (5.1)
    channel_layout: str  # "L R", "L R C LFE Ls Rs"
    sample_rate: int  # 44100, 48000
    is_dolby_atmos: bool  # True if Dolby Atmos detected
    is_xhe_aac: bool  # True if xHE-AAC/USAC detected
    format_commercial: str | None  # "Dolby Digital Plus with Dolby Atmos"
    dynamic_objects: int | None  # Number of Atmos dynamic objects

    def get_edition_tag(self) -> str | None:
        """
        Get an edition tag based on audio format.

        Returns:
            Edition tag like "(Dolby Atmos)", "(xHE-AAC)", "(768kbps)" or None
        """
        if self.is_dolby_atmos:
            return "(Dolby Atmos)"

        if self.is_xhe_aac:
            return "(xHE-AAC)"

        # High bitrate detection (> 256kbps for AAC is high quality)
        bitrate_kbps = self.bitrate // 1000
        if bitrate_kbps >= 256 and self.codec == "AAC":
            return f"({bitrate_kbps}kbps)"

        return None

    def get_quality_tier(self) -> str:
        """
        Get quality tier for sorting/comparison.

        Returns:
            Quality tier: "atmos", "high", "standard", "low"
        """
        if self.is_dolby_atmos:
            return "atmos"

        # xHE-AAC is high efficiency - similar quality at lower bitrate
        if self.is_xhe_aac:
            return "high"

        bitrate_kbps = self.bitrate // 1000
        if bitrate_kbps >= 256:
            return "high"
        if bitrate_kbps >= 96:
            return "standard"
        return "low"

    def get_format_description(self) -> str:
        """
        Get human-readable format description.

        Returns:
            Description like "Dolby Atmos 5.1 768kbps" or "xHE-AAC 124kbps"
        """
        parts = []

        if self.is_dolby_atmos:
            parts.append("Dolby Atmos")
        elif self.is_xhe_aac:
            parts.append("xHE-AAC")
        else:
            parts.append(self.codec)

        if self.channels > 2:
            if self.channels == 6:
                parts.append("5.1")
            else:
                parts.append(f"{self.channels}ch")

        parts.append(f"{self.bitrate // 1000}kbps")

        return " ".join(parts)


def detect_audio_format(mediainfo_data: dict[str, Any] | None) -> AudioFormat | None:
    """
    Extract audio format information from MediaInfo JSON.

    Detects Dolby Atmos, codec, bitrate, channels, etc.

    Args:
        mediainfo_data: Parsed MediaInfo JSON from run_mediainfo()

    Returns:
        AudioFormat with detected properties, or None if no audio track found.

    Example MediaInfo audio track for Dolby Atmos:
        {
            "@type": "Audio",
            "Format": "E-AC-3",
            "Format_Commercial_IfAny": "Dolby Digital Plus with Dolby Atmos",
            "Format_AdditionalFeatures": "JOC",
            "CodecID": "ec-3",
            "BitRate": "768500",
            "Channels": "6",
            "ChannelLayout": "L R C LFE Ls Rs",
            "SamplingRate": "48000",
            "extra": {"NumberOfDynamicObjects": "15"}
        }
    """
    if not mediainfo_data:
        return None

    media = mediainfo_data.get("media")
    if not media:
        return None

    tracks = media.get("track", [])

    # Find the audio track
    audio_track: dict[str, Any] | None = None
    for track in tracks:
        if track.get("@type") == "Audio":
            audio_track = track
            break

    if not audio_track:
        logger.debug("No audio track found in MediaInfo")
        return None

    # Extract basic properties
    codec = audio_track.get("Format", "Unknown")
    codec_id = audio_track.get("CodecID", "")
    bitrate_str = audio_track.get("BitRate", "0")
    bitrate_mode = audio_track.get("BitRate_Mode", "VBR")
    channels_str = audio_track.get("Channels", "2")
    channel_layout = audio_track.get("ChannelLayout", "")
    sample_rate_str = audio_track.get("SamplingRate", "44100")

    # Parse numeric values
    try:
        bitrate = int(float(bitrate_str))
    except (ValueError, TypeError):
        bitrate = 0

    try:
        channels = int(channels_str)
    except (ValueError, TypeError):
        channels = 2

    try:
        sample_rate = int(sample_rate_str)
    except (ValueError, TypeError):
        sample_rate = 44100

    # Detect Dolby Atmos
    format_commercial = audio_track.get("Format_Commercial_IfAny")
    format_additional = audio_track.get("Format_AdditionalFeatures", "")
    extra = audio_track.get("extra", {})
    dynamic_objects_str = extra.get("NumberOfDynamicObjects")

    is_dolby_atmos = any(
        (
            format_commercial and "Dolby Atmos" in format_commercial,
            "JOC" in format_additional,  # Joint Object Coding = Atmos
            codec_id == "ec-3" and dynamic_objects_str,  # E-AC-3 with objects
        )
    )

    # Detect xHE-AAC (USAC - Unified Speech and Audio Coding)
    # MediaInfo reports this as "USAC" format or codec_id "mp4a-40-42"
    is_xhe_aac = any(
        (
            codec == "USAC",
            codec_id == "mp4a-40-42",  # xHE-AAC codec ID
            "xHE-AAC" in (format_commercial or ""),
        )
    )

    # Parse dynamic objects count
    dynamic_objects: int | None = None
    if dynamic_objects_str:
        with contextlib.suppress(ValueError, TypeError):
            dynamic_objects = int(dynamic_objects_str)

    return AudioFormat(
        codec=codec,
        codec_id=codec_id,
        bitrate=bitrate,
        bitrate_mode=bitrate_mode,
        channels=channels,
        channel_layout=channel_layout,
        sample_rate=sample_rate,
        is_dolby_atmos=is_dolby_atmos,
        is_xhe_aac=is_xhe_aac,
        format_commercial=format_commercial,
        dynamic_objects=dynamic_objects,
    )


def detect_audio_format_from_file(file_path: Path) -> AudioFormat | None:
    """
    Detect audio format directly from a file.

    Convenience wrapper that runs mediainfo and extracts format.

    Args:
        file_path: Path to audio file (m4b, mp3, etc.)

    Returns:
        AudioFormat or None if detection fails.
    """
    mediainfo_data = run_mediainfo(file_path)
    return detect_audio_format(mediainfo_data)


# =============================================================================
# MediaInfo Execution
# =============================================================================


@retry_with_backoff(
    max_retries=3,
    base_delay=1.0,
    max_delay=10.0,
    exceptions=SUBPROCESS_EXCEPTIONS,
)
def _run_mediainfo_subprocess(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run mediainfo subprocess with retry on transient failures."""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,  # Timeout for large files
    )


def run_mediainfo(file_path: Path) -> dict[str, Any] | None:
    """
    Run mediainfo on a file and return parsed JSON output.

    Args:
        file_path: Path to audio file (typically .m4b)

    Returns:
        Parsed MediaInfo JSON or None on error.

    Note:
        P2 Migration Deferred: This function uses subprocess directly instead of
        the sh library wrapper (utils/cmd.py). Migration deferred due to single
        call in large file (low impact). See docs/archive/P1_SH_LIBRARY_COMPLETE.md and
        docs/MIGRATION_BACKLOG.md for rationale and future migration plan.
    """
    settings = get_settings()
    binary = settings.mediainfo.binary

    if not file_path.exists():
        logger.error(f"File not found for mediainfo: {file_path}")
        return None

    cmd = [
        binary,
        "--Output=JSON",
        str(file_path),
    ]

    logger.debug(f"Running mediainfo: {' '.join(cmd)}")

    try:
        result = _run_mediainfo_subprocess(cmd)

        data: dict[str, Any] = json.loads(result.stdout)
        logger.info(f"Got MediaInfo for: {file_path.name}")
        return data

    except FileNotFoundError:
        logger.error(f"mediainfo binary not found: {binary}")
        return None

    except subprocess.CalledProcessError as e:
        logger.error(f"mediainfo failed: {e.stderr}")
        return None

    except subprocess.TimeoutExpired:
        logger.error(f"mediainfo timed out for: {file_path}")
        return None

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON from mediainfo: {e}")
        return None


def save_mediainfo_json(data: dict[str, Any], output_path: Path) -> None:
    """Write MediaInfo data to JSON file."""
    settings = get_settings()
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    fix_ownership(output_path, settings.target_uid, settings.target_gid)
    logger.info(f"Saved MediaInfo to: {output_path}")


# =============================================================================
# Chapter Extraction (used by formatting/bbcode)
# =============================================================================


def _format_chapter_time(seconds: float) -> str:
    """
    Format chapter timestamp to HH:MM:SS format.

    Always uses leading zeros for professional appearance:
    - 0 seconds -> 00:00:00
    - 65 seconds -> 00:01:05
    - 5465 seconds -> 01:31:05

    Args:
        seconds: Time in seconds

    Returns:
        Formatted time string in HH:MM:SS format
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _format_duration(seconds: float) -> str:
    """
    Format duration in seconds to human readable (e.g., '6h 11m').

    Args:
        seconds: Duration in seconds

    Returns:
        Human readable duration string
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)

    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _parse_chapters_from_mediainfo(mediainfo_data: dict[str, Any]) -> list[Chapter]:
    """
    Extract chapter list from MediaInfo JSON.

    Args:
        mediainfo_data: MediaInfo JSON dict

    Returns:
        List of Chapter objects
    """
    # Import here to avoid circular import at module load time
    from shelfr.metadata.models import Chapter

    chapters: list[Chapter] = []

    try:
        media = mediainfo_data.get("media", {})
        tracks = media.get("track", [])

        # Find the Menu track which contains chapters
        for track in tracks:
            if track.get("@type") == "Menu":
                extra = track.get("extra", {})
                # Chapter entries look like: "_00_07_35_573": "Chapter 1"
                chapter_entries = []
                for key, value in extra.items():
                    if key.startswith("_") and "_" in key[1:]:
                        # Parse timestamp: _00_07_35_573 -> 00:07:35.573
                        parts = key[1:].split("_")
                        if len(parts) >= 3:
                            h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
                            total_seconds = h * 3600 + m * 60 + s
                            chapter_entries.append((total_seconds, value))

                # Sort by timestamp and convert to Chapter objects
                chapter_entries.sort(key=lambda x: x[0])
                for seconds, title in chapter_entries:
                    chapters.append(
                        Chapter(
                            start=_format_chapter_time(seconds),
                            title=title,
                        )
                    )
                break

    except (KeyError, TypeError, ValueError) as e:
        logger.warning(f"Failed to parse chapters from mediainfo: {type(e).__name__}: {e}")

    return chapters


def _extract_audio_info(
    mediainfo_data: dict[str, Any],
) -> dict[str, str]:
    """
    Extract audio/file info from MediaInfo for BBCode template.

    Returns:
        Dict with container, codec, sample_rate, channels, duration_human
    """
    info = {
        "container": "M4B",
        "codec": "AAC LC",
        "sample_rate": "44.1 kHz",
        "channels": "2",
        "duration_human": "Unknown",
    }

    try:
        media = mediainfo_data.get("media", {})
        tracks = media.get("track", [])

        for track in tracks:
            track_type = track.get("@type")

            if track_type == "General":
                # Duration
                duration_str = track.get("Duration")
                if duration_str:
                    duration = float(duration_str)
                    info["duration_human"] = _format_duration(duration)

                # Container format
                fmt = track.get("Format")
                if fmt:
                    ext = track.get("FileExtension", "").upper()
                    info["container"] = ext or fmt

            elif track_type == "Audio":
                # Codec
                codec = track.get("Format", "")
                codec_profile = track.get("Format_AdditionalFeatures", "")
                bitrate_mode = track.get("BitRate_Mode", "")
                bitrate = track.get("BitRate", "")

                if codec:
                    codec_str = codec
                    if codec_profile:
                        codec_str += f" {codec_profile}"
                    if bitrate_mode and bitrate:
                        br_kb = int(bitrate) // 1000
                        codec_str += f" ({bitrate_mode} ~{br_kb} kb/s)"
                    info["codec"] = codec_str

                # Sample rate
                sample_rate = track.get("SamplingRate")
                if sample_rate:
                    sr_khz = float(sample_rate) / 1000
                    info["sample_rate"] = f"{sr_khz} kHz"

                # Channels
                channels = track.get("Channels")
                if channels:
                    info["channels"] = channels

    except (KeyError, TypeError, ValueError) as e:
        logger.warning(f"Failed to extract audio info from mediainfo: {type(e).__name__}: {e}")

    return info
