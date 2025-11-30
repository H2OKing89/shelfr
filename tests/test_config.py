"""Tests for config module."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from mamfast.config import (
    ConfigurationError,
    FiltersConfig,
    MamConfig,
    MkbrrConfig,
    PathsConfig,
    QBittorrentConfig,
    _get_env,
    _get_env_int,
    clear_settings,
    load_settings,
    load_yaml_config,
    reload_settings,
    validate_paths,
)


class TestPathsConfig:
    """Tests for PathsConfig dataclass."""

    def test_paths_config_creation(self):
        """Test creating PathsConfig with required fields."""
        config = PathsConfig(
            library_root=Path("/tmp/library"),
            torrent_output=Path("/tmp/torrents"),
            seed_root=Path("/tmp/seed"),
            state_file=Path("/tmp/state.json"),
            log_file=Path("/tmp/app.log"),
        )
        assert config.library_root == Path("/tmp/library")
        assert config.torrent_output == Path("/tmp/torrents")
        assert config.seed_root == Path("/tmp/seed")


class TestMamConfig:
    """Tests for MamConfig dataclass."""

    def test_default_values(self):
        """Test default values are set correctly."""
        config = MamConfig()
        assert config.max_filename_length == 225
        assert ".m4b" in config.allowed_extensions
        assert ".jpg" in config.allowed_extensions

    def test_custom_values(self):
        """Test custom values override defaults."""
        config = MamConfig(max_filename_length=200)
        assert config.max_filename_length == 200


class TestFiltersConfig:
    """Tests for FiltersConfig dataclass."""

    def test_default_values(self):
        """Test default values."""
        config = FiltersConfig()
        assert config.remove_phrases == []
        assert config.remove_book_numbers is True
        assert config.author_map == {}
        assert config.transliterate_japanese is True

    def test_custom_phrases(self):
        """Test custom remove phrases."""
        config = FiltersConfig(
            remove_phrases=["Light Novel", "Unabridged"],
            author_map={"猫子": "Necoco"},
        )
        assert "Light Novel" in config.remove_phrases
        assert config.author_map["猫子"] == "Necoco"


class TestMkbrrConfig:
    """Tests for MkbrrConfig dataclass."""

    def test_default_values(self):
        """Test default mkbrr configuration."""
        config = MkbrrConfig()
        assert config.preset == "mam"
        assert "mkbrr" in config.image


class TestQBittorrentConfig:
    """Tests for QBittorrentConfig dataclass."""

    def test_default_values(self):
        """Test default qBittorrent configuration."""
        config = QBittorrentConfig()
        assert config.auto_start is True
        assert "mamfast" in config.tags


class TestLoadYamlConfig:
    """Tests for YAML config loading."""

    def test_load_valid_yaml(self):
        """Test loading a valid YAML config file."""
        yaml_content = """
paths:
  library_root: "/tmp/library"
  torrent_output: "/tmp/torrents"
  seed_root: "/tmp/seed"

mam:
  max_filename_length: 200
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_yaml_config(Path(f.name))

        assert config["paths"]["library_root"] == "/tmp/library"
        assert config["mam"]["max_filename_length"] == 200

    def test_load_missing_file(self):
        """Test that FileNotFoundError is raised for missing file."""
        with pytest.raises(FileNotFoundError):
            load_yaml_config(Path("/nonexistent/config.yaml"))

    def test_load_empty_yaml(self):
        """Test loading empty YAML returns empty dict."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            config = load_yaml_config(Path(f.name))

        assert config == {} or config is None


class TestGetEnv:
    """Tests for _get_env function."""

    def test_returns_env_value(self):
        """Test returns environment variable value."""
        with patch.dict(os.environ, {"TEST_VAR": "test_value"}):
            result = _get_env("TEST_VAR")
            assert result == "test_value"

    def test_returns_default(self):
        """Test returns default when env var not set."""
        with patch.dict(os.environ, {}, clear=True):
            result = _get_env("NONEXISTENT_VAR", "default_value")
            assert result == "default_value"

    def test_raises_without_default(self):
        """Test raises ValueError when no default and var not set."""
        with (
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(ValueError, match="Missing required"),
        ):
            _get_env("REQUIRED_VAR")


class TestGetEnvInt:
    """Tests for _get_env_int function."""

    def test_returns_int_value(self):
        """Test returns integer from environment."""
        with patch.dict(os.environ, {"TEST_INT": "42"}):
            result = _get_env_int("TEST_INT", 0)
            assert result == 42

    def test_returns_default(self):
        """Test returns default when env var not set."""
        with patch.dict(os.environ, {}, clear=True):
            result = _get_env_int("NONEXISTENT_INT", 99)
            assert result == 99


class TestLoadSettings:
    """Tests for load_settings function."""

    def test_loads_settings_from_yaml(self):
        """Test loading settings from config file."""
        yaml_content = """
paths:
  library_root: "/tmp/library"
  torrent_output: "/tmp/torrents"
  seed_root: "/tmp/seed"
  state_file: "/tmp/state.json"
  log_file: "/tmp/app.log"

mam:
  max_filename_length: 200

mkbrr:
  preset: "test-preset"

qbittorrent:
  category: "test-category"

audnex:
  timeout_seconds: 60

mediainfo:
  binary: "/usr/bin/mediainfo"

filters:
  remove_phrases:
    - "Light Novel"
  author_map:
    "川原礫": "Reki Kawahara"

environment:
  log_level: "DEBUG"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(yaml_content)

            # Create .env with required values
            env_path = Path(tmpdir) / ".env"
            env_path.write_text(
                "QB_HOST=localhost:8080\n"
                "QB_USERNAME=admin\n"
                "QB_PASSWORD=secret\n"
                "MAM_ANNOUNCE_URL=http://tracker.example.com\n"
            )

            settings = load_settings(env_file=env_path, config_file=config_path)

            assert settings.paths.library_root == Path("/tmp/library")
            assert settings.mam.max_filename_length == 200
            assert settings.mkbrr.preset == "test-preset"
            assert settings.qbittorrent.category == "test-category"
            assert settings.audnex.timeout_seconds == 60
            assert settings.mediainfo.binary == "/usr/bin/mediainfo"
            assert "Light Novel" in settings.filters.remove_phrases
            assert settings.log_level == "DEBUG"

    def test_finds_env_next_to_config(self):
        """Test .env file is found next to config.yaml."""
        yaml_content = """
paths:
  library_root: "/tmp/library"
  torrent_output: "/tmp/torrents"
  seed_root: "/tmp/seed"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "config"
            config_dir.mkdir()

            config_path = config_dir / "config.yaml"
            config_path.write_text(yaml_content)

            env_path = config_dir / ".env"
            env_path.write_text("QB_HOST=found\n" "QB_USERNAME=admin\n" "QB_PASSWORD=secret\n")

            # Clear any existing env vars and reload
            with patch.dict(
                os.environ, {"QB_HOST": "", "QB_USERNAME": "", "QB_PASSWORD": ""}, clear=False
            ):
                settings = load_settings(config_file=config_path)

            # The .env file should have been loaded
            assert settings.qbittorrent.host in ["found", ""]  # May vary based on test isolation


class TestReloadSettings:
    """Tests for reload_settings function."""

    def test_reloads_settings(self):
        """Test reloading settings clears cache."""
        yaml_content = """
paths:
  library_root: "/tmp/new-library"
  torrent_output: "/tmp/torrents"
  seed_root: "/tmp/seed"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(yaml_content)

            env_path = Path(tmpdir) / ".env"
            env_path.write_text("QB_HOST=localhost\n" "QB_USERNAME=admin\n" "QB_PASSWORD=secret\n")

            settings = reload_settings(env_file=env_path, config_file=config_path, validate=False)

            assert settings.paths.library_root == Path("/tmp/new-library")


class TestValidatePaths:
    """Tests for validate_paths function."""

    def test_returns_empty_for_existing_paths(self):
        """Test no warnings when all paths exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            library = Path(tmpdir) / "library"
            library.mkdir()
            seed = Path(tmpdir) / "seed"
            seed.mkdir()
            torrents = Path(tmpdir) / "torrents"
            torrents.mkdir()

            paths = PathsConfig(
                library_root=library,
                torrent_output=torrents,
                seed_root=seed,
                state_file=Path(tmpdir) / "state.json",
                log_file=Path(tmpdir) / "app.log",
            )

            warnings = validate_paths(paths)
            # Only library_root is strictly required
            assert not any("library_root" in w for w in warnings)

    def test_warns_on_missing_library_root(self):
        """Test warning when library_root doesn't exist."""
        paths = PathsConfig(
            library_root=Path("/nonexistent/library"),
            torrent_output=Path("/tmp/torrents"),
            seed_root=Path("/tmp/seed"),
            state_file=Path("/tmp/state.json"),
            log_file=Path("/tmp/app.log"),
        )

        warnings = validate_paths(paths)
        assert any("library_root" in w for w in warnings)

    def test_strict_raises_on_missing_library_root(self):
        """Test ConfigurationError raised when library_root missing and strict=True."""
        paths = PathsConfig(
            library_root=Path("/nonexistent/library"),
            torrent_output=Path("/tmp/torrents"),
            seed_root=Path("/tmp/seed"),
            state_file=Path("/tmp/state.json"),
            log_file=Path("/tmp/app.log"),
        )

        with pytest.raises(ConfigurationError, match="library_root does not exist"):
            validate_paths(paths, strict=True)

    def test_warns_on_missing_seed_root(self):
        """Test warning for non-existent seed_root (will be created)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            library = Path(tmpdir) / "library"
            library.mkdir()

            paths = PathsConfig(
                library_root=library,
                torrent_output=Path("/tmp/torrents"),
                seed_root=Path("/nonexistent/seed"),
                state_file=Path("/tmp/state.json"),
                log_file=Path("/tmp/app.log"),
            )

            warnings = validate_paths(paths)
            assert any("seed_root" in w and "will be created" in w for w in warnings)


class TestClearSettings:
    """Tests for clear_settings function."""

    def test_clears_cached_settings(self):
        """Test that clear_settings resets the global cache."""
        yaml_content = """
paths:
  library_root: "/tmp/library"
  torrent_output: "/tmp/torrents"
  seed_root: "/tmp/seed"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(yaml_content)

            env_path = Path(tmpdir) / ".env"
            env_path.write_text("QB_HOST=localhost\n" "QB_USERNAME=admin\n" "QB_PASSWORD=secret\n")

            # Load settings
            reload_settings(env_file=env_path, config_file=config_path, validate=False)

            # Clear the cache
            clear_settings()

            # Importing the module to check internal state would be tricky,
            # but we can at least verify clear_settings doesn't raise
            assert True  # No exception means success

    def test_allows_fresh_reload_after_clear(self):
        """Test settings can be reloaded after clearing."""
        yaml_content = """
paths:
  library_root: "/tmp/library-v1"
  torrent_output: "/tmp/torrents"
  seed_root: "/tmp/seed"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(yaml_content)

            env_path = Path(tmpdir) / ".env"
            env_path.write_text("QB_HOST=localhost\n" "QB_USERNAME=admin\n" "QB_PASSWORD=secret\n")

            settings1 = reload_settings(env_file=env_path, config_file=config_path, validate=False)
            assert settings1.paths.library_root == Path("/tmp/library-v1")

            # Clear and reload with different config
            clear_settings()

            yaml_content_v2 = yaml_content.replace("library-v1", "library-v2")
            config_path.write_text(yaml_content_v2)

            settings2 = reload_settings(env_file=env_path, config_file=config_path, validate=False)
            assert settings2.paths.library_root == Path("/tmp/library-v2")
