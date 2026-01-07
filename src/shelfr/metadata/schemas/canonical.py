"""
Canonical metadata schemas for audiobook processing.

This module defines the unified internal representation of audiobook metadata.
All metadata providers emit partial data that gets merged into CanonicalMetadata.

Design principles:
- Single source of truth for Person, Series, Genre, CanonicalMetadata
- Keep all core types in ONE file to avoid circular imports
- Use Pydantic v2 for validation and serialization
- Match Audnex naming conventions for easy API mapping

These schemas are INTERNAL truth - richer than any single export format.
Exporters (OPF, ABS JSON, MAM JSON) map canonical → specific format.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

# Supported content classification flags
# Designed to be platform-agnostic but starts with MAM vocabulary
ContentFlag = Literal["cLang", "vio", "sSex", "eSex", "abridged", "lgbt"]


class Person(BaseModel):
    """Author, narrator, or other contributor.

    Unified schema that works for both Audnex authors/narrators and
    internal processing. Replaces both AudnexAuthor and opf.Person.

    Attributes:
        name: Display name (e.g., "Brandon Sanderson")
        asin: Amazon ASIN if known (e.g., "B001IGFHW6")
    """

    name: str
    asin: str | None = None

    model_config = {"extra": "ignore"}


class Genre(BaseModel):
    """Genre or tag from metadata sources.

    Attributes:
        name: Genre display name (e.g., "Science Fiction & Fantasy")
        asin: Amazon genre ASIN if known
        type: Classification hint ("genre" vs "tag")
    """

    name: str
    asin: str | None = None
    type: Literal["genre", "tag"] | None = None

    model_config = {"extra": "ignore"}


class Series(BaseModel):
    """Series information with position.

    Attributes:
        name: Series name (e.g., "The Stormlight Archive")
        position: Book position (e.g., "1", "2.5", "1-3")
        asin: Amazon series ASIN if known
    """

    name: str
    position: str | None = None
    asin: str | None = None

    model_config = {"extra": "ignore"}

    @field_validator("position", mode="before")
    @classmethod
    def normalize_position(cls, v: str | int | float | None) -> str | None:
        """Convert numeric positions to strings."""
        if v is None:
            return None
        return str(v)


class CanonicalMetadata(BaseModel):
    """
    Canonical audiobook metadata schema.

    This is the internal representation that all providers emit into and
    all exporters read from. It's richer than any single export format.

    Field naming follows Audnex conventions for easy API mapping.
    Exporters are responsible for mapping to format-specific names.

    Required vs Optional:
    - asin + title are required (minimum viable audiobook)
    - Everything else optional with sensible defaults

    Usage:
        # From Audnex API response
        meta = CanonicalMetadata.from_audnex(audnex_response)

        # From aggregated provider results
        meta = CanonicalMetadata(asin="...", title="...", **merged_fields)
    """

    # Required identifiers
    asin: str
    title: str

    # People
    authors: list[Person] = Field(default_factory=list)
    narrators: list[Person] = Field(default_factory=list)

    # Series (Audnex supports primary + secondary)
    series_primary: Series | None = Field(default=None, alias="seriesPrimary")
    series_secondary: Series | None = Field(default=None, alias="seriesSecondary")

    # Text content
    subtitle: str | None = None
    description: str = ""
    summary: str = ""

    # Classification
    genres: list[Genre] = Field(default_factory=list)
    literature_type: str | None = Field(default=None, alias="literatureType")
    format_type: str = Field(default="unabridged", alias="formatType")
    is_adult: bool = Field(default=False, alias="isAdult")

    # Content flags for platform-agnostic classification (MAM, AO3, etc.)
    content_flags: list[ContentFlag] = Field(
        default_factory=list,
        description=(
            "Platform-agnostic content warnings/classification flags. "
            "Supported values: 'cLang' (crude language), 'vio' (violence), "
            "'sSex' (some sexual content), 'eSex' (explicit sexual content), "
            "'abridged', 'lgbt' (LGBTQ+ themes)"
        ),
    )

    # Publication info
    publisher_name: str = Field(default="", alias="publisherName")
    release_date: str | datetime | None = Field(default=None, alias="releaseDate")
    copyright: int | None = None
    language: str = "english"
    region: Literal["au", "ca", "de", "es", "fr", "in", "it", "jp", "us", "uk"] = "us"

    # Source provenance (Phase 10)
    # Split "retrieval provider" (API) from "source platform" (storefront)
    retrieved_via: str | None = Field(
        default=None,
        description="API/provider that supplied this metadata (e.g., 'audnex', 'hardcover')",
    )
    source_platform: str | None = Field(
        default=None,
        description="Platform the metadata represents (e.g., 'Audible', 'Hardcover')",
    )
    source_region: Literal["au", "ca", "de", "es", "fr", "in", "it", "jp", "us", "uk"] | None = (
        Field(
            default=None,
            description="Region where source ID was resolved (for region-locked IDs like ASINs)",
        )
    )
    source_id: str | None = Field(
        default=None,
        description="Primary identifier from source (ASIN, ISBN, etc.)",
    )
    source_id_type: Literal["asin", "isbn", "hardcover_id"] | None = Field(
        default=None,
        description="Type of source_id",
    )
    source_url: str | None = Field(
        default=None,
        description="Canonical URL to source storefront (pre-built from platform + region + id)",
    )

    # Runtime
    runtime_length_min: int | None = Field(default=None, alias="runtimeLengthMin")

    # Media
    image: str | None = None  # Cover image URL
    isbn: str | None = None
    rating: str = ""

    model_config = {"extra": "ignore", "populate_by_name": True}

    @field_validator("content_flags")
    @classmethod
    def validate_mutually_exclusive_flags(cls, flags: list[ContentFlag]) -> list[ContentFlag]:
        """Prevent conflicting sexual content flags.

        sSex (suggestive) and eSex (explicit) are mutually exclusive.
        If both are present, this indicates a data conflict.
        """
        if "sSex" in flags and "eSex" in flags:
            raise ValueError("Cannot have both sSex and eSex flags - they are mutually exclusive")
        return flags

    @model_validator(mode="after")
    def validate_source_provenance(self) -> CanonicalMetadata:
        """Ensure source_url is only set when source_id is present.

        It doesn't make sense to have a URL without knowing what ID it points to.
        This catches configuration errors early.
        """
        if self.source_url and not self.source_id:
            raise ValueError("source_url requires source_id to be set")
        return self

    @field_validator(
        "description",
        "summary",
        "publisher_name",
        "rating",
        "format_type",
        "language",
        mode="before",
    )
    @classmethod
    def coerce_null_to_empty_or_default(cls, v: str | None, info: ValidationInfo) -> str:
        """Coerce null values from Audnex API to empty string or field default.

        Audnex API can return null for these fields, but we want non-optional
        strings internally for easier downstream processing.
        """
        if v is None:
            # Return field-specific defaults
            defaults = {
                "format_type": "unabridged",
                "language": "english",
            }
            return defaults.get(info.field_name or "", "")
        return v

    @classmethod
    def from_audnex(cls, data: dict[str, object]) -> CanonicalMetadata:
        """Create from raw Audnex API response.

        Handles field mapping and validation in one step.
        """
        return cls.model_validate(data)

    @property
    def release_year(self) -> int | None:
        """Extract year from release_date."""
        if not self.release_date:
            return None
        if isinstance(self.release_date, datetime):
            return self.release_date.year
        # Parse ISO date string
        try:
            return int(self.release_date[:4])
        except (ValueError, IndexError):
            return None

    @property
    def release_date_iso(self) -> str | None:
        """Get release date in ISO format (YYYY-MM-DD)."""
        if not self.release_date:
            return None
        if isinstance(self.release_date, datetime):
            return self.release_date.strftime("%Y-%m-%d")
        # Only return if we have a full ISO date (YYYY-MM-DD = 10 chars minimum)
        if len(self.release_date) >= 10:
            return self.release_date[:10]
        return None

    def get_all_genres(self) -> list[str]:
        """Get deduplicated genre/tag names."""
        seen: set[str] = set()
        result: list[str] = []
        for g in self.genres:
            if g.name not in seen:
                seen.add(g.name)
                result.append(g.name)
        return result

    @property
    def primary_author(self) -> str | None:
        """Get first author name, or None if no authors."""
        return self.authors[0].name if self.authors else None

    @property
    def primary_narrator(self) -> str | None:
        """Get first narrator name, or None if no narrators."""
        return self.narrators[0].name if self.narrators else None

    @property
    def all_series(self) -> list[Series]:
        """Get all series (primary + secondary) as a list."""
        result = []
        if self.series_primary:
            result.append(self.series_primary)
        if self.series_secondary:
            result.append(self.series_secondary)
        return result
