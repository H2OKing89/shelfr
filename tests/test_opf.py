"""Tests for OPF metadata generation module."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from shelfr.opf import (
    CanonicalMetadata,
    Genre,
    OPFGenerator,
    OPFMetadata,
    Person,
    Series,
    generate_opf,
    get_marc_relator,
    is_valid_iso_language,
    to_iso_language,
    write_opf,
)

# =============================================================================
# Test Helpers
# =============================================================================


def strip_xml_declaration(xml_str: str) -> str:
    """Remove XML declaration for ET.fromstring compatibility.

    The XML declaration (<?xml ...?>) must be stripped before parsing
    with ElementTree.fromstring() in some cases.
    """
    return re.sub(r"^<\?xml[^?]*\?>\s*", "", xml_str, count=1)


# =============================================================================
# Test Data - Sample Audnexus Response
# =============================================================================

SAMPLE_AUDNEX_RESPONSE = {
    "asin": "1774248182",
    "authors": [
        {"asin": "B08VWFRTMS", "name": "Shirtaloon"},
        {"name": "Travis Deverell"},
    ],
    "copyright": 2021,
    "description": (
        "Jason, a former office-supplies-store manager, battles monsters "
        "in a magical realm, wielding powers in search of courage...and pants."
    ),
    "formatType": "unabridged",
    "genres": [
        {"asin": "18580606011", "name": "Science Fiction & Fantasy", "type": "genre"},
        {"asin": "18580607011", "name": "Fantasy", "type": "tag"},
        {"asin": "18580608011", "name": "Action & Adventure", "type": "tag"},
        {"asin": "18580615011", "name": "Epic", "type": "tag"},
        {"asin": "18580622011", "name": "Paranormal & Urban", "type": "tag"},
        {"asin": "18580625011", "name": "Urban", "type": "tag"},
    ],
    "image": "https://m.media-amazon.com/images/I/81hRIws99iL.jpg",
    "isAdult": False,
    "isbn": "9781774248188",
    "language": "english",
    "literatureType": "fiction",
    "narrators": [{"name": "Heath Miller"}],
    "publisherName": "Podium Audio",
    "rating": "4.8",
    "region": "us",
    "releaseDate": "2021-03-09T00:00:00.000Z",
    "runtimeLengthMin": 1736,
    "seriesPrimary": {
        "asin": "B08WJ59784",
        "name": "He Who Fights with Monsters",
        "position": "1",
    },
    "subtitle": "He Who Fights with Monsters, Book 1",
    "summary": "<p><b><i>Selected as one of Audible's best audiobooks of 2021</i></b></p>",
    "title": "He Who Fights with Monsters: A LitRPG Adventure",
}


# =============================================================================
# Language Mapping Tests
# =============================================================================


class TestLanguageMapping:
    """Tests for language code conversion."""

    @pytest.mark.parametrize(
        "input_lang,expected",
        [
            ("english", "eng"),
            ("English", "eng"),
            ("ENGLISH", "eng"),
            ("en", "eng"),
            ("en-us", "eng"),
            ("eng", "eng"),
            ("german", "ger"),
            ("deutsch", "ger"),
            ("de", "ger"),
            ("french", "fre"),
            ("français", "fre"),
            ("fr", "fre"),
            ("spanish", "spa"),
            ("español", "spa"),
            ("japanese", "jpn"),
            ("日本語", "jpn"),
            ("chinese", "chi"),
            ("中文", "chi"),
            ("korean", "kor"),
            ("한국어", "kor"),
        ],
    )
    def test_known_languages(self, input_lang: str, expected: str) -> None:
        """Test conversion of known language names/codes."""
        assert to_iso_language(input_lang) == expected

    def test_unknown_language_defaults_to_english(self) -> None:
        """Unknown languages default to English."""
        assert to_iso_language("klingon") == "eng"
        assert to_iso_language("gibberish") == "eng"

    def test_none_defaults_to_english(self) -> None:
        """None input defaults to English."""
        assert to_iso_language(None) == "eng"

    def test_empty_string_defaults_to_english(self) -> None:
        """Empty string defaults to English."""
        assert to_iso_language("") == "eng"

    def test_whitespace_handling(self) -> None:
        """Whitespace is stripped before lookup."""
        assert to_iso_language("  english  ") == "eng"
        assert to_iso_language("\tenglish\n") == "eng"

    def test_is_valid_iso_language(self) -> None:
        """Test ISO code validation."""
        assert is_valid_iso_language("eng")
        assert is_valid_iso_language("ENG")
        assert is_valid_iso_language("ger")
        assert not is_valid_iso_language("english")
        assert not is_valid_iso_language("xyz")


class TestMarcRelatorCodes:
    """Tests for MARC relator code lookup."""

    def test_common_roles(self) -> None:
        """Test common role mappings."""
        assert get_marc_relator("author") == "aut"
        assert get_marc_relator("narrator") == "nrt"
        assert get_marc_relator("translator") == "trl"
        assert get_marc_relator("editor") == "edt"
        assert get_marc_relator("reader") == "nrt"

    def test_case_insensitive(self) -> None:
        """Role lookup is case-insensitive."""
        assert get_marc_relator("Author") == "aut"
        assert get_marc_relator("NARRATOR") == "nrt"

    def test_unknown_defaults_to_contributor(self) -> None:
        """Unknown roles default to contributor."""
        assert get_marc_relator("unknown") == "ctb"
        assert get_marc_relator("assistant") == "ctb"


# =============================================================================
# Schema Tests
# =============================================================================


class TestPerson:
    """Tests for Person model."""

    def test_basic_creation(self) -> None:
        """Create person with name only."""
        person = Person(name="John Doe")
        assert person.name == "John Doe"
        assert person.asin is None

    def test_with_asin(self) -> None:
        """Create person with ASIN."""
        person = Person(name="Jane Doe", asin="B001234567")
        assert person.name == "Jane Doe"
        assert person.asin == "B001234567"


class TestGenre:
    """Tests for Genre model."""

    def test_genre_type(self) -> None:
        """Create genre with type."""
        genre = Genre(name="Fantasy", type="genre")
        assert genre.name == "Fantasy"
        assert genre.type == "genre"

    def test_tag_type(self) -> None:
        """Create tag with type."""
        tag = Genre(name="Epic", type="tag")
        assert tag.name == "Epic"
        assert tag.type == "tag"


class TestSeries:
    """Tests for Series model."""

    def test_basic_series(self) -> None:
        """Create basic series."""
        series = Series(name="Test Series", position="1")
        assert series.name == "Test Series"
        assert series.position == "1"

    def test_numeric_position_normalized(self) -> None:
        """Numeric positions are converted to strings."""
        series = Series(name="Test", position=5)  # type: ignore
        assert series.position == "5"

    def test_float_position_normalized(self) -> None:
        """Float positions are converted to strings."""
        series = Series(name="Test", position=1.5)  # type: ignore
        assert series.position == "1.5"


class TestCanonicalMetadata:
    """Tests for CanonicalMetadata model."""

    def test_from_audnex_response(self) -> None:
        """Parse full Audnexus API response."""
        meta = CanonicalMetadata.from_audnex(SAMPLE_AUDNEX_RESPONSE)

        assert meta.asin == "1774248182"
        assert meta.title == "He Who Fights with Monsters: A LitRPG Adventure"
        assert meta.subtitle == "He Who Fights with Monsters, Book 1"
        assert len(meta.authors) == 2
        assert meta.authors[0].name == "Shirtaloon"
        assert meta.authors[1].name == "Travis Deverell"
        assert len(meta.narrators) == 1
        assert meta.narrators[0].name == "Heath Miller"
        assert meta.publisher_name == "Podium Audio"
        assert meta.isbn == "9781774248188"
        assert meta.language == "english"
        assert meta.series_primary is not None
        assert meta.series_primary.name == "He Who Fights with Monsters"
        assert meta.series_primary.position == "1"
        assert len(meta.genres) == 6

    def test_release_year_extraction(self) -> None:
        """Extract year from release date."""
        meta = CanonicalMetadata.from_audnex(SAMPLE_AUDNEX_RESPONSE)
        assert meta.release_year == 2021

    def test_release_date_iso(self) -> None:
        """Get ISO formatted release date."""
        meta = CanonicalMetadata.from_audnex(SAMPLE_AUDNEX_RESPONSE)
        assert meta.release_date_iso == "2021-03-09"

    def test_get_all_genres_deduped(self) -> None:
        """Genres are deduplicated by name."""
        meta = CanonicalMetadata(
            asin="test",
            title="Test",
            genres=[
                Genre(name="Fantasy"),
                Genre(name="Fantasy"),  # Duplicate
                Genre(name="Adventure"),
            ],
        )
        genres = meta.get_all_genres()
        assert genres == ["Fantasy", "Adventure"]

    def test_minimal_metadata(self) -> None:
        """Create with minimal required fields."""
        meta = CanonicalMetadata(asin="B001234567", title="Minimal Book")
        assert meta.asin == "B001234567"
        assert meta.title == "Minimal Book"
        assert meta.authors == []
        assert meta.language == "english"


class TestOPFMetadata:
    """Tests for OPFMetadata model."""

    def test_from_canonical(self) -> None:
        """Convert canonical metadata to OPF format."""
        canonical = CanonicalMetadata.from_audnex(SAMPLE_AUDNEX_RESPONSE)
        opf = OPFMetadata.from_canonical(canonical)

        # Title is cleaned (filter_title removes format indicators
        # AND genre tags like "A LitRPG Adventure")
        assert opf.title == "He Who Fights with Monsters"
        # Subtitle is cleaned (filter_title removes ", Book 1" pattern)
        assert opf.subtitle == "He Who Fights with Monsters"
        assert opf.language == "eng"  # Converted to ISO
        assert opf.publisher == "Podium Audio"
        assert opf.date == "2021-03-09"

        # Creators
        assert len(opf.creators) == 3  # 2 authors + 1 narrator
        assert opf.creators[0].name == "Shirtaloon"
        assert opf.creators[0].role == "aut"
        assert opf.creators[2].name == "Heath Miller"
        assert opf.creators[2].role == "nrt"

        # Identifiers
        assert len(opf.identifiers) == 2  # ASIN + ISBN
        assert any(i.scheme == "ASIN" and i.value == "1774248182" for i in opf.identifiers)
        assert any(i.scheme == "ISBN" and i.value == "9781774248188" for i in opf.identifiers)

        # Series (Calibre format)
        assert len(opf.series) == 1
        assert opf.series[0].name == "He Who Fights with Monsters"
        assert opf.series[0].index == "1"

        # Subjects (genres)
        assert "Science Fiction & Fantasy" in opf.subjects
        assert "Fantasy" in opf.subjects

        # Custom metadata preserved
        assert opf.custom_meta["audnex:rating"] == "4.8"
        assert opf.custom_meta["audnex:runtimeLengthMin"] == "1736"

    def test_adult_tag(self) -> None:
        """isAdult flag becomes a tag."""
        canonical = CanonicalMetadata(
            asin="test",
            title="Adult Book",
            is_adult=True,
        )
        opf = OPFMetadata.from_canonical(canonical)
        assert "Adult" in opf.tags

    def test_multiple_series(self) -> None:
        """Both primary and secondary series are included."""
        canonical = CanonicalMetadata(
            asin="test",
            title="Multi-Series Book",
            series_primary=Series(name="Series One", position="3"),
            series_secondary=Series(name="Series Two", position="1"),
        )
        opf = OPFMetadata.from_canonical(canonical)
        assert len(opf.series) == 2
        assert opf.series[0].name == "Series One"
        assert opf.series[0].index == "3"
        assert opf.series[1].name == "Series Two"
        assert opf.series[1].index == "1"


# =============================================================================
# Generator Tests
# =============================================================================


class TestOPFGenerator:
    """Tests for OPF XML generation."""

    def test_generate_basic_opf(self) -> None:
        """Generate basic OPF from canonical metadata."""
        meta = CanonicalMetadata(
            asin="B001234567",
            title="Test Book",
            authors=[Person(name="Test Author")],
            language="english",
        )
        generator = OPFGenerator()
        xml_str = generator.generate_from_canonical(meta)

        assert '<?xml version="1.0" encoding="UTF-8"?>' in xml_str
        assert "<dc:title>Test Book</dc:title>" in xml_str
        assert "<dc:language>eng</dc:language>" in xml_str
        assert 'opf:scheme="ASIN"' in xml_str
        assert ">B001234567<" in xml_str

    def test_generate_full_opf(self) -> None:
        """Generate OPF from full Audnexus response."""
        meta = CanonicalMetadata.from_audnex(SAMPLE_AUDNEX_RESPONSE)
        xml_str = generate_opf(meta)

        # Verify structure
        root = ET.fromstring(strip_xml_declaration(xml_str))
        assert root.tag == "package"
        assert root.get("version") == "2.0"

        # Find metadata element
        metadata = root.find("metadata")
        assert metadata is not None

    def test_xml_valid_structure(self) -> None:
        """Generated XML is valid and parseable."""
        meta = CanonicalMetadata.from_audnex(SAMPLE_AUDNEX_RESPONSE)
        xml_str = generate_opf(meta)

        # Should parse without error
        root = ET.fromstring(strip_xml_declaration(xml_str))

        # Check namespaces
        assert "http://www.idpf.org/2007/opf" in root.tag or root.tag == "package"

    def test_html_stripping(self) -> None:
        """HTML in description is stripped."""
        meta = CanonicalMetadata(
            asin="test",
            title="Test",
            description="<p><b>Bold</b> text with <i>italics</i></p>",
        )
        xml_str = generate_opf(meta)

        # HTML tags should be removed
        assert "<p>" not in xml_str
        assert "<b>" not in xml_str
        assert "Bold text with italics" in xml_str

    def test_special_characters_escaped(self) -> None:
        """Special XML characters are properly escaped."""
        meta = CanonicalMetadata(
            asin="test",
            title="Book & Other < Things > More",
        )
        xml_str = generate_opf(meta)

        # Should be valid XML (not raising parsing error)
        ET.fromstring(strip_xml_declaration(xml_str))

        # Ampersand should be escaped
        assert "&amp;" in xml_str or "Book &amp; Other" in xml_str

    def test_calibre_series_format(self) -> None:
        """Series uses Calibre meta format."""
        # Use a series name that won't be cleaned by filter_series
        meta = CanonicalMetadata(
            asin="test",
            title="Test",
            series_primary=Series(name="The Stormlight Archive", position="5"),
        )
        xml_str = generate_opf(meta)

        assert 'name="calibre:series"' in xml_str
        assert 'content="The Stormlight Archive"' in xml_str
        assert 'name="calibre:series_index"' in xml_str
        assert 'content="5"' in xml_str

    def test_custom_meta_optional(self) -> None:
        """Custom metadata can be disabled."""
        meta = CanonicalMetadata.from_audnex(SAMPLE_AUDNEX_RESPONSE)

        # With custom meta
        gen_with = OPFGenerator(include_custom_meta=True)
        xml_with = gen_with.generate_from_canonical(meta)
        assert "audnex:rating" in xml_with

        # Without custom meta
        gen_without = OPFGenerator(include_custom_meta=False)
        xml_without = gen_without.generate_from_canonical(meta)
        assert "audnex:rating" not in xml_without

    def test_write_to_file(self, tmp_path: Path) -> None:
        """Write OPF to file."""
        meta = CanonicalMetadata(
            asin="test",
            title="Test Book",
        )
        output_path = write_opf(meta, tmp_path)

        assert output_path.exists()
        assert output_path.name == "metadata.opf"

        content = output_path.read_text()
        assert "Test Book" in content

    def test_write_custom_filename(self, tmp_path: Path) -> None:
        """Write OPF with custom filename."""
        meta = CanonicalMetadata(asin="test", title="Test")
        output_path = write_opf(meta, tmp_path, filename="custom.opf")

        assert output_path.name == "custom.opf"

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Writing creates parent directories if needed."""
        meta = CanonicalMetadata(asin="test", title="Test")
        nested_path = tmp_path / "a" / "b" / "c" / "metadata.opf"
        output_path = write_opf(meta, nested_path)

        assert output_path.exists()
        assert output_path.parent.exists()


# =============================================================================
# Integration Tests
# =============================================================================


class TestEndToEnd:
    """End-to-end integration tests."""

    def test_audnex_to_opf_file(self, tmp_path: Path) -> None:
        """Full pipeline from Audnexus response to OPF file."""
        # Simulate receiving Audnexus API response
        api_response = SAMPLE_AUDNEX_RESPONSE.copy()

        # Parse into canonical model
        canonical = CanonicalMetadata.from_audnex(api_response)
        assert canonical.asin == "1774248182"

        # Convert to OPF model
        opf = OPFMetadata.from_canonical(canonical)
        assert opf.language == "eng"

        # Generate and write
        output_path = write_opf(opf, tmp_path)

        # Verify file content
        content = output_path.read_text()
        assert "He Who Fights with Monsters" in content
        assert "Shirtaloon" in content
        assert "Heath Miller" in content
        assert 'opf:role="aut"' in content
        assert 'opf:role="nrt"' in content
        assert "calibre:series" in content

    def test_minimal_book_opf(self, tmp_path: Path) -> None:
        """Generate valid OPF for book with minimal metadata."""
        minimal = {
            "asin": "B999999999",
            "title": "Unknown Book",
            "authors": [],
            "description": "",
            "formatType": "unabridged",
            "language": "english",
            "publisherName": "",
            "rating": "",
            "region": "us",
            "releaseDate": None,
            "runtimeLengthMin": None,
            "summary": "",
        }

        canonical = CanonicalMetadata.from_audnex(minimal)
        output_path = write_opf(canonical, tmp_path)

        # Should produce valid XML
        content = output_path.read_text()
        ET.fromstring(strip_xml_declaration(content))  # Should not raise

        assert "<dc:title>Unknown Book</dc:title>" in content
        assert "<dc:language>eng</dc:language>" in content


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestHelperFunctions:
    """Tests for OPF helper functions."""

    def test_clean_role_from_name(self) -> None:
        """Remove role suffix from name."""
        from shelfr.opf import clean_role_from_name

        assert clean_role_from_name("John Smith - translator", "translator") == "John Smith"
        assert clean_role_from_name("John Smith-translator", "translator") == "John Smith"
        assert clean_role_from_name("John Smith translator", "translator") == "John Smith"
        assert clean_role_from_name("John Smith - Translator", "translator") == "John Smith"
        assert clean_role_from_name("Jane Doe", "translator") == "Jane Doe"

    def test_detect_role_from_name(self) -> None:
        """Detect MARC role from name suffix."""
        from shelfr.opf import detect_role_from_name

        assert detect_role_from_name("John Smith - translator") == ("John Smith", "trl")
        assert detect_role_from_name("Jane Doe - illustrator") == ("Jane Doe", "ill")
        assert detect_role_from_name("Bob Editor - editor") == ("Bob Editor", "edt")
        assert detect_role_from_name("Normal Author") == ("Normal Author", "ctb")

    def test_name_to_file_as(self) -> None:
        """Convert name to filing format."""
        from shelfr.opf import name_to_file_as

        assert name_to_file_as("Brandon Sanderson") == "Sanderson, Brandon"
        assert name_to_file_as("J.R.R. Tolkien") == "Tolkien, J.R.R."
        assert name_to_file_as("Shirtaloon") is None  # Single name
        assert name_to_file_as("Sanderson, Brandon") is None  # Already formatted


class TestAuthorFiltering:
    """Tests for author/translator filtering in OPF generation."""

    def test_translators_filtered_from_authors(self) -> None:
        """Translators are removed from author list and credited separately."""
        data = {
            "asin": "TEST123",
            "title": "Test Book",
            "authors": [
                {"name": "Main Author"},
                {"name": "John Smith - translator"},
            ],
            "narrators": [],
            "language": "english",
        }
        canonical = CanonicalMetadata.from_audnex(data)
        opf = OPFMetadata.from_canonical(canonical)

        # Should have 2 creators: author + translator
        assert len(opf.creators) == 2

        # First should be the main author
        author = opf.creators[0]
        assert author.name == "Main Author"
        assert author.role == "aut"

        # Second should be translator with proper role
        translator = opf.creators[1]
        assert translator.name == "John Smith"
        assert translator.role == "trl"

    def test_illustrators_credited_properly(self) -> None:
        """Illustrators get ill role code."""
        data = {
            "asin": "TEST123",
            "title": "Test Book",
            "authors": [
                {"name": "Main Author"},
                {"name": "Art Person - illustrator"},
            ],
            "narrators": [],
            "language": "english",
        }
        canonical = CanonicalMetadata.from_audnex(data)
        opf = OPFMetadata.from_canonical(canonical)

        illustrator = [c for c in opf.creators if c.role == "ill"]
        assert len(illustrator) == 1
        assert illustrator[0].name == "Art Person"

    def test_narrators_still_included(self) -> None:
        """Narrators are included with nrt role."""
        data = {
            "asin": "TEST123",
            "title": "Test Book",
            "authors": [{"name": "Main Author"}],
            "narrators": [{"name": "Voice Actor"}],
            "language": "english",
        }
        canonical = CanonicalMetadata.from_audnex(data)
        opf = OPFMetadata.from_canonical(canonical)

        narrators = [c for c in opf.creators if c.role == "nrt"]
        assert len(narrators) == 1
        assert narrators[0].name == "Voice Actor"

    def test_multiple_authors_preserved(self) -> None:
        """Multiple authors without role suffixes are all preserved."""
        data = {
            "asin": "TEST123",
            "title": "Collaborative Book",
            "authors": [
                {"name": "Author One"},
                {"name": "Author Two"},
                {"name": "Author Three"},
            ],
            "narrators": [],
            "language": "english",
        }
        canonical = CanonicalMetadata.from_audnex(data)
        opf = OPFMetadata.from_canonical(canonical)

        authors = [c for c in opf.creators if c.role == "aut"]
        assert len(authors) == 3
        assert {a.name for a in authors} == {"Author One", "Author Two", "Author Three"}
