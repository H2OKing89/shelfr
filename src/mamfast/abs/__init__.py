"""Audiobookshelf integration for MAMFast."""

from __future__ import annotations

from mamfast.abs.asin import (
    AUDIO_EXTENSIONS,
    AsinEntry,
    AsinSource,
    SearchMatch,
    asin_exists,
    build_asin_index,
    extract_all_asins,
    extract_asin,
    extract_asin_from_abs_item,
    extract_asin_with_source,
    is_valid_asin,
    match_search_results,
    resolve_asin_via_abs_search,
)
from mamfast.abs.client import (
    AbsApiError,
    AbsAuthError,
    AbsClient,
    AbsConnectionError,
    AbsLibrary,
    AbsLibraryItem,
    AbsUser,
)
from mamfast.abs.importer import (
    BatchImportResult,
    DuplicateError,
    FilesystemMismatchError,
    ImportError,
    ImportResult,
    ParsedFolderName,
    build_target_path,
    discover_staged_books,
    import_batch,
    import_single,
    parse_mam_folder_name,
    trigger_scan_safe,
    validate_import_prerequisites,
)
from mamfast.abs.paths import PathMapper, abs_path_to_host, host_path_to_abs

__all__ = [
    # ASIN extraction and in-memory index
    "AUDIO_EXTENSIONS",
    "AsinEntry",
    "AsinSource",
    "SearchMatch",
    "asin_exists",
    "build_asin_index",
    "extract_asin",
    "extract_asin_from_abs_item",
    "extract_asin_with_source",
    "extract_all_asins",
    "is_valid_asin",
    "match_search_results",
    "resolve_asin_via_abs_search",
    # Client
    "AbsApiError",
    "AbsAuthError",
    "AbsClient",
    "AbsConnectionError",
    "AbsLibrary",
    "AbsLibraryItem",
    "AbsUser",
    # Importer
    "BatchImportResult",
    "DuplicateError",
    "FilesystemMismatchError",
    "ImportError",
    "ImportResult",
    "ParsedFolderName",
    "build_target_path",
    "discover_staged_books",
    "import_batch",
    "import_single",
    "parse_mam_folder_name",
    "trigger_scan_safe",
    "validate_import_prerequisites",
    # Paths
    "PathMapper",
    "abs_path_to_host",
    "host_path_to_abs",
]
