"""Tests for hardlinker module."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mamfast.hardlinker import (
    find_allowed_files,
    hardlink_file,
    should_include_file,
    stage_release,
)
from mamfast.models import AudiobookRelease


@pytest.fixture
def mock_settings():
    """Create mock settings for tests."""
    settings = MagicMock()
    settings.paths.seed_root = Path(tempfile.mkdtemp())
    settings.paths.library_root = Path(tempfile.mkdtemp())
    settings.mam.max_filename_length = 225
    settings.mam.allowed_extensions = [".m4b", ".jpg", ".pdf", ".cue"]
    settings.filters.remove_phrases = []
    settings.filters.author_map = {}
    settings.filters.transliterate_japanese = False
    # Add naming config (None uses defaults)
    settings.naming = None
    return settings


@pytest.fixture
def temp_source_dir():
    """Create a temporary source directory with test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        source = Path(tmpdir) / "source"
        source.mkdir()

        # Create test files
        (source / "audiobook.m4b").write_bytes(b"fake m4b content")
        (source / "cover.jpg").write_bytes(b"fake jpg content")
        (source / "notes.pdf").write_bytes(b"fake pdf content")
        (source / "readme.txt").write_text("should be excluded")

        yield source


class TestFindAllowedFiles:
    """Tests for find_allowed_files function."""

    def test_finds_allowed_extensions(self, temp_source_dir, mock_settings):
        """Test that allowed file types are found."""
        with patch("mamfast.hardlinker.get_settings", return_value=mock_settings):
            files = find_allowed_files(temp_source_dir)

        extensions = {f.suffix.lower() for f in files}
        assert ".m4b" in extensions
        assert ".jpg" in extensions
        assert ".pdf" in extensions

    def test_excludes_disallowed_extensions(self, temp_source_dir, mock_settings):
        """Test that disallowed file types are excluded."""
        with patch("mamfast.hardlinker.get_settings", return_value=mock_settings):
            files = find_allowed_files(temp_source_dir)

        extensions = {f.suffix.lower() for f in files}
        assert ".txt" not in extensions

    def test_finds_files_recursively(self, mock_settings):
        """Test that files in subdirectories are found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            subdir = source / "subdir"
            subdir.mkdir()

            (source / "top.m4b").write_bytes(b"top level")
            (subdir / "nested.m4b").write_bytes(b"nested")

            with patch("mamfast.hardlinker.get_settings", return_value=mock_settings):
                files = find_allowed_files(source)

            names = {f.name for f in files}
            assert "top.m4b" in names
            assert "nested.m4b" in names


class TestHardlinkFile:
    """Tests for hardlink_file function."""

    def test_creates_hardlink(self):
        """Test that hardlink is created successfully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "source.txt"
            dst = Path(tmpdir) / "dest.txt"

            src.write_text("test content")
            hardlink_file(src, dst)

            assert dst.exists()
            assert dst.read_text() == "test content"
            # Verify it's a hardlink (same inode)
            assert os.stat(src).st_ino == os.stat(dst).st_ino

    def test_skips_existing_destination(self):
        """Test that existing destination is not overwritten."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "source.txt"
            dst = Path(tmpdir) / "dest.txt"

            src.write_text("source content")
            dst.write_text("existing content")

            hardlink_file(src, dst)

            # Original content should be preserved
            assert dst.read_text() == "existing content"

    def test_falls_back_to_copy_on_cross_device(self):
        """Test that copy is used when hardlink fails with EXDEV."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "source.txt"
            dst = Path(tmpdir) / "dest.txt"

            src.write_text("test content")

            # Mock os.link to raise EXDEV error
            with patch("os.link") as mock_link:
                mock_link.side_effect = OSError(18, "Cross-device link")
                hardlink_file(src, dst)

            assert dst.exists()
            assert dst.read_text() == "test content"

    def test_raises_on_missing_source(self):
        """Test that FileNotFoundError is raised when source doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "nonexistent.txt"
            dst = Path(tmpdir) / "dest.txt"

            with pytest.raises(FileNotFoundError, match="Source file does not exist"):
                hardlink_file(src, dst)


class TestShouldIncludeFile:
    """Tests for should_include_file function."""

    def test_includes_m4b(self, mock_settings):
        """Test that .m4b files are included."""
        with patch("mamfast.hardlinker.get_settings", return_value=mock_settings):
            assert should_include_file(Path("book.m4b")) is True
            assert should_include_file(Path("book.M4B")) is True

    def test_includes_jpg(self, mock_settings):
        """Test that .jpg files are included."""
        with patch("mamfast.hardlinker.get_settings", return_value=mock_settings):
            assert should_include_file(Path("cover.jpg")) is True

    def test_excludes_txt(self, mock_settings):
        """Test that .txt files are excluded."""
        with patch("mamfast.hardlinker.get_settings", return_value=mock_settings):
            assert should_include_file(Path("readme.txt")) is False


class TestStageRelease:
    """Tests for stage_release function."""

    def test_raises_on_missing_source_dir(self, mock_settings):
        """Test that ValueError is raised when source_dir is None."""
        release = AudiobookRelease(title="Test Book")

        with (
            patch("mamfast.hardlinker.get_settings", return_value=mock_settings),
            pytest.raises(ValueError, match="no source_dir"),
        ):
            stage_release(release)

    def test_creates_staging_directory(self, temp_source_dir, mock_settings):
        """Test that staging directory is created."""
        release = AudiobookRelease(
            title="Test Book",
            author="Test Author",
            source_dir=temp_source_dir,
        )

        with patch("mamfast.hardlinker.get_settings", return_value=mock_settings):
            staging_dir = stage_release(release)

        assert staging_dir.exists()
        assert staging_dir.is_dir()

    def test_hardlinks_allowed_files(self, temp_source_dir, mock_settings):
        """Test that allowed files are hardlinked to staging with MAM-compliant names."""
        release = AudiobookRelease(
            title="Test Book",
            author="Test Author",
            source_dir=temp_source_dir,
        )

        with patch("mamfast.hardlinker.get_settings", return_value=mock_settings):
            staging_dir = stage_release(release)

        staged_files = list(staging_dir.iterdir())
        staged_names = {f.name for f in staged_files}

        # Files should be renamed to MAM-compliant format: "Title (Author).ext"
        assert "Test Book (Test Author).m4b" in staged_names
        assert "Test Book (Test Author).jpg" in staged_names
        assert "Test Book (Test Author).pdf" in staged_names
        # txt should still be excluded
        assert len([n for n in staged_names if n.endswith(".txt")]) == 0

    def test_updates_release_staging_dir(self, temp_source_dir, mock_settings):
        """Test that release.staging_dir is updated."""
        release = AudiobookRelease(
            title="Test Book",
            author="Test Author",
            source_dir=temp_source_dir,
        )

        with patch("mamfast.hardlinker.get_settings", return_value=mock_settings):
            staging_dir = stage_release(release)

        assert release.staging_dir == staging_dir

    def test_sets_main_m4b(self, temp_source_dir, mock_settings):
        """Test that release.main_m4b is set."""
        release = AudiobookRelease(
            title="Test Book",
            author="Test Author",
            source_dir=temp_source_dir,
        )

        with patch("mamfast.hardlinker.get_settings", return_value=mock_settings):
            stage_release(release)

        assert release.main_m4b is not None
        assert release.main_m4b.suffix == ".m4b"

    def test_truncates_long_filenames(self, mock_settings):
        """Test that long filenames are truncated."""
        mock_settings.mam.max_filename_length = 50

        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source"
            source.mkdir()

            # Create file with very long name
            long_name = "A" * 100 + ".m4b"
            (source / long_name).write_bytes(b"content")

            release = AudiobookRelease(
                title="Test",
                author="Author",
                source_dir=source,
            )

            with patch("mamfast.hardlinker.get_settings", return_value=mock_settings):
                staging_dir = stage_release(release)

            staged_files = list(staging_dir.iterdir())
            assert len(staged_files) == 1
            assert len(staged_files[0].name) <= 50
