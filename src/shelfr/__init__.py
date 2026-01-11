"""shelfr - Fast MAM audiobook upload automation tool."""

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

__version__ = "0.3.0"

__all__ = [
    "AudiobookshelfError",
    "AudnexError",
    # Configuration
    "ConfigurationError",
    "DiscoveryValidationError",
    "DockerError",
    # External tools
    "ExternalToolError",
    "LibationError",
    "MetadataError",
    "MkbrrError",
    # Network
    "NetworkError",
    # Pipeline stages
    "PipelineError",
    "PreUploadValidationError",
    "QBittorrentError",
    # Base exception
    "ShelfrError",
    "ShelfrError",  # Deprecated alias for backward compatibility
    "StagingError",
    "StateCorruptionError",
    # State
    "StateError",
    "StateLockError",
    "TorrentError",
    "UploadError",
    # Validation
    "ValidationError",
    "__version__",
]
