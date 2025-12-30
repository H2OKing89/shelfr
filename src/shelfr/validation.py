"""Validation framework for MAMFast health checks and runtime validation."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import httpx

from shelfr.utils.fuzzy import analyze_change

if TYPE_CHECKING:
    from shelfr.config import Settings
    from shelfr.models import AudiobookRelease

logger = logging.getLogger(__name__)

# ASIN validation pattern - 10 chars: B + 9 alphanumeric or 10 digits (ISBN-10)
ASIN_VALID_PATTERN = re.compile(r"^(?:B[0-9A-Z]{9}|[0-9]{10})$")

# Maximum filename length for MAM
MAM_MAX_FILENAME_LENGTH = 225

# Minimum disk space required for staging (in bytes) - 1GB default
MIN_DISK_SPACE_BYTES = 1 * 1024 * 1024 * 1024


class CheckCategory(Enum):
    """Categories of health checks."""

    CONFIG = "Configuration"
    PATHS = "Paths"
    SERVICES = "Services"
    CATEGORIES = "Categories"
    FILESYSTEM = "Filesystem"


@dataclass
class ValidationCheck:
    """Result of a single validation check."""

    name: str
    passed: bool
    message: str
    severity: Literal["error", "warning", "info"] = "error"
    category: CheckCategory = CheckCategory.CONFIG

    @property
    def icon(self) -> str:
        """Return icon based on pass/fail status."""
        if self.passed:
            return "✅"
        if self.severity == "error":
            return "❌"
        if self.severity == "warning":
            return "⚠️"
        return "ℹ️"


@dataclass
class ValidationResult:
    """Collection of validation checks with summary methods."""

    checks: list[ValidationCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """True if all error-severity checks passed."""
        return all(c.passed for c in self.checks if c.severity == "error")

    @property
    def error_count(self) -> int:
        """Count of failed error-severity checks."""
        return sum(1 for c in self.checks if not c.passed and c.severity == "error")

    @property
    def warning_count(self) -> int:
        """Count of failed warning-severity checks."""
        return sum(1 for c in self.checks if not c.passed and c.severity == "warning")

    @property
    def passed_count(self) -> int:
        """Count of passed checks."""
        return sum(1 for c in self.checks if c.passed)

    def add(self, check: ValidationCheck) -> None:
        """Add a check to the result."""
        self.checks.append(check)

    def by_category(self, category: CheckCategory) -> list[ValidationCheck]:
        """Get checks filtered by category."""
        return [c for c in self.checks if c.category == category]

    def merge(self, other: ValidationResult) -> None:
        """Merge another ValidationResult into this one."""
        self.checks.extend(other.checks)


# =============================================================================
# Health Check Functions
# =============================================================================


def check_config(settings: Settings) -> ValidationResult:
    """Run configuration health checks."""
    result = ValidationResult()

    # Check that required settings have values
    required_checks = [
        ("libation_container", settings.libation_container, "Libation container name"),
        ("docker_bin", settings.docker_bin, "Docker binary path"),
    ]

    for field_name, value, description in required_checks:
        has_value = bool(value and str(value).strip())
        result.add(
            ValidationCheck(
                name=field_name,
                passed=has_value,
                message=f"{description}: {value}" if has_value else f"{description} not set",
                category=CheckCategory.CONFIG,
            )
        )

    # Check UID/GID are valid
    result.add(
        ValidationCheck(
            name="target_uid",
            passed=settings.target_uid >= 0,
            message=f"Target UID: {settings.target_uid}",
            category=CheckCategory.CONFIG,
        )
    )
    result.add(
        ValidationCheck(
            name="target_gid",
            passed=settings.target_gid >= 0,
            message=f"Target GID: {settings.target_gid}",
            category=CheckCategory.CONFIG,
        )
    )

    # Check qBittorrent settings
    result.add(
        ValidationCheck(
            name="qbittorrent_host",
            passed=bool(settings.qbittorrent.host),
            message=f"qBittorrent host: {settings.qbittorrent.host}"
            if settings.qbittorrent.host
            else "qBittorrent host not configured",
            category=CheckCategory.CONFIG,
        )
    )

    return result


def check_paths(settings: Settings) -> ValidationResult:
    """Run path health checks."""
    result = ValidationResult()

    # Check library_root exists and is readable
    library_root = settings.paths.library_root
    library_exists = library_root.exists() and library_root.is_dir()
    result.add(
        ValidationCheck(
            name="library_root",
            passed=library_exists,
            message=f"library_root: {library_root} (exists, readable)"
            if library_exists
            else f"library_root: {library_root} (not found)",
            category=CheckCategory.PATHS,
        )
    )

    # Check seed_root exists and is writable
    seed_root = settings.paths.seed_root
    seed_exists = seed_root.exists() and seed_root.is_dir()
    seed_writable = seed_exists and os.access(seed_root, os.W_OK)
    result.add(
        ValidationCheck(
            name="seed_root",
            passed=seed_writable,
            message=f"seed_root: {seed_root} (exists, writable)"
            if seed_writable
            else f"seed_root: {seed_root} ({'not writable' if seed_exists else 'not found'})",
            category=CheckCategory.PATHS,
        )
    )

    # Check torrent_output exists and is writable
    torrent_output = settings.paths.torrent_output
    torrent_exists = torrent_output.exists() and torrent_output.is_dir()
    torrent_writable = torrent_exists and os.access(torrent_output, os.W_OK)
    if torrent_writable:
        torrent_msg = f"torrent_output: {torrent_output} (exists, writable)"
    else:
        status = "not writable" if torrent_exists else "not found"
        torrent_msg = f"torrent_output: {torrent_output} ({status})"
    result.add(
        ValidationCheck(
            name="torrent_output",
            passed=torrent_writable,
            message=torrent_msg,
            category=CheckCategory.PATHS,
        )
    )

    # Check same filesystem for hardlinks (library_root and seed_root)
    if library_exists and seed_exists:
        try:
            library_stat = os.stat(library_root)
            seed_stat = os.stat(seed_root)
            same_fs = library_stat.st_dev == seed_stat.st_dev
            result.add(
                ValidationCheck(
                    name="same_filesystem",
                    passed=same_fs,
                    message="library_root ↔ seed_root: same filesystem (hardlinks supported)"
                    if same_fs
                    else "library_root ↔ seed_root: different filesystems (hardlinks will fail!)",
                    category=CheckCategory.PATHS,
                )
            )
        except OSError as e:
            result.add(
                ValidationCheck(
                    name="same_filesystem",
                    passed=False,
                    message=f"Could not check filesystem: {e}",
                    category=CheckCategory.PATHS,
                )
            )

    # Check state file directory is writable
    state_dir = settings.paths.state_file.parent
    state_dir_exists = state_dir.exists()
    state_dir_writable = state_dir_exists and os.access(state_dir, os.W_OK)
    if state_dir_writable:
        state_msg = f"state_file dir: {state_dir} (writable)"
    else:
        status = "not writable" if state_dir_exists else "not found"
        state_msg = f"state_file dir: {state_dir} ({status})"
    result.add(
        ValidationCheck(
            name="state_file_dir",
            passed=state_dir_writable,
            message=state_msg,
            category=CheckCategory.PATHS,
        )
    )

    return result


def check_services(settings: Settings) -> ValidationResult:
    """Run service connectivity health checks."""
    result = ValidationResult()

    # Check Docker daemon
    docker_running = _check_docker_running(settings.docker_bin)
    result.add(
        ValidationCheck(
            name="docker_daemon",
            passed=docker_running,
            message="Docker: Running"
            if docker_running
            else "Docker: Not running or not accessible",
            category=CheckCategory.SERVICES,
        )
    )

    # Check mkbrr image available
    if docker_running:
        mkbrr_available = _check_docker_image(settings.docker_bin, settings.mkbrr.image)
        result.add(
            ValidationCheck(
                name="mkbrr_image",
                passed=mkbrr_available,
                message=f"mkbrr: Image available ({settings.mkbrr.image})"
                if mkbrr_available
                else f"mkbrr: Image not found ({settings.mkbrr.image})",
                severity="warning" if not mkbrr_available else "error",
                category=CheckCategory.SERVICES,
            )
        )

        # Check Libation container exists
        libation_exists = _check_docker_container(settings.docker_bin, settings.libation_container)
        result.add(
            ValidationCheck(
                name="libation_container",
                passed=libation_exists,
                message=f"Libation: Container exists ({settings.libation_container})"
                if libation_exists
                else f"Libation: Container not found ({settings.libation_container})",
                category=CheckCategory.SERVICES,
            )
        )

    # Check qBittorrent API
    qb_connected, qb_message = _check_qbittorrent(settings)
    result.add(
        ValidationCheck(
            name="qbittorrent_api",
            passed=qb_connected,
            message=qb_message,
            category=CheckCategory.SERVICES,
        )
    )

    # Check Audnex API
    audnex_reachable = _check_audnex_api(settings.audnex.base_url, settings.audnex.timeout_seconds)
    result.add(
        ValidationCheck(
            name="audnex_api",
            passed=audnex_reachable,
            message=f"Audnex API: Reachable ({settings.audnex.base_url})"
            if audnex_reachable
            else f"Audnex API: Not reachable ({settings.audnex.base_url})",
            category=CheckCategory.SERVICES,
        )
    )

    return result


def check_categories(settings: Settings) -> ValidationResult:
    """Check categories.json configuration."""
    result = ValidationResult()

    genre_count = len(settings.categories.genre_map)
    has_genres = genre_count > 0

    result.add(
        ValidationCheck(
            name="categories_loaded",
            passed=has_genres,
            message=f"categories.json: Loaded ({genre_count} genre mappings)"
            if has_genres
            else "categories.json: No genre mappings loaded",
            category=CheckCategory.CATEGORIES,
        )
    )

    # Check that all category IDs are integers
    if has_genres:
        invalid_ids = [
            genre
            for genre, cat_id in settings.categories.genre_map.items()
            if not isinstance(cat_id, int)
        ]
        result.add(
            ValidationCheck(
                name="category_ids_valid",
                passed=len(invalid_ids) == 0,
                message="All category IDs are valid integers"
                if not invalid_ids
                else f"Invalid category IDs for: {', '.join(invalid_ids[:5])}",
                category=CheckCategory.CATEGORIES,
            )
        )

    return result


def run_all_checks(settings: Settings) -> ValidationResult:
    """Run all health checks and return combined result."""
    result = ValidationResult()
    result.merge(check_config(settings))
    result.merge(check_paths(settings))
    result.merge(check_services(settings))
    result.merge(check_categories(settings))
    return result


# =============================================================================
# Helper Functions
# =============================================================================


def _check_docker_running(docker_bin: str) -> bool:
    """Check if Docker daemon is running."""
    try:
        result = subprocess.run(
            [docker_bin, "info"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _check_docker_image(docker_bin: str, image: str) -> bool:
    """Check if a Docker image exists locally."""
    try:
        result = subprocess.run(
            [docker_bin, "image", "inspect", image],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _check_docker_container(docker_bin: str, container_name: str) -> bool:
    """Check if a Docker container exists."""
    try:
        result = subprocess.run(
            [docker_bin, "container", "inspect", container_name],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _check_qbittorrent(settings: Settings) -> tuple[bool, str]:
    """Check qBittorrent API connectivity and authentication."""
    if not settings.qbittorrent.host:
        return False, "qBittorrent: Host not configured"

    host = settings.qbittorrent.host.rstrip("/")

    try:
        # First check if API is reachable
        version_url = f"{host}/api/v2/app/version"
        response = httpx.get(version_url, timeout=5)

        if response.status_code == 200:
            version = response.text.strip()
            return True, f"qBittorrent: Connected (v{version})"

        # Try to authenticate
        if settings.qbittorrent.username and settings.qbittorrent.password:
            login_url = f"{host}/api/v2/auth/login"
            login_response = httpx.post(
                login_url,
                data={
                    "username": settings.qbittorrent.username,
                    "password": settings.qbittorrent.password,
                },
                timeout=5,
            )

            if login_response.status_code == 200 and login_response.text == "Ok.":
                # Try version again with cookies
                cookies = login_response.cookies
                version_response = httpx.get(version_url, cookies=cookies, timeout=5)
                if version_response.status_code == 200:
                    version = version_response.text.strip()
                    return True, f"qBittorrent: Connected (v{version})"

            return False, f"qBittorrent: Authentication failed at {host}"

        return False, f"qBittorrent: Requires authentication at {host}"

    except httpx.ConnectError:
        return False, f"qBittorrent: Connection refused at {host}"
    except httpx.TimeoutException:
        return False, f"qBittorrent: Connection timeout at {host}"
    except httpx.HTTPError as e:
        return False, f"qBittorrent: Error - {e}"


def _check_audnex_api(base_url: str, timeout: int) -> bool:
    """Check if Audnex API is reachable."""
    try:
        # Use a known ASIN to test the API (lightweight check)
        test_url = f"{base_url}/books/B0G4NFQDWR"
        response = httpx.head(test_url, timeout=timeout)
        # Accept any response (200, 404, etc.) as long as we got a response
        return bool(response.status_code < 500)
    except httpx.HTTPError:
        return False


# =============================================================================
# Runtime Validation Classes (Phase 3)
# =============================================================================


@dataclass
class ChapterComparisonResult:
    """Result of comparing embedded vs API chapters."""

    count_match: bool
    titles_match: bool
    durations_match: bool  # Within tolerance
    embedded_count: int
    api_count: int
    duration_diff_seconds: float = 0.0
    mismatched_titles: list[tuple[str, str]] = field(default_factory=list)


class PreflightValidation:
    """Pre-flight checks before starting the pipeline.

    Validates environment is ready for processing:
    - Disk space available
    - Directory permissions (read/write)
    - Required paths exist
    """

    def __init__(self, settings: Settings) -> None:
        """
        Initialize preflight validation.

        Args:
            settings: MAMFast settings object
        """
        self._settings = settings

    def validate(self, release_size_bytes: int = 0) -> ValidationResult:
        """
        Run all pre-flight validation checks.

        Args:
            release_size_bytes: Size of content to stage (for disk space check)

        Returns:
            ValidationResult with all check results
        """
        result = ValidationResult()
        result.add(self._check_library_root_readable())
        result.add(self._check_seed_root_writable())
        result.add(self._check_torrent_output_writable())
        result.add(self._check_disk_space(release_size_bytes))
        result.add(self._check_state_file_writable())
        return result

    def _check_library_root_readable(self) -> ValidationCheck:
        """Check library_root exists and is readable."""
        library_root = self._settings.paths.library_root

        if not library_root.exists():
            return ValidationCheck(
                name="library_root_readable",
                passed=False,
                message=f"Library root does not exist: {library_root}",
                severity="error",
                category=CheckCategory.FILESYSTEM,
            )

        if not os.access(library_root, os.R_OK):
            return ValidationCheck(
                name="library_root_readable",
                passed=False,
                message=f"Library root not readable: {library_root}",
                severity="error",
                category=CheckCategory.FILESYSTEM,
            )

        return ValidationCheck(
            name="library_root_readable",
            passed=True,
            message=f"Library root OK: {library_root}",
            severity="info",
            category=CheckCategory.FILESYSTEM,
        )

    def _check_seed_root_writable(self) -> ValidationCheck:
        """Check seed_root exists and is writable."""
        seed_root = self._settings.paths.seed_root

        if not seed_root.exists():
            # Try to create it
            try:
                seed_root.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return ValidationCheck(
                    name="seed_root_writable",
                    passed=False,
                    message=f"Cannot create seed root: {seed_root} ({e})",
                    severity="error",
                    category=CheckCategory.FILESYSTEM,
                )

        if not os.access(seed_root, os.W_OK):
            return ValidationCheck(
                name="seed_root_writable",
                passed=False,
                message=f"Seed root not writable: {seed_root}",
                severity="error",
                category=CheckCategory.FILESYSTEM,
            )

        return ValidationCheck(
            name="seed_root_writable",
            passed=True,
            message=f"Seed root OK: {seed_root}",
            severity="info",
            category=CheckCategory.FILESYSTEM,
        )

    def _check_torrent_output_writable(self) -> ValidationCheck:
        """Check torrent_output exists and is writable."""
        torrent_output = self._settings.paths.torrent_output

        if not torrent_output.exists():
            # Try to create it
            try:
                torrent_output.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return ValidationCheck(
                    name="torrent_output_writable",
                    passed=False,
                    message=f"Cannot create torrent output: {torrent_output} ({e})",
                    severity="error",
                    category=CheckCategory.FILESYSTEM,
                )

        if not os.access(torrent_output, os.W_OK):
            return ValidationCheck(
                name="torrent_output_writable",
                passed=False,
                message=f"Torrent output not writable: {torrent_output}",
                severity="error",
                category=CheckCategory.FILESYSTEM,
            )

        return ValidationCheck(
            name="torrent_output_writable",
            passed=True,
            message=f"Torrent output OK: {torrent_output}",
            severity="info",
            category=CheckCategory.FILESYSTEM,
        )

    def _check_disk_space(self, release_size_bytes: int = 0) -> ValidationCheck:
        """Check sufficient disk space for staging.

        Args:
            release_size_bytes: Size of content to stage (0 for general check)
        """
        seed_root = self._settings.paths.seed_root

        # Ensure directory exists for disk check
        if not seed_root.exists():
            return ValidationCheck(
                name="disk_space",
                passed=False,
                message=f"Seed root does not exist: {seed_root}",
                severity="error",
                category=CheckCategory.FILESYSTEM,
            )

        try:
            disk_usage = shutil.disk_usage(seed_root)
            free_bytes = disk_usage.free
            free_gb = free_bytes / (1024**3)

            # Check against release size (plus 10% buffer) or minimum threshold
            required_bytes = max(
                int(release_size_bytes * 1.1),  # 10% buffer for staging
                MIN_DISK_SPACE_BYTES,
            )
            required_gb = required_bytes / (1024**3)

            if free_bytes < required_bytes:
                return ValidationCheck(
                    name="disk_space",
                    passed=False,
                    message=(
                        f"Insufficient disk space: {free_gb:.1f}GB free, "
                        f"need {required_gb:.1f}GB"
                    ),
                    severity="error",
                    category=CheckCategory.FILESYSTEM,
                )

            return ValidationCheck(
                name="disk_space",
                passed=True,
                message=f"Disk space OK: {free_gb:.1f}GB free",
                severity="info",
                category=CheckCategory.FILESYSTEM,
            )

        except OSError as e:
            return ValidationCheck(
                name="disk_space",
                passed=False,
                message=f"Cannot check disk space: {e}",
                severity="warning",
                category=CheckCategory.FILESYSTEM,
            )

    def _check_state_file_writable(self) -> ValidationCheck:
        """Check state file directory is writable."""
        state_file = self._settings.paths.state_file
        state_dir = state_file.parent

        if not state_dir.exists():
            # Try to create it
            try:
                state_dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return ValidationCheck(
                    name="state_file_writable",
                    passed=False,
                    message=f"Cannot create state directory: {state_dir} ({e})",
                    severity="error",
                    category=CheckCategory.FILESYSTEM,
                )

        if not os.access(state_dir, os.W_OK):
            return ValidationCheck(
                name="state_file_writable",
                passed=False,
                message=f"State directory not writable: {state_dir}",
                severity="error",
                category=CheckCategory.FILESYSTEM,
            )

        # If state file exists, check it's writable too
        if state_file.exists() and not os.access(state_file, os.W_OK):
            return ValidationCheck(
                name="state_file_writable",
                passed=False,
                message=f"State file not writable: {state_file}",
                severity="error",
                category=CheckCategory.FILESYSTEM,
            )

        return ValidationCheck(
            name="state_file_writable",
            passed=True,
            message="State file OK",
            severity="info",
            category=CheckCategory.FILESYSTEM,
        )


class DiscoveryValidation:
    """Validate discovered releases before processing."""

    def __init__(self, processed_identifiers: set[str] | None = None) -> None:
        """
        Initialize discovery validation.

        Args:
            processed_identifiers: Set of already processed ASINs/paths
        """
        self._processed = processed_identifiers or set()

    def validate(self, release: AudiobookRelease) -> ValidationResult:
        """
        Run all discovery validation checks.

        Checks:
        - ASIN format is valid (10 alphanumeric)
        - M4B file exists and is readable
        - Cover image exists (jpg/png)
        - Not already processed

        Args:
            release: AudiobookRelease to validate

        Returns:
            ValidationResult with all check results
        """
        result = ValidationResult()
        result.add(self._check_asin_format(release))
        result.add(self._check_m4b_exists(release))
        result.add(self._check_cover_exists(release))
        result.add(self._check_not_duplicate(release))
        result.add(self._check_title_cleaning(release))
        return result

    def _check_asin_format(self, release: AudiobookRelease) -> ValidationCheck:
        """Check if ASIN is present and valid format."""
        if not release.asin:
            return ValidationCheck(
                name="asin_format",
                passed=False,
                message="No ASIN found - required for metadata lookup",
                severity="error",
            )

        is_valid = bool(ASIN_VALID_PATTERN.match(release.asin))
        return ValidationCheck(
            name="asin_format",
            passed=is_valid,
            message=f"Valid ASIN: {release.asin}"
            if is_valid
            else f"Invalid ASIN format: {release.asin} (expected B0XXXXXXXX or 10 digits)",
            severity="error" if not is_valid else "info",
        )

    def _check_m4b_exists(self, release: AudiobookRelease) -> ValidationCheck:
        """Check if M4B file exists and is readable."""
        if not release.main_m4b:
            return ValidationCheck(
                name="m4b_exists",
                passed=False,
                message="No M4B file found in release directory",
                severity="error",
            )

        m4b_path = release.main_m4b
        if not m4b_path.exists():
            return ValidationCheck(
                name="m4b_exists",
                passed=False,
                message=f"M4B file does not exist: {m4b_path.name}",
                severity="error",
            )

        if not os.access(m4b_path, os.R_OK):
            return ValidationCheck(
                name="m4b_exists",
                passed=False,
                message=f"M4B file not readable: {m4b_path.name}",
                severity="error",
            )

        # Get file size for info
        size_mb = m4b_path.stat().st_size / (1024 * 1024)
        return ValidationCheck(
            name="m4b_exists",
            passed=True,
            message=f"M4B file found: {m4b_path.name} ({size_mb:.1f} MB)",
            severity="info",
        )

    def _check_cover_exists(self, release: AudiobookRelease) -> ValidationCheck:
        """Check if cover image exists."""
        if not release.source_dir:
            return ValidationCheck(
                name="cover_exists",
                passed=False,
                message="No source directory set",
                severity="warning",
            )

        # Look for cover files
        cover_patterns = ["cover.jpg", "cover.jpeg", "cover.png", "folder.jpg"]
        for pattern in cover_patterns:
            cover_path = release.source_dir / pattern
            if cover_path.exists():
                return ValidationCheck(
                    name="cover_exists",
                    passed=True,
                    message=f"Cover image found: {pattern}",
                    severity="info",
                )

        # Also check in files list for any image file (cover may be named after the book)
        for f in release.files:
            if f.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                return ValidationCheck(
                    name="cover_exists",
                    passed=True,
                    message=f"Cover image found: {f.name}",
                    severity="info",
                )

        # Finally, scan source directory for any image files
        if release.source_dir and release.source_dir.exists():
            for img in release.source_dir.iterdir():
                if img.is_file() and img.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                    return ValidationCheck(
                        name="cover_exists",
                        passed=True,
                        message=f"Cover image found: {img.name}",
                        severity="info",
                    )

        return ValidationCheck(
            name="cover_exists",
            passed=False,
            message="No cover image found (jpg/png expected)",
            severity="warning",
        )

    def _check_not_duplicate(self, release: AudiobookRelease) -> ValidationCheck:
        """Check if release has already been processed."""
        identifier = release.asin or str(release.source_dir)

        if identifier in self._processed:
            return ValidationCheck(
                name="not_duplicate",
                passed=False,
                message=f"Already processed: {identifier}",
                severity="error",
            )

        # Also check by path
        if release.source_dir and str(release.source_dir) in self._processed:
            return ValidationCheck(
                name="not_duplicate",
                passed=False,
                message=f"Already processed (by path): {release.source_dir}",
                severity="error",
            )

        return ValidationCheck(
            name="not_duplicate",
            passed=True,
            message="Not previously processed",
            severity="info",
        )

    def _check_title_cleaning(self, release: AudiobookRelease) -> ValidationCheck:
        """
        Check if title cleaning is too aggressive.

        Uses fuzzy matching to detect when naming rules remove
        too much from the original title.
        """
        from shelfr.utils.naming import filter_title

        if not release.title:
            return ValidationCheck(
                name="title_cleaning",
                passed=True,
                message="No title to check",
                severity="info",
            )

        original = release.title
        cleaned = filter_title(original)

        # Analyze the change
        analysis = analyze_change(original, cleaned)

        if analysis.is_suspicious:
            return ValidationCheck(
                name="title_cleaning",
                passed=True,  # Warning, not failure
                message=(
                    f"Title cleaning may be aggressive: "
                    f"'{original}' → '{cleaned}' ({analysis.similarity:.0f}% similar)"
                ),
                severity="warning",
            )

        return ValidationCheck(
            name="title_cleaning",
            passed=True,
            message=f"Title cleaning OK ({analysis.similarity:.0f}% similar)",
            severity="info",
        )


class MetadataValidation:
    """Validate fetched metadata before using."""

    def __init__(self, runtime_tolerance: float = 0.05) -> None:
        """
        Initialize metadata validation.

        Args:
            runtime_tolerance: Acceptable difference as fraction (default 5%)
        """
        self._runtime_tolerance = runtime_tolerance

    def validate(
        self,
        release: AudiobookRelease,
        audnex_data: dict[str, Any] | None = None,
        mediainfo_data: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """
        Run all metadata validation checks.

        Checks:
        - Required fields present (title, authors, asin)
        - At least one author present
        - At least one narrator present
        - Runtime matches between API and embedded (within tolerance)

        Args:
            release: AudiobookRelease being processed
            audnex_data: Audnex API response data
            mediainfo_data: MediaInfo JSON data

        Returns:
            ValidationResult with all check results
        """
        result = ValidationResult()
        result.add(self._check_required_fields(audnex_data))
        result.add(self._check_authors_present(audnex_data))
        result.add(self._check_narrators_present(audnex_data))
        result.add(self._check_runtime_matches(audnex_data, mediainfo_data))
        return result

    def _check_required_fields(self, audnex_data: dict[str, Any] | None) -> ValidationCheck:
        """Check that required metadata fields are present."""
        if not audnex_data:
            return ValidationCheck(
                name="required_fields",
                passed=False,
                message="No Audnex metadata available",
                severity="warning",
            )

        required = ["title", "asin"]
        missing = [f for f in required if not audnex_data.get(f)]

        if missing:
            return ValidationCheck(
                name="required_fields",
                passed=False,
                message=f"Missing required fields: {', '.join(missing)}",
                severity="error",
            )

        return ValidationCheck(
            name="required_fields",
            passed=True,
            message="All required fields present (title, asin)",
            severity="info",
        )

    def _check_authors_present(self, audnex_data: dict[str, Any] | None) -> ValidationCheck:
        """Check that at least one author is present."""
        if not audnex_data:
            return ValidationCheck(
                name="authors_present",
                passed=False,
                message="No metadata to check authors",
                severity="warning",
            )

        authors = audnex_data.get("authors", [])
        if not authors:
            return ValidationCheck(
                name="authors_present",
                passed=False,
                message="No authors found in metadata",
                severity="warning",
            )

        author_names = [a.get("name", "Unknown") for a in authors if isinstance(a, dict)]
        return ValidationCheck(
            name="authors_present",
            passed=True,
            message=f"Authors: {', '.join(author_names[:3])}"
            + ("..." if len(author_names) > 3 else ""),
            severity="info",
        )

    def _check_narrators_present(self, audnex_data: dict[str, Any] | None) -> ValidationCheck:
        """Check that at least one narrator is present."""
        if not audnex_data:
            return ValidationCheck(
                name="narrators_present",
                passed=False,
                message="No metadata to check narrators",
                severity="warning",
            )

        narrators = audnex_data.get("narrators", [])
        if not narrators:
            return ValidationCheck(
                name="narrators_present",
                passed=False,
                message="No narrators found in metadata",
                severity="warning",
            )

        narrator_names = [n.get("name", "Unknown") for n in narrators if isinstance(n, dict)]
        return ValidationCheck(
            name="narrators_present",
            passed=True,
            message=f"Narrators: {', '.join(narrator_names[:3])}"
            + ("..." if len(narrator_names) > 3 else ""),
            severity="info",
        )

    def _check_runtime_matches(
        self,
        audnex_data: dict[str, Any] | None,
        mediainfo_data: dict[str, Any] | None,
    ) -> ValidationCheck:
        """Check if runtime from API matches embedded duration."""
        if not audnex_data or not mediainfo_data:
            return ValidationCheck(
                name="runtime_match",
                passed=True,
                message="Cannot verify runtime (missing data)",
                severity="info",
            )

        # Get API runtime (in seconds or minutes depending on API response)
        api_runtime = audnex_data.get("runtimeLengthSec") or audnex_data.get("runtime_length_sec")
        if not api_runtime:
            api_minutes = audnex_data.get("runtimeLengthMin") or audnex_data.get(
                "runtime_length_min"
            )
            if api_minutes:
                api_runtime = int(api_minutes) * 60

        if not api_runtime:
            return ValidationCheck(
                name="runtime_match",
                passed=True,
                message="No API runtime to verify",
                severity="info",
            )

        # Get embedded duration from mediainfo
        embedded_duration = self._get_duration_from_mediainfo(mediainfo_data)
        if not embedded_duration:
            return ValidationCheck(
                name="runtime_match",
                passed=True,
                message="No embedded duration to verify",
                severity="info",
            )

        # Compare with tolerance
        diff = abs(embedded_duration - api_runtime)
        tolerance_seconds = api_runtime * self._runtime_tolerance

        if diff <= tolerance_seconds:
            return ValidationCheck(
                name="runtime_match",
                passed=True,
                message=f"Runtime matches: API={api_runtime}s, Embedded={embedded_duration:.0f}s "
                f"(diff: {diff:.0f}s)",
                severity="info",
            )

        return ValidationCheck(
            name="runtime_match",
            passed=False,
            message=f"Runtime mismatch: API={api_runtime}s, Embedded={embedded_duration:.0f}s "
            f"(diff: {diff:.0f}s, tolerance: {tolerance_seconds:.0f}s)",
            severity="warning",
        )

    def _get_duration_from_mediainfo(self, mediainfo_data: dict[str, Any]) -> float | None:
        """Extract duration in seconds from MediaInfo data."""
        try:
            media = mediainfo_data.get("media", {})
            tracks = media.get("track", [])

            for track in tracks:
                if track.get("@type") == "General":
                    duration = track.get("Duration")
                    if duration:
                        return float(duration)

            return None
        except (KeyError, ValueError, TypeError):
            return None


class PreUploadValidation:
    """Validate everything before committing to upload."""

    def __init__(self, settings: Settings) -> None:
        """
        Initialize pre-upload validation.

        Args:
            settings: Application settings
        """
        self._settings = settings

    def validate(self, release: AudiobookRelease) -> ValidationResult:
        """
        Run all pre-upload validation checks.

        Checks:
        - Torrent file created and valid
        - Staging directory exists (hardlink created)
        - Filename length within MAM limit (225 chars)
        - Category resolved (genre → category ID)
        - Seed path is valid

        Args:
            release: AudiobookRelease to validate

        Returns:
            ValidationResult with all check results
        """
        result = ValidationResult()
        result.add(self._check_torrent_valid(release))
        result.add(self._check_staging_exists(release))
        result.add(self._check_filename_length(release))
        result.add(self._check_category_resolved(release))
        result.add(self._check_seed_path_valid(release))
        return result

    def _check_torrent_valid(self, release: AudiobookRelease) -> ValidationCheck:
        """Check if torrent file exists and is valid."""
        if not release.torrent_path:
            return ValidationCheck(
                name="torrent_valid",
                passed=False,
                message="No torrent file path set",
                severity="error",
            )

        if not release.torrent_path.exists():
            return ValidationCheck(
                name="torrent_valid",
                passed=False,
                message=f"Torrent file not found: {release.torrent_path}",
                severity="error",
            )

        # Check file size (should be > 0)
        size = release.torrent_path.stat().st_size
        if size == 0:
            return ValidationCheck(
                name="torrent_valid",
                passed=False,
                message="Torrent file is empty",
                severity="error",
            )

        return ValidationCheck(
            name="torrent_valid",
            passed=True,
            message=f"Torrent file valid: {release.torrent_path.name} ({size} bytes)",
            severity="info",
        )

    def _check_staging_exists(self, release: AudiobookRelease) -> ValidationCheck:
        """Check if staging directory exists."""
        if not release.staging_dir:
            return ValidationCheck(
                name="staging_exists",
                passed=False,
                message="No staging directory set",
                severity="error",
            )

        if not release.staging_dir.exists():
            return ValidationCheck(
                name="staging_exists",
                passed=False,
                message=f"Staging directory not found: {release.staging_dir}",
                severity="error",
            )

        # Count files in staging
        file_count = sum(1 for _ in release.staging_dir.iterdir() if _.is_file())
        return ValidationCheck(
            name="staging_exists",
            passed=True,
            message=f"Staging directory valid: {release.staging_dir.name} ({file_count} files)",
            severity="info",
        )

    def _check_filename_length(self, release: AudiobookRelease) -> ValidationCheck:
        """Check if filename length is within MAM limit."""
        if not release.staging_dir:
            return ValidationCheck(
                name="filename_length",
                passed=True,
                message="No staging dir to check filename length",
                severity="info",
            )

        dirname = release.staging_dir.name
        length = len(dirname)

        if length > MAM_MAX_FILENAME_LENGTH:
            return ValidationCheck(
                name="filename_length",
                passed=False,
                message=f"Filename too long: {length} chars (max {MAM_MAX_FILENAME_LENGTH})",
                severity="error",
            )

        return ValidationCheck(
            name="filename_length",
            passed=True,
            message=f"Filename length OK: {length} chars (max {MAM_MAX_FILENAME_LENGTH})",
            severity="info",
        )

    def _check_category_resolved(self, release: AudiobookRelease) -> ValidationCheck:
        """Check if genre → category ID mapping resolved."""
        if not release.audnex_metadata:
            return ValidationCheck(
                name="category_resolved",
                passed=True,
                message="No Audnex metadata - using default category",
                severity="info",
            )

        # Get genres from Audnex data
        genres = release.audnex_metadata.get("genres", [])
        if not genres:
            return ValidationCheck(
                name="category_resolved",
                passed=True,
                message="No genres in metadata - using default category",
                severity="info",
            )

        # Check if any genre maps to a category
        genre_map = self._settings.categories.genre_map
        for genre in genres:
            genre_name = genre.get("name", "") if isinstance(genre, dict) else str(genre)
            if genre_name in genre_map:
                category_id = genre_map[genre_name]
                return ValidationCheck(
                    name="category_resolved",
                    passed=True,
                    message=f"Category resolved: '{genre_name}' → {category_id}",
                    severity="info",
                )

        return ValidationCheck(
            name="category_resolved",
            passed=True,
            message=f"No matching genre found - using default (genres: {genres[:3]})",
            severity="warning",
        )

    def _check_seed_path_valid(self, release: AudiobookRelease) -> ValidationCheck:
        """Check if seed root path is valid."""
        seed_root = self._settings.paths.seed_root

        if not seed_root.exists():
            return ValidationCheck(
                name="seed_path_valid",
                passed=False,
                message=f"Seed root does not exist: {seed_root}",
                severity="error",
            )

        if not os.access(seed_root, os.W_OK):
            return ValidationCheck(
                name="seed_path_valid",
                passed=False,
                message=f"Seed root not writable: {seed_root}",
                severity="error",
            )

        return ValidationCheck(
            name="seed_path_valid",
            passed=True,
            message=f"Seed root valid: {seed_root}",
            severity="info",
        )


# =============================================================================
# Chapter Integrity Checks (Phase 4)
# =============================================================================


class ChapterIntegrityChecker:
    """Detect chapter metadata issues like the Libation bug."""

    def __init__(self, duration_tolerance: float = 0.05) -> None:
        """
        Initialize chapter integrity checker.

        Args:
            duration_tolerance: Acceptable difference as fraction (default 5%)
        """
        self._duration_tolerance = duration_tolerance

    def compare_chapters(
        self,
        embedded_chapters: list[dict[str, Any]],
        api_chapters: list[dict[str, Any]],
    ) -> ChapterComparisonResult:
        """
        Compare embedded chapters against API chapters.

        Detects issues like the Libation bug where chapter counts mismatch.

        Args:
            embedded_chapters: Chapters from MediaInfo
            api_chapters: Chapters from Audnex API

        Returns:
            ChapterComparisonResult with comparison details
        """
        embedded_count = len(embedded_chapters)
        api_count = len(api_chapters)
        count_match = embedded_count == api_count

        # Compare titles
        titles_match = True
        mismatched_titles: list[tuple[str, str]] = []

        min_count = min(embedded_count, api_count)
        for i in range(min_count):
            emb_title = self._normalize_title(embedded_chapters[i].get("title", f"Chapter {i + 1}"))
            api_title = self._normalize_title(api_chapters[i].get("title", f"Chapter {i + 1}"))

            if emb_title != api_title:
                titles_match = False
                mismatched_titles.append((emb_title, api_title))

        # Compare total durations
        embedded_duration = self._sum_durations(embedded_chapters)
        api_duration = self._sum_durations(api_chapters)

        duration_diff = abs(embedded_duration - api_duration)
        tolerance_seconds = max(embedded_duration, api_duration) * self._duration_tolerance
        durations_match = duration_diff <= tolerance_seconds

        return ChapterComparisonResult(
            count_match=count_match,
            titles_match=titles_match,
            durations_match=durations_match,
            embedded_count=embedded_count,
            api_count=api_count,
            duration_diff_seconds=duration_diff,
            mismatched_titles=mismatched_titles[:5],  # Limit to first 5
        )

    def validate(
        self,
        release: AudiobookRelease,
        audnex_chapters: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """
        Run chapter integrity validation.

        Args:
            release: AudiobookRelease with mediainfo_data
            audnex_chapters: Audnex chapters API response

        Returns:
            ValidationResult with chapter check results
        """
        result = ValidationResult()

        # Extract embedded chapters from mediainfo
        embedded_chapters = self._extract_mediainfo_chapters(release.mediainfo_data)

        # Extract API chapters
        api_chapters = []
        if audnex_chapters:
            api_chapters = audnex_chapters.get("chapters", [])

        if not embedded_chapters and not api_chapters:
            result.add(
                ValidationCheck(
                    name="chapter_integrity",
                    passed=True,
                    message="No chapter data available for comparison",
                    severity="info",
                )
            )
            return result

        if not embedded_chapters:
            result.add(
                ValidationCheck(
                    name="chapter_integrity",
                    passed=True,
                    message=f"No embedded chapters, API has {len(api_chapters)} chapters",
                    severity="info",
                )
            )
            return result

        if not api_chapters:
            result.add(
                ValidationCheck(
                    name="chapter_integrity",
                    passed=True,
                    message=f"No API chapters, embedded has {len(embedded_chapters)} chapters",
                    severity="info",
                )
            )
            return result

        # Compare chapters
        comparison = self.compare_chapters(embedded_chapters, api_chapters)

        # Chapter count check
        if comparison.count_match:
            result.add(
                ValidationCheck(
                    name="chapter_count",
                    passed=True,
                    message=f"Chapter count matches: {comparison.embedded_count}",
                    severity="info",
                )
            )
        else:
            result.add(
                ValidationCheck(
                    name="chapter_count",
                    passed=False,
                    message=f"Chapter count MISMATCH: embedded={comparison.embedded_count}, "
                    f"API={comparison.api_count} (possible Libation bug)",
                    severity="warning",
                )
            )

        # Duration check
        if comparison.durations_match:
            result.add(
                ValidationCheck(
                    name="chapter_duration",
                    passed=True,
                    message="Chapter durations match within tolerance",
                    severity="info",
                )
            )
        else:
            diff_secs = comparison.duration_diff_seconds
            result.add(
                ValidationCheck(
                    name="chapter_duration",
                    passed=False,
                    message=f"Chapter duration mismatch: {diff_secs:.0f}s difference",
                    severity="warning",
                )
            )

        return result

    def _normalize_title(self, title: str) -> str:
        """Normalize chapter title for comparison."""
        # Lowercase, strip whitespace, remove common prefixes
        t = title.lower().strip()
        # Remove "Chapter X: " prefix
        t = re.sub(r"^chapter\s*\d+\s*[:\-]?\s*", "", t)
        return t

    def _sum_durations(self, chapters: list[dict[str, Any]]) -> float:
        """Sum chapter durations in seconds."""
        total = 0.0
        for ch in chapters:
            duration: float | None = None

            # Prefer explicit milliseconds fields (field name indicates unit)
            if "lengthMs" in ch and ch["lengthMs"] is not None:
                duration = float(ch["lengthMs"]) / 1000
            elif "length_ms" in ch and ch["length_ms"] is not None:
                duration = float(ch["length_ms"]) / 1000
            elif "duration" in ch and ch["duration"] is not None:
                duration = float(ch["duration"])
                # If duration is suspiciously large, treat as ms
                # Threshold: 10,000,000 = ~115 days (extremely unlikely for audiobooks)
                if duration > 10_000_000:
                    duration = duration / 1000

            if duration is not None:
                total += duration
        return total

    def _extract_mediainfo_chapters(
        self, mediainfo_data: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        """Extract chapters from MediaInfo JSON with calculated durations."""
        if not mediainfo_data:
            return []

        chapters: list[dict[str, Any]] = []
        total_duration_ms: float = 0

        try:
            media = mediainfo_data.get("media", {})
            tracks = media.get("track", [])

            # First, get total duration from General or Audio track
            for track in tracks:
                track_type = track.get("@type")
                if track_type in ("General", "Audio"):
                    duration_str = track.get("Duration")
                    if duration_str:
                        total_duration_ms = float(duration_str) * 1000
                        break

            # Extract chapter start times
            chapter_starts: list[tuple[int, str]] = []  # (startMs, title)
            for track in tracks:
                if track.get("@type") == "Menu":
                    extra = track.get("extra", {})
                    # Chapter entries look like: "_00_07_35_573": "Chapter 1"
                    for key, value in extra.items():
                        if key.startswith("_") and "_" in key[1:]:
                            parts = key[1:].split("_")
                            if len(parts) >= 3:
                                # Validate parts are numeric before conversion
                                if not all(p.isdigit() for p in parts[:3]):
                                    logger.debug(f"Skipping non-numeric chapter key: {key}")
                                    continue
                                h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
                                # Handle milliseconds if present (4th part)
                                ms = int(parts[3]) if len(parts) >= 4 and parts[3].isdigit() else 0
                                total_ms = (h * 3600 + m * 60 + s) * 1000 + ms
                                chapter_starts.append((total_ms, value))
                    break

            # Sort by start time and calculate durations
            chapter_starts.sort(key=lambda x: x[0])
            for i, (start_ms, title) in enumerate(chapter_starts):
                # Duration = next chapter start - current start (or total - current for last)
                if i + 1 < len(chapter_starts):
                    duration_ms = chapter_starts[i + 1][0] - start_ms
                else:
                    # Last chapter: duration = total - start
                    duration_ms = int(total_duration_ms - start_ms) if total_duration_ms > 0 else 0

                chapters.append(
                    {
                        "title": title,
                        "startMs": start_ms,
                        "lengthMs": duration_ms,
                    }
                )

        except (TypeError, KeyError, ValueError) as e:
            logger.warning(f"Failed to extract chapters from mediainfo: {e}")

        return chapters


# =============================================================================
# Safety Utilities (Phase 5)
# =============================================================================


def sanitize_path_component(name: str) -> str:
    """
    Sanitize a path component to prevent directory traversal.

    Removes: ../, ./, null bytes, and other dangerous patterns.

    Args:
        name: The path component to sanitize

    Returns:
        Sanitized string safe for use in paths
    """
    if not name:
        return ""

    # Remove null bytes
    result = name.replace("\x00", "")

    # Remove path separators FIRST (before traversal patterns)
    # This prevents bypass attacks like "..../" -> "../" after single replacement
    result = result.replace("/", "-")
    result = result.replace("\\", "-")

    # Remove directory traversal patterns in a loop until none remain
    # This prevents bypass attacks like "...." -> ".." after single replacement
    # Note: "./" and ".\\" patterns are already handled by the path separator
    # replacement above (they become ".-" which is safe)
    while ".." in result:
        result = result.replace("..", "")

    # Remove leading/trailing dots and spaces
    result = result.strip(". ")

    # Collapse multiple dashes
    while "--" in result:
        result = result.replace("--", "-")

    return result


def is_safe_path(path: Path, allowed_root: Path) -> bool:
    """
    Check if a path is safely within an allowed root directory.

    Prevents directory traversal attacks.

    Args:
        path: The path to check
        allowed_root: The root directory that path must be within

    Returns:
        True if path is safely within allowed_root
    """
    try:
        # Resolve both paths to absolute, following symlinks
        resolved_path = path.resolve()
        resolved_root = allowed_root.resolve()

        # Check if path is under root
        return resolved_path.is_relative_to(resolved_root)
    except (ValueError, OSError):
        return False


def compute_file_checksum(file_path: Path, algorithm: str = "md5") -> str | None:
    """
    Compute checksum of a file.

    Args:
        file_path: Path to the file
        algorithm: Hash algorithm ('md5', 'sha256')

    Returns:
        Hex digest string or None if file doesn't exist
    """
    if not file_path.exists():
        return None

    hash_func = hashlib.new(algorithm)
    try:
        with open(file_path, "rb") as f:
            # Read in chunks to handle large files
            for chunk in iter(lambda: f.read(8192), b""):
                hash_func.update(chunk)
        return hash_func.hexdigest()
    except OSError:
        return None


# =============================================================================
# Validation Report Generation (Phase 4)
# =============================================================================


@dataclass
class ValidationReport:
    """Complete validation report for a release."""

    asin: str | None
    title: str
    validated_at: str  # ISO format
    discovery_result: ValidationResult | None = None
    metadata_result: ValidationResult | None = None
    chapter_result: ValidationResult | None = None
    pre_upload_result: ValidationResult | None = None

    @property
    def all_passed(self) -> bool:
        """True if all validation stages passed."""
        results = [
            self.discovery_result,
            self.metadata_result,
            self.chapter_result,
            self.pre_upload_result,
        ]
        return all(r.passed for r in results if r is not None)

    @property
    def total_warnings(self) -> int:
        """Total warning count across all stages."""
        results = [
            self.discovery_result,
            self.metadata_result,
            self.chapter_result,
            self.pre_upload_result,
        ]
        return sum(r.warning_count for r in results if r is not None)

    @property
    def total_errors(self) -> int:
        """Total error count across all stages."""
        results = [
            self.discovery_result,
            self.metadata_result,
            self.chapter_result,
            self.pre_upload_result,
        ]
        return sum(r.error_count for r in results if r is not None)

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary for JSON serialization."""

        def result_to_dict(result: ValidationResult | None) -> dict[str, Any] | None:
            if result is None:
                return None
            return {
                "passed": result.passed,
                "checks": [
                    {
                        "name": c.name,
                        "passed": c.passed,
                        "message": c.message,
                        "severity": c.severity,
                    }
                    for c in result.checks
                ],
                "warnings": result.warning_count,
                "errors": result.error_count,
            }

        return {
            "asin": self.asin,
            "title": self.title,
            "validated_at": self.validated_at,
            "all_passed": self.all_passed,
            "total_warnings": self.total_warnings,
            "total_errors": self.total_errors,
            "discovery": result_to_dict(self.discovery_result),
            "metadata": result_to_dict(self.metadata_result),
            "chapters": result_to_dict(self.chapter_result),
            "pre_upload": result_to_dict(self.pre_upload_result),
        }
