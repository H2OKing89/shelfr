"""Async HTTP client for Audiobookshelf API.

Phase 11.1: Async version of AbsClient for better performance with large libraries.

Provides async methods to interact with an Audiobookshelf server including:
- Connection testing (ping/authorize)
- Library listing
- Library item retrieval with parallel pagination
- Library scanning

Usage:
    async with AbsAsyncClient.from_config(config) as client:
        user = await client.authorize()
        libraries = await client.get_libraries()
        items = await client.get_all_library_items(library_id)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
from aiolimiter import AsyncLimiter

from shelfr.schemas.abs import (
    validate_authorize_response,
    validate_libraries_response,
    validate_library_items_response,
)

if TYPE_CHECKING:
    from types import TracebackType

    from shelfr.config import AudiobookshelfConfig

logger = logging.getLogger(__name__)


# =============================================================================
# Exceptions (reuse from sync client)
# =============================================================================


class AbsAuthError(Exception):
    """Raised when authentication with Audiobookshelf fails."""


class AbsConnectionError(Exception):
    """Raised when unable to connect to Audiobookshelf server."""


class AbsApiError(Exception):
    """Raised when API returns an unexpected error."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


# =============================================================================
# Data Classes (same as sync client)
# =============================================================================


@dataclass
class AbsUser:
    """Authenticated user information from ABS."""

    id: str
    username: str
    user_type: str
    is_active: bool
    has_admin: bool


@dataclass
class AbsLibrary:
    """Library information from ABS."""

    id: str
    name: str
    media_type: str
    folders: list[str]
    display_order: int

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> AbsLibrary:
        """Create from API response dict."""
        folders = [f.get("fullPath", "") for f in data.get("folders", [])]
        return cls(
            id=data["id"],
            name=data["name"],
            media_type=data.get("mediaType", "book"),
            folders=folders,
            display_order=data.get("displayOrder", 0),
        )


@dataclass
class AbsLibraryItem:
    """Library item (book/podcast) from ABS."""

    id: str
    library_id: str
    path: str
    rel_path: str
    is_missing: bool
    media_type: str
    title: str
    subtitle: str | None
    author_name: str | None
    narrator_name: str | None
    series_name: str | None
    asin: str | None
    isbn: str | None
    duration: float
    size: int
    added_at: int
    updated_at: int

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> AbsLibraryItem:
        """Create from API response dict."""
        media = data.get("media", {})
        metadata = media.get("metadata", {})

        return cls(
            id=data["id"],
            library_id=data.get("libraryId", ""),
            path=data.get("path", ""),
            rel_path=data.get("relPath", ""),
            is_missing=data.get("isMissing", False),
            media_type=data.get("mediaType", "book"),
            title=metadata.get("title", ""),
            subtitle=metadata.get("subtitle"),
            author_name=metadata.get("authorName"),
            narrator_name=metadata.get("narratorName"),
            series_name=metadata.get("seriesName"),
            asin=metadata.get("asin"),
            isbn=metadata.get("isbn"),
            duration=media.get("duration", 0.0),
            size=data.get("size", 0),
            added_at=data.get("addedAt", 0),
            updated_at=data.get("updatedAt", 0),
        )


# =============================================================================
# Constants
# =============================================================================

# Default rate limits for ABS API
DEFAULT_RATE_LIMIT_PER_MIN = 120  # ABS is usually local, can be higher
DEFAULT_BURST_LIMIT = 20.0
DEFAULT_BURST_PERIOD = 1.0

# Connection limits
MAX_CONNECTIONS = 20
MAX_KEEPALIVE = 10

# Pagination
DEFAULT_BATCH_SIZE = 100
MAX_CONCURRENT_PAGES = 5  # Limit concurrent page fetches


# =============================================================================
# AbsAsyncClient Class
# =============================================================================


class AbsAsyncClient:
    """Async HTTP client for interacting with Audiobookshelf API.

    ⚠️ Use as context manager for proper connection lifecycle.

    Example:
        async with AbsAsyncClient(host="http://localhost:13378", api_key="key") as client:
            user = await client.authorize()
            print(f"Connected as: {user.username}")
            for lib in await client.get_libraries():
                print(f"Library: {lib.name}")
    """

    def __init__(
        self,
        host: str,
        api_key: str,
        timeout: float = 30.0,
        rate_limit_per_min: int = DEFAULT_RATE_LIMIT_PER_MIN,
        burst_limit: float = DEFAULT_BURST_LIMIT,
        burst_period: float = DEFAULT_BURST_PERIOD,
    ) -> None:
        """Initialize the async client.

        Args:
            host: Audiobookshelf server URL (e.g., "http://localhost:13378")
            api_key: API token for authentication
            timeout: Request timeout in seconds
            rate_limit_per_min: Maximum requests per minute
            burst_limit: Maximum requests in burst period
            burst_period: Burst period in seconds
        """
        # Normalize host URL (remove trailing slash)
        self.host = host.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

        # HTTP client (created on context entry)
        self._client: httpx.AsyncClient | None = None

        # Rate limiters (Phase 10 pattern)
        self._minute_limiter = AsyncLimiter(rate_limit_per_min, 60.0)
        self._burst_limiter = AsyncLimiter(burst_limit, burst_period)

        # Semaphore for concurrent page fetches
        self._page_semaphore = asyncio.Semaphore(MAX_CONCURRENT_PAGES)

        # In-memory cache: {library_id: [AbsLibraryItem, ...]}
        self._library_cache: dict[str, list[AbsLibraryItem]] = {}

    @classmethod
    def from_config(cls, config: AudiobookshelfConfig) -> AbsAsyncClient:
        """Create client from AudiobookshelfConfig.

        Args:
            config: Audiobookshelf configuration dataclass

        Returns:
            Configured AbsAsyncClient instance
        """
        return cls(
            host=config.host,
            api_key=config.api_key,
            timeout=float(config.timeout_seconds),
        )

    async def __aenter__(self) -> AbsAsyncClient:
        """Create HTTP client on context entry."""
        self._client = httpx.AsyncClient(
            base_url=self.host,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(
                connect=5.0,
                read=self.timeout,
                write=5.0,
                pool=5.0,
            ),
            limits=httpx.Limits(
                max_connections=MAX_CONNECTIONS,
                max_keepalive_connections=MAX_KEEPALIVE,
            ),
            http2=True,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Close HTTP client on context exit."""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._library_cache.clear()

    @property
    def client(self) -> httpx.AsyncClient:
        """Get HTTP client, ensuring it's initialized."""
        if self._client is None:
            raise RuntimeError(
                "AbsAsyncClient not initialized. Use 'async with AbsAsyncClient(...) as client:'"
            )
        return self._client

    async def _acquire_rate_limit(self) -> None:
        """Acquire both rate limiters before making a request."""
        await self._minute_limiter.acquire()
        await self._burst_limiter.acquire()

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make an HTTP request to the API with rate limiting.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: API endpoint path (e.g., "/api/libraries")
            **kwargs: Additional arguments to pass to httpx

        Returns:
            Response object

        Raises:
            AbsAuthError: If authentication fails (401)
            AbsApiError: If API returns an error
            AbsConnectionError: If unable to connect
        """
        await self._acquire_rate_limit()

        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.ConnectError as e:
            raise AbsConnectionError(f"Failed to connect to {self.host}: {e}") from e
        except httpx.TimeoutException as e:
            raise AbsConnectionError(f"Request to {self.host} timed out: {e}") from e

        if response.status_code == 401:
            raise AbsAuthError("Invalid API key or unauthorized access")

        if response.status_code == 404:
            raise AbsApiError(f"Resource not found: {path}", status_code=404)

        if response.status_code >= 400:
            raise AbsApiError(
                f"API error: {response.status_code} - {response.text}",
                status_code=response.status_code,
            )

        return response

    # =========================================================================
    # Authentication
    # =========================================================================

    async def authorize(self) -> AbsUser:
        """Test connection and get authenticated user info.

        Returns:
            AbsUser with authenticated user details

        Raises:
            AbsAuthError: If authentication fails
            AbsConnectionError: If unable to connect
        """
        logger.debug("Testing authorization with ABS server")
        response = await self._request("GET", "/api/me")
        data = response.json()

        # Validate response structure using Pydantic schema
        # /api/me returns user object directly (not wrapped in {"user": ...})
        validated = validate_authorize_response({"user": data})
        user = validated.user

        return AbsUser(
            id=user.id,
            username=user.username,
            user_type=user.type,
            is_active=user.is_active,
            has_admin=user.has_admin,
        )

    async def ping(self) -> bool:
        """Quick connection test without full authorization.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            await self.authorize()
            return True
        except (AbsAuthError, AbsConnectionError, AbsApiError):
            return False

    # =========================================================================
    # Libraries
    # =========================================================================

    async def get_libraries(self) -> list[AbsLibrary]:
        """Get all libraries from the server.

        Returns:
            List of AbsLibrary objects

        Raises:
            AbsAuthError: If authentication fails
            AbsConnectionError: If unable to connect
        """
        logger.debug("Fetching libraries from ABS")
        response = await self._request("GET", "/api/libraries")
        data = response.json()

        # Validate response structure using Pydantic schema
        validated = validate_libraries_response(data)

        libraries = []
        for lib_schema in validated.libraries:
            libraries.append(
                AbsLibrary(
                    id=lib_schema.id,
                    name=lib_schema.name,
                    media_type=lib_schema.media_type,
                    folders=lib_schema.get_folder_paths(),
                    display_order=lib_schema.display_order,
                )
            )

        logger.info(f"Found {len(libraries)} libraries in ABS")
        return libraries

    # =========================================================================
    # Library Items
    # =========================================================================

    async def get_library_items(
        self,
        library_id: str,
        limit: int = DEFAULT_BATCH_SIZE,
        page: int = 0,
        sort: str = "addedAt",
        desc: bool = True,
        filter_str: str | None = None,
    ) -> tuple[list[AbsLibraryItem], int]:
        """Get items from a library (single page).

        Args:
            library_id: ID of the library to query
            limit: Maximum items to return per page
            page: Page number for pagination (0-indexed)
            sort: Field to sort by
            desc: Sort descending if True
            filter_str: Optional filter string (base64 encoded)

        Returns:
            Tuple of (list of items, total count)

        Raises:
            AbsAuthError: If authentication fails
            AbsConnectionError: If unable to connect
            AbsApiError: If library not found
        """
        logger.debug(f"Fetching items from library {library_id} (page {page})")

        params: dict[str, Any] = {
            "limit": limit,
            "page": page,
            "sort": sort,
            "desc": "1" if desc else "0",
        }
        if filter_str:
            params["filter"] = filter_str

        response = await self._request("GET", f"/api/libraries/{library_id}/items", params=params)
        data = response.json()

        # Validate response structure using Pydantic schema
        validated = validate_library_items_response(data)

        items = []
        for item_schema in validated.results:
            items.append(
                AbsLibraryItem(
                    id=item_schema.id,
                    library_id=item_schema.library_id,
                    path=item_schema.path,
                    rel_path=item_schema.rel_path,
                    is_missing=item_schema.is_missing,
                    media_type=item_schema.media_type,
                    title=item_schema.title,
                    subtitle=item_schema.subtitle,
                    author_name=item_schema.author_name,
                    narrator_name=item_schema.narrator_name,
                    series_name=item_schema.series_name,
                    asin=item_schema.asin,
                    isbn=item_schema.isbn,
                    duration=item_schema.duration,
                    size=item_schema.size,
                    added_at=item_schema.added_at,
                    updated_at=item_schema.updated_at,
                )
            )

        total = validated.total
        logger.debug(f"Fetched page {page} with {len(items)} items (library total: {total})")
        return items, total

    async def _fetch_page(
        self,
        library_id: str,
        page: int,
        batch_size: int,
    ) -> list[AbsLibraryItem]:
        """Fetch a single page with semaphore control."""
        async with self._page_semaphore:
            items, _ = await self.get_library_items(library_id, limit=batch_size, page=page)
            return items

    async def get_all_library_items(
        self,
        library_id: str,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> list[AbsLibraryItem]:
        """Get all items from a library with parallel pagination.

        Unlike the sync version which fetches pages sequentially, this
        fetches the first page to get total count, then fetches remaining
        pages in parallel.

        Args:
            library_id: ID of the library to query
            batch_size: Number of items to fetch per page

        Returns:
            Complete list of all items in the library
        """
        # Fetch first page to get total count
        first_items, total = await self.get_library_items(library_id, limit=batch_size, page=0)

        if len(first_items) >= total:
            logger.info(f"Fetched all {len(first_items)} items from library {library_id}")
            return first_items

        # Calculate remaining pages needed
        remaining = total - len(first_items)
        pages_needed = (remaining + batch_size - 1) // batch_size  # Ceiling division

        logger.info(
            f"Fetching {pages_needed} additional pages in parallel "
            f"({remaining} remaining items)"
        )

        # Fetch remaining pages in parallel (with semaphore limiting)
        tasks = [
            self._fetch_page(library_id, page, batch_size) for page in range(1, pages_needed + 1)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Combine results
        all_items = list(first_items)
        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                logger.error(f"Failed to fetch page {i + 1}: {result}")
                # Continue with partial results rather than failing completely
                continue
            # result is now known to be list[AbsLibraryItem]
            all_items.extend(result)

        logger.info(f"Fetched {len(all_items)}/{total} items from library {library_id}")
        return all_items

    async def get_library_items_cached(
        self,
        library_id: str,
        *,
        force_refresh: bool = False,
    ) -> list[AbsLibraryItem]:
        """Get all items from a library, caching in memory for this session.

        This is the preferred method for import operations - fetch once, use many.
        Cache is cleared when client is closed or force_refresh=True.

        Args:
            library_id: ID of the library to query
            force_refresh: If True, bypass cache and fetch fresh data

        Returns:
            List of all items in the library (from cache if available)
        """
        if force_refresh or library_id not in self._library_cache:
            logger.info(f"Fetching all items from library {library_id}")
            items = await self.get_all_library_items(library_id)
            self._library_cache[library_id] = items
            logger.info(f"Cached {len(items)} items for library {library_id}")
        else:
            cached_count = len(self._library_cache[library_id])
            logger.debug(f"Using cached {cached_count} items for library {library_id}")

        return self._library_cache[library_id]

    def clear_cache(self, library_id: str | None = None) -> None:
        """Clear the in-memory library cache.

        Args:
            library_id: If provided, clear only that library's cache.
                       If None, clear all cached libraries.
        """
        if library_id:
            self._library_cache.pop(library_id, None)
        else:
            self._library_cache.clear()

    # =========================================================================
    # Item Details
    # =========================================================================

    async def get_item_details(self, item_id: str) -> dict[str, Any]:
        """Get detailed information about a specific item.

        Args:
            item_id: ID of the library item

        Returns:
            Full item details as a dictionary

        Raises:
            AbsApiError: If item not found
        """
        logger.debug(f"Fetching details for item {item_id}")
        response = await self._request("GET", f"/api/items/{item_id}")
        result: dict[str, Any] = response.json()
        return result

    # =========================================================================
    # Library Scanning
    # =========================================================================

    async def scan_library(self, library_id: str, force: bool = False) -> bool:
        """Trigger a library scan.

        Args:
            library_id: ID of the library to scan
            force: Force rescan of all items

        Returns:
            True if scan was triggered successfully
        """
        logger.info(f"Triggering scan for library {library_id} (force={force})")

        params = {"force": "1"} if force else {}
        response = await self._request("POST", f"/api/libraries/{library_id}/scan", params=params)

        # ABS returns 200 on success
        return response.status_code == 200

    async def scan_libraries(self, library_ids: list[str], force: bool = False) -> dict[str, bool]:
        """Trigger scans for multiple libraries in parallel.

        Args:
            library_ids: List of library IDs to scan
            force: Force rescan of all items

        Returns:
            Dict mapping library_id to success status
        """
        if not library_ids:
            return {}

        logger.info(f"Triggering parallel scans for {len(library_ids)} libraries")

        async def _scan_one(lib_id: str) -> tuple[str, bool]:
            try:
                success = await self.scan_library(lib_id, force=force)
                return lib_id, success
            except Exception as e:
                logger.warning(f"Failed to scan library {lib_id}: {e}")
                return lib_id, False

        results = await asyncio.gather(*[_scan_one(lib_id) for lib_id in library_ids])
        return dict(results)

    # =========================================================================
    # Metadata Search
    # =========================================================================

    async def search_books(
        self,
        title: str,
        author: str | None = None,
        provider: str = "audible",
    ) -> list[dict[str, Any]]:
        """Search for books via ABS metadata provider.

        Uses ABS as a proxy to search Audible (or other providers) for book metadata.
        This is useful for resolving ASINs for books that don't have them.

        Args:
            title: Book title to search for
            author: Optional author name to narrow results
            provider: Metadata provider (default: "audible")

        Returns:
            List of search results with book metadata including ASIN

        Raises:
            AbsConnectionError: If unable to connect
            AbsApiError: If API returns an error
        """
        logger.debug(f"Searching ABS for books: title={title!r}, author={author!r}")

        params: dict[str, str] = {
            "title": title,
            "provider": provider,
        }
        if author:
            params["author"] = author

        response = await self._request("GET", "/api/search/books", params=params)
        results = response.json()

        # API returns a list directly
        if not isinstance(results, list):
            logger.warning(f"Unexpected search response type: {type(results)}")
            return []

        logger.debug(f"Search returned {len(results)} results")
        return results

    async def search_books_batch(
        self,
        queries: list[tuple[str, str | None]],
    ) -> list[list[dict[str, Any]]]:
        """Search for multiple books in parallel.

        Args:
            queries: List of (title, author) tuples to search

        Returns:
            List of search results, one per query
        """
        if not queries:
            return []

        logger.info(f"Searching ABS for {len(queries)} books in parallel")

        async def _search_one(title: str, author: str | None) -> list[dict[str, Any]]:
            try:
                return await self.search_books(title, author)
            except Exception as e:
                logger.warning(f"Search failed for {title!r}: {e}")
                return []

        results = await asyncio.gather(*[_search_one(t, a) for t, a in queries])
        return list(results)
