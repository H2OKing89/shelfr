"""
OPF exporter for Audiobookshelf metadata.opf sidecar.

This exporter converts aggregated metadata to OPF format,
which is read by Audiobookshelf during library scans.

The OPF exporter uses the existing OPF generation infrastructure
from shelfr.metadata.opf, wrapping it in the MetadataExporter protocol.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from shelfr.exceptions import ExportError

if TYPE_CHECKING:
    from shelfr.metadata.aggregator import AggregatedResult
    from shelfr.metadata.opf import OPFMetadata

logger = logging.getLogger(__name__)


class OpfExporter:
    """Exporter for OPF (Open Packaging Format) sidecar files.

    Converts aggregated metadata fields to OPF format for
    Audiobookshelf import.

    The OPF format follows EPUB 2.0 conventions with Dublin Core
    elements and Calibre series extensions for maximum ABS compatibility.

    Attributes:
        name: "opf"
        file_extension: ".opf"
        description: Human-readable description
    """

    name: str = "opf"
    file_extension: str = ".opf"
    description: str = "Audiobookshelf metadata.opf (OPF/Dublin Core format)"

    async def export(self, result: AggregatedResult, output_dir: Path) -> Path:
        """Export aggregated metadata to metadata.opf.

        Args:
            result: Aggregated metadata from MetadataAggregator
            output_dir: Directory to write metadata.opf

        Returns:
            Path to the written file

        Raises:
            ExportError: If file write fails or required fields missing
        """
        from shelfr.metadata.opf import OPFGenerator

        # Build OPF metadata from aggregated fields
        opf_metadata = self._convert_to_opf_metadata(result)

        # Generate and write OPF file
        generator = OPFGenerator()
        output_path = output_dir / "metadata.opf"

        try:
            xml_str = generator.generate(opf_metadata)
            output_path.write_text(xml_str, encoding="utf-8")
        except OSError as e:
            raise ExportError(
                f"Failed to write metadata.opf: {e}",
                format_name=self.name,
                output_path=output_path,
            ) from e

        logger.debug("Exported OPF metadata to %s", output_path)
        return output_path

    def _convert_to_opf_metadata(self, result: AggregatedResult) -> OPFMetadata:
        """Convert AggregatedResult to OPFMetadata.

        This method maps from the aggregator's field dict to the
        OPFMetadata schema expected by the generator.

        Args:
            result: Aggregated metadata with fields dict

        Returns:
            OPFMetadata instance ready for XML generation
        """
        from shelfr.metadata.opf import OPFCreator, OPFIdentifier, OPFMetadata, OPFSeries
        from shelfr.metadata.opf.mappings import to_iso_language

        fields = result.fields

        # Build creators list
        creators: list[OPFCreator] = []

        # Authors (role="aut")
        authors = fields.get("authors", [])
        for author in authors:
            name = author.get("name", author) if isinstance(author, dict) else str(author)
            creators.append(OPFCreator(name=name, role="aut"))

        # Narrators (role="nrt")
        narrators = fields.get("narrators", [])
        for narrator in narrators:
            name = narrator.get("name", narrator) if isinstance(narrator, dict) else str(narrator)
            creators.append(OPFCreator(name=name, role="nrt"))

        # Build identifiers
        identifiers: list[OPFIdentifier] = []
        if asin := fields.get("asin"):
            identifiers.append(OPFIdentifier(value=asin, scheme="ASIN"))
        if isbn := fields.get("isbn"):
            identifiers.append(OPFIdentifier(value=isbn, scheme="ISBN"))

        # Build series list
        series: list[OPFSeries] = []
        series_name = fields.get("series_name")
        series_position = fields.get("series_position")
        if series_name:
            series.append(
                OPFSeries(
                    name=series_name,
                    index=str(series_position) if series_position else "1",
                )
            )

        # Build subjects from genres
        subjects: list[str] = []
        genres = fields.get("genres", [])
        for genre in genres:
            name = genre.get("name", genre) if isinstance(genre, dict) else str(genre)
            subjects.append(name)

        # Build tags
        tags: list[str] = []
        if fields.get("is_adult"):
            tags.append("Adult")

        # Convert release_date to ISO format if present
        date_str: str | None = None
        if release_date := fields.get("release_date"):
            if hasattr(release_date, "isoformat"):
                date_str = release_date.isoformat()[:10]  # YYYY-MM-DD
            else:
                date_str = str(release_date)[:10]

        # Get language, convert to ISO code
        language = fields.get("language", "English")
        iso_language = to_iso_language(language)

        return OPFMetadata(
            title=fields.get("title", "Unknown"),
            language=iso_language,
            creators=creators,
            identifiers=identifiers,
            date=date_str,
            subtitle=fields.get("subtitle"),
            publisher=fields.get("publisher"),
            description=fields.get("description") or fields.get("summary"),
            subjects=subjects,
            series=series,
            tags=tags,
            custom_meta={},  # Custom meta not populated from aggregated result
        )
