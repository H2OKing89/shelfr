"""Build Audiobookshelf metadata.json from Audnex data.

This module transforms Audnex API responses into the format expected
by Audiobookshelf's metadata.json for library imports.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from shelfr.schemas.abs_metadata import AbsChapter, AbsMetadataJson

if TYPE_CHECKING:
    from shelfr.abs.importer import ParsedFolderName

logger = logging.getLogger(__name__)


def build_abs_metadata_from_audnex(
    audnex_data: dict[str, Any],
    audnex_chapters: dict[str, Any] | None = None,
) -> AbsMetadataJson:
    """Build Audiobookshelf metadata.json from Audnex API data.

    Args:
        audnex_data: Response from Audnex /books/{asin} endpoint
        audnex_chapters: Response from Audnex /books/{asin}/chapters endpoint

    Returns:
        AbsMetadataJson model ready for serialization
    """
    # Title (required)
    title = audnex_data.get("title", "Unknown Title")
    subtitle = audnex_data.get("subtitle")

    # Authors - extract names from author objects
    authors = [a.get("name") for a in audnex_data.get("authors", []) if a.get("name")]

    # Narrators - extract names from narrator objects
    narrators = [n.get("name") for n in audnex_data.get("narrators", []) if n.get("name")]

    # Series - format as "Series Name #Position"
    series_list: list[str] = []
    primary_series = audnex_data.get("seriesPrimary")
    if primary_series and primary_series.get("name"):
        series_name = primary_series.get("name")
        series_pos = primary_series.get("position")
        if series_pos:
            series_list.append(f"{series_name} #{series_pos}")
        else:
            series_list.append(series_name)

    secondary_series = audnex_data.get("seriesSecondary")
    if secondary_series and secondary_series.get("name"):
        series_name = secondary_series.get("name")
        series_pos = secondary_series.get("position")
        if series_pos:
            series_list.append(f"{series_name} #{series_pos}")
        else:
            series_list.append(series_name)

    # Genres - extract names from genre objects
    genres = [g.get("name") for g in audnex_data.get("genres", []) if g.get("name")]

    # Tags - use genres for tags (ABS uses both)
    tags = genres.copy()

    # Published year/date
    release_date = audnex_data.get("releaseDate")
    published_year = None
    published_date = None
    if release_date:
        # Format: "2025-11-25T00:00:00.000Z" or "2025-11-25"
        published_date = release_date[:10] if len(release_date) >= 10 else None
        published_year = release_date[:4] if len(release_date) >= 4 else None

    # Publisher
    publisher = audnex_data.get("publisherName")

    # Description - use summary (HTML allowed)
    description = audnex_data.get("summary")

    # ASIN
    asin = audnex_data.get("asin")

    # Language
    language = audnex_data.get("language")
    if language:
        language = language.capitalize()

    # Explicit content
    explicit = audnex_data.get("isAdult", False)

    # Abridged
    format_type = audnex_data.get("formatType", "") or ""
    abridged = format_type.lower() == "abridged"

    # Chapters - convert from Audnex format
    chapters: list[AbsChapter] = []
    if audnex_chapters:
        audnex_chapter_list = audnex_chapters.get("chapters", [])
        for i, ch in enumerate(audnex_chapter_list):
            start_sec = ch.get("startOffsetSec", 0)
            length_ms = ch.get("lengthMs", 0)
            end_sec = start_sec + (length_ms / 1000.0)
            chapter_title = ch.get("title", f"Chapter {i + 1}")

            chapters.append(
                AbsChapter(
                    id=i,
                    start=float(start_sec),
                    end=end_sec,
                    title=chapter_title,
                )
            )

    return AbsMetadataJson(
        title=title,
        subtitle=subtitle,
        authors=authors,
        narrators=narrators,
        series=series_list,
        genres=genres,
        tags=tags,
        chapters=chapters,
        published_year=published_year,
        published_date=published_date,
        publisher=publisher,
        description=description,
        isbn=None,  # We use ASIN, not ISBN
        asin=asin,
        language=language,
        explicit=explicit,
        abridged=abridged,
    )


def build_abs_metadata_fallback(
    parsed: ParsedFolderName,
) -> AbsMetadataJson:
    """Build minimal Audiobookshelf metadata from parsed folder name.

    Used as fallback when ASIN is not available and Audnex
    cannot be queried.

    Args:
        parsed: ParsedFolderName from parse_mam_folder_name()

    Returns:
        AbsMetadataJson with minimal data
    """
    # Build series list from parsed data
    series_list: list[str] = []
    if parsed.series:
        if parsed.series_position:
            series_list.append(f"{parsed.series} #{parsed.series_position}")
        else:
            series_list.append(parsed.series)

    return AbsMetadataJson(
        title=parsed.title,
        subtitle=None,
        authors=[parsed.author] if parsed.author else [],
        narrators=[parsed.narrator] if parsed.narrator else [],
        series=series_list,
        genres=[],
        tags=[],
        chapters=[],
        published_year=parsed.year,
        published_date=None,
        publisher=None,
        description=None,
        isbn=None,
        asin=parsed.asin,
        language=None,
        explicit=False,
        abridged=False,
    )


def write_abs_metadata_json(
    dst_folder: Path,
    metadata: AbsMetadataJson,
    *,
    dry_run: bool = False,
) -> Path | None:
    """Write metadata.json to the destination folder.

    Args:
        dst_folder: Folder to write metadata.json into
        metadata: AbsMetadataJson model to serialize
        dry_run: If True, only log what would happen

    Returns:
        Path to written file, or None if dry_run or error
    """
    metadata_path = dst_folder / "metadata.json"

    if dry_run:
        logger.info("[DRY RUN] Would write metadata.json to %s", dst_folder)
        return None

    result: Path | None = None
    temp_path: str | None = None
    try:
        # Serialize using Pydantic's model_dump with by_alias for camelCase
        json_data = metadata.model_dump(
            by_alias=True,
            exclude_none=True,  # Don't include null fields
        )

        # Write to a temporary file in the same directory and fsync to ensure durability
        with tempfile.NamedTemporaryFile("w", dir=dst_folder, delete=False, encoding="utf-8") as tf:
            temp_path = tf.name
            tf.write(json.dumps(json_data, indent=2, ensure_ascii=False))
            tf.flush()
            try:
                os.fsync(tf.fileno())
            except OSError:
                # fsync not critical on some platforms/filesystems, but log failure
                logger.debug("fsync failed for %s", temp_path)

        # Atomically replace the target file with the temp file
        try:
            os.replace(temp_path, metadata_path)
        except OSError as e:
            logger.warning("Failed to atomically replace metadata file %s: %s", metadata_path, e)
            # Attempt to clean up temp file; do not raise further
            try:
                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                logger.debug("Failed to remove temp metadata file %s", temp_path)
            return None

        logger.debug("Wrote metadata.json to %s", metadata_path)
        result = metadata_path
    except OSError as e:
        logger.warning("Failed to write metadata.json to %s: %s", dst_folder, e)
        # Try to remove temp file on error
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                logger.debug("Could not remove temporary metadata file %s", temp_path)

    return result
