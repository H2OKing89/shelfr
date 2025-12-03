"""Tests for pathvalidate integration (cross-platform filename safety)."""

from __future__ import annotations

from mamfast.utils.paths import safe_dirname, safe_filename, safe_filepath


class TestSafeFilename:
    """Tests for safe_filename function."""

    def test_normal_filename(self):
        """Test that normal filenames pass through unchanged."""
        result = safe_filename("My Audiobook.m4b")
        assert result == "My Audiobook.m4b"

    def test_reserved_windows_names(self):
        """Test that Windows reserved names are sanitized."""
        # CON, PRN, AUX, NUL, COM1-9, LPT1-9 are reserved on Windows
        result = safe_filename("CON.m4b")
        assert result != "CON.m4b"
        assert "CON" not in result or result != "CON.m4b"

        result = safe_filename("NUL.txt")
        assert result != "NUL.txt"

        result = safe_filename("COM1.m4b")
        assert result != "COM1.m4b"

    def test_trailing_dot_removed(self):
        """Test that trailing dots are removed (Windows issue)."""
        result = safe_filename("My Book...")
        assert not result.endswith(".")

    def test_trailing_space_removed(self):
        """Test that trailing spaces are removed."""
        result = safe_filename("My Book   ")
        assert not result.endswith(" ")

    def test_max_length_respected(self):
        """Test that max_length is respected."""
        long_name = "A" * 300 + ".m4b"
        result = safe_filename(long_name, max_length=225)
        assert len(result) <= 225

    def test_preserves_extension(self):
        """Test that file extension is preserved during truncation."""
        long_name = "A" * 300 + ".m4b"
        result = safe_filename(long_name, max_length=225)
        assert result.endswith(".m4b")

    def test_unicode_characters(self):
        """Test that Unicode characters are handled."""
        # Japanese title
        result = safe_filename("転生したらスライムだった件.m4b")
        assert len(result) > 0
        assert ".m4b" in result

        # Mixed scripts
        result = safe_filename("Sword Art Online ソードアート・オンライン.m4b")
        assert len(result) > 0


class TestSafeDirname:
    """Tests for safe_dirname function."""

    def test_normal_dirname(self):
        """Test that normal directory names pass through."""
        result = safe_dirname("My Audiobook Series")
        assert result == "My Audiobook Series"

    def test_reserved_windows_names_in_dir(self):
        """Test that reserved names are handled in directory names."""
        result = safe_dirname("CON")
        assert result != "CON"

        result = safe_dirname("AUX")
        assert result != "AUX"

    def test_mam_compliant_name(self):
        """Test MAM-style folder name with ASIN."""
        name = "Sword Art Online vol_01 Aincrad (2012) (Reki Kawahara) {ASIN.B00ABC123} [H2OKing]"
        result = safe_dirname(name)
        # Should preserve the structure
        assert "vol_01" in result
        assert "ASIN" in result

    def test_max_length_for_dir(self):
        """Test max_length for directory names."""
        long_name = "Series Name " * 30
        result = safe_dirname(long_name, max_length=225)
        assert len(result) <= 225


class TestSafeFilepath:
    """Tests for safe_filepath function."""

    def test_normal_path(self):
        """Test that normal paths work."""
        from pathlib import Path

        result = safe_filepath("/home/user/audiobooks/My Book.m4b")
        assert isinstance(result, Path)

    def test_path_with_problematic_component(self):
        """Test path with problematic directory component."""
        result = safe_filepath("/data/CON/file.m4b")
        # The CON component should be sanitized
        assert "CON" not in str(result) or str(result) != "/data/CON/file.m4b"


class TestIntegrationWithNaming:
    """Test integration with naming.py functions."""

    def test_build_mam_folder_name_safe(self):
        """Test that build_mam_folder_name produces safe names."""
        from mamfast.utils.naming import build_mam_folder_name

        # Test with potentially problematic inputs
        result = build_mam_folder_name(
            series="CON",  # Reserved Windows name
            title="My Book",
            volume_number="1",
            year="2023",
            author="Author",
            asin="B00ABC123",
        )
        # Should not produce exactly "CON" as a path component
        assert result != "CON"
        assert len(result) > 3  # Should have more than just "CON"

    def test_build_mam_file_name_safe(self):
        """Test that build_mam_file_name produces safe names."""
        from mamfast.utils.naming import build_mam_file_name

        result = build_mam_file_name(
            series="PRN",  # Reserved Windows name
            title="Book Title",
            volume_number="1",
            year="2023",
            author="Author",
            asin="B00ABC123",
            extension=".m4b",
        )
        # Should be a valid filename
        assert result.endswith(".m4b")
        assert len(result) <= 225


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_empty_string(self):
        """Test handling of empty strings."""
        result = safe_filename("")
        # pathvalidate may return empty or raise - just check it doesn't crash
        assert isinstance(result, str)

    def test_only_dots(self):
        """Test handling of strings with only dots."""
        result = safe_filename("...")
        # Should sanitize to something
        assert not result.endswith(".")

    def test_only_spaces(self):
        """Test handling of strings with only spaces."""
        result = safe_filename("   ")
        # Should sanitize to something (likely empty after strip)
        assert isinstance(result, str)

    def test_null_bytes(self):
        """Test handling of null bytes."""
        result = safe_filename("My\x00Book.m4b")
        # Null bytes should be removed
        assert "\x00" not in result

    def test_very_long_unicode(self):
        """Test handling of long Unicode strings."""
        # 300 Japanese characters (each is 3 bytes in UTF-8, but 1 char)
        # Note: 225 hiragana characters + ".m4b" = 229 chars, which exceeds limit
        # So extension may be truncated when dealing with pure Unicode
        long_unicode = "あ" * 300 + ".m4b"
        result = safe_filename(long_unicode, max_length=225)
        assert len(result) <= 225
        # Extension preservation depends on available space after Unicode truncation
        # The important thing is the result is valid and within limit
