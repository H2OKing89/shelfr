"""Audiobookshelf integration for MAMFast."""

from __future__ import annotations

from mamfast.abs.asin import (
    AsinSource,
    extract_all_asins,
    extract_asin,
    extract_asin_from_abs_item,
    extract_asin_with_source,
    is_valid_asin,
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
from mamfast.abs.indexer import (
    AbsIndex,
    AuthorVariant,
    BookRecord,
    ImportStatus,
    IndexStats,
    SyncResult,
)
from mamfast.abs.paths import PathMapper, abs_path_to_host, host_path_to_abs

__all__ = [
    # ASIN extraction
    "AsinSource",
    "extract_asin",
    "extract_asin_from_abs_item",
    "extract_asin_with_source",
    "extract_all_asins",
    "is_valid_asin",
    # Client
    "AbsApiError",
    "AbsAuthError",
    "AbsClient",
    "AbsConnectionError",
    "AbsLibrary",
    "AbsLibraryItem",
    "AbsUser",
    # Indexer
    "AbsIndex",
    "AuthorVariant",
    "BookRecord",
    "ImportStatus",
    "IndexStats",
    "SyncResult",
    # Paths
    "PathMapper",
    "abs_path_to_host",
    "host_path_to_abs",
]
