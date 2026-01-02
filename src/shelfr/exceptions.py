"""
Shelfr exception hierarchy.

Provides typed exceptions for better error handling and clearer error messages.

Exception Hierarchy:
    ShelfrError (base)
    ├── ConfigurationError - Config file issues, missing settings
    ├── ValidationError - Pre-flight and runtime validation failures
    │   ├── DiscoveryValidationError - Discovery stage validation
    │   └── PreUploadValidationError - Pre-upload validation
    ├── PipelineError - Stage execution failures
    │   ├── StagingError - Hardlink/copy failures
    │   ├── MetadataError - Audnex/MediaInfo failures
    │   ├── TorrentError - mkbrr/torrent creation failures
    │   └── UploadError - qBittorrent upload failures
    ├── NetworkError - External service communication failures
    │   ├── AudnexError - Audnex API failures
    │   ├── QBittorrentError - qBittorrent API failures
    │   └── AudiobookshelfError - ABS API failures
    ├── StateError - State file operations
    │   ├── StateLockError - Lock acquisition failures
    │   └── StateCorruptionError - State file corruption
    └── ExternalToolError - Docker/subprocess failures
        ├── DockerError - Docker daemon issues
        ├── MkbrrError - mkbrr tool failures
        └── LibationError - Libation CLI failures
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class ShelfrError(Exception):
    """Base exception for all shelfr errors."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        """
        Initialize shelfr exception.

        Args:
            message: Human-readable error message
            details: Optional structured error details for logging/debugging
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        return self.message


# =============================================================================
# Configuration Errors
# =============================================================================


class ConfigurationError(ShelfrError):
    """Configuration file or settings error."""

    def __init__(
        self,
        message: str,
        *,
        config_file: Path | str | None = None,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        details = details or {}
        if config_file:
            details["config_file"] = str(config_file)
        if field:
            details["field"] = field
        super().__init__(message, details=details)
        self.config_file = config_file
        self.field = field


# =============================================================================
# Validation Errors
# =============================================================================


class ValidationError(ShelfrError):
    """Validation failure (pre-flight or runtime)."""

    def __init__(
        self,
        message: str,
        *,
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        details = details or {}
        if errors:
            details["errors"] = errors
        if warnings:
            details["warnings"] = warnings
        super().__init__(message, details=details)
        self.errors = errors or []
        self.warnings = warnings or []


class DiscoveryValidationError(ValidationError):
    """Discovery stage validation failure."""

    pass


class PreUploadValidationError(ValidationError):
    """Pre-upload validation failure."""

    pass


# =============================================================================
# Pipeline Stage Errors
# =============================================================================


class PipelineError(ShelfrError):
    """Pipeline stage execution failure."""

    def __init__(
        self,
        message: str,
        *,
        stage: str | None = None,
        release_asin: str | None = None,
        release_title: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        details = details or {}
        if stage:
            details["stage"] = stage
        if release_asin:
            details["release_asin"] = release_asin
        if release_title:
            details["release_title"] = release_title
        super().__init__(message, details=details)
        self.stage = stage
        self.release_asin = release_asin
        self.release_title = release_title


class StagingError(PipelineError):
    """Staging (hardlink/copy) failure."""

    def __init__(
        self,
        message: str,
        *,
        source_path: Path | str | None = None,
        target_path: Path | str | None = None,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("stage", "staging")
        details = kwargs.get("details", {})
        if source_path:
            details["source_path"] = str(source_path)
        if target_path:
            details["target_path"] = str(target_path)
        kwargs["details"] = details
        super().__init__(message, **kwargs)
        self.source_path = source_path
        self.target_path = target_path


class MetadataError(PipelineError):
    """Metadata fetching failure."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("stage", "metadata")
        super().__init__(message, **kwargs)


class ExportError(MetadataError):
    """Metadata export failure (file write, validation, etc.)."""

    def __init__(
        self,
        message: str,
        *,
        format_name: str | None = None,
        output_path: Path | str | None = None,
        **kwargs: Any,
    ) -> None:
        details = kwargs.get("details", {})
        if format_name:
            details["format_name"] = format_name
        if output_path:
            details["output_path"] = str(output_path)
        kwargs["details"] = details
        super().__init__(message, **kwargs)
        self.format_name = format_name
        self.output_path = output_path


class TorrentError(PipelineError):
    """Torrent creation failure."""

    def __init__(
        self,
        message: str,
        *,
        torrent_path: Path | str | None = None,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("stage", "torrent")
        details = kwargs.get("details", {})
        if torrent_path:
            details["torrent_path"] = str(torrent_path)
        kwargs["details"] = details
        super().__init__(message, **kwargs)
        self.torrent_path = torrent_path


class UploadError(PipelineError):
    """qBittorrent upload failure."""

    def __init__(
        self,
        message: str,
        *,
        infohash: str | None = None,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("stage", "upload")
        details = kwargs.get("details", {})
        if infohash:
            details["infohash"] = infohash
        kwargs["details"] = details
        super().__init__(message, **kwargs)
        self.infohash = infohash


# =============================================================================
# Network Errors
# =============================================================================


class NetworkError(ShelfrError):
    """External service communication failure."""

    def __init__(
        self,
        message: str,
        *,
        service: str | None = None,
        url: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        details = details or {}
        if service:
            details["service"] = service
        if url:
            details["url"] = url
        if status_code:
            details["status_code"] = status_code
        super().__init__(message, details=details)
        self.service = service
        self.url = url
        self.status_code = status_code


class AudnexError(NetworkError):
    """Audnex API failure."""

    def __init__(self, message: str, *, asin: str | None = None, **kwargs: Any) -> None:
        kwargs.setdefault("service", "audnex")
        details = kwargs.get("details", {})
        if asin:
            details["asin"] = asin
        kwargs["details"] = details
        super().__init__(message, **kwargs)
        self.asin = asin


class QBittorrentError(NetworkError):
    """qBittorrent API failure."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("service", "qbittorrent")
        super().__init__(message, **kwargs)


class AudiobookshelfError(NetworkError):
    """Audiobookshelf API failure."""

    def __init__(
        self,
        message: str,
        *,
        library_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("service", "audiobookshelf")
        details = kwargs.get("details", {})
        if library_id:
            details["library_id"] = library_id
        kwargs["details"] = details
        super().__init__(message, **kwargs)
        self.library_id = library_id


# =============================================================================
# State Management Errors
# =============================================================================


class StateError(ShelfrError):
    """State file operation failure."""

    def __init__(
        self,
        message: str,
        *,
        state_file: Path | str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        details = details or {}
        if state_file:
            details["state_file"] = str(state_file)
        super().__init__(message, details=details)
        self.state_file = state_file


class StateLockError(StateError):
    """Lock acquisition failure (another instance running)."""

    def __init__(
        self,
        message: str,
        *,
        lock_file: Path | str | None = None,
        **kwargs: Any,
    ) -> None:
        details = kwargs.get("details", {})
        if lock_file:
            details["lock_file"] = str(lock_file)
        kwargs["details"] = details
        super().__init__(message, **kwargs)
        self.lock_file = lock_file


class StateCorruptionError(StateError):
    """State file corruption detected."""

    pass


# =============================================================================
# External Tool Errors
# =============================================================================


class ExternalToolError(ShelfrError):
    """External tool/subprocess failure."""

    def __init__(
        self,
        message: str,
        *,
        tool: str | None = None,
        command: str | None = None,
        return_code: int | None = None,
        stdout: str | None = None,
        stderr: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        details = details or {}
        if tool:
            details["tool"] = tool
        if command:
            details["command"] = command
        if return_code is not None:
            details["return_code"] = return_code
        if stdout:
            details["stdout"] = stdout
        if stderr:
            details["stderr"] = stderr
        super().__init__(message, details=details)
        self.tool = tool
        self.command = command
        self.return_code = return_code
        self.stdout = stdout
        self.stderr = stderr


class DockerError(ExternalToolError):
    """Docker daemon/container failure."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("tool", "docker")
        super().__init__(message, **kwargs)


class MkbrrError(ExternalToolError):
    """mkbrr torrent tool failure."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("tool", "mkbrr")
        super().__init__(message, **kwargs)


class LibationError(ExternalToolError):
    """Libation CLI failure."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("tool", "libation")
        super().__init__(message, **kwargs)


# =============================================================================
# Convenience Aliases
# =============================================================================

# For backward compatibility with existing code that uses generic exceptions
ConfigError = ConfigurationError
