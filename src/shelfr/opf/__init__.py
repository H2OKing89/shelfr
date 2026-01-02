"""
DEPRECATED: OPF module has moved to shelfr.metadata.opf.

This module is a deprecation shim that re-exports from the new location.
Direct imports from shelfr.opf will continue to work but emit a
DeprecationWarning unless SHELFR_ENABLE_LEGACY_OPF=1 is set.

Migration:
    # Old (deprecated)
    from shelfr.opf import CanonicalMetadata, generate_opf, write_opf

    # New (preferred)
    from shelfr.metadata.opf import CanonicalMetadata, generate_opf, write_opf

The old import path will be removed in a future release.
"""

from __future__ import annotations

import os
import warnings

# Check if legacy mode is enabled (suppresses warnings)
_LEGACY_MODE = os.getenv("SHELFR_ENABLE_LEGACY_OPF", "").lower() in ("1", "true", "yes")

if not _LEGACY_MODE:
    warnings.warn(
        "shelfr.opf is deprecated. Use shelfr.metadata.opf instead. "
        "Set SHELFR_ENABLE_LEGACY_OPF=1 to suppress this warning.",
        DeprecationWarning,
        stacklevel=2,
    )

# Re-export everything from the new location
from shelfr.metadata.opf import (  # noqa: E402
    LANGUAGE_TO_ISO,
    MARC_RELATOR_CODES,
    CanonicalMetadata,
    Genre,
    OPFCreator,
    OPFGenerator,
    OPFIdentifier,
    OPFMetadata,
    OPFSeries,
    Person,
    Series,
    clean_role_from_name,
    clear_naming_config_cache,
    detect_role_from_name,
    generate_opf,
    get_marc_relator,
    get_naming_config,
    is_valid_iso_language,
    name_to_file_as,
    to_iso_language,
    write_opf,
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
