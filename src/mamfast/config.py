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
   - filters: remove_phrases, remove_book_numbers, author_map, transliterate_japanese
   - environment: can override any .env variable (see below)

2. **.env file** (for secrets and environment-specific values):
   - QB_HOST, QB_USERNAME, QB_PASSWORD (qBittorrent credentials)
   - MAM_ANNOUNCE_URL (tracker announce URL - secret)
   - LIBATION_CONTAINER, DOCKER_BIN, TARGET_UID, TARGET_GID
   - MAMFAST_ENV, LOG_LEVEL

3. **config/categories.json** (MAM category mappings):
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
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


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
class MamConfig:
    """MAM compliance settings (from config.yaml mam section)."""

    max_filename_length: int = 225
    allowed_extensions: list[str] = field(
        default_factory=lambda: [".m4b", ".jpg", ".jpeg", ".png", ".pdf", ".cue"]
    )


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


@dataclass
class QBittorrentConfig:
    """
    qBittorrent settings.

    Credentials (host, username, password) come from .env file.
    Other settings (category, tags, auto_start) come from config.yaml.
    """

    host: str = ""  # From .env: QB_HOST
    username: str = ""  # From .env: QB_USERNAME
    password: str = ""  # From .env: QB_PASSWORD
    category: str = "mam-audiobooks"
    tags: list[str] = field(default_factory=lambda: ["mamfast"])
    auto_start: bool = True


@dataclass
class AudnexConfig:
    """Audnex API settings (from config.yaml audnex section)."""

    base_url: str = "https://api.audnex.us"
    timeout_seconds: int = 30


@dataclass
class MediaInfoConfig:
    """MediaInfo settings (from config.yaml mediainfo section)."""

    binary: str = "mediainfo"


@dataclass
class LibationConfig:
    """Libation library discovery settings (from config.yaml libation section)."""

    # Regex pattern for parsing folder names: "Title vol_N (YEAR)"
    folder_pattern: str = r"^(.*?)(?: vol_(\d+))?(?: \((\d{4})\))?$"
    # Suffix for Libation metadata files
    metadata_file_suffix: str = ".metadata.json"
    # Valid ASIN pattern (10 alphanumeric characters)
    asin_pattern: str = r"^[A-Z0-9]{10}$"


@dataclass
class FiltersConfig:
    """Title filtering settings (from config.yaml filters section)."""

    # Phrases to remove from titles (case-insensitive)
    remove_phrases: list[str] = field(default_factory=list)
    # Remove "Book XX" patterns (we keep vol_XX)
    remove_book_numbers: bool = True
    # Author name mapping (foreign name -> romanized name)
    author_map: dict[str, str] = field(default_factory=dict)
    # Use pykakasi to transliterate unknown Japanese text
    transliterate_japanese: bool = True


@dataclass
class CategoriesConfig:
    """MAM category mapping (from config/categories.json)."""

    # Maps lowercase genre names to MAM category IDs
    genre_map: dict[str, int] = field(default_factory=dict)


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
    mam_announce_url: str  # .env: MAM_ANNOUNCE_URL
    env: str  # .env: MAMFAST_ENV
    log_level: str  # .env: LOG_LEVEL

    # From config.yaml
    paths: PathsConfig
    mam: MamConfig
    mkbrr: MkbrrConfig
    qbittorrent: QBittorrentConfig
    audnex: AudnexConfig
    mediainfo: MediaInfoConfig
    libation: LibationConfig
    filters: FiltersConfig
    categories: CategoriesConfig


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
                f"{field_name} is required but not set\n"
                f"Fix: Set {field_name} in config/config.yaml"
            )
        return

    if required and not path.exists():
        raise ConfigurationError(
            f"{field_name} does not exist: {path}\n"
            f"Fix: Create the directory or update the path in config/config.yaml\n"
            f"Example: mkdir -p {path}"
        )


def validate_required_env_vars() -> None:
    """
    Validate that all required environment variables are set.

    Raises:
        ConfigurationError: If required variables are missing
    """
    required = {
        "QB_HOST": "qBittorrent Web UI URL (e.g., http://10.1.60.10:8080)",
        "QB_USERNAME": "qBittorrent username",
        "QB_PASSWORD": "qBittorrent password",
        "MAM_ANNOUNCE_URL": "MAM tracker announce URL",
    }

    missing = []
    for var, description in required.items():
        if not os.getenv(var):
            missing.append(f"  - {var}: {description}")

    if missing:
        raise ConfigurationError(
            "Missing required environment variables in config/.env:\n"
            + "\n".join(missing)
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
    validate_url(settings.mam_announce_url, "MAM_ANNOUNCE_URL")

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
            "qBittorrent credentials are empty. "
            "Fix: Set QB_USERNAME and QB_PASSWORD in config/.env"
        )

    # Validate file extensions format
    invalid_extensions = [ext for ext in settings.mam.allowed_extensions if not ext.startswith(".")]
    if invalid_extensions:
        formatted = ", ".join(f"'{ext}' -> '.{ext}'" for ext in invalid_extensions)
        warnings.append(f"Extensions should start with dot: {formatted}")

    return warnings


def _get_env(key: str, default: str | None = None) -> str:
    """Get environment variable with optional default."""
    value = os.getenv(key, default)
    if value is None:
        raise ValueError(f"Missing required environment variable: {key}")
    return value


def _get_env_int(key: str, default: int) -> int:
    """Get environment variable as integer."""
    value = os.getenv(key)
    if value is None:
        return default
    return int(value)


def _load_categories(config_dir: Path) -> CategoriesConfig:
    """
    Load MAM category mapping from config/categories.json.

    Args:
        config_dir: Project root directory containing config/

    Returns:
        CategoriesConfig with genre_map populated
    """
    categories_path = config_dir / "config" / "categories.json"

    if not categories_path.exists():
        logger.warning(f"categories.json not found at {categories_path}, using empty map")
        return CategoriesConfig()

    try:
        with open(categories_path, encoding="utf-8") as f:
            data = json.load(f)

        # Filter out comment keys (starting with _) and non-int values
        genre_map = {k: v for k, v in data.items() if not k.startswith("_") and isinstance(v, int)}

        logger.debug(f"Loaded {len(genre_map)} category mappings from {categories_path}")
        return CategoriesConfig(genre_map=genre_map)

    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load categories.json: {e}")
        return CategoriesConfig()


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
        load_dotenv(env_path)
    else:
        # Try loading from environment anyway (for containerized usage)
        load_dotenv()

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
    paths_data = yaml_config.get("paths", {})
    paths = PathsConfig(
        library_root=Path(paths_data.get("library_root", "")),
        torrent_output=Path(paths_data.get("torrent_output", "")),
        seed_root=Path(paths_data.get("seed_root", "")),
        state_file=resolve_path(paths_data.get("state_file", "./data/processed.json")),
        log_file=resolve_path(paths_data.get("log_file", "./logs/mamfast.log")),
    )

    # Parse MAM config
    mam_data = yaml_config.get("mam", {})
    mam = MamConfig(
        max_filename_length=mam_data.get("max_filename_length", 225),
        allowed_extensions=mam_data.get(
            "allowed_extensions", [".m4b", ".jpg", ".jpeg", ".png", ".pdf", ".cue"]
        ),
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
    )

    # Parse qBittorrent config
    qb_data = yaml_config.get("qbittorrent", {})
    qbittorrent = QBittorrentConfig(
        host=_get_env("QB_HOST", ""),
        username=_get_env("QB_USERNAME", ""),
        password=_get_env("QB_PASSWORD", ""),
        category=qb_data.get("category", "mam-audiobooks"),
        tags=qb_data.get("tags", ["mamfast"]),
        auto_start=qb_data.get("auto_start", True),
    )

    # Parse Audnex config
    audnex_data = yaml_config.get("audnex", {})
    audnex = AudnexConfig(
        base_url=audnex_data.get("base_url", "https://api.audnex.us"),
        timeout_seconds=audnex_data.get("timeout_seconds", 30),
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
    )

    # Parse filters config
    filters_data = yaml_config.get("filters", {})
    filters = FiltersConfig(
        remove_phrases=filters_data.get("remove_phrases", []),
        remove_book_numbers=filters_data.get("remove_book_numbers", True),
        author_map=filters_data.get("author_map", {}),
        transliterate_japanese=filters_data.get("transliterate_japanese", True),
    )

    # Load categories from config/categories.json
    categories = _load_categories(config_dir)

    # Parse environment section (YAML overrides env vars)
    env_data = yaml_config.get("environment", {})

    settings = Settings(
        # Environment: YAML config > env var > default
        libation_container=env_data.get(
            "libation_container", _get_env("LIBATION_CONTAINER", "libation")
        ),
        docker_bin=env_data.get("docker_bin", _get_env("DOCKER_BIN", "/usr/bin/docker")),
        target_uid=env_data.get("target_uid", _get_env_int("TARGET_UID", 99)),
        target_gid=env_data.get("target_gid", _get_env_int("TARGET_GID", 100)),
        mam_announce_url=env_data.get("mam_announce_url", _get_env("MAM_ANNOUNCE_URL", "")),
        env=env_data.get("env", _get_env("MAMFAST_ENV", "development")),
        log_level=env_data.get("log_level", _get_env("LOG_LEVEL", "INFO")),
        # YAML config
        paths=paths,
        mam=mam,
        mkbrr=mkbrr,
        qbittorrent=qbittorrent,
        audnex=audnex,
        mediainfo=mediainfo,
        libation=libation,
        filters=filters,
        categories=categories,
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
