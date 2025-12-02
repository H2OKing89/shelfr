"""Validation framework for MAMFast health checks and runtime validation."""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Literal

import requests

if TYPE_CHECKING:
    from mamfast.config import Settings

logger = logging.getLogger(__name__)


class CheckCategory(Enum):
    """Categories of health checks."""

    CONFIG = "Configuration"
    PATHS = "Paths"
    SERVICES = "Services"
    CATEGORIES = "Categories"


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
        response = requests.get(version_url, timeout=5)

        if response.status_code == 200:
            version = response.text.strip()
            return True, f"qBittorrent: Connected (v{version})"

        # Try to authenticate
        if settings.qbittorrent.username and settings.qbittorrent.password:
            login_url = f"{host}/api/v2/auth/login"
            login_response = requests.post(
                login_url,
                data={
                    "username": settings.qbittorrent.username,
                    "password": settings.qbittorrent.password,
                },
                timeout=5,
            )

            if login_response.status_code == 200 and login_response.text == "Ok.":
                # Try version again with session
                session = requests.Session()
                session.cookies = login_response.cookies
                version_response = session.get(version_url, timeout=5)
                if version_response.status_code == 200:
                    version = version_response.text.strip()
                    return True, f"qBittorrent: Connected (v{version})"

            return False, f"qBittorrent: Authentication failed at {host}"

        return False, f"qBittorrent: Requires authentication at {host}"

    except requests.exceptions.ConnectionError:
        return False, f"qBittorrent: Connection refused at {host}"
    except requests.exceptions.Timeout:
        return False, f"qBittorrent: Connection timeout at {host}"
    except requests.exceptions.RequestException as e:
        return False, f"qBittorrent: Error - {e}"


def _check_audnex_api(base_url: str, timeout: int) -> bool:
    """Check if Audnex API is reachable."""
    try:
        # Use a known ASIN to test the API (lightweight check)
        test_url = f"{base_url}/books/B0G4NFQDWR"
        response = requests.head(test_url, timeout=timeout)
        # Accept any response (200, 404, etc.) as long as we got a response
        return bool(response.status_code < 500)
    except requests.exceptions.RequestException:
        return False
