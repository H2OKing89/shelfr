"""Tests for exception hierarchy."""

from __future__ import annotations

from pathlib import Path

import pytest

from shelfr.exceptions import (
    AudiobookshelfError,
    AudnexError,
    ConfigurationError,
    DiscoveryValidationError,
    DockerError,
    ExternalToolError,
    LibationError,
    MetadataError,
    MkbrrError,
    NetworkError,
    PipelineError,
    PreUploadValidationError,
    QBittorrentError,
    ShelfrError,
    StagingError,
    StateCorruptionError,
    StateError,
    StateLockError,
    TorrentError,
    UploadError,
    ValidationError,
)


class TestShelfrError:
    """Tests for base exception."""

    def test_simple_message(self) -> None:
        """Base exception stores message."""
        exc = ShelfrError("test error")
        assert str(exc) == "test error"
        assert exc.message == "test error"
        assert exc.details == {}

    def test_with_details(self) -> None:
        """Details dict is stored."""
        exc = ShelfrError("test", details={"key": "value"})
        assert exc.details == {"key": "value"}

    def test_can_be_raised(self) -> None:
        """Can raise and catch as Exception."""
        with pytest.raises(ShelfrError) as exc_info:
            raise ShelfrError("raised")
        assert str(exc_info.value) == "raised"

    def test_can_be_caught_as_exception(self) -> None:
        """Can catch as generic Exception."""
        exc = ShelfrError("generic")
        assert isinstance(exc, Exception)


class TestConfigurationError:
    """Tests for configuration errors."""

    def test_basic(self) -> None:
        """Basic message."""
        exc = ConfigurationError("Invalid config")
        assert str(exc) == "Invalid config"
        assert exc.config_file is None
        assert exc.field is None

    def test_with_file(self) -> None:
        """Config file path stored."""
        exc = ConfigurationError("Missing", config_file=Path("/etc/config.yaml"))
        assert exc.config_file == Path("/etc/config.yaml")
        assert exc.details["config_file"] == "/etc/config.yaml"

    def test_with_field(self) -> None:
        """Field name stored."""
        exc = ConfigurationError("Invalid value", field="log_level")
        assert exc.field == "log_level"
        assert exc.details["field"] == "log_level"

    def test_inherits_shelfr_error(self) -> None:
        """Inherits from base."""
        exc = ConfigurationError("test")
        assert isinstance(exc, ShelfrError)


class TestValidationError:
    """Tests for validation errors."""

    def test_basic(self) -> None:
        """Basic validation error."""
        exc = ValidationError("Validation failed")
        assert exc.errors == []
        assert exc.warnings == []

    def test_with_errors_list(self) -> None:
        """Stores error list."""
        exc = ValidationError("Failed", errors=["error1", "error2"])
        assert exc.errors == ["error1", "error2"]
        assert exc.details["errors"] == ["error1", "error2"]

    def test_with_warnings_list(self) -> None:
        """Stores warning list."""
        exc = ValidationError("Issues", warnings=["warn1"])
        assert exc.warnings == ["warn1"]

    def test_discovery_validation_error(self) -> None:
        """Discovery validation subclass."""
        exc = DiscoveryValidationError("No books found")
        assert isinstance(exc, ValidationError)
        assert isinstance(exc, ShelfrError)

    def test_pre_upload_validation_error(self) -> None:
        """Pre-upload validation subclass."""
        exc = PreUploadValidationError("ASIN missing")
        assert isinstance(exc, ValidationError)


class TestPipelineError:
    """Tests for pipeline stage errors."""

    def test_basic(self) -> None:
        """Basic pipeline error."""
        exc = PipelineError("Stage failed")
        assert exc.stage is None
        assert exc.release_asin is None
        assert exc.release_title is None

    def test_with_stage(self) -> None:
        """Stage info stored."""
        exc = PipelineError("Failed", stage="metadata")
        assert exc.stage == "metadata"
        assert exc.details["stage"] == "metadata"

    def test_with_release_info(self) -> None:
        """Release info stored."""
        exc = PipelineError(
            "Failed",
            release_asin="B123456789",
            release_title="Test Book",
        )
        assert exc.release_asin == "B123456789"
        assert exc.release_title == "Test Book"


class TestStagingError:
    """Tests for staging errors."""

    def test_default_stage(self) -> None:
        """Auto-sets stage to staging."""
        exc = StagingError("Hardlink failed")
        assert exc.stage == "staging"

    def test_paths(self) -> None:
        """Source/target paths stored."""
        exc = StagingError(
            "Failed",
            source_path=Path("/src/book"),
            target_path=Path("/dst/book"),
        )
        assert exc.source_path == Path("/src/book")
        assert exc.target_path == Path("/dst/book")
        assert exc.details["source_path"] == "/src/book"


class TestMetadataError:
    """Tests for metadata errors."""

    def test_default_stage(self) -> None:
        """Auto-sets stage to metadata."""
        exc = MetadataError("Audnex failed")
        assert exc.stage == "metadata"

    def test_inherits_pipeline(self) -> None:
        """Inherits from PipelineError."""
        exc = MetadataError("Failed", release_asin="B123")
        assert isinstance(exc, PipelineError)
        assert exc.release_asin == "B123"


class TestTorrentError:
    """Tests for torrent errors."""

    def test_default_stage(self) -> None:
        """Auto-sets stage to torrent."""
        exc = TorrentError("mkbrr failed")
        assert exc.stage == "torrent"

    def test_torrent_path(self) -> None:
        """Torrent path stored."""
        exc = TorrentError("Failed", torrent_path=Path("/tmp/book.torrent"))
        assert exc.torrent_path == Path("/tmp/book.torrent")
        assert exc.details["torrent_path"] == "/tmp/book.torrent"


class TestUploadError:
    """Tests for upload errors."""

    def test_default_stage(self) -> None:
        """Auto-sets stage to upload."""
        exc = UploadError("qBittorrent failed")
        assert exc.stage == "upload"

    def test_infohash(self) -> None:
        """Infohash stored."""
        exc = UploadError("Failed", infohash="abc123def456")
        assert exc.infohash == "abc123def456"
        assert exc.details["infohash"] == "abc123def456"


class TestNetworkError:
    """Tests for network errors."""

    def test_basic(self) -> None:
        """Basic network error."""
        exc = NetworkError("Connection failed")
        assert exc.service is None
        assert exc.url is None
        assert exc.status_code is None

    def test_with_service_info(self) -> None:
        """Service info stored."""
        exc = NetworkError(
            "Failed",
            service="audnex",
            url="https://api.audnex.us/books",
            status_code=503,
        )
        assert exc.service == "audnex"
        assert exc.url == "https://api.audnex.us/books"
        assert exc.status_code == 503


class TestAudnexError:
    """Tests for Audnex errors."""

    def test_default_service(self) -> None:
        """Auto-sets service to audnex."""
        exc = AudnexError("API error")
        assert exc.service == "audnex"

    def test_with_asin(self) -> None:
        """ASIN stored."""
        exc = AudnexError("Not found", asin="B123456789")
        assert exc.asin == "B123456789"
        assert exc.details["asin"] == "B123456789"


class TestQBittorrentError:
    """Tests for qBittorrent errors."""

    def test_default_service(self) -> None:
        """Auto-sets service to qbittorrent."""
        exc = QBittorrentError("Login failed")
        assert exc.service == "qbittorrent"


class TestAudiobookshelfError:
    """Tests for Audiobookshelf errors."""

    def test_default_service(self) -> None:
        """Auto-sets service to audiobookshelf."""
        exc = AudiobookshelfError("API error")
        assert exc.service == "audiobookshelf"

    def test_with_library_id(self) -> None:
        """Library ID stored."""
        exc = AudiobookshelfError("Failed", library_id="lib_abc123")
        assert exc.library_id == "lib_abc123"


class TestStateError:
    """Tests for state errors."""

    def test_basic(self) -> None:
        """Basic state error."""
        exc = StateError("State issue")
        assert exc.state_file is None

    def test_with_state_file(self) -> None:
        """State file path stored."""
        exc = StateError("Corrupted", state_file=Path("/data/state.json"))
        assert exc.state_file == Path("/data/state.json")


class TestStateLockError:
    """Tests for lock errors."""

    def test_basic(self) -> None:
        """Basic lock error."""
        exc = StateLockError("Lock failed")
        assert exc.lock_file is None

    def test_with_lock_file(self) -> None:
        """Lock file path stored."""
        exc = StateLockError("Conflict", lock_file="/tmp/shelfr.lock")
        assert exc.lock_file == "/tmp/shelfr.lock"

    def test_inherits_state_error(self) -> None:
        """Inherits from StateError."""
        exc = StateLockError("test")
        assert isinstance(exc, StateError)


class TestStateCorruptionError:
    """Tests for corruption errors."""

    def test_inherits_state_error(self) -> None:
        """Inherits from StateError."""
        exc = StateCorruptionError("JSON invalid", state_file="/data/state.json")
        assert isinstance(exc, StateError)
        assert exc.state_file == "/data/state.json"


class TestExternalToolError:
    """Tests for external tool errors."""

    def test_basic(self) -> None:
        """Basic tool error."""
        exc = ExternalToolError("Tool failed")
        assert exc.tool is None
        assert exc.command is None
        assert exc.return_code is None
        assert exc.stdout is None
        assert exc.stderr is None

    def test_with_all_fields(self) -> None:
        """All fields stored."""
        exc = ExternalToolError(
            "Failed",
            tool="mkbrr",
            command="mkbrr create /path",
            return_code=1,
            stdout="output",
            stderr="error output",
        )
        assert exc.tool == "mkbrr"
        assert exc.command == "mkbrr create /path"
        assert exc.return_code == 1
        assert exc.stdout == "output"
        assert exc.stderr == "error output"


class TestDockerError:
    """Tests for Docker errors."""

    def test_default_tool(self) -> None:
        """Auto-sets tool to docker."""
        exc = DockerError("Daemon not running")
        assert exc.tool == "docker"


class TestMkbrrError:
    """Tests for mkbrr errors."""

    def test_default_tool(self) -> None:
        """Auto-sets tool to mkbrr."""
        exc = MkbrrError("Torrent creation failed")
        assert exc.tool == "mkbrr"


class TestLibationError:
    """Tests for Libation errors."""

    def test_default_tool(self) -> None:
        """Auto-sets tool to libation."""
        exc = LibationError("Export failed")
        assert exc.tool == "libation"


class TestExceptionHierarchy:
    """Test exception inheritance hierarchy."""

    def test_all_inherit_from_base(self) -> None:
        """All exceptions inherit from ShelfrError."""
        exceptions = [
            ConfigurationError("test"),
            ValidationError("test"),
            DiscoveryValidationError("test"),
            PreUploadValidationError("test"),
            PipelineError("test"),
            StagingError("test"),
            MetadataError("test"),
            TorrentError("test"),
            UploadError("test"),
            NetworkError("test"),
            AudnexError("test"),
            QBittorrentError("test"),
            AudiobookshelfError("test"),
            StateError("test"),
            StateLockError("test"),
            StateCorruptionError("test"),
            ExternalToolError("test"),
            DockerError("test"),
            MkbrrError("test"),
            LibationError("test"),
        ]
        for exc in exceptions:
            assert isinstance(exc, ShelfrError), f"{type(exc)} not ShelfrError"

    def test_catch_by_category(self) -> None:
        """Can catch by category."""
        # Catch all network errors
        with pytest.raises(NetworkError):
            raise AudnexError("API failed")

        with pytest.raises(NetworkError):
            raise QBittorrentError("Upload failed")

        # Catch all pipeline errors
        with pytest.raises(PipelineError):
            raise StagingError("Hardlink failed")

        with pytest.raises(PipelineError):
            raise TorrentError("Creation failed")

        # Catch all tool errors
        with pytest.raises(ExternalToolError):
            raise DockerError("Daemon error")

        with pytest.raises(ExternalToolError):
            raise MkbrrError("Tool error")

    def test_catch_all_shelfr_errors(self) -> None:
        """Can catch all Shelfr errors with base class."""
        errors = [
            ConfigurationError("config"),
            StagingError("staging"),
            AudnexError("audnex"),
            StateLockError("lock"),
            DockerError("docker"),
        ]
        for error in errors:
            with pytest.raises(ShelfrError):
                raise error
