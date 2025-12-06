"""Tests for ASIN extraction utilities."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from mamfast.abs.asin import (
    AsinResolution,
    _check_mediainfo_available,
    extract_all_asins,
    extract_asin,
    extract_asin_from_abs_item,
    extract_asin_from_mediainfo,
    extract_asin_with_source,
    is_valid_asin,
    resolve_asin_from_folder,
    resolve_asin_from_folder_with_mediainfo,
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


# =============================================================================
# Phase 3: Enhanced ASIN Resolution Tests
# =============================================================================


class TestAsinResolution:
    """Tests for AsinResolution dataclass."""

    def test_found_property_with_asin(self) -> None:
        """found property returns True when ASIN is set."""
        result = AsinResolution(asin="B0ABC12345", source="folder")
        assert result.found is True

    def test_found_property_without_asin(self) -> None:
        """found property returns False when ASIN is None."""
        result = AsinResolution(asin=None, source="unknown")
        assert result.found is False

    def test_source_detail(self) -> None:
        """source_detail tracks where ASIN was found."""
        result = AsinResolution(asin="B0ABC12345", source="filename", source_detail="book.m4b")
        assert result.source == "filename"
        assert result.source_detail == "book.m4b"


class TestResolveAsinFromFolder:
    """Tests for resolve_asin_from_folder() Phase 3 cascade."""

    def test_uses_parsed_asin_if_provided(self, tmp_path: Path) -> None:
        """If caller provides parsed_asin, use it immediately."""
        folder = tmp_path / "SomeBook"
        folder.mkdir()

        result = resolve_asin_from_folder(folder, parsed_asin="B0ABC12345")
        assert result.found is True
        assert result.asin == "B0ABC12345"
        assert result.source == "folder"

    def test_extracts_from_folder_name(self, tmp_path: Path) -> None:
        """Extract ASIN from folder name when no parsed_asin."""
        folder = tmp_path / "Book Title {ASIN.B0FROMNAME}"
        folder.mkdir()

        result = resolve_asin_from_folder(folder)
        assert result.found is True
        assert result.asin == "B0FROMNAME"
        assert result.source == "folder"

    def test_extracts_from_audio_filename(self, tmp_path: Path) -> None:
        """Fall back to audio file names when folder has no ASIN."""
        folder = tmp_path / "Book Without ASIN Tag"
        folder.mkdir()
        # Create audio file with ASIN in name
        audio_file = folder / "Book Title {ASIN.B0FILENAME}.m4b"
        audio_file.touch()

        result = resolve_asin_from_folder(folder)
        assert result.found is True
        assert result.asin == "B0FILENAME"
        assert result.source == "filename"
        assert result.source_detail == audio_file.name

    def test_extracts_from_metadata_json(self, tmp_path: Path) -> None:
        """Fall back to metadata.json sidecar when no ASIN in names."""
        folder = tmp_path / "Book Without ASIN"
        folder.mkdir()
        # Create plain audio file
        (folder / "book.m4b").touch()
        # Create metadata sidecar with ASIN
        meta_file = folder / "book.metadata.json"
        meta_file.write_text(json.dumps({"asin": "B0METADATA"}))

        result = resolve_asin_from_folder(folder)
        assert result.found is True
        assert result.asin == "B0METADATA"
        assert result.source == "metadata"
        assert result.source_detail == "book.metadata.json"

    def test_extracts_from_plain_metadata_json(self, tmp_path: Path) -> None:
        """Also check plain metadata.json file."""
        folder = tmp_path / "Book Without ASIN"
        folder.mkdir()
        (folder / "book.m4b").touch()
        meta_file = folder / "metadata.json"
        meta_file.write_text(json.dumps({"asin": "B0PLAINMET"}))

        result = resolve_asin_from_folder(folder)
        assert result.found is True
        assert result.asin == "B0PLAINMET"
        assert result.source == "metadata"
        assert result.source_detail == "metadata.json"

    def test_extracts_nested_audible_asin(self, tmp_path: Path) -> None:
        """Handle nested audible.asin structure in metadata."""
        folder = tmp_path / "Book"
        folder.mkdir()
        (folder / "book.m4b").touch()
        meta_file = folder / "metadata.json"
        meta_file.write_text(json.dumps({"audible": {"asin": "B0NESTED01"}}))

        result = resolve_asin_from_folder(folder)
        assert result.found is True
        assert result.asin == "B0NESTED01"

    def test_returns_unknown_when_not_found(self, tmp_path: Path) -> None:
        """Return source='unknown' when no ASIN found anywhere."""
        folder = tmp_path / "Book Without ASIN"
        folder.mkdir()
        (folder / "plain_book.m4b").touch()
        # metadata.json without ASIN field
        (folder / "metadata.json").write_text(json.dumps({"title": "Book"}))

        result = resolve_asin_from_folder(folder)
        assert result.found is False
        assert result.asin is None
        assert result.source == "unknown"

    def test_skips_non_audio_files(self, tmp_path: Path) -> None:
        """Don't extract ASIN from non-audio files."""
        folder = tmp_path / "Book"
        folder.mkdir()
        # ASIN only in text file, not audio
        (folder / "notes {ASIN.B0TXTFILE1}.txt").touch()
        (folder / "book.m4b").touch()  # No ASIN

        result = resolve_asin_from_folder(folder)
        assert result.found is False  # Should NOT find txt file ASIN

    def test_handles_malformed_metadata_json(self, tmp_path: Path) -> None:
        """Gracefully handle malformed JSON in metadata file."""
        folder = tmp_path / "Book"
        folder.mkdir()
        (folder / "book.m4b").touch()
        (folder / "metadata.json").write_text("not valid json {{{")

        result = resolve_asin_from_folder(folder)
        assert result.found is False
        assert result.source == "unknown"

    def test_priority_folder_over_filename(self, tmp_path: Path) -> None:
        """Folder ASIN takes priority over filename ASIN."""
        folder = tmp_path / "Book {ASIN.B0FOLDERID}"
        folder.mkdir()
        (folder / "Book {ASIN.B0FILEID01}.m4b").touch()

        result = resolve_asin_from_folder(folder)
        assert result.asin == "B0FOLDERID"
        assert result.source == "folder"

    def test_priority_filename_over_metadata(self, tmp_path: Path) -> None:
        """Filename ASIN takes priority over metadata ASIN."""
        folder = tmp_path / "Book"
        folder.mkdir()
        (folder / "Book {ASIN.B0FILEID01}.m4b").touch()
        (folder / "metadata.json").write_text(json.dumps({"asin": "B0METADATA"}))

        result = resolve_asin_from_folder(folder)
        assert result.asin == "B0FILEID01"
        assert result.source == "filename"

    def test_handles_nonexistent_folder(self, tmp_path: Path) -> None:
        """Handle folder that doesn't exist."""
        folder = tmp_path / "nonexistent"

        result = resolve_asin_from_folder(folder)
        # Should still try folder name extraction
        assert result.found is False
        assert result.source == "unknown"

    @pytest.mark.parametrize("ext", [".m4b", ".mp3", ".m4a", ".opus", ".flac"])
    def test_various_audio_extensions(self, tmp_path: Path, ext: str) -> None:
        """Test ASIN extraction from various audio file types."""
        folder = tmp_path / f"Book_{ext.replace('.', '')}"
        folder.mkdir()
        # Use a valid 10-char ASIN format
        asin = f"B0{ext[1:].upper().ljust(8, 'X')}"[:10]  # Ensure 10 chars
        (folder / f"audio [ASIN.{asin}]{ext}").touch()

        result = resolve_asin_from_folder(folder)
        assert result.found is True, f"Failed for {ext}, expected ASIN {asin}"
        assert result.source == "filename"


# =============================================================================
# Phase 4 Tests: mediainfo Probe
# =============================================================================


class TestMediainfoAvailable:
    """Tests for mediainfo availability check."""

    def test_mediainfo_available_when_installed(self) -> None:
        """Check returns True when mediainfo is in PATH."""
        with patch.object(shutil, "which", return_value="/usr/bin/mediainfo"):
            assert _check_mediainfo_available() is True

    def test_mediainfo_not_available(self) -> None:
        """Check returns False when mediainfo not in PATH."""
        with patch.object(shutil, "which", return_value=None):
            assert _check_mediainfo_available() is False


class TestExtractAsinFromMediainfo:
    """Tests for extract_asin_from_mediainfo()."""

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        """Return None for nonexistent file."""
        result = extract_asin_from_mediainfo(tmp_path / "nonexistent.m4b")
        assert result is None

    def test_not_a_file(self, tmp_path: Path) -> None:
        """Return None for directory."""
        folder = tmp_path / "folder"
        folder.mkdir()
        result = extract_asin_from_mediainfo(folder)
        assert result is None

    def test_mediainfo_returns_asin_field(self, tmp_path: Path) -> None:
        """Extract ASIN from direct 'asin' field in mediainfo output."""
        mock_output = {
            "media": {
                "track": [
                    {
                        "@type": "General",
                        "asin": "B0FDCW8SS7",
                        "Title": "Beware of Chicken 5",
                    }
                ]
            }
        }

        audio_file = tmp_path / "book.m4b"
        audio_file.touch()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = json.dumps(mock_output)
            mock_run.return_value.returncode = 0

            result = extract_asin_from_mediainfo(audio_file)
            assert result == "B0FDCW8SS7"

    def test_mediainfo_returns_cdek_field(self, tmp_path: Path) -> None:
        """Extract ASIN from 'CDEK' field (Audible internal tag)."""
        mock_output = {
            "media": {
                "track": [
                    {
                        "@type": "General",
                        "CDEK": "B0ABC12345",
                        "Title": "Some Book",
                    }
                ]
            }
        }

        audio_file = tmp_path / "book.m4b"
        audio_file.touch()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = json.dumps(mock_output)
            mock_run.return_value.returncode = 0

            result = extract_asin_from_mediainfo(audio_file)
            assert result == "B0ABC12345"

    def test_mediainfo_asin_priority_over_cdek(self, tmp_path: Path) -> None:
        """The 'asin' field has priority over 'CDEK'."""
        mock_output = {
            "media": {
                "track": [
                    {
                        "@type": "General",
                        "asin": "B0ASIN0001",
                        "CDEK": "B0CDEK0002",
                    }
                ]
            }
        }

        audio_file = tmp_path / "book.m4b"
        audio_file.touch()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = json.dumps(mock_output)
            mock_run.return_value.returncode = 0

            result = extract_asin_from_mediainfo(audio_file)
            assert result == "B0ASIN0001"

    def test_mediainfo_nested_extra_asin(self, tmp_path: Path) -> None:
        """Extract ASIN from nested 'extra' dict (common in m4b files)."""
        # Real-world structure from Audible m4b files
        mock_output = {
            "media": {
                "track": [
                    {
                        "@type": "General",
                        "Title": "Some Book",
                        "extra": {
                            "prID": "BK_PODM_010813",
                            "CDEK": "B0FDCW8SS7",
                            "asin": "B0FDCW8SS7",
                        },
                    }
                ]
            }
        }

        audio_file = tmp_path / "book.m4b"
        audio_file.touch()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = json.dumps(mock_output)
            mock_run.return_value.returncode = 0

            result = extract_asin_from_mediainfo(audio_file)
            assert result == "B0FDCW8SS7"

    def test_mediainfo_nested_extra_cdek_only(self, tmp_path: Path) -> None:
        """Extract ASIN from nested extra.CDEK when asin not present."""
        mock_output = {
            "media": {
                "track": [
                    {
                        "@type": "General",
                        "extra": {
                            "CDEK": "B0CDEK1234",
                        },
                    }
                ]
            }
        }

        audio_file = tmp_path / "book.m4b"
        audio_file.touch()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = json.dumps(mock_output)
            mock_run.return_value.returncode = 0

            result = extract_asin_from_mediainfo(audio_file)
            assert result == "B0CDEK1234"

    def test_mediainfo_no_asin_fields(self, tmp_path: Path) -> None:
        """Return None when no ASIN fields present."""
        mock_output = {
            "media": {
                "track": [
                    {
                        "@type": "General",
                        "Title": "Some Book",
                        "Album": "Some Album",
                    }
                ]
            }
        }

        audio_file = tmp_path / "book.m4b"
        audio_file.touch()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = json.dumps(mock_output)
            mock_run.return_value.returncode = 0

            result = extract_asin_from_mediainfo(audio_file)
            assert result is None

    def test_mediainfo_invalid_asin_ignored(self, tmp_path: Path) -> None:
        """Invalid ASIN values are ignored."""
        mock_output = {
            "media": {
                "track": [
                    {
                        "@type": "General",
                        "asin": "invalid",  # Too short
                    }
                ]
            }
        }

        audio_file = tmp_path / "book.m4b"
        audio_file.touch()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = json.dumps(mock_output)
            mock_run.return_value.returncode = 0

            result = extract_asin_from_mediainfo(audio_file)
            assert result is None

    def test_mediainfo_subprocess_error(self, tmp_path: Path) -> None:
        """Handle subprocess error gracefully."""
        audio_file = tmp_path / "book.m4b"
        audio_file.touch()

        with patch("subprocess.run") as mock_run:
            import subprocess as sp

            mock_run.side_effect = sp.SubprocessError("mediainfo failed")

            result = extract_asin_from_mediainfo(audio_file)
            assert result is None

    def test_mediainfo_invalid_json(self, tmp_path: Path) -> None:
        """Handle invalid JSON output gracefully."""
        audio_file = tmp_path / "book.m4b"
        audio_file.touch()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = "not valid json {{{}"
            mock_run.return_value.returncode = 0

            result = extract_asin_from_mediainfo(audio_file)
            assert result is None

    def test_mediainfo_timeout(self, tmp_path: Path) -> None:
        """Handle timeout gracefully."""
        audio_file = tmp_path / "book.m4b"
        audio_file.touch()

        with patch("subprocess.run") as mock_run:
            import subprocess as sp

            mock_run.side_effect = sp.TimeoutExpired(cmd="mediainfo", timeout=30)

            result = extract_asin_from_mediainfo(audio_file)
            assert result is None

    def test_mediainfo_track_is_single_dict(self, tmp_path: Path) -> None:
        """Handle mediainfo returning track as single dict instead of list."""
        # Some versions of mediainfo return a single dict when only one track
        mock_output = {
            "media": {
                "track": {
                    "@type": "General",
                    "asin": "B0SINGLEDI",  # 10 chars
                }
            }
        }

        audio_file = tmp_path / "book.m4b"
        audio_file.touch()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = json.dumps(mock_output)
            mock_run.return_value.returncode = 0

            result = extract_asin_from_mediainfo(audio_file)
            assert result == "B0SINGLEDI"

    def test_mediainfo_track_is_none(self, tmp_path: Path) -> None:
        """Handle mediainfo returning track as None."""
        mock_output = {"media": {"track": None}}

        audio_file = tmp_path / "book.m4b"
        audio_file.touch()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = json.dumps(mock_output)
            mock_run.return_value.returncode = 0

            result = extract_asin_from_mediainfo(audio_file)
            assert result is None

    def test_mediainfo_track_contains_non_dict(self, tmp_path: Path) -> None:
        """Handle track list containing non-dict entries."""
        mock_output = {
            "media": {
                "track": [
                    "not a dict",
                    None,
                    {"@type": "General", "asin": "B0VALIDASN"},  # 10 chars
                    123,
                ]
            }
        }

        audio_file = tmp_path / "book.m4b"
        audio_file.touch()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = json.dumps(mock_output)
            mock_run.return_value.returncode = 0

            result = extract_asin_from_mediainfo(audio_file)
            assert result == "B0VALIDASN"

    def test_mediainfo_unexpected_track_type(self, tmp_path: Path) -> None:
        """Handle unexpected track type (not dict, list, or None)."""
        mock_output = {"media": {"track": "unexpected string"}}

        audio_file = tmp_path / "book.m4b"
        audio_file.touch()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = json.dumps(mock_output)
            mock_run.return_value.returncode = 0

            result = extract_asin_from_mediainfo(audio_file)
            assert result is None


class TestResolveAsinFromFolderWithMediainfo:
    """Tests for resolve_asin_from_folder_with_mediainfo()."""

    def test_falls_back_to_phase3_first(self, tmp_path: Path) -> None:
        """Phase 3 sources are checked before mediainfo."""
        folder = tmp_path / "Book {ASIN.B0FOLDERID}"
        folder.mkdir()
        (folder / "book.m4b").touch()

        # Don't need to mock mediainfo - folder name should resolve first
        result = resolve_asin_from_folder_with_mediainfo(folder)
        assert result.asin == "B0FOLDERID"
        assert result.source == "folder"

    def test_mediainfo_used_when_phase3_fails(self, tmp_path: Path) -> None:
        """mediainfo is used when Phase 3 sources don't find ASIN."""
        folder = tmp_path / "Book Without ASIN"
        folder.mkdir()
        audio_file = folder / "book.m4b"
        audio_file.touch()

        mock_output = {"media": {"track": [{"@type": "General", "asin": "B0MEDIAINF"}]}}

        with (
            patch("mamfast.abs.asin._check_mediainfo_available", return_value=True),
            patch("mamfast.abs.asin.subprocess.run") as mock_run,
        ):
            mock_run.return_value.stdout = json.dumps(mock_output)
            mock_run.return_value.returncode = 0

            result = resolve_asin_from_folder_with_mediainfo(folder)
            assert result.asin == "B0MEDIAINF"
            assert result.source == "mediainfo"
            assert result.source_detail == "book.m4b"

    def test_mediainfo_not_available_returns_unknown(self, tmp_path: Path) -> None:
        """When mediainfo not available, returns unknown."""
        folder = tmp_path / "Book Without ASIN"
        folder.mkdir()
        (folder / "book.m4b").touch()

        with patch("mamfast.abs.asin._check_mediainfo_available", return_value=False):
            result = resolve_asin_from_folder_with_mediainfo(folder)
            assert result.found is False
            assert result.source == "unknown"

    def test_mediainfo_probes_multiple_files(self, tmp_path: Path) -> None:
        """mediainfo probes files until ASIN found."""
        folder = tmp_path / "Book"
        folder.mkdir()
        (folder / "part1.m4b").touch()
        (folder / "part2.m4b").touch()

        # First file has no ASIN, second does
        call_count = 0

        def mock_mediainfo(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = type("Result", (), {"returncode": 0, "stdout": ""})()

            if call_count == 1:
                mock_result.stdout = json.dumps({"media": {"track": [{"@type": "General"}]}})
            else:
                mock_result.stdout = json.dumps(
                    {"media": {"track": [{"@type": "General", "asin": "B0SECOND01"}]}}
                )
            return mock_result

        with (
            patch("mamfast.abs.asin._check_mediainfo_available", return_value=True),
            patch("mamfast.abs.asin.subprocess.run", side_effect=mock_mediainfo),
        ):
            result = resolve_asin_from_folder_with_mediainfo(folder)
            assert result.asin == "B0SECOND01"
            assert result.source == "mediainfo"

    def test_only_probes_audio_files(self, tmp_path: Path) -> None:
        """Non-audio files are not probed with mediainfo."""
        folder = tmp_path / "Book"
        folder.mkdir()
        (folder / "cover.jpg").touch()
        (folder / "metadata.json").write_text("{}")
        (folder / "book.pdf").touch()
        audio = folder / "book.m4b"
        audio.touch()

        mock_output = {"media": {"track": [{"@type": "General", "asin": "B0AUDIOFIL"}]}}

        with (
            patch("mamfast.abs.asin._check_mediainfo_available", return_value=True),
            patch("mamfast.abs.asin.subprocess.run") as mock_run,
        ):
            mock_run.return_value.stdout = json.dumps(mock_output)
            mock_run.return_value.returncode = 0

            result = resolve_asin_from_folder_with_mediainfo(folder)

            # Should only be called once for the .m4b file
            assert mock_run.call_count == 1
            assert result.asin == "B0AUDIOFIL"


# =============================================================================
# Phase 5: ABS Metadata Search Tests
# =============================================================================


class TestMatchSearchResults:
    """Tests for match_search_results() fuzzy matching."""

    def test_exact_title_match(self) -> None:
        """Exact title match returns high confidence."""
        from mamfast.abs.asin import match_search_results

        results = [
            {
                "title": "Wizard's First Rule",
                "author": "Terry Goodkind",
                "asin": "B002V0QK4C",
                "language": "English",
            }
        ]

        match = match_search_results(results, "Wizard's First Rule", "Terry Goodkind")
        assert match is not None
        assert match.asin == "B002V0QK4C"
        assert match.confidence >= 0.9

    def test_fuzzy_title_match(self) -> None:
        """Fuzzy title match with minor differences."""
        from mamfast.abs.asin import match_search_results

        results = [
            {
                "title": "Wizard's First Rule",
                "author": "Terry Goodkind",
                "asin": "B002V0QK4C",
                "language": "English",
            }
        ]

        # Slight variation in title
        match = match_search_results(results, "Wizards First Rule", "Terry Goodkind")
        assert match is not None
        assert match.asin == "B002V0QK4C"
        assert match.confidence >= 0.75

    def test_no_match_below_threshold(self) -> None:
        """No match returned when below confidence threshold."""
        from mamfast.abs.asin import match_search_results

        results = [
            {
                "title": "Completely Different Book",
                "author": "Other Author",
                "asin": "B0DIFFERENT",
                "language": "English",
            }
        ]

        match = match_search_results(
            results, "Wizard's First Rule", "Terry Goodkind", confidence_threshold=0.75
        )
        assert match is None

    def test_prefers_english_results(self) -> None:
        """English results preferred over translations."""
        from mamfast.abs.asin import match_search_results

        results = [
            {
                "title": "Proyecto Hail Mary",
                "author": "Andy Weir",
                "asin": "8418037121",
                "language": "Spanish",
            },
            {
                "title": "Project Hail Mary",
                "author": "Andy Weir",
                "asin": "B08G9PRS1K",
                "language": "English",
            },
        ]

        match = match_search_results(results, "Project Hail Mary", "Andy Weir", prefer_english=True)
        assert match is not None
        assert match.asin == "B08G9PRS1K"  # English version

    def test_empty_results_returns_none(self) -> None:
        """Empty results list returns None."""
        from mamfast.abs.asin import match_search_results

        match = match_search_results([], "Any Title", "Any Author")
        assert match is None

    def test_skips_invalid_asin(self) -> None:
        """Results with invalid ASIN are skipped."""
        from mamfast.abs.asin import match_search_results

        results = [
            {
                "title": "Wizard's First Rule",
                "author": "Terry Goodkind",
                "asin": "INVALID",  # Not a valid ASIN
                "language": "English",
            }
        ]

        match = match_search_results(results, "Wizard's First Rule", "Terry Goodkind")
        assert match is None

    def test_extracts_series_info(self) -> None:
        """Series info extracted from results."""
        from mamfast.abs.asin import match_search_results

        results = [
            {
                "title": "Wizard's First Rule",
                "author": "Terry Goodkind",
                "asin": "B002V0QK4C",
                "language": "English",
                "series": [{"series": "Sword of Truth", "sequence": "1"}],
            }
        ]

        match = match_search_results(results, "Wizard's First Rule", "Terry Goodkind")
        assert match is not None
        assert match.series == "Sword of Truth"
        assert match.sequence == "1"

    def test_handles_no_series(self) -> None:
        """Books without series info handled gracefully."""
        from mamfast.abs.asin import match_search_results

        results = [
            {
                "title": "Project Hail Mary",
                "author": "Andy Weir",
                "asin": "B08G9PRS1K",
                "language": "English",
                "series": None,
            }
        ]

        match = match_search_results(results, "Project Hail Mary", "Andy Weir")
        assert match is not None
        assert match.series is None
        assert match.sequence is None

    def test_title_only_matching(self) -> None:
        """Matching works with title only (no author)."""
        from mamfast.abs.asin import match_search_results

        results = [
            {
                "title": "Project Hail Mary",
                "author": "Andy Weir",
                "asin": "B08G9PRS1K",
                "language": "English",
            }
        ]

        match = match_search_results(results, "Project Hail Mary", folder_author=None)
        assert match is not None
        assert match.asin == "B08G9PRS1K"


class TestResolveAsinViaAbsSearch:
    """Tests for resolve_asin_via_abs_search()."""

    def test_successful_resolution(self) -> None:
        """Successful ASIN resolution via search."""
        from unittest.mock import MagicMock

        from mamfast.abs.asin import resolve_asin_via_abs_search

        mock_client = MagicMock()
        mock_client.search_books.return_value = [
            {
                "title": "Wizard's First Rule",
                "author": "Terry Goodkind",
                "asin": "B002V0QK4C",
                "language": "English",
            }
        ]

        result = resolve_asin_via_abs_search(
            mock_client, title="Wizard's First Rule", author="Terry Goodkind"
        )

        assert result.found is True
        assert result.asin == "B002V0QK4C"
        assert result.source == "abs_search"
        assert "confidence=" in result.source_detail

    def test_no_results_returns_unknown(self) -> None:
        """No search results returns unknown."""
        from unittest.mock import MagicMock

        from mamfast.abs.asin import resolve_asin_via_abs_search

        mock_client = MagicMock()
        mock_client.search_books.return_value = []

        result = resolve_asin_via_abs_search(
            mock_client, title="Nonexistent Book", author="Unknown Author"
        )

        assert result.found is False
        assert result.source == "unknown"

    def test_search_error_returns_unknown(self) -> None:
        """Search API error returns unknown."""
        from unittest.mock import MagicMock

        from mamfast.abs.asin import resolve_asin_via_abs_search

        mock_client = MagicMock()
        mock_client.search_books.side_effect = Exception("Connection failed")

        result = resolve_asin_via_abs_search(mock_client, title="Any Title", author="Any Author")

        assert result.found is False
        assert result.source == "unknown"

    def test_respects_confidence_threshold(self) -> None:
        """Confidence threshold is respected."""
        from unittest.mock import MagicMock

        from mamfast.abs.asin import resolve_asin_via_abs_search

        mock_client = MagicMock()
        mock_client.search_books.return_value = [
            {
                "title": "Very Different Title",
                "author": "Other Author",
                "asin": "B0DIFFERENT",
                "language": "English",
            }
        ]

        # High threshold should reject poor match
        result = resolve_asin_via_abs_search(
            mock_client,
            title="Wizard's First Rule",
            author="Terry Goodkind",
            confidence_threshold=0.9,
        )

        assert result.found is False


class TestSearchMatch:
    """Tests for SearchMatch dataclass."""

    def test_search_match_fields(self) -> None:
        """SearchMatch has expected fields."""
        from mamfast.abs.asin import SearchMatch

        match = SearchMatch(
            asin="B002V0QK4C",
            title="Wizard's First Rule",
            author="Terry Goodkind",
            confidence=0.95,
            language="English",
            series="Sword of Truth",
            sequence="1",
        )

        assert match.asin == "B002V0QK4C"
        assert match.title == "Wizard's First Rule"
        assert match.author == "Terry Goodkind"
        assert match.confidence == 0.95
        assert match.language == "English"
        assert match.series == "Sword of Truth"
        assert match.sequence == "1"
