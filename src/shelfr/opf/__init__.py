"""
OPF metadata generation for Audiobookshelf import.

This package provides a modular two-layer approach to metadata handling:

1. **CanonicalMetadata** - Internal schema matching Audnexus API structure.
   Use this for validation, storage, and as the source of truth.

2. **OPFMetadata** - ABS-compatible export profile with only the fields
   that Audiobookshelf reliably ingests.

Example usage:

    from shelfr.opf import CanonicalMetadata, generate_opf, write_opf
    from pathlib import Path

    # From raw Audnexus API response
    audnex_data = fetch_audnex_book("1774248182")
    meta = CanonicalMetadata.from_audnex(audnex_data)

    # Generate XML string
    xml_str = generate_opf(meta)

    # Or write directly to file
    write_opf(meta, Path("/audiobooks/MyBook"))  # Creates metadata.opf

The mapping from Audnexus to OPF follows these rules:
- `dc:title` ← title
- `dc:subtitle` ← subtitle
- `dc:creator opf:role="aut"` ← authors[].name
- `dc:creator opf:role="nrt"` ← narrators[].name
- `dc:publisher` ← publisherName
- `dc:date` ← releaseDate (ISO format)
- `dc:language` ← language (converted to ISO 639-2/B)
- `dc:identifier opf:scheme="ASIN"` ← asin
- `dc:identifier opf:scheme="ISBN"` ← isbn
- `dc:description` ← description or summary (HTML stripped)
- `dc:subject` ← genres[].name
- `calibre:series` + `calibre:series_index` ← seriesPrimary, seriesSecondary
- `dc:tag` ← "Adult" if isAdult

Custom fields (ABS ignores, kept for future use):
- `audnex:rating`, `audnex:runtimeLengthMin`, `audnex:formatType`,
  `audnex:region`, `audnex:image`, `audnex:copyright`, `audnex:literatureType`
"""

from __future__ import annotations

from shelfr.opf.generator import OPFGenerator, generate_opf, write_opf
from shelfr.opf.helpers import (
    clean_role_from_name,
    clear_naming_config_cache,
    detect_role_from_name,
    get_naming_config,
    name_to_file_as,
)
from shelfr.opf.mappings import (
    LANGUAGE_TO_ISO,
    MARC_RELATOR_CODES,
    get_marc_relator,
    is_valid_iso_language,
    to_iso_language,
)
from shelfr.opf.schemas import (
    CanonicalMetadata,
    Genre,
    OPFCreator,
    OPFIdentifier,
    OPFMetadata,
    OPFSeries,
    Person,
    Series,
)

__all__ = [
    # Core schemas
    "CanonicalMetadata",
    "OPFMetadata",
    "Person",
    "Genre",
    "Series",
    "OPFCreator",
    "OPFIdentifier",
    "OPFSeries",
    # Generator
    "OPFGenerator",
    "generate_opf",
    "write_opf",
    # Helpers
    "get_naming_config",
    "clear_naming_config_cache",
    "clean_role_from_name",
    "detect_role_from_name",
    "name_to_file_as",
    # Mappings
    "to_iso_language",
    "is_valid_iso_language",
    "get_marc_relator",
    "LANGUAGE_TO_ISO",
    "MARC_RELATOR_CODES",
]
