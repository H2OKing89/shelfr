"""Configuration loading from .env and config.yaml."""

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


@dataclass
class PathsConfig:
    """Path configuration settings."""

    library_root: Path  # Libation library / staging directory (same in Libation workflow)
    torrent_output: Path
    seed_root: Path
    state_file: Path
    log_file: Path


@dataclass
class MamConfig:
    """MAM compliance settings."""

    max_filename_length: int = 225
    allowed_extensions: list[str] = field(
        default_factory=lambda: [".m4b", ".jpg", ".jpeg", ".png", ".pdf", ".cue"]
    )


@dataclass
class MkbrrConfig:
    """mkbrr Docker configuration."""

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
    """qBittorrent settings."""

    host: str = ""
    username: str = ""
    password: str = ""
    category: str = "mam-audiobooks"
    tags: list[str] = field(default_factory=lambda: ["mamfast"])
    auto_start: bool = True


@dataclass
class AudnexConfig:
    """Audnex API settings."""

    base_url: str = "https://api.audnex.us"
    timeout_seconds: int = 30


@dataclass
class MediaInfoConfig:
    """MediaInfo settings."""

    binary: str = "mediainfo"


@dataclass
class FiltersConfig:
    """Title filtering settings."""

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
    """MAM category mapping (genre name -> category ID)."""

    # Maps lowercase genre names to MAM category IDs
    genre_map: dict[str, int] = field(default_factory=dict)


@dataclass
class Settings:
    """Complete application settings."""

    # From .env
    libation_container: str
    docker_bin: str
    target_uid: int
    target_gid: int
    mam_announce_url: str
    env: str
    log_level: str

    # From config.yaml
    paths: PathsConfig
    mam: MamConfig
    mkbrr: MkbrrConfig
    qbittorrent: QBittorrentConfig
    audnex: AudnexConfig
    mediainfo: MediaInfoConfig
    filters: FiltersConfig
    categories: CategoriesConfig


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
) -> Settings:
    """
    Load settings from .env and config.yaml files.

    Args:
        env_file: Path to .env file (default: .env next to config.yaml, or in current dir)
        config_file: Path to config.yaml (default: config.yaml in current directory)

    Returns:
        Populated Settings object
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

    return Settings(
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
        filters=filters,
        categories=categories,
    )


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
) -> Settings:
    """Reload settings from files."""
    global _settings
    _settings = load_settings(env_file, config_file)
    return _settings
