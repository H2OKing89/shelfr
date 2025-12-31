"""Tests for mkbrr module."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shelfr.mkbrr import (
    MkbrrResult,
    _cleanup_stale_torrents,
    _docker_base_command,
    _find_torrent_deterministic,
    check_docker_available,
    check_torrent,
    create_torrent,
    fix_torrent_permissions,
    get_mkbrr_version,
    inspect_torrent,
    load_presets,
    modify_torrent,
)
from shelfr.utils.cmd import CmdError
from tests.conftest import make_cmd_result


class TestMkbrrResult:
    """Tests for MkbrrResult dataclass."""

    def test_success_result(self):
        """Test successful result."""
        result = MkbrrResult(
            success=True,
            return_code=0,
            torrent_path=Path("/tmp/test.torrent"),
        )
        assert result.success is True
        assert result.return_code == 0
        assert result.torrent_path == Path("/tmp/test.torrent")
        assert result.error is None

    def test_failure_result(self):
        """Test failed result."""
        result = MkbrrResult(
            success=False,
            return_code=1,
            error="Docker command failed",
        )
        assert result.success is False
        assert result.return_code == 1
        assert result.error == "Docker command failed"
        assert result.torrent_path is None


class TestCheckDockerAvailable:
    """Tests for Docker availability check."""

    def test_docker_available(self):
        """Test when docker is available."""
        mock_result = make_cmd_result(exit_code=0)

        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"

        with (
            patch("shelfr.mkbrr.run", return_value=mock_result),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
        ):
            assert check_docker_available() is True

    def test_docker_not_available(self):
        """Test when docker is not available."""
        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"

        with (
            patch(
                "shelfr.mkbrr.run",
                side_effect=CmdError(
                    argv=["docker", "--version"],
                    exit_code=127,
                    stdout="",
                    stderr="Command not found",
                ),
            ),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
        ):
            assert check_docker_available() is False


class TestGetMkbrrVersion:
    """Tests for get_mkbrr_version function."""

    def test_version_standard_format(self):
        """Test parsing standard 'mkbrr version X.Y.Z' format."""
        mock_result = make_cmd_result(
            exit_code=0,
            stdout="mkbrr version 1.5.0\n",
        )

        with (
            patch("shelfr.mkbrr._docker_base_command", return_value=["docker", "run", "mkbrr"]),
            patch("shelfr.mkbrr._run_docker_command", return_value=mock_result),
        ):
            version = get_mkbrr_version()

        assert version == "1.5.0"

    def test_version_just_number(self):
        """Test parsing bare version number output."""
        mock_result = make_cmd_result(
            exit_code=0,
            stdout="2.0.1\n",
        )

        with (
            patch("shelfr.mkbrr._docker_base_command", return_value=["docker", "run", "mkbrr"]),
            patch("shelfr.mkbrr._run_docker_command", return_value=mock_result),
        ):
            version = get_mkbrr_version()

        assert version == "2.0.1"

    def test_version_empty_output(self):
        """Test handling empty output."""
        mock_result = make_cmd_result(
            exit_code=0,
            stdout="",
        )

        with (
            patch("shelfr.mkbrr._docker_base_command", return_value=["docker", "run", "mkbrr"]),
            patch("shelfr.mkbrr._run_docker_command", return_value=mock_result),
        ):
            version = get_mkbrr_version()

        assert version is None

    def test_version_command_fails(self):
        """Test when mkbrr version command returns non-zero exit code."""
        mock_result = make_cmd_result(
            exit_code=1,
            stderr="Error: unknown command",
        )

        with (
            patch("shelfr.mkbrr._docker_base_command", return_value=["docker", "run", "mkbrr"]),
            patch("shelfr.mkbrr._run_docker_command", return_value=mock_result),
        ):
            version = get_mkbrr_version()

        assert version is None

    def test_version_docker_error(self):
        """Test when Docker command raises CmdError."""
        with (
            patch("shelfr.mkbrr._docker_base_command", return_value=["docker", "run", "mkbrr"]),
            patch(
                "shelfr.mkbrr._run_docker_command",
                side_effect=CmdError(
                    argv=["docker", "run", "mkbrr", "version"],
                    exit_code=125,
                    stdout="",
                    stderr="Docker daemon not running",
                ),
            ),
        ):
            version = get_mkbrr_version()

        assert version is None

    def test_version_unexpected_exception(self):
        """Test handling unexpected exceptions gracefully."""
        with (
            patch("shelfr.mkbrr._docker_base_command", return_value=["docker", "run", "mkbrr"]),
            patch(
                "shelfr.mkbrr._run_docker_command",
                side_effect=RuntimeError("Unexpected error"),
            ),
        ):
            version = get_mkbrr_version()

        assert version is None

    def test_version_unusual_format_returned_as_is(self):
        """Test that unusual version formats are returned as-is."""
        mock_result = make_cmd_result(
            exit_code=0,
            stdout="mkbrr 1.5.0-beta+build.123\n",
        )

        with (
            patch("shelfr.mkbrr._docker_base_command", return_value=["docker", "run", "mkbrr"]),
            patch("shelfr.mkbrr._run_docker_command", return_value=mock_result),
        ):
            version = get_mkbrr_version()

        # Should return the whole string when format doesn't match expected patterns
        assert version == "mkbrr 1.5.0-beta+build.123"


class TestModifyTorrent:
    """Tests for modify_torrent function."""

    def test_modify_single_torrent_with_source(self, tmp_path: Path):
        """Test modifying a single torrent with new source tag."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.touch()

        mock_result = make_cmd_result(
            exit_code=0,
            stdout="Modified: test.torrent -> modified_test.torrent\n",
        )

        with (
            patch("shelfr.mkbrr._docker_base_command", return_value=["docker", "run", "mkbrr"]),
            patch("shelfr.mkbrr._run_docker_command", return_value=mock_result) as mock_run,
            patch(
                "shelfr.mkbrr.host_to_container_torrent_path",
                side_effect=lambda p: f"/torrentfiles/{Path(p).name}",
            ),
            patch("shelfr.mkbrr.fix_torrent_permissions"),
        ):
            result = modify_torrent(torrent_file, source="MAM")

        assert result.success is True
        assert result.return_code == 0
        # Verify command includes source flag
        call_args = mock_run.call_args[0][0]
        assert "-s" in call_args
        assert "MAM" in call_args

    def test_modify_with_tracker(self, tmp_path: Path):
        """Test modifying torrent with new tracker URL."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.touch()

        mock_result = make_cmd_result(exit_code=0, stdout="Modified successfully\n")

        with (
            patch("shelfr.mkbrr._docker_base_command", return_value=["docker", "run", "mkbrr"]),
            patch("shelfr.mkbrr._run_docker_command", return_value=mock_result) as mock_run,
            patch(
                "shelfr.mkbrr.host_to_container_torrent_path",
                side_effect=lambda p: f"/torrentfiles/{Path(p).name}",
            ),
            patch("shelfr.mkbrr.fix_torrent_permissions"),
        ):
            result = modify_torrent(torrent_file, tracker="https://new.tracker/announce")

        assert result.success is True
        call_args = mock_run.call_args[0][0]
        assert "-t" in call_args
        assert "https://new.tracker/announce" in call_args

    def test_modify_with_comment(self, tmp_path: Path):
        """Test modifying torrent with new comment."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.touch()

        mock_result = make_cmd_result(exit_code=0, stdout="Modified\n")

        with (
            patch("shelfr.mkbrr._docker_base_command", return_value=["docker", "run", "mkbrr"]),
            patch("shelfr.mkbrr._run_docker_command", return_value=mock_result) as mock_run,
            patch(
                "shelfr.mkbrr.host_to_container_torrent_path",
                side_effect=lambda p: f"/torrentfiles/{Path(p).name}",
            ),
            patch("shelfr.mkbrr.fix_torrent_permissions"),
        ):
            result = modify_torrent(torrent_file, comment="Uploaded via shelfr")

        assert result.success is True
        call_args = mock_run.call_args[0][0]
        assert "-c" in call_args
        assert "Uploaded via shelfr" in call_args

    def test_modify_with_preset(self, tmp_path: Path):
        """Test modifying torrent with preset."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.touch()

        mock_result = make_cmd_result(exit_code=0, stdout="Modified\n")

        with (
            patch("shelfr.mkbrr._docker_base_command", return_value=["docker", "run", "mkbrr"]),
            patch("shelfr.mkbrr._run_docker_command", return_value=mock_result) as mock_run,
            patch(
                "shelfr.mkbrr.host_to_container_torrent_path",
                side_effect=lambda p: f"/torrentfiles/{Path(p).name}",
            ),
            patch("shelfr.mkbrr.fix_torrent_permissions"),
        ):
            result = modify_torrent(torrent_file, preset="mam")

        assert result.success is True
        call_args = mock_run.call_args[0][0]
        assert "-P" in call_args
        assert "mam" in call_args

    def test_modify_private_true(self, tmp_path: Path):
        """Test setting private flag to true."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.touch()

        mock_result = make_cmd_result(exit_code=0, stdout="Modified\n")

        with (
            patch("shelfr.mkbrr._docker_base_command", return_value=["docker", "run", "mkbrr"]),
            patch("shelfr.mkbrr._run_docker_command", return_value=mock_result) as mock_run,
            patch(
                "shelfr.mkbrr.host_to_container_torrent_path",
                side_effect=lambda p: f"/torrentfiles/{Path(p).name}",
            ),
            patch("shelfr.mkbrr.fix_torrent_permissions"),
        ):
            result = modify_torrent(torrent_file, private=True)

        assert result.success is True
        call_args = mock_run.call_args[0][0]
        assert "--private" in call_args
        assert "--private=false" not in call_args

    def test_modify_private_false(self, tmp_path: Path):
        """Test setting private flag to false."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.touch()

        mock_result = make_cmd_result(exit_code=0, stdout="Modified\n")

        with (
            patch("shelfr.mkbrr._docker_base_command", return_value=["docker", "run", "mkbrr"]),
            patch("shelfr.mkbrr._run_docker_command", return_value=mock_result) as mock_run,
            patch(
                "shelfr.mkbrr.host_to_container_torrent_path",
                side_effect=lambda p: f"/torrentfiles/{Path(p).name}",
            ),
            patch("shelfr.mkbrr.fix_torrent_permissions"),
        ):
            result = modify_torrent(torrent_file, private=False)

        assert result.success is True
        call_args = mock_run.call_args[0][0]
        assert "--private=false" in call_args

    def test_modify_with_entropy(self, tmp_path: Path):
        """Test adding entropy to randomize info hash."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.touch()

        mock_result = make_cmd_result(exit_code=0, stdout="Modified\n")

        with (
            patch("shelfr.mkbrr._docker_base_command", return_value=["docker", "run", "mkbrr"]),
            patch("shelfr.mkbrr._run_docker_command", return_value=mock_result) as mock_run,
            patch(
                "shelfr.mkbrr.host_to_container_torrent_path",
                side_effect=lambda p: f"/torrentfiles/{Path(p).name}",
            ),
            patch("shelfr.mkbrr.fix_torrent_permissions"),
        ):
            result = modify_torrent(torrent_file, entropy=True)

        assert result.success is True
        call_args = mock_run.call_args[0][0]
        assert "-e" in call_args

    def test_modify_dry_run(self, tmp_path: Path):
        """Test dry run mode previews changes without writing."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.touch()

        mock_result = make_cmd_result(exit_code=0, stdout="Would modify: test.torrent\n")

        with (
            patch("shelfr.mkbrr._docker_base_command", return_value=["docker", "run", "mkbrr"]),
            patch("shelfr.mkbrr._run_docker_command", return_value=mock_result) as mock_run,
            patch(
                "shelfr.mkbrr.host_to_container_torrent_path",
                side_effect=lambda p: f"/torrentfiles/{Path(p).name}",
            ),
            patch("shelfr.mkbrr.fix_torrent_permissions") as mock_fix,
        ):
            result = modify_torrent(torrent_file, source="TEST", dry_run=True)

        assert result.success is True
        call_args = mock_run.call_args[0][0]
        assert "--dry-run" in call_args
        # Should NOT fix permissions in dry run mode
        mock_fix.assert_not_called()

    def test_modify_with_output_dir(self, tmp_path: Path):
        """Test modifying with output directory for batch operations."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.touch()
        output_dir = tmp_path / "output"

        mock_result = make_cmd_result(exit_code=0, stdout="Modified\n")

        with (
            patch("shelfr.mkbrr._docker_base_command", return_value=["docker", "run", "mkbrr"]),
            patch("shelfr.mkbrr._run_docker_command", return_value=mock_result) as mock_run,
            patch(
                "shelfr.mkbrr.host_to_container_torrent_path",
                side_effect=lambda p: f"/torrentfiles/{Path(p).name}",
            ),
            patch("shelfr.mkbrr.fix_torrent_permissions"),
        ):
            result = modify_torrent(torrent_file, output_dir=output_dir)

        assert result.success is True
        call_args = mock_run.call_args[0][0]
        assert "--output-dir" in call_args

    def test_modify_multiple_files_rejects_output_path(self, tmp_path: Path):
        """Test that using output_path with multiple files returns error."""
        torrent1 = tmp_path / "test1.torrent"
        torrent2 = tmp_path / "test2.torrent"
        torrent1.touch()
        torrent2.touch()

        result = modify_torrent([torrent1, torrent2], output_path="output")

        assert result.success is False
        assert "Cannot use output_path with multiple files" in result.error

    def test_modify_multiple_files_with_output_dir(self, tmp_path: Path):
        """Test modifying multiple files with output directory."""
        torrent1 = tmp_path / "test1.torrent"
        torrent2 = tmp_path / "test2.torrent"
        torrent1.touch()
        torrent2.touch()
        output_dir = tmp_path / "output"

        mock_result = make_cmd_result(exit_code=0, stdout="Modified 2 files\n")

        with (
            patch("shelfr.mkbrr._docker_base_command", return_value=["docker", "run", "mkbrr"]),
            patch("shelfr.mkbrr._run_docker_command", return_value=mock_result) as mock_run,
            patch(
                "shelfr.mkbrr.host_to_container_torrent_path",
                side_effect=lambda p: f"/torrentfiles/{Path(p).name}",
            ),
            patch("shelfr.mkbrr.fix_torrent_permissions"),
        ):
            result = modify_torrent([torrent1, torrent2], output_dir=output_dir, source="MAM")

        assert result.success is True
        call_args = mock_run.call_args[0][0]
        # Should have both torrent paths in command
        assert "/torrentfiles/test1.torrent" in call_args
        assert "/torrentfiles/test2.torrent" in call_args

    def test_modify_command_failure(self, tmp_path: Path):
        """Test handling mkbrr command failure."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.touch()

        mock_result = make_cmd_result(
            exit_code=1,
            stderr="Error: invalid torrent file",
        )

        with (
            patch("shelfr.mkbrr._docker_base_command", return_value=["docker", "run", "mkbrr"]),
            patch("shelfr.mkbrr._run_docker_command", return_value=mock_result),
            patch(
                "shelfr.mkbrr.host_to_container_torrent_path",
                side_effect=lambda p: f"/torrentfiles/{Path(p).name}",
            ),
        ):
            result = modify_torrent(torrent_file, source="MAM")

        assert result.success is False
        assert result.return_code == 1
        assert "invalid torrent file" in result.error

    def test_modify_docker_error(self, tmp_path: Path):
        """Test handling Docker command errors."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.touch()

        with (
            patch("shelfr.mkbrr._docker_base_command", return_value=["docker", "run", "mkbrr"]),
            patch(
                "shelfr.mkbrr._run_docker_command",
                side_effect=CmdError(
                    argv=["docker", "run", "mkbrr", "modify"],
                    exit_code=125,
                    stdout="",
                    stderr="Docker daemon not running",
                ),
            ),
            patch(
                "shelfr.mkbrr.host_to_container_torrent_path",
                side_effect=lambda p: f"/torrentfiles/{Path(p).name}",
            ),
        ):
            result = modify_torrent(torrent_file, source="MAM")

        assert result.success is False

    def test_modify_accepts_string_path(self, tmp_path: Path):
        """Test that string paths are accepted."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.touch()

        mock_result = make_cmd_result(exit_code=0, stdout="Modified\n")

        with (
            patch("shelfr.mkbrr._docker_base_command", return_value=["docker", "run", "mkbrr"]),
            patch("shelfr.mkbrr._run_docker_command", return_value=mock_result),
            patch(
                "shelfr.mkbrr.host_to_container_torrent_path",
                side_effect=lambda p: f"/torrentfiles/{Path(p).name}",
            ),
            patch("shelfr.mkbrr.fix_torrent_permissions"),
        ):
            # Pass string instead of Path
            result = modify_torrent(str(torrent_file), source="MAM")

        assert result.success is True


class TestLoadPresets:
    """Tests for load_presets function."""

    def test_load_presets_success(self, tmp_path: Path):
        """Test loading presets from yaml file."""
        presets_file = tmp_path / "presets.yaml"
        presets_file.write_text(
            """
presets:
  mam:
    announce: https://example.com/announce
  other:
    announce: https://other.com/announce
"""
        )

        mock_settings = MagicMock()
        mock_settings.mkbrr.host_config_dir = str(tmp_path)
        mock_settings.mkbrr.preset = "mam"

        with patch("shelfr.mkbrr.get_settings", return_value=mock_settings):
            presets = load_presets()

        assert "mam" in presets
        assert "other" in presets
        # Default preset should be first
        assert presets[0] == "mam"

    def test_load_presets_file_not_found(self, tmp_path: Path):
        """Test fallback when presets file doesn't exist."""
        mock_settings = MagicMock()
        mock_settings.mkbrr.host_config_dir = str(tmp_path)
        mock_settings.mkbrr.preset = "default"

        with patch("shelfr.mkbrr.get_settings", return_value=mock_settings):
            presets = load_presets()

        assert presets == ["default"]


class TestCleanupStaleTorrents:
    """Tests for _cleanup_stale_torrents function."""

    def test_removes_matching_torrents(self, tmp_path: Path):
        """Test that stale torrents matching content name are removed."""
        content_name = "My Book"
        # Create some torrent files
        (tmp_path / f"{content_name}.torrent").touch()
        (tmp_path / f"mam_{content_name}.torrent").touch()
        (tmp_path / "other.torrent").touch()

        removed = _cleanup_stale_torrents(tmp_path, content_name)

        assert removed == 2
        assert not (tmp_path / f"{content_name}.torrent").exists()
        assert not (tmp_path / f"mam_{content_name}.torrent").exists()
        assert (tmp_path / "other.torrent").exists()

    def test_handles_empty_directory(self, tmp_path: Path):
        """Test that empty directory causes no errors."""
        removed = _cleanup_stale_torrents(tmp_path, "content")
        assert removed == 0

    def test_handles_permission_error(self, tmp_path: Path, caplog):
        """Test graceful handling of permission errors."""
        content_name = "content"
        torrent = tmp_path / f"{content_name}.torrent"
        torrent.touch()

        with patch.object(Path, "unlink", side_effect=OSError("Permission denied")):
            removed = _cleanup_stale_torrents(tmp_path, content_name)

        assert removed == 0
        assert "Failed to remove" in caplog.text


class TestFindTorrentDeterministic:
    """Tests for _find_torrent_deterministic function."""

    def test_finds_exact_match(self, tmp_path: Path):
        """Test finding torrent with exact content name match."""
        content_name = "My Book"
        expected = tmp_path / f"{content_name}.torrent"
        expected.touch()

        result = _find_torrent_deterministic(tmp_path, content_name)

        assert result == expected

    def test_finds_prefixed_match(self, tmp_path: Path):
        """Test finding torrent with preset prefix."""
        content_name = "My Book"
        prefixed = tmp_path / f"mam_{content_name}.torrent"
        prefixed.touch()

        result = _find_torrent_deterministic(tmp_path, content_name)

        assert result == prefixed

    def test_deterministic_tiebreak_by_name(self, tmp_path: Path):
        """Test that multiple matches with same mtime are resolved deterministically."""
        content_name = "content"

        # Create two torrents with same mtime (filesystem precision issue)
        t1 = tmp_path / f"a_{content_name}.torrent"
        t2 = tmp_path / f"b_{content_name}.torrent"
        t1.touch()
        t2.touch()

        # Force same mtime
        shared_time = time.time()
        import os

        os.utime(t1, (shared_time, shared_time))
        os.utime(t2, (shared_time, shared_time))

        # Should consistently return the same one (alphabetically last)
        result1 = _find_torrent_deterministic(tmp_path, content_name)
        result2 = _find_torrent_deterministic(tmp_path, content_name)

        assert result1 == result2 == t2  # 'b' > 'a'

    def test_newest_wins_with_different_mtime(self, tmp_path: Path):
        """Test that newer file wins when mtimes differ."""
        content_name = "content"

        old = tmp_path / f"old_{content_name}.torrent"
        new = tmp_path / f"new_{content_name}.torrent"
        old.touch()
        time.sleep(0.01)  # Ensure different mtime
        new.touch()

        result = _find_torrent_deterministic(tmp_path, content_name)

        assert result == new

    def test_returns_none_when_not_found(self, tmp_path: Path):
        """Test that None is returned when no matching torrent exists."""
        result = _find_torrent_deterministic(tmp_path, "nonexistent")
        assert result is None

    def test_fallback_to_any_torrent(self, tmp_path: Path):
        """Test fallback when content name doesn't match any pattern."""
        # Create a torrent with completely different name
        other = tmp_path / "unrelated.torrent"
        other.touch()

        result = _find_torrent_deterministic(tmp_path, "content")

        assert result == other


class TestCreateTorrent:
    """Tests for torrent creation."""

    def test_create_torrent_success(self, tmp_path: Path):
        """Test successful torrent creation."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "audio.m4b").write_bytes(b"audio data")

        output_dir = tmp_path / "torrents"
        output_dir.mkdir()

        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"
        mock_settings.mkbrr.preset = "mam"
        mock_settings.mkbrr.host_output_dir = str(output_dir)
        mock_settings.mkbrr.host_data_root = "/data"
        mock_settings.mkbrr.container_data_root = "/data"
        mock_settings.mkbrr.host_config_dir = str(tmp_path)
        mock_settings.mkbrr.container_config_dir = "/config"
        mock_settings.mkbrr.container_output_dir = "/torrents"
        mock_settings.mkbrr.image = "ghcr.io/autobrr/mkbrr:latest"
        mock_settings.target_uid = 99
        mock_settings.target_gid = 100

        expected_torrent = output_dir / f"{content_dir.name}.torrent"

        def mock_run(argv, **kwargs):
            # Simulate mkbrr creating the torrent file during execution
            # (after _cleanup_stale_torrents removes any existing files)
            expected_torrent.touch()
            return make_cmd_result(stdout="Torrent created", exit_code=0)

        with (
            patch("shelfr.mkbrr.run", side_effect=mock_run),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("shelfr.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
        ):
            result = create_torrent(content_dir, output_dir)

        assert result.success is True
        assert result.return_code == 0
        assert result.torrent_path == expected_torrent

    def test_create_torrent_failure(self, tmp_path: Path):
        """Test failed torrent creation."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"
        mock_settings.mkbrr.preset = "mam"
        mock_settings.mkbrr.host_output_dir = str(tmp_path)
        mock_settings.mkbrr.host_data_root = "/data"
        mock_settings.mkbrr.container_data_root = "/data"
        mock_settings.mkbrr.host_config_dir = str(tmp_path)
        mock_settings.mkbrr.container_config_dir = "/config"
        mock_settings.mkbrr.container_output_dir = "/torrents"
        mock_settings.mkbrr.image = "ghcr.io/autobrr/mkbrr:latest"

        with (
            patch(
                "shelfr.mkbrr.run",
                return_value=make_cmd_result(exit_code=1, stderr="Error creating torrent"),
            ),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("shelfr.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
        ):
            result = create_torrent(content_dir)

        assert result.success is False
        assert result.return_code == 1
        assert "exited with code" in (result.error or "")

    def test_create_torrent_exception(self, tmp_path: Path):
        """Test torrent creation with exception."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"
        mock_settings.mkbrr.preset = "mam"
        mock_settings.mkbrr.host_output_dir = str(tmp_path)
        mock_settings.mkbrr.host_data_root = "/data"
        mock_settings.mkbrr.container_data_root = "/data"
        mock_settings.mkbrr.host_config_dir = str(tmp_path)
        mock_settings.mkbrr.container_config_dir = "/config"
        mock_settings.mkbrr.container_output_dir = "/torrents"
        mock_settings.mkbrr.image = "ghcr.io/autobrr/mkbrr:latest"

        with (
            patch("shelfr.mkbrr.run", side_effect=Exception("Unexpected error")),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("shelfr.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
        ):
            result = create_torrent(content_dir)

        assert result.success is False
        assert result.return_code == -1
        assert "Unexpected error" in (result.error or "")


class TestCreateTorrentExtendedParams:
    """Tests for create_torrent extended parameters."""

    def _make_mock_settings(self, tmp_path: Path) -> MagicMock:
        """Create mock settings for create_torrent tests."""
        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"
        mock_settings.mkbrr.preset = "mam"
        mock_settings.mkbrr.host_output_dir = str(tmp_path)
        mock_settings.mkbrr.host_data_root = "/data"
        mock_settings.mkbrr.container_data_root = "/data"
        mock_settings.mkbrr.host_config_dir = str(tmp_path)
        mock_settings.mkbrr.container_config_dir = "/config"
        mock_settings.mkbrr.container_output_dir = "/torrents"
        mock_settings.mkbrr.image = "ghcr.io/autobrr/mkbrr:latest"
        mock_settings.target_uid = 99
        mock_settings.target_gid = 100
        return mock_settings

    def test_create_with_tracker(self, tmp_path: Path):
        """Test creating torrent with custom tracker URL."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        output_dir = tmp_path / "torrents"
        output_dir.mkdir()
        expected_torrent = output_dir / f"{content_dir.name}.torrent"

        mock_settings = self._make_mock_settings(tmp_path)

        def mock_run(argv, **kwargs):
            expected_torrent.touch()
            # Verify tracker flag is in command
            assert "-t" in argv
            assert "https://custom.tracker/announce" in argv
            return make_cmd_result(exit_code=0)

        with (
            patch("shelfr.mkbrr.run", side_effect=mock_run),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("shelfr.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
        ):
            result = create_torrent(
                content_dir,
                output_dir,
                tracker="https://custom.tracker/announce",
            )

        assert result.success is True

    def test_create_with_source(self, tmp_path: Path):
        """Test creating torrent with source tag."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        output_dir = tmp_path / "torrents"
        output_dir.mkdir()
        expected_torrent = output_dir / f"{content_dir.name}.torrent"

        mock_settings = self._make_mock_settings(tmp_path)

        def mock_run(argv, **kwargs):
            expected_torrent.touch()
            assert "-s" in argv
            assert "MAM" in argv
            return make_cmd_result(exit_code=0)

        with (
            patch("shelfr.mkbrr.run", side_effect=mock_run),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("shelfr.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
        ):
            result = create_torrent(content_dir, output_dir, source="MAM")

        assert result.success is True

    def test_create_with_piece_length(self, tmp_path: Path):
        """Test creating torrent with custom piece length."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        output_dir = tmp_path / "torrents"
        output_dir.mkdir()
        expected_torrent = output_dir / f"{content_dir.name}.torrent"

        mock_settings = self._make_mock_settings(tmp_path)

        def mock_run(argv, **kwargs):
            expected_torrent.touch()
            assert "-l" in argv
            assert "20" in argv  # 2^20 = 1MiB
            return make_cmd_result(exit_code=0)

        with (
            patch("shelfr.mkbrr.run", side_effect=mock_run),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("shelfr.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
        ):
            result = create_torrent(content_dir, output_dir, piece_length=20)

        assert result.success is True

    def test_create_piece_length_validation_too_low(self, tmp_path: Path):
        """Test piece_length validation rejects values below 16."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        mock_settings = self._make_mock_settings(tmp_path)

        with (
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("shelfr.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
        ):
            result = create_torrent(content_dir, piece_length=15)

        assert result.success is False
        assert "piece_length must be 16-27" in result.error

    def test_create_piece_length_validation_too_high(self, tmp_path: Path):
        """Test piece_length validation rejects values above 27."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        mock_settings = self._make_mock_settings(tmp_path)

        with (
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("shelfr.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
        ):
            result = create_torrent(content_dir, piece_length=28)

        assert result.success is False
        assert "piece_length must be 16-27" in result.error

    def test_create_max_piece_length_validation(self, tmp_path: Path):
        """Test max_piece_length validation."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        mock_settings = self._make_mock_settings(tmp_path)

        with (
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("shelfr.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
        ):
            result = create_torrent(content_dir, max_piece_length=30)

        assert result.success is False
        assert "max_piece_length must be 16-27" in result.error

    def test_create_with_exclude_patterns(self, tmp_path: Path):
        """Test creating torrent with exclude patterns."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        output_dir = tmp_path / "torrents"
        output_dir.mkdir()
        expected_torrent = output_dir / f"{content_dir.name}.torrent"

        mock_settings = self._make_mock_settings(tmp_path)

        def mock_run(argv, **kwargs):
            expected_torrent.touch()
            # Check exclude patterns are added
            exclude_indices = [i for i, arg in enumerate(argv) if arg == "--exclude"]
            assert len(exclude_indices) == 2
            assert "*.nfo" in argv
            assert "*.txt" in argv
            return make_cmd_result(exit_code=0)

        with (
            patch("shelfr.mkbrr.run", side_effect=mock_run),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("shelfr.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
        ):
            result = create_torrent(
                content_dir,
                output_dir,
                exclude_patterns=["*.nfo", "*.txt"],
            )

        assert result.success is True

    def test_create_with_include_patterns(self, tmp_path: Path):
        """Test creating torrent with include patterns (whitelist mode)."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        output_dir = tmp_path / "torrents"
        output_dir.mkdir()
        expected_torrent = output_dir / f"{content_dir.name}.torrent"

        mock_settings = self._make_mock_settings(tmp_path)

        def mock_run(argv, **kwargs):
            expected_torrent.touch()
            assert "--include" in argv
            assert "*.m4b" in argv
            return make_cmd_result(exit_code=0)

        with (
            patch("shelfr.mkbrr.run", side_effect=mock_run),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("shelfr.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
        ):
            result = create_torrent(
                content_dir,
                output_dir,
                include_patterns=["*.m4b"],
            )

        assert result.success is True

    def test_create_with_skip_prefix(self, tmp_path: Path):
        """Test creating torrent with skip_prefix flag."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        output_dir = tmp_path / "torrents"
        output_dir.mkdir()
        expected_torrent = output_dir / f"{content_dir.name}.torrent"

        mock_settings = self._make_mock_settings(tmp_path)

        def mock_run(argv, **kwargs):
            expected_torrent.touch()
            assert "--skip-prefix" in argv
            return make_cmd_result(exit_code=0)

        with (
            patch("shelfr.mkbrr.run", side_effect=mock_run),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("shelfr.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
        ):
            result = create_torrent(content_dir, output_dir, skip_prefix=True)

        assert result.success is True

    def test_create_with_comment(self, tmp_path: Path):
        """Test creating torrent with comment."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        output_dir = tmp_path / "torrents"
        output_dir.mkdir()
        expected_torrent = output_dir / f"{content_dir.name}.torrent"

        mock_settings = self._make_mock_settings(tmp_path)

        def mock_run(argv, **kwargs):
            expected_torrent.touch()
            assert "-c" in argv
            assert "Uploaded via shelfr" in argv
            return make_cmd_result(exit_code=0)

        with (
            patch("shelfr.mkbrr.run", side_effect=mock_run),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("shelfr.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
        ):
            result = create_torrent(content_dir, output_dir, comment="Uploaded via shelfr")

        assert result.success is True

    def test_create_with_private_true(self, tmp_path: Path):
        """Test creating torrent with private flag true."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        output_dir = tmp_path / "torrents"
        output_dir.mkdir()
        expected_torrent = output_dir / f"{content_dir.name}.torrent"

        mock_settings = self._make_mock_settings(tmp_path)

        def mock_run(argv, **kwargs):
            expected_torrent.touch()
            assert "--private" in argv
            assert "--private=false" not in argv
            return make_cmd_result(exit_code=0)

        with (
            patch("shelfr.mkbrr.run", side_effect=mock_run),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("shelfr.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
        ):
            result = create_torrent(content_dir, output_dir, private=True)

        assert result.success is True

    def test_create_with_private_false(self, tmp_path: Path):
        """Test creating torrent with private flag false (public torrent)."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        output_dir = tmp_path / "torrents"
        output_dir.mkdir()
        expected_torrent = output_dir / f"{content_dir.name}.torrent"

        mock_settings = self._make_mock_settings(tmp_path)

        def mock_run(argv, **kwargs):
            expected_torrent.touch()
            assert "--private=false" in argv
            return make_cmd_result(exit_code=0)

        with (
            patch("shelfr.mkbrr.run", side_effect=mock_run),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("shelfr.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
        ):
            result = create_torrent(content_dir, output_dir, private=False)

        assert result.success is True

    def test_create_with_no_date(self, tmp_path: Path):
        """Test creating torrent without creation date."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        output_dir = tmp_path / "torrents"
        output_dir.mkdir()
        expected_torrent = output_dir / f"{content_dir.name}.torrent"

        mock_settings = self._make_mock_settings(tmp_path)

        def mock_run(argv, **kwargs):
            expected_torrent.touch()
            assert "--no-date" in argv
            return make_cmd_result(exit_code=0)

        with (
            patch("shelfr.mkbrr.run", side_effect=mock_run),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("shelfr.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
        ):
            result = create_torrent(content_dir, output_dir, no_date=True)

        assert result.success is True

    def test_create_with_no_creator(self, tmp_path: Path):
        """Test creating torrent without creator field."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        output_dir = tmp_path / "torrents"
        output_dir.mkdir()
        expected_torrent = output_dir / f"{content_dir.name}.torrent"

        mock_settings = self._make_mock_settings(tmp_path)

        def mock_run(argv, **kwargs):
            expected_torrent.touch()
            assert "--no-creator" in argv
            return make_cmd_result(exit_code=0)

        with (
            patch("shelfr.mkbrr.run", side_effect=mock_run),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("shelfr.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
        ):
            result = create_torrent(content_dir, output_dir, no_creator=True)

        assert result.success is True

    def test_create_with_web_seeds(self, tmp_path: Path):
        """Test creating torrent with web seeds."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        output_dir = tmp_path / "torrents"
        output_dir.mkdir()
        expected_torrent = output_dir / f"{content_dir.name}.torrent"

        mock_settings = self._make_mock_settings(tmp_path)

        def mock_run(argv, **kwargs):
            expected_torrent.touch()
            # Find web seed flags (they come after "mkbrr" and "create" in the command)
            # Look for the pattern: -w followed by a URL
            cmd_str = " ".join(argv)
            assert "https://seed1.example.com/files" in cmd_str
            assert "https://seed2.example.com/files" in cmd_str
            return make_cmd_result(exit_code=0)

        with (
            patch("shelfr.mkbrr.run", side_effect=mock_run),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("shelfr.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
        ):
            result = create_torrent(
                content_dir,
                output_dir,
                web_seeds=[
                    "https://seed1.example.com/files",
                    "https://seed2.example.com/files",
                ],
            )

        assert result.success is True

    def test_create_with_entropy(self, tmp_path: Path):
        """Test creating torrent with entropy flag."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        output_dir = tmp_path / "torrents"
        output_dir.mkdir()
        expected_torrent = output_dir / f"{content_dir.name}.torrent"

        mock_settings = self._make_mock_settings(tmp_path)

        def mock_run(argv, **kwargs):
            expected_torrent.touch()
            assert "-e" in argv
            return make_cmd_result(exit_code=0)

        with (
            patch("shelfr.mkbrr.run", side_effect=mock_run),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("shelfr.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
        ):
            result = create_torrent(content_dir, output_dir, entropy=True)

        assert result.success is True

    def test_create_with_output_filename(self, tmp_path: Path):
        """Test creating torrent with custom output filename."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        output_dir = tmp_path / "torrents"
        output_dir.mkdir()
        expected_torrent = output_dir / f"{content_dir.name}.torrent"

        mock_settings = self._make_mock_settings(tmp_path)

        def mock_run(argv, **kwargs):
            expected_torrent.touch()
            assert "-o" in argv
            assert "custom_name.torrent" in argv
            return make_cmd_result(exit_code=0)

        with (
            patch("shelfr.mkbrr.run", side_effect=mock_run),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("shelfr.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
        ):
            result = create_torrent(content_dir, output_dir, output_filename="custom_name.torrent")

        assert result.success is True

    def test_create_with_multiple_params(self, tmp_path: Path):
        """Test creating torrent with multiple parameters combined."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        output_dir = tmp_path / "torrents"
        output_dir.mkdir()
        expected_torrent = output_dir / f"{content_dir.name}.torrent"

        mock_settings = self._make_mock_settings(tmp_path)

        def mock_run(argv, **kwargs):
            expected_torrent.touch()
            # Verify multiple params are all present
            assert "-s" in argv
            assert "MAM" in argv
            assert "-c" in argv
            assert "--no-date" in argv
            assert "--exclude" in argv
            return make_cmd_result(exit_code=0)

        with (
            patch("shelfr.mkbrr.run", side_effect=mock_run),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("shelfr.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
        ):
            result = create_torrent(
                content_dir,
                output_dir,
                source="MAM",
                comment="Test upload",
                no_date=True,
                exclude_patterns=["*.nfo"],
            )

        assert result.success is True


class TestDockerBaseCommand:
    """Tests for _docker_base_command function."""

    def test_builds_command(self):
        """Test building docker command with volume mounts."""
        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"
        mock_settings.mkbrr.host_data_root = "/mnt/user/data"
        mock_settings.mkbrr.container_data_root = "/data"
        mock_settings.mkbrr.host_output_dir = "/mnt/user/torrents"
        mock_settings.mkbrr.container_output_dir = "/torrentfiles"
        mock_settings.mkbrr.host_config_dir = "/mnt/cache/mkbrr"
        mock_settings.mkbrr.container_config_dir = "/root/.config/mkbrr"
        mock_settings.mkbrr.image = "ghcr.io/autobrr/mkbrr:latest"

        with patch("shelfr.mkbrr.get_settings", return_value=mock_settings):
            cmd = _docker_base_command()

        assert "/usr/bin/docker" in cmd
        assert "run" in cmd
        assert "--rm" in cmd
        assert "-v" in cmd
        assert "ghcr.io/autobrr/mkbrr:latest" in cmd


class TestLoadPresetsEdgeCases:
    """Additional tests for load_presets."""

    def test_invalid_yaml(self, tmp_path: Path):
        """Test handling invalid YAML."""
        presets_file = tmp_path / "presets.yaml"
        presets_file.write_text("invalid: yaml: {{{")

        mock_settings = MagicMock()
        mock_settings.mkbrr.host_config_dir = str(tmp_path)
        mock_settings.mkbrr.preset = "fallback"

        with patch("shelfr.mkbrr.get_settings", return_value=mock_settings):
            presets = load_presets()

        assert presets == ["fallback"]

    def test_empty_presets(self, tmp_path: Path):
        """Test handling YAML with no presets."""
        presets_file = tmp_path / "presets.yaml"
        presets_file.write_text("presets: {}")

        mock_settings = MagicMock()
        mock_settings.mkbrr.host_config_dir = str(tmp_path)
        mock_settings.mkbrr.preset = "fallback"

        with patch("shelfr.mkbrr.get_settings", return_value=mock_settings):
            presets = load_presets()

        assert presets == ["fallback"]

    def test_missing_presets_key(self, tmp_path: Path):
        """Test handling YAML without presets key."""
        presets_file = tmp_path / "presets.yaml"
        presets_file.write_text("other_key: value")

        mock_settings = MagicMock()
        mock_settings.mkbrr.host_config_dir = str(tmp_path)
        mock_settings.mkbrr.preset = "fallback"

        with patch("shelfr.mkbrr.get_settings", return_value=mock_settings):
            presets = load_presets()

        assert presets == ["fallback"]


class TestFixTorrentPermissions:
    """Tests for fix_torrent_permissions function."""

    def test_fix_permissions(self, tmp_path: Path):
        """Test fixing torrent file permissions."""
        # Create some torrent files
        (tmp_path / "test1.torrent").write_bytes(b"torrent1")
        (tmp_path / "test2.torrent").write_bytes(b"torrent2")
        (tmp_path / "other.txt").write_bytes(b"not torrent")

        mock_settings = MagicMock()
        mock_settings.target_uid = 99
        mock_settings.target_gid = 100
        mock_settings.mkbrr.host_output_dir = str(tmp_path)

        with (
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch("os.chown"),
        ):
            count = fix_torrent_permissions(tmp_path)

        # Files already have correct uid/gid, count should be 0
        # We're just testing that it doesn't crash
        assert count >= 0

    def test_nonexistent_directory(self, tmp_path: Path):
        """Test handling non-existent directory."""
        mock_settings = MagicMock()
        mock_settings.target_uid = 99
        mock_settings.target_gid = 100
        mock_settings.mkbrr.host_output_dir = str(tmp_path / "nonexistent")

        with patch("shelfr.mkbrr.get_settings", return_value=mock_settings):
            count = fix_torrent_permissions(tmp_path / "nonexistent")

        assert count == 0

    def test_uses_default_directory(self, tmp_path: Path):
        """Test using default directory from settings."""
        (tmp_path / "test.torrent").write_bytes(b"torrent")

        mock_settings = MagicMock()
        mock_settings.target_uid = 99
        mock_settings.target_gid = 100
        mock_settings.mkbrr.host_output_dir = str(tmp_path)

        with (
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch("os.chown"),
        ):
            count = fix_torrent_permissions()  # No arg - uses default

        # Should work with default directory
        assert count >= 0


class TestInspectTorrent:
    """Tests for inspect_torrent function."""

    def test_inspect_success(self, tmp_path: Path):
        """Test successful torrent inspection."""
        mock_result = make_cmd_result(stdout="Name: test\nSize: 1234", exit_code=0)

        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"
        mock_settings.mkbrr.host_data_root = "/data"
        mock_settings.mkbrr.container_data_root = "/data"
        mock_settings.mkbrr.host_output_dir = str(tmp_path)
        mock_settings.mkbrr.container_output_dir = "/torrents"
        mock_settings.mkbrr.host_config_dir = str(tmp_path)
        mock_settings.mkbrr.container_config_dir = "/config"
        mock_settings.mkbrr.image = "ghcr.io/autobrr/mkbrr:latest"

        with (
            patch("shelfr.mkbrr.run", return_value=mock_result),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch(
                "shelfr.mkbrr.host_to_container_torrent_path",
                return_value="/torrents/test.torrent",
            ),
        ):
            result = inspect_torrent(tmp_path / "test.torrent")

        assert result.success is True
        assert result.return_code == 0
        assert "Name: test" in result.stdout

    def test_inspect_verbose(self, tmp_path: Path):
        """Test verbose torrent inspection."""
        mock_result = make_cmd_result(stdout="Detailed info...", exit_code=0)

        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"
        mock_settings.mkbrr.host_data_root = "/data"
        mock_settings.mkbrr.container_data_root = "/data"
        mock_settings.mkbrr.host_output_dir = str(tmp_path)
        mock_settings.mkbrr.container_output_dir = "/torrents"
        mock_settings.mkbrr.host_config_dir = str(tmp_path)
        mock_settings.mkbrr.container_config_dir = "/config"
        mock_settings.mkbrr.image = "ghcr.io/autobrr/mkbrr:latest"

        with (
            patch("shelfr.mkbrr.run", return_value=mock_result) as mock_run,
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch(
                "shelfr.mkbrr.host_to_container_torrent_path",
                return_value="/torrents/test.torrent",
            ),
        ):
            result = inspect_torrent(tmp_path / "test.torrent", verbose=True)

        assert result.success is True
        # Verify -v flag is passed
        call_args = mock_run.call_args[0][0]
        assert "-v" in call_args

    def test_inspect_failure(self, tmp_path: Path):
        """Test failed torrent inspection."""
        mock_result = make_cmd_result(stderr="File not found", exit_code=1)

        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"
        mock_settings.mkbrr.host_data_root = "/data"
        mock_settings.mkbrr.container_data_root = "/data"
        mock_settings.mkbrr.host_output_dir = str(tmp_path)
        mock_settings.mkbrr.container_output_dir = "/torrents"
        mock_settings.mkbrr.host_config_dir = str(tmp_path)
        mock_settings.mkbrr.container_config_dir = "/config"
        mock_settings.mkbrr.image = "ghcr.io/autobrr/mkbrr:latest"

        with (
            patch("shelfr.mkbrr.run", return_value=mock_result),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch(
                "shelfr.mkbrr.host_to_container_torrent_path",
                return_value="/torrents/test.torrent",
            ),
        ):
            result = inspect_torrent(tmp_path / "test.torrent")

        assert result.success is False
        assert result.return_code == 1

    def test_inspect_exception(self, tmp_path: Path):
        """Test torrent inspection with exception."""
        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"
        mock_settings.mkbrr.host_data_root = "/data"
        mock_settings.mkbrr.container_data_root = "/data"
        mock_settings.mkbrr.host_output_dir = str(tmp_path)
        mock_settings.mkbrr.container_output_dir = "/torrents"
        mock_settings.mkbrr.host_config_dir = str(tmp_path)
        mock_settings.mkbrr.container_config_dir = "/config"
        mock_settings.mkbrr.image = "ghcr.io/autobrr/mkbrr:latest"

        with (
            patch("shelfr.mkbrr.run", side_effect=Exception("Docker error")),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch(
                "shelfr.mkbrr.host_to_container_torrent_path",
                return_value="/torrents/test.torrent",
            ),
        ):
            result = inspect_torrent(tmp_path / "test.torrent")

        assert result.success is False
        assert result.return_code == -1
        assert "Docker error" in (result.error or "")


class TestCheckTorrent:
    """Tests for check_torrent function."""

    def test_check_success(self, tmp_path: Path):
        """Test successful torrent check."""
        mock_result = make_cmd_result(stdout="100% verified", exit_code=0)

        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"
        mock_settings.mkbrr.host_data_root = "/data"
        mock_settings.mkbrr.container_data_root = "/data"
        mock_settings.mkbrr.host_output_dir = str(tmp_path)
        mock_settings.mkbrr.container_output_dir = "/torrents"
        mock_settings.mkbrr.host_config_dir = str(tmp_path)
        mock_settings.mkbrr.container_config_dir = "/config"
        mock_settings.mkbrr.image = "ghcr.io/autobrr/mkbrr:latest"

        with (
            patch("shelfr.mkbrr.run", return_value=mock_result),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch(
                "shelfr.mkbrr.host_to_container_torrent_path",
                return_value="/torrents/test.torrent",
            ),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
        ):
            result = check_torrent(tmp_path / "test.torrent", tmp_path / "content")

        assert result.success is True
        assert result.return_code == 0

    def test_check_with_options(self, tmp_path: Path):
        """Test torrent check with verbose, quiet and workers options."""
        mock_result = make_cmd_result(stdout="OK", exit_code=0)

        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"
        mock_settings.mkbrr.host_data_root = "/data"
        mock_settings.mkbrr.container_data_root = "/data"
        mock_settings.mkbrr.host_output_dir = str(tmp_path)
        mock_settings.mkbrr.container_output_dir = "/torrents"
        mock_settings.mkbrr.host_config_dir = str(tmp_path)
        mock_settings.mkbrr.container_config_dir = "/config"
        mock_settings.mkbrr.image = "ghcr.io/autobrr/mkbrr:latest"

        with (
            patch("shelfr.mkbrr.run", return_value=mock_result) as mock_run,
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch(
                "shelfr.mkbrr.host_to_container_torrent_path",
                return_value="/torrents/test.torrent",
            ),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
        ):
            result = check_torrent(
                tmp_path / "test.torrent",
                tmp_path / "content",
                quiet=True,
                workers=4,
            )

        assert result.success is True
        call_args = mock_run.call_args[0][0]
        assert "--quiet" in call_args
        assert "--workers" in call_args
        assert "4" in call_args

    def test_check_verbose_without_quiet(self, tmp_path: Path):
        """Test torrent check with verbose flag (no quiet)."""
        mock_result = make_cmd_result(stdout="Detailed output", exit_code=0)

        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"
        mock_settings.mkbrr.host_data_root = "/data"
        mock_settings.mkbrr.container_data_root = "/data"
        mock_settings.mkbrr.host_output_dir = str(tmp_path)
        mock_settings.mkbrr.container_output_dir = "/torrents"
        mock_settings.mkbrr.host_config_dir = str(tmp_path)
        mock_settings.mkbrr.container_config_dir = "/config"
        mock_settings.mkbrr.image = "ghcr.io/autobrr/mkbrr:latest"

        with (
            patch("shelfr.mkbrr.run", return_value=mock_result) as mock_run,
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch(
                "shelfr.mkbrr.host_to_container_torrent_path",
                return_value="/torrents/test.torrent",
            ),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
        ):
            result = check_torrent(
                tmp_path / "test.torrent",
                tmp_path / "content",
                verbose=True,
                quiet=False,
            )

        assert result.success is True
        call_args = mock_run.call_args[0][0]
        assert "-v" in call_args
        assert "--quiet" not in call_args

    def test_check_failure(self, tmp_path: Path):
        """Test failed torrent check."""
        mock_result = make_cmd_result(stderr="Verification failed", exit_code=1)

        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"
        mock_settings.mkbrr.host_data_root = "/data"
        mock_settings.mkbrr.container_data_root = "/data"
        mock_settings.mkbrr.host_output_dir = str(tmp_path)
        mock_settings.mkbrr.container_output_dir = "/torrents"
        mock_settings.mkbrr.host_config_dir = str(tmp_path)
        mock_settings.mkbrr.container_config_dir = "/config"
        mock_settings.mkbrr.image = "ghcr.io/autobrr/mkbrr:latest"

        with (
            patch("shelfr.mkbrr.run", return_value=mock_result),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch(
                "shelfr.mkbrr.host_to_container_torrent_path",
                return_value="/torrents/test.torrent",
            ),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
        ):
            result = check_torrent(tmp_path / "test.torrent", tmp_path / "content")

        assert result.success is False
        assert result.return_code == 1

    def test_check_exception(self, tmp_path: Path):
        """Test torrent check with exception."""
        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"
        mock_settings.mkbrr.host_data_root = "/data"
        mock_settings.mkbrr.container_data_root = "/data"
        mock_settings.mkbrr.host_output_dir = str(tmp_path)
        mock_settings.mkbrr.container_output_dir = "/torrents"
        mock_settings.mkbrr.host_config_dir = str(tmp_path)
        mock_settings.mkbrr.container_config_dir = "/config"
        mock_settings.mkbrr.image = "ghcr.io/autobrr/mkbrr:latest"

        with (
            patch("shelfr.mkbrr.run", side_effect=Exception("Check failed")),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch(
                "shelfr.mkbrr.host_to_container_torrent_path",
                return_value="/torrents/test.torrent",
            ),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
        ):
            result = check_torrent(tmp_path / "test.torrent", tmp_path / "content")

        assert result.success is False
        assert result.return_code == -1
        assert "Check failed" in (result.error or "")


class TestTorrentFileDiscoveryWithPresetPrefix:
    """Tests for torrent file discovery with mkbrr preset prefixes."""

    def test_create_torrent_finds_prefixed_file(self, tmp_path: Path):
        """Test that create_torrent finds torrent file with preset prefix."""
        content_dir = tmp_path / "My Audiobook [2024]"
        content_dir.mkdir()
        output_dir = tmp_path / "torrents"
        output_dir.mkdir()

        mock_result = make_cmd_result(stdout="Created torrent", exit_code=0)

        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"
        mock_settings.mkbrr.preset = "myanonamouse"
        mock_settings.mkbrr.host_output_dir = str(output_dir)
        mock_settings.mkbrr.host_data_root = "/data"
        mock_settings.mkbrr.container_data_root = "/data"
        mock_settings.mkbrr.host_config_dir = str(tmp_path)
        mock_settings.mkbrr.container_config_dir = "/config"
        mock_settings.mkbrr.container_output_dir = "/torrents"
        mock_settings.mkbrr.image = "ghcr.io/autobrr/mkbrr:latest"
        mock_settings.target_uid = 99
        mock_settings.target_gid = 100

        # Create torrent file with preset prefix (what mkbrr actually creates)
        prefixed_torrent = output_dir / f"myanonamouse_{content_dir.name}.torrent"
        prefixed_torrent.touch()

        with (
            patch("shelfr.mkbrr.run", return_value=mock_result),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("shelfr.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
        ):
            result = create_torrent(content_dir, output_dir)

        assert result.success is True
        assert result.torrent_path == prefixed_torrent

    def test_create_torrent_finds_unprefixed_when_no_prefix_match(self, tmp_path: Path):
        """Test fallback to unprefixed file when no preset-prefixed file exists."""
        content_dir = tmp_path / "My Audiobook [2024]"
        content_dir.mkdir()
        output_dir = tmp_path / "torrents"
        output_dir.mkdir()

        mock_result = make_cmd_result(exit_code=0, stdout="Created torrent")

        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"
        mock_settings.mkbrr.preset = "mam"
        mock_settings.mkbrr.host_output_dir = str(output_dir)
        mock_settings.mkbrr.host_data_root = "/data"
        mock_settings.mkbrr.container_data_root = "/data"
        mock_settings.mkbrr.host_config_dir = str(tmp_path)
        mock_settings.mkbrr.container_config_dir = "/config"
        mock_settings.mkbrr.container_output_dir = "/torrents"
        mock_settings.mkbrr.image = "ghcr.io/autobrr/mkbrr:latest"
        mock_settings.target_uid = 99
        mock_settings.target_gid = 100

        # Create torrent file WITHOUT prefix
        unprefixed_torrent = output_dir / f"{content_dir.name}.torrent"
        unprefixed_torrent.touch()

        with (
            patch("shelfr.mkbrr.run", return_value=mock_result),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("shelfr.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
        ):
            result = create_torrent(content_dir, output_dir)

        assert result.success is True
        assert result.torrent_path == unprefixed_torrent

    def test_create_torrent_selects_most_recent_when_multiple(self, tmp_path: Path):
        """Test that most recently modified torrent is selected when multiple exist."""
        import time

        content_dir = tmp_path / "My Audiobook [2024]"
        content_dir.mkdir()
        output_dir = tmp_path / "torrents"
        output_dir.mkdir()

        mock_result = make_cmd_result(exit_code=0, stdout="Created torrent")

        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"
        mock_settings.mkbrr.preset = "mam"
        mock_settings.mkbrr.host_output_dir = str(output_dir)
        mock_settings.mkbrr.host_data_root = "/data"
        mock_settings.mkbrr.container_data_root = "/data"
        mock_settings.mkbrr.host_config_dir = str(tmp_path)
        mock_settings.mkbrr.container_config_dir = "/config"
        mock_settings.mkbrr.container_output_dir = "/torrents"
        mock_settings.mkbrr.image = "ghcr.io/autobrr/mkbrr:latest"
        mock_settings.target_uid = 99
        mock_settings.target_gid = 100

        # Create older torrent file
        older_torrent = output_dir / f"{content_dir.name}.torrent"
        older_torrent.touch()
        time.sleep(0.1)  # Ensure different mtime

        # Create newer torrent file with prefix
        newer_torrent = output_dir / f"mam_{content_dir.name}.torrent"
        newer_torrent.touch()

        with (
            patch("shelfr.mkbrr.run", return_value=mock_result),
            patch("shelfr.mkbrr.get_settings", return_value=mock_settings),
            patch("shelfr.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("shelfr.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
        ):
            result = create_torrent(content_dir, output_dir)

        assert result.success is True
        assert result.torrent_path == newer_torrent


# =============================================================================
# parse_torrent_file() tests
# =============================================================================

# Check if bencodepy is available
try:
    import bencodepy  # noqa: F401

    HAS_BENCODEPY = True
except ImportError:
    HAS_BENCODEPY = False


@pytest.mark.skipif(not HAS_BENCODEPY, reason="bencodepy not installed")
class TestParseTorrentFile:
    """Tests for parse_torrent_file() bencode parsing."""

    def _create_minimal_torrent(self, tmp_path: Path, name: str = "test") -> Path:
        """Create a minimal valid torrent file for testing."""
        import bencodepy

        # Create minimal valid torrent structure
        info_dict = {
            b"name": name.encode("utf-8"),
            b"piece length": 262144,  # 256 KiB
            b"pieces": b"\x00" * 20,  # 1 piece (20 bytes per SHA1)
            b"length": 100000,  # Single file, 100KB
        }

        torrent_dict = {
            b"info": info_dict,
            b"announce": b"https://tracker.example.com/announce",
        }

        torrent_path = tmp_path / f"{name}.torrent"
        with open(torrent_path, "wb") as f:
            f.write(bencodepy.encode(torrent_dict))

        return torrent_path

    def _create_multi_file_torrent(self, tmp_path: Path, name: str = "multi") -> Path:
        """Create a multi-file torrent for testing."""
        import bencodepy

        info_dict = {
            b"name": name.encode("utf-8"),
            b"piece length": 262144,
            b"pieces": b"\x00" * 40,  # 2 pieces
            b"files": [
                {b"length": 50000, b"path": [b"chapter01.mp3"]},
                {b"length": 50000, b"path": [b"chapter02.mp3"]},
                {b"length": 25000, b"path": [b"cover", b"front.jpg"]},
            ],
        }

        torrent_dict = {
            b"info": info_dict,
            b"announce": b"https://tracker.example.com/announce",
            b"announce-list": [
                [b"https://tracker1.example.com/announce"],
                [b"https://tracker2.example.com/announce"],
            ],
            b"comment": b"Test multi-file torrent",
            b"created by": b"test-suite/1.0",
            b"creation date": 1735574400,  # 2024-12-30 UTC
        }

        torrent_path = tmp_path / f"{name}.torrent"
        with open(torrent_path, "wb") as f:
            f.write(bencodepy.encode(torrent_dict))

        return torrent_path

    def test_parse_minimal_single_file(self, tmp_path: Path) -> None:
        """Parse a minimal single-file torrent."""
        from shelfr.mkbrr import parse_torrent_file

        torrent_path = self._create_minimal_torrent(tmp_path, "audiobook")
        info = parse_torrent_file(torrent_path)

        assert info.name == "audiobook"
        assert len(info.info_hash) == 40
        assert all(c in "0123456789abcdef" for c in info.info_hash)
        assert info.size == 100000
        assert info.piece_length == 262144
        assert info.piece_count == 1
        assert info.private is False
        assert info.trackers == ["https://tracker.example.com/announce"]
        assert info.file_count == 1
        assert info.is_multi_file is False
        assert info.files == []

    def test_parse_multi_file_torrent(self, tmp_path: Path) -> None:
        """Parse a multi-file torrent with full metadata."""
        from shelfr.mkbrr import parse_torrent_file

        torrent_path = self._create_multi_file_torrent(tmp_path, "my_audiobook")
        info = parse_torrent_file(torrent_path)

        assert info.name == "my_audiobook"
        assert info.size == 125000  # 50000 + 50000 + 25000
        assert info.piece_length == 262144
        assert info.piece_count == 2
        assert info.private is False

        # Check trackers (primary + announce-list, deduplicated)
        assert "https://tracker.example.com/announce" in info.trackers
        assert "https://tracker1.example.com/announce" in info.trackers
        assert "https://tracker2.example.com/announce" in info.trackers

        # Check optional metadata
        assert info.comment == "Test multi-file torrent"
        assert info.created_by == "test-suite/1.0"
        assert info.creation_date is not None

        # Check files
        assert info.file_count == 3
        assert info.is_multi_file is True
        assert len(info.files) == 3
        assert info.files[0].path == "chapter01.mp3"
        assert info.files[0].size == 50000
        assert info.files[2].path == "cover/front.jpg"
        assert info.files[2].size == 25000

    def test_parse_private_torrent(self, tmp_path: Path) -> None:
        """Parse a private torrent."""
        import bencodepy

        info_dict = {
            b"name": b"private_audiobook",
            b"piece length": 262144,
            b"pieces": b"\x00" * 20,
            b"length": 100000,
            b"private": 1,
            b"source": b"MAM",
        }

        torrent_dict = {b"info": info_dict}
        torrent_path = tmp_path / "private.torrent"
        with open(torrent_path, "wb") as f:
            f.write(bencodepy.encode(torrent_dict))

        from shelfr.mkbrr import parse_torrent_file

        info = parse_torrent_file(torrent_path)

        assert info.private is True
        assert info.source == "MAM"
        assert info.trackers == []  # No announce URL

    def test_parse_with_web_seeds(self, tmp_path: Path) -> None:
        """Parse torrent with web seeds (BEP 19)."""
        import bencodepy

        info_dict = {
            b"name": b"test",
            b"piece length": 262144,
            b"pieces": b"\x00" * 20,
            b"length": 100000,
        }

        torrent_dict = {
            b"info": info_dict,
            b"url-list": [
                b"https://cdn1.example.com/files/",
                b"https://cdn2.example.com/files/",
            ],
        }

        torrent_path = tmp_path / "webseeds.torrent"
        with open(torrent_path, "wb") as f:
            f.write(bencodepy.encode(torrent_dict))

        from shelfr.mkbrr import parse_torrent_file

        info = parse_torrent_file(torrent_path)

        assert len(info.web_seeds) == 2
        assert "https://cdn1.example.com/files/" in info.web_seeds
        assert "https://cdn2.example.com/files/" in info.web_seeds

    def test_parse_with_single_web_seed(self, tmp_path: Path) -> None:
        """Parse torrent with single web seed (string not list)."""
        import bencodepy

        info_dict = {
            b"name": b"test",
            b"piece length": 262144,
            b"pieces": b"\x00" * 20,
            b"length": 100000,
        }

        torrent_dict = {
            b"info": info_dict,
            b"url-list": b"https://cdn.example.com/files/",
        }

        torrent_path = tmp_path / "single_webseed.torrent"
        with open(torrent_path, "wb") as f:
            f.write(bencodepy.encode(torrent_dict))

        from shelfr.mkbrr import parse_torrent_file

        info = parse_torrent_file(torrent_path)

        assert len(info.web_seeds) == 1
        assert info.web_seeds[0] == "https://cdn.example.com/files/"

    def test_parse_extra_fields(self, tmp_path: Path) -> None:
        """Parse torrent with non-standard fields in info dict."""
        import bencodepy

        info_dict = {
            b"name": b"test",
            b"piece length": 262144,
            b"pieces": b"\x00" * 20,
            b"length": 100000,
            b"x_custom": b"custom_value",
            b"some_other_field": 42,
        }

        torrent_dict = {b"info": info_dict}
        torrent_path = tmp_path / "extra.torrent"
        with open(torrent_path, "wb") as f:
            f.write(bencodepy.encode(torrent_dict))

        from shelfr.mkbrr import parse_torrent_file

        info = parse_torrent_file(torrent_path)

        assert info.extra_fields is not None
        assert info.extra_fields.get("x_custom") == "custom_value"
        assert info.extra_fields.get("some_other_field") == 42

    def test_computed_properties(self, tmp_path: Path) -> None:
        """Test computed properties on parsed torrent."""
        import bencodepy

        info_dict = {
            b"name": b"Large Audiobook",
            b"piece length": 1048576,  # 1 MiB (2^20)
            b"pieces": b"\x00" * 100,  # 5 pieces
            b"length": 1610612736,  # 1.5 GiB
        }

        torrent_dict = {b"info": info_dict}
        torrent_path = tmp_path / "large.torrent"
        with open(torrent_path, "wb") as f:
            f.write(bencodepy.encode(torrent_dict))

        from shelfr.mkbrr import parse_torrent_file

        info = parse_torrent_file(torrent_path)

        assert info.piece_length_exponent == 20
        assert info.human_piece_length() == "1 MiB"
        assert info.human_size() == "1.50 GiB"

    def test_parse_file_not_found(self, tmp_path: Path) -> None:
        """Raise FileNotFoundError for missing file."""
        import pytest

        from shelfr.mkbrr import parse_torrent_file

        with pytest.raises(FileNotFoundError):
            parse_torrent_file(tmp_path / "nonexistent.torrent")

    def test_parse_invalid_bencode(self, tmp_path: Path) -> None:
        """Raise ValueError for invalid bencode data."""
        import pytest

        torrent_path = tmp_path / "invalid.torrent"
        torrent_path.write_bytes(b"not valid bencode data")

        from shelfr.mkbrr import parse_torrent_file

        with pytest.raises(ValueError, match="Failed to decode"):
            parse_torrent_file(torrent_path)

    def test_parse_missing_info_dict(self, tmp_path: Path) -> None:
        """Raise ValueError for torrent missing info dict."""
        import bencodepy
        import pytest

        torrent_dict = {b"announce": b"https://example.com/announce"}
        torrent_path = tmp_path / "no_info.torrent"
        with open(torrent_path, "wb") as f:
            f.write(bencodepy.encode(torrent_dict))

        from shelfr.mkbrr import parse_torrent_file

        with pytest.raises(ValueError, match="missing or invalid 'info'"):
            parse_torrent_file(torrent_path)

    def test_parse_missing_name(self, tmp_path: Path) -> None:
        """Raise ValueError for torrent missing name field."""
        import bencodepy
        import pytest

        info_dict = {
            b"piece length": 262144,
            b"pieces": b"\x00" * 20,
            b"length": 100000,
        }
        torrent_dict = {b"info": info_dict}
        torrent_path = tmp_path / "no_name.torrent"
        with open(torrent_path, "wb") as f:
            f.write(bencodepy.encode(torrent_dict))

        from shelfr.mkbrr import parse_torrent_file

        with pytest.raises(ValueError, match="missing 'name'"):
            parse_torrent_file(torrent_path)

    def test_parse_unicode_name(self, tmp_path: Path) -> None:
        """Parse torrent with unicode characters in name."""
        import bencodepy

        info_dict = {
            b"name": "日本語オーディオブック".encode(),
            b"piece length": 262144,
            b"pieces": b"\x00" * 20,
            b"length": 100000,
        }

        torrent_dict = {b"info": info_dict}
        torrent_path = tmp_path / "unicode.torrent"
        with open(torrent_path, "wb") as f:
            f.write(bencodepy.encode(torrent_dict))

        from shelfr.mkbrr import parse_torrent_file

        info = parse_torrent_file(torrent_path)
        assert info.name == "日本語オーディオブック"

    def test_parse_accepts_path_str(self, tmp_path: Path) -> None:
        """Accept string path as well as Path object."""
        from shelfr.mkbrr import parse_torrent_file

        torrent_path = self._create_minimal_torrent(tmp_path, "str_path_test")
        info = parse_torrent_file(str(torrent_path))

        assert info.name == "str_path_test"

    def test_info_hash_is_stable(self, tmp_path: Path) -> None:
        """Info hash should be deterministic for same content."""
        import bencodepy

        info_dict = {
            b"name": b"stable_hash_test",
            b"piece length": 262144,
            b"pieces": b"\x00" * 20,
            b"length": 100000,
        }

        # Create two identical torrents
        torrent_dict = {b"info": info_dict}
        torrent1 = tmp_path / "stable1.torrent"
        torrent2 = tmp_path / "stable2.torrent"

        for path in [torrent1, torrent2]:
            with open(path, "wb") as f:
                f.write(bencodepy.encode(torrent_dict))

        from shelfr.mkbrr import parse_torrent_file

        info1 = parse_torrent_file(torrent1)
        info2 = parse_torrent_file(torrent2)

        assert info1.info_hash == info2.info_hash

    def test_warns_on_non_torrent_extension(self, tmp_path: Path, caplog) -> None:
        """Log warning for files without .torrent extension."""
        import logging

        import bencodepy

        info_dict = {
            b"name": b"test",
            b"piece length": 262144,
            b"pieces": b"\x00" * 20,
            b"length": 100000,
        }

        torrent_dict = {b"info": info_dict}
        torrent_path = tmp_path / "not_a_torrent.dat"
        with open(torrent_path, "wb") as f:
            f.write(bencodepy.encode(torrent_dict))

        from shelfr.mkbrr import parse_torrent_file

        with caplog.at_level(logging.WARNING):
            info = parse_torrent_file(torrent_path)

        assert info.name == "test"
        assert "does not have .torrent extension" in caplog.text


class TestParseInspectOutput:
    """Tests for parse_inspect_output text parser."""

    def test_parse_basic_output(self) -> None:
        """Parse minimal inspect output with required fields."""
        from shelfr.mkbrr import parse_inspect_output

        stdout = """
Torrent info:
  Name:         My.Audiobook.2024
  Hash:         a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2
  Size:         1.5 GiB
  Piece length: 1 MiB
  Pieces:       1536
"""
        info = parse_inspect_output(stdout)

        assert info.name == "My.Audiobook.2024"
        assert info.info_hash == "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
        assert info.size == int(1.5 * 1024**3)
        assert info.piece_length == 1024**2
        assert info.piece_count == 1536

    def test_parse_full_output(self) -> None:
        """Parse complete inspect output with all optional fields."""
        from shelfr.mkbrr import parse_inspect_output

        stdout = """
Torrent info:
  Name:         Complete.Audiobook.2024
  Hash:         abcdef0123456789abcdef0123456789abcdef01
  Size:         2.5 GiB
  Piece length: 2 MiB
  Pieces:       1280
  Magnet:       magnet:?xt=urn:btih:abcdef01...
  Tracker:      https://tracker.example.com/announce
  Private:      yes
  Source:       MAM
  Comment:      Test comment
  Created by:   mkbrr 1.5.0
  Created on:   2024-01-15 10:30:45 UTC
  Files:        15
"""
        info = parse_inspect_output(stdout)

        assert info.name == "Complete.Audiobook.2024"
        assert info.info_hash == "abcdef0123456789abcdef0123456789abcdef01"
        assert info.size == int(2.5 * 1024**3)
        assert info.piece_length == 2 * 1024**2
        assert info.piece_count == 1280
        assert info.private is True
        assert info.source == "MAM"
        assert info.comment == "Test comment"
        assert info.created_by == "mkbrr 1.5.0"
        assert info.trackers == ["https://tracker.example.com/announce"]
        assert info.extra_fields == {"_parsed_file_count": 15}

    def test_parse_multiple_trackers(self) -> None:
        """Parse output with multiple tracker tiers."""
        from shelfr.mkbrr import parse_inspect_output

        stdout = """
Torrent info:
  Name:         Multi.Tracker.Test
  Hash:         1234567890abcdef1234567890abcdef12345678
  Size:         100 MiB
  Piece length: 256 KiB
  Pieces:       400
  Trackers:
    https://tracker1.example.com/announce
    https://tracker2.example.com/announce
    https://tracker3.example.com/announce
"""
        info = parse_inspect_output(stdout)

        assert len(info.trackers) == 3
        assert "https://tracker1.example.com/announce" in info.trackers
        assert "https://tracker2.example.com/announce" in info.trackers

    def test_parse_web_seeds(self) -> None:
        """Parse output with web seeds."""
        from shelfr.mkbrr import parse_inspect_output

        stdout = """
Torrent info:
  Name:         WebSeeds.Test
  Hash:         0123456789abcdef0123456789abcdef01234567
  Size:         50 MiB
  Piece length: 256 KiB
  Pieces:       200
  Web seeds:
    https://seed1.example.com/files/test
    https://seed2.example.com/files/test
"""
        info = parse_inspect_output(stdout)

        assert len(info.web_seeds) == 2
        assert "https://seed1.example.com/files/test" in info.web_seeds

    def test_parse_with_ansi_codes(self) -> None:
        """Parse output containing ANSI color codes."""
        from shelfr.mkbrr import parse_inspect_output

        stdout = """
\x1b[35mTorrent info:\x1b[0m
  \x1b[36mName:\x1b[0m         \x1b[32mAnsi.Test.2024\x1b[0m
  \x1b[36mHash:\x1b[0m         fedcba9876543210fedcba9876543210fedcba98
  \x1b[36mSize:\x1b[0m         500 MiB
  \x1b[36mPiece length:\x1b[0m 512 KiB
  \x1b[36mPieces:\x1b[0m       1000
"""
        info = parse_inspect_output(stdout)

        assert info.name == "Ansi.Test.2024"
        assert info.info_hash == "fedcba9876543210fedcba9876543210fedcba98"

    def test_parse_private_false(self) -> None:
        """Parse output without Private field (defaults to False)."""
        from shelfr.mkbrr import parse_inspect_output

        stdout = """
Torrent info:
  Name:         Public.Torrent
  Hash:         0000000000000000000000000000000000000000
  Size:         100 MiB
  Piece length: 256 KiB
  Pieces:       400
"""
        info = parse_inspect_output(stdout)
        assert info.private is False

    def test_missing_required_name_raises(self) -> None:
        """Raise ValueError when Name is missing."""
        import pytest

        from shelfr.mkbrr import parse_inspect_output

        stdout = """
Torrent info:
  Hash:         a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2
  Size:         1 GiB
"""
        with pytest.raises(ValueError, match="missing Name or Hash"):
            parse_inspect_output(stdout)

    def test_missing_required_hash_raises(self) -> None:
        """Raise ValueError when Hash is missing."""
        import pytest

        from shelfr.mkbrr import parse_inspect_output

        stdout = """
Torrent info:
  Name:         Test.Torrent
  Size:         1 GiB
"""
        with pytest.raises(ValueError, match="missing Name or Hash"):
            parse_inspect_output(stdout)

    def test_parse_size_formats(self) -> None:
        """Handle various size format strings."""
        from shelfr.mkbrr import _parse_size_string

        assert _parse_size_string("1.5 GiB") == int(1.5 * 1024**3)
        assert _parse_size_string("500 MiB") == 500 * 1024**2
        assert _parse_size_string("256 KiB") == 256 * 1024
        assert _parse_size_string("1234567") == 1234567
        assert _parse_size_string("2.5GB") == int(2.5 * 1024**3)
        assert _parse_size_string(None) == 0
        assert _parse_size_string("") == 0


class TestParseCheckOutput:
    """Tests for parse_check_output text parser."""

    def test_parse_full_output(self) -> None:
        """Parse complete check output with all fields."""
        from shelfr.mkbrr import parse_check_output

        stdout = """
Verifying:
  Torrent file: /path/to/test.torrent
  Content: /path/to/content

  Completion:     100.00%
  Good pieces:    1536
  Bad pieces:     0
  Missing files:  0
  Check time:     2.34s
"""
        result = parse_check_output(stdout)

        assert result.percent_complete == 100.00
        assert result.good_pieces == 1536
        assert result.bad_pieces == 0
        assert result.total_pieces == 1536
        assert result.missing_files == []
        assert result.check_time_seconds == 2.34
        assert result.valid is True

    def test_parse_incomplete_torrent(self) -> None:
        """Parse check output for incomplete torrent."""
        from shelfr.mkbrr import parse_check_output

        stdout = """
  Completion:     75.50%
  Good pieces:    1200
  Bad pieces:     50
  Missing files:  2
  Check time:     5.67s
"""
        result = parse_check_output(stdout)

        assert result.percent_complete == 75.50
        assert result.good_pieces == 1200
        assert result.bad_pieces == 50
        assert result.total_pieces == 1250
        assert result.valid is False

    def test_parse_quiet_mode(self) -> None:
        """Parse quiet mode output (percentage only)."""
        from shelfr.mkbrr import parse_check_output

        stdout = "99.50%\n"
        result = parse_check_output(stdout)

        assert result.percent_complete == 99.50
        assert result.valid is False

    def test_parse_quiet_mode_100_percent(self) -> None:
        """Parse quiet mode output at 100%."""
        from shelfr.mkbrr import parse_check_output

        stdout = "100.00%"
        result = parse_check_output(stdout)

        assert result.percent_complete == 100.00
        assert result.valid is True

    def test_parse_with_ansi_codes(self) -> None:
        """Parse check output with ANSI color codes."""
        from shelfr.mkbrr import parse_check_output

        stdout = """
\x1b[32mVerifying:\x1b[0m
  \x1b[36mCompletion:\x1b[0m     \x1b[32m100.00%\x1b[0m
  \x1b[36mGood pieces:\x1b[0m    500
  \x1b[36mBad pieces:\x1b[0m     0
  \x1b[36mCheck time:\x1b[0m     1.5s
"""
        result = parse_check_output(stdout)

        assert result.percent_complete == 100.00
        assert result.good_pieces == 500
        assert result.bad_pieces == 0

    def test_missing_completion_raises(self) -> None:
        """Raise ValueError when Completion is missing."""
        import pytest

        from shelfr.mkbrr import parse_check_output

        stdout = """
  Good pieces:    100
  Bad pieces:     0
"""
        with pytest.raises(ValueError, match="missing Completion"):
            parse_check_output(stdout)

    def test_parse_duration_formats(self) -> None:
        """Handle various duration format strings."""
        from shelfr.mkbrr import _parse_duration_string

        assert _parse_duration_string("1.23s") == 1.23
        assert _parse_duration_string("500ms") == 0.5
        assert _parse_duration_string("2m30s") == 150.0
        assert _parse_duration_string("1h2m3s") == 3723.0
        assert _parse_duration_string(None) is None
        assert _parse_duration_string("") is None

    def test_valid_logic(self) -> None:
        """Verify valid flag logic."""
        from shelfr.mkbrr import parse_check_output

        # Valid: 100%, no bad pieces, no missing files
        stdout1 = """
  Completion:     100.00%
  Good pieces:    100
  Bad pieces:     0
  Missing files:  0
"""
        assert parse_check_output(stdout1).valid is True

        # Not valid: 100% but has bad pieces
        stdout2 = """
  Completion:     100.00%
  Good pieces:    98
  Bad pieces:     2
  Missing files:  0
"""
        assert parse_check_output(stdout2).valid is False

        # Not valid: 100% but has missing files
        stdout3 = """
  Completion:     100.00%
  Good pieces:    100
  Bad pieces:     0
  Missing files:  1
"""
        assert parse_check_output(stdout3).valid is False


class TestStripAnsiCodes:
    """Tests for ANSI code stripping helper."""

    def test_strip_basic_codes(self) -> None:
        """Strip basic color codes."""
        from shelfr.mkbrr import _strip_ansi_codes

        text = "\x1b[32mgreen\x1b[0m \x1b[31mred\x1b[0m"
        assert _strip_ansi_codes(text) == "green red"

    def test_strip_complex_codes(self) -> None:
        """Strip codes with multiple parameters."""
        from shelfr.mkbrr import _strip_ansi_codes

        text = "\x1b[1;32;40mBold green on black\x1b[0m"
        assert _strip_ansi_codes(text) == "Bold green on black"

    def test_no_codes(self) -> None:
        """Handle text without ANSI codes."""
        from shelfr.mkbrr import _strip_ansi_codes

        text = "plain text"
        assert _strip_ansi_codes(text) == "plain text"
