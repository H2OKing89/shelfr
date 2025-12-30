"""Tests for metadata module."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from shelfr.metadata import (
    AudioFormat,
    _build_series_list,
    _clean_html,
    _extract_audio_info,
    _format_chapter_time,
    _format_duration,
    _get_mediainfo_string,
    _html_to_bbcode,
    _map_genres_to_categories,
    _parse_chapters_from_mediainfo,
    build_mam_json,
    detect_audio_format,
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
        mock_settings.audnex.regions = ["us"]

        with (
            patch("httpx.Client", return_value=mock_client),
            patch("shelfr.metadata.get_settings", return_value=mock_settings),
        ):
            result, region = fetch_audnex_book("B09TEST123")

        assert result is not None
        assert result["asin"] == "B09TEST123"
        assert result["title"] == "Test Book"
        assert region == "us"

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
        mock_settings.audnex.regions = ["us"]

        with (
            patch("httpx.Client", return_value=mock_client),
            patch("shelfr.metadata.get_settings", return_value=mock_settings),
        ):
            result, region = fetch_audnex_book("INVALID_ASIN")

        assert result is None
        assert region is None

    def test_region_fallback(self):
        """Test fallback to second region when first returns 500."""
        mock_settings = MagicMock()
        mock_settings.audnex.base_url = "https://api.audnex.us"
        mock_settings.audnex.timeout_seconds = 30
        mock_settings.audnex.regions = ["uk", "us"]  # UK first, US second

        call_count = 0

        def mock_get(url, params=None):
            nonlocal call_count
            call_count += 1
            response = MagicMock()

            if params and params.get("region") == "uk":
                # First region fails with 500
                response.status_code = 500
                return response
            else:
                # Second region succeeds
                response.status_code = 200
                response.json.return_value = {
                    "asin": "B09TEST123",
                    "title": "Test Book",
                }
                return response

        mock_client = MagicMock()
        mock_client.get = mock_get
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with (
            patch("httpx.Client", return_value=mock_client),
            patch("shelfr.metadata.get_settings", return_value=mock_settings),
        ):
            result, region = fetch_audnex_book("B09TEST123")

        assert result is not None
        assert result["asin"] == "B09TEST123"
        assert call_count == 2  # Both regions tried
        assert region == "us"  # Found in US region

    def test_specific_region_no_fallback(self):
        """Test that specifying region skips fallback."""
        mock_settings = MagicMock()
        mock_settings.audnex.base_url = "https://api.audnex.us"
        mock_settings.audnex.timeout_seconds = 30
        mock_settings.audnex.regions = ["us", "uk"]

        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with (
            patch("httpx.Client", return_value=mock_client),
            patch("shelfr.metadata.get_settings", return_value=mock_settings),
        ):
            result, region = fetch_audnex_book("B09TEST123", region="uk")

        assert result is None
        assert region is None
        # Only called once (no fallback to other regions)
        assert mock_client.get.call_count == 1


class TestFetchAudnexAuthor:
    """Tests for Audnex author API integration."""

    def test_fetch_author_success(self):
        """Test successful author fetch."""
        from shelfr.metadata import fetch_audnex_author

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "asin": "B001H6KJPW",
            "name": "Brandon Sanderson",
        }

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()
        mock_settings.audnex.base_url = "https://api.audnex.us"
        mock_settings.audnex.timeout_seconds = 30
        mock_settings.audnex.regions = ["us"]

        with (
            patch("httpx.Client", return_value=mock_client),
            patch("shelfr.metadata.get_settings", return_value=mock_settings),
        ):
            result = fetch_audnex_author("B001H6KJPW")

        assert result is not None
        assert result["name"] == "Brandon Sanderson"

    def test_fetch_author_not_found(self):
        """Test handling 404 response for author."""
        from shelfr.metadata import fetch_audnex_author

        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()
        mock_settings.audnex.base_url = "https://api.audnex.us"
        mock_settings.audnex.timeout_seconds = 30
        mock_settings.audnex.regions = ["us"]

        with (
            patch("httpx.Client", return_value=mock_client),
            patch("shelfr.metadata.get_settings", return_value=mock_settings),
        ):
            result = fetch_audnex_author("INVALID_ASIN")

        assert result is None

    def test_fetch_author_timeout(self):
        """Test that timeout returns None and logs warning."""
        import httpx

        from shelfr.metadata import fetch_audnex_author

        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.TimeoutException("Connection timed out")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()
        mock_settings.audnex.base_url = "https://api.audnex.us"
        mock_settings.audnex.timeout_seconds = 30
        mock_settings.audnex.regions = ["us"]

        with (
            patch("httpx.Client", return_value=mock_client),
            patch("shelfr.metadata.get_settings", return_value=mock_settings),
        ):
            result = fetch_audnex_author("B001H6KJPW")

        assert result is None

    def test_fetch_author_json_decode_error(self):
        """Test that JSON decode error returns None (catch-all exception)."""
        from shelfr.metadata import fetch_audnex_author

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()
        mock_settings.audnex.base_url = "https://api.audnex.us"
        mock_settings.audnex.timeout_seconds = 30
        mock_settings.audnex.regions = ["us"]

        with (
            patch("httpx.Client", return_value=mock_client),
            patch("shelfr.metadata.get_settings", return_value=mock_settings),
        ):
            result = fetch_audnex_author("B001H6KJPW")

        # Should return None, not raise exception
        assert result is None

    def test_fetch_author_rate_limit(self):
        """Test that 429 rate limit returns None."""
        import httpx

        from shelfr.metadata import fetch_audnex_author

        mock_response = MagicMock()
        mock_response.status_code = 429

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        # Make raise_for_status raise HTTPStatusError for 429
        error_response = MagicMock()
        error_response.status_code = 429
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Rate limited", request=MagicMock(), response=error_response
        )

        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()
        mock_settings.audnex.base_url = "https://api.audnex.us"
        mock_settings.audnex.timeout_seconds = 30
        mock_settings.audnex.regions = ["us"]

        with (
            patch("httpx.Client", return_value=mock_client),
            patch("shelfr.metadata.get_settings", return_value=mock_settings),
        ):
            result = fetch_audnex_author("B001H6KJPW")

        assert result is None


class TestFetchAudnexChapters:
    """Tests for Audnex chapters API integration."""

    def test_fetch_chapters_success(self):
        """Test successful chapters fetch."""
        from shelfr.metadata import fetch_audnex_chapters

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
        mock_settings.audnex.regions = ["us"]

        with (
            patch("httpx.Client", return_value=mock_client),
            patch("shelfr.metadata.get_settings", return_value=mock_settings),
        ):
            result = fetch_audnex_chapters("B09TEST123")

        assert result is not None
        assert result["asin"] == "B09TEST123"
        assert result["runtimeLengthSec"] == 25050
        assert len(result["chapters"]) == 2
        assert result["chapters"][0]["title"] == "Opening Credits"

    def test_fetch_chapters_not_found(self):
        """Test handling 404 response for chapters."""
        from shelfr.metadata import fetch_audnex_chapters

        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()
        mock_settings.audnex.base_url = "https://api.audnex.us"
        mock_settings.audnex.timeout_seconds = 30
        mock_settings.audnex.regions = ["us"]

        with (
            patch("httpx.Client", return_value=mock_client),
            patch("shelfr.metadata.get_settings", return_value=mock_settings),
        ):
            result = fetch_audnex_chapters("INVALID_ASIN")

        assert result is None

    """Tests for parsing Audnex chapters response."""

    def test_parse_chapters(self):
        """Test parsing chapters from Audnex response."""
        from shelfr.metadata import _parse_chapters_from_audnex

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
        from shelfr.metadata import _parse_chapters_from_audnex

        result = _parse_chapters_from_audnex({"chapters": []})
        assert result == []

    def test_parse_no_chapters_key(self):
        """Test parsing response without chapters key."""
        from shelfr.metadata import _parse_chapters_from_audnex

        result = _parse_chapters_from_audnex({})
        assert result == []


class TestRunMediainfo:
    """Tests for mediainfo integration."""

    def test_run_mediainfo_file_not_found(self):
        """Test handling missing file."""
        mock_settings = MagicMock()
        mock_settings.mediainfo.binary = "mediainfo"

        with patch("shelfr.metadata.get_settings", return_value=mock_settings):
            result = run_mediainfo(Path("/nonexistent/file.m4b"))

        assert result is None

    def test_run_mediainfo_success(self, tmp_path: Path):
        """Test successful mediainfo extraction."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"media": {"track": [{"@type": "Audio"}]}}'

        mock_settings = MagicMock()
        mock_settings.mediainfo.binary = "mediainfo"

        # Create a temp file
        temp_path = tmp_path / "test.m4b"
        temp_path.write_bytes(b"fake audio data")

        with (
            patch("subprocess.run", return_value=mock_result),
            patch("shelfr.metadata.get_settings", return_value=mock_settings),
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


class TestHtmlToBbcode:
    """Tests for HTML to BBCode conversion."""

    def test_converts_bold_tags(self):
        """Test bold tag conversion to BBCode."""
        text = "<p><b>Bold text</b></p>"
        result = _html_to_bbcode(text)
        assert "[b]Bold text[/b]" in result

    def test_converts_strong_tags(self):
        """Test strong tag conversion to BBCode."""
        text = "<strong>Strong text</strong>"
        result = _html_to_bbcode(text)
        assert "[b]Strong text[/b]" in result

    def test_converts_italic_tags(self):
        """Test italic tag conversion to BBCode."""
        text = "<p>Read <i>New York Times</i> bestseller</p>"
        result = _html_to_bbcode(text)
        assert "Read [i]New York Times[/i] bestseller" in result

    def test_converts_em_tags(self):
        """Test em tag conversion to BBCode."""
        text = "<em>Emphasized text</em>"
        result = _html_to_bbcode(text)
        assert "[i]Emphasized text[/i]" in result

    def test_converts_underline_tags(self):
        """Test underline tag conversion to BBCode."""
        text = "<u>Underlined text</u>"
        result = _html_to_bbcode(text)
        assert "[u]Underlined text[/u]" in result

    def test_converts_strikethrough_tags(self):
        """Test strikethrough tag conversion to BBCode."""
        text = "<s>Struck text</s>"
        result = _html_to_bbcode(text)
        assert "[s]Struck text[/s]" in result

    def test_converts_strike_tags(self):
        """Test strike tag conversion to BBCode."""
        text = "<strike>Old text</strike>"
        result = _html_to_bbcode(text)
        assert "[s]Old text[/s]" in result

    def test_converts_br_to_bbcode_br(self):
        """Test br tag conversion to [br] tag for MAM."""
        text = "Line one<br>Line two<br/>Line three"
        result = _html_to_bbcode(text)
        assert "Line one[br]Line two[br]Line three" in result

    def test_converts_paragraphs_to_br_tags(self):
        """Test paragraph conversion to [br][br] for MAM."""
        text = "<p>First paragraph.</p><p>Second paragraph.</p>"
        result = _html_to_bbcode(text)
        assert "First paragraph." in result
        assert "Second paragraph." in result
        # Should have [br][br] between paragraphs
        assert "[br][br]" in result

    def test_nested_formatting(self):
        """Test nested bold and italic."""
        text = "<p><b><i>New York Times</i></b> bestseller</p>"
        result = _html_to_bbcode(text)
        assert "[b][i]New York Times[/i][/b] bestseller" in result

    def test_complex_html_like_audnex(self):
        """Test complex HTML like from Audnex API."""
        text = (
            "<p><b>A teenager becomes a romantic hero in an "
            "artificial-reality school full of supernatural secrets.</b></p> "
            "<p>Leonard Dunning wakes up in a home he doesn't remember.</p> "
            "<p>Now, two girls have set their romantic sights on <i>him</i>.</p>"
        )
        result = _html_to_bbcode(text)
        # Bold should be preserved
        assert "[b]A teenager becomes a romantic hero" in result
        # Italic should be preserved
        assert "[i]him[/i]" in result
        # Paragraphs should create newlines
        assert "Leonard Dunning" in result

    def test_decodes_html_entities(self):
        """Test HTML entity decoding."""
        text = "<p>Tom &amp; Jerry &lt;3 &quot;Fun&quot;</p>"
        result = _html_to_bbcode(text)
        assert 'Tom & Jerry <3 "Fun"' in result

    def test_empty_string(self):
        """Test empty string handling."""
        assert _html_to_bbcode("") == ""

    def test_removes_unsupported_tags(self):
        """Test that unsupported tags are stripped."""
        text = "<p><span class='test'>Text</span> with <div>nested</div> tags</p>"
        result = _html_to_bbcode(text)
        assert "<span" not in result
        assert "<div" not in result
        assert "Text" in result
        assert "nested" in result


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

    def test_deduplicates_order_variants(self):
        """Test that order variants become one entry after cleaning.

        Audnex often provides both seriesPrimary and seriesSecondary with
        order suffixes like [publication order] vs [chronological order].
        After cleaning, these become identical and should be deduplicated.
        """
        from shelfr.config import NamingConfig

        config = NamingConfig(
            series_suffixes=[r"\s*\[[^\]]*[Oo]rder\]$"],  # Pattern from naming.json
        )

        audnex = {
            "seriesPrimary": {"name": "Ascend Online [publication order]", "position": "1"},
            "seriesSecondary": {"name": "Ascend Online [chronological order]", "position": "1"},
        }

        series = _build_series_list(audnex, naming_config=config)

        # Should deduplicate: both clean to "Ascend Online"
        assert len(series) == 1
        assert series[0]["name"] == "Ascend Online"
        assert series[0]["number"] == "1"

    def test_keeps_distinct_series(self):
        """Test that genuinely different series are preserved."""
        from shelfr.config import NamingConfig

        config = NamingConfig(
            series_suffixes=[r"\s*\[[^\]]*[Oo]rder\]$"],
        )

        audnex = {
            "seriesPrimary": {"name": "Ascend Online [publication order]", "position": "1"},
            "seriesSecondary": {"name": "Epic LitRPG Universe", "position": "5"},
        }

        series = _build_series_list(audnex, naming_config=config)

        # Both should be kept: they're genuinely different
        assert len(series) == 2
        assert series[0]["name"] == "Ascend Online"
        assert series[0]["number"] == "1"
        assert series[1]["name"] == "Epic LitRPG Universe"
        assert series[1]["number"] == "5"


class TestBuildMamJson:
    """Tests for MAM JSON building."""

    def test_builds_basic_json(self):
        """Test building basic MAM JSON."""
        from shelfr.models import AudiobookRelease

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

        with patch("shelfr.metadata.render_bbcode_description", return_value="Description"):
            result = build_mam_json(release, audnex_data=audnex)

        assert result["title"] == "Test Book"
        assert result["authors"] == ["Test Author"]
        assert result["narrators"] == ["Test Narrator"]
        assert result["language"] == "English"
        assert result["isbn"] == "ASIN:B09TEST123"
        assert result["mediaType"] == 1

    def test_filters_translator_from_authors(self):
        """Test that translators are filtered from authors."""
        from shelfr.models import AudiobookRelease

        release = AudiobookRelease(title="Test Book", asin="B09TEST123")

        audnex = {
            "title": "Test Book",
            "authors": [
                {"name": "Real Author"},
                {"name": "Jane Doe - translator"},
            ],
        }

        with patch("shelfr.metadata.render_bbcode_description", return_value="Description"):
            result = build_mam_json(release, audnex_data=audnex)

        assert result["authors"] == ["Real Author"]

    def test_fallback_to_release_data(self):
        """Test fallback to release data when audnex is empty."""
        from shelfr.models import AudiobookRelease

        release = AudiobookRelease(
            title="Fallback Title",
            author="Fallback Author",
            narrator="Fallback Narrator",
            series="Fallback Series",
            series_position="2",
            asin="B09TEST123",
        )

        with patch("shelfr.metadata.render_bbcode_description", return_value=""):
            result = build_mam_json(release, audnex_data={})

        assert result["title"] == "Fallback Title"
        assert result["authors"] == ["Fallback Author"]
        assert result["narrators"] == ["Fallback Narrator"]
        assert result["series"] == [{"name": "Fallback Series", "number": "2"}]

    def test_builds_tags_string(self):
        """Test building tags string from mediainfo."""
        from shelfr.models import AudiobookRelease

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

        with patch("shelfr.metadata.render_bbcode_description", return_value=""):
            result = build_mam_json(release, audnex_data=audnex, mediainfo_data=mediainfo)

        tags = result.get("tags", "")
        assert "Length:" in tags
        assert "Release date: 11-25-25" in tags
        assert "Format:" in tags
        assert "Chapterized" in tags

    def test_sets_flags(self):
        """Test setting flags for adult content and abridged."""
        from shelfr.models import AudiobookRelease

        release = AudiobookRelease(title="Adult Book", asin="B09TEST123")

        audnex = {
            "title": "Adult Book",
            "isAdult": True,
            "formatType": "Abridged",
        }

        with patch("shelfr.metadata.render_bbcode_description", return_value=""):
            result = build_mam_json(release, audnex_data=audnex)

        assert "eSex" in result.get("flags", [])
        assert "abridged" in result.get("flags", [])

    def test_sets_main_category(self):
        """Test setting main category based on literature type."""
        from shelfr.models import AudiobookRelease

        # Fiction
        release1 = AudiobookRelease(title="Fiction Book", asin="B09TEST123")
        with patch("shelfr.metadata.render_bbcode_description", return_value=""):
            result1 = build_mam_json(release1, audnex_data={"literatureType": "fiction"})
        assert result1.get("main_cat") == 1

        # Non-fiction
        release2 = AudiobookRelease(title="NonFiction Book", asin="B09TEST456")
        with patch("shelfr.metadata.render_bbcode_description", return_value=""):
            result2 = build_mam_json(release2, audnex_data={"literatureType": "non-fiction"})
        assert result2.get("main_cat") == 2


class TestBuildMamJsonCleaning:
    """Tests for MAM JSON cleaning with filter_title and filter_series.

    Phase 3: Verifies that titles, subtitles, and series names are cleaned
    using the naming config rules.
    """

    def _get_mock_settings(self):
        """Create mock settings with NamingConfig for testing cleaning."""
        from shelfr.config import NamingConfig

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
        from shelfr.models import AudiobookRelease

        release = AudiobookRelease(title="Test", asin="B09TEST123")
        audnex = {
            "title": "Overlord (Light Novel), Vol. 3",
            "authors": [{"name": "Author"}],
        }

        with (
            patch("shelfr.metadata.render_bbcode_description", return_value=""),
            patch("shelfr.metadata.get_settings", return_value=self._get_mock_settings()),
        ):
            result = build_mam_json(release, audnex_data=audnex)

        # Should remove (Light Novel) but keep Vol. 3
        assert "(Light Novel)" not in result["title"]
        assert "Vol. 3" in result["title"]
        assert "Overlord" in result["title"]

    def test_title_keeps_volume_for_json(self):
        """Test that Vol. X is preserved in MAM JSON titles."""
        from shelfr.models import AudiobookRelease

        release = AudiobookRelease(title="Test", asin="B09TEST123")
        audnex = {
            "title": "Sword Art Online, Vol. 12",
            "authors": [{"name": "Author"}],
        }

        with (
            patch("shelfr.metadata.render_bbcode_description", return_value=""),
            patch("shelfr.metadata.get_settings", return_value=self._get_mock_settings()),
        ):
            result = build_mam_json(release, audnex_data=audnex)

        # Vol. 12 should be preserved for human-readable JSON
        assert "Vol. 12" in result["title"]

    def test_title_removes_genre_tags(self):
        """Test that genre tags like 'A LitRPG Adventure' are removed."""
        from shelfr.models import AudiobookRelease

        release = AudiobookRelease(title="Test", asin="B09TEST123")
        audnex = {
            "title": "Dungeon Crawler Carl: A LitRPG Adventure",
            "authors": [{"name": "Author"}],
        }

        with (
            patch("shelfr.metadata.render_bbcode_description", return_value=""),
            patch("shelfr.metadata.get_settings", return_value=self._get_mock_settings()),
        ):
            result = build_mam_json(release, audnex_data=audnex)

        # Genre tag should be removed
        assert "LitRPG Adventure" not in result["title"]
        assert "Dungeon Crawler Carl" in result["title"]

    def test_subtitle_removes_format_indicators(self):
        """Test that format indicators are removed from subtitle."""
        from shelfr.models import AudiobookRelease

        release = AudiobookRelease(title="Test", asin="B09TEST123")
        audnex = {
            "title": "Test Book",
            "subtitle": "Light Novel",
            "authors": [{"name": "Author"}],
        }

        with (
            patch("shelfr.metadata.render_bbcode_description", return_value=""),
            patch("shelfr.metadata.get_settings", return_value=self._get_mock_settings()),
        ):
            result = build_mam_json(release, audnex_data=audnex)

        # "Light Novel" alone should be removed, so no subtitle
        assert "subtitle" not in result or result.get("subtitle") == ""

    def test_subtitle_keeps_meaningful_content(self):
        """Test that meaningful subtitle content is preserved."""
        from shelfr.models import AudiobookRelease

        release = AudiobookRelease(title="Test", asin="B09TEST123")
        audnex = {
            "title": "Test Book",
            "subtitle": "The Aincrad Arc",
            "authors": [{"name": "Author"}],
        }

        with (
            patch("shelfr.metadata.render_bbcode_description", return_value=""),
            patch("shelfr.metadata.get_settings", return_value=self._get_mock_settings()),
        ):
            result = build_mam_json(release, audnex_data=audnex)

        # Meaningful subtitle should be preserved
        assert result.get("subtitle") == "The Aincrad Arc"

    def test_series_removes_format_indicators(self):
        """Test that format indicators are removed from series names."""
        from shelfr.models import AudiobookRelease

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
            patch("shelfr.metadata.render_bbcode_description", return_value=""),
            patch("shelfr.metadata.get_settings", return_value=self._get_mock_settings()),
        ):
            result = build_mam_json(release, audnex_data=audnex)

        # Should remove (Light Novel) from series
        series_name = result["series"][0]["name"]
        assert "(Light Novel)" not in series_name
        assert "Kuma Kuma Kuma Bear" in series_name

    def test_series_removes_series_suffixes(self):
        """Test that series suffixes like ' Series', ' Trilogy' are removed."""
        from shelfr.models import AudiobookRelease

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
            patch("shelfr.metadata.render_bbcode_description", return_value=""),
            patch("shelfr.metadata.get_settings", return_value=self._get_mock_settings()),
        ):
            result = build_mam_json(release, audnex_data=audnex)

        # Should remove " Series" suffix
        series_name = result["series"][0]["name"]
        assert series_name.endswith("Series") is False
        assert "A Most Unlikely Hero" in series_name

    def test_series_from_release_is_cleaned(self):
        """Test that series from release (not audnex) is also cleaned."""
        from shelfr.models import AudiobookRelease

        release = AudiobookRelease(
            title="Test Book",
            series="Epic Fantasy Trilogy",
            series_position="2",
            asin="B09TEST123",
        )

        with (
            patch("shelfr.metadata.render_bbcode_description", return_value=""),
            patch("shelfr.metadata.get_settings", return_value=self._get_mock_settings()),
        ):
            result = build_mam_json(release, audnex_data={})

        # Should remove " Trilogy" suffix
        series_name = result["series"][0]["name"]
        assert series_name.endswith("Trilogy") is False
        assert "Epic Fantasy" in series_name

    def test_series_removes_volume_but_title_keeps(self):
        """Test that series removes Vol. X while title keeps it."""
        from shelfr.models import AudiobookRelease

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
            patch("shelfr.metadata.render_bbcode_description", return_value=""),
            patch("shelfr.metadata.get_settings", return_value=self._get_mock_settings()),
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

            # Mock settings for permission fixing
            mock_settings = MagicMock()
            mock_settings.target_uid = 99
            mock_settings.target_gid = 100

            with (
                patch("shelfr.metadata.get_settings", return_value=mock_settings),
                patch("shelfr.metadata.fix_ownership") as mock_fix,
            ):
                save_mam_json(data, output_path)

                # Verify fix_ownership was called with correct args
                mock_fix.assert_called_once_with(output_path, 99, 100)

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
        mock_settings.audnex.regions = ["us"]

        with (
            patch("httpx.Client") as mock_client_class,
            patch("shelfr.metadata.get_settings", return_value=mock_settings),
        ):
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.side_effect = httpx.TimeoutException("Timeout")
            mock_client_class.return_value = mock_client

            result, region = fetch_audnex_book("B09TEST123")

        assert result is None
        assert region is None

    def test_http_error(self):
        """Test handling HTTP status error."""
        import httpx

        mock_settings = MagicMock()
        mock_settings.audnex.base_url = "https://api.audnex.us"
        mock_settings.audnex.timeout_seconds = 30
        mock_settings.audnex.regions = ["us"]

        with (
            patch("httpx.Client") as mock_client_class,
            patch("shelfr.metadata.get_settings", return_value=mock_settings),
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

            result, region = fetch_audnex_book("B09TEST123")

        assert result is None
        assert region is None


class TestRunMediainfoEdgeCases:
    """Additional tests for run_mediainfo."""

    def test_binary_not_found(self, tmp_path: Path):
        """Test handling missing mediainfo binary."""
        mock_settings = MagicMock()
        mock_settings.mediainfo.binary = "/nonexistent/mediainfo"

        temp_file = tmp_path / "test.m4b"
        temp_file.write_bytes(b"fake")

        with (
            patch("subprocess.run", side_effect=FileNotFoundError()),
            patch("shelfr.metadata.get_settings", return_value=mock_settings),
        ):
            result = run_mediainfo(temp_file)

        assert result is None

    def test_process_error(self, tmp_path: Path):
        """Test handling subprocess error."""
        import subprocess

        mock_settings = MagicMock()
        mock_settings.mediainfo.binary = "mediainfo"

        temp_file = tmp_path / "test.m4b"
        temp_file.write_bytes(b"fake")

        with (
            patch(
                "subprocess.run",
                side_effect=subprocess.CalledProcessError(1, "mediainfo", stderr="Error"),
            ),
            patch("shelfr.metadata.get_settings", return_value=mock_settings),
        ):
            result = run_mediainfo(temp_file)

        assert result is None

    def test_invalid_json_output(self, tmp_path: Path):
        """Test handling invalid JSON output from mediainfo."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not valid json"

        mock_settings = MagicMock()
        mock_settings.mediainfo.binary = "mediainfo"

        temp_file = tmp_path / "test.m4b"
        temp_file.write_bytes(b"fake")

        with (
            patch("subprocess.run", return_value=mock_result),
            patch("shelfr.metadata.get_settings", return_value=mock_settings),
        ):
            result = run_mediainfo(temp_file)

        assert result is None


class TestInferFictionOrNonfiction:
    """Tests for _infer_fiction_or_nonfiction function."""

    def test_fantasy_genre_returns_fiction(self):
        """Fantasy genre should return Fiction (1)."""
        from shelfr.metadata import _infer_fiction_or_nonfiction

        data = {"genres": [{"name": "Science Fiction & Fantasy"}, {"name": "Fantasy"}]}
        assert _infer_fiction_or_nonfiction(data) == 1

    def test_fantasy_overrides_wrong_literature_type(self):
        """Genre detection should override incorrect literatureType."""
        from shelfr.metadata import _infer_fiction_or_nonfiction

        data = {
            "literatureType": "nonfiction",  # Wrong!
            "genres": [{"name": "Fantasy"}, {"name": "Action & Adventure"}],
        }
        assert _infer_fiction_or_nonfiction(data) == 1

    def test_biography_returns_nonfiction(self):
        """Biography genre should return Non-Fiction (2)."""
        from shelfr.metadata import _infer_fiction_or_nonfiction

        data = {"genres": [{"name": "Biographies & Memoirs"}, {"name": "History"}]}
        assert _infer_fiction_or_nonfiction(data) == 2

    def test_self_help_returns_nonfiction(self):
        """Self-help genre should return Non-Fiction (2)."""
        from shelfr.metadata import _infer_fiction_or_nonfiction

        data = {"genres": [{"name": "Self-Help"}, {"name": "Personal Development"}]}
        assert _infer_fiction_or_nonfiction(data) == 2

    def test_historical_fiction_returns_fiction(self):
        """Historical fiction should be detected as Fiction."""
        from shelfr.metadata import _infer_fiction_or_nonfiction

        data = {"genres": [{"name": "Historical Fiction"}, {"name": "Romance"}]}
        assert _infer_fiction_or_nonfiction(data) == 1

    def test_fallback_to_literature_type_fiction(self):
        """Falls back to literatureType when genres don't match."""
        from shelfr.metadata import _infer_fiction_or_nonfiction

        data = {"literatureType": "fiction", "genres": [{"name": "Obscure Genre"}]}
        assert _infer_fiction_or_nonfiction(data) == 1

    def test_fallback_to_literature_type_nonfiction(self):
        """Falls back to literatureType when genres don't match."""
        from shelfr.metadata import _infer_fiction_or_nonfiction

        data = {"literatureType": "nonfiction", "genres": [{"name": "Obscure Genre"}]}
        assert _infer_fiction_or_nonfiction(data) == 2

    def test_empty_genres_defaults_to_fiction(self):
        """Defaults to Fiction when no genres or literatureType."""
        from shelfr.metadata import _infer_fiction_or_nonfiction

        data = {"genres": []}
        assert _infer_fiction_or_nonfiction(data) == 1

    def test_missing_genres_defaults_to_fiction(self):
        """Defaults to Fiction when genres key is missing."""
        from shelfr.metadata import _infer_fiction_or_nonfiction

        data = {}
        assert _infer_fiction_or_nonfiction(data) == 1

    def test_science_fiction_not_confused_with_science(self):
        """'Science fiction' should be detected as fiction, not non-fiction."""
        from shelfr.metadata import _infer_fiction_or_nonfiction

        data = {"genres": [{"name": "Science Fiction"}]}
        assert _infer_fiction_or_nonfiction(data) == 1

    def test_word_boundary_matching(self):
        """Word boundary matching should avoid false positives."""
        from shelfr.metadata import _infer_fiction_or_nonfiction

        # "urban" shouldn't match in "Suburban Life"
        data = {"genres": [{"name": "Suburban Life"}]}
        # This should fall back to default (fiction) since no keywords match
        assert _infer_fiction_or_nonfiction(data) == 1


class TestGetAudiobookCategory:
    """Tests for _get_audiobook_category function."""

    def test_fantasy_genre_returns_fantasy_category(self):
        """Fantasy genre should map to 'Audiobooks - Fantasy'."""
        from shelfr.metadata import _get_audiobook_category

        mock_settings = MagicMock()
        mock_settings.categories.audiobook_fiction_map = {
            "fantasy": "Audiobooks - Fantasy",
        }
        mock_settings.categories.audiobook_defaults = {"fiction": "Audiobooks - General Fiction"}

        with patch("shelfr.metadata.get_settings", return_value=mock_settings):
            data = {"genres": [{"name": "Fantasy"}]}
            result = _get_audiobook_category(data, is_fiction=True)

        assert result == "Audiobooks - Fantasy"

    def test_biography_genre_returns_biographical_category(self):
        """Biography genre should map to 'Audiobooks - Biographical'."""
        from shelfr.metadata import _get_audiobook_category

        mock_settings = MagicMock()
        mock_settings.categories.audiobook_nonfiction_map = {
            "biography": "Audiobooks - Biographical",
        }
        mock_settings.categories.audiobook_defaults = {"nonfiction": "Audiobooks - General Non-Fic"}

        with patch("shelfr.metadata.get_settings", return_value=mock_settings):
            data = {"genres": [{"name": "Biography"}]}
            result = _get_audiobook_category(data, is_fiction=False)

        assert result == "Audiobooks - Biographical"

    def test_first_match_wins(self):
        """First matching keyword in the map should win."""
        from shelfr.metadata import _get_audiobook_category

        mock_settings = MagicMock()
        mock_settings.categories.audiobook_fiction_map = {
            "horror": "Audiobooks - Horror",
            "thriller": "Audiobooks - Crime/Thriller",
        }
        mock_settings.categories.audiobook_defaults = {"fiction": "Audiobooks - General Fiction"}

        with patch("shelfr.metadata.get_settings", return_value=mock_settings):
            # Horror should win because it comes first in the map
            data = {"genres": [{"name": "Horror"}, {"name": "Thriller"}]}
            result = _get_audiobook_category(data, is_fiction=True)

        assert result == "Audiobooks - Horror"

    def test_fallback_to_default_fiction(self):
        """Falls back to default when no keywords match."""
        from shelfr.metadata import _get_audiobook_category

        mock_settings = MagicMock()
        mock_settings.categories.audiobook_fiction_map = {
            "fantasy": "Audiobooks - Fantasy",
        }
        mock_settings.categories.audiobook_defaults = {"fiction": "Audiobooks - General Fiction"}

        with patch("shelfr.metadata.get_settings", return_value=mock_settings):
            data = {"genres": [{"name": "Obscure Genre"}]}
            result = _get_audiobook_category(data, is_fiction=True)

        assert result == "Audiobooks - General Fiction"

    def test_fallback_to_default_nonfiction(self):
        """Falls back to default when no keywords match."""
        from shelfr.metadata import _get_audiobook_category

        mock_settings = MagicMock()
        mock_settings.categories.audiobook_nonfiction_map = {
            "biography": "Audiobooks - Biographical",
        }
        mock_settings.categories.audiobook_defaults = {"nonfiction": "Audiobooks - General Non-Fic"}

        with patch("shelfr.metadata.get_settings", return_value=mock_settings):
            data = {"genres": [{"name": "Obscure Genre"}]}
            result = _get_audiobook_category(data, is_fiction=False)

        assert result == "Audiobooks - General Non-Fic"

    def test_empty_map_returns_default(self):
        """Returns default when category map is empty."""
        from shelfr.metadata import _get_audiobook_category

        mock_settings = MagicMock()
        mock_settings.categories.audiobook_fiction_map = {}
        mock_settings.categories.audiobook_defaults = {"fiction": "Audiobooks - General Fiction"}

        with patch("shelfr.metadata.get_settings", return_value=mock_settings):
            data = {"genres": [{"name": "Fantasy"}]}
            result = _get_audiobook_category(data, is_fiction=True)

        assert result == "Audiobooks - General Fiction"

    def test_hardcoded_default_when_not_in_config(self):
        """Uses hardcoded default when not in config defaults."""
        from shelfr.metadata import _get_audiobook_category

        mock_settings = MagicMock()
        mock_settings.categories.audiobook_fiction_map = {}
        mock_settings.categories.audiobook_defaults = {}  # Empty!

        with patch("shelfr.metadata.get_settings", return_value=mock_settings):
            data = {"genres": [{"name": "Fantasy"}]}
            result = _get_audiobook_category(data, is_fiction=True)

        assert result == "Audiobooks - General Fiction"


class TestBuildMamJsonCategory:
    """Tests for category field in build_mam_json."""

    def test_category_field_included(self):
        """build_mam_json should include category field."""
        from shelfr.models import AudiobookRelease

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

        with patch("shelfr.metadata.get_settings", return_value=mock_settings):
            result = build_mam_json(release, audnex_data=audnex_data)

        assert "category" in result
        assert result["category"] == "Audiobooks - Fantasy"
        assert result["main_cat"] == 1  # Fiction


class TestDetectAudioFormat:
    """Tests for audio format detection from MediaInfo."""

    def test_detect_dolby_atmos(self):
        """Detect Dolby Atmos from E-AC-3 with JOC."""
        mediainfo_data = {
            "media": {
                "track": [
                    {"@type": "General"},
                    {
                        "@type": "Audio",
                        "Format": "E-AC-3",
                        "Format_Commercial_IfAny": "Dolby Digital Plus with Dolby Atmos",
                        "Format_AdditionalFeatures": "JOC",
                        "CodecID": "ec-3",
                        "BitRate": "768500",
                        "BitRate_Mode": "CBR",
                        "Channels": "6",
                        "ChannelLayout": "L R C LFE Ls Rs",
                        "SamplingRate": "48000",
                        "extra": {"NumberOfDynamicObjects": "15"},
                    },
                ]
            }
        }

        result = detect_audio_format(mediainfo_data)

        assert result is not None
        assert result.is_dolby_atmos is True
        assert result.codec == "E-AC-3"
        assert result.codec_id == "ec-3"
        assert result.bitrate == 768500
        assert result.channels == 6
        assert result.channel_layout == "L R C LFE Ls Rs"
        assert result.dynamic_objects == 15
        assert result.format_commercial == "Dolby Digital Plus with Dolby Atmos"

    def test_detect_standard_aac(self):
        """Detect standard AAC stereo audio."""
        mediainfo_data = {
            "media": {
                "track": [
                    {"@type": "General"},
                    {
                        "@type": "Audio",
                        "Format": "AAC",
                        "Format_AdditionalFeatures": "LC",
                        "CodecID": "mp4a-40-2",
                        "BitRate": "125588",
                        "BitRate_Mode": "VBR",
                        "Channels": "2",
                        "ChannelLayout": "L R",
                        "SamplingRate": "44100",
                    },
                ]
            }
        }

        result = detect_audio_format(mediainfo_data)

        assert result is not None
        assert result.is_dolby_atmos is False
        assert result.codec == "AAC"
        assert result.codec_id == "mp4a-40-2"
        assert result.bitrate == 125588
        assert result.channels == 2
        assert result.channel_layout == "L R"
        assert result.dynamic_objects is None

    def test_detect_high_bitrate_aac(self):
        """Detect high bitrate AAC (256kbps+)."""
        mediainfo_data = {
            "media": {
                "track": [
                    {
                        "@type": "Audio",
                        "Format": "AAC",
                        "CodecID": "mp4a-40-2",
                        "BitRate": "320000",
                        "Channels": "2",
                        "SamplingRate": "44100",
                    },
                ]
            }
        }

        result = detect_audio_format(mediainfo_data)

        assert result is not None
        assert result.is_dolby_atmos is False
        assert result.bitrate == 320000
        assert result.get_edition_tag() == "(320kbps)"
        assert result.get_quality_tier() == "high"

    def test_edition_tag_dolby_atmos(self):
        """Edition tag returns (Dolby Atmos) for Atmos content."""
        audio_format = AudioFormat(
            codec="E-AC-3",
            codec_id="ec-3",
            bitrate=768500,
            bitrate_mode="CBR",
            channels=6,
            channel_layout="L R C LFE Ls Rs",
            sample_rate=48000,
            is_dolby_atmos=True,
            is_xhe_aac=False,
            format_commercial="Dolby Digital Plus with Dolby Atmos",
            dynamic_objects=15,
        )

        assert audio_format.get_edition_tag() == "(Dolby Atmos)"
        assert audio_format.get_quality_tier() == "atmos"

    def test_edition_tag_standard_bitrate(self):
        """Edition tag returns None for standard bitrate."""
        audio_format = AudioFormat(
            codec="AAC",
            codec_id="mp4a-40-2",
            bitrate=128000,
            bitrate_mode="VBR",
            channels=2,
            channel_layout="L R",
            sample_rate=44100,
            is_dolby_atmos=False,
            is_xhe_aac=False,
            format_commercial=None,
            dynamic_objects=None,
        )

        assert audio_format.get_edition_tag() is None
        assert audio_format.get_quality_tier() == "standard"

    def test_quality_tier_low(self):
        """Quality tier returns low for < 96kbps."""
        audio_format = AudioFormat(
            codec="AAC",
            codec_id="mp4a-40-2",
            bitrate=64000,
            bitrate_mode="VBR",
            channels=2,
            channel_layout="L R",
            sample_rate=44100,
            is_dolby_atmos=False,
            is_xhe_aac=False,
            format_commercial=None,
            dynamic_objects=None,
        )

        assert audio_format.get_quality_tier() == "low"

    def test_detect_xhe_aac_usac_format(self):
        """Detect xHE-AAC from USAC format name."""
        mediainfo_data = {
            "media": {
                "track": [
                    {
                        "@type": "Audio",
                        "Format": "USAC",
                        "CodecID": "mp4a-40-42",
                        "BitRate": "124000",
                        "BitRate_Mode": "VBR",
                        "Channels": "2",
                        "ChannelLayout": "L R",
                        "SamplingRate": "48000",
                    },
                ]
            }
        }

        result = detect_audio_format(mediainfo_data)

        assert result is not None
        assert result.is_xhe_aac is True
        assert result.codec == "USAC"
        assert result.get_edition_tag() == "(xHE-AAC)"
        assert result.get_quality_tier() == "high"

    def test_edition_tag_xhe_aac(self):
        """Edition tag returns (xHE-AAC) for xHE-AAC content."""
        audio_format = AudioFormat(
            codec="USAC",
            codec_id="mp4a-40-42",
            bitrate=124000,
            bitrate_mode="VBR",
            channels=2,
            channel_layout="L R",
            sample_rate=48000,
            is_dolby_atmos=False,
            is_xhe_aac=True,
            format_commercial=None,
            dynamic_objects=None,
        )

        assert audio_format.get_edition_tag() == "(xHE-AAC)"
        assert audio_format.get_quality_tier() == "high"

    def test_format_description_dolby_atmos(self):
        """Format description for Dolby Atmos 5.1."""
        audio_format = AudioFormat(
            codec="E-AC-3",
            codec_id="ec-3",
            bitrate=768000,
            bitrate_mode="CBR",
            channels=6,
            channel_layout="L R C LFE Ls Rs",
            sample_rate=48000,
            is_dolby_atmos=True,
            is_xhe_aac=False,
            format_commercial="Dolby Digital Plus with Dolby Atmos",
            dynamic_objects=15,
        )

        assert audio_format.get_format_description() == "Dolby Atmos 5.1 768kbps"

    def test_format_description_xhe_aac(self):
        """Format description for xHE-AAC."""
        audio_format = AudioFormat(
            codec="USAC",
            codec_id="mp4a-40-42",
            bitrate=124000,
            bitrate_mode="VBR",
            channels=2,
            channel_layout="L R",
            sample_rate=48000,
            is_dolby_atmos=False,
            is_xhe_aac=True,
            format_commercial=None,
            dynamic_objects=None,
        )

        assert audio_format.get_format_description() == "xHE-AAC 124kbps"

    def test_format_description_standard_aac(self):
        """Format description for standard AAC."""
        audio_format = AudioFormat(
            codec="AAC",
            codec_id="mp4a-40-2",
            bitrate=128000,
            bitrate_mode="VBR",
            channels=2,
            channel_layout="L R",
            sample_rate=44100,
            is_dolby_atmos=False,
            is_xhe_aac=False,
            format_commercial=None,
            dynamic_objects=None,
        )

        assert audio_format.get_format_description() == "AAC 128kbps"

    def test_detect_none_input(self):
        """Returns None when mediainfo_data is None."""
        assert detect_audio_format(None) is None

    def test_detect_no_media(self):
        """Returns None when media key is missing."""
        assert detect_audio_format({}) is None
        assert detect_audio_format({"media": None}) is None

    def test_detect_no_audio_track(self):
        """Returns None when no audio track found."""
        mediainfo_data = {
            "media": {
                "track": [
                    {"@type": "General"},
                    {"@type": "Image"},
                ]
            }
        }
        assert detect_audio_format(mediainfo_data) is None

    def test_detect_joc_without_commercial_name(self):
        """Detect Atmos from JOC format feature even without commercial name."""
        mediainfo_data = {
            "media": {
                "track": [
                    {
                        "@type": "Audio",
                        "Format": "E-AC-3",
                        "Format_AdditionalFeatures": "JOC",
                        "CodecID": "ec-3",
                        "BitRate": "768000",
                        "Channels": "6",
                        "SamplingRate": "48000",
                    },
                ]
            }
        }

        result = detect_audio_format(mediainfo_data)

        assert result is not None
        assert result.is_dolby_atmos is True

    def test_detect_handles_missing_fields(self):
        """Handles missing optional fields gracefully."""
        mediainfo_data = {
            "media": {
                "track": [
                    {
                        "@type": "Audio",
                        "Format": "MP3",
                    },
                ]
            }
        }

        result = detect_audio_format(mediainfo_data)

        assert result is not None
        assert result.codec == "MP3"
        assert result.codec_id == ""
        assert result.bitrate == 0
        assert result.channels == 2  # default
        assert result.sample_rate == 44100  # default
        assert result.is_dolby_atmos is False


class TestMapGenresToCategories:
    """Tests for _map_genres_to_categories function."""

    def test_exact_match(self):
        """Exact genre match returns correct category."""
        mock_settings = MagicMock()
        mock_settings.categories.genre_map = {
            "fantasy": 13,
            "science fiction": 45,
        }

        with patch("shelfr.metadata.get_settings", return_value=mock_settings):
            result = _map_genres_to_categories([{"name": "Fantasy"}])

        assert result == [13]

    def test_compound_genre_splits_on_ampersand(self):
        """Compound genre 'Science Fiction & Fantasy' maps to both categories."""
        mock_settings = MagicMock()
        mock_settings.categories.genre_map = {
            "fantasy": 13,
            "science fiction": 45,
        }

        with patch("shelfr.metadata.get_settings", return_value=mock_settings):
            result = _map_genres_to_categories([{"name": "Science Fiction & Fantasy"}])

        # Should map to both Science Fiction (45) and Fantasy (13)
        assert sorted(result) == [13, 45]

    def test_compound_genre_splits_on_comma(self):
        """Compound genre 'Literature & Fiction, Fantasy' maps all parts."""
        mock_settings = MagicMock()
        mock_settings.categories.genre_map = {
            "literature": 57,
            "fiction": 57,
            "fantasy": 13,
        }

        with patch("shelfr.metadata.get_settings", return_value=mock_settings):
            result = _map_genres_to_categories([{"name": "Literature & Fiction, Fantasy"}])

        # Should map to both Literary Fiction (57) and Fantasy (13)
        assert sorted(result) == [13, 57]

    def test_multiple_genres_deduplicated(self):
        """Multiple genres with same category are deduplicated."""
        mock_settings = MagicMock()
        mock_settings.categories.genre_map = {
            "fantasy": 13,
            "epic": 13,
            "high fantasy": 13,
        }

        with patch("shelfr.metadata.get_settings", return_value=mock_settings):
            result = _map_genres_to_categories(
                [
                    {"name": "Fantasy"},
                    {"name": "Epic"},
                    {"name": "High Fantasy"},
                ]
            )

        # All map to Fantasy (13), should be deduplicated
        assert result == [13]

    def test_partial_match_fallback(self):
        """Falls back to partial matching when no exact/split match."""
        mock_settings = MagicMock()
        mock_settings.categories.genre_map = {
            "thriller": 51,
        }

        with patch("shelfr.metadata.get_settings", return_value=mock_settings):
            result = _map_genres_to_categories([{"name": "Psychological Thriller"}])

        # Partial match should find "thriller"
        assert result == [51]

    def test_empty_genres_returns_empty(self):
        """Empty genres list returns empty categories."""
        mock_settings = MagicMock()
        mock_settings.categories.genre_map = {"fantasy": 13}

        with patch("shelfr.metadata.get_settings", return_value=mock_settings):
            result = _map_genres_to_categories([])

        assert result == []

    def test_unmatched_genre_returns_empty(self):
        """Unmatched genre returns empty categories."""
        mock_settings = MagicMock()
        mock_settings.categories.genre_map = {"fantasy": 13}

        with patch("shelfr.metadata.get_settings", return_value=mock_settings):
            result = _map_genres_to_categories([{"name": "Audiobook"}])

        assert result == []
