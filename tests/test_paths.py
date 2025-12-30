"""Tests for path utilities."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shelfr.utils.paths import (
    container_to_host_data_path,
    container_to_host_torrent_path,
    ensure_dir,
    host_to_container_data_path,
    host_to_container_torrent_path,
    path_exists_on_host,
)


@pytest.fixture
def mock_settings():
    """Create mock settings for path tests."""
    settings = MagicMock()
    settings.mkbrr.host_data_root = "/mnt/user/data"
    settings.mkbrr.container_data_root = "/data"
    settings.mkbrr.host_output_dir = "/mnt/user/data/downloads/torrents/torrentfiles"
    settings.mkbrr.container_output_dir = "/torrentfiles"
    return settings


class TestHostToContainerDataPath:
    """Tests for host_to_container_data_path."""

    def test_converts_host_path(self, mock_settings):
        """Test converting host path to container path."""
        with patch("shelfr.utils.paths.get_settings", return_value=mock_settings):
            result = host_to_container_data_path("/mnt/user/data/audio/book.m4b")
            assert result == "/data/audio/book.m4b"

    def test_already_container_path(self, mock_settings):
        """Test path already in container format."""
        with patch("shelfr.utils.paths.get_settings", return_value=mock_settings):
            result = host_to_container_data_path("/data/audio/book.m4b")
            assert result == "/data/audio/book.m4b"

    def test_exact_container_root(self, mock_settings):
        """Test exact container root path."""
        with patch("shelfr.utils.paths.get_settings", return_value=mock_settings):
            result = host_to_container_data_path("/data")
            assert result == "/data"

    def test_not_under_data_root(self, mock_settings):
        """Test path not under data root returns as-is."""
        with patch("shelfr.utils.paths.get_settings", return_value=mock_settings):
            result = host_to_container_data_path("/other/path/file.m4b")
            # Should normalize to absolute and return as-is
            assert "file.m4b" in result

    def test_handles_path_object(self, mock_settings):
        """Test Path object input."""
        with patch("shelfr.utils.paths.get_settings", return_value=mock_settings):
            result = host_to_container_data_path(Path("/mnt/user/data/book.m4b"))
            assert result == "/data/book.m4b"

    def test_strips_whitespace(self, mock_settings):
        """Test whitespace is stripped."""
        with patch("shelfr.utils.paths.get_settings", return_value=mock_settings):
            result = host_to_container_data_path("  /mnt/user/data/book.m4b  ")
            assert result == "/data/book.m4b"


class TestHostToContainerTorrentPath:
    """Tests for host_to_container_torrent_path."""

    def test_converts_host_torrent_path(self, mock_settings):
        """Test converting host torrent path to container path."""
        with patch("shelfr.utils.paths.get_settings", return_value=mock_settings):
            result = host_to_container_torrent_path(
                "/mnt/user/data/downloads/torrents/torrentfiles/book.torrent"
            )
            assert result == "/torrentfiles/book.torrent"

    def test_already_container_path(self, mock_settings):
        """Test path already in container format."""
        with patch("shelfr.utils.paths.get_settings", return_value=mock_settings):
            result = host_to_container_torrent_path("/torrentfiles/book.torrent")
            assert result == "/torrentfiles/book.torrent"

    def test_exact_container_output(self, mock_settings):
        """Test exact container output path."""
        with patch("shelfr.utils.paths.get_settings", return_value=mock_settings):
            result = host_to_container_torrent_path("/torrentfiles")
            assert result == "/torrentfiles"


class TestContainerToHostDataPath:
    """Tests for container_to_host_data_path."""

    def test_converts_container_path(self, mock_settings):
        """Test converting container path to host path."""
        with patch("shelfr.utils.paths.get_settings", return_value=mock_settings):
            result = container_to_host_data_path("/data/audio/book.m4b")
            assert result == "/mnt/user/data/audio/book.m4b"

    def test_already_host_path(self, mock_settings):
        """Test path already in host format."""
        with patch("shelfr.utils.paths.get_settings", return_value=mock_settings):
            result = container_to_host_data_path("/mnt/user/data/audio/book.m4b")
            assert result == "/mnt/user/data/audio/book.m4b"

    def test_exact_host_root(self, mock_settings):
        """Test exact host root path."""
        with patch("shelfr.utils.paths.get_settings", return_value=mock_settings):
            result = container_to_host_data_path("/mnt/user/data")
            assert result == "/mnt/user/data"

    def test_exact_container_root(self, mock_settings):
        """Test exact container root."""
        with patch("shelfr.utils.paths.get_settings", return_value=mock_settings):
            result = container_to_host_data_path("/data")
            assert result == "/mnt/user/data"

    def test_unrelated_path(self, mock_settings):
        """Test unrelated path returned as-is."""
        with patch("shelfr.utils.paths.get_settings", return_value=mock_settings):
            result = container_to_host_data_path("/other/path")
            assert result == "/other/path"


class TestContainerToHostTorrentPath:
    """Tests for container_to_host_torrent_path."""

    def test_converts_container_torrent_path(self, mock_settings):
        """Test converting container torrent path to host path."""
        with patch("shelfr.utils.paths.get_settings", return_value=mock_settings):
            result = container_to_host_torrent_path("/torrentfiles/book.torrent")
            assert result == "/mnt/user/data/downloads/torrents/torrentfiles/book.torrent"

    def test_already_host_path(self, mock_settings):
        """Test path already in host format."""
        with patch("shelfr.utils.paths.get_settings", return_value=mock_settings):
            result = container_to_host_torrent_path(
                "/mnt/user/data/downloads/torrents/torrentfiles/book.torrent"
            )
            assert result == "/mnt/user/data/downloads/torrents/torrentfiles/book.torrent"

    def test_exact_host_output(self, mock_settings):
        """Test exact host output path."""
        with patch("shelfr.utils.paths.get_settings", return_value=mock_settings):
            result = container_to_host_torrent_path(
                "/mnt/user/data/downloads/torrents/torrentfiles"
            )
            assert result == "/mnt/user/data/downloads/torrents/torrentfiles"

    def test_exact_container_output(self, mock_settings):
        """Test exact container output."""
        with patch("shelfr.utils.paths.get_settings", return_value=mock_settings):
            result = container_to_host_torrent_path("/torrentfiles")
            assert result == "/mnt/user/data/downloads/torrents/torrentfiles"


class TestEnsureDir:
    """Tests for ensure_dir."""

    def test_creates_directory(self):
        """Test directory is created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            new_dir = Path(tmpdir) / "new" / "nested" / "dir"
            assert not new_dir.exists()

            result = ensure_dir(new_dir)

            assert new_dir.exists()
            assert new_dir.is_dir()
            assert result == new_dir

    def test_existing_directory(self):
        """Test existing directory is not affected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            existing = Path(tmpdir)
            result = ensure_dir(existing)
            assert result == existing
            assert existing.exists()


class TestPathExistsOnHost:
    """Tests for path_exists_on_host."""

    def test_existing_path(self):
        """Test existing path returns True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            assert path_exists_on_host(tmpdir) is True

    def test_nonexistent_path(self):
        """Test non-existent path returns False."""
        assert path_exists_on_host("/nonexistent/path/12345") is False

    def test_path_object(self):
        """Test Path object input."""
        with tempfile.TemporaryDirectory() as tmpdir:
            assert path_exists_on_host(Path(tmpdir)) is True
