"""Tests for CLI tools commands."""

from __future__ import annotations

from typer.testing import CliRunner

from shelfr.cli import app

runner = CliRunner()


class TestMamBBCode:
    """Tests for the mam bbcode command."""

    def test_bbcode_help(self) -> None:
        """Test bbcode command help displays."""
        result = runner.invoke(app, ["mam", "bbcode", "--help"])
        assert result.exit_code == 0
        assert "BBCode description" in result.stdout

    def test_bbcode_no_args(self) -> None:
        """Test bbcode command with no args shows error (missing required path)."""
        result = runner.invoke(app, ["mam", "bbcode"])
        # Typer uses exit code 2 for missing required args
        assert result.exit_code == 2

    def test_bbcode_nonexistent_path(self) -> None:
        """Test bbcode command with non-existent path shows error."""
        result = runner.invoke(app, ["mam", "bbcode", "/nonexistent/path"])
        assert result.exit_code != 0
        # Typer validates the path exists


class TestMamRender:
    """Tests for the mam render command."""

    def test_render_help(self) -> None:
        """Test render command help displays."""
        result = runner.invoke(app, ["mam", "render", "--help"])
        assert result.exit_code == 0
        assert "Render BBCode visually" in result.stdout

    def test_render_no_args(self) -> None:
        """Test render command with no args shows error (missing required path)."""
        result = runner.invoke(app, ["mam", "render"])
        # Typer uses exit code 2 for missing required args
        assert result.exit_code == 2

    def test_render_nonexistent_path(self) -> None:
        """Test render command with non-existent path shows error."""
        result = runner.invoke(app, ["mam", "render", "/nonexistent/path"])
        assert result.exit_code != 0
        # Typer validates the path exists


class TestToolsMamff:
    """Tests for the tools mamff command."""

    def test_mamff_help(self) -> None:
        """Test mamff command help displays."""
        result = runner.invoke(app, ["tools", "mamff", "--help"])
        assert result.exit_code == 0
        assert "MAM fast-fill JSON" in result.stdout

    def test_mamff_missing_path(self) -> None:
        """Test mamff command with missing path shows error."""
        result = runner.invoke(app, ["tools", "mamff"])
        assert result.exit_code != 0
        # Typer uses exit code 2 for usage errors
        assert result.exit_code == 2

    def test_mamff_nonexistent_path(self) -> None:
        """Test mamff command with non-existent path shows error."""
        result = runner.invoke(app, ["tools", "mamff", "/nonexistent/path"])
        assert result.exit_code != 0
        # Typer validates the path exists


class TestToolsApp:
    """Tests for the tools sub-app."""

    def test_tools_help(self) -> None:
        """Test tools sub-app help displays."""
        result = runner.invoke(app, ["tools", "--help"])
        assert result.exit_code == 0
        assert "mamff" in result.stdout
        # bbcode moved to mam sub-app
        assert "prepare" in result.stdout


class TestMamApp:
    """Tests for the mam sub-app."""

    def test_mam_help(self) -> None:
        """Test mam sub-app help displays."""
        result = runner.invoke(app, ["mam", "--help"])
        assert result.exit_code == 0
        assert "bbcode" in result.stdout
        assert "render" in result.stdout
        # Check for MAM upload page bug warning
        assert "upload page" in result.stdout.lower() or "MAM" in result.stdout
