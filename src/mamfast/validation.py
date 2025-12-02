"""Validation framework for MAMFast health checks and runtime validation."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import httpx

if TYPE_CHECKING:
    from mamfast.config import Settings
    from mamfast.models import AudiobookRelease

logger = logging.getLogger(__name__)

# ASIN validation pattern - 10 chars: B + 9 alphanumeric or 10 digits (ISBN-10)
ASIN_VALID_PATTERN = re.compile(r"^(?:B[0-9A-Z]{9}|[0-9]{10})$")

# Maximum filename length for MAM
MAM_MAX_FILENAME_LENGTH = 225


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

        # Also check in files list
        for f in release.files:
            if f.suffix.lower() in {".jpg", ".jpeg", ".png"} and "cover" in f.name.lower():
                return ValidationCheck(
                    name="cover_exists",
                    passed=True,
                    message=f"Cover image found: {f.name}",
                    severity="info",
                )

        return ValidationCheck(
            name="cover_exists",
            passed=False,
            message="No cover image found (cover.jpg/png expected)",
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
            # Try different duration field names
            duration = ch.get("lengthMs") or ch.get("length_ms") or ch.get("duration")
            if duration:
                # Convert ms to seconds if needed
                if duration > 1000000:  # Likely milliseconds
                    duration = duration / 1000
                total += float(duration)
        return total

    def _extract_mediainfo_chapters(
        self, mediainfo_data: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        """Extract chapters from MediaInfo JSON."""
        if not mediainfo_data:
            return []

        chapters: list[dict[str, Any]] = []
        try:
            media = mediainfo_data.get("media", {})
            tracks = media.get("track", [])

            for track in tracks:
                if track.get("@type") == "Menu":
                    extra = track.get("extra", {})
                    # Chapter entries look like: "_00_07_35_573": "Chapter 1"
                    for key, value in extra.items():
                        if key.startswith("_") and "_" in key[1:]:
                            parts = key[1:].split("_")
                            if len(parts) >= 3:
                                h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
                                total_ms = (h * 3600 + m * 60 + s) * 1000
                                chapters.append(
                                    {
                                        "title": value,
                                        "startMs": total_ms,
                                    }
                                )
                    break

        except Exception as e:
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

    # Remove directory traversal patterns
    result = result.replace("..", "")
    result = result.replace("./", "")
    result = result.replace(".\\", "")

    # Remove leading/trailing dots and spaces
    result = result.strip(". ")

    # Remove path separators
    result = result.replace("/", "-")
    result = result.replace("\\", "-")

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
