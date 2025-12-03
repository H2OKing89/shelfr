"""Tests for config.yaml Pydantic schema validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mamfast.schemas.config import (
    AudnexSchema,
    EnvironmentSchema,
    FiltersSchema,
    MamSchema,
    PathsSchema,
    validate_config_yaml,
)


class TestEnvironmentSchema:
    """Tests for EnvironmentSchema validation."""

    def test_valid_defaults(self) -> None:
        """Test default values are valid."""
        schema = EnvironmentSchema()
        assert schema.libation_container == "libation"
        assert schema.docker_bin == "/usr/bin/docker"
        assert schema.target_uid == 99
        assert schema.target_gid == 100
        assert schema.log_level == "INFO"

    def test_valid_log_levels(self) -> None:
        """Test all valid log levels are accepted."""
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            schema = EnvironmentSchema(log_level=level)
            assert schema.log_level == level

    def test_log_level_case_insensitive(self) -> None:
        """Test log level is normalized to uppercase."""
        schema = EnvironmentSchema(log_level="debug")
        assert schema.log_level == "DEBUG"

    def test_invalid_log_level(self) -> None:
        """Test invalid log level raises error."""
        with pytest.raises(ValidationError) as exc_info:
            EnvironmentSchema(log_level="VERBOSE")
        assert "Invalid log_level" in str(exc_info.value)

    def test_uid_gid_string_coercion(self) -> None:
        """Test UID/GID can be provided as strings."""
        schema = EnvironmentSchema(target_uid="1000", target_gid="1000")
        assert schema.target_uid == 1000
        assert schema.target_gid == 1000


class TestPathsSchema:
    """Tests for PathsSchema validation."""

    def test_valid_paths(self) -> None:
        """Test valid path configuration."""
        schema = PathsSchema(
            library_root="/mnt/data/audiobooks",
            torrent_output="/mnt/data/torrents",
            seed_root="/mnt/data/seed",
        )
        assert schema.library_root == "/mnt/data/audiobooks"
        assert schema.state_file == "./data/processed.json"  # default

    def test_required_paths(self) -> None:
        """Test required paths must be provided."""
        with pytest.raises(ValidationError):
            PathsSchema()

    def test_empty_path_rejected(self) -> None:
        """Test empty required paths are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            PathsSchema(
                library_root="",
                torrent_output="/mnt/data/torrents",
                seed_root="/mnt/data/seed",
            )
        assert "library_root" in str(exc_info.value)


class TestMamSchema:
    """Tests for MamSchema validation."""

    def test_valid_defaults(self) -> None:
        """Test default values are valid."""
        schema = MamSchema()
        assert schema.max_filename_length == 225
        assert ".m4b" in schema.allowed_extensions

    def test_filename_length_bounds(self) -> None:
        """Test filename length is within bounds."""
        schema = MamSchema(max_filename_length=100)
        assert schema.max_filename_length == 100

        with pytest.raises(ValidationError):
            MamSchema(max_filename_length=10)  # Too small

        with pytest.raises(ValidationError):
            MamSchema(max_filename_length=500)  # Too large

    def test_extension_validation(self) -> None:
        """Test extensions must start with dot."""
        with pytest.raises(ValidationError) as exc_info:
            MamSchema(allowed_extensions=["m4b", ".jpg"])
        assert "must start with a dot" in str(exc_info.value)


class TestAudnexSchema:
    """Tests for AudnexSchema validation."""

    def test_valid_defaults(self) -> None:
        """Test default values are valid."""
        schema = AudnexSchema()
        assert schema.base_url == "https://api.audnex.us"
        assert schema.timeout_seconds == 30

    def test_url_validation(self) -> None:
        """Test URL must have valid protocol."""
        with pytest.raises(ValidationError) as exc_info:
            AudnexSchema(base_url="api.audnex.us")
        assert "must start with http" in str(exc_info.value)

    def test_url_trailing_slash_removed(self) -> None:
        """Test trailing slash is normalized."""
        schema = AudnexSchema(base_url="https://api.audnex.us/")
        assert schema.base_url == "https://api.audnex.us"

    def test_timeout_bounds(self) -> None:
        """Test timeout is within reasonable bounds."""
        with pytest.raises(ValidationError):
            AudnexSchema(timeout_seconds=1)  # Too small

        with pytest.raises(ValidationError):
            AudnexSchema(timeout_seconds=300)  # Too large


class TestFiltersSchema:
    """Tests for FiltersSchema validation."""

    def test_valid_defaults(self) -> None:
        """Test default values are valid."""
        schema = FiltersSchema()
        assert schema.remove_book_numbers is True
        assert schema.transliterate_japanese is True

    def test_legacy_fields_accepted(self) -> None:
        """Test legacy fields are accepted but excluded from output."""
        schema = FiltersSchema(
            remove_phrases=["test"],
            author_map={"a": "b"},
        )
        # Should not raise, but fields are excluded
        assert schema.remove_book_numbers is True
        data = schema.model_dump()
        assert "remove_phrases" not in data
        assert "author_map" not in data


class TestConfigSchema:
    """Tests for complete ConfigSchema validation."""

    def test_valid_minimal_config(self) -> None:
        """Test minimal valid configuration."""
        data = {
            "paths": {
                "library_root": "/mnt/data/audiobooks",
                "torrent_output": "/mnt/data/torrents",
                "seed_root": "/mnt/data/seed",
            }
        }
        schema = validate_config_yaml(data)
        assert schema.paths.library_root == "/mnt/data/audiobooks"
        assert schema.mam.max_filename_length == 225  # default

    def test_valid_full_config(self) -> None:
        """Test full configuration with all sections."""
        data = {
            "environment": {
                "libation_container": "Libation",
                "docker_bin": "/usr/bin/docker",
                "target_uid": 99,
                "target_gid": 100,
            },
            "paths": {
                "library_root": "/mnt/data/audiobooks",
                "torrent_output": "/mnt/data/torrents",
                "seed_root": "/mnt/data/seed",
                "state_file": "./data/state.json",
                "log_file": "./logs/app.log",
            },
            "mam": {
                "max_filename_length": 225,
                "allowed_extensions": [".m4b", ".mp3"],
            },
            "mkbrr": {
                "image": "ghcr.io/autobrr/mkbrr:latest",
                "preset": "mam",
            },
            "qbittorrent": {
                "category": "audiobooks",
                "tags": ["mam", "auto"],
                "auto_start": True,
            },
            "audnex": {
                "base_url": "https://api.audnex.us",
                "timeout_seconds": 30,
            },
            "mediainfo": {
                "binary": "mediainfo",
            },
            "filters": {
                "remove_book_numbers": True,
                "transliterate_japanese": True,
            },
        }
        schema = validate_config_yaml(data)
        assert schema.environment.libation_container == "Libation"
        assert schema.mam.allowed_extensions == [".m4b", ".mp3"]
        assert schema.qbittorrent.tags == ["mam", "auto"]

    def test_extra_keys_rejected(self) -> None:
        """Test unknown top-level keys are rejected."""
        data = {
            "paths": {
                "library_root": "/mnt/data/audiobooks",
                "torrent_output": "/mnt/data/torrents",
                "seed_root": "/mnt/data/seed",
            },
            "unknown_section": {"foo": "bar"},
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_config_yaml(data)
        assert "unknown_section" in str(exc_info.value)

    def test_missing_required_paths(self) -> None:
        """Test missing required paths raises error."""
        data = {
            "paths": {
                "library_root": "/mnt/data/audiobooks",
                # Missing torrent_output and seed_root
            }
        }
        with pytest.raises(ValidationError):
            validate_config_yaml(data)


class TestConfigSchemaLibation:
    """Tests for LibationSchema regex validation."""

    def test_valid_regex_patterns(self) -> None:
        """Test valid regex patterns are accepted."""
        data = {
            "paths": {
                "library_root": "/mnt/data/audiobooks",
                "torrent_output": "/mnt/data/torrents",
                "seed_root": "/mnt/data/seed",
            },
            "libation": {
                "folder_pattern": r"^(.*?)(?: vol_(\d+))?$",
                "asin_pattern": r"^[A-Z0-9]{10}$",
            },
        }
        schema = validate_config_yaml(data)
        assert schema.libation.asin_pattern == r"^[A-Z0-9]{10}$"

    def test_invalid_regex_rejected(self) -> None:
        """Test invalid regex patterns are rejected."""
        data = {
            "paths": {
                "library_root": "/mnt/data/audiobooks",
                "torrent_output": "/mnt/data/torrents",
                "seed_root": "/mnt/data/seed",
            },
            "libation": {
                "asin_pattern": "[invalid(regex",  # Unclosed bracket
            },
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_config_yaml(data)
        assert "Invalid regex" in str(exc_info.value)
