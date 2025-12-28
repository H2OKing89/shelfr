"""Tests for input validation utilities (utils/validation.py)."""

from __future__ import annotations

import argparse

import pytest

from mamfast.utils.validation import (
    ASIN_PATTERN,
    is_valid_asin,
    validate_asin,
    validate_asin_list,
)


class TestAsinPattern:
    """Test ASIN regex pattern."""

    def test_valid_asins(self) -> None:
        """Test pattern matches valid ASINs."""
        valid_asins = [
            "B0DK9T5P28",
            "B017V4IM1G",
            "B000000000",
            "BZZZZZZZZ9",
            "B0ABCDEFGH",
        ]
        for asin in valid_asins:
            assert ASIN_PATTERN.match(asin), f"Should match: {asin}"

    def test_invalid_asins(self) -> None:
        """Test pattern rejects invalid ASINs."""
        invalid_asins = [
            "A0DK9T5P28",  # Wrong first letter
            "B0DK9T5P2",  # Too short (9 chars)
            "B0DK9T5P28X",  # Too long (11 chars)
            "b0dk9t5p28",  # Lowercase (pattern is case-sensitive)
            "B0DK9T5P2!",  # Special character
            "",  # Empty
            "B0DK 9T5P2",  # Space
        ]
        for asin in invalid_asins:
            assert not ASIN_PATTERN.match(asin), f"Should not match: {asin}"


class TestValidateAsin:
    """Test validate_asin function for argparse."""

    def test_valid_uppercase(self) -> None:
        """Test valid uppercase ASIN is returned as-is."""
        assert validate_asin("B0DK9T5P28") == "B0DK9T5P28"

    def test_valid_lowercase_normalized(self) -> None:
        """Test lowercase ASIN is normalized to uppercase."""
        assert validate_asin("b0dk9t5p28") == "B0DK9T5P28"

    def test_valid_with_whitespace_trimmed(self) -> None:
        """Test whitespace is trimmed from valid ASIN."""
        assert validate_asin(" B0DK9T5P28 ") == "B0DK9T5P28"
        assert validate_asin("\tB0DK9T5P28\n") == "B0DK9T5P28"

    def test_invalid_too_short(self) -> None:
        """Test too-short ASIN raises ArgumentTypeError."""
        with pytest.raises(argparse.ArgumentTypeError) as exc_info:
            validate_asin("B0DK9T5P2")
        assert "Invalid ASIN format" in str(exc_info.value)
        assert "10 characters" in str(exc_info.value)

    def test_invalid_too_long(self) -> None:
        """Test too-long ASIN raises ArgumentTypeError."""
        with pytest.raises(argparse.ArgumentTypeError) as exc_info:
            validate_asin("B0DK9T5P28X")
        assert "Invalid ASIN format" in str(exc_info.value)

    def test_invalid_wrong_prefix(self) -> None:
        """Test ASIN without 'B' prefix raises ArgumentTypeError."""
        with pytest.raises(argparse.ArgumentTypeError) as exc_info:
            validate_asin("A0DK9T5P28")
        assert "Invalid ASIN format" in str(exc_info.value)
        assert "starting with 'B'" in str(exc_info.value)

    def test_invalid_special_chars(self) -> None:
        """Test ASIN with special characters raises ArgumentTypeError."""
        with pytest.raises(argparse.ArgumentTypeError) as exc_info:
            validate_asin("B0DK9T5P2!")
        assert "Invalid ASIN format" in str(exc_info.value)

    def test_invalid_empty(self) -> None:
        """Test empty string raises ArgumentTypeError."""
        with pytest.raises(argparse.ArgumentTypeError):
            validate_asin("")


class TestValidateAsinList:
    """Test validate_asin_list function."""

    def test_delegates_to_validate_asin(self) -> None:
        """Test validate_asin_list delegates to validate_asin."""
        assert validate_asin_list("B0DK9T5P28") == "B0DK9T5P28"
        assert validate_asin_list("b0dk9t5p28") == "B0DK9T5P28"

    def test_invalid_raises(self) -> None:
        """Test invalid ASIN raises ArgumentTypeError."""
        with pytest.raises(argparse.ArgumentTypeError):
            validate_asin_list("invalid")


class TestIsValidAsin:
    """Test is_valid_asin helper function."""

    def test_valid_asin_returns_true(self) -> None:
        """Test valid ASINs return True."""
        assert is_valid_asin("B0DK9T5P28") is True
        assert is_valid_asin("b0dk9t5p28") is True  # Case insensitive
        assert is_valid_asin(" B0DK9T5P28 ") is True  # Whitespace handled

    def test_invalid_asin_returns_false(self) -> None:
        """Test invalid ASINs return False."""
        assert is_valid_asin("invalid") is False
        assert is_valid_asin("B0DK9T5P2") is False
        assert is_valid_asin("") is False
        assert is_valid_asin("A0DK9T5P28") is False

    def test_none_returns_false(self) -> None:
        """Test None-like values return False."""
        assert is_valid_asin("") is False


class TestCliIntegration:
    """Test ASIN validation integrates correctly with CLI parsers.

    Note: These tests use the argparse-based CLI (cli_argparse) for backwards
    compatibility testing. The main CLI has been migrated to Typer.
    """

    def test_prepare_asin_validation(self) -> None:
        """Test prepare command validates ASIN."""
        from mamfast.cli_argparse import build_parser

        parser = build_parser()

        # Valid ASIN works
        args = parser.parse_args(["prepare", "--asin", "B0DK9T5P28"])
        assert args.asin == "B0DK9T5P28"

        # Lowercase normalized
        args = parser.parse_args(["prepare", "-a", "b0dk9t5p28"])
        assert args.asin == "B0DK9T5P28"

    def test_metadata_asin_validation(self) -> None:
        """Test metadata command validates ASIN."""
        from mamfast.cli_argparse import build_parser

        parser = build_parser()
        args = parser.parse_args(["metadata", "--asin", "B0DK9T5P28"])
        assert args.asin == "B0DK9T5P28"

    def test_torrent_asin_validation(self) -> None:
        """Test torrent command validates ASIN."""
        from mamfast.cli_argparse import build_parser

        parser = build_parser()
        args = parser.parse_args(["torrent", "--asin", "B0DK9T5P28"])
        assert args.asin == "B0DK9T5P28"

    def test_validate_asin_validation(self) -> None:
        """Test validate command validates ASIN."""
        from mamfast.cli_argparse import build_parser

        parser = build_parser()
        args = parser.parse_args(["validate", "--asin", "B0DK9T5P28"])
        assert args.asin == "B0DK9T5P28"

    def test_dry_run_asin_validation(self) -> None:
        """Test dry-run command validates ASIN."""
        from mamfast.cli_argparse import build_parser

        parser = build_parser()
        args = parser.parse_args(["dry-run", "--asin", "B0DK9T5P28"])
        assert args.asin == "B0DK9T5P28"

    def test_check_suspicious_asin_validation(self) -> None:
        """Test check-suspicious command validates ASIN."""
        from mamfast.cli_argparse import build_parser

        parser = build_parser()
        args = parser.parse_args(["check-suspicious", "--asin", "B0DK9T5P28"])
        assert args.asin == "B0DK9T5P28"

    def test_abs_restore_asin_validation(self) -> None:
        """Test abs-restore command validates ASIN."""
        from mamfast.cli_argparse import build_parser

        parser = build_parser()
        args = parser.parse_args(["abs-restore", "--asin", "B0DK9T5P28"])
        assert args.asin == "B0DK9T5P28"

    def test_invalid_asin_rejected_by_parser(self) -> None:
        """Test invalid ASIN causes parser to exit."""
        from mamfast.cli_argparse import build_parser

        parser = build_parser()

        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["prepare", "--asin", "invalid"])
        assert exc_info.value.code == 2  # argparse error exit code
