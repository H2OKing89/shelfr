"""
Language and field mappings for OPF generation.

Provides ISO 639-2/B language code conversion and other
normalization utilities for OPF metadata.
"""

from __future__ import annotations

# ISO 639-2/B three-letter language codes
# Mapping from common names/variations to standard codes
# See: https://www.loc.gov/standards/iso639-2/php/code_list.php
LANGUAGE_TO_ISO: dict[str, str] = {
    # English variations
    "english": "eng",
    "en": "eng",
    "en-us": "eng",
    "en-gb": "eng",
    "en-au": "eng",
    "eng": "eng",
    # German
    "german": "ger",
    "deutsch": "ger",
    "de": "ger",
    "deu": "ger",
    "ger": "ger",
    # French
    "french": "fre",
    "français": "fre",
    "francais": "fre",
    "fr": "fre",
    "fra": "fre",
    "fre": "fre",
    # Spanish
    "spanish": "spa",
    "español": "spa",
    "espanol": "spa",
    "es": "spa",
    "spa": "spa",
    # Italian
    "italian": "ita",
    "italiano": "ita",
    "it": "ita",
    "ita": "ita",
    # Japanese
    "japanese": "jpn",
    "日本語": "jpn",
    "ja": "jpn",
    "jpn": "jpn",
    # Portuguese
    "portuguese": "por",
    "português": "por",
    "portugues": "por",
    "pt": "por",
    "por": "por",
    # Dutch
    "dutch": "dut",
    "nederlands": "dut",
    "nl": "dut",
    "nld": "dut",
    "dut": "dut",
    # Russian
    "russian": "rus",
    "русский": "rus",
    "ru": "rus",
    "rus": "rus",
    # Chinese
    "chinese": "chi",
    "中文": "chi",
    "zh": "chi",
    "zho": "chi",
    "chi": "chi",
    # Korean
    "korean": "kor",
    "한국어": "kor",
    "ko": "kor",
    "kor": "kor",
    # Polish
    "polish": "pol",
    "polski": "pol",
    "pl": "pol",
    "pol": "pol",
    # Swedish
    "swedish": "swe",
    "svenska": "swe",
    "sv": "swe",
    "swe": "swe",
    # Norwegian
    "norwegian": "nor",
    "norsk": "nor",
    "no": "nor",
    "nor": "nor",
    # Danish
    "danish": "dan",
    "dansk": "dan",
    "da": "dan",
    "dan": "dan",
    # Finnish
    "finnish": "fin",
    "suomi": "fin",
    "fi": "fin",
    "fin": "fin",
    # Hindi
    "hindi": "hin",
    "हिन्दी": "hin",
    "hi": "hin",
    "hin": "hin",
    # Arabic
    "arabic": "ara",
    "العربية": "ara",
    "ar": "ara",
    "ara": "ara",
    # Turkish
    "turkish": "tur",
    "türkçe": "tur",
    "turkce": "tur",
    "tr": "tur",
    "tur": "tur",
    # Czech
    "czech": "cze",
    "čeština": "cze",
    "cestina": "cze",
    "cs": "cze",
    "ces": "cze",
    "cze": "cze",
    # Greek
    "greek": "gre",
    "ελληνικά": "gre",
    "el": "gre",
    "ell": "gre",
    "gre": "gre",
    # Hebrew
    "hebrew": "heb",
    "עברית": "heb",
    "he": "heb",
    "heb": "heb",
    # Hungarian
    "hungarian": "hun",
    "magyar": "hun",
    "hu": "hun",
    "hun": "hun",
    # Indonesian
    "indonesian": "ind",
    "bahasa indonesia": "ind",
    "id": "ind",
    "ind": "ind",
    # Thai
    "thai": "tha",
    "ไทย": "tha",
    "th": "tha",
    "tha": "tha",
    # Vietnamese
    "vietnamese": "vie",
    "tiếng việt": "vie",
    "vi": "vie",
    "vie": "vie",
    # Romanian
    "romanian": "rum",
    "română": "rum",
    "romana": "rum",
    "ro": "rum",
    "ron": "rum",
    "rum": "rum",
    # Ukrainian
    "ukrainian": "ukr",
    "українська": "ukr",
    "uk": "ukr",
    "ukr": "ukr",
    # Bulgarian
    "bulgarian": "bul",
    "български": "bul",
    "bg": "bul",
    "bul": "bul",
    # Croatian
    "croatian": "hrv",
    "hrvatski": "hrv",
    "hr": "hrv",
    "hrv": "hrv",
    # Serbian
    "serbian": "srp",
    "srpski": "srp",
    "sr": "srp",
    "srp": "srp",
    # Slovak
    "slovak": "slo",
    "slovenčina": "slo",
    "slovencina": "slo",
    "sk": "slo",
    "slk": "slo",
    "slo": "slo",
    # Slovenian
    "slovenian": "slv",
    "slovenščina": "slv",
    "slovenscina": "slv",
    "sl": "slv",
    "slv": "slv",
    # Catalan
    "catalan": "cat",
    "català": "cat",
    "catala": "cat",
    "ca": "cat",
    "cat": "cat",
    # Latin
    "latin": "lat",
    "latina": "lat",
    "la": "lat",
    "lat": "lat",
    # Afrikaans
    "afrikaans": "afr",
    "af": "afr",
    "afr": "afr",
}

# Default language if unknown
DEFAULT_LANGUAGE = "eng"

# Pre-computed set of valid ISO codes for validation
_VALID_ISO_CODES: frozenset[str] = frozenset(LANGUAGE_TO_ISO.values())


def to_iso_language(language: str | None) -> str:
    """
    Convert language name/code to ISO 639-2/B three-letter code.

    Args:
        language: Language name or code (e.g., "english", "en", "eng")

    Returns:
        ISO 639-2/B code (e.g., "eng") or default if unknown

    Examples:
        >>> to_iso_language("english")
        'eng'
        >>> to_iso_language("de")
        'ger'
        >>> to_iso_language(None)
        'eng'
    """
    if not language:
        return DEFAULT_LANGUAGE

    normalized = language.lower().strip()
    return LANGUAGE_TO_ISO.get(normalized, DEFAULT_LANGUAGE)


def is_valid_iso_language(code: str) -> bool:
    """Check if a code is a valid ISO 639-2/B language code."""
    return code.lower() in _VALID_ISO_CODES


# MARC relator codes for OPF roles
# See: https://www.loc.gov/marc/relators/relaterm.html
MARC_RELATOR_CODES: dict[str, str] = {
    "author": "aut",
    "narrator": "nrt",
    "translator": "trl",
    "editor": "edt",
    "illustrator": "ill",
    "contributor": "ctb",
    "reader": "nrt",  # Reader maps to narrator
    "performer": "prf",
    "composer": "cmp",
    "arranger": "arr",
    "director": "drt",
    "producer": "pro",
    "publisher": "pbl",
}


def get_marc_relator(role: str) -> str:
    """
    Get MARC relator code for a role.

    Args:
        role: Role name (e.g., "author", "narrator")

    Returns:
        MARC relator code (e.g., "aut", "nrt")
    """
    return MARC_RELATOR_CODES.get(role.lower(), "ctb")  # Default to contributor
