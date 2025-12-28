"""Tests for CLI tools commands."""

from __future__ import annotations

from typer.testing import CliRunner

from mamfast.cli import app

runner = CliRunner()


class TestToolsBBCode:
    """Tests for the tools bbcode command."""

    def test_bbcode_help(self) -> None:
        """Test bbcode command help displays."""
        result = runner.invoke(app, ["tools", "bbcode", "--help"])
        assert result.exit_code == 0
        assert "HTML to BBCode conversion" in result.stdout

    def test_bbcode_no_args(self) -> None:
        """Test bbcode command with no args shows error."""
        result = runner.invoke(app, ["tools", "bbcode"])
        assert result.exit_code == 1
        assert "Provide --asin or --html" in result.stdout

    def test_bbcode_html_simple(self) -> None:
        """Test bbcode command with simple HTML."""
        result = runner.invoke(app, ["tools", "bbcode", "--html", "<b>bold</b> and <i>italic</i>"])
        assert result.exit_code == 0
        assert "[b]bold[/b]" in result.stdout
        assert "[i]italic[/i]" in result.stdout

    def test_bbcode_html_paragraphs(self) -> None:
        """Test bbcode command with paragraph HTML."""
        result = runner.invoke(app, ["tools", "bbcode", "--html", "<p>Para 1</p><p>Para 2</p>"])
        assert result.exit_code == 0
        # Paragraphs converted to double newlines
        assert "Para 1" in result.stdout
        assert "Para 2" in result.stdout


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
        assert "bbcode" in result.stdout
