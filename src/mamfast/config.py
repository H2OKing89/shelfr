"""Configuration loading from .env and config.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


@dataclass
class PathsConfig:
    """Path configuration settings."""

    libation_library_root: Path
    staging_root: Path
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
        env_file: Path to .env file (default: .env in current directory)
        config_file: Path to config.yaml (default: config.yaml in current directory)

    Returns:
        Populated Settings object
    """
    # Load .env file
    env_path = env_file or Path(".env")
    if env_path.exists():
        load_dotenv(env_path)
    else:
        # Try loading from environment anyway (for containerized usage)
        load_dotenv()

    # Load config.yaml
    config_path = config_file or Path("config.yaml")
    yaml_config = load_yaml_config(config_path)

    # Parse paths config
    paths_data = yaml_config.get("paths", {})
    paths = PathsConfig(
        libation_library_root=Path(paths_data.get("libation_library_root", "")),
        staging_root=Path(paths_data.get("staging_root", "")),
        torrent_output=Path(paths_data.get("torrent_output", "")),
        seed_root=Path(paths_data.get("seed_root", "")),
        state_file=Path(paths_data.get("state_file", "./data/processed.json")),
        log_file=Path(paths_data.get("log_file", "./logs/mamfast.log")),
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

    # Parse environment section (YAML overrides env vars)
    env_data = yaml_config.get("environment", {})

    return Settings(
        # Environment: YAML config > env var > default
        libation_container=env_data.get(
            "libation_container", _get_env("LIBATION_CONTAINER", "libation")
        ),
        docker_bin=env_data.get(
            "docker_bin", _get_env("DOCKER_BIN", "/usr/bin/docker")
        ),
        target_uid=env_data.get(
            "target_uid", _get_env_int("TARGET_UID", 99)
        ),
        target_gid=env_data.get(
            "target_gid", _get_env_int("TARGET_GID", 100)
        ),
        mam_announce_url=env_data.get(
            "mam_announce_url", _get_env("MAM_ANNOUNCE_URL", "")
        ),
        env=env_data.get("env", _get_env("MAMFAST_ENV", "development")),
        log_level=env_data.get("log_level", _get_env("LOG_LEVEL", "INFO")),
        # YAML config
        paths=paths,
        mam=mam,
        mkbrr=mkbrr,
        qbittorrent=qbittorrent,
        audnex=audnex,
        mediainfo=mediainfo,
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
