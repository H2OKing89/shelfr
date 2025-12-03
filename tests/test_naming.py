"""Tests for naming utilities."""

from mamfast.config import FiltersConfig, NamingConfig
from mamfast.utils.naming import (
    build_release_dirname,
    ensure_unique_name,
    extract_translator,
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


class TestFilterTitleWithNamingConfig:
    """Tests for filter_title with NamingConfig."""

    def test_removes_format_indicators(self):
        """Test removing format indicators from NamingConfig."""
        config = NamingConfig(format_indicators=["(Light Novel)", "Unabridged"])
        result = filter_title("Overlord (Light Novel)", naming_config=config)
        assert result == "Overlord"

    def test_removes_genre_tags(self):
        """Test removing genre tags from NamingConfig."""
        config = NamingConfig(genre_tags=["A LitRPG Adventure"])
        result = filter_title("Dungeon Crawler Carl A LitRPG Adventure", naming_config=config)
        assert result == "Dungeon Crawler Carl"

    def test_removes_publisher_tags(self):
        """Test removing publisher tags from NamingConfig."""
        config = NamingConfig(publisher_tags=["[Yen Audio]", "(J-Novel Club)"])
        result = filter_title("Sword Art Online [Yen Audio]", naming_config=config)
        assert result == "Sword Art Online"

    def test_removes_multiple_categories(self):
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

    def test_case_insensitive_matching(self):
        """Test that matching is case-insensitive."""
        config = NamingConfig(format_indicators=["(Light Novel)"])
        result = filter_title("Overlord (light novel)", naming_config=config)
        assert result == "Overlord"

    def test_backward_compatibility_with_remove_phrases(self):
        """Test that legacy remove_phrases still works."""
        result = filter_title(
            "Title [Custom Tag]",
            remove_phrases=["[Custom Tag]"],
        )
        assert result == "Title"

    def test_combined_naming_config_and_remove_phrases(self):
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

    def test_preserves_exact_match(self):
        """Test exact match is preserved."""
        config = NamingConfig(
            format_indicators=["(Light Novel)"],
            preserve_exact=["Re:ZERO"],
        )
        # The colon would normally be problematic, but preserve_exact bypasses cleaning
        result = filter_title("Re:ZERO", naming_config=config)
        assert result == "Re:ZERO"

    def test_preserves_substring_match(self):
        """Test substring match is preserved."""
        config = NamingConfig(
            format_indicators=["(Light Novel)"],
            preserve_exact=["Re:ZERO"],
        )
        result = filter_title("Re:ZERO (Light Novel)", naming_config=config)
        # Should preserve because "Re:ZERO" is in the input
        assert result == "Re:ZERO (Light Novel)"

    def test_preserves_86_eighty_six(self):
        """Test 86--EIGHTY-SIX is preserved."""
        config = NamingConfig(
            format_indicators=["(Light Novel)"],
            preserve_exact=["86--EIGHTY-SIX"],
        )
        result = filter_title("86--EIGHTY-SIX (Light Novel)", naming_config=config)
        assert result == "86--EIGHTY-SIX (Light Novel)"

    def test_preserves_sao_progressive(self):
        """Test Sword Art Online: Progressive is preserved."""
        config = NamingConfig(
            preserve_exact=["Sword Art Online: Progressive"],
        )
        result = filter_title("Sword Art Online: Progressive", naming_config=config)
        assert result == "Sword Art Online: Progressive"

    def test_non_preserved_still_cleaned(self):
        """Test non-preserved titles are still cleaned."""
        config = NamingConfig(
            format_indicators=["(Light Novel)"],
            preserve_exact=["Re:ZERO"],
        )
        result = filter_title("Overlord (Light Novel)", naming_config=config)
        assert result == "Overlord"


class TestFilterSeries:
    """Tests for filter_series function."""

    def test_removes_series_suffix(self):
        """Test removing ' Series' suffix."""
        config = NamingConfig(series_suffixes=[r"\s+[Ss]eries$"])
        result = filter_series("A Most Unlikely Hero Series", naming_config=config)
        assert result == "A Most Unlikely Hero"

    def test_removes_trilogy_suffix(self):
        """Test removing ' Trilogy' suffix."""
        config = NamingConfig(series_suffixes=[r"\s+[Tt]rilogy$"])
        result = filter_series("Epic Fantasy Trilogy", naming_config=config)
        assert result == "Epic Fantasy"

    def test_removes_light_novel_suffix(self):
        """Test removing ' Light Novel' suffix from series."""
        config = NamingConfig(series_suffixes=[r"\s+[Ll]ight [Nn]ovel$"])
        result = filter_series("Kuma Kuma Kuma Bear Light Novel", naming_config=config)
        assert result == "Kuma Kuma Kuma Bear"

    def test_removes_parenthetical_light_novel(self):
        """Test removing '(Light Novel)' suffix from series."""
        config = NamingConfig(series_suffixes=[r"\s*\([Ll]ight [Nn]ovel\)$"])
        result = filter_series("Overlord (Light Novel)", naming_config=config)
        assert result == "Overlord"

    def test_also_applies_format_indicators(self):
        """Test filter_series also removes format_indicators."""
        config = NamingConfig(
            format_indicators=["(Unabridged)"],
            series_suffixes=[r"\s+[Ss]eries$"],
        )
        result = filter_series("Hero Series (Unabridged)", naming_config=config)
        assert result == "Hero"

    def test_preserves_non_suffix_series(self):
        """Test series without matching suffix is preserved."""
        config = NamingConfig(series_suffixes=[r"\s+[Ss]eries$"])
        result = filter_series("The Stormlight Archive", naming_config=config)
        assert result == "The Stormlight Archive"

    def test_preserve_exact_works_in_series(self):
        """Test preserve_exact also works in filter_series."""
        config = NamingConfig(
            series_suffixes=[r"\s+[Ss]eries$"],
            preserve_exact=["Re:ZERO"],
        )
        result = filter_series("Re:ZERO Series", naming_config=config)
        # Should preserve because "Re:ZERO" is in preserve_exact
        assert result == "Re:ZERO Series"

    def test_multiple_suffix_patterns(self):
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

    def test_invalid_regex_handled_gracefully(self):
        """Test invalid regex patterns don't crash."""
        config = NamingConfig(series_suffixes=[r"[invalid(regex"])
        # Should not raise, just skip the bad pattern
        result = filter_series("Test Series", naming_config=config)
        assert result == "Test Series"


class TestFilterTitleKeepVolume:
    """Tests for the keep_volume parameter in filter_title.

    Phase 3: MAM JSON keeps Vol. X human-readable, folders use vol_XX.
    """

    def test_default_removes_volume(self):
        """Test that Vol. X is removed by default (for folder names)."""
        result = filter_title("Overlord, Vol. 3")
        assert "Vol. 3" not in result
        assert "Overlord" in result

    def test_keep_volume_true_preserves_vol(self):
        """Test that keep_volume=True preserves Vol. X (for JSON)."""
        result = filter_title("Overlord, Vol. 3", keep_volume=True)
        assert "Vol. 3" in result
        assert "Overlord" in result

    def test_keep_volume_preserves_volume_word(self):
        """Test that keep_volume=True also preserves Volume X."""
        result = filter_title("Overlord, Volume 12", keep_volume=True)
        assert "Volume 12" in result

    def test_keep_volume_removes_format_indicators(self):
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

    def test_keep_volume_still_removes_book(self):
        """Test that Book X is still removed (we normalize to Vol.)."""
        result = filter_title("Title, Book 5", keep_volume=True)
        # "Book 5" should still be removed (hardcoded pattern)
        assert "Book 5" not in result


class TestFilterSeriesKeepVolume:
    """Tests for the keep_volume parameter in filter_series."""

    def test_default_removes_volume(self):
        """Test that Vol. X is removed by default from series."""
        config = NamingConfig()
        result = filter_series("Overlord, Vol. 3", naming_config=config)
        assert "Vol. 3" not in result

    def test_keep_volume_true_in_series(self):
        """Test keep_volume parameter is passed through filter_series."""
        config = NamingConfig()
        result = filter_series("Overlord, Vol. 3", naming_config=config, keep_volume=True)
        assert "Vol. 3" in result

    def test_series_suffixes_still_applied_with_keep_volume(self):
        """Test that series suffixes are applied regardless of keep_volume."""
        config = NamingConfig(series_suffixes=[r"\s+[Ss]eries$"])
        result = filter_series("Epic Vol. 2 Series", naming_config=config, keep_volume=True)
        # Vol. 2 kept, but "Series" suffix removed
        assert "Vol. 2" in result
        assert result.endswith("Series") is False


class TestFilterSubtitle:
    """Tests for the filter_subtitle function."""

    def test_empty_subtitle_returns_none(self):
        """Test that empty/whitespace subtitles return None."""

        assert filter_subtitle("") is None
        assert filter_subtitle("   ") is None
        assert filter_subtitle(None) is None  # type: ignore[arg-type]

    def test_simple_subtitle_passes_through(self):
        """Test that normal subtitles pass through unchanged."""

        result = filter_subtitle("A Tale of Mystery")
        assert result == "A Tale of Mystery"

    def test_remove_patterns_drop_subtitle(self):
        """Test that matching remove_patterns drop the entire subtitle."""

        config = NamingConfig(subtitle_remove_patterns=[r"^[Ll]ight [Nn]ovel$", r"^[Uu]nabridged$"])
        assert filter_subtitle("Light Novel", naming_config=config) is None
        assert filter_subtitle("light novel", naming_config=config) is None
        assert filter_subtitle("Unabridged", naming_config=config) is None
        # But not partial matches
        assert filter_subtitle("The Light Novel Chronicles", naming_config=config) is not None

    def test_keep_patterns_preserve_subtitle(self):
        """Test that matching keep_patterns preserve the subtitle."""

        config = NamingConfig(
            subtitle_remove_patterns=[r"^.*Aria.*$"],
            subtitle_keep_patterns=[r".*[Aa]ria.*"],
        )
        # Without keep_pattern, would be removed by remove_pattern
        result = filter_subtitle("Aria of the Stars", naming_config=config)
        assert result == "Aria of the Stars"

    def test_series_match_drops_subtitle(self):
        """Test that subtitle matching series name is dropped."""

        config = NamingConfig(remove_subtitle_if_matches_series=True)
        result = filter_subtitle(
            "The Wandering Inn",
            series="The Wandering Inn",
            naming_config=config,
        )
        assert result is None

    def test_series_match_case_insensitive(self):
        """Test that series matching is case-insensitive."""

        config = NamingConfig(remove_subtitle_if_matches_series=True)
        result = filter_subtitle(
            "the wandering inn",
            series="The Wandering Inn",
            naming_config=config,
        )
        assert result is None

    def test_series_match_disabled(self):
        """Test that series matching can be disabled."""

        config = NamingConfig(remove_subtitle_if_matches_series=False)
        result = filter_subtitle(
            "The Wandering Inn",
            series="The Wandering Inn",
            naming_config=config,
        )
        assert result == "The Wandering Inn"

    def test_redundancy_rule_drop_subtitle(self):
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

    def test_redundancy_rule_strip_match(self):
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

    def test_redundancy_skips_rule_if_series_empty(self):
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

    def test_redundancy_rule_with_title(self):
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

    def test_redundancy_disabled(self):
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

    def test_preserve_exact_bypasses_all_rules(self):
        """Test that preserve_exact bypasses all subtitle filtering."""

        config = NamingConfig(
            subtitle_remove_patterns=[r"^[Ll]ight [Nn]ovel$"],
            preserve_exact=["Light Novel"],
        )
        # Would normally be removed, but preserved
        result = filter_subtitle("Light Novel", naming_config=config)
        assert result == "Light Novel"

    def test_strip_match_leaves_empty_drops_subtitle(self):
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

    def test_multiple_rules_applied_in_order(self):
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

    def test_cleanup_applied_to_result(self):
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

    def test_verbose_logging(self, caplog):
        """Test that verbose mode logs transformations."""
        import logging

        config = NamingConfig(
            subtitle_remove_patterns=[r"^[Uu]nabridged$"],
        )
        with caplog.at_level(logging.DEBUG):
            filter_subtitle("Unabridged", naming_config=config, verbose=True)

        assert "remove_pattern" in caplog.text
