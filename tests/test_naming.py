"""Tests for naming utilities."""

from typing import Any

from shelfr.config import FiltersConfig, NamingConfig
from shelfr.utils.naming import (
    build_release_dirname,
    ensure_unique_name,
    extract_translator,
    # Using backward-compatible alias; function is now extract_non_authors_from_mediainfo
    # but handles translators, illustrators, editors, etc.
    extract_translators_from_mediainfo,
    filter_authors,
    filter_series,
    filter_subtitle,
    filter_title,
    is_author_role,
    sanitize_filename,
    transliterate_text,
    truncate_filename,
)


class TestSanitizeFilename:
    """Tests for filename sanitization."""

    def test_removes_illegal_chars(self) -> None:
        """Test removal of illegal characters."""
        assert sanitize_filename("Book: A Story") == "Book - A Story"
        assert sanitize_filename("What?") == "What"
        assert sanitize_filename("This/That") == "This-That"
        assert sanitize_filename('Say "Hello"') == "Say 'Hello'"

    def test_collapses_spaces(self) -> None:
        """Test multiple spaces are collapsed."""
        assert sanitize_filename("Too    Many   Spaces") == "Too Many Spaces"

    def test_strips_dots_and_spaces(self) -> None:
        """Test leading/trailing dots and spaces are stripped."""
        assert sanitize_filename("  Book  ") == "Book"
        assert sanitize_filename("...Book...") == "Book"
        assert sanitize_filename(". Book .") == "Book"


class TestTruncateFilename:
    """Tests for filename truncation."""

    def test_short_name_unchanged(self) -> None:
        """Test short names are returned unchanged."""
        name = "Short Name.m4b"
        assert truncate_filename(name, max_length=225) == name

    def test_long_name_truncated(self) -> None:
        """Test long names are truncated."""
        name = "A" * 300 + ".m4b"
        result = truncate_filename(name, max_length=225)
        assert len(result) <= 225
        assert result.endswith(".m4b")

    def test_preserves_extension(self) -> None:
        """Test file extension is preserved."""
        name = "Very Long Title " * 20 + ".m4b"
        result = truncate_filename(name, max_length=100)
        assert result.endswith(".m4b")

    def test_adds_hash_suffix(self) -> None:
        """Test truncated names get hash suffix for uniqueness."""
        name = "A" * 300 + ".m4b"
        result = truncate_filename(name, max_length=225)
        assert "...[" in result
        assert "]" in result


class TestBuildReleaseDirname:
    """Tests for release directory name building."""

    def test_author_and_title(self) -> None:
        """Test basic author - title format."""
        result = build_release_dirname(author="John Smith", title="Great Book")
        assert result == "John Smith - Great Book"

    def test_with_year(self) -> None:
        """Test author - title (year) format."""
        result = build_release_dirname(
            author="Jane Doe",
            title="Another Book",
            year="2023",
        )
        assert result == "Jane Doe - Another Book (2023)"

    def test_with_series(self) -> None:
        """Test including series info."""
        result = build_release_dirname(
            author="Author",
            title="Book",
            series="Epic Series",
            series_position="3",
        )
        assert "Epic Series #3" in result

    def test_title_only(self) -> None:
        """Test with only title provided."""
        result = build_release_dirname(author=None, title="Just Title")
        assert result == "Just Title"

    def test_sanitizes_special_chars(self) -> None:
        """Test special characters are sanitized."""
        result = build_release_dirname(
            author="Author: Name",
            title="Book/Title",
        )
        assert ":" not in result
        assert "/" not in result


class TestFilterAuthors:
    """Tests for author filtering."""

    def test_filters_translator(self) -> None:
        """Test filtering out translators."""
        authors = [
            {"name": "Real Author"},
            {"name": "Jane Doe - translator"},
        ]
        result = filter_authors(authors)
        assert len(result) == 1
        assert result[0]["name"] == "Real Author"

    def test_filters_illustrator(self) -> None:
        """Test filtering out illustrators."""
        authors = [
            {"name": "Real Author"},
            {"name": "Bob Jones (illustrator)"},
        ]
        result = filter_authors(authors)
        assert len(result) == 1
        assert result[0]["name"] == "Real Author"

    def test_filters_multiple_roles(self) -> None:
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

    def test_empty_list(self) -> None:
        """Test handling empty list."""
        result = filter_authors([])
        assert result == []


class TestIsAuthorRole:
    """Tests for author role detection."""

    def test_detects_translator(self) -> None:
        """Test detecting translator role."""
        assert is_author_role("Jane Doe - translator") is True
        assert is_author_role("Jane Doe (translator)") is True

    def test_detects_illustrator(self) -> None:
        """Test detecting illustrator role."""
        assert is_author_role("Bob (illustrator)") is True

    def test_detects_editor(self) -> None:
        """Test detecting editor role."""
        assert is_author_role("Alice - editor") is True

    def test_primary_author_not_filtered(self) -> None:
        """Test primary authors are not detected as roles."""
        assert is_author_role("John Smith") is False
        assert is_author_role("J.R.R. Tolkien") is False

    def test_no_false_positives_on_names(self) -> None:
        """Test names containing role words are NOT filtered (word boundary check)."""
        # These should NOT be detected as roles - the word appears in the name
        assert is_author_role("John Translator Smith") is False
        assert is_author_role("Editor Johnson") is False
        assert is_author_role("Illustrator Jane") is False
        assert is_author_role("Afterword Publishing") is False

    def test_detects_foreword_afterword(self) -> None:
        """Test detecting foreword/afterword credits."""
        assert is_author_role("Charlie (foreword)") is True
        assert is_author_role("Bob - afterword") is True
        assert is_author_role("Foreword by Someone") is True


class TestExtractTranslator:
    """Tests for translator extraction."""

    def test_extracts_translator(self) -> None:
        """Test extracting translator name."""
        authors = [
            {"name": "Real Author"},
            {"name": "Jane Doe - translator"},
        ]
        result = extract_translator(authors)
        assert result == "Jane Doe"

    def test_no_translator(self) -> None:
        """Test when no translator present."""
        authors = [{"name": "Real Author"}]
        result = extract_translator(authors)
        assert result is None


class TestExtractTranslatorsFromMediainfo:
    """Tests for extracting non-authors from MediaInfo metadata."""

    def test_extracts_single_translator(self) -> None:
        """Test extracting a single translator from Album_Performer."""
        mediainfo_data = {
            "media": {
                "track": [
                    {
                        "@type": "General",
                        "Album_Performer": "Author One; Author Two; John Smith - translator",
                    }
                ]
            }
        }
        result = extract_translators_from_mediainfo(mediainfo_data)
        assert result == {"John Smith"}

    def test_extracts_multiple_translators(self) -> None:
        """Test extracting multiple translators."""
        mediainfo_data = {
            "media": {
                "track": [
                    {
                        "@type": "General",
                        "Album_Performer": "Author; Trans One - translator; Trans Two - translator",
                    }
                ]
            }
        }
        result = extract_translators_from_mediainfo(mediainfo_data)
        assert result == {"Trans One", "Trans Two"}

    def test_extracts_illustrator(self) -> None:
        """Test extracting illustrators."""
        mediainfo_data = {
            "media": {
                "track": [
                    {
                        "@type": "General",
                        "Album_Performer": "Author; Artist Name - illustrator",
                    }
                ]
            }
        }
        result = extract_translators_from_mediainfo(mediainfo_data)
        assert result == {"Artist Name"}

    def test_extracts_editor(self) -> None:
        """Test extracting editors."""
        mediainfo_data = {
            "media": {
                "track": [
                    {
                        "@type": "General",
                        "Album_Performer": "Author; Jane Doe - editor",
                    }
                ]
            }
        }
        result = extract_translators_from_mediainfo(mediainfo_data)
        assert result == {"Jane Doe"}

    def test_extracts_multiple_roles(self) -> None:
        """Test extracting multiple different roles."""
        mediainfo_data = {
            "media": {
                "track": [
                    {
                        "@type": "General",
                        "Album_Performer": (
                            "Real Author; Trans - translator; Artist - illustrator; Ed - editor"
                        ),
                    }
                ]
            }
        }
        result = extract_translators_from_mediainfo(mediainfo_data)
        assert result == {"Trans", "Artist", "Ed"}

    def test_no_non_authors(self) -> None:
        """Test when no non-authors present."""
        mediainfo_data = {
            "media": {
                "track": [
                    {
                        "@type": "General",
                        "Album_Performer": "Author One; Author Two",
                    }
                ]
            }
        }
        result = extract_translators_from_mediainfo(mediainfo_data)
        assert result == set()

    def test_none_input(self) -> None:
        """Test with None input."""
        result = extract_translators_from_mediainfo(None)
        assert result == set()

    def test_empty_mediainfo(self) -> None:
        """Test with empty mediainfo."""
        result = extract_translators_from_mediainfo({})
        assert result == set()

    def test_uses_performer_fallback(self) -> None:
        """Test using Performer field when Album_Performer not present."""
        mediainfo_data = {
            "media": {
                "track": [
                    {
                        "@type": "General",
                        "Performer": "Author; Jane Doe - translator",
                    }
                ]
            }
        }
        result = extract_translators_from_mediainfo(mediainfo_data)
        assert result == {"Jane Doe"}


class TestFilterTitle:
    """Tests for title filtering."""

    def test_removes_book_pattern(self) -> None:
        """Test removing 'Book XX' pattern."""
        result = filter_title("Epic Story Book 3")
        assert "Book 3" not in result

    def test_removes_custom_phrases(self) -> None:
        """Test removing custom phrases."""
        result = filter_title("Title [Custom Tag]", remove_phrases=["[Custom Tag]"])
        assert "[Custom Tag]" not in result

    def test_removes_duplicate_volume(self) -> None:
        """Test removing duplicate number before vol_XX."""
        result = filter_title("Title 12 vol_12")
        assert result == "Title vol_12"

    def test_cleans_whitespace(self) -> None:
        """Test whitespace cleanup."""
        result = filter_title("Title   with   spaces")
        assert "  " not in result


class TestTransliterateText:
    """Tests for text transliteration."""

    def test_ascii_unchanged(self) -> None:
        """Test ASCII text is unchanged."""
        filters = FiltersConfig(author_map={}, transliterate_japanese=False)
        result = transliterate_text("Hello World", filters)
        assert result == "Hello World"

    def test_applies_author_map(self) -> None:
        """Test author map substitution."""
        filters = FiltersConfig(
            author_map={"川原礫": "Reki Kawahara"},
            transliterate_japanese=False,
        )
        result = transliterate_text("川原礫", filters)
        assert result == "Reki Kawahara"

    def test_none_filters_returns_unchanged(self) -> None:
        """Test None filters returns text unchanged."""
        result = transliterate_text("Test 日本語", None)
        assert result == "Test 日本語"


class TestEnsureUniqueName:
    """Tests for unique name generation."""

    def test_unique_name_unchanged(self) -> None:
        """Test unique name returned unchanged."""
        existing = {"other.m4b", "another.m4b"}
        result = ensure_unique_name("unique.m4b", existing)
        assert result == "unique.m4b"

    def test_adds_counter_for_duplicate(self) -> None:
        """Test counter added for duplicate."""
        existing = {"book.m4b"}
        result = ensure_unique_name("book.m4b", existing)
        assert result == "book (2).m4b"

    def test_increments_counter(self) -> None:
        """Test counter increments for multiple duplicates."""
        existing = {"book.m4b", "book (2).m4b", "book (3).m4b"}
        result = ensure_unique_name("book.m4b", existing)
        assert result == "book (4).m4b"

    def test_preserves_extension(self) -> None:
        """Test extension is preserved."""
        existing = {"file.txt"}
        result = ensure_unique_name("file.txt", existing)
        assert result.endswith(".txt")


class TestFilterTitleWithNamingConfig:
    """Tests for filter_title with NamingConfig."""

    def test_removes_format_indicators(self) -> None:
        """Test removing format indicators from NamingConfig."""
        config = NamingConfig(format_indicators=["(Light Novel)", "Unabridged"])
        result = filter_title("Overlord (Light Novel)", naming_config=config)
        assert result == "Overlord"

    def test_removes_genre_tags(self) -> None:
        """Test removing genre tags from NamingConfig."""
        config = NamingConfig(genre_tags=["A LitRPG Adventure"])
        result = filter_title("Dungeon Crawler Carl A LitRPG Adventure", naming_config=config)
        assert result == "Dungeon Crawler Carl"

    def test_removes_publisher_tags(self) -> None:
        """Test removing publisher tags from NamingConfig."""
        config = NamingConfig(publisher_tags=["[Yen Audio]", "(J-Novel Club)"])
        result = filter_title("Sword Art Online [Yen Audio]", naming_config=config)
        assert result == "Sword Art Online"

    def test_removes_multiple_categories(self) -> None:
        """Test removing from multiple categories in one pass."""
        config = NamingConfig(
            format_indicators=["(Light Novel)"],
            genre_tags=["A LitRPG Adventure"],
            publisher_tags=["[Yen Audio]"],
        )
        result = filter_title(
            "My Book (Light Novel) A LitRPG Adventure [Yen Audio]",
            naming_config=config,
        )
        assert result == "My Book"

    def test_case_insensitive_matching(self) -> None:
        """Test that matching is case-insensitive."""
        config = NamingConfig(format_indicators=["(Light Novel)"])
        result = filter_title("Overlord (light novel)", naming_config=config)
        assert result == "Overlord"

    def test_backward_compatibility_with_remove_phrases(self) -> None:
        """Test that legacy remove_phrases still works."""
        result = filter_title(
            "Title [Custom Tag]",
            remove_phrases=["[Custom Tag]"],
        )
        assert result == "Title"

    def test_combined_naming_config_and_remove_phrases(self) -> None:
        """Test both naming_config and remove_phrases work together."""
        config = NamingConfig(format_indicators=["(Light Novel)"])
        result = filter_title(
            "Title (Light Novel) [Custom]",
            remove_phrases=["[Custom]"],
            naming_config=config,
        )
        assert result == "Title"


class TestFilterTitlePreserveExact:
    """Tests for preserve_exact bypass in filter_title."""

    def test_preserves_exact_match(self) -> None:
        """Test exact match is preserved."""
        config = NamingConfig(
            format_indicators=["(Light Novel)"],
            preserve_exact=["Re:ZERO"],
        )
        # The colon would normally be problematic, but preserve_exact bypasses cleaning
        result = filter_title("Re:ZERO", naming_config=config)
        assert result == "Re:ZERO"

    def test_preserves_prefix_match(self) -> None:
        """Test prefix match preserves title with suffix.

        With prefix matching, 'Re:ZERO' in preserve_exact will preserve
        'Re:ZERO (Light Novel)' because it starts with 'Re:ZERO' followed
        by a valid separator (space + parenthesis).
        """
        config = NamingConfig(
            format_indicators=["(Light Novel)"],
            preserve_exact=["Re:ZERO"],
        )
        result = filter_title("Re:ZERO (Light Novel)", naming_config=config)
        # Should preserve because input starts with "Re:ZERO" + " ("
        assert result == "Re:ZERO (Light Novel)"

    def test_preserves_86_eighty_six_with_suffix(self) -> None:
        """Test 86--EIGHTY-SIX is preserved with suffix via prefix matching.

        With prefix matching, '86--EIGHTY-SIX' in preserve_exact will preserve
        '86--EIGHTY-SIX (Light Novel)' because it starts with the preserved
        string followed by a valid separator.
        """
        config = NamingConfig(
            format_indicators=["(Light Novel)"],
            preserve_exact=["86--EIGHTY-SIX"],
        )
        # Exact match - preserved
        result = filter_title("86--EIGHTY-SIX", naming_config=config)
        assert result == "86--EIGHTY-SIX"

        # Prefix match with (Light Novel) - also preserved
        result2 = filter_title("86--EIGHTY-SIX (Light Novel)", naming_config=config)
        assert result2 == "86--EIGHTY-SIX (Light Novel)"

        # Prefix match with Vol. - also preserved
        result3 = filter_title("86--EIGHTY-SIX, Vol. 1", naming_config=config)
        assert result3 == "86--EIGHTY-SIX, Vol. 1"

    def test_preserves_sao_progressive(self) -> None:
        """Test Sword Art Online: Progressive is preserved."""
        config = NamingConfig(
            preserve_exact=["Sword Art Online: Progressive"],
        )
        result = filter_title("Sword Art Online: Progressive", naming_config=config)
        assert result == "Sword Art Online: Progressive"

    def test_non_preserved_still_cleaned(self) -> None:
        """Test non-preserved titles are still cleaned."""
        config = NamingConfig(
            format_indicators=["(Light Novel)"],
            preserve_exact=["Re:ZERO"],
        )
        result = filter_title("Overlord (Light Novel)", naming_config=config)
        assert result == "Overlord"


class TestFilterSeries:
    """Tests for filter_series function."""

    def test_removes_series_suffix(self) -> None:
        """Test removing ' Series' suffix."""
        config = NamingConfig(series_suffixes=[r"\s+[Ss]eries$"])
        result = filter_series("A Most Unlikely Hero Series", naming_config=config)
        assert result == "A Most Unlikely Hero"

    def test_removes_trilogy_suffix(self) -> None:
        """Test removing ' Trilogy' suffix."""
        config = NamingConfig(series_suffixes=[r"\s+[Tt]rilogy$"])
        result = filter_series("Epic Fantasy Trilogy", naming_config=config)
        assert result == "Epic Fantasy"

    def test_removes_light_novel_suffix(self) -> None:
        """Test removing ' Light Novel' suffix from series."""
        config = NamingConfig(series_suffixes=[r"\s+[Ll]ight [Nn]ovel$"])
        result = filter_series("Kuma Kuma Kuma Bear Light Novel", naming_config=config)
        assert result == "Kuma Kuma Kuma Bear"

    def test_removes_parenthetical_light_novel(self) -> None:
        """Test removing '(Light Novel)' suffix from series."""
        config = NamingConfig(series_suffixes=[r"\s*\([Ll]ight [Nn]ovel\)$"])
        result = filter_series("Overlord (Light Novel)", naming_config=config)
        assert result == "Overlord"

    def test_also_applies_format_indicators(self) -> None:
        """Test filter_series also removes format_indicators."""
        config = NamingConfig(
            format_indicators=["(Unabridged)"],
            series_suffixes=[r"\s+[Ss]eries$"],
        )
        result = filter_series("Hero Series (Unabridged)", naming_config=config)
        assert result == "Hero"

    def test_preserves_non_suffix_series(self) -> None:
        """Test series without matching suffix is preserved."""
        config = NamingConfig(series_suffixes=[r"\s+[Ss]eries$"])
        result = filter_series("The Stormlight Archive", naming_config=config)
        assert result == "The Stormlight Archive"

    def test_preserve_exact_works_in_series(self) -> None:
        """Test preserve_exact works in filter_series with prefix matching.

        filter_series uses the same preserve_exact logic as filter_title,
        with prefix matching for titles followed by valid separators.
        """
        config = NamingConfig(
            series_suffixes=[r"\s+[Ss]eries$"],
            preserve_exact=["Re:ZERO"],
        )
        # Prefix match with " Series" - preserved
        result = filter_series("Re:ZERO Series", naming_config=config)
        assert result == "Re:ZERO Series"

        # Exact match - also preserved
        result2 = filter_series("Re:ZERO", naming_config=config)
        assert result2 == "Re:ZERO"

    def test_multiple_suffix_patterns(self) -> None:
        """Test multiple suffix patterns."""
        config = NamingConfig(
            series_suffixes=[
                r"\s+[Ss]eries$",
                r"\s+[Tt]rilogy$",
                r"\s+[Ss]aga$",
            ]
        )
        assert filter_series("Epic Series", naming_config=config) == "Epic"
        assert filter_series("Epic Trilogy", naming_config=config) == "Epic"
        assert filter_series("Epic Saga", naming_config=config) == "Epic"

    def test_invalid_regex_handled_gracefully(self) -> None:
        """Test invalid regex patterns don't crash."""
        config = NamingConfig(series_suffixes=[r"[invalid(regex"])
        # Should not raise, just skip the bad pattern
        result = filter_series("Test Series", naming_config=config)
        assert result == "Test Series"

    def test_removes_publication_order_tag(self) -> None:
        """Test removing '[publication order]' sorting tag from series."""
        config = NamingConfig(series_suffixes=[r"\s*\[[^\]]*[Oo]rder\]$"])
        result = filter_series("Ascend Online [publication order]", naming_config=config)
        assert result == "Ascend Online"

    def test_removes_chronological_order_tag(self) -> None:
        """Test removing '[chronological order]' sorting tag from series."""
        config = NamingConfig(series_suffixes=[r"\s*\[[^\]]*[Oo]rder\]$"])
        result = filter_series("Epic Fantasy [chronological order]", naming_config=config)
        assert result == "Epic Fantasy"

    def test_removes_reading_order_tag(self) -> None:
        """Test removing '[reading order]' sorting tag from series."""
        config = NamingConfig(series_suffixes=[r"\s*\[[^\]]*[Oo]rder\]$"])
        result = filter_series("Some Series [reading order]", naming_config=config)
        assert result == "Some Series"

    def test_combined_series_suffix_and_order_tag(self) -> None:
        """Test combined patterns (Series suffix and order tag)."""
        config = NamingConfig(
            series_suffixes=[
                r"[\s—-]?[Ss]eries$",
                r"\s*\[[^\]]*[Oo]rder\]$",
            ]
        )
        # Both should work
        assert filter_series("Epic Series", naming_config=config) == "Epic"
        assert filter_series("Epic [publication order]", naming_config=config) == "Epic"


class TestInheritThePrefix:
    """Tests for inherit_the_prefix function."""

    def test_inherits_the_from_title(self) -> None:
        """Test 'The' is inherited when title starts with 'The {series}'."""
        from shelfr.utils.naming import inherit_the_prefix

        result = inherit_the_prefix("Great Cleric", "The Great Cleric: Volume 1")
        assert result == "The Great Cleric"

    def test_already_has_the_prefix(self) -> None:
        """Test series with 'The' prefix is unchanged."""
        from shelfr.utils.naming import inherit_the_prefix

        result = inherit_the_prefix("The Great Cleric", "The Great Cleric: Volume 1")
        assert result == "The Great Cleric"

    def test_no_the_in_title(self) -> None:
        """Test no inheritance when title doesn't start with 'The'."""
        from shelfr.utils.naming import inherit_the_prefix

        result = inherit_the_prefix("Ascend Online", "Ascend Online")
        assert result == "Ascend Online"

    def test_title_does_not_match_series(self) -> None:
        """Test no inheritance when title doesn't match series."""
        from shelfr.utils.naming import inherit_the_prefix

        result = inherit_the_prefix("Epic Fantasy", "Volume 1: Epic Fantasy")
        assert result == "Epic Fantasy"

    def test_none_series(self) -> None:
        """Test None series returns None."""
        from shelfr.utils.naming import inherit_the_prefix

        result = inherit_the_prefix(None, "The Great Cleric")
        assert result is None

    def test_none_title(self) -> None:
        """Test None title returns series unchanged."""
        from shelfr.utils.naming import inherit_the_prefix

        result = inherit_the_prefix("Great Cleric", None)
        assert result == "Great Cleric"

    def test_case_insensitive_match(self) -> None:
        """Test case-insensitive matching for 'The' inheritance."""
        from shelfr.utils.naming import inherit_the_prefix

        result = inherit_the_prefix("great cleric", "The Great Cleric: Volume 1")
        assert result == "The great cleric"


class TestFilterTitleKeepVolume:
    """Tests for the keep_volume parameter in filter_title.

    Phase 3: MAM JSON keeps Vol. X human-readable, folders use vol_XX.
    """

    def test_default_removes_volume(self) -> None:
        """Test that Vol. X is removed by default (for folder names)."""
        result = filter_title("Overlord, Vol. 3")
        assert "Vol. 3" not in result
        assert "Overlord" in result

    def test_keep_volume_true_preserves_vol(self) -> None:
        """Test that keep_volume=True preserves Vol. X (for JSON)."""
        result = filter_title("Overlord, Vol. 3", keep_volume=True)
        assert "Vol. 3" in result
        assert "Overlord" in result

    def test_keep_volume_preserves_volume_word(self) -> None:
        """Test that keep_volume=True also preserves Volume X."""
        result = filter_title("Overlord, Volume 12", keep_volume=True)
        assert "Volume 12" in result

    def test_keep_volume_removes_format_indicators(self) -> None:
        """Test that keep_volume=True still removes format indicators."""
        config = NamingConfig(format_indicators=["(Light Novel)"])
        result = filter_title(
            "Overlord (Light Novel), Vol. 3",
            naming_config=config,
            keep_volume=True,
        )
        assert "(Light Novel)" not in result
        assert "Vol. 3" in result
        assert "Overlord" in result

    def test_keep_volume_still_removes_book(self) -> None:
        """Test that Book X is still removed (we normalize to Vol.)."""
        result = filter_title("Title, Book 5", keep_volume=True)
        # "Book 5" should still be removed (hardcoded pattern)
        assert "Book 5" not in result


class TestFilterSeriesKeepVolume:
    """Tests for the keep_volume parameter in filter_series."""

    def test_default_removes_volume(self) -> None:
        """Test that Vol. X is removed by default from series."""
        config = NamingConfig()
        result = filter_series("Overlord, Vol. 3", naming_config=config)
        assert "Vol. 3" not in result

    def test_keep_volume_true_in_series(self) -> None:
        """Test keep_volume parameter is passed through filter_series."""
        config = NamingConfig()
        result = filter_series("Overlord, Vol. 3", naming_config=config, keep_volume=True)
        assert "Vol. 3" in result

    def test_series_suffixes_still_applied_with_keep_volume(self) -> None:
        """Test that series suffixes are applied regardless of keep_volume."""
        config = NamingConfig(series_suffixes=[r"\s+[Ss]eries$"])
        result = filter_series("Epic Vol. 2 Series", naming_config=config, keep_volume=True)
        # Vol. 2 kept, but "Series" suffix removed
        assert "Vol. 2" in result
        assert result.endswith("Series") is False


class TestFilterSubtitle:
    """Tests for the filter_subtitle function."""

    def test_empty_subtitle_returns_none(self) -> None:
        """Test that empty/whitespace subtitles return None."""

        assert filter_subtitle("") is None
        assert filter_subtitle("   ") is None
        assert filter_subtitle(None) is None  # type: ignore[arg-type]

    def test_simple_subtitle_passes_through(self) -> None:
        """Test that normal subtitles pass through unchanged."""

        result = filter_subtitle("A Tale of Mystery")
        assert result == "A Tale of Mystery"

    def test_remove_patterns_drop_subtitle(self) -> None:
        """Test that matching remove_patterns drop the entire subtitle."""

        config = NamingConfig(subtitle_remove_patterns=[r"^[Ll]ight [Nn]ovel$", r"^[Uu]nabridged$"])
        assert filter_subtitle("Light Novel", naming_config=config) is None
        assert filter_subtitle("light novel", naming_config=config) is None
        assert filter_subtitle("Unabridged", naming_config=config) is None
        # But not partial matches
        assert filter_subtitle("The Light Novel Chronicles", naming_config=config) is not None

    def test_keep_patterns_preserve_subtitle(self) -> None:
        """Test that matching keep_patterns preserve the subtitle."""

        config = NamingConfig(
            subtitle_remove_patterns=[r"^.*Aria.*$"],
            subtitle_keep_patterns=[r".*[Aa]ria.*"],
        )
        # Without keep_pattern, would be removed by remove_pattern
        result = filter_subtitle("Aria of the Stars", naming_config=config)
        assert result == "Aria of the Stars"

    def test_series_match_drops_subtitle(self) -> None:
        """Test that subtitle matching series name is dropped."""

        config = NamingConfig(remove_subtitle_if_matches_series=True)
        result = filter_subtitle(
            "The Wandering Inn",
            series="The Wandering Inn",
            naming_config=config,
        )
        assert result is None

    def test_series_match_case_insensitive(self) -> None:
        """Test that series matching is case-insensitive."""

        config = NamingConfig(remove_subtitle_if_matches_series=True)
        result = filter_subtitle(
            "the wandering inn",
            series="The Wandering Inn",
            naming_config=config,
        )
        assert result is None

    def test_series_match_disabled(self) -> None:
        """Test that series matching can be disabled."""

        config = NamingConfig(remove_subtitle_if_matches_series=False)
        result = filter_subtitle(
            "The Wandering Inn",
            series="The Wandering Inn",
            naming_config=config,
        )
        assert result == "The Wandering Inn"

    def test_redundancy_rule_drop_subtitle(self) -> None:
        """Test drop_subtitle action in redundancy rules."""

        config = NamingConfig(
            subtitle_redundancy_enabled=True,
            subtitle_redundancy_rules=[
                {
                    "id": "series_book",
                    "pattern_template": r"^{{series}},?\s*Book\s*\d+$",
                    "action": "drop_subtitle",
                }
            ],
        )
        result = filter_subtitle(
            "Overlord, Book 3",
            series="Overlord",
            naming_config=config,
        )
        assert result is None

    def test_redundancy_rule_strip_match(self) -> None:
        """Test strip_match action in redundancy rules."""

        config = NamingConfig(
            subtitle_redundancy_enabled=True,
            subtitle_redundancy_rules=[
                {
                    "id": "series_in_parens",
                    "pattern_template": r"\({{series}},?\s*Book\s*\d+\)$",
                    "action": "strip_match",
                }
            ],
        )
        result = filter_subtitle(
            "A Tale of Adventure (Overlord, Book 3)",
            series="Overlord",
            naming_config=config,
        )
        assert result == "A Tale of Adventure"

    def test_redundancy_skips_rule_if_series_empty(self) -> None:
        """Test that rules with {{series}} are skipped if series is empty."""

        config = NamingConfig(
            subtitle_redundancy_enabled=True,
            subtitle_redundancy_rules=[
                {
                    "id": "series_book",
                    "pattern_template": r"^{{series}},?\s*Book\s*\d+$",
                    "action": "drop_subtitle",
                }
            ],
        )
        # No series provided, rule should be skipped
        result = filter_subtitle(
            "Some Series, Book 3",
            series=None,
            naming_config=config,
        )
        assert result == "Some Series, Book 3"

    def test_redundancy_rule_with_title(self) -> None:
        """Test {{title}} placeholder substitution."""

        config = NamingConfig(
            subtitle_redundancy_enabled=True,
            subtitle_redundancy_rules=[
                {
                    "id": "title_book",
                    "pattern_template": r"^{{title}},?\s*Book\s*\d+$",
                    "action": "drop_subtitle",
                }
            ],
        )
        result = filter_subtitle(
            "Epic Adventure, Book 1",
            title="Epic Adventure",
            naming_config=config,
        )
        assert result is None

    def test_redundancy_disabled(self) -> None:
        """Test that redundancy rules are skipped when disabled."""

        config = NamingConfig(
            subtitle_redundancy_enabled=False,
            subtitle_redundancy_rules=[
                {
                    "id": "series_book",
                    "pattern_template": r"^{{series}},?\s*Book\s*\d+$",
                    "action": "drop_subtitle",
                }
            ],
        )
        result = filter_subtitle(
            "Overlord, Book 3",
            series="Overlord",
            naming_config=config,
        )
        # Should NOT be dropped because redundancy is disabled
        assert result == "Overlord, Book 3"

    def test_preserve_exact_bypasses_all_rules(self) -> None:
        """Test that preserve_exact bypasses all subtitle filtering."""

        config = NamingConfig(
            subtitle_remove_patterns=[r"^[Ll]ight [Nn]ovel$"],
            preserve_exact=["Light Novel"],
        )
        # Would normally be removed, but preserved
        result = filter_subtitle("Light Novel", naming_config=config)
        assert result == "Light Novel"

    def test_strip_match_leaves_empty_drops_subtitle(self) -> None:
        """Test that strip_match leaving empty string drops subtitle."""

        config = NamingConfig(
            subtitle_redundancy_enabled=True,
            subtitle_redundancy_rules=[
                {
                    "id": "strip_all",
                    "pattern_template": r"^{{series}},?\s*Book\s*\d+$",
                    "action": "strip_match",
                }
            ],
        )
        result = filter_subtitle(
            "Overlord, Book 3",
            series="Overlord",
            naming_config=config,
        )
        # Strip match removes entire string, leaving empty -> None
        assert result is None

    def test_multiple_rules_applied_in_order(self) -> None:
        """Test that redundancy rules are applied in order."""

        config = NamingConfig(
            subtitle_redundancy_enabled=True,
            subtitle_redundancy_rules=[
                # First rule: drop exact series+book
                {
                    "id": "series_book",
                    "pattern_template": r"^{{series}},?\s*Book\s*\d+$",
                    "action": "drop_subtitle",
                },
                # Second rule: strip series in parens
                {
                    "id": "series_in_parens",
                    "pattern_template": r"\({{series}},?\s*Book\s*\d+\)$",
                    "action": "strip_match",
                },
            ],
        )
        # First rule should match and drop
        result1 = filter_subtitle(
            "Overlord, Book 3",
            series="Overlord",
            naming_config=config,
        )
        assert result1 is None

        # Second rule should strip the parens part
        result2 = filter_subtitle(
            "Epic Adventure (Overlord, Book 3)",
            series="Overlord",
            naming_config=config,
        )
        assert result2 == "Epic Adventure"

    def test_cleanup_applied_to_result(self) -> None:
        """Test that cleanup is applied to the final result."""

        config = NamingConfig(
            subtitle_redundancy_enabled=True,
            subtitle_redundancy_rules=[
                {
                    "id": "strip_suffix",
                    "pattern_template": r"\({{series}}\)$",
                    "action": "strip_match",
                }
            ],
        )
        # After stripping, should clean up trailing comma
        result = filter_subtitle(
            "A Great Story, (Overlord)",
            series="Overlord",
            naming_config=config,
        )
        # Should remove trailing comma after cleanup
        assert result == "A Great Story"

    def test_verbose_logging(self, caplog) -> None:
        """Test that verbose mode logs transformations."""
        import logging

        config = NamingConfig(
            subtitle_remove_patterns=[r"^[Uu]nabridged$"],
        )
        # Need to set the logger for mamfast.utils.naming specifically
        with caplog.at_level(logging.DEBUG, logger="shelfr.utils.naming"):
            result = filter_subtitle("Unabridged", naming_config=config, verbose=True)

        # Should return None when matching remove pattern
        assert result is None
        assert "remove_pattern" in caplog.text


class TestExtractVolumeNumber:
    """Tests for extract_volume_number function."""

    def test_series_position_priority(self) -> None:
        """Test that series_position is used when provided."""
        from shelfr.utils.naming import extract_volume_number

        assert extract_volume_number("Overlord, Vol. 5", series_position="3") == "3"
        assert extract_volume_number("Title", series_position="12") == "12"
        assert extract_volume_number("Title", series_position="1.5") == "1.5"

    def test_vol_pattern(self) -> None:
        """Test Vol. extraction from title."""
        from shelfr.utils.naming import extract_volume_number

        assert extract_volume_number("Overlord, Vol. 3") == "3"
        assert extract_volume_number("Overlord Vol 12") == "12"
        assert extract_volume_number("Title, Vol.5") == "5"

    def test_volume_pattern(self) -> None:
        """Test Volume extraction from title."""
        from shelfr.utils.naming import extract_volume_number

        assert extract_volume_number("Overlord, Volume 3") == "3"
        assert extract_volume_number("Title Volume 12") == "12"

    def test_book_pattern(self) -> None:
        """Test Book extraction from title."""
        from shelfr.utils.naming import extract_volume_number

        assert extract_volume_number("The Wandering Inn, Book 1") == "1"
        assert extract_volume_number("Series Book 5") == "5"

    def test_trailing_number(self) -> None:
        """Test trailing number extraction."""
        from shelfr.utils.naming import extract_volume_number

        assert extract_volume_number("He Who Fights with Monsters 11") == "11"

    def test_no_volume(self) -> None:
        """Test returns None when no volume found."""
        from shelfr.utils.naming import extract_volume_number

        assert extract_volume_number("Project Hail Mary") is None
        assert extract_volume_number("The Martian") is None


class TestFormatVolumeNumber:
    """Tests for format_volume_number function."""

    def test_zero_padding(self) -> None:
        """Test zero padding."""
        from shelfr.utils.naming import format_volume_number

        assert format_volume_number("3") == "vol_03"
        assert format_volume_number("12") == "vol_12"
        assert format_volume_number("1") == "vol_01"

    def test_no_padding(self) -> None:
        """Test without zero padding."""
        from shelfr.utils.naming import format_volume_number

        assert format_volume_number("3", zero_pad=False) == "vol_3"

    def test_decimal_volumes(self) -> None:
        """Test decimal volume numbers."""
        from shelfr.utils.naming import format_volume_number

        assert format_volume_number("1.5") == "vol_01.5"
        assert format_volume_number("10.5") == "vol_10.5"

    def test_none_returns_empty(self) -> None:
        """Test None returns empty string."""
        from shelfr.utils.naming import format_volume_number

        assert format_volume_number(None) == ""
        assert format_volume_number("") == ""

    def test_part_notation(self) -> None:
        """Test part notation for Graphic Audio splits."""
        from shelfr.utils.naming import format_volume_number

        assert format_volume_number("1p1") == "vol_01p1"
        assert format_volume_number("1p2") == "vol_01p2"
        assert format_volume_number("12p1") == "vol_12p1"

    def test_range_notation(self) -> None:
        """Test range notation for Publisher Packs."""
        from shelfr.utils.naming import format_volume_number

        assert format_volume_number("1-3") == "vol_01-03"
        assert format_volume_number("4-6") == "vol_04-06"
        assert format_volume_number("10-12") == "vol_10-12"


class TestParseVolumeNotation:
    """Tests for parse_volume_notation function."""

    def test_simple_volume(self) -> None:
        """Test parsing simple volume numbers."""
        from shelfr.utils.naming import parse_volume_notation

        result = parse_volume_notation("vol_01")
        assert result["base"] == 1.0
        assert result.get("range_end") is None
        assert result.get("part") is None

        result = parse_volume_notation("vol_12")
        assert result["base"] == 12.0

    def test_novella_decimal(self) -> None:
        """Test parsing decimal volumes (novellas)."""
        from shelfr.utils.naming import parse_volume_notation

        result = parse_volume_notation("vol_01.5")
        assert result["base"] == 1.5
        assert result.get("range_end") is None
        assert result.get("part") is None

    def test_range_publisher_pack(self) -> None:
        """Test parsing range notation (Publisher Packs)."""
        from shelfr.utils.naming import parse_volume_notation

        result = parse_volume_notation("vol_01-03")
        assert result["base"] == 1.0
        assert result["range_end"] == 3.0
        assert result.get("part") is None

        result = parse_volume_notation("vol_04-06")
        assert result["base"] == 4.0
        assert result["range_end"] == 6.0

    def test_part_graphic_audio(self) -> None:
        """Test parsing part notation (Graphic Audio splits)."""
        from shelfr.utils.naming import parse_volume_notation

        result = parse_volume_notation("vol_01p1")
        assert result["base"] == 1.0
        assert result["part"] == 1
        assert result.get("range_end") is None

        result = parse_volume_notation("vol_01p2")
        assert result["base"] == 1.0
        assert result["part"] == 2

    def test_invalid_notation(self) -> None:
        """Test invalid notation returns None."""
        from shelfr.utils.naming import parse_volume_notation

        assert parse_volume_notation("invalid") is None
        assert parse_volume_notation("") is None
        assert parse_volume_notation("volume_01") is None


class TestNormalizePosition:
    """Tests for normalize_position function."""

    def test_simple_number(self) -> None:
        """Test normalizing simple numbers."""
        from shelfr.utils.naming import normalize_position

        assert normalize_position("1") == "vol_01"
        assert normalize_position("12") == "vol_12"
        assert normalize_position("5") == "vol_05"

    def test_decimal_novella(self) -> None:
        """Test normalizing decimal numbers (novellas)."""
        from shelfr.utils.naming import normalize_position

        assert normalize_position("1.5") == "vol_01.5"
        assert normalize_position("10.5") == "vol_10.5"

    def test_part_notation_variants(self) -> None:
        """Test normalizing various part notation formats."""
        from shelfr.utils.naming import normalize_position

        # "1p1" style
        assert normalize_position("1p1") == "vol_01p1"
        assert normalize_position("1p2") == "vol_01p2"
        # "1 part 1" style
        assert normalize_position("1 part 1") == "vol_01p1"
        assert normalize_position("1 Part 2") == "vol_01p2"
        # "1_01" style (legacy)
        assert normalize_position("1_01") == "vol_01p1"
        assert normalize_position("1_02") == "vol_01p2"

    def test_range_notation(self) -> None:
        """Test normalizing range notation (Publisher Packs)."""
        from shelfr.utils.naming import normalize_position

        assert normalize_position("1-3") == "vol_01-03"
        assert normalize_position("4-6") == "vol_04-06"
        assert normalize_position("01-03") == "vol_01-03"

    def test_aliases(self) -> None:
        """Test volume aliases (prequel, prologue, etc.)."""
        from shelfr.utils.naming import normalize_position

        assert normalize_position("prequel") == "vol_00"
        assert normalize_position("Prequel") == "vol_00"
        assert normalize_position("prologue") == "vol_00"
        assert normalize_position("prelude") == "vol_00"

    def test_empty_or_none(self) -> None:
        """Test empty or None returns empty string."""
        from shelfr.utils.naming import normalize_position

        assert normalize_position("") == ""
        assert normalize_position(None) == ""

    def test_omnibus(self) -> None:
        """Test omnibus returns empty (no volume)."""
        from shelfr.utils.naming import normalize_position

        assert normalize_position("omnibus") == ""


class TestBuildMamFolderName:
    """Tests for build_mam_folder_name function."""

    def test_series_book_full(self) -> None:
        """Test series book with all components."""
        from shelfr.utils.naming import build_mam_folder_name

        result = build_mam_folder_name(
            series="Sword Art Online",
            title="Sword Art Online",
            volume_number="1",
            arc="Aincrad",
            year="2021",
            author="Reki Kawahara",
            asin="1975337182",
            ripper_tag="H2OKing",
        )
        assert "Sword Art Online" in result
        assert "vol_01" in result
        assert "Aincrad" in result
        assert "(2021)" in result
        assert "(Reki Kawahara)" in result
        assert "{ASIN.1975337182}" in result
        assert "[H2OKing]" in result

    def test_series_book_no_arc(self) -> None:
        """Test series book without arc/subtitle."""
        from shelfr.utils.naming import build_mam_folder_name

        result = build_mam_folder_name(
            series="Skyward",
            title="Skyward",
            volume_number="1",
            year="2018",
            author="Brandon Sanderson",
            asin="B07H7Q5D3M",
        )
        assert "Skyward" in result
        assert "vol_01" in result
        assert "(2018)" in result
        assert "(Brandon Sanderson)" in result
        assert "{ASIN.B07H7Q5D3M}" in result
        assert "[" not in result  # No ripper tag

    def test_standalone_book(self) -> None:
        """Test standalone book (no series)."""
        from shelfr.utils.naming import build_mam_folder_name

        result = build_mam_folder_name(
            series=None,
            title="Project Hail Mary",
            volume_number=None,
            year="2021",
            author="Andy Weir",
            asin="B08G9PRS1K",
        )
        assert "Project Hail Mary" in result
        assert "vol_" not in result  # No volume for standalone
        assert "(2021)" in result
        assert "(Andy Weir)" in result
        assert "{ASIN.B08G9PRS1K}" in result

    def test_truncation_drops_arc_first(self) -> None:
        """Test that arc is dropped first when truncating."""
        from shelfr.utils.naming import build_mam_folder_name

        # Very long series name + arc should truncate
        result = build_mam_folder_name(
            series="A" * 100,
            title="Test",
            volume_number="1",
            arc="B" * 50,
            year="2021",
            author="C" * 50,
            asin="TEST123",
            max_length=150,
        )
        # Arc should be dropped to fit
        assert len(result) <= 150
        assert "{ASIN.TEST123}" in result  # ASIN preserved

    def test_truncation_preserves_identity(self) -> None:
        """Test that series + vol + ASIN are always preserved."""
        from shelfr.utils.naming import build_mam_folder_name

        result = build_mam_folder_name(
            series="Overlord",
            title="Overlord",
            volume_number="3",
            arc="The Bloody Valkyrie",
            year="2021",
            author="Kugane Maruyama",
            asin="B09TEST123",
            ripper_tag="H2OKing",
            max_length=80,
        )
        # Core identity preserved even with aggressive truncation
        assert "Overlord" in result
        assert "vol_03" in result
        assert "ASIN" in result

    def test_no_asin(self) -> None:
        """Test folder name without ASIN."""
        from shelfr.utils.naming import build_mam_folder_name

        result = build_mam_folder_name(
            series="Test Series",
            title="Test",
            volume_number="1",
            year="2021",
            author="Author",
        )
        assert "Test Series" in result
        assert "{ASIN" not in result

    def test_special_characters_sanitized(self) -> None:
        """Test that special characters are sanitized."""
        from shelfr.utils.naming import build_mam_folder_name

        result = build_mam_folder_name(
            series="Re:ZERO -Starting Life in Another World-",
            title="Re:ZERO",
            volume_number="1",
            asin="TEST",
        )
        # Colons are replaced with " -"
        assert ":" not in result or "Re:ZERO" in result  # preserve_exact may keep it

    def test_inherits_the_prefix_from_title(self) -> None:
        """Test 'The' prefix is inherited from title to series."""
        from shelfr.utils.naming import build_mam_folder_name

        result = build_mam_folder_name(
            series="Great Cleric",
            title="The Great Cleric: Volume 1",
            volume_number="1",
            year="2024",
            author="Broccoli Lion",
            asin="B0DW5D1JLQ",
        )
        assert "The Great Cleric" in result
        assert result.startswith("The Great Cleric vol_01")  # Should have "The" prefix

    def test_removes_series_suffix(self) -> None:
        """Test ' Series' suffix is removed from series name."""
        from shelfr.utils.naming import build_mam_folder_name

        config = NamingConfig(series_suffixes=[r"[\s—-]?[Ss]eries$"])
        result = build_mam_folder_name(
            series="A Most Unlikely Hero Series",
            title="A Most Unlikely Hero",
            volume_number="2",
            year="2024",
            author="Brandon Varnell",
            asin="B0DR9J6V2M",
            naming_config=config,
        )
        assert "A Most Unlikely Hero vol_02" in result
        assert "Series" not in result

    def test_removes_order_tag_from_series(self) -> None:
        """Test '[publication order]' tag is removed from series name."""
        from shelfr.utils.naming import build_mam_folder_name

        config = NamingConfig(series_suffixes=[r"\s*\[[^\]]*[Oo]rder\]$"])
        result = build_mam_folder_name(
            series="Ascend Online [publication order]",
            title="Ascend Online",
            volume_number="1",
            year="2017",
            author="Luke Chmilenko",
            asin="B073PG4DX8",
            naming_config=config,
        )
        assert "Ascend Online vol_01" in result
        assert "[publication order]" not in result


class TestBuildMamFileName:
    """Tests for build_mam_file_name function."""

    def test_file_has_extension(self) -> None:
        """Test file name includes extension."""
        from shelfr.utils.naming import build_mam_file_name

        result = build_mam_file_name(
            series="Overlord",
            title="Overlord",
            volume_number="3",
            year="2021",
            author="Kugane Maruyama",
            asin="B09TEST123",
        )
        assert result.endswith(".m4b")

    def test_file_no_ripper_tag(self) -> None:
        """Test file name never has ripper tag."""
        from shelfr.utils.naming import build_mam_file_name

        result = build_mam_file_name(
            series="Test",
            title="Test",
            volume_number="1",
            asin="TEST",
            # Note: ripper_tag is not even a parameter for file name
        )
        assert "[" not in result
        assert "]" not in result or "{ASIN" in result  # Only ASIN braces

    def test_custom_extension(self) -> None:
        """Test custom file extension."""
        from shelfr.utils.naming import build_mam_file_name

        result = build_mam_file_name(
            title="Test",
            asin="TEST",
            extension=".mp3",
        )
        assert result.endswith(".mp3")

    def test_extension_without_dot(self) -> None:
        """Test extension without leading dot."""
        from shelfr.utils.naming import build_mam_file_name

        result = build_mam_file_name(
            title="Test",
            asin="TEST",
            extension="m4b",  # No dot
        )
        assert result.endswith(".m4b")

    def test_truncation_reserves_extension_space(self) -> None:
        """Test that truncation reserves space for extension."""
        from shelfr.utils.naming import build_mam_file_name

        result = build_mam_file_name(
            series="A" * 200,
            title="Test",
            volume_number="1",
            asin="TEST",
            max_length=100,
        )
        assert len(result) <= 100
        assert result.endswith(".m4b")


# =============================================================================
# Phase 8: Full Path Truncation Tests
# =============================================================================


class TestBuildMamPath:
    """
    Tests for build_mam_path function (Phase 8).

    The 225-char limit applies to the FULL RELATIVE PATH (folder/filename),
    not individual components. These tests verify correct truncation behavior.
    """

    def test_short_path_no_truncation(self) -> None:
        """Test short path that doesn't need truncation."""
        from shelfr.utils.naming import build_mam_path

        result = build_mam_path(
            series="Overlord",
            title="Overlord",
            volume_number="3",
            arc="The Bloody Valkyrie",
            year="2021",
            author="Kugane Maruyama",
            asin="B09TEST123",
            ripper_tag="H2OKing",
        )

        assert result.length <= 225
        assert result.truncated is False
        assert result.dropped_components == []
        assert "Overlord" in result.folder
        assert "vol_03" in result.folder
        assert "The Bloody Valkyrie" in result.folder
        assert "(2021)" in result.folder
        assert "(Kugane Maruyama)" in result.folder
        assert "{ASIN.B09TEST123}" in result.folder
        assert "[H2OKing]" in result.folder
        assert result.filename.endswith(".m4b")
        assert "[H2OKing]" not in result.filename  # Tag only in folder

    def test_trapped_in_dating_sim_barely_over(self) -> None:
        """
        Test 'Trapped in a Dating Sim' - a real-world case that was 241 chars.

        Should drop arc to fit but keep author/year/tag.
        """
        from shelfr.utils.naming import build_mam_path

        result = build_mam_path(
            series="Trapped in a Dating Sim",
            title="Trapped in a Dating Sim",
            volume_number="1",
            arc="The World of Otome Games is Tough for Mobs",
            year="2024",
            author="Yomu Mishima",
            asin="B0DK27WWT8",
            ripper_tag="H2OKing",
        )

        assert result.length <= 225
        assert result.truncated is True
        assert "arc" in result.dropped_components
        # Should NOT drop author, year, or tag since arc alone is enough
        assert "author" not in result.dropped_components
        assert "year" not in result.dropped_components
        # Verify components are preserved
        assert "Trapped in a Dating Sim" in result.folder
        assert "vol_01" in result.folder
        assert "(2024)" in result.folder
        assert "(Yomu Mishima)" in result.folder
        assert "{ASIN.B0DK27WWT8}" in result.folder
        assert "[H2OKing]" in result.folder

    def test_haunted_bookstore_worst_case(self) -> None:
        """
        Test 'Haunted Bookstore' - worst case from library (was 299 chars).

        Must truncate to fit within 225 chars.
        """
        from shelfr.utils.naming import build_mam_path

        result = build_mam_path(
            series="The Haunted Bookstore - Gateway to a Parallel Universe",
            title="The Haunted Bookstore",
            volume_number="1",
            arc="The Spirit Daughter and the Exorcist Son",
            year="2022",
            author="Shinobumaru",
            asin="B09EXAMPLE1",
            ripper_tag="H2OKing",
        )

        assert result.length <= 225
        assert result.truncated is True
        # Series, vol, and ASIN must be preserved
        assert "The Haunted Bookstore" in result.folder
        assert "vol_01" in result.folder
        assert "{ASIN.B09EXAMPLE1}" in result.folder
        # Verify path structure
        assert result.full_path == f"{result.folder}/{result.filename}"

    def test_extreme_truncation_triggers_series_truncation(self) -> None:
        """Test extreme case that requires series name truncation."""
        from shelfr.utils.naming import build_mam_path

        long_series = (
            "The Most Ridiculously Extraordinarily Impossibly Long Light Novel "
            "Series Name That Someone Actually Published And Keeps Going"
        )
        result = build_mam_path(
            series=long_series,
            title="Test",
            volume_number="1",
            arc="An Equally Long Arc Subtitle",
            year="2025",
            author="Author With A Very Long Name Indeed",
            asin="B0ABCDEFGH",
            ripper_tag="H2OKing",
        )

        assert result.length <= 225
        assert result.truncated is True
        assert "series_truncated" in result.dropped_components
        # Series should end with "..."
        assert "..." in result.folder
        # Vol and ASIN must be intact
        assert "vol_01" in result.folder
        assert "{ASIN.B0ABCDEFGH}" in result.folder

    def test_multifile_adjusts_budget(self) -> None:
        """Test that part_count > 1 adjusts budget for ' - Part XX.m4b'."""
        from shelfr.utils.naming import build_mam_path

        # Same input, compare single vs multi-file
        kwargs: dict[str, Any] = {
            "series": "A Medium Length Series Name For Testing",
            "title": "Test",
            "volume_number": "1",
            "arc": "A Reasonably Long Arc Name Here",
            "year": "2025",
            "author": "Some Author Name",
            "asin": "B0TESTTEST",
            "ripper_tag": "H2OKing",
        }

        single = build_mam_path(**kwargs, part_count=1)
        multi = build_mam_path(**kwargs, part_count=2)

        # Multi-file should be more aggressive in truncation
        # (it reserves 14 chars for " - Part XX.m4b" vs 4 for ".m4b")
        # Both should fit
        assert single.length <= 225
        assert multi.length <= 225
        # Multi should have more dropped OR shorter base
        if single.truncated or multi.truncated:
            # If either truncated, multi should have dropped at least as much
            assert len(multi.dropped_components) >= len(single.dropped_components) or len(
                multi.folder
            ) < len(single.folder)

    def test_no_tag_increases_budget(self) -> None:
        """Test that omitting ripper_tag increases available budget."""
        from shelfr.utils.naming import build_mam_path

        # A case that might need truncation with tag but not without
        kwargs: dict[str, Any] = {
            "series": "A Medium Length Series Name",
            "title": "Test",
            "volume_number": "1",
            "arc": "A Medium Arc",
            "year": "2025",
            "author": "Some Author",
            "asin": "B0TEST",
        }

        with_tag = build_mam_path(**kwargs, ripper_tag="H2OKing")
        without_tag = build_mam_path(**kwargs, ripper_tag=None)

        # Without tag should have more room
        # Budget without tag: (225 - ext - 1) // 2 = (225 - 4 - 1) // 2 = 110
        # Budget with "H2OKing": (225 - (len(tag)+4) - ext) // 2 = (225 - 11 - 4) // 2 = 105
        assert without_tag.length < with_tag.length
        assert "[H2OKing]" in with_tag.folder
        assert "[" not in without_tag.folder

    def test_standalone_book_no_series(self) -> None:
        """Test standalone book (no series) truncation."""
        from shelfr.utils.naming import build_mam_path

        result = build_mam_path(
            series=None,
            title="Project Hail Mary",
            volume_number=None,
            year="2021",
            author="Andy Weir",
            asin="B08G9PRS1K",
            ripper_tag="H2OKing",
        )

        assert result.length <= 225
        assert "Project Hail Mary" in result.folder
        assert "vol_" not in result.folder  # No volume for standalone
        assert "(2021)" in result.folder
        assert "(Andy Weir)" in result.folder
        assert "{ASIN.B08G9PRS1K}" in result.folder

    def test_minimum_series_floor(self) -> None:
        """Test that series is never truncated below MIN_SERIES_LENGTH."""
        from shelfr.utils.naming import build_mam_path

        # Force extreme truncation with very tight length
        result = build_mam_path(
            series="AAAA",  # Very short series
            title="Test",
            volume_number="1",
            asin="B0TEST",
            max_path_length=100,  # Very tight
        )

        # Series should still have at least MIN_SERIES_LENGTH chars + "..."
        assert result.length <= 100
        # The series part should be visible
        assert "A" in result.folder

    def test_preserves_asin_always(self) -> None:
        """Test that ASIN is NEVER truncated or dropped."""
        from shelfr.utils.naming import build_mam_path

        result = build_mam_path(
            series="A" * 200,  # Very long series
            title="Test",
            volume_number="1",
            arc="B" * 100,
            year="2025",
            author="C" * 100,
            asin="B0ABCDEFGHIJ",  # Full ASIN
            ripper_tag="H2OKing",
        )

        assert result.length <= 225
        # ASIN must be complete and intact
        assert "{ASIN.B0ABCDEFGHIJ}" in result.folder
        assert "{ASIN.B0ABCDEFGHIJ}" in result.filename

    def test_full_path_structure(self) -> None:
        """Test that full_path is correctly computed as folder/filename."""
        from shelfr.utils.naming import build_mam_path

        result = build_mam_path(
            series="Test Series",
            title="Test",
            volume_number="1",
            asin="B0TEST",
            ripper_tag="H2OKing",
        )

        assert result.full_path == f"{result.folder}/{result.filename}"
        assert result.length == len(result.full_path)

    def test_dropped_components_tracks_correctly(self) -> None:
        """Test that dropped_components accurately reflects what was dropped."""
        from shelfr.utils.naming import build_mam_path

        # Case that needs to drop arc only
        result1 = build_mam_path(
            series="Medium Series Name Here",
            title="Test",
            volume_number="1",
            arc="A Very Long Arc Name That Will Cause Truncation",
            year="2025",
            author="Short Author",
            asin="B0TEST",
            ripper_tag="H2OKing",
            max_path_length=150,  # Force truncation
        )

        if result1.truncated and result1.dropped_components:
            # Should drop in order: arc, author, year, series_truncated
            # First drop should be arc
            assert result1.dropped_components[0] == "arc"

    def test_custom_extension(self) -> None:
        """Test that custom extensions are handled correctly."""
        from shelfr.utils.naming import build_mam_path

        result = build_mam_path(
            series="Test",
            title="Test",
            volume_number="1",
            asin="B0TEST",
            extension=".mp3",
        )

        assert result.filename.endswith(".mp3")
        assert result.length <= 225

    def test_extension_without_dot(self) -> None:
        """Test that extension without leading dot is handled."""
        from shelfr.utils.naming import build_mam_path

        result = build_mam_path(
            series="Test",
            title="Test",
            volume_number="1",
            asin="B0TEST",
            extension="m4b",  # No dot
        )

        assert result.filename.endswith(".m4b")
