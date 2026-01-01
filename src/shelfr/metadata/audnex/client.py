"""
Audnex API client for audiobook metadata.

Audnex API: https://api.audnex.us
- GET /books/{asin} - Get book metadata by ASIN
- GET /books/{asin}/chapters - Get chapter data
- GET /authors/{asin} - Get author info

All functions support region fallback - they try configured regions in order
until one succeeds. Some ASINs are region-specific.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from shelfr.config import get_settings
from shelfr.utils.circuit_breaker import CircuitOpenError, audnex_breaker

logger = logging.getLogger(__name__)


# =============================================================================
# Book Metadata
# =============================================================================


def _fetch_audnex_book_region(
    asin: str,
    region: str,
    base_url: str,
    timeout: int,
) -> dict[str, Any] | None:
    """
    Fetch book metadata from Audnex API for a specific region.

    Internal helper - use fetch_audnex_book() which handles region fallback.

    Args:
        asin: Audible ASIN (e.g., "B000SEI1RG")
        region: Region code (us, uk, au, ca, de, es, fr, in, it, jp)
        base_url: Audnex API base URL
        timeout: Request timeout in seconds

    Returns:
        Parsed JSON response or None if not found/error.

    Raises:
        CircuitOpenError: If Audnex API circuit breaker is open.
    """
    url = f"{base_url}/books/{asin}"
    params = {"region": region}

    logger.debug(f"Fetching Audnex metadata: {url} (region={region})")

    try:
        # Circuit breaker protects against cascading failures
        # Only network-level errors trip the breaker (not 404s which are normal)
        with audnex_breaker, httpx.Client(timeout=timeout, http2=True) as client:
            response = client.get(url, params=params)

            if response.status_code == 404:
                logger.debug(f"ASIN {asin} not found in region {region}")
                return None

            # 500 errors are common for region mismatches - treat as "not found"
            if response.status_code == 500:
                logger.debug(f"ASIN {asin} returned 500 for region {region} (likely not available)")
                return None

            response.raise_for_status()
            data: dict[str, Any] = response.json()

            # Validate response structure (warns but doesn't fail)
            try:
                from shelfr.schemas.audnex import validate_audnex_book

                validate_audnex_book(data)
            except Exception as validation_error:
                logger.warning(
                    f"Audnex book response validation warning for {asin}: {validation_error}"
                )

            return data

    except CircuitOpenError:
        # Re-raise circuit breaker errors - caller should handle
        raise

    except httpx.TimeoutException:
        # Network issue - warn since this may indicate a problem
        logger.warning(f"Timeout fetching Audnex metadata for {asin} (region={region})")
        return None

    except httpx.HTTPStatusError as e:
        # Distinguish between "not found" type errors and actual issues
        if e.response.status_code in (401, 403, 429):
            logger.warning(
                "Auth/rate limit error fetching book %s (region=%s): %s",
                asin,
                region,
                e.response.status_code,
            )
        else:
            logger.debug(f"HTTP error from Audnex for {asin} (region={region}): {e}")
        return None

    except Exception as e:
        # Catch-all for JSON decode errors, connection issues, etc.
        logger.warning(
            f"Unexpected error fetching Audnex metadata for {asin} (region={region}): {e}"
        )
        return None


def fetch_audnex_book(
    asin: str, region: str | None = None
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Fetch book metadata from Audnex API with region fallback.

    Tries configured regions in order until one succeeds. Some ASINs are
    region-specific (e.g., B0BN2HMHZ8 only exists in US region).

    Args:
        asin: Audible ASIN (e.g., "B000SEI1RG")
        region: Optional specific region to try (skips fallback if provided)

    Returns:
        Tuple of (parsed JSON response or None, region found in or None).
        The region is useful for ASIN normalization to a preferred region.
    """
    settings = get_settings()

    # If specific region requested, only try that one
    if region:
        data = _fetch_audnex_book_region(
            asin, region, settings.audnex.base_url, settings.audnex.timeout_seconds
        )
        if data:
            logger.info(f"Fetched Audnex metadata for ASIN: {asin} (region={region})")
            return data, region
        logger.warning(f"ASIN {asin} not found in region {region}")
        return None, None

    # Try each configured region in order
    regions = settings.audnex.regions
    for r in regions:
        data = _fetch_audnex_book_region(
            asin, r, settings.audnex.base_url, settings.audnex.timeout_seconds
        )
        if data:
            logger.info(f"Fetched Audnex metadata for ASIN: {asin} (region={r})")
            return data, r

    logger.warning(f"ASIN {asin} not found in any configured region: {regions}")
    return None, None


# =============================================================================
# Author Metadata
# =============================================================================


def fetch_audnex_author(asin: str, region: str | None = None) -> dict[str, Any] | None:
    """
    Fetch author metadata from Audnex API with region fallback.

    Args:
        asin: Author ASIN
        region: Optional specific region to try (skips fallback if provided)

    Returns:
        Parsed JSON response or None if not found.
    """
    settings = get_settings()

    def _try_region(r: str) -> dict[str, Any] | None:
        url = f"{settings.audnex.base_url}/authors/{asin}"
        params = {"region": r}

        logger.debug(f"Fetching Audnex author: {url} (region={r})")

        try:
            with httpx.Client(timeout=settings.audnex.timeout_seconds, http2=True) as client:
                response = client.get(url, params=params)

                if response.status_code in (404, 500):
                    # Expected "not found" - keep at debug level
                    logger.debug(f"Author ASIN {asin} not found in region {r}")
                    return None

                response.raise_for_status()
                data: dict[str, Any] = response.json()
                return data

        except httpx.TimeoutException:
            # Network issue - warn since this may indicate a problem
            logger.warning(f"Timeout fetching author metadata for {asin} (region={r})")
            return None

        except httpx.HTTPStatusError as e:
            # Distinguish between "not found" type errors and actual issues
            if e.response.status_code in (401, 403, 429):
                logger.warning(
                    "Auth/rate limit error fetching author %s (region=%s): %s",
                    asin,
                    r,
                    e.response.status_code,
                )
            else:
                logger.debug(f"HTTP error fetching author {asin} (region={r}): {e}")
            return None

        except Exception as e:
            # Catch-all for JSON decode errors, connection issues, etc.
            logger.warning(
                f"Unexpected error fetching author metadata for {asin} (region={r}): {e}"
            )
            return None

    # If specific region requested, only try that one
    if region:
        data = _try_region(region)
        if data:
            logger.info(f"Fetched Audnex author: {asin} (region={region})")
        return data

    # Try each configured region in order
    for r in settings.audnex.regions:
        data = _try_region(r)
        if data:
            logger.info(f"Fetched Audnex author: {asin} (region={r})")
            return data

    logger.warning(f"Author ASIN {asin} not found in any configured region")
    return None


# =============================================================================
# Chapter Data
# =============================================================================


def _fetch_audnex_chapters_region(
    asin: str,
    region: str,
    base_url: str,
    timeout: int,
) -> dict[str, Any] | None:
    """
    Fetch chapter data from Audnex API for a specific region.

    Internal helper - use fetch_audnex_chapters() which handles region fallback.

    Args:
        asin: Audible ASIN
        region: Region code
        base_url: Audnex API base URL
        timeout: Request timeout in seconds

    Returns:
        Parsed JSON response or None if not found/error.
    """
    url = f"{base_url}/books/{asin}/chapters"
    params = {"region": region}

    logger.debug(f"Fetching Audnex chapters: {url} (region={region})")

    try:
        with httpx.Client(timeout=timeout, http2=True) as client:
            response = client.get(url, params=params)

            if response.status_code == 404:
                logger.debug(f"Chapters for {asin} not found in region {region}")
                return None

            # 500 errors are common for region mismatches
            if response.status_code == 500:
                logger.debug(f"Chapters for {asin} returned 500 for region {region}")
                return None

            response.raise_for_status()
            data: dict[str, Any] = response.json()

            # Validate response structure (warns but doesn't fail)
            try:
                from shelfr.schemas.audnex import validate_audnex_chapters

                validate_audnex_chapters(data)
            except Exception as validation_error:
                logger.warning(
                    f"Audnex chapters response validation warning for {asin}: {validation_error}"
                )

            return data

    except httpx.TimeoutException:
        # Network issue - warn since this may indicate a problem
        logger.warning(f"Timeout fetching Audnex chapters for {asin} (region={region})")
        return None

    except httpx.HTTPStatusError as e:
        # Distinguish between "not found" type errors and actual issues
        if e.response.status_code in (401, 403, 429):
            logger.warning(
                "Auth/rate limit error fetching chapters %s (region=%s): %s",
                asin,
                region,
                e.response.status_code,
            )
        else:
            logger.debug(f"HTTP error from Audnex chapters for {asin} (region={region}): {e}")
        return None

    except Exception as e:
        # Catch-all for JSON decode errors, connection issues, etc.
        logger.warning(
            f"Unexpected error fetching Audnex chapters for {asin} (region={region}): {e}"
        )
        return None


def fetch_audnex_chapters(asin: str, region: str | None = None) -> dict[str, Any] | None:
    """
    Fetch chapter data from Audnex API with region fallback.

    Args:
        asin: Audible ASIN (e.g., "B000SEI1RG")
        region: Optional specific region to try (skips fallback if provided)

    Returns:
        Parsed JSON response with chapters or None if not found.
        Response includes: asin, brandIntroDurationMs, brandOutroDurationMs,
        chapters (list with lengthMs, startOffsetMs, startOffsetSec, title),
        runtimeLengthMs, runtimeLengthSec
    """
    settings = get_settings()

    # If specific region requested, only try that one
    if region:
        data = _fetch_audnex_chapters_region(
            asin, region, settings.audnex.base_url, settings.audnex.timeout_seconds
        )
        if data:
            chapter_count = len(data.get("chapters", []))
            logger.info(
                f"Fetched {chapter_count} chapters from Audnex for ASIN: {asin} (region={region})"
            )
        return data

    # Try each configured region in order
    regions = settings.audnex.regions
    for r in regions:
        data = _fetch_audnex_chapters_region(
            asin, r, settings.audnex.base_url, settings.audnex.timeout_seconds
        )
        if data:
            chapter_count = len(data.get("chapters", []))
            logger.info(
                f"Fetched {chapter_count} chapters from Audnex for ASIN: {asin} (region={r})"
            )
            return data

    logger.warning(f"Chapters for ASIN {asin} not found in any configured region")
    return None


# =============================================================================
# File Operations
# =============================================================================


def save_audnex_json(data: dict[str, Any], output_path: Path) -> None:
    """Write Audnex metadata to JSON file."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.debug(f"Saved Audnex metadata to: {output_path}")
