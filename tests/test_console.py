"""Tests for console module - Rich UI output functions."""

from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from typing import Any
from unittest.mock import patch

import pytest
from rich.console import Console

from mamfast.console import (
    MAMFAST_THEME,
    StepResult,
    confirm,
    console,
    err_console,
    fatal_error,
    print_config_section,
    print_directory_status,
    print_divider,
    print_dry_run,
    print_error,
    print_header,
    print_info,
    print_release_table,
    print_status_table,
    print_step,
    print_substep,
    print_success,
    print_summary,
    print_warning,
    status,
)

# =============================================================================
# Test fixtures
# =============================================================================


@pytest.fixture
def mock_console():
    """Create a mock console for testing output."""
    output = StringIO()
    test_console = Console(file=output, force_terminal=True, theme=MAMFAST_THEME)
    return test_console, output


@pytest.fixture
def mock_release():
    """Create a mock release object for table tests."""

    @dataclass
    class MockRelease:
        author: str = "Test Author"
        title: str = "Test Title"
        asin: str = "B001234567"
        status: Any = None

    return MockRelease


# =============================================================================
# Test theme and console instances
# =============================================================================


class TestConsoleSetup:
    """Test console setup and theme."""

    def test_theme_has_required_styles(self):
        """Theme should have all required styles."""
        assert "info" in MAMFAST_THEME.styles
        assert "success" in MAMFAST_THEME.styles
        assert "warning" in MAMFAST_THEME.styles
        assert "error" in MAMFAST_THEME.styles
        assert "step" in MAMFAST_THEME.styles
        assert "title" in MAMFAST_THEME.styles
        assert "dim" in MAMFAST_THEME.styles
        assert "highlight" in MAMFAST_THEME.styles

    def test_console_instances_exist(self):
        """Console instances should be created."""
        assert console is not None
        assert err_console is not None

    def test_console_uses_stdout(self):
        """Main console should write to stdout."""
        assert console.stderr is False

    def test_err_console_uses_stderr(self):
        """Error console should write to stderr."""
        assert err_console.stderr is True


# =============================================================================
# Test StepResult dataclass
# =============================================================================


class TestStepResult:
    """Test StepResult dataclass."""

    def test_step_result_success(self):
        """StepResult should work with success=True."""
        result = StepResult(success=True, message="OK")
        assert result.success is True
        assert result.message == "OK"
        assert result.details is None

    def test_step_result_failure(self):
        """StepResult should work with success=False."""
        result = StepResult(success=False, message="Failed", details=["Error 1", "Error 2"])
        assert result.success is False
        assert result.message == "Failed"
        assert result.details == ["Error 1", "Error 2"]

    def test_step_result_defaults(self):
        """StepResult should have sensible defaults."""
        result = StepResult(success=True)
        assert result.message == ""
        assert result.details is None


# =============================================================================
# Test print functions
# =============================================================================


class TestPrintHeader:
    """Test print_header function."""

    def test_print_header_basic(self, capsys):
        """print_header should print a panel with title."""
        with patch.object(console, "print") as mock_print:
            print_header("Test Title")
            assert mock_print.call_count == 2  # Panel + empty line

    def test_print_header_with_subtitle(self):
        """print_header should include subtitle if provided."""
        with patch.object(console, "print") as mock_print:
            print_header("Test Title", subtitle="Test Subtitle")
            assert mock_print.call_count == 2

    def test_print_header_with_dry_run(self):
        """print_header should show DRY RUN indicator."""
        with patch.object(console, "print") as mock_print:
            print_header("Test Title", dry_run=True)
            assert mock_print.call_count == 2


class TestPrintStep:
    """Test print_step function."""

    def test_print_step(self):
        """print_step should format step number correctly."""
        with patch.object(console, "print") as mock_print:
            print_step(1, 3, "Processing")
            mock_print.assert_called_once()
            call_args = str(mock_print.call_args)
            assert "1/3" in call_args
            assert "Processing" in call_args


class TestPrintSubstep:
    """Test print_substep function."""

    def test_print_substep(self):
        """print_substep should print indented message."""
        with patch.object(console, "print") as mock_print:
            print_substep("Sub message")
            mock_print.assert_called_once()
            call_args = str(mock_print.call_args)
            assert "Sub message" in call_args

    def test_print_substep_custom_style(self):
        """print_substep should use custom style."""
        with patch.object(console, "print") as mock_print:
            print_substep("Sub message", style="info")
            mock_print.assert_called_once()


class TestPrintSuccess:
    """Test print_success function."""

    def test_print_success(self):
        """print_success should print checkmark and message."""
        with patch.object(console, "print") as mock_print:
            print_success("Operation complete")
            mock_print.assert_called_once()
            call_args = str(mock_print.call_args)
            assert "✓" in call_args
            assert "Operation complete" in call_args


class TestPrintError:
    """Test print_error function."""

    def test_print_error(self):
        """print_error should print X and message."""
        with patch.object(console, "print") as mock_print:
            print_error("Something failed")
            mock_print.assert_called_once()
            call_args = str(mock_print.call_args)
            assert "✗" in call_args
            assert "Something failed" in call_args


class TestPrintWarning:
    """Test print_warning function."""

    def test_print_warning(self):
        """print_warning should print warning message."""
        with patch.object(console, "print") as mock_print:
            print_warning("Be careful")
            mock_print.assert_called_once()
            call_args = str(mock_print.call_args)
            assert "Be careful" in call_args


class TestPrintInfo:
    """Test print_info function."""

    def test_print_info(self):
        """print_info should print info message."""
        with patch.object(console, "print") as mock_print:
            print_info("FYI")
            mock_print.assert_called_once()
            call_args = str(mock_print.call_args)
            assert "FYI" in call_args
            assert "→" in call_args


class TestPrintDryRun:
    """Test print_dry_run function."""

    def test_print_dry_run(self):
        """print_dry_run should print DRY RUN prefix."""
        with patch.object(console, "print") as mock_print:
            print_dry_run("Would do something")
            mock_print.assert_called_once()
            call_args = str(mock_print.call_args)
            assert "DRY RUN" in call_args
            assert "Would do something" in call_args


class TestPrintDivider:
    """Test print_divider function."""

    def test_print_divider(self):
        """print_divider should print a line of dashes."""
        with patch.object(console, "print") as mock_print:
            print_divider()
            mock_print.assert_called_once()
            call_args = str(mock_print.call_args)
            assert "─" in call_args


# =============================================================================
# Test print_summary function
# =============================================================================


class TestPrintSummary:
    """Test print_summary function."""

    def test_summary_all_success(self):
        """print_summary should show successful count."""
        with patch.object(console, "print"):
            # Should not raise
            print_summary(5, 0)

    def test_summary_all_failed(self):
        """print_summary should show failed count."""
        with patch.object(console, "print"):
            print_summary(0, 3)

    def test_summary_mixed(self):
        """print_summary should show both counts."""
        with patch.object(console, "print"):
            print_summary(2, 1)

    def test_summary_with_skipped(self):
        """print_summary should show skipped count."""
        with patch.object(console, "print"):
            print_summary(2, 1, skipped=3)

    def test_summary_with_duration(self):
        """print_summary should show duration."""
        with patch.object(console, "print"):
            print_summary(2, 0, duration=1.5)

    def test_summary_none_processed(self):
        """print_summary should handle zero counts."""
        with patch.object(console, "print"):
            print_summary(0, 0)


# =============================================================================
# Test print_release_table function
# =============================================================================


class TestPrintReleaseTable:
    """Test print_release_table function."""

    def test_release_table_empty(self):
        """print_release_table should handle empty list."""
        with patch.object(console, "print") as mock_print:
            print_release_table([])
            mock_print.assert_called_once()
            call_args = str(mock_print.call_args)
            assert "No releases found" in call_args

    def test_release_table_with_releases(self, mock_release):
        """print_release_table should display releases in table."""
        releases = [mock_release(), mock_release()]
        with patch.object(console, "print"):
            print_release_table(releases)

    def test_release_table_custom_title(self, mock_release):
        """print_release_table should use custom title."""
        releases = [mock_release()]
        with patch.object(console, "print"):
            print_release_table(releases, title="New Audiobooks")

    def test_release_table_with_status(self, mock_release):
        """print_release_table should show status column when requested."""

        @dataclass
        class MockStatus:
            value: str = "COMPLETED"

        release = mock_release()
        release.status = MockStatus()
        with patch.object(console, "print"):
            print_release_table([release], show_status=True)

    def test_release_table_with_status_none(self, mock_release):
        """print_release_table should handle None status when show_status=True."""
        release = mock_release()
        release.status = None
        with patch.object(console, "print"):
            print_release_table([release], show_status=True)

    def test_release_table_missing_fields(self):
        """print_release_table should handle missing fields."""

        @dataclass
        class PartialRelease:
            author: str | None = None
            title: str | None = None
            asin: str | None = None

        releases = [PartialRelease()]
        with patch.object(console, "print"):
            print_release_table(releases)


# =============================================================================
# Test print_config_section function
# =============================================================================


class TestPrintConfigSection:
    """Test print_config_section function."""

    def test_config_section(self):
        """print_config_section should print title and items."""
        with patch.object(console, "print") as mock_print:
            print_config_section("Settings", {"key1": "value1", "key2": "value2"})
            assert mock_print.call_count == 3  # title + 2 items


# =============================================================================
# Test print_status_table function
# =============================================================================


class TestPrintStatusTable:
    """Test print_status_table function."""

    def test_status_table_processed(self):
        """print_status_table should display processed releases."""
        processed = {
            "B001234567": {
                "author": "Author 1",
                "title": "Title 1",
                "processed_at": "2025-01-01T12:00:00",
            }
        }
        with patch.object(console, "print"):
            print_status_table(processed)

    def test_status_table_with_failed(self):
        """print_status_table should display failed releases."""
        processed = {}
        failed = {
            "B009876543": {
                "title": "Failed Book",
                "error": "Connection timeout",
            }
        }
        with patch.object(console, "print"):
            print_status_table(processed, failed=failed)

    def test_status_table_respects_limit(self):
        """print_status_table should respect limit parameter."""
        processed = {
            f"B00000000{i}": {
                "author": f"Author {i}",
                "title": f"Title {i}",
                "processed_at": f"2025-01-{i:02d}T12:00:00",
            }
            for i in range(1, 21)
        }
        with patch.object(console, "print"):
            print_status_table(processed, limit=5)

    def test_status_table_empty(self):
        """print_status_table should handle empty dicts."""
        with patch.object(console, "print"):
            print_status_table({})


# =============================================================================
# Test print_directory_status function
# =============================================================================


class TestPrintDirectoryStatus:
    """Test print_directory_status function."""

    def test_directory_exists(self):
        """print_directory_status should show checkmark for existing dir."""
        with patch.object(console, "print") as mock_print:
            print_directory_status("Library", "/path/to/lib", exists=True)
            call_args = str(mock_print.call_args)
            assert "✓" in call_args
            assert "Library" in call_args

    def test_directory_not_exists(self):
        """print_directory_status should show X for missing dir."""
        with patch.object(console, "print") as mock_print:
            print_directory_status("Library", "/path/to/lib", exists=False)
            call_args = str(mock_print.call_args)
            assert "✗" in call_args
            assert "not found" in call_args

    def test_directory_with_count(self):
        """print_directory_status should show item count."""
        with patch.object(console, "print") as mock_print:
            print_directory_status("Library", "/path/to/lib", exists=True, count=42)
            call_args = str(mock_print.call_args)
            assert "42 items" in call_args


# =============================================================================
# Test confirm function
# =============================================================================


class TestConfirm:
    """Test confirm function."""

    def test_confirm_yes(self):
        """confirm should return True for 'y' input."""
        with patch.object(console, "input", return_value="y"):
            assert confirm("Continue?") is True

    def test_confirm_yes_full(self):
        """confirm should return True for 'yes' input."""
        with patch.object(console, "input", return_value="yes"):
            assert confirm("Continue?") is True

    def test_confirm_no(self):
        """confirm should return False for 'n' input."""
        with patch.object(console, "input", return_value="n"):
            assert confirm("Continue?") is False

    def test_confirm_empty_default_false(self):
        """confirm should return default=False for empty input."""
        with patch.object(console, "input", return_value=""):
            assert confirm("Continue?", default=False) is False

    def test_confirm_empty_default_true(self):
        """confirm should return default=True for empty input."""
        with patch.object(console, "input", return_value=""):
            assert confirm("Continue?", default=True) is True

    def test_confirm_keyboard_interrupt(self):
        """confirm should return False on KeyboardInterrupt."""
        with (
            patch.object(console, "input", side_effect=KeyboardInterrupt),
            patch.object(console, "print"),
        ):
            assert confirm("Continue?") is False

    def test_confirm_eof_error(self):
        """confirm should return False on EOFError."""
        with (
            patch.object(console, "input", side_effect=EOFError),
            patch.object(console, "print"),
        ):
            assert confirm("Continue?") is False


# =============================================================================
# Test fatal_error function
# =============================================================================


class TestFatalError:
    """Test fatal_error function."""

    def test_fatal_error_basic(self):
        """fatal_error should print error message."""
        with patch.object(err_console, "print") as mock_print:
            fatal_error("Something went wrong")
            mock_print.assert_called_once()
            call_args = str(mock_print.call_args)
            assert "Error" in call_args
            assert "Something went wrong" in call_args

    def test_fatal_error_with_hint(self):
        """fatal_error should print hint if provided."""
        with patch.object(err_console, "print") as mock_print:
            fatal_error("Something went wrong", hint="Try this instead")
            assert mock_print.call_count == 2
            # Second call should have the hint
            hint_call = str(mock_print.call_args_list[1])
            assert "Try this instead" in hint_call


# =============================================================================
# Test status function
# =============================================================================


class TestStatus:
    """Test status convenience function."""

    def test_status_default_style(self):
        """status should use default info style."""
        with patch.object(console, "print") as mock_print:
            status("Hello world")
            mock_print.assert_called_once()
            call_args = str(mock_print.call_args)
            assert "Hello world" in call_args

    def test_status_custom_style(self):
        """status should use custom style."""
        with patch.object(console, "print") as mock_print:
            status("Warning message", style="warning")
            mock_print.assert_called_once()


# =============================================================================
# Phase 3: Test Rule Trace Functions
# =============================================================================


class TestRuleTrace:
    """Test RuleTrace dataclass and related functions."""

    def test_rule_trace_dataclass(self):
        """RuleTrace should store transformation data."""
        from mamfast.console import RuleTrace

        trace = RuleTrace(
            field="title",
            before="Original Title",
            after="Cleaned Title",
            rule_id="format_indicators",
            rule_type="phrase_removal",
        )
        assert trace.field == "title"
        assert trace.before == "Original Title"
        assert trace.after == "Cleaned Title"
        assert trace.rule_id == "format_indicators"
        assert trace.rule_type == "phrase_removal"

    def test_rule_trace_defaults(self):
        """RuleTrace should have None defaults for optional fields."""
        from mamfast.console import RuleTrace

        trace = RuleTrace(field="title", before="Before", after="After")
        assert trace.rule_id is None
        assert trace.rule_type is None


class TestLogTitleTransform:
    """Test log_title_transform function."""

    def test_no_output_when_not_verbose(self):
        """log_title_transform should not print when verbose=False."""
        from mamfast.console import log_title_transform

        with patch.object(console, "print") as mock_print:
            log_title_transform("title", "Before", "After", verbose=False)
            mock_print.assert_not_called()

    def test_no_output_when_no_change(self):
        """log_title_transform should not print when before==after."""
        from mamfast.console import log_title_transform

        with patch.object(console, "print") as mock_print:
            log_title_transform("title", "Same", "Same", verbose=True)
            mock_print.assert_not_called()

    def test_output_when_verbose_and_changed(self):
        """log_title_transform should print table when verbose and changed."""
        from mamfast.console import log_title_transform

        with patch.object(console, "print") as mock_print:
            log_title_transform("title", "Before", "After", verbose=True)
            assert mock_print.call_count >= 1

    def test_output_includes_rule_id(self):
        """log_title_transform should show rule_id if provided."""
        from mamfast.console import log_title_transform

        with patch.object(console, "print") as mock_print:
            log_title_transform("title", "Before", "After", rule_id="test_rule", verbose=True)
            # Should have table + rule line
            assert mock_print.call_count >= 2


class TestPrintRuleTrace:
    """Test print_rule_trace function."""

    def test_empty_traces(self):
        """print_rule_trace should handle empty list."""
        from mamfast.console import print_rule_trace

        with patch.object(console, "print") as mock_print:
            print_rule_trace([])
            mock_print.assert_called_once()
            assert "No" in str(mock_print.call_args)

    def test_no_changes_message(self):
        """print_rule_trace should show message when no changes made."""
        from mamfast.console import RuleTrace, print_rule_trace

        traces = [
            RuleTrace(field="title", before="Same", after="Same", rule_id="rule1"),
            RuleTrace(field="subtitle", before="Same2", after="Same2", rule_id="rule2"),
        ]
        with patch.object(console, "print") as mock_print:
            print_rule_trace(traces)
            call_str = str(mock_print.call_args)
            assert "No changes" in call_str

    def test_shows_changes_only(self):
        """print_rule_trace should only show traces where before != after."""
        from mamfast.console import RuleTrace, print_rule_trace

        traces = [
            RuleTrace(field="title", before="Old", after="New", rule_id="rule1"),
            RuleTrace(field="subtitle", before="Same", after="Same", rule_id="rule2"),
        ]
        with patch.object(console, "print") as mock_print:
            print_rule_trace(traces)
            # Should print table and summary
            assert mock_print.call_count >= 2


# =============================================================================
# Phase 3: Test Validation Report Functions
# =============================================================================


class TestPrintValidationReport:
    """Test print_validation_report function."""

    def test_empty_result(self):
        """print_validation_report should handle empty result."""
        from mamfast.console import print_validation_report
        from mamfast.validation import ValidationResult

        result = ValidationResult()
        with patch.object(console, "print") as mock_print:
            print_validation_report(result)
            assert mock_print.call_count >= 1

    def test_shows_all_checks(self):
        """print_validation_report should show all checks in table."""
        from mamfast.console import print_validation_report
        from mamfast.validation import CheckCategory, ValidationCheck, ValidationResult

        result = ValidationResult()
        result.add(
            ValidationCheck(
                name="test_check",
                passed=True,
                message="Test passed",
                category=CheckCategory.CONFIG,
            )
        )
        result.add(
            ValidationCheck(
                name="failed_check",
                passed=False,
                message="Test failed",
                severity="error",
                category=CheckCategory.PATHS,
            )
        )

        with patch.object(console, "print") as mock_print:
            print_validation_report(result)
            # Should print table and summary
            assert mock_print.call_count >= 2


class TestPrintValidationSummary:
    """Test print_validation_summary function."""

    def test_all_passed(self):
        """print_validation_summary should show checkmark when all passed."""
        from mamfast.console import print_validation_summary
        from mamfast.validation import CheckCategory, ValidationCheck, ValidationResult

        result = ValidationResult()
        result.add(
            ValidationCheck(name="check1", passed=True, message="OK", category=CheckCategory.CONFIG)
        )
        result.add(
            ValidationCheck(name="check2", passed=True, message="OK", category=CheckCategory.PATHS)
        )

        with patch.object(console, "print") as mock_print:
            print_validation_summary(result)
            call_str = str(mock_print.call_args)
            assert "✓" in call_str
            assert "2 passed" in call_str

    def test_with_errors(self):
        """print_validation_summary should show X when errors present."""
        from mamfast.console import print_validation_summary
        from mamfast.validation import CheckCategory, ValidationCheck, ValidationResult

        result = ValidationResult()
        result.add(
            ValidationCheck(name="check1", passed=True, message="OK", category=CheckCategory.CONFIG)
        )
        result.add(
            ValidationCheck(
                name="check2",
                passed=False,
                message="Failed",
                severity="error",
                category=CheckCategory.PATHS,
            )
        )

        with patch.object(console, "print") as mock_print:
            print_validation_summary(result)
            call_str = str(mock_print.call_args)
            assert "✗" in call_str
            assert "1 error" in call_str

    def test_pluralization_multiple_errors_and_warnings(self):
        """print_validation_summary should use plural form for multiple errors/warnings."""
        from mamfast.console import print_validation_summary
        from mamfast.validation import CheckCategory, ValidationCheck, ValidationResult

        result = ValidationResult()
        # Add 2 errors
        result.add(
            ValidationCheck(
                name="err1",
                passed=False,
                message="Fail",
                severity="error",
                category=CheckCategory.CONFIG,
            )
        )
        result.add(
            ValidationCheck(
                name="err2",
                passed=False,
                message="Fail",
                severity="error",
                category=CheckCategory.PATHS,
            )
        )
        # Add 3 warnings
        result.add(
            ValidationCheck(
                name="warn1",
                passed=False,
                message="Warn",
                severity="warning",
                category=CheckCategory.CONFIG,
            )
        )
        result.add(
            ValidationCheck(
                name="warn2",
                passed=False,
                message="Warn",
                severity="warning",
                category=CheckCategory.PATHS,
            )
        )
        result.add(
            ValidationCheck(
                name="warn3",
                passed=False,
                message="Warn",
                severity="warning",
                category=CheckCategory.SERVICES,
            )
        )

        with patch.object(console, "print") as mock_print:
            print_validation_summary(result)
            call_str = str(mock_print.call_args)
            assert "2 errors" in call_str  # Plural
            assert "3 warnings" in call_str  # Plural


class TestPrintCheckCategory:
    """Test print_check_category function."""

    def test_prints_category_checks(self):
        """print_check_category should print checks for given category."""
        from mamfast.console import print_check_category
        from mamfast.validation import CheckCategory, ValidationCheck, ValidationResult

        result = ValidationResult()
        result.add(
            ValidationCheck(name="check1", passed=True, message="OK", category=CheckCategory.CONFIG)
        )
        result.add(
            ValidationCheck(
                name="check2", passed=False, message="Failed", category=CheckCategory.CONFIG
            )
        )

        with patch.object(console, "print") as mock_print:
            print_check_category(result, CheckCategory.CONFIG)
            # Should print title + 2 check lines
            assert mock_print.call_count == 3

    def test_skips_empty_category(self):
        """print_check_category should not print if category has no checks."""
        from mamfast.console import print_check_category
        from mamfast.validation import CheckCategory, ValidationCheck, ValidationResult

        result = ValidationResult()
        result.add(
            ValidationCheck(name="check1", passed=True, message="OK", category=CheckCategory.CONFIG)
        )

        with patch.object(console, "print") as mock_print:
            print_check_category(result, CheckCategory.PATHS)
            mock_print.assert_not_called()


# =============================================================================
# Phase 3: Test Workflow Progress Functions
# =============================================================================


class TestPrintWorkflowSummary:
    """Test print_workflow_summary function."""

    def test_basic_stats(self):
        """print_workflow_summary should display stats table."""
        from mamfast.console import print_workflow_summary

        stats = {
            "discovered": 10,
            "staged": 8,
            "metadata": 8,
            "torrents": 7,
            "uploaded": 7,
            "skipped": 2,
            "errors": 1,
        }
        with patch.object(console, "print") as mock_print:
            print_workflow_summary(stats)
            assert mock_print.call_count >= 1

    def test_with_duration(self):
        """print_workflow_summary should show duration if provided."""
        from mamfast.console import print_workflow_summary

        stats = {"discovered": 5, "errors": 0}
        with patch.object(console, "print") as mock_print:
            print_workflow_summary(stats, duration=12.5)
            # Should print table + duration line
            assert mock_print.call_count >= 2
            call_str = str(mock_print.call_args)
            assert "12.5s" in call_str


class TestPrintReleaseDetails:
    """Test print_release_details function."""

    def test_basic_release(self):
        """print_release_details should show release in panel."""
        from mamfast.console import print_release_details

        @dataclass
        class MockRelease:
            asin: str = "B001234567"
            title: str = "Test Book"
            author: str = "Test Author"
            series: str = "Test Series"

        release = MockRelease()
        with patch.object(console, "print") as mock_print:
            print_release_details(release)
            mock_print.assert_called_once()

    def test_verbose_mode(self):
        """print_release_details should show extra fields in verbose mode."""
        from pathlib import Path

        from mamfast.console import print_release_details

        @dataclass
        class MockRelease:
            asin: str = "B001234567"
            title: str = "Test Book"
            source_dir: Path = Path("/source")
            staged_dir: Path = Path("/staged")

        release = MockRelease()
        with patch.object(console, "print") as mock_print:
            print_release_details(release, verbose=True)
            mock_print.assert_called_once()


class TestPrintPipelineProgress:
    """Test print_pipeline_progress function."""

    def test_basic_progress(self):
        """print_pipeline_progress should show stage progress."""
        from mamfast.console import print_pipeline_progress

        with patch.object(console, "print") as mock_print:
            print_pipeline_progress("Staging", 3, 10)
            mock_print.assert_called_once()
            call_str = str(mock_print.call_args)
            assert "3/10" in call_str
            assert "Staging" in call_str

    def test_with_release_name(self):
        """print_pipeline_progress should show release name."""
        from mamfast.console import print_pipeline_progress

        with patch.object(console, "print") as mock_print:
            print_pipeline_progress("Metadata", 1, 5, "Test Book Title")
            call_str = str(mock_print.call_args)
            assert "Test Book Title" in call_str

    def test_truncates_long_name(self):
        """print_pipeline_progress should truncate very long names."""
        from mamfast.console import print_pipeline_progress

        long_name = "A" * 100  # Very long name
        with patch.object(console, "print") as mock_print:
            print_pipeline_progress("Staging", 1, 1, long_name)
            call_str = str(mock_print.call_args)
            assert "..." in call_str


# =============================================================================
# Phase 3: Test Error Formatting Functions
# =============================================================================


class TestPrintException:
    """Test print_exception function."""

    def test_basic_exception(self):
        """print_exception should show error message."""
        from mamfast.console import err_console, print_exception

        error = ValueError("Test error message")
        with patch.object(err_console, "print") as mock_print:
            print_exception(error)
            assert mock_print.call_count >= 2  # Title + message
            call_str = str(mock_print.call_args_list)
            assert "ValueError" in call_str
            assert "Test error message" in call_str

    def test_with_context(self):
        """print_exception should show context dict."""
        from mamfast.console import err_console, print_exception

        error = RuntimeError("Failed")
        context = {"asin": "B001234567", "file": "/path/to/file"}
        with patch.object(err_console, "print") as mock_print:
            print_exception(error, context=context)
            call_str = str(mock_print.call_args_list)
            assert "asin" in call_str
            assert "B001234567" in call_str

    def test_without_traceback(self):
        """print_exception should skip traceback if requested."""
        from mamfast.console import err_console, print_exception

        error = ValueError("Test")
        with patch.object(err_console, "print") as mock_print:
            print_exception(error, show_traceback=False)
            # Should only have title + message, no traceback
            assert mock_print.call_count == 2


class TestPrintErrorSummary:
    """Test print_error_summary function."""

    def test_empty_errors(self):
        """print_error_summary should handle empty list."""
        from mamfast.console import err_console, print_error_summary

        with patch.object(err_console, "print") as mock_print:
            print_error_summary([])
            mock_print.assert_not_called()

    def test_multiple_errors(self):
        """print_error_summary should show table of errors."""
        from mamfast.console import err_console, print_error_summary

        errors = [
            ("Book 1", ValueError("Error 1")),
            ("Book 2", RuntimeError("Error 2")),
        ]
        with patch.object(err_console, "print") as mock_print:
            print_error_summary(errors)
            mock_print.assert_called_once()


# =============================================================================
# Phase 3: Test Progress Context Manager
# =============================================================================


class TestProgressContext:
    """Test progress_context context manager."""

    def test_progress_context_creates_progress(self):
        """progress_context should yield a Progress and TaskID."""
        from mamfast.console import progress_context

        with progress_context("Test task", total=5) as (progress, task):
            assert progress is not None
            assert task is not None
            # Advance and verify no errors
            progress.update(task, advance=1)

    def test_progress_context_with_none_total(self):
        """progress_context should work with indeterminate total."""
        from mamfast.console import progress_context

        with progress_context("Indeterminate task", total=None) as (progress, task):
            assert progress is not None
            # Update description
            progress.update(task, description="Still working...")


class TestCreatePipelineProgress:
    """Test create_pipeline_progress function."""

    def test_creates_progress_instance(self):
        """create_pipeline_progress should return a Progress instance."""
        from rich.progress import Progress

        from mamfast.console import create_pipeline_progress

        progress = create_pipeline_progress()
        assert isinstance(progress, Progress)

    def test_can_use_as_context_manager(self):
        """create_pipeline_progress result should work as context manager."""
        from mamfast.console import create_pipeline_progress

        with create_pipeline_progress() as progress:
            task = progress.add_task("[cyan]Test", total=3)
            progress.update(task, advance=1)
            progress.update(task, advance=2)


# =============================================================================
# Dry Run Output Tests (Phase 3)
# =============================================================================


class TestDryRunTransform:
    """Test DryRunTransform dataclass."""

    def test_create_transform(self):
        """DryRunTransform should store field transformation data."""
        from mamfast.console import DryRunTransform

        t = DryRunTransform(
            field="title",
            before="Overlord (Light Novel)",
            after="Overlord",
            rule="format_indicators",
        )
        assert t.field == "title"
        assert t.before == "Overlord (Light Novel)"
        assert t.after == "Overlord"
        assert t.rule == "format_indicators"

    def test_create_transform_without_rule(self):
        """DryRunTransform should work without rule specified."""
        from mamfast.console import DryRunTransform

        t = DryRunTransform(field="author", before="John Smith", after="John Smith")
        assert t.rule is None


class TestPrintDryRunHeader:
    """Test print_dry_run_header function."""

    def test_single_release(self):
        """print_dry_run_header should use singular for 1 release."""
        from mamfast.console import print_dry_run_header

        with patch.object(console, "print") as mock_print:
            print_dry_run_header(1)
            # The Panel contains the text
            assert mock_print.call_count >= 1
            # Check that Panel was created with "1 release" (singular)
            panel_arg = mock_print.call_args_list[0][0][0]
            assert "1 release" in str(panel_arg.renderable)

    def test_multiple_releases(self):
        """print_dry_run_header should use plural for multiple releases."""
        from mamfast.console import print_dry_run_header

        with patch.object(console, "print") as mock_print:
            print_dry_run_header(5)
            panel_arg = mock_print.call_args_list[0][0][0]
            assert "5 releases" in str(panel_arg.renderable)


class TestPrintDryRunRelease:
    """Test print_dry_run_release function."""

    def test_with_transforms(self):
        """print_dry_run_release should display transforms table."""
        from mamfast.console import DryRunTransform, print_dry_run_release

        transforms = [
            DryRunTransform(
                field="title",
                before="Overlord (Light Novel)",
                after="Overlord",
                rule="format_indicators",
            ),
        ]

        with patch.object(console, "print") as mock_print:
            print_dry_run_release(transforms, release_title="Overlord")
            assert mock_print.called

    def test_with_no_changes(self):
        """print_dry_run_release should show source/target when paths provided."""
        from mamfast.console import DryRunTransform, print_dry_run_release

        transforms = [
            DryRunTransform(field="title", before="Same", after="Same"),
        ]

        with patch.object(console, "print") as mock_print:
            print_dry_run_release(transforms, source_path="My Folder", target_path="My Folder")
            call_str = str(mock_print.call_args_list)
            assert "Source" in call_str
            assert "unchanged" in call_str

    def test_shows_different_target(self):
        """print_dry_run_release should highlight different target path."""
        from mamfast.console import DryRunTransform, print_dry_run_release

        transforms = [
            DryRunTransform(field="title", before="Old", after="New"),
        ]

        with patch.object(console, "print") as mock_print:
            print_dry_run_release(
                transforms,
                source_path="Old Folder",
                target_path="New Folder",
            )
            call_str = str(mock_print.call_args_list)
            assert "Source" in call_str
            assert "Target" in call_str

    def test_filters_unchanged_fields(self):
        """print_dry_run_release should only show fields that changed."""
        from mamfast.console import DryRunTransform, print_dry_run_release

        transforms = [
            DryRunTransform(field="title", before="Same", after="Same"),
            DryRunTransform(field="author", before="Old Author", after="New Author"),
        ]

        with patch.object(console, "print") as mock_print:
            print_dry_run_release(transforms)
            # Should be called (table output) but only show changed fields
            assert mock_print.called


class TestPrintDryRunSummary:
    """Test print_dry_run_summary function."""

    def test_summary_output(self):
        """print_dry_run_summary should display counts."""
        from mamfast.console import print_dry_run_summary

        with patch.object(console, "print") as mock_print:
            print_dry_run_summary(processed=10, would_change=3, no_change=7)
            call_str = str(mock_print.call_args)
            assert "10 releases" in call_str
            assert "3" in call_str
            assert "7" in call_str
