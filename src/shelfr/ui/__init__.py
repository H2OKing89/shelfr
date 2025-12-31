"""MAMFast UI - Beautiful Rich console output components.

This package provides a comprehensive set of Rich-based UI components
for beautiful terminal output throughout MAMFast.

Modules:
    core: Console instance, theme, and base configuration
    messages: Simple print helpers (success, error, warning, info)
    panels: Headers, panels, dividers, and boxed content
    tables: Table formatters for releases, status, configs
    progress: Progress bars, spinners, and pipeline progress
    validation: Validation report and check output
    errors: Exception and error formatting
    dryrun: Dry-run specific output helpers
    trumping: Trumping comparison and decision output
    formatting: MediaInfo and path formatting helpers

Usage:
    from shelfr.ui import console, print_success, print_header
    from shelfr.ui.tables import print_release_table
    from shelfr.ui.progress import progress_context
"""

from __future__ import annotations

# Banner and version
from shelfr.ui.banner import (
    BANNER_ART,
    get_version,
    get_version_string,
    make_banner_text,
    print_banner,
)

# Core - always import these
from shelfr.ui.core import (
    MAMFAST_THEME,
    StepResult,
    console,
    err_console,
)

# Dry run
from shelfr.ui.dryrun import (
    DryRunTransform,
    print_dry_run_header,
    print_dry_run_release,
    print_dry_run_summary,
)

# Errors
from shelfr.ui.errors import (
    print_error_summary,
    print_exception,
)

# Formatting
from shelfr.ui.formatting import (
    format_bitrate,
    format_duration,
    format_file_size,
    format_mediainfo_stats,
    truncate_path,
)

# Icons - standardized icon system
from shelfr.ui.icons import (
    ASCII_ICONS,
    EMOJI_ICONS,
    UNICODE_ICONS,
    Icons,
    get_icon_mode,
    get_icons,
    icons,
    set_icon_mode,
)

# Messages - frequently used print helpers
from shelfr.ui.messages import (
    confirm,
    fatal_error,
    print_dry_run,
    print_error,
    print_info,
    print_step,
    print_substep,
    print_success,
    print_warning,
    status,
)

# Panels - headers and panels
from shelfr.ui.panels import (
    print_config_section,
    print_directory_status,
    print_divider,
    print_header,
    print_summary,
)

# Progress
from shelfr.ui.progress import (
    create_pipeline_progress,
    print_pipeline_progress,
    progress_context,
)

# Tables
from shelfr.ui.tables import (
    print_duplicate_pairs,
    print_release_details,
    print_release_table,
    print_status_table,
    print_suspicious_changes,
    print_workflow_summary,
    render_libation_status,
)

# Trumping
from shelfr.ui.trumping import (
    print_trump_comparison_table,
    print_trump_decision,
    print_trump_summary,
)

# Validation
from shelfr.ui.validation import (
    RuleTrace,
    log_title_transform,
    print_change_analysis,
    print_check_category,
    print_rule_trace,
    print_validation_report,
    print_validation_summary,
)

__all__ = [
    # Core
    "MAMFAST_THEME",
    "console",
    "err_console",
    "StepResult",
    # Banner
    "BANNER_ART",
    "get_version",
    "get_version_string",
    "make_banner_text",
    "print_banner",
    # Messages
    "print_success",
    "print_error",
    "print_warning",
    "print_info",
    "print_step",
    "print_substep",
    "print_dry_run",
    "status",
    "confirm",
    "fatal_error",
    # Panels
    "print_header",
    "print_divider",
    "print_summary",
    "print_config_section",
    "print_directory_status",
    # Tables
    "render_libation_status",
    "print_release_table",
    "print_status_table",
    "print_release_details",
    "print_workflow_summary",
    "print_duplicate_pairs",
    "print_suspicious_changes",
    # Progress
    "print_pipeline_progress",
    "progress_context",
    "create_pipeline_progress",
    # Validation
    "RuleTrace",
    "log_title_transform",
    "print_rule_trace",
    "print_validation_report",
    "print_validation_summary",
    "print_check_category",
    "print_change_analysis",
    # Errors
    "print_exception",
    "print_error_summary",
    # Dry run
    "DryRunTransform",
    "print_dry_run_header",
    "print_dry_run_release",
    "print_dry_run_summary",
    # Trumping
    "print_trump_decision",
    "print_trump_comparison_table",
    "print_trump_summary",
    # Formatting
    "format_mediainfo_stats",
    "truncate_path",
    "format_duration",
    "format_bitrate",
    "format_file_size",
    # Icons
    "icons",
    "Icons",
    "get_icons",
    "set_icon_mode",
    "get_icon_mode",
    "UNICODE_ICONS",
    "ASCII_ICONS",
    "EMOJI_ICONS",
]
