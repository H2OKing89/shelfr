"""Tests for ASIN extraction utilities."""

from __future__ import annotations

from mamfast.abs.asin import (
    extract_all_asins,
    extract_asin,
    extract_asin_from_abs_item,
    extract_asin_with_source,
    is_valid_asin,
)


class TestIsValidAsin:
    """Tests for is_valid_asin()."""

    def test_valid_audiobook_asin(self) -> None:
        """Standard audiobook ASINs start with B0."""
        assert is_valid_asin("B0DK9TS6D9") is True
        assert is_valid_asin("B0CNTY7LVH") is True
        assert is_valid_asin("B0DMQ2WP9F") is True

    def test_valid_kindle_asin(self) -> None:
        """Kindle ASINs can start with B0 or other patterns."""
        assert is_valid_asin("B08G9PRS1K") is True
        assert is_valid_asin("0123456789") is True

    def test_invalid_asin_wrong_length(self) -> None:
        """ASINs must be exactly 10 characters."""
        assert is_valid_asin("B0DK9TS6D") is False  # 9 chars
        assert is_valid_asin("B0DK9TS6D9X") is False  # 11 chars
        assert is_valid_asin("") is False
        assert is_valid_asin("B0") is False

    def test_invalid_asin_special_chars(self) -> None:
        """ASINs must be alphanumeric only."""
        assert is_valid_asin("B0DK9TS6D!") is False
        assert is_valid_asin("B0DK-TS6D9") is False
        assert is_valid_asin("B0DK TS6D9") is False

    def test_none_and_empty(self) -> None:
        """None and empty strings are invalid."""
        assert is_valid_asin(None) is False
        assert is_valid_asin("") is False


class TestExtractAsin:
    """Tests for extract_asin()."""

    def test_current_mamfast_format(self) -> None:
        """Current MAMFast format: {ASIN.B0xxx}."""
        assert extract_asin("Book Title {ASIN.B0DK9TS6D9}") == "B0DK9TS6D9"
        assert extract_asin("{ASIN.B0CNTY7LVH} Book") == "B0CNTY7LVH"
        assert (
            extract_asin("Sword Art Online vol_16 (2025) (Reki Kawahara) {ASIN.B0DK9TS6D9}")
            == "B0DK9TS6D9"
        )

    def test_old_bracket_format(self) -> None:
        """Older bracket format: [ASIN.B0xxx]."""
        assert extract_asin("Book [ASIN.B0CNTY7LVH]") == "B0CNTY7LVH"
        text = "Mushoku Tensei - vol_03 [2024] [Author] [ASIN.B0CNTY7LVH]"
        assert extract_asin(text) == "B0CNTY7LVH"

    def test_bare_bracket_format(self) -> None:
        """Older format: [B0xxxxxxxx] without ASIN prefix."""
        assert extract_asin("Azarinth Healer - vol_04 [Rhaegar] [B0DMQ2WP9F]") == "B0DMQ2WP9F"
        assert extract_asin("Book [B0ABC12345]") == "B0ABC12345"

    def test_bare_asin_format(self) -> None:
        """Fallback: bare ASIN with word boundaries."""
        assert extract_asin("Book B0ABC12345 extra") == "B0ABC12345"
        assert extract_asin("B0XYZ98765") == "B0XYZ98765"

    def test_priority_order(self) -> None:
        """More specific patterns should match first."""
        # {ASIN.} format has priority over bare ASIN
        text = "Book {ASIN.B0DK9TS6D9} with B0OTHERXXX"
        assert extract_asin(text) == "B0DK9TS6D9"

        # [ASIN.] format has priority over [B0xxx]
        text = "Book [ASIN.B0DK9TS6D9] and [B0OTHERXXX]"
        assert extract_asin(text) == "B0DK9TS6D9"

    def test_no_asin_found(self) -> None:
        """Return None when no ASIN pattern matches."""
        assert extract_asin("Project Hail Mary (2021) (Andy Weir)") is None
        assert extract_asin("") is None
        assert extract_asin("Random text without ASIN") is None

    def test_empty_and_none(self) -> None:
        """Handle empty/None input."""
        assert extract_asin("") is None
        # Note: extract_asin expects str, but handle gracefully


class TestExtractAsinWithSource:
    """Tests for extract_asin_with_source()."""

    def test_returns_source_info(self) -> None:
        """Should return AsinSource with pattern info."""
        result = extract_asin_with_source("Book {ASIN.B0DK9TS6D9}", "folder_name")
        assert result is not None
        assert result.asin == "B0DK9TS6D9"
        assert result.source == "folder_name"
        assert result.pattern_index == 0  # First pattern

    def test_different_patterns(self) -> None:
        """Track which pattern matched."""
        # Pattern 0: {ASIN.xxx}
        r0 = extract_asin_with_source("{ASIN.B0ABC12345}", "test")
        assert r0 is not None
        assert r0.pattern_index == 0

        # Pattern 1: [ASIN.xxx]
        r1 = extract_asin_with_source("[ASIN.B0ABC12345]", "test")
        assert r1 is not None
        assert r1.pattern_index == 1

        # Pattern 2: [B0xxx]
        r2 = extract_asin_with_source("[B0ABC12345]", "test")
        assert r2 is not None
        assert r2.pattern_index == 2

        # Pattern 3: bare B0xxx
        r3 = extract_asin_with_source("text B0ABC12345 text", "test")
        assert r3 is not None
        assert r3.pattern_index == 3

    def test_no_match_returns_none(self) -> None:
        """Return None when no match."""
        assert extract_asin_with_source("no asin here", "test") is None
        assert extract_asin_with_source("", "test") is None


class TestExtractAsinFromAbsItem:
    """Tests for extract_asin_from_abs_item()."""

    def test_asin_from_metadata(self) -> None:
        """Prefer ASIN from ABS metadata."""
        item = {
            "id": "li_123",
            "path": "/audiobooks/Author/Book {ASIN.B0OTHER123}",
            "media": {"metadata": {"asin": "B0METADAT1"}},  # 10 chars
        }
        result = extract_asin_from_abs_item(item)
        assert result is not None
        assert result.asin == "B0METADAT1"
        assert result.source == "metadata"

    def test_asin_from_folder_name(self) -> None:
        """Fall back to folder name if no metadata ASIN."""
        item = {
            "id": "li_123",
            "path": "/audiobooks/Author/Book {ASIN.B0FOLDER12}",
            "media": {"metadata": {"title": "Book"}},
        }
        result = extract_asin_from_abs_item(item)
        assert result is not None
        assert result.asin == "B0FOLDER12"
        assert result.source == "folder_name"

    def test_asin_from_file_name(self) -> None:
        """Fall back to audio file name."""
        item = {
            "id": "li_123",
            "path": "/audiobooks/Author/Book",
            "media": {"metadata": {"title": "Book"}},
            "libraryFiles": [
                {
                    "metadata": {"filename": "Book {ASIN.B0FILENAM1}.m4b"},
                }
            ],
        }
        result = extract_asin_from_abs_item(item)
        assert result is not None
        assert result.asin == "B0FILENAM1"
        assert result.source == "file_name"

    def test_skip_non_audio_files(self) -> None:
        """Only check audio file extensions."""
        item = {
            "id": "li_123",
            "path": "/audiobooks/Author/Book",
            "media": {"metadata": {"title": "Book"}},
            "libraryFiles": [
                {
                    "metadata": {"filename": "cover {ASIN.B0NOTAUDIO}.jpg"},
                },
                {
                    "metadata": {"filename": "Book {ASIN.B0AUDIOFIL}.m4b"},
                },
            ],
        }
        result = extract_asin_from_abs_item(item)
        assert result is not None
        assert result.asin == "B0AUDIOFIL"

    def test_no_asin_found(self) -> None:
        """Return None when no ASIN anywhere."""
        item = {
            "id": "li_123",
            "path": "/audiobooks/Author/Book",
            "media": {"metadata": {"title": "Book"}},
            "libraryFiles": [{"metadata": {"filename": "book.m4b"}}],
        }
        assert extract_asin_from_abs_item(item) is None

    def test_invalid_metadata_asin(self) -> None:
        """Skip invalid ASIN in metadata."""
        item = {
            "id": "li_123",
            "path": "/audiobooks/Author/Book {ASIN.B0VALIDASI}",
            "media": {"metadata": {"asin": "invalid"}},
        }
        # Should fall back to folder name
        result = extract_asin_from_abs_item(item)
        assert result is not None
        assert result.asin == "B0VALIDASI"
        assert result.source == "folder_name"


class TestExtractAllAsins:
    """Tests for extract_all_asins()."""

    def test_multiple_asins(self) -> None:
        """Find all ASINs in text."""
        text = "Book {ASIN.B0FIRST123} and {ASIN.B0SECOND12}"
        result = extract_all_asins(text)
        assert len(result) == 2
        assert "B0FIRST123" in result
        assert "B0SECOND12" in result

    def test_deduplication(self) -> None:
        """Same ASIN should appear only once."""
        text = "Book {ASIN.B0SAME0001} repeated {ASIN.B0SAME0001}"
        result = extract_all_asins(text)
        assert result == ["B0SAME0001"]

    def test_mixed_formats(self) -> None:
        """Find ASINs in different formats."""
        text = "{ASIN.B0CURLY001} [ASIN.B0BRACKET1] [B0BARE0001] B0PLAIN001"
        result = extract_all_asins(text)
        assert len(result) == 4
        assert "B0CURLY001" in result
        assert "B0BRACKET1" in result
        assert "B0BARE0001" in result
        assert "B0PLAIN001" in result

    def test_empty_input(self) -> None:
        """Return empty list for empty input."""
        assert extract_all_asins("") == []
        assert extract_all_asins("no asin here") == []

    def test_order_preserved(self) -> None:
        """First occurrence order is preserved."""
        text = "B0FIRST123 B0SECOND12 B0THIRD123"
        result = extract_all_asins(text)
        assert result[0] == "B0FIRST123"
        assert result[1] == "B0SECOND12"
        assert result[2] == "B0THIRD123"
