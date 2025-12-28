"""Tests for Libation CLI wrapper commands."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mamfast.commands.libation import (
    LibationCommandResult,
    _get_library_status,
    _run_libation_cmd,
    add_libation_parser,
    cmd_libation,
    cmd_libation_help,
    cmd_libation_liberate,
    cmd_libation_scan,
    cmd_libation_search,
    cmd_libation_settings,
    print_hint_box,
    print_libation_header,
    print_status_dashboard,
)


class TestLibationCommandResult:
    """Tests for LibationCommandResult dataclass."""

    def test_success_result(self) -> None:
        """Test successful command result."""
        result = LibationCommandResult(success=True, returncode=0, stdout="output")
        assert result.success is True
        assert result.returncode == 0
        assert result.stdout == "output"

    def test_failed_result(self) -> None:
        """Test failed command result."""
        result = LibationCommandResult(
            success=False, returncode=1, stderr="error", error_message="failed"
        )
        assert result.success is False
        assert result.returncode == 1
        assert result.error_message == "failed"


class TestGetLibraryStatus:
    """Tests for _get_library_status helper."""

    def test_counts_statuses(self) -> None:
        """Test status counting from books list."""
        books = [
            {"BookStatus": "Liberated"},
            {"BookStatus": "Liberated"},
            {"BookStatus": "NotLiberated"},
            {"BookStatus": "Error"},
        ]
        status = _get_library_status(books)
        assert status["Liberated"] == 2
        assert status["NotLiberated"] == 1
        assert status["Error"] == 1

    def test_empty_list(self) -> None:
        """Test with empty books list."""
        status = _get_library_status([])
        assert status == {}

    def test_unknown_status(self) -> None:
        """Test with unknown status values."""
        books = [{"BookStatus": "CustomStatus"}, {"BookStatus": "CustomStatus"}]
        status = _get_library_status(books)
        assert status["CustomStatus"] == 2


class TestAddLibationParser:
    """Tests for parser setup."""

    def test_adds_libation_command(self) -> None:
        """Test that libation command is added to parser."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        add_libation_parser(subparsers)

        # Parse libation command
        args = parser.parse_args(["libation"])
        assert args.command == "libation"

    def test_scan_subcommand(self) -> None:
        """Test scan subcommand parsing."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        add_libation_parser(subparsers)

        args = parser.parse_args(["libation", "scan", "--liberate"])
        assert args.libation_cmd == "scan"
        assert args.liberate is True

    def test_liberate_subcommand(self) -> None:
        """Test liberate subcommand parsing."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        add_libation_parser(subparsers)

        args = parser.parse_args(["libation", "liberate", "--asin", "B0DK9T5P28", "-f"])
        assert args.libation_cmd == "liberate"
        assert args.asin == "B0DK9T5P28"
        assert args.force is True

    def test_search_subcommand(self) -> None:
        """Test search subcommand parsing."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        add_libation_parser(subparsers)

        args = parser.parse_args(["libation", "search", "Brandon Sanderson", "-n", "50"])
        assert args.libation_cmd == "search"
        assert args.query == "Brandon Sanderson"
        assert args.limit == 50

    def test_export_subcommand(self) -> None:
        """Test export subcommand parsing."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        add_libation_parser(subparsers)

        args = parser.parse_args(["libation", "export", "-o", "library.csv", "-f", "csv"])
        assert args.libation_cmd == "export"
        assert args.output == "library.csv"
        assert args.format == "csv"


class TestRunLibationCmd:
    """Tests for _run_libation_cmd helper."""

    @patch("mamfast.commands.libation.subprocess.run")
    def test_successful_command(self, mock_run: MagicMock) -> None:
        """Test successful command execution."""
        mock_run.return_value = MagicMock(returncode=0, stdout="output", stderr="")

        result = _run_libation_cmd("TestContainer", "scan")

        assert result.success is True
        assert result.returncode == 0
        assert result.stdout == "output"

    @patch("mamfast.commands.libation.subprocess.run")
    def test_failed_command(self, mock_run: MagicMock) -> None:
        """Test failed command execution."""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")

        result = _run_libation_cmd("TestContainer", "scan")

        assert result.success is False
        assert result.returncode == 1

    @patch("mamfast.commands.libation.subprocess.run")
    def test_timeout(self, mock_run: MagicMock) -> None:
        """Test command timeout."""
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=10)

        result = _run_libation_cmd("TestContainer", "scan", timeout=10)

        assert result.success is False
        assert result.returncode == -1
        assert "timed out" in result.error_message


class TestCmdLibationHelp:
    """Tests for help command."""

    def test_help_returns_zero(self) -> None:
        """Test help command returns success."""
        args = argparse.Namespace()
        result = cmd_libation_help(args)
        assert result == 0


class TestCmdLibationScan:
    """Tests for scan command."""

    @patch("mamfast.config.reload_settings")
    def test_dry_run_mode(self, mock_settings: MagicMock) -> None:
        """Test scan in dry-run mode."""
        mock_settings.return_value = MagicMock(libation_container="Libation")
        args = argparse.Namespace(dry_run=True, liberate=False, config=Path("config.yaml"))

        result = cmd_libation_scan(args)

        assert result == 0

    @patch("mamfast.config.reload_settings")
    def test_dry_run_with_liberate(self, mock_settings: MagicMock) -> None:
        """Test scan --liberate in dry-run mode."""
        mock_settings.return_value = MagicMock(libation_container="Libation")
        args = argparse.Namespace(dry_run=True, liberate=True, config=Path("config.yaml"))

        result = cmd_libation_scan(args)

        assert result == 0

    @patch("mamfast.config.reload_settings")
    def test_config_not_found(self, mock_settings: MagicMock) -> None:
        """Test scan with missing config."""
        mock_settings.side_effect = FileNotFoundError("config not found")
        args = argparse.Namespace(dry_run=False, liberate=False, config=Path("missing.yaml"))

        result = cmd_libation_scan(args)

        assert result == 1


class TestCmdLibationLiberate:
    """Tests for liberate command."""

    @patch("mamfast.config.reload_settings")
    def test_dry_run_mode(self, mock_settings: MagicMock) -> None:
        """Test liberate in dry-run mode."""
        mock_settings.return_value = MagicMock(libation_container="Libation")
        args = argparse.Namespace(
            dry_run=True, asin=None, force=False, config=Path("config.yaml")
        )

        result = cmd_libation_liberate(args)

        assert result == 0

    @patch("mamfast.config.reload_settings")
    def test_dry_run_with_asin(self, mock_settings: MagicMock) -> None:
        """Test liberate with specific ASIN in dry-run mode."""
        mock_settings.return_value = MagicMock(libation_container="Libation")
        args = argparse.Namespace(
            dry_run=True, asin="B0DK9T5P28", force=True, config=Path("config.yaml")
        )

        result = cmd_libation_liberate(args)

        assert result == 0


class TestCmdLibationSearch:
    """Tests for search command."""

    @patch("mamfast.commands.libation._run_libation_cmd")
    @patch("mamfast.config.reload_settings")
    def test_search_success(
        self, mock_settings: MagicMock, mock_run_cmd: MagicMock
    ) -> None:
        """Test successful search."""
        mock_settings.return_value = MagicMock(libation_container="Libation")
        mock_run_cmd.return_value = LibationCommandResult(
            success=True, returncode=0, stdout="Search results..."
        )
        args = argparse.Namespace(
            query="Brandon Sanderson", limit=20, config=Path("config.yaml")
        )

        result = cmd_libation_search(args)

        assert result == 0
        mock_run_cmd.assert_called_once()


class TestCmdLibationSettings:
    """Tests for settings command."""

    @patch("mamfast.commands.libation._run_libation_cmd")
    @patch("mamfast.config.reload_settings")
    def test_settings_success(
        self, mock_settings: MagicMock, mock_run_cmd: MagicMock
    ) -> None:
        """Test successful settings retrieval."""
        mock_settings.return_value = MagicMock(libation_container="Libation")
        mock_run_cmd.return_value = LibationCommandResult(
            success=True, returncode=0, stdout="| Setting | Value |"
        )
        args = argparse.Namespace(
            setting=None, list_enum=False, config=Path("config.yaml")
        )

        result = cmd_libation_settings(args)

        assert result == 0


class TestPrintFunctions:
    """Tests for Rich print helper functions."""

    def test_print_libation_header(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test header printing doesn't crash."""
        # Just verify no exceptions are raised
        print_libation_header("Test Title", "Test subtitle", dry_run=True)

    def test_print_hint_box(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test hint box printing doesn't crash."""
        print_hint_box(["Hint 1", "Hint 2"])

    def test_print_hint_box_empty(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test empty hint box."""
        print_hint_box([])  # Should not print anything

    def test_print_status_dashboard(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test status dashboard printing doesn't crash."""
        status = {"Liberated": 100, "NotLiberated": 5, "Error": 2}
        print_status_dashboard(status)


class TestCmdLibation:
    """Tests for main libation command entry point."""

    @patch("mamfast.commands.libation.cmd_libation_status")
    def test_no_subcommand_calls_status(self, mock_status: MagicMock) -> None:
        """Test that no subcommand defaults to status."""
        mock_status.return_value = 0
        args = argparse.Namespace()
        # Simulate no libation_func set

        cmd_libation(args)

        mock_status.assert_called_once()

    def test_with_subcommand_func(self) -> None:
        """Test that subcommand func is called when set."""
        mock_func = MagicMock(return_value=42)
        args = argparse.Namespace(libation_func=mock_func)

        result = cmd_libation(args)

        assert result == 42
        mock_func.assert_called_once_with(args)
