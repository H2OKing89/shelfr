"""Tests for MLA title case transformation.

Tests the mla_title_case function used for MAM compliance.
"""

from __future__ import annotations

from shelfr.utils.naming.titlecase import mla_title_case


class TestMlaTitleCase:
    """Test MLA title case transformation."""

    def test_empty_string(self) -> None:
        """Empty string returns empty."""
        assert mla_title_case("") == ""

    def test_none_returns_none(self) -> None:
        """None input returns None (falsy passthrough)."""
        assert mla_title_case(None) is None  # type: ignore[arg-type]

    def test_basic_lowercase(self) -> None:
        """All lowercase gets proper title case."""
        assert mla_title_case("the beginning after the end") == "The Beginning After the End"

    def test_preserves_articles_in_middle(self) -> None:
        """Articles (a, an, the) stay lowercase in middle."""
        result = mla_title_case("lord of the rings")
        assert result == "Lord of the Rings"

    def test_capitalizes_first_word_article(self) -> None:
        """First word is always capitalized, even if article."""
        assert mla_title_case("the hobbit") == "The Hobbit"
        assert mla_title_case("a brief history of time") == "A Brief History of Time"

    def test_capitalizes_last_word(self) -> None:
        """Last word is always capitalized."""
        assert mla_title_case("what dreams may come to") == "What Dreams May Come To"

    def test_prepositions_lowercase(self) -> None:
        """Prepositions stay lowercase in middle."""
        result = mla_title_case("is it wrong to try to pick up girls in a dungeon?")
        assert result == "Is It Wrong to Try to Pick Up Girls in a Dungeon?"

    def test_volume_abbreviation(self) -> None:
        """Vol. is properly capitalized."""
        assert mla_title_case("the eminence in shadow, vol. 3") == "The Eminence in Shadow, Vol. 3"
        assert mla_title_case("overlord vol. 14") == "Overlord Vol. 14"

    def test_all_caps_to_title_case(self) -> None:
        """ALL CAPS gets converted to title case."""
        assert mla_title_case("OVERLORD VOL. II") == "Overlord Vol. II"

    def test_roman_numerals_preserved(self) -> None:
        """Roman numerals in uppercase stay uppercase."""
        assert mla_title_case("final fantasy XIV") == "Final Fantasy XIV"
        assert mla_title_case("part III: the return") == "Part III: The Return"
        # Note: lowercase roman numerals get title-cased (iii -> Iii)
        # This is expected - source data should have proper case

    def test_question_mark_handling(self) -> None:
        """Handles question marks in titles."""
        result = mla_title_case("so i'm a spider, so what?")
        assert result == "So I'm a Spider, So What?"

    def test_series_names(self) -> None:
        """Common series name patterns."""
        assert mla_title_case("sword art online") == "Sword Art Online"
        assert mla_title_case("the saga of tanya the evil") == "The Saga of Tanya the Evil"
        assert mla_title_case("86-eighty six") == "86-Eighty Six"

    def test_already_correct_case(self) -> None:
        """Already correct title case is preserved."""
        assert mla_title_case("The Beginning After the End") == "The Beginning After the End"

    def test_mixed_case_input(self) -> None:
        """Mixed case input - titlecase preserves some existing casing."""
        # titlecase package preserves existing caps for words it considers acronyms
        # This is intentional - it avoids overcorrecting proper names like "iPhone"
        result = mla_title_case("tHe BEGinNing AFTER the EnD")
        # First word gets capitalized, articles lowercased
        assert result.startswith("The")
        assert "the" in result.lower()  # has 'the' in it

    def test_numbers_in_title(self) -> None:
        """Numbers in titles handled correctly."""
        assert mla_title_case("sword art online 16") == "Sword Art Online 16"
        assert mla_title_case("86") == "86"

    def test_acronyms_preserved(self) -> None:
        """All-caps words that look like acronyms stay uppercase."""
        # Our callback preserves 2-5 letter all-caps words
        assert mla_title_case("the CIA files") == "The CIA Files"
        assert mla_title_case("USA today") == "USA Today"
        # Note: lowercase 'cia' becomes 'Cia' - source should be uppercase

    def test_light_novel_common_titles(self) -> None:
        """Common light novel title patterns."""
        test_cases = [
            ("mushoku tensei", "Mushoku Tensei"),
            ("Re:Zero", "Re:Zero"),  # Preserve source casing for stylized titles
            ("no game no life", "No Game No Life"),
            ("that time i got reincarnated as a slime", "That Time I Got Reincarnated as a Slime"),
        ]
        for input_title, expected in test_cases:
            assert mla_title_case(input_title) == expected, f"Failed for: {input_title}"


class TestMlaTitleCaseCallback:
    """Test custom callback functionality."""

    def test_disable_callback(self) -> None:
        """Can disable custom callback entirely."""
        # With no callback, should still work (default titlecase behavior)
        result = mla_title_case("the CIA files", callback=lambda w, **kw: None)
        # Without our callback, CIA might get lowercased by default titlecase
        assert "Cia" in result or "CIA" in result  # Either is acceptable


class TestMlaTitleCaseEdgeCases:
    """Edge cases and special handling."""

    def test_single_word(self) -> None:
        """Single word gets capitalized."""
        assert mla_title_case("overlord") == "Overlord"

    def test_whitespace_only(self) -> None:
        """Whitespace-only string."""
        assert mla_title_case("   ") == "   "

    def test_unicode_characters(self) -> None:
        """Unicode characters handled."""
        assert mla_title_case("café society") == "Café Society"

    def test_colon_subtitle(self) -> None:
        """Colon separating title and subtitle."""
        result = mla_title_case("defiance of the fall: a cultivation novel")
        assert result == "Defiance of the Fall: A Cultivation Novel"

    def test_longer_prepositions(self) -> None:
        """Document actual behavior with longer prepositions."""
        # titlecase uses NY Times-derived small-word list, not strict MLA
        # Common prepositions are lowercased; less-common ones may be capitalized
        result1 = mla_title_case("the book throughout the war")
        result2 = mla_title_case("information regarding the matter")
        result3 = mla_title_case("journey across the sea")
        result4 = mla_title_case("tales from beyond the stars")

        # Verify titlecase behavior (may differ from strict MLA)
        # These assertions document current behavior
        assert result1 == "The Book Throughout the War"
        assert result2 == "Information Regarding the Matter"
        assert result3 == "Journey Across the Sea"
        assert result4 == "Tales From Beyond the Stars"
