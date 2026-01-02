"""
MetadataExporter protocol definition.

All metadata exporters implement this protocol. The protocol uses duck typing
via typing.Protocol for flexibility with custom exporters.

Exporters convert AggregatedResult → specific output format (file on disk).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from shelfr.metadata.aggregator import AggregatedResult


@runtime_checkable
class MetadataExporter(Protocol):
    """Protocol for pluggable metadata exporters.

    Exporters take aggregated metadata and write it to a specific format.
    The export() method is async to support potential network operations
    (e.g., cover image download) in future exporters.

    Attributes:
        name: Unique exporter identifier (e.g., "json", "opf")
        file_extension: Output file extension (e.g., ".json", ".opf")
        description: Human-readable description

    Example implementation:
        class MyExporter:
            name = "my_format"
            file_extension = ".xml"
            description = "My custom metadata format"

            async def export(
                self, result: AggregatedResult, output_dir: Path
            ) -> Path:
                # Convert result.fields to your format...
                output_path = output_dir / f"metadata{self.file_extension}"
                output_path.write_text(content)
                return output_path
    """

    name: str
    file_extension: str
    description: str

    async def export(self, result: AggregatedResult, output_dir: Path) -> Path:
        """Export aggregated metadata to a file.

        Args:
            result: Aggregated metadata from MetadataAggregator
            output_dir: Directory to write the output file

        Returns:
            Path to the written file

        Raises:
            shelfr.exceptions.ExportError: If export fails (file write,
                validation, permission denied, etc.)
        """
        ...
