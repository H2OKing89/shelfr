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

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from jinja2 import Environment, PackageLoader

from mamfast.config import get_settings
from mamfast.utils.naming import filter_authors

if TYPE_CHECKING:
    from mamfast.models import AudiobookRelease

logger = logging.getLogger(__name__)


# =============================================================================
# BBCode Description Template
# =============================================================================


@dataclass
class Chapter:
    """Chapter info for BBCode template."""

    start: str  # "00:55:52" or "1:30:45"
    title: str  # "Chapter 2: Wandering Goblin Slayer"


def _get_jinja_env() -> Environment:
    """Get Jinja2 environment with template loader."""
    return Environment(
        loader=PackageLoader("mamfast", "templates"),
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
) -> str:
    """
    Render BBCode description from Audnex and MediaInfo data.

    Uses Jinja2 template for the formatting.

    Args:
        audnex_data: Audnex API response
        mediainfo_data: MediaInfo JSON (optional)
        asin: ASIN override (uses audnex_data.asin if not provided)

    Returns:
        Rendered BBCode description string
    """
    env = _get_jinja_env()
    template = env.get_template("mam_description.j2")

    # Extract data from Audnex
    title = audnex_data.get("title", "Unknown Title")
    subtitle = audnex_data.get("subtitle")

    # Only add subtitle if it adds new info (not just "Series, Book N")
    # Skip if subtitle is like "Series Name, Book N" pattern
    if subtitle:
        # Check if subtitle is just "Book N" or "Series, Book N" which is redundant
        subtitle_lower = subtitle.lower()
        is_book_pattern = ", book " in subtitle_lower or subtitle_lower.startswith("book ")
        # Also check if the core series name is already in the title
        if not is_book_pattern and subtitle not in title:
            title = f"{title}: {subtitle}"

    synopsis = _clean_html(audnex_data.get("summary", ""))

    authors_raw = audnex_data.get("authors", [])
    authors_filtered = filter_authors(authors_raw)
    authors = [a.get("name", "") for a in authors_filtered if a.get("name")]
    narrators = [n.get("name", "") for n in audnex_data.get("narrators", []) if n.get("name")]

    # Translator detection (look for "translator" in author/narrator names or roles)
    translator = None
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
    chapters: list[Chapter] = []
    if mediainfo_data:
        audio_info = _extract_audio_info(mediainfo_data)
        chapters = _parse_chapters_from_mediainfo(mediainfo_data)

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
    )

    return str(description).strip()


# =============================================================================
# Audnex API
# =============================================================================


def fetch_audnex_book(asin: str) -> dict[str, Any] | None:
    """
    Fetch book metadata from Audnex API.

    Args:
        asin: Audible ASIN (e.g., "B000SEI1RG")

    Returns:
        Parsed JSON response or None if not found.
    """
    settings = get_settings()
    url = f"{settings.audnex.base_url}/books/{asin}"

    logger.debug(f"Fetching Audnex metadata: {url}")

    try:
        with httpx.Client(timeout=settings.audnex.timeout_seconds) as client:
            response = client.get(url)

            if response.status_code == 404:
                logger.warning(f"ASIN not found in Audnex: {asin}")
                return None

            response.raise_for_status()
            data: dict[str, Any] = response.json()

            logger.info(f"Fetched Audnex metadata for ASIN: {asin}")
            return data

    except httpx.TimeoutException:
        logger.error(f"Timeout fetching Audnex metadata for: {asin}")
        return None

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error from Audnex: {e}")
        return None

    except Exception as e:
        logger.exception(f"Error fetching Audnex metadata: {e}")
        return None


def fetch_audnex_author(asin: str) -> dict[str, Any] | None:
    """
    Fetch author metadata from Audnex API.

    Args:
        asin: Author ASIN

    Returns:
        Parsed JSON response or None if not found.
    """
    settings = get_settings()
    url = f"{settings.audnex.base_url}/authors/{asin}"

    logger.debug(f"Fetching Audnex author: {url}")

    try:
        with httpx.Client(timeout=settings.audnex.timeout_seconds) as client:
            response = client.get(url)

            if response.status_code == 404:
                logger.warning(f"Author ASIN not found: {asin}")
                return None

            response.raise_for_status()
            data: dict[str, Any] = response.json()
            return data

    except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
        logger.warning(f"Error fetching author metadata: {e}")
        return None


def save_audnex_json(data: dict[str, Any], output_path: Path) -> None:
    """Write Audnex metadata to JSON file."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.debug(f"Saved Audnex metadata to: {output_path}")


# =============================================================================
# MediaInfo
# =============================================================================


def run_mediainfo(file_path: Path) -> dict[str, Any] | None:
    """
    Run mediainfo on a file and return parsed JSON output.

    Args:
        file_path: Path to audio file (typically .m4b)

    Returns:
        Parsed MediaInfo JSON or None on error.
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
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )

        data: dict[str, Any] = json.loads(result.stdout)
        logger.info(f"Got MediaInfo for: {file_path.name}")
        return data

    except FileNotFoundError:
        logger.error(f"mediainfo binary not found: {binary}")
        return None

    except subprocess.CalledProcessError as e:
        logger.error(f"mediainfo failed: {e.stderr}")
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


def fetch_all_metadata(
    asin: str | None,
    m4b_path: Path | None,
    output_dir: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """
    Fetch both Audnex and MediaInfo metadata, saving to output directory.

    Args:
        asin: Audible ASIN (None to skip Audnex)
        m4b_path: Path to m4b file (None to skip MediaInfo)
        output_dir: Directory to save JSON files

    Returns:
        Tuple of (audnex_data, mediainfo_data), either may be None.
    """
    audnex_data = None
    mediainfo_data = None

    output_dir.mkdir(parents=True, exist_ok=True)

    # Audnex
    if asin:
        audnex_data = fetch_audnex_book(asin)
        if audnex_data:
            save_audnex_json(audnex_data, output_dir / "audnex.json")

    # MediaInfo
    if m4b_path and m4b_path.exists():
        mediainfo_data = run_mediainfo(m4b_path)
        if mediainfo_data:
            save_mediainfo_json(mediainfo_data, output_dir / "mediainfo.json")

    return audnex_data, mediainfo_data


# =============================================================================
# MAM JSON Export
# =============================================================================

# MAM category mapping based on Audnex genres
MAM_CATEGORY_MAP: dict[str, int] = {
    # Fiction categories
    "action & adventure": 1,
    "art": 2,
    "biography": 3,
    "business": 4,
    "comedy": 5,
    "computer": 7,
    "contemporary": 59,
    "crime": 9,
    "drama": 60,
    "education": 11,
    "fantasy": 13,
    "food": 14,
    "health": 16,
    "historical": 17,
    "horror": 19,
    "humor": 20,
    "juvenile": 23,
    "language": 24,
    "lgbtq": 25,
    "literary classics": 28,
    "literary fiction": 57,
    "litrpg": 29,
    "math": 30,
    "medicine": 31,
    "music": 32,
    "mystery": 34,
    "nature": 35,
    "paranormal": 36,
    "philosophy": 37,
    "poetry": 38,
    "politics": 39,
    "progression fantasy": 58,
    "reference": 40,
    "religion": 41,
    "romance": 42,
    "science": 44,
    "science fiction": 45,
    "sci-fi": 45,
    "self-help": 46,
    "sports": 49,
    "superheroes": 56,
    "technology": 50,
    "thriller": 51,
    "suspense": 51,
    "travel": 52,
    "urban fantasy": 53,
    "western": 54,
    "young adult": 55,
    "epic": 13,  # Map Epic to Fantasy
    "paranormal & urban": 53,  # Urban Fantasy
}


def _map_genres_to_categories(genres: list[dict[str, Any]]) -> list[int]:
    """
    Map Audnex genres to MAM category IDs.

    Args:
        genres: List of genre dicts from Audnex (with 'name' key)

    Returns:
        List of unique MAM category IDs
    """
    categories: set[int] = set()

    for genre in genres:
        name = genre.get("name", "").lower()
        if name in MAM_CATEGORY_MAP:
            categories.add(MAM_CATEGORY_MAP[name])
        else:
            # Try partial matching
            for key, cat_id in MAM_CATEGORY_MAP.items():
                if key in name or name in key:
                    categories.add(cat_id)
                    break

    return sorted(categories)


def _build_series_list(audnex_data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Build series list for MAM JSON from Audnex data.

    Args:
        audnex_data: Audnex book metadata

    Returns:
        List of series dicts with 'name' and 'number' keys
    """
    series_list = []

    # Primary series
    primary = audnex_data.get("seriesPrimary")
    if primary:
        series_list.append(
            {
                "name": primary.get("name", ""),
                "number": primary.get("position", ""),
            }
        )

    # Secondary series (if any)
    secondary = audnex_data.get("seriesSecondary")
    if secondary:
        series_list.append(
            {
                "name": secondary.get("name", ""),
                "number": secondary.get("position", ""),
            }
        )

    return series_list


def _clean_html(text: str) -> str:
    """
    Clean HTML tags from description text.

    Simple approach - just strips common HTML tags.
    """
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Decode common entities
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    text = text.replace("&nbsp;", " ")
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
) -> dict[str, Any]:
    """
    Build MAM fast-fillout JSON from release metadata.

    Args:
        release: AudiobookRelease object with metadata
        audnex_data: Optional Audnex API response (uses release.audnex_metadata if None)
        mediainfo_data: Optional MediaInfo JSON (uses release.mediainfo_data if None)

    Returns:
        Dict ready to be serialized as MAM JSON
    """
    # Use release metadata if not provided
    audnex = audnex_data or release.audnex_metadata or {}
    mediainfo = mediainfo_data or release.mediainfo_data

    mam_json: dict[str, Any] = {}

    # Title - use Audnex title or fallback to release title
    title = audnex.get("title") or release.title
    if title:
        mam_json["title"] = title

    # Authors (filter out translators, illustrators, etc.)
    authors = audnex.get("authors", [])
    if authors:
        filtered_authors = filter_authors(authors)
        mam_json["authors"] = [a.get("name", "") for a in filtered_authors if a.get("name")]
    elif release.author:
        mam_json["authors"] = [release.author]

    # Narrators
    narrators = audnex.get("narrators", [])
    if narrators:
        mam_json["narrators"] = [n.get("name", "") for n in narrators if n.get("name")]
    elif release.narrator:
        mam_json["narrators"] = [release.narrator]

    # Description - render BBCode using Jinja2 template
    if audnex:
        bbcode_description = render_bbcode_description(
            audnex_data=audnex,
            mediainfo_data=mediainfo,
            asin=release.asin,
        )
        if bbcode_description:
            mam_json["description"] = bbcode_description

    # Series
    series_list = _build_series_list(audnex)
    if series_list:
        mam_json["series"] = series_list
    elif release.series:
        mam_json["series"] = [
            {
                "name": release.series,
                "number": release.series_position or "",
            }
        ]

    # Subtitle
    subtitle = audnex.get("subtitle")
    if subtitle:
        mam_json["subtitle"] = subtitle

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
    lit_type = audnex.get("literatureType", "").lower()
    if lit_type == "fiction":
        mam_json["main_cat"] = 1
    elif lit_type == "non-fiction" or lit_type == "nonfiction":
        mam_json["main_cat"] = 2

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

    logger.info(f"Saved MAM JSON: {output_path}")


def generate_mam_json_for_release(
    release: AudiobookRelease,
    output_dir: Path | None = None,
) -> Path | None:
    """
    Generate MAM JSON file for a release.

    Uses release.audnex_metadata and release.mediainfo_data if available,
    or fetches them if not.

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

    # Build filename: same as torrent but .json extension
    # Format: "Author - Title.json"
    if release.staging_dir:
        json_name = f"{release.staging_dir.name}.json"
    else:
        json_name = f"{release.display_name}.json"

    output_path = Path(output_dir) / json_name

    # Build and save
    mam_data = build_mam_json(release)

    if not mam_data.get("title"):
        logger.warning(f"No title for MAM JSON: {release.display_name}")
        return None

    save_mam_json(mam_data, output_path)
    return output_path
