"""Pydantic schemas for validating external data sources."""

from __future__ import annotations

from shelfr.schemas.abs_metadata import (
    AbsChapter,
    AbsMetadataJson,
    validate_abs_metadata,
)
from shelfr.schemas.audnex import (
    AudnexAuthor,
    AudnexAuthorProfile,
    AudnexBook,
    AudnexChapter,
    AudnexChaptersResponse,
    AudnexGenre,
    AudnexSeries,
    validate_audnex_author,
    validate_audnex_book,
    validate_audnex_chapters,
)
from shelfr.schemas.config import (
    AudnexSchema,
    ConfigSchema,
    EnvironmentSchema,
    FiltersSchema,
    LibationSchema,
    MamSchema,
    MediaInfoSchema,
    MkbrrSchema,
    PathsSchema,
    QBittorrentSchema,
    validate_config_yaml,
)
from shelfr.schemas.mkbrr import (
    CheckResult,
    TorrentFileInfo,
    TorrentInfo,
    validate_check_result,
    validate_torrent_info,
)
from shelfr.schemas.naming import NamingSchema, validate_naming_json
from shelfr.schemas.state import (
    FailedRelease,
    ProcessedRelease,
    ProcessedState,
    create_empty_state,
    validate_state,
)

__all__ = [
    # ABS Metadata
    "AbsChapter",
    "AbsMetadataJson",
    # Audnex
    "AudnexAuthor",
    "AudnexAuthorProfile",
    "AudnexBook",
    "AudnexChapter",
    "AudnexChaptersResponse",
    "AudnexGenre",
    # Config
    "AudnexSchema",
    "AudnexSeries",
    # mkbrr Data
    "CheckResult",
    "ConfigSchema",
    "EnvironmentSchema",
    # State
    "FailedRelease",
    "FiltersSchema",
    "LibationSchema",
    "MamSchema",
    "MediaInfoSchema",
    "MkbrrSchema",
    # Naming
    "NamingSchema",
    "PathsSchema",
    "ProcessedRelease",
    "ProcessedState",
    "QBittorrentSchema",
    "TorrentFileInfo",
    "TorrentInfo",
    "create_empty_state",
    "validate_abs_metadata",
    "validate_audnex_author",
    "validate_audnex_book",
    "validate_audnex_chapters",
    "validate_check_result",
    "validate_config_yaml",
    "validate_naming_json",
    "validate_state",
    "validate_torrent_info",
]
