"""Rich console output for shelfr CLI.

This module provides backward compatibility by re-exporting
all UI components from the shelfr.ui package.

For new code, prefer importing directly from shelfr.ui:
    from shelfr.ui import console, print_success
    from shelfr.ui.tables import print_release_table

This file will continue to work for existing imports:
    from shelfr.console import console, print_success
"""

from __future__ import annotations

# Re-export everything from the ui package for backward compatibility
from shelfr.ui import (
    # Core
    SHELFR_THEME,
    # Dry run
    DryRunTransform,
    # Validation
    RuleTrace,
    StepResult,
    confirm,
    console,
    create_pipeline_progress,
    err_console,
    fatal_error,
    format_bitrate,
    format_duration,
    format_file_size,
    # Formatting
    format_mediainfo_stats,
    log_title_transform,
    print_change_analysis,
    print_check_category,
    print_config_section,
    print_directory_status,
    print_divider,
    print_dry_run,
    print_dry_run_header,
    print_dry_run_release,
    print_dry_run_summary,
    print_duplicate_pairs,
    print_error,
    print_error_summary,
    # Errors
    print_exception,
    # Panels
    print_header,
    print_info,
    # Progress
    print_pipeline_progress,
    print_release_details,
    print_release_table,
    print_rule_trace,
    print_status_table,
    print_step,
    print_substep,
    # Messages
    print_success,
    print_summary,
    print_suspicious_changes,
    print_trump_comparison_table,
    # Trumping
    print_trump_decision,
    print_trump_summary,
    print_validation_report,
    print_validation_summary,
    print_warning,
    print_workflow_summary,
    progress_context,
    # Tables
    render_libation_status,
    status,
    truncate_path,
)

__all__ = [
    "SHELFR_THEME",
    "DryRunTransform",
    "RuleTrace",
    "StepResult",
    "confirm",
    "console",
    "create_pipeline_progress",
    "err_console",
    "fatal_error",
    "format_bitrate",
    "format_duration",
    "format_file_size",
    "format_mediainfo_stats",
    "log_title_transform",
    "print_change_analysis",
    "print_check_category",
    "print_config_section",
    "print_directory_status",
    "print_divider",
    "print_dry_run",
    "print_dry_run_header",
    "print_dry_run_release",
    "print_dry_run_summary",
    "print_duplicate_pairs",
    "print_error",
    "print_error_summary",
    "print_exception",
    "print_header",
    "print_info",
    "print_pipeline_progress",
    "print_release_details",
    "print_release_table",
    "print_rule_trace",
    "print_status_table",
    "print_step",
    "print_substep",
    "print_success",
    "print_summary",
    "print_suspicious_changes",
    "print_trump_comparison_table",
    "print_trump_decision",
    "print_trump_summary",
    "print_validation_report",
    "print_validation_summary",
    "print_warning",
    "print_workflow_summary",
    "progress_context",
    "render_libation_status",
    "status",
    "truncate_path",
]
