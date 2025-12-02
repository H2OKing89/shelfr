"""Tests for the validation module."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock, patch

from mamfast.validation import (
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


# =============================================================================
# ValidationCheck Tests
# =============================================================================


class TestValidationCheck:
    """Tests for ValidationCheck dataclass."""

    def test_passed_check_icon(self):
        """Passed checks show checkmark."""
        check = ValidationCheck(name="test", passed=True, message="OK")
        assert check.icon == "✅"

    def test_failed_error_icon(self):
        """Failed error checks show X."""
        check = ValidationCheck(name="test", passed=False, message="Failed", severity="error")
        assert check.icon == "❌"

    def test_failed_warning_icon(self):
        """Failed warning checks show warning sign."""
        check = ValidationCheck(name="test", passed=False, message="Warn", severity="warning")
        assert check.icon == "⚠️"

    def test_failed_info_icon(self):
        """Failed info checks show info sign."""
        check = ValidationCheck(name="test", passed=False, message="Info", severity="info")
        assert check.icon == "ℹ️"

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
        settings = MockSettings()
        result = check_config(settings)

        assert result.passed is True
        assert result.error_count == 0

    def test_missing_container_fails(self):
        """Missing libation_container should fail."""
        settings = MockSettings(libation_container="")
        result = check_config(settings)

        failed = [c for c in result.checks if c.name == "libation_container"]
        assert len(failed) == 1
        assert failed[0].passed is False

    def test_invalid_uid_fails(self):
        """Negative UID should fail."""
        settings = MockSettings(target_uid=-1)
        result = check_config(settings)

        failed = [c for c in result.checks if c.name == "target_uid"]
        assert len(failed) == 1
        assert failed[0].passed is False

    def test_missing_qb_host_fails(self):
        """Missing qBittorrent host should fail."""
        settings = MockSettings()
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

        settings = MockSettings()
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
        settings = MockSettings()
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

        settings = MockSettings()
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

    @patch("mamfast.validation._check_docker_running")
    @patch("mamfast.validation._check_docker_image")
    @patch("mamfast.validation._check_docker_container")
    @patch("mamfast.validation._check_qbittorrent")
    @patch("mamfast.validation._check_audnex_api")
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

        settings = MockSettings()
        result = check_services(settings)

        assert result.passed is True
        assert result.error_count == 0

    @patch("mamfast.validation._check_docker_running")
    def test_docker_not_running_fails(self, mock_docker):
        """Docker not running should fail."""
        mock_docker.return_value = False

        settings = MockSettings()
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
        settings = MockSettings()
        result = check_categories(settings)

        assert result.passed is True

    def test_empty_categories_fail(self):
        """Empty genre_map should fail."""
        settings = MockSettings()
        settings.categories.genre_map = {}
        result = check_categories(settings)

        cat_check = next(c for c in result.checks if c.name == "categories_loaded")
        assert cat_check.passed is False

    def test_invalid_category_id_fails(self):
        """Non-integer category ID should fail."""
        settings = MockSettings()
        settings.categories.genre_map = {"fantasy": "invalid"}  # type: ignore[dict-item]
        result = check_categories(settings)

        id_check = next(c for c in result.checks if c.name == "category_ids_valid")
        assert id_check.passed is False


# =============================================================================
# run_all_checks Tests
# =============================================================================


class TestRunAllChecks:
    """Tests for run_all_checks function."""

    @patch("mamfast.validation._check_docker_running")
    @patch("mamfast.validation._check_qbittorrent")
    @patch("mamfast.validation._check_audnex_api")
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

        settings = MockSettings()
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
        settings = MockSettings()
        settings.qbittorrent.host = ""

        success, message = _check_qbittorrent(settings)
        assert success is False
        assert "not configured" in message

    @patch("requests.get")
    def test_connection_success(self, mock_get):
        """Successful connection should return True."""
        mock_get.return_value = MagicMock(status_code=200, text="4.5.0")

        settings = MockSettings()
        success, message = _check_qbittorrent(settings)

        assert success is True
        assert "Connected" in message

    @patch("requests.get")
    def test_connection_refused(self, mock_get):
        """Connection refused should return False."""
        import requests

        mock_get.side_effect = requests.exceptions.ConnectionError()

        settings = MockSettings()
        success, message = _check_qbittorrent(settings)

        assert success is False
        assert "refused" in message.lower()


class TestAudnexHelper:
    """Tests for Audnex API helper function."""

    @patch("requests.head")
    def test_api_reachable(self, mock_head):
        """Reachable API should return True."""
        mock_head.return_value = MagicMock(status_code=200)
        assert _check_audnex_api("https://api.audnex.us", 30) is True

    @patch("requests.head")
    def test_api_404_still_reachable(self, mock_head):
        """404 response should still count as reachable."""
        mock_head.return_value = MagicMock(status_code=404)
        assert _check_audnex_api("https://api.audnex.us", 30) is True

    @patch("requests.head")
    def test_api_500_not_reachable(self, mock_head):
        """500 response should count as not reachable."""
        mock_head.return_value = MagicMock(status_code=500)
        assert _check_audnex_api("https://api.audnex.us", 30) is False

    @patch("requests.head")
    def test_api_connection_error(self, mock_head):
        """Connection error should return False."""
        import requests

        mock_head.side_effect = requests.exceptions.ConnectionError()
        assert _check_audnex_api("https://api.audnex.us", 30) is False
