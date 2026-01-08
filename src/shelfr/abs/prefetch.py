"""Async metadata prefetching for batch imports.

Phase 11.3: Pre-fetch Audnex metadata for all staged books in parallel
before sequential filesystem operations.

This module provides functions to:
1. Extract ASINs from staged folders
2. Prefetch metadata in parallel using the Phase 10 Audnex async client
3. Cache results for use during import

Usage:
    async with AudnexAsyncClient() as audnex_client:
        cache = await prefetch_metadata_async(
            staging_folders,
            audnex_client,
        )

    # Use cache during sync import
    for folder in staging_folders:
        asin = extract_asin(folder.name)
        if asin and asin in cache:
            audnex_data, region = cache[asin]
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from shelfr.abs.asin import extract_asin
from shelfr.abs.importer import parse_mam_folder_name

if TYPE_CHECKING:
    from shelfr.metadata.audnex.async_client import AudnexAsyncClient
    from shelfr.metadata.audnex.region_cache import RegionCache

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class PrefetchResult:
    """Result of metadata prefetch for a single ASIN."""

    asin: str
    data: dict[str, Any] | None
    region: str | None
    elapsed: float  # seconds


@dataclass
class PrefetchSummary:
    """Summary of batch metadata prefetch operation."""

    total_asins: int
    success_count: int
    failure_count: int
    skipped_count: int  # No ASIN in folder
    elapsed: float  # total seconds
    asins_per_second: float

    @property
    def success_rate(self) -> float:
        """Return success rate as a percentage."""
        if self.total_asins == 0:
            return 0.0
        return (self.success_count / self.total_asins) * 100


# Type alias for the metadata cache (maps ASIN -> (metadata, region))
# Named AsinMetadataCache to avoid collision with shelfr.metadata.MetadataCache Protocol
AsinMetadataCache = dict[str, tuple[dict[str, Any] | None, str | None]]


# =============================================================================
# Core Functions
# =============================================================================


def extract_asins_from_folders(folders: list[Path]) -> dict[Path, str | None]:
    """Extract ASINs from folder names.

    Args:
        folders: List of staging folder paths

    Returns:
        Dict mapping folder path to ASIN (or None if not found)
    """
    result: dict[Path, str | None] = {}
    for folder in folders:
        # Try folder name first
        asin = extract_asin(folder.name)

        # If not found, try parsing folder name for embedded ASIN
        if not asin:
            try:
                parsed = parse_mam_folder_name(folder.name)
                asin = parsed.asin
            except Exception:
                logger.debug("Could not parse folder name: %s", folder.name)

        result[folder] = asin
    return result


async def prefetch_metadata_async(
    folders: list[Path],
    audnex_client: AudnexAsyncClient,
    *,
    region_cache: RegionCache | None = None,
    include_chapters: bool = False,
) -> tuple[AsinMetadataCache, PrefetchSummary]:
    """Prefetch Audnex metadata for all staged folders in parallel.

    Uses the Phase 10 AudnexAsyncClient.fetch_batch() for efficient
    parallel fetching with rate limiting and concurrency control.

    Args:
        folders: List of staging folder paths
        audnex_client: Initialized AudnexAsyncClient (must be in async context)
        region_cache: Optional RegionCache for faster lookups
        include_chapters: Whether to fetch chapters (default False)

    Returns:
        Tuple of (cache, summary):
        - cache: Dict mapping ASIN to (metadata, region) tuple
        - summary: PrefetchSummary with statistics
    """
    start_time = time.perf_counter()

    # Extract ASINs from folders
    folder_asins = extract_asins_from_folders(folders)

    # Get unique ASINs (skip None values)
    unique_asins = list({asin for asin in folder_asins.values() if asin})
    # Count folders without ASINs (not deduplicated folders)
    skipped_count = sum(1 for asin in folder_asins.values() if asin is None)

    if not unique_asins:
        logger.info("No ASINs found in %d folders, skipping prefetch", len(folders))
        return {}, PrefetchSummary(
            total_asins=0,
            success_count=0,
            failure_count=0,
            skipped_count=skipped_count,
            elapsed=0.0,
            asins_per_second=0.0,
        )

    logger.info(
        "Prefetching metadata for %d unique ASINs from %d folders",
        len(unique_asins),
        len(folders),
    )

    # Use the batch fetch method from Phase 10
    results = await audnex_client.fetch_batch(
        unique_asins,
        region_cache=region_cache,
        include_chapters=include_chapters,
    )

    # Build cache from results
    cache: AsinMetadataCache = {}
    success_count = 0
    failure_count = 0

    for asin, data, region in results:
        cache[asin] = (data, region)
        if data is not None:
            success_count += 1
        else:
            failure_count += 1

    elapsed = time.perf_counter() - start_time
    asins_per_second = len(unique_asins) / elapsed if elapsed > 0 else 0.0

    summary = PrefetchSummary(
        total_asins=len(unique_asins),
        success_count=success_count,
        failure_count=failure_count,
        skipped_count=skipped_count,
        elapsed=elapsed,
        asins_per_second=asins_per_second,
    )

    logger.info(
        "Prefetch complete: %d/%d succeeded (%.1f%%) in %.2fs (%.1f ASINs/sec)",
        success_count,
        len(unique_asins),
        summary.success_rate,
        elapsed,
        asins_per_second,
    )

    return cache, summary


async def prefetch_single_async(
    asin: str,
    audnex_client: AudnexAsyncClient,
    *,
    region_cache: RegionCache | None = None,
) -> PrefetchResult:
    """Prefetch metadata for a single ASIN.

    Convenience function for single-ASIN lookups.

    Args:
        asin: ASIN to fetch
        audnex_client: Initialized AudnexAsyncClient
        region_cache: Optional RegionCache

    Returns:
        PrefetchResult with metadata and timing
    """
    from shelfr.metadata.audnex.region_cache import get_default_region_cache

    start_time = time.perf_counter()

    # Get cached region if available
    cache = region_cache if region_cache is not None else get_default_region_cache()
    cached_region = await cache.get(asin)

    # Fetch
    data, region = await audnex_client.fetch_book_parallel(asin, cached_region)

    # Update cache on success
    if region:
        await cache.set(asin, region)

    elapsed = time.perf_counter() - start_time

    return PrefetchResult(
        asin=asin,
        data=data,
        region=region,
        elapsed=elapsed,
    )


# =============================================================================
# Helper Functions
# =============================================================================


def get_cached_metadata(
    cache: AsinMetadataCache,
    asin: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Get metadata from prefetch cache.

    Args:
        cache: AsinMetadataCache from prefetch_metadata_async()
        asin: ASIN to look up

    Returns:
        (metadata, region) tuple or (None, None) if not in cache
    """
    return cache.get(asin, (None, None))


def has_cached_metadata(cache: AsinMetadataCache, asin: str) -> bool:
    """Check if ASIN has successfully cached metadata.

    Args:
        cache: AsinMetadataCache from prefetch_metadata_async()
        asin: ASIN to check

    Returns:
        True if metadata is cached and not None
    """
    if asin not in cache:
        return False
    data, _ = cache[asin]
    return data is not None
