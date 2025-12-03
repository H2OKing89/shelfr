"""Tests for metadata module."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from mamfast.metadata import (
    _build_series_list,
    _clean_html,
    _extract_audio_info,
    _format_chapter_time,
    _format_duration,
    _get_mediainfo_string,
    _parse_chapters_from_mediainfo,
    build_mam_json,
    fetch_audnex_book,
    render_bbcode_description,
    run_mediainfo,
    save_audnex_json,
    save_mam_json,
    save_mediainfo_json,
)


class TestFetchAudnexBook:
    """Tests for Audnex API integration."""

    def test_fetch_success(self):
        """Test successful metadata fetch."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "asin": "B09TEST123",
            "title": "Test Book",
            "authors": [{"name": "Test Author"}],
        }

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()
        mock_settings.audnex.base_url = "https://api.audnex.us"
        mock_settings.audnex.timeout_seconds = 30

        with (
            patch("httpx.Client", return_value=mock_client),
            patch("mamfast.metadata.get_settings", return_value=mock_settings),
        ):
            result = fetch_audnex_book("B09TEST123")

        assert result is not None
        assert result["asin"] == "B09TEST123"
        assert result["title"] == "Test Book"

    def test_fetch_not_found(self):
        """Test handling 404 response."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()
        mock_settings.audnex.base_url = "https://api.audnex.us"
        mock_settings.audnex.timeout_seconds = 30

        with (
            patch("httpx.Client", return_value=mock_client),
            patch("mamfast.metadata.get_settings", return_value=mock_settings),
        ):
            result = fetch_audnex_book("INVALID_ASIN")

        assert result is None


class TestFetchAudnexChapters:
    """Tests for Audnex chapters API integration."""

    def test_fetch_chapters_success(self):
        """Test successful chapters fetch."""
        from mamfast.metadata import fetch_audnex_chapters

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "asin": "B09TEST123",
            "runtimeLengthMs": 25050260,
            "runtimeLengthSec": 25050,
            "chapters": [
                {
                    "lengthMs": 19597,
                    "startOffsetMs": 0,
                    "startOffsetSec": 0,
                    "title": "Opening Credits",
                },
                {
                    "lengthMs": 706513,
                    "startOffsetMs": 19597,
                    "startOffsetSec": 19,
                    "title": "Prologue",
                },
            ],
        }

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()
        mock_settings.audnex.base_url = "https://api.audnex.us"
        mock_settings.audnex.timeout_seconds = 30

        with (
            patch("httpx.Client", return_value=mock_client),
            patch("mamfast.metadata.get_settings", return_value=mock_settings),
        ):
            result = fetch_audnex_chapters("B09TEST123")

        assert result is not None
        assert result["asin"] == "B09TEST123"
        assert result["runtimeLengthSec"] == 25050
        assert len(result["chapters"]) == 2
        assert result["chapters"][0]["title"] == "Opening Credits"

    def test_fetch_chapters_not_found(self):
        """Test handling 404 response for chapters."""
        from mamfast.metadata import fetch_audnex_chapters

        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()
        mock_settings.audnex.base_url = "https://api.audnex.us"
        mock_settings.audnex.timeout_seconds = 30

        with (
            patch("httpx.Client", return_value=mock_client),
            patch("mamfast.metadata.get_settings", return_value=mock_settings),
        ):
            result = fetch_audnex_chapters("INVALID_ASIN")

        assert result is None


class TestParseChaptersFromAudnex:
    """Tests for parsing Audnex chapters response."""

    def test_parse_chapters(self):
        """Test parsing chapters from Audnex response."""
        from mamfast.metadata import _parse_chapters_from_audnex

        chapters_data = {
            "chapters": [
                {"startOffsetSec": 0, "title": "Opening Credits"},
                {"startOffsetSec": 726, "title": "Chapter 1"},
                {"startOffsetSec": 5479, "title": "Chapter 2"},
            ],
        }

        result = _parse_chapters_from_audnex(chapters_data)

        assert len(result) == 3
        assert result[0].start == "00:00"
        assert result[0].title == "Opening Credits"
        assert result[1].start == "12:06"
        assert result[1].title == "Chapter 1"
        assert result[2].start == "1:31:19"
        assert result[2].title == "Chapter 2"

    def test_parse_empty_chapters(self):
        """Test parsing empty chapters list."""
        from mamfast.metadata import _parse_chapters_from_audnex

        result = _parse_chapters_from_audnex({"chapters": []})
        assert result == []

    def test_parse_no_chapters_key(self):
        """Test parsing response without chapters key."""
        from mamfast.metadata import _parse_chapters_from_audnex

        result = _parse_chapters_from_audnex({})
        assert result == []


class TestRunMediainfo:
    """Tests for mediainfo integration."""

    def test_run_mediainfo_file_not_found(self):
        """Test handling missing file."""
        mock_settings = MagicMock()
        mock_settings.mediainfo.binary = "mediainfo"

        with patch("mamfast.metadata.get_settings", return_value=mock_settings):
            result = run_mediainfo(Path("/nonexistent/file.m4b"))

        assert result is None

    def test_run_mediainfo_success(self):
        """Test successful mediainfo extraction."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"media": {"track": [{"@type": "Audio"}]}}'

        mock_settings = MagicMock()
        mock_settings.mediainfo.binary = "mediainfo"

        # Create a temp file
        with tempfile.NamedTemporaryFile(suffix=".m4b", delete=False) as f:
            f.write(b"fake audio data")
            temp_path = Path(f.name)

        with (
            patch("subprocess.run", return_value=mock_result),
            patch("mamfast.metadata.get_settings", return_value=mock_settings),
        ):
            result = run_mediainfo(temp_path)

        assert result is not None
        assert "media" in result


class TestFormatDuration:
    """Tests for duration formatting."""

    def test_hours_and_minutes(self):
        """Test formatting with hours and minutes."""

        assert _format_duration(22260) == "6h 11m"  # 6:11

    def test_only_minutes(self):
        """Test formatting with only minutes."""

        assert _format_duration(1800) == "30m"

    def test_zero_minutes(self):
        """Test edge case with zero seconds."""

        assert _format_duration(0) == "0m"


class TestFormatChapterTime:
    """Tests for chapter time formatting."""

    def test_with_hours(self):
        """Test formatting time with hours."""

        assert _format_chapter_time(5445) == "1:30:45"

    def test_without_hours(self):
        """Test formatting time without hours."""

        assert _format_chapter_time(1647) == "27:27"

    def test_zero(self):
        """Test zero seconds."""

        assert _format_chapter_time(0) == "00:00"


class TestParseChaptersFromMediainfo:
    """Tests for chapter parsing."""

    def test_parses_chapters(self):
        """Test parsing chapters from mediainfo."""

        mediainfo = {
            "media": {
                "track": [
                    {
                        "@type": "Menu",
                        "extra": {
                            "_00_07_35_573": "Chapter 1",
                            "_00_55_52_000": "Chapter 2: Battle",
                            "_01_30_45_200": "Chapter 3: End",
                        },
                    }
                ]
            }
        }

        chapters = _parse_chapters_from_mediainfo(mediainfo)

        assert len(chapters) == 3
        assert chapters[0].start == "07:35"
        assert chapters[0].title == "Chapter 1"
        assert chapters[1].start == "55:52"
        assert chapters[1].title == "Chapter 2: Battle"
        assert chapters[2].start == "1:30:45"
        assert chapters[2].title == "Chapter 3: End"

    def test_no_menu_track(self):
        """Test handling no Menu track."""

        mediainfo = {"media": {"track": [{"@type": "Audio"}]}}

        chapters = _parse_chapters_from_mediainfo(mediainfo)
        assert chapters == []

    def test_empty_mediainfo(self):
        """Test handling empty mediainfo."""

        chapters = _parse_chapters_from_mediainfo({})
        assert chapters == []


class TestExtractAudioInfo:
    """Tests for audio info extraction."""

    def test_extracts_audio_info(self):
        """Test extracting audio info from mediainfo."""

        mediainfo = {
            "media": {
                "track": [
                    {
                        "@type": "General",
                        "Duration": "22260.5",
                        "Format": "MPEG-4",
                        "FileExtension": "M4B",
                    },
                    {
                        "@type": "Audio",
                        "Format": "AAC",
                        "Format_AdditionalFeatures": "LC",
                        "BitRate_Mode": "VBR",
                        "BitRate": "128000",
                        "SamplingRate": "44100",
                        "Channels": "2",
                    },
                ]
            }
        }

        info = _extract_audio_info(mediainfo)

        assert info["container"] == "M4B"
        assert "AAC" in info["codec"]
        assert "LC" in info["codec"]
        assert "VBR" in info["codec"]
        assert "128" in info["codec"]
        assert info["sample_rate"] == "44.1 kHz"
        assert info["channels"] == "2"
        assert "6h" in info["duration_human"]

    def test_default_values(self):
        """Test default values for missing data."""

        info = _extract_audio_info({})

        assert info["container"] == "M4B"
        assert info["codec"] == "AAC LC"
        assert info["sample_rate"] == "44.1 kHz"
        assert info["channels"] == "2"
        assert info["duration_human"] == "Unknown"


class TestCleanHtml:
    """Tests for HTML cleaning."""

    def test_removes_html_tags(self):
        """Test removal of HTML tags."""

        text = "<p>Hello <b>World</b></p>"
        assert _clean_html(text) == "Hello World"

    def test_decodes_entities(self):
        """Test HTML entity decoding."""

        text = "Tom &amp; Jerry &lt;3 &quot;Fun&quot;"
        assert _clean_html(text) == 'Tom & Jerry <3 "Fun"'

    def test_empty_string(self):
        """Test empty string handling."""

        assert _clean_html("") == ""


class TestBuildSeriesList:
    """Tests for series list building."""

    def test_primary_series(self):
        """Test extracting primary series."""

        audnex = {
            "seriesPrimary": {"name": "Epic Series", "position": "3"},
        }

        series = _build_series_list(audnex)

        assert len(series) == 1
        assert series[0]["name"] == "Epic Series"
        assert series[0]["number"] == "3"

    def test_both_series(self):
        """Test extracting both primary and secondary series."""

        audnex = {
            "seriesPrimary": {"name": "Main Series", "position": "1"},
            "seriesSecondary": {"name": "Universe", "position": "5"},
        }

        series = _build_series_list(audnex)

        assert len(series) == 2
        assert series[0]["name"] == "Main Series"
        assert series[1]["name"] == "Universe"

    def test_no_series(self):
        """Test no series data."""

        series = _build_series_list({})
        assert series == []


class TestBuildMamJson:
    """Tests for MAM JSON building."""

    def test_builds_basic_json(self):
        """Test building basic MAM JSON."""
        from mamfast.models import AudiobookRelease

        release = AudiobookRelease(
            title="Test Book",
            author="Test Author",
            asin="B09TEST123",
        )

        audnex = {
            "title": "Test Book",
            "authors": [{"name": "Test Author"}],
            "narrators": [{"name": "Test Narrator"}],
            "language": "english",
        }

        with patch("mamfast.metadata.render_bbcode_description", return_value="Description"):
            result = build_mam_json(release, audnex_data=audnex)

        assert result["title"] == "Test Book"
        assert result["authors"] == ["Test Author"]
        assert result["narrators"] == ["Test Narrator"]
        assert result["language"] == "English"
        assert result["isbn"] == "ASIN:B09TEST123"
        assert result["mediaType"] == 1

    def test_filters_translator_from_authors(self):
        """Test that translators are filtered from authors."""
        from mamfast.models import AudiobookRelease

        release = AudiobookRelease(title="Test Book", asin="B09TEST123")

        audnex = {
            "title": "Test Book",
            "authors": [
                {"name": "Real Author"},
                {"name": "Jane Doe - translator"},
            ],
        }

        with patch("mamfast.metadata.render_bbcode_description", return_value="Description"):
            result = build_mam_json(release, audnex_data=audnex)

        assert result["authors"] == ["Real Author"]

    def test_fallback_to_release_data(self):
        """Test fallback to release data when audnex is empty."""
        from mamfast.models import AudiobookRelease

        release = AudiobookRelease(
            title="Fallback Title",
            author="Fallback Author",
            narrator="Fallback Narrator",
            series="Fallback Series",
            series_position="2",
            asin="B09TEST123",
        )

        with patch("mamfast.metadata.render_bbcode_description", return_value=""):
            result = build_mam_json(release, audnex_data={})

        assert result["title"] == "Fallback Title"
        assert result["authors"] == ["Fallback Author"]
        assert result["narrators"] == ["Fallback Narrator"]
        assert result["series"] == [{"name": "Fallback Series", "number": "2"}]

    def test_builds_tags_string(self):
        """Test building tags string from mediainfo."""
        from mamfast.models import AudiobookRelease

        release = AudiobookRelease(title="Test Book", asin="B09TEST123")

        audnex = {
            "title": "Test Book",
            "releaseDate": "2025-11-25",
        }

        mediainfo = {
            "media": {
                "track": [
                    {"@type": "General", "Duration": "22260"},
                    {
                        "@type": "Audio",
                        "Format": "AAC",
                        "Format_AdditionalFeatures": "LC",
                        "BitRate_Mode": "VBR",
                        "BitRate": "128000",
                    },
                    {
                        "@type": "Menu",
                        "extra": {"_00_00_00_000": "Chapter 1"},
                    },
                ]
            }
        }

        with patch("mamfast.metadata.render_bbcode_description", return_value=""):
            result = build_mam_json(release, audnex_data=audnex, mediainfo_data=mediainfo)

        tags = result.get("tags", "")
        assert "Length:" in tags
        assert "Release date: 11-25-25" in tags
        assert "Format:" in tags
        assert "Chapterized" in tags

    def test_sets_flags(self):
        """Test setting flags for adult content and abridged."""
        from mamfast.models import AudiobookRelease

        release = AudiobookRelease(title="Adult Book", asin="B09TEST123")

        audnex = {
            "title": "Adult Book",
            "isAdult": True,
            "formatType": "Abridged",
        }

        with patch("mamfast.metadata.render_bbcode_description", return_value=""):
            result = build_mam_json(release, audnex_data=audnex)

        assert "eSex" in result.get("flags", [])
        assert "abridged" in result.get("flags", [])

    def test_sets_main_category(self):
        """Test setting main category based on literature type."""
        from mamfast.models import AudiobookRelease

        # Fiction
        release1 = AudiobookRelease(title="Fiction Book", asin="B09TEST123")
        with patch("mamfast.metadata.render_bbcode_description", return_value=""):
            result1 = build_mam_json(release1, audnex_data={"literatureType": "fiction"})
        assert result1.get("main_cat") == 1

        # Non-fiction
        release2 = AudiobookRelease(title="NonFiction Book", asin="B09TEST456")
        with patch("mamfast.metadata.render_bbcode_description", return_value=""):
            result2 = build_mam_json(release2, audnex_data={"literatureType": "non-fiction"})
        assert result2.get("main_cat") == 2


class TestBuildMamJsonCleaning:
    """Tests for MAM JSON cleaning with filter_title and filter_series.

    Phase 3: Verifies that titles, subtitles, and series names are cleaned
    using the naming config rules.
    """

    def _get_mock_settings(self):
        """Create mock settings with NamingConfig for testing cleaning."""
        from mamfast.config import NamingConfig

        mock_settings = MagicMock()
        mock_settings.filters = None
        mock_settings.naming = NamingConfig(
            format_indicators=["(Light Novel)", "Light Novel", "(Unabridged)"],
            genre_tags=["A LitRPG Adventure", "A Progression Fantasy"],
            publisher_tags=["[Yen Audio]"],
            series_suffixes=[r"\s+[Ss]eries$", r"\s+[Tt]rilogy$"],
            preserve_exact=["Re:ZERO"],
            # Subtitle patterns for filter_subtitle
            subtitle_remove_patterns=[r"^[Ll]ight [Nn]ovel$", r"^[Uu]nabridged$"],
            subtitle_keep_patterns=[r".*[Aa]incrad.*"],
        )
        return mock_settings

    def test_title_removes_format_indicators(self):
        """Test that format indicators like (Light Novel) are removed from title."""
        from mamfast.models import AudiobookRelease

        release = AudiobookRelease(title="Test", asin="B09TEST123")
        audnex = {
            "title": "Overlord (Light Novel), Vol. 3",
            "authors": [{"name": "Author"}],
        }

        with (
            patch("mamfast.metadata.render_bbcode_description", return_value=""),
            patch("mamfast.metadata.get_settings", return_value=self._get_mock_settings()),
        ):
            result = build_mam_json(release, audnex_data=audnex)

        # Should remove (Light Novel) but keep Vol. 3
        assert "(Light Novel)" not in result["title"]
        assert "Vol. 3" in result["title"]
        assert "Overlord" in result["title"]

    def test_title_keeps_volume_for_json(self):
        """Test that Vol. X is preserved in MAM JSON titles."""
        from mamfast.models import AudiobookRelease

        release = AudiobookRelease(title="Test", asin="B09TEST123")
        audnex = {
            "title": "Sword Art Online, Vol. 12",
            "authors": [{"name": "Author"}],
        }

        with (
            patch("mamfast.metadata.render_bbcode_description", return_value=""),
            patch("mamfast.metadata.get_settings", return_value=self._get_mock_settings()),
        ):
            result = build_mam_json(release, audnex_data=audnex)

        # Vol. 12 should be preserved for human-readable JSON
        assert "Vol. 12" in result["title"]

    def test_title_removes_genre_tags(self):
        """Test that genre tags like 'A LitRPG Adventure' are removed."""
        from mamfast.models import AudiobookRelease

        release = AudiobookRelease(title="Test", asin="B09TEST123")
        audnex = {
            "title": "Dungeon Crawler Carl: A LitRPG Adventure",
            "authors": [{"name": "Author"}],
        }

        with (
            patch("mamfast.metadata.render_bbcode_description", return_value=""),
            patch("mamfast.metadata.get_settings", return_value=self._get_mock_settings()),
        ):
            result = build_mam_json(release, audnex_data=audnex)

        # Genre tag should be removed
        assert "LitRPG Adventure" not in result["title"]
        assert "Dungeon Crawler Carl" in result["title"]

    def test_subtitle_removes_format_indicators(self):
        """Test that format indicators are removed from subtitle."""
        from mamfast.models import AudiobookRelease

        release = AudiobookRelease(title="Test", asin="B09TEST123")
        audnex = {
            "title": "Test Book",
            "subtitle": "Light Novel",
            "authors": [{"name": "Author"}],
        }

        with (
            patch("mamfast.metadata.render_bbcode_description", return_value=""),
            patch("mamfast.metadata.get_settings", return_value=self._get_mock_settings()),
        ):
            result = build_mam_json(release, audnex_data=audnex)

        # "Light Novel" alone should be removed, so no subtitle
        assert "subtitle" not in result or result.get("subtitle") == ""

    def test_subtitle_keeps_meaningful_content(self):
        """Test that meaningful subtitle content is preserved."""
        from mamfast.models import AudiobookRelease

        release = AudiobookRelease(title="Test", asin="B09TEST123")
        audnex = {
            "title": "Test Book",
            "subtitle": "The Aincrad Arc",
            "authors": [{"name": "Author"}],
        }

        with (
            patch("mamfast.metadata.render_bbcode_description", return_value=""),
            patch("mamfast.metadata.get_settings", return_value=self._get_mock_settings()),
        ):
            result = build_mam_json(release, audnex_data=audnex)

        # Meaningful subtitle should be preserved
        assert result.get("subtitle") == "The Aincrad Arc"

    def test_series_removes_format_indicators(self):
        """Test that format indicators are removed from series names."""
        from mamfast.models import AudiobookRelease

        release = AudiobookRelease(title="Test", asin="B09TEST123")
        audnex = {
            "title": "Test Book",
            "seriesPrimary": {
                "name": "Kuma Kuma Kuma Bear (Light Novel)",
                "position": "1",
            },
            "authors": [{"name": "Author"}],
        }

        with (
            patch("mamfast.metadata.render_bbcode_description", return_value=""),
            patch("mamfast.metadata.get_settings", return_value=self._get_mock_settings()),
        ):
            result = build_mam_json(release, audnex_data=audnex)

        # Should remove (Light Novel) from series
        series_name = result["series"][0]["name"]
        assert "(Light Novel)" not in series_name
        assert "Kuma Kuma Kuma Bear" in series_name

    def test_series_removes_series_suffixes(self):
        """Test that series suffixes like ' Series', ' Trilogy' are removed."""
        from mamfast.models import AudiobookRelease

        release = AudiobookRelease(title="Test", asin="B09TEST123")
        audnex = {
            "title": "Test Book",
            "seriesPrimary": {
                "name": "A Most Unlikely Hero Series",
                "position": "1",
            },
            "authors": [{"name": "Author"}],
        }

        with (
            patch("mamfast.metadata.render_bbcode_description", return_value=""),
            patch("mamfast.metadata.get_settings", return_value=self._get_mock_settings()),
        ):
            result = build_mam_json(release, audnex_data=audnex)

        # Should remove " Series" suffix
        series_name = result["series"][0]["name"]
        assert series_name.endswith("Series") is False
        assert "A Most Unlikely Hero" in series_name

    def test_series_from_release_is_cleaned(self):
        """Test that series from release (not audnex) is also cleaned."""
        from mamfast.models import AudiobookRelease

        release = AudiobookRelease(
            title="Test Book",
            series="Epic Fantasy Trilogy",
            series_position="2",
            asin="B09TEST123",
        )

        with (
            patch("mamfast.metadata.render_bbcode_description", return_value=""),
            patch("mamfast.metadata.get_settings", return_value=self._get_mock_settings()),
        ):
            result = build_mam_json(release, audnex_data={})

        # Should remove " Trilogy" suffix
        series_name = result["series"][0]["name"]
        assert series_name.endswith("Trilogy") is False
        assert "Epic Fantasy" in series_name

    def test_series_removes_volume_but_title_keeps(self):
        """Test that series removes Vol. X while title keeps it."""
        from mamfast.models import AudiobookRelease

        release = AudiobookRelease(title="Test", asin="B09TEST123")
        audnex = {
            "title": "Overlord, Vol. 14",
            "seriesPrimary": {
                "name": "Overlord (Light Novel)",
                "position": "14",
            },
            "authors": [{"name": "Author"}],
        }

        with (
            patch("mamfast.metadata.render_bbcode_description", return_value=""),
            patch("mamfast.metadata.get_settings", return_value=self._get_mock_settings()),
        ):
            result = build_mam_json(release, audnex_data=audnex)

        # Title should keep Vol. 14
        assert "Vol. 14" in result["title"]
        # Series should be clean (no Light Novel, no volume)
        series_name = result["series"][0]["name"]
        assert "(Light Novel)" not in series_name
        assert "Vol." not in series_name


class TestRenderBbcodeDescription:
    """Tests for render_bbcode_description function."""

    def test_renders_basic_description(self):
        """Test rendering basic BBCode description."""
        audnex = {
            "title": "Test Book",
            "summary": "<p>This is a synopsis.</p>",
            "authors": [{"name": "Test Author"}],
            "narrators": [{"name": "Test Narrator"}],
            "publisherName": "Test Publisher",
            "releaseDate": "2025-11-25",
            "genres": [{"name": "Fiction"}],
            "language": "english",
            "asin": "B09TEST123",
        }

        result = render_bbcode_description(audnex)

        assert "Test Book" in result
        assert "synopsis" in result.lower() or "This is a synopsis" in result
        assert "Test Author" in result
        assert "Test Narrator" in result

    def test_handles_subtitle(self):
        """Test handling subtitle in title."""
        audnex = {
            "title": "Main Title",
            "subtitle": "The Subtitle",
            "summary": "Synopsis",
            "authors": [{"name": "Author"}],
        }

        result = render_bbcode_description(audnex)

        # Subtitle should be added to title
        assert "Main Title" in result

    def test_skips_book_pattern_subtitle(self):
        """Test skipping 'Book N' pattern subtitle."""
        audnex = {
            "title": "Series Name",
            "subtitle": "Series Name, Book 1",
            "summary": "Synopsis",
            "authors": [{"name": "Author"}],
        }

        result = render_bbcode_description(audnex)

        # Should not double-add series name
        assert result.count("Series Name") >= 1

    def test_with_mediainfo(self):
        """Test rendering with mediainfo data."""
        audnex = {
            "title": "Test Book",
            "authors": [{"name": "Author"}],
        }
        mediainfo = {
            "media": {
                "track": [
                    {"@type": "General", "Duration": "22260"},
                    {"@type": "Audio", "Format": "AAC", "Channels": "2"},
                ]
            }
        }

        result = render_bbcode_description(audnex, mediainfo_data=mediainfo)

        assert "Test Book" in result

    def test_detects_translator(self):
        """Test translator detection from authors."""
        audnex = {
            "title": "Translated Book",
            "authors": [
                {"name": "Original Author"},
                {"name": "Jane Doe - translator"},
            ],
        }

        result = render_bbcode_description(audnex)

        # Translator should be detected
        assert "Original Author" in result


class TestSaveJson:
    """Tests for JSON saving functions."""

    def test_save_audnex_json(self):
        """Test saving Audnex JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "audnex.json"
            data = {"asin": "B09TEST123", "title": "Test"}

            save_audnex_json(data, output_path)

            assert output_path.exists()
            import json

            with open(output_path) as f:
                saved = json.load(f)
            assert saved["asin"] == "B09TEST123"

    def test_save_mediainfo_json(self):
        """Test saving MediaInfo JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "mediainfo.json"
            data = {"media": {"track": []}}

            save_mediainfo_json(data, output_path)

            assert output_path.exists()

    def test_save_mam_json(self):
        """Test saving MAM JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "mam.json"
            data = {"title": "Test", "authors": ["Author"]}

            save_mam_json(data, output_path)

            assert output_path.exists()
            import json

            with open(output_path) as f:
                saved = json.load(f)
            assert saved["title"] == "Test"


class TestGetMediainfoString:
    """Tests for _get_mediainfo_string function."""

    def test_converts_to_string(self):
        """Test converting mediainfo dict to string."""
        data = {"media": {"track": [{"@type": "General"}]}}

        result = _get_mediainfo_string(data)

        assert result is not None
        assert isinstance(result, str)
        assert "General" in result

    def test_returns_none_for_none(self):
        """Test returning None for None input."""
        result = _get_mediainfo_string(None)
        assert result is None


class TestFetchAudnexEdgeCases:
    """Additional tests for fetch_audnex_book."""

    def test_timeout_error(self):
        """Test handling timeout error."""
        import httpx

        mock_settings = MagicMock()
        mock_settings.audnex.base_url = "https://api.audnex.us"
        mock_settings.audnex.timeout_seconds = 30

        with (
            patch("httpx.Client") as mock_client_class,
            patch("mamfast.metadata.get_settings", return_value=mock_settings),
        ):
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.side_effect = httpx.TimeoutException("Timeout")
            mock_client_class.return_value = mock_client

            result = fetch_audnex_book("B09TEST123")

        assert result is None

    def test_http_error(self):
        """Test handling HTTP status error."""
        import httpx

        mock_settings = MagicMock()
        mock_settings.audnex.base_url = "https://api.audnex.us"
        mock_settings.audnex.timeout_seconds = 30

        with (
            patch("httpx.Client") as mock_client_class,
            patch("mamfast.metadata.get_settings", return_value=mock_settings),
        ):
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)

            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Server Error", request=MagicMock(), response=mock_response
            )
            mock_client.get.return_value = mock_response
            mock_client_class.return_value = mock_client

            result = fetch_audnex_book("B09TEST123")

        assert result is None


class TestRunMediainfoEdgeCases:
    """Additional tests for run_mediainfo."""

    def test_binary_not_found(self):
        """Test handling missing mediainfo binary."""
        mock_settings = MagicMock()
        mock_settings.mediainfo.binary = "/nonexistent/mediainfo"

        with (
            tempfile.NamedTemporaryFile(suffix=".m4b", delete=False) as f,
            patch("subprocess.run", side_effect=FileNotFoundError()),
            patch("mamfast.metadata.get_settings", return_value=mock_settings),
        ):
            result = run_mediainfo(Path(f.name))

        assert result is None

    def test_process_error(self):
        """Test handling subprocess error."""
        import subprocess

        mock_settings = MagicMock()
        mock_settings.mediainfo.binary = "mediainfo"

        with (
            tempfile.NamedTemporaryFile(suffix=".m4b", delete=False) as f,
            patch(
                "subprocess.run",
                side_effect=subprocess.CalledProcessError(1, "mediainfo", stderr="Error"),
            ),
            patch("mamfast.metadata.get_settings", return_value=mock_settings),
        ):
            result = run_mediainfo(Path(f.name))

        assert result is None

    def test_invalid_json_output(self):
        """Test handling invalid JSON output from mediainfo."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not valid json"

        mock_settings = MagicMock()
        mock_settings.mediainfo.binary = "mediainfo"

        with (
            tempfile.NamedTemporaryFile(suffix=".m4b", delete=False) as f,
            patch("subprocess.run", return_value=mock_result),
            patch("mamfast.metadata.get_settings", return_value=mock_settings),
        ):
            result = run_mediainfo(Path(f.name))

        assert result is None


class TestInferFictionOrNonfiction:
    """Tests for _infer_fiction_or_nonfiction function."""

    def test_fantasy_genre_returns_fiction(self):
        """Fantasy genre should return Fiction (1)."""
        from mamfast.metadata import _infer_fiction_or_nonfiction

        data = {"genres": [{"name": "Science Fiction & Fantasy"}, {"name": "Fantasy"}]}
        assert _infer_fiction_or_nonfiction(data) == 1

    def test_fantasy_overrides_wrong_literature_type(self):
        """Genre detection should override incorrect literatureType."""
        from mamfast.metadata import _infer_fiction_or_nonfiction

        data = {
            "literatureType": "nonfiction",  # Wrong!
            "genres": [{"name": "Fantasy"}, {"name": "Action & Adventure"}],
        }
        assert _infer_fiction_or_nonfiction(data) == 1

    def test_biography_returns_nonfiction(self):
        """Biography genre should return Non-Fiction (2)."""
        from mamfast.metadata import _infer_fiction_or_nonfiction

        data = {"genres": [{"name": "Biographies & Memoirs"}, {"name": "History"}]}
        assert _infer_fiction_or_nonfiction(data) == 2

    def test_self_help_returns_nonfiction(self):
        """Self-help genre should return Non-Fiction (2)."""
        from mamfast.metadata import _infer_fiction_or_nonfiction

        data = {"genres": [{"name": "Self-Help"}, {"name": "Personal Development"}]}
        assert _infer_fiction_or_nonfiction(data) == 2

    def test_historical_fiction_returns_fiction(self):
        """Historical fiction should be detected as Fiction."""
        from mamfast.metadata import _infer_fiction_or_nonfiction

        data = {"genres": [{"name": "Historical Fiction"}, {"name": "Romance"}]}
        assert _infer_fiction_or_nonfiction(data) == 1

    def test_fallback_to_literature_type_fiction(self):
        """Falls back to literatureType when genres don't match."""
        from mamfast.metadata import _infer_fiction_or_nonfiction

        data = {"literatureType": "fiction", "genres": [{"name": "Obscure Genre"}]}
        assert _infer_fiction_or_nonfiction(data) == 1

    def test_fallback_to_literature_type_nonfiction(self):
        """Falls back to literatureType when genres don't match."""
        from mamfast.metadata import _infer_fiction_or_nonfiction

        data = {"literatureType": "nonfiction", "genres": [{"name": "Obscure Genre"}]}
        assert _infer_fiction_or_nonfiction(data) == 2

    def test_empty_genres_defaults_to_fiction(self):
        """Defaults to Fiction when no genres or literatureType."""
        from mamfast.metadata import _infer_fiction_or_nonfiction

        data = {"genres": []}
        assert _infer_fiction_or_nonfiction(data) == 1

    def test_missing_genres_defaults_to_fiction(self):
        """Defaults to Fiction when genres key is missing."""
        from mamfast.metadata import _infer_fiction_or_nonfiction

        data = {}
        assert _infer_fiction_or_nonfiction(data) == 1

    def test_science_fiction_not_confused_with_science(self):
        """'Science fiction' should be detected as fiction, not non-fiction."""
        from mamfast.metadata import _infer_fiction_or_nonfiction

        data = {"genres": [{"name": "Science Fiction"}]}
        assert _infer_fiction_or_nonfiction(data) == 1

    def test_word_boundary_matching(self):
        """Word boundary matching should avoid false positives."""
        from mamfast.metadata import _infer_fiction_or_nonfiction

        # "urban" shouldn't match in "Suburban Life"
        data = {"genres": [{"name": "Suburban Life"}]}
        # This should fall back to default (fiction) since no keywords match
        assert _infer_fiction_or_nonfiction(data) == 1


class TestGetAudiobookCategory:
    """Tests for _get_audiobook_category function."""

    def test_fantasy_genre_returns_fantasy_category(self):
        """Fantasy genre should map to 'Audiobooks - Fantasy'."""
        from mamfast.metadata import _get_audiobook_category

        mock_settings = MagicMock()
        mock_settings.categories.audiobook_fiction_map = {
            "fantasy": "Audiobooks - Fantasy",
        }
        mock_settings.categories.audiobook_defaults = {"fiction": "Audiobooks - General Fiction"}

        with patch("mamfast.metadata.get_settings", return_value=mock_settings):
            data = {"genres": [{"name": "Fantasy"}]}
            result = _get_audiobook_category(data, is_fiction=True)

        assert result == "Audiobooks - Fantasy"

    def test_biography_genre_returns_biographical_category(self):
        """Biography genre should map to 'Audiobooks - Biographical'."""
        from mamfast.metadata import _get_audiobook_category

        mock_settings = MagicMock()
        mock_settings.categories.audiobook_nonfiction_map = {
            "biography": "Audiobooks - Biographical",
        }
        mock_settings.categories.audiobook_defaults = {"nonfiction": "Audiobooks - General Non-Fic"}

        with patch("mamfast.metadata.get_settings", return_value=mock_settings):
            data = {"genres": [{"name": "Biography"}]}
            result = _get_audiobook_category(data, is_fiction=False)

        assert result == "Audiobooks - Biographical"

    def test_first_match_wins(self):
        """First matching keyword in the map should win."""
        from mamfast.metadata import _get_audiobook_category

        mock_settings = MagicMock()
        mock_settings.categories.audiobook_fiction_map = {
            "horror": "Audiobooks - Horror",
            "thriller": "Audiobooks - Crime/Thriller",
        }
        mock_settings.categories.audiobook_defaults = {"fiction": "Audiobooks - General Fiction"}

        with patch("mamfast.metadata.get_settings", return_value=mock_settings):
            # Horror should win because it comes first in the map
            data = {"genres": [{"name": "Horror"}, {"name": "Thriller"}]}
            result = _get_audiobook_category(data, is_fiction=True)

        assert result == "Audiobooks - Horror"

    def test_fallback_to_default_fiction(self):
        """Falls back to default when no keywords match."""
        from mamfast.metadata import _get_audiobook_category

        mock_settings = MagicMock()
        mock_settings.categories.audiobook_fiction_map = {
            "fantasy": "Audiobooks - Fantasy",
        }
        mock_settings.categories.audiobook_defaults = {"fiction": "Audiobooks - General Fiction"}

        with patch("mamfast.metadata.get_settings", return_value=mock_settings):
            data = {"genres": [{"name": "Obscure Genre"}]}
            result = _get_audiobook_category(data, is_fiction=True)

        assert result == "Audiobooks - General Fiction"

    def test_fallback_to_default_nonfiction(self):
        """Falls back to default when no keywords match."""
        from mamfast.metadata import _get_audiobook_category

        mock_settings = MagicMock()
        mock_settings.categories.audiobook_nonfiction_map = {
            "biography": "Audiobooks - Biographical",
        }
        mock_settings.categories.audiobook_defaults = {"nonfiction": "Audiobooks - General Non-Fic"}

        with patch("mamfast.metadata.get_settings", return_value=mock_settings):
            data = {"genres": [{"name": "Obscure Genre"}]}
            result = _get_audiobook_category(data, is_fiction=False)

        assert result == "Audiobooks - General Non-Fic"

    def test_empty_map_returns_default(self):
        """Returns default when category map is empty."""
        from mamfast.metadata import _get_audiobook_category

        mock_settings = MagicMock()
        mock_settings.categories.audiobook_fiction_map = {}
        mock_settings.categories.audiobook_defaults = {"fiction": "Audiobooks - General Fiction"}

        with patch("mamfast.metadata.get_settings", return_value=mock_settings):
            data = {"genres": [{"name": "Fantasy"}]}
            result = _get_audiobook_category(data, is_fiction=True)

        assert result == "Audiobooks - General Fiction"

    def test_hardcoded_default_when_not_in_config(self):
        """Uses hardcoded default when not in config defaults."""
        from mamfast.metadata import _get_audiobook_category

        mock_settings = MagicMock()
        mock_settings.categories.audiobook_fiction_map = {}
        mock_settings.categories.audiobook_defaults = {}  # Empty!

        with patch("mamfast.metadata.get_settings", return_value=mock_settings):
            data = {"genres": [{"name": "Fantasy"}]}
            result = _get_audiobook_category(data, is_fiction=True)

        assert result == "Audiobooks - General Fiction"


class TestBuildMamJsonCategory:
    """Tests for category field in build_mam_json."""

    def test_category_field_included(self):
        """build_mam_json should include category field."""
        from mamfast.models import AudiobookRelease

        mock_settings = MagicMock()
        mock_settings.categories.genre_map = {}
        mock_settings.categories.audiobook_fiction_map = {"fantasy": "Audiobooks - Fantasy"}
        mock_settings.categories.audiobook_nonfiction_map = {}
        mock_settings.categories.audiobook_defaults = {"fiction": "Audiobooks - General Fiction"}

        release = AudiobookRelease(
            asin="B09TEST123",
            title="Test Book",
        )

        audnex_data = {
            "title": "Test Book",
            "genres": [{"name": "Fantasy"}],
        }

        with patch("mamfast.metadata.get_settings", return_value=mock_settings):
            result = build_mam_json(release, audnex_data=audnex_data)

        assert "category" in result
        assert result["category"] == "Audiobooks - Fantasy"
        assert result["main_cat"] == 1  # Fiction
