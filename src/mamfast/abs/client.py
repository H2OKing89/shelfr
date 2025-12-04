"""HTTP client for Audiobookshelf API.

Provides methods to interact with an Audiobookshelf server including:
- Connection testing (ping/authorize)
- Library listing
- Library item retrieval
- Library scanning
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from mamfast.utils.retry import NETWORK_EXCEPTIONS, retry_with_backoff

if TYPE_CHECKING:
    from mamfast.config import AudiobookshelfConfig

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
        >>> from mamfast.abs import AbsClient
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
            )
        return self._client

    def close(self) -> None:
        """Close the HTTP client connection."""
        if self._client is not None:
            self._client.close()
            self._client = None

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

        try:
            response = client.request(method, path, **kwargs)
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
        response = self._request("GET", "/api/authorize")
        data = response.json()

        user_data = data.get("user", {})
        permissions = user_data.get("permissions", {})

        return AbsUser(
            id=user_data.get("id", ""),
            username=user_data.get("username", ""),
            user_type=user_data.get("type", ""),
            is_active=user_data.get("isActive", False),
            has_admin=permissions.get("delete", False),  # Admin-level permission
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
        response = self._request("GET", "/api/libraries")
        data = response.json()

        libraries = []
        for lib_data in data.get("libraries", []):
            libraries.append(AbsLibrary.from_api_response(lib_data))

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

        response = self._request("GET", f"/api/libraries/{library_id}/items", params=params)
        data = response.json()

        items = []
        for item_data in data.get("results", []):
            items.append(AbsLibraryItem.from_api_response(item_data))

        total = data.get("total", len(items))
        logger.info(f"Fetched {len(items)} items from library (total: {total})")
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

        while True:
            items, total = self.get_library_items(
                library_id,
                limit=batch_size,
                page=page,
            )
            all_items.extend(items)

            logger.debug(f"Fetched page {page + 1}, {len(all_items)}/{total} items")

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
        response = self._request("GET", f"/api/items/{item_id}")
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
        response = self._request("POST", f"/api/libraries/{library_id}/scan", params=params)

        # ABS returns 200 on success
        return response.status_code == 200
