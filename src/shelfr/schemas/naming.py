"""Pydantic schema for naming.json validation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class TitleSubtitleNormalization(BaseModel):
    """Title/subtitle normalization settings."""

    enabled: bool = True
    log_swaps: bool = True


class InheritThePrefixConfig(BaseModel):
    """Config for inheriting 'The' prefix from title to series name."""

    enabled: bool = True

    model_config = {"extra": "allow"}  # Allow _comment fields


class SeriesNameCleaningConfig(BaseModel):
    """Series name cleaning configuration."""

    enabled: bool = True
    inherit_the_prefix: InheritThePrefixConfig = Field(default_factory=InheritThePrefixConfig)

    model_config = {"extra": "allow"}  # Allow _comment fields


class AuthorRolesConfig(BaseModel):
    """Author roles configuration for filtering non-primary authors."""

    match_mode: Literal["suffix", "prefix", "contains"] = "suffix"
    case_sensitive: bool = False
    roles: list[str] = Field(default_factory=list)
    credit_roles: list[str] = Field(default_factory=list)


class PhraseCategory(BaseModel):
    """Category of phrases to filter (format indicators, genre tags, etc.)."""

    match_mode: Literal["phrase", "regex"] = "phrase"
    case_sensitive: bool = False
    phrases: list[str] = Field(default_factory=list)


class RegexCategory(BaseModel):
    """Category of regex patterns (series suffixes, etc.)."""

    match_mode: Literal["phrase", "regex"] = "regex"
    case_sensitive: bool = False
    patterns: list[str] = Field(default_factory=list)

    @field_validator("patterns")
    @classmethod
    def validate_regex_patterns(cls, v: list[str]) -> list[str]:
        """Validate that all patterns are valid regex."""
        for pattern in v:
            try:
                re.compile(pattern)
            except re.error as e:
                raise ValueError(f"Invalid regex pattern '{pattern}': {e}") from e
        return v


class SubtitlePatternsConfig(BaseModel):
    """Two-tier subtitle handling configuration."""

    remove_if_matches_series: bool = True
    remove_patterns: list[str] = Field(default_factory=list)
    keep_patterns: list[str] = Field(default_factory=list)

    @field_validator("remove_patterns", "keep_patterns")
    @classmethod
    def validate_regex_patterns(cls, v: list[str]) -> list[str]:
        """Validate that all patterns are valid regex."""
        for pattern in v:
            try:
                re.compile(pattern)
            except re.error as e:
                raise ValueError(f"Invalid regex pattern '{pattern}': {e}") from e
        return v


class SubtitleRedundancyRule(BaseModel):
    """A single subtitle redundancy rule with template placeholders."""

    id: str = Field(..., description="Unique rule identifier")
    description: str = Field(..., description="Human-readable description")
    pattern_template: str = Field(
        ..., description="Regex template with {{series}}/{{title}} placeholders"
    )
    action: Literal["drop_subtitle", "strip_match"] = Field(
        ..., description="What to do when pattern matches"
    )

    @field_validator("pattern_template")
    @classmethod
    def validate_pattern_template(cls, v: str) -> str:
        """Validate that the template becomes valid regex when placeholders are replaced."""
        # Replace placeholders with dummy text to validate base regex
        test_pattern = v.replace("{{series}}", "TestSeries").replace("{{title}}", "TestTitle")
        try:
            re.compile(test_pattern)
        except re.error as e:
            raise ValueError(f"Invalid regex template '{v}': {e}") from e
        return v


class SubtitleRedundancyConfig(BaseModel):
    """Subtitle redundancy checking configuration."""

    enabled: bool = True
    rules: list[SubtitleRedundancyRule] = Field(default_factory=list)


class PreserveExactConfig(BaseModel):
    """Configuration for titles that bypass all cleaning rules."""

    case_sensitive: bool = True
    titles: list[str] = Field(default_factory=list)


class PreserveInJsonConfig(BaseModel):
    """Patterns preserved in MAM JSON but removed from folder/file names."""

    volume_patterns: list[str] = Field(default_factory=list)

    @field_validator("volume_patterns")
    @classmethod
    def validate_regex_patterns(cls, v: list[str]) -> list[str]:
        """Validate that all patterns are valid regex."""
        for pattern in v:
            try:
                re.compile(pattern)
            except re.error as e:
                raise ValueError(f"Invalid regex pattern '{pattern}': {e}") from e
        return v


class PathTruncationConfig(BaseModel):
    """
    Configuration for what gets dropped when paths exceed MAM's 225-char limit.

    The drop_priority list controls the order components are removed:
    - Components are dropped from first to last until path fits
    - "arc", "author", "year" are valid component names
    - Series/title and ASIN are NEVER dropped (identity components)

    Example:
        drop_priority: ["arc", "author", "year"]  # Default: drop arc first, then author, then year
        drop_priority: ["arc", "year", "author"]  # Keep author longer, drop year before author
    """

    drop_priority: list[str] = Field(
        default=["arc", "author", "year"],
        description="Order to drop components when path too long (first dropped first)",
    )

    @field_validator("drop_priority")
    @classmethod
    def validate_drop_priority(cls, v: list[str]) -> list[str]:
        """Validate that only known components are listed."""
        valid_components = {"arc", "author", "year"}
        for comp in v:
            if comp not in valid_components:
                raise ValueError(
                    f"Unknown drop_priority component '{comp}'. "
                    f"Valid components: {sorted(valid_components)}"
                )
        return v


class NamingSchema(BaseModel):
    """
    Pydantic schema for naming.json validation.

    Validates the JSON structure at load time, catching:
    - Invalid regex patterns
    - Missing required fields
    - Wrong types
    - Unknown keys (with extra="forbid")

    The validated data is then converted to NamingConfig dataclass
    for use throughout the application.
    """

    # Version field (aliased from _version, optional for legacy configs)
    version: str = Field(default="0.0.0", alias="_version", pattern=r"^\d+\.\d+\.\d+$")

    # Title/subtitle normalization settings
    title_subtitle_normalization: TitleSubtitleNormalization = Field(
        default_factory=TitleSubtitleNormalization
    )

    # Series name cleaning settings
    series_name_cleaning: SeriesNameCleaningConfig = Field(default_factory=SeriesNameCleaningConfig)

    # Author role filtering
    author_roles: AuthorRolesConfig = Field(default_factory=AuthorRolesConfig)

    # Phrase categories (case-insensitive whole phrase matching)
    format_indicators: PhraseCategory = Field(default_factory=PhraseCategory)
    genre_tags: PhraseCategory = Field(default_factory=PhraseCategory)
    publisher_tags: PhraseCategory = Field(default_factory=PhraseCategory)

    # Series suffix regex patterns
    series_suffixes: RegexCategory = Field(default_factory=RegexCategory)

    # Subtitle handling (two-tier: remove and keep patterns)
    subtitle_patterns: SubtitlePatternsConfig = Field(default_factory=SubtitlePatternsConfig)

    # Subtitle redundancy rules (template-based with {{series}}/{{title}})
    subtitle_redundancy_rules: SubtitleRedundancyConfig = Field(
        default_factory=SubtitleRedundancyConfig
    )

    # Titles that bypass ALL cleaning rules
    preserve_exact: PreserveExactConfig = Field(default_factory=PreserveExactConfig)

    # Author name mapping (foreign name -> romanized name)
    author_map: dict[str, str] = Field(default_factory=dict)

    # Patterns preserved in JSON but removed from folder/file names
    preserve_in_json: PreserveInJsonConfig = Field(default_factory=PreserveInJsonConfig)

    # Path truncation settings (what gets dropped when path exceeds 225 chars)
    path_truncation: PathTruncationConfig = Field(default_factory=PathTruncationConfig)

    @field_validator("author_map")
    @classmethod
    def filter_comment_keys(cls, v: dict[str, str]) -> dict[str, str]:
        """Filter out comment keys starting with underscore."""
        return {k: val for k, val in v.items() if not k.startswith("_") and isinstance(val, str)}

    @model_validator(mode="before")
    @classmethod
    def filter_comments(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Remove top-level comment keys before validation."""
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if not k.startswith("_") or k == "_version"}
        return data

    model_config = {
        "extra": "forbid",  # Fail on unknown keys (catches typos)
        "populate_by_name": True,  # Allow both alias and field name
    }


def validate_naming_json(data: Mapping[str, Any]) -> NamingSchema:
    """
    Validate naming.json data against the schema.

    Args:
        data: Raw dict loaded from naming.json

    Returns:
        Validated NamingSchema instance

    Raises:
        pydantic.ValidationError: If validation fails
    """
    return NamingSchema.model_validate(data)
