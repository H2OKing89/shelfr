"""Pydantic schemas for Audiobookshelf API response validation.

These schemas validate responses from the Audiobookshelf API and provide
type-safe access to library and item data. Uses extra="ignore" to allow
new fields from API without breaking (forward compatibility).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AbsFolder(BaseModel):
    """Folder within an ABS library."""

    id: str
    full_path: str = Field(alias="fullPath")
    library_id: str = Field(alias="libraryId")
    added_at: int = Field(alias="addedAt")

    model_config = {"extra": "ignore", "populate_by_name": True}


class AbsLibrarySettings(BaseModel):
    """Library settings from ABS."""

    cover_aspect_ratio: int = Field(default=1, alias="coverAspectRatio")
    disable_watcher: bool = Field(default=False, alias="disableWatcher")
    skip_matching_media_with_asin: bool = Field(default=False, alias="skipMatchingMediaWithAsin")
    skip_matching_media_with_isbn: bool = Field(default=False, alias="skipMatchingMediaWithIsbn")
    auto_scan_cron_expression: str | None = Field(default=None, alias="autoScanCronExpression")

    model_config = {"extra": "ignore", "populate_by_name": True}


class AbsLibrarySchema(BaseModel):
    """Library from ABS API /api/libraries endpoint."""

    id: str
    name: str
    folders: list[AbsFolder] = Field(default_factory=list)
    display_order: int = Field(alias="displayOrder")
    icon: str = Field(default="database")
    media_type: str = Field(alias="mediaType")
    provider: str = Field(default="audible")
    settings: AbsLibrarySettings = Field(default_factory=AbsLibrarySettings)
    created_at: int = Field(alias="createdAt")
    last_update: int = Field(alias="lastUpdate")

    model_config = {"extra": "ignore", "populate_by_name": True}

    def get_folder_paths(self) -> list[str]:
        """Get list of folder paths in this library."""
        return [f.full_path for f in self.folders]


class AbsLibrariesResponse(BaseModel):
    """Response from GET /api/libraries."""

    libraries: list[AbsLibrarySchema]

    model_config = {"extra": "ignore"}


class AbsBookMetadata(BaseModel):
    """Book metadata from ABS library item."""

    title: str = ""
    title_ignore_prefix: str = Field(default="", alias="titleIgnorePrefix")
    subtitle: str | None = None
    author_name: str | None = Field(default=None, alias="authorName")
    author_name_lf: str | None = Field(default=None, alias="authorNameLF")
    narrator_name: str | None = Field(default=None, alias="narratorName")
    series_name: str | None = Field(default=None, alias="seriesName")
    genres: list[str] = Field(default_factory=list)
    published_year: str | None = Field(default=None, alias="publishedYear")
    published_date: str | None = Field(default=None, alias="publishedDate")
    publisher: str | None = None
    description: str | None = None
    isbn: str | None = None
    asin: str | None = None
    language: str | None = None
    explicit: bool = False

    model_config = {"extra": "ignore", "populate_by_name": True}


class AbsBookMedia(BaseModel):
    """Media info for a book item in ABS."""

    metadata: AbsBookMetadata = Field(default_factory=AbsBookMetadata)
    cover_path: str | None = Field(default=None, alias="coverPath")
    tags: list[str] = Field(default_factory=list)
    num_tracks: int = Field(default=0, alias="numTracks")
    num_audio_files: int = Field(default=0, alias="numAudioFiles")
    num_chapters: int = Field(default=0, alias="numChapters")
    duration: float = 0.0
    size: int = 0

    model_config = {"extra": "ignore", "populate_by_name": True}


class AbsLibraryItemSchema(BaseModel):
    """Library item (book) from ABS API.

    This represents a single audiobook in the library, containing
    paths, metadata, and media information.
    """

    id: str
    ino: str = ""
    library_id: str = Field(alias="libraryId")
    folder_id: str = Field(default="", alias="folderId")
    path: str = ""
    rel_path: str = Field(default="", alias="relPath")
    is_file: bool = Field(default=False, alias="isFile")
    mtime_ms: int = Field(default=0, alias="mtimeMs")
    ctime_ms: int = Field(default=0, alias="ctimeMs")
    birthtime_ms: int = Field(default=0, alias="birthtimeMs")
    added_at: int = Field(default=0, alias="addedAt")
    updated_at: int = Field(default=0, alias="updatedAt")
    last_scan: int | None = Field(default=None, alias="lastScan")
    scan_version: str | None = Field(default=None, alias="scanVersion")
    is_missing: bool = Field(default=False, alias="isMissing")
    is_invalid: bool = Field(default=False, alias="isInvalid")
    media_type: str = Field(default="book", alias="mediaType")
    media: AbsBookMedia = Field(default_factory=AbsBookMedia)
    num_files: int = Field(default=0, alias="numFiles")
    size: int = 0

    model_config = {"extra": "ignore", "populate_by_name": True}

    @property
    def title(self) -> str:
        """Get book title from nested metadata."""
        return self.media.metadata.title

    @property
    def subtitle(self) -> str | None:
        """Get book subtitle from nested metadata."""
        return self.media.metadata.subtitle

    @property
    def author_name(self) -> str | None:
        """Get author name from nested metadata."""
        return self.media.metadata.author_name

    @property
    def narrator_name(self) -> str | None:
        """Get narrator name from nested metadata."""
        return self.media.metadata.narrator_name

    @property
    def series_name(self) -> str | None:
        """Get series name from nested metadata."""
        return self.media.metadata.series_name

    @property
    def asin(self) -> str | None:
        """Get ASIN from nested metadata."""
        return self.media.metadata.asin

    @property
    def isbn(self) -> str | None:
        """Get ISBN from nested metadata."""
        return self.media.metadata.isbn

    @property
    def duration(self) -> float:
        """Get duration from media."""
        return self.media.duration


class AbsLibraryItemsResponse(BaseModel):
    """Response from GET /api/libraries/{id}/items."""

    results: list[AbsLibraryItemSchema]
    total: int = 0
    limit: int = 0
    page: int = 0
    sort_by: str | None = Field(default=None, alias="sortBy")
    sort_desc: bool = Field(default=False, alias="sortDesc")
    filter_by: str | None = Field(default=None, alias="filterBy")
    media_type: str = Field(default="book", alias="mediaType")
    minified: bool = False
    collapsed_series: Any = Field(default=None, alias="collapsedSeries")
    include: str = Field(default="")

    model_config = {"extra": "ignore", "populate_by_name": True}


class AbsUserPermissions(BaseModel):
    """User permissions from ABS."""

    download: bool = True
    update: bool = False
    delete: bool = False
    upload: bool = False
    access_all_libraries: bool = Field(default=True, alias="accessAllLibraries")
    access_all_tags: bool = Field(default=True, alias="accessAllTags")
    access_explicit_content: bool = Field(default=True, alias="accessExplicitContent")

    model_config = {"extra": "ignore", "populate_by_name": True}


class AbsUserSchema(BaseModel):
    """User from ABS /api/authorize response."""

    id: str
    username: str
    type: str  # "admin", "user", "guest"
    token: str | None = None
    is_active: bool = Field(default=True, alias="isActive")
    is_locked: bool = Field(default=False, alias="isLocked")
    last_seen: int | None = Field(default=None, alias="lastSeen")
    created_at: int = Field(alias="createdAt")
    permissions: AbsUserPermissions = Field(default_factory=AbsUserPermissions)
    libraries_accessible: list[str] = Field(default_factory=list, alias="librariesAccessible")
    item_tags_accessible: list[str] = Field(default_factory=list, alias="itemTagsAccessible")

    model_config = {"extra": "ignore", "populate_by_name": True}

    @property
    def has_admin(self) -> bool:
        """Check if user has admin privileges."""
        return self.type == "admin"


class AbsAuthorizeResponse(BaseModel):
    """Response from POST /api/authorize."""

    user: AbsUserSchema

    model_config = {"extra": "ignore"}


# Validation helper functions


def validate_libraries_response(data: dict[str, Any]) -> AbsLibrariesResponse:
    """Validate and parse libraries API response.

    Args:
        data: Raw API response dict

    Returns:
        Validated AbsLibrariesResponse

    Raises:
        pydantic.ValidationError: If response doesn't match schema
    """
    return AbsLibrariesResponse.model_validate(data)


def validate_library_items_response(data: dict[str, Any]) -> AbsLibraryItemsResponse:
    """Validate and parse library items API response.

    Args:
        data: Raw API response dict

    Returns:
        Validated AbsLibraryItemsResponse

    Raises:
        pydantic.ValidationError: If response doesn't match schema
    """
    return AbsLibraryItemsResponse.model_validate(data)


def validate_authorize_response(data: dict[str, Any]) -> AbsAuthorizeResponse:
    """Validate and parse authorize API response.

    Args:
        data: Raw API response dict

    Returns:
        Validated AbsAuthorizeResponse

    Raises:
        pydantic.ValidationError: If response doesn't match schema
    """
    return AbsAuthorizeResponse.model_validate(data)


# =============================================================================
# Metadata Search Schemas (for /api/search/books endpoint)
# =============================================================================


class AbsSearchSeriesEntry(BaseModel):
    """Series entry in search results."""

    series: str
    sequence: str

    model_config = {"extra": "ignore"}


class AbsSearchBookResult(BaseModel):
    """Single book result from /api/search/books endpoint.

    This is the response from external metadata providers like Audible.
    Different from AbsLibraryItemSchema which represents items in the library.
    """

    title: str
    subtitle: str | None = None
    author: str
    narrator: str | None = None
    publisher: str | None = None
    published_year: str | None = Field(default=None, alias="publishedYear")
    description: str | None = None
    description_plain: str | None = Field(default=None, alias="descriptionPlain")
    cover: str | None = None
    asin: str | None = None
    isbn: str | None = None
    genres: list[str] = Field(default_factory=list)
    tags: str | None = None  # Note: comma-separated string, not array
    series: list[AbsSearchSeriesEntry] | None = None
    language: str | None = None
    duration: int | None = None  # Duration in MINUTES (not seconds)
    region: str | None = None
    rating: str | None = None
    abridged: bool = False

    model_config = {"extra": "ignore", "populate_by_name": True}

    @property
    def series_name(self) -> str | None:
        """Get primary series name if available."""
        if self.series and len(self.series) > 0:
            return self.series[0].series
        return None

    @property
    def series_sequence(self) -> str | None:
        """Get primary series sequence if available."""
        if self.series and len(self.series) > 0:
            return self.series[0].sequence
        return None


def validate_search_books_response(data: list[Any]) -> list[AbsSearchBookResult]:
    """Validate and parse search books API response.

    Args:
        data: Raw API response (list of book results)

    Returns:
        List of validated AbsSearchBookResult

    Raises:
        pydantic.ValidationError: If response doesn't match schema
    """
    return [AbsSearchBookResult.model_validate(item) for item in data]
