"""
Audnex metadata provider.

Wraps the existing Audnex client (metadata/audnex/client.py) in the
provider interface for use with the aggregator.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from typing import Any

from aiolimiter import AsyncLimiter

from ..audnex.client import fetch_audnex_book
from ..cache import CachedResult, MetadataCache, get_default_cache, make_cache_key
from .base import ProviderKind
from .types import IdType, LookupContext, ProviderResult

logger = logging.getLogger(__name__)


class AudnexProvider:
    """Audnex API provider for audiobook metadata.

    Primary source for audiobook metadata. Provides:
    - Title, subtitle, authors, narrators
    - Series information (primary and secondary)
    - Genres, description, summary
    - Publisher, release date, language
    - Cover image URL
    - Runtime

    Attributes:
        name: "audnex"
        priority: 10 (high priority - authoritative for audiobooks)
        kind: "network" (makes HTTP requests)
        is_override: False (cannot intentionally clear fields)
    """

    name: str = "audnex"
    priority: int = 10
    kind: ProviderKind = "network"
    is_override: bool = False

    def __init__(
        self,
        region: str | None = None,
        cache: MetadataCache | None = None,
        cache_ttl_seconds: int = 30 * 24 * 3600,  # 30 days default
        rate_limit: float = 10.0,  # requests per second
    ):
        """Initialize Audnex provider.

        Args:
            region: Optional fixed region to use. If None, uses
                    configured region fallback from settings.
            cache: Optional cache instance. If None, uses default FileCache.
            cache_ttl_seconds: Cache TTL in seconds (default: 30 days)
            rate_limit: Maximum requests per second (default: 10)
        """
        self._region = region
        self._cache = cache or get_default_cache()
        self._cache_ttl_seconds = cache_ttl_seconds
        # AsyncLimiter(max_rate, time_period=1.0) = max_rate requests per second
        self._rate_limiter = AsyncLimiter(max_rate=rate_limit, time_period=1.0)

    def can_lookup(self, ctx: LookupContext, id_type: IdType) -> bool:
        """Check if provider can handle this lookup.

        Audnex only supports ASIN lookups.
        """
        return id_type == "asin" and ctx.asin is not None

    async def fetch(self, ctx: LookupContext, id_type: IdType) -> ProviderResult:
        """Fetch metadata from Audnex API (with caching).

        Wraps sync HTTP client in asyncio.to_thread() to avoid blocking.
        Checks cache first; only hits API on cache miss.
        """
        if id_type != "asin" or not ctx.asin:
            return ProviderResult.failure(self.name, "ASIN required for Audnex lookup")

        # Validate ASIN format (10 alphanumeric characters)
        if not re.match(r"^[A-Z0-9]{10}$", ctx.asin):
            return ProviderResult.failure(self.name, f"Invalid ASIN format: {ctx.asin}")

        # Check cache first
        cache_key = make_cache_key(
            provider=self.name,
            id_type="asin",
            identifier=ctx.asin,
            region=self._region or "us",
        )
        cached = await self._cache.get(cache_key)
        if cached and not cached.is_expired(self._cache_ttl_seconds):
            logger.debug("Cache hit for Audnex ASIN %s", ctx.asin)
            return self._result_from_cache(cached)

        # Cache miss - fetch from API
        logger.debug("Cache miss for Audnex ASIN %s", ctx.asin)
        try:
            # Apply rate limiting before making request
            async with self._rate_limiter:
                # Run sync HTTP call in thread pool
                data, region = await asyncio.to_thread(fetch_audnex_book, ctx.asin, self._region)

            if data is None:
                return ProviderResult.failure(self.name, f"ASIN {ctx.asin} not found in Audnex")

            result = self._map_to_result(data, region)

            # Store raw data for backward compatibility (orchestration needs this)
            result.raw_data = {"audnex": data, "region": region}

            # Cache successful results (including raw_data)
            if result.success:
                cached_result = CachedResult(
                    provider=self.name,
                    fields=result.fields,
                    confidence=result.confidence,
                    fetched_at=datetime.now(UTC).isoformat(),
                    raw_data=result.raw_data,
                )
                await self._cache.set(cache_key, cached_result)

            return result

        except Exception as e:
            logger.warning("Audnex provider error for %s: %s", ctx.asin, e)
            return ProviderResult.failure(self.name, str(e))

    def _result_from_cache(self, cached: CachedResult) -> ProviderResult:
        """Reconstruct ProviderResult from cached data.

        Args:
            cached: Cached result from cache

        Returns:
            ProviderResult with cached fields, confidence, and raw_data
        """
        result = ProviderResult(provider=self.name, success=True)
        result.fields = cached.fields.copy()
        result.confidence = cached.confidence.copy()
        result.raw_data = cached.raw_data.copy() if cached.raw_data else {}
        result.cached = True
        return result

    def _map_to_result(self, data: dict[str, Any], region: str | None) -> ProviderResult:
        """Map Audnex API response to ProviderResult.

        Maps Audnex field names to canonical field names.
        """
        result = ProviderResult(provider=self.name, success=True)

        # Title and subtitle
        if title := data.get("title"):
            result.set_field("title", title)
        if subtitle := data.get("subtitle"):
            result.set_field("subtitle", subtitle)

        # Authors - convert to list of dicts with name/asin
        if authors := data.get("authors"):
            author_list = [
                {"name": a.get("name"), "asin": a.get("asin")} for a in authors if a.get("name")
            ]
            if author_list:
                result.set_field("authors", author_list)

        # Narrators - convert to list of dicts with name/asin
        if narrators := data.get("narrators"):
            narrator_list = [
                {"name": n.get("name"), "asin": n.get("asin")} for n in narrators if n.get("name")
            ]
            if narrator_list:
                result.set_field("narrators", narrator_list)

        # Series - extract name and position from primary series
        if series_primary := data.get("seriesPrimary"):
            if series_name := series_primary.get("name"):
                result.set_field("series_name", series_name)
            if series_position := series_primary.get("position"):
                result.set_field("series_position", str(series_position))

        # Text fields
        if description := data.get("description"):
            result.set_field("description", description)
        if summary := data.get("summary"):
            result.set_field("summary", summary)

        # Publisher and dates
        if publisher := data.get("publisherName"):
            result.set_field("publisher", publisher)
        if release_date := data.get("releaseDate"):
            result.set_field("release_date", release_date)
        if copyright_year := data.get("copyright"):
            result.set_field("copyright", copyright_year)

        # Classification
        if language := data.get("language"):
            result.set_field("language", language)
        if format_type := data.get("formatType"):
            result.set_field("format_type", format_type)
        if literature_type := data.get("literatureType"):
            result.set_field("literature_type", literature_type)
        # Use explicit None check to preserve False values
        is_adult = data.get("isAdult")
        if is_adult is not None:
            result.set_field("is_adult", is_adult)

        # Genres - convert to list of dicts
        if genres := data.get("genres"):
            genre_list = [
                {"name": g.get("name"), "asin": g.get("asin"), "type": g.get("type")}
                for g in genres
                if g.get("name")
            ]
            if genre_list:
                result.set_field("genres", genre_list)

        # Media
        if image := data.get("image"):
            result.set_field("cover_url", image)
        if rating := data.get("rating"):
            result.set_field("rating", rating)
        if isbn := data.get("isbn"):
            result.set_field("isbn", isbn)

        # Runtime (Audnex provides minutes)
        if runtime_min := data.get("runtimeLengthMin"):
            result.set_field("duration_seconds", runtime_min * 60)

        return result
