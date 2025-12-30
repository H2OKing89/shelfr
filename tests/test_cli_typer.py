"""Tests for the Typer-based CLI.

These tests validate the new Typer CLI implementation using typer.testing.CliRunner.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from mamfast.cli import app


@pytest.fixture
def runner() -> CliRunner:
    """Create a CLI runner for testing."""
    return CliRunner()


class TestCliHelp:
    """Test CLI help output."""

    def test_main_help(self, runner: CliRunner) -> None:
        """Test main help shows all command groups."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        # Check for command groups
        assert "Core Pipeline" in result.output or "prepare" in result.output
        assert "mamfast" in result.output.lower() or "MAMFast" in result.output

    def test_version_option(self, runner: CliRunner) -> None:
        """Test --version displays version info."""
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "MAMFast" in result.output or "mamfast" in result.output.lower()

    def test_prepare_help(self, runner: CliRunner) -> None:
        """Test prepare command help."""
        result = runner.invoke(app, ["prepare", "--help"])
        assert result.exit_code == 0
        assert "--asin" in result.output or "ASIN" in result.output

    def test_metadata_help(self, runner: CliRunner) -> None:
        """Test metadata command help."""
        result = runner.invoke(app, ["metadata", "--help"])
        assert result.exit_code == 0
        assert "metadata" in result.output.lower()

    def test_state_help(self, runner: CliRunner) -> None:
        """Test state subcommand help."""
        result = runner.invoke(app, ["state", "--help"])
        assert result.exit_code == 0
        assert "state" in result.output.lower()

    def test_libation_help(self, runner: CliRunner) -> None:
        """Test libation subcommand help."""
        result = runner.invoke(app, ["libation", "--help"])
        assert result.exit_code == 0
        assert "libation" in result.output.lower()


class TestAsinValidation:
    """Test ASIN validation in Typer CLI."""

    def test_prepare_invalid_asin_rejected(self, runner: CliRunner) -> None:
        """Test prepare command rejects invalid ASIN."""
        result = runner.invoke(app, ["prepare", "--asin", "invalid", "/tmp/test"])
        assert result.exit_code != 0
        assert "ASIN" in result.output or "Invalid" in result.output

    def test_prepare_valid_asin_format_accepted(self, runner: CliRunner) -> None:
        """Test prepare command accepts valid ASIN format.

        Note: The command will fail for other reasons (missing config, etc.)
        but ASIN validation should pass.
        """
        result = runner.invoke(app, ["prepare", "--asin", "B0DK9T5P28", "/tmp/nonexistent"])
        # Should not fail due to ASIN validation
        assert "Invalid ASIN" not in result.output

    def test_metadata_invalid_asin_rejected(self, runner: CliRunner) -> None:
        """Test metadata command rejects invalid ASIN."""
        result = runner.invoke(app, ["metadata", "--asin", "toolong123456"])
        assert result.exit_code != 0
        assert "ASIN" in result.output or "Invalid" in result.output

    def test_asin_lowercase_normalized(self, runner: CliRunner) -> None:
        """Test lowercase ASIN is accepted (normalized internally)."""
        result = runner.invoke(app, ["prepare", "--asin", "b0dk9t5p28", "/tmp/test"])
        # Should not fail due to ASIN validation (lowercase is valid)
        assert "Invalid ASIN" not in result.output


class TestGlobalOptions:
    """Test global CLI options."""

    def test_verbose_flag_accepted(self, runner: CliRunner) -> None:
        """Test --verbose flag is accepted."""
        result = runner.invoke(app, ["--verbose", "--help"])
        assert result.exit_code == 0

    def test_dry_run_flag_accepted(self, runner: CliRunner) -> None:
        """Test --dry-run flag is accepted."""
        result = runner.invoke(app, ["--dry-run", "--help"])
        assert result.exit_code == 0

    def test_config_option_accepted(self, runner: CliRunner) -> None:
        """Test -c/--config option is accepted."""
        result = runner.invoke(app, ["-c", "custom.yaml", "--help"])
        assert result.exit_code == 0


class TestSubcommands:
    """Test subcommand structure."""

    def test_state_list_help(self, runner: CliRunner) -> None:
        """Test state list subcommand help."""
        result = runner.invoke(app, ["state", "list", "--help"])
        assert result.exit_code == 0

    def test_state_clear_help(self, runner: CliRunner) -> None:
        """Test state clear subcommand help."""
        result = runner.invoke(app, ["state", "clear", "--help"])
        assert result.exit_code == 0

    def test_state_prune_help(self, runner: CliRunner) -> None:
        """Test state prune subcommand help."""
        result = runner.invoke(app, ["state", "prune", "--help"])
        assert result.exit_code == 0

    def test_state_retry_help(self, runner: CliRunner) -> None:
        """Test state retry subcommand help."""
        result = runner.invoke(app, ["state", "retry", "--help"])
        assert result.exit_code == 0

    def test_libation_scan_help(self, runner: CliRunner) -> None:
        """Test libation scan subcommand help."""
        result = runner.invoke(app, ["libation", "scan", "--help"])
        assert result.exit_code == 0

    def test_libation_search_help(self, runner: CliRunner) -> None:
        """Test libation search subcommand help."""
        result = runner.invoke(app, ["libation", "search", "--help"])
        assert result.exit_code == 0


class TestAllCommandsHaveHelp:
    """Test all commands have working help output."""

    @pytest.mark.parametrize(
        "command",
        [
            # Core Pipeline
            ["scan", "--help"],
            ["discover", "--help"],
            ["prepare", "--help"],
            ["metadata", "--help"],
            ["torrent", "--help"],
            ["upload", "--help"],
            ["run", "--help"],
            ["status", "--help"],
            ["config", "--help"],
            # Diagnostics
            ["check", "--help"],
            ["validate", "--help"],
            ["validate-config", "--help"],
            ["preview-naming", "--help"],
            ["check-duplicates", "--help"],
            ["check-suspicious", "--help"],
            # Audiobookshelf (sub-app syntax)
            ["abs", "--help"],
            ["abs", "init", "--help"],
            ["abs", "import", "--help"],
            ["abs", "cleanup", "--help"],
            ["abs", "restore", "--help"],
            ["abs", "check-asin", "--help"],
            ["abs", "resolve-asins", "--help"],
            ["abs", "trump-preview", "--help"],
            ["abs", "rename", "--help"],
            ["abs", "orphans", "--help"],
            # State Management
            ["state", "--help"],
            ["state", "list", "--help"],
            ["state", "clear", "--help"],
            ["state", "prune", "--help"],
            ["state", "retry", "--help"],
            ["state", "export", "--help"],
            # Libation
            ["libation", "--help"],
            ["libation", "scan", "--help"],
            ["libation", "search", "--help"],
            ["libation", "status", "--help"],
            ["libation", "books", "--help"],
        ],
    )
    def test_command_help_works(self, runner: CliRunner, command: list[str]) -> None:
        """Test each command has working help."""
        result = runner.invoke(app, command)
        assert result.exit_code == 0, f"Command {command} failed: {result.output}"

    @pytest.mark.parametrize(
        "command",
        [
            # Deprecated ABS aliases still work (backward compatibility)
            ["abs-init", "--help"],
            ["abs-import", "--help"],
            ["abs-cleanup", "--help"],
            ["abs-check-duplicate", "--help"],
            ["abs-trump-check", "--help"],
        ],
    )
    def test_deprecated_abs_aliases_work(self, runner: CliRunner, command: list[str]) -> None:
        """Test deprecated abs-* aliases still work for backward compatibility."""
        result = runner.invoke(app, command)
        assert result.exit_code == 0, f"Deprecated command {command} failed: {result.output}"
        # Help should still work (docstring says "deprecated")
        assert (
            "deprecated" in result.output.lower()
            or "ASIN" in result.output
            or "help" in result.output.lower()
        )

    def test_global_flags_before_subapp(self, runner: CliRunner) -> None:
        """Test that global flags work BEFORE sub-app commands.

        Global flags like --dry-run must be placed before the subcommand:
          mamfast --dry-run abs import  ✓ (correct)
          mamfast abs import --dry-run  ✗ (wrong - flag after subcommand)
        """
        # Global flag BEFORE subcommand should work
        result = runner.invoke(app, ["--dry-run", "abs", "init"])
        # Should not error on flag parsing (may error on missing config, that's OK)
        assert result.exit_code in (0, 1), f"Global flag before subapp failed: {result.output}"
        # Should recognize --dry-run (no "Unknown option" error)
        assert "Unknown option" not in result.output
