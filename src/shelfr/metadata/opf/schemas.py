"""
Pydantic schemas for OPF metadata generation.

Two-layer architecture:
    1. CanonicalMetadata - Internal representation matching Audnexus API
    2. OPFMetadata - ABS-compatible export profile

This separation keeps the internal schema stable while allowing
export format changes without affecting the canonical model.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Person(BaseModel):
    """Author or narrator with optional ASIN identifier."""

    name: str
    asin: str | None = None

    model_config = {"extra": "ignore"}


class Genre(BaseModel):
    """Genre or tag from Audnexus."""

    name: str
    asin: str | None = None
    type: Literal["genre", "tag"] | None = None

    model_config = {"extra": "ignore"}


class Series(BaseModel):
    """Series information with position."""

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

    This is the internal representation that matches the Audnexus API response.
    Use this model for long-term storage and validation.

    All fields follow Audnexus naming conventions for easy mapping.
    """

    # Required fields
    asin: str
    title: str
    authors: list[Person] = Field(default_factory=list)
    description: str = ""
    format_type: str = Field(default="unabridged", alias="formatType")
    language: str = "english"
    publisher_name: str = Field(default="", alias="publisherName")
    rating: str = ""
    region: Literal["au", "ca", "de", "es", "fr", "in", "it", "jp", "us", "uk"] = "us"
    release_date: str | datetime | None = Field(default=None, alias="releaseDate")
    runtime_length_min: int | None = Field(default=None, alias="runtimeLengthMin")
    summary: str = ""

    # Optional fields
    copyright: int | None = None
    genres: list[Genre] = Field(default_factory=list)
    image: str | None = None
    is_adult: bool = Field(default=False, alias="isAdult")
    isbn: str | None = None
    literature_type: str | None = Field(default=None, alias="literatureType")
    narrators: list[Person] = Field(default_factory=list)
    series_primary: Series | None = Field(default=None, alias="seriesPrimary")
    series_secondary: Series | None = Field(default=None, alias="seriesSecondary")
    subtitle: str | None = None

    model_config = {"extra": "ignore", "populate_by_name": True}

    @classmethod
    def from_audnex(cls, data: dict[str, object]) -> CanonicalMetadata:
        """Create from raw Audnexus API response."""
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
        # Assume already ISO-like, extract date portion
        return self.release_date[:10] if len(self.release_date) >= 10 else self.release_date

    def get_all_genres(self) -> list[str]:
        """Get deduplicated genre/tag names."""
        seen: set[str] = set()
        result: list[str] = []
        for g in self.genres:
            if g.name not in seen:
                seen.add(g.name)
                result.append(g.name)
        return result


class OPFCreator(BaseModel):
    """Creator element for OPF (author/narrator/translator/etc.)."""

    name: str
    role: str = "aut"  # MARC relator codes: aut, nrt, trl, ill, edt, ctb
    file_as: str | None = None  # "Last, First" sorting form


class OPFIdentifier(BaseModel):
    """Identifier element for OPF (ASIN/ISBN)."""

    value: str
    scheme: Literal["ASIN", "ISBN", "UUID"]


class OPFSeries(BaseModel):
    """Series info in Calibre format for OPF."""

    name: str
    index: str  # Can be decimal like "1.5"


class OPFMetadata(BaseModel):
    """
    ABS-compatible OPF export profile.

    This model contains only fields that ABS can reliably ingest.
    Custom/extended fields are stored separately for future use.

    Use OPFGenerator to convert this to XML.
    """

    # Core required fields
    title: str
    language: str = "eng"  # ISO 639-2/B code

    # People
    creators: list[OPFCreator] = Field(default_factory=list)

    # Identifiers
    identifiers: list[OPFIdentifier] = Field(default_factory=list)

    # Dates
    date: str | None = None  # ISO date, ABS keeps year

    # Text fields
    subtitle: str | None = None
    publisher: str | None = None
    description: str | None = None

    # Subjects (genres/tags)
    subjects: list[str] = Field(default_factory=list)

    # Series (Calibre convention)
    series: list[OPFSeries] = Field(default_factory=list)

    # Tags (non-standard but ABS may ingest dc:tag)
    tags: list[str] = Field(default_factory=list)

    # Custom metadata (ABS ignores, we keep for ourselves)
    custom_meta: dict[str, str] = Field(default_factory=dict)

    model_config = {"extra": "ignore"}

    @classmethod
    def from_canonical(cls, meta: CanonicalMetadata) -> OPFMetadata:
        """
        Convert canonical metadata to ABS-friendly OPF format.

        This applies the Audnexus → OPF mapping rules:
        - Title is cleaned using filter_title (removes format indicators like "Light Novel")
        - Authors are filtered (removes translators/illustrators from author list)
        - Translators/illustrators extracted and credited with proper MARC roles
        - Authors get role="aut", narrators get role="nrt"
        - Language is converted to ISO 639-2/B (e.g., "english" → "eng")
        - Series uses Calibre meta format with filter_series applied
        - Custom fields preserved in custom_meta
        """
        from shelfr.metadata.opf.helpers import get_naming_config
        from shelfr.metadata.opf.mappings import to_iso_language
        from shelfr.utils.naming import (
            filter_authors,
            filter_series,
            filter_title,
            is_author_role,
        )

        # Load naming config for filter functions
        naming_config = get_naming_config()

        # Clean title using filter_title (removes "Light Novel", etc.)
        # keep_volume=True to preserve "Vol. X" for ABS
        clean_title = filter_title(meta.title, naming_config=naming_config, keep_volume=True)

        # Clean subtitle if present
        clean_subtitle: str | None = None
        if meta.subtitle:
            clean_subtitle = filter_title(
                meta.subtitle, naming_config=naming_config, keep_volume=True
            )

        # Build creators list with proper role filtering
        creators: list[OPFCreator] = []

        # Convert Person list to dict format for filter_authors
        authors_dicts = [{"name": a.name} for a in meta.authors]

        # Filter authors - removes translators/illustrators/etc.
        filtered_authors = filter_authors(authors_dicts)
        for author_dict in filtered_authors:
            name = author_dict.get("name", "")
            creators.append(OPFCreator(name=name, role="aut"))

        # Add translators/illustrators with proper MARC roles
        from shelfr.metadata.opf.helpers import detect_role_from_name

        for author in meta.authors:
            if is_author_role(author.name):
                clean_name, role = detect_role_from_name(author.name)
                creators.append(OPFCreator(name=clean_name, role=role))

        # Add narrators
        for narrator in meta.narrators:
            creators.append(OPFCreator(name=narrator.name, role="nrt"))

        # Build identifiers
        identifiers: list[OPFIdentifier] = []
        if meta.asin:
            identifiers.append(OPFIdentifier(value=meta.asin, scheme="ASIN"))
        if meta.isbn:
            identifiers.append(OPFIdentifier(value=meta.isbn, scheme="ISBN"))

        # Build series list (primary first, then secondary)
        # Apply filter_series for consistent naming
        series: list[OPFSeries] = []
        if meta.series_primary:
            clean_series_name = filter_series(meta.series_primary.name, naming_config=naming_config)
            series.append(
                OPFSeries(
                    name=clean_series_name,
                    index=meta.series_primary.position or "1",
                )
            )
        if meta.series_secondary:
            clean_series_name = filter_series(
                meta.series_secondary.name, naming_config=naming_config
            )
            series.append(
                OPFSeries(
                    name=clean_series_name,
                    index=meta.series_secondary.position or "1",
                )
            )

        # Build tags (isAdult flag becomes a tag)
        tags: list[str] = []
        if meta.is_adult:
            tags.append("Adult")

        # Build custom metadata (fields ABS ignores but we want to keep)
        custom_meta: dict[str, str] = {}
        if meta.rating:
            custom_meta["audnex:rating"] = meta.rating
        if meta.runtime_length_min:
            custom_meta["audnex:runtimeLengthMin"] = str(meta.runtime_length_min)
        if meta.format_type:
            custom_meta["audnex:formatType"] = meta.format_type
        if meta.region:
            custom_meta["audnex:region"] = meta.region
        if meta.image:
            custom_meta["audnex:image"] = meta.image
        if meta.copyright:
            custom_meta["audnex:copyright"] = str(meta.copyright)
        if meta.literature_type:
            custom_meta["audnex:literatureType"] = meta.literature_type

        # Use description for OPF (strip HTML from summary if using that)
        # Prefer description (plain text) over summary (may contain HTML)
        desc = meta.description or meta.summary or ""

        return cls(
            title=clean_title,
            language=to_iso_language(meta.language),
            creators=creators,
            identifiers=identifiers,
            date=meta.release_date_iso,
            subtitle=clean_subtitle,
            publisher=meta.publisher_name or None,
            description=desc if desc else None,
            subjects=meta.get_all_genres(),
            series=series,
            tags=tags,
            custom_meta=custom_meta,
        )
