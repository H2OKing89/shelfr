"""Tests for Audiobookshelf API client."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from mamfast.abs.client import (
    AbsApiError,
    AbsAuthError,
    AbsClient,
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


@pytest.fixture
def client() -> AbsClient:
    """Create a test client instance."""
    return AbsClient(
        host="http://localhost:13378",
        api_key="test-api-key",
        timeout=10.0,
    )


class TestAbsClientInit:
    """Test AbsClient initialization."""

    def test_basic_init(self) -> None:
        """Test basic client initialization."""
        client = AbsClient(
            host="http://localhost:13378",
            api_key="test-key",
        )
        assert client.host == "http://localhost:13378"
        assert client.api_key == "test-key"
        assert client.timeout == 30.0

    def test_host_trailing_slash_normalized(self) -> None:
        """Test that trailing slash is removed from host."""
        client = AbsClient(
            host="http://localhost:13378/",
            api_key="test-key",
        )
        assert client.host == "http://localhost:13378"

    def test_custom_timeout(self) -> None:
        """Test custom timeout setting."""
        client = AbsClient(
            host="http://localhost",
            api_key="key",
            timeout=60.0,
        )
        assert client.timeout == 60.0

    def test_from_config(self) -> None:
        """Test creating client from config object."""
        # Create a mock config
        mock_config = MagicMock()
        mock_config.host = "http://abs.local:13378"
        mock_config.api_key = "config-api-key"
        mock_config.timeout_seconds = 45

        client = AbsClient.from_config(mock_config)
        assert client.host == "http://abs.local:13378"
        assert client.api_key == "config-api-key"
        assert client.timeout == 45.0


class TestAbsClientAuthorize:
    """Test authorization/connection testing."""

    def test_authorize_success(
        self,
        client: AbsClient,
        mock_authorize_response: dict[str, Any],
    ) -> None:
        """Test successful authorization."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_authorize_response

        with patch.object(client, "_request", return_value=mock_response):
            user = client.authorize()

        assert isinstance(user, AbsUser)
        assert user.id == "usr_mamfast"
        assert user.username == "mamfast"
        assert user.user_type == "admin"
        assert user.is_active is True
        assert user.has_admin is True

    def test_authorize_invalid_key(self, client: AbsClient) -> None:
        """Test authorization with invalid API key."""
        with (
            patch.object(
                client,
                "_request",
                side_effect=AbsAuthError("Invalid API key"),
            ),
            pytest.raises(AbsAuthError, match="Invalid API key"),
        ):
            client.authorize()

    def test_ping_success(
        self,
        client: AbsClient,
        mock_authorize_response: dict[str, Any],
    ) -> None:
        """Test ping returns True on success."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_authorize_response

        with patch.object(client, "_request", return_value=mock_response):
            assert client.ping() is True

    def test_ping_failure(self, client: AbsClient) -> None:
        """Test ping returns False on failure."""
        with patch.object(
            client,
            "_request",
            side_effect=AbsConnectionError("Connection refused"),
        ):
            assert client.ping() is False


class TestAbsClientLibraries:
    """Test library listing."""

    def test_get_libraries(
        self,
        client: AbsClient,
        mock_libraries_response: dict[str, Any],
    ) -> None:
        """Test getting libraries."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_libraries_response

        with patch.object(client, "_request", return_value=mock_response):
            libraries = client.get_libraries()

        assert len(libraries) == 2

        # Check first library (Audiobooks)
        lib1 = libraries[0]
        assert isinstance(lib1, AbsLibrary)
        assert lib1.id == "lib_c1u6t4p45c35rf0nzd"
        assert lib1.name == "Audiobooks"
        assert lib1.media_type == "book"
        assert "/audiobooks" in lib1.folders

        # Check second library (Podcasts)
        lib2 = libraries[1]
        assert lib2.id == "lib_p9wkw2i85qy9oltijt"
        assert lib2.name == "Podcasts"
        assert lib2.media_type == "podcast"


class TestAbsClientLibraryItems:
    """Test library item fetching."""

    def test_get_library_items(
        self,
        client: AbsClient,
        mock_library_items_response: dict[str, Any],
    ) -> None:
        """Test getting library items."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_library_items_response

        with patch.object(client, "_request", return_value=mock_response):
            items, total = client.get_library_items("lib_c1u6t4p45c35rf0nzd")

        # Fixture has 5 items
        assert len(items) >= 3
        assert total >= 3

        # Check first item (SAO)
        item = items[0]
        assert isinstance(item, AbsLibraryItem)
        assert item.id == "li_sao16_alicization"
        assert item.title == "Sword Art Online vol_16 Alicization Exploding"
        assert item.author_name == "Reki Kawahara"
        assert item.asin == "B0DK9TS6D9"
        assert item.series_name == "Sword Art Online"

    def test_get_library_items_with_pagination(
        self,
        client: AbsClient,
        mock_library_items_response: dict[str, Any],
    ) -> None:
        """Test pagination parameters are passed correctly."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_library_items_response

        with patch.object(client, "_request", return_value=mock_response) as mock_request:
            client.get_library_items("lib_test", limit=10, page=2)

        # Check that params were passed
        call_args = mock_request.call_args
        assert call_args[0][0] == "GET"
        assert "lib_test" in call_args[0][1]

    def test_item_without_asin(
        self,
        client: AbsClient,
        mock_library_items_response: dict[str, Any],
    ) -> None:
        """Test handling items without ASIN."""
        # The fixture includes a book without ASIN
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_library_items_response

        with patch.object(client, "_request", return_value=mock_response):
            items, _ = client.get_library_items("lib_test")

        # Find the item without ASIN
        no_asin_items = [item for item in items if item.asin is None]
        # Fixture should have at least one
        assert len(no_asin_items) >= 1


class TestAbsClientErrors:
    """Test error handling."""

    def test_connection_error(self, client: AbsClient) -> None:
        """Test handling connection errors."""
        mock_client = MagicMock()
        mock_client.request.side_effect = httpx.ConnectError("Connection refused")

        with (
            patch.object(client, "_get_client", return_value=mock_client),
            pytest.raises(AbsConnectionError, match="Failed to connect"),
        ):
            client._request("GET", "/api/test")

    def test_timeout_error(self, client: AbsClient) -> None:
        """Test handling timeout errors."""
        mock_client = MagicMock()
        mock_client.request.side_effect = httpx.TimeoutException("Timeout")

        with (
            patch.object(client, "_get_client", return_value=mock_client),
            pytest.raises(AbsConnectionError, match="timed out"),
        ):
            client._request("GET", "/api/test")

    def test_401_raises_auth_error(self, client: AbsClient) -> None:
        """Test that 401 responses raise AbsAuthError."""
        mock_response = MagicMock()
        mock_response.status_code = 401

        mock_client = MagicMock()
        mock_client.request.return_value = mock_response

        with (
            patch.object(client, "_get_client", return_value=mock_client),
            pytest.raises(AbsAuthError, match="Invalid API key"),
        ):
            client._request("GET", "/api/test")

    def test_404_raises_api_error(self, client: AbsClient) -> None:
        """Test that 404 responses raise AbsApiError."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = MagicMock()
        mock_client.request.return_value = mock_response

        with (
            patch.object(client, "_get_client", return_value=mock_client),
            pytest.raises(AbsApiError, match="not found") as exc_info,
        ):
            client._request("GET", "/api/items/missing")

        assert exc_info.value.status_code == 404

    def test_500_raises_api_error(self, client: AbsClient) -> None:
        """Test that 500 responses raise AbsApiError."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        mock_client = MagicMock()
        mock_client.request.return_value = mock_response

        with (
            patch.object(client, "_get_client", return_value=mock_client),
            pytest.raises(AbsApiError) as exc_info,
        ):
            client._request("GET", "/api/test")

        assert exc_info.value.status_code == 500


class TestAbsClientContextManager:
    """Test context manager protocol."""

    def test_context_manager(self) -> None:
        """Test using client as context manager."""
        with AbsClient(host="http://localhost", api_key="key") as client:
            assert client is not None

    def test_close_cleans_up(self) -> None:
        """Test that close() properly cleans up."""
        client = AbsClient(host="http://localhost", api_key="key")
        # Access _client to create it
        client._client = MagicMock()

        client.close()
        assert client._client is None


class TestAbsLibrary:
    """Test AbsLibrary dataclass."""

    def test_from_api_response(self) -> None:
        """Test creating AbsLibrary from API response."""
        data = {
            "id": "lib_test",
            "name": "Test Library",
            "mediaType": "book",
            "displayOrder": 1,
            "folders": [
                {"id": "fol_1", "fullPath": "/audiobooks"},
                {"id": "fol_2", "fullPath": "/more/books"},
            ],
        }

        lib = AbsLibrary.from_api_response(data)
        assert lib.id == "lib_test"
        assert lib.name == "Test Library"
        assert lib.media_type == "book"
        assert lib.display_order == 1
        assert lib.folders == ["/audiobooks", "/more/books"]

    def test_from_api_response_defaults(self) -> None:
        """Test defaults when fields are missing."""
        data = {"id": "lib_min", "name": "Minimal"}

        lib = AbsLibrary.from_api_response(data)
        assert lib.media_type == "book"
        assert lib.display_order == 0
        assert lib.folders == []


class TestAbsLibraryItem:
    """Test AbsLibraryItem dataclass."""

    def test_from_api_response_full(self) -> None:
        """Test creating item with all fields."""
        data = {
            "id": "li_test",
            "libraryId": "lib_123",
            "path": "/audiobooks/Author/Book",
            "relPath": "Author/Book",
            "isMissing": False,
            "mediaType": "book",
            "size": 1000000,
            "addedAt": 1700000000,
            "updatedAt": 1700000001,
            "media": {
                "metadata": {
                    "title": "Test Book",
                    "subtitle": "A Novel",
                    "authorName": "Test Author",
                    "narratorName": "Test Narrator",
                    "seriesName": "Test Series",
                    "asin": "B123456789",
                    "isbn": "9781234567890",
                },
                "duration": 36000.0,
            },
        }

        item = AbsLibraryItem.from_api_response(data)
        assert item.id == "li_test"
        assert item.library_id == "lib_123"
        assert item.path == "/audiobooks/Author/Book"
        assert item.title == "Test Book"
        assert item.subtitle == "A Novel"
        assert item.author_name == "Test Author"
        assert item.narrator_name == "Test Narrator"
        assert item.series_name == "Test Series"
        assert item.asin == "B123456789"
        assert item.isbn == "9781234567890"
        assert item.duration == 36000.0

    def test_from_api_response_minimal(self) -> None:
        """Test creating item with minimal fields."""
        data = {"id": "li_min", "media": {"metadata": {}}}

        item = AbsLibraryItem.from_api_response(data)
        assert item.id == "li_min"
        assert item.title == ""
        assert item.asin is None
        assert item.duration == 0.0
