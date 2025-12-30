"""Tests for qbittorrent module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shelfr.qbittorrent import (
    check_torrent_exists,
    get_client,
    get_torrent_info,
    reset_client,
    upload_torrent,
)
from shelfr.qbittorrent import (
    test_connection as qb_test_connection,
)


@pytest.fixture(autouse=True)
def reset_qb_client():
    """Reset the qBittorrent client pool before each test."""
    reset_client()
    yield
    reset_client()


class TestGetClient:
    """Tests for getting qBittorrent client."""

    def test_get_client_connects_successfully(self):
        """Test successful client connection."""
        mock_client = MagicMock()
        mock_settings = MagicMock()
        mock_settings.qbittorrent.host = "http://localhost:8080"
        mock_settings.qbittorrent.username = "admin"
        mock_settings.qbittorrent.password = "admin"

        with (
            patch("shelfr.qbittorrent.qbittorrentapi.Client", return_value=mock_client),
            patch("shelfr.qbittorrent.get_settings", return_value=mock_settings),
        ):
            client = get_client()

        mock_client.auth_log_in.assert_called_once()
        assert client is mock_client

    def test_get_client_reuses_connection(self):
        """Test that get_client reuses the same connection."""
        mock_client = MagicMock()
        mock_settings = MagicMock()
        mock_settings.qbittorrent.host = "http://localhost:8080"
        mock_settings.qbittorrent.username = "admin"
        mock_settings.qbittorrent.password = "admin"

        with (
            patch("shelfr.qbittorrent.qbittorrentapi.Client", return_value=mock_client),
            patch("shelfr.qbittorrent.get_settings", return_value=mock_settings),
        ):
            # First call creates client
            client1 = get_client()
            # Second call should reuse
            client2 = get_client()

        # Should only create one client (one auth_log_in call)
        assert mock_client.auth_log_in.call_count == 1
        assert client1 is client2


class TestResetClient:
    """Tests for reset_client function."""

    def test_reset_forces_new_connection(self):
        """Test that reset_client forces new connection on next call."""
        mock_client1 = MagicMock()
        mock_client2 = MagicMock()
        mock_settings = MagicMock()
        mock_settings.qbittorrent.host = "http://localhost:8080"
        mock_settings.qbittorrent.username = "admin"
        mock_settings.qbittorrent.password = "admin"

        with (
            patch(
                "shelfr.qbittorrent.qbittorrentapi.Client",
                side_effect=[mock_client1, mock_client2],
            ),
            patch("shelfr.qbittorrent.get_settings", return_value=mock_settings),
        ):
            # First call
            client1 = get_client()
            assert client1 is mock_client1

            # Reset
            reset_client()

            # Second call should create new client
            client2 = get_client()
            assert client2 is mock_client2


class TestTestConnection:
    """Tests for test_connection function."""

    def test_connection_success(self):
        """Test successful connection check."""
        mock_client = MagicMock()
        mock_client.app.version = "4.5.0"

        with patch("shelfr.qbittorrent.get_client", return_value=mock_client):
            assert qb_test_connection() is True

    def test_connection_failure(self):
        """Test failed connection check."""
        with patch("shelfr.qbittorrent.get_client", side_effect=Exception("Connection failed")):
            assert qb_test_connection() is False


class TestCheckTorrentExists:
    """Tests for check_torrent_exists function."""

    def test_torrent_exists(self):
        """Test when torrent exists."""
        mock_client = MagicMock()
        mock_client.torrents_info.return_value = [MagicMock()]

        with patch("shelfr.qbittorrent.get_client", return_value=mock_client):
            result = check_torrent_exists("abc123")

        assert result is True
        mock_client.torrents_info.assert_called_once_with(hashes="abc123")

    def test_torrent_not_exists(self):
        """Test when torrent does not exist."""
        mock_client = MagicMock()
        mock_client.torrents_info.return_value = []

        with patch("shelfr.qbittorrent.get_client", return_value=mock_client):
            result = check_torrent_exists("abc123")

        assert result is False


class TestGetTorrentInfo:
    """Tests for get_torrent_info function."""

    def test_get_info_success(self):
        """Test getting torrent info."""
        mock_torrent = MagicMock()
        mock_torrent.info = {"name": "test", "size": 1000}
        mock_client = MagicMock()
        mock_client.torrents_info.return_value = [mock_torrent]

        with patch("shelfr.qbittorrent.get_client", return_value=mock_client):
            result = get_torrent_info("abc123")

        assert result == {"name": "test", "size": 1000}

    def test_get_info_not_found(self):
        """Test when torrent not found."""
        mock_client = MagicMock()
        mock_client.torrents_info.return_value = []

        with patch("shelfr.qbittorrent.get_client", return_value=mock_client):
            result = get_torrent_info("abc123")

        assert result is None


class TestUploadTorrent:
    """Tests for upload_torrent function.

    Note: upload_torrent returns tuple[bool, str | None] for idempotency.
    Tests mock extract_infohash and check_torrent_exists for proper isolation.
    """

    def test_upload_torrent_file_not_found(self, tmp_path: Path):
        """Test upload with missing torrent file."""
        mock_settings = MagicMock()
        mock_settings.qbittorrent.category = "audiobooks"
        mock_settings.qbittorrent.tags = ["mam"]
        mock_settings.qbittorrent.auto_start = True

        with patch("shelfr.qbittorrent.get_settings", return_value=mock_settings):
            success, infohash = upload_torrent(
                torrent_path=tmp_path / "nonexistent.torrent",
                save_path=tmp_path,
            )
        assert success is False
        assert infohash is None

    def test_upload_torrent_success(self, tmp_path: Path):
        """Test successful torrent upload."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.write_bytes(b"torrent data")

        mock_client = MagicMock()
        mock_client.torrents_add.return_value = "Ok."
        mock_settings = MagicMock()
        mock_settings.qbittorrent.category = "audiobooks"
        mock_settings.qbittorrent.tags = ["mam"]
        mock_settings.qbittorrent.auto_start = True

        with (
            patch("shelfr.qbittorrent.get_client", return_value=mock_client),
            patch("shelfr.qbittorrent.get_settings", return_value=mock_settings),
            patch("shelfr.qbittorrent.extract_infohash", return_value="abc123def456"),
            patch("shelfr.qbittorrent.check_torrent_exists", return_value=False),
        ):
            success, infohash = upload_torrent(
                torrent_path=torrent_file,
                save_path=tmp_path,
            )

        assert success is True
        assert infohash == "abc123def456"
        mock_client.torrents_add.assert_called_once()

    def test_upload_torrent_unexpected_result(self, tmp_path: Path):
        """Test upload with unexpected result from qBittorrent."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.write_bytes(b"torrent data")

        mock_client = MagicMock()
        mock_client.torrents_add.return_value = "Fail."
        mock_settings = MagicMock()
        mock_settings.qbittorrent.category = "audiobooks"
        mock_settings.qbittorrent.tags = ["mam"]
        mock_settings.qbittorrent.auto_start = True

        with (
            patch("shelfr.qbittorrent.get_client", return_value=mock_client),
            patch("shelfr.qbittorrent.get_settings", return_value=mock_settings),
            patch("shelfr.qbittorrent.extract_infohash", return_value="abc123"),
            patch("shelfr.qbittorrent.check_torrent_exists", return_value=False),
        ):
            success, infohash = upload_torrent(
                torrent_path=torrent_file,
                save_path=tmp_path,
            )

        assert success is False
        assert infohash == "abc123"

    def test_upload_torrent_login_failed(self, tmp_path: Path):
        """Test upload when login fails."""
        import qbittorrentapi

        torrent_file = tmp_path / "test.torrent"
        torrent_file.write_bytes(b"torrent data")

        mock_settings = MagicMock()
        mock_settings.qbittorrent.category = "audiobooks"
        mock_settings.qbittorrent.tags = ["mam"]
        mock_settings.qbittorrent.auto_start = True
        mock_settings.qbittorrent.username = "admin"
        mock_settings.qbittorrent.host = "http://localhost:8080"

        with (
            patch(
                "shelfr.qbittorrent.get_client",
                side_effect=qbittorrentapi.LoginFailed("Bad credentials"),
            ),
            patch("shelfr.qbittorrent.get_settings", return_value=mock_settings),
            patch("shelfr.qbittorrent.extract_infohash", return_value="abc123"),
            patch("shelfr.qbittorrent.check_torrent_exists", return_value=False),
        ):
            success, infohash = upload_torrent(
                torrent_path=torrent_file,
                save_path=tmp_path,
            )

        assert success is False
        assert infohash == "abc123"

    def test_upload_torrent_connection_error(self, tmp_path: Path):
        """Test upload when connection fails."""
        import qbittorrentapi

        torrent_file = tmp_path / "test.torrent"
        torrent_file.write_bytes(b"torrent data")

        mock_settings = MagicMock()
        mock_settings.qbittorrent.category = "audiobooks"
        mock_settings.qbittorrent.tags = ["mam"]
        mock_settings.qbittorrent.auto_start = True
        mock_settings.qbittorrent.host = "http://localhost:8080"

        with (
            patch(
                "shelfr.qbittorrent.get_client",
                side_effect=qbittorrentapi.APIConnectionError("No connection"),
            ),
            patch("shelfr.qbittorrent.get_settings", return_value=mock_settings),
            patch("shelfr.qbittorrent.extract_infohash", return_value="abc123"),
            patch("shelfr.qbittorrent.check_torrent_exists", return_value=False),
        ):
            success, infohash = upload_torrent(
                torrent_path=torrent_file,
                save_path=tmp_path,
            )

        assert success is False
        assert infohash == "abc123"

    def test_upload_torrent_with_custom_options(self, tmp_path: Path):
        """Test upload with custom category, tags, and paused state."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.write_bytes(b"torrent data")

        mock_client = MagicMock()
        mock_client.torrents_add.return_value = "Ok."
        mock_settings = MagicMock()
        mock_settings.qbittorrent.category = "default"
        mock_settings.qbittorrent.tags = ["default"]
        mock_settings.qbittorrent.auto_start = True

        with (
            patch("shelfr.qbittorrent.get_client", return_value=mock_client),
            patch("shelfr.qbittorrent.get_settings", return_value=mock_settings),
            patch("shelfr.qbittorrent.extract_infohash", return_value="abc123"),
            patch("shelfr.qbittorrent.check_torrent_exists", return_value=False),
        ):
            success, infohash = upload_torrent(
                torrent_path=torrent_file,
                save_path=tmp_path,
                category="audiobooks",
                tags=["mam", "audiobook"],
                paused=True,
            )

        assert success is True
        assert infohash == "abc123"
        call_kwargs = mock_client.torrents_add.call_args[1]
        assert call_kwargs["category"] == "audiobooks"
        assert call_kwargs["tags"] == "mam,audiobook"
        assert call_kwargs["is_paused"] is True

    def test_upload_torrent_with_empty_tags(self, tmp_path: Path):
        """Test upload with empty tags list."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.write_bytes(b"torrent data")

        mock_client = MagicMock()
        mock_client.torrents_add.return_value = "Ok."
        mock_settings = MagicMock()
        mock_settings.qbittorrent.category = "audiobooks"
        mock_settings.qbittorrent.tags = []
        mock_settings.qbittorrent.auto_start = False

        with (
            patch("shelfr.qbittorrent.get_client", return_value=mock_client),
            patch("shelfr.qbittorrent.get_settings", return_value=mock_settings),
            patch("shelfr.qbittorrent.extract_infohash", return_value="abc123"),
            patch("shelfr.qbittorrent.check_torrent_exists", return_value=False),
        ):
            success, infohash = upload_torrent(
                torrent_path=torrent_file,
                save_path=tmp_path,
            )

        assert success is True
        call_kwargs = mock_client.torrents_add.call_args[1]
        assert call_kwargs["tags"] is None

    def test_upload_torrent_already_exists(self, tmp_path: Path):
        """Test upload when torrent already exists (idempotent)."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.write_bytes(b"torrent data")

        mock_client = MagicMock()
        mock_settings = MagicMock()
        mock_settings.qbittorrent.category = "audiobooks"
        mock_settings.qbittorrent.tags = ["mam"]
        mock_settings.qbittorrent.auto_start = True

        with (
            patch("shelfr.qbittorrent.get_client", return_value=mock_client),
            patch("shelfr.qbittorrent.get_settings", return_value=mock_settings),
            patch("shelfr.qbittorrent.extract_infohash", return_value="existing123"),
            patch("shelfr.qbittorrent.check_torrent_exists", return_value=True),
        ):
            success, infohash = upload_torrent(
                torrent_path=torrent_file,
                save_path=tmp_path,
            )

        assert success is True
        assert infohash == "existing123"
        # Should NOT call torrents_add because torrent already exists
        mock_client.torrents_add.assert_not_called()

    def test_upload_torrent_infohash_extraction_fails(self, tmp_path: Path):
        """Test upload when infohash extraction fails."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.write_bytes(b"torrent data")

        mock_settings = MagicMock()
        mock_settings.qbittorrent.category = "audiobooks"
        mock_settings.qbittorrent.tags = ["mam"]
        mock_settings.qbittorrent.auto_start = True

        with (
            patch("shelfr.qbittorrent.get_settings", return_value=mock_settings),
            patch("shelfr.qbittorrent.extract_infohash", return_value=None),
        ):
            success, infohash = upload_torrent(
                torrent_path=torrent_file,
                save_path=tmp_path,
            )

        assert success is False
        assert infohash is None


class TestUploadTorrentAutoTMM:
    """Tests for auto_tmm functionality in upload_torrent."""

    def test_upload_with_auto_tmm_enabled(self, tmp_path: Path):
        """Test that save_path is not sent when auto_tmm is enabled."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.write_bytes(b"torrent data")

        mock_client = MagicMock()
        mock_client.torrents_add.return_value = "Ok."
        mock_settings = MagicMock()
        mock_settings.qbittorrent.category = "audiobooks"
        mock_settings.qbittorrent.tags = ["mam"]
        mock_settings.qbittorrent.auto_start = True
        mock_settings.qbittorrent.auto_tmm = True
        mock_settings.qbittorrent.save_path = "/some/path"

        with (
            patch("shelfr.qbittorrent.get_client", return_value=mock_client),
            patch("shelfr.qbittorrent.get_settings", return_value=mock_settings),
            patch("shelfr.qbittorrent.extract_infohash", return_value="abc123"),
            patch("shelfr.qbittorrent.check_torrent_exists", return_value=False),
        ):
            success, infohash = upload_torrent(torrent_path=torrent_file)

        assert success is True
        call_kwargs = mock_client.torrents_add.call_args[1]
        assert call_kwargs["use_auto_tmm"] is True
        assert "save_path" not in call_kwargs

    def test_upload_with_auto_tmm_disabled_explicit_path(self, tmp_path: Path):
        """Test that explicit save_path is used when auto_tmm is disabled."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.write_bytes(b"torrent data")
        explicit_path = tmp_path / "explicit"

        mock_client = MagicMock()
        mock_client.torrents_add.return_value = "Ok."
        mock_settings = MagicMock()
        mock_settings.qbittorrent.category = "audiobooks"
        mock_settings.qbittorrent.tags = ["mam"]
        mock_settings.qbittorrent.auto_start = True
        mock_settings.qbittorrent.auto_tmm = False
        mock_settings.qbittorrent.save_path = "/config/path"

        with (
            patch("shelfr.qbittorrent.get_client", return_value=mock_client),
            patch("shelfr.qbittorrent.get_settings", return_value=mock_settings),
            patch("shelfr.qbittorrent.extract_infohash", return_value="abc123"),
            patch("shelfr.qbittorrent.check_torrent_exists", return_value=False),
        ):
            success, infohash = upload_torrent(torrent_path=torrent_file, save_path=explicit_path)

        assert success is True
        call_kwargs = mock_client.torrents_add.call_args[1]
        assert call_kwargs["use_auto_tmm"] is False
        assert call_kwargs["save_path"] == str(explicit_path)

    def test_upload_with_auto_tmm_disabled_config_path(self, tmp_path: Path):
        """Test that config save_path is used when auto_tmm is disabled and no explicit path."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.write_bytes(b"torrent data")

        mock_client = MagicMock()
        mock_client.torrents_add.return_value = "Ok."
        mock_settings = MagicMock()
        mock_settings.qbittorrent.category = "audiobooks"
        mock_settings.qbittorrent.tags = ["mam"]
        mock_settings.qbittorrent.auto_start = True
        mock_settings.qbittorrent.auto_tmm = False
        mock_settings.qbittorrent.save_path = "/config/save/path"

        with (
            patch("shelfr.qbittorrent.get_client", return_value=mock_client),
            patch("shelfr.qbittorrent.get_settings", return_value=mock_settings),
            patch("shelfr.qbittorrent.extract_infohash", return_value="abc123"),
            patch("shelfr.qbittorrent.check_torrent_exists", return_value=False),
        ):
            success, infohash = upload_torrent(torrent_path=torrent_file)

        assert success is True
        call_kwargs = mock_client.torrents_add.call_args[1]
        assert call_kwargs["use_auto_tmm"] is False
        assert call_kwargs["save_path"] == "/config/save/path"

    def test_upload_with_auto_tmm_disabled_no_path(self, tmp_path: Path):
        """Test that no save_path is sent when auto_tmm is disabled and no path configured."""
        torrent_file = tmp_path / "test.torrent"
        torrent_file.write_bytes(b"torrent data")

        mock_client = MagicMock()
        mock_client.torrents_add.return_value = "Ok."
        mock_settings = MagicMock()
        mock_settings.qbittorrent.category = "audiobooks"
        mock_settings.qbittorrent.tags = ["mam"]
        mock_settings.qbittorrent.auto_start = True
        mock_settings.qbittorrent.auto_tmm = False
        mock_settings.qbittorrent.save_path = ""  # Empty - no path configured

        with (
            patch("shelfr.qbittorrent.get_client", return_value=mock_client),
            patch("shelfr.qbittorrent.get_settings", return_value=mock_settings),
            patch("shelfr.qbittorrent.extract_infohash", return_value="abc123"),
            patch("shelfr.qbittorrent.check_torrent_exists", return_value=False),
        ):
            success, infohash = upload_torrent(torrent_path=torrent_file)

        assert success is True
        call_kwargs = mock_client.torrents_add.call_args[1]
        assert call_kwargs["use_auto_tmm"] is False
        # No save_path sent - qBittorrent uses its default
        assert "save_path" not in call_kwargs


class TestCheckTorrentExistsErrors:
    """Tests for check_torrent_exists error handling."""

    def test_torrent_exists_login_failed(self):
        """Test when login fails."""
        import qbittorrentapi

        with patch(
            "shelfr.qbittorrent.get_client",
            side_effect=qbittorrentapi.LoginFailed("Bad credentials"),
        ):
            result = check_torrent_exists("abc123")

        assert result is False

    def test_torrent_exists_connection_error(self):
        """Test when connection fails."""
        import qbittorrentapi

        with patch(
            "shelfr.qbittorrent.get_client",
            side_effect=qbittorrentapi.APIConnectionError("No connection"),
        ):
            result = check_torrent_exists("abc123")

        assert result is False


class TestGetTorrentInfoErrors:
    """Tests for get_torrent_info error handling."""

    def test_get_info_login_failed(self):
        """Test when login fails."""
        import qbittorrentapi

        with patch(
            "shelfr.qbittorrent.get_client",
            side_effect=qbittorrentapi.LoginFailed("Bad credentials"),
        ):
            result = get_torrent_info("abc123")

        assert result is None

    def test_get_info_connection_error(self):
        """Test when connection fails."""
        import qbittorrentapi

        with patch(
            "shelfr.qbittorrent.get_client",
            side_effect=qbittorrentapi.APIConnectionError("No connection"),
        ):
            result = get_torrent_info("abc123")

        assert result is None
