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


@functools.lru_cache(maxsize=1)
def _get_jinja_env() -> Environment:
    """Get Jinja2 environment with template loader (cached)."""
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


def fetch_metadata(
    asin: str | None = None,
    m4b_path: Path | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """
    Fetch Audnex and MediaInfo metadata without saving.

    Args:
        asin: Audible ASIN (None to skip Audnex)
        m4b_path: Path to m4b file (None to skip MediaInfo)

    Returns:
        Tuple of (audnex_data, mediainfo_data), either may be None on error.
    """
    audnex_data = None
    mediainfo_data = None

    if asin:
        audnex_data = fetch_audnex_book(asin)

    if m4b_path and m4b_path.exists():
        mediainfo_data = run_mediainfo(m4b_path)

    return audnex_data, mediainfo_data


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
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """
    Fetch both Audnex and MediaInfo metadata, optionally saving intermediate files.

    By default, this function only fetches metadata without saving files.
    Set save_intermediate=True to write audnex.json and mediainfo.json to output_dir.

    Args:
        asin: Audible ASIN (None to skip Audnex)
        m4b_path: Path to m4b file (None to skip MediaInfo)
        output_dir: Directory to save JSON files (only used if save_intermediate=True)
        save_intermediate: If True, save audnex.json and mediainfo.json files

    Returns:
        Tuple of (audnex_data, mediainfo_data), either may be None on error.
    """
    audnex_data, mediainfo_data = fetch_metadata(asin=asin, m4b_path=m4b_path)

    if save_intermediate and output_dir:
        save_metadata_files(output_dir, audnex_data=audnex_data, mediainfo_data=mediainfo_data)

    return audnex_data, mediainfo_data


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
    settings = get_settings()
    categories = settings.categories

    # Select the appropriate map based on fiction/nonfiction
    if is_fiction:
        category_map = categories.audiobook_fiction_map
        default_key = "fiction"
    else:
        category_map = categories.audiobook_nonfiction_map
        default_key = "nonfiction"

    # Get default from config or hardcode
    default_category = categories.audiobook_defaults.get(
        default_key,
        "Audiobooks - General Fiction" if is_fiction else "Audiobooks - General Non-Fic",
    )

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

    Args:
        genres: List of genre dicts from Audnex (with 'name' key)

    Returns:
        List of unique MAM category IDs
    """
    settings = get_settings()
    category_map = settings.categories.genre_map
    categories: set[int] = set()

    for genre in genres:
        name = genre.get("name", "").lower()
        if name in category_map:
            categories.add(category_map[name])
        else:
            # Try partial matching
            for key, cat_id in category_map.items():
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

    Strips HTML tags and decodes HTML entities.
    """
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Decode HTML entities (handles &amp;, &lt;, &#39;, etc.)
    text = html.unescape(text)
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
