"""Tests for Audiobookshelf async API client.

Phase 11.1: Tests for AbsAsyncClient.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from shelfr.abs.async_client import (
    AbsAsyncClient,
    AbsAuthError,
    AbsConnectionError,
    AbsLibrary,
    AbsLibraryItem,
    AbsUser,
)


@pytest.fixture
def abs_fixtures_path() -> Path:
    """Path to ABS API response fixtures."""
    return Path(__file__).parent / "fixtures" / "abs_responses"


@pytest.fixture
def mock_authorize_response(abs_fixtures_path: Path) -> dict[str, Any]:
    """Load authorize.json fixture."""
    with open(abs_fixtures_path / "authorize.json") as f:
        result: dict[str, Any] = json.load(f)
        return result


@pytest.fixture
def mock_libraries_response(abs_fixtures_path: Path) -> dict[str, Any]:
    """Load libraries.json fixture."""
    with open(abs_fixtures_path / "libraries.json") as f:
        result: dict[str, Any] = json.load(f)
        return result


@pytest.fixture
def mock_library_items_response(abs_fixtures_path: Path) -> dict[str, Any]:
    """Load library_items.json fixture."""
    with open(abs_fixtures_path / "library_items.json") as f:
        result: dict[str, Any] = json.load(f)
        return result


class TestAbsAsyncClientInit:
    """Test AbsAsyncClient initialization."""

    def test_basic_init(self) -> None:
        """Test basic client initialization."""
        client = AbsAsyncClient(
            host="http://localhost:13378",
            api_key="test-key",
        )
        assert client.host == "http://localhost:13378"
        assert client.api_key == "test-key"
        assert client.timeout == 30.0

    def test_host_trailing_slash_normalized(self) -> None:
        """Test that trailing slash is removed from host."""
        client = AbsAsyncClient(
            host="http://localhost:13378/",
            api_key="test-key",
        )
        assert client.host == "http://localhost:13378"

    def test_custom_timeout(self) -> None:
        """Test custom timeout setting."""
        client = AbsAsyncClient(
            host="http://localhost",
            api_key="key",
            timeout=60.0,
        )
        assert client.timeout == 60.0

    def test_from_config(self) -> None:
        """Test creating client from config object."""
        mock_config = MagicMock()
        mock_config.host = "http://abs.local:13378"
        mock_config.api_key = "config-api-key"
        mock_config.timeout_seconds = 45

        client = AbsAsyncClient.from_config(mock_config)
        assert client.host == "http://abs.local:13378"
        assert client.api_key == "config-api-key"
        assert client.timeout == 45.0


class TestAbsAsyncClientContextManager:
    """Test async context manager behavior."""

    @pytest.mark.asyncio
    async def test_context_manager_creates_client(self) -> None:
        """Test that context manager creates httpx client."""
        async_client = AbsAsyncClient(
            host="http://localhost:13378",
            api_key="test-key",
        )
        assert async_client._client is None

        async with async_client as client:
            assert client._client is not None
            assert isinstance(client._client, httpx.AsyncClient)

        # Client should be closed after exit
        assert async_client._client is None

    @pytest.mark.asyncio
    async def test_client_property_raises_before_enter(self) -> None:
        """Test that client property raises if not initialized."""
        async_client = AbsAsyncClient(
            host="http://localhost:13378",
            api_key="test-key",
        )
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = async_client.client


class TestAbsAsyncClientAuthorize:
    """Test async authorization/connection testing."""

    @pytest.mark.asyncio
    async def test_authorize_success(
        self,
        mock_authorize_response: dict[str, Any],
    ) -> None:
        """Test successful authorization."""
        async_client = AbsAsyncClient(
            host="http://localhost:13378",
            api_key="test-key",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_authorize_response

        async with async_client as client:
            with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
                mock_request.return_value = mock_response
                user = await client.authorize()

        assert isinstance(user, AbsUser)
        assert user.id == "usr_Shelfr"
        assert user.username == "Shelfr"
        assert user.user_type == "admin"
        assert user.is_active is True
        assert user.has_admin is True

    @pytest.mark.asyncio
    async def test_authorize_invalid_key(self) -> None:
        """Test authorization with invalid API key."""
        async_client = AbsAsyncClient(
            host="http://localhost:13378",
            api_key="invalid-key",
        )

        async with async_client as client:
            with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
                mock_request.side_effect = AbsAuthError("Invalid API key")
                with pytest.raises(AbsAuthError, match="Invalid API key"):
                    await client.authorize()

    @pytest.mark.asyncio
    async def test_ping_success(
        self,
        mock_authorize_response: dict[str, Any],
    ) -> None:
        """Test ping returns True on success."""
        async_client = AbsAsyncClient(
            host="http://localhost:13378",
            api_key="test-key",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_authorize_response

        async with async_client as client:
            with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
                mock_request.return_value = mock_response
                result = await client.ping()

        assert result is True

    @pytest.mark.asyncio
    async def test_ping_failure(self) -> None:
        """Test ping returns False on connection error."""
        async_client = AbsAsyncClient(
            host="http://localhost:13378",
            api_key="test-key",
        )

        async with async_client as client:
            with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
                mock_request.side_effect = AbsConnectionError("Connection refused")
                result = await client.ping()

        assert result is False


class TestAbsAsyncClientLibraries:
    """Test async library operations."""

    @pytest.mark.asyncio
    async def test_get_libraries(
        self,
        mock_libraries_response: dict[str, Any],
    ) -> None:
        """Test fetching libraries."""
        async_client = AbsAsyncClient(
            host="http://localhost:13378",
            api_key="test-key",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_libraries_response

        async with async_client as client:
            with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
                mock_request.return_value = mock_response
                libraries = await client.get_libraries()

        assert len(libraries) >= 1
        assert isinstance(libraries[0], AbsLibrary)


class TestAbsAsyncClientLibraryItems:
    """Test async library item operations."""

    @pytest.mark.asyncio
    async def test_get_library_items(
        self,
        mock_library_items_response: dict[str, Any],
    ) -> None:
        """Test fetching library items (single page)."""
        async_client = AbsAsyncClient(
            host="http://localhost:13378",
            api_key="test-key",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_library_items_response

        async with async_client as client:
            with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
                mock_request.return_value = mock_response
                items, total = await client.get_library_items("lib_123")

        assert isinstance(items, list)
        assert isinstance(total, int)
        if items:
            assert isinstance(items[0], AbsLibraryItem)

    @pytest.mark.asyncio
    async def test_get_all_library_items_single_page(
        self,
        mock_library_items_response: dict[str, Any],
    ) -> None:
        """Test fetching all items when they fit in one page."""
        async_client = AbsAsyncClient(
            host="http://localhost:13378",
            api_key="test-key",
        )

        # Set total to match number of results (single page)
        response_data = mock_library_items_response.copy()
        response_data["total"] = len(response_data.get("results", []))

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response_data

        async with async_client as client:
            with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
                mock_request.return_value = mock_response
                items = await client.get_all_library_items("lib_123")

        assert isinstance(items, list)

    @pytest.mark.asyncio
    async def test_get_all_library_items_parallel_pages(self) -> None:
        """Test fetching all items with parallel pagination."""
        async_client = AbsAsyncClient(
            host="http://localhost:13378",
            api_key="test-key",
        )

        # Create mock items for pagination test
        def make_item(i: int) -> dict[str, Any]:
            return {
                "id": f"item_{i}",
                "libraryId": "lib_123",
                "path": f"/audiobooks/book_{i}",
                "relPath": f"book_{i}",
                "isMissing": False,
                "mediaType": "book",
                "media": {
                    "duration": 3600.0,
                    "metadata": {
                        "title": f"Book {i}",
                        "authorName": "Author",
                    },
                },
                "size": 100000,
                "addedAt": 1704067200000,
                "updatedAt": 1704067200000,
            }

        # Page 0: returns 100 items, total is 250
        page0_items = [make_item(i) for i in range(100)]
        page0_response = {"results": page0_items, "total": 250}

        # Page 1: returns 100 items
        page1_items = [make_item(i) for i in range(100, 200)]
        page1_response = {"results": page1_items, "total": 250}

        # Page 2: returns 50 items
        page2_items = [make_item(i) for i in range(200, 250)]
        page2_response = {"results": page2_items, "total": 250}

        call_count = 0

        async def mock_request(method: str, path: str, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            page = kwargs.get("params", {}).get("page", 0)
            mock_resp = MagicMock()
            mock_resp.status_code = 200

            if page == 0:
                mock_resp.json.return_value = page0_response
            elif page == 1:
                mock_resp.json.return_value = page1_response
            else:
                mock_resp.json.return_value = page2_response

            call_count += 1
            return mock_resp

        async with async_client as client:
            with patch.object(client, "_request", side_effect=mock_request):
                items = await client.get_all_library_items("lib_123")

        # Should have fetched all 250 items
        assert len(items) == 250
        # First page + 2 parallel pages = at least 3 calls
        assert call_count >= 3


class TestAbsAsyncClientCache:
    """Test async client caching."""

    @pytest.mark.asyncio
    async def test_cache_stores_results(
        self,
        mock_library_items_response: dict[str, Any],
    ) -> None:
        """Test that results are cached."""
        async_client = AbsAsyncClient(
            host="http://localhost:13378",
            api_key="test-key",
        )

        response_data = mock_library_items_response.copy()
        response_data["total"] = len(response_data.get("results", []))

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response_data

        async with async_client as client:
            with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
                mock_request.return_value = mock_response

                # First call should fetch
                await client.get_library_items_cached("lib_123")
                assert mock_request.call_count >= 1
                first_count = mock_request.call_count

                # Second call should use cache
                await client.get_library_items_cached("lib_123")
                assert mock_request.call_count == first_count  # No additional calls

    @pytest.mark.asyncio
    async def test_cache_force_refresh(
        self,
        mock_library_items_response: dict[str, Any],
    ) -> None:
        """Test force refresh bypasses cache."""
        async_client = AbsAsyncClient(
            host="http://localhost:13378",
            api_key="test-key",
        )

        response_data = mock_library_items_response.copy()
        response_data["total"] = len(response_data.get("results", []))

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response_data

        async with async_client as client:
            with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
                mock_request.return_value = mock_response

                # First call
                await client.get_library_items_cached("lib_123")
                first_count = mock_request.call_count

                # Force refresh should make new requests
                await client.get_library_items_cached("lib_123", force_refresh=True)
                assert mock_request.call_count > first_count

    def test_clear_cache_specific(self) -> None:
        """Test clearing cache for specific library."""
        client = AbsAsyncClient(
            host="http://localhost:13378",
            api_key="test-key",
        )
        # Manually populate cache
        client._library_cache["lib_1"] = []
        client._library_cache["lib_2"] = []

        client.clear_cache("lib_1")

        assert "lib_1" not in client._library_cache
        assert "lib_2" in client._library_cache

    def test_clear_cache_all(self) -> None:
        """Test clearing all cache."""
        client = AbsAsyncClient(
            host="http://localhost:13378",
            api_key="test-key",
        )
        # Manually populate cache
        client._library_cache["lib_1"] = []
        client._library_cache["lib_2"] = []

        client.clear_cache()

        assert len(client._library_cache) == 0


class TestAbsAsyncClientScan:
    """Test async library scanning."""

    @pytest.mark.asyncio
    async def test_scan_library_success(self) -> None:
        """Test successful library scan trigger."""
        async_client = AbsAsyncClient(
            host="http://localhost:13378",
            api_key="test-key",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200

        async with async_client as client:
            with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
                mock_request.return_value = mock_response
                result = await client.scan_library("lib_123")

        assert result is True

    @pytest.mark.asyncio
    async def test_scan_libraries_parallel(self) -> None:
        """Test parallel library scanning."""
        async_client = AbsAsyncClient(
            host="http://localhost:13378",
            api_key="test-key",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200

        async with async_client as client:
            with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
                mock_request.return_value = mock_response
                results = await client.scan_libraries(["lib_1", "lib_2", "lib_3"])

        assert results == {"lib_1": True, "lib_2": True, "lib_3": True}


class TestAbsAsyncClientSearch:
    """Test async book search."""

    @pytest.mark.asyncio
    async def test_search_books_success(self) -> None:
        """Test successful book search."""
        async_client = AbsAsyncClient(
            host="http://localhost:13378",
            api_key="test-key",
        )

        search_results = [
            {
                "title": "Test Book",
                "author": "Test Author",
                "asin": "B0123456789",
            }
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = search_results

        async with async_client as client:
            with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
                mock_request.return_value = mock_response
                results = await client.search_books("Test Book", author="Test Author")

        assert len(results) == 1
        assert results[0]["asin"] == "B0123456789"

    @pytest.mark.asyncio
    async def test_search_books_batch(self) -> None:
        """Test batch book search."""
        async_client = AbsAsyncClient(
            host="http://localhost:13378",
            api_key="test-key",
        )

        async def mock_search(
            title: str, author: str | None = None, **kwargs: Any
        ) -> list[dict[str, Any]]:
            return [{"title": title, "author": author or "Unknown"}]

        async with async_client as client:
            with patch.object(client, "search_books", side_effect=mock_search):
                results = await client.search_books_batch(
                    [
                        ("Book 1", "Author 1"),
                        ("Book 2", None),
                        ("Book 3", "Author 3"),
                    ]
                )

        assert len(results) == 3
        assert results[0][0]["title"] == "Book 1"
        assert results[1][0]["author"] == "Unknown"


class TestAbsDataClasses:
    """Test data class behavior."""

    def test_abs_library_from_api_response(self) -> None:
        """Test creating AbsLibrary from API response."""
        data = {
            "id": "lib_123",
            "name": "Audiobooks",
            "mediaType": "book",
            "folders": [{"fullPath": "/audiobooks"}],
            "displayOrder": 1,
        }
        lib = AbsLibrary.from_api_response(data)
        assert lib.id == "lib_123"
        assert lib.name == "Audiobooks"
        assert lib.media_type == "book"
        assert lib.folders == ["/audiobooks"]
        assert lib.display_order == 1

    def test_abs_library_item_from_api_response(self) -> None:
        """Test creating AbsLibraryItem from API response."""
        data = {
            "id": "item_123",
            "libraryId": "lib_123",
            "path": "/audiobooks/Test Book",
            "relPath": "Test Book",
            "isMissing": False,
            "mediaType": "book",
            "media": {
                "duration": 3600.5,
                "metadata": {
                    "title": "Test Book",
                    "subtitle": "A Subtitle",
                    "authorName": "Test Author",
                    "narratorName": "Test Narrator",
                    "seriesName": "Test Series",
                    "asin": "B0123456789",
                    "isbn": "9781234567890",
                },
            },
            "size": 100000000,
            "addedAt": 1704067200000,
            "updatedAt": 1704153600000,
        }
        item = AbsLibraryItem.from_api_response(data)
        assert item.id == "item_123"
        assert item.library_id == "lib_123"
        assert item.title == "Test Book"
        assert item.subtitle == "A Subtitle"
        assert item.author_name == "Test Author"
        assert item.narrator_name == "Test Narrator"
        assert item.series_name == "Test Series"
        assert item.asin == "B0123456789"
        assert item.isbn == "9781234567890"
        assert item.duration == 3600.5
        assert item.size == 100000000


# =============================================================================
# Phase 11.2: Async ASIN Index Tests
# =============================================================================


class TestBuildAsinIndexAsync:
    """Test async ASIN index building."""

    @pytest.mark.asyncio
    async def test_build_asin_index_basic(self) -> None:
        """Test basic async ASIN index building."""
        from shelfr.abs.asin import AsinEntry, build_asin_index_async

        async_client = AbsAsyncClient(
            host="http://localhost:13378",
            api_key="test-key",
        )

        # Create mock items with ASINs
        mock_items = [
            AbsLibraryItem(
                id="item_1",
                library_id="lib_123",
                path="/audiobooks/Book 1 {ASIN.B0ABC123456}",
                rel_path="Book 1",
                is_missing=False,
                media_type="book",
                title="Book 1",
                subtitle=None,
                author_name="Author 1",
                narrator_name=None,
                series_name=None,
                asin="B0ABC123456",
                isbn=None,
                duration=3600.0,
                size=100000,
                added_at=1704067200000,
                updated_at=1704067200000,
            ),
            AbsLibraryItem(
                id="item_2",
                library_id="lib_123",
                path="/audiobooks/Book 2 {ASIN.B0DEF789012}",
                rel_path="Book 2",
                is_missing=False,
                media_type="book",
                title="Book 2",
                subtitle=None,
                author_name="Author 2",
                narrator_name=None,
                series_name=None,
                asin="B0DEF789012",
                isbn=None,
                duration=7200.0,
                size=200000,
                added_at=1704067200000,
                updated_at=1704067200000,
            ),
        ]

        async with async_client as client:
            with patch.object(
                client, "get_library_items_cached", new_callable=AsyncMock
            ) as mock_fetch:
                mock_fetch.return_value = mock_items
                index = await build_asin_index_async(client, "lib_123")

        assert len(index) == 2
        assert "B0ABC123456" in index
        assert "B0DEF789012" in index
        assert isinstance(index["B0ABC123456"], AsinEntry)
        assert index["B0ABC123456"].title == "Book 1"
        assert index["B0DEF789012"].author == "Author 2"

    @pytest.mark.asyncio
    async def test_build_asin_index_extracts_from_path(self) -> None:
        """Test ASIN extraction from path when not in metadata."""
        from shelfr.abs.asin import build_asin_index_async

        async_client = AbsAsyncClient(
            host="http://localhost:13378",
            api_key="test-key",
        )

        # Item without ASIN in metadata but has it in path
        mock_items = [
            AbsLibraryItem(
                id="item_1",
                library_id="lib_123",
                path="/audiobooks/Book {ASIN.B0PATHONL1}",
                rel_path="Book",
                is_missing=False,
                media_type="book",
                title="Book Without Metadata ASIN",
                subtitle=None,
                author_name="Author",
                narrator_name=None,
                series_name=None,
                asin=None,  # No ASIN in metadata
                isbn=None,
                duration=3600.0,
                size=100000,
                added_at=1704067200000,
                updated_at=1704067200000,
            ),
        ]

        async with async_client as client:
            with patch.object(
                client, "get_library_items_cached", new_callable=AsyncMock
            ) as mock_fetch:
                mock_fetch.return_value = mock_items
                index = await build_asin_index_async(client, "lib_123")

        assert len(index) == 1
        assert "B0PATHONL1" in index

    @pytest.mark.asyncio
    async def test_build_asin_index_skips_duplicates(self) -> None:
        """Test that duplicate ASINs keep only first occurrence."""
        from shelfr.abs.asin import build_asin_index_async

        async_client = AbsAsyncClient(
            host="http://localhost:13378",
            api_key="test-key",
        )

        # Two items with same ASIN
        mock_items = [
            AbsLibraryItem(
                id="item_1",
                library_id="lib_123",
                path="/audiobooks/First Copy",
                rel_path="First Copy",
                is_missing=False,
                media_type="book",
                title="First Copy",
                subtitle=None,
                author_name="Author",
                narrator_name=None,
                series_name=None,
                asin="B0DUPLICATE1",
                isbn=None,
                duration=3600.0,
                size=100000,
                added_at=1704067200000,
                updated_at=1704067200000,
            ),
            AbsLibraryItem(
                id="item_2",
                library_id="lib_123",
                path="/audiobooks/Second Copy",
                rel_path="Second Copy",
                is_missing=False,
                media_type="book",
                title="Second Copy",
                subtitle=None,
                author_name="Author",
                narrator_name=None,
                series_name=None,
                asin="B0DUPLICATE1",  # Same ASIN
                isbn=None,
                duration=3600.0,
                size=100000,
                added_at=1704067200000,
                updated_at=1704067200000,
            ),
        ]

        async with async_client as client:
            with patch.object(
                client, "get_library_items_cached", new_callable=AsyncMock
            ) as mock_fetch:
                mock_fetch.return_value = mock_items
                index = await build_asin_index_async(client, "lib_123")

        # Only one entry, the first one
        assert len(index) == 1
        assert index["B0DUPLICATE1"].title == "First Copy"
        assert index["B0DUPLICATE1"].path == "/audiobooks/First Copy"

    @pytest.mark.asyncio
    async def test_build_asin_index_skips_items_without_asin(self) -> None:
        """Test that items without ASIN are skipped."""
        from shelfr.abs.asin import build_asin_index_async

        async_client = AbsAsyncClient(
            host="http://localhost:13378",
            api_key="test-key",
        )

        mock_items = [
            AbsLibraryItem(
                id="item_1",
                library_id="lib_123",
                path="/audiobooks/Book With ASIN",
                rel_path="Book With ASIN",
                is_missing=False,
                media_type="book",
                title="Book With ASIN",
                subtitle=None,
                author_name="Author",
                narrator_name=None,
                series_name=None,
                asin="B0HASASIN01",
                isbn=None,
                duration=3600.0,
                size=100000,
                added_at=1704067200000,
                updated_at=1704067200000,
            ),
            AbsLibraryItem(
                id="item_2",
                library_id="lib_123",
                path="/audiobooks/Book Without ASIN",  # No ASIN in path either
                rel_path="Book Without ASIN",
                is_missing=False,
                media_type="book",
                title="Book Without ASIN",
                subtitle=None,
                author_name="Author",
                narrator_name=None,
                series_name=None,
                asin=None,  # No ASIN
                isbn=None,
                duration=3600.0,
                size=100000,
                added_at=1704067200000,
                updated_at=1704067200000,
            ),
        ]

        async with async_client as client:
            with patch.object(
                client, "get_library_items_cached", new_callable=AsyncMock
            ) as mock_fetch:
                mock_fetch.return_value = mock_items
                index = await build_asin_index_async(client, "lib_123")

        # Only the item with ASIN
        assert len(index) == 1
        assert "B0HASASIN01" in index

    @pytest.mark.asyncio
    async def test_build_asin_index_empty_library(self) -> None:
        """Test building index from empty library."""
        from shelfr.abs.asin import build_asin_index_async

        async_client = AbsAsyncClient(
            host="http://localhost:13378",
            api_key="test-key",
        )

        async with async_client as client:
            with patch.object(
                client, "get_library_items_cached", new_callable=AsyncMock
            ) as mock_fetch:
                mock_fetch.return_value = []
                index = await build_asin_index_async(client, "lib_123")

        assert len(index) == 0
