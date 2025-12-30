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
    "validate_abs_metadata",
    # Config
    "AudnexSchema",
    "ConfigSchema",
    "EnvironmentSchema",
    "FiltersSchema",
    "LibationSchema",
    "MamSchema",
    "MediaInfoSchema",
    "MkbrrSchema",
    "PathsSchema",
    "QBittorrentSchema",
    "validate_config_yaml",
    # Naming
    "NamingSchema",
    "validate_naming_json",
    # Audnex
    "AudnexAuthor",
    "AudnexAuthorProfile",
    "AudnexBook",
    "AudnexChapter",
    "AudnexChaptersResponse",
    "AudnexGenre",
    "AudnexSeries",
    "validate_audnex_author",
    "validate_audnex_book",
    "validate_audnex_chapters",
    # State
    "FailedRelease",
    "ProcessedRelease",
    "ProcessedState",
    "create_empty_state",
    "validate_state",
]
