"""Pydantic schemas for Audiobookshelf metadata.json validation.

This schema matches what Audiobookshelf reads from metadata.json files
during library scans to populate audiobook metadata.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AbsChapter(BaseModel):
    """Chapter entry for Audiobookshelf metadata.json."""

    id: int
    start: float  # Start time in seconds
    end: float  # End time in seconds
    title: str

    model_config = {"extra": "ignore"}


class AbsMetadataJson(BaseModel):
    """Schema for Audiobookshelf metadata.json file.

    This file is read by ABS during library scans to populate
    audiobook metadata. All fields are optional except title.

    Field names use camelCase for ABS compatibility via aliases.
    """

    title: str
    subtitle: str | None = None
    authors: list[str] = Field(default_factory=list)
    narrators: list[str] = Field(default_factory=list)
    series: list[str] = Field(default_factory=list)  # Format: "Series Name #1"
    genres: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    chapters: list[AbsChapter] = Field(default_factory=list)
    # Accept ABS-style camelCase keys on input (validation_alias) and emit them on output (serialization_alias)
    # With populate_by_name=True, Python code can still use snake_case field names
    published_year: str | None = Field(
        default=None, validation_alias="publishedYear", serialization_alias="publishedYear"
    )
    published_date: str | None = Field(
        default=None, validation_alias="publishedDate", serialization_alias="publishedDate"
    )
    publisher: str | None = None
    description: str | None = None  # HTML allowed
    isbn: str | None = None
    asin: str | None = None
    language: str | None = None
    explicit: bool = False
    abridged: bool = False

    model_config = {
        "extra": "ignore",
        "populate_by_name": True,
        "json_schema_extra": {
            "examples": [
                {
                    "title": "Example Book",
                    "authors": ["Author Name"],
                    "asin": "B0CJWTXLPJ",
                }
            ]
        },
    }


def validate_abs_metadata(data: dict[str, Any]) -> AbsMetadataJson:
    """Validate metadata.json structure.

    Args:
        data: Dictionary to validate

    Returns:
        Validated AbsMetadataJson model

    Raises:
        pydantic.ValidationError: If validation fails
    """
    return AbsMetadataJson.model_validate(data)
