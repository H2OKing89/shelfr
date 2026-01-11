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
    # Phase 10.6 concurrency settings
    settings.audnex.rate_limit_per_minute = 90
    settings.audnex.burst_limit = 10.0
    settings.audnex.burst_period = 5.0
    settings.audnex.asin_concurrency = 5
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
        """Client initializes with default parameters from config."""
        client = AudnexAsyncClient()
        assert client is not None
        # Should use config defaults (90/min, 10 burst, 5 ASIN concurrency)
        assert client._minute_limiter.max_rate == 90
        assert client._burst_limiter.max_rate == 10.0
        assert client._asin_semaphore._value == 5

    def test_custom_minute_limit(self) -> None:
        """Client accepts custom minute rate limit."""
        client = AudnexAsyncClient(rate_limit_per_min=60)
        assert client._minute_limiter.max_rate == 60

    def test_custom_burst_limit(self) -> None:
        """Client accepts custom burst rate limit."""
        client = AudnexAsyncClient(burst_limit=5)
        assert client._burst_limiter.max_rate == 5

    def test_custom_asin_concurrency(self) -> None:
        """Client accepts custom ASIN concurrency limit."""
        client = AudnexAsyncClient(asin_concurrency=10)
        assert client._asin_semaphore._value == 10


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

    @pytest.mark.asyncio
    async def test_404_returns_none(self) -> None:
        """Returns None for 404 responses."""
        client = AudnexAsyncClient()

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch.object(client, "_http_client") as mock_http:
            mock_http.get = AsyncMock(return_value=mock_response)

            result = await client._fetch_chapters_region("INVALID123", "us")

            assert result is None

    @pytest.mark.asyncio
    async def test_500_returns_none(self) -> None:
        """Returns None for 500 responses (treated as not found)."""
        client = AudnexAsyncClient()

        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch.object(client, "_http_client") as mock_http:
            mock_http.get = AsyncMock(return_value=mock_response)

            result = await client._fetch_chapters_region("B08G9PRS1K", "us")

            assert result is None


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

            (data, region), definitive_404s, request_count = await client._race_regions(
                "B08G9PRS1K", ["us", "uk", "de"], STAGE_1_TIMEOUT
            )

            assert data is not None
            assert isinstance(data, dict)
            assert region == "us"
            # 404s only collected for non-successful probes
            assert isinstance(definitive_404s, set)
            assert request_count >= 1

    @pytest.mark.asyncio
    async def test_collects_definitive_404s(self) -> None:
        """Collects 404s from regions that definitively don't have the ASIN."""
        client = AudnexAsyncClient()

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch.object(client, "_http_client") as mock_http:
            mock_http.get = AsyncMock(return_value=mock_response)

            (data, region), definitive_404s, request_count = await client._race_regions(
                "INVALID123", ["us", "uk"], STAGE_1_TIMEOUT
            )

            assert data is None
            assert region is None
            assert "us" in definitive_404s
            assert "uk" in definitive_404s
            assert len(definitive_404s) == 2
            assert request_count == 2


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

            data, region, stage, total_requests, elapsed = await client._staged_race(
                "B08G9PRS1K", cached_region="uk"
            )

            assert data is not None
            assert region == "uk"
            assert stage == 0  # Cache hit is stage 0
            # Should only make one request (cached region hit)
            assert call_count == 1
            assert total_requests == 1
            assert elapsed >= 0

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

            data, region, stage, _total_requests, _elapsed = await client._staged_race("B08G9PRS1K")

            assert data is not None
            assert region in STAGE_1_REGIONS
            assert stage == 1  # Stage 1 success

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

            data, region, stage, _total_requests, _elapsed = await client._staged_race("B08G9PRS1K")

            # Should succeed from Stage 2
            assert data is not None
            assert region not in STAGE_1_REGIONS
            assert stage == 2  # Stage 2 success


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
            # Verify region parameter is in the request params
            call_params = mock_http.get.call_args[1].get("params", {})
            assert call_params.get("region") == "uk"


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
            assert region in ALL_REGIONS


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

    @pytest.mark.asyncio
    async def test_invalid_response_logs_warning(self, caplog) -> None:
        """Invalid response logs validation warning but still returns data."""
        import logging

        client = AudnexAsyncClient()

        # Missing required fields like 'title', 'authors'
        invalid_response = {"asin": "B08G9PRS1K", "region": "us"}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = invalid_response

        with (
            patch.object(client, "_http_client") as mock_http,
            caplog.at_level(logging.WARNING),
        ):
            mock_http.get = AsyncMock(return_value=mock_response)

            # Should still return data despite validation warning
            result = await client._fetch_book_region("B08G9PRS1K", "us")
            assert result is not None
            assert result == invalid_response

            # Verify validation warning was logged
            assert any("validation" in record.message.lower() for record in caplog.records)


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


class TestBatchFetch:
    """Test batch fetch with ASIN semaphore."""

    @pytest.fixture
    def mock_region_cache(self):
        """Create a mock region cache for batch tests."""
        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()
        mock_cache.record_failure = AsyncMock()
        return mock_cache

    @pytest.mark.asyncio
    async def test_batch_fetch_returns_all_asins(
        self, sample_book_response: dict[str, Any], mock_region_cache
    ) -> None:
        """Batch fetch returns results for all ASINs."""
        asins = ["B08G9PRS1K", "B00HBQRIHY", "B000FBJCJE"]

        async with AudnexAsyncClient() as client:
            # Mock fetch_book_parallel to return data for each ASIN
            async def mock_fetch(asin: str, cached_region: str | None = None):
                response = sample_book_response.copy()
                response["asin"] = asin
                return response, "us"

            with patch.object(client, "fetch_book_parallel", side_effect=mock_fetch):
                results = await client.fetch_batch(asins, region_cache=mock_region_cache)

                assert len(results) == 3
                for asin, data, region in results:
                    assert asin in asins
                    assert data is not None
                    assert region == "us"

    @pytest.mark.asyncio
    async def test_batch_fetch_handles_failures(
        self, sample_book_response: dict[str, Any], mock_region_cache
    ) -> None:
        """Batch fetch handles individual ASIN failures gracefully."""
        asins = ["B08G9PRS1K", "INVALID123", "B000FBJCJE"]

        async with AudnexAsyncClient() as client:
            # Mock: first and third succeed, second fails
            async def mock_fetch(asin: str, cached_region: str | None = None):
                if asin == "INVALID123":
                    return None, None
                response = sample_book_response.copy()
                response["asin"] = asin
                return response, "us"

            with patch.object(client, "fetch_book_parallel", side_effect=mock_fetch):
                results = await client.fetch_batch(asins, region_cache=mock_region_cache)

                assert len(results) == 3
                # Check successful results
                assert results[0][1] is not None  # First ASIN succeeded
                assert results[2][1] is not None  # Third ASIN succeeded
                # Check failed result
                assert results[1][0] == "INVALID123"
                assert results[1][1] is None
                assert results[1][2] is None

    @pytest.mark.asyncio
    async def test_batch_fetch_respects_semaphore(self, mock_region_cache) -> None:
        """Batch fetch respects ASIN concurrency semaphore."""
        asins = ["ASIN1", "ASIN2", "ASIN3", "ASIN4", "ASIN5", "ASIN6"]
        max_concurrent_observed = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        # Create client with concurrency limit of 2
        async with AudnexAsyncClient(asin_concurrency=2) as client:

            async def mock_fetch(asin: str, cached_region: str | None = None):
                nonlocal max_concurrent_observed, current_concurrent
                async with lock:
                    current_concurrent += 1
                    max_concurrent_observed = max(max_concurrent_observed, current_concurrent)

                # Simulate some async work
                await asyncio.sleep(0.05)

                async with lock:
                    current_concurrent -= 1

                return {
                    "asin": asin,
                    "title": f"Book {asin}",
                    "authors": [{"name": "Author"}],
                }, "us"

            with patch.object(client, "fetch_book_parallel", side_effect=mock_fetch):
                results = await client.fetch_batch(asins, region_cache=mock_region_cache)

                assert len(results) == 6
                # Should never exceed semaphore limit of 2
                assert max_concurrent_observed <= 2

    @pytest.mark.asyncio
    async def test_batch_fetch_with_chapters(
        self,
        sample_book_response: dict[str, Any],
        sample_chapters_response: dict[str, Any],
        mock_region_cache,
    ) -> None:
        """Batch fetch includes chapters when requested."""
        asins = ["B08G9PRS1K"]

        async with AudnexAsyncClient() as client:

            async def mock_fetch_book(asin: str, cached_region: str | None = None):
                return sample_book_response.copy(), "us"

            async def mock_fetch_chapters(asin: str, region: str):
                return sample_chapters_response.copy()

            with (
                patch.object(client, "fetch_book_parallel", side_effect=mock_fetch_book),
                patch.object(client, "fetch_chapters", side_effect=mock_fetch_chapters),
            ):
                results = await client.fetch_batch(
                    asins, region_cache=mock_region_cache, include_chapters=True
                )

                assert len(results) == 1
                _asin, data, _region = results[0]
                assert data is not None
                # chapters is the entire chapters response dict, not just the list
                assert "chapters" in data
                chapters_data = data["chapters"]
                assert chapters_data["asin"] == "B08G9PRS1K"
                assert len(chapters_data["chapters"]) == 2

    @pytest.mark.asyncio
    async def test_batch_fetch_caches_winning_regions(
        self, sample_book_response: dict[str, Any], mock_region_cache
    ) -> None:
        """Batch fetch caches winning regions for successful lookups."""
        asins = ["B08G9PRS1K", "B00HBQRIHY"]

        async with AudnexAsyncClient() as client:

            async def mock_fetch(asin: str, cached_region: str | None = None):
                response = sample_book_response.copy()
                response["asin"] = asin
                return response, "uk"  # Simulating UK region wins

            with patch.object(client, "fetch_book_parallel", side_effect=mock_fetch):
                await client.fetch_batch(asins, region_cache=mock_region_cache)

                # Should have called cache.set for each successful ASIN
                assert mock_region_cache.set.call_count == 2
                # Verify correct region was cached
                mock_region_cache.set.assert_any_call("B08G9PRS1K", "uk")
                mock_region_cache.set.assert_any_call("B00HBQRIHY", "uk")
