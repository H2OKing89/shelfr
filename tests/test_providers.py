"""
Tests for the metadata provider system.

Tests cover:
- Provider types (LookupContext, ProviderResult)
- Provider registry
- Mock provider
- Audnex provider (with mocked HTTP)
- Metadata aggregator
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from shelfr.metadata.aggregator import MetadataAggregator
from shelfr.metadata.providers import (
    AudnexProvider,
    LookupContext,
    MetadataProvider,
    MockProvider,
    ProviderRegistry,
    ProviderResult,
)

# =============================================================================
# LookupContext Tests
# =============================================================================


class TestLookupContext:
    """Tests for LookupContext dataclass."""

    def test_from_asin(self) -> None:
        """Test creating context from ASIN."""
        ctx = LookupContext.from_asin(asin="B08G9PRS1K")
        assert ctx.asin == "B08G9PRS1K"
        assert ctx.isbn is None
        assert ctx.path is None

    def test_from_asin_with_path(self) -> None:
        """Test creating context with ASIN and path."""
        path = Path("/books/test.m4b")
        ctx = LookupContext.from_asin(asin="B08G9PRS1K", path=path)
        assert ctx.asin == "B08G9PRS1K"
        assert ctx.path == path

    def test_from_isbn(self) -> None:
        """Test creating context from ISBN."""
        ctx = LookupContext.from_isbn(isbn="9780765365286")
        assert ctx.isbn == "9780765365286"
        assert ctx.asin is None

    def test_from_id_generic(self) -> None:
        """Test creating context from generic ID."""
        ctx = LookupContext.from_id(id_type="goodreads_id", identifier="7235533")
        assert ctx.ids.get("goodreads_id") == "7235533"

    def test_multiple_ids(self) -> None:
        """Test context with multiple IDs."""
        ctx = LookupContext(ids={"asin": "B08G9PRS1K", "isbn": "9780765365286"})
        assert ctx.asin == "B08G9PRS1K"
        assert ctx.isbn == "9780765365286"


# =============================================================================
# ProviderResult Tests
# =============================================================================


class TestProviderResult:
    """Tests for ProviderResult dataclass."""

    def test_set_field(self) -> None:
        """Test setting a field with confidence."""
        result = ProviderResult(provider="test", success=True)
        result.set_field("title", "The Way of Kings", confidence=0.95)

        assert result.fields["title"] == "The Way of Kings"
        assert result.confidence["title"] == 0.95

    def test_set_field_default_confidence(self) -> None:
        """Test setting a field uses default confidence 1.0."""
        result = ProviderResult(provider="test", success=True)
        result.set_field("title", "Test Book")

        assert result.confidence["title"] == 1.0

    def test_set_field_confidence_bounds_validation(self) -> None:
        """Test that confidence outside [0.0, 1.0] raises ValueError."""
        result = ProviderResult(provider="test", success=True)

        # Test confidence > 1.0
        with pytest.raises(ValueError, match=r"confidence must be in \[0\.0, 1\.0\], got 1\.5"):
            result.set_field("title", "Test", confidence=1.5)

        # Test confidence < 0.0
        with pytest.raises(ValueError, match=r"confidence must be in \[0\.0, 1\.0\], got -0\.1"):
            result.set_field("title", "Test", confidence=-0.1)

        # Valid edge cases should work
        result.set_field("title", "Test", confidence=0.0)
        assert result.confidence["title"] == 0.0

        result.set_field("authors", ["Author"], confidence=1.0)
        assert result.confidence["authors"] == 1.0

    def test_failure_factory(self) -> None:
        """Test creating failure result."""
        result = ProviderResult.failure("test", "Not found")

        assert result.success is False
        assert result.error == "Not found"
        assert result.provider == "test"

    def test_empty_factory(self) -> None:
        """Test creating empty success result."""
        result = ProviderResult.empty("test")

        assert result.success is True
        assert len(result.fields) == 0


# =============================================================================
# ProviderRegistry Tests
# =============================================================================


class TestProviderRegistry:
    """Tests for ProviderRegistry."""

    def test_register_and_get(self) -> None:
        """Test registering and retrieving a provider."""
        registry = ProviderRegistry()
        mock = MockProvider(name="test_provider")

        registry.register(mock)
        retrieved = registry.get("test_provider")

        assert retrieved is mock

    def test_get_nonexistent(self) -> None:
        """Test getting a non-existent provider returns None."""
        registry = ProviderRegistry()
        assert registry.get("nonexistent") is None

    def test_all_sorted_by_priority(self) -> None:
        """Test all() returns providers sorted by priority."""
        registry = ProviderRegistry()
        registry.register(MockProvider(name="low", priority=100))
        registry.register(MockProvider(name="high", priority=10))
        registry.register(MockProvider(name="medium", priority=50))

        providers = registry.all()
        names = [p.name for p in providers]

        assert names == ["high", "medium", "low"]

    def test_all_stable_sort_by_name(self) -> None:
        """Test all() uses name as tie-breaker for same priority."""
        registry = ProviderRegistry()
        registry.register(MockProvider(name="zeta", priority=50))
        registry.register(MockProvider(name="alpha", priority=50))
        registry.register(MockProvider(name="beta", priority=50))

        providers = registry.all()
        names = [p.name for p in providers]

        assert names == ["alpha", "beta", "zeta"]

    def test_get_for_context(self) -> None:
        """Test filtering providers by context."""
        registry = ProviderRegistry()
        # Provider that can handle ASIN
        registry.register(
            MockProvider(
                name="asin_provider",
                responses={"B08G9PRS1K": {"title": "Test"}},
                supported_id_types={"asin"},
            )
        )
        # Provider that only handles ISBN
        registry.register(
            MockProvider(
                name="isbn_provider",
                responses={"9780765365286": {"title": "Test"}},
                supported_id_types={"isbn"},
            )
        )

        ctx = LookupContext.from_asin(asin="B08G9PRS1K")
        providers = registry.get_for_context(ctx, "asin")

        assert len(providers) == 1
        assert providers[0].name == "asin_provider"

    def test_unregister(self) -> None:
        """Test unregistering a provider."""
        registry = ProviderRegistry()
        registry.register(MockProvider(name="test"))

        assert "test" in registry
        result = registry.unregister("test")
        assert result is True
        assert "test" not in registry

    def test_unregister_nonexistent(self) -> None:
        """Test unregistering non-existent provider returns False."""
        registry = ProviderRegistry()
        result = registry.unregister("nonexistent")
        assert result is False

    def test_clear(self) -> None:
        """Test clearing all providers."""
        registry = ProviderRegistry()
        registry.register(MockProvider(name="a"))
        registry.register(MockProvider(name="b"))

        registry.clear()

        assert len(registry) == 0

    def test_len(self) -> None:
        """Test registry length."""
        registry = ProviderRegistry()
        assert len(registry) == 0

        registry.register(MockProvider(name="a"))
        assert len(registry) == 1

        registry.register(MockProvider(name="b"))
        assert len(registry) == 2


# =============================================================================
# MockProvider Tests
# =============================================================================


class TestMockProvider:
    """Tests for MockProvider."""

    def test_protocol_compliance(self) -> None:
        """Test MockProvider implements MetadataProvider protocol."""
        mock = MockProvider()
        assert isinstance(mock, MetadataProvider)

    def test_can_lookup_with_response(self) -> None:
        """Test can_lookup returns True when response configured."""
        mock = MockProvider(responses={"B08G9PRS1K": {"title": "Test"}})
        ctx = LookupContext.from_asin(asin="B08G9PRS1K")

        assert mock.can_lookup(ctx, "asin") is True

    def test_can_lookup_without_response(self) -> None:
        """Test can_lookup returns False when no response configured."""
        mock = MockProvider()
        ctx = LookupContext.from_asin(asin="UNKNOWN")

        assert mock.can_lookup(ctx, "asin") is False

    def test_can_lookup_unsupported_id_type(self) -> None:
        """Test can_lookup returns False for unsupported ID type."""
        mock = MockProvider(
            responses={"B08G9PRS1K": {"title": "Test"}},
            supported_id_types={"asin"},
        )
        ctx = LookupContext(ids={"asin": "B08G9PRS1K", "isbn": "123"})

        assert mock.can_lookup(ctx, "asin") is True
        assert mock.can_lookup(ctx, "isbn") is False

    def test_fetch_returns_configured_response(self) -> None:
        """Test fetch returns configured response."""

        async def run_test() -> None:
            mock = MockProvider(
                responses={
                    "B08G9PRS1K": {
                        "title": "The Way of Kings",
                        "authors": [{"name": "Brandon Sanderson"}],
                    }
                }
            )
            ctx = LookupContext.from_asin(asin="B08G9PRS1K")

            result = await mock.fetch(ctx, "asin")

            assert result.success is True
            assert result.fields["title"] == "The Way of Kings"
            assert result.fields["authors"] == [{"name": "Brandon Sanderson"}]

        asyncio.run(run_test())

    def test_fetch_returns_error(self) -> None:
        """Test fetch returns configured error."""

        async def run_test() -> None:
            mock = MockProvider(errors={"BAD_ASIN": "Not found"})
            ctx = LookupContext.from_asin(asin="BAD_ASIN")

            result = await mock.fetch(ctx, "asin")

            assert result.success is False
            assert result.error == "Not found"

        asyncio.run(run_test())

    def test_fetch_tracks_history(self) -> None:
        """Test fetch tracks call history."""

        async def run_test() -> None:
            mock = MockProvider(responses={"A": {"title": "A"}, "B": {"title": "B"}})

            await mock.fetch(LookupContext.from_asin(asin="A"), "asin")
            await mock.fetch(LookupContext.from_asin(asin="B"), "asin")

            assert mock.fetch_count == 2
            assert len(mock.fetch_history) == 2

        asyncio.run(run_test())

    def test_reset(self) -> None:
        """Test reset clears history."""
        mock = MockProvider()
        mock._fetch_count = 5
        mock._fetch_history = [("ctx", "asin")]  # type: ignore[list-item]

        mock.reset()

        assert mock.fetch_count == 0
        assert len(mock.fetch_history) == 0


# =============================================================================
# AudnexProvider Tests
# =============================================================================


class TestAudnexProvider:
    """Tests for AudnexProvider."""

    def test_protocol_compliance(self) -> None:
        """Test AudnexProvider implements MetadataProvider protocol."""
        provider = AudnexProvider()
        assert isinstance(provider, MetadataProvider)

    def test_attributes(self) -> None:
        """Test provider has correct attributes."""
        provider = AudnexProvider()
        assert provider.name == "audnex"
        assert provider.kind == "network"
        assert provider.is_override is False
        assert provider.priority == 10

    def test_can_lookup_asin(self) -> None:
        """Test can_lookup returns True for ASIN."""
        provider = AudnexProvider()
        ctx = LookupContext.from_asin(asin="B08G9PRS1K")

        assert provider.can_lookup(ctx, "asin") is True

    def test_can_lookup_isbn_false(self) -> None:
        """Test can_lookup returns False for ISBN."""
        provider = AudnexProvider()
        ctx = LookupContext.from_isbn(isbn="9780765365286")

        assert provider.can_lookup(ctx, "isbn") is False

    def test_fetch_maps_audnex_response(self) -> None:
        """Test fetch correctly maps Audnex API response."""

        async def run_test() -> None:
            provider = AudnexProvider()
            ctx = LookupContext.from_asin(asin="B08G9PRS1K")

            mock_response = {
                "title": "The Way of Kings",
                "subtitle": "Book One of the Stormlight Archive",
                "authors": [{"name": "Brandon Sanderson", "asin": "B001IGFHW6"}],
                "narrators": [{"name": "Michael Kramer"}, {"name": "Kate Reading"}],
                "seriesPrimary": {"name": "Stormlight Archive", "position": "1"},
                "description": "<p>Epic fantasy...</p>",
                "publisherName": "Tor Books",
                "releaseDate": "2010-08-31",
                "language": "english",
                "genres": [{"name": "Fantasy", "asin": "G123"}],
                "image": "https://example.com/cover.jpg",
                "runtimeLengthMin": 2700,
            }

            with patch("shelfr.metadata.providers.audnex.fetch_audnex_book") as mock_fetch:
                mock_fetch.return_value = (mock_response, "us")
                result = await provider.fetch(ctx, "asin")

            assert result.success is True
            assert result.fields["title"] == "The Way of Kings"
            assert result.fields["subtitle"] == "Book One of the Stormlight Archive"
            assert result.fields["authors"] == [{"name": "Brandon Sanderson", "asin": "B001IGFHW6"}]
            assert len(result.fields["narrators"]) == 2
            assert result.fields["series_name"] == "Stormlight Archive"
            assert result.fields["series_position"] == "1"
            assert result.fields["publisher"] == "Tor Books"
            assert result.fields["duration_seconds"] == 2700 * 60

        asyncio.run(run_test())

    def test_fetch_not_found(self) -> None:
        """Test fetch returns failure when ASIN not found."""

        async def run_test() -> None:
            provider = AudnexProvider()
            # Use valid ASIN format that doesn't exist
            ctx = LookupContext.from_asin(asin="B000000000")

            with patch("shelfr.metadata.providers.audnex.fetch_audnex_book") as mock_fetch:
                mock_fetch.return_value = (None, None)
                result = await provider.fetch(ctx, "asin")

            assert result.success is False
            assert result.error is not None
            assert "not found" in result.error.lower()

        asyncio.run(run_test())

    def test_fetch_invalid_asin_format(self) -> None:
        """Test fetch rejects invalid ASIN format."""

        async def run_test() -> None:
            provider = AudnexProvider()

            # Too short
            ctx = LookupContext.from_asin(asin="B08G9")
            result = await provider.fetch(ctx, "asin")
            assert result.success is False
            assert "Invalid ASIN format" in result.error

            # Invalid characters (lowercase)
            ctx = LookupContext.from_asin(asin="b08g9prs1k")
            result = await provider.fetch(ctx, "asin")
            assert result.success is False
            assert "Invalid ASIN format" in result.error

            # Too long
            ctx = LookupContext.from_asin(asin="B08G9PRS1K1")
            result = await provider.fetch(ctx, "asin")
            assert result.success is False
            assert "Invalid ASIN format" in result.error

        asyncio.run(run_test())

    def test_fetch_preserves_is_adult_false(self) -> None:
        """Test is_adult=False is preserved, not skipped."""

        async def run_test() -> None:
            provider = AudnexProvider()
            ctx = LookupContext.from_asin(asin="B08G9PRS1K")

            mock_response = {
                "title": "Kids Book",
                "isAdult": False,  # Explicitly non-adult
            }

            with patch("shelfr.metadata.providers.audnex.fetch_audnex_book") as mock_fetch:
                mock_fetch.return_value = (mock_response, "us")
                result = await provider.fetch(ctx, "asin")

            assert result.success is True
            assert "is_adult" in result.fields
            assert result.fields["is_adult"] is False

        asyncio.run(run_test())

    def test_fetch_preserves_is_adult_true(self) -> None:
        """Test is_adult=True is also preserved."""

        async def run_test() -> None:
            provider = AudnexProvider()
            ctx = LookupContext.from_asin(asin="B08G9PRS1K")

            mock_response = {
                "title": "Adult Book",
                "isAdult": True,
            }

            with patch("shelfr.metadata.providers.audnex.fetch_audnex_book") as mock_fetch:
                mock_fetch.return_value = (mock_response, "us")
                result = await provider.fetch(ctx, "asin")

            assert result.success is True
            assert "is_adult" in result.fields
            assert result.fields["is_adult"] is True

        asyncio.run(run_test())


# =============================================================================
# MetadataAggregator Tests
# =============================================================================


class TestMetadataAggregator:
    """Tests for MetadataAggregator."""

    def test_single_provider(self) -> None:
        """Test aggregation with single provider."""

        async def run_test() -> None:
            registry = ProviderRegistry()
            registry.register(
                MockProvider(
                    name="test",
                    responses={
                        "B08G9PRS1K": {
                            "title": "Test Book",
                            "authors": [{"name": "Test Author"}],
                        }
                    },
                )
            )

            aggregator = MetadataAggregator(registry)
            ctx = LookupContext.from_asin(asin="B08G9PRS1K")
            result = await aggregator.fetch_all(ctx)

            assert result.fields["title"] == "Test Book"
            assert result.sources["title"] == "test"
            assert len(result.conflicts) == 0

        asyncio.run(run_test())

    def test_multiple_providers_no_conflict(self) -> None:
        """Test aggregation with multiple providers providing different fields."""

        async def run_test() -> None:
            registry = ProviderRegistry()
            registry.register(
                MockProvider(name="provider_a", priority=10, responses={"A": {"title": "Book A"}})
            )
            registry.register(
                MockProvider(
                    name="provider_b", priority=20, responses={"A": {"publisher": "Publisher B"}}
                )
            )

            aggregator = MetadataAggregator(registry)
            ctx = LookupContext.from_asin(asin="A")
            # stop_on_complete=False to ensure both providers contribute
            result = await aggregator.fetch_all(ctx, stop_on_complete=False)

            assert result.fields["title"] == "Book A"
            assert result.fields["publisher"] == "Publisher B"
            assert result.sources["title"] == "provider_a"
            assert result.sources["publisher"] == "provider_b"

        asyncio.run(run_test())

    def test_conflict_resolution_by_confidence(self) -> None:
        """Test conflict resolved by confidence score."""

        async def run_test() -> None:
            registry = ProviderRegistry()
            registry.register(
                MockProvider(
                    name="low_conf",
                    priority=10,
                    responses={"A": {"title": "Wrong Title"}},
                    confidences={"A": {"title": 0.5}},
                )
            )
            registry.register(
                MockProvider(
                    name="high_conf",
                    priority=20,
                    responses={"A": {"title": "Correct Title"}},
                    confidences={"A": {"title": 0.9}},
                )
            )

            aggregator = MetadataAggregator(registry, merge_strategy="confidence")
            ctx = LookupContext.from_asin(asin="A")
            # stop_on_complete=False to ensure both providers are queried
            result = await aggregator.fetch_all(ctx, stop_on_complete=False)

            assert result.fields["title"] == "Correct Title"
            assert len(result.conflicts) == 1
            assert result.conflicts[0].resolution_reason == "confidence"

        asyncio.run(run_test())

    def test_conflict_resolution_by_priority(self) -> None:
        """Test conflict resolved by priority when confidences equal."""

        async def run_test() -> None:
            registry = ProviderRegistry()
            registry.register(
                MockProvider(
                    name="high_priority",
                    priority=10,
                    responses={"A": {"title": "Priority Title"}},
                )
            )
            registry.register(
                MockProvider(
                    name="low_priority",
                    priority=50,
                    responses={"A": {"title": "Other Title"}},
                )
            )

            aggregator = MetadataAggregator(registry, merge_strategy="confidence")
            ctx = LookupContext.from_asin(asin="A")
            # stop_on_complete=False to ensure both providers are queried
            result = await aggregator.fetch_all(ctx, stop_on_complete=False)

            assert result.fields["title"] == "Priority Title"
            assert result.sources["title"] == "high_priority"

        asyncio.run(run_test())

    def test_priority_strategy(self) -> None:
        """Test merge_strategy='priority' ignores confidence."""

        async def run_test() -> None:
            registry = ProviderRegistry()
            registry.register(
                MockProvider(
                    name="high_priority",
                    priority=10,
                    responses={"A": {"title": "Priority Wins"}},
                    confidences={"A": {"title": 0.1}},  # Low confidence
                )
            )
            registry.register(
                MockProvider(
                    name="high_conf",
                    priority=50,
                    responses={"A": {"title": "Should Lose"}},
                    confidences={"A": {"title": 0.99}},  # High confidence
                )
            )

            aggregator = MetadataAggregator(registry, merge_strategy="priority")
            ctx = LookupContext.from_asin(asin="A")
            # stop_on_complete=False to ensure both providers are queried
            result = await aggregator.fetch_all(ctx, stop_on_complete=False)

            assert result.fields["title"] == "Priority Wins"

        asyncio.run(run_test())

    def test_skips_empty_values(self) -> None:
        """Test empty values are skipped unless from override provider."""

        async def run_test() -> None:
            registry = ProviderRegistry()
            registry.register(
                MockProvider(
                    name="empty",
                    priority=10,
                    responses={"A": {"title": "", "publisher": "Real Publisher"}},
                )
            )
            registry.register(
                MockProvider(
                    name="real",
                    priority=50,
                    responses={"A": {"title": "Real Title"}},
                )
            )

            aggregator = MetadataAggregator(registry)
            ctx = LookupContext.from_asin(asin="A")
            # stop_on_complete=False to ensure both providers are queried
            result = await aggregator.fetch_all(ctx, stop_on_complete=False)

            # Empty title from high-priority provider should be skipped
            assert result.fields["title"] == "Real Title"
            # Non-empty publisher from high-priority should be used
            assert result.fields["publisher"] == "Real Publisher"

        asyncio.run(run_test())

    def test_override_provider_can_set_empty(self) -> None:
        """Test override provider can intentionally set empty values."""

        async def run_test() -> None:
            registry = ProviderRegistry()
            registry.register(
                MockProvider(
                    name="override",
                    priority=10,
                    is_override=True,
                    responses={"A": {"title": ""}},  # Intentionally clearing
                )
            )
            registry.register(
                MockProvider(
                    name="normal",
                    priority=50,
                    responses={"A": {"title": "Should Be Cleared"}},
                )
            )

            aggregator = MetadataAggregator(registry)
            ctx = LookupContext.from_asin(asin="A")
            # stop_on_complete=False to ensure both providers are queried
            result = await aggregator.fetch_all(ctx, stop_on_complete=False)

            # Override provider's empty value should win
            assert result.fields["title"] == ""

        asyncio.run(run_test())

    def test_provider_failure_isolated(self) -> None:
        """Test one provider failure doesn't affect others."""

        async def run_test() -> None:
            registry = ProviderRegistry()
            registry.register(
                MockProvider(
                    name="failing",
                    priority=10,
                    errors={"A": "Connection failed"},
                )
            )
            registry.register(
                MockProvider(
                    name="working",
                    priority=50,
                    responses={"A": {"title": "Success"}},
                )
            )

            aggregator = MetadataAggregator(registry)
            ctx = LookupContext.from_asin(asin="A")
            # stop_on_complete=False to ensure all providers are queried
            result = await aggregator.fetch_all(ctx, stop_on_complete=False)

            assert result.fields["title"] == "Success"
            assert "failing" in result.errors
            assert result.errors["failing"] == "Connection failed"

        asyncio.run(run_test())

    def test_two_stage_fetch_local_first(self) -> None:
        """Test local providers run first in two-stage fetch."""

        async def run_test() -> None:
            registry = ProviderRegistry()

            # Local provider (should run first)
            local = MockProvider(
                name="local",
                priority=50,
                kind="local",
                responses={"A": {"title": "Local Title"}},
            )
            registry.register(local)

            # Network provider (should not run if local fills required fields)
            network = MockProvider(
                name="network",
                priority=10,
                kind="network",
                responses={"A": {"title": "Network Title", "publisher": "Network Pub"}},
            )
            registry.register(network)

            aggregator = MetadataAggregator(registry)
            ctx = LookupContext.from_asin(asin="A")
            result = await aggregator.fetch_all(
                ctx, required_fields=["title"], stop_on_complete=True
            )

            # Local title should be used, network not called
            assert result.fields["title"] == "Local Title"
            assert network.fetch_count == 0
            assert "publisher" not in result.fields

        asyncio.run(run_test())

    def test_two_stage_fetch_network_when_needed(self) -> None:
        """Test network providers run when local doesn't fill required fields."""

        async def run_test() -> None:
            registry = ProviderRegistry()

            local = MockProvider(
                name="local",
                priority=50,
                kind="local",
                responses={"A": {"publisher": "Local Pub"}},  # No title
            )
            registry.register(local)

            network = MockProvider(
                name="network",
                priority=10,
                kind="network",
                responses={"A": {"title": "Network Title"}},
            )
            registry.register(network)

            aggregator = MetadataAggregator(registry)
            ctx = LookupContext.from_asin(asin="A")
            result = await aggregator.fetch_all(
                ctx, required_fields=["title"], stop_on_complete=True
            )

            # Network should have been called to get title
            assert result.fields["title"] == "Network Title"
            assert network.fetch_count == 1

        asyncio.run(run_test())

    def test_tracks_missing_fields(self) -> None:
        """Test missing fields are tracked."""

        async def run_test() -> None:
            registry = ProviderRegistry()
            registry.register(MockProvider(name="test", responses={"A": {"title": "Test"}}))

            aggregator = MetadataAggregator(registry)
            ctx = LookupContext.from_asin(asin="A")
            result = await aggregator.fetch_all(ctx)

            # All fields except title should be in missing
            assert "title" not in result.missing
            assert "authors" in result.missing
            assert "publisher" in result.missing

        asyncio.run(run_test())

    def test_specific_providers_filter(self) -> None:
        """Test providers parameter filters to specific providers."""

        async def run_test() -> None:
            registry = ProviderRegistry()
            registry.register(MockProvider(name="include", responses={"A": {"title": "Included"}}))
            registry.register(
                MockProvider(name="exclude", responses={"A": {"publisher": "Excluded"}})
            )

            aggregator = MetadataAggregator(registry)
            ctx = LookupContext.from_asin(asin="A")
            result = await aggregator.fetch_all(ctx, providers=["include"])

            assert result.fields["title"] == "Included"
            assert "publisher" not in result.fields

        asyncio.run(run_test())

    def test_no_providers_returns_empty(self) -> None:
        """Test empty registry returns result with all fields missing."""

        async def run_test() -> None:
            registry = ProviderRegistry()
            aggregator = MetadataAggregator(registry)
            ctx = LookupContext.from_asin(asin="A")
            result = await aggregator.fetch_all(ctx)

            assert len(result.fields) == 0
            assert len(result.missing) > 0

        asyncio.run(run_test())


# =============================================================================
# Integration Tests
# =============================================================================


class TestProviderIntegration:
    """Integration tests for the provider system."""

    def test_full_workflow(self) -> None:
        """Test typical workflow: register providers, fetch, merge."""

        async def run_test() -> None:
            # Set up registry
            registry = ProviderRegistry()

            # Simulated Audnex-like provider
            registry.register(
                MockProvider(
                    name="audnex",
                    priority=10,
                    kind="network",
                    responses={
                        "B08G9PRS1K": {
                            "title": "The Way of Kings",
                            "authors": [{"name": "Brandon Sanderson"}],
                            "series_name": "Stormlight Archive",
                        }
                    },
                )
            )

            # Simulated MediaInfo-like provider (local)
            registry.register(
                MockProvider(
                    name="mediainfo",
                    priority=20,
                    kind="local",
                    responses={
                        "B08G9PRS1K": {
                            "duration_seconds": 162000,
                            "codec": "AAC",
                            "bitrate": 128,
                        }
                    },
                )
            )

            # Fetch and aggregate
            aggregator = MetadataAggregator(registry)
            ctx = LookupContext.from_asin(asin="B08G9PRS1K")
            result = await aggregator.fetch_all(ctx, stop_on_complete=False)

            # Verify merged result
            assert result.fields["title"] == "The Way of Kings"
            assert result.fields["authors"] == [{"name": "Brandon Sanderson"}]
            assert result.fields["duration_seconds"] == 162000
            assert result.fields["codec"] == "AAC"

            # Verify sources
            assert result.sources["title"] == "audnex"
            assert result.sources["duration_seconds"] == "mediainfo"

        asyncio.run(run_test())
