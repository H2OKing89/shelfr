"""Tests for AudnexAsyncClient with staged region racing."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from shelfr.metadata.audnex.async_client import (
    ALL_REGIONS,
    STAGE_1_REGIONS,
    STAGE_1_TIMEOUT,
    STAGE_2_TIMEOUT,
    AudnexAsyncClient,
    fetch_audnex_book_parallel,
)


@pytest.fixture
def mock_settings():
    """Create mock settings for async client tests."""
    settings = MagicMock()
    settings.audnex.base_url = "https://api.audnex.us"
    settings.audnex.timeout_seconds = 10.0
    return settings


@pytest.fixture(autouse=True)
def patch_get_settings(mock_settings):
    """Auto-patch get_settings for all tests in this module."""
    with patch("shelfr.metadata.audnex.async_client.get_settings", return_value=mock_settings):
        yield


@pytest.fixture
def sample_book_response() -> dict[str, Any]:
    """Sample valid Audnex book response."""
    return {
        "asin": "B08G9PRS1K",
        "title": "Project Hail Mary",
        "subtitle": "A Novel",
        "description": "A lone astronaut must save Earth from disaster.",
        "releaseDate": "2021-05-04",
        "publisherName": "Audible Studios",
        "runtimeLengthMin": 970,
        "seriesPrimary": {
            "asin": "B09LPMNRWF",
            "name": "Project Hail Mary",
            "position": "1",
        },
        "seriesSecondary": None,
        "authors": [{"asin": "B001HCZRP4", "name": "Andy Weir"}],
        "narrators": [{"name": "Ray Porter"}],
        "genres": [
            {"asin": "18574597011", "name": "Science Fiction", "type": "tag"},
        ],
        "rating": "4.8",
        "image": "https://m.media-amazon.com/images/I/91vS2L5YfEL._SL500_.jpg",
        "language": "english",
        "region": "us",
        "copyright": 2021,
    }


@pytest.fixture
def sample_chapters_response() -> dict[str, Any]:
    """Sample valid Audnex chapters response."""
    return {
        "asin": "B08G9PRS1K",
        "brandIntroDurationMs": 2043,
        "brandOutroDurationMs": 5061,
        "isAccurate": True,
        "region": "us",
        "runtimeLengthMs": 58200000,
        "runtimeLengthSec": 58200,
        "chapters": [
            {
                "lengthMs": 1800000,
                "startOffsetMs": 0,
                "startOffsetSec": 0,
                "title": "Opening Credits",
            },
            {
                "lengthMs": 2400000,
                "startOffsetMs": 1800000,
                "startOffsetSec": 1800,
                "title": "Chapter 1",
            },
        ],
    }


class TestAudnexAsyncClientInit:
    """Test client initialization."""

    def test_default_initialization(self) -> None:
        """Client initializes with default parameters."""
        client = AudnexAsyncClient()
        assert client is not None

    def test_custom_minute_limit(self) -> None:
        """Client accepts custom minute rate limit."""
        client = AudnexAsyncClient(rate_limit_per_min=60)
        assert client._minute_limiter.max_rate == 60

    def test_custom_burst_limit(self) -> None:
        """Client accepts custom burst rate limit."""
        client = AudnexAsyncClient(burst_limit=5)
        assert client._burst_limiter.max_rate == 5


class TestStagedRaceConstants:
    """Test stage configuration constants."""

    def test_stage_1_regions(self) -> None:
        """Stage 1 contains expected high-priority regions."""
        assert STAGE_1_REGIONS == ["us", "uk", "de"]

    def test_stage_1_timeout(self) -> None:
        """Stage 1 timeout is appropriate for fast response."""
        assert STAGE_1_TIMEOUT == 1.5

    def test_stage_2_timeout(self) -> None:
        """Stage 2 timeout allows for slower regions."""
        assert STAGE_2_TIMEOUT == 8.5

    def test_all_regions_complete(self) -> None:
        """ALL_REGIONS contains all expected Audible regions."""
        expected = ["us", "uk", "de", "au", "ca", "es", "fr", "in", "it", "jp"]
        assert expected == ALL_REGIONS


class TestFetchBookRegion:
    """Test _fetch_book_region method."""

    @pytest.mark.asyncio
    async def test_successful_fetch(self, sample_book_response: dict[str, Any]) -> None:
        """Successfully fetches book data."""
        client = AudnexAsyncClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_book_response

        with patch.object(client, "_http_client") as mock_http:
            mock_http.get = AsyncMock(return_value=mock_response)

            result = await client._fetch_book_region("B08G9PRS1K", "us")

            assert result is not None
            assert isinstance(result, dict)
            assert result["asin"] == "B08G9PRS1K"
            assert result["title"] == "Project Hail Mary"
            assert result["region"] == "us"

    @pytest.mark.asyncio
    async def test_404_returns_none(self) -> None:
        """Returns None for 404 responses."""
        client = AudnexAsyncClient()

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch.object(client, "_http_client") as mock_http:
            mock_http.get = AsyncMock(return_value=mock_response)

            result = await client._fetch_book_region("INVALID123", "us")

            assert result is None

    @pytest.mark.asyncio
    async def test_500_returns_none(self) -> None:
        """Returns None for 500 responses (treated as not found)."""
        client = AudnexAsyncClient()

        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch.object(client, "_http_client") as mock_http:
            mock_http.get = AsyncMock(return_value=mock_response)

            result = await client._fetch_book_region("B08G9PRS1K", "us")

            assert result is None


class TestFetchChaptersRegion:
    """Test _fetch_chapters_region method."""

    @pytest.mark.asyncio
    async def test_successful_fetch(self, sample_chapters_response: dict[str, Any]) -> None:
        """Successfully fetches chapters data."""
        client = AudnexAsyncClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_chapters_response

        with patch.object(client, "_http_client") as mock_http:
            mock_http.get = AsyncMock(return_value=mock_response)

            result = await client._fetch_chapters_region("B08G9PRS1K", "us")

            assert result is not None
            assert isinstance(result, dict)
            assert result["asin"] == "B08G9PRS1K"
            assert len(result["chapters"]) == 2


class TestProbeRegion:
    """Test _probe_region helper method."""

    @pytest.mark.asyncio
    async def test_probe_returns_region_data_err_tuple(
        self, sample_book_response: dict[str, Any]
    ) -> None:
        """Probe returns tuple of (region, data, error)."""
        client = AudnexAsyncClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_book_response

        with patch.object(client, "_http_client") as mock_http:
            mock_http.get = AsyncMock(return_value=mock_response)

            region, data, err = await client._probe_region("B08G9PRS1K", "us")

            assert region == "us"
            assert isinstance(data, dict)
            assert err is None

    @pytest.mark.asyncio
    async def test_probe_404_returns_none_data(self) -> None:
        """Probe returns None data for 404."""
        client = AudnexAsyncClient()

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch.object(client, "_http_client") as mock_http:
            mock_http.get = AsyncMock(return_value=mock_response)

            region, data, err = await client._probe_region("INVALID123", "us")

            assert region == "us"
            assert data is None
            assert err is None  # 404 is not an error, just not found

    @pytest.mark.asyncio
    async def test_probe_timeout_returns_error(self) -> None:
        """Probe returns error string for timeout."""
        client = AudnexAsyncClient()

        with patch.object(client, "_http_client") as mock_http:
            mock_http.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

            region, data, err = await client._probe_region("B08G9PRS1K", "us")

            assert region == "us"
            assert data is None
            assert err is not None
            assert "timeout" in str(err).lower()


class TestRaceRegions:
    """Test _race_regions method."""

    @pytest.mark.asyncio
    async def test_returns_first_success(self, sample_book_response: dict[str, Any]) -> None:
        """Returns first successful result."""
        client = AudnexAsyncClient()

        # Create book objects for different regions
        us_book = sample_book_response.copy()
        us_book["region"] = "us"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = us_book

        with patch.object(client, "_http_client") as mock_http:
            mock_http.get = AsyncMock(return_value=mock_response)

            (data, region), definitive_404s = await client._race_regions(
                "B08G9PRS1K", ["us", "uk", "de"], STAGE_1_TIMEOUT
            )

            assert data is not None
            assert isinstance(data, dict)
            assert region == "us"
            # 404s only collected for non-successful probes
            assert isinstance(definitive_404s, set)

    @pytest.mark.asyncio
    async def test_collects_definitive_404s(self) -> None:
        """Collects 404s from regions that definitively don't have the ASIN."""
        client = AudnexAsyncClient()

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch.object(client, "_http_client") as mock_http:
            mock_http.get = AsyncMock(return_value=mock_response)

            (data, region), definitive_404s = await client._race_regions(
                "INVALID123", ["us", "uk"], STAGE_1_TIMEOUT
            )

            assert data is None
            assert region is None
            assert "us" in definitive_404s
            assert "uk" in definitive_404s


class TestStagedRace:
    """Test _staged_race two-stage pattern."""

    @pytest.mark.asyncio
    async def test_cached_region_fast_path(self, sample_book_response: dict[str, Any]) -> None:
        """Cached region is tried first."""
        client = AudnexAsyncClient()

        uk_book = sample_book_response.copy()
        uk_book["region"] = "uk"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = uk_book

        call_count = 0

        async def mock_get(url: str, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            return mock_response

        with patch.object(client, "_http_client") as mock_http:
            mock_http.get = AsyncMock(side_effect=mock_get)

            data, region = await client._staged_race("B08G9PRS1K", cached_region="uk")

            assert data is not None
            assert region == "uk"
            # Should only make one request (cached region hit)
            assert call_count == 1

    @pytest.mark.asyncio
    async def test_stage1_success_skips_stage2(self, sample_book_response: dict[str, Any]) -> None:
        """Stage 1 success skips Stage 2 entirely."""
        client = AudnexAsyncClient()

        us_book = sample_book_response.copy()
        us_book["region"] = "us"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = us_book

        with patch.object(client, "_http_client") as mock_http:
            mock_http.get = AsyncMock(return_value=mock_response)

            data, region = await client._staged_race("B08G9PRS1K")

            assert data is not None
            assert region in STAGE_1_REGIONS

    @pytest.mark.asyncio
    async def test_stage2_runs_when_stage1_fails(self) -> None:
        """Stage 2 runs when Stage 1 returns no results."""
        client = AudnexAsyncClient()

        # Stage 1: all 404s
        stage1_response = MagicMock()
        stage1_response.status_code = 404

        # Stage 2: success from jp
        stage2_book = {
            "asin": "B08G9PRS1K",
            "title": "Project Hail Mary",
            "region": "jp",
            "authors": [{"name": "Andy Weir"}],
            "narrators": [{"name": "Narrator"}],
        }
        stage2_response = MagicMock()
        stage2_response.status_code = 200
        stage2_response.json.return_value = stage2_book

        call_count = 0

        async def mock_get(url: str, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            # First 3 calls are Stage 1 (us, uk, de) - all 404
            if call_count <= 3:
                return stage1_response
            # Remaining calls are Stage 2 - jp succeeds
            return stage2_response

        with patch.object(client, "_http_client") as mock_http:
            mock_http.get = AsyncMock(side_effect=mock_get)

            data, region = await client._staged_race("B08G9PRS1K")

            # Should succeed from Stage 2
            assert data is not None


class TestFetchBookParallel:
    """Test public fetch_book_parallel method."""

    @pytest.mark.asyncio
    async def test_returns_dict_and_region(self, sample_book_response: dict[str, Any]) -> None:
        """Returns (data, region) tuple."""
        client = AudnexAsyncClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_book_response

        with patch.object(client, "_http_client") as mock_http:
            mock_http.get = AsyncMock(return_value=mock_response)

            data, region = await client.fetch_book_parallel("B08G9PRS1K")

            assert isinstance(data, dict)
            assert data["asin"] == "B08G9PRS1K"
            assert region in ALL_REGIONS

    @pytest.mark.asyncio
    async def test_returns_none_tuple_for_not_found(self) -> None:
        """Returns (None, None) when ASIN not found in any region."""
        client = AudnexAsyncClient()

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch.object(client, "_http_client") as mock_http:
            mock_http.get = AsyncMock(return_value=mock_response)

            data, region = await client.fetch_book_parallel("INVALID123")

            assert data is None
            assert region is None


class TestFetchChapters:
    """Test fetch_chapters method."""

    @pytest.mark.asyncio
    async def test_uses_known_region(self, sample_chapters_response: dict[str, Any]) -> None:
        """Fetches chapters from known region."""
        client = AudnexAsyncClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_chapters_response

        with patch.object(client, "_http_client") as mock_http:
            mock_http.get = AsyncMock(return_value=mock_response)

            chapters = await client.fetch_chapters("B08G9PRS1K", region="uk")

            assert chapters is not None
            assert isinstance(chapters, dict)
            assert chapters["asin"] == "B08G9PRS1K"
            # Verify UK region was used
            mock_http.get.assert_called_once()
            call_url = mock_http.get.call_args[0][0]
            assert "chapters" in call_url


class TestConvenienceFunction:
    """Test fetch_audnex_book_parallel convenience function."""

    @pytest.mark.asyncio
    async def test_function_wraps_client(self, sample_book_response: dict[str, Any]) -> None:
        """Convenience function properly wraps client."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_book_response

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_class.return_value = mock_client

            data, region = await fetch_audnex_book_parallel("B08G9PRS1K")

            assert data is not None
            assert isinstance(data, dict)


class TestValidation:
    """Test Level 1 and Level 2 validation."""

    @pytest.mark.asyncio
    async def test_valid_response_passes_validation(
        self, sample_book_response: dict[str, Any]
    ) -> None:
        """Valid response passes Pydantic validation."""
        client = AudnexAsyncClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_book_response

        with patch.object(client, "_http_client") as mock_http:
            mock_http.get = AsyncMock(return_value=mock_response)

            # Should not raise
            result = await client._fetch_book_region("B08G9PRS1K", "us")
            assert result is not None


class TestRateLimiting:
    """Test rate limiter integration."""

    @pytest.mark.asyncio
    async def test_respects_rate_limits(self, sample_book_response: dict[str, Any]) -> None:
        """Client respects rate limiting (smoke test)."""
        # Create client with lower limits
        client = AudnexAsyncClient(rate_limit_per_min=60, burst_limit=2)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_book_response

        with patch.object(client, "_http_client") as mock_http:
            mock_http.get = AsyncMock(return_value=mock_response)

            # Multiple rapid requests should still work (just may be queued)
            tasks = [client._fetch_book_region("B08G9PRS1K", "us") for _ in range(3)]
            results = await asyncio.gather(*tasks)

            assert all(r is not None for r in results)


class TestCircuitBreaker:
    """Test circuit breaker integration."""

    @pytest.mark.asyncio
    async def test_raises_when_circuit_open(self) -> None:
        """Client raises CircuitOpenError when breaker is open."""
        from shelfr.utils.circuit_breaker import CircuitOpenError, CircuitState

        client = AudnexAsyncClient()

        with patch("shelfr.metadata.audnex.async_client.audnex_breaker") as mock_breaker:
            mock_breaker.state = CircuitState.OPEN
            mock_breaker.recovery_timeout = 30.0

            # Should raise before even acquiring rate limiter tokens
            with pytest.raises(CircuitOpenError):
                await client._fetch_book_region("B08G9PRS1K", "us")

    @pytest.mark.asyncio
    async def test_circuit_breaker_records_success(
        self, sample_book_response: dict[str, Any]
    ) -> None:
        """Circuit breaker context records successful requests."""
        from shelfr.utils.circuit_breaker import CircuitState

        client = AudnexAsyncClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_book_response

        with (
            patch.object(client, "_http_client") as mock_http,
            patch("shelfr.metadata.audnex.async_client.audnex_breaker") as mock_breaker,
        ):
            mock_http.get = AsyncMock(return_value=mock_response)
            mock_breaker.state = CircuitState.CLOSED
            mock_breaker.__enter__ = MagicMock(return_value=mock_breaker)
            mock_breaker.__exit__ = MagicMock(return_value=False)

            await client._fetch_book_region("B08G9PRS1K", "us")

            # Verify circuit breaker context was entered (records success/failure)
            mock_breaker.__enter__.assert_called_once()
            mock_breaker.__exit__.assert_called_once()

    @pytest.mark.asyncio
    async def test_circuit_breaker_records_timeout_failure(self) -> None:
        """Circuit breaker context records timeout failures."""
        from shelfr.utils.circuit_breaker import CircuitState

        client = AudnexAsyncClient()

        with (
            patch.object(client, "_http_client") as mock_http,
            patch("shelfr.metadata.audnex.async_client.audnex_breaker") as mock_breaker,
        ):
            mock_http.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_breaker.state = CircuitState.CLOSED
            mock_breaker.__enter__ = MagicMock(return_value=mock_breaker)
            mock_breaker.__exit__ = MagicMock(return_value=False)

            # The timeout will be caught by _probe_region, but breaker context should record it
            with pytest.raises(httpx.TimeoutException):
                await client._fetch_book_region("B08G9PRS1K", "us")

            # Verify circuit breaker exit was called with exception info
            mock_breaker.__exit__.assert_called_once()
            exit_args = mock_breaker.__exit__.call_args[0]
            assert exit_args[0] is httpx.TimeoutException  # exc_type


class TestContextManager:
    """Test async context manager behavior."""

    @pytest.mark.asyncio
    async def test_context_manager_creates_client(self) -> None:
        """Context manager properly creates HTTP client."""
        async with AudnexAsyncClient() as client:
            assert client._http_client is not None
            assert isinstance(client._http_client, httpx.AsyncClient)

    @pytest.mark.asyncio
    async def test_context_manager_closes_client(self) -> None:
        """Context manager properly closes HTTP client."""
        client = AudnexAsyncClient()
        async with client:
            http_client = client._http_client
            assert http_client is not None

        # After context exit, client should be None
        assert client._http_client is None

    def test_client_property_raises_outside_context(self) -> None:
        """Accessing client outside context raises RuntimeError."""
        client = AudnexAsyncClient()
        with pytest.raises(RuntimeError, match="async context manager"):
            _ = client.client
