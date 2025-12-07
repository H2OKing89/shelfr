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


# Valid Audnex regions
VALID_AUDNEX_REGIONS = frozenset(["us", "uk", "au", "ca", "de", "es", "fr", "in", "it", "jp"])


class AudnexSchema(BaseModel):
    """Audnex API settings."""

    base_url: str = "https://api.audnex.us"
    timeout_seconds: int = Field(default=30, ge=5, le=120)
    # Regions to try in order (first success wins)
    regions: list[str] = Field(default_factory=lambda: ["us"])

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Ensure URL has valid protocol."""
        if not v.startswith(("http://", "https://")):
            raise ValueError(f"base_url must start with http:// or https://, got: {v}")
        return v.rstrip("/")  # Normalize: remove trailing slash

    @field_validator("regions")
    @classmethod
    def validate_regions(cls, v: list[str]) -> list[str]:
        """Validate region codes are valid."""
        if not v:
            raise ValueError("At least one region is required")
        invalid = [r for r in v if r.lower() not in VALID_AUDNEX_REGIONS]
        if invalid:
            raise ValueError(f"Invalid regions: {invalid}. Valid: {sorted(VALID_AUDNEX_REGIONS)}")
        return [r.lower() for r in v]  # Normalize to lowercase


class MediaInfoSchema(BaseModel):
    """MediaInfo settings."""

    binary: str = "mediainfo"


class AudiobookshelfPathMapSchema(BaseModel):
    """Docker path mapping for Audiobookshelf."""

    container: str = Field(..., description="Path as seen inside ABS container")
    host: str = Field(..., description="Corresponding path on host filesystem")

    @field_validator("container", "host")
    @classmethod
    def validate_paths(cls, v: str, info: ValidationInfo) -> str:
        """Ensure paths are non-empty and absolute-looking."""
        if not v or not v.strip():
            raise ValueError(f"{info.field_name} path is required but empty")
        if not v.startswith("/"):
            raise ValueError(f"{info.field_name} path must be absolute (start with /)")
        return v.rstrip("/")  # Normalize: remove trailing slash


class AudiobookshelfLibrarySchema(BaseModel):
    """Audiobookshelf library configuration."""

    id: str = Field(..., description="ABS library ID (e.g., lib_xxxxx)")
    name: str = Field(default="", description="Human-readable library name")
    mamfast_managed: bool = Field(
        default=False, description="Whether mamfast imports to this library"
    )

    @field_validator("id")
    @classmethod
    def validate_library_id(cls, v: str) -> str:
        """Validate library ID format."""
        if not v or not v.strip():
            raise ValueError("Library id is required")
        if not v.startswith("lib_"):
            raise ValueError(f"Library id should start with 'lib_', got: {v}")
        return v


# Valid trumping aggressiveness levels
VALID_TRUMP_AGGRESSIVENESS = frozenset(["conservative", "balanced", "aggressive"])


class TrumpingSchema(BaseModel):
    """Configuration for quality-based replacement.

    Nested under AudiobookshelfImportSchema.trumping in config.
    See docs/audiobookshelf/TRUMPING.md for full documentation.
    """

    enabled: bool = Field(default=False, description="Enable trumping")

    aggressiveness: str = Field(
        default="balanced",
        description="How eager to replace existing content: conservative | balanced | aggressive",
    )

    min_bitrate_increase_kbps: int = Field(
        default=64,
        ge=0,
        description="Minimum bitrate improvement for trumping (kbps)",
    )

    prefer_chapters: bool = Field(
        default=True,
        description="Chapters trump non-chaptered at same quality",
    )

    prefer_stereo: bool = Field(
        default=True,
        description="Stereo trumps mono at same quality",
    )

    min_duration_ratio: float = Field(
        default=0.9,
        ge=0.5,
        le=1.0,
        description="Minimum duration ratio (incoming/existing) - reject if below",
    )

    max_duration_ratio: float = Field(
        default=1.25,
        ge=1.0,
        le=2.0,
        description="Maximum duration ratio - keep both if exceeded",
    )

    archive_root: str | None = Field(
        default=None,
        description="Where to archive replaced content (required if enabled)",
    )

    archive_by_year: bool = Field(
        default=True,
        description="Organize archive by year",
    )

    @field_validator("aggressiveness")
    @classmethod
    def validate_aggressiveness(cls, v: str) -> str:
        """Validate aggressiveness is a recognized value."""
        if v.lower() not in VALID_TRUMP_AGGRESSIVENESS:
            valid = sorted(VALID_TRUMP_AGGRESSIVENESS)
            raise ValueError(f"Invalid aggressiveness '{v}'. Must be one of: {valid}")
        return v.lower()

    @field_validator("archive_root")
    @classmethod
    def validate_archive_root_absolute(cls, v: str | None) -> str | None:
        """Ensure archive_root is absolute when provided."""
        if v is not None and v.strip():
            if not v.startswith("/"):
                raise ValueError(f"archive_root must be an absolute path (start with /), got: {v}")
            return v.rstrip("/")  # Normalize: remove trailing slash
        return v

    @model_validator(mode="after")
    def validate_archive_required_when_enabled(self) -> TrumpingSchema:
        """Ensure archive_root is set when trumping is enabled."""
        if self.enabled and (not self.archive_root or not self.archive_root.strip()):
            raise ValueError("archive_root is required when trumping is enabled")
        return self


# Valid cleanup strategies
VALID_CLEANUP_STRATEGIES = frozenset(["none", "hide", "move", "delete"])


class CleanupSchema(BaseModel):
    """Configuration for post-import cleanup of Libation source files.

    Nested under AudiobookshelfImportSchema.cleanup in config.
    See docs/audiobookshelf/CLEANUP_PLAN.md for full documentation.
    """

    strategy: str = Field(
        default="none",
        description="Cleanup strategy: none | hide | move | delete",
    )

    cleanup_path: str | None = Field(
        default=None,
        description="Destination path for moved files (required if strategy=move)",
    )

    require_seed_exists: bool = Field(
        default=True,
        description="Only cleanup if seed hardlinks exist",
    )

    verify_in_abs: bool = Field(
        default=False,
        description="Query ABS API to confirm book exists before cleanup",
    )

    hide_marker: str = Field(
        default=".mamfast_imported",
        description="Marker filename for hide strategy",
    )

    min_age_days: int = Field(
        default=0,
        ge=0,
        description="Only cleanup sources older than N days (0 = disabled)",
    )

    ignore_dirs: list[str] = Field(
        default_factory=lambda: ["__import_test", ".git", ".venv"],
        description="Directory names to always ignore during standalone cleanup",
    )

    ignore_glob: list[str] = Field(
        default_factory=lambda: ["*/__*", "*/.#*"],
        description="Glob patterns to ignore during standalone cleanup",
    )

    @field_validator("strategy")
    @classmethod
    def validate_strategy(cls, v: str) -> str:
        """Validate cleanup strategy is a recognized value."""
        if v.lower() not in VALID_CLEANUP_STRATEGIES:
            valid = sorted(VALID_CLEANUP_STRATEGIES)
            raise ValueError(f"Invalid cleanup strategy '{v}'. Must be one of: {valid}")
        return v.lower()

    @field_validator("cleanup_path")
    @classmethod
    def validate_cleanup_path_absolute(cls, v: str | None) -> str | None:
        """Ensure cleanup_path is absolute when provided."""
        if v is not None and v.strip():
            if not v.startswith("/"):
                raise ValueError(f"cleanup_path must be an absolute path (start with /), got: {v}")
            return v.rstrip("/")  # Normalize: remove trailing slash
        return v

    @field_validator("hide_marker")
    @classmethod
    def validate_hide_marker(cls, v: str) -> str:
        """Validate hide_marker is a valid filename."""
        if not v or not v.strip():
            raise ValueError("hide_marker cannot be empty")
        # Should be a simple filename, not a path
        if "/" in v or "\\" in v:
            raise ValueError("hide_marker must be a filename, not a path")
        return v

    @model_validator(mode="after")
    def validate_move_requires_path(self) -> CleanupSchema:
        """Ensure cleanup_path is set when strategy is move."""
        if self.strategy == "move" and (not self.cleanup_path or not self.cleanup_path.strip()):
            raise ValueError("cleanup_path is required when strategy is 'move'")
        return self


class AudiobookshelfImportSchema(BaseModel):
    """Audiobookshelf import settings."""

    duplicate_policy: str = Field(default="skip", description="What to do with duplicates")
    trigger_scan: str = Field(default="batch", description="When to trigger ABS library scan")
    unknown_asin_policy: str = Field(
        default="import",
        description="How to handle books without ASIN: import | quarantine | skip",
    )
    quarantine_path: str | None = Field(
        default=None,
        description="Path for quarantined books (required if unknown_asin_policy=quarantine)",
    )
    ignore_file_extensions: list[str] = Field(
        default_factory=list,
        description="File patterns to ignore during import (e.g., '.json', '*.metadata.json')",
    )
    trumping: TrumpingSchema = Field(
        default_factory=TrumpingSchema,
        description="Quality-based replacement settings",
    )
    cleanup: CleanupSchema = Field(
        default_factory=CleanupSchema,
        description="Post-import cleanup settings for Libation source files",
    )
    # ABS search settings (query Audible via ABS for missing ASINs)
    abs_search: bool = Field(
        default=True,
        description="Enable ABS metadata search for books without ASIN",
    )
    abs_search_confidence: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold for ABS search matches (0.0-1.0)",
    )

    @field_validator("duplicate_policy")
    @classmethod
    def validate_duplicate_policy(cls, v: str) -> str:
        """Validate duplicate_policy is a recognized value."""
        valid = {"skip", "warn", "overwrite"}
        if v.lower() not in valid:
            raise ValueError(f"Invalid duplicate_policy '{v}'. Must be one of: {valid}")
        return v.lower()

    @field_validator("trigger_scan")
    @classmethod
    def validate_trigger_scan(cls, v: str) -> str:
        """Validate trigger_scan is a recognized value."""
        valid = {"none", "each", "batch"}
        if v.lower() not in valid:
            raise ValueError(f"Invalid trigger_scan '{v}'. Must be one of: {valid}")
        return v.lower()

    @field_validator("unknown_asin_policy")
    @classmethod
    def validate_unknown_asin_policy(cls, v: str) -> str:
        """Validate unknown_asin_policy is a recognized value."""
        valid = {"import", "quarantine", "skip"}
        if v.lower() not in valid:
            raise ValueError(f"Invalid unknown_asin_policy '{v}'. Must be one of: {valid}")
        return v.lower()

    @field_validator("quarantine_path")
    @classmethod
    def validate_quarantine_path_absolute(cls, v: str | None) -> str | None:
        """Ensure quarantine_path is absolute when provided."""
        if v is not None and v.strip():
            if not v.startswith("/"):
                raise ValueError(
                    f"quarantine_path must be an absolute path (start with /), got: {v}"
                )
            return v.rstrip("/")  # Normalize: remove trailing slash
        return v

    @model_validator(mode="after")
    def validate_quarantine_requires_path(self) -> AudiobookshelfImportSchema:
        """Ensure quarantine_path is set when policy is quarantine."""
        if self.unknown_asin_policy == "quarantine" and (
            not self.quarantine_path or not self.quarantine_path.strip()
        ):
            raise ValueError("quarantine_path is required when unknown_asin_policy is 'quarantine'")
        return self


class AudiobookshelfSchema(BaseModel):
    """Audiobookshelf integration settings (credentials come from .env)."""

    enabled: bool = Field(default=False, description="Enable ABS integration")
    timeout_seconds: int = Field(default=30, ge=5, le=120)
    docker_mode: bool = Field(default=True, description="Whether ABS runs in Docker")
    path_map: list[AudiobookshelfPathMapSchema] = Field(
        default_factory=list, description="Container-to-host path mappings"
    )
    libraries: list[AudiobookshelfLibrarySchema] = Field(
        default_factory=list, description="Library configurations"
    )
    import_settings: AudiobookshelfImportSchema = Field(
        default_factory=AudiobookshelfImportSchema,
        alias="import",
        description="Import behavior settings",
    )
    index_db: str = Field(default="./data/abs_index.db", description="Index database path")

    model_config = {"populate_by_name": True}  # Allow both 'import' and 'import_settings'

    @model_validator(mode="after")
    def validate_docker_mode_requires_path_map(self) -> AudiobookshelfSchema:
        """Ensure path_map is provided when docker_mode is enabled."""
        if self.enabled and self.docker_mode and not self.path_map:
            raise ValueError("path_map is required when docker_mode is true")
        return self


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
    audiobookshelf: AudiobookshelfSchema = Field(default_factory=AudiobookshelfSchema)

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
