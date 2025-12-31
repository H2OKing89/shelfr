"""Tests for the validation module."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

from shelfr.config import Settings
from shelfr.validation import (
    CheckCategory,
    ValidationCheck,
    ValidationResult,
    _check_audnex_api,
    _check_docker_container,
    _check_docker_image,
    _check_docker_running,
    _check_qbittorrent,
    check_categories,
    check_config,
    check_paths,
    check_services,
    run_all_checks,
)

# =============================================================================
# Mock Settings
# =============================================================================


@dataclass
class MockPathsConfig:
    """Mock paths config for testing."""

    library_root: Path = field(default_factory=lambda: Path("/tmp/test_library"))
    seed_root: Path = field(default_factory=lambda: Path("/tmp/test_seed"))
    torrent_output: Path = field(default_factory=lambda: Path("/tmp/test_torrents"))
    state_file: Path = field(default_factory=lambda: Path("/tmp/test_state.json"))
    log_file: Path = field(default_factory=lambda: Path("/tmp/test.log"))


@dataclass
class MockMkbrrConfig:
    """Mock mkbrr config for testing."""

    image: str = "ghcr.io/autobrr/mkbrr"
    preset: str = "mam"
    host_data_root: str = "/data"
    container_data_root: str = "/data"
    host_output_dir: str = "/torrents"
    container_output_dir: str = "/torrents"
    host_config_dir: str = "/config"
    container_config_dir: str = "/config"


@dataclass
class MockQBittorrentConfig:
    """Mock qBittorrent config for testing."""

    host: str = "http://localhost:8080"
    username: str = "admin"
    password: str = "password"
    category: str = "audiobooks"
    tags: list[str] = field(default_factory=lambda: ["test"])
    auto_start: bool = True
    auto_tmm: bool = False
    save_path: str = ""


@dataclass
class MockAudnexConfig:
    """Mock Audnex config for testing."""

    base_url: str = "https://api.audnex.us"
    timeout_seconds: int = 30


@dataclass
class MockCategoriesConfig:
    """Mock categories config for testing."""

    genre_map: dict[str, int] = field(default_factory=lambda: {"fantasy": 100, "sci-fi": 101})
    audiobook_fiction_map: dict[str, str] = field(default_factory=dict)
    audiobook_nonfiction_map: dict[str, str] = field(default_factory=dict)
    audiobook_defaults: dict[str, str] = field(default_factory=dict)


@dataclass
class MockSettings:
    """Mock settings for testing validation."""

    libation_container: str = "Libation"
    docker_bin: str = "/usr/bin/docker"
    target_uid: int = 99
    target_gid: int = 100
    env: str = "test"
    log_level: str = "INFO"
    paths: MockPathsConfig = field(default_factory=MockPathsConfig)
    mkbrr: MockMkbrrConfig = field(default_factory=MockMkbrrConfig)
    qbittorrent: MockQBittorrentConfig = field(default_factory=MockQBittorrentConfig)
    audnex: MockAudnexConfig = field(default_factory=MockAudnexConfig)
    categories: MockCategoriesConfig = field(default_factory=MockCategoriesConfig)


def build_settings(**overrides: Any) -> Settings:
    """Return a Settings-typed mock instance for type checkers."""
    return cast(Settings, MockSettings(**overrides))


# =============================================================================
# ValidationCheck Tests
# =============================================================================


class TestValidationCheck:
    """Tests for ValidationCheck dataclass."""

    def test_passed_check_icon(self):
        """Passed checks show checkmark."""
        check = ValidationCheck(name="test", passed=True, message="OK")
        assert check.icon == "✓"

    def test_failed_error_icon(self):
        """Failed error checks show X."""
        check = ValidationCheck(name="test", passed=False, message="Failed", severity="error")
        assert check.icon == "✗"

    def test_failed_warning_icon(self):
        """Failed warning checks show warning sign."""
        check = ValidationCheck(name="test", passed=False, message="Warn", severity="warning")
        assert check.icon == "⚠"

    def test_failed_info_icon(self):
        """Failed info checks show info sign."""
        check = ValidationCheck(name="test", passed=False, message="Info", severity="info")
        assert check.icon == "ℹ"

    def test_default_severity_is_error(self):
        """Default severity should be error."""
        check = ValidationCheck(name="test", passed=True, message="OK")
        assert check.severity == "error"

    def test_default_category_is_config(self):
        """Default category should be CONFIG."""
        check = ValidationCheck(name="test", passed=True, message="OK")
        assert check.category == CheckCategory.CONFIG


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_empty_result_passes(self):
        """Empty result should pass."""
        result = ValidationResult()
        assert result.passed is True
        assert result.error_count == 0
        assert result.warning_count == 0
        assert result.passed_count == 0

    def test_all_passed_checks(self):
        """Result with all passed checks should pass."""
        result = ValidationResult()
        result.add(ValidationCheck(name="a", passed=True, message="OK"))
        result.add(ValidationCheck(name="b", passed=True, message="OK"))
        assert result.passed is True
        assert result.passed_count == 2
        assert result.error_count == 0

    def test_failed_error_check_fails_result(self):
        """Result with a failed error check should fail."""
        result = ValidationResult()
        result.add(ValidationCheck(name="a", passed=True, message="OK"))
        result.add(ValidationCheck(name="b", passed=False, message="Fail", severity="error"))
        assert result.passed is False
        assert result.error_count == 1
        assert result.passed_count == 1

    def test_failed_warning_doesnt_fail_result(self):
        """Result with only failed warnings should still pass."""
        result = ValidationResult()
        result.add(ValidationCheck(name="a", passed=True, message="OK"))
        result.add(ValidationCheck(name="b", passed=False, message="Warn", severity="warning"))
        assert result.passed is True
        assert result.warning_count == 1

    def test_by_category_filter(self):
        """by_category should filter checks correctly."""
        result = ValidationResult()
        result.add(
            ValidationCheck(name="a", passed=True, message="OK", category=CheckCategory.CONFIG)
        )
        result.add(
            ValidationCheck(name="b", passed=True, message="OK", category=CheckCategory.PATHS)
        )
        result.add(
            ValidationCheck(name="c", passed=True, message="OK", category=CheckCategory.CONFIG)
        )

        config_checks = result.by_category(CheckCategory.CONFIG)
        assert len(config_checks) == 2
        path_checks = result.by_category(CheckCategory.PATHS)
        assert len(path_checks) == 1

    def test_merge_combines_checks(self):
        """merge should combine checks from both results."""
        result1 = ValidationResult()
        result1.add(ValidationCheck(name="a", passed=True, message="OK"))

        result2 = ValidationResult()
        result2.add(ValidationCheck(name="b", passed=True, message="OK"))

        result1.merge(result2)
        assert len(result1.checks) == 2


# =============================================================================
# check_config Tests
# =============================================================================


class TestCheckConfig:
    """Tests for check_config function."""

    def test_valid_config_passes(self):
        """Valid config should pass all checks."""
        settings = build_settings()
        result = check_config(settings)

        assert result.passed is True
        assert result.error_count == 0

    def test_missing_container_fails(self):
        """Missing libation_container should fail."""
        settings = build_settings(libation_container="")
        result = check_config(settings)

        failed = [c for c in result.checks if c.name == "libation_container"]
        assert len(failed) == 1
        assert failed[0].passed is False

    def test_invalid_uid_fails(self):
        """Negative UID should fail."""
        settings = build_settings(target_uid=-1)
        result = check_config(settings)

        failed = [c for c in result.checks if c.name == "target_uid"]
        assert len(failed) == 1
        assert failed[0].passed is False

    def test_missing_qb_host_fails(self):
        """Missing qBittorrent host should fail."""
        settings = build_settings()
        settings.qbittorrent.host = ""
        result = check_config(settings)

        failed = [c for c in result.checks if c.name == "qbittorrent_host"]
        assert len(failed) == 1
        assert failed[0].passed is False


# =============================================================================
# check_paths Tests
# =============================================================================


class TestCheckPaths:
    """Tests for check_paths function."""

    def test_existing_paths_pass(self, tmp_path):
        """Existing, accessible paths should pass."""
        library = tmp_path / "library"
        library.mkdir()
        seed = tmp_path / "seed"
        seed.mkdir()
        torrents = tmp_path / "torrents"
        torrents.mkdir()
        state_dir = tmp_path / "data"
        state_dir.mkdir()

        settings = cast(Any, build_settings())
        settings.paths = MockPathsConfig(
            library_root=library,
            seed_root=seed,
            torrent_output=torrents,
            state_file=state_dir / "state.json",
        )

        result = check_paths(settings)

        # Check library_root passed
        lib_check = next(c for c in result.checks if c.name == "library_root")
        assert lib_check.passed is True

        # Check seed_root passed
        seed_check = next(c for c in result.checks if c.name == "seed_root")
        assert seed_check.passed is True

    def test_missing_library_fails(self, tmp_path):
        """Missing library_root should fail."""
        settings = cast(Any, build_settings())
        settings.paths = MockPathsConfig(
            library_root=tmp_path / "nonexistent",
            seed_root=tmp_path / "seed",
            torrent_output=tmp_path / "torrents",
        )

        result = check_paths(settings)

        lib_check = next(c for c in result.checks if c.name == "library_root")
        assert lib_check.passed is False

    def test_same_filesystem_check(self, tmp_path):
        """Same filesystem check should pass when on same fs."""
        library = tmp_path / "library"
        library.mkdir()
        seed = tmp_path / "seed"
        seed.mkdir()
        torrents = tmp_path / "torrents"
        torrents.mkdir()
        state_dir = tmp_path / "data"
        state_dir.mkdir()

        settings = cast(Any, build_settings())
        settings.paths = MockPathsConfig(
            library_root=library,
            seed_root=seed,
            torrent_output=torrents,
            state_file=state_dir / "state.json",
        )

        result = check_paths(settings)

        fs_check = next((c for c in result.checks if c.name == "same_filesystem"), None)
        if fs_check:
            assert fs_check.passed is True


# =============================================================================
# check_services Tests (mocked)
# =============================================================================


class TestCheckServices:
    """Tests for check_services function."""

    @patch("shelfr.validation._check_docker_running")
    @patch("shelfr.validation._check_docker_image")
    @patch("shelfr.validation._check_docker_container")
    @patch("shelfr.validation._check_qbittorrent")
    @patch("shelfr.validation._check_audnex_api")
    def test_all_services_available(
        self,
        mock_audnex,
        mock_qb,
        mock_container,
        mock_image,
        mock_docker,
    ):
        """All services available should pass."""
        mock_docker.return_value = True
        mock_image.return_value = True
        mock_container.return_value = True
        mock_qb.return_value = (True, "qBittorrent: Connected (v4.5.0)")
        mock_audnex.return_value = True

        settings = build_settings()
        result = check_services(settings)

        assert result.passed is True
        assert result.error_count == 0

    @patch("shelfr.validation._check_docker_running")
    def test_docker_not_running_fails(self, mock_docker):
        """Docker not running should fail."""
        mock_docker.return_value = False

        settings = build_settings()
        result = check_services(settings)

        docker_check = next(c for c in result.checks if c.name == "docker_daemon")
        assert docker_check.passed is False


# =============================================================================
# check_categories Tests
# =============================================================================


class TestCheckCategories:
    """Tests for check_categories function."""

    def test_valid_categories_pass(self):
        """Valid categories should pass."""
        settings = build_settings()
        result = check_categories(settings)

        assert result.passed is True

    def test_empty_categories_fail(self):
        """Empty genre_map should fail."""
        settings = build_settings()
        settings.categories.genre_map = {}
        result = check_categories(settings)

        cat_check = next(c for c in result.checks if c.name == "categories_loaded")
        assert cat_check.passed is False

    def test_invalid_category_id_fails(self):
        """Non-integer category ID should fail."""
        settings = cast(Any, build_settings())
        settings.categories.genre_map = {"fantasy": "invalid"}  # type: ignore[dict-item]
        result = check_categories(settings)

        id_check = next(c for c in result.checks if c.name == "category_ids_valid")
        assert id_check.passed is False


# =============================================================================
# run_all_checks Tests
# =============================================================================


class TestRunAllChecks:
    """Tests for run_all_checks function."""

    @patch("shelfr.validation._check_docker_running")
    @patch("shelfr.validation._check_qbittorrent")
    @patch("shelfr.validation._check_audnex_api")
    def test_runs_all_check_categories(
        self,
        mock_audnex,
        mock_qb,
        mock_docker,
        tmp_path,
    ):
        """run_all_checks should include checks from all categories."""
        mock_docker.return_value = False
        mock_qb.return_value = (False, "Connection refused")
        mock_audnex.return_value = False

        # Create directories
        library = tmp_path / "library"
        library.mkdir()
        seed = tmp_path / "seed"
        seed.mkdir()
        torrents = tmp_path / "torrents"
        torrents.mkdir()
        state_dir = tmp_path / "data"
        state_dir.mkdir()

        settings = cast(Any, build_settings())
        settings.paths = MockPathsConfig(
            library_root=library,
            seed_root=seed,
            torrent_output=torrents,
            state_file=state_dir / "state.json",
        )

        result = run_all_checks(settings)

        # Should have checks from all categories
        categories_found = {c.category for c in result.checks}
        assert CheckCategory.CONFIG in categories_found
        assert CheckCategory.PATHS in categories_found
        assert CheckCategory.SERVICES in categories_found
        assert CheckCategory.CATEGORIES in categories_found


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestDockerHelpers:
    """Tests for Docker helper functions."""

    @patch("subprocess.run")
    def test_check_docker_running_success(self, mock_run):
        """Docker running should return True."""
        mock_run.return_value = MagicMock(returncode=0)
        assert _check_docker_running("/usr/bin/docker") is True

    @patch("subprocess.run")
    def test_check_docker_running_failure(self, mock_run):
        """Docker not running should return False."""
        mock_run.return_value = MagicMock(returncode=1)
        assert _check_docker_running("/usr/bin/docker") is False

    @patch("subprocess.run")
    def test_check_docker_running_timeout(self, mock_run):
        """Docker command timeout should return False."""
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker info", timeout=10)
        assert _check_docker_running("/usr/bin/docker") is False

    @patch("subprocess.run")
    def test_check_docker_image_exists(self, mock_run):
        """Existing image should return True."""
        mock_run.return_value = MagicMock(returncode=0)
        assert _check_docker_image("/usr/bin/docker", "test:latest") is True

    @patch("subprocess.run")
    def test_check_docker_image_missing(self, mock_run):
        """Missing image should return False."""
        mock_run.return_value = MagicMock(returncode=1)
        assert _check_docker_image("/usr/bin/docker", "test:latest") is False

    @patch("subprocess.run")
    def test_check_docker_container_exists(self, mock_run):
        """Existing container should return True."""
        mock_run.return_value = MagicMock(returncode=0)
        assert _check_docker_container("/usr/bin/docker", "mycontainer") is True


class TestQBittorrentHelper:
    """Tests for qBittorrent helper function."""

    def test_missing_host_fails(self):
        """Missing host should fail."""
        settings = build_settings()
        settings.qbittorrent.host = ""

        success, message = _check_qbittorrent(settings)
        assert success is False
        assert "not configured" in message

    @patch("httpx.get")
    def test_connection_success(self, mock_get):
        """Successful connection should return True."""
        mock_get.return_value = MagicMock(status_code=200, text="4.5.0")

        settings = build_settings()
        success, message = _check_qbittorrent(settings)

        assert success is True
        assert "Connected" in message

    @patch("httpx.get")
    def test_connection_refused(self, mock_get):
        """Connection refused should return False."""
        import httpx

        mock_get.side_effect = httpx.ConnectError("Connection refused")

        settings = build_settings()
        success, message = _check_qbittorrent(settings)

        assert success is False
        assert "refused" in message.lower()


class TestAudnexHelper:
    """Tests for Audnex API helper function."""

    @patch("httpx.head")
    def test_api_reachable(self, mock_head):
        """Reachable API should return True."""
        mock_head.return_value = MagicMock(status_code=200)
        assert _check_audnex_api("https://api.audnex.us", 30) is True

    @patch("httpx.head")
    def test_api_404_still_reachable(self, mock_head):
        """404 response should still count as reachable."""
        mock_head.return_value = MagicMock(status_code=404)
        assert _check_audnex_api("https://api.audnex.us", 30) is True

    @patch("httpx.head")
    def test_api_500_not_reachable(self, mock_head):
        """500 response should count as not reachable."""
        mock_head.return_value = MagicMock(status_code=500)
        assert _check_audnex_api("https://api.audnex.us", 30) is False

    @patch("httpx.head")
    def test_api_connection_error(self, mock_head):
        """Connection error should return False."""
        import httpx

        mock_head.side_effect = httpx.ConnectError("Connection refused")
        assert _check_audnex_api("https://api.audnex.us", 30) is False


# =============================================================================
# Runtime Validation Tests (Phase 3)
# =============================================================================


class TestDiscoveryValidation:
    """Tests for DiscoveryValidation class."""

    def test_valid_asin_passes(self, tmp_path):
        """Valid ASIN format should pass."""
        from shelfr.models import AudiobookRelease
        from shelfr.validation import DiscoveryValidation

        # Create a mock M4B file
        m4b_file = tmp_path / "test.m4b"
        m4b_file.write_bytes(b"fake m4b content")

        release = AudiobookRelease(
            asin="B09GHD1R2R",
            title="Test Book",
            source_dir=tmp_path,
            main_m4b=m4b_file,
        )

        validator = DiscoveryValidation()
        result = validator.validate(release)

        asin_check = next(c for c in result.checks if c.name == "asin_format")
        assert asin_check.passed is True

    def test_invalid_asin_fails(self, tmp_path):
        """Invalid ASIN format should fail."""
        from shelfr.models import AudiobookRelease
        from shelfr.validation import DiscoveryValidation

        m4b_file = tmp_path / "test.m4b"
        m4b_file.write_bytes(b"fake m4b content")

        release = AudiobookRelease(
            asin="INVALID",
            title="Test Book",
            source_dir=tmp_path,
            main_m4b=m4b_file,
        )

        validator = DiscoveryValidation()
        result = validator.validate(release)

        asin_check = next(c for c in result.checks if c.name == "asin_format")
        assert asin_check.passed is False

    def test_missing_asin_fails(self, tmp_path):
        """Missing ASIN should fail."""
        from shelfr.models import AudiobookRelease
        from shelfr.validation import DiscoveryValidation

        m4b_file = tmp_path / "test.m4b"
        m4b_file.write_bytes(b"fake m4b content")

        release = AudiobookRelease(
            title="Test Book",
            source_dir=tmp_path,
            main_m4b=m4b_file,
        )

        validator = DiscoveryValidation()
        result = validator.validate(release)

        asin_check = next(c for c in result.checks if c.name == "asin_format")
        assert asin_check.passed is False

    def test_m4b_exists_passes(self, tmp_path):
        """Existing M4B file should pass."""
        from shelfr.models import AudiobookRelease
        from shelfr.validation import DiscoveryValidation

        m4b_file = tmp_path / "test.m4b"
        m4b_file.write_bytes(b"fake m4b content")

        release = AudiobookRelease(
            asin="B09GHD1R2R",
            main_m4b=m4b_file,
            source_dir=tmp_path,
        )

        validator = DiscoveryValidation()
        result = validator.validate(release)

        m4b_check = next(c for c in result.checks if c.name == "m4b_exists")
        assert m4b_check.passed is True

    def test_missing_m4b_fails(self, tmp_path):
        """Missing M4B file should fail."""
        from shelfr.models import AudiobookRelease
        from shelfr.validation import DiscoveryValidation

        release = AudiobookRelease(
            asin="B09GHD1R2R",
            source_dir=tmp_path,
        )

        validator = DiscoveryValidation()
        result = validator.validate(release)

        m4b_check = next(c for c in result.checks if c.name == "m4b_exists")
        assert m4b_check.passed is False

    def test_cover_exists_passes(self, tmp_path):
        """Existing cover should pass."""
        from shelfr.models import AudiobookRelease
        from shelfr.validation import DiscoveryValidation

        m4b_file = tmp_path / "test.m4b"
        m4b_file.write_bytes(b"fake m4b content")

        cover_file = tmp_path / "cover.jpg"
        cover_file.write_bytes(b"fake cover")

        release = AudiobookRelease(
            asin="B09GHD1R2R",
            source_dir=tmp_path,
            main_m4b=m4b_file,
            files=[m4b_file, cover_file],
        )

        validator = DiscoveryValidation()
        result = validator.validate(release)

        cover_check = next(c for c in result.checks if c.name == "cover_exists")
        assert cover_check.passed is True

    def test_duplicate_detection(self, tmp_path):
        """Already processed release should be flagged."""
        from shelfr.models import AudiobookRelease
        from shelfr.validation import DiscoveryValidation

        m4b_file = tmp_path / "test.m4b"
        m4b_file.write_bytes(b"fake m4b content")

        release = AudiobookRelease(
            asin="B09GHD1R2R",
            main_m4b=m4b_file,
            source_dir=tmp_path,
        )

        # Mark as already processed
        validator = DiscoveryValidation(processed_identifiers={"B09GHD1R2R"})
        result = validator.validate(release)

        dup_check = next(c for c in result.checks if c.name == "not_duplicate")
        assert dup_check.passed is False

    def test_title_cleaning_ok(self, tmp_path):
        """Normal title cleaning should pass."""
        from shelfr.models import AudiobookRelease
        from shelfr.validation import DiscoveryValidation

        m4b_file = tmp_path / "test.m4b"
        m4b_file.write_bytes(b"fake m4b content")

        release = AudiobookRelease(
            asin="B09GHD1R2R",
            title="Sword Art Online: Alicization",  # Similar after cleaning
            source_dir=tmp_path,
            main_m4b=m4b_file,
        )

        validator = DiscoveryValidation()
        result = validator.validate(release)

        title_check = next(c for c in result.checks if c.name == "title_cleaning")
        assert title_check.passed is True
        assert title_check.severity == "info"

    def test_aggressive_title_cleaning_warns(self, tmp_path, monkeypatch):
        """Aggressive title cleaning should warn."""
        from shelfr.models import AudiobookRelease
        from shelfr.validation import DiscoveryValidation

        m4b_file = tmp_path / "test.m4b"
        m4b_file.write_bytes(b"fake m4b content")

        # Title with lots of stuff that gets removed
        release = AudiobookRelease(
            asin="B09GHD1R2R",
            title="This is a Very Long Title: Unabridged Audiobook Edition - Publisher Name (2023)",
            source_dir=tmp_path,
            main_m4b=m4b_file,
        )

        # Mock filter_title to return something very different (aggressive cleaning)
        def mock_filter_title(title):
            return "Title"  # Very short - triggers low similarity

        monkeypatch.setattr("shelfr.utils.naming.filter_title", mock_filter_title)

        validator = DiscoveryValidation()
        result = validator.validate(release)

        title_check = next(c for c in result.checks if c.name == "title_cleaning")
        # Should pass but with warning severity if similarity is low
        assert title_check.passed is True
        assert title_check.severity == "warning"


class TestMetadataValidation:
    """Tests for MetadataValidation class."""

    def test_required_fields_present_passes(self):
        """All required fields present should pass."""
        from shelfr.models import AudiobookRelease
        from shelfr.validation import MetadataValidation

        release = AudiobookRelease(asin="B09GHD1R2R", title="Test Book")
        audnex_data = {
            "title": "Test Book",
            "asin": "B09GHD1R2R",
            "authors": [{"name": "Test Author"}],
            "narrators": [{"name": "Test Narrator"}],
        }

        validator = MetadataValidation()
        result = validator.validate(release, audnex_data=audnex_data)

        fields_check = next(c for c in result.checks if c.name == "required_fields")
        assert fields_check.passed is True

    def test_missing_required_fields_fails(self):
        """Missing required fields should fail."""
        from shelfr.models import AudiobookRelease
        from shelfr.validation import MetadataValidation

        release = AudiobookRelease(asin="B09GHD1R2R", title="Test Book")
        audnex_data = {
            "authors": [{"name": "Test Author"}],
            # Missing title and asin
        }

        validator = MetadataValidation()
        result = validator.validate(release, audnex_data=audnex_data)

        fields_check = next(c for c in result.checks if c.name == "required_fields")
        assert fields_check.passed is False

    def test_authors_present_passes(self):
        """Authors present should pass."""
        from shelfr.models import AudiobookRelease
        from shelfr.validation import MetadataValidation

        release = AudiobookRelease(asin="B09GHD1R2R")
        audnex_data = {
            "title": "Test",
            "asin": "B09GHD1R2R",
            "authors": [{"name": "Author 1"}, {"name": "Author 2"}],
        }

        validator = MetadataValidation()
        result = validator.validate(release, audnex_data=audnex_data)

        authors_check = next(c for c in result.checks if c.name == "authors_present")
        assert authors_check.passed is True

    def test_narrators_present_passes(self):
        """Narrators present should pass."""
        from shelfr.models import AudiobookRelease
        from shelfr.validation import MetadataValidation

        release = AudiobookRelease(asin="B09GHD1R2R")
        audnex_data = {
            "title": "Test",
            "asin": "B09GHD1R2R",
            "narrators": [{"name": "Narrator 1"}],
        }

        validator = MetadataValidation()
        result = validator.validate(release, audnex_data=audnex_data)

        narrators_check = next(c for c in result.checks if c.name == "narrators_present")
        assert narrators_check.passed is True

    def test_runtime_match_within_tolerance(self):
        """Runtime within tolerance should pass."""
        from shelfr.models import AudiobookRelease
        from shelfr.validation import MetadataValidation

        release = AudiobookRelease(asin="B09GHD1R2R")
        audnex_data = {"title": "Test", "asin": "B09", "runtimeLengthSec": 10000}
        mediainfo_data = {
            "media": {"track": [{"@type": "General", "Duration": 10050}]}  # 0.5% diff
        }

        validator = MetadataValidation(runtime_tolerance=0.05)
        result = validator.validate(release, audnex_data=audnex_data, mediainfo_data=mediainfo_data)

        runtime_check = next(c for c in result.checks if c.name == "runtime_match")
        assert runtime_check.passed is True

    def test_runtime_mismatch_outside_tolerance(self):
        """Runtime outside tolerance should warn."""
        from shelfr.models import AudiobookRelease
        from shelfr.validation import MetadataValidation

        release = AudiobookRelease(asin="B09GHD1R2R")
        audnex_data = {"title": "Test", "asin": "B09", "runtimeLengthSec": 10000}
        mediainfo_data = {
            "media": {"track": [{"@type": "General", "Duration": 12000}]}  # 20% diff
        }

        validator = MetadataValidation(runtime_tolerance=0.05)
        result = validator.validate(release, audnex_data=audnex_data, mediainfo_data=mediainfo_data)

        runtime_check = next(c for c in result.checks if c.name == "runtime_match")
        assert runtime_check.passed is False


class TestPreUploadValidation:
    """Tests for PreUploadValidation class."""

    def test_torrent_valid_passes(self, tmp_path):
        """Valid torrent file should pass."""
        from shelfr.models import AudiobookRelease
        from shelfr.validation import PreUploadValidation

        torrent_file = tmp_path / "test.torrent"
        torrent_file.write_bytes(b"d8:announce...")

        release = AudiobookRelease(
            asin="B09GHD1R2R",
            torrent_path=torrent_file,
            staging_dir=tmp_path,
        )

        settings = build_settings()
        settings.paths.seed_root = tmp_path

        validator = PreUploadValidation(settings)
        result = validator.validate(release)

        torrent_check = next(c for c in result.checks if c.name == "torrent_valid")
        assert torrent_check.passed is True

    def test_missing_torrent_fails(self, tmp_path):
        """Missing torrent file should fail."""
        from shelfr.models import AudiobookRelease
        from shelfr.validation import PreUploadValidation

        release = AudiobookRelease(
            asin="B09GHD1R2R",
            staging_dir=tmp_path,
        )

        settings = build_settings()
        settings.paths.seed_root = tmp_path

        validator = PreUploadValidation(settings)
        result = validator.validate(release)

        torrent_check = next(c for c in result.checks if c.name == "torrent_valid")
        assert torrent_check.passed is False

    def test_filename_length_ok(self, tmp_path):
        """Filename under 225 chars should pass."""
        from shelfr.models import AudiobookRelease
        from shelfr.validation import PreUploadValidation

        staging = tmp_path / ("A" * 100)  # 100 chars - OK
        staging.mkdir()

        release = AudiobookRelease(
            asin="B09GHD1R2R",
            staging_dir=staging,
        )

        settings = build_settings()
        settings.paths.seed_root = tmp_path

        validator = PreUploadValidation(settings)
        result = validator.validate(release)

        length_check = next(c for c in result.checks if c.name == "filename_length")
        assert length_check.passed is True

    def test_filename_too_long_fails(self, tmp_path):
        """Filename over 225 chars should fail."""
        from shelfr.models import AudiobookRelease
        from shelfr.validation import PreUploadValidation

        staging = tmp_path / ("A" * 230)  # 230 chars - Too long
        staging.mkdir()

        release = AudiobookRelease(
            asin="B09GHD1R2R",
            staging_dir=staging,
        )

        settings = build_settings()
        settings.paths.seed_root = tmp_path

        validator = PreUploadValidation(settings)
        result = validator.validate(release)

        length_check = next(c for c in result.checks if c.name == "filename_length")
        assert length_check.passed is False


class TestChapterIntegrityChecker:
    """Tests for ChapterIntegrityChecker class."""

    def test_matching_chapter_counts(self):
        """Matching chapter counts should pass."""
        from shelfr.validation import ChapterIntegrityChecker

        embedded = [{"title": "Ch 1"}, {"title": "Ch 2"}, {"title": "Ch 3"}]
        api = [{"title": "Ch 1"}, {"title": "Ch 2"}, {"title": "Ch 3"}]

        checker = ChapterIntegrityChecker()
        result = checker.compare_chapters(embedded, api)

        assert result.count_match is True
        assert result.embedded_count == 3
        assert result.api_count == 3

    def test_mismatched_chapter_counts(self):
        """Mismatched chapter counts should fail - detects Libation bug."""
        from shelfr.validation import ChapterIntegrityChecker

        embedded = [{"title": "Ch 1"}, {"title": "Ch 2"}]  # 2 chapters
        api = [{"title": "Ch 1"}, {"title": "Ch 2"}, {"title": "Ch 3"}]  # 3 chapters

        checker = ChapterIntegrityChecker()
        result = checker.compare_chapters(embedded, api)

        assert result.count_match is False
        assert result.embedded_count == 2
        assert result.api_count == 3

    def test_chapter_validation_integration(self):
        """Full chapter validation flow."""
        from shelfr.models import AudiobookRelease
        from shelfr.validation import ChapterIntegrityChecker

        release = AudiobookRelease(
            asin="B09GHD1R2R",
            mediainfo_data={
                "media": {
                    "track": [
                        {
                            "@type": "Menu",
                            "extra": {
                                "_00_00_00_000": "Chapter 1",
                                "_00_10_00_000": "Chapter 2",
                            },
                        }
                    ]
                }
            },
        )

        audnex_chapters = {
            "chapters": [
                {"title": "Chapter 1", "lengthMs": 600000},
                {"title": "Chapter 2", "lengthMs": 600000},
                {"title": "Chapter 3", "lengthMs": 600000},  # Extra chapter - mismatch!
            ]
        }

        checker = ChapterIntegrityChecker()
        result = checker.validate(release, audnex_chapters)

        # Should have chapter count mismatch warning
        count_check = next((c for c in result.checks if c.name == "chapter_count"), None)
        assert count_check is not None
        assert count_check.passed is False
        assert "MISMATCH" in count_check.message


class TestSafetyUtilities:
    """Tests for Phase 5 safety utilities."""

    def test_sanitize_path_component_removes_traversal(self):
        """Path traversal patterns should be removed."""
        from shelfr.validation import sanitize_path_component

        assert ".." not in sanitize_path_component("../evil")
        assert ".." not in sanitize_path_component("foo/../bar")
        assert "/" not in sanitize_path_component("foo/bar")
        assert "\\" not in sanitize_path_component("foo\\bar")

    def test_sanitize_path_component_removes_null_bytes(self):
        """Null bytes should be removed."""
        from shelfr.validation import sanitize_path_component

        result = sanitize_path_component("test\x00evil")
        assert "\x00" not in result

    def test_is_safe_path_within_root(self, tmp_path):
        """Path within root should be safe."""
        from shelfr.validation import is_safe_path

        subdir = tmp_path / "subdir"
        subdir.mkdir()

        assert is_safe_path(subdir, tmp_path) is True

    def test_is_safe_path_outside_root(self, tmp_path):
        """Path outside root should not be safe."""
        from shelfr.validation import is_safe_path

        outside = tmp_path.parent / "other"
        assert is_safe_path(outside, tmp_path) is False

    def test_compute_file_checksum(self, tmp_path):
        """File checksum should be computed correctly."""
        from shelfr.validation import compute_file_checksum

        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")

        checksum = compute_file_checksum(test_file, "md5")
        assert checksum is not None
        assert len(checksum) == 32  # MD5 hex length

    def test_compute_file_checksum_missing_file(self, tmp_path):
        """Missing file should return None."""
        from shelfr.validation import compute_file_checksum

        missing = tmp_path / "missing.txt"
        assert compute_file_checksum(missing) is None


class TestValidationReport:
    """Tests for ValidationReport class."""

    def test_report_all_passed(self):
        """Report with all passing results should indicate all_passed."""
        from shelfr.validation import ValidationReport, ValidationResult

        result = ValidationResult()
        result.add(ValidationCheck(name="test1", passed=True, message="OK"))
        result.add(ValidationCheck(name="test2", passed=True, message="OK"))

        report = ValidationReport(
            asin="B09GHD1R2R",
            title="Test Book",
            validated_at="2025-12-02T00:00:00",
            discovery_result=result,
        )

        assert report.all_passed is True
        assert report.total_errors == 0
        assert report.total_warnings == 0

    def test_report_with_failures(self):
        """Report with failures should indicate not all_passed."""
        from shelfr.validation import ValidationReport, ValidationResult

        result = ValidationResult()
        result.add(ValidationCheck(name="test1", passed=True, message="OK"))
        result.add(ValidationCheck(name="test2", passed=False, message="Failed", severity="error"))

        report = ValidationReport(
            asin="B09GHD1R2R",
            title="Test Book",
            validated_at="2025-12-02T00:00:00",
            discovery_result=result,
        )

        assert report.all_passed is False
        assert report.total_errors == 1

    def test_report_to_dict(self):
        """Report should serialize to dictionary."""
        from shelfr.validation import ValidationReport, ValidationResult

        result = ValidationResult()
        result.add(ValidationCheck(name="test1", passed=True, message="OK"))

        report = ValidationReport(
            asin="B09GHD1R2R",
            title="Test Book",
            validated_at="2025-12-02T00:00:00",
            discovery_result=result,
        )

        data = report.to_dict()
        assert data["asin"] == "B09GHD1R2R"
        assert data["title"] == "Test Book"
        assert data["all_passed"] is True
        assert "discovery" in data
