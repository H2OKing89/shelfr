"""MLA-style title case transformation for MAM compliance and general use.

This module applies MLA-style title case via the `titlecase` package with
audiobook-specific customizations (Roman numerals, abbreviations, acronyms).

MAM explicitly requires MLA-style title case for English-language audiobook titles,
subtitles, and series names.

Core Rules (titlecase package with NY Times-derived small-word list):
- Capitalize the first word and the last word
- Capitalize nouns, pronouns, verbs, adjectives, adverbs, subordinating conjunctions
- Do NOT capitalize articles (a, an, the)
- Do NOT capitalize prepositions (via titlecase small-word list)
- Do NOT capitalize coordinating conjunctions (and, but, or, nor)
- Do NOT capitalize "to" in infinitives
- Capitalize principal words after hyphens

Note: The titlecase package uses NY Times-derived rules, not strict MLA.
For strict MLA compliance, all prepositions would be lowercased; titlecase
lowercases common prepositions but may capitalize less-common ones.

References:
- https://titlecaseconverter.com/ (online converter with MLA option)
- https://style.mla.org (MLA Style Center)
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import cast

from titlecase import titlecase as _titlecase  # type: ignore[import-untyped]

__all__ = ["mla_title_case"]

# Custom callback to preserve certain patterns
# The titlecase package allows a callback for special handling


def _shelfr_callback(word: str, **kwargs: object) -> str | None:
    """Custom callback for shelfr-specific title case handling.

    Returns the word as-is for special cases, or None to use default behavior.

    Special handling:
    - Preserve Roman numerals (I, II, III, IV, V, VI, VII, VIII, IX, X, etc.)
    - Preserve common audiobook abbreviations (Vol., Bk., Pt., No.)
    - Preserve all-caps acronyms (USA, FBI, CIA, etc.)
    """
    word_upper = word.upper()

    # Roman numerals - preserve as uppercase
    roman_pattern = r"^M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$"
    if re.match(roman_pattern, word_upper):
        return word_upper

    # MAM-convention volume tokens (vol_01, vol_01_02, vol_01p2) — preserve
    # as lowercase since these are structured tokens, not natural-language
    # words.  Must be checked BEFORE the abbreviation map so "vol_01" is
    # not partially matched as "Vol".
    if re.match(r"^vol[_.]\d+", word, re.IGNORECASE):
        return word.lower()

    # Common audiobook volume/part indicators - standardize capitalization
    abbrev_map = {
        "VOL": "Vol",
        "VOL.": "Vol.",
        "BK": "Bk",
        "BK.": "Bk.",
        "PT": "Pt",
        "PT.": "Pt.",
        "NO": "No",
        "NO.": "No.",
    }
    if word_upper in abbrev_map:
        return abbrev_map[word_upper]

    # Preserve likely acronyms (2-5 uppercase letters)
    if re.match(r"^[A-Z]{2,5}$", word):
        return word

    # Let titlecase handle everything else
    return None


def mla_title_case(text: str, callback: Callable[..., str | None] | None = None) -> str:
    """Apply MLA title case rules to text.

    Uses the well-tested `titlecase` package with shelfr-specific customizations
    for audiobook metadata handling (Roman numerals, Vol., acronyms).

    Args:
        text: The text to transform.
        callback: Optional custom callback. If None, uses shelfr defaults.
                  Pass `lambda w, **kw: None` to disable all custom handling.

    Returns:
        The text in MLA title case.

    Examples:
        >>> mla_title_case("the beginning after the end")
        'The Beginning After the End'

        >>> mla_title_case("is it wrong to try to pick up girls in a dungeon?")
        'Is It Wrong to Try to Pick Up Girls in a Dungeon?'

        >>> mla_title_case("the eminence in shadow, vol. 3")
        'The Eminence in Shadow, Vol. 3'

        >>> mla_title_case("sword art online 16")
        'Sword Art Online 16'

    Can be used for:
        - MAM JSON title/subtitle (required)
        - MAM series names (required)
        - ABS metadata (optional)
        - Any export format requiring proper capitalization
    """
    if not text:
        return text

    # Use provided callback or default shelfr callback
    cb = callback if callback is not None else _shelfr_callback

    return cast(str, _titlecase(text, callback=cb))
