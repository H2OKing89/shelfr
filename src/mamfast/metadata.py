"""
Metadata fetching from Audnex API and MediaInfo.

Audnex API: https://api.audnex.us
- GET /books/{asin} - Get book metadata by ASIN
- GET /authors/{asin} - Get author info

MediaInfo: Command-line tool for technical metadata
- mediainfo --Output=JSON <file>
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

import httpx

from mamfast.config import get_settings

logger = logging.getLogger(__name__)


# =============================================================================
# Audnex API
# =============================================================================


def fetch_audnex_book(asin: str) -> dict[str, Any] | None:
    """
    Fetch book metadata from Audnex API.

    Args:
        asin: Audible ASIN (e.g., "B000SEI1RG")

    Returns:
        Parsed JSON response or None if not found.
    """
    settings = get_settings()
    url = f"{settings.audnex.base_url}/books/{asin}"

    logger.debug(f"Fetching Audnex metadata: {url}")

    try:
        with httpx.Client(timeout=settings.audnex.timeout_seconds) as client:
            response = client.get(url)

            if response.status_code == 404:
                logger.warning(f"ASIN not found in Audnex: {asin}")
                return None

            response.raise_for_status()
            data: dict[str, Any] = response.json()

            logger.info(f"Fetched Audnex metadata for ASIN: {asin}")
            return data

    except httpx.TimeoutException:
        logger.error(f"Timeout fetching Audnex metadata for: {asin}")
        return None

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error from Audnex: {e}")
        return None

    except Exception as e:
        logger.exception(f"Error fetching Audnex metadata: {e}")
        return None


def fetch_audnex_author(asin: str) -> dict[str, Any] | None:
    """
    Fetch author metadata from Audnex API.

    Args:
        asin: Author ASIN

    Returns:
        Parsed JSON response or None if not found.
    """
    settings = get_settings()
    url = f"{settings.audnex.base_url}/authors/{asin}"

    logger.debug(f"Fetching Audnex author: {url}")

    try:
        with httpx.Client(timeout=settings.audnex.timeout_seconds) as client:
            response = client.get(url)

            if response.status_code == 404:
                logger.warning(f"Author ASIN not found: {asin}")
                return None

            response.raise_for_status()
            data: dict[str, Any] = response.json()
            return data

    except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
        logger.warning(f"Error fetching author metadata: {e}")
        return None


def save_audnex_json(data: dict[str, Any], output_path: Path) -> None:
    """Write Audnex metadata to JSON file."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.debug(f"Saved Audnex metadata to: {output_path}")


# =============================================================================
# MediaInfo
# =============================================================================


def run_mediainfo(file_path: Path) -> dict[str, Any] | None:
    """
    Run mediainfo on a file and return parsed JSON output.

    Args:
        file_path: Path to audio file (typically .m4b)

    Returns:
        Parsed MediaInfo JSON or None on error.
    """
    settings = get_settings()
    binary = settings.mediainfo.binary

    if not file_path.exists():
        logger.error(f"File not found for mediainfo: {file_path}")
        return None

    cmd = [
        binary,
        "--Output=JSON",
        str(file_path),
    ]

    logger.debug(f"Running mediainfo: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )

        data: dict[str, Any] = json.loads(result.stdout)
        logger.info(f"Got MediaInfo for: {file_path.name}")
        return data

    except FileNotFoundError:
        logger.error(f"mediainfo binary not found: {binary}")
        return None

    except subprocess.CalledProcessError as e:
        logger.error(f"mediainfo failed: {e.stderr}")
        return None

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON from mediainfo: {e}")
        return None


def save_mediainfo_json(data: dict[str, Any], output_path: Path) -> None:
    """Write MediaInfo data to JSON file."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.debug(f"Saved MediaInfo to: {output_path}")


# =============================================================================
# Combined Operations
# =============================================================================


def fetch_all_metadata(
    asin: str | None,
    m4b_path: Path | None,
    output_dir: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """
    Fetch both Audnex and MediaInfo metadata, saving to output directory.

    Args:
        asin: Audible ASIN (None to skip Audnex)
        m4b_path: Path to m4b file (None to skip MediaInfo)
        output_dir: Directory to save JSON files

    Returns:
        Tuple of (audnex_data, mediainfo_data), either may be None.
    """
    audnex_data = None
    mediainfo_data = None

    output_dir.mkdir(parents=True, exist_ok=True)

    # Audnex
    if asin:
        audnex_data = fetch_audnex_book(asin)
        if audnex_data:
            save_audnex_json(audnex_data, output_dir / "audnex.json")

    # MediaInfo
    if m4b_path and m4b_path.exists():
        mediainfo_data = run_mediainfo(m4b_path)
        if mediainfo_data:
            save_mediainfo_json(mediainfo_data, output_dir / "mediainfo.json")

    return audnex_data, mediainfo_data
