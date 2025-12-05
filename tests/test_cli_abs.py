"""Tests for Audiobookshelf CLI commands."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mamfast.cli import build_parser, cmd_abs_index, cmd_abs_init


class TestAbsCliParser:
    """Tests for ABS command parser setup."""

    def test_abs_init_parser_exists(self) -> None:
        """Test abs-init subcommand is registered."""
        parser = build_parser()
        # Parse with abs-init command
        args = parser.parse_args(["abs-init"])
        assert args.command == "abs-init"
        assert hasattr(args, "func")

    def test_abs_index_parser_exists(self) -> None:
        """Test abs-index subcommand is registered."""
        parser = build_parser()
        args = parser.parse_args(["abs-index"])
        assert args.command == "abs-index"
        assert hasattr(args, "func")

    def test_abs_index_full_flag(self) -> None:
        """Test abs-index --full flag is parsed."""
        parser = build_parser()
        args = parser.parse_args(["abs-index", "--full"])
        assert args.full is True

    def test_abs_index_library_option(self) -> None:
        """Test abs-index --library option is parsed."""
        parser = build_parser()
        args = parser.parse_args(["abs-index", "--library", "lib_test123"])
        assert args.library == "lib_test123"

    def test_abs_index_defaults(self) -> None:
        """Test abs-index default values."""
        parser = build_parser()
        args = parser.parse_args(["abs-index"])
        assert args.full is False
        assert args.library is None


@dataclass
class MockAbsPathMap:
    """Mock path map for testing."""

    container: str = "/audiobooks"
    host: str = "/mnt/data/audiobooks"


@dataclass
class MockAbsLibrary:
    """Mock library config for testing."""

    id: str = "lib_test"
    name: str = "Test Library"
    mamfast_managed: bool = True


class TestAbsInitCommand:
    """Tests for abs-init command implementation."""

    @pytest.fixture
    def args(self) -> argparse.Namespace:
        """Create basic args namespace."""
        return argparse.Namespace(
            config="config/config.yaml",
            dry_run=False,
            verbose=False,
        )

    @pytest.fixture
    def mock_abs_config(self) -> MagicMock:
        """Create mock audiobookshelf config."""
        config = MagicMock()
        config.enabled = True
        config.host = "http://localhost:13378"
        config.api_key = "test-key"
        config.timeout_seconds = 30
        config.docker_mode = True
        config.path_map = [MockAbsPathMap()]
        config.libraries = [MockAbsLibrary()]
        return config

    def test_abs_init_config_not_found(self, args: argparse.Namespace) -> None:
        """Test abs-init handles missing config file."""
        with patch("mamfast.config.reload_settings") as mock_reload:
            mock_reload.side_effect = FileNotFoundError("config not found")
            result = cmd_abs_init(args)
            assert result == 1

    def test_abs_init_abs_disabled(self, args: argparse.Namespace) -> None:
        """Test abs-init warns when ABS is disabled."""
        mock_settings = MagicMock()
        mock_settings.audiobookshelf.enabled = False

        with patch("mamfast.config.reload_settings", return_value=mock_settings):
            result = cmd_abs_init(args)
            assert result == 1

    def test_abs_init_connection_success(
        self,
        args: argparse.Namespace,
        mock_abs_config: MagicMock,
    ) -> None:
        """Test abs-init with successful connection."""
        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config

        mock_user = MagicMock()
        mock_user.username = "testuser"
        mock_user.user_type = "admin"
        mock_user.has_admin = True

        mock_lib = MagicMock()
        mock_lib.id = "lib_test"
        mock_lib.name = "Audiobooks"
        mock_lib.media_type = "book"
        mock_lib.folders = ["/audiobooks"]

        mock_client = MagicMock()
        mock_client.authorize.return_value = mock_user
        mock_client.get_libraries.return_value = [mock_lib]

        with (
            patch("mamfast.config.reload_settings", return_value=mock_settings),
            patch("mamfast.abs.client.AbsClient.from_config", return_value=mock_client),
        ):
            result = cmd_abs_init(args)

        assert result == 0
        mock_client.authorize.assert_called_once()
        mock_client.get_libraries.assert_called_once()
        mock_client.close.assert_called_once()

    def test_abs_init_auth_failure(
        self,
        args: argparse.Namespace,
        mock_abs_config: MagicMock,
    ) -> None:
        """Test abs-init handles authentication failure."""
        from mamfast.abs.client import AbsAuthError

        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config

        mock_client = MagicMock()
        mock_client.authorize.side_effect = AbsAuthError("Invalid API key")

        with (
            patch("mamfast.config.reload_settings", return_value=mock_settings),
            patch("mamfast.abs.client.AbsClient.from_config", return_value=mock_client),
        ):
            result = cmd_abs_init(args)

        assert result == 1

    def test_abs_init_connection_failure(
        self,
        args: argparse.Namespace,
        mock_abs_config: MagicMock,
    ) -> None:
        """Test abs-init handles connection failure."""
        from mamfast.abs.client import AbsConnectionError

        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config

        mock_client = MagicMock()
        mock_client.authorize.side_effect = AbsConnectionError("Connection refused")

        with (
            patch("mamfast.config.reload_settings", return_value=mock_settings),
            patch("mamfast.abs.client.AbsClient.from_config", return_value=mock_client),
        ):
            result = cmd_abs_init(args)

        assert result == 1

    def test_abs_init_no_audiobook_libraries(
        self,
        args: argparse.Namespace,
        mock_abs_config: MagicMock,
    ) -> None:
        """Test abs-init when no audiobook libraries exist."""
        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config

        mock_user = MagicMock()
        mock_user.username = "testuser"
        mock_user.user_type = "admin"
        mock_user.has_admin = True

        # Return only podcast library
        mock_lib = MagicMock()
        mock_lib.media_type = "podcast"

        mock_client = MagicMock()
        mock_client.authorize.return_value = mock_user
        mock_client.get_libraries.return_value = [mock_lib]

        with (
            patch("mamfast.config.reload_settings", return_value=mock_settings),
            patch("mamfast.abs.client.AbsClient.from_config", return_value=mock_client),
        ):
            result = cmd_abs_init(args)

        assert result == 1


class TestAbsIndexCommand:
    """Tests for abs-index command implementation."""

    @pytest.fixture
    def args(self) -> argparse.Namespace:
        """Create basic args namespace."""
        return argparse.Namespace(
            config="config/config.yaml",
            dry_run=False,
            verbose=False,
            full=False,
            library=None,
        )

    def test_abs_index_config_not_found(self, args: argparse.Namespace) -> None:
        """Test abs-index handles missing config file."""
        with patch("mamfast.config.reload_settings") as mock_reload:
            mock_reload.side_effect = FileNotFoundError("config not found")
            result = cmd_abs_index(args)
            assert result == 1

    def test_abs_index_abs_disabled(self, args: argparse.Namespace) -> None:
        """Test abs-index warns when ABS is disabled."""
        mock_settings = MagicMock()
        mock_settings.audiobookshelf.enabled = False

        with patch("mamfast.config.reload_settings", return_value=mock_settings):
            result = cmd_abs_index(args)
            assert result == 1

    def test_abs_index_stub_returns_success(self, args: argparse.Namespace, tmp_path: Path) -> None:
        """Test abs-index returns 0 when sync succeeds."""
        from mamfast.abs import AbsLibrary, AbsUser, SyncResult

        # Create proper mock settings
        mock_lib_config = MagicMock()
        mock_lib_config.id = "lib_test"
        mock_lib_config.mamfast_managed = True

        mock_settings = MagicMock()
        mock_settings.audiobookshelf.enabled = True
        mock_settings.audiobookshelf.host = "http://localhost:13378"
        mock_settings.audiobookshelf.api_key = "test-key"
        mock_settings.audiobookshelf.timeout_seconds = 30
        mock_settings.audiobookshelf.libraries = [mock_lib_config]
        mock_settings.audiobookshelf.path_map = []  # path_map is on AudiobookshelfConfig
        mock_settings.audiobookshelf.index_db = str(tmp_path / "abs_index.db")

        mock_user = AbsUser(
            id="user_123",
            username="testuser",
            user_type="admin",
            is_active=True,
            has_admin=True,
        )
        mock_library = AbsLibrary(
            id="lib_test",
            name="Audiobooks",
            media_type="book",
            folders=[],
            display_order=0,
        )
        mock_sync_result = SyncResult(
            books_indexed=10,
            with_asin=8,
            without_asin=2,
            author_variants_found=0,
            libraries_synced=1,
            errors=[],
        )

        with (
            patch("mamfast.config.reload_settings", return_value=mock_settings),
            patch("mamfast.abs.AbsClient") as mock_client_cls,
            patch("mamfast.abs.AbsIndex") as mock_index_cls,
        ):
            mock_client = MagicMock()
            mock_client.authorize.return_value = mock_user
            mock_client.get_libraries.return_value = [mock_library]
            mock_client_cls.return_value = mock_client

            mock_index = MagicMock()
            mock_index.sync_from_abs.return_value = mock_sync_result
            mock_index.__enter__ = MagicMock(return_value=mock_index)
            mock_index.__exit__ = MagicMock(return_value=False)
            mock_index_cls.return_value = mock_index

            result = cmd_abs_index(args)
            assert result == 0

    def test_abs_index_full_mode(self, args: argparse.Namespace, tmp_path: Path) -> None:
        """Test abs-index with --full flag."""
        from mamfast.abs import AbsLibrary, AbsUser, SyncResult

        args.full = True

        mock_lib_config = MagicMock()
        mock_lib_config.id = "lib_test"
        mock_lib_config.mamfast_managed = True

        mock_settings = MagicMock()
        mock_settings.audiobookshelf.enabled = True
        mock_settings.audiobookshelf.host = "http://localhost:13378"
        mock_settings.audiobookshelf.api_key = "test-key"
        mock_settings.audiobookshelf.timeout_seconds = 30
        mock_settings.audiobookshelf.libraries = [mock_lib_config]
        mock_settings.audiobookshelf.path_map = []  # path_map is on AudiobookshelfConfig
        mock_settings.audiobookshelf.index_db = str(tmp_path / "abs_index.db")

        mock_user = AbsUser(
            id="user_123",
            username="testuser",
            user_type="admin",
            is_active=True,
            has_admin=True,
        )
        mock_library = AbsLibrary(
            id="lib_test",
            name="Audiobooks",
            media_type="book",
            folders=[],
            display_order=0,
        )
        mock_sync_result = SyncResult(
            books_indexed=10,
            with_asin=8,
            without_asin=2,
            author_variants_found=0,
            libraries_synced=1,
            errors=[],
        )

        with (
            patch("mamfast.config.reload_settings", return_value=mock_settings),
            patch("mamfast.abs.AbsClient") as mock_client_cls,
            patch("mamfast.abs.AbsIndex") as mock_index_cls,
        ):
            mock_client = MagicMock()
            mock_client.authorize.return_value = mock_user
            mock_client.get_libraries.return_value = [mock_library]
            mock_client_cls.return_value = mock_client

            mock_index = MagicMock()
            mock_index.sync_from_abs.return_value = mock_sync_result
            mock_index.__enter__ = MagicMock(return_value=mock_index)
            mock_index.__exit__ = MagicMock(return_value=False)
            mock_index_cls.return_value = mock_index

            result = cmd_abs_index(args)
            assert result == 0
            # Verify full_rebuild=True was passed
            mock_index.sync_from_abs.assert_called_once()
            call_kwargs = mock_index.sync_from_abs.call_args.kwargs
            assert call_kwargs.get("full_rebuild") is True

    def test_abs_index_specific_library(self, args: argparse.Namespace, tmp_path: Path) -> None:
        """Test abs-index with --library flag."""
        from mamfast.abs import AbsLibrary, AbsUser, SyncResult

        args.library = "lib_specific123"

        mock_lib_config = MagicMock()
        mock_lib_config.id = "lib_specific123"
        mock_lib_config.mamfast_managed = True

        mock_settings = MagicMock()
        mock_settings.audiobookshelf.enabled = True
        mock_settings.audiobookshelf.host = "http://localhost:13378"
        mock_settings.audiobookshelf.api_key = "test-key"
        mock_settings.audiobookshelf.timeout_seconds = 30
        mock_settings.audiobookshelf.libraries = [mock_lib_config]
        mock_settings.audiobookshelf.path_map = []  # path_map is on AudiobookshelfConfig
        mock_settings.audiobookshelf.index_db = str(tmp_path / "abs_index.db")

        mock_user = AbsUser(
            id="user_123",
            username="testuser",
            user_type="admin",
            is_active=True,
            has_admin=True,
        )
        mock_library = AbsLibrary(
            id="lib_specific123",
            name="Audiobooks",
            media_type="book",
            folders=[],
            display_order=0,
        )
        mock_sync_result = SyncResult(
            books_indexed=5,
            with_asin=5,
            without_asin=0,
            author_variants_found=0,
            libraries_synced=1,
            errors=[],
        )

        with (
            patch("mamfast.config.reload_settings", return_value=mock_settings),
            patch("mamfast.abs.AbsClient") as mock_client_cls,
            patch("mamfast.abs.AbsIndex") as mock_index_cls,
        ):
            mock_client = MagicMock()
            mock_client.authorize.return_value = mock_user
            mock_client.get_libraries.return_value = [mock_library]
            mock_client_cls.return_value = mock_client

            mock_index = MagicMock()
            mock_index.sync_from_abs.return_value = mock_sync_result
            mock_index.__enter__ = MagicMock(return_value=mock_index)
            mock_index.__exit__ = MagicMock(return_value=False)
            mock_index_cls.return_value = mock_index

            result = cmd_abs_index(args)
            assert result == 0
