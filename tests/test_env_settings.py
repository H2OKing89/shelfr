"""Tests for pydantic-settings based environment configuration."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from shelfr.env_settings import (
    AppEnvSettings,
    AudiobookshelfEnvSettings,
    DockerEnvSettings,
    EnvSettings,
    QBittorrentEnvSettings,
    clear_env_settings_cache,
    get_env_settings,
    load_env_settings_from_file,
)


class TestQBittorrentEnvSettings:
    """Tests for qBittorrent environment settings."""

    def test_default_values(self) -> None:
        """Test default values when no env vars set."""
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = QBittorrentEnvSettings()
            assert settings.host == ""
            assert settings.username == ""
            assert settings.password == ""

    def test_loads_from_env(self) -> None:
        """Test loading from environment variables."""
        env = {
            "QB_HOST": "http://localhost:8080",
            "QB_USERNAME": "admin",
            "QB_PASSWORD": "secret123",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            settings = QBittorrentEnvSettings()
            assert settings.host == "http://localhost:8080"
            assert settings.username == "admin"
            assert settings.password == "secret123"

    def test_validates_host_url(self) -> None:
        """Test host URL validation."""
        env = {"QB_HOST": "localhost:8080"}  # Missing protocol
        with (
            mock.patch.dict(os.environ, env, clear=True),
            pytest.raises(ValueError, match="must start with http://"),
        ):
            QBittorrentEnvSettings()

    def test_strips_trailing_slash(self) -> None:
        """Test trailing slash is stripped from host."""
        env = {"QB_HOST": "http://localhost:8080/"}
        with mock.patch.dict(os.environ, env, clear=True):
            settings = QBittorrentEnvSettings()
            assert settings.host == "http://localhost:8080"


class TestAudiobookshelfEnvSettings:
    """Tests for Audiobookshelf environment settings."""

    def test_default_values(self) -> None:
        """Test default values when no env vars set."""
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = AudiobookshelfEnvSettings()
            assert settings.host == ""
            assert settings.api_key == ""

    def test_loads_from_env(self) -> None:
        """Test loading from environment variables."""
        env = {
            "AUDIOBOOKSHELF_HOST": "https://abs.example.com",
            "AUDIOBOOKSHELF_API_KEY": "abc123token",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            settings = AudiobookshelfEnvSettings()
            assert settings.host == "https://abs.example.com"
            assert settings.api_key == "abc123token"

    def test_validates_host_url(self) -> None:
        """Test host URL validation."""
        env = {"AUDIOBOOKSHELF_HOST": "abs.example.com"}  # Missing protocol
        with (
            mock.patch.dict(os.environ, env, clear=True),
            pytest.raises(ValueError, match="must start with http://"),
        ):
            AudiobookshelfEnvSettings()


class TestDockerEnvSettings:
    """Tests for Docker environment settings."""

    def test_default_values(self) -> None:
        """Test default values when no env vars set."""
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = DockerEnvSettings()
            assert settings.libation_container == "libation"
            assert settings.docker_bin == "/usr/bin/docker"
            assert settings.target_uid == 99
            assert settings.target_gid == 100

    def test_loads_from_env(self) -> None:
        """Test loading from environment variables."""
        env = {
            "LIBATION_CONTAINER": "my-libation",
            "DOCKER_BIN": "/usr/local/bin/docker",
            "TARGET_UID": "1000",
            "TARGET_GID": "1000",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            settings = DockerEnvSettings()
            assert settings.libation_container == "my-libation"
            assert settings.docker_bin == "/usr/local/bin/docker"
            assert settings.target_uid == 1000
            assert settings.target_gid == 1000

    def test_coerces_string_to_int(self) -> None:
        """Test string UID/GID are coerced to int."""
        env = {"TARGET_UID": "500", "TARGET_GID": "500"}
        with mock.patch.dict(os.environ, env, clear=True):
            settings = DockerEnvSettings()
            assert isinstance(settings.target_uid, int)
            assert isinstance(settings.target_gid, int)


class TestAppEnvSettings:
    """Tests for application environment settings."""

    def test_default_values(self) -> None:
        """Test default values when no env vars set."""
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = AppEnvSettings()
            assert settings.env == "production"
            assert settings.log_level == "INFO"

    def test_loads_from_env(self) -> None:
        """Test loading from environment variables."""
        env = {
            "SHELFR_ENV": "development",
            "LOG_LEVEL": "debug",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            settings = AppEnvSettings()
            assert settings.env == "development"
            assert settings.log_level == "DEBUG"  # Normalized to uppercase

    def test_validates_log_level(self) -> None:
        """Test log level validation."""
        env = {"LOG_LEVEL": "VERBOSE"}  # Invalid level
        with (
            mock.patch.dict(os.environ, env, clear=True),
            pytest.raises(ValueError, match="LOG_LEVEL must be one of"),
        ):
            AppEnvSettings()

    def test_normalizes_log_level_case(self) -> None:
        """Test log level is normalized to uppercase."""
        env = {"LOG_LEVEL": "warning"}
        with mock.patch.dict(os.environ, env, clear=True):
            settings = AppEnvSettings()
            assert settings.log_level == "WARNING"


class TestEnvSettings:
    """Tests for combined environment settings."""

    def test_aggregates_all_settings(self) -> None:
        """Test that EnvSettings aggregates all nested settings."""
        env = {
            "QB_HOST": "http://localhost:8080",
            "AUDIOBOOKSHELF_HOST": "https://abs.example.com",
            "LIBATION_CONTAINER": "test-container",
            "SHELFR_ENV": "development",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            settings = EnvSettings()
            assert settings.qb.host == "http://localhost:8080"
            assert settings.abs.host == "https://abs.example.com"
            assert settings.docker.libation_container == "test-container"
            assert settings.app.env == "development"

    def test_validate_required_for_mam_missing(self) -> None:
        """Test MAM validation catches missing required fields."""
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = EnvSettings()
            errors = settings.validate_required_for_mam()
            assert len(errors) == 3
            assert any("QB_HOST" in e for e in errors)
            assert any("QB_USERNAME" in e for e in errors)
            assert any("QB_PASSWORD" in e for e in errors)

    def test_validate_required_for_mam_success(self) -> None:
        """Test MAM validation passes with all required fields."""
        env = {
            "QB_HOST": "http://localhost:8080",
            "QB_USERNAME": "admin",
            "QB_PASSWORD": "secret",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            settings = EnvSettings()
            errors = settings.validate_required_for_mam()
            assert errors == []

    def test_validate_required_for_abs_missing(self) -> None:
        """Test ABS validation catches missing required fields."""
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = EnvSettings()
            errors = settings.validate_required_for_abs()
            assert len(errors) == 2
            assert any("AUDIOBOOKSHELF_HOST" in e for e in errors)
            assert any("AUDIOBOOKSHELF_API_KEY" in e for e in errors)

    def test_validate_required_for_abs_success(self) -> None:
        """Test ABS validation passes with all required fields."""
        env = {
            "AUDIOBOOKSHELF_HOST": "https://abs.example.com",
            "AUDIOBOOKSHELF_API_KEY": "token123",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            settings = EnvSettings()
            errors = settings.validate_required_for_abs()
            assert errors == []


class TestGetEnvSettings:
    """Tests for get_env_settings caching."""

    def test_returns_cached_instance(self) -> None:
        """Test that get_env_settings returns cached instance."""
        clear_env_settings_cache()
        with mock.patch.dict(os.environ, {}, clear=True):
            settings1 = get_env_settings()
            settings2 = get_env_settings()
            assert settings1 is settings2

    def test_clear_cache_allows_reload(self) -> None:
        """Test that clearing cache allows fresh reload."""
        env1 = {"QB_HOST": "http://host1:8080"}
        env2 = {"QB_HOST": "http://host2:8080"}

        with mock.patch.dict(os.environ, env1, clear=True):
            clear_env_settings_cache()
            settings1 = get_env_settings()
            assert settings1.qb.host == "http://host1:8080"

        with mock.patch.dict(os.environ, env2, clear=True):
            clear_env_settings_cache()
            settings2 = get_env_settings()
            assert settings2.qb.host == "http://host2:8080"


class TestLoadEnvSettingsFromFile:
    """Tests for loading from .env files."""

    def test_loads_from_env_file(self, tmp_path: Path) -> None:
        """Test loading environment settings from a .env file."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "QB_HOST=http://from-file:8080\n" "QB_USERNAME=fileuser\n" "QB_PASSWORD=filepass\n"
        )

        # Clear any existing env vars
        with mock.patch.dict(
            os.environ,
            {"QB_HOST": "", "QB_USERNAME": "", "QB_PASSWORD": ""},
            clear=False,
        ):
            settings = load_env_settings_from_file(env_file)
            assert settings.qb.host == "http://from-file:8080"
            assert settings.qb.username == "fileuser"
            assert settings.qb.password == "filepass"
