"""
Hardcover metadata provider.

Phase 12.3: Wraps the async Hardcover client in the provider interface
for use with the aggregator.

Hardcover provides rich content warnings that map to MAM flags,
which is the primary value add over Audnex.
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ..cache import CachedResult, MetadataCache, get_default_cache, make_cache_key
from ..hardcover.async_client import HardcoverAsyncClient
from ..hardcover.schemas import HardcoverSearchResult
from .base import ProviderKind
from .types import IdType, LookupContext, ProviderResult

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# Content warning → MAM flag mapping
# See docs/reference/metadata/architecture/archive/07-content-flags.md
HARDCOVER_TO_MAM_FLAGS: dict[str, str] = {
    # Violence-related → vio
    "Violence": "vio",
    "Gore": "vio",
    "murder": "vio",
    "war": "vio",
    "Torture": "vio",
    "Blood": "vio",
    "Gun violence": "vio",
    "violent imagery": "vio",
    "graphic violence": "vio",
    "death": "vio",
    "child death": "vio",
    "animal death": "vio",
    # Language → cLang
    "Strong language": "cLang",
    "Cursing": "cLang",
    "profanity": "cLang",
    # Sexual content → sSex (suggestive) or eSex (explicit)
    "Sexual content": "sSex",
    "Spicy": "sSex",
    "sexual themes": "sSex",
    "Rape": "eSex",
    "Sexual assault": "eSex",
    "Sexual violence": "eSex",
    "sexual harassment": "eSex",
    "explicit sex": "eSex",
    # LGBTQ+ → lgbt
    "LGBTQ+": "lgbt",
    "LGBT": "lgbt",
    "queer": "lgbt",
    "gay": "lgbt",
    "lesbian": "lgbt",
    "bisexual": "lgbt",
    "transgender": "lgbt",
}


class HardcoverProvider:
    """Hardcover API provider for content warnings and rich metadata.

    Primary value: granular content warnings → accurate MAM flags.

    ⚠️ LIFECYCLE: Must call startup() before use and shutdown() when done.

    Provides:
    - Content warnings (maps to MAM flags: vio, cLang, sSex, eSex, lgbt)
    - Genres and moods
    - Rating information

    Does NOT provide (use Audnex for these):
    - ASIN, ISBN
    - Chapters
    - Publisher, release date
    - Narrators

    Attributes:
        name: "hardcover"
        priority: 60 (lower than Audnex - supplementary data)
        kind: "network" (makes HTTP requests)
        is_override: False (cannot intentionally clear fields)
    """

    name: str = "hardcover"
    priority: int = 60  # Lower priority than Audnex (70)
    kind: ProviderKind = "network"
    is_override: bool = False

    def __init__(
        self,
        cache: MetadataCache | None = None,
        cache_ttl_seconds: int = 7 * 24 * 3600,  # 7 days default (book metadata changes slowly)
        match_threshold: float = 0.70,
    ):
        """Initialize Hardcover provider.

        Args:
            cache: Optional metadata cache instance. If None, uses default FileCache.
            cache_ttl_seconds: Cache TTL in seconds (default: 7 days)
            match_threshold: Minimum fuzzy match score (default: 0.70)
        """
        self._cache = cache or get_default_cache()
        self._cache_ttl_seconds = cache_ttl_seconds
        self._match_threshold = match_threshold

        # Async client - created in startup()
        self._client: HardcoverAsyncClient | None = None
        self._stack: AsyncExitStack | None = None
        self._started = False

    async def startup(self) -> None:
        """Initialize shared async client. Call once at process start.

        Creates the HTTP client and rate limiters. Must be called before
        any fetch() calls.

        Raises:
            RuntimeError: If already started
        """
        if self._started:
            raise RuntimeError("HardcoverProvider already started")

        self._stack = AsyncExitStack()
        self._client = await self._stack.enter_async_context(
            HardcoverAsyncClient(match_threshold=self._match_threshold)
        )
        self._started = True

        if not self._client.is_configured:
            logger.warning(
                "HardcoverProvider started but API key not configured. "
                "Set HARDCOVER_API_KEY environment variable."
            )
        else:
            logger.info("HardcoverProvider started (async client ready)")

    async def shutdown(self) -> None:
        """Close shared async client. Call at process end.

        Releases HTTP connections and cleans up resources.
        Safe to call multiple times (idempotent).
        """
        if self._stack:
            await self._stack.aclose()
            self._stack = None
        self._client = None
        self._started = False
        logger.info("HardcoverProvider shut down")

    @property
    def is_started(self) -> bool:
        """Check if provider is started and ready for use."""
        return self._started and self._client is not None

    def can_lookup(self, ctx: LookupContext, id_type: IdType) -> bool:
        """Check if provider can handle this lookup.

        Hardcover requires title for search - we can't lookup by ASIN directly.
        We need existing_abs_json with title, or we need to have been passed
        title info through another mechanism.

        For now, require ASIN in context (we'll get title from aggregator's
        prior Audnex fetch).
        """
        # We need ASIN to form cache key, but we search by title
        # The aggregator should call us AFTER Audnex populates title
        return id_type == "asin" and ctx.asin is not None

    async def fetch(self, ctx: LookupContext, id_type: IdType) -> ProviderResult:
        """Fetch metadata from Hardcover API.

        Uses title+author search since Hardcover doesn't support ASIN lookup.
        Relies on title/author being available from existing_abs_json or
        prior provider results.

        Args:
            ctx: Lookup context with ASIN and ideally existing metadata
            id_type: Must be "asin" for cache key consistency

        Returns:
            ProviderResult with content_flags and genres
        """
        if id_type != "asin" or not ctx.asin:
            return ProviderResult.failure(self.name, "ASIN required for cache key")

        if not self._started or not self._client:
            return ProviderResult.failure(self.name, "Provider not started")

        if not self._client.is_configured:
            return ProviderResult.failure(self.name, "API key not configured")

        # Extract title and author from existing metadata
        title, author = self._extract_title_author(ctx)
        if not title:
            return ProviderResult.failure(
                self.name, "Title required for Hardcover search (not available in context)"
            )

        # Check cache first
        cache_key = make_cache_key(
            provider=self.name,
            id_type="asin",
            identifier=ctx.asin,
            region="global",  # Hardcover is not region-specific
        )
        cached = await self._cache.get(cache_key)
        if cached and not cached.is_expired(self._cache_ttl_seconds):
            logger.debug("Cache hit for Hardcover ASIN %s", ctx.asin)
            return self._result_from_cache(cached)

        # Cache miss - search Hardcover
        logger.debug(
            "Cache miss for Hardcover ASIN %s, searching: '%s' by '%s'", ctx.asin, title, author
        )

        try:
            search_result = await self._client.search_book(title=title, author=author)

            if search_result is None:
                logger.debug("No Hardcover match for '%s' by '%s'", title, author)
                return ProviderResult.failure(self.name, "No match found")

            result = self._map_to_result(search_result)

            # Cache successful results
            if result.success:
                cached_result = CachedResult(
                    provider=self.name,
                    fields=result.fields,
                    confidence=result.confidence,
                    fetched_at=datetime.now(UTC).isoformat(),
                    raw_data={
                        "hardcover_id": search_result.book.id,
                        "match_score": search_result.match_score,
                    },
                )
                await self._cache.set(cache_key, cached_result)

            return result

        except Exception as e:
            logger.warning("Hardcover provider error for %s: %s", ctx.asin, e)
            return ProviderResult.failure(self.name, str(e))

    def _extract_title_author(self, ctx: LookupContext) -> tuple[str | None, str]:
        """Extract title and author from lookup context.

        Looks in existing_abs_json for title and author information.

        Args:
            ctx: Lookup context

        Returns:
            Tuple of (title, author) - author may be empty string
        """
        title: str | None = None
        author: str = ""

        if ctx.existing_abs_json:
            title = ctx.existing_abs_json.get("title")

            # Get first author name
            authors = ctx.existing_abs_json.get("authors", [])
            if authors:
                if isinstance(authors[0], dict):
                    author = authors[0].get("name", "")
                elif isinstance(authors[0], str):
                    author = authors[0]

        return title, author

    def _result_from_cache(self, cached: CachedResult) -> ProviderResult:
        """Reconstruct ProviderResult from cached data."""
        result = ProviderResult(provider=self.name, success=True)
        result.fields = cached.fields.copy()
        result.confidence = cached.confidence.copy()
        result.raw_data = cached.raw_data.copy() if cached.raw_data else {}
        result.cached = True
        return result

    def _map_to_result(self, search_result: HardcoverSearchResult) -> ProviderResult:
        """Map Hardcover search result to ProviderResult.

        Primary focus: content_flags mapping from content_warnings.
        """
        result = ProviderResult(provider=self.name, success=True)
        book = search_result.book

        # Map content warnings to MAM flags
        content_flags = self._map_content_warnings(book.warning_names)
        if content_flags:
            result.set_field("content_flags", content_flags, confidence=0.85)

        # Genres (lower confidence than Audnex since it's supplementary)
        if book.genre_names:
            genre_list = [{"name": g} for g in book.genre_names]
            result.set_field("genres", genre_list, confidence=0.7)

        # Rating
        if book.rating is not None:
            result.set_field("rating", book.rating, confidence=0.9)

        # Source provenance
        result.set_field("retrieved_via", "hardcover")
        result.set_field("source_platform", "Hardcover")
        result.set_field("source_id", str(book.id))
        result.set_field("source_id_type", "hardcover_id")
        result.set_field("source_url", f"https://hardcover.app/books/{book.id}")

        # Store match score in raw_data for debugging
        result.raw_data = {
            "hardcover_id": book.id,
            "match_score": search_result.match_score,
            "raw_warnings": book.warning_names,
        }

        return result

    def _map_content_warnings(self, warnings: list[str]) -> list[str]:
        """Map Hardcover content warnings to MAM flags.

        Uses case-insensitive matching against HARDCOVER_TO_MAM_FLAGS.

        Args:
            warnings: List of Hardcover content warning names

        Returns:
            Deduplicated list of MAM flag codes
        """
        flags: set[str] = set()

        for warning in warnings:
            warning_lower = warning.lower()

            # Try exact match first (case-insensitive)
            for hc_warning, mam_flag in HARDCOVER_TO_MAM_FLAGS.items():
                if hc_warning.lower() == warning_lower:
                    flags.add(mam_flag)
                    break
            else:
                # Try substring match for common patterns
                if any(
                    v in warning_lower
                    for v in ["violen", "gore", "blood", "murder", "death", "war"]
                ):
                    flags.add("vio")
                elif any(s in warning_lower for s in ["sex", "spicy", "eroti"]):
                    # Distinguish explicit from suggestive
                    if any(e in warning_lower for e in ["rape", "assault", "explicit"]):
                        flags.add("eSex")
                    else:
                        flags.add("sSex")
                elif any(lang in warning_lower for lang in ["language", "profan", "curs", "swear"]):
                    flags.add("cLang")
                elif any(
                    q in warning_lower
                    for q in ["lgbt", "queer", "gay", "lesbian", "bisex", "trans"]
                ):
                    flags.add("lgbt")

        return sorted(flags)
