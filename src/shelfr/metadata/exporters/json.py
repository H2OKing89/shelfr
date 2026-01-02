"""
JSON exporter for Audiobookshelf metadata.json sidecar.

This exporter converts aggregated metadata to the ABS metadata.json format,
which is read by Audiobookshelf during library scans.

The output matches the AbsMetadataJson schema in schemas/abs_metadata.py.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from shelfr.exceptions import ExportError

if TYPE_CHECKING:
    from shelfr.metadata.aggregator import AggregatedResult

logger = logging.getLogger(__name__)


class JsonExporter:
    """Exporter for ABS metadata.json sidecar format.

    Converts aggregated metadata fields to the format expected by
    Audiobookshelf during library scans.

    Field mappings (canonical -> ABS):
    - title -> title
    - subtitle -> subtitle
    - authors -> authors (list of names, not Person objects)
    - narrators -> narrators (list of names)
    - series_name -> series (formatted as "Name #Position")
    - genres -> genres
    - description -> description
    - release_date -> publishedDate
    - publisher -> publisher
    - isbn -> isbn
    - language -> language
    - is_adult -> explicit
    - chapters -> chapters
    """

    name: str = "json"
    file_extension: str = ".json"
    description: str = "Audiobookshelf metadata.json sidecar"

    async def export(self, result: AggregatedResult, output_dir: Path) -> Path:
        """Export aggregated metadata to metadata.json.

        Args:
            result: Aggregated metadata from MetadataAggregator
            output_dir: Directory to write metadata.json

        Returns:
            Path to the written file

        Raises:
            ExportError: If file write fails (permission denied, disk full, etc.)

        Note:
            Uses synchronous file write (Path.write_text) which is acceptable
            for small metadata files. For latency-sensitive scenarios with
            large files, consider using asyncio.to_thread().
        """
        output_path = output_dir / "metadata.json"

        # Convert aggregated fields to ABS format
        abs_data = self._convert_to_abs_format(result)

        # Write with pretty formatting for readability
        try:
            output_path.write_text(
                json.dumps(abs_data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except OSError as e:
            raise ExportError(
                f"Failed to write metadata.json: {e}",
                format_name=self.name,
                output_path=output_path,
            ) from e

        logger.debug("Exported metadata to %s", output_path)
        return output_path

    def _convert_to_abs_format(self, result: AggregatedResult) -> dict[str, Any]:
        """Convert aggregated result to ABS metadata.json format.

        Args:
            result: Aggregated metadata

        Returns:
            Dict matching AbsMetadataJson schema
        """
        fields = result.fields
        abs_data: dict[str, Any] = {}

        # Required field
        title = fields.get("title")
        if title:
            abs_data["title"] = title
        else:
            # ABS requires title, use placeholder if missing
            abs_data["title"] = "Unknown"
            logger.warning("Missing title in aggregated metadata")

        # Optional simple fields
        if subtitle := fields.get("subtitle"):
            abs_data["subtitle"] = subtitle

        if publisher := fields.get("publisher"):
            abs_data["publisher"] = publisher

        if description := fields.get("description"):
            abs_data["description"] = description

        if isbn := fields.get("isbn"):
            abs_data["isbn"] = isbn

        if language := fields.get("language"):
            abs_data["language"] = language

        # Boolean fields
        if fields.get("is_adult"):
            abs_data["explicit"] = True

        # People lists - extract names from Person objects or use strings directly
        authors = fields.get("authors", [])
        if authors:
            abs_data["authors"] = self._extract_names(authors)

        narrators = fields.get("narrators", [])
        if narrators:
            abs_data["narrators"] = self._extract_names(narrators)

        # Series - format as "Name #Position"
        series_name = fields.get("series_name")
        series_position = fields.get("series_position")
        if series_name:
            series_str = series_name
            if series_position:
                series_str = f"{series_name} #{series_position}"
            abs_data["series"] = [series_str]

        # Genres - extract names from Genre objects or use strings directly
        genres = fields.get("genres", [])
        if genres:
            abs_data["genres"] = self._extract_names(genres)

        # Date fields - ABS uses publishedYear and publishedDate
        release_date = fields.get("release_date")
        if release_date:
            # Try to extract year
            year = self._extract_year(release_date)
            if year:
                abs_data["publishedYear"] = str(year)
            # Also include full date if available
            if isinstance(release_date, str) and len(release_date) >= 10:
                abs_data["publishedDate"] = release_date[:10]

        # ASIN - include if available
        # Check both the fields dict and result for ASIN
        asin = fields.get("asin")
        if asin:
            abs_data["asin"] = asin

        # Chapters
        chapters = fields.get("chapters", [])
        if chapters:
            abs_data["chapters"] = self._convert_chapters(chapters)

        return abs_data

    def _extract_names(self, items: list[Any]) -> list[str]:
        """Extract names from Person/Genre objects or return strings as-is.

        Args:
            items: List of Person/Genre objects or strings

        Returns:
            List of name strings
        """
        names = []
        for item in items:
            if isinstance(item, str):
                names.append(item)
            elif hasattr(item, "name"):
                names.append(item.name)
            elif isinstance(item, dict) and "name" in item:
                names.append(item["name"])
        return names

    def _extract_year(self, date_value: Any) -> int | None:
        """Extract year from various date formats.

        Args:
            date_value: Date as string, datetime, or other format

        Returns:
            Year as int, or None if extraction fails
        """
        if date_value is None:
            return None

        # Handle datetime objects
        if hasattr(date_value, "year"):
            year: int = date_value.year
            return year

        # Handle string dates (ISO format: YYYY-MM-DD or YYYY)
        if isinstance(date_value, str) and len(date_value) >= 4:
            try:
                return int(date_value[:4])
            except ValueError:
                pass

        return None

    def _convert_chapters(self, chapters: list[Any]) -> list[dict[str, Any]]:
        """Convert chapter data to ABS format.

        Args:
            chapters: List of Chapter objects or dicts

        Returns:
            List of chapter dicts matching AbsChapter schema
        """
        abs_chapters = []
        for i, chapter in enumerate(chapters):
            if isinstance(chapter, dict):
                abs_chapters.append(
                    {
                        "id": chapter.get("id", i),
                        "start": chapter.get("start", chapter.get("start_time", 0)),
                        "end": chapter.get("end", chapter.get("end_time", 0)),
                        "title": chapter.get("title", f"Chapter {i + 1}"),
                    }
                )
            elif hasattr(chapter, "title"):
                # Chapter dataclass or similar
                abs_chapters.append(
                    {
                        "id": getattr(chapter, "id", i),
                        "start": getattr(chapter, "start_time", getattr(chapter, "start", 0)),
                        "end": getattr(chapter, "end_time", getattr(chapter, "end", 0)),
                        "title": chapter.title,
                    }
                )
        return abs_chapters
