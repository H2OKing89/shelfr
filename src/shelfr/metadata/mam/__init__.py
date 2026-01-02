"""
MAM (MyAnonamouse) export module.

Provides functions to build MAM-compatible JSON payloads for audiobook uploads,
including category mapping and genre inference.

Public API:
    build_mam_json: Build MAM fast-fillout JSON from release metadata
    save_mam_json: Write MAM JSON to file
    generate_mam_json_for_release: Generate MAM JSON file for a release
"""

from __future__ import annotations

from shelfr.metadata.mam.categories import (
    FICTION_GENRE_KEYWORDS as FICTION_GENRE_KEYWORDS,
)
from shelfr.metadata.mam.categories import (
    NONFICTION_GENRE_KEYWORDS as NONFICTION_GENRE_KEYWORDS,
)
from shelfr.metadata.mam.categories import (
    _get_audiobook_category as _get_audiobook_category,
)
from shelfr.metadata.mam.categories import (
    _infer_fiction_or_nonfiction as _infer_fiction_or_nonfiction,
)
from shelfr.metadata.mam.categories import (
    _map_genres_to_categories as _map_genres_to_categories,
)
from shelfr.metadata.mam.json_builder import (
    _build_series_list as _build_series_list,
)
from shelfr.metadata.mam.json_builder import (
    _get_mediainfo_string as _get_mediainfo_string,
)
from shelfr.metadata.mam.json_builder import (
    build_mam_json as build_mam_json,
)
from shelfr.metadata.mam.json_builder import (
    generate_mam_json_for_release as generate_mam_json_for_release,
)
from shelfr.metadata.mam.json_builder import (
    save_mam_json as save_mam_json,
)

__all__ = [
    # Public API
    "build_mam_json",
    "save_mam_json",
    "generate_mam_json_for_release",
    # Category constants
    "FICTION_GENRE_KEYWORDS",
    "NONFICTION_GENRE_KEYWORDS",
    # Internal helpers (exposed for testing/backward compat)
    "_infer_fiction_or_nonfiction",
    "_get_audiobook_category",
    "_map_genres_to_categories",
    "_build_series_list",
    "_get_mediainfo_string",
]
