"""Pydantic schemas for Audiobookshelf metadata.json validation.

This schema matches what Audiobookshelf reads from metadata.json files
during library scans to populate audiobook metadata.

Two modes of operation:
- Reading (lenient): Use AbsMetadataJson with all optional fields
- Writing (strict): Use validate_abs_metadata_for_write() which requires title
"""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


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
    audiobook metadata. Title is optional for reading existing files
    (some may have incomplete metadata), but required for writing.

    Field names use camelCase for ABS compatibility via aliases.

    For reading existing metadata.json: Use model_validate() directly
    For writing new metadata.json: Use validate_abs_metadata_for_write()
    """

    title: str | None = None  # Optional for reading, required for writing
    subtitle: str | None = None
    authors: list[str] = Field(default_factory=list)
    narrators: list[str] = Field(default_factory=list)
    series: list[str] = Field(default_factory=list)  # Format: "Series Name #1"
    genres: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    chapters: list[AbsChapter] = Field(default_factory=list)
    # Accept ABS-style camelCase keys on input (validation_alias)
    # and emit them on output (serialization_alias).
    # With populate_by_name=True, Python code can still use snake_case field names
    published_year: str | int | None = Field(
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

    @field_validator("asin")
    @classmethod
    def validate_asin_format(cls, v: str | None) -> str | None:
        """Validate ASIN format and log warning if invalid.

        ASINs should be 10 alphanumeric characters (uppercase letters and digits).
        Does not raise on invalid ASINs, only logs a warning.

        Args:
            v: ASIN value to validate

        Returns:
            Original ASIN value (unchanged)
        """
        if v is not None and v != "" and not re.match(r"^[A-Z0-9]{10}$", v):
            logger.warning(
                "Invalid ASIN format: %r (expected 10 uppercase alphanumeric characters)", v
            )
        return v


def validate_abs_metadata(data: dict[str, Any]) -> AbsMetadataJson:
    """Validate metadata.json structure (lenient, for reading).

    Args:
        data: Dictionary to validate

    Returns:
        Validated AbsMetadataJson model

    Raises:
        pydantic.ValidationError: If validation fails
    """
    return AbsMetadataJson.model_validate(data)


def validate_abs_metadata_for_write(data: dict[str, Any]) -> AbsMetadataJson:
    """Validate metadata.json structure for writing (strict, requires title).

    Args:
        data: Dictionary to validate

    Returns:
        Validated AbsMetadataJson model

    Raises:
        pydantic.ValidationError: If validation fails
        ValueError: If title is missing or empty
    """
    model = AbsMetadataJson.model_validate(data)
    if not model.title:
        msg = "title is required for writing metadata.json"
        raise ValueError(msg)
    return model
