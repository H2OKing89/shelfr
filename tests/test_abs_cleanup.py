"""Tests for the abs/cleanup.py module."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from mamfast.abs.cleanup import (
    CLEANUP_ELIGIBLE_STATUSES,
    CleanupError,
    CleanupPrefs,
    CleanupResult,
    CleanupStrategy,
    _cleanup_delete,
    _cleanup_hide,
    _cleanup_move,
    _has_hardlinked_files,
    cleanup_source,
    is_cleanup_eligible,
    should_ignore_folder,
    verify_seed_exists,
)


class TestCleanupStrategy:
    """Tests for CleanupStrategy enum."""

    def test_values(self) -> None:
        """Test all strategy values exist."""
        assert CleanupStrategy.NONE.value == "none"
        assert CleanupStrategy.HIDE.value == "hide"
        assert CleanupStrategy.MOVE.value == "move"
        assert CleanupStrategy.DELETE.value == "delete"

    def test_string_enum(self) -> None:
        """Test string enum behavior."""
        assert str(CleanupStrategy.NONE) == "CleanupStrategy.NONE"
        assert CleanupStrategy.NONE == "none"  # str enum comparison


class TestCleanupPrefs:
    """Tests for CleanupPrefs dataclass."""

    def test_defaults(self) -> None:
        """Test default values."""
        prefs = CleanupPrefs()
        assert prefs.strategy == CleanupStrategy.NONE
        assert prefs.cleanup_path is None
        assert prefs.require_seed_exists is True
        assert prefs.verify_in_abs is False
        assert prefs.hide_marker == ".mamfast_imported"
        assert prefs.min_age_days == 0

    def test_custom_values(self) -> None:
        """Test custom values."""
        prefs = CleanupPrefs(
            strategy=CleanupStrategy.MOVE,
            cleanup_path=Path("/tmp/cleanup"),
            require_seed_exists=False,
            hide_marker=".imported",
        )
        assert prefs.strategy == CleanupStrategy.MOVE
        assert prefs.cleanup_path == Path("/tmp/cleanup")
        assert prefs.require_seed_exists is False
        assert prefs.hide_marker == ".imported"


class TestCleanupResult:
    """Tests for CleanupResult dataclass."""

    def test_basic_result(self) -> None:
        """Test basic result creation."""
        result = CleanupResult(
            source_path=Path("/test/source"),
            status="success",
            strategy=CleanupStrategy.HIDE,
        )
        assert result.source_path == Path("/test/source")
        assert result.status == "success"
        assert result.strategy == CleanupStrategy.HIDE
        assert result.error is None
        assert result.destination is None

    def test_move_result_with_destination(self) -> None:
        """Test move result includes destination."""
        result = CleanupResult(
            source_path=Path("/test/source"),
            status="success",
            strategy=CleanupStrategy.MOVE,
            destination=Path("/cleanup/source"),
        )
        assert result.destination == Path("/cleanup/source")


class TestEligibleStatuses:
    """Tests for CLEANUP_ELIGIBLE_STATUSES constant."""

    def test_eligible_statuses(self) -> None:
        """Test eligible statuses are correct."""
        assert "success" in CLEANUP_ELIGIBLE_STATUSES
        assert "trump_replaced" in CLEANUP_ELIGIBLE_STATUSES
        assert "failed" not in CLEANUP_ELIGIBLE_STATUSES
        assert "skipped" not in CLEANUP_ELIGIBLE_STATUSES
        assert "duplicate" not in CLEANUP_ELIGIBLE_STATUSES


class TestIsCleanupEligible:
    """Tests for is_cleanup_eligible function."""

    def test_eligible_with_m4b_and_metadata(self, tmp_path: Path) -> None:
        """Test folder with .m4b and .metadata.json is eligible."""
        folder = tmp_path / "Author" / "Book"
        folder.mkdir(parents=True)
        (folder / "Book.m4b").touch()
        (folder / "Book.metadata.json").touch()

        assert is_cleanup_eligible(folder) is True

    def test_eligible_with_m4b_and_asin_in_name(self, tmp_path: Path) -> None:
        """Test folder with .m4b and ASIN in name is eligible."""
        # ASIN is exactly 10 chars: B0 + 8 alphanumeric
        folder = tmp_path / "Author - Book {ASIN.B012345678}"
        folder.mkdir(parents=True)
        (folder / "Book.m4b").touch()

        assert is_cleanup_eligible(folder) is True

    def test_ineligible_no_m4b(self, tmp_path: Path) -> None:
        """Test folder without .m4b is not eligible."""
        folder = tmp_path / "Author" / "Book"
        folder.mkdir(parents=True)
        (folder / "Book.mp3").touch()
        (folder / "Book.metadata.json").touch()

        assert is_cleanup_eligible(folder) is False

    def test_ineligible_no_metadata_or_asin(self, tmp_path: Path) -> None:
        """Test folder with .m4b but no metadata/ASIN is not eligible."""
        folder = tmp_path / "Random Book"
        folder.mkdir(parents=True)
        (folder / "Book.m4b").touch()

        assert is_cleanup_eligible(folder) is False

    def test_ineligible_nonexistent(self, tmp_path: Path) -> None:
        """Test nonexistent folder is not eligible."""
        folder = tmp_path / "doesnt" / "exist"
        assert is_cleanup_eligible(folder) is False

    def test_ineligible_file_not_dir(self, tmp_path: Path) -> None:
        """Test file (not directory) is not eligible."""
        file_path = tmp_path / "file.m4b"
        file_path.touch()
        assert is_cleanup_eligible(file_path) is False

    def test_eligible_without_metadata_requirement(self, tmp_path: Path) -> None:
        """Test folder with just .m4b when require_metadata=False."""
        folder = tmp_path / "Random Book"
        folder.mkdir(parents=True)
        (folder / "Book.m4b").touch()

        assert is_cleanup_eligible(folder, require_metadata=False) is True


class TestShouldIgnoreFolder:
    """Tests for should_ignore_folder function."""

    def test_ignore_by_name(self, tmp_path: Path) -> None:
        """Test ignoring folder by exact name match."""
        folder = tmp_path / "__import_test"
        folder.mkdir()

        assert should_ignore_folder(folder, ignore_dirs=["__import_test"]) is True

    def test_ignore_by_parent_name(self, tmp_path: Path) -> None:
        """Test ignoring folder with ignored parent."""
        parent = tmp_path / ".git"
        parent.mkdir()
        folder = parent / "objects"
        folder.mkdir()

        assert should_ignore_folder(folder, ignore_dirs=[".git"]) is True

    def test_ignore_by_glob(self, tmp_path: Path) -> None:
        """Test ignoring folder by glob pattern."""
        folder = tmp_path / "__hidden_folder"
        folder.mkdir()

        # Pattern matches name starting with __
        assert should_ignore_folder(folder, ignore_glob=["__*"]) is True

    def test_not_ignored(self, tmp_path: Path) -> None:
        """Test normal folder is not ignored."""
        folder = tmp_path / "Author" / "Book"
        folder.mkdir(parents=True)

        assert (
            should_ignore_folder(
                folder,
                ignore_dirs=["__import_test", ".git"],
                ignore_glob=["*/__*"],
            )
            is False
        )


class TestVerifySeedExists:
    """Tests for verify_seed_exists function."""

    def test_direct_match_with_hardlinks(self, tmp_path: Path) -> None:
        """Test finding seed by direct name match with hardlinks."""
        # Create source and seed folders
        source_path = tmp_path / "library" / "Book"
        seed_root = tmp_path / "seed"
        seed_path = seed_root / "Book"

        source_path.mkdir(parents=True)
        seed_path.mkdir(parents=True)

        # Create hardlinked file
        source_file = source_path / "book.m4b"
        source_file.write_text("test content")
        seed_file = seed_path / "book.m4b"
        os.link(str(source_file), str(seed_file))

        exists, found_path = verify_seed_exists(source_path, seed_root)
        assert exists is True
        assert found_path == seed_path

    def test_find_by_asin(self, tmp_path: Path) -> None:
        """Test finding seed folder by ASIN in name."""
        source_path = tmp_path / "library" / "Book"
        seed_root = tmp_path / "seed"
        # Seed folder has ASIN in name
        seed_path = seed_root / "Author - Book {ASIN.B0123456789}"

        source_path.mkdir(parents=True)
        seed_path.mkdir(parents=True)

        # Create hardlinked file
        source_file = source_path / "book.m4b"
        source_file.write_text("test content")
        seed_file = seed_path / "book.m4b"
        os.link(str(source_file), str(seed_file))

        exists, found_path = verify_seed_exists(source_path, seed_root, asin="B0123456789")
        assert exists is True
        assert found_path == seed_path

    def test_no_seed_found(self, tmp_path: Path) -> None:
        """Test when no seed exists."""
        source_path = tmp_path / "library" / "Book"
        seed_root = tmp_path / "seed"

        source_path.mkdir(parents=True)
        seed_root.mkdir(parents=True)

        (source_path / "book.m4b").write_text("test")

        exists, found_path = verify_seed_exists(source_path, seed_root)
        assert exists is False
        assert found_path is None

    def test_seed_exists_but_no_hardlinks(self, tmp_path: Path) -> None:
        """Test when seed folder exists but files aren't hardlinked."""
        source_path = tmp_path / "library" / "Book"
        seed_root = tmp_path / "seed"
        seed_path = seed_root / "Book"

        source_path.mkdir(parents=True)
        seed_path.mkdir(parents=True)

        # Create separate files (not hardlinked)
        (source_path / "book.m4b").write_text("source content")
        (seed_path / "book.m4b").write_text("seed content")

        exists, found_path = verify_seed_exists(source_path, seed_root)
        assert exists is False
        assert found_path is None


class TestHasHardlinkedFiles:
    """Tests for _has_hardlinked_files function."""

    def test_hardlinked_files(self, tmp_path: Path) -> None:
        """Test detecting hardlinked files."""
        source_dir = tmp_path / "source"
        seed_dir = tmp_path / "seed"
        source_dir.mkdir()
        seed_dir.mkdir()

        # Create hardlink
        source_file = source_dir / "book.m4b"
        source_file.write_text("content")
        seed_file = seed_dir / "book.m4b"
        os.link(str(source_file), str(seed_file))

        assert _has_hardlinked_files(source_dir, seed_dir) is True

    def test_no_m4b_files(self, tmp_path: Path) -> None:
        """Test with no .m4b files in source."""
        source_dir = tmp_path / "source"
        seed_dir = tmp_path / "seed"
        source_dir.mkdir()
        seed_dir.mkdir()

        (source_dir / "book.txt").touch()

        assert _has_hardlinked_files(source_dir, seed_dir) is False

    def test_different_inodes(self, tmp_path: Path) -> None:
        """Test files with different inodes (copies, not hardlinks)."""
        source_dir = tmp_path / "source"
        seed_dir = tmp_path / "seed"
        source_dir.mkdir()
        seed_dir.mkdir()

        (source_dir / "book.m4b").write_text("source")
        (seed_dir / "book.m4b").write_text("copy")

        assert _has_hardlinked_files(source_dir, seed_dir) is False


class TestCleanupHide:
    """Tests for _cleanup_hide function."""

    def test_creates_marker(self, tmp_path: Path) -> None:
        """Test hide strategy creates marker file."""
        source_path = tmp_path / "book"
        source_path.mkdir()

        result = _cleanup_hide(source_path, ".mamfast_imported", dry_run=False)

        assert result.status == "success"
        assert result.strategy == CleanupStrategy.HIDE
        assert (source_path / ".mamfast_imported").exists()

    def test_dry_run_no_marker(self, tmp_path: Path) -> None:
        """Test dry run doesn't create marker."""
        source_path = tmp_path / "book"
        source_path.mkdir()

        result = _cleanup_hide(source_path, ".mamfast_imported", dry_run=True)

        assert result.status == "dry_run"
        assert not (source_path / ".mamfast_imported").exists()

    def test_handles_permission_error(self, tmp_path: Path) -> None:
        """Test handling permission error when creating marker."""
        source_path = tmp_path / "book"
        source_path.mkdir()

        with patch("pathlib.Path.touch", side_effect=OSError("Permission denied")):
            result = _cleanup_hide(source_path, ".mamfast_imported", dry_run=False)

        assert result.status == "failed"
        assert result.error is not None
        assert "Permission denied" in result.error


class TestCleanupMove:
    """Tests for _cleanup_move function."""

    def test_moves_folder(self, tmp_path: Path) -> None:
        """Test move strategy relocates folder."""
        source_path = tmp_path / "library" / "book"
        cleanup_path = tmp_path / "cleanup"
        source_path.mkdir(parents=True)
        (source_path / "book.m4b").touch()

        result = _cleanup_move(source_path, cleanup_path, dry_run=False)

        assert result.status == "success"
        assert result.strategy == CleanupStrategy.MOVE
        assert result.destination == cleanup_path / "book"
        assert not source_path.exists()
        assert (cleanup_path / "book" / "book.m4b").exists()

    def test_handles_collision(self, tmp_path: Path) -> None:
        """Test collision handling with numeric suffix."""
        source_path = tmp_path / "library" / "book"
        cleanup_path = tmp_path / "cleanup"
        source_path.mkdir(parents=True)
        cleanup_path.mkdir(parents=True)
        # Pre-create collision
        (cleanup_path / "book").mkdir()

        (source_path / "book.m4b").touch()

        result = _cleanup_move(source_path, cleanup_path, dry_run=False)

        assert result.status == "success"
        assert result.destination == cleanup_path / "book_1"

    def test_dry_run_no_move(self, tmp_path: Path) -> None:
        """Test dry run doesn't move folder."""
        source_path = tmp_path / "library" / "book"
        cleanup_path = tmp_path / "cleanup"
        source_path.mkdir(parents=True)
        (source_path / "book.m4b").touch()

        result = _cleanup_move(source_path, cleanup_path, dry_run=True)

        assert result.status == "dry_run"
        assert source_path.exists()
        assert not cleanup_path.exists()


class TestCleanupDelete:
    """Tests for _cleanup_delete function."""

    def test_deletes_folder(self, tmp_path: Path) -> None:
        """Test delete strategy removes folder."""
        source_path = tmp_path / "book"
        source_path.mkdir()
        (source_path / "book.m4b").touch()

        result = _cleanup_delete(source_path, dry_run=False)

        assert result.status == "success"
        assert result.strategy == CleanupStrategy.DELETE
        assert not source_path.exists()

    def test_dry_run_no_delete(self, tmp_path: Path) -> None:
        """Test dry run doesn't delete folder."""
        source_path = tmp_path / "book"
        source_path.mkdir()
        (source_path / "book.m4b").touch()

        result = _cleanup_delete(source_path, dry_run=True)

        assert result.status == "dry_run"
        assert source_path.exists()


class TestCleanupSource:
    """Tests for cleanup_source main function."""

    def test_strategy_none_skips(self, tmp_path: Path) -> None:
        """Test NONE strategy skips cleanup."""
        source_path = tmp_path / "book"
        source_path.mkdir()
        prefs = CleanupPrefs(strategy=CleanupStrategy.NONE)

        result = cleanup_source(source_path, prefs)

        assert result.status == "skipped"
        assert result.strategy == CleanupStrategy.NONE

    def test_refuses_cleanup_under_seed_root(self, tmp_path: Path) -> None:
        """Test refusing to cleanup path under seed_root."""
        seed_root = tmp_path / "seed"
        source_path = seed_root / "book"
        seed_root.mkdir()
        source_path.mkdir()

        prefs = CleanupPrefs(strategy=CleanupStrategy.DELETE)

        with pytest.raises(CleanupError, match="Refusing to cleanup path under seed_root"):
            cleanup_source(source_path, prefs, seed_root=seed_root)

    def test_skips_nonexistent_source(self, tmp_path: Path) -> None:
        """Test skipping nonexistent source path."""
        source_path = tmp_path / "doesnt" / "exist"
        prefs = CleanupPrefs(strategy=CleanupStrategy.DELETE, require_seed_exists=False)

        result = cleanup_source(source_path, prefs)

        assert result.status == "skipped"
        assert result.error is not None
        assert "does not exist" in result.error

    def test_skips_when_seed_not_found(self, tmp_path: Path) -> None:
        """Test skipping when seed verification fails."""
        source_path = tmp_path / "library" / "book"
        seed_root = tmp_path / "seed"
        source_path.mkdir(parents=True)
        seed_root.mkdir()
        (source_path / "book.m4b").touch()

        prefs = CleanupPrefs(
            strategy=CleanupStrategy.DELETE,
            require_seed_exists=True,
        )

        result = cleanup_source(source_path, prefs, seed_root=seed_root)

        assert result.status == "skipped"
        assert result.error is not None
        assert "Seed copy not found" in result.error

    def test_skips_when_no_seed_root_provided(self, tmp_path: Path) -> None:
        """Test skipping when require_seed_exists but no seed_root."""
        source_path = tmp_path / "book"
        source_path.mkdir()

        prefs = CleanupPrefs(
            strategy=CleanupStrategy.DELETE,
            require_seed_exists=True,
        )

        result = cleanup_source(source_path, prefs)

        assert result.status == "skipped"
        assert result.error is not None
        assert "No seed_root provided" in result.error

    def test_hide_strategy_integration(self, tmp_path: Path) -> None:
        """Test hide strategy through main function."""
        source_path = tmp_path / "book"
        source_path.mkdir()

        prefs = CleanupPrefs(
            strategy=CleanupStrategy.HIDE,
            require_seed_exists=False,
            hide_marker=".done",
        )

        result = cleanup_source(source_path, prefs, dry_run=False)

        assert result.status == "success"
        assert (source_path / ".done").exists()

    def test_move_strategy_requires_cleanup_path(self, tmp_path: Path) -> None:
        """Test move strategy fails without cleanup_path."""
        source_path = tmp_path / "book"
        source_path.mkdir()

        prefs = CleanupPrefs(
            strategy=CleanupStrategy.MOVE,
            cleanup_path=None,  # Missing!
            require_seed_exists=False,
        )

        result = cleanup_source(source_path, prefs)

        assert result.status == "failed"
        assert result.error is not None
        assert "cleanup_path is required" in result.error

    def test_move_strategy_integration(self, tmp_path: Path) -> None:
        """Test move strategy through main function."""
        source_path = tmp_path / "library" / "book"
        cleanup_path = tmp_path / "cleanup"
        source_path.mkdir(parents=True)
        (source_path / "book.m4b").touch()

        prefs = CleanupPrefs(
            strategy=CleanupStrategy.MOVE,
            cleanup_path=cleanup_path,
            require_seed_exists=False,
        )

        result = cleanup_source(source_path, prefs, dry_run=False)

        assert result.status == "success"
        assert not source_path.exists()
        assert result.destination is not None
        assert result.destination.exists()

    def test_delete_strategy_with_seed_verification(self, tmp_path: Path) -> None:
        """Test delete strategy with successful seed verification."""
        source_path = tmp_path / "library" / "book"
        seed_root = tmp_path / "seed"
        seed_path = seed_root / "book"

        source_path.mkdir(parents=True)
        seed_path.mkdir(parents=True)

        # Create hardlink
        source_file = source_path / "book.m4b"
        source_file.write_text("content")
        seed_file = seed_path / "book.m4b"
        os.link(str(source_file), str(seed_file))

        prefs = CleanupPrefs(
            strategy=CleanupStrategy.DELETE,
            require_seed_exists=True,
        )

        result = cleanup_source(source_path, prefs, seed_root=seed_root, dry_run=False)

        assert result.status == "success"
        assert not source_path.exists()
        # Seed should still exist
        assert seed_path.exists()
        assert seed_file.exists()


class TestCleanupSchemaValidation:
    """Tests for CleanupSchema in schemas/config.py."""

    def test_default_values(self) -> None:
        """Test schema default values."""
        from mamfast.schemas.config import CleanupSchema

        schema = CleanupSchema()
        assert schema.strategy == "none"
        assert schema.cleanup_path is None
        assert schema.require_seed_exists is True
        assert schema.verify_in_abs is False
        assert schema.hide_marker == ".mamfast_imported"
        assert schema.min_age_days == 0

    def test_valid_strategies(self) -> None:
        """Test all valid strategy values."""
        from mamfast.schemas.config import CleanupSchema

        # Test strategies that don't require additional config
        for strategy in ["none", "hide", "delete"]:
            schema = CleanupSchema(strategy=strategy)
            assert schema.strategy == strategy

        # Test move strategy with required cleanup_path
        schema = CleanupSchema(strategy="move", cleanup_path="/tmp/cleanup")
        assert schema.strategy == "move"

    def test_invalid_strategy(self) -> None:
        """Test invalid strategy is rejected."""
        from pydantic import ValidationError

        from mamfast.schemas.config import CleanupSchema

        with pytest.raises(ValidationError, match="Invalid cleanup strategy"):
            CleanupSchema(strategy="invalid")

    def test_move_requires_cleanup_path(self) -> None:
        """Test move strategy requires cleanup_path."""
        from pydantic import ValidationError

        from mamfast.schemas.config import CleanupSchema

        with pytest.raises(ValidationError, match="cleanup_path is required"):
            CleanupSchema(strategy="move")

    def test_move_with_cleanup_path(self) -> None:
        """Test move strategy with cleanup_path succeeds."""
        from mamfast.schemas.config import CleanupSchema

        schema = CleanupSchema(strategy="move", cleanup_path="/tmp/cleanup")
        assert schema.strategy == "move"
        assert schema.cleanup_path == "/tmp/cleanup"

    def test_cleanup_path_must_be_absolute(self) -> None:
        """Test cleanup_path must be absolute."""
        from pydantic import ValidationError

        from mamfast.schemas.config import CleanupSchema

        with pytest.raises(ValidationError, match="must be an absolute path"):
            CleanupSchema(strategy="move", cleanup_path="relative/path")

    def test_hide_marker_cannot_be_path(self) -> None:
        """Test hide_marker cannot contain path separators."""
        from pydantic import ValidationError

        from mamfast.schemas.config import CleanupSchema

        with pytest.raises(ValidationError, match="must be a filename, not a path"):
            CleanupSchema(hide_marker="/path/to/marker")

    def test_nested_in_import_settings(self) -> None:
        """Test cleanup is nested under import settings."""
        from mamfast.schemas.config import AudiobookshelfImportSchema, CleanupSchema

        # Test using dict (Pydantic should coerce)
        schema = AudiobookshelfImportSchema.model_validate({"cleanup": {"strategy": "hide"}})
        assert schema.cleanup.strategy == "hide"

        # Test using schema instance
        schema2 = AudiobookshelfImportSchema(cleanup=CleanupSchema(strategy="hide"))
        assert schema2.cleanup.strategy == "hide"
