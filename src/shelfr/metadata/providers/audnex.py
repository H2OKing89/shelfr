"""
Audnex metadata provider.

Wraps the async Audnex client (metadata/audnex/async_client.py) in the
provider interface for use with the aggregator.

Phase 10.4: Updated to use AudnexAsyncClient with lifecycle management.
The provider must be started before use and shut down when done.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from shelfr.utils.audible_urls import build_audible_url

from ..audnex.async_client import AudnexAsyncClient, fetch_audnex_book_with_cache
from ..cache import CachedResult, MetadataCache, get_default_cache, make_cache_key
from .base import ProviderKind
from .types import IdType, LookupContext, ProviderResult

if TYPE_CHECKING:
    from ..audnex.region_cache import RegionCache

logger = logging.getLogger(__name__)


class AudnexProvider:
    """Audnex API provider for audiobook metadata with lifecycle management.

    Primary source for audiobook metadata. Uses async client with staged region
    racing (Phase 10.1) and region caching (Phase 10.2).

    ⚠️ LIFECYCLE: Must call startup() before use and shutdown() when done.

    Provides:
    - Title, subtitle, authors, narrators
    - Series information (primary and secondary)
    - Genres, description, summary
    - Publisher, release date, language
    - Cover image URL
    - Runtime
    - Chapters (fetched using winning region - no re-race)

    Attributes:
        name: "audnex"
        priority: 70 (high priority - authoritative for audiobooks)
        kind: "network" (makes HTTP requests)
        is_override: False (cannot intentionally clear fields)

    Example:
        provider = AudnexProvider()
        await provider.startup()
        try:
            result = await provider.fetch(ctx, IdType.ASIN)
        finally:
            await provider.shutdown()
    """

    name: str = "audnex"
    priority: int = 70
    kind: ProviderKind = "network"
    is_override: bool = False

    def __init__(
        self,
        cache: MetadataCache | None = None,
        cache_ttl_seconds: int = 30 * 24 * 3600,  # 30 days default
        region_cache: RegionCache | None = None,
    ):
        """Initialize Audnex provider.

        Args:
            cache: Optional metadata cache instance. If None, uses default FileCache.
            cache_ttl_seconds: Cache TTL in seconds (default: 30 days)
            region_cache: Optional region cache for ASIN→region mappings.
                         If None, uses a new instance with default settings.
        """
        self._cache = cache or get_default_cache()
        self._cache_ttl_seconds = cache_ttl_seconds
        self._region_cache = region_cache

        # Async client - created in startup()
        self._client: AudnexAsyncClient | None = None
        self._started = False

    async def startup(self) -> None:
        """Initialize shared async client. Call once at process start.

        Creates the HTTP client and rate limiters. Must be called before
        any fetch() calls.

        Raises:
            RuntimeError: If already started
        """
        if self._started:
            raise RuntimeError("AudnexProvider already started")

        self._client = AudnexAsyncClient()
        await self._client.__aenter__()
        self._started = True
        logger.info("AudnexProvider started (async client ready)")

    async def shutdown(self) -> None:
        """Close shared async client. Call at process end.

        Releases HTTP connections and cleans up resources.
        Safe to call multiple times (idempotent).
        """
        if self._client:
            await self._client.__aexit__(None, None, None)
            self._client = None
        self._started = False
        logger.info("AudnexProvider shut down")

    @property
    def is_started(self) -> bool:
        """Check if provider is started and ready for use."""
        return self._started and self._client is not None

    def can_lookup(self, ctx: LookupContext, id_type: IdType) -> bool:
        """Check if provider can handle this lookup.

        Audnex only supports ASIN lookups.
        """
        return id_type == "asin" and ctx.asin is not None

    async def fetch(self, ctx: LookupContext, id_type: IdType) -> ProviderResult:
        """Fetch metadata from Audnex API using async client with region racing.

        Uses staged region racing (Phase 10.1) and region caching (Phase 10.2)
        for efficient lookups. Chapters are fetched using the winning region
        to avoid re-racing.

        Args:
            ctx: Lookup context with ASIN and options
            id_type: Must be "asin" for Audnex

        Returns:
            ProviderResult with metadata fields or failure
        """
        if id_type != "asin" or not ctx.asin:
            return ProviderResult.failure(self.name, "ASIN required for Audnex lookup")

        # Validate ASIN format (10 alphanumeric characters)
        if not re.match(r"^[A-Z0-9]{10}$", ctx.asin):
            return ProviderResult.failure(self.name, f"Invalid ASIN format: {ctx.asin}")

        # Check metadata cache first (provider-level cache)
        cache_key = make_cache_key(
            provider=self.name,
            id_type="asin",
            identifier=ctx.asin,
            region="parallel",  # Use "parallel" since we race regions
        )
        cached = await self._cache.get(cache_key)
        if cached and not cached.is_expired(self._cache_ttl_seconds):
            logger.debug("Cache hit for Audnex ASIN %s", ctx.asin)
            return self._result_from_cache(cached)

        # Cache miss - fetch from API
        logger.debug("Cache miss for Audnex ASIN %s", ctx.asin)
        try:
            # Use shared client if available (lifecycle-managed)
            # Falls back to temporary client for backwards compatibility
            data, region = await fetch_audnex_book_with_cache(
                asin=ctx.asin,
                client=self._client,
                region_cache=self._region_cache,
            )

            if data is None:
                return ProviderResult.failure(self.name, f"ASIN {ctx.asin} not found in Audnex")

            result = self._map_to_result(data, region)

            # Store raw data for backward compatibility (orchestration needs this)
            result.raw_data = {"audnex": data, "region": region}

            # Fetch chapters using SAME region (don't re-race!)
            if ctx.include_chapters and region and self._client:
                try:
                    chapters_data = await self._client.fetch_chapters(ctx.asin, region)
                    if chapters_data:
                        chapters_list = chapters_data.get("chapters", [])
                        if chapters_list:
                            result.set_field("chapters", self._map_chapters(chapters_list))
                            logger.debug(
                                "Fetched %d chapters for %s (region=%s)",
                                len(chapters_list),
                                ctx.asin,
                                region,
                            )
                except Exception as e:
                    # Chapters are optional - don't fail the whole request
                    logger.warning("Failed to fetch chapters for %s: %s", ctx.asin, e)

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

    def _map_chapters(self, chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Map Audnex chapters response to canonical chapter format.

        Args:
            chapters: Raw chapters from Audnex API

        Returns:
            List of chapter dicts with canonical field names
        """
        mapped = []
        for ch in chapters:
            chapter = {}
            if title := ch.get("title"):
                chapter["title"] = title
            if (start := ch.get("startOffsetMs")) is not None:
                chapter["start"] = start / 1000.0  # Convert ms to seconds
            if (length := ch.get("lengthMs")) is not None:
                chapter["end"] = (ch.get("startOffsetMs", 0) + length) / 1000.0
            if chapter:
                mapped.append(chapter)
        return mapped

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

        # Content flags - infer from Audnex data
        # Note: Audnex doesn't provide cLang or vio data - those require manual override
        # IMPORTANT: isAdult is a weak signal - map to sSex (suggestive), NOT eSex (explicit)
        # See docs/reference/metadata/architecture/07-content-flags.md for rationale
        content_flags: list[str] = []
        if is_adult:
            content_flags.append("sSex")  # Weak signal: at most suggestive, never explicit
        if format_type and isinstance(format_type, str) and format_type.lower() == "abridged":
            content_flags.append("abridged")

        # Check genres for LGBTQ+ tag (Audnex provides this as genre/tag)
        if genres := data.get("genres"):
            for genre in genres:
                genre_name = genre.get("name", "")
                if not isinstance(genre_name, str):
                    continue
                genre_name_lower = genre_name.lower()
                if "lgbtq" in genre_name_lower or "lgbt" in genre_name_lower:
                    if "lgbt" not in content_flags:
                        content_flags.append("lgbt")
                    break

        if content_flags:
            result.set_field("content_flags", content_flags)

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

        # Source provenance (Phase 10.3)
        # Split "retrieval provider" (API) from "source platform" (storefront)
        asin = data.get("asin")
        if asin:
            result.set_field("retrieved_via", "audnex")  # The API we used
            result.set_field("source_platform", "Audible")  # What the data represents
            result.set_field("source_id", asin)
            result.set_field("source_id_type", "asin")

            # Region-aware source URL
            effective_region = region or "us"
            result.set_field("source_region", effective_region)
            result.set_field("source_url", build_audible_url(asin, effective_region))

        return result
