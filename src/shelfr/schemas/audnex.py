"""Pydantic schemas for Audnex API response validation.

These schemas are used for parsing raw Audnex API responses.

Note: AudnexAuthor, AudnexSeries, AudnexGenre are structurally identical to
the canonical Person, Series, Genre in metadata.schemas.canonical. They are
kept separate to avoid circular imports (schemas → metadata → providers → schemas).

For internal processing, prefer the canonical schemas. These Audnex-prefixed
schemas are for API response parsing only.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AudnexAuthor(BaseModel):
    """Author/narrator from Audnex API.

    Structurally identical to metadata.schemas.canonical.Person.
    """

    name: str
    asin: str | None = None

    model_config = {"extra": "ignore"}


class AudnexSeries(BaseModel):
    """Series info from Audnex API.

    Structurally identical to metadata.schemas.canonical.Series.
    """

    name: str
    position: str | None = None
    asin: str | None = None

    model_config = {"extra": "ignore"}


class AudnexGenre(BaseModel):
    """Genre from Audnex API.

    Structurally identical to metadata.schemas.canonical.Genre.
    """

    name: str
    asin: str | None = None
    type: Literal["genre", "tag"] | None = None

    model_config = {"extra": "ignore"}


class AudnexChapter(BaseModel):
    """Chapter from Audnex API chapters endpoint."""

    length_ms: int = Field(alias="lengthMs")
    start_offset_ms: int = Field(alias="startOffsetMs")
    start_offset_sec: int = Field(alias="startOffsetSec")
    title: str

    model_config = {"extra": "ignore", "populate_by_name": True}


class AudnexChaptersResponse(BaseModel):
    """
    Response from Audnex /books/{asin}/chapters endpoint.

    Contains chapter timing and branding info.
    """

    asin: str
    brand_intro_duration_ms: int = Field(default=0, alias="brandIntroDurationMs")
    brand_outro_duration_ms: int = Field(default=0, alias="brandOutroDurationMs")
    chapters: list[AudnexChapter] = Field(default_factory=list)
    is_accurate: bool = Field(default=True, alias="isAccurate")
    runtime_length_ms: int | None = Field(default=None, alias="runtimeLengthMs")
    runtime_length_sec: int | None = Field(default=None, alias="runtimeLengthSec")

    model_config = {"extra": "ignore", "populate_by_name": True}


class AudnexBook(BaseModel):
    """
    Validated Audnex book response from /books/{asin} endpoint.

    Uses extra="ignore" to allow new fields from API without breaking.
    This catches malformed responses and API changes that remove required fields.
    """

    asin: str
    title: str
    subtitle: str | None = None
    authors: list[AudnexAuthor] = Field(default_factory=list)
    narrators: list[AudnexAuthor] = Field(default_factory=list)
    series_primary: AudnexSeries | None = Field(default=None, alias="seriesPrimary")
    series_secondary: AudnexSeries | None = Field(default=None, alias="seriesSecondary")
    genres: list[AudnexGenre] = Field(default_factory=list)
    release_date: str | None = Field(default=None, alias="releaseDate")
    publisher_name: str | None = Field(default=None, alias="publisherName")
    summary: str | None = None
    image: str | None = None
    length_min: int | None = Field(default=None, alias="lengthMin")
    language: str | None = None
    region: str | None = None
    rating: str | None = None
    format_type: str | None = Field(default=None, alias="formatType")
    description: str | None = None

    model_config = {"extra": "ignore", "populate_by_name": True}  # API may add new fields


class AudnexAuthorProfile(BaseModel):
    """
    Validated Audnex author response from /authors/{asin} endpoint.
    """

    asin: str
    name: str
    description: str | None = None
    image: str | None = None
    genres: list[AudnexGenre] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


def validate_audnex_book(data: dict[str, Any]) -> AudnexBook:
    """
    Validate Audnex book API response.

    Args:
        data: Raw JSON response from Audnex /books/{asin}

    Returns:
        Validated AudnexBook instance

    Raises:
        pydantic.ValidationError: If required fields missing or wrong type
    """
    return AudnexBook.model_validate(data)


def validate_audnex_chapters(data: dict[str, Any]) -> AudnexChaptersResponse:
    """
    Validate Audnex chapters API response.

    Args:
        data: Raw JSON response from Audnex /books/{asin}/chapters

    Returns:
        Validated AudnexChaptersResponse instance

    Raises:
        pydantic.ValidationError: If required fields missing or wrong type
    """
    return AudnexChaptersResponse.model_validate(data)


def validate_audnex_author(data: dict[str, Any]) -> AudnexAuthorProfile:
    """
    Validate Audnex author API response.

    Args:
        data: Raw JSON response from Audnex /authors/{asin}

    Returns:
        Validated AudnexAuthorProfile instance

    Raises:
        pydantic.ValidationError: If required fields missing or wrong type
    """
    return AudnexAuthorProfile.model_validate(data)
