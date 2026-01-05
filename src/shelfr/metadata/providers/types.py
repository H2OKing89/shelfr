"""
Core types for the metadata provider system.

This module defines the contract between providers and the aggregator:
- LookupContext: What providers need to look up metadata
- ProviderResult: What providers return
- FieldName: All canonical metadata field names (typed)
- IdType: Supported identifier types
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

# Supported identifier types for lookups
IdType = Literal["asin", "isbn", "goodreads_id", "hardcover_id"]

# All canonical metadata fields - typed literal for safety
# Note: Consider migrating to Enum later for runtime validation/iteration
FieldName = Literal[
    # Identifiers
    "asin",
    # Book metadata
    "title",
    "subtitle",
    "authors",
    "narrators",
    "publisher",
    "language",
    "release_date",
    "series_name",
    "series_position",
    "genres",
    "summary",
    "description",
    "cover_url",
    "format_type",
    "literature_type",
    "is_adult",
    "copyright",
    "rating",
    "isbn",
    # Audio metadata (from MediaInfo)
    "chapters",
    "duration_seconds",
    "codec",
    "bitrate",
    "channels",
    "container",
]


@dataclass(frozen=True)
class LookupContext:
    """Everything a provider might need to look up metadata.

    The `ids` dict is future-proof: adding goodreads_id/hardcover_id
    doesn't require changing this class signature.

    Attributes:
        ids: Mapping of identifier type to value (e.g., {"asin": "B08G9PRS1K"})
        path: Path to m4b file or audiobook folder
        source_dir: Libation source path (series heuristics)
        existing_abs_json: Pre-loaded ABS metadata.json contents
    """

    ids: dict[IdType, str] = field(default_factory=dict)
    path: Path | None = None
    source_dir: Path | None = None
    existing_abs_json: dict[str, Any] | None = None

    @property
    def asin(self) -> str | None:
        """Get ASIN if present."""
        return self.ids.get("asin")

    @property
    def isbn(self) -> str | None:
        """Get ISBN if present."""
        return self.ids.get("isbn")

    @classmethod
    def from_id(
        cls,
        *,
        id_type: IdType,
        identifier: str,
        path: Path | None = None,
        source_dir: Path | None = None,
        existing_abs_json: dict[str, Any] | None = None,
    ) -> LookupContext:
        """Create context from a single identifier."""
        return cls(
            ids={id_type: identifier},
            path=path,
            source_dir=source_dir,
            existing_abs_json=existing_abs_json,
        )

    @classmethod
    def from_asin(
        cls,
        *,
        asin: str,
        path: Path | None = None,
        source_dir: Path | None = None,
        existing_abs_json: dict[str, Any] | None = None,
    ) -> LookupContext:
        """Create context from ASIN (convenience method)."""
        return cls.from_id(
            id_type="asin",
            identifier=asin,
            path=path,
            source_dir=source_dir,
            existing_abs_json=existing_abs_json,
        )

    @classmethod
    def from_isbn(
        cls,
        *,
        isbn: str,
        path: Path | None = None,
        source_dir: Path | None = None,
        existing_abs_json: dict[str, Any] | None = None,
    ) -> LookupContext:
        """Create context from ISBN (convenience method)."""
        return cls.from_id(
            id_type="isbn",
            identifier=isbn,
            path=path,
            source_dir=source_dir,
            existing_abs_json=existing_abs_json,
        )


@dataclass
class ProviderResult:
    """Result from a metadata provider lookup.

    Providers return partial data in `fields`. The aggregator merges
    results from multiple providers using confidence scores and priority.

    Attributes:
        provider: Name of the provider (e.g., "audnex", "mediainfo")
        success: Whether the lookup succeeded
        fields: Field name -> value mapping (partial canonical data)
        confidence: Field name -> confidence score (0.0 to 1.0)
        error: Error message if success=False
        cached: Whether result came from cache
        cache_age_seconds: Age of cached result if cached=True
        raw_data: Original API response for backward compatibility
    """

    provider: str
    success: bool
    fields: dict[FieldName, Any] = field(default_factory=dict)
    confidence: dict[FieldName, float] = field(default_factory=dict)
    error: str | None = None
    cached: bool = False
    cache_age_seconds: int | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)

    def set_field(
        self,
        name: FieldName,
        value: Any,
        confidence: float = 1.0,
    ) -> None:
        """Set a field value with confidence score.

        Args:
            name: Canonical field name
            value: Field value
            confidence: Confidence score (0.0 to 1.0, default 1.0)

        Raises:
            ValueError: If confidence is outside [0.0, 1.0] range
        """
        if not 0.0 <= confidence <= 1.0:
            raise ValueError(f"confidence must be in [0.0, 1.0], got {confidence}")
        self.fields[name] = value
        self.confidence[name] = confidence

    @classmethod
    def failure(cls, provider: str, error: str) -> ProviderResult:
        """Create a failed result."""
        return cls(provider=provider, success=False, error=error)

    @classmethod
    def empty(cls, provider: str) -> ProviderResult:
        """Create a successful but empty result."""
        return cls(provider=provider, success=True)
