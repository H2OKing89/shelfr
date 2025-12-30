"""Tests for circuit breaker module."""

from __future__ import annotations

import time

import pytest

from shelfr.utils.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    get_breaker_status,
    reset_all_breakers,
)


class TestCircuitBreaker:
    """Tests for CircuitBreaker class."""

    def test_initial_state_is_closed(self):
        """Test that breaker starts in closed state."""
        breaker = CircuitBreaker("test", failure_threshold=3)
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    def test_successful_calls_dont_open_circuit(self):
        """Test that successful calls don't affect circuit state."""
        breaker = CircuitBreaker("test", failure_threshold=3)

        @breaker
        def success():
            return "ok"

        for _ in range(10):
            assert success() == "ok"

        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    def test_failures_increment_count(self):
        """Test that failures are counted."""
        breaker = CircuitBreaker("test", failure_threshold=5, exceptions=(ValueError,))

        @breaker
        def fail():
            raise ValueError("test error")

        for _ in range(3):
            with pytest.raises(ValueError):
                fail()

        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 3

    def test_circuit_opens_after_threshold(self):
        """Test that circuit opens after failure threshold is reached."""
        breaker = CircuitBreaker("test", failure_threshold=3, exceptions=(ValueError,))

        @breaker
        def fail():
            raise ValueError("test error")

        # First 3 failures should open the circuit
        for _ in range(3):
            with pytest.raises(ValueError):
                fail()

        assert breaker.state == CircuitState.OPEN
        assert breaker.failure_count == 3

    def test_open_circuit_rejects_requests(self):
        """Test that open circuit rejects new requests."""
        breaker = CircuitBreaker(
            "test", failure_threshold=1, recovery_timeout=60, exceptions=(ValueError,)
        )

        @breaker
        def fail():
            raise ValueError("test error")

        # Open the circuit
        with pytest.raises(ValueError):
            fail()

        assert breaker.state == CircuitState.OPEN

        # Now calls should be rejected
        with pytest.raises(CircuitOpenError) as exc_info:
            fail()

        assert "test" in exc_info.value.service_name
        assert exc_info.value.retry_after > 0

    def test_circuit_enters_half_open_after_recovery_timeout(self):
        """Test that circuit transitions to half-open after recovery timeout."""
        breaker = CircuitBreaker(
            "test", failure_threshold=1, recovery_timeout=0.1, exceptions=(ValueError,)
        )

        @breaker
        def fail():
            raise ValueError("test error")

        # Open the circuit
        with pytest.raises(ValueError):
            fail()

        assert breaker.state == CircuitState.OPEN

        # Wait for recovery timeout
        time.sleep(0.15)

        # Next call should be allowed (half-open)
        with pytest.raises(ValueError):
            fail()

        # But since it failed, should go back to open
        assert breaker.state == CircuitState.OPEN

    def test_half_open_closes_after_success_threshold(self):
        """Test that circuit closes after success threshold in half-open state."""
        breaker = CircuitBreaker(
            "test",
            failure_threshold=1,
            recovery_timeout=0.1,
            success_threshold=2,
            exceptions=(ValueError,),
        )

        call_count = 0

        @breaker
        def maybe_fail():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("first call fails")
            return "success"

        # First call opens circuit
        with pytest.raises(ValueError):
            maybe_fail()

        assert breaker.state == CircuitState.OPEN

        # Wait for recovery timeout
        time.sleep(0.15)

        # These successes should close the circuit
        assert maybe_fail() == "success"
        assert breaker.state == CircuitState.HALF_OPEN

        assert maybe_fail() == "success"
        assert breaker.state == CircuitState.CLOSED

    def test_reset_clears_state(self):
        """Test that reset returns breaker to initial state."""
        breaker = CircuitBreaker("test", failure_threshold=1, exceptions=(ValueError,))

        @breaker
        def fail():
            raise ValueError("test error")

        with pytest.raises(ValueError):
            fail()

        assert breaker.state == CircuitState.OPEN

        breaker.reset()

        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    def test_context_manager_usage(self):
        """Test circuit breaker as context manager."""
        breaker = CircuitBreaker("test", failure_threshold=3, exceptions=(ValueError,))

        # Successful usage
        with breaker:
            result = "ok"
        assert result == "ok"

        # Failed usage
        with pytest.raises(ValueError), breaker:
            raise ValueError("test")

        assert breaker.failure_count == 1

    def test_non_matching_exceptions_not_counted(self):
        """Test that exceptions not in the list don't count as failures."""
        breaker = CircuitBreaker("test", failure_threshold=1, exceptions=(ValueError,))

        @breaker
        def fail_different():
            raise TypeError("different error")

        # This shouldn't count as a failure since it's TypeError not ValueError
        with pytest.raises(TypeError):
            fail_different()

        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0


class TestCircuitOpenError:
    """Tests for CircuitOpenError exception."""

    def test_error_contains_service_name(self):
        """Test that error message includes service name."""
        error = CircuitOpenError("test-service", 30.0)
        assert "test-service" in str(error)
        assert error.service_name == "test-service"

    def test_error_contains_retry_after(self):
        """Test that error includes retry information."""
        error = CircuitOpenError("test", 45.5)
        assert error.retry_after == 45.5
        assert "45.5" in str(error)


class TestGlobalBreakers:
    """Tests for global circuit breaker utilities."""

    def test_get_breaker_status_returns_all_breakers(self):
        """Test that status includes all pre-configured breakers."""
        status = get_breaker_status()

        assert "audnex-api" in status
        assert "qbittorrent" in status
        assert "docker" in status
        assert "audiobookshelf" in status

        # Check structure
        for info in status.values():
            assert "state" in info
            assert "failure_count" in info

    def test_reset_all_breakers(self):
        """Test that all breakers can be reset."""
        # This should not raise
        reset_all_breakers()

        # Verify all are closed
        status = get_breaker_status()
        for info in status.values():
            assert info["state"] == "closed"
            assert info["failure_count"] == 0


class TestThreadSafety:
    """Tests for thread safety of circuit breaker."""

    def test_concurrent_access(self):
        """Test that concurrent access doesn't cause issues."""
        import threading

        breaker = CircuitBreaker("test", failure_threshold=100, exceptions=(ValueError,))

        errors: list[Exception] = []

        def make_calls() -> None:
            for _ in range(50):
                try:
                    with breaker:
                        pass  # Success
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=make_calls) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert breaker.state == CircuitState.CLOSED
