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
        # Use model_validate to allow passing strings (runtime coercion) without
        # static type-checker complaints about constructor argument types.
        schema = EnvironmentSchema.model_validate({"target_uid": "1000", "target_gid": "1000"})
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
        # Use model_validate with empty dict to avoid static error for missing args
        with pytest.raises(ValidationError):
            PathsSchema.model_validate({})

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


class TestAudiobookshelfSchema:
    """Tests for AudiobookshelfSchema validation."""

    def test_valid_defaults_disabled(self) -> None:
        """Test default values when disabled."""
        from mamfast.schemas.config import AudiobookshelfSchema

        schema = AudiobookshelfSchema()
        assert schema.enabled is False
        assert schema.timeout_seconds == 30
        assert schema.docker_mode is True
        assert schema.path_map == []
        assert schema.libraries == []

    def test_valid_full_config(self) -> None:
        """Test full valid audiobookshelf configuration."""
        from mamfast.schemas.config import AudiobookshelfSchema

        # Build a data dict and validate via model_validate to avoid static ctor type issues
        data = {
            "enabled": True,
            "timeout_seconds": 60,
            "docker_mode": True,
            "path_map": [{"container": "/audiobooks", "host": "/mnt/data/audiobooks"}],
            "libraries": [{"id": "lib_abc123", "name": "Audiobooks", "mamfast_managed": True}],
            "import_settings": {"duplicate_policy": "skip", "trigger_scan": "batch"},
            "index_db": "./data/abs_index.db",
        }
        schema = AudiobookshelfSchema.model_validate(data)
        assert schema.enabled is True
        assert schema.timeout_seconds == 60
        assert len(schema.path_map) == 1
        assert schema.path_map[0].container == "/audiobooks"
        assert schema.path_map[0].host == "/mnt/data/audiobooks"
        assert schema.libraries[0].id == "lib_abc123"
        assert schema.import_settings.duplicate_policy == "skip"

    def test_import_alias_works(self) -> None:
        """Test 'import' key works as alias for import_settings."""
        from mamfast.schemas.config import AudiobookshelfSchema

        # Using the 'import' key (as in YAML)
        data = {
            "enabled": False,
            "import": {"duplicate_policy": "warn", "trigger_scan": "each"},
        }
        schema = AudiobookshelfSchema.model_validate(data)
        assert schema.import_settings.duplicate_policy == "warn"
        assert schema.import_settings.trigger_scan == "each"

    def test_docker_mode_requires_path_map(self) -> None:
        """Test that path_map is required when docker_mode is enabled."""
        from mamfast.schemas.config import AudiobookshelfSchema

        with pytest.raises(ValidationError) as exc_info:
            AudiobookshelfSchema(enabled=True, docker_mode=True, path_map=[])
        assert "path_map is required" in str(exc_info.value)

    def test_docker_mode_false_no_path_map_ok(self) -> None:
        """Test that path_map is not required when docker_mode is False."""
        from mamfast.schemas.config import AudiobookshelfSchema

        schema = AudiobookshelfSchema(enabled=True, docker_mode=False, path_map=[])
        assert schema.docker_mode is False
        assert schema.path_map == []

    def test_path_map_validation(self) -> None:
        """Test path_map entries are validated."""
        from mamfast.schemas.config import AudiobookshelfPathMapSchema

        # Valid
        schema = AudiobookshelfPathMapSchema(container="/audiobooks", host="/mnt/data")
        assert schema.container == "/audiobooks"
        assert schema.host == "/mnt/data"

        # Invalid - not absolute
        with pytest.raises(ValidationError) as exc_info:
            AudiobookshelfPathMapSchema(container="audiobooks", host="/mnt/data")
        assert "must be absolute" in str(exc_info.value)

        # Invalid - empty
        with pytest.raises(ValidationError) as exc_info:
            AudiobookshelfPathMapSchema(container="", host="/mnt/data")
        assert "required but empty" in str(exc_info.value)

    def test_path_map_trailing_slash_normalized(self) -> None:
        """Test trailing slashes are removed from path mappings."""
        from mamfast.schemas.config import AudiobookshelfPathMapSchema

        schema = AudiobookshelfPathMapSchema(container="/audiobooks/", host="/mnt/data/audiobooks/")
        assert schema.container == "/audiobooks"
        assert schema.host == "/mnt/data/audiobooks"

    def test_library_id_validation(self) -> None:
        """Test library ID format validation."""
        from mamfast.schemas.config import AudiobookshelfLibrarySchema

        # Valid
        schema = AudiobookshelfLibrarySchema(id="lib_abc123", name="Test")
        assert schema.id == "lib_abc123"

        # Invalid - missing lib_ prefix
        with pytest.raises(ValidationError) as exc_info:
            AudiobookshelfLibrarySchema(id="abc123", name="Test")
        assert "should start with 'lib_'" in str(exc_info.value)

        # Invalid - empty
        with pytest.raises(ValidationError) as exc_info:
            AudiobookshelfLibrarySchema(id="", name="Test")
        assert "required" in str(exc_info.value)

    def test_duplicate_policy_validation(self) -> None:
        """Test duplicate_policy must be valid value."""
        from mamfast.schemas.config import AudiobookshelfImportSchema

        # Valid values
        for policy in ["skip", "warn", "overwrite"]:
            schema = AudiobookshelfImportSchema(duplicate_policy=policy)
            assert schema.duplicate_policy == policy

        # Invalid
        with pytest.raises(ValidationError) as exc_info:
            AudiobookshelfImportSchema(duplicate_policy="replace")
        assert "Invalid duplicate_policy" in str(exc_info.value)

    def test_trigger_scan_validation(self) -> None:
        """Test trigger_scan must be valid value."""
        from mamfast.schemas.config import AudiobookshelfImportSchema

        # Valid values
        for scan in ["none", "each", "batch"]:
            schema = AudiobookshelfImportSchema(trigger_scan=scan)
            assert schema.trigger_scan == scan

        # Invalid
        with pytest.raises(ValidationError) as exc_info:
            AudiobookshelfImportSchema(trigger_scan="always")
        assert "Invalid trigger_scan" in str(exc_info.value)

    def test_full_config_with_audiobookshelf(self) -> None:
        """Test complete config including audiobookshelf section."""
        data = {
            "paths": {
                "library_root": "/mnt/data/audiobooks",
                "torrent_output": "/mnt/data/torrents",
                "seed_root": "/mnt/data/seed",
            },
            "audiobookshelf": {
                "enabled": True,
                "timeout_seconds": 45,
                "docker_mode": True,
                "path_map": [{"container": "/audiobooks", "host": "/mnt/user/data/audiobooks"}],
                "libraries": [
                    {"id": "lib_test123", "name": "Main Library", "mamfast_managed": True}
                ],
                "import": {"duplicate_policy": "skip", "trigger_scan": "batch"},
                "index_db": "./data/abs_index.db",
            },
        }
        schema = validate_config_yaml(data)
        assert schema.audiobookshelf.enabled is True
        assert schema.audiobookshelf.path_map[0].container == "/audiobooks"
        assert schema.audiobookshelf.libraries[0].mamfast_managed is True
        assert schema.audiobookshelf.import_settings.trigger_scan == "batch"
