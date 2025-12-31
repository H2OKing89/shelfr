"""Tests for models module."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from shelfr.models import (
    AudiobookRelease,
    ProcessedState,
    ProcessingResult,
    ReleaseStatus,
    sanitize_for_filename,
)


class TestReleaseStatus:
    """Tests for ReleaseStatus enum."""

    def test_status_values(self):
        """Test that all expected statuses exist."""
        assert ReleaseStatus.DISCOVERED
        assert ReleaseStatus.STAGED
        assert ReleaseStatus.METADATA_FETCHED
        assert ReleaseStatus.TORRENT_CREATED
        assert ReleaseStatus.UPLOADED
        assert ReleaseStatus.COMPLETE
        assert ReleaseStatus.FAILED


class TestAudiobookRelease:
    """Tests for AudiobookRelease dataclass."""

    def test_minimal_creation(self):
        """Test creating release with minimal data."""
        release = AudiobookRelease(title="Test Book")
        assert release.title == "Test Book"
        assert release.author == ""
        assert release.asin is None
        assert release.status == ReleaseStatus.DISCOVERED

    def test_full_creation(self):
        """Test creating release with all fields."""
        release = AudiobookRelease(
            asin="B09ABCD123",
            title="Epic Fantasy",
            author="Jane Author",
            narrator="John Narrator",
            series="Fantasy Series",
            series_position="1",
            year="2024",
            source_dir=Path("/tmp/source"),
            staging_dir=Path("/tmp/staging"),
        )
        assert release.asin == "B09ABCD123"
        assert release.title == "Epic Fantasy"
        assert release.author == "Jane Author"
        assert release.narrator == "John Narrator"
        assert release.series == "Fantasy Series"
        assert release.series_position == "1"
        assert release.year == "2024"

    def test_display_name_author_and_title(self):
        """Test display_name with author and title."""
        release = AudiobookRelease(title="Test Book", author="Test Author")
        assert release.display_name == "Test Author - Test Book"

    def test_display_name_title_only(self):
        """Test display_name with only title."""
        release = AudiobookRelease(title="Test Book")
        assert release.display_name == "Test Book"

    def test_display_name_no_title(self):
        """Test display_name with no title falls back to ASIN or unknown."""
        release = AudiobookRelease(asin="B09TEST123")
        assert "B09TEST123" in release.display_name or "Unknown" in release.display_name

    def test_default_status(self):
        """Test default status is DISCOVERED."""
        release = AudiobookRelease(title="Test")
        assert release.status == ReleaseStatus.DISCOVERED

    def test_status_can_be_changed(self):
        """Test status can be updated."""
        release = AudiobookRelease(title="Test")
        release.status = ReleaseStatus.STAGED
        assert release.status == ReleaseStatus.STAGED

    def test_files_default_empty_list(self):
        """Test files defaults to empty list."""
        release = AudiobookRelease(title="Test")
        assert release.files == []
        assert isinstance(release.files, list)

    def test_files_can_be_populated(self):
        """Test files list can be populated."""
        release = AudiobookRelease(title="Test")
        release.files = [Path("/tmp/book.m4b"), Path("/tmp/cover.jpg")]
        assert len(release.files) == 2

    def test_error_field(self):
        """Test error field for failed releases."""
        release = AudiobookRelease(
            title="Failed Book",
            status=ReleaseStatus.FAILED,
            error="Connection timeout",
        )
        assert release.status == ReleaseStatus.FAILED
        assert release.error == "Connection timeout"

    def test_metadata_fields(self):
        """Test metadata fields can store dicts."""
        release = AudiobookRelease(title="Test")
        release.audnex_metadata = {"title": "Test", "runtime": 3600}
        release.mediainfo_data = {"bitrate": "128kbps"}

        assert release.audnex_metadata["runtime"] == 3600
        assert release.mediainfo_data["bitrate"] == "128kbps"

    def test_timestamps(self):
        """Test timestamp fields."""
        now = datetime.now()
        release = AudiobookRelease(
            title="Test",
            discovered_at=now,
        )
        assert release.discovered_at == now
        assert release.processed_at is None


class TestSafeDirname:
    """Tests for safe_dirname property."""

    def test_author_and_title(self):
        """Test safe_dirname with author and title."""
        release = AudiobookRelease(author="John Smith", title="Great Book")
        assert release.safe_dirname == "John Smith - Great Book"

    def test_with_year(self):
        """Test safe_dirname includes year."""
        release = AudiobookRelease(author="Jane Doe", title="Another Book", year="2023")
        assert release.safe_dirname == "Jane Doe - Another Book (2023)"

    def test_title_only(self):
        """Test safe_dirname with only title."""
        release = AudiobookRelease(title="Just Title")
        assert release.safe_dirname == "Just Title"

    def test_sanitizes_special_chars(self):
        """Test safe_dirname sanitizes special characters."""
        release = AudiobookRelease(author="Author/Name", title="Book: Subtitle")
        result = release.safe_dirname
        assert "/" not in result
        assert ":" not in result

    def test_fallback_to_source_dir(self):
        """Test safe_dirname falls back to source_dir name."""
        release = AudiobookRelease(source_dir=Path("/path/to/Book Name"))
        assert release.safe_dirname == "Book Name"

    def test_unknown_fallback(self):
        """Test safe_dirname falls back to unknown_release."""
        release = AudiobookRelease()
        assert release.safe_dirname == "unknown_release"


class TestProcessingResult:
    """Tests for ProcessingResult dataclass."""

    def test_success_result(self):
        """Test successful processing result."""
        release = AudiobookRelease(title="Test Book")
        result = ProcessingResult(
            release=release,
            success=True,
            torrent_path=Path("/tmp/test.torrent"),
            duration_seconds=5.5,
        )
        assert result.success is True
        assert result.error is None
        assert result.status_emoji == "✓"
        assert result.duration_seconds == 5.5

    def test_failure_result(self):
        """Test failed processing result."""
        release = AudiobookRelease(title="Failed Book")
        result = ProcessingResult(
            release=release,
            success=False,
            error="Connection failed",
        )
        assert result.success is False
        assert result.error == "Connection failed"
        assert result.status_emoji == "✗"


class TestProcessedState:
    """Tests for ProcessedState dataclass."""

    def test_creation(self):
        """Test creating ProcessedState."""
        state = ProcessedState(
            asin="B09TEST123",
            title="Test Book",
            author="Test Author",
            processed_at="2024-01-15T10:30:00",
            staging_dir="/tmp/staging/Test",
            torrent_path="/tmp/torrents/test.torrent",
            status="COMPLETE",
        )
        assert state.asin == "B09TEST123"
        assert state.title == "Test Book"
        assert state.status == "COMPLETE"


class TestSanitizeForFilename:
    """Tests for sanitize_for_filename function."""

    def test_removes_illegal_chars(self):
        """Test removal of illegal filename characters."""
        assert sanitize_for_filename("Book: Subtitle") == "Book - Subtitle"
        assert sanitize_for_filename("File/Name") == "File-Name"
        assert sanitize_for_filename("What?") == "What"
        assert sanitize_for_filename("Star*") == "Star"
        assert sanitize_for_filename("<Tag>") == "Tag"
        assert sanitize_for_filename('Say "Hello"') == "Say 'Hello'"
        assert sanitize_for_filename("One|Two") == "One-Two"
        assert sanitize_for_filename("Path\\Name") == "Path-Name"

    def test_collapses_spaces(self):
        """Test multiple spaces are collapsed."""
        assert sanitize_for_filename("Too    Many   Spaces") == "Too Many Spaces"

    def test_strips_dots_and_spaces(self):
        """Test leading/trailing dots and spaces are stripped."""
        assert sanitize_for_filename("  Book  ") == "Book"
        assert sanitize_for_filename("...Book...") == "Book"

    def test_empty_string(self):
        """Test empty string handling."""
        assert sanitize_for_filename("") == ""

    def test_complex_case(self):
        """Test complex case with multiple issues."""
        result = sanitize_for_filename("  Book:  Title?  <Part 1>  ")
        assert ":" not in result
        assert "?" not in result
        assert "<" not in result
        assert ">" not in result
        assert "  " not in result
