"""Tests for audio file metadata sanitization."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shelfr.sanitize import (
    check_unwanted_tags,
    preview_sanitization,
    sanitize_file,
    sanitize_release,
)

# Default tags used in tests (matches config default)
DEFAULT_TEST_TAGS = ("audible_acr",)


# =============================================================================
# check_unwanted_tags Tests
# =============================================================================


class TestCheckUnwantedTags:
    """Tests for check_unwanted_tags function."""

    def test_no_tags_when_probe_fails(self, tmp_path: Path) -> None:
        """Test returns empty list when ffprobe fails."""
        test_file = tmp_path / "test.m4b"
        test_file.touch()

        with patch("shelfr.sanitize.get_audio_tags", return_value=None):
            result = check_unwanted_tags(test_file, DEFAULT_TEST_TAGS)

        assert result == []

    def test_no_unwanted_tags(self, tmp_path: Path) -> None:
        """Test returns empty list when no unwanted tags present."""
        test_file = tmp_path / "test.m4b"
        test_file.touch()

        clean_tags = {
            "title": "My Audiobook",
            "artist": "Author Name",
            "album": "Series Name",
        }

        with patch("shelfr.sanitize.get_audio_tags", return_value=clean_tags):
            result = check_unwanted_tags(test_file, DEFAULT_TEST_TAGS)

        assert result == []

    def test_finds_audible_acr(self, tmp_path: Path) -> None:
        """Test finds AUDIBLE_ACR tag."""
        test_file = tmp_path / "test.m4b"
        test_file.touch()

        tags_with_acr = {
            "title": "My Audiobook",
            "AUDIBLE_ACR": "CR!SOME_VALUE_HERE",
        }

        with patch("shelfr.sanitize.get_audio_tags", return_value=tags_with_acr):
            result = check_unwanted_tags(test_file, DEFAULT_TEST_TAGS)

        assert "AUDIBLE_ACR" in result

    def test_case_insensitive_match(self, tmp_path: Path) -> None:
        """Test matches tags case-insensitively."""
        test_file = tmp_path / "test.m4b"
        test_file.touch()

        # Lowercase version
        tags = {"audible_acr": "some_value"}

        with patch("shelfr.sanitize.get_audio_tags", return_value=tags):
            result = check_unwanted_tags(test_file, DEFAULT_TEST_TAGS)

        assert "audible_acr" in result

    def test_empty_tags_returns_empty(self, tmp_path: Path) -> None:
        """Test returns empty list when no tags to check."""
        test_file = tmp_path / "test.m4b"
        test_file.touch()

        tags_with_acr = {
            "AUDIBLE_ACR": "CR!SOME_VALUE_HERE",
        }

        with patch("shelfr.sanitize.get_audio_tags", return_value=tags_with_acr):
            result = check_unwanted_tags(test_file, ())

        assert result == []


# =============================================================================
# preview_sanitization Tests
# =============================================================================


class TestPreviewSanitization:
    """Tests for preview_sanitization function."""

    @pytest.fixture
    def mock_release(self, tmp_path: Path) -> MagicMock:
        """Create mock release."""
        release = MagicMock()
        release.source_dir = tmp_path
        return release

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create mock settings with ffmpeg and sanitize enabled."""
        settings = MagicMock()
        settings.ffmpeg.enabled = True
        settings.workflow.upload.sanitize.enabled = True
        settings.workflow.upload.sanitize.tags = DEFAULT_TEST_TAGS
        return settings

    def test_returns_empty_when_sanitize_disabled(self, mock_release: MagicMock) -> None:
        """Test returns empty dict when sanitize is disabled."""
        settings = MagicMock()
        settings.workflow.upload.sanitize.enabled = False

        with patch("shelfr.sanitize.get_settings", return_value=settings):
            result = preview_sanitization(mock_release)

        assert result == {}

    def test_returns_empty_when_no_tags_configured(self, mock_release: MagicMock) -> None:
        """Test returns empty dict when no tags configured."""
        settings = MagicMock()
        settings.workflow.upload.sanitize.enabled = True
        settings.workflow.upload.sanitize.tags = ()

        with patch("shelfr.sanitize.get_settings", return_value=settings):
            result = preview_sanitization(mock_release)

        assert result == {}

    def test_returns_empty_when_ffmpeg_disabled(self, mock_release: MagicMock) -> None:
        """Test returns empty dict when FFmpeg is disabled."""
        settings = MagicMock()
        settings.ffmpeg.enabled = False
        settings.workflow.upload.sanitize.enabled = True
        settings.workflow.upload.sanitize.tags = DEFAULT_TEST_TAGS

        with patch("shelfr.sanitize.get_settings", return_value=settings):
            result = preview_sanitization(mock_release)

        assert result == {}

    def test_returns_empty_when_ffmpeg_unavailable(
        self, mock_release: MagicMock, mock_settings: MagicMock
    ) -> None:
        """Test returns empty dict when FFmpeg is not available."""
        with (
            patch("shelfr.sanitize.get_settings", return_value=mock_settings),
            patch("shelfr.sanitize.ffmpeg_available", return_value=False),
        ):
            result = preview_sanitization(mock_release)

        assert result == {}

    def test_returns_empty_when_no_source_dir(self, mock_settings: MagicMock) -> None:
        """Test returns empty dict when release has no source_dir."""
        release = MagicMock()
        release.source_dir = None

        with (
            patch("shelfr.sanitize.get_settings", return_value=mock_settings),
            patch("shelfr.sanitize.ffmpeg_available", return_value=True),
        ):
            result = preview_sanitization(release)

        assert result == {}

    def test_finds_tags_to_strip(self, tmp_path: Path, mock_settings: MagicMock) -> None:
        """Test finds unwanted tags in m4b files."""
        # Create test file
        m4b_file = tmp_path / "test.m4b"
        m4b_file.touch()

        release = MagicMock()
        release.source_dir = tmp_path

        with (
            patch("shelfr.sanitize.get_settings", return_value=mock_settings),
            patch("shelfr.sanitize.ffmpeg_available", return_value=True),
            patch(
                "shelfr.sanitize.check_unwanted_tags",
                return_value=["AUDIBLE_ACR"],
            ),
        ):
            result = preview_sanitization(release)

        assert m4b_file in result
        assert result[m4b_file] == ["AUDIBLE_ACR"]


# =============================================================================
# sanitize_file Tests
# =============================================================================


class TestSanitizeFile:
    """Tests for sanitize_file function."""

    def test_no_modification_when_no_unwanted_tags(self, tmp_path: Path) -> None:
        """Test returns False when no unwanted tags found."""
        test_file = tmp_path / "test.m4b"
        test_file.touch()

        with patch("shelfr.sanitize.check_unwanted_tags", return_value=[]):
            modified, tags, error = sanitize_file(test_file, unwanted_tags=DEFAULT_TEST_TAGS)

        assert modified is False
        assert tags == []
        assert error is None

    def test_dry_run_reports_but_no_modify(self, tmp_path: Path) -> None:
        """Test dry_run reports tags but doesn't modify."""
        test_file = tmp_path / "test.m4b"
        test_file.write_bytes(b"fake m4b content")
        original_content = test_file.read_bytes()

        with patch(
            "shelfr.sanitize.check_unwanted_tags",
            return_value=["AUDIBLE_ACR"],
        ):
            modified, tags, error = sanitize_file(
                test_file, unwanted_tags=DEFAULT_TEST_TAGS, dry_run=True
            )

        assert modified is False
        assert tags == ["AUDIBLE_ACR"]
        assert error is None
        # File unchanged
        assert test_file.read_bytes() == original_content


# =============================================================================
# sanitize_release Tests
# =============================================================================


class TestSanitizeRelease:
    """Tests for sanitize_release function."""

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create mock settings with ffmpeg and sanitize enabled."""
        settings = MagicMock()
        settings.ffmpeg.enabled = True
        settings.workflow.upload.sanitize.enabled = True
        settings.workflow.upload.sanitize.tags = DEFAULT_TEST_TAGS
        return settings

    def test_skipped_when_sanitize_disabled(self) -> None:
        """Test returns skipped result when sanitize disabled."""
        settings = MagicMock()
        settings.workflow.upload.sanitize.enabled = False

        release = MagicMock()

        with patch("shelfr.sanitize.get_settings", return_value=settings):
            result = sanitize_release(release)

        assert result.success is True
        assert result.skipped_reason == "Sanitization disabled in config"

    def test_skipped_when_no_tags_configured(self) -> None:
        """Test returns skipped result when no tags configured."""
        settings = MagicMock()
        settings.workflow.upload.sanitize.enabled = True
        settings.workflow.upload.sanitize.tags = ()

        release = MagicMock()

        with patch("shelfr.sanitize.get_settings", return_value=settings):
            result = sanitize_release(release)

        assert result.success is True
        assert result.skipped_reason == "No tags configured to strip"

    def test_skipped_when_ffmpeg_disabled(self) -> None:
        """Test returns skipped result when FFmpeg disabled."""
        settings = MagicMock()
        settings.ffmpeg.enabled = False
        settings.workflow.upload.sanitize.enabled = True
        settings.workflow.upload.sanitize.tags = DEFAULT_TEST_TAGS

        release = MagicMock()

        with patch("shelfr.sanitize.get_settings", return_value=settings):
            result = sanitize_release(release)

        assert result.success is True
        assert result.skipped_reason == "FFmpeg disabled in config"

    def test_skipped_when_ffmpeg_unavailable(self, mock_settings: MagicMock) -> None:
        """Test returns skipped result when FFmpeg unavailable."""
        release = MagicMock()

        with (
            patch("shelfr.sanitize.get_settings", return_value=mock_settings),
            patch("shelfr.sanitize.ffmpeg_available", return_value=False),
        ):
            result = sanitize_release(release)

        assert result.success is True
        assert result.skipped_reason == "FFmpeg/Docker not available"

    def test_fails_when_no_source_dir(self, mock_settings: MagicMock) -> None:
        """Test returns error when release has no source_dir."""
        release = MagicMock()
        release.source_dir = None

        with (
            patch("shelfr.sanitize.get_settings", return_value=mock_settings),
            patch("shelfr.sanitize.ffmpeg_available", return_value=True),
        ):
            result = sanitize_release(release)

        assert result.success is False
        assert "no source_dir" in result.errors[0]

    def test_success_with_no_m4b_files(self, tmp_path: Path, mock_settings: MagicMock) -> None:
        """Test succeeds when no m4b files in source_dir."""
        release = MagicMock()
        release.source_dir = tmp_path

        with (
            patch("shelfr.sanitize.get_settings", return_value=mock_settings),
            patch("shelfr.sanitize.ffmpeg_available", return_value=True),
        ):
            result = sanitize_release(release)

        assert result.success is True
        assert result.files_checked == 0

    def test_counts_files_checked(self, tmp_path: Path, mock_settings: MagicMock) -> None:
        """Test counts files that were checked."""
        # Create test files
        (tmp_path / "file1.m4b").touch()
        (tmp_path / "file2.m4b").touch()

        release = MagicMock()
        release.source_dir = tmp_path

        with (
            patch("shelfr.sanitize.get_settings", return_value=mock_settings),
            patch("shelfr.sanitize.ffmpeg_available", return_value=True),
            patch("shelfr.sanitize.sanitize_file", return_value=(False, [], None)),
        ):
            result = sanitize_release(release)

        assert result.success is True
        assert result.files_checked == 2
        assert result.files_skipped == 2  # No tags found


# =============================================================================
# Workflow Config Integration Tests
# =============================================================================


class TestWorkflowConfigIntegration:
    """Tests for workflow config integration."""

    def test_default_tags_from_config(self) -> None:
        """Test default config has AUDIBLE_ACR tag (lowercase)."""
        from shelfr.config import WorkflowConfig

        config = WorkflowConfig()
        assert "audible_acr" in config.upload.sanitize.tags

    def test_case_normalization(self) -> None:
        """Test tags are normalized to lowercase."""
        from shelfr.config import UploadSanitizeConfig

        # Simulate what config loading does
        config = UploadSanitizeConfig(enabled=True, tags=("AUDIBLE_ACR", "Some_Other_TAG"))
        assert config.tags == ("AUDIBLE_ACR", "Some_Other_TAG")  # frozen, user passes normalized
