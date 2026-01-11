"""
Audnex API client for audiobook metadata.

Provides functions to fetch book, author, and chapter data from the Audnex API
with region fallback support.

Public API:
    fetch_audnex_book: Fetch book metadata by ASIN (sync, sequential regions)
    fetch_audnex_book_parallel: Fetch book metadata by ASIN (async, parallel regions)
    fetch_audnex_book_with_cache: Fetch with automatic region caching (recommended)
    fetch_audnex_author: Fetch author metadata by ASIN
    fetch_audnex_chapters: Fetch chapter data by ASIN
    save_audnex_json: Save Audnex response to JSON file
    AudnexAsyncClient: Async client for parallel region racing
    RegionCache: ASIN → region cache for fast lookups
    FailureType: Failure type enum for cache invalidation
"""

from __future__ import annotations

# Async client (Phase 10.1)
from shelfr.metadata.audnex.async_client import (
    AudnexAsyncClient as AudnexAsyncClient,
)
from shelfr.metadata.audnex.async_client import (
    fetch_audnex_book_parallel as fetch_audnex_book_parallel,
)
from shelfr.metadata.audnex.async_client import (
    fetch_audnex_book_with_cache as fetch_audnex_book_with_cache,
)

# Private helpers (exposed for testing and backward compatibility)
from shelfr.metadata.audnex.client import (
    _fetch_audnex_book_region as _fetch_audnex_book_region,
)
from shelfr.metadata.audnex.client import (
    _fetch_audnex_chapters_region as _fetch_audnex_chapters_region,
)
from shelfr.metadata.audnex.client import (
    fetch_audnex_author as fetch_audnex_author,
)
from shelfr.metadata.audnex.client import (
    fetch_audnex_book as fetch_audnex_book,
)
from shelfr.metadata.audnex.client import (
    fetch_audnex_chapters as fetch_audnex_chapters,
)
from shelfr.metadata.audnex.client import (
    save_audnex_json as save_audnex_json,
)

# Region cache (Phase 10.2)
from shelfr.metadata.audnex.region_cache import (
    FailureType as FailureType,
)
from shelfr.metadata.audnex.region_cache import (
    RegionCache as RegionCache,
)
from shelfr.metadata.audnex.region_cache import (
    RegionCacheEntry as RegionCacheEntry,
)
from shelfr.metadata.audnex.region_cache import (
    get_default_region_cache as get_default_region_cache,
)

__all__ = [
    # Public API
    "AudnexAsyncClient",
    "FailureType",
    # Region cache (Phase 10.2)
    "RegionCache",
    "RegionCacheEntry",
    # Private (for testing/backward compat)
    "_fetch_audnex_book_region",
    "_fetch_audnex_chapters_region",
    "fetch_audnex_author",
    "fetch_audnex_book",
    "fetch_audnex_book_parallel",
    "fetch_audnex_book_with_cache",
    "fetch_audnex_chapters",
    "get_default_region_cache",
    "save_audnex_json",
]
