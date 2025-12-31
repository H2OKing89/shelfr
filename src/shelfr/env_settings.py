"""Environment-based settings using pydantic-settings.

This module provides type-safe environment variable loading with validation.
Environment variables are loaded automatically and can be overridden by YAML config.

Usage:
    from shelfr.env_settings import get_env_settings

    env = get_env_settings()
    print(env.qb.host)  # From QB_HOST env var

Environment Variables:
    Docker/Libation:
        LIBATION_CONTAINER - Libation Docker container name (default: "libation")
        DOCKER_BIN - Docker binary path (default: "/usr/bin/docker")
        TARGET_UID - Unraid file ownership UID (default: 99)
        TARGET_GID - Unraid file ownership GID (default: 100)

    qBittorrent:
        QB_HOST - qBittorrent Web UI URL (required, e.g., "http://10.1.60.10:8080")
        QB_USERNAME - qBittorrent username (required)
        QB_PASSWORD - qBittorrent password (required)

    Audiobookshelf:
        AUDIOBOOKSHELF_HOST - ABS server URL (e.g., "https://abs.example.com")
        AUDIOBOOKSHELF_API_KEY - ABS API token

    Application:
        SHELFR_ENV - Environment name (default: "production")
        LOG_LEVEL - Logging level (default: "INFO")

    Path Overrides (from platformdirs):
        SHELFR_DATA_DIR - Override data directory
        SHELFR_CACHE_DIR - Override cache directory
        SHELFR_LOG_DIR - Override log directory
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


def _validate_url_field(v: str, field_name: str) -> str:
    """Validate URL format (shared validator).

    Args:
        v: The URL value to validate.
        field_name: Name of the field for error messages.

    Returns:
        The validated URL with trailing slash stripped.

    Raises:
        ValueError: If URL doesn't start with http:// or https://.
    """
    if v and not v.startswith(("http://", "https://")):
        raise ValueError(f"{field_name} must start with http:// or https://, got: {v}")
    return v.rstrip("/") if v else v


class QBittorrentEnvSettings(BaseSettings):
    """qBittorrent credentials from environment variables.

    Reads from QB_HOST, QB_USERNAME, QB_PASSWORD env vars.
    """

    model_config = SettingsConfigDict(
        env_prefix="QB_",
        extra="ignore",
    )

    host: str = Field(default="", description="qBittorrent Web UI URL")
    username: str = Field(default="", description="qBittorrent username")
    password: str = Field(default="", description="qBittorrent password")

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        """Validate qBittorrent host URL format."""
        return _validate_url_field(v, "QB_HOST")


class AudiobookshelfEnvSettings(BaseSettings):
    """Audiobookshelf credentials from environment variables.

    Reads from AUDIOBOOKSHELF_HOST, AUDIOBOOKSHELF_API_KEY env vars.
    """

    model_config = SettingsConfigDict(
        env_prefix="AUDIOBOOKSHELF_",
        extra="ignore",
    )

    host: str = Field(default="", description="Audiobookshelf server URL")
    api_key: str = Field(default="", description="Audiobookshelf API token")

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        """Validate ABS host URL format."""
        return _validate_url_field(v, "AUDIOBOOKSHELF_HOST")


class DockerEnvSettings(BaseSettings):
    """Docker/Libation settings from environment variables.

    Reads from LIBATION_CONTAINER, DOCKER_BIN, TARGET_UID, TARGET_GID env vars.
    """

    model_config = SettingsConfigDict(
        extra="ignore",
    )

    libation_container: str = Field(
        default="libation",
        validation_alias="LIBATION_CONTAINER",
        description="Libation Docker container name",
    )
    docker_bin: str = Field(
        default="/usr/bin/docker",
        validation_alias="DOCKER_BIN",
        description="Docker binary path",
    )
    target_uid: int = Field(
        default=99,
        validation_alias="TARGET_UID",
        description="Unraid file ownership UID",
    )
    target_gid: int = Field(
        default=100,
        validation_alias="TARGET_GID",
        description="Unraid file ownership GID",
    )

    @field_validator("docker_bin")
    @classmethod
    def validate_docker_bin(cls, v: str) -> str:
        """Validate Docker binary path exists.

        This is intentionally a warning-only check: if the configured path does
        not exist on the current host, we log a warning but still return the
        value unchanged. This allows configuration to be loaded and validated
        in environments where Docker might not be installed yet or where the
        path only exists inside a container.
        """
        if v and not Path(v).exists():
            logger.warning("Docker binary not found at: %s", v)
        return v

    @field_validator("target_uid", "target_gid", mode="before")
    @classmethod
    def coerce_to_int(cls, v: str | int) -> int:
        """Allow string values and convert to int."""
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                raise ValueError(f"Must be an integer, got: {v!r}") from None
        return v


class AppEnvSettings(BaseSettings):
    """Application-level settings from environment variables.

    Reads from SHELFR_ENV, LOG_LEVEL env vars.
    """

    model_config = SettingsConfigDict(
        extra="ignore",
    )

    env: str = Field(
        default="production",
        validation_alias="SHELFR_ENV",
        description="Environment name (development/production)",
    )
    log_level: str = Field(
        default="INFO",
        validation_alias="LOG_LEVEL",
        description="Logging level",
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate and normalize log level."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid_levels:
            raise ValueError(f"LOG_LEVEL must be one of {valid_levels}, got: {v}")
        return upper


class EnvSettings(BaseSettings):
    """Combined environment settings.

    This class aggregates all environment-based settings into a single object.
    Use get_env_settings() to get a cached instance.

    Example:
        env = get_env_settings()
        print(env.qb.host)
        print(env.abs.api_key)
        print(env.docker.libation_container)
        print(env.app.log_level)
    """

    model_config = SettingsConfigDict(
        extra="ignore",
    )

    # Nested settings - each loads from their own env vars
    qb: QBittorrentEnvSettings = Field(default_factory=QBittorrentEnvSettings)
    abs: AudiobookshelfEnvSettings = Field(default_factory=AudiobookshelfEnvSettings)
    docker: DockerEnvSettings = Field(default_factory=DockerEnvSettings)
    app: AppEnvSettings = Field(default_factory=AppEnvSettings)

    def validate_required_for_mam(self) -> list[str]:
        """Validate required settings for MAM upload workflow.

        Returns:
            List of error messages for missing/invalid settings.
        """
        errors: list[str] = []

        if not self.qb.host:
            errors.append("QB_HOST is required for MAM uploads")
        if not self.qb.username:
            errors.append("QB_USERNAME is required for MAM uploads")
        if not self.qb.password:
            errors.append("QB_PASSWORD is required for MAM uploads")

        return errors

    def validate_required_for_abs(self) -> list[str]:
        """Validate required settings for Audiobookshelf integration.

        Returns:
            List of error messages for missing/invalid settings.
        """
        errors: list[str] = []

        if not self.abs.host:
            errors.append("AUDIOBOOKSHELF_HOST is required for ABS integration")
        if not self.abs.api_key:
            errors.append("AUDIOBOOKSHELF_API_KEY is required for ABS integration")

        return errors


@lru_cache(maxsize=1)
def get_env_settings() -> EnvSettings:
    """Get cached environment settings.

    This function returns a cached EnvSettings instance that reads
    from environment variables. The cache is populated on first call.

    Returns:
        EnvSettings instance with all environment-based configuration.

    Example:
        env = get_env_settings()
        print(f"qBittorrent host: {env.qb.host}")
        print(f"Log level: {env.app.log_level}")
    """
    return EnvSettings()


def clear_env_settings_cache() -> None:
    """Clear the cached environment settings.

    Useful for testing to ensure fresh settings are loaded.
    """
    get_env_settings.cache_clear()


def load_env_settings_from_file(env_file: Path) -> EnvSettings:
    """Load environment settings from a specific .env file.

    This creates a new EnvSettings instance loading from the specified file,
    bypassing the cache. Useful for testing or loading from non-standard locations.

    Args:
        env_file: Path to .env file to load.

    Returns:
        EnvSettings instance with configuration from the file.
    """
    from dotenv import load_dotenv

    # Load the env file into os.environ
    load_dotenv(env_file, override=True)

    # Clear cache and reload
    clear_env_settings_cache()
    return get_env_settings()
