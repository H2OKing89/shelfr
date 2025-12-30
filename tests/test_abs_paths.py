"""Tests for Audiobookshelf path mapping utilities."""

from __future__ import annotations

from pathlib import Path

import pytest

from shelfr.abs.paths import PathMapper, abs_path_to_host, host_path_to_abs


class TestAbsPathToHost:
    """Test abs_path_to_host function."""

    def test_simple_path(self) -> None:
        """Test simple path conversion."""
        result = abs_path_to_host(
            "/audiobooks/Author/Book",
            container_prefix="/audiobooks",
            host_prefix="/mnt/user/data/audio/audiobooks",
        )
        assert result == Path("/mnt/user/data/audio/audiobooks/Author/Book")

    def test_nested_path(self) -> None:
        """Test nested path conversion."""
        result = abs_path_to_host(
            "/audiobooks/Author/Series Name/Book Title (2024)",
            container_prefix="/audiobooks",
            host_prefix="/mnt/user/data/audio/audiobooks",
        )
        expected = Path("/mnt/user/data/audio/audiobooks/Author/Series Name/Book Title (2024)")
        assert result == expected

    def test_trailing_slash_container(self) -> None:
        """Test that trailing slashes on container prefix are handled."""
        result = abs_path_to_host(
            "/audiobooks/Author/Book",
            container_prefix="/audiobooks/",
            host_prefix="/mnt/user/data",
        )
        assert result == Path("/mnt/user/data/Author/Book")

    def test_trailing_slash_host(self) -> None:
        """Test that trailing slashes on host prefix are handled."""
        result = abs_path_to_host(
            "/audiobooks/Author/Book",
            container_prefix="/audiobooks",
            host_prefix="/mnt/user/data/",
        )
        assert result == Path("/mnt/user/data/Author/Book")

    def test_exact_container_prefix(self) -> None:
        """Test when path equals container prefix exactly."""
        result = abs_path_to_host(
            "/audiobooks",
            container_prefix="/audiobooks",
            host_prefix="/mnt/user/data/audiobooks",
        )
        assert result == Path("/mnt/user/data/audiobooks")

    def test_path_not_under_container_raises(self) -> None:
        """Test that paths not under container prefix raise ValueError."""
        with pytest.raises(ValueError, match="does not start with container prefix"):
            abs_path_to_host(
                "/podcasts/Show/Episode",
                container_prefix="/audiobooks",
                host_prefix="/mnt/user/data",
            )

    def test_with_path_object(self) -> None:
        """Test accepting Path object."""
        result = abs_path_to_host(
            Path("/audiobooks/Book"),
            container_prefix="/audiobooks",
            host_prefix="/host",
        )
        assert result == Path("/host/Book")

    def test_special_characters_in_path(self) -> None:
        """Test paths with special characters."""
        result = abs_path_to_host(
            "/audiobooks/日本語 Author/Book [2024] {ASIN.B123}",
            container_prefix="/audiobooks",
            host_prefix="/mnt/data",
        )
        assert result == Path("/mnt/data/日本語 Author/Book [2024] {ASIN.B123}")

    def test_empty_relative_portion(self) -> None:
        """Test when the relative portion is empty."""
        result = abs_path_to_host(
            "/audiobooks",
            container_prefix="/audiobooks",
            host_prefix="/data",
        )
        assert result == Path("/data")


class TestHostPathToAbs:
    """Test host_path_to_abs function."""

    def test_simple_path(self) -> None:
        """Test simple path conversion."""
        result = host_path_to_abs(
            "/mnt/user/data/audio/audiobooks/Author/Book",
            container_prefix="/audiobooks",
            host_prefix="/mnt/user/data/audio/audiobooks",
        )
        assert result == "/audiobooks/Author/Book"

    def test_nested_path(self) -> None:
        """Test nested path conversion."""
        result = host_path_to_abs(
            "/mnt/user/data/audio/audiobooks/Author/Series/Book (2024) [Narrator]",
            container_prefix="/audiobooks",
            host_prefix="/mnt/user/data/audio/audiobooks",
        )
        assert result == "/audiobooks/Author/Series/Book (2024) [Narrator]"

    def test_trailing_slashes_handled(self) -> None:
        """Test that trailing slashes are handled."""
        result = host_path_to_abs(
            "/mnt/data/Author/Book",
            container_prefix="/audiobooks/",
            host_prefix="/mnt/data/",
        )
        assert result == "/audiobooks/Author/Book"

    def test_exact_host_prefix(self) -> None:
        """Test when path equals host prefix exactly."""
        result = host_path_to_abs(
            "/mnt/user/data",
            container_prefix="/audiobooks",
            host_prefix="/mnt/user/data",
        )
        assert result == "/audiobooks"

    def test_path_not_under_host_raises(self) -> None:
        """Test that paths not under host prefix raise ValueError."""
        with pytest.raises(ValueError, match="does not start with host prefix"):
            host_path_to_abs(
                "/other/location/file",
                container_prefix="/audiobooks",
                host_prefix="/mnt/user/data",
            )

    def test_with_path_object(self) -> None:
        """Test accepting Path object."""
        result = host_path_to_abs(
            Path("/host/data/Book"),
            container_prefix="/audiobooks",
            host_prefix="/host/data",
        )
        assert result == "/audiobooks/Book"


class TestPathMapper:
    """Test PathMapper convenience class."""

    @pytest.fixture
    def mapper(self) -> PathMapper:
        """Create a test mapper."""
        return PathMapper(
            container_prefix="/audiobooks",
            host_prefix="/mnt/user/data/audio/audiobooks",
        )

    def test_to_host(self, mapper: PathMapper) -> None:
        """Test to_host method."""
        result = mapper.to_host("/audiobooks/Author/Book")
        assert result == Path("/mnt/user/data/audio/audiobooks/Author/Book")

    def test_to_container(self, mapper: PathMapper) -> None:
        """Test to_container method."""
        result = mapper.to_container("/mnt/user/data/audio/audiobooks/Author/Book")
        assert result == "/audiobooks/Author/Book"

    def test_is_under_container(self, mapper: PathMapper) -> None:
        """Test is_under_container check."""
        assert mapper.is_under_container("/audiobooks/Book") is True
        assert mapper.is_under_container("/podcasts/Show") is False

    def test_is_under_host(self, mapper: PathMapper) -> None:
        """Test is_under_host check."""
        assert mapper.is_under_host("/mnt/user/data/audio/audiobooks/Book") is True
        assert mapper.is_under_host("/other/path") is False

    def test_trailing_slashes_normalized(self) -> None:
        """Test that trailing slashes are normalized in constructor."""
        mapper = PathMapper(
            container_prefix="/audiobooks/",
            host_prefix="/data/",
        )
        assert mapper.container_prefix == "/audiobooks"
        assert mapper.host_prefix == "/data"

    def test_mappings_validation_missing_container(self) -> None:
        """Test that mappings validation catches missing 'container' key."""
        with pytest.raises(ValueError, match="missing required 'container' or 'host' key"):
            PathMapper(mappings=[{"host": "/data"}])

    def test_mappings_validation_missing_host(self) -> None:
        """Test that mappings validation catches missing 'host' key."""
        with pytest.raises(ValueError, match="missing required 'container' or 'host' key"):
            PathMapper(mappings=[{"container": "/audiobooks"}])

    def test_mappings_validation_empty_dict(self) -> None:
        """Test that mappings validation catches empty dict."""
        with pytest.raises(ValueError, match="missing required 'container' or 'host' key"):
            PathMapper(mappings=[{}])

    def test_mappings_validation_empty_container_value(self) -> None:
        """Test that mappings validation catches empty container string."""
        with pytest.raises(ValueError, match="empty 'container' or 'host' value"):
            PathMapper(mappings=[{"container": "", "host": "/data"}])

    def test_mappings_validation_empty_host_value(self) -> None:
        """Test that mappings validation catches empty host string."""
        with pytest.raises(ValueError, match="empty 'container' or 'host' value"):
            PathMapper(mappings=[{"container": "/audiobooks", "host": ""}])

    def test_round_trip_container_to_host_to_container(self, mapper: PathMapper) -> None:
        """Test round-trip: container → host → container."""
        original = "/audiobooks/Author/Series/Book (2024)"
        host = mapper.to_host(original)
        back = mapper.to_container(host)
        assert back == original

    def test_round_trip_host_to_container_to_host(self, mapper: PathMapper) -> None:
        """Test round-trip: host → container → host."""
        original = "/mnt/user/data/audio/audiobooks/Author/Book"
        container = mapper.to_container(original)
        back = mapper.to_host(container)
        assert back == Path(original)


class TestRealWorldPaths:
    """Test with realistic MAMFast paths."""

    @pytest.fixture
    def mam_mapper(self) -> PathMapper:
        """Mapper with typical MAMFast setup."""
        return PathMapper(
            container_prefix="/audiobooks",
            host_prefix="/mnt/user/data/audio/audiobooks",
        )

    def test_sword_art_online_path(self, mam_mapper: PathMapper) -> None:
        """Test with SAO fixture path."""
        abs_path = (
            "/audiobooks/Reki Kawahara/Sword Art Online/"
            "Sword Art Online vol_16 Alicization Exploding (2025) "
            "(Reki Kawahara) {ASIN.B0DK9TS6D9} [H2OKing]"
        )
        host = mam_mapper.to_host(abs_path)
        expected = Path(
            "/mnt/user/data/audio/audiobooks/Reki Kawahara/Sword Art Online/"
            "Sword Art Online vol_16 Alicization Exploding (2025) "
            "(Reki Kawahara) {ASIN.B0DK9TS6D9} [H2OKing]"
        )
        assert host == expected

    def test_project_hail_mary_path(self, mam_mapper: PathMapper) -> None:
        """Test with standalone book path."""
        abs_path = "/audiobooks/Andy Weir/Project Hail Mary (2021) (Andy Weir) {ASIN.B08G9PRS1K}"
        host = mam_mapper.to_host(abs_path)
        expected = Path(
            "/mnt/user/data/audio/audiobooks/Andy Weir/Project Hail Mary (2021) "
            "(Andy Weir) {ASIN.B08G9PRS1K}"
        )
        assert host == expected

    def test_japanese_author_name(self, mam_mapper: PathMapper) -> None:
        """Test with Japanese author name in path."""
        abs_path = "/audiobooks/Rifujin na Magonote/Mushoku Tensei/Vol 1"
        host = mam_mapper.to_host(abs_path)
        assert "Rifujin na Magonote" in str(host)
        assert host.name == "Vol 1"


class TestPrefixBoundaryMatching:
    """Test that prefix matching respects path boundaries.

    Ensures /audiobooks doesn't match /audiobooks2, /mnt/data doesn't match /mnt/data2.
    """

    def test_abs_path_to_host_rejects_similar_prefix(self) -> None:
        """Test that /audiobooks doesn't match /audiobooks2."""
        with pytest.raises(ValueError, match="does not start with container prefix"):
            abs_path_to_host(
                "/audiobooks2/Author/Book",
                container_prefix="/audiobooks",
                host_prefix="/mnt/data",
            )

    def test_abs_path_to_host_rejects_partial_match(self) -> None:
        """Test that /audiobooks doesn't match /audiobookshelf."""
        with pytest.raises(ValueError, match="does not start with container prefix"):
            abs_path_to_host(
                "/audiobookshelf/data",
                container_prefix="/audiobooks",
                host_prefix="/mnt/data",
            )

    def test_host_path_to_abs_rejects_similar_prefix(self) -> None:
        """Test that /mnt/data doesn't match /mnt/data2."""
        with pytest.raises(ValueError, match="does not start with host prefix"):
            host_path_to_abs(
                "/mnt/data2/Author/Book",
                container_prefix="/audiobooks",
                host_prefix="/mnt/data",
            )

    def test_host_path_to_abs_rejects_partial_match(self) -> None:
        """Test that /mnt/data doesn't match /mnt/datafiles."""
        with pytest.raises(ValueError, match="does not start with host prefix"):
            host_path_to_abs(
                "/mnt/datafiles/stuff",
                container_prefix="/audiobooks",
                host_prefix="/mnt/data",
            )

    def test_is_under_container_rejects_similar_prefix(self) -> None:
        """Test that is_under_container rejects similar prefixes."""
        mapper = PathMapper(container_prefix="/audiobooks", host_prefix="/mnt/data")
        assert mapper.is_under_container("/audiobooks/Book") is True
        assert mapper.is_under_container("/audiobooks") is True  # exact match
        assert mapper.is_under_container("/audiobooks2/Book") is False
        assert mapper.is_under_container("/audiobookshelf") is False

    def test_is_under_host_rejects_similar_prefix(self) -> None:
        """Test that is_under_host rejects similar prefixes."""
        mapper = PathMapper(container_prefix="/audiobooks", host_prefix="/mnt/data")
        assert mapper.is_under_host("/mnt/data/Book") is True
        assert mapper.is_under_host("/mnt/data") is True  # exact match
        assert mapper.is_under_host("/mnt/data2/Book") is False
        assert mapper.is_under_host("/mnt/datafiles") is False

    def test_exact_prefix_match_accepted(self) -> None:
        """Test that exact prefix matches are still accepted."""
        # Container exact match
        result = abs_path_to_host(
            "/audiobooks",
            container_prefix="/audiobooks",
            host_prefix="/mnt/data",
        )
        assert result == Path("/mnt/data")

        # Host exact match
        result2 = host_path_to_abs(
            "/mnt/data",
            container_prefix="/audiobooks",
            host_prefix="/mnt/data",
        )
        assert result2 == "/audiobooks"
