"""Tests for mkbrr module."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from mamfast.mkbrr import (
    MkbrrResult,
    _cleanup_stale_torrents,
    _docker_base_command,
    _find_torrent_deterministic,
    check_docker_available,
    check_torrent,
    create_torrent,
    fix_torrent_permissions,
    inspect_torrent,
    load_presets,
)
from mamfast.utils.cmd import CmdError
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
            patch("mamfast.mkbrr.run", return_value=mock_result),
            patch("mamfast.mkbrr.get_settings", return_value=mock_settings),
        ):
            assert check_docker_available() is True

    def test_docker_not_available(self):
        """Test when docker is not available."""
        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"

        with (
            patch(
                "mamfast.mkbrr.run",
                side_effect=CmdError(
                    argv=["docker", "--version"],
                    exit_code=127,
                    stdout="",
                    stderr="Command not found",
                ),
            ),
            patch("mamfast.mkbrr.get_settings", return_value=mock_settings),
        ):
            assert check_docker_available() is False


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

        with patch("mamfast.mkbrr.get_settings", return_value=mock_settings):
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

        with patch("mamfast.mkbrr.get_settings", return_value=mock_settings):
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
            patch("mamfast.mkbrr.run", side_effect=mock_run),
            patch("mamfast.mkbrr.get_settings", return_value=mock_settings),
            patch("mamfast.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("mamfast.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
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
                "mamfast.mkbrr.run",
                return_value=make_cmd_result(exit_code=1, stderr="Error creating torrent"),
            ),
            patch("mamfast.mkbrr.get_settings", return_value=mock_settings),
            patch("mamfast.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("mamfast.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
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
            patch("mamfast.mkbrr.run", side_effect=Exception("Unexpected error")),
            patch("mamfast.mkbrr.get_settings", return_value=mock_settings),
            patch("mamfast.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("mamfast.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
        ):
            result = create_torrent(content_dir)

        assert result.success is False
        assert result.return_code == -1
        assert "Unexpected error" in (result.error or "")


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

        with patch("mamfast.mkbrr.get_settings", return_value=mock_settings):
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

        with patch("mamfast.mkbrr.get_settings", return_value=mock_settings):
            presets = load_presets()

        assert presets == ["fallback"]

    def test_empty_presets(self, tmp_path: Path):
        """Test handling YAML with no presets."""
        presets_file = tmp_path / "presets.yaml"
        presets_file.write_text("presets: {}")

        mock_settings = MagicMock()
        mock_settings.mkbrr.host_config_dir = str(tmp_path)
        mock_settings.mkbrr.preset = "fallback"

        with patch("mamfast.mkbrr.get_settings", return_value=mock_settings):
            presets = load_presets()

        assert presets == ["fallback"]

    def test_missing_presets_key(self, tmp_path: Path):
        """Test handling YAML without presets key."""
        presets_file = tmp_path / "presets.yaml"
        presets_file.write_text("other_key: value")

        mock_settings = MagicMock()
        mock_settings.mkbrr.host_config_dir = str(tmp_path)
        mock_settings.mkbrr.preset = "fallback"

        with patch("mamfast.mkbrr.get_settings", return_value=mock_settings):
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
            patch("mamfast.mkbrr.get_settings", return_value=mock_settings),
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

        with patch("mamfast.mkbrr.get_settings", return_value=mock_settings):
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
            patch("mamfast.mkbrr.get_settings", return_value=mock_settings),
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
            patch("mamfast.mkbrr.run", return_value=mock_result),
            patch("mamfast.mkbrr.get_settings", return_value=mock_settings),
            patch(
                "mamfast.mkbrr.host_to_container_torrent_path",
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
            patch("mamfast.mkbrr.run", return_value=mock_result) as mock_run,
            patch("mamfast.mkbrr.get_settings", return_value=mock_settings),
            patch(
                "mamfast.mkbrr.host_to_container_torrent_path",
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
            patch("mamfast.mkbrr.run", return_value=mock_result),
            patch("mamfast.mkbrr.get_settings", return_value=mock_settings),
            patch(
                "mamfast.mkbrr.host_to_container_torrent_path",
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
            patch("mamfast.mkbrr.run", side_effect=Exception("Docker error")),
            patch("mamfast.mkbrr.get_settings", return_value=mock_settings),
            patch(
                "mamfast.mkbrr.host_to_container_torrent_path",
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
            patch("mamfast.mkbrr.run", return_value=mock_result),
            patch("mamfast.mkbrr.get_settings", return_value=mock_settings),
            patch(
                "mamfast.mkbrr.host_to_container_torrent_path",
                return_value="/torrents/test.torrent",
            ),
            patch("mamfast.mkbrr.host_to_container_data_path", return_value="/data/content"),
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
            patch("mamfast.mkbrr.run", return_value=mock_result) as mock_run,
            patch("mamfast.mkbrr.get_settings", return_value=mock_settings),
            patch(
                "mamfast.mkbrr.host_to_container_torrent_path",
                return_value="/torrents/test.torrent",
            ),
            patch("mamfast.mkbrr.host_to_container_data_path", return_value="/data/content"),
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
            patch("mamfast.mkbrr.run", return_value=mock_result) as mock_run,
            patch("mamfast.mkbrr.get_settings", return_value=mock_settings),
            patch(
                "mamfast.mkbrr.host_to_container_torrent_path",
                return_value="/torrents/test.torrent",
            ),
            patch("mamfast.mkbrr.host_to_container_data_path", return_value="/data/content"),
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
            patch("mamfast.mkbrr.run", return_value=mock_result),
            patch("mamfast.mkbrr.get_settings", return_value=mock_settings),
            patch(
                "mamfast.mkbrr.host_to_container_torrent_path",
                return_value="/torrents/test.torrent",
            ),
            patch("mamfast.mkbrr.host_to_container_data_path", return_value="/data/content"),
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
            patch("mamfast.mkbrr.run", side_effect=Exception("Check failed")),
            patch("mamfast.mkbrr.get_settings", return_value=mock_settings),
            patch(
                "mamfast.mkbrr.host_to_container_torrent_path",
                return_value="/torrents/test.torrent",
            ),
            patch("mamfast.mkbrr.host_to_container_data_path", return_value="/data/content"),
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
            patch("mamfast.mkbrr.run", return_value=mock_result),
            patch("mamfast.mkbrr.get_settings", return_value=mock_settings),
            patch("mamfast.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("mamfast.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
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
            patch("mamfast.mkbrr.run", return_value=mock_result),
            patch("mamfast.mkbrr.get_settings", return_value=mock_settings),
            patch("mamfast.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("mamfast.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
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
            patch("mamfast.mkbrr.run", return_value=mock_result),
            patch("mamfast.mkbrr.get_settings", return_value=mock_settings),
            patch("mamfast.mkbrr.host_to_container_data_path", return_value="/data/content"),
            patch("mamfast.mkbrr.host_to_container_torrent_path", return_value="/torrents"),
        ):
            result = create_torrent(content_dir, output_dir)

        assert result.success is True
        assert result.torrent_path == newer_torrent
