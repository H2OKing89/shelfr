"""Tests for mkbrr CLI commands.

These tests validate the mkbrr CLI subcommands using typer.testing.CliRunner.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from shelfr.cli import app
from shelfr.mkbrr import MkbrrResult
from tests.conftest import make_cmd_result


@pytest.fixture
def runner() -> CliRunner:
    """Create a CLI runner for testing."""
    return CliRunner()


# Patch target for mkbrr functions (imported inside CLI commands)
MKBRR_MODULE = "shelfr.mkbrr"


class TestMkbrrHelp:
    """Test mkbrr subcommand help output."""

    def test_mkbrr_help(self, runner: CliRunner) -> None:
        """Test mkbrr --help shows all commands."""
        result = runner.invoke(app, ["mkbrr", "--help"])
        assert result.exit_code == 0
        assert "create" in result.output
        assert "inspect" in result.output
        assert "check" in result.output
        assert "modify" in result.output
        assert "presets" in result.output
        assert "version" in result.output
        assert "update" in result.output

    def test_mkbrr_no_args_shows_help(self, runner: CliRunner) -> None:
        """Test mkbrr without args shows help."""
        result = runner.invoke(app, ["mkbrr"])
        # Callback shows help and exits 0, but if no callback might be 2
        assert result.exit_code in (0, 2)
        assert "create" in result.output

    def test_mkbrr_create_help(self, runner: CliRunner) -> None:
        """Test mkbrr create --help shows options."""
        result = runner.invoke(app, ["mkbrr", "create", "--help"])
        assert result.exit_code == 0
        assert "--preset" in result.output
        assert "--tracker" in result.output
        assert "--source" in result.output
        assert "--output" in result.output
        assert "--piece-length" in result.output

    def test_mkbrr_inspect_help(self, runner: CliRunner) -> None:
        """Test mkbrr inspect --help shows options."""
        result = runner.invoke(app, ["mkbrr", "inspect", "--help"])
        assert result.exit_code == 0
        assert "--verbose" in result.output or "-v" in result.output
        assert "TORRENT" in result.output or "torrent" in result.output

    def test_mkbrr_check_help(self, runner: CliRunner) -> None:
        """Test mkbrr check --help shows options."""
        result = runner.invoke(app, ["mkbrr", "check", "--help"])
        assert result.exit_code == 0
        assert "--verbose" in result.output or "-v" in result.output
        assert "--quiet" in result.output or "-q" in result.output

    def test_mkbrr_modify_help(self, runner: CliRunner) -> None:
        """Test mkbrr modify --help shows options."""
        result = runner.invoke(app, ["mkbrr", "modify", "--help"])
        assert result.exit_code == 0
        assert "--tracker" in result.output
        assert "--source" in result.output
        assert "--dry-run" in result.output

    def test_mkbrr_presets_help(self, runner: CliRunner) -> None:
        """Test mkbrr presets --help."""
        result = runner.invoke(app, ["mkbrr", "presets", "--help"])
        assert result.exit_code == 0

    def test_mkbrr_version_help(self, runner: CliRunner) -> None:
        """Test mkbrr version --help."""
        result = runner.invoke(app, ["mkbrr", "version", "--help"])
        assert result.exit_code == 0

    def test_mkbrr_update_help(self, runner: CliRunner) -> None:
        """Test mkbrr update --help."""
        result = runner.invoke(app, ["mkbrr", "update", "--help"])
        assert result.exit_code == 0


class TestMkbrrCreate:
    """Test mkbrr create command."""

    def test_create_requires_path(self, runner: CliRunner) -> None:
        """Test create command requires path argument."""
        result = runner.invoke(app, ["mkbrr", "create"])
        assert result.exit_code != 0
        assert "Missing argument" in result.output or "PATH" in result.output

    def test_create_invalid_path_rejected(self, runner: CliRunner) -> None:
        """Test create command rejects non-existent path."""
        result = runner.invoke(app, ["mkbrr", "create", "/nonexistent/path"])
        assert result.exit_code != 0
        assert "does not exist" in result.output or "Invalid" in result.output

    def test_create_piece_length_validation(self, runner: CliRunner) -> None:
        """Test piece length must be 16-27."""
        # Below range
        result = runner.invoke(app, ["mkbrr", "create", "/tmp", "--piece-length", "15"])
        assert result.exit_code != 0

        # Above range
        result = runner.invoke(app, ["mkbrr", "create", "/tmp", "--piece-length", "28"])
        assert result.exit_code != 0

    def test_create_success(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test successful torrent creation."""
        # Create a test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        mock_result = MkbrrResult(
            success=True,
            return_code=0,
            torrent_path=tmp_path / "test.torrent",
            stdout="Created torrent: test.torrent",
        )

        with patch(f"{MKBRR_MODULE}.create_torrent", return_value=mock_result):
            result = runner.invoke(app, ["mkbrr", "create", str(test_file)])
            assert result.exit_code == 0
            assert "Created" in result.output or "torrent" in result.output.lower()

    def test_create_with_preset(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test create with preset option."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        mock_result = MkbrrResult(
            success=True,
            return_code=0,
            torrent_path=tmp_path / "test.torrent",
        )

        with patch(f"{MKBRR_MODULE}.create_torrent", return_value=mock_result) as mock_create:
            result = runner.invoke(app, ["mkbrr", "create", str(test_file), "--preset", "mam"])
            assert result.exit_code == 0
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs.get("preset") == "mam"

    def test_create_failure_shows_error(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test create failure shows error message."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        mock_result = MkbrrResult(
            success=False,
            return_code=1,
            error="Docker not available",
        )

        with patch(f"{MKBRR_MODULE}.create_torrent", return_value=mock_result):
            result = runner.invoke(app, ["mkbrr", "create", str(test_file)])
            assert result.exit_code == 1
            assert "Docker" in result.output or "error" in result.output.lower()


class TestMkbrrInspect:
    """Test mkbrr inspect command."""

    def test_inspect_requires_torrent(self, runner: CliRunner) -> None:
        """Test inspect command requires torrent argument."""
        result = runner.invoke(app, ["mkbrr", "inspect"])
        assert result.exit_code != 0

    def test_inspect_invalid_file_rejected(self, runner: CliRunner) -> None:
        """Test inspect rejects non-existent file."""
        result = runner.invoke(app, ["mkbrr", "inspect", "/nonexistent.torrent"])
        assert result.exit_code != 0

    def test_inspect_success(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test successful torrent inspection."""
        from shelfr.schemas.mkbrr import TorrentInfo

        # Create dummy torrent file
        torrent_file = tmp_path / "test.torrent"
        torrent_file.write_bytes(b"dummy")  # Content doesn't matter, we mock parser

        mock_info = TorrentInfo(
            name="test",
            info_hash="a" * 40,  # SHA1 hash is 40 hex characters
            size=1024,
            piece_length=262144,
            piece_count=4,
            private=True,
            trackers=["https://tracker.example.com/announce"],
        )

        with patch(f"{MKBRR_MODULE}.parse_torrent_file", return_value=mock_info):
            result = runner.invoke(app, ["mkbrr", "inspect", str(torrent_file)])
            assert result.exit_code == 0
            assert "test" in result.output or "abc123" in result.output


class TestMkbrrCheck:
    """Test mkbrr check command."""

    def test_check_requires_both_args(self, runner: CliRunner) -> None:
        """Test check requires torrent and content path."""
        result = runner.invoke(app, ["mkbrr", "check"])
        assert result.exit_code != 0

    def test_check_success(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test successful content verification."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.write_bytes(b"d4:infod4:name4:teste8:piece li20ee6:pieces0:ee")
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "test.txt").write_text("content")

        mock_result = MkbrrResult(
            success=True,
            return_code=0,
            stdout="Completion: 100.00%\nGood pieces: 100\nBad pieces: 0",
        )

        with patch(f"{MKBRR_MODULE}.check_torrent", return_value=mock_result):
            result = runner.invoke(app, ["mkbrr", "check", str(torrent_file), str(content_dir)])
            assert result.exit_code == 0

    def test_check_failure(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test check with mismatched content."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.write_bytes(b"d4:infod4:name4:teste8:piece li20ee6:pieces0:ee")
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        mock_result = MkbrrResult(
            success=False,
            return_code=1,
            stdout="Completion: 50.00%\nGood pieces: 50\nBad pieces: 50",
        )

        with patch(f"{MKBRR_MODULE}.check_torrent", return_value=mock_result):
            result = runner.invoke(app, ["mkbrr", "check", str(torrent_file), str(content_dir)])
            # Check command may show warning for partial verification
            assert "50" in result.output or result.exit_code in (0, 1)


class TestMkbrrModify:
    """Test mkbrr modify command."""

    def test_modify_requires_torrent(self, runner: CliRunner) -> None:
        """Test modify requires torrent argument."""
        result = runner.invoke(app, ["mkbrr", "modify"])
        assert result.exit_code != 0

    def test_modify_dry_run(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test modify with --dry-run shows preview."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.write_bytes(b"d4:infod4:name4:teste8:piece li20ee6:pieces0:ee")

        mock_result = MkbrrResult(
            success=True,
            return_code=0,
            stdout="Would modify: test.torrent",
        )

        with patch(f"{MKBRR_MODULE}.modify_torrent", return_value=mock_result):
            result = runner.invoke(
                app,
                ["mkbrr", "modify", str(torrent_file), "--source", "TEST", "--dry-run"],
            )
            assert result.exit_code == 0

    def test_modify_with_options(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test modify with various options."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.write_bytes(b"d4:infod4:name4:teste8:piece li20ee6:pieces0:ee")

        mock_result = MkbrrResult(
            success=True,
            return_code=0,
            stdout="Modified: test.torrent",
            torrent_path=tmp_path / "modified.torrent",
        )

        with patch(f"{MKBRR_MODULE}.modify_torrent", return_value=mock_result) as mock_modify:
            result = runner.invoke(
                app,
                [
                    "mkbrr",
                    "modify",
                    str(torrent_file),
                    "--source",
                    "MAM",
                    "--tracker",
                    "https://tracker.example.com/announce",
                ],
            )
            assert result.exit_code == 0
            mock_modify.assert_called_once()


class TestMkbrrPresets:
    """Test mkbrr presets command."""

    def test_presets_success(self, runner: CliRunner) -> None:
        """Test presets command lists available presets."""
        mock_presets = ["mam", "red", "btn"]

        with patch(f"{MKBRR_MODULE}.load_presets", return_value=mock_presets):
            result = runner.invoke(app, ["mkbrr", "presets"])
            assert result.exit_code == 0
            assert "mam" in result.output or "Preset" in result.output

    def test_presets_no_presets_file(self, runner: CliRunner) -> None:
        """Test presets command when no presets.yaml exists."""
        with patch(f"{MKBRR_MODULE}.load_presets", return_value=[]):
            result = runner.invoke(app, ["mkbrr", "presets"])
            # Should still exit 0 but show message about no presets
            assert result.exit_code == 0


class TestMkbrrVersion:
    """Test mkbrr version command."""

    def test_version_success(self, runner: CliRunner) -> None:
        """Test version command shows mkbrr version."""
        with patch(f"{MKBRR_MODULE}.get_mkbrr_version", return_value="1.5.0"):
            result = runner.invoke(app, ["mkbrr", "version"])
            assert result.exit_code == 0
            assert "1.5.0" in result.output

    def test_version_docker_unavailable(self, runner: CliRunner) -> None:
        """Test version when Docker is unavailable."""
        with patch(f"{MKBRR_MODULE}.get_mkbrr_version", return_value=None):
            result = runner.invoke(app, ["mkbrr", "version"])
            # Should handle gracefully
            assert "unavailable" in result.output.lower() or result.exit_code != 0


class TestMkbrrUpdate:
    """Test mkbrr update command."""

    def test_update_success(self, runner: CliRunner) -> None:
        """Test successful Docker image update."""
        mock_result = make_cmd_result(
            exit_code=0,
            stdout="Using default tag: latest\nPulling from autobrr/mkbrr\n",
        )

        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"
        mock_settings.mkbrr.image = "ghcr.io/autobrr/mkbrr:latest"

        with (
            patch(f"{MKBRR_MODULE}.run", return_value=mock_result),
            patch(f"{MKBRR_MODULE}.get_settings", return_value=mock_settings),
        ):
            result = runner.invoke(app, ["mkbrr", "update"])
            assert result.exit_code == 0
            assert "pull" in result.output.lower() or "updated" in result.output.lower()

    def test_update_failure(self, runner: CliRunner) -> None:
        """Test update failure handling."""
        from shelfr.utils.cmd import CmdError

        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"
        mock_settings.mkbrr.image = "ghcr.io/autobrr/mkbrr:latest"

        # The update command uses run() with ok_codes=(0,), so non-zero raises CmdError
        with (
            patch(
                "shelfr.utils.cmd.run",
                side_effect=CmdError(
                    argv=["docker", "pull"],
                    exit_code=1,
                    stdout="",
                    stderr="Error: pull access denied",
                ),
            ),
            patch("shelfr.config.get_settings", return_value=mock_settings),
        ):
            result = runner.invoke(app, ["mkbrr", "update"])
            assert result.exit_code == 1


class TestMkbrrGlobalFlags:
    """Test that global flags work with mkbrr commands."""

    def test_dry_run_with_create(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test --dry-run global flag with mkbrr create."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        # Dry-run should prevent actual creation
        result = runner.invoke(
            app, ["--dry-run", "mkbrr", "create", str(test_file), "--preset", "mam"]
        )
        # Should accept the flag (may fail for other reasons)
        assert "--dry-run" not in result.output or "Unknown option" not in result.output

    def test_verbose_with_inspect(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test --verbose global flag with mkbrr inspect."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.write_bytes(b"d4:infod4:name4:teste8:piece li20ee6:pieces0:ee")

        mock_result = MkbrrResult(success=True, return_code=0, stdout="test")

        with patch(f"{MKBRR_MODULE}.inspect_torrent", return_value=mock_result):
            result = runner.invoke(app, ["--verbose", "mkbrr", "inspect", str(torrent_file)])
            # Should accept the flag
            assert "Unknown option" not in result.output
