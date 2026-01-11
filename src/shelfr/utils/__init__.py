"""Utility modules for shelfr."""

from shelfr.utils.editor import (
    EditorError,
    NoEditorError,
    edit_file,
    edit_json,
    edit_temp,
    edit_yaml,
    edit_yaml_temp,
    get_editor,
)
from shelfr.utils.fuzzy import (
    ChangeAnalysis,
    DuplicatePair,
    analyze_change,
    find_best_match,
    find_duplicates,
    find_duplicates_in_groups,
    find_matches,
    group_similar_series,
    is_suspicious_change,
    match_name,
    normalize_author_name,
    normalize_series_name,
    partial_ratio,
    similarity_ratio,
    weighted_ratio,
)
from shelfr.utils.mini_editor import (
    MiniEditorError,
    MiniEditorNotAvailableError,
    edit_file_inline,
    edit_json_inline,
    edit_yaml_inline,
    mini_edit,
)
from shelfr.utils.mini_editor import (
    check_available as is_tui_available,
)
from shelfr.utils.paths import safe_dirname, safe_filename, safe_filepath
from shelfr.utils.preview import (
    preview_bbcode,
    preview_diff,
    preview_file,
    preview_json,
    preview_markdown,
    preview_side_by_side,
    preview_validation_result,
    preview_yaml,
    preview_yaml_structure,
)

__all__ = [
    # Fuzzy matching utilities
    "ChangeAnalysis",
    "DuplicatePair",
    # Editor utilities
    "EditorError",
    # Mini editor utilities (Tier 2)
    "MiniEditorError",
    "MiniEditorNotAvailableError",
    "NoEditorError",
    "analyze_change",
    "edit_file",
    "edit_file_inline",
    "edit_json",
    "edit_json_inline",
    "edit_temp",
    "edit_yaml",
    "edit_yaml_inline",
    "edit_yaml_temp",
    "find_best_match",
    "find_duplicates",
    "find_duplicates_in_groups",
    "find_matches",
    "get_editor",
    "group_similar_series",
    "is_suspicious_change",
    "is_tui_available",
    "match_name",
    "mini_edit",
    "normalize_author_name",
    "normalize_series_name",
    "partial_ratio",
    # Preview utilities (Tier 2)
    "preview_bbcode",
    "preview_diff",
    "preview_file",
    "preview_json",
    "preview_markdown",
    "preview_side_by_side",
    "preview_validation_result",
    "preview_yaml",
    "preview_yaml_structure",
    "safe_dirname",
    "safe_filename",
    "safe_filepath",
    "similarity_ratio",
    "weighted_ratio",
]
