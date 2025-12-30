"""Retry logic using tenacity library.

Provides exponential backoff with jitter for network operations.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from typing import TypeVar

from tenacity import (
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)
from tenacity import (
    retry as _retry,
)

T = TypeVar("T")

logger = logging.getLogger(__name__)


def retry_with_backoff(
    *,
    max_retries: int | None = None,
    max_attempts: int | None = None,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: float | bool = 1.0,
    retry_exceptions: tuple[type[BaseException], ...] | None = None,
    exceptions: tuple[type[Exception], ...] | None = None,
    logger_instance: logging.Logger | None = None,
    exponential_base: float = 2.0,  # Ignored, kept for backward compatibility
    on_retry: Callable[[Exception, int, float], None] | None = None,  # Ignored
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Retry decorator with exponential backoff and jitter.

    Supports both new (max_retries) and legacy (max_attempts) parameter names.

    Args:
        max_retries: Number of retries AFTER the first attempt (total = max_retries + 1)
        max_attempts: Legacy param - total attempts including first try
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        jitter: Random jitter (float value or bool for backward compatibility)
        retry_exceptions: Tuple of exception types to retry on
        exceptions: Legacy param name for retry_exceptions
        logger_instance: Logger for retry warnings (uses module logger if None)
        exponential_base: Legacy param - ignored (tenacity uses fixed exponential)
        on_retry: Legacy param - ignored (tenacity handles logging differently)

    Returns:
        Decorator function

    Example:
        # New API
        @retry_with_backoff(max_retries=3, base_delay=1.0)
        def fetch_data():
            return requests.get(url)

        # Legacy API (still works)
        @retry_with_backoff(max_attempts=3, base_delay=1.0, exceptions=(ConnectionError,))
        def legacy_fetch():
            return requests.get(url)
    """
    # Handle backward compatibility for max_retries/max_attempts
    if max_retries is not None and max_attempts is not None:
        raise ValueError("Cannot specify both max_retries and max_attempts")

    if max_attempts is not None:
        # Legacy: max_attempts includes first try, so retries = attempts - 1
        effective_retries = max_attempts - 1 if max_attempts > 0 else 0
    elif max_retries is not None:
        effective_retries = max_retries
    else:
        # Default: 3 retries (4 total attempts)
        effective_retries = 3

    # Handle backward compatibility for jitter (bool -> float)
    jitter_value = (1.0 if jitter else 0.0) if isinstance(jitter, bool) else float(jitter)

    # Handle backward compatibility for retry_exceptions/exceptions
    if retry_exceptions is not None and exceptions is not None:
        raise ValueError("Cannot specify both retry_exceptions and exceptions")

    effective_exceptions = retry_exceptions or exceptions or (Exception,)

    log = logger_instance or logger

    return _retry(
        reraise=True,
        stop=stop_after_attempt(effective_retries + 1),
        wait=wait_exponential_jitter(initial=base_delay, max=max_delay, jitter=jitter_value),
        retry=retry_if_exception_type(effective_exceptions),
        before_sleep=before_sleep_log(log, logging.WARNING),
    )


class RetryableError(Exception):
    """Exception that explicitly indicates the operation should be retried.

    Use this to wrap non-retryable exceptions when you want retry behavior.
    """

    def __init__(self, message: str, original: Exception | None = None) -> None:
        super().__init__(message)
        self.original = original


# Common exception groups for different operation types
_BASE_NETWORK_EXCEPTIONS: tuple[type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,  # Covers socket errors
    RetryableError,
)

# Import httpx exceptions if available
_HTTPX_EXCEPTIONS: tuple[type[Exception], ...]
try:
    import httpx

    _HTTPX_EXCEPTIONS = (
        httpx.TimeoutException,
        httpx.ConnectError,
        httpx.ReadError,
    )
except ImportError:
    _HTTPX_EXCEPTIONS = ()

NETWORK_EXCEPTIONS: tuple[type[Exception], ...] = (
    *_BASE_NETWORK_EXCEPTIONS,
    *_HTTPX_EXCEPTIONS,
)


# Subprocess exceptions for Docker/CLI tool retries
SUBPROCESS_EXCEPTIONS: tuple[type[Exception], ...] = (
    subprocess.TimeoutExpired,
    OSError,  # Covers "No such file or directory", resource exhaustion
    RetryableError,
)
