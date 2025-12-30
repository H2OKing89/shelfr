"""HTTP client for Audiobookshelf API.

Provides methods to interact with an Audiobookshelf server including:
- Connection testing (ping/authorize)
- Library listing
- Library item retrieval (with in-memory caching)
- Library scanning
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from shelfr.schemas.abs import (
    validate_authorize_response,
    validate_libraries_response,
    validate_library_items_response,
)
from shelfr.utils.retry import NETWORK_EXCEPTIONS, retry_with_backoff

if TYPE_CHECKING:
    from shelfr.config import AudiobookshelfConfig

logger = logging.getLogger(__name__)


class AbsAuthError(Exception):
    """Raised when authentication with Audiobookshelf fails."""


class AbsConnectionError(Exception):
    """Raised when unable to connect to Audiobookshelf server."""


class AbsApiError(Exception):
    """Raised when API returns an unexpected error."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


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


class AbsClient:
    """HTTP client for interacting with Audiobookshelf API.

    Example:
        >>> from shelfr.abs import AbsClient
        >>> client = AbsClient(host="http://localhost:13378", api_key="your-key")
        >>> user = client.authorize()
        >>> print(f"Connected as: {user.username}")
        >>> for lib in client.get_libraries():
        ...     print(f"Library: {lib.name}")
    """

    def __init__(
        self,
        host: str,
        api_key: str,
        timeout: float = 30.0,
    ) -> None:
        """Initialize the client.

        Args:
            host: Audiobookshelf server URL (e.g., "http://localhost:13378")
            api_key: API token for authentication
            timeout: Request timeout in seconds
        """
        # Normalize host URL (remove trailing slash)
        self.host = host.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._client: httpx.Client | None = None
        # In-memory cache: {library_id: [AbsLibraryItem, ...]}
        # Populated on first access per library, cleared on close()
        self._library_cache: dict[str, list[AbsLibraryItem]] = {}

    @classmethod
    def from_config(cls, config: AudiobookshelfConfig) -> AbsClient:
        """Create client from AudiobookshelfConfig.

        Args:
            config: Audiobookshelf configuration dataclass

        Returns:
            Configured AbsClient instance
        """
        return cls(
            host=config.host,
            api_key=config.api_key,
            timeout=float(config.timeout_seconds),
        )

    def _get_client(self) -> httpx.Client:
        """Get or create the httpx client."""
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.host,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
                http2=True,
            )
        return self._client

    def close(self) -> None:
        """Close the HTTP client connection and clear cache."""
        if self._client is not None:
            self._client.close()
            self._client = None
        self._library_cache.clear()

    def __enter__(self) -> AbsClient:
        """Context manager entry."""
        return self

    def __exit__(self, *args: object) -> None:
        """Context manager exit."""
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make an HTTP request to the API.

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
        client = self._get_client()

        # Let httpx exceptions propagate so retry decorator can catch them
        # They will be caught and wrapped in the public methods after retries exhaust
        response = client.request(method, path, **kwargs)

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

    @retry_with_backoff(max_attempts=3, base_delay=1.0, exceptions=NETWORK_EXCEPTIONS)
    def authorize(self) -> AbsUser:
        """Test connection and get authenticated user info.

        Returns:
            AbsUser with authenticated user details

        Raises:
            AbsAuthError: If authentication fails
            AbsConnectionError: If unable to connect
        """
        logger.debug("Testing authorization with ABS server")
        try:
            response = self._request("GET", "/api/me")
        except httpx.ConnectError as e:
            raise AbsConnectionError(f"Failed to connect to {self.host}: {e}") from e
        except httpx.TimeoutException as e:
            raise AbsConnectionError(f"Request to {self.host} timed out: {e}") from e

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
            has_admin=user.has_admin,  # Uses type == "admin" check from schema
        )

    def ping(self) -> bool:
        """Quick connection test without full authorization.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            self.authorize()
            return True
        except (AbsAuthError, AbsConnectionError, AbsApiError):
            return False

    @retry_with_backoff(max_attempts=3, base_delay=1.0, exceptions=NETWORK_EXCEPTIONS)
    def get_libraries(self) -> list[AbsLibrary]:
        """Get all libraries from the server.

        Returns:
            List of AbsLibrary objects

        Raises:
            AbsAuthError: If authentication fails
            AbsConnectionError: If unable to connect
        """
        logger.debug("Fetching libraries from ABS")
        try:
            response = self._request("GET", "/api/libraries")
        except httpx.ConnectError as e:
            raise AbsConnectionError(f"Failed to connect to {self.host}: {e}") from e
        except httpx.TimeoutException as e:
            raise AbsConnectionError(f"Request to {self.host} timed out: {e}") from e

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

    @retry_with_backoff(max_attempts=3, base_delay=1.0, exceptions=NETWORK_EXCEPTIONS)
    def get_library_items(
        self,
        library_id: str,
        limit: int = 0,
        page: int = 0,
        sort: str = "addedAt",
        desc: bool = True,
        filter_str: str | None = None,
    ) -> tuple[list[AbsLibraryItem], int]:
        """Get items from a library.

        Args:
            library_id: ID of the library to query
            limit: Maximum items to return (0 = all)
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
        logger.debug(f"Fetching items from library {library_id}")

        params: dict[str, Any] = {
            "sort": sort,
            "desc": "1" if desc else "0",
        }
        if limit > 0:
            params["limit"] = limit
            params["page"] = page
        if filter_str:
            params["filter"] = filter_str

        try:
            response = self._request("GET", f"/api/libraries/{library_id}/items", params=params)
        except httpx.ConnectError as e:
            raise AbsConnectionError(f"Failed to connect to {self.host}: {e}") from e
        except httpx.TimeoutException as e:
            raise AbsConnectionError(f"Request to {self.host} timed out: {e}") from e

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
        logger.debug(f"Fetched page with {len(items)} items (library total: {total})")
        return items, total

    def get_all_library_items(
        self,
        library_id: str,
        batch_size: int = 100,
    ) -> list[AbsLibraryItem]:
        """Get all items from a library, handling pagination automatically.

        Args:
            library_id: ID of the library to query
            batch_size: Number of items to fetch per request

        Returns:
            Complete list of all items in the library
        """
        all_items: list[AbsLibraryItem] = []
        page = 0
        total = 0

        while True:
            items, total = self.get_library_items(
                library_id,
                limit=batch_size,
                page=page,
            )
            all_items.extend(items)

            # Log progress as "fetched so far / total"
            logger.info(f"Fetched {len(all_items)}/{total} items from library")

            if len(all_items) >= total or not items:
                break
            page += 1

        return all_items

    @retry_with_backoff(max_attempts=2, base_delay=1.0, exceptions=NETWORK_EXCEPTIONS)
    def get_item_details(self, item_id: str) -> dict[str, Any]:
        """Get detailed information about a specific item.

        Args:
            item_id: ID of the library item

        Returns:
            Full item details as a dictionary

        Raises:
            AbsApiError: If item not found
        """
        logger.debug(f"Fetching details for item {item_id}")
        try:
            response = self._request("GET", f"/api/items/{item_id}")
        except httpx.ConnectError as e:
            raise AbsConnectionError(f"Failed to connect to {self.host}: {e}") from e
        except httpx.TimeoutException as e:
            raise AbsConnectionError(f"Request to {self.host} timed out: {e}") from e
        result: dict[str, Any] = response.json()
        return result

    @retry_with_backoff(max_attempts=2, base_delay=2.0, exceptions=NETWORK_EXCEPTIONS)
    def scan_library(self, library_id: str, force: bool = False) -> bool:
        """Trigger a library scan.

        Args:
            library_id: ID of the library to scan
            force: Force rescan of all items

        Returns:
            True if scan was triggered successfully
        """
        logger.info(f"Triggering scan for library {library_id} (force={force})")

        params = {"force": "1"} if force else {}
        try:
            response = self._request("POST", f"/api/libraries/{library_id}/scan", params=params)
        except httpx.ConnectError as e:
            raise AbsConnectionError(f"Failed to connect to {self.host}: {e}") from e
        except httpx.TimeoutException as e:
            raise AbsConnectionError(f"Request to {self.host} timed out: {e}") from e

        # ABS returns 200 on success
        return response.status_code == 200

    def get_library_items_cached(
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
            items = self.get_all_library_items(library_id)
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
    # Metadata Search (Phase 5)
    # =========================================================================

    @retry_with_backoff(max_attempts=3, base_delay=2.0, exceptions=NETWORK_EXCEPTIONS)
    def search_books(
        self,
        title: str,
        author: str | None = None,
        provider: str = "audible",
    ) -> list[dict[str, Any]]:
        """Search for books via ABS metadata provider.

        Uses ABS as a proxy to search Audible (or other providers) for book metadata.
        This is useful for resolving ASINs for books that don't have them in folder/file names.

        Args:
            title: Book title to search for
            author: Optional author name to narrow results
            provider: Metadata provider (default: "audible")

        Returns:
            List of search results with book metadata including ASIN

        Raises:
            AbsConnectionError: If unable to connect
            AbsApiError: If API returns an error

        Example response structure::

            [
                {
                    "title": "Wizard's First Rule",
                    "subtitle": "Sword of Truth, Book 1",
                    "author": "Terry Goodkind",
                    "narrator": "Sam Tsoutsouvas",
                    "asin": "B002V0QK4C",
                    "series": [{"series": "Sword of Truth", "sequence": "1"}],
                    ...
                }
            ]
        """
        logger.debug(f"Searching ABS for books: title={title!r}, author={author!r}")

        params: dict[str, str] = {
            "title": title,
            "provider": provider,
        }
        if author:
            params["author"] = author

        try:
            response = self._request("GET", "/api/search/books", params=params)
        except httpx.ConnectError as e:
            raise AbsConnectionError(f"Failed to connect to {self.host}: {e}") from e
        except httpx.TimeoutException as e:
            raise AbsConnectionError(f"Request to {self.host} timed out: {e}") from e

        results = response.json()

        # API returns a list directly
        if not isinstance(results, list):
            logger.warning(f"Unexpected search response type: {type(results)}")
            return []

        logger.debug(f"Search returned {len(results)} results")
        return results
