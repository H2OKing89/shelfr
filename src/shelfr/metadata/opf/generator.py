"""
OPF XML generator for Audiobookshelf import.

Generates ABS-compatible OPF (Open Packaging Format) files from
canonical metadata. Uses ElementTree for XML generation to avoid
external dependencies.

Output follows EPUB 2.0 OPF spec with Dublin Core elements and
Calibre series conventions for maximum ABS compatibility.
"""

from __future__ import annotations

import contextlib
import html
import logging
import re
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shelfr.metadata.opf.schemas import CanonicalMetadata, OPFMetadata

logger = logging.getLogger(__name__)

# XML namespaces
NS_DC = "http://purl.org/dc/elements/1.1/"
NS_OPF = "http://www.idpf.org/2007/opf"


def _strip_html(text: str) -> str:
    """
    Strip HTML tags from text while preserving content.

    ABS strips HTML anyway, so we do it ourselves for clean output.

    Args:
        text: Potentially HTML-containing text

    Returns:
        Plain text with HTML entities decoded
    """
    if not text:
        return ""
    # Remove HTML tags
    cleaned = re.sub(r"<[^>]+>", "", text)
    # Decode HTML entities
    cleaned = html.unescape(cleaned)
    # Normalize whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _sanitize_xml_text(text: str | None) -> str:
    """
    Sanitize text for XML content.

    Removes control characters that are invalid in XML 1.0.

    Args:
        text: Text to sanitize

    Returns:
        Sanitized text safe for XML
    """
    if not text:
        return ""
    # Remove control characters except tab, newline, carriage return
    # XML 1.0: #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD]
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)


class OPFGenerator:
    """
    Generate ABS-compatible OPF XML files.

    Usage:
        generator = OPFGenerator()
        xml_str = generator.generate(opf_metadata)
        generator.write(opf_metadata, Path("/path/to/metadata.opf"))

    The generator produces OPF files following these conventions:
    - EPUB 2.0 package format
    - Dublin Core metadata elements (dc:*)
    - OPF attributes for roles and schemes
    - Calibre series meta elements
    - Custom audnex:* meta elements for extended data
    """

    def __init__(self, *, include_custom_meta: bool = True) -> None:
        """
        Initialize the OPF generator.

        Args:
            include_custom_meta: Whether to include audnex:* custom metadata
        """
        self.include_custom_meta = include_custom_meta

    def generate(self, metadata: OPFMetadata) -> str:
        """
        Generate OPF XML string from metadata.

        Args:
            metadata: OPFMetadata instance

        Returns:
            Formatted XML string with proper declaration
        """
        root = self._build_package(metadata)
        return self._to_string(root)

    def generate_from_canonical(self, metadata: CanonicalMetadata) -> str:
        """
        Generate OPF XML from canonical metadata.

        Convenience method that handles the conversion internally.

        Args:
            metadata: CanonicalMetadata instance

        Returns:
            Formatted XML string
        """
        from shelfr.metadata.opf.schemas import OPFMetadata

        opf_meta = OPFMetadata.from_canonical(metadata)
        return self.generate(opf_meta)

    def write(
        self,
        metadata: OPFMetadata,
        path: Path,
        *,
        filename: str = "metadata.opf",
    ) -> Path:
        """
        Write OPF file to disk.

        Args:
            metadata: OPFMetadata instance
            path: Directory or full file path
            filename: Filename if path is a directory

        Returns:
            Path to the written file
        """
        # Detect directory intent: existing dir, or no suffix (assume dir)
        if path.is_dir() or (not path.exists() and not path.suffix):
            path.mkdir(parents=True, exist_ok=True)
            file_path = path / filename
        else:
            file_path = path
            file_path.parent.mkdir(parents=True, exist_ok=True)

        xml_str = self.generate(metadata)
        file_path.write_text(xml_str, encoding="utf-8")
        logger.info("Wrote OPF metadata to %s", file_path)
        return file_path

    def write_from_canonical(
        self,
        metadata: CanonicalMetadata,
        path: Path,
        *,
        filename: str = "metadata.opf",
    ) -> Path:
        """
        Write OPF file from canonical metadata.

        Args:
            metadata: CanonicalMetadata instance
            path: Directory or full file path
            filename: Filename if path is a directory

        Returns:
            Path to the written file
        """
        from shelfr.metadata.opf.schemas import OPFMetadata

        opf_meta = OPFMetadata.from_canonical(metadata)
        return self.write(opf_meta, path, filename=filename)

    def _build_package(self, metadata: OPFMetadata) -> ET.Element:
        """Build the OPF package element tree."""
        # Register namespaces for this build
        # This must be done before creating elements to get clean output
        ET.register_namespace("dc", NS_DC)
        ET.register_namespace("opf", NS_OPF)

        # Create package root
        package = ET.Element("package")
        package.set("version", "2.0")
        package.set("unique-identifier", "bookid")

        # Create metadata container
        meta_elem = ET.SubElement(package, "metadata")

        # Add all metadata elements
        self._add_title(meta_elem, metadata)
        self._add_subtitle(meta_elem, metadata)
        self._add_creators(meta_elem, metadata)
        self._add_publisher(meta_elem, metadata)
        self._add_date(meta_elem, metadata)
        self._add_language(meta_elem, metadata)
        self._add_identifiers(meta_elem, metadata)
        self._add_description(meta_elem, metadata)
        self._add_subjects(meta_elem, metadata)
        self._add_tags(meta_elem, metadata)
        self._add_series(meta_elem, metadata)
        if self.include_custom_meta:
            self._add_custom_meta(meta_elem, metadata)

        return package

    def _add_title(self, parent: ET.Element, metadata: OPFMetadata) -> None:
        """Add dc:title element."""
        title = ET.SubElement(parent, f"{{{NS_DC}}}title")
        title.text = _sanitize_xml_text(metadata.title)

    def _add_subtitle(self, parent: ET.Element, metadata: OPFMetadata) -> None:
        """Add dc:subtitle element if present."""
        if metadata.subtitle:
            subtitle = ET.SubElement(parent, f"{{{NS_DC}}}subtitle")
            subtitle.text = _sanitize_xml_text(metadata.subtitle)

    def _add_creators(self, parent: ET.Element, metadata: OPFMetadata) -> None:
        """Add dc:creator elements with opf:role attributes."""
        for creator in metadata.creators:
            elem = ET.SubElement(parent, f"{{{NS_DC}}}creator")
            elem.text = _sanitize_xml_text(creator.name)
            elem.set(f"{{{NS_OPF}}}role", creator.role)
            if creator.file_as:
                elem.set(f"{{{NS_OPF}}}file-as", creator.file_as)

    def _add_publisher(self, parent: ET.Element, metadata: OPFMetadata) -> None:
        """Add dc:publisher element if present."""
        if metadata.publisher:
            publisher = ET.SubElement(parent, f"{{{NS_DC}}}publisher")
            publisher.text = _sanitize_xml_text(metadata.publisher)

    def _add_date(self, parent: ET.Element, metadata: OPFMetadata) -> None:
        """Add dc:date element if present."""
        if metadata.date:
            date = ET.SubElement(parent, f"{{{NS_DC}}}date")
            date.text = metadata.date

    def _add_language(self, parent: ET.Element, metadata: OPFMetadata) -> None:
        """Add dc:language element."""
        language = ET.SubElement(parent, f"{{{NS_DC}}}language")
        language.text = metadata.language

    def _add_identifiers(self, parent: ET.Element, metadata: OPFMetadata) -> None:
        """Add dc:identifier elements with opf:scheme attributes."""
        # Add a UUID as the unique identifier if no ASIN
        has_asin = any(i.scheme == "ASIN" for i in metadata.identifiers)
        if not has_asin:
            uid = ET.SubElement(parent, f"{{{NS_DC}}}identifier")
            uid.set("id", "bookid")
            uid.set(f"{{{NS_OPF}}}scheme", "UUID")
            uid.text = str(uuid.uuid4())

        for identifier in metadata.identifiers:
            elem = ET.SubElement(parent, f"{{{NS_DC}}}identifier")
            elem.text = identifier.value
            elem.set(f"{{{NS_OPF}}}scheme", identifier.scheme)
            # First ASIN becomes the bookid
            if identifier.scheme == "ASIN" and has_asin:
                elem.set("id", "bookid")
                has_asin = False  # Only first ASIN gets id

    def _add_description(self, parent: ET.Element, metadata: OPFMetadata) -> None:
        """Add dc:description element if present."""
        if metadata.description:
            desc = ET.SubElement(parent, f"{{{NS_DC}}}description")
            # Strip HTML since ABS does this anyway
            desc.text = _strip_html(_sanitize_xml_text(metadata.description))

    def _add_subjects(self, parent: ET.Element, metadata: OPFMetadata) -> None:
        """Add dc:subject elements for genres."""
        for subject in metadata.subjects:
            elem = ET.SubElement(parent, f"{{{NS_DC}}}subject")
            elem.text = _sanitize_xml_text(subject)

    def _add_tags(self, parent: ET.Element, metadata: OPFMetadata) -> None:
        """Add dc:tag elements (non-standard but ABS may ingest)."""
        for tag in metadata.tags:
            elem = ET.SubElement(parent, f"{{{NS_DC}}}tag")
            elem.text = _sanitize_xml_text(tag)

    def _add_series(self, parent: ET.Element, metadata: OPFMetadata) -> None:
        """Add Calibre series meta elements."""
        for series in metadata.series:
            # calibre:series
            series_elem = ET.SubElement(parent, "meta")
            series_elem.set("name", "calibre:series")
            series_elem.set("content", _sanitize_xml_text(series.name))

            # calibre:series_index
            index_elem = ET.SubElement(parent, "meta")
            index_elem.set("name", "calibre:series_index")
            index_elem.set("content", series.index)

    def _add_custom_meta(self, parent: ET.Element, metadata: OPFMetadata) -> None:
        """Add custom audnex:* meta elements."""
        for name, value in metadata.custom_meta.items():
            elem = ET.SubElement(parent, "meta")
            elem.set("name", name)
            elem.set("content", _sanitize_xml_text(value))

    def _to_string(self, root: ET.Element) -> str:
        """
        Convert element tree to formatted XML string.

        Returns properly indented XML with declaration.
        """
        # Python 3.9+ has indent function
        with contextlib.suppress(AttributeError):
            ET.indent(root, space="  ")

        xml_bytes = ET.tostring(root, encoding="unicode")

        # Add XML declaration
        return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_bytes}'


def generate_opf(metadata: CanonicalMetadata | OPFMetadata) -> str:
    """
    Generate OPF XML string from metadata.

    Convenience function for simple use cases.

    Args:
        metadata: CanonicalMetadata or OPFMetadata instance

    Returns:
        Formatted XML string
    """
    from shelfr.metadata.opf.schemas import CanonicalMetadata

    generator = OPFGenerator()
    if isinstance(metadata, CanonicalMetadata):
        return generator.generate_from_canonical(metadata)
    return generator.generate(metadata)


def write_opf(
    metadata: CanonicalMetadata | OPFMetadata,
    path: Path,
    *,
    filename: str = "metadata.opf",
) -> Path:
    """
    Write OPF file to disk.

    Convenience function for simple use cases.

    Args:
        metadata: CanonicalMetadata or OPFMetadata instance
        path: Directory or full file path
        filename: Filename if path is a directory

    Returns:
        Path to the written file
    """
    from shelfr.metadata.opf.schemas import CanonicalMetadata

    generator = OPFGenerator()
    if isinstance(metadata, CanonicalMetadata):
        return generator.write_from_canonical(metadata, path, filename=filename)
    return generator.write(metadata, path, filename=filename)
