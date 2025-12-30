"""Validation script for naming output quality.

This script analyzes the output of naming functions to flag suspicious results.
It can be run against the full library export or individual test cases.

Usage:
    python -m mamfast.utils.validate_naming --library samples/library_full.json
    python -m mamfast.utils.validate_naming --input "Test Title (Light Novel)"
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shelfr.config import NamingConfig

logger = logging.getLogger(__name__)


@dataclass
class ValidationIssue:
    """A single validation issue found in a naming result."""

    field: str  # title, series, subtitle
    input_value: str
    output_value: str
    issue_type: str
    severity: str  # error, warning, info
    message: str


@dataclass
class ValidationResult:
    """Result of validating a single book's naming."""

    book_id: str | None = None
    title: str | None = None
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        """Check if there are any errors."""
        return any(i.severity == "error" for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        """Check if there are any warnings."""
        return any(i.severity == "warning" for i in self.issues)


def validate_output(
    input_value: str,
    output_value: str,
    field_name: str,
    preserve_exact: list[str] | None = None,
) -> list[ValidationIssue]:
    """
    Validate a single naming output for suspicious results.

    Args:
        input_value: Original input string
        output_value: Cleaned output string
        field_name: Name of the field (title, series, subtitle)
        preserve_exact: List of strings that should never be modified

    Returns:
        List of validation issues found
    """
    issues: list[ValidationIssue] = []

    # Skip validation for empty inputs
    if not input_value:
        return issues

    # 1. Empty result after cleaning (unless input was also empty-ish)
    if not output_value and len(input_value.strip()) > 0:
        issues.append(
            ValidationIssue(
                field=field_name,
                input_value=input_value,
                output_value=output_value,
                issue_type="empty_result",
                severity="error",
                message="Cleaning produced empty result from non-empty input",
            )
        )

    # 2. Result shorter than 3 characters (suspicious for titles/series)
    if output_value and len(output_value) < 3 and len(input_value) >= 3:
        issues.append(
            ValidationIssue(
                field=field_name,
                input_value=input_value,
                output_value=output_value,
                issue_type="too_short",
                severity="warning",
                message=f"Result is very short ({len(output_value)} chars)",
            )
        )

    # 3. Leftover brackets [], () that are empty or unbalanced
    if output_value:
        # Empty brackets
        if re.search(r"\[\s*\]|\(\s*\)", output_value):
            issues.append(
                ValidationIssue(
                    field=field_name,
                    input_value=input_value,
                    output_value=output_value,
                    issue_type="empty_brackets",
                    severity="warning",
                    message="Contains empty brackets [] or ()",
                )
            )

        # Unbalanced brackets
        if output_value.count("[") != output_value.count("]"):
            issues.append(
                ValidationIssue(
                    field=field_name,
                    input_value=input_value,
                    output_value=output_value,
                    issue_type="unbalanced_brackets",
                    severity="warning",
                    message="Unbalanced square brackets",
                )
            )
        if output_value.count("(") != output_value.count(")"):
            issues.append(
                ValidationIssue(
                    field=field_name,
                    input_value=input_value,
                    output_value=output_value,
                    issue_type="unbalanced_parens",
                    severity="warning",
                    message="Unbalanced parentheses",
                )
            )

    # 4. Dangling punctuation
    if output_value:
        # Trailing punctuation (except period for abbreviations)
        if re.search(r"[,:\-;]\s*$", output_value):
            issues.append(
                ValidationIssue(
                    field=field_name,
                    input_value=input_value,
                    output_value=output_value,
                    issue_type="dangling_punctuation",
                    severity="warning",
                    message="Ends with dangling punctuation",
                )
            )
        # Leading punctuation
        if re.search(r"^\s*[,:\-;]", output_value):
            issues.append(
                ValidationIssue(
                    field=field_name,
                    input_value=input_value,
                    output_value=output_value,
                    issue_type="leading_punctuation",
                    severity="warning",
                    message="Starts with punctuation",
                )
            )

    # 5. Double spaces
    if output_value and "  " in output_value:
        issues.append(
            ValidationIssue(
                field=field_name,
                input_value=input_value,
                output_value=output_value,
                issue_type="double_spaces",
                severity="warning",
                message="Contains double spaces",
            )
        )

    # 6. Change too large (>50% length reduction is suspicious)
    if output_value and input_value:
        length_change = abs(len(output_value) - len(input_value)) / len(input_value)
        if length_change > 0.5 and len(input_value) > 10:
            issues.append(
                ValidationIssue(
                    field=field_name,
                    input_value=input_value,
                    output_value=output_value,
                    issue_type="large_change",
                    severity="info",
                    message=f"Large length change: {length_change:.0%} reduction",
                )
            )

    # 7. Preserve-exact drift check
    if preserve_exact and output_value:
        for preserved in preserve_exact:
            if preserved in input_value and preserved not in output_value:
                issues.append(
                    ValidationIssue(
                        field=field_name,
                        input_value=input_value,
                        output_value=output_value,
                        issue_type="preserve_exact_drift",
                        severity="error",
                        message=f"Preserve-exact entry '{preserved}' was modified",
                    )
                )

    return issues


def validate_library(
    library_path: Path,
    naming_config: NamingConfig | None = None,
) -> list[ValidationResult]:
    """
    Validate naming output against a full library export.

    Args:
        library_path: Path to library JSON export
        naming_config: Optional NamingConfig for preserve_exact checking

    Returns:
        List of validation results
    """
    from shelfr.utils.naming import filter_series, filter_title

    with open(library_path) as f:
        library = json.load(f)

    results: list[ValidationResult] = []
    preserve_exact = naming_config.preserve_exact if naming_config else []

    for book in library:
        result = ValidationResult(
            book_id=book.get("AudibleProductId"),
            title=book.get("Title"),
        )

        # Validate title (JSON context)
        title = book.get("Title", "")
        if title:
            title_output = filter_title(
                title,
                naming_config=naming_config,
                keep_volume=True,
            )
            result.issues.extend(validate_output(title, title_output, "title", preserve_exact))

        # Validate series
        series = book.get("SeriesNames", "")
        if series:
            series_output = filter_series(series, naming_config=naming_config)
            result.issues.extend(validate_output(series, series_output, "series", preserve_exact))

        # Validate subtitle
        subtitle = book.get("Subtitle", "")
        if subtitle:
            subtitle_output = filter_title(
                subtitle,
                naming_config=naming_config,
                keep_volume=True,
            )
            result.issues.extend(
                validate_output(subtitle, subtitle_output, "subtitle", preserve_exact)
            )

        if result.issues:
            results.append(result)

    return results


def print_validation_report(results: list[ValidationResult]) -> None:
    """Print a formatted validation report."""
    error_count = sum(1 for r in results if r.has_errors)
    warning_count = sum(1 for r in results if r.has_warnings and not r.has_errors)

    print("\n" + "=" * 70)
    print("NAMING VALIDATION REPORT")
    print("=" * 70)
    print(f"Total books with issues: {len(results)}")
    print(f"  - With errors:   {error_count}")
    print(f"  - With warnings: {warning_count}")
    print("=" * 70)

    # Group by issue type
    issue_counts: dict[str, int] = {}
    for result in results:
        for issue in result.issues:
            key = f"{issue.severity}:{issue.issue_type}"
            issue_counts[key] = issue_counts.get(key, 0) + 1

    print("\nIssue Summary:")
    for key in sorted(issue_counts.keys()):
        severity, issue_type = key.split(":")
        print(f"  [{severity.upper():7}] {issue_type}: {issue_counts[key]}")

    # Print detailed errors first
    if error_count > 0:
        print("\n" + "-" * 70)
        print("ERRORS (require attention):")
        print("-" * 70)
        for result in results:
            for issue in result.issues:
                if issue.severity == "error":
                    print(f"\n  Book: {result.title} ({result.book_id})")
                    print(f"  Field: {issue.field}")
                    print(f"  Type: {issue.issue_type}")
                    print(f"  Input:  {issue.input_value!r}")
                    print(f"  Output: {issue.output_value!r}")
                    print(f"  Message: {issue.message}")

    # Print sample warnings
    warning_results = [r for r in results if r.has_warnings]
    if warning_results and len(warning_results) <= 10:
        print("\n" + "-" * 70)
        print("WARNINGS:")
        print("-" * 70)
        for result in warning_results[:10]:
            for issue in result.issues:
                if issue.severity == "warning":
                    print(f"\n  Book: {result.title}")
                    print(f"  Field: {issue.field}")
                    print(f"  Type: {issue.issue_type}")
                    print(f"  Input:  {issue.input_value!r}")
                    print(f"  Output: {issue.output_value!r}")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Validate naming output quality")
    parser.add_argument(
        "--library",
        type=Path,
        help="Path to library JSON export",
    )
    parser.add_argument(
        "--input",
        type=str,
        help="Single input string to validate",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args()

    # Try to load naming config
    naming_config: NamingConfig | None = None
    try:
        from shelfr.config import get_settings

        settings = get_settings()
        naming_config = settings.naming
    except Exception:
        logger.warning("Could not load naming config, running without preserve_exact check")

    if args.library:
        results = validate_library(args.library, naming_config)
        print_validation_report(results)

        if any(r.has_errors for r in results):
            return 1
        return 0

    elif args.input:
        from shelfr.utils.naming import filter_title

        output = filter_title(args.input, naming_config=naming_config, keep_volume=True)
        issues = validate_output(
            args.input,
            output,
            "input",
            naming_config.preserve_exact if naming_config else [],
        )

        print(f"Input:  {args.input!r}")
        print(f"Output: {output!r}")
        if issues:
            print(f"\nIssues found: {len(issues)}")
            for issue in issues:
                print(f"  [{issue.severity}] {issue.issue_type}: {issue.message}")
            return 1
        else:
            print("\nNo issues found.")
            return 0

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
