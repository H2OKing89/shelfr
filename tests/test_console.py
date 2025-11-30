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
