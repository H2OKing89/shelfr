"""
Pydantic schema for config.yaml validation.

This validates the YAML structure at load time before converting to dataclasses.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator


class EnvironmentSchema(BaseModel):
    """Environment/Docker settings."""

    libation_container: str = "libation"
    docker_bin: str = "/usr/bin/docker"
    target_uid: int = 99
    target_gid: int = 100
    env: str = "development"
    log_level: str = "INFO"

    @field_validator("target_uid", "target_gid", mode="before")
    @classmethod
    def coerce_to_int(cls, v: Any) -> int:
        """Allow string values from YAML and convert to int."""
        if isinstance(v, str):
            return int(v)
        if isinstance(v, int):
            return v
        raise TypeError(f"Expected int or str, got {type(v).__name__}")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is a recognized value."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid_levels:
            raise ValueError(f"Invalid log_level '{v}'. Must be one of: {valid_levels}")
        return v.upper()


class PathsSchema(BaseModel):
    """Path configuration settings."""

    library_root: str = Field(..., description="Libation library directory")
    torrent_output: str = Field(..., description="Where .torrent files are written")
    seed_root: str = Field(..., description="qBittorrent seed directory")
    state_file: str = "./data/processed.json"
    log_file: str = "./logs/mamfast.log"

    @field_validator("library_root", "torrent_output", "seed_root")
    @classmethod
    def validate_required_paths(cls, v: str, info: ValidationInfo) -> str:
        """Ensure required paths are non-empty."""
        if not v or not v.strip():
            raise ValueError(f"{info.field_name} is required but empty")
        return v


class MamSchema(BaseModel):
    """MAM compliance settings."""

    max_filename_length: int = Field(default=225, ge=50, le=300)
    allowed_extensions: list[str] = Field(
        default_factory=lambda: [".m4b", ".jpg", ".jpeg", ".png", ".pdf", ".cue"]
    )

    @field_validator("allowed_extensions")
    @classmethod
    def validate_extensions(cls, v: list[str]) -> list[str]:
        """Ensure extensions start with a dot."""
        for ext in v:
            if not ext.startswith("."):
                raise ValueError(f"Extension '{ext}' must start with a dot")
        return v


class MkbrrSchema(BaseModel):
    """mkbrr Docker configuration."""

    image: str = "ghcr.io/autobrr/mkbrr:latest"
    preset: str = "mam"
    host_data_root: str = "/mnt/user/data"
    container_data_root: str = "/data"
    host_config_dir: str = "/mnt/cache/appdata/mkbrr"
    container_config_dir: str = "/root/.config/mkbrr"


class QBittorrentSchema(BaseModel):
    """qBittorrent settings (credentials come from .env)."""

    category: str = "mam-audiobooks"
    tags: list[str] = Field(default_factory=lambda: ["mamfast"])
    auto_start: bool = True
    auto_tmm: bool = False
    save_path: str = ""


class AudnexSchema(BaseModel):
    """Audnex API settings."""

    base_url: str = "https://api.audnex.us"
    timeout_seconds: int = Field(default=30, ge=5, le=120)

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Ensure URL has valid protocol."""
        if not v.startswith(("http://", "https://")):
            raise ValueError(f"base_url must start with http:// or https://, got: {v}")
        return v.rstrip("/")  # Normalize: remove trailing slash


class MediaInfoSchema(BaseModel):
    """MediaInfo settings."""

    binary: str = "mediainfo"


class FiltersSchema(BaseModel):
    """
    Title filtering settings.

    Note: remove_phrases and author_map have moved to naming.json.
    Only behavioral flags remain here.
    """

    remove_book_numbers: bool = True
    transliterate_japanese: bool = True

    # Legacy fields - accepted but ignored (for migration)
    # These are now in naming.json
    remove_phrases: list[str] | None = Field(default=None, exclude=True)
    author_map: dict[str, str] | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def warn_deprecated_fields(self) -> FiltersSchema:
        """Log deprecation warning for legacy fields."""
        # Note: We just accept and ignore these for backward compatibility
        # The actual warning happens at config load time in config.py
        return self


class LibationSchema(BaseModel):
    """Libation library discovery settings."""

    folder_pattern: str = r"^(.*?)(?: vol_(\d+))?(?: \((\d{4})\))?$"
    metadata_file_suffix: str = ".metadata.json"
    asin_pattern: str = r"^[A-Z0-9]{10}$"

    @field_validator("folder_pattern", "asin_pattern")
    @classmethod
    def validate_regex(cls, v: str, info: ValidationInfo) -> str:
        """Validate regex patterns compile."""
        import re

        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(f"Invalid regex in {info.field_name}: {e}") from e
        return v


class ConfigSchema(BaseModel):
    """
    Complete config.yaml schema.

    Validates structure and types. Actual path resolution and
    environment variable merging happens in config.py after validation.
    """

    environment: EnvironmentSchema = Field(default_factory=EnvironmentSchema)
    paths: PathsSchema
    mam: MamSchema = Field(default_factory=MamSchema)
    mkbrr: MkbrrSchema = Field(default_factory=MkbrrSchema)
    qbittorrent: QBittorrentSchema = Field(default_factory=QBittorrentSchema)
    audnex: AudnexSchema = Field(default_factory=AudnexSchema)
    mediainfo: MediaInfoSchema = Field(default_factory=MediaInfoSchema)
    filters: FiltersSchema = Field(default_factory=FiltersSchema)
    libation: LibationSchema = Field(default_factory=LibationSchema)

    model_config = {"extra": "forbid"}  # Catch typos in config keys


def validate_config_yaml(data: dict[str, Any]) -> ConfigSchema:
    """
    Validate config.yaml data against schema.

    Args:
        data: Parsed YAML dictionary

    Returns:
        Validated ConfigSchema

    Raises:
        pydantic.ValidationError: If validation fails
    """
    return ConfigSchema.model_validate(data)
