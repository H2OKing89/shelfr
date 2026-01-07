"""
High-level orchestration functions for metadata operations.

This module provides the main entry points for fetching, aggregating,
and saving metadata. It ties together the provider system, aggregator,
and exporters into simple, easy-to-use functions.

Phase 5c: Initially a thin facade (wire-through) over existing functions.
Phase 8.5: Now wires AudnexProvider (with cache + rate limiting) into production.

Key functions:
- fetch_metadata_legacy(): Sync API with optional caching via AudnexProvider
- fetch_all_metadata_legacy(): Current with optional save
- save_metadata_files_legacy(): Save audnex.json and mediainfo.json

Future functions (after full provider migration):
- fetch_metadata_async(): Async, returns AggregatedResult (already implemented)
- export_metadata_async(): Export to multiple formats via exporters (already implemented)
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from shelfr.metadata.providers.registry import ProviderRegistry

# Import functions used by legacy orchestration
# These are at module level to enable proper mocking in tests
from shelfr.metadata.audnex import (
    fetch_audnex_book,
    fetch_audnex_chapters,
    save_audnex_json,
)
from shelfr.metadata.mediainfo import run_mediainfo, save_mediainfo_json

if TYPE_CHECKING:
    from shelfr.metadata.aggregator import AggregatedResult
    from shelfr.metadata.providers.types import LookupContext

logger = logging.getLogger(__name__)


# =============================================================================
# Provider-Based Audnex Fetching (Phase 8.5)
# =============================================================================
# Uses AudnexProvider with caching and rate limiting

# Timeout for provider operations in seconds
# This can be made configurable via settings in future if needed
PROVIDER_TIMEOUT_SECONDS = 60


def _fetch_audnex_with_provider(
    asin: str,
    region: str | None = None,  # Deprecated - region is now auto-detected
) -> tuple[dict[str, Any] | None, str | None]:
    """Fetch Audnex data using AudnexProvider (with caching).

    This is the cached path that wraps AudnexProvider.fetch() for sync use.
    Applies consistent timeouts to both async execution paths.

    Args:
        asin: Audible ASIN
        region: Deprecated - region is auto-detected via region racing/caching

    Returns:
        Tuple of (audnex_data, region), or (None, None) on failure
    """
    from shelfr.metadata.providers.audnex import AudnexProvider
    from shelfr.metadata.providers.types import LookupContext

    provider = AudnexProvider()
    ctx = LookupContext(ids={"asin": asin})

    async def run_provider() -> Any:
        """Run provider with lifecycle management."""
        await provider.startup()
        try:
            return await asyncio.wait_for(
                provider.fetch(ctx, "asin"),
                timeout=PROVIDER_TIMEOUT_SECONDS,
            )
        finally:
            await provider.shutdown()

    # Run async provider in event loop
    try:
        # Get or create event loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            # We're in an async context - create a new loop in a thread
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, run_provider())
                result = future.result(timeout=PROVIDER_TIMEOUT_SECONDS + 5)  # Extra margin
        else:
            # No running loop - safe to use asyncio.run
            result = asyncio.run(run_provider())

        if not result.success:
            logger.debug("AudnexProvider failed: %s", result.error)
            return None, None

        # Provider caches raw_data from fetch_audnex_book
        # Use cached raw_data if available; this is the whole point of caching
        raw_data = result.raw_data.get("audnex") if result.raw_data else None
        if raw_data is not None:
            # Get region from raw_data which now includes it
            actual_region = result.raw_data.get("region") or "us"
            return raw_data, actual_region

        # Fallback: provider succeeded but no raw data (shouldn't happen)
        logger.warning("Provider succeeded but no raw audnex data for %s", asin)
        return None, None

    except TimeoutError:
        logger.warning("Timeout fetching from AudnexProvider for %s", asin)
        return None, None
    except Exception as e:
        logger.warning("Error using AudnexProvider for %s: %s", asin, e)
        return None, None


# =============================================================================
# Legacy Orchestration (Phase 5c: thin facade, now with caching)
# =============================================================================
# These functions preserve the existing API while providing caching.


def fetch_metadata_legacy(
    asin: str | None = None,
    m4b_path: Path | None = None,
    *,
    use_cache: bool = True,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    """
    Fetch Audnex book metadata, chapters, and MediaInfo without saving.

    This is the legacy sync API with optional caching. When use_cache=True,
    uses AudnexProvider which provides caching and rate limiting.

    Args:
        asin: Audible ASIN (None to skip Audnex)
        m4b_path: Path to m4b file (None to skip MediaInfo)
        use_cache: If True, use AudnexProvider with caching (default: True)

    Returns:
        Tuple of (audnex_data, mediainfo_data, audnex_chapters), any may be None on error.
    """
    audnex_data = None
    mediainfo_data = None
    audnex_chapters = None

    if asin:
        if use_cache:
            # Use provider with caching + rate limiting
            audnex_data, _ = _fetch_audnex_with_provider(asin)
        else:
            # Direct fetch without caching (for --no-cache flag)
            audnex_data, _ = fetch_audnex_book(asin)

        # Also fetch chapter data from Audnex (authoritative source)
        # Note: Chapters are not cached separately (they're part of book data)
        audnex_chapters = fetch_audnex_chapters(asin)

    if m4b_path and m4b_path.exists():
        mediainfo_data = run_mediainfo(m4b_path)

    return audnex_data, mediainfo_data, audnex_chapters


def save_metadata_files_legacy(
    output_dir: Path,
    audnex_data: dict[str, Any] | None = None,
    mediainfo_data: dict[str, Any] | None = None,
) -> None:
    """
    Save metadata to JSON files in output directory.

    This is the legacy sync API. For the new exporter-based API,
    use export_metadata() instead (once migrated).

    Args:
        output_dir: Directory to save JSON files
        audnex_data: Audnex data to save (skipped if None)
        mediainfo_data: MediaInfo data to save (skipped if None)
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if audnex_data:
        save_audnex_json(audnex_data, output_dir / "audnex.json")

    if mediainfo_data:
        save_mediainfo_json(mediainfo_data, output_dir / "mediainfo.json")


def fetch_all_metadata_legacy(
    asin: str | None,
    m4b_path: Path | None,
    output_dir: Path | None = None,
    *,
    save_intermediate: bool = False,
    use_cache: bool = True,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    """
    Fetch Audnex book data, chapters, and MediaInfo, optionally saving intermediate files.

    This is the legacy sync API with optional caching.

    By default, this function only fetches metadata without saving files.
    Set save_intermediate=True to write audnex.json and mediainfo.json to output_dir.

    Args:
        asin: Audible ASIN (None to skip Audnex)
        m4b_path: Path to m4b file (None to skip MediaInfo)
        output_dir: Directory to save JSON files (only used if save_intermediate=True)
        save_intermediate: If True, save audnex.json and mediainfo.json files
        use_cache: If True, use AudnexProvider with caching (default: True)

    Returns:
        Tuple of (audnex_data, mediainfo_data, audnex_chapters), any may be None on error.
    """
    audnex_data, mediainfo_data, audnex_chapters = fetch_metadata_legacy(
        asin=asin, m4b_path=m4b_path, use_cache=use_cache
    )

    if save_intermediate and output_dir:
        save_metadata_files_legacy(
            output_dir, audnex_data=audnex_data, mediainfo_data=mediainfo_data
        )

    return audnex_data, mediainfo_data, audnex_chapters


# =============================================================================
# New Provider-Based Orchestration (Phase 5c+)
# =============================================================================
# These functions use the provider system and aggregator.
# They will eventually replace the legacy functions above.


async def fetch_metadata_async(
    ctx: LookupContext,
    *,
    providers: list[str] | None = None,
    stop_on_complete: bool = True,
    registry: ProviderRegistry | None = None,
) -> AggregatedResult:
    """
    Fetch metadata using the provider system.

    This is the new async API that uses pluggable providers and
    deterministic aggregation.

    Args:
        ctx: Lookup context with identifiers and paths
        providers: Optional list of provider names (all if None)
        stop_on_complete: Skip network calls if required fields filled
        registry: Optional provider registry (uses default if None).
                  Useful for testing with custom/mock providers.

    Returns:
        AggregatedResult with merged fields from all providers

    Example:
        ctx = LookupContext.from_asin(asin="B08G9PRS1K", path=book_path)
        result = await fetch_metadata_async(ctx)
        print(f"Title: {result.fields.get('title')}")
    """
    from shelfr.metadata.aggregator import MetadataAggregator
    from shelfr.metadata.providers.registry import (
        default_registry as _default_registry,
    )

    aggregator = MetadataAggregator(registry=registry or _default_registry)
    return await aggregator.fetch_all(
        ctx,
        providers=providers,
        stop_on_complete=stop_on_complete,
    )


async def export_metadata_async(
    result: AggregatedResult,
    output_dir: Path,
    *,
    formats: list[str] | None = None,
) -> dict[str, Path]:
    """
    Export aggregated metadata to various formats.

    Args:
        result: Aggregated metadata from fetch_metadata_async()
        output_dir: Directory to write output files
        formats: List of format names (default: ["json"])
                 Supported: "json" (ABS metadata.json)
                 Future: "opf", "nfo"

    Returns:
        Dict mapping format name to written file path

    Example:
        result = await fetch_metadata_async(ctx)
        files = await export_metadata_async(result, book_path, formats=["json"])
        print(f"Wrote: {files['json']}")
    """
    from shelfr.exceptions import ExportError
    from shelfr.metadata.exporters import get_exporter

    formats = formats or ["json"]
    written: dict[str, Path] = {}

    output_dir.mkdir(parents=True, exist_ok=True)

    for format_name in formats:
        try:
            exporter = get_exporter(format_name)
            file_path = await exporter.export(result, output_dir)
            written[format_name] = file_path
            logger.debug("Exported %s to %s", format_name, file_path)
        except ValueError as e:
            logger.warning("Unknown export format '%s': %s", format_name, e)
        except ExportError as e:
            logger.error("Failed to export %s: %s", format_name, e)

    return written
