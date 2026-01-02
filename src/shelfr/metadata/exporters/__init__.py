"""
Metadata exporters package.

Exporters convert aggregated metadata to specific output formats.
Each exporter implements the MetadataExporter protocol.

Available exporters:
- JsonExporter: ABS metadata.json sidecar format
- OpfExporter: OPF sidecar format (Dublin Core/EPUB)

Future exporters:
- NfoExporter: Kodi/Plex NFO format
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from shelfr.metadata.exporters.base import MetadataExporter
from shelfr.metadata.exporters.json import JsonExporter
from shelfr.metadata.exporters.opf import OpfExporter

if TYPE_CHECKING:
    pass

__all__ = [
    "MetadataExporter",
    "JsonExporter",
    "OpfExporter",
    "get_exporter",
    "list_exporters",
]

# Registry of available exporters
_EXPORTERS: dict[str, type[MetadataExporter]] = {
    "json": JsonExporter,
    "opf": OpfExporter,
}


def get_exporter(format_name: str) -> MetadataExporter:
    """Get an exporter instance by format name.

    Args:
        format_name: Name of the export format (e.g., "json", "opf")

    Returns:
        Instantiated exporter

    Raises:
        ValueError: If format_name is not supported
    """
    exporter_cls = _EXPORTERS.get(format_name)
    if exporter_cls is None:
        supported = ", ".join(sorted(_EXPORTERS.keys()))
        raise ValueError(f"Unknown export format '{format_name}'. Supported: {supported}")
    return exporter_cls()


def list_exporters() -> list[str]:
    """List available export format names.

    Returns:
        Sorted list of supported format names
    """
    return sorted(_EXPORTERS.keys())


def register_exporter(format_name: str, exporter_cls: type[MetadataExporter]) -> None:
    """Register a new exporter.

    This allows plugins to add custom exporters at runtime.

    Args:
        format_name: Name for the export format
        exporter_cls: Exporter class (must implement MetadataExporter protocol)
    """
    _EXPORTERS[format_name] = exporter_cls
