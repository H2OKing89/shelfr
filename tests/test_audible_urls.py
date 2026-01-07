"""
Tests for Audible URL building utilities.

Phase 10.3: Source provenance URL generation.
"""

from __future__ import annotations

from shelfr.utils.audible_urls import (
    AUDIBLE_DOMAINS,
    build_audible_url,
    get_audible_domain,
    is_valid_audible_region,
)


class TestBuildAudibleUrl:
    """Tests for build_audible_url function."""

    def test_default_region_us(self) -> None:
        """Test default region is US."""
        url = build_audible_url("B08G9PRS1K")
        assert url == "https://www.audible.com/pd/B08G9PRS1K"

    def test_explicit_us_region(self) -> None:
        """Test explicit US region."""
        url = build_audible_url("B08G9PRS1K", "us")
        assert url == "https://www.audible.com/pd/B08G9PRS1K"

    def test_uk_region(self) -> None:
        """Test UK region uses .co.uk domain."""
        url = build_audible_url("B08G9PRS1K", "uk")
        assert url == "https://www.audible.co.uk/pd/B08G9PRS1K"

    def test_de_region(self) -> None:
        """Test German region uses .de domain."""
        url = build_audible_url("B08G9PRS1K", "de")
        assert url == "https://www.audible.de/pd/B08G9PRS1K"

    def test_jp_region(self) -> None:
        """Test Japan region uses .co.jp domain."""
        url = build_audible_url("B08G9PRS1K", "jp")
        assert url == "https://www.audible.co.jp/pd/B08G9PRS1K"

    def test_au_region(self) -> None:
        """Test Australia region uses .com.au domain."""
        url = build_audible_url("B08G9PRS1K", "au")
        assert url == "https://www.audible.com.au/pd/B08G9PRS1K"

    def test_all_supported_regions(self) -> None:
        """Test all supported regions produce valid URLs."""
        asin = "B08G9PRS1K"
        expected = {
            "us": "https://www.audible.com/pd/B08G9PRS1K",
            "uk": "https://www.audible.co.uk/pd/B08G9PRS1K",
            "au": "https://www.audible.com.au/pd/B08G9PRS1K",
            "ca": "https://www.audible.ca/pd/B08G9PRS1K",
            "de": "https://www.audible.de/pd/B08G9PRS1K",
            "es": "https://www.audible.es/pd/B08G9PRS1K",
            "fr": "https://www.audible.fr/pd/B08G9PRS1K",
            "in": "https://www.audible.in/pd/B08G9PRS1K",
            "it": "https://www.audible.it/pd/B08G9PRS1K",
            "jp": "https://www.audible.co.jp/pd/B08G9PRS1K",
        }
        for region, expected_url in expected.items():
            assert build_audible_url(asin, region) == expected_url

    def test_region_case_insensitive(self) -> None:
        """Test region is case-insensitive."""
        assert build_audible_url("B08G9PRS1K", "UK") == "https://www.audible.co.uk/pd/B08G9PRS1K"
        assert build_audible_url("B08G9PRS1K", "Uk") == "https://www.audible.co.uk/pd/B08G9PRS1K"
        assert build_audible_url("B08G9PRS1K", "DE") == "https://www.audible.de/pd/B08G9PRS1K"

    def test_unknown_region_falls_back_to_us(self) -> None:
        """Test unknown regions fall back to US domain."""
        url = build_audible_url("B08G9PRS1K", "unknown")
        assert url == "https://www.audible.com/pd/B08G9PRS1K"

    def test_empty_region_uses_default(self) -> None:
        """Test empty region string uses default (US)."""
        url = build_audible_url("B08G9PRS1K", "")
        assert url == "https://www.audible.com/pd/B08G9PRS1K"


class TestGetAudibleDomain:
    """Tests for get_audible_domain function."""

    def test_default_region(self) -> None:
        """Test default region returns US domain."""
        domain = get_audible_domain()
        assert domain == "www.audible.com"

    def test_uk_domain(self) -> None:
        """Test UK domain."""
        domain = get_audible_domain("uk")
        assert domain == "www.audible.co.uk"

    def test_unknown_region_falls_back(self) -> None:
        """Test unknown region falls back to US."""
        domain = get_audible_domain("zz")
        assert domain == "www.audible.com"


class TestIsValidAudibleRegion:
    """Tests for is_valid_audible_region function."""

    def test_valid_regions(self) -> None:
        """Test all supported regions are valid."""
        for region in AUDIBLE_DOMAINS:
            assert is_valid_audible_region(region) is True

    def test_case_insensitive(self) -> None:
        """Test validation is case-insensitive."""
        assert is_valid_audible_region("US") is True
        assert is_valid_audible_region("Us") is True
        assert is_valid_audible_region("uk") is True
        assert is_valid_audible_region("UK") is True

    def test_invalid_regions(self) -> None:
        """Test invalid regions return False."""
        assert is_valid_audible_region("zz") is False
        assert is_valid_audible_region("xx") is False
        assert is_valid_audible_region("brazil") is False

    def test_empty_string(self) -> None:
        """Test empty string is invalid."""
        assert is_valid_audible_region("") is False


class TestAudibleDomainsConstant:
    """Tests for AUDIBLE_DOMAINS constant."""

    def test_all_regions_present(self) -> None:
        """Test all expected regions are present."""
        expected_regions = {"us", "uk", "au", "ca", "de", "es", "fr", "in", "it", "jp"}
        assert set(AUDIBLE_DOMAINS.keys()) == expected_regions

    def test_domain_format(self) -> None:
        """Test all domains have valid format."""
        for _region, domain in AUDIBLE_DOMAINS.items():
            assert domain.startswith("www.audible.")
            assert "://" not in domain  # No protocol
            assert not domain.endswith("/")  # No trailing slash
