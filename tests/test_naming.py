"""Tests for naming utilities."""

import pytest

from mamfast.utils.naming import (
    build_release_dirname,
    sanitize_filename,
    truncate_filename,
)


class TestSanitizeFilename:
    """Tests for filename sanitization."""

    def test_removes_illegal_chars(self):
        """Test removal of illegal characters."""
        assert sanitize_filename("Book: A Story") == "Book - A Story"
        assert sanitize_filename("What?") == "What"
        assert sanitize_filename("This/That") == "This-That"
        assert sanitize_filename('Say "Hello"') == "Say 'Hello'"

    def test_collapses_spaces(self):
        """Test multiple spaces are collapsed."""
        assert sanitize_filename("Too    Many   Spaces") == "Too Many Spaces"

    def test_strips_dots_and_spaces(self):
        """Test leading/trailing dots and spaces are stripped."""
        assert sanitize_filename("  Book  ") == "Book"
        assert sanitize_filename("...Book...") == "Book"
        assert sanitize_filename(". Book .") == "Book"


class TestTruncateFilename:
    """Tests for filename truncation."""

    def test_short_name_unchanged(self):
        """Test short names are returned unchanged."""
        name = "Short Name.m4b"
        assert truncate_filename(name, max_length=225) == name

    def test_long_name_truncated(self):
        """Test long names are truncated."""
        name = "A" * 300 + ".m4b"
        result = truncate_filename(name, max_length=225)
        assert len(result) <= 225
        assert result.endswith(".m4b")

    def test_preserves_extension(self):
        """Test file extension is preserved."""
        name = "Very Long Title " * 20 + ".m4b"
        result = truncate_filename(name, max_length=100)
        assert result.endswith(".m4b")

    def test_adds_hash_suffix(self):
        """Test truncated names get hash suffix for uniqueness."""
        name = "A" * 300 + ".m4b"
        result = truncate_filename(name, max_length=225)
        assert "...[" in result
        assert "]" in result


class TestBuildReleaseDirname:
    """Tests for release directory name building."""

    def test_author_and_title(self):
        """Test basic author - title format."""
        result = build_release_dirname(author="John Smith", title="Great Book")
        assert result == "John Smith - Great Book"

    def test_with_year(self):
        """Test author - title (year) format."""
        result = build_release_dirname(
            author="Jane Doe",
            title="Another Book",
            year="2023",
        )
        assert result == "Jane Doe - Another Book (2023)"

    def test_with_series(self):
        """Test including series info."""
        result = build_release_dirname(
            author="Author",
            title="Book",
            series="Epic Series",
            series_position="3",
        )
        assert "Epic Series #3" in result

    def test_title_only(self):
        """Test with only title provided."""
        result = build_release_dirname(author=None, title="Just Title")
        assert result == "Just Title"

    def test_sanitizes_special_chars(self):
        """Test special characters are sanitized."""
        result = build_release_dirname(
            author="Author: Name",
            title="Book/Title",
        )
        assert ":" not in result
        assert "/" not in result
