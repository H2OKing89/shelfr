"""
Configuration loading from .env, config.yaml, and categories.json.

Setting Sources and Precedence
==============================
Settings are loaded from three sources:

1. **config.yaml** (highest priority for structured config):
   - paths: library_root, torrent_output, seed_root, state_file, log_file
   - mam: max_filename_length, allowed_extensions
   - mkbrr: image, preset, host_data_root, container_data_root, etc.
   - qbittorrent: category, tags, auto_start
   - audnex: base_url, timeout_seconds
   - mediainfo: binary
   - filters: remove_book_numbers, transliterate_japanese
   - environment: can override any .env variable (see below)

2. **naming.json** (title/author/series cleanup rules):
   - format_indicators, genre_tags, publisher_tags (phrases to remove)
   - author_map (foreign name -> romanized name mapping)
   - series_suffixes, subtitle patterns, preserve_exact, etc.

3. **.env file** (for secrets and environment-specific values):
   - QB_HOST, QB_USERNAME, QB_PASSWORD (qBittorrent credentials)
   - LIBATION_CONTAINER, DOCKER_BIN, TARGET_UID, TARGET_GID
   - SHELFR_ENV, LOG_LEVEL
   - AUDIOBOOKSHELF_HOST, AUDIOBOOKSHELF_API_KEY

   Environment variables are loaded using pydantic-settings for type-safe
   validation. See env_settings.py for the full list of supported variables.

4. **config/categories.json** (MAM category mappings):
   - Maps genre names to MAM category IDs (e.g., "fantasy" -> 39)

Precedence for environment section: YAML environment > .env file > defaults

Path Resolution
===============
- Absolute paths are used as-is
- Relative paths in config.yaml are resolved relative to project root
  (parent of config/ directory)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from dotenv import load_dotenv
from pydantic import ValidationError as PydanticValidationError

from shelfr.env_settings import clear_env_settings_cache, get_env_settings

if TYPE_CHECKING:
    from shelfr.abs.cleanup import CleanupPrefs
    from shelfr.abs.trumping import TrumpPrefs

logger = logging.getLogger(__name__)

# Valid Audnex regions (must match schemas/config.py:VALID_AUDNEX_REGIONS)
VALID_AUDNEX_REGIONS = frozenset(["us", "uk", "au", "ca", "de", "es", "fr", "in", "it", "jp"])

# Default ASIN region for normalization (centralized constant)
# Also update in schemas/config.py AudnexSchema and config.yaml.example if changed
DEFAULT_ASIN_REGION = "us"


class ConfigurationError(Exception):
    """Raised when configuration is invalid."""

    pass


@dataclass
class PathsConfig:
    """Path configuration settings (from config.yaml paths section)."""

    library_root: Path  # Libation library / staging directory (same in Libation workflow)
    torrent_output: Path
    seed_root: Path
    state_file: Path
    log_file: Path


@dataclass
class DescriptionConfig:
    """MAM description/template settings (from config.yaml mam.description section)."""

    show_signature: bool = True
    signature_template: str = "signature.j2"


@dataclass
class MamConfig:
    """MAM compliance settings (from config.yaml mam section)."""

    max_filename_length: int = 225
    allowed_extensions: list[str] = field(
        default_factory=lambda: [".m4b", ".jpg", ".jpeg", ".png", ".pdf", ".cue"]
    )
    description: DescriptionConfig = field(default_factory=DescriptionConfig)


@dataclass
class MkbrrConfig:
    """mkbrr Docker configuration (from config.yaml mkbrr section)."""

    image: str = "ghcr.io/autobrr/mkbrr"
    preset: str = "mam"
    host_data_root: str = "/mnt/user/data"
    container_data_root: str = "/data"
    host_output_dir: str = "/mnt/user/data/downloads/torrents/torrentfiles"
    container_output_dir: str = "/torrentfiles"
    host_config_dir: str = "/mnt/cache/appdata/mkbrr"
    container_config_dir: str = "/root/.config/mkbrr"

    # Docker command timeout (filtering/presets handled by mkbrr's presets.yaml)
    timeout_seconds: int = 300


@dataclass
class FFmpegConfig:
    """FFmpeg Docker configuration (linuxserver/ffmpeg)."""

    enabled: bool = False  # Disabled by default until configured
    image: str = "lscr.io/linuxserver/ffmpeg:latest"
    timeout_seconds: int = 1800  # 30 minutes default (transcoding can be slow)
    hwaccel: str = "none"  # Hardware acceleration: none, vaapi, qsv, nvenc, vulkan


@dataclass
class QBittorrentConfig:
    """
    qBittorrent settings.

    Credentials (host, username, password) come from .env file.
    Other settings (category, tags, auto_start, auto_tmm, save_path) come from config.yaml.
    """

    host: str = ""  # From .env: QB_HOST
    username: str = ""  # From .env: QB_USERNAME
    password: str = ""  # From .env: QB_PASSWORD
    category: str = "mam-audiobooks"
    tags: list[str] = field(default_factory=lambda: ["shelfr"])
    auto_start: bool = True
    auto_tmm: bool = False  # Automatic Torrent Management
    save_path: str = ""  # Static save path as seen by qBittorrent (container path)


@dataclass
class AudnexConfig:
    """Audnex API settings (from config.yaml audnex section)."""

    base_url: str = "https://api.audnex.us"
    timeout_seconds: int = 30
    # Regions to try in order (first success wins)
    # Valid: us, uk, au, ca, de, es, fr, in, it, jp
    regions: list[str] = field(default_factory=lambda: [DEFAULT_ASIN_REGION])
    # Phase 10.6 concurrency settings
    rate_limit_per_minute: int = 90  # Max requests/min to Audnex API
    burst_limit: float = 10.0  # Max requests in burst period
    burst_period: float = 5.0  # Burst period in seconds
    asin_concurrency: int = 5  # Max concurrent ASIN lookups for batch ops


@dataclass
class HardcoverConfig:
    """Hardcover API settings (from config.yaml hardcover section).

    Phase 12: Hardcover provider for content warnings and rich metadata.
    """

    enabled: bool = True  # Enable/disable Hardcover provider
    # API key from environment variable HARDCOVER_API_KEY (not stored in config)
    timeout_seconds: int = 30
    rate_limit_per_minute: int = 60  # Hardcover API limit
    match_threshold: float = 0.70  # Fuzzy match threshold (0.0-1.0)
    cache_ttl_days: int = 7  # Cache TTL in days (book metadata changes slowly)

    def __post_init__(self) -> None:
        """Validate field ranges."""
        if not 0.0 <= self.match_threshold <= 1.0:
            raise ValueError(f"match_threshold must be 0.0-1.0, got {self.match_threshold}")
        if self.timeout_seconds < 1:
            raise ValueError(f"timeout_seconds must be >= 1, got {self.timeout_seconds}")
        if self.rate_limit_per_minute < 1:
            raise ValueError(
                f"rate_limit_per_minute must be >= 1, got {self.rate_limit_per_minute}"
            )
        if self.cache_ttl_days < 0:
            raise ValueError(f"cache_ttl_days must be >= 0, got {self.cache_ttl_days}")


@dataclass
class MediaInfoConfig:
    """MediaInfo settings (from config.yaml mediainfo section)."""

    binary: str = "mediainfo"


@dataclass
class LibationConfig:
    """Libation library discovery and CLI wrapper settings (from config.yaml libation section)."""

    # Discovery settings
    # Regex pattern for parsing folder names: "Title vol_N (YEAR)"
    folder_pattern: str = r"^(.*?)(?: vol_(\d+))?(?: \((\d{4})\))?$"
    # Suffix for Libation metadata files
    metadata_file_suffix: str = ".metadata.json"
    # Valid ASIN pattern (10 alphanumeric characters)
    asin_pattern: str = r"^[A-Z0-9]{10}$"

    # CLI timeouts (seconds)
    scan_timeout: int = 600  # 10 minutes
    liberate_timeout: int = 14400  # 4 hours
    command_timeout: int = 300  # 5 minutes


@dataclass
class NamingConfig:
    """
    Naming rules configuration (from config/naming.json).

    Separate from FiltersConfig to allow independent updates and sharing
    of naming rules without affecting main config.
    """

    # Format indicators to remove: "(Light Novel)", "Unabridged", etc.
    format_indicators: list[str] = field(default_factory=list)
    # Genre tags to remove: "A LitRPG Adventure", etc.
    genre_tags: list[str] = field(default_factory=list)
    # Series suffixes to remove (regex patterns): " Series", " Light Novel", etc.
    series_suffixes: list[str] = field(default_factory=list)
    # Publisher tags to remove: "[Yen Audio]", etc.
    publisher_tags: list[str] = field(default_factory=list)
    # Subtitle patterns (regex) to remove
    subtitle_remove_patterns: list[str] = field(default_factory=list)
    # Subtitle patterns (regex) to preserve
    subtitle_keep_patterns: list[str] = field(default_factory=list)
    # Whether to remove subtitle if it matches series name
    remove_subtitle_if_matches_series: bool = True
    # Subtitle redundancy rules - templates with {{series}}/{{title}} placeholders
    subtitle_redundancy_rules: list[dict[str, str]] = field(default_factory=list)
    # Whether subtitle redundancy checking is enabled
    subtitle_redundancy_enabled: bool = True
    # Titles that bypass ALL cleaning rules (exact match, case-sensitive)
    preserve_exact: list[str] = field(default_factory=list)
    # Author name mapping (foreign name -> romanized name)
    author_map: dict[str, str] = field(default_factory=dict)
    # Patterns to preserve in JSON but remove from folder/file names
    preserve_volume_in_json: bool = True
    # Ripper tag for folder names (e.g., "H2OKing" -> "[H2OKing]")
    # Set to None or empty string to disable
    ripper_tag: str | None = None
    # Non-author roles to filter: "translator", "illustrator", etc.
    author_roles: list[str] = field(
        default_factory=lambda: [
            "translator",
            "illustrator",
            "editor",
            "adapter",
            "contributor",
            "compiler",
        ]
    )
    # Credit roles (afterword, foreword, etc.)
    credit_roles: list[str] = field(
        default_factory=lambda: [
            "afterword",
            "foreword",
            "introduction",
            "cover design",
            "cover art",
        ]
    )
    # Title/subtitle normalization settings
    normalize_title_subtitle: bool = True  # Enable Audnex title/subtitle swap detection
    log_normalization_swaps: bool = True  # Log when swaps are detected
    # Path truncation: order to drop components when path exceeds 225 chars
    # Valid components: "arc", "author", "year" (dropped in order, first dropped first)
    path_drop_priority: list[str] = field(default_factory=lambda: ["arc", "author", "year"])
    # Edition flags: tokens in parentheses detected and preserved in target name
    edition_flags: list[str] = field(
        default_factory=lambda: [
            "Full-Cast",
            "Full Cast",
            "Dolby Atmos",
            "Atmos",
            "Unabridged",
            "Abridged",
            "Dramatized",
            "Graphic Audio",
            "Publisher's Pack",
            "Publishers Pack",
            "AIT",
        ]
    )
    # Edition flag aliases: lowercase variant -> canonical form
    edition_flag_aliases: dict[str, str] = field(
        default_factory=lambda: {
            "full cast": "Full-Cast",
            "atmos": "Dolby Atmos",
            "publishers pack": "Publisher's Pack",
            "ait": "AIT",
        }
    )
    # Series aliases: canonical name -> list of alternate names
    # Used by ABS rename to merge series with punctuation/spelling variants
    series_aliases: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class FiltersConfig:
    """Title filtering settings (from config.yaml filters section + naming.json)."""

    # Phrases to remove from titles (case-insensitive) - combined from all sources
    remove_phrases: list[str] = field(default_factory=list)
    # Remove "Book XX" patterns (we keep vol_XX)
    remove_book_numbers: bool = True
    # Author name mapping (foreign name -> romanized name)
    author_map: dict[str, str] = field(default_factory=dict)
    # Use pykakasi to transliterate unknown Japanese text
    transliterate_japanese: bool = True
    # Naming config (loaded from naming.json)
    naming: NamingConfig = field(default_factory=NamingConfig)


@dataclass
class MamSchemaConfig:
    """Official MAM category schema (from config/mam_categories_reference.json).

    Loaded flexibly from JSON — unknown top-level keys are stored in `extra`
    so MAM API changes never break the loader. Only fields we actively use
    are typed; everything else stays as raw dicts.
    """

    # category_id (str) -> category dict (with id, name, main_type_ids,
    # media_type_ids, required_siblings, excluded_siblings, + any future fields)
    categories: dict[str, dict[str, Any]] = field(default_factory=dict)
    # media_type_id (str) -> media type dict
    media_types: dict[str, dict[str, Any]] = field(default_factory=dict)
    # main_type_id (str) -> main type dict
    main_types: dict[str, dict[str, Any]] = field(default_factory=dict)
    # language_id (str) -> language dict
    languages: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Catch-all for any future top-level keys MAM adds
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class CategoriesConfig:
    """MAM category mapping (from config/categories.json and audiobook_categories.json)."""

    # Maps lowercase genre names to MAM category IDs
    genre_map: dict[str, int] = field(default_factory=dict)
    # Maps genre keywords to MAM audiobook category strings (fiction)
    audiobook_fiction_map: dict[str, str] = field(default_factory=dict)
    # Maps genre keywords to MAM audiobook category strings (non-fiction)
    audiobook_nonfiction_map: dict[str, str] = field(default_factory=dict)
    # Default category strings when no genre match
    audiobook_defaults: dict[str, str] = field(default_factory=dict)
    # Official MAM schema for validation (sibling rules, media type checks, etc.)
    mam_schema: MamSchemaConfig = field(default_factory=MamSchemaConfig)


@dataclass
class AudiobookshelfPathMap:
    """Docker path mapping for Audiobookshelf."""

    container: str  # Path as seen inside ABS container
    host: str  # Corresponding path on host filesystem


@dataclass
class AudiobookshelfLibrary:
    """Audiobookshelf library configuration."""

    id: str  # ABS library ID (e.g., lib_xxxxx)
    name: str = ""  # Human-readable library name
    shelfr_managed: bool = False  # Whether Shelfr imports to this library


@dataclass
class TrumpingConfig:
    """Trumping (quality-based replacement) settings."""

    enabled: bool = False
    aggressiveness: str = "balanced"  # conservative | balanced | aggressive
    min_bitrate_increase_kbps: int = 64
    prefer_chapters: bool = True
    prefer_stereo: bool = True
    min_duration_ratio: float = 0.9
    max_duration_ratio: float = 1.25
    archive_root: str | None = None
    archive_by_year: bool = True
    # Own ripper tags: auto-trump if incoming has one of these tags (your uploads)
    own_ripper_tags: list[str] = field(default_factory=list)


@dataclass
class CleanupConfig:
    """Post-import cleanup settings for Libation source files."""

    strategy: str = "none"  # none | hide | move | delete
    cleanup_path: str | None = None  # Required if strategy=move
    require_seed_exists: bool = True
    verify_in_abs: bool = False
    hide_marker: str = ".shelfr_imported"
    min_age_days: int = 0
    ignore_dirs: list[str] = field(default_factory=lambda: ["__import_test", ".git", ".venv"])
    ignore_glob: list[str] = field(default_factory=lambda: ["*/__*", "*/.#*"])
    prune_empty_dirs: bool = True  # Remove empty directories after import


# =============================================================================
# Workflow Config (controls pipeline behavior)
# =============================================================================


@dataclass(frozen=True)
class UploadSanitizeConfig:
    """Sanitization settings for the upload workflow.

    Note: Tags should be passed as lowercase for case-insensitive matching.
    The Pydantic schema normalizes tags during config file loading.
    """

    enabled: bool = True
    # Stored as tuple of lowercase tags for efficient membership testing
    tags: tuple[str, ...] = ("audible_acr",)


@dataclass(frozen=True)
class ContentWarningsConfig:
    """Content warnings settings for the upload workflow.

    When enabled, fetches content warnings from Hardcover API
    and maps them to MAM content flags (vio, cLang, sSex, eSex, lgbt).
    Requires hardcover.enabled = True in global config.
    """

    enabled: bool = False


@dataclass(frozen=True)
class UploadWorkflowConfig:
    """Upload workflow settings (shelfr run)."""

    sanitize: UploadSanitizeConfig = field(default_factory=UploadSanitizeConfig)
    content_warnings: ContentWarningsConfig = field(default_factory=ContentWarningsConfig)
    packaging: str = "folder"  # "folder" or "audio_only"
    # Ripper tag appended to folder names during upload staging (e.g., "H2OKing" -> "[H2OKing]")
    # Set to None or empty string (normalized to None during parsing) to disable
    ripper_tag: str | None = None


@dataclass(frozen=True)
class WorkflowConfig:
    """Workflow settings - controls behavior of various pipelines."""

    upload: UploadWorkflowConfig = field(default_factory=UploadWorkflowConfig)


def build_trump_prefs(
    trumping_config: TrumpingConfig,
    *,
    enabled_override: bool | None = None,
    aggressiveness_override: str | None = None,
) -> TrumpPrefs | None:
    """Build TrumpPrefs from config with optional CLI overrides.

    Centralizes trumping preference construction so CLI and importer
    don't need to know config structure details.

    Args:
        trumping_config: TrumpingConfig from AudiobookshelfImportConfig
        enabled_override: If False, disable trumping regardless of config
        aggressiveness_override: Override aggressiveness level (conservative/balanced/aggressive)

    Returns:
        TrumpPrefs instance if enabled, None if disabled
    """
    # Import here to avoid circular dependency
    from shelfr.abs.trumping import TrumpPrefs

    # Check if trumping is enabled (CLI override takes precedence)
    enabled = trumping_config.enabled
    if enabled_override is not None:
        enabled = enabled_override

    if not enabled:
        return None

    # Apply aggressiveness override if provided
    aggressiveness = trumping_config.aggressiveness
    if aggressiveness_override is not None:
        aggressiveness = aggressiveness_override

    # Create a modified config for TrumpPrefs.from_config
    # We create a temporary config with overrides applied
    modified_config = TrumpingConfig(
        enabled=enabled,
        aggressiveness=aggressiveness,
        min_bitrate_increase_kbps=trumping_config.min_bitrate_increase_kbps,
        prefer_chapters=trumping_config.prefer_chapters,
        prefer_stereo=trumping_config.prefer_stereo,
        min_duration_ratio=trumping_config.min_duration_ratio,
        max_duration_ratio=trumping_config.max_duration_ratio,
        archive_root=trumping_config.archive_root,
        archive_by_year=trumping_config.archive_by_year,
        own_ripper_tags=trumping_config.own_ripper_tags,
    )

    return TrumpPrefs.from_config(modified_config)


def build_cleanup_prefs(
    cleanup_config: CleanupConfig,
    *,
    strategy_override: str | None = None,
    cleanup_path_override: str | None = None,
) -> CleanupPrefs:
    """Build CleanupPrefs from config with optional CLI overrides.

    Centralizes cleanup preference construction so CLI and importer
    don't need to know config structure details.

    Args:
        cleanup_config: CleanupConfig from AudiobookshelfImportConfig
        strategy_override: Override cleanup strategy (none/hide/move/delete)
        cleanup_path_override: Override cleanup_path for move strategy

    Returns:
        CleanupPrefs instance
    """
    # Import here to avoid circular dependency
    from shelfr.abs.cleanup import CleanupPrefs, CleanupStrategy

    # Apply strategy override if provided
    strategy_str = strategy_override if strategy_override is not None else cleanup_config.strategy
    strategy = CleanupStrategy(strategy_str.lower())

    # Apply cleanup_path override if provided
    cleanup_path_str = (
        cleanup_path_override if cleanup_path_override is not None else cleanup_config.cleanup_path
    )
    cleanup_path = Path(cleanup_path_str) if cleanup_path_str else None

    return CleanupPrefs(
        strategy=strategy,
        cleanup_path=cleanup_path,
        require_seed_exists=cleanup_config.require_seed_exists,
        verify_in_abs=cleanup_config.verify_in_abs,
        hide_marker=cleanup_config.hide_marker,
        min_age_days=cleanup_config.min_age_days,
        ignore_dirs=tuple(cleanup_config.ignore_dirs),
        ignore_glob=tuple(cleanup_config.ignore_glob),
        prune_empty_dirs=cleanup_config.prune_empty_dirs,
    )


@dataclass
class AudiobookshelfImportConfig:
    """Audiobookshelf import settings."""

    # Ripper tag appended to folder names during import (e.g., "H2OKing" -> "[H2OKing]")
    # Set to None or empty string to disable forced tagging; existing tags in folder names
    # are preserved via extraction fallback in the rename pipeline
    ripper_tag: str | None = None
    duplicate_policy: str = "skip"  # skip | warn | overwrite
    trigger_scan: str = "batch"  # none | each | batch
    # Preferred ASIN region when importing to Audiobookshelf.
    # When an ASIN is found in a different region, use ABS search to find this region's ASIN.
    # This ONLY affects ABS import; Audnex metadata lookup uses audnex.regions instead.
    # Set to None to disable ASIN normalization. Valid: us, uk, au, ca, de, es, fr, in, it, jp
    preferred_asin_region: str | None = DEFAULT_ASIN_REGION
    trumping: TrumpingConfig = field(default_factory=TrumpingConfig)
    cleanup: CleanupConfig = field(default_factory=CleanupConfig)
    # ABS search: query Audible via ABS for missing ASINs (default: enabled)
    abs_search: bool = True
    abs_search_confidence: float = 0.75  # Minimum confidence threshold (0.0-1.0)
    # How to handle books without ASIN: import | quarantine | skip
    unknown_asin_policy: str = "import"
    # Path for quarantined books (required if unknown_asin_policy=quarantine)
    quarantine_path: str | None = None
    # File patterns to ignore during import (e.g., [".json", "*.metadata.json"])
    ignore_file_extensions: list[str] = field(default_factory=list)
    # Generate metadata.json for Audiobookshelf (with Audnex data)
    generate_metadata_json: bool = True
    # Generate metadata.json even without ASIN (minimal data from folder name)
    metadata_json_fallback: bool = True
    # Generate metadata.opf sidecar for Audiobookshelf (Calibre-compatible OPF)
    generate_opf_sidecar: bool = False


@dataclass
class AudiobookshelfRenameConfig:
    """Audiobookshelf rename planning/apply settings."""

    policy_profile: str = "default"  # default | sao_gold
    hierarchy_mode: str = "preserve"  # preserve | author_series_book
    arc_policy: str = "optional"  # optional | infer | manual
    asin_policy: str = "preserve"  # preserve | prefer_b | strict_b
    ripper_tag_policy: str = (
        "import_override"  # import_override | preserve_if_in_allowlist | strip_all
    )
    allowed_ripper_tags: list[str] = field(default_factory=list)
    non_allowlisted_tag_action: str = "keep"  # keep | drop
    series_source: str = "preserve_existing"  # preserve_existing | folder_first | abs_first
    transaction_backup_root: str = "./data/reports/rename_backups"
    ollama_enabled: bool = False
    ollama_model: str = "llama3.1:8b-instruct-q4_K_M"
    ollama_endpoints: list[str] = field(default_factory=lambda: ["http://127.0.0.1:11434"])
    ollama_timeout_seconds: int = 60
    ollama_max_items: int = 200
    ollama_batch_size: int = 15
    ollama_workers: int = 1
    ollama_retry_count: int = 1
    ollama_debug_dump_dir: str | None = None


@dataclass
class AudiobookshelfConfig:
    """Audiobookshelf integration settings (from config.yaml audiobookshelf section)."""

    # Enable/disable ABS integration
    enabled: bool = False
    # ABS server URL (from .env: AUDIOBOOKSHELF_HOST)
    host: str = ""
    # API token (from .env: AUDIOBOOKSHELF_API_KEY)
    api_key: str = ""
    # Connection timeout
    timeout_seconds: int = 30
    # Whether ABS runs in Docker (requires path mapping)
    docker_mode: bool = True
    # Container-to-host path mappings
    path_map: list[AudiobookshelfPathMap] = field(default_factory=list)
    # Library configurations
    libraries: list[AudiobookshelfLibrary] = field(default_factory=list)
    # Import settings
    import_settings: AudiobookshelfImportConfig = field(default_factory=AudiobookshelfImportConfig)
    # Rename planning/apply policy settings
    rename: AudiobookshelfRenameConfig = field(default_factory=AudiobookshelfRenameConfig)
    # Index database path
    index_db: str = "./data/abs_index.db"


@dataclass
class Settings:
    """
    Complete application settings.

    See module docstring for full documentation of setting sources.
    """

    # From .env (can be overridden by config.yaml environment section)
    libation_container: str  # .env: LIBATION_CONTAINER
    docker_bin: str  # .env: DOCKER_BIN
    target_uid: int  # .env: TARGET_UID
    target_gid: int  # .env: TARGET_GID
    env: str  # .env: SHELFR_ENV
    log_level: str  # .env: LOG_LEVEL

    # From config.yaml (required - no defaults)
    paths: PathsConfig
    mam: MamConfig
    mkbrr: MkbrrConfig
    ffmpeg: FFmpegConfig
    qbittorrent: QBittorrentConfig
    audnex: AudnexConfig
    mediainfo: MediaInfoConfig
    libation: LibationConfig
    filters: FiltersConfig
    categories: CategoriesConfig
    naming: NamingConfig

    # From config.yaml (optional - with defaults)
    hardcover: HardcoverConfig = field(default_factory=HardcoverConfig)
    audiobookshelf: AudiobookshelfConfig = field(default_factory=AudiobookshelfConfig)
    workflow: WorkflowConfig = field(default_factory=WorkflowConfig)


def validate_url(url: str, field_name: str) -> None:
    """
    Validate that a URL is well-formed.

    Args:
        url: URL to validate
        field_name: Name of the field for error messages

    Raises:
        ConfigurationError: If URL is invalid
    """
    if not url:
        raise ConfigurationError(f"{field_name} is required but not set")

    if not url.startswith(("http://", "https://")):
        raise ConfigurationError(
            f"{field_name} must be a valid URL starting with http:// or https://\n"
            f"Got: {url}\n"
            f"Fix: Update {field_name} in config/.env to include the protocol"
        )


def validate_path_exists(path: Path, field_name: str, *, required: bool = True) -> None:
    """
    Validate that a path exists.

    Args:
        path: Path to validate
        field_name: Name of the field for error messages
        required: If True, raise error if path doesn't exist

    Raises:
        ConfigurationError: If path doesn't exist and required=True
    """
    if not path or str(path) == ".":
        if required:
            raise ConfigurationError(
                f"{field_name} is required but not set\nFix: Set {field_name} in config/config.yaml"
            )
        return

    if required and not path.exists():
        raise ConfigurationError(
            f"{field_name} does not exist: {path}\n"
            f"Fix: Create the directory or update the path in config/config.yaml\n"
            f"Example: mkdir -p {path}"
        )


def validate_same_filesystem(path1: Path, path2: Path, name1: str, name2: str) -> None:
    """
    Validate that two paths are on the same filesystem.

    This is required for hardlinks to work. If paths are on different filesystems,
    hardlinks will fail and copying would be needed instead.

    Args:
        path1: First path to check
        path2: Second path to check
        name1: Name of first path for error messages
        name2: Name of second path for error messages

    Raises:
        ConfigurationError: If paths are on different filesystems
    """
    # Resolve to existing parent directories if paths don't exist yet
    resolved1 = path1
    while not resolved1.exists() and resolved1.parent != resolved1:
        resolved1 = resolved1.parent

    resolved2 = path2
    while not resolved2.exists() and resolved2.parent != resolved2:
        resolved2 = resolved2.parent

    if not resolved1.exists() or not resolved2.exists():
        # Can't validate if we can't find existing directories
        return

    try:
        stat1 = resolved1.stat()
        stat2 = resolved2.stat()

        if stat1.st_dev != stat2.st_dev:
            raise ConfigurationError(
                f"{name1} and {name2} must be on the same filesystem for hardlinks.\n"
                f"  {name1}: {path1} (device: {stat1.st_dev})\n"
                f"  {name2}: {path2} (device: {stat2.st_dev})\n"
                f"Fix: Move one of the directories to the same filesystem, or consider "
                f"using symlinks/copying instead."
            )
    except OSError as e:
        # Log but don't fail if we can't stat the paths
        logger.warning(f"Could not validate filesystem for {name1}/{name2}: {e}")


def validate_required_env_vars() -> None:
    """
    Validate that all required environment variables are set.

    Uses pydantic-settings for type-safe validation.

    Raises:
        ConfigurationError: If required variables are missing
    """
    env = get_env_settings()
    errors = env.validate_required_for_mam()

    if errors:
        raise ConfigurationError(
            "Missing required environment variables in config/.env:\n"
            + "\n".join(f"  - {e}" for e in errors)
            + "\n\nFix: Copy .env.example to config/.env and fill in the values"
        )


def validate_paths(paths: PathsConfig, *, strict: bool = False) -> list[str]:
    """
    Validate that required paths exist.

    Args:
        paths: PathsConfig to validate
        strict: If True, raise ConfigurationError on validation failure

    Returns:
        List of warning messages for paths that don't exist

    Raises:
        ConfigurationError: If strict=True and library_root doesn't exist
    """
    warnings = []

    # library_root must exist (source of audiobooks)
    if not paths.library_root.exists():
        msg = f"library_root does not exist: {paths.library_root}"
        if strict:
            raise ConfigurationError(
                f"{msg}\n"
                f"Fix: Create the directory or update library_root in config/config.yaml\n"
                f"Example: mkdir -p {paths.library_root}"
            )
        warnings.append(msg)

    # These directories will be created if needed, just warn
    for name, path in [
        ("seed_root", paths.seed_root),
        ("torrent_output", paths.torrent_output),
    ]:
        if path and not path.exists():
            warnings.append(f"{name} does not exist (will be created): {path}")

    # Validate library_root and seed_root are on the same filesystem for hardlinks
    if paths.library_root and paths.seed_root:
        validate_same_filesystem(paths.library_root, paths.seed_root, "library_root", "seed_root")

    return warnings


def validate_settings(settings: Settings) -> list[str]:
    """
    Comprehensive validation of all settings.

    Args:
        settings: Settings object to validate

    Returns:
        List of warning messages (non-fatal issues)

    Raises:
        ConfigurationError: If critical validation fails
    """
    warnings = []

    # Validate required environment variables
    validate_required_env_vars()

    # Validate URLs
    validate_url(settings.qbittorrent.host, "QB_HOST")

    # Validate Audnex API URL
    if settings.audnex.base_url:
        validate_url(settings.audnex.base_url, "audnex.base_url")

    # Validate critical paths
    validate_path_exists(settings.paths.library_root, "library_root", required=True)

    # Validate numeric ranges
    if settings.mam.max_filename_length < 1 or settings.mam.max_filename_length > 255:
        raise ConfigurationError(
            f"mam.max_filename_length must be between 1 and 255, "
            f"got: {settings.mam.max_filename_length}\n"
            f"Fix: Update mam.max_filename_length in config/config.yaml"
        )

    if settings.audnex.timeout_seconds < 1 or settings.audnex.timeout_seconds > 300:
        warnings.append(
            f"audnex.timeout_seconds is unusual: {settings.audnex.timeout_seconds} "
            f"(recommended: 10-60 seconds)"
        )

    # Validate Docker binary exists
    docker_bin = Path(settings.docker_bin)
    if not docker_bin.is_file():
        warnings.append(
            f"Docker binary not found at: {settings.docker_bin}\n"
            f"Fix: Install Docker or update DOCKER_BIN in config/.env"
        )

    # Check for empty credentials
    if not settings.qbittorrent.username or not settings.qbittorrent.password:
        warnings.append(
            "qBittorrent credentials are empty. Fix: Set QB_USERNAME and QB_PASSWORD in config/.env"
        )

    # Validate file extensions format
    invalid_extensions = [ext for ext in settings.mam.allowed_extensions if not ext.startswith(".")]
    if invalid_extensions:
        formatted = ", ".join(f"'{ext}' -> '.{ext}'" for ext in invalid_extensions)
        warnings.append(f"Extensions should start with dot: {formatted}")

    return warnings


def _parse_trumping_config(data: dict[str, Any]) -> TrumpingConfig:
    """Parse trumping config from YAML data.

    Args:
        data: Dict from YAML audiobookshelf.import.trumping section

    Returns:
        TrumpingConfig with values from YAML or defaults
    """
    if not data:
        return TrumpingConfig()

    return TrumpingConfig(
        enabled=data.get("enabled", False),
        aggressiveness=data.get("aggressiveness", "balanced"),
        min_bitrate_increase_kbps=data.get("min_bitrate_increase_kbps", 64),
        prefer_chapters=data.get("prefer_chapters", True),
        prefer_stereo=data.get("prefer_stereo", True),
        min_duration_ratio=data.get("min_duration_ratio", 0.9),
        max_duration_ratio=data.get("max_duration_ratio", 1.25),
        archive_root=data.get("archive_root"),
        archive_by_year=data.get("archive_by_year", True),
        own_ripper_tags=data.get("own_ripper_tags", []),
    )


def _parse_cleanup_config(data: dict[str, Any]) -> CleanupConfig:
    """Parse cleanup config from YAML data.

    Args:
        data: Dict from YAML audiobookshelf.import.cleanup section

    Returns:
        CleanupConfig with values from YAML or defaults
    """
    if not data:
        return CleanupConfig()

    return CleanupConfig(
        strategy=data.get("strategy", "none"),
        cleanup_path=data.get("cleanup_path"),
        require_seed_exists=data.get("require_seed_exists", True),
        verify_in_abs=data.get("verify_in_abs", False),
        hide_marker=data.get("hide_marker", ".shelfr_imported"),
        min_age_days=data.get("min_age_days", 0),
        ignore_dirs=data.get("ignore_dirs", ["__import_test", ".git", ".venv"]),
        ignore_glob=data.get("ignore_glob", ["*/__*", "*/.#*"]),
        prune_empty_dirs=data.get("prune_empty_dirs", True),
    )


def _parse_workflow_config(data: dict[str, Any] | None) -> WorkflowConfig:
    """Parse workflow config from YAML data with backward compatibility.

    If workflow section is missing, returns defaults matching current behavior
    (sanitize enabled with AUDIBLE_ACR tag).

    Args:
        data: Dict from YAML workflow section, or None if missing

    Returns:
        WorkflowConfig with values from YAML or sensible defaults
    """
    # Backward compatibility: missing workflow section = current default behavior
    if data is None:
        logger.debug("No workflow section in config - using defaults (sanitize enabled)")
        return WorkflowConfig()

    upload_data = data.get("upload", {})
    sanitize_data = upload_data.get("sanitize", {})

    # Parse sanitize config
    sanitize_enabled = sanitize_data.get("enabled", True)
    raw_tags = sanitize_data.get("tags", ["AUDIBLE_ACR"])

    # Normalize tags to lowercase at load time for case-insensitive matching
    normalized_tags = tuple(
        t.strip().lower() for t in raw_tags if t and isinstance(t, str) and t.strip()
    )

    # Warn if enabled but no tags configured
    if sanitize_enabled and not normalized_tags:
        logger.warning(
            "workflow.upload.sanitize enabled but no tags configured - sanitize will be a no-op"
        )

    sanitize_config = UploadSanitizeConfig(
        enabled=sanitize_enabled,
        tags=normalized_tags,
    )

    # Parse content_warnings config (with type guard)
    content_warnings_raw = upload_data.get("content_warnings", {})
    content_warnings_data = content_warnings_raw if isinstance(content_warnings_raw, dict) else {}
    if not isinstance(content_warnings_raw, dict) and content_warnings_raw is not None:
        logger.warning(
            "Invalid content_warnings type '%s', defaulting to disabled",
            type(content_warnings_raw).__name__,
        )
    content_warnings_config = ContentWarningsConfig(
        enabled=content_warnings_data.get("enabled", False),
    )

    # Parse packaging mode (with type guard)
    packaging_raw = upload_data.get("packaging", "folder")
    if isinstance(packaging_raw, str):
        packaging_mode = packaging_raw.lower()
    else:
        logger.warning(
            "Invalid packaging mode type '%s', defaulting to 'folder'",
            type(packaging_raw).__name__,
        )
        packaging_mode = "folder"
    if packaging_mode not in {"folder", "audio_only"}:
        logger.warning(
            "Invalid packaging mode '%s', defaulting to 'folder'",
            packaging_mode,
        )
        packaging_mode = "folder"

    # Parse upload ripper_tag (empty string means disabled)
    upload_ripper_tag_raw = upload_data.get("ripper_tag")
    upload_ripper_tag: str | None = None
    if upload_ripper_tag_raw is not None:
        if isinstance(upload_ripper_tag_raw, str):
            upload_ripper_tag = upload_ripper_tag_raw.strip() or None
        else:
            logger.warning(
                "workflow.upload.ripper_tag must be a string, got '%s'; ignoring",
                type(upload_ripper_tag_raw).__name__,
            )

    return WorkflowConfig(
        upload=UploadWorkflowConfig(
            sanitize=sanitize_config,
            content_warnings=content_warnings_config,
            packaging=packaging_mode,
            ripper_tag=upload_ripper_tag,
        )
    )


def _load_categories(config_dir: Path) -> CategoriesConfig:
    """
    Load MAM category mappings from config/categories.json and audiobook_categories.json.

    Args:
        config_dir: Project root directory containing config/

    Returns:
        CategoriesConfig with all category maps populated
    """
    genre_map: dict[str, int] = {}
    audiobook_fiction_map: dict[str, str] = {}
    audiobook_nonfiction_map: dict[str, str] = {}
    audiobook_defaults: dict[str, str] = {}

    # Load categories.json (genre -> category ID)
    categories_path = config_dir / "config" / "categories.json"
    if categories_path.exists():
        try:
            with open(categories_path, encoding="utf-8") as f:
                data = json.load(f)
            # Filter out comment keys (starting with _) and non-int values
            genre_map = {
                k: v for k, v in data.items() if not k.startswith("_") and isinstance(v, int)
            }
            logger.debug(f"Loaded {len(genre_map)} category mappings from {categories_path}")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load categories.json: {e}")
    else:
        logger.warning(f"categories.json not found at {categories_path}, using empty map")

    # Load audiobook_categories.json (genre -> audiobook category string)
    audiobook_path = config_dir / "config" / "audiobook_categories.json"
    if audiobook_path.exists():
        try:
            with open(audiobook_path, encoding="utf-8") as f:
                data = json.load(f)
            # Filter to ensure string keys and string values only
            audiobook_fiction_map = {
                k: v
                for k, v in data.get("_fiction", {}).items()
                if isinstance(k, str) and isinstance(v, str)
            }
            audiobook_nonfiction_map = {
                k: v
                for k, v in data.get("_nonfiction", {}).items()
                if isinstance(k, str) and isinstance(v, str)
            }
            audiobook_defaults = {
                k: v
                for k, v in data.get("_defaults", {}).items()
                if isinstance(k, str) and isinstance(v, str)
            }
            logger.debug(
                f"Loaded audiobook category mappings: {len(audiobook_fiction_map)} fiction, "
                f"{len(audiobook_nonfiction_map)} nonfiction"
            )
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load audiobook_categories.json: {e}")
    else:
        logger.debug(f"audiobook_categories.json not found at {audiobook_path}, using defaults")

    # Load MAM reference schema for validation
    mam_schema = _load_mam_schema(config_dir)

    return CategoriesConfig(
        genre_map=genre_map,
        audiobook_fiction_map=audiobook_fiction_map,
        audiobook_nonfiction_map=audiobook_nonfiction_map,
        audiobook_defaults=audiobook_defaults,
        mam_schema=mam_schema,
    )


def _load_mam_schema(config_dir: Path) -> MamSchemaConfig:
    """
    Load official MAM category schema from config/mam_categories_reference.json.

    This loader is intentionally flexible: it reads known top-level keys into
    typed fields and stores everything else in ``extra`` so that MAM API
    additions (new fields on categories, new top-level sections) never break
    the loader.

    Args:
        config_dir: Project root directory containing config/

    Returns:
        MamSchemaConfig populated from JSON, or empty defaults on failure
    """
    schema_path = config_dir / "config" / "mam_categories_reference.json"
    if not schema_path.exists():
        logger.debug("mam_categories_reference.json not found at %s", schema_path)
        return MamSchemaConfig()

    try:
        with open(schema_path, encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load mam_categories_reference.json: %s", e)
        return MamSchemaConfig()

    if not isinstance(raw, dict):
        logger.warning("mam_categories_reference.json root must be a JSON object")
        return MamSchemaConfig()

    # Known top-level keys we consume
    known_keys = {"categories", "media_types", "main_types", "languages"}
    allowed_private_extra_keys = {
        "_comment",
        "_source",
        "_updated",
        "_audiobook_categories",
    }

    categories = raw.get("categories", {})
    media_types = raw.get("media_types", {})
    main_types = raw.get("main_types", {})
    languages = raw.get("languages", {})

    # Everything else (including _comment, _source, _updated,
    # _audiobook_categories, and any future keys) goes into extra
    extra = {
        k: v
        for k, v in raw.items()
        if k not in known_keys and (not k.startswith("_") or k in allowed_private_extra_keys)
    }

    cat_count = len(categories) if isinstance(categories, dict) else 0
    logger.debug(
        "Loaded MAM schema: %d categories, %d media types, %d languages",
        cat_count,
        len(media_types) if isinstance(media_types, dict) else 0,
        len(languages) if isinstance(languages, dict) else 0,
    )

    return MamSchemaConfig(
        categories=categories if isinstance(categories, dict) else {},
        media_types=media_types if isinstance(media_types, dict) else {},
        main_types=main_types if isinstance(main_types, dict) else {},
        languages=languages if isinstance(languages, dict) else {},
        extra=extra,
    )


def _load_naming_config(config_dir: Path) -> NamingConfig:
    """
    Load naming rules from config/naming.json.

    Validates the JSON structure using Pydantic schema before processing.

    Args:
        config_dir: Project root directory containing config/

    Returns:
        NamingConfig with all naming rules populated

    Raises:
        ConfigurationError: If naming.json has invalid structure or regex patterns
    """
    naming_path = config_dir / "config" / "naming.json"

    if not naming_path.exists():
        logger.debug(f"naming.json not found at {naming_path}, using defaults")
        return NamingConfig()

    try:
        with open(naming_path, encoding="utf-8") as f:
            data = json.load(f)

        # Validate with Pydantic schema (catches invalid regex, wrong types, unknown keys)
        from shelfr.schemas.naming import validate_naming_json

        try:
            schema = validate_naming_json(data)
            logger.debug(f"naming.json v{schema.version} validated successfully")
        except PydanticValidationError as e:
            raise ConfigurationError(f"Invalid naming.json: {e}") from e

        # Extract format indicators
        format_indicators = data.get("format_indicators", {}).get("phrases", [])

        # Extract genre tags
        genre_tags = data.get("genre_tags", {}).get("phrases", [])

        # Extract series suffixes (now regex patterns)
        series_suffixes_data = data.get("series_suffixes", {})
        # Support both old "phrases" format and new "patterns" format
        series_suffixes = series_suffixes_data.get(
            "patterns", series_suffixes_data.get("phrases", [])
        )

        # Extract publisher tags (new)
        publisher_tags = data.get("publisher_tags", {}).get("phrases", [])

        # Extract subtitle patterns (two-tier: remove and keep)
        subtitle_data = data.get("subtitle_patterns", {})
        subtitle_remove_patterns = subtitle_data.get(
            "remove_patterns", subtitle_data.get("patterns", [])
        )
        subtitle_keep_patterns = subtitle_data.get("keep_patterns", [])
        remove_subtitle_if_matches_series = subtitle_data.get("remove_if_matches_series", True)

        # Extract subtitle redundancy rules (template-based with {{series}}/{{title}})
        redundancy_data = data.get("subtitle_redundancy_rules", {})
        subtitle_redundancy_enabled = redundancy_data.get("enabled", True)
        subtitle_redundancy_rules = redundancy_data.get("rules", [])

        # Extract preserve_exact titles (new)
        preserve_exact = data.get("preserve_exact", {}).get("titles", [])

        # Extract author map (skip comment keys)
        author_map = {
            k: v
            for k, v in data.get("author_map", {}).items()
            if not k.startswith("_") and isinstance(v, str)
        }

        # Extract preserve settings
        preserve_data = data.get("preserve_in_json", {})
        preserve_volume_in_json = bool(preserve_data.get("volume_patterns", []))

        # Extract author roles (non-author roles to filter)
        author_roles_data = data.get("author_roles", {})
        author_roles = author_roles_data.get(
            "roles", ["translator", "illustrator", "editor", "adapter", "contributor", "compiler"]
        )
        credit_roles = author_roles_data.get(
            "credit_roles", ["afterword", "foreword", "introduction", "cover design", "cover art"]
        )

        # Extract title/subtitle normalization settings
        normalization_data = data.get("title_subtitle_normalization", {})
        normalize_title_subtitle = normalization_data.get("enabled", True)
        log_normalization_swaps = normalization_data.get("log_swaps", True)

        # Extract path truncation settings
        path_truncation_data = data.get("path_truncation", {})
        path_drop_priority = path_truncation_data.get("drop_priority", ["arc", "author", "year"])

        # Extract edition flags (tokens in parentheses preserved in target name)
        edition_data = data.get("edition_flags", {})
        edition_flags_raw = edition_data.get("flags", None)
        # Use NamingConfig defaults when naming.json has no edition_flags section
        _defaults = NamingConfig()
        edition_flags = (
            edition_flags_raw if edition_flags_raw is not None else _defaults.edition_flags
        )
        edition_flag_aliases: dict[str, str] = {
            k: v
            for k, v in edition_data.get("aliases", {}).items()
            if not k.startswith("_") and isinstance(v, str)
        }
        if not edition_flag_aliases and edition_flags_raw is None:
            edition_flag_aliases = _defaults.edition_flag_aliases

        # Extract series aliases (canonical name -> list of alternate names)
        series_aliases_data = data.get("series_aliases", {})
        series_aliases: dict[str, list[str]] = {
            k: v
            for k, v in series_aliases_data.items()
            if not k.startswith("_") and isinstance(v, list)
        }

        logger.debug(
            f"Loaded naming.json v{data.get('_version', '?')}: "
            f"{len(format_indicators)} format indicators, "
            f"{len(genre_tags)} genre tags, {len(series_suffixes)} series suffixes, "
            f"{len(publisher_tags)} publisher tags, {len(preserve_exact)} preserve_exact, "
            f"{len(subtitle_redundancy_rules)} redundancy rules, "
            f"{len(author_map)} author mappings, "
            f"{len(author_roles)} author roles, {len(credit_roles)} credit roles, "
            f"{len(edition_flags)} edition flags, "
            f"normalize_title_subtitle={normalize_title_subtitle}"
        )

        return NamingConfig(
            format_indicators=format_indicators,
            genre_tags=genre_tags,
            series_suffixes=series_suffixes,
            publisher_tags=publisher_tags,
            subtitle_remove_patterns=subtitle_remove_patterns,
            subtitle_keep_patterns=subtitle_keep_patterns,
            remove_subtitle_if_matches_series=remove_subtitle_if_matches_series,
            subtitle_redundancy_rules=subtitle_redundancy_rules,
            subtitle_redundancy_enabled=subtitle_redundancy_enabled,
            preserve_exact=preserve_exact,
            author_map=author_map,
            preserve_volume_in_json=preserve_volume_in_json,
            author_roles=author_roles,
            credit_roles=credit_roles,
            normalize_title_subtitle=normalize_title_subtitle,
            log_normalization_swaps=log_normalization_swaps,
            path_drop_priority=path_drop_priority,
            edition_flags=edition_flags,
            edition_flag_aliases=edition_flag_aliases,
            series_aliases=series_aliases,
        )

    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load naming.json: {e}, using defaults")
        return NamingConfig()


def load_yaml_config(config_path: Path) -> dict[str, Any]:
    """Load configuration from YAML file."""
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return data


def load_settings(
    env_file: Path | None = None,
    config_file: Path | None = None,
    *,
    validate: bool = True,
) -> Settings:
    """
    Load settings from .env and config.yaml files.

    Args:
        env_file: Path to .env file (default: .env next to config.yaml, or in current dir)
        config_file: Path to config.yaml (default: config.yaml in current directory)
        validate: If True, validate paths and log warnings (default: True)

    Returns:
        Populated Settings object

    Raises:
        FileNotFoundError: If config file doesn't exist
        ConfigurationError: If validation fails with strict=True
    """
    # Determine config path first
    config_path = config_file or Path("config.yaml")

    # Load .env file - look next to config.yaml if not specified
    if env_file:
        env_path = env_file
    else:
        # Try .env next to config.yaml first
        env_next_to_config = config_path.resolve().parent / ".env"
        env_path = env_next_to_config if env_next_to_config.exists() else Path(".env")

    if env_path.exists():
        load_dotenv(env_path, override=True)
    else:
        # Try loading from environment anyway (for containerized usage)
        load_dotenv()

    # Clear pydantic-settings cache to pick up newly loaded env vars
    clear_env_settings_cache()

    # Get type-safe environment settings via pydantic-settings
    env_settings = get_env_settings()

    # Load config.yaml
    yaml_config = load_yaml_config(config_path)

    # Base directory for resolving relative paths (parent of config file)
    config_dir = config_path.resolve().parent.parent  # Go up from config/ to project root

    def resolve_path(path_str: str) -> Path:
        """Resolve a path, making relative paths relative to config directory."""
        p = Path(path_str)
        if p.is_absolute():
            return p
        return (config_dir / p).resolve()

    # Parse paths config
    # Import platformdirs-based paths for XDG-compliant defaults
    from shelfr.paths import data_dir, log_dir

    paths_data = yaml_config.get("paths", {})
    paths = PathsConfig(
        library_root=Path(paths_data.get("library_root", "")),
        torrent_output=Path(paths_data.get("torrent_output", "")),
        seed_root=Path(paths_data.get("seed_root", "")),
        state_file=resolve_path(paths_data.get("state_file", str(data_dir() / "processed.json"))),
        log_file=resolve_path(paths_data.get("log_file", str(log_dir() / "shelfr.log"))),
    )

    # Parse MAM config
    mam_data = yaml_config.get("mam", {})
    desc_data = mam_data.get("description", {})
    description_config = DescriptionConfig(
        show_signature=desc_data.get("show_signature", True),
        signature_template=desc_data.get("signature_template", "signature.j2"),
    )
    mam = MamConfig(
        max_filename_length=mam_data.get("max_filename_length", 225),
        allowed_extensions=mam_data.get(
            "allowed_extensions", [".m4b", ".jpg", ".jpeg", ".png", ".pdf", ".cue"]
        ),
        description=description_config,
    )

    # Parse mkbrr config
    mkbrr_data = yaml_config.get("mkbrr", {})
    mkbrr = MkbrrConfig(
        image=mkbrr_data.get("image", "ghcr.io/autobrr/mkbrr"),
        preset=mkbrr_data.get("preset", "mam"),
        host_data_root=mkbrr_data.get("host_data_root", "/mnt/user/data"),
        container_data_root=mkbrr_data.get("container_data_root", "/data"),
        host_output_dir=mkbrr_data.get(
            "host_output_dir", "/mnt/user/data/downloads/torrents/torrentfiles"
        ),
        container_output_dir=mkbrr_data.get("container_output_dir", "/torrentfiles"),
        host_config_dir=mkbrr_data.get("host_config_dir", "/mnt/cache/appdata/mkbrr"),
        container_config_dir=mkbrr_data.get("container_config_dir", "/root/.config/mkbrr"),
        timeout_seconds=mkbrr_data.get("timeout_seconds", 300),
    )

    # Parse FFmpeg config
    ffmpeg_data = yaml_config.get("ffmpeg", {})
    ffmpeg = FFmpegConfig(
        enabled=ffmpeg_data.get("enabled", False),
        image=ffmpeg_data.get("image", "lscr.io/linuxserver/ffmpeg:latest"),
        timeout_seconds=ffmpeg_data.get("timeout_seconds", 1800),
        hwaccel=ffmpeg_data.get("hwaccel", "none"),
    )

    # Parse qBittorrent config (credentials from pydantic-settings, rest from YAML)
    qb_data = yaml_config.get("qbittorrent", {})
    qbittorrent = QBittorrentConfig(
        host=env_settings.qb.host,
        username=env_settings.qb.username,
        password=env_settings.qb.password,
        category=qb_data.get("category", "mam-audiobooks"),
        tags=qb_data.get("tags", ["shelfr"]),
        auto_start=qb_data.get("auto_start", True),
        auto_tmm=qb_data.get("auto_tmm", False),
        save_path=qb_data.get("save_path", ""),
    )

    # Parse Audnex config
    audnex_data = yaml_config.get("audnex", {})

    # Validate and normalize regions (guard against bypassed Pydantic validation)
    raw_regions = audnex_data.get("regions", [DEFAULT_ASIN_REGION])
    validated_regions: list[str] = []
    for region in raw_regions:
        region_lower = region.lower()
        if region_lower not in VALID_AUDNEX_REGIONS:
            raise ConfigurationError(
                f"Invalid audnex region '{region}'. Valid: {sorted(VALID_AUDNEX_REGIONS)}"
            )
        validated_regions.append(region_lower)
    if not validated_regions:
        validated_regions = [DEFAULT_ASIN_REGION]

    audnex = AudnexConfig(
        base_url=audnex_data.get("base_url", "https://api.audnex.us"),
        timeout_seconds=audnex_data.get("timeout_seconds", 30),
        regions=validated_regions,
        # Phase 10.6 concurrency settings
        rate_limit_per_minute=audnex_data.get("rate_limit_per_minute", 90),
        burst_limit=audnex_data.get("burst_limit", 10.0),
        burst_period=audnex_data.get("burst_period", 5.0),
        asin_concurrency=audnex_data.get("asin_concurrency", 5),
    )

    # Parse MediaInfo config
    mediainfo_data = yaml_config.get("mediainfo", {})
    mediainfo = MediaInfoConfig(
        binary=mediainfo_data.get("binary", "mediainfo"),
    )

    # Parse Libation config
    libation_data = yaml_config.get("libation", {})
    default_folder_pattern = r"^(.*?)(?: vol_(\d+))?(?: \((\d{4})\))?$"
    libation = LibationConfig(
        folder_pattern=libation_data.get("folder_pattern", default_folder_pattern),
        metadata_file_suffix=libation_data.get("metadata_file_suffix", ".metadata.json"),
        asin_pattern=libation_data.get("asin_pattern", r"^[A-Z0-9]{10}$"),
        # CLI timeouts (seconds)
        scan_timeout=libation_data.get("scan_timeout", 600),
        liberate_timeout=libation_data.get("liberate_timeout", 14400),
        command_timeout=libation_data.get("command_timeout", 300),
    )

    # Load naming config from config/naming.json
    naming = _load_naming_config(config_dir)

    # Parse naming section from config.yaml (for ripper_tag and other output settings)
    naming_yaml_data = yaml_config.get("naming", {})
    ripper_tag_value = naming_yaml_data.get("ripper_tag")
    # Update naming config with ripper_tag from yaml (empty string means disabled)
    if ripper_tag_value is not None:
        naming = NamingConfig(
            format_indicators=naming.format_indicators,
            genre_tags=naming.genre_tags,
            series_suffixes=naming.series_suffixes,
            publisher_tags=naming.publisher_tags,
            subtitle_remove_patterns=naming.subtitle_remove_patterns,
            subtitle_keep_patterns=naming.subtitle_keep_patterns,
            remove_subtitle_if_matches_series=naming.remove_subtitle_if_matches_series,
            subtitle_redundancy_rules=naming.subtitle_redundancy_rules,
            subtitle_redundancy_enabled=naming.subtitle_redundancy_enabled,
            preserve_exact=naming.preserve_exact,
            author_map=naming.author_map,
            preserve_volume_in_json=naming.preserve_volume_in_json,
            ripper_tag=ripper_tag_value if ripper_tag_value else None,
            author_roles=naming.author_roles,
            credit_roles=naming.credit_roles,
            normalize_title_subtitle=naming.normalize_title_subtitle,
            log_normalization_swaps=naming.log_normalization_swaps,
            path_drop_priority=naming.path_drop_priority,
        )

    # Parse filters config
    # Note: remove_phrases and author_map now come exclusively from naming.json
    filters_data = yaml_config.get("filters", {})

    # Log deprecation warning if legacy fields are present
    if filters_data.get("remove_phrases"):
        logger.warning(
            "filters.remove_phrases in config.yaml is deprecated and ignored. "
            "Use format_indicators/genre_tags/publisher_tags in naming.json instead."
        )
    if filters_data.get("author_map"):
        logger.warning(
            "filters.author_map in config.yaml is deprecated and ignored. "
            "Use author_map in naming.json instead."
        )

    # Build remove_phrases from naming.json only
    remove_phrases = naming.format_indicators + naming.genre_tags + naming.publisher_tags

    filters = FiltersConfig(
        remove_phrases=remove_phrases,
        remove_book_numbers=filters_data.get("remove_book_numbers", True),
        author_map=naming.author_map,  # From naming.json only
        transliterate_japanese=filters_data.get("transliterate_japanese", True),
        naming=naming,
    )

    # Load categories from config/categories.json
    categories = _load_categories(config_dir)

    # Parse Hardcover config (with type guard and error wrapping)
    hardcover_raw = yaml_config.get("hardcover", {})
    if not isinstance(hardcover_raw, dict):
        logger.warning(
            "hardcover config must be a mapping, got '%s'; using defaults",
            type(hardcover_raw).__name__,
        )
        hardcover_raw = {}
    try:
        hardcover = HardcoverConfig(
            enabled=hardcover_raw.get("enabled", True),
            timeout_seconds=hardcover_raw.get("timeout_seconds", 30),
            rate_limit_per_minute=hardcover_raw.get("rate_limit_per_minute", 60),
            match_threshold=hardcover_raw.get("match_threshold", 0.70),
            cache_ttl_days=hardcover_raw.get("cache_ttl_days", 7),
        )
    except ValueError as e:
        raise ConfigurationError(f"Invalid hardcover configuration: {e}") from e

    # Parse Audiobookshelf config
    abs_data = yaml_config.get("audiobookshelf", {})
    abs_import_data = abs_data.get("import", {})
    abs_rename_data = abs_data.get("rename", {})
    if not isinstance(abs_rename_data, dict):
        logger.warning(
            "audiobookshelf.rename config must be a mapping, got '%s'; using defaults",
            type(abs_rename_data).__name__,
        )
        abs_rename_data = {}

    # Validate preferred_asin_region for ABS import (None disables normalization)
    raw_preferred = abs_import_data.get("preferred_asin_region", DEFAULT_ASIN_REGION)
    if raw_preferred is not None:
        preferred_lower = raw_preferred.lower()
        if preferred_lower not in VALID_AUDNEX_REGIONS:
            raise ConfigurationError(
                f"Invalid audiobookshelf.import.preferred_asin_region '{raw_preferred}'. "
                f"Valid: {sorted(VALID_AUDNEX_REGIONS)} or null"
            )
        validated_preferred: str | None = preferred_lower
    else:
        validated_preferred = None

    # Build path mappings
    abs_path_map = []
    for pm in abs_data.get("path_map", []):
        if isinstance(pm, dict) and "container" in pm and "host" in pm:
            abs_path_map.append(
                AudiobookshelfPathMap(
                    container=pm["container"].rstrip("/"),
                    host=pm["host"].rstrip("/"),
                )
            )

    # Build library configs
    abs_libraries = []
    for lib in abs_data.get("libraries", []):
        if isinstance(lib, dict) and "id" in lib:
            abs_libraries.append(
                AudiobookshelfLibrary(
                    id=lib["id"],
                    name=lib.get("name", ""),
                    shelfr_managed=lib.get("shelfr_managed", False),
                )
            )

    # Parse import ripper_tag (empty string means disabled)
    import_ripper_tag_raw = abs_import_data.get("ripper_tag")
    import_ripper_tag: str | None = None
    if import_ripper_tag_raw is not None:
        if isinstance(import_ripper_tag_raw, str):
            import_ripper_tag = import_ripper_tag_raw.strip() or None
        else:
            logger.warning(
                "audiobookshelf.import.ripper_tag must be a string, got '%s'; ignoring",
                type(import_ripper_tag_raw).__name__,
            )

    ollama_model_raw = abs_rename_data.get("ollama_model", "llama3.1:8b-instruct-q4_K_M")
    ollama_model = (
        ollama_model_raw.strip()
        if isinstance(ollama_model_raw, str) and ollama_model_raw.strip()
        else "llama3.1:8b-instruct-q4_K_M"
    )

    ollama_endpoints_raw = abs_rename_data.get("ollama_endpoints", ["http://127.0.0.1:11434"])
    endpoints_input: list[str]
    if isinstance(ollama_endpoints_raw, str):
        endpoints_input = list(ollama_endpoints_raw.split(","))
    elif isinstance(ollama_endpoints_raw, list):
        endpoints_input = [str(item) for item in ollama_endpoints_raw]
    else:
        endpoints_input = []
    ollama_endpoints: list[str] = []
    seen_endpoints: set[str] = set()
    for endpoint in endpoints_input:
        cleaned = endpoint.strip().rstrip("/")
        if not cleaned or cleaned in seen_endpoints:
            continue
        ollama_endpoints.append(cleaned)
        seen_endpoints.add(cleaned)
    if not ollama_endpoints:
        ollama_endpoints = ["http://127.0.0.1:11434"]

    ollama_debug_dump_dir_raw = abs_rename_data.get("ollama_debug_dump_dir")
    ollama_debug_dump_dir = (
        str(ollama_debug_dump_dir_raw).strip() if ollama_debug_dump_dir_raw is not None else None
    )
    if not ollama_debug_dump_dir:
        ollama_debug_dump_dir = None

    audiobookshelf = AudiobookshelfConfig(
        enabled=abs_data.get("enabled", False),
        host=env_settings.abs.host,
        api_key=env_settings.abs.api_key,
        timeout_seconds=abs_data.get("timeout_seconds", 30),
        docker_mode=abs_data.get("docker_mode", True),
        path_map=abs_path_map,
        libraries=abs_libraries,
        import_settings=AudiobookshelfImportConfig(
            ripper_tag=import_ripper_tag,
            duplicate_policy=abs_import_data.get("duplicate_policy", "skip"),
            trigger_scan=abs_import_data.get("trigger_scan", "batch"),
            preferred_asin_region=validated_preferred,
            trumping=_parse_trumping_config(abs_import_data.get("trumping", {})),
            cleanup=_parse_cleanup_config(abs_import_data.get("cleanup", {})),
            abs_search=abs_import_data.get("abs_search", True),
            abs_search_confidence=abs_import_data.get("abs_search_confidence", 0.75),
            unknown_asin_policy=abs_import_data.get("unknown_asin_policy", "import"),
            quarantine_path=abs_import_data.get("quarantine_path"),
            ignore_file_extensions=abs_import_data.get("ignore_file_extensions", []),
            generate_metadata_json=abs_import_data.get("generate_metadata_json", True),
            metadata_json_fallback=abs_import_data.get("metadata_json_fallback", True),
            generate_opf_sidecar=abs_import_data.get("generate_opf_sidecar", False),
        ),
        rename=AudiobookshelfRenameConfig(
            policy_profile=abs_rename_data.get("policy_profile", "default"),
            hierarchy_mode=abs_rename_data.get("hierarchy_mode", "preserve"),
            arc_policy=abs_rename_data.get("arc_policy", "optional"),
            asin_policy=abs_rename_data.get("asin_policy", "preserve"),
            ripper_tag_policy=abs_rename_data.get("ripper_tag_policy", "import_override"),
            allowed_ripper_tags=abs_rename_data.get("allowed_ripper_tags", []),
            non_allowlisted_tag_action=abs_rename_data.get("non_allowlisted_tag_action", "keep"),
            series_source=abs_rename_data.get("series_source", "preserve_existing"),
            transaction_backup_root=abs_rename_data.get(
                "transaction_backup_root",
                "./data/reports/rename_backups",
            ),
            ollama_enabled=abs_rename_data.get("ollama_enabled", False),
            ollama_model=ollama_model,
            ollama_endpoints=ollama_endpoints,
            ollama_timeout_seconds=abs_rename_data.get("ollama_timeout_seconds", 60),
            ollama_max_items=abs_rename_data.get("ollama_max_items", 200),
            ollama_batch_size=abs_rename_data.get("ollama_batch_size", 15),
            ollama_workers=abs_rename_data.get("ollama_workers", 1),
            ollama_retry_count=abs_rename_data.get("ollama_retry_count", 1),
            ollama_debug_dump_dir=ollama_debug_dump_dir,
        ),
        index_db=abs_data.get("index_db", "./data/abs_index.db"),
    )

    # Parse workflow config (with backward compatibility)
    workflow = _parse_workflow_config(yaml_config.get("workflow"))

    # Sanitize deprecated naming.ripper_tag before migration
    # Apply same normalization as new fields: type-guard, strip, convert empty to None
    legacy_ripper_tag: str | None = None
    if naming.ripper_tag is not None:
        if isinstance(naming.ripper_tag, str):
            legacy_ripper_tag = naming.ripper_tag.strip() or None
        else:
            logger.warning(
                "naming.ripper_tag must be a string, got '%s'; ignoring",
                type(naming.ripper_tag).__name__,
            )

    # Backward compatibility: fall back to naming.ripper_tag if workflow.upload.ripper_tag not set
    # This supports the deprecated naming.ripper_tag location during migration period
    if workflow.upload.ripper_tag is None and legacy_ripper_tag is not None:
        logger.warning(
            "naming.ripper_tag is deprecated for uploads. "
            "Please migrate to workflow.upload.ripper_tag"
        )
        workflow = replace(
            workflow,
            upload=replace(workflow.upload, ripper_tag=legacy_ripper_tag),
        )

    # Backward compatibility: fall back to naming.ripper_tag for ABS import if not set
    if audiobookshelf.import_settings.ripper_tag is None and legacy_ripper_tag is not None:
        logger.warning(
            "naming.ripper_tag is deprecated for ABS imports. "
            "Please migrate to audiobookshelf.import.ripper_tag"
        )
        audiobookshelf = replace(
            audiobookshelf,
            import_settings=replace(audiobookshelf.import_settings, ripper_tag=legacy_ripper_tag),
        )

    # Parse environment section (YAML overrides pydantic-settings values)
    env_data = yaml_config.get("environment", {})

    settings = Settings(
        # Environment: YAML config > pydantic-settings (env vars) > defaults
        libation_container=env_data.get(
            "libation_container", env_settings.docker.libation_container
        ),
        docker_bin=env_data.get("docker_bin", env_settings.docker.docker_bin),
        target_uid=env_data.get("target_uid", env_settings.docker.target_uid),
        target_gid=env_data.get("target_gid", env_settings.docker.target_gid),
        env=env_data.get("env", env_settings.app.env),
        log_level=env_data.get("log_level", env_settings.app.log_level),
        # YAML config
        paths=paths,
        mam=mam,
        mkbrr=mkbrr,
        ffmpeg=ffmpeg,
        qbittorrent=qbittorrent,
        audnex=audnex,
        mediainfo=mediainfo,
        libation=libation,
        filters=filters,
        categories=categories,
        naming=naming,
        audiobookshelf=audiobookshelf,
        hardcover=hardcover,
        workflow=workflow,
    )

    # Comprehensive validation if requested
    if validate:
        try:
            warnings = validate_settings(settings)
            for warning in warnings:
                logger.warning(warning)
        except ConfigurationError as e:
            # Add helpful context to configuration errors
            raise ConfigurationError(
                f"Configuration validation failed:\n{e}\n\n"
                f"Configuration file: {config_path.resolve()}\n"
                f"Environment file: {env_path if env_path.exists() else 'NOT FOUND'}"
            ) from None

    return settings


# Lazy-loaded global settings instance
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get the global settings instance (lazy-loaded)."""
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def reload_settings(
    env_file: Path | None = None,
    config_file: Path | None = None,
    *,
    validate: bool = True,
) -> Settings:
    """
    Reload settings from files.

    Useful for testing or when config files have changed.

    Args:
        env_file: Path to .env file
        config_file: Path to config.yaml
        validate: If True, validate paths and log warnings

    Returns:
        Newly loaded Settings object
    """
    global _settings
    _settings = load_settings(env_file, config_file, validate=validate)
    return _settings


def clear_settings() -> None:
    """
    Clear the cached settings instance.

    Useful for testing to ensure a fresh settings load.
    """
    global _settings
    _settings = None
