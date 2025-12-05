"""Tests for Audiobookshelf API response schemas."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from mamfast.schemas.abs import (
    AbsAuthorizeResponse,
    AbsBookMedia,
    AbsBookMetadata,
    AbsFolder,
    AbsLibrariesResponse,
    AbsLibraryItemSchema,
    AbsLibraryItemsResponse,
    AbsLibrarySchema,
    AbsLibrarySettings,
    AbsUserPermissions,
    AbsUserSchema,
    validate_authorize_response,
    validate_libraries_response,
    validate_library_items_response,
)


@pytest.fixture
def fixtures_dir() -> Path:
    """Return path to ABS fixtures directory."""
    return Path(__file__).parent / "fixtures" / "abs_responses"


@pytest.fixture
def libraries_response(fixtures_dir: Path) -> dict[str, Any]:
    """Load libraries.json fixture."""
    with open(fixtures_dir / "libraries.json") as f:
        return cast(dict[str, Any], json.load(f))


@pytest.fixture
def library_items_response(fixtures_dir: Path) -> dict[str, Any]:
    """Load library_items.json fixture."""
    with open(fixtures_dir / "library_items.json") as f:
        return cast(dict[str, Any], json.load(f))


@pytest.fixture
def authorize_response(fixtures_dir: Path) -> dict[str, Any]:
    """Load authorize.json fixture."""
    with open(fixtures_dir / "authorize.json") as f:
        return cast(dict[str, Any], json.load(f))


class TestAbsFolder:
    """Tests for AbsFolder schema."""

    def test_valid_folder(self) -> None:
        """Test parsing valid folder data."""
        data = {
            "id": "fol_123",
            "fullPath": "/audiobooks",
            "libraryId": "lib_456",
            "addedAt": 1633522963509,
        }
        folder = AbsFolder.model_validate(data)
        assert folder.id == "fol_123"
        assert folder.full_path == "/audiobooks"
        assert folder.library_id == "lib_456"
        assert folder.added_at == 1633522963509

    def test_extra_fields_ignored(self) -> None:
        """Test that extra fields are ignored."""
        data = {
            "id": "fol_123",
            "fullPath": "/audiobooks",
            "libraryId": "lib_456",
            "addedAt": 1633522963509,
            "unknownField": "should be ignored",
        }
        folder = AbsFolder.model_validate(data)
        assert folder.id == "fol_123"
        assert not hasattr(folder, "unknownField")

    def test_missing_required_field(self) -> None:
        """Test that missing required fields raise error."""
        data = {"id": "fol_123", "fullPath": "/audiobooks"}
        with pytest.raises(ValidationError):
            AbsFolder.model_validate(data)


class TestAbsLibrarySettings:
    """Tests for AbsLibrarySettings schema."""

    def test_defaults(self) -> None:
        """Test default values."""
        settings = AbsLibrarySettings.model_validate({})
        assert settings.cover_aspect_ratio == 1
        assert settings.disable_watcher is False
        assert settings.skip_matching_media_with_asin is False
        assert settings.auto_scan_cron_expression is None

    def test_full_settings(self) -> None:
        """Test parsing full settings."""
        data = {
            "coverAspectRatio": 2,
            "disableWatcher": True,
            "skipMatchingMediaWithAsin": True,
            "skipMatchingMediaWithIsbn": True,
            "autoScanCronExpression": "0 0 * * *",
        }
        settings = AbsLibrarySettings.model_validate(data)
        assert settings.cover_aspect_ratio == 2
        assert settings.disable_watcher is True
        assert settings.auto_scan_cron_expression == "0 0 * * *"


class TestAbsLibrarySchema:
    """Tests for AbsLibrarySchema."""

    def test_valid_library(self, libraries_response: dict[str, Any]) -> None:
        """Test parsing valid library data."""
        lib_data = libraries_response["libraries"][0]
        library = AbsLibrarySchema.model_validate(lib_data)
        assert library.id == "lib_c1u6t4p45c35rf0nzd"
        assert library.name == "Audiobooks"
        assert library.media_type == "book"
        assert library.display_order == 1
        assert len(library.folders) == 1

    def test_get_folder_paths(self, libraries_response: dict[str, Any]) -> None:
        """Test get_folder_paths method."""
        lib_data = libraries_response["libraries"][0]
        library = AbsLibrarySchema.model_validate(lib_data)
        paths = library.get_folder_paths()
        assert paths == ["/audiobooks"]

    def test_podcast_library(self, libraries_response: dict[str, Any]) -> None:
        """Test parsing podcast library."""
        lib_data = libraries_response["libraries"][1]
        library = AbsLibrarySchema.model_validate(lib_data)
        assert library.name == "Podcasts"
        assert library.media_type == "podcast"


class TestAbsLibrariesResponse:
    """Tests for AbsLibrariesResponse."""

    def test_full_response(self, libraries_response: dict[str, Any]) -> None:
        """Test parsing full libraries response."""
        response = AbsLibrariesResponse.model_validate(libraries_response)
        assert len(response.libraries) == 2
        assert response.libraries[0].name == "Audiobooks"
        assert response.libraries[1].name == "Podcasts"

    def test_validate_helper(self, libraries_response: dict[str, Any]) -> None:
        """Test validate_libraries_response helper."""
        response = validate_libraries_response(libraries_response)
        assert len(response.libraries) == 2

    def test_empty_libraries(self) -> None:
        """Test empty libraries list."""
        response = AbsLibrariesResponse.model_validate({"libraries": []})
        assert len(response.libraries) == 0


class TestAbsBookMetadata:
    """Tests for AbsBookMetadata schema."""

    def test_full_metadata(self) -> None:
        """Test parsing full metadata."""
        data = {
            "title": "Test Book",
            "titleIgnorePrefix": "Test Book",
            "subtitle": "A Subtitle",
            "authorName": "Test Author",
            "authorNameLF": "Author, Test",
            "narratorName": "Test Narrator",
            "seriesName": "Test Series",
            "genres": ["Fantasy", "Adventure"],
            "publishedYear": "2024",
            "publisher": "Test Publisher",
            "description": "A test description",
            "isbn": "1234567890",
            "asin": "B0TEST123",
            "language": "English",
            "explicit": False,
        }
        metadata = AbsBookMetadata.model_validate(data)
        assert metadata.title == "Test Book"
        assert metadata.subtitle == "A Subtitle"
        assert metadata.author_name == "Test Author"
        assert metadata.asin == "B0TEST123"

    def test_minimal_metadata(self) -> None:
        """Test parsing minimal metadata."""
        metadata = AbsBookMetadata.model_validate({})
        assert metadata.title == ""
        assert metadata.subtitle is None
        assert metadata.author_name is None


class TestAbsBookMedia:
    """Tests for AbsBookMedia schema."""

    def test_full_media(self) -> None:
        """Test parsing full media data."""
        data = {
            "metadata": {"title": "Test", "asin": "B0TEST"},
            "coverPath": "/path/to/cover.jpg",
            "tags": ["tag1", "tag2"],
            "numTracks": 1,
            "numAudioFiles": 1,
            "numChapters": 10,
            "duration": 36000.0,
            "size": 500000000,
        }
        media = AbsBookMedia.model_validate(data)
        assert media.metadata.title == "Test"
        assert media.cover_path == "/path/to/cover.jpg"
        assert media.num_chapters == 10
        assert media.duration == 36000.0

    def test_defaults(self) -> None:
        """Test default values."""
        media = AbsBookMedia.model_validate({})
        assert media.metadata.title == ""
        assert media.cover_path is None
        assert media.duration == 0.0


class TestAbsLibraryItemSchema:
    """Tests for AbsLibraryItemSchema."""

    def test_full_item(self, library_items_response: dict[str, Any]) -> None:
        """Test parsing full library item."""
        item_data = library_items_response["results"][0]
        item = AbsLibraryItemSchema.model_validate(item_data)
        assert item.id == "li_sao16_alicization"
        assert item.library_id == "lib_c1u6t4p45c35rf0nzd"
        assert item.media_type == "book"
        assert item.is_missing is False

    def test_property_accessors(self, library_items_response: dict[str, Any]) -> None:
        """Test property accessors for nested fields."""
        item_data = library_items_response["results"][0]
        item = AbsLibraryItemSchema.model_validate(item_data)
        assert item.title == "Sword Art Online vol_16 Alicization Exploding"
        assert item.author_name == "Reki Kawahara"
        assert item.narrator_name == "Bryce Papenbrook"
        assert item.series_name == "Sword Art Online"
        assert item.asin == "B0DK9TS6D9"
        assert item.duration == 36000.0

    def test_item_with_subtitle(self, library_items_response: dict[str, Any]) -> None:
        """Test item with subtitle."""
        item_data = library_items_response["results"][1]
        item = AbsLibraryItemSchema.model_validate(item_data)
        assert item.title == "Mushoku Tensei vol_03"
        assert item.subtitle == "Jobless Reincarnation"

    def test_missing_optional_fields(self) -> None:
        """Test item with minimal fields."""
        data = {
            "id": "li_test",
            "libraryId": "lib_test",
        }
        item = AbsLibraryItemSchema.model_validate(data)
        assert item.id == "li_test"
        assert item.title == ""
        assert item.asin is None


class TestAbsLibraryItemsResponse:
    """Tests for AbsLibraryItemsResponse."""

    def test_full_response(self, library_items_response: dict[str, Any]) -> None:
        """Test parsing full library items response."""
        response = AbsLibraryItemsResponse.model_validate(library_items_response)
        assert len(response.results) > 0
        assert response.total >= len(response.results)

    def test_validate_helper(self, library_items_response: dict[str, Any]) -> None:
        """Test validate_library_items_response helper."""
        response = validate_library_items_response(library_items_response)
        assert len(response.results) > 0

    def test_pagination_fields(self) -> None:
        """Test pagination fields."""
        data = {
            "results": [],
            "total": 100,
            "limit": 10,
            "page": 5,
            "sortBy": "media.metadata.authorName",
            "sortDesc": True,
        }
        response = AbsLibraryItemsResponse.model_validate(data)
        assert response.total == 100
        assert response.limit == 10
        assert response.page == 5
        assert response.sort_by == "media.metadata.authorName"
        assert response.sort_desc is True

    def test_null_sort_by(self) -> None:
        """Test that null sortBy is handled."""
        data = {
            "results": [],
            "total": 0,
            "sortBy": None,
        }
        response = AbsLibraryItemsResponse.model_validate(data)
        assert response.sort_by is None


class TestAbsUserPermissions:
    """Tests for AbsUserPermissions schema."""

    def test_defaults(self) -> None:
        """Test default permissions."""
        perms = AbsUserPermissions.model_validate({})
        assert perms.download is True
        assert perms.update is False
        assert perms.delete is False
        assert perms.access_all_libraries is True

    def test_admin_permissions(self) -> None:
        """Test admin permissions."""
        data = {
            "download": True,
            "update": True,
            "delete": True,
            "upload": True,
            "accessAllLibraries": True,
            "accessAllTags": True,
            "accessExplicitContent": True,
        }
        perms = AbsUserPermissions.model_validate(data)
        assert perms.update is True
        assert perms.delete is True
        assert perms.upload is True


class TestAbsUserSchema:
    """Tests for AbsUserSchema."""

    def test_admin_user(self, authorize_response: dict[str, Any]) -> None:
        """Test parsing admin user.

        Note: authorize_response fixture now matches /api/me format which
        returns user data directly (not wrapped in {"user": ...}).
        """
        user = AbsUserSchema.model_validate(authorize_response)
        assert user.username == "mamfast"
        assert user.type == "admin"
        assert user.has_admin is True
        assert user.is_active is True

    def test_regular_user(self) -> None:
        """Test parsing regular user."""
        data = {
            "id": "user_123",
            "username": "reader",
            "type": "user",
            "isActive": True,
            "createdAt": 1633522963509,
        }
        user = AbsUserSchema.model_validate(data)
        assert user.has_admin is False
        assert user.type == "user"


class TestAbsAuthorizeResponse:
    """Tests for AbsAuthorizeResponse.

    Note: The actual API (/api/me) returns user data directly. The client wraps it
    in {"user": ...} for schema validation. These tests use wrapped format.
    """

    def test_full_response(self, authorize_response: dict[str, Any]) -> None:
        """Test parsing full authorize response (wrapped format)."""
        # Client wraps /api/me response in {"user": ...} for schema validation
        wrapped = {"user": authorize_response}
        response = AbsAuthorizeResponse.model_validate(wrapped)
        assert response.user.username == "mamfast"
        assert response.user.has_admin is True

    def test_validate_helper(self, authorize_response: dict[str, Any]) -> None:
        """Test validate_authorize_response helper (wrapped format)."""
        # Client wraps /api/me response in {"user": ...} for schema validation
        wrapped = {"user": authorize_response}
        response = validate_authorize_response(wrapped)
        assert response.user.id == "usr_mamfast"


class TestSchemaForwardCompatibility:
    """Tests for forward compatibility with new API fields."""

    def test_library_with_new_fields(self) -> None:
        """Test that libraries with unknown fields still parse."""
        data = {
            "id": "lib_test",
            "name": "Test",
            "folders": [],
            "displayOrder": 1,
            "mediaType": "book",
            "createdAt": 1633522963509,
            "lastUpdate": 1633522963509,
            "futureField": "should be ignored",
            "anotherNewField": {"nested": "data"},
        }
        library = AbsLibrarySchema.model_validate(data)
        assert library.id == "lib_test"

    def test_item_with_new_fields(self) -> None:
        """Test that items with unknown fields still parse."""
        data = {
            "id": "li_test",
            "libraryId": "lib_test",
            "futureFeature": True,
            "newMetrics": {"plays": 100},
        }
        item = AbsLibraryItemSchema.model_validate(data)
        assert item.id == "li_test"

    def test_user_with_new_permissions(self) -> None:
        """Test that users with new permissions still parse."""
        data = {
            "id": "user_test",
            "username": "test",
            "type": "user",
            "createdAt": 1633522963509,
            "permissions": {
                "download": True,
                "newPermission": True,
                "futureAccess": ["lib1", "lib2"],
            },
        }
        user = AbsUserSchema.model_validate(data)
        assert user.permissions.download is True


class TestSchemaValidationErrors:
    """Tests for validation error handling."""

    def test_library_missing_id(self) -> None:
        """Test that missing library ID raises error."""
        data = {
            "name": "Test",
            "folders": [],
            "displayOrder": 1,
            "mediaType": "book",
            "createdAt": 1633522963509,
            "lastUpdate": 1633522963509,
        }
        with pytest.raises(ValidationError) as exc_info:
            AbsLibrarySchema.model_validate(data)
        assert "id" in str(exc_info.value)

    def test_item_missing_library_id(self) -> None:
        """Test that missing libraryId raises error."""
        data = {"id": "li_test"}
        with pytest.raises(ValidationError) as exc_info:
            AbsLibraryItemSchema.model_validate(data)
        assert "libraryId" in str(exc_info.value)

    def test_invalid_type(self) -> None:
        """Test that invalid types raise errors."""
        data = {
            "id": "lib_test",
            "name": "Test",
            "folders": "not a list",  # Should be list
            "displayOrder": 1,
            "mediaType": "book",
            "createdAt": 1633522963509,
            "lastUpdate": 1633522963509,
        }
        with pytest.raises(ValidationError):
            AbsLibrarySchema.model_validate(data)
