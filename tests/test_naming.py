"""Tests for naming utilities."""

from mamfast.config import FiltersConfig
from mamfast.utils.naming import (
    build_release_dirname,
    ensure_unique_name,
    extract_translator,
    filter_authors,
    filter_title,
    is_author_role,
    sanitize_filename,
    transliterate_text,
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


class TestFilterAuthors:
    """Tests for author filtering."""

    def test_filters_translator(self):
        """Test filtering out translators."""
        authors = [
            {"name": "Real Author"},
            {"name": "Jane Doe - translator"},
        ]
        result = filter_authors(authors)
        assert len(result) == 1
        assert result[0]["name"] == "Real Author"

    def test_filters_illustrator(self):
        """Test filtering out illustrators."""
        authors = [
            {"name": "Real Author"},
            {"name": "Bob Jones (illustrator)"},
        ]
        result = filter_authors(authors)
        assert len(result) == 1
        assert result[0]["name"] == "Real Author"

    def test_filters_multiple_roles(self):
        """Test filtering multiple non-author roles."""
        authors = [
            {"name": "Real Author"},
            {"name": "Jane - translator"},
            {"name": "Bob (editor)"},
            {"name": "Alice - cover design"},
            {"name": "Charlie (foreword)"},
        ]
        result = filter_authors(authors)
        assert len(result) == 1
        assert result[0]["name"] == "Real Author"

    def test_empty_list(self):
        """Test handling empty list."""
        result = filter_authors([])
        assert result == []


class TestIsAuthorRole:
    """Tests for author role detection."""

    def test_detects_translator(self):
        """Test detecting translator role."""
        assert is_author_role("Jane Doe - translator") is True
        assert is_author_role("Jane Doe (translator)") is True

    def test_detects_illustrator(self):
        """Test detecting illustrator role."""
        assert is_author_role("Bob (illustrator)") is True

    def test_detects_editor(self):
        """Test detecting editor role."""
        assert is_author_role("Alice - editor") is True

    def test_primary_author_not_filtered(self):
        """Test primary authors are not detected as roles."""
        assert is_author_role("John Smith") is False
        assert is_author_role("J.R.R. Tolkien") is False

    def test_no_false_positives_on_names(self):
        """Test names containing role words are NOT filtered (word boundary check)."""
        # These should NOT be detected as roles - the word appears in the name
        assert is_author_role("John Translator Smith") is False
        assert is_author_role("Editor Johnson") is False
        assert is_author_role("Illustrator Jane") is False
        assert is_author_role("Afterword Publishing") is False

    def test_detects_foreword_afterword(self):
        """Test detecting foreword/afterword credits."""
        assert is_author_role("Charlie (foreword)") is True
        assert is_author_role("Bob - afterword") is True
        assert is_author_role("Foreword by Someone") is True


class TestExtractTranslator:
    """Tests for translator extraction."""

    def test_extracts_translator(self):
        """Test extracting translator name."""
        authors = [
            {"name": "Real Author"},
            {"name": "Jane Doe - translator"},
        ]
        result = extract_translator(authors)
        assert result == "Jane Doe"

    def test_no_translator(self):
        """Test when no translator present."""
        authors = [{"name": "Real Author"}]
        result = extract_translator(authors)
        assert result is None


class TestFilterTitle:
    """Tests for title filtering."""

    def test_removes_book_pattern(self):
        """Test removing 'Book XX' pattern."""
        result = filter_title("Epic Story Book 3")
        assert "Book 3" not in result

    def test_removes_custom_phrases(self):
        """Test removing custom phrases."""
        result = filter_title("Title [Custom Tag]", remove_phrases=["[Custom Tag]"])
        assert "[Custom Tag]" not in result

    def test_removes_duplicate_volume(self):
        """Test removing duplicate number before vol_XX."""
        result = filter_title("Title 12 vol_12")
        assert result == "Title vol_12"

    def test_cleans_whitespace(self):
        """Test whitespace cleanup."""
        result = filter_title("Title   with   spaces")
        assert "  " not in result


class TestTransliterateText:
    """Tests for text transliteration."""

    def test_ascii_unchanged(self):
        """Test ASCII text is unchanged."""
        filters = FiltersConfig(author_map={}, transliterate_japanese=False)
        result = transliterate_text("Hello World", filters)
        assert result == "Hello World"

    def test_applies_author_map(self):
        """Test author map substitution."""
        filters = FiltersConfig(
            author_map={"川原礫": "Reki Kawahara"},
            transliterate_japanese=False,
        )
        result = transliterate_text("川原礫", filters)
        assert result == "Reki Kawahara"

    def test_none_filters_returns_unchanged(self):
        """Test None filters returns text unchanged."""
        result = transliterate_text("Test 日本語", None)
        assert result == "Test 日本語"


class TestEnsureUniqueName:
    """Tests for unique name generation."""

    def test_unique_name_unchanged(self):
        """Test unique name returned unchanged."""
        existing = {"other.m4b", "another.m4b"}
        result = ensure_unique_name("unique.m4b", existing)
        assert result == "unique.m4b"

    def test_adds_counter_for_duplicate(self):
        """Test counter added for duplicate."""
        existing = {"book.m4b"}
        result = ensure_unique_name("book.m4b", existing)
        assert result == "book (2).m4b"

    def test_increments_counter(self):
        """Test counter increments for multiple duplicates."""
        existing = {"book.m4b", "book (2).m4b", "book (3).m4b"}
        result = ensure_unique_name("book.m4b", existing)
        assert result == "book (4).m4b"

    def test_preserves_extension(self):
        """Test extension is preserved."""
        existing = {"file.txt"}
        result = ensure_unique_name("file.txt", existing)
        assert result.endswith(".txt")
