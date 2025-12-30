"""
Metadata fetching from Audnex API and MediaInfo.

Audnex API: https://api.audnex.us
- GET /books/{asin} - Get book metadata by ASIN
- GET /authors/{asin} - Get author info

MediaInfo: Command-line tool for technical metadata
- mediainfo --Output=JSON <file>

MAM JSON: Fast fillout format for MAM uploads
"""

from __future__ import annotations

import contextlib
import functools
import html
import json
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from jinja2 import BaseLoader, ChoiceLoader, Environment, FileSystemLoader, PackageLoader

from shelfr.config import get_settings
from shelfr.models import NormalizedBook
from shelfr.paths import config_dir
from shelfr.utils.circuit_breaker import CircuitOpenError, audnex_breaker
from shelfr.utils.naming import (
    extract_translators_from_mediainfo,
    filter_authors,
    filter_series,
    filter_subtitle,
    filter_title,
    normalize_audnex_book,
    resolve_series,
    transliterate_text,
)
from shelfr.utils.permissions import fix_ownership
from shelfr.utils.retry import SUBPROCESS_EXCEPTIONS, retry_with_backoff

if TYPE_CHECKING:
    from shelfr.models import AudiobookRelease

logger = logging.getLogger(__name__)


# =============================================================================
# BBCode Description Template
# =============================================================================


@dataclass
class Chapter:
    """Chapter info for BBCode template."""

    start: str  # "00:55:52" or "1:30:45"
    title: str  # "Chapter 2: Wandering Goblin Slayer"


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
        [
            format_commercial and "Dolby Atmos" in format_commercial,
            "JOC" in format_additional,  # Joint Object Coding = Atmos
            codec_id == "ec-3" and dynamic_objects_str,  # E-AC-3 with objects
        ]
    )

    # Detect xHE-AAC (USAC - Unified Speech and Audio Coding)
    # MediaInfo reports this as "USAC" format or codec_id "mp4a-40-42"
    is_xhe_aac = any(
        [
            codec == "USAC",
            codec_id == "mp4a-40-42",  # xHE-AAC codec ID
            "xHE-AAC" in (format_commercial or ""),
        ]
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


@functools.lru_cache(maxsize=1)
def _get_jinja_env() -> Environment:
    """Get Jinja2 environment with template loader (cached).

    Loads templates from:
    1. config/templates/ (user overrides, gitignored)
    2. mamfast/templates/ (package defaults)
    """
    user_templates = config_dir() / "templates"
    loaders: list[BaseLoader] = []

    # User templates take priority if directory exists
    if user_templates.is_dir():
        loaders.append(FileSystemLoader(str(user_templates)))

    # Package templates as fallback
    loaders.append(PackageLoader("shelfr", "templates"))

    return Environment(
        loader=ChoiceLoader(loaders),
        autoescape=False,  # BBCode, not HTML
        trim_blocks=True,
        lstrip_blocks=True,
    )


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


def _format_chapter_time(seconds: float) -> str:
    """
    Format chapter timestamp (e.g., '1:30:45' or '00:27').

    Args:
        seconds: Time in seconds

    Returns:
        Formatted time string
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _parse_chapters_from_mediainfo(mediainfo_data: dict[str, Any]) -> list[Chapter]:
    """
    Extract chapter list from MediaInfo JSON.

    Args:
        mediainfo_data: MediaInfo JSON dict

    Returns:
        List of Chapter objects
    """
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

    except Exception as e:
        logger.warning(f"Failed to parse chapters from mediainfo: {e}")

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

    except Exception as e:
        logger.warning(f"Failed to extract audio info from mediainfo: {e}")

    return info


def render_bbcode_description(
    audnex_data: dict[str, Any],
    mediainfo_data: dict[str, Any] | None = None,
    asin: str | None = None,
    audnex_chapters: dict[str, Any] | None = None,
) -> str:
    """
    Render BBCode description from Audnex and MediaInfo data.

    Uses Jinja2 template for the formatting.

    Args:
        audnex_data: Audnex API response
        mediainfo_data: MediaInfo JSON (optional)
        asin: ASIN override (uses audnex_data.asin if not provided)
        audnex_chapters: Audnex chapters API response (preferred over mediainfo)

    Returns:
        Rendered BBCode description string
    """
    env = _get_jinja_env()
    template = env.get_template("mam_description.j2")

    # Get settings for transliteration and naming config
    try:
        settings = get_settings()
        filters = settings.filters
        naming_config = settings.naming
    except Exception:
        filters = None
        naming_config = None

    # Extract and clean title from Audnex
    # Apply same filter_title() used for JSON title field for consistency
    raw_title = audnex_data.get("title", "Unknown Title")
    title = filter_title(raw_title, naming_config=naming_config, keep_volume=True)
    subtitle = audnex_data.get("subtitle")

    # Only add subtitle if it adds new info (not just "Series, Book N")
    # Skip if subtitle is like "Series Name, Book N" pattern
    # Also filter the subtitle before appending
    if subtitle:
        # Check if subtitle is just "Book N" or "Series, Book N" which is redundant
        subtitle_lower = subtitle.lower()
        is_book_pattern = ", book " in subtitle_lower or subtitle_lower.startswith("book ")
        # Also check if the core series name is already in the title
        if not is_book_pattern and subtitle not in title:
            # Filter the subtitle too (removes "Light Novel", etc.)
            cleaned_subtitle = filter_subtitle(
                subtitle,
                title=title,
                series=None,  # Don't have series context here
                naming_config=naming_config,
            )
            if cleaned_subtitle and cleaned_subtitle not in title:
                title = f"{title}: {cleaned_subtitle}"

    synopsis = _html_to_bbcode(audnex_data.get("summary", ""))

    authors_raw = audnex_data.get("authors", [])
    authors_filtered = filter_authors(authors_raw)

    # Also filter out translators detected from MediaInfo
    # (Audnex doesn't include "- translator" suffix, but MediaInfo does)
    mediainfo_translators = extract_translators_from_mediainfo(mediainfo_data)
    if mediainfo_translators:
        logger.debug(f"Filtering translators from MediaInfo: {mediainfo_translators}")
        authors_filtered = [
            a for a in authors_filtered if a.get("name", "") not in mediainfo_translators
        ]

    authors = [
        transliterate_text(a.get("name", ""), filters) for a in authors_filtered if a.get("name")
    ]
    narrators = [
        transliterate_text(n.get("name", ""), filters)
        for n in audnex_data.get("narrators", [])
        if n.get("name")
    ]

    # Translator detection (look for "translator" in author/narrator names or roles)
    # First check MediaInfo (more reliable), then fall back to Audnex author names
    translator = None
    if mediainfo_translators:
        translator = next(iter(mediainfo_translators))  # Use first translator found
    else:
        for author in authors_raw:
            name = author.get("name", "")
            if "translator" in name.lower():
                translator = name
                break

    publisher = audnex_data.get("publisherName", "")
    release_date = audnex_data.get("releaseDate", "")
    if release_date:
        # Format: 2025-11-25
        release_date = release_date[:10] if len(release_date) >= 10 else release_date

    genres = [g.get("name", "") for g in audnex_data.get("genres", []) if g.get("name")]
    language = audnex_data.get("language", "English")
    if language:
        language = language.capitalize()

    book_asin = asin or audnex_data.get("asin", "")

    # Audio info from MediaInfo
    audio_info = {}
    if mediainfo_data:
        audio_info = _extract_audio_info(mediainfo_data)

    # Chapters: prefer Audnex API data over mediainfo (Audnex is authoritative)
    chapters: list[Chapter] = []
    if audnex_chapters:
        chapters = _parse_chapters_from_audnex(audnex_chapters)
        logger.debug(f"Using {len(chapters)} chapters from Audnex API")
    elif mediainfo_data:
        chapters = _parse_chapters_from_mediainfo(mediainfo_data)
        logger.debug(f"Using {len(chapters)} chapters from mediainfo (Audnex not available)")

    # Get signature setting from config
    show_signature = True  # Default
    try:
        settings = get_settings()
        if settings.mam and settings.mam.description:
            show_signature = settings.mam.description.show_signature
    except Exception:
        pass  # Use default if config not available

    # Render template
    description = template.render(
        title=title,
        synopsis=synopsis,
        authors=authors or ["Unknown"],
        narrators=narrators or ["Unknown"],
        translator=translator,
        publisher=publisher,
        release_date=release_date,
        genres=genres or ["Audiobook"],
        language=language,
        asin=book_asin,
        container=audio_info.get("container", "M4B"),
        codec=audio_info.get("codec", "AAC LC"),
        sample_rate=audio_info.get("sample_rate", "44.1 kHz"),
        channels=audio_info.get("channels", "2"),
        duration_human=audio_info.get("duration_human", "Unknown"),
        chapters=chapters,
        show_signature=show_signature,
    )

    return str(description).strip()


# =============================================================================
# Audnex API
# =============================================================================


def _fetch_audnex_book_region(
    asin: str,
    region: str,
    base_url: str,
    timeout: int,
) -> dict[str, Any] | None:
    """
    Fetch book metadata from Audnex API for a specific region.

    Internal helper - use fetch_audnex_book() which handles region fallback.

    Args:
        asin: Audible ASIN (e.g., "B000SEI1RG")
        region: Region code (us, uk, au, ca, de, es, fr, in, it, jp)
        base_url: Audnex API base URL
        timeout: Request timeout in seconds

    Returns:
        Parsed JSON response or None if not found/error.

    Raises:
        CircuitOpenError: If Audnex API circuit breaker is open.
    """
    url = f"{base_url}/books/{asin}"
    params = {"region": region}

    logger.debug(f"Fetching Audnex metadata: {url} (region={region})")

    try:
        # Circuit breaker protects against cascading failures
        # Only network-level errors trip the breaker (not 404s which are normal)
        with audnex_breaker, httpx.Client(timeout=timeout, http2=True) as client:
            response = client.get(url, params=params)

            if response.status_code == 404:
                logger.debug(f"ASIN {asin} not found in region {region}")
                return None

            # 500 errors are common for region mismatches - treat as "not found"
            if response.status_code == 500:
                logger.debug(f"ASIN {asin} returned 500 for region {region} (likely not available)")
                return None

            response.raise_for_status()
            data: dict[str, Any] = response.json()

            # Validate response structure (warns but doesn't fail)
            try:
                from shelfr.schemas.audnex import validate_audnex_book

                validate_audnex_book(data)
            except Exception as validation_error:
                logger.warning(
                    f"Audnex book response validation warning for {asin}: {validation_error}"
                )

            return data

    except CircuitOpenError:
        # Re-raise circuit breaker errors - caller should handle
        raise

    except httpx.TimeoutException:
        # Network issue - warn since this may indicate a problem
        logger.warning(f"Timeout fetching Audnex metadata for {asin} (region={region})")
        return None

    except httpx.HTTPStatusError as e:
        # Distinguish between "not found" type errors and actual issues
        if e.response.status_code in (401, 403, 429):
            logger.warning(
                "Auth/rate limit error fetching book %s (region=%s): %s",
                asin,
                region,
                e.response.status_code,
            )
        else:
            logger.debug(f"HTTP error from Audnex for {asin} (region={region}): {e}")
        return None

    except Exception as e:
        # Catch-all for JSON decode errors, connection issues, etc.
        logger.warning(
            f"Unexpected error fetching Audnex metadata for {asin} (region={region}): {e}"
        )
        return None


def fetch_audnex_book(
    asin: str, region: str | None = None
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Fetch book metadata from Audnex API with region fallback.

    Tries configured regions in order until one succeeds. Some ASINs are
    region-specific (e.g., B0BN2HMHZ8 only exists in US region).

    Args:
        asin: Audible ASIN (e.g., "B000SEI1RG")
        region: Optional specific region to try (skips fallback if provided)

    Returns:
        Tuple of (parsed JSON response or None, region found in or None).
        The region is useful for ASIN normalization to a preferred region.
    """
    settings = get_settings()

    # If specific region requested, only try that one
    if region:
        data = _fetch_audnex_book_region(
            asin, region, settings.audnex.base_url, settings.audnex.timeout_seconds
        )
        if data:
            logger.info(f"Fetched Audnex metadata for ASIN: {asin} (region={region})")
            return data, region
        logger.warning(f"ASIN {asin} not found in region {region}")
        return None, None

    # Try each configured region in order
    regions = settings.audnex.regions
    for r in regions:
        data = _fetch_audnex_book_region(
            asin, r, settings.audnex.base_url, settings.audnex.timeout_seconds
        )
        if data:
            logger.info(f"Fetched Audnex metadata for ASIN: {asin} (region={r})")
            return data, r

    logger.warning(f"ASIN {asin} not found in any configured region: {regions}")
    return None, None


def fetch_audnex_author(asin: str, region: str | None = None) -> dict[str, Any] | None:
    """
    Fetch author metadata from Audnex API with region fallback.

    Args:
        asin: Author ASIN
        region: Optional specific region to try (skips fallback if provided)

    Returns:
        Parsed JSON response or None if not found.
    """
    settings = get_settings()

    def _try_region(r: str) -> dict[str, Any] | None:
        url = f"{settings.audnex.base_url}/authors/{asin}"
        params = {"region": r}

        logger.debug(f"Fetching Audnex author: {url} (region={r})")

        try:
            with httpx.Client(timeout=settings.audnex.timeout_seconds, http2=True) as client:
                response = client.get(url, params=params)

                if response.status_code in (404, 500):
                    # Expected "not found" - keep at debug level
                    logger.debug(f"Author ASIN {asin} not found in region {r}")
                    return None

                response.raise_for_status()
                data: dict[str, Any] = response.json()
                return data

        except httpx.TimeoutException:
            # Network issue - warn since this may indicate a problem
            logger.warning(f"Timeout fetching author metadata for {asin} (region={r})")
            return None

        except httpx.HTTPStatusError as e:
            # Distinguish between "not found" type errors and actual issues
            if e.response.status_code in (401, 403, 429):
                logger.warning(
                    "Auth/rate limit error fetching author %s (region=%s): %s",
                    asin,
                    r,
                    e.response.status_code,
                )
            else:
                logger.debug(f"HTTP error fetching author {asin} (region={r}): {e}")
            return None

        except Exception as e:
            # Catch-all for JSON decode errors, connection issues, etc.
            logger.warning(
                f"Unexpected error fetching author metadata for {asin} (region={r}): {e}"
            )
            return None

    # If specific region requested, only try that one
    if region:
        data = _try_region(region)
        if data:
            logger.info(f"Fetched Audnex author: {asin} (region={region})")
        return data

    # Try each configured region in order
    for r in settings.audnex.regions:
        data = _try_region(r)
        if data:
            logger.info(f"Fetched Audnex author: {asin} (region={r})")
            return data

    logger.warning(f"Author ASIN {asin} not found in any configured region")
    return None


def _fetch_audnex_chapters_region(
    asin: str,
    region: str,
    base_url: str,
    timeout: int,
) -> dict[str, Any] | None:
    """
    Fetch chapter data from Audnex API for a specific region.

    Internal helper - use fetch_audnex_chapters() which handles region fallback.

    Args:
        asin: Audible ASIN
        region: Region code
        base_url: Audnex API base URL
        timeout: Request timeout in seconds

    Returns:
        Parsed JSON response or None if not found/error.
    """
    url = f"{base_url}/books/{asin}/chapters"
    params = {"region": region}

    logger.debug(f"Fetching Audnex chapters: {url} (region={region})")

    try:
        with httpx.Client(timeout=timeout, http2=True) as client:
            response = client.get(url, params=params)

            if response.status_code == 404:
                logger.debug(f"Chapters for {asin} not found in region {region}")
                return None

            # 500 errors are common for region mismatches
            if response.status_code == 500:
                logger.debug(f"Chapters for {asin} returned 500 for region {region}")
                return None

            response.raise_for_status()
            data: dict[str, Any] = response.json()

            # Validate response structure (warns but doesn't fail)
            try:
                from shelfr.schemas.audnex import validate_audnex_chapters

                validate_audnex_chapters(data)
            except Exception as validation_error:
                logger.warning(
                    f"Audnex chapters response validation warning for {asin}: {validation_error}"
                )

            return data

    except httpx.TimeoutException:
        # Network issue - warn since this may indicate a problem
        logger.warning(f"Timeout fetching Audnex chapters for {asin} (region={region})")
        return None

    except httpx.HTTPStatusError as e:
        # Distinguish between "not found" type errors and actual issues
        if e.response.status_code in (401, 403, 429):
            logger.warning(
                "Auth/rate limit error fetching chapters %s (region=%s): %s",
                asin,
                region,
                e.response.status_code,
            )
        else:
            logger.debug(f"HTTP error from Audnex chapters for {asin} (region={region}): {e}")
        return None

    except Exception as e:
        # Catch-all for JSON decode errors, connection issues, etc.
        logger.warning(
            f"Unexpected error fetching Audnex chapters for {asin} (region={region}): {e}"
        )
        return None


def fetch_audnex_chapters(asin: str, region: str | None = None) -> dict[str, Any] | None:
    """
    Fetch chapter data from Audnex API with region fallback.

    Args:
        asin: Audible ASIN (e.g., "B000SEI1RG")
        region: Optional specific region to try (skips fallback if provided)

    Returns:
        Parsed JSON response with chapters or None if not found.
        Response includes: asin, brandIntroDurationMs, brandOutroDurationMs,
        chapters (list with lengthMs, startOffsetMs, startOffsetSec, title),
        runtimeLengthMs, runtimeLengthSec
    """
    settings = get_settings()

    # If specific region requested, only try that one
    if region:
        data = _fetch_audnex_chapters_region(
            asin, region, settings.audnex.base_url, settings.audnex.timeout_seconds
        )
        if data:
            chapter_count = len(data.get("chapters", []))
            logger.info(
                f"Fetched {chapter_count} chapters from Audnex for ASIN: {asin} (region={region})"
            )
        return data

    # Try each configured region in order
    regions = settings.audnex.regions
    for r in regions:
        data = _fetch_audnex_chapters_region(
            asin, r, settings.audnex.base_url, settings.audnex.timeout_seconds
        )
        if data:
            chapter_count = len(data.get("chapters", []))
            logger.info(
                f"Fetched {chapter_count} chapters from Audnex for ASIN: {asin} (region={r})"
            )
            return data

    logger.warning(f"Chapters for ASIN {asin} not found in any configured region")
    return None


def _parse_chapters_from_audnex(chapters_data: dict[str, Any]) -> list[Chapter]:
    """
    Convert Audnex chapters API response to list of Chapter objects.

    Args:
        chapters_data: Audnex chapters API response

    Returns:
        List of Chapter objects with formatted timestamps
    """
    chapters: list[Chapter] = []

    try:
        raw_chapters = chapters_data.get("chapters", [])
        for ch in raw_chapters:
            start_seconds = ch.get("startOffsetSec", 0)
            title = ch.get("title", "")
            if title:
                chapters.append(
                    Chapter(
                        start=_format_chapter_time(float(start_seconds)),
                        title=title,
                    )
                )
    except Exception as e:
        logger.warning(f"Failed to parse chapters from Audnex: {e}")

    return chapters


def save_audnex_json(data: dict[str, Any], output_path: Path) -> None:
    """Write Audnex metadata to JSON file."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.debug(f"Saved Audnex metadata to: {output_path}")


# =============================================================================
# MediaInfo
# =============================================================================


@retry_with_backoff(
    max_attempts=3,
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
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.debug(f"Saved MediaInfo to: {output_path}")


# =============================================================================
# Combined Operations
# =============================================================================


def fetch_metadata(
    asin: str | None = None,
    m4b_path: Path | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    """
    Fetch Audnex book metadata, chapters, and MediaInfo without saving.

    Args:
        asin: Audible ASIN (None to skip Audnex)
        m4b_path: Path to m4b file (None to skip MediaInfo)

    Returns:
        Tuple of (audnex_data, mediainfo_data, audnex_chapters), any may be None on error.
    """
    audnex_data = None
    mediainfo_data = None
    audnex_chapters = None

    if asin:
        audnex_data, _ = fetch_audnex_book(asin)  # Region not needed here
        # Also fetch chapter data from Audnex (authoritative source)
        audnex_chapters = fetch_audnex_chapters(asin)

    if m4b_path and m4b_path.exists():
        mediainfo_data = run_mediainfo(m4b_path)

    return audnex_data, mediainfo_data, audnex_chapters


def save_metadata_files(
    output_dir: Path,
    audnex_data: dict[str, Any] | None = None,
    mediainfo_data: dict[str, Any] | None = None,
) -> None:
    """
    Save metadata to JSON files in output directory.

    Args:
        output_dir: Directory to save JSON files
        audnex_data: Audnex data to save (skipped if None)
        mediainfo_data: MediaInfo data to save (skipped if None)
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if audnex_data:
        save_audnex_json(audnex_data, output_dir / "audnex.json")

    if mediainfo_data:
        save_mediainfo_json(mediainfo_data, output_dir / "mediainfo.json")


def fetch_all_metadata(
    asin: str | None,
    m4b_path: Path | None,
    output_dir: Path | None = None,
    *,
    save_intermediate: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    """
    Fetch Audnex book data, chapters, and MediaInfo, optionally saving intermediate files.

    By default, this function only fetches metadata without saving files.
    Set save_intermediate=True to write audnex.json and mediainfo.json to output_dir.

    Args:
        asin: Audible ASIN (None to skip Audnex)
        m4b_path: Path to m4b file (None to skip MediaInfo)
        output_dir: Directory to save JSON files (only used if save_intermediate=True)
        save_intermediate: If True, save audnex.json and mediainfo.json files

    Returns:
        Tuple of (audnex_data, mediainfo_data, audnex_chapters), any may be None on error.
    """
    audnex_data, mediainfo_data, audnex_chapters = fetch_metadata(asin=asin, m4b_path=m4b_path)

    if save_intermediate and output_dir:
        save_metadata_files(output_dir, audnex_data=audnex_data, mediainfo_data=mediainfo_data)

    return audnex_data, mediainfo_data, audnex_chapters


# =============================================================================
# MAM JSON Export
# =============================================================================

# Genre keywords that indicate Fiction (case-insensitive matching)
FICTION_GENRE_KEYWORDS = frozenset(
    [
        "fantasy",
        "fiction",
        "mystery",
        "thriller",
        "suspense",
        "romance",
        "horror",
        "sci-fi",
        "science fiction",
        "adventure",
        "detective",
        "crime",
        "western",
        "humor",
        "comedy",
        "drama",
        "erotica",
        "paranormal",
        "urban",
        "epic",
        "literary",
        "classics",
        "historical fiction",
        "contemporary",
        "dystopian",
        "fairy tales",
        "mythology",
        "legends",
        "anthologies",
        "short stories",
    ]
)

# Genre keywords that indicate Non-Fiction (case-insensitive matching)
NONFICTION_GENRE_KEYWORDS = frozenset(
    [
        "biography",
        "biographies",
        "memoir",
        "self-help",
        "business",
        "history",
        "science",
        "politics",
        "religion",
        "spirituality",
        "philosophy",
        "psychology",
        "health",
        "fitness",
        "cooking",
        "travel",
        "true crime",
        "education",
        "reference",
        "how-to",
        "guide",
        "self development",
        "personal development",
        "finance",
        "economics",
        "journalism",
        "essays",
        "nature",
        "technology",
        "computers",
    ]
)


def _infer_fiction_or_nonfiction(audnex_data: dict[str, Any]) -> int:
    """
    Infer whether a book is Fiction (1) or Non-Fiction (2).

    Audnex literatureType is unreliable, so we check genres first.
    Fiction keywords take priority since genre keywords like "fantasy"
    are unambiguous, while non-fiction keywords may appear in fiction
    (e.g., "historical fiction").

    Args:
        audnex_data: Audnex API response

    Returns:
        1 for Fiction, 2 for Non-Fiction
    """
    genres = audnex_data.get("genres", [])
    genre_names_lower = [g.get("name", "").lower() for g in genres]
    all_genre_text = " ".join(genre_names_lower)

    # Check for fiction indicators first (higher priority)
    # Use word boundary matching to avoid false positives (e.g., "urban" in "Suburban")
    for keyword in FICTION_GENRE_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", all_genre_text):
            return 1  # Fiction

    # Check for non-fiction indicators
    for keyword in NONFICTION_GENRE_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", all_genre_text):
            return 2  # Non-Fiction

    # Fallback to literatureType if genres don't give a clear signal
    lit_type = audnex_data.get("literatureType", "").lower()
    if lit_type == "fiction":
        return 1
    if lit_type in ("non-fiction", "nonfiction"):
        return 2

    # Default to Fiction (most audiobooks are fiction)
    return 1


def _get_audiobook_category(audnex_data: dict[str, Any], is_fiction: bool) -> str:
    """
    Determine the MAM audiobook category string from genres.

    Uses config/audiobook_categories.json mappings. Checks genre keywords
    against the appropriate map (fiction or nonfiction) and returns the
    first match. Falls back to default category if no match found.

    Note: Order of keywords in the JSON file matters (first match wins).
    This relies on Python 3.7+ dict insertion order preservation.
    More specific keywords (e.g., "urban fantasy") should appear before
    general ones (e.g., "fantasy") in the JSON file.

    Args:
        audnex_data: Audnex API response
        is_fiction: Whether the book is fiction (from _infer_fiction_or_nonfiction)

    Returns:
        MAM audiobook category string (e.g., "Audiobooks - Fantasy")
    """
    # Default fallback
    default_category = (
        "Audiobooks - General Fiction" if is_fiction else "Audiobooks - General Non-Fic"
    )

    try:
        settings = get_settings()
        categories = settings.categories
    except Exception:
        return default_category

    # Select the appropriate map based on fiction/nonfiction
    if is_fiction:
        category_map = categories.audiobook_fiction_map
        default_key = "fiction"
    else:
        category_map = categories.audiobook_nonfiction_map
        default_key = "nonfiction"

    # Get default from config
    default_category = categories.audiobook_defaults.get(default_key, default_category)

    # If no map loaded, return default
    if not category_map:
        return default_category

    # Build genre text for matching
    genres = audnex_data.get("genres", [])
    genre_names_lower = [g.get("name", "").lower() for g in genres]
    all_genre_text = " ".join(genre_names_lower)

    # Check each keyword in the map (order matters - first match wins)
    # Use word boundary matching to avoid false positives (e.g., "art" in "martial")
    for keyword, category in category_map.items():
        if re.search(rf"\b{re.escape(keyword)}\b", all_genre_text):
            return category

    return default_category


def _map_genres_to_categories(genres: list[dict[str, Any]]) -> list[int]:
    """
    Map Audnex genres to MAM category IDs.

    Handles compound genres like "Science Fiction & Fantasy" by:
    1. First trying exact match for the full compound string
    2. Then splitting on " & " and ", " to match individual components

    Args:
        genres: List of genre dicts from Audnex (with 'name' key)

    Returns:
        List of unique MAM category IDs
    """
    try:
        settings = get_settings()
        category_map = settings.categories.genre_map
    except Exception:
        return []

    categories: set[int] = set()

    for genre in genres:
        name = genre.get("name", "").lower().strip()
        if not name:
            continue

        # First try exact match for the full string
        if name in category_map:
            categories.add(category_map[name])
            continue

        # Split compound genres on " & " and ", " to match individual parts
        # e.g., "Science Fiction & Fantasy" -> ["science fiction", "fantasy"]
        # e.g., "Literature & Fiction, Fantasy" -> ["literature", "fiction", "fantasy"]
        parts = []
        for part in name.replace(" & ", ", ").split(", "):
            part = part.strip()
            if part:
                parts.append(part)

        # Try to match each part
        matched = False
        for part in parts:
            if part in category_map:
                categories.add(category_map[part])
                matched = True

        # Fallback: partial matching if no parts matched
        if not matched:
            for key, cat_id in category_map.items():
                if key in name or name in key:
                    categories.add(cat_id)
                    break

    return sorted(categories)


def _build_series_list(
    audnex_data: dict[str, Any],
    naming_config: Any = None,
) -> list[dict[str, Any]]:
    """
    Build series list for MAM JSON from Audnex data.

    Applies filter_series to clean series names (removes format indicators,
    series suffixes like " Series", " Trilogy", "[publication order]", etc.)

    Deduplicates series that become identical after cleaning (e.g., when
    seriesPrimary="Ascend Online [publication order]" and
    seriesSecondary="Ascend Online [chronological order]" both clean to
    "Ascend Online"). Primary series takes precedence.

    Args:
        audnex_data: Audnex book metadata
        naming_config: NamingConfig for cleaning rules (optional)

    Returns:
        List of series dicts with 'name' and 'number' keys (deduplicated)
    """
    series_list: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    # Primary series (takes precedence)
    primary = audnex_data.get("seriesPrimary")
    if primary:
        name = primary.get("name", "")
        if name:
            cleaned_name = filter_series(name, naming_config=naming_config)
            if cleaned_name:
                seen_names.add(cleaned_name.lower())
                series_list.append(
                    {
                        "name": cleaned_name,
                        "number": primary.get("position", ""),
                    }
                )

    # Secondary series (if any, skip if duplicate of primary after cleaning)
    secondary = audnex_data.get("seriesSecondary")
    if secondary:
        name = secondary.get("name", "")
        if name:
            cleaned_name = filter_series(name, naming_config=naming_config)
            # Only add if distinct from primary (case-insensitive)
            if cleaned_name and cleaned_name.lower() not in seen_names:
                series_list.append(
                    {
                        "name": cleaned_name,
                        "number": secondary.get("position", ""),
                    }
                )

    return series_list


def _html_to_bbcode(text: str) -> str:
    """
    Convert HTML tags to BBCode for MAM description.

    Supported MAM BBCode tags:
    - [b], [i], [u], [s] - Basic formatting
    - [size=N], [font=], [color=] - Font styling
    - [url], [url=], [img] - Links and images
    - [center], [sup], [sub] - Layout
    - [br] - Line breaks

    Converts:
    - <b>, <strong> → [b], [/b]
    - <i>, <em> → [i], [/i]
    - <u> → [u], [/u]
    - <s>, <strike> → [s], [/s]
    - </p> → [br][br] (paragraph break)
    - <br> → [br] (line break)

    MAM requires explicit [br] tags for line breaks - plain newlines
    in the JSON are ignored by their BBCode renderer.

    Also decodes HTML entities.
    """
    # Convert bold tags to BBCode
    text = re.sub(r"<b\b[^>]*>", "[b]", text, flags=re.IGNORECASE)
    text = re.sub(r"</b>", "[/b]", text, flags=re.IGNORECASE)
    text = re.sub(r"<strong\b[^>]*>", "[b]", text, flags=re.IGNORECASE)
    text = re.sub(r"</strong>", "[/b]", text, flags=re.IGNORECASE)

    # Convert italic tags to BBCode
    text = re.sub(r"<i\b[^>]*>", "[i]", text, flags=re.IGNORECASE)
    text = re.sub(r"</i>", "[/i]", text, flags=re.IGNORECASE)
    text = re.sub(r"<em\b[^>]*>", "[i]", text, flags=re.IGNORECASE)
    text = re.sub(r"</em>", "[/i]", text, flags=re.IGNORECASE)

    # Convert underline tags to BBCode
    text = re.sub(r"<u\b[^>]*>", "[u]", text, flags=re.IGNORECASE)
    text = re.sub(r"</u>", "[/u]", text, flags=re.IGNORECASE)

    # Convert strikethrough tags to BBCode
    text = re.sub(r"<s\b[^>]*>", "[s]", text, flags=re.IGNORECASE)
    text = re.sub(r"</s>", "[/s]", text, flags=re.IGNORECASE)
    text = re.sub(r"<strike\b[^>]*>", "[s]", text, flags=re.IGNORECASE)
    text = re.sub(r"</strike>", "[/s]", text, flags=re.IGNORECASE)

    # Convert paragraph breaks to [br][br] for MAM
    # Handle both </p> and <p> as paragraph boundaries
    text = re.sub(r"</p>\s*", "[br][br]", text, flags=re.IGNORECASE)
    text = re.sub(r"<p[^>]*>", "", text, flags=re.IGNORECASE)

    # Convert <br> tags to [br]
    text = re.sub(r"<br\s*/?>", "[br]", text, flags=re.IGNORECASE)

    # Remove any remaining HTML tags (that we don't support)
    text = re.sub(r"<[^>]+>", "", text)

    # Decode HTML entities (handles &amp;, &lt;, &#39;, etc.)
    text = html.unescape(text)

    # Clean up excessive whitespace
    text = re.sub(r"[ \t]+", " ", text)  # Collapse horizontal whitespace
    text = re.sub(r"(\[br\]){3,}", "[br][br]", text)  # Max 2 [br] tags
    return text.strip()


def _clean_html(text: str) -> str:
    """
    Clean HTML tags from description text (strips all formatting).

    DEPRECATED: Use _html_to_bbcode() for MAM descriptions to preserve formatting.

    Converts HTML paragraphs to newlines, strips remaining tags,
    and decodes HTML entities.
    """
    # Convert paragraph breaks to double newlines (before stripping tags)
    # Handle both </p> and <p> as paragraph boundaries
    text = re.sub(r"</p>\s*", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<p[^>]*>", "", text, flags=re.IGNORECASE)
    # Convert <br> tags to single newlines
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    # Remove remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Decode HTML entities (handles &amp;, &lt;, &#39;, etc.)
    text = html.unescape(text)
    # Clean up excessive whitespace while preserving intentional newlines
    text = re.sub(r"[ \t]+", " ", text)  # Collapse horizontal whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)  # Max 2 newlines (1 blank line)
    return text.strip()


def _get_mediainfo_string(mediainfo_data: dict[str, Any] | None) -> str | None:
    """
    Convert mediainfo JSON to a string for MAM.

    MAM expects the mediainfo JSON as a string in the mediaInfo field.
    """
    if not mediainfo_data:
        return None
    return json.dumps(mediainfo_data, ensure_ascii=False)


def build_mam_json(
    release: AudiobookRelease,
    audnex_data: dict[str, Any] | None = None,
    mediainfo_data: dict[str, Any] | None = None,
    audnex_chapters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build MAM fast-fillout JSON from release metadata.

    Args:
        release: AudiobookRelease object with metadata
        audnex_data: Optional Audnex API response (uses release.audnex_metadata if None)
        mediainfo_data: Optional MediaInfo JSON (uses release.mediainfo_data if None)
        audnex_chapters: Optional Audnex chapters API response (for accurate chapter data)

    Returns:
        Dict ready to be serialized as MAM JSON
    """
    # Use release metadata if not provided
    audnex = audnex_data or release.audnex_metadata or {}
    mediainfo = mediainfo_data or release.mediainfo_data

    mam_json: dict[str, Any] = {}

    # Get settings for transliteration and naming config
    try:
        settings = get_settings()
        filters = settings.filters
        naming_config = settings.naming
    except Exception:
        filters = None
        naming_config = None

    # Normalize Audnex data first to fix title/subtitle swaps
    # This uses seriesPrimary as the source of truth
    # Default to enabled if no config available
    normalized: NormalizedBook | None = None
    should_normalize = (
        naming_config.normalize_title_subtitle
        if naming_config is not None
        else True  # Default to enabled
    )
    if audnex and should_normalize:
        normalized = normalize_audnex_book(audnex)

    # Title - use normalized title if available, else Audnex title or fallback to release title
    # Apply filter_title to remove format indicators, genre tags, etc.
    # keep_volume=True to preserve "Vol. X" for human-readable JSON
    cleaned_title: str | None = None
    title = normalized.display_title if normalized else audnex.get("title") or release.title
    if title:
        cleaned_title = filter_title(
            title,
            naming_config=naming_config,
            keep_volume=True,
        )
        mam_json["title"] = cleaned_title

    # Authors (filter out translators, illustrators, etc. and transliterate Japanese names)
    authors = audnex.get("authors", [])
    if authors:
        filtered_authors = filter_authors(authors)
        # Also filter out translators detected from MediaInfo
        mediainfo_translators = extract_translators_from_mediainfo(mediainfo)
        if mediainfo_translators:
            logger.debug(
                f"Filtering translators from MediaInfo in MAM JSON: {mediainfo_translators}"
            )
            filtered_authors = [
                a for a in filtered_authors if a.get("name", "") not in mediainfo_translators
            ]
        author_names = [a.get("name", "") for a in filtered_authors if a.get("name")]
        # Transliterate Japanese/foreign names
        mam_json["authors"] = [transliterate_text(name, filters) for name in author_names]
    elif release.author:
        mam_json["authors"] = [transliterate_text(release.author, filters)]

    # Narrators (also transliterate)
    narrators = audnex.get("narrators", [])
    if narrators:
        narrator_names = [n.get("name", "") for n in narrators if n.get("name")]
        mam_json["narrators"] = [transliterate_text(name, filters) for name in narrator_names]
    elif release.narrator:
        mam_json["narrators"] = [transliterate_text(release.narrator, filters)]

    # Description - render BBCode using Jinja2 template
    if audnex:
        bbcode_description = render_bbcode_description(
            audnex_data=audnex,
            mediainfo_data=mediainfo,
            asin=release.asin,
            audnex_chapters=audnex_chapters,
        )
        if bbcode_description:
            mam_json["description"] = bbcode_description

    # Series - resolve from multiple sources with smart fallback and gap-filling
    # Priority:
    #   1) Normalized book (from swap detection) + secondary series from Audnex
    #   2) Audnex via _build_series_list (preserves primary + secondary series)
    #   3) resolve_series() fallback (Libation path → Title heuristics)
    #
    # Key principle: resolve_series() is an ENHANCER, not a bulldozer.
    # It fills gaps (missing position) but doesn't overwrite existing multi-series data.
    series_entries: list[dict[str, str]] = []
    cleaned_series: str | None = None  # For subtitle filtering

    # Step 1: Try normalized book (from swap detection)
    if normalized and normalized.series_name:
        cleaned_series = filter_series(
            normalized.series_name,
            naming_config=naming_config,
        )
        series_number = (
            normalized.series_position
            or release.series_position
            or (
                str(audnex.get("seriesPrimary", {}).get("position"))
                if audnex.get("seriesPrimary")
                else ""
            )
        )
        series_entries = [
            {
                "name": cleaned_series,
                "number": series_number,
            }
        ]
        # Also add secondary series if present (normalized only handles primary)
        # but skip if it's a duplicate after cleaning (e.g., chronological vs publication order)
        secondary = audnex.get("seriesSecondary")
        if secondary and secondary.get("name"):
            secondary_name = filter_series(secondary.get("name", ""), naming_config=naming_config)
            # Only add if distinct from primary (case-insensitive)
            if secondary_name and secondary_name.lower() != cleaned_series.lower():
                series_entries.append(
                    {
                        "name": secondary_name,
                        "number": secondary.get("position", ""),
                    }
                )
        logger.debug(
            "Series from normalized book: %s",
            [s.get("name") for s in series_entries],
        )
    else:
        # Step 2: Try _build_series_list() to preserve primary + secondary series
        series_list = _build_series_list(audnex, naming_config=naming_config)
        if series_list:
            series_entries = series_list
            cleaned_series = series_list[0].get("name")
            logger.debug(
                "Series from Audnex (primary + secondary): %s",
                [s.get("name") for s in series_list],
            )

    # Step 3: Use resolve_series() as enhancer or fallback
    # - If no series yet: use as primary source (Libation → Title heuristics)
    # - If we have exactly one series with missing info: fill gaps
    title_for_heuristic = cleaned_title or audnex.get("title") or release.title
    series_info = resolve_series(
        audnex_data=audnex,
        libation_path=release.source_dir,
        title=title_for_heuristic,
    )

    if series_info:
        resolved_name = filter_series(
            series_info.name,
            naming_config=naming_config,
        )
        # Always use resolved name for subtitle filtering (it's the cleaned version)
        cleaned_series = resolved_name

        if not series_entries:
            # No series yet → use resolver as primary source
            series_entries = [
                {
                    "name": resolved_name,
                    "number": series_info.position or "",
                }
            ]
            logger.debug(
                "Series from %s (confidence=%.1f): %s #%s",
                series_info.source.value,
                series_info.confidence,
                resolved_name,
                series_info.position or "N/A",
            )
        elif len(series_entries) == 1:
            # We have one series entry; let resolver fill gaps but not overwrite
            entry = series_entries[0]
            if not entry.get("name"):
                entry["name"] = resolved_name
            if not entry.get("number") and series_info.position:
                entry["number"] = series_info.position
                logger.debug(
                    "Filled series position from %s: %s #%s",
                    series_info.source.value,
                    entry.get("name"),
                    series_info.position,
                )
        # else: multiple series entries from Audnex - don't touch them

    # Step 4: Last-ditch fallback - release.series (only if still nothing)
    if not series_entries and release.series:
        cleaned_series = filter_series(
            release.series,
            naming_config=naming_config,
        )
        series_entries = [
            {
                "name": cleaned_series,
                "number": release.series_position or "",
            }
        ]
        logger.debug(
            "Series from release fallback: %s #%s",
            cleaned_series,
            release.series_position or "N/A",
        )

    # Commit series to MAM JSON
    if series_entries:
        mam_json["series"] = series_entries

    # Subtitle - use normalized arc_name (from swap detection) or filter raw subtitle
    # Arc name is the meaningful subtitle (e.g., "Alicization Exploding", "Mother's Rosary")
    if normalized and normalized.arc_name:
        # Use arc name directly as subtitle (it's already the "good" part)
        cleaned_subtitle = filter_subtitle(
            normalized.arc_name,
            title=cleaned_title,
            series=cleaned_series if mam_json.get("series") else None,
            naming_config=naming_config,
        )
        if cleaned_subtitle:
            mam_json["subtitle"] = cleaned_subtitle
    else:
        # Fallback: apply filter_subtitle with full redundancy checking
        subtitle = audnex.get("subtitle")
        if subtitle:
            cleaned_subtitle = filter_subtitle(
                subtitle,
                title=cleaned_title,
                series=cleaned_series if mam_json.get("series") else None,
                naming_config=naming_config,
            )
            if cleaned_subtitle:  # Only add if non-empty after cleaning
                mam_json["subtitle"] = cleaned_subtitle

    # Thumbnail (cover image URL)
    image = audnex.get("image")
    if image:
        mam_json["thumbnail"] = image

    # Language
    language = audnex.get("language")
    if language:
        # Capitalize first letter
        mam_json["language"] = language.capitalize()

    # Categories - map genres to MAM category IDs
    genres = audnex.get("genres", [])
    if genres:
        categories = _map_genres_to_categories(genres)
        if categories:
            mam_json["categories"] = categories

    # Media type - always Audiobook (1)
    mam_json["mediaType"] = 1

    # Tags - build audio info string
    # Format: Length: Xh Xm | Release date: MM-DD-YY | Format: M4B, codec | Chapterized |
    tag_parts = []

    # Get audio info from mediainfo
    if mediainfo:
        audio_info = _extract_audio_info(mediainfo)
        chapters = _parse_chapters_from_mediainfo(mediainfo)

        # Length
        duration = audio_info.get("duration_human", "")
        if duration and duration != "Unknown":
            tag_parts.append(f"Length: {duration}")

        # Release date from Audnex
        release_date = audnex.get("releaseDate", "")
        if release_date:
            # Convert 2025-11-25 to 11-25-25
            try:
                parts = release_date[:10].split("-")
                if len(parts) == 3:
                    tag_parts.append(f"Release date: {parts[1]}-{parts[2]}-{parts[0][2:]}")
            except (IndexError, ValueError):
                pass

        # Format
        container = audio_info.get("container", "M4B")
        codec = audio_info.get("codec", "AAC LC")
        tag_parts.append(f"Format: {container}, {codec}")

        # Chapterized
        if chapters:
            tag_parts.append("Chapterized")

    mam_json["tags"] = " | ".join(tag_parts) + " |" if tag_parts else ""

    # MediaInfo - as JSON string
    mediainfo_str = _get_mediainfo_string(mediainfo)
    if mediainfo_str:
        mam_json["mediaInfo"] = mediainfo_str

    # ISBN - use ASIN format for audiobooks: ASIN:<asin>
    asin = release.asin or audnex.get("asin", "")
    if asin:
        mam_json["isbn"] = f"ASIN:{asin}"

    # Flags
    flags = []
    if audnex.get("isAdult"):
        flags.append("eSex")
    format_type = audnex.get("formatType", "").lower()
    if format_type == "abridged":
        flags.append("abridged")
    if flags:
        mam_json["flags"] = flags

    # Main category (Fiction=1, Non-Fiction=2)
    # Audnex literatureType is unreliable, so we infer from genres first
    main_cat = _infer_fiction_or_nonfiction(audnex)
    mam_json["main_cat"] = main_cat

    # Category string (e.g., "Audiobooks - Fantasy")
    # Uses audiobook_categories.json mapping based on genres
    is_fiction = main_cat == 1
    mam_json["category"] = _get_audiobook_category(audnex, is_fiction)

    return mam_json


def save_mam_json(
    mam_data: dict[str, Any],
    output_path: Path,
) -> None:
    """
    Write MAM JSON to file.

    Args:
        mam_data: MAM JSON dict
        output_path: Where to write the JSON file
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(mam_data, f, indent=2, ensure_ascii=False)

    # Fix ownership to target UID:GID (e.g., Unraid's nobody:users)
    # This ensures JSON files have same permissions as torrent files
    settings = get_settings()
    fix_ownership(output_path, settings.target_uid, settings.target_gid)

    logger.info(f"Saved MAM JSON: {output_path}")


def generate_mam_json_for_release(
    release: AudiobookRelease,
    output_dir: Path | None = None,
) -> Path | None:
    """
    Generate MAM JSON file for a release.

    Uses release.audnex_metadata, release.mediainfo_data, and release.audnex_chapters
    if available, or fetches them if not.

    Args:
        release: AudiobookRelease with metadata populated
        output_dir: Directory to write JSON (defaults to torrent_output from config)

    Returns:
        Path to generated JSON file, or None on failure
    """
    settings = get_settings()

    # Determine output directory
    if output_dir is None:
        output_dir = settings.paths.torrent_output

    # Ensure output directory exists (may be per-release subfolder)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Build filename: same as torrent but .json extension
    # Format: "Author - Title.json"
    if release.staging_dir:
        json_name = f"{release.staging_dir.name}.json"
    else:
        json_name = f"{release.display_name}.json"

    output_path = Path(output_dir) / json_name

    # Build and save (pass audnex_chapters from release if available)
    mam_data = build_mam_json(release, audnex_chapters=release.audnex_chapters)

    if not mam_data.get("title"):
        logger.warning(f"No title for MAM JSON: {release.display_name}")
        return None

    save_mam_json(mam_data, output_path)
    return output_path
