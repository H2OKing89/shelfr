"""
State management for tracking processed releases.

Uses a JSON file to persist state between runs.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from mamfast.config import get_settings
from mamfast.models import AudiobookRelease

logger = logging.getLogger(__name__)


def _get_state_file() -> Path:
    """Get the configured state file path."""
    settings = get_settings()
    return settings.paths.state_file


def load_state() -> dict[str, Any]:
    """
    Load state from the JSON file.

    Returns empty state if file doesn't exist.
    """
    state_file = _get_state_file()

    if not state_file.exists():
        return {
            "version": 1,
            "processed": {},
            "failed": {},
        }

    try:
        with open(state_file, encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
            return data
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON in state file: {e}")
        # Back up corrupted file
        backup = state_file.with_suffix(".json.bak")
        state_file.rename(backup)
        logger.info(f"Backed up corrupted state to {backup}")
        return {"version": 1, "processed": {}, "failed": {}}


def save_state(state: dict[str, Any]) -> None:
    """Save state to the JSON file."""
    state_file = _get_state_file()
    state_file.parent.mkdir(parents=True, exist_ok=True)

    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    logger.debug(f"Saved state to {state_file}")


def is_processed(identifier: str) -> bool:
    """
    Check if a release has been processed.

    Args:
        identifier: ASIN or path-based identifier
    """
    state = load_state()
    return identifier in state.get("processed", {})


def is_failed(identifier: str) -> bool:
    """Check if a release has previously failed."""
    state = load_state()
    return identifier in state.get("failed", {})


def mark_processed(release: AudiobookRelease) -> None:
    """
    Add a release to the processed state.

    Uses ASIN as primary identifier, falls back to path.
    """
    state = load_state()

    identifier = release.asin or str(release.source_dir)
    if not identifier:
        logger.warning("Cannot mark release processed: no identifier")
        return

    state["processed"][identifier] = {
        "asin": release.asin,
        "title": release.title,
        "author": release.author,
        "processed_at": datetime.now().isoformat(),
        "staging_dir": str(release.staging_dir) if release.staging_dir else None,
        "torrent_path": str(release.torrent_path) if release.torrent_path else None,
        "status": release.status.name,
    }

    # Remove from failed if it was there
    if identifier in state.get("failed", {}):
        del state["failed"][identifier]

    save_state(state)
    logger.info(f"Marked as processed: {release.display_name}")


def mark_failed(release: AudiobookRelease, error: str) -> None:
    """Add a release to the failed state with error info."""
    state = load_state()

    identifier = release.asin or str(release.source_dir)
    if not identifier:
        logger.warning("Cannot mark release failed: no identifier")
        return

    state["failed"][identifier] = {
        "asin": release.asin,
        "title": release.title,
        "author": release.author,
        "failed_at": datetime.now().isoformat(),
        "error": error,
        "source_dir": str(release.source_dir) if release.source_dir else None,
    }

    save_state(state)
    logger.warning(f"Marked as failed: {release.display_name} - {error}")


def get_processed_identifiers() -> set[str]:
    """Get all processed identifiers (ASINs and paths)."""
    state = load_state()
    return set(state.get("processed", {}).keys())


def get_failed_identifiers() -> set[str]:
    """Get all failed identifiers."""
    state = load_state()
    return set(state.get("failed", {}).keys())


def clear_failed(identifier: str) -> bool:
    """
    Remove a release from the failed state to allow retry.

    Returns True if it was removed, False if not found.
    """
    state = load_state()

    if identifier in state.get("failed", {}):
        del state["failed"][identifier]
        save_state(state)
        logger.info(f"Cleared failed state for: {identifier}")
        return True

    return False


def get_stats() -> dict[str, int]:
    """Get count statistics from state."""
    state = load_state()
    return {
        "processed": len(state.get("processed", {})),
        "failed": len(state.get("failed", {})),
    }
