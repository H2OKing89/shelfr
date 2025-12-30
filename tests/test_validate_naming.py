"""Tests for validate_naming module."""

from __future__ import annotations

from pathlib import Path

import pytest

from shelfr.utils.validate_naming import (
    ValidationIssue,
    ValidationResult,
    validate_output,
)


class TestValidationIssue:
    """Tests for ValidationIssue dataclass."""

    def test_creation(self) -> None:
        """Test creating a ValidationIssue."""
        issue = ValidationIssue(
            field="title",
            input_value="Test Input",
            output_value="Test Output",
            issue_type="test_issue",
            severity="warning",
            message="Test message",
        )
        assert issue.field == "title"
        assert issue.input_value == "Test Input"
        assert issue.output_value == "Test Output"
        assert issue.issue_type == "test_issue"
        assert issue.severity == "warning"
        assert issue.message == "Test message"


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_default_creation(self) -> None:
        """Test creating with defaults."""
        result = ValidationResult()
        assert result.book_id is None
        assert result.title is None
        assert result.issues == []

    def test_with_values(self) -> None:
        """Test creating with values."""
        result = ValidationResult(book_id="B12345", title="Test Book")
        assert result.book_id == "B12345"
        assert result.title == "Test Book"

    def test_has_errors_false(self) -> None:
        """Test has_errors when no errors."""
        result = ValidationResult()
        assert result.has_errors is False

    def test_has_errors_true(self) -> None:
        """Test has_errors when errors present."""
        result = ValidationResult()
        result.issues.append(
            ValidationIssue(
                field="title",
                input_value="test",
                output_value="",
                issue_type="empty_result",
                severity="error",
                message="Test error",
            )
        )
        assert result.has_errors is True

    def test_has_errors_only_warnings(self) -> None:
        """Test has_errors when only warnings present."""
        result = ValidationResult()
        result.issues.append(
            ValidationIssue(
                field="title",
                input_value="test",
                output_value="t",
                issue_type="too_short",
                severity="warning",
                message="Test warning",
            )
        )
        assert result.has_errors is False

    def test_has_warnings_false(self) -> None:
        """Test has_warnings when no warnings."""
        result = ValidationResult()
        assert result.has_warnings is False

    def test_has_warnings_true(self) -> None:
        """Test has_warnings when warnings present."""
        result = ValidationResult()
        result.issues.append(
            ValidationIssue(
                field="title",
                input_value="test",
                output_value="t",
                issue_type="too_short",
                severity="warning",
                message="Test warning",
            )
        )
        assert result.has_warnings is True


class TestValidateOutput:
    """Tests for validate_output function."""

    def test_empty_input(self) -> None:
        """Test with empty input - should return no issues."""
        issues = validate_output("", "output", "title")
        assert issues == []

    def test_empty_result_from_non_empty_input(self) -> None:
        """Test empty result from non-empty input."""
        issues = validate_output("Test Input", "", "title")
        assert len(issues) == 1
        assert issues[0].issue_type == "empty_result"
        assert issues[0].severity == "error"

    def test_empty_result_from_whitespace_input(self) -> None:
        """Test empty result from whitespace-only input."""
        issues = validate_output("   ", "", "title")
        assert issues == []  # Whitespace-only input is OK to become empty

    def test_too_short_result(self) -> None:
        """Test result that's too short."""
        issues = validate_output("Long Title Here", "AB", "title")
        assert any(i.issue_type == "too_short" for i in issues)
        assert any(i.severity == "warning" for i in issues)

    def test_short_input_short_output_ok(self) -> None:
        """Test that short input producing short output is OK."""
        issues = validate_output("AB", "AB", "title")
        assert not any(i.issue_type == "too_short" for i in issues)

    def test_empty_brackets_square(self) -> None:
        """Test detection of empty square brackets."""
        issues = validate_output("Test [ ] Title", "Test [ ] Title", "title")
        assert any(i.issue_type == "empty_brackets" for i in issues)

    def test_empty_brackets_round(self) -> None:
        """Test detection of empty parentheses."""
        issues = validate_output("Test ( ) Title", "Test ( ) Title", "title")
        assert any(i.issue_type == "empty_brackets" for i in issues)

    def test_unbalanced_square_brackets(self) -> None:
        """Test detection of unbalanced square brackets."""
        issues = validate_output("Test [Title", "Test [Title", "title")
        assert any(i.issue_type == "unbalanced_brackets" for i in issues)

    def test_unbalanced_parentheses(self) -> None:
        """Test detection of unbalanced parentheses."""
        issues = validate_output("Test (Title", "Test (Title", "title")
        assert any(i.issue_type == "unbalanced_parens" for i in issues)

    def test_balanced_brackets_ok(self) -> None:
        """Test that balanced brackets don't flag."""
        issues = validate_output("Test [Vol. 1] Title", "Test [Vol. 1] Title", "title")
        assert not any(i.issue_type == "unbalanced_brackets" for i in issues)
        assert not any(i.issue_type == "unbalanced_parens" for i in issues)

    def test_trailing_punctuation(self) -> None:
        """Test detection of trailing punctuation."""
        issues = validate_output("Test Title-", "Test Title-", "title")
        assert any(i.issue_type == "dangling_punctuation" for i in issues)

    def test_trailing_comma(self) -> None:
        """Test detection of trailing comma."""
        issues = validate_output("Test Title,", "Test Title,", "title")
        assert any(i.issue_type == "dangling_punctuation" for i in issues)

    def test_trailing_colon(self) -> None:
        """Test detection of trailing colon."""
        issues = validate_output("Test Title:", "Test Title:", "title")
        assert any(i.issue_type == "dangling_punctuation" for i in issues)

    def test_leading_punctuation(self) -> None:
        """Test detection of leading punctuation."""
        issues = validate_output("-Test Title", "-Test Title", "title")
        assert any(i.issue_type == "leading_punctuation" for i in issues)

    def test_double_spaces(self) -> None:
        """Test detection of double spaces."""
        issues = validate_output("Test  Title", "Test  Title", "title")
        assert any(i.issue_type == "double_spaces" for i in issues)

    def test_single_spaces_ok(self) -> None:
        """Test that single spaces don't flag."""
        issues = validate_output("Test Title Here", "Test Title Here", "title")
        assert not any(i.issue_type == "double_spaces" for i in issues)

    def test_large_length_change(self) -> None:
        """Test detection of large length change."""
        issues = validate_output(
            "This Is A Very Long Title That Gets Much Shorter", "Short", "title"
        )
        assert any(i.issue_type == "large_change" for i in issues)

    def test_small_length_change_ok(self) -> None:
        """Test that small length changes don't flag."""
        issues = validate_output("Test Title", "Test Titl", "title")
        assert not any(i.issue_type == "large_change" for i in issues)

    def test_preserve_exact_drift(self) -> None:
        """Test detection of preserve_exact drift."""
        issues = validate_output(
            "Light Novel Title",
            "Novel Title",  # Light was removed
            "title",
            preserve_exact=["Light Novel"],
        )
        assert any(i.issue_type == "preserve_exact_drift" for i in issues)
        assert any(i.severity == "error" for i in issues)

    def test_preserve_exact_maintained(self) -> None:
        """Test that maintained preserve_exact doesn't flag."""
        issues = validate_output(
            "Light Novel Title",
            "Light Novel Title",
            "title",
            preserve_exact=["Light Novel"],
        )
        assert not any(i.issue_type == "preserve_exact_drift" for i in issues)

    def test_preserve_exact_not_in_input(self) -> None:
        """Test that preserve_exact not in input doesn't flag."""
        issues = validate_output(
            "Some Other Title",
            "Some Other Title",
            "title",
            preserve_exact=["Light Novel"],
        )
        assert not any(i.issue_type == "preserve_exact_drift" for i in issues)

    def test_multiple_issues(self) -> None:
        """Test that multiple issues can be detected."""
        # Has double spaces AND unbalanced brackets
        issues = validate_output("Test  [Title", "Test  [Title", "title")
        issue_types = {i.issue_type for i in issues}
        assert "unbalanced_brackets" in issue_types
        assert "double_spaces" in issue_types


class TestValidateLibrary:
    """Tests for validate_library function."""

    def test_validate_empty_library(self, tmp_path: Path) -> None:
        """Test validating empty library."""
        from shelfr.utils.validate_naming import validate_library

        lib_file = tmp_path / "library.json"
        lib_file.write_text("[]")

        results = validate_library(lib_file)
        assert results == []

    def test_validate_clean_library(self, tmp_path: Path) -> None:
        """Test validating library with clean entries."""
        import json

        from shelfr.utils.validate_naming import validate_library

        library = [
            {
                "AudibleProductId": "B12345",
                "Title": "Good Title",
                "SeriesNames": "Good Series",
                "Subtitle": "Good Subtitle",
            }
        ]
        lib_file = tmp_path / "library.json"
        lib_file.write_text(json.dumps(library))

        results = validate_library(lib_file)
        # Clean entries should have no issues
        assert len(results) == 0 or all(len(r.issues) == 0 for r in results)


class TestPrintValidationReport:
    """Tests for print_validation_report function."""

    def test_print_empty_results(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test printing empty results."""
        from shelfr.utils.validate_naming import print_validation_report

        print_validation_report([])
        captured = capsys.readouterr()
        assert "NAMING VALIDATION REPORT" in captured.out
        assert "Total books with issues: 0" in captured.out

    def test_print_with_errors(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test printing results with errors."""
        from shelfr.utils.validate_naming import print_validation_report

        result = ValidationResult(book_id="B12345", title="Test Book")
        result.issues.append(
            ValidationIssue(
                field="title",
                input_value="Test",
                output_value="",
                issue_type="empty_result",
                severity="error",
                message="Empty result",
            )
        )

        print_validation_report([result])
        captured = capsys.readouterr()
        assert "ERRORS (require attention)" in captured.out
        assert "empty_result" in captured.out

    def test_print_with_warnings(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test printing results with warnings."""
        from shelfr.utils.validate_naming import print_validation_report

        result = ValidationResult(book_id="B12345", title="Test Book")
        result.issues.append(
            ValidationIssue(
                field="title",
                input_value="Long Title",
                output_value="AB",
                issue_type="too_short",
                severity="warning",
                message="Too short",
            )
        )

        print_validation_report([result])
        captured = capsys.readouterr()
        assert "WARNINGS" in captured.out
        assert "too_short" in captured.out
