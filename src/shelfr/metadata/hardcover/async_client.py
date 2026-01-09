"""
Async Hardcover API client with rate limiting.

Phase 12.1: GraphQL client for Hardcover book search and metadata.

The Hardcover API uses GraphQL with a Typesense search backend for fast,
relevant book matching. Rate limit is 60 requests/minute.

Usage:
    async with HardcoverAsyncClient() as client:
        result = await client.search_book(title="It", author="Stephen King")
        if result and result.is_confident_match:
            print(result.book.warning_names)  # ['Violence', 'Gore', ...]
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import TYPE_CHECKING, Any

import httpx
from aiolimiter import AsyncLimiter
from rapidfuzz import fuzz

from shelfr.utils.circuit_breaker import CircuitOpenError, hardcover_breaker

from .schemas import HardcoverBook, HardcoverSearchResult

if TYPE_CHECKING:
    from types import TracebackType

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# API Configuration
API_ENDPOINT = "https://api.hardcover.app/v1/graphql"
DEFAULT_RATE_LIMIT = 60  # requests per minute (Hardcover limit)
DEFAULT_TIMEOUT = 30.0  # seconds
DEFAULT_RETRIES = 3
USER_AGENT = "Shelfr-Hardcover-Client/1.0.0"

# Matching configuration
DEFAULT_MATCH_THRESHOLD = 0.70  # 70% similarity required


# =============================================================================
# GraphQL Queries
# =============================================================================

SEARCH_BOOKS_QUERY = """
query SearchBooks($query: String!, $queryType: String!, $perPage: Int!) {
  search(query: $query, query_type: $queryType, per_page: $perPage) {
    results
  }
}
"""


# =============================================================================
# HardcoverAsyncClient Class
# =============================================================================


class HardcoverAsyncClient:
    """Async client for Hardcover GraphQL API with rate limiting.

    ⚠️ Create ONE instance per process and share it.
    The rate limiter is per-instance — multiple instances = 429s.

    Usage:
        async with HardcoverAsyncClient() as client:
            result = await client.search_book(title="It", author="Stephen King")
            if result:
                print(result.book.content_warnings)

    Attributes:
        api_key: Hardcover API key (from env or explicit)
        match_threshold: Minimum fuzzy match score (0.0-1.0)
    """

    def __init__(
        self,
        api_key: str | None = None,
        rate_limit_per_min: int = DEFAULT_RATE_LIMIT,
        match_threshold: float = DEFAULT_MATCH_THRESHOLD,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        """Initialize Hardcover async client.

        Args:
            api_key: Hardcover API key. If None, reads from HARDCOVER_API_KEY env var.
            rate_limit_per_min: Maximum requests per minute (default: 60)
            match_threshold: Minimum fuzzy match score (default: 0.70)
            timeout: Request timeout in seconds (default: 30.0)
        """
        self._api_key = api_key or os.getenv("HARDCOVER_API_KEY", "")
        self._match_threshold = match_threshold
        self._timeout = timeout

        # HTTP client - created on __aenter__
        self._http_client: httpx.AsyncClient | None = None

        # Rate limiter: X requests per 60 seconds
        self._rate_limiter = AsyncLimiter(rate_limit_per_min, 60.0)

        # Stats tracking
        self._request_count = 0
        self._error_count = 0

    @property
    def api_key(self) -> str | None:
        """Get the API key."""
        return self._api_key

    @property
    def is_configured(self) -> bool:
        """Check if API key is configured."""
        return bool(self._api_key)

    async def __aenter__(self) -> HardcoverAsyncClient:
        """Enter async context - create HTTP client."""
        if not self.is_configured:
            logger.warning("Hardcover API key not configured. Set HARDCOVER_API_KEY env var.")

        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout),
            limits=httpx.Limits(
                max_connections=10,
                max_keepalive_connections=5,
                keepalive_expiry=30.0,
            ),
        )
        logger.debug("HardcoverAsyncClient initialized")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit async context - close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        logger.debug(
            "HardcoverAsyncClient closed (requests=%d, errors=%d)",
            self._request_count,
            self._error_count,
        )

    def _get_headers(self) -> dict[str, str]:
        """Build request headers with auth."""
        return {
            "authorization": f"Bearer {self._api_key}",
            "content-type": "application/json",
            "user-agent": USER_AGENT,
        }

    async def _execute_graphql(
        self,
        query: str,
        variables: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Execute a GraphQL query with rate limiting and retry.

        Args:
            query: GraphQL query string
            variables: Query variables

        Returns:
            Response data dict or None on failure
        """
        if not self._http_client:
            raise RuntimeError("Client not initialized. Use 'async with' context.")

        if not self.is_configured:
            logger.warning("Hardcover API key not configured, skipping request")
            return None

        payload = {"query": query, "variables": variables}

        for attempt in range(DEFAULT_RETRIES):
            try:
                with hardcover_breaker:
                    async with self._rate_limiter:
                        self._request_count += 1
                        response = await self._http_client.post(
                            API_ENDPOINT,
                            json=payload,
                            headers=self._get_headers(),
                        )

                    if response.status_code == 200:
                        data = response.json()

                        # Check for GraphQL errors
                        if "errors" in data:
                            logger.error("GraphQL errors: %s", data["errors"])
                            self._error_count += 1
                            return None

                        result: dict[str, Any] | None = data.get("data")
                        return result

                    elif response.status_code == 401:
                        logger.error("Hardcover API auth failed - check API key")
                        self._error_count += 1
                        return None

                    elif response.status_code == 403:
                        logger.error("Hardcover API forbidden - check permissions")
                        self._error_count += 1
                        return None

                    elif response.status_code == 429:
                        retry_after = int(response.headers.get("retry-after", 60))
                        logger.warning("Rate limited. Waiting %ds before retry", retry_after)
                        await asyncio.sleep(retry_after)
                        continue

                    elif response.status_code >= 500:
                        self._error_count += 1
                        if attempt < DEFAULT_RETRIES - 1:
                            wait_time = 2.0 * (attempt + 1)
                            logger.warning(
                                "Server error %d, retrying in %.1fs",
                                response.status_code,
                                wait_time,
                            )
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            logger.error("Server error persists after retries")
                            return None

                    else:
                        logger.warning("Unexpected status: %d", response.status_code)
                        self._error_count += 1
                        return None

            except CircuitOpenError:
                logger.warning("Hardcover circuit breaker open, skipping request")
                return None

            except httpx.TimeoutException:
                self._error_count += 1
                if attempt < DEFAULT_RETRIES - 1:
                    logger.warning("Request timeout, retrying...")
                    await asyncio.sleep(1.0)
                    continue
                else:
                    logger.error("Request timeout after retries")
                    return None

            except httpx.RequestError as e:
                self._error_count += 1
                logger.error("Request error: %s", e)
                return None

        return None

    async def search_book(
        self,
        title: str,
        author: str,
        *,
        per_page: int = 10,
    ) -> HardcoverSearchResult | None:
        """Search for a book by title and author.

        Uses Hardcover's Typesense-powered search with title-first strategy,
        then validates author match from results.

        Search strategy:
        1. Search by title only (combined queries return companion books)
        2. Score results using weighted title (70%) + author (30%) matching
        3. Return best match above confidence threshold

        Args:
            title: Book title
            author: Primary author name
            per_page: Maximum results to fetch (default: 10)

        Returns:
            HardcoverSearchResult if a confident match found, else None
        """
        # Search by title only - combined queries cause issues with companion books
        search_query = title.strip()

        logger.debug("Searching Hardcover: title='%s', author='%s'", title, author)

        data = await self._execute_graphql(
            SEARCH_BOOKS_QUERY,
            {
                "query": search_query,
                "queryType": "book",
                "perPage": per_page,
            },
        )

        if not data:
            return None

        # Parse Typesense results
        results = data.get("search", {}).get("results")
        if not results:
            logger.debug("No search results for '%s'", search_query)
            return None

        # Results may be JSON string or dict
        if isinstance(results, str):
            try:
                results = json.loads(results)
            except json.JSONDecodeError:
                logger.error("Failed to parse search results JSON")
                return None

        hits = results.get("hits", [])
        if not hits:
            logger.debug("No hits for '%s'", search_query)
            return None

        # Find best match using fuzzy matching
        # Strategy: Weight title match heavily, author is secondary
        best_match: HardcoverBook | None = None
        best_score = 0.0

        # Normalize inputs for matching
        query_title = title.lower().strip()
        query_author = author.lower().strip() if author else ""
        # Normalize author: remove periods, extra spaces
        query_author_normalized = query_author.replace(".", "").replace("  ", " ")

        for hit in hits:
            doc = hit.get("document", {})
            if not doc:
                continue

            hit_title = doc.get("title", "").lower().strip()
            hit_authors = doc.get("author_names", [])
            hit_author = hit_authors[0].lower().strip() if hit_authors else ""
            hit_author_normalized = hit_author.replace(".", "").replace("  ", " ")

            # Calculate title match (most important)
            title_score = fuzz.ratio(query_title, hit_title) / 100.0

            # Calculate author match (if we have both)
            if query_author and hit_author:
                # Try both normalized and raw comparisons
                author_score_raw = fuzz.ratio(query_author, hit_author) / 100.0
                author_score_norm = (
                    fuzz.ratio(query_author_normalized, hit_author_normalized) / 100.0
                )
                # Also try partial matching for "E L James" vs "E.L. James"
                author_score_partial = (
                    fuzz.partial_ratio(query_author_normalized, hit_author_normalized) / 100.0
                )
                author_score = max(author_score_raw, author_score_norm, author_score_partial)
            elif not query_author:
                # No author provided - only match on title
                author_score = 1.0
            else:
                # Author provided but hit has no author
                author_score = 0.5  # Neutral

            # Combined score: 70% title, 30% author
            combined_score = (title_score * 0.7) + (author_score * 0.3)

            # Bonus for exact title match
            if title_score > 0.95:
                combined_score = min(1.0, combined_score + 0.1)

            if combined_score > best_score:
                best_score = combined_score
                best_match = HardcoverBook.from_search_hit(doc)

        if not best_match:
            logger.debug("No valid matches for '%s'", search_query)
            return None

        result = HardcoverSearchResult(
            book=best_match,
            match_score=best_score,
            search_query=search_query,
        )

        if result.is_confident_match:
            logger.debug(
                "Found match: '%s' (score=%.2f, warnings=%d)",
                best_match.title,
                best_score,
                len(best_match.content_warnings),
            )
            return result
        else:
            logger.debug(
                "Low confidence match: '%s' (score=%.2f < %.2f threshold)",
                best_match.title,
                best_score,
                self._match_threshold,
            )
            return None

    async def search_book_by_title(
        self,
        title: str,
        *,
        per_page: int = 5,
    ) -> HardcoverSearchResult | None:
        """Search for a book by title only.

        Useful when author is unknown or unreliable.

        Args:
            title: Book title
            per_page: Maximum results to fetch

        Returns:
            HardcoverSearchResult if a confident match found, else None
        """
        return await self.search_book(title=title, author="", per_page=per_page)
