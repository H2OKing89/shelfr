"""Tests for Audiobookshelf CLI commands."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mamfast.cli import build_parser, cmd_abs_init


class TestAbsCliParser:
    """Tests for ABS command parser setup."""

    def test_abs_init_parser_exists(self) -> None:
        """Test abs-init subcommand is registered."""
        parser = build_parser()
        # Parse with abs-init command
        args = parser.parse_args(["abs-init"])
        assert args.command == "abs-init"
        assert hasattr(args, "func")


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


# =============================================================================
# Tests: abs-import command
# =============================================================================


class TestAbsImportParser:
    """Tests for abs-import command parser setup."""

    def test_abs_import_parser_exists(self) -> None:
        """Test abs-import subcommand is registered."""
        parser = build_parser()
        args = parser.parse_args(["abs-import"])
        assert args.command == "abs-import"
        assert hasattr(args, "func")

    def test_abs_import_dry_run_flag(self) -> None:
        """Test abs-import --dry-run flag is parsed (global flag before subcommand)."""
        parser = build_parser()
        args = parser.parse_args(["--dry-run", "abs-import"])
        assert args.dry_run is True

    def test_abs_import_duplicate_policy_option(self) -> None:
        """Test abs-import --duplicate-policy option is parsed."""
        parser = build_parser()
        for policy in ["skip", "warn", "overwrite"]:
            args = parser.parse_args(["abs-import", "--duplicate-policy", policy])
            assert args.duplicate_policy == policy

    def test_abs_import_no_scan_flag(self) -> None:
        """Test abs-import --no-scan flag is parsed."""
        parser = build_parser()
        args = parser.parse_args(["abs-import", "--no-scan"])
        assert args.no_scan is True

    def test_abs_import_abs_search_flag(self) -> None:
        """Test abs-import --abs-search flag is parsed (opt-in)."""
        parser = build_parser()
        # Default is False (off)
        args_default = parser.parse_args(["abs-import"])
        assert args_default.abs_search is False
        # Explicit enable
        args_enabled = parser.parse_args(["abs-import", "--abs-search"])
        assert args_enabled.abs_search is True

    def test_abs_import_confidence_flag(self) -> None:
        """Test abs-import --confidence flag is parsed."""
        parser = build_parser()
        # Default value
        args_default = parser.parse_args(["abs-import"])
        assert args_default.confidence == 0.75
        # Custom value
        args_custom = parser.parse_args(["abs-import", "--confidence", "0.6"])
        assert args_custom.confidence == 0.6

    def test_abs_import_paths_positional(self, tmp_path: Path) -> None:
        """Test abs-import accepts positional paths."""
        parser = build_parser()
        path1 = str(tmp_path / "book1")
        path2 = str(tmp_path / "book2")
        args = parser.parse_args(["abs-import", path1, path2])
        assert len(args.paths) == 2

    def test_abs_import_defaults(self) -> None:
        """Test abs-import default values."""
        parser = build_parser()
        args = parser.parse_args(["abs-import"])
        assert args.duplicate_policy is None
        assert args.no_scan is False
        assert args.abs_search is False  # Default off (opt-in)
        assert args.confidence == 0.75
        assert args.paths == []


class TestAbsImportCommand:
    """Tests for abs-import command implementation."""

    @pytest.fixture
    def args(self) -> argparse.Namespace:
        """Create basic args namespace."""
        return argparse.Namespace(
            config="config/config.yaml",
            dry_run=False,
            verbose=False,
            duplicate_policy=None,
            no_scan=False,
            abs_search=False,  # Opt-in, default off
            confidence=0.75,
            paths=[],
        )

    @pytest.fixture
    def mock_abs_config(self, tmp_path: Path) -> MagicMock:
        """Create mock audiobookshelf config."""
        config = MagicMock()
        config.enabled = True
        config.host = "http://localhost:13378"
        config.api_key = "test-key"
        config.timeout_seconds = 30
        config.docker_mode = True
        config.path_map = [MockAbsPathMap(host=str(tmp_path / "audiobooks"))]
        config.libraries = [MockAbsLibrary()]
        config.index_db = str(tmp_path / "abs_index.db")
        config.import_settings = MagicMock()
        config.import_settings.duplicate_policy = "skip"
        config.import_settings.trigger_scan = "batch"
        # Trumping config - disabled by default for tests
        config.import_settings.trumping = MagicMock()
        config.import_settings.trumping.enabled = False
        config.import_settings.trumping.aggressiveness = "balanced"
        config.import_settings.trumping.min_bitrate_increase_kbps = 64
        config.import_settings.trumping.prefer_chapters = True
        config.import_settings.trumping.prefer_stereo = True
        config.import_settings.trumping.min_duration_ratio = 0.9
        config.import_settings.trumping.max_duration_ratio = 1.25
        config.import_settings.trumping.archive_root = None
        config.import_settings.trumping.archive_by_year = True
        return config

    def test_abs_import_config_not_found(self, args: argparse.Namespace) -> None:
        """Test abs-import handles missing config file."""
        from mamfast.cli import cmd_abs_import

        with patch("mamfast.config.reload_settings") as mock_reload:
            mock_reload.side_effect = FileNotFoundError("config not found")
            result = cmd_abs_import(args)
            assert result == 1

    def test_abs_import_abs_disabled(self, args: argparse.Namespace) -> None:
        """Test abs-import warns when ABS is disabled."""
        from mamfast.cli import cmd_abs_import

        mock_settings = MagicMock()
        mock_settings.audiobookshelf.enabled = False

        with patch("mamfast.config.reload_settings", return_value=mock_settings):
            result = cmd_abs_import(args)
            assert result == 1

    def test_abs_import_no_managed_libraries(
        self, args: argparse.Namespace, mock_abs_config: MagicMock
    ) -> None:
        """Test abs-import fails when no managed libraries configured."""
        from mamfast.cli import cmd_abs_import

        mock_abs_config.libraries = []  # No libraries
        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config

        with patch("mamfast.config.reload_settings", return_value=mock_settings):
            result = cmd_abs_import(args)
            assert result == 1

    def test_abs_import_no_path_map(
        self, args: argparse.Namespace, mock_abs_config: MagicMock
    ) -> None:
        """Test abs-import fails when no path_map configured."""
        from mamfast.cli import cmd_abs_import

        mock_abs_config.path_map = []  # No path map
        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config

        with patch("mamfast.config.reload_settings", return_value=mock_settings):
            result = cmd_abs_import(args)
            assert result == 1

    def test_abs_import_no_books_to_import(
        self, args: argparse.Namespace, mock_abs_config: MagicMock, tmp_path: Path
    ) -> None:
        """Test abs-import with empty staging directory."""
        from mamfast.cli import cmd_abs_import

        # Create required directories
        staging = tmp_path / "staging"
        staging.mkdir()
        library = tmp_path / "audiobooks"
        library.mkdir()
        index_db = tmp_path / "abs_index.db"
        index_db.touch()

        mock_abs_config.path_map = [MockAbsPathMap(host=str(library))]
        mock_abs_config.index_db = str(index_db)

        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config
        mock_settings.paths.library_root = staging

        with patch("mamfast.config.reload_settings", return_value=mock_settings):
            result = cmd_abs_import(args)
            assert result == 0  # Success with nothing to do

    def test_abs_import_dry_run_success(
        self, args: argparse.Namespace, mock_abs_config: MagicMock, tmp_path: Path
    ) -> None:
        """Test abs-import dry run mode."""
        from mamfast.abs.importer import BatchImportResult, ImportResult
        from mamfast.cli import cmd_abs_import

        args.dry_run = True

        # Create staging directory with a book
        staging = tmp_path / "staging"
        staging.mkdir()
        book_folder = staging / "Author - Book {ASIN.B0ABCDEFGH}"
        book_folder.mkdir()
        (book_folder / "book.m4b").write_text("audio")

        library = tmp_path / "audiobooks"
        library.mkdir()

        mock_abs_config.path_map = [MockAbsPathMap(host=str(library))]

        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config
        mock_settings.paths.library_root = staging

        mock_result = BatchImportResult()
        mock_result.add(
            ImportResult(
                staging_path=book_folder,
                target_path=library / "Author" / book_folder.name,
                asin="B0ABCDEFGH",
                status="success",
            )
        )

        # Mock the AbsClient and build_asin_index
        mock_user = MagicMock()
        mock_user.username = "testuser"
        mock_client = MagicMock()
        mock_client.authorize.return_value = mock_user

        with (
            patch("mamfast.config.reload_settings", return_value=mock_settings),
            patch("mamfast.abs.AbsClient", return_value=mock_client),
            patch("mamfast.abs.build_asin_index", return_value={}),
            patch("mamfast.abs.import_batch", return_value=mock_result),
        ):
            result = cmd_abs_import(args)
            assert result == 0

    def test_abs_import_abs_search_disabled_by_default(
        self, args: argparse.Namespace, mock_abs_config: MagicMock, tmp_path: Path
    ) -> None:
        """Test that ABS search is disabled by default (opt-in)."""
        from mamfast.abs.importer import BatchImportResult
        from mamfast.cli import cmd_abs_import

        # Create staging directory with a book
        staging = tmp_path / "staging"
        staging.mkdir()
        book_folder = staging / "Author - Book"  # No ASIN in name
        book_folder.mkdir()
        (book_folder / "book.m4b").write_text("audio")

        library = tmp_path / "audiobooks"
        library.mkdir()

        mock_abs_config.path_map = [MockAbsPathMap(host=str(library))]

        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config
        mock_settings.paths.library_root = staging

        mock_user = MagicMock()
        mock_user.username = "testuser"
        mock_client = MagicMock()
        mock_client.authorize.return_value = mock_user

        with (
            patch("mamfast.config.reload_settings", return_value=mock_settings),
            patch("mamfast.abs.AbsClient", return_value=mock_client),
            patch("mamfast.abs.build_asin_index", return_value={}),
            patch("mamfast.abs.import_batch", return_value=BatchImportResult()) as mock_batch,
        ):
            result = cmd_abs_import(args)
            assert result == 0
            # Verify abs_client is None when --abs-search not passed
            call_kwargs = mock_batch.call_args.kwargs
            assert call_kwargs["abs_client"] is None

    def test_abs_import_abs_search_enabled_with_flag(
        self, args: argparse.Namespace, mock_abs_config: MagicMock, tmp_path: Path
    ) -> None:
        """Test that --abs-search enables ABS search."""
        from mamfast.abs.importer import BatchImportResult
        from mamfast.cli import cmd_abs_import

        args.abs_search = True  # Enable ABS search

        staging = tmp_path / "staging"
        staging.mkdir()
        book_folder = staging / "Author - Book"
        book_folder.mkdir()
        (book_folder / "book.m4b").write_text("audio")

        library = tmp_path / "audiobooks"
        library.mkdir()

        mock_abs_config.path_map = [MockAbsPathMap(host=str(library))]

        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config
        mock_settings.paths.library_root = staging

        mock_user = MagicMock()
        mock_user.username = "testuser"
        mock_client = MagicMock()
        mock_client.authorize.return_value = mock_user

        with (
            patch("mamfast.config.reload_settings", return_value=mock_settings),
            patch("mamfast.abs.AbsClient", return_value=mock_client),
            patch("mamfast.abs.build_asin_index", return_value={}),
            patch("mamfast.abs.import_batch", return_value=BatchImportResult()) as mock_batch,
        ):
            result = cmd_abs_import(args)
            assert result == 0
            # Verify abs_client is passed when --abs-search is set
            call_kwargs = mock_batch.call_args.kwargs
            assert call_kwargs["abs_client"] is mock_client

    def test_abs_import_confidence_flows_through(
        self, args: argparse.Namespace, mock_abs_config: MagicMock, tmp_path: Path
    ) -> None:
        """Test that --confidence value flows through to import_batch."""
        from mamfast.abs.importer import BatchImportResult
        from mamfast.cli import cmd_abs_import

        args.abs_search = True
        args.confidence = 0.6  # Custom confidence

        staging = tmp_path / "staging"
        staging.mkdir()
        book_folder = staging / "Author - Book"
        book_folder.mkdir()
        (book_folder / "book.m4b").write_text("audio")

        library = tmp_path / "audiobooks"
        library.mkdir()

        mock_abs_config.path_map = [MockAbsPathMap(host=str(library))]

        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config
        mock_settings.paths.library_root = staging

        mock_user = MagicMock()
        mock_user.username = "testuser"
        mock_client = MagicMock()
        mock_client.authorize.return_value = mock_user

        with (
            patch("mamfast.config.reload_settings", return_value=mock_settings),
            patch("mamfast.abs.AbsClient", return_value=mock_client),
            patch("mamfast.abs.build_asin_index", return_value={}),
            patch("mamfast.abs.import_batch", return_value=BatchImportResult()) as mock_batch,
        ):
            result = cmd_abs_import(args)
            assert result == 0
            call_kwargs = mock_batch.call_args.kwargs
            assert call_kwargs["abs_search_confidence"] == 0.6

    def test_abs_import_invalid_confidence_too_high(
        self, args: argparse.Namespace, mock_abs_config: MagicMock, tmp_path: Path
    ) -> None:
        """Test that confidence > 1.0 is rejected with error."""
        from mamfast.cli import cmd_abs_import

        args.confidence = 75  # Common mistake: 75 instead of 0.75

        staging = tmp_path / "staging"
        staging.mkdir()
        book_folder = staging / "Author - Book"
        book_folder.mkdir()
        (book_folder / "book.m4b").write_text("audio")

        library = tmp_path / "audiobooks"
        library.mkdir()

        mock_abs_config.path_map = [MockAbsPathMap(host=str(library))]

        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config
        mock_settings.paths.library_root = staging

        mock_user = MagicMock()
        mock_user.username = "testuser"
        mock_client = MagicMock()
        mock_client.authorize.return_value = mock_user

        with (
            patch("mamfast.config.reload_settings", return_value=mock_settings),
            patch("mamfast.abs.AbsClient", return_value=mock_client),
            patch("mamfast.abs.build_asin_index", return_value={}),
        ):
            result = cmd_abs_import(args)
            assert result == 1  # Should fail with invalid confidence

    def test_abs_import_invalid_confidence_negative(
        self, args: argparse.Namespace, mock_abs_config: MagicMock, tmp_path: Path
    ) -> None:
        """Test that negative confidence is rejected with error."""
        from mamfast.cli import cmd_abs_import

        args.confidence = -0.5

        staging = tmp_path / "staging"
        staging.mkdir()
        book_folder = staging / "Author - Book"
        book_folder.mkdir()
        (book_folder / "book.m4b").write_text("audio")

        library = tmp_path / "audiobooks"
        library.mkdir()

        mock_abs_config.path_map = [MockAbsPathMap(host=str(library))]

        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config
        mock_settings.paths.library_root = staging

        mock_user = MagicMock()
        mock_user.username = "testuser"
        mock_client = MagicMock()
        mock_client.authorize.return_value = mock_user

        with (
            patch("mamfast.config.reload_settings", return_value=mock_settings),
            patch("mamfast.abs.AbsClient", return_value=mock_client),
            patch("mamfast.abs.build_asin_index", return_value={}),
        ):
            result = cmd_abs_import(args)
            assert result == 1  # Should fail with invalid confidence


# =============================================================================
# Tests: abs-check-duplicate command
# =============================================================================


class TestAbsCheckDuplicateParser:
    """Tests for abs-check-duplicate command parser setup."""

    def test_abs_check_duplicate_parser_exists(self) -> None:
        """Test abs-check-duplicate subcommand is registered."""
        parser = build_parser()
        args = parser.parse_args(["abs-check-duplicate", "B0ABCDEFGH"])
        assert args.command == "abs-check-duplicate"
        assert hasattr(args, "func")

    def test_abs_check_duplicate_asin_argument(self) -> None:
        """Test abs-check-duplicate requires ASIN argument."""
        parser = build_parser()
        args = parser.parse_args(["abs-check-duplicate", "B0TESTTEST"])
        assert args.asin == "B0TESTTEST"


class TestAbsCheckDuplicateCommand:
    """Tests for abs-check-duplicate command implementation."""

    @pytest.fixture
    def args(self) -> argparse.Namespace:
        """Create basic args namespace."""
        return argparse.Namespace(
            config="config/config.yaml",
            asin="B0ABCDEFGH",
        )

    def test_abs_check_duplicate_invalid_asin(self, args: argparse.Namespace) -> None:
        """Test abs-check-duplicate rejects invalid ASIN."""
        from mamfast.cli import cmd_abs_check_duplicate

        args.asin = "invalid"
        result = cmd_abs_check_duplicate(args)
        assert result == 1

    def test_abs_check_duplicate_config_not_found(self, args: argparse.Namespace) -> None:
        """Test abs-check-duplicate handles missing config file."""
        from mamfast.cli import cmd_abs_check_duplicate

        with patch("mamfast.config.reload_settings") as mock_reload:
            mock_reload.side_effect = FileNotFoundError("config not found")
            result = cmd_abs_check_duplicate(args)
            assert result == 1

    def test_abs_check_duplicate_abs_disabled(self, args: argparse.Namespace) -> None:
        """Test abs-check-duplicate warns when ABS is disabled."""
        from mamfast.cli import cmd_abs_check_duplicate

        mock_settings = MagicMock()
        mock_settings.audiobookshelf.enabled = False

        with patch("mamfast.config.reload_settings", return_value=mock_settings):
            result = cmd_abs_check_duplicate(args)
            assert result == 1

    def test_abs_check_duplicate_abs_connection_error(
        self, args: argparse.Namespace, tmp_path: Path
    ) -> None:
        """Test abs-check-duplicate handles ABS connection errors."""
        from mamfast.cli import cmd_abs_check_duplicate

        mock_lib_config = MagicMock()
        mock_lib_config.id = "lib_test"
        mock_lib_config.mamfast_managed = True

        mock_settings = MagicMock()
        mock_settings.audiobookshelf.enabled = True
        mock_settings.audiobookshelf.host = "http://localhost:13378"
        mock_settings.audiobookshelf.api_key = "test-key"
        mock_settings.audiobookshelf.timeout_seconds = 30
        mock_settings.audiobookshelf.libraries = [mock_lib_config]

        with (
            patch("mamfast.config.reload_settings", return_value=mock_settings),
            patch("mamfast.abs.AbsClient"),
            patch("mamfast.abs.build_asin_index", side_effect=Exception("Connection refused")),
        ):
            result = cmd_abs_check_duplicate(args)
            assert result == 1  # Error = non-zero

    def test_abs_check_duplicate_not_found(self, args: argparse.Namespace, tmp_path: Path) -> None:
        """Test abs-check-duplicate returns 0 when ASIN not found."""
        from mamfast.cli import cmd_abs_check_duplicate

        mock_lib_config = MagicMock()
        mock_lib_config.id = "lib_test"
        mock_lib_config.mamfast_managed = True

        mock_settings = MagicMock()
        mock_settings.audiobookshelf.enabled = True
        mock_settings.audiobookshelf.host = "http://localhost:13378"
        mock_settings.audiobookshelf.api_key = "test-key"
        mock_settings.audiobookshelf.timeout_seconds = 30
        mock_settings.audiobookshelf.libraries = [mock_lib_config]

        mock_client = MagicMock()

        # Empty ASIN index = no duplicates
        empty_index: dict[str, MagicMock] = {}

        with (
            patch("mamfast.config.reload_settings", return_value=mock_settings),
            patch("mamfast.abs.AbsClient", return_value=mock_client),
            patch("mamfast.abs.build_asin_index", return_value=empty_index),
        ):
            result = cmd_abs_check_duplicate(args)
            assert result == 0  # Not found = safe to import

    def test_abs_check_duplicate_found(self, args: argparse.Namespace, tmp_path: Path) -> None:
        """Test abs-check-duplicate returns 1 when ASIN exists."""
        from mamfast.abs import AsinEntry
        from mamfast.cli import cmd_abs_check_duplicate

        mock_lib_config = MagicMock()
        mock_lib_config.id = "lib_test"
        mock_lib_config.mamfast_managed = True

        mock_settings = MagicMock()
        mock_settings.audiobookshelf.enabled = True
        mock_settings.audiobookshelf.host = "http://localhost:13378"
        mock_settings.audiobookshelf.api_key = "test-key"
        mock_settings.audiobookshelf.timeout_seconds = 30
        mock_settings.audiobookshelf.libraries = [mock_lib_config]

        mock_client = MagicMock()

        # Index with the ASIN we're looking for
        mock_entry = AsinEntry(
            asin="B0ABCDEFGH",
            path="/audiobooks/Test Author/Test Book",
            library_item_id="li_test",
            title="Test Book",
            author="Test Author",
        )
        asin_index = {"B0ABCDEFGH": mock_entry}

        with (
            patch("mamfast.config.reload_settings", return_value=mock_settings),
            patch("mamfast.abs.AbsClient", return_value=mock_client),
            patch("mamfast.abs.build_asin_index", return_value=asin_index),
        ):
            result = cmd_abs_check_duplicate(args)
            assert result == 1  # Found = duplicate


# =============================================================================
# Tests: abs-resolve-asins command
# =============================================================================


class TestAbsResolveAsinsParser:
    """Tests for abs-resolve-asins command parser setup."""

    def test_abs_resolve_asins_parser_exists(self) -> None:
        """Test abs-resolve-asins subcommand is registered."""
        parser = build_parser()
        args = parser.parse_args(["abs-resolve-asins"])
        assert args.command == "abs-resolve-asins"
        assert hasattr(args, "func")

    def test_abs_resolve_asins_default_confidence(self) -> None:
        """Test abs-resolve-asins default confidence is 0.75."""
        parser = build_parser()
        args = parser.parse_args(["abs-resolve-asins"])
        assert args.confidence == 0.75

    def test_abs_resolve_asins_custom_confidence(self) -> None:
        """Test abs-resolve-asins --confidence flag."""
        parser = build_parser()
        args = parser.parse_args(["abs-resolve-asins", "--confidence", "0.9"])
        assert args.confidence == 0.9

    def test_abs_resolve_asins_path_flag(self) -> None:
        """Test abs-resolve-asins --path flag."""
        parser = build_parser()
        args = parser.parse_args(["abs-resolve-asins", "--path", "/some/path"])
        assert args.path == Path("/some/path")

    def test_abs_resolve_asins_write_sidecar_flag(self) -> None:
        """Test abs-resolve-asins --write-sidecar flag."""
        parser = build_parser()
        args_no_flag = parser.parse_args(["abs-resolve-asins"])
        assert args_no_flag.write_sidecar is False

        args_with_flag = parser.parse_args(["abs-resolve-asins", "--write-sidecar"])
        assert args_with_flag.write_sidecar is True


class TestAbsResolveAsinsConfidenceValidation:
    """Tests for abs-resolve-asins confidence validation."""

    @pytest.fixture
    def args(self) -> argparse.Namespace:
        """Create basic args namespace."""
        return argparse.Namespace(
            config="config/config.yaml",
            dry_run=False,
            verbose=False,
            path=None,
            confidence=0.75,
            write_sidecar=False,
        )

    @pytest.fixture
    def mock_abs_config(self) -> MagicMock:
        """Create mock ABS config."""
        config = MagicMock()
        config.enabled = True
        config.host = "http://localhost:13378"
        config.api_key = "test-key"
        config.timeout_seconds = 30
        return config

    def test_abs_resolve_asins_invalid_confidence_too_high(
        self, args: argparse.Namespace, mock_abs_config: MagicMock, tmp_path: Path
    ) -> None:
        """Test that confidence > 1.0 is rejected with error."""
        from mamfast.cli import cmd_abs_resolve_asins

        args.confidence = 75  # Common mistake: 75 instead of 0.75
        args.path = tmp_path

        # Create folder to scan
        book_folder = tmp_path / "Some Book"
        book_folder.mkdir()

        mock_abs_config.path_map = [MockAbsPathMap(host=str(tmp_path))]

        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config

        with patch("mamfast.config.reload_settings", return_value=mock_settings):
            result = cmd_abs_resolve_asins(args)
            assert result == 1  # Should fail with invalid confidence

    def test_abs_resolve_asins_invalid_confidence_negative(
        self, args: argparse.Namespace, mock_abs_config: MagicMock, tmp_path: Path
    ) -> None:
        """Test that negative confidence is rejected with error."""
        from mamfast.cli import cmd_abs_resolve_asins

        args.confidence = -0.5
        args.path = tmp_path

        # Create folder to scan
        book_folder = tmp_path / "Some Book"
        book_folder.mkdir()

        mock_abs_config.path_map = [MockAbsPathMap(host=str(tmp_path))]

        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config

        with patch("mamfast.config.reload_settings", return_value=mock_settings):
            result = cmd_abs_resolve_asins(args)
            assert result == 1  # Should fail with invalid confidence

    def test_abs_resolve_asins_valid_confidence_at_boundaries(
        self, args: argparse.Namespace, mock_abs_config: MagicMock, tmp_path: Path
    ) -> None:
        """Test that confidence at 0.0 and 1.0 boundaries is accepted."""
        from mamfast.cli import cmd_abs_resolve_asins

        # Create empty folder (no subfolders to process)
        args.path = tmp_path
        mock_abs_config.path_map = [MockAbsPathMap(host=str(tmp_path))]

        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config

        # Test 0.0 boundary
        args.confidence = 0.0
        with patch("mamfast.config.reload_settings", return_value=mock_settings):
            result = cmd_abs_resolve_asins(args)
            # Should not fail on validation, just return 0 because no folders
            assert result == 0

        # Test 1.0 boundary
        args.confidence = 1.0
        with patch("mamfast.config.reload_settings", return_value=mock_settings):
            result = cmd_abs_resolve_asins(args)
            assert result == 0


class TestAbsTrumpCheckCommand:
    """Tests for abs-trump-check command implementation."""

    @pytest.fixture
    def args(self) -> argparse.Namespace:
        """Create basic args namespace."""
        return argparse.Namespace(
            config="config/config.yaml",
            paths=[],
            verbose=False,
        )

    @pytest.fixture
    def mock_abs_config(self) -> MagicMock:
        """Create mock audiobookshelf config with trumping."""
        config = MagicMock()
        config.enabled = True
        config.host = "http://localhost:13378"
        config.api_key = "test-key"
        config.timeout_seconds = 30
        config.path_map = [MockAbsPathMap()]
        config.libraries = [MockAbsLibrary()]

        # Trumping config
        trumping = MagicMock()
        trumping.enabled = True
        trumping.aggressiveness = "balanced"
        trumping.min_bitrate_increase_kbps = 64
        trumping.prefer_chapters = True
        trumping.prefer_stereo = True
        trumping.min_duration_ratio = 0.9
        trumping.max_duration_ratio = 1.25
        trumping.archive_root = "/tmp/archive"
        trumping.archive_by_year = True
        config.import_settings.trumping = trumping

        return config

    def test_abs_trump_check_parser_exists(self) -> None:
        """Test abs-trump-check subcommand is registered."""
        parser = build_parser()
        args = parser.parse_args(["abs-trump-check"])
        assert args.command == "abs-trump-check"
        assert hasattr(args, "func")

    def test_abs_trump_check_verbose_flag(self) -> None:
        """Test abs-trump-check accepts verbose flag."""
        parser = build_parser()
        args = parser.parse_args(["abs-trump-check", "--verbose"])
        assert args.verbose is True

    def test_abs_trump_check_paths_argument(self) -> None:
        """Test abs-trump-check accepts paths argument."""
        parser = build_parser()
        args = parser.parse_args(["abs-trump-check", "/path/to/folder"])
        assert len(args.paths) == 1

    def test_abs_trump_check_config_not_found(self, args: argparse.Namespace) -> None:
        """Test abs-trump-check handles missing config file."""
        from mamfast.cli import cmd_abs_trump_check

        with patch("mamfast.config.reload_settings") as mock_reload:
            mock_reload.side_effect = FileNotFoundError("config not found")
            result = cmd_abs_trump_check(args)
            assert result == 1

    def test_abs_trump_check_abs_disabled(self, args: argparse.Namespace) -> None:
        """Test abs-trump-check warns when ABS is disabled."""
        from mamfast.cli import cmd_abs_trump_check

        mock_settings = MagicMock()
        mock_settings.audiobookshelf.enabled = False

        with patch("mamfast.config.reload_settings", return_value=mock_settings):
            result = cmd_abs_trump_check(args)
            assert result == 1

    def test_abs_trump_check_no_managed_libraries(
        self, args: argparse.Namespace, mock_abs_config: MagicMock
    ) -> None:
        """Test abs-trump-check fails when no managed libraries configured."""
        from mamfast.cli import cmd_abs_trump_check

        mock_abs_config.libraries = []

        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config

        with patch("mamfast.config.reload_settings", return_value=mock_settings):
            result = cmd_abs_trump_check(args)
            assert result == 1

    def test_abs_trump_check_no_staged_books(
        self, args: argparse.Namespace, mock_abs_config: MagicMock, tmp_path: Path
    ) -> None:
        """Test abs-trump-check returns 0 when no staged books found."""
        from mamfast.cli import cmd_abs_trump_check

        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config
        mock_settings.paths.library_root = tmp_path  # Empty directory

        with (
            patch("mamfast.config.reload_settings", return_value=mock_settings),
            patch("mamfast.abs.AbsClient"),
            patch("mamfast.abs.build_asin_index", return_value={}),
            patch("mamfast.abs.discover_staged_books", return_value=[]),
        ):
            result = cmd_abs_trump_check(args)
            assert result == 0

    def test_abs_trump_check_connection_error(
        self, args: argparse.Namespace, mock_abs_config: MagicMock, tmp_path: Path
    ) -> None:
        """Test abs-trump-check handles ABS connection errors."""
        from mamfast.cli import cmd_abs_trump_check

        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config
        mock_settings.paths.library_root = tmp_path

        # Create a staged folder
        staged_folder = tmp_path / "Test Book"
        staged_folder.mkdir()

        with (
            patch("mamfast.config.reload_settings", return_value=mock_settings),
            patch("mamfast.abs.discover_staged_books", return_value=[staged_folder]),
            patch("mamfast.abs.AbsClient", side_effect=Exception("Connection refused")),
        ):
            result = cmd_abs_trump_check(args)
            assert result == 1

    def test_abs_trump_check_book_without_asin(
        self, args: argparse.Namespace, mock_abs_config: MagicMock, tmp_path: Path
    ) -> None:
        """Test abs-trump-check handles books without ASIN."""
        from mamfast.cli import cmd_abs_trump_check

        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config
        mock_settings.paths.library_root = tmp_path

        # Create a staged folder without ASIN
        staged_folder = tmp_path / "Author - Some Book (2024)"
        staged_folder.mkdir()

        mock_client = MagicMock()
        mock_client.close = MagicMock()

        with (
            patch("mamfast.config.reload_settings", return_value=mock_settings),
            patch("mamfast.abs.discover_staged_books", return_value=[staged_folder]),
            patch("mamfast.abs.AbsClient", return_value=mock_client),
            patch("mamfast.abs.build_asin_index", return_value={}),
        ):
            result = cmd_abs_trump_check(args)
            assert result == 0  # Success, just no ASIN

    def test_abs_trump_check_new_book(
        self, args: argparse.Namespace, mock_abs_config: MagicMock, tmp_path: Path
    ) -> None:
        """Test abs-trump-check handles new books (ASIN not in library)."""
        from mamfast.cli import cmd_abs_trump_check

        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config
        mock_settings.paths.library_root = tmp_path

        # Create a staged folder with ASIN
        staged_folder = tmp_path / "Author - Title (2024) {ASIN.B0NEWBOOK01}"
        staged_folder.mkdir()

        mock_client = MagicMock()
        mock_client.close = MagicMock()

        with (
            patch("mamfast.config.reload_settings", return_value=mock_settings),
            patch("mamfast.abs.discover_staged_books", return_value=[staged_folder]),
            patch("mamfast.abs.AbsClient", return_value=mock_client),
            patch("mamfast.abs.build_asin_index", return_value={}),  # Empty index
        ):
            result = cmd_abs_trump_check(args)
            assert result == 0

    def test_abs_trump_check_trumping_disabled_shows_preview(
        self, args: argparse.Namespace, mock_abs_config: MagicMock, tmp_path: Path
    ) -> None:
        """Test abs-trump-check still works when trumping is disabled."""
        from mamfast.cli import cmd_abs_trump_check

        # Disable trumping
        mock_abs_config.import_settings.trumping.enabled = False

        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config
        mock_settings.paths.library_root = tmp_path

        mock_client = MagicMock()
        mock_client.close = MagicMock()

        with (
            patch("mamfast.config.reload_settings", return_value=mock_settings),
            patch("mamfast.abs.discover_staged_books", return_value=[]),
            patch("mamfast.abs.AbsClient", return_value=mock_client),
            patch("mamfast.abs.build_asin_index", return_value={}),
        ):
            result = cmd_abs_trump_check(args)
            assert result == 0  # Should still work, just show preview message


class TestAbsRestoreCommand:
    """Tests for abs-restore command implementation."""

    @pytest.fixture
    def args(self) -> argparse.Namespace:
        """Create basic args namespace."""
        return argparse.Namespace(
            config="config/config.yaml",
            dry_run=False,
            archive_path=None,
            asin=None,
            list=False,
        )

    @pytest.fixture
    def mock_abs_config(self) -> MagicMock:
        """Create mock audiobookshelf config with trumping."""
        config = MagicMock()
        config.enabled = True
        config.host = "http://localhost:13378"
        config.api_key = "test-key"
        config.timeout_seconds = 30
        config.path_map = [MockAbsPathMap()]
        config.libraries = [MockAbsLibrary()]

        # Trumping config with archive_root
        trumping = MagicMock()
        trumping.enabled = True
        trumping.archive_root = "/tmp/archive"
        config.import_settings.trumping = trumping

        return config

    def test_abs_restore_parser_exists(self) -> None:
        """Test abs-restore subcommand is registered."""
        parser = build_parser()
        args = parser.parse_args(["abs-restore"])
        assert args.command == "abs-restore"
        assert hasattr(args, "func")

    def test_abs_restore_list_flag(self) -> None:
        """Test abs-restore accepts list flag."""
        parser = build_parser()
        args = parser.parse_args(["abs-restore", "--list"])
        assert args.list is True

    def test_abs_restore_asin_filter(self) -> None:
        """Test abs-restore accepts asin filter."""
        parser = build_parser()
        args = parser.parse_args(["abs-restore", "--asin", "B0TEST12345"])
        assert args.asin == "B0TEST12345"

    def test_abs_restore_config_not_found(self, args: argparse.Namespace) -> None:
        """Test abs-restore handles missing config file."""
        from mamfast.cli import cmd_abs_restore

        with patch("mamfast.config.reload_settings") as mock_reload:
            mock_reload.side_effect = FileNotFoundError("config not found")
            result = cmd_abs_restore(args)
            assert result == 1

    def test_abs_restore_abs_disabled(self, args: argparse.Namespace) -> None:
        """Test abs-restore warns when ABS is disabled."""
        from mamfast.cli import cmd_abs_restore

        mock_settings = MagicMock()
        mock_settings.audiobookshelf.enabled = False

        with patch("mamfast.config.reload_settings", return_value=mock_settings):
            result = cmd_abs_restore(args)
            assert result == 1

    def test_abs_restore_no_archive_root(
        self, args: argparse.Namespace, mock_abs_config: MagicMock
    ) -> None:
        """Test abs-restore fails when no archive_root configured."""
        from mamfast.cli import cmd_abs_restore

        mock_abs_config.import_settings.trumping.archive_root = None

        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config

        with patch("mamfast.config.reload_settings", return_value=mock_settings):
            result = cmd_abs_restore(args)
            assert result == 1

    def test_abs_restore_list_empty(
        self, args: argparse.Namespace, mock_abs_config: MagicMock, tmp_path: Path
    ) -> None:
        """Test abs-restore list mode with empty archives."""
        from mamfast.cli import cmd_abs_restore

        mock_abs_config.import_settings.trumping.archive_root = str(tmp_path)

        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config

        args.list = True

        with patch("mamfast.config.reload_settings", return_value=mock_settings):
            result = cmd_abs_restore(args)
            assert result == 0

    def test_abs_restore_list_archives(
        self, args: argparse.Namespace, mock_abs_config: MagicMock, tmp_path: Path
    ) -> None:
        """Test abs-restore list mode shows archives."""
        import json

        from mamfast.cli import cmd_abs_restore

        mock_abs_config.import_settings.trumping.archive_root = str(tmp_path)

        # Create an archive
        archive = tmp_path / "B0TEST12345" / "2024-01-01T12-00-00"
        archive.mkdir(parents=True)
        sidecar = archive / ".mamfast_trump.json"
        sidecar.write_text(
            json.dumps(
                {
                    "archived_at": "2024-01-01T12:00:00+00:00",
                    "reason": "Format upgrade",
                    "decision": "REPLACE_WITH_NEW",
                    "existing_meta": {"asin": "B0TEST12345", "format": "mp3"},
                }
            )
        )

        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config

        args.list = True

        with patch("mamfast.config.reload_settings", return_value=mock_settings):
            result = cmd_abs_restore(args)
            assert result == 0

    def test_abs_restore_invalid_archive_path(
        self, args: argparse.Namespace, mock_abs_config: MagicMock, tmp_path: Path
    ) -> None:
        """Test abs-restore fails for nonexistent archive path."""
        from mamfast.cli import cmd_abs_restore

        mock_abs_config.import_settings.trumping.archive_root = str(tmp_path)

        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config

        args.archive_path = tmp_path / "nonexistent"

        with patch("mamfast.config.reload_settings", return_value=mock_settings):
            result = cmd_abs_restore(args)
            assert result == 1

    def test_abs_restore_missing_sidecar(
        self, args: argparse.Namespace, mock_abs_config: MagicMock, tmp_path: Path
    ) -> None:
        """Test abs-restore fails when archive has no sidecar."""
        from mamfast.cli import cmd_abs_restore

        mock_abs_config.import_settings.trumping.archive_root = str(tmp_path)

        # Create archive without sidecar
        archive = tmp_path / "fake_archive"
        archive.mkdir()

        mock_settings = MagicMock()
        mock_settings.audiobookshelf = mock_abs_config

        args.archive_path = archive

        with patch("mamfast.config.reload_settings", return_value=mock_settings):
            result = cmd_abs_restore(args)
            assert result == 1
