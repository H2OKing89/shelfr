"""Circuit breaker pattern implementation for external services.

Prevents cascading failures by temporarily disabling calls to failing services.
The circuit breaker has three states:
- CLOSED: Normal operation, requests pass through
- OPEN: Service is failing, requests are immediately rejected
- HALF_OPEN: Testing if service recovered, limited requests allowed

Usage:
    breaker = CircuitBreaker("audnex-api", failure_threshold=5, recovery_timeout=60)

    @breaker
    def fetch_from_audnex():
        return httpx.get("https://api.audnex.us/...")

    # Or manually:
    with breaker:
        result = make_external_call()
"""

from __future__ import annotations

import functools
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitOpenError(Exception):
    """Raised when circuit is open and request is rejected."""

    def __init__(self, service_name: str, retry_after: float) -> None:
        self.service_name = service_name
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker for '{service_name}' is OPEN. "
            f"Retry after {retry_after:.1f} seconds."
        )


@dataclass
class CircuitBreaker:
    """
    Thread-safe circuit breaker for protecting external service calls.

    Args:
        service_name: Human-readable name for logging
        failure_threshold: Number of failures before opening circuit
        recovery_timeout: Seconds to wait before trying again (half-open state)
        success_threshold: Successes needed in half-open to close circuit
        exceptions: Exception types to count as failures

    Example:
        breaker = CircuitBreaker("qbittorrent", failure_threshold=3, recovery_timeout=30)

        @breaker
        def upload_torrent():
            return qbt.torrents_add(...)
    """

    service_name: str
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    success_threshold: int = 2
    exceptions: tuple[type[Exception], ...] = (Exception,)

    # Internal state (not constructor args)
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _success_count: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state

    @property
    def failure_count(self) -> int:
        """Get current failure count."""
        return self._failure_count

    def _time_since_failure(self) -> float:
        """Seconds since last failure."""
        if self._last_failure_time == 0:
            return float("inf")
        return time.monotonic() - self._last_failure_time

    def _should_attempt(self) -> bool:
        """Check if a request should be attempted."""
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True

            if self._state == CircuitState.OPEN:
                # Check if recovery timeout has passed
                if self._time_since_failure() >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0
                    logger.info(f"Circuit breaker '{self.service_name}' entering HALF_OPEN state")
                    return True
                return False

            # HALF_OPEN: allow the attempt
            return True

    def _record_success(self) -> None:
        """Record a successful call."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    logger.info(
                        f"Circuit breaker '{self.service_name}' CLOSED "
                        f"(service recovered after {self._success_count} successes)"
                    )
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failure_count = 0

    def _record_failure(self, exc: Exception) -> None:
        """Record a failed call."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open goes back to open
                self._state = CircuitState.OPEN
                logger.warning(
                    f"Circuit breaker '{self.service_name}' OPEN "
                    f"(failed during recovery: {exc})"
                )
            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    self._state = CircuitState.OPEN
                    logger.warning(
                        f"Circuit breaker '{self.service_name}' OPEN "
                        f"after {self._failure_count} failures: {exc}"
                    )

    def reset(self) -> None:
        """Manually reset the circuit breaker to closed state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = 0.0
            logger.info(f"Circuit breaker '{self.service_name}' manually reset to CLOSED")

    def __enter__(self) -> CircuitBreaker:
        """Context manager entry - check if request is allowed."""
        if not self._should_attempt():
            retry_after = self.recovery_timeout - self._time_since_failure()
            raise CircuitOpenError(self.service_name, max(0, retry_after))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> Literal[False]:
        """Context manager exit - record result."""
        if exc_val is None:
            self._record_success()
        elif isinstance(exc_val, self.exceptions):
            self._record_failure(exc_val)
        # Don't suppress exceptions
        return False

    def __call__(self, func: Callable[..., T]) -> Callable[..., T]:
        """Decorator usage."""

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            with self:
                return func(*args, **kwargs)

        return wrapper


# Pre-configured circuit breakers for common services
# These can be imported and used directly or as templates


def _get_httpx_exceptions() -> tuple[type[Exception], ...]:
    """Get httpx exception types if available."""
    try:
        import httpx

        return (
            httpx.TimeoutException,
            httpx.ConnectError,
            httpx.ReadError,
        )
    except ImportError:
        return ()


_HTTPX_EXCEPTIONS: tuple[type[Exception], ...] = _get_httpx_exceptions()

audnex_breaker = CircuitBreaker(
    service_name="audnex-api",
    failure_threshold=5,
    recovery_timeout=60.0,  # 1 minute
    exceptions=(ConnectionError, TimeoutError, OSError) + _HTTPX_EXCEPTIONS,
)

qbittorrent_breaker = CircuitBreaker(
    service_name="qbittorrent",
    failure_threshold=3,
    recovery_timeout=30.0,  # 30 seconds
    exceptions=(ConnectionError, TimeoutError, OSError),
)

docker_breaker = CircuitBreaker(
    service_name="docker",
    failure_threshold=3,
    recovery_timeout=30.0,
    exceptions=(OSError, TimeoutError),
)

audiobookshelf_breaker = CircuitBreaker(
    service_name="audiobookshelf",
    failure_threshold=5,
    recovery_timeout=60.0,
    exceptions=(ConnectionError, TimeoutError, OSError) + _HTTPX_EXCEPTIONS,
)

hardcover_breaker = CircuitBreaker(
    service_name="hardcover-api",
    failure_threshold=5,
    recovery_timeout=60.0,
    exceptions=(ConnectionError, TimeoutError, OSError) + _HTTPX_EXCEPTIONS,
)


def get_breaker_status() -> dict[str, dict[str, Any]]:
    """Get status of all pre-configured circuit breakers."""
    breakers = {
        "audnex-api": audnex_breaker,
        "qbittorrent": qbittorrent_breaker,
        "docker": docker_breaker,
        "audiobookshelf": audiobookshelf_breaker,
        "hardcover-api": hardcover_breaker,
    }

    result: dict[str, dict[str, Any]] = {}
    for name, breaker in breakers.items():
        result[name] = {
            "state": breaker.state.value,
            "failure_count": breaker.failure_count,
        }
    return result


def reset_all_breakers() -> None:
    """Reset all circuit breakers to closed state."""
    for breaker in [
        audnex_breaker,
        qbittorrent_breaker,
        docker_breaker,
        audiobookshelf_breaker,
        hardcover_breaker,
    ]:
        breaker.reset()
