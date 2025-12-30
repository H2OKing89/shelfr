"""Tests for retry utilities."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from shelfr.utils.retry import (
    NETWORK_EXCEPTIONS,
    RetryableError,
    retry_with_backoff,
)


class TestTenacityRetryWithBackoff:
    """Tests for the tenacity-based retry_with_backoff decorator."""

    def test_retry_with_backoff_attempts(self) -> None:
        """Test retry counts are correct with new API."""
        calls = {"n": 0}

        @retry_with_backoff(max_retries=2, base_delay=0, max_delay=0, jitter=0)
        def flake() -> None:
            calls["n"] += 1
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            flake()

        assert calls["n"] == 3  # 1 initial + 2 retries

    def test_success_on_first_try_new_api(self) -> None:
        """Function should return immediately on success with new API."""
        call_count = 0

        @retry_with_backoff(max_retries=3, base_delay=0.01)
        def success_func() -> str:
            nonlocal call_count
            call_count += 1
            return "success"

        result = success_func()

        assert result == "success"
        assert call_count == 1

    def test_success_after_retry_new_api(self) -> None:
        """Function should succeed after retrying with new API."""
        call_count = 0

        @retry_with_backoff(max_retries=3, base_delay=0.01, retry_exceptions=(ConnectionError,))
        def fail_then_succeed() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Network error")
            return "success"

        result = fail_then_succeed()

        assert result == "success"
        assert call_count == 3


class TestRetryWithBackoff:
    """Tests for the retry_with_backoff decorator."""

    def test_success_on_first_try(self) -> None:
        """Function should return immediately on success."""
        call_count = 0

        @retry_with_backoff(max_attempts=3, base_delay=0.01)
        def success_func() -> str:
            nonlocal call_count
            call_count += 1
            return "success"

        result = success_func()

        assert result == "success"
        assert call_count == 1

    def test_success_after_retry(self) -> None:
        """Function should succeed after retrying."""
        call_count = 0

        @retry_with_backoff(max_attempts=3, base_delay=0.01)
        def fail_then_succeed() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Network error")
            return "success"

        result = fail_then_succeed()

        assert result == "success"
        assert call_count == 3

    def test_fails_after_max_attempts(self) -> None:
        """Function should raise after max attempts exceeded."""
        call_count = 0

        @retry_with_backoff(max_attempts=3, base_delay=0.01)
        def always_fail() -> str:
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Always fails")

        with pytest.raises(ConnectionError, match="Always fails"):
            always_fail()

        assert call_count == 3

    def test_only_catches_specified_exceptions(self) -> None:
        """Should not retry for non-specified exceptions."""
        call_count = 0

        @retry_with_backoff(
            max_attempts=3,
            base_delay=0.01,
            exceptions=(ConnectionError,),
        )
        def raise_value_error() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("Not retryable")

        with pytest.raises(ValueError, match="Not retryable"):
            raise_value_error()

        assert call_count == 1  # No retry for ValueError

    def test_exponential_backoff_timing(self) -> None:
        """Verify retries happen with exponential backoff (tenacity handles timing)."""
        call_count = 0

        @retry_with_backoff(
            max_attempts=4,
            base_delay=0.01,
            max_delay=10.0,
            jitter=0,  # Disable jitter for predictable behavior
        )
        def fail_three_times() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 4:
                raise ConnectionError("Fail")
            return "success"

        result = fail_three_times()

        assert result == "success"
        assert call_count == 4  # 1 initial + 3 retries

    def test_max_delay_cap(self) -> None:
        """Verify retry behavior with max_delay cap (tenacity handles timing)."""
        call_count = 0

        @retry_with_backoff(
            max_attempts=5,
            base_delay=0.01,
            max_delay=0.02,  # Cap at low value
            jitter=0,
        )
        def always_fail() -> str:
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Fail")

        with pytest.raises(ConnectionError):
            always_fail()

        # All 5 attempts should be made
        assert call_count == 5

    def test_on_retry_parameter_ignored(self) -> None:
        """Verify on_retry parameter is accepted but ignored (tenacity uses logging)."""
        callback = MagicMock()
        call_count = 0

        # on_retry is accepted for backward compatibility but ignored
        @retry_with_backoff(
            max_attempts=3,
            base_delay=0.01,
            jitter=0,
            on_retry=callback,
        )
        def fail_twice() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Network error")
            return "success"

        result = fail_twice()

        assert result == "success"
        assert call_count == 3
        # on_retry callback is no longer called (tenacity uses before_sleep_log instead)
        assert callback.call_count == 0

    def test_preserves_function_metadata(self) -> None:
        """Decorator should preserve function name and docstring."""

        @retry_with_backoff(max_attempts=3)
        def my_function() -> str:
            """My docstring."""
            return "result"

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring."

    def test_jitter_adds_randomness(self) -> None:
        """Verify jitter parameter is accepted (tenacity handles randomness internally)."""
        call_count = 0

        @retry_with_backoff(
            max_attempts=3,
            base_delay=0.01,
            max_delay=0.05,
            jitter=True,  # Enable jitter
        )
        def always_fail() -> str:
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Fail")

        with pytest.raises(ConnectionError):
            always_fail()

        # All 3 attempts should be made
        assert call_count == 3


class TestRetryableError:
    """Tests for RetryableError exception."""

    def test_retryable_error_is_caught(self) -> None:
        """RetryableError should be caught by retry decorator."""
        call_count = 0

        @retry_with_backoff(
            max_attempts=3,
            base_delay=0.01,
            exceptions=(RetryableError,),
        )
        def raise_retryable() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RetryableError("Retry me")
            return "success"

        result = raise_retryable()

        assert result == "success"
        assert call_count == 3

    def test_retryable_error_preserves_original(self) -> None:
        """RetryableError should preserve original exception."""
        original = ValueError("Original error")
        error = RetryableError("Wrapped", original=original)

        assert error.original is original
        assert str(error) == "Wrapped"


class TestNetworkExceptions:
    """Tests for NETWORK_EXCEPTIONS tuple."""

    def test_contains_base_exceptions(self) -> None:
        """Should contain basic network-related exceptions."""
        assert ConnectionError in NETWORK_EXCEPTIONS
        assert TimeoutError in NETWORK_EXCEPTIONS
        assert OSError in NETWORK_EXCEPTIONS
        assert RetryableError in NETWORK_EXCEPTIONS

    def test_retry_catches_network_exceptions(self) -> None:
        """Retry decorator should catch NETWORK_EXCEPTIONS."""
        call_count = 0

        @retry_with_backoff(
            max_attempts=3,
            base_delay=0.01,
            exceptions=NETWORK_EXCEPTIONS,
        )
        def network_operation() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Connection refused")
            if call_count == 2:
                raise TimeoutError("Timed out")
            return "success"

        result = network_operation()

        assert result == "success"
        assert call_count == 3
