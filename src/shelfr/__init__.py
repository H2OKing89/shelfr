"""MAMFast - Fast MAM audiobook upload automation tool."""

from shelfr.exceptions import (
    AudiobookshelfError,
    AudnexError,
    ConfigurationError,
    DiscoveryValidationError,
    DockerError,
    ExternalToolError,
    LibationError,
    MAMFastError,
    MetadataError,
    MkbrrError,
    NetworkError,
    PipelineError,
    PreUploadValidationError,
    QBittorrentError,
    StagingError,
    StateCorruptionError,
    StateError,
    StateLockError,
    TorrentError,
    UploadError,
    ValidationError,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # Base exception
    "MAMFastError",
    # Configuration
    "ConfigurationError",
    # Validation
    "ValidationError",
    "DiscoveryValidationError",
    "PreUploadValidationError",
    # Pipeline stages
    "PipelineError",
    "StagingError",
    "MetadataError",
    "TorrentError",
    "UploadError",
    # Network
    "NetworkError",
    "AudnexError",
    "QBittorrentError",
    "AudiobookshelfError",
    # State
    "StateError",
    "StateLockError",
    "StateCorruptionError",
    # External tools
    "ExternalToolError",
    "DockerError",
    "MkbrrError",
    "LibationError",
]
