"""
Async Audnex client with staged region racing.

Phase 10.1: Replaces sequential region fallback with parallel "race" semantics.
Instead of trying regions one at a time (up to 30s worst case), we:
  1. Check region cache for cached ASIN → region mapping
  2. Stage 1: Race top 3 regions (us, uk, de) with 1.5s timeout
  3. Stage 2: Race ALL regions if Stage 1 fails

Typical case: 1-3 requests per ASIN
Worst case: 10 requests (rare)
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

import httpx
from aiolimiter import AsyncLimiter
from pydantic import ValidationError

from shelfr.config import get_settings
from shelfr.schemas.audnex import validate_audnex_book, validate_audnex_chapters
from shelfr.utils.circuit_breaker import (
    CircuitOpenError,
    CircuitState,
    audnex_breaker,
)

if TYPE_CHECKING:
    from .region_cache import RegionCache

if TYPE_CHECKING:
    from types import TracebackType

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Stage 1: Common regions (covers ~95% of ASINs)
STAGE_1_REGIONS = ["us", "uk", "de"]
STAGE_1_TIMEOUT = 1.5  # seconds

# Stage 2: ALL regions (not just remaining - timeout means Stage 1 might have had the answer)
ALL_REGIONS = ["us", "uk", "de", "au", "ca", "es", "fr", "in", "it", "jp"]
STAGE_2_TIMEOUT = 8.5  # seconds


# =============================================================================
# Validation Helpers
# =============================================================================


def _is_valid_for_race(data: dict[str, Any], expected_asin: str) -> bool:
    """Minimal validation for race winner selection.

    Be lenient: APIs sometimes violate their own spec.
    We just need enough to confirm this is the right book.

    Args:
        data: API response data
        expected_asin: The ASIN we requested

    Returns:
        True if response is valid enough to be a race winner
    """
    if not data:
        return False
    # ASIN must match (some APIs return different content on region mismatch)
    if data.get("asin", "").upper() != expected_asin.upper():
        return False
    # Must have title and at least one author
    if not data.get("title"):
        return False
    return bool(data.get("authors"))


def _validate_and_log_quality(data: dict[str, Any], asin: str) -> None:
    """Log warnings for missing optional fields (don't reject the response).

    This is Level 2 validation - called AFTER winner is chosen.
    """
    expected_fields = [
        "description",
        "formatType",
        "language",
        "publisherName",
        "rating",
        "releaseDate",
        "runtimeLengthMin",
        "summary",
    ]
    missing = [f for f in expected_fields if not data.get(f)]
    if missing:
        logger.warning(
            "Audnex response for %s missing fields: %s (continuing anyway)",
            asin,
            missing,
        )


# =============================================================================
# AudnexAsyncClient Class
# =============================================================================


class AudnexAsyncClient:
    """Async client for Audnex API with proper lifecycle management.

    ⚠️ Create ONE instance per process and share it.
    The rate limiter is per-instance — multiple instances = multiple limiters = 429s.

    Usage:
        async with AudnexAsyncClient() as client:
            for asin in asins:
                data, region = await client.fetch_book_parallel(asin)
                if region:
                    chapters = await client.fetch_chapters(asin, region)

    Attributes:
        base_url: Audnex API base URL
        timeout: httpx.Timeout configuration
    """

    def __init__(
        self,
        rate_limit_per_min: int = 90,
        burst_limit: float = 10.0,
        burst_period: float = 5.0,
    ):
        """Initialize Audnex async client.

        Args:
            rate_limit_per_min: Maximum requests per minute (sustained rate)
            burst_limit: Maximum requests in burst period
            burst_period: Burst period in seconds
        """
        self._http_client: httpx.AsyncClient | None = None

        # Dual limiters: minute-scale (sustained) AND burst protection
        # This prevents both:
        # - Sustained overuse (90/min)
        # - Burst spikes that hit fixed-window limits (10 req / 5s)
        self._minute_limiter = AsyncLimiter(rate_limit_per_min, 60.0)
        self._burst_limiter = AsyncLimiter(burst_limit, burst_period)

        # Get settings for base_url and timeout
        settings = get_settings()
        self._base_url = settings.audnex.base_url
        self._default_timeout = settings.audnex.timeout_seconds

    async def __aenter__(self) -> AudnexAsyncClient:
        """Create HTTP client on context entry."""
        self._http_client = httpx.AsyncClient(
            http2=True,
            timeout=httpx.Timeout(
                connect=5.0,
                read=self._default_timeout,
                write=5.0,
                pool=5.0,
            ),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Close HTTP client on context exit."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Get HTTP client, ensuring it's initialized."""
        if self._http_client is None:
            raise RuntimeError(
                "AudnexAsyncClient must be used as async context manager: "
                "async with AudnexAsyncClient() as client: ..."
            )
        return self._http_client

    # -------------------------------------------------------------------------
    # Low-Level Request Methods
    # -------------------------------------------------------------------------

    async def _fetch_book_region(
        self,
        asin: str,
        region: str,
    ) -> dict[str, Any] | None:
        """Fetch book metadata for a specific region.

        Internal method - respects rate limits but doesn't do region fallback.

        Args:
            asin: Audible ASIN
            region: Region code (us, uk, etc.)

        Returns:
            Parsed JSON response or None if not found

        Raises:
            httpx.HTTPStatusError: On non-404/500 HTTP errors
            httpx.TimeoutException: On timeout
            CircuitOpenError: If circuit breaker is open
        """
        url = f"{self._base_url}/books/{asin}"
        params = {"region": region}

        logger.debug("Fetching Audnex book: %s (region=%s)", asin, region)

        # Circuit breaker check BEFORE rate limiting to avoid wasting tokens
        if audnex_breaker.state == CircuitState.OPEN:
            raise CircuitOpenError("audnex", audnex_breaker.recovery_timeout)

        # Apply rate limiting
        async with self._minute_limiter, self._burst_limiter:
            # Use circuit breaker context to record success/failure
            with audnex_breaker:
                response = await self.client.get(url, params=params)

            # 404/500 are authoritative "not found"
            if response.status_code in (404, 500):
                logger.debug(
                    "ASIN %s not found in region %s (HTTP %d)", asin, region, response.status_code
                )
                return None

            # 401/403/429 - auth/rate limit issues
            if response.status_code in (401, 403, 429):
                logger.warning(
                    "Auth/rate limit error for %s (region=%s): HTTP %d",
                    asin,
                    region,
                    response.status_code,
                )
                # Raise to signal rate limiting (may need backoff)
                response.raise_for_status()

            # Other HTTP errors
            response.raise_for_status()

            data: dict[str, Any] = response.json()

            # Validate response structure (warns but doesn't fail)
            try:
                validate_audnex_book(data)
            except ValidationError as e:
                logger.warning("Audnex book validation warning for %s: %s", asin, e)

            return data

    async def _fetch_chapters_region(
        self,
        asin: str,
        region: str,
    ) -> dict[str, Any] | None:
        """Fetch chapter data for a specific region.

        Args:
            asin: Audible ASIN
            region: Region code

        Returns:
            Parsed JSON response or None if not found
        """
        url = f"{self._base_url}/books/{asin}/chapters"
        params = {"region": region}

        logger.debug("Fetching Audnex chapters: %s (region=%s)", asin, region)

        # Circuit breaker check BEFORE rate limiting to avoid wasting tokens
        if audnex_breaker.state == CircuitState.OPEN:
            raise CircuitOpenError("audnex", audnex_breaker.recovery_timeout)

        async with self._minute_limiter, self._burst_limiter:
            # Use circuit breaker context to record success/failure
            with audnex_breaker:
                response = await self.client.get(url, params=params)

            if response.status_code in (404, 500):
                logger.debug("Chapters for %s not found in region %s", asin, region)
                return None

            if response.status_code in (401, 403, 429):
                logger.warning(
                    "Auth/rate limit error for chapters %s (region=%s): HTTP %d",
                    asin,
                    region,
                    response.status_code,
                )
                response.raise_for_status()

            response.raise_for_status()

            data: dict[str, Any] = response.json()

            try:
                validate_audnex_chapters(data)
            except ValidationError as e:
                logger.warning("Audnex chapters validation warning for %s: %s", asin, e)

            return data

    # -------------------------------------------------------------------------
    # Race Logic
    # -------------------------------------------------------------------------

    async def _probe_region(
        self,
        asin: str,
        region: str,
    ) -> tuple[str, dict[str, Any] | None, Exception | None]:
        """Probe a single region, returning (region, data, error).

        This is the unit of work for the race pattern.
        """
        try:
            data = await self._fetch_book_region(asin, region)
            return region, data, None
        except httpx.HTTPStatusError as e:
            # Include the error for classification (404 vs transient)
            return region, None, e
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            return region, None, e
        except CircuitOpenError as e:
            return region, None, e
        except Exception as e:
            logger.exception("Unexpected error probing region %s for %s", region, asin)
            return region, None, e

    async def _race_regions(
        self,
        asin: str,
        regions: list[str],
        timeout: float,
    ) -> tuple[tuple[dict[str, Any] | None, str | None], set[str]]:
        """Race multiple regions, first valid response wins.

        Args:
            asin: ASIN to fetch
            regions: List of regions to try
            timeout: Overall timeout for the race

        Returns:
            Tuple of:
            - (data, winning_region) or (None, None)
            - Set of regions that definitively returned 404 (for Stage 2 exclusion)
        """
        if not regions:
            return (None, None), set()

        definitive_404s: set[str] = set()
        winner: tuple[dict[str, Any] | None, str | None] = (None, None)

        # Create tasks for all regions
        tasks = [
            asyncio.create_task(self._probe_region(asin, r), name=f"audnex-{r}") for r in regions
        ]

        try:
            for coro in asyncio.as_completed(tasks, timeout=timeout):
                try:
                    region, data, err = await coro
                except asyncio.CancelledError:
                    # Task was cancelled, skip it
                    continue

                if err:
                    logger.debug("Region %s failed for %s: %s", region, asin, err)
                    # Timeouts and connection errors are NOT definitive 404s
                    # Only HTTP 4xx errors are definitive
                    if isinstance(err, httpx.HTTPStatusError) and err.response.status_code == 404:
                        definitive_404s.add(region)
                    continue

                # data=None with err=None means authoritative "not found" (404/500)
                if data is None:
                    logger.debug("Region %s: authoritative not-found for %s", region, asin)
                    definitive_404s.add(region)
                    continue

                # Check if response is valid
                if _is_valid_for_race(data, asin):
                    winner = (data, region)
                    logger.debug("Race winner for %s: region %s", asin, region)
                    break
                else:
                    logger.debug(
                        "Region %s returned data for %s but failed validation",
                        region,
                        asin,
                    )

        except TimeoutError:
            logger.debug("Race timeout for %s after %.1fs", asin, timeout)

        # Cancel remaining tasks AND await them to avoid "Task destroyed" warnings
        for task in tasks:
            if not task.done():
                task.cancel()

        # Drain cancelled tasks cleanly
        await asyncio.gather(*tasks, return_exceptions=True)

        return winner, definitive_404s

    async def _staged_race(
        self,
        asin: str,
        cached_region: str | None = None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Two-stage race: common regions first, then ALL regions if needed.

        If a cached region is provided, tries that first (single request).

        Args:
            asin: ASIN to fetch
            cached_region: Optional cached region to try first

        Returns:
            (data, winning_region) or (None, None)
        """
        # Fast path: try cached region first
        if cached_region:
            logger.debug("Trying cached region %s for %s", cached_region, asin)
            region, data, err = await self._probe_region(asin, cached_region)
            if data and _is_valid_for_race(data, asin):
                logger.debug("Cache hit: %s found in cached region %s", asin, region)
                return data, region
            if err:
                logger.debug("Cached region %s failed for %s: %s", cached_region, asin, err)

        # Stage 1: Race common regions
        logger.debug("Stage 1: Racing regions %s for %s", STAGE_1_REGIONS, asin)
        winner, stage1_404s = await self._race_regions(asin, STAGE_1_REGIONS, STAGE_1_TIMEOUT)

        if winner[0] is not None:
            _validate_and_log_quality(winner[0], asin)
            return winner

        # Stage 2: Race ALL regions (not just remaining!)
        # If Stage 1 timed out (vs 404), the correct region might still be us/uk/de
        # Only skip regions that definitively returned 404
        stage2_regions = [r for r in ALL_REGIONS if r not in stage1_404s]
        logger.debug(
            "Stage 2: Racing regions %s for %s (excluded 404s: %s)",
            stage2_regions,
            asin,
            stage1_404s,
        )

        winner, _ = await self._race_regions(asin, stage2_regions, STAGE_2_TIMEOUT)

        if winner[0] is not None:
            _validate_and_log_quality(winner[0], asin)

        return winner

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def fetch_book_parallel(
        self,
        asin: str,
        cached_region: str | None = None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Fetch book metadata using staged region racing.

        This is the main entry point for parallel region lookup.

        Args:
            asin: Audible ASIN
            cached_region: Optional cached region to try first (from RegionCache)

        Returns:
            (metadata, winning_region) or (None, None) if all fail
        """
        return await self._staged_race(asin, cached_region)

    async def fetch_chapters(
        self,
        asin: str,
        region: str,
    ) -> dict[str, Any] | None:
        """Fetch chapters using known region.

        ⚠️ Call this AFTER fetch_book_parallel() with the winning region.
        Don't re-race for chapters - use the region that worked for book.

        Args:
            asin: Audible ASIN
            region: Region where book was found

        Returns:
            Chapter data or None
        """
        try:
            data = await self._fetch_chapters_region(asin, region)
            if data:
                chapter_count = len(data.get("chapters", []))
                logger.info(
                    "Fetched %d chapters for %s (region=%s)",
                    chapter_count,
                    asin,
                    region,
                )
            return data
        except Exception as e:
            logger.warning("Failed to fetch chapters for %s (region=%s): %s", asin, region, e)
            return None


# =============================================================================
# Convenience Function
# =============================================================================


async def fetch_audnex_book_parallel(
    asin: str,
    client: AudnexAsyncClient | None = None,
    cached_region: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Fetch book metadata using staged region racing.

    Convenience function that creates a client if not provided.
    For batch operations, pass a shared client to avoid creating
    multiple rate limiters.

    Args:
        asin: Audible ASIN
        client: Optional shared AudnexAsyncClient instance
        cached_region: Optional cached region to try first

    Returns:
        (metadata, winning_region) or (None, None)
    """
    if client:
        return await client.fetch_book_parallel(asin, cached_region)

    # Create temporary client for single lookup
    async with AudnexAsyncClient() as temp_client:
        return await temp_client.fetch_book_parallel(asin, cached_region)


async def fetch_audnex_book_with_cache(
    asin: str,
    client: AudnexAsyncClient | None = None,
    region_cache: RegionCache | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Fetch book metadata with automatic region caching.

    This is the recommended entry point for production use.
    It automatically:
    1. Checks the region cache for a known region
    2. Falls back to staged race if not cached
    3. Caches the winning region for future lookups
    4. Records failures for cache invalidation

    Args:
        asin: Audible ASIN
        client: Optional shared AudnexAsyncClient instance
        region_cache: Optional RegionCache instance (uses default if not provided)

    Returns:
        (metadata, winning_region) or (None, None) if all fail
    """
    from .region_cache import (
        FailureType,
        get_default_region_cache,
    )

    # Use explicit None check - RegionCache is falsy when empty due to __len__
    cache = region_cache if region_cache is not None else get_default_region_cache()

    # Check cache for known region
    cached_region = await cache.get(asin)

    if client:
        data, region = await client.fetch_book_parallel(asin, cached_region)
    else:
        async with AudnexAsyncClient() as temp_client:
            data, region = await temp_client.fetch_book_parallel(asin, cached_region)

    # Update cache based on result
    if region:
        # Success! Cache the winning region
        await cache.set(asin, region)
        if cached_region and cached_region != region:
            # Region changed - log for observability
            logger.info(
                "Region changed for %s: cached=%s, actual=%s",
                asin,
                cached_region,
                region,
            )
    elif cached_region:
        # Failed with a cached region - record failure as TRANSIENT
        # Since we don't know if it's 404 or transient, use TRANSIENT
        # to avoid fast invalidation of potentially-correct cached regions
        # during service outages (timeouts/5xx across all regions)
        await cache.record_failure(asin, FailureType.TRANSIENT)

    return data, region
