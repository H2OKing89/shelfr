"""Rich console output for MAMFast CLI.

This module provides backward compatibility by re-exporting
all UI components from the new mamfast.ui package.

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
    MAMFAST_THEME,
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
    # Core
    "MAMFAST_THEME",
    "console",
    "err_console",
    "StepResult",
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
]
