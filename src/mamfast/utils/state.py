"""
State management for tracking processed releases.

Uses a JSON file to persist state between runs with file locking
to prevent concurrent access issues.

State Structure:
    {
        "version": 1,
        "processed": {
            "<asin>": {
                "asin": str,
                "title": str,
                "author": str,
                "processed_at": ISO datetime,
                "staging_dir": str | None,
                "torrent_path": str | None,
                "infohash": str | None,  # NEW: for idempotent upload checks
                "status": str,
                "checkpoints": {  # NEW: per-stage timestamps
                    "staged_at": ISO datetime | None,
                    "metadata_at": ISO datetime | None,
                    "torrent_at": ISO datetime | None,
                    "uploaded_at": ISO datetime | None,
                }
            }
        },
        "failed": { ... }
    }
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from mamfast.config import get_settings
from mamfast.exceptions import StateLockError
from mamfast.models import AudiobookRelease

logger = logging.getLogger(__name__)


def _get_state_file() -> Path:
    """Get the configured state file path."""
    settings = get_settings()
    return settings.paths.state_file


def _get_run_lock_file() -> Path:
    """Get the run lock file path (next to state file)."""
    state_file = _get_state_file()
    return state_file.parent / "mamfast.lock"


@contextmanager
def run_lock(force: bool = False) -> Generator[None, None, None]:
    """
    Global run lock to prevent concurrent MAMFast instances.

    Prevents race conditions by ensuring only one instance runs at a time.
    Use force=True to bypass the lock (dangerous, only for debugging).

    Args:
        force: If True, skip acquiring the lock (dangerous!)

    Raises:
        RuntimeError: If another instance is already running

    Example:
        with run_lock():
            # Your pipeline code here
            pass
    """
    if force:
        logger.warning("Run lock bypassed with --no-run-lock (DANGEROUS!)")
        yield
        return

    lock_file = _get_run_lock_file()
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    # Open lock file and try to acquire exclusive lock
    with open(lock_file, "a+") as lockf:
        try:
            logger.debug(f"Acquiring run lock: {lock_file}")
            fcntl.flock(lockf.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            logger.debug("Run lock acquired")
            yield
        except BlockingIOError as e:
            raise StateLockError(
                f"Another MAMFast instance is already running.\n"
                f"Lock file: {lock_file}\n\n"
                f"If you're sure no other instance is running, delete the lock file:\n"
                f"  rm {lock_file}\n\n"
                f"Or use --no-run-lock to bypass (DANGEROUS - can cause data corruption)",
                lock_file=lock_file,
            ) from e
        finally:
            with contextlib.suppress(Exception):
                fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)


@contextmanager
def _locked_state_file(state_file: Path) -> Generator[None, None, None]:
    """
    Context manager for exclusive state file access.

    Uses a dedicated .lock file (not the state file itself) to avoid
    issues with atomic rename operations.

    This ensures read-modify-write operations are serialized across
    processes/threads.
    """
    state_file.parent.mkdir(parents=True, exist_ok=True)
    lock_path = state_file.with_suffix(state_file.suffix + ".lock")

    with open(lock_path, "a+") as lockf:
        fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)


def _load_state_unsafe(state_file: Path) -> dict[str, Any]:
    """
    Load state from JSON file without locking.

    Internal use only - use load_state() or update_state() instead.
    """
    if not state_file.exists():
        return {
            "version": 1,
            "processed": {},
            "failed": {},
        }

    try:
        with open(state_file, encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)

            # Validate state structure (warns but doesn't fail)
            try:
                from mamfast.schemas.state import validate_state

                validate_state(data)
                logger.debug("State file validated successfully")
            except Exception as validation_error:
                logger.warning(f"State file validation warning: {validation_error}")

            return data
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON in state file: {e}")
        # Back up corrupted file
        backup = state_file.with_suffix(".json.bak")
        state_file.rename(backup)
        logger.info(f"Backed up corrupted state to {backup}")
        return {"version": 1, "processed": {}, "failed": {}}


def _save_state_unsafe(state_file: Path, state: dict[str, Any]) -> None:
    """
    Save state atomically without locking.

    Internal use only - use update_state() instead.

    Uses temporary file + atomic rename to prevent corruption.
    """
    state_file.parent.mkdir(parents=True, exist_ok=True)

    # Write to temporary file first
    temp_file = state_file.with_suffix(".tmp")

    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False, sort_keys=True)

        # Atomic rename (POSIX guarantee)
        os.replace(temp_file, state_file)

        logger.debug(f"Saved state to {state_file}")
    except Exception as e:
        # Clean up temp file on error
        if temp_file.exists():
            temp_file.unlink()
        logger.error(f"Failed to save state: {e}")
        raise


def update_state(fn: Callable[[dict[str, Any]], None]) -> None:
    """
    Thread-safe state update with exclusive locking.

    This is the PRIMARY API for modifying state. It ensures atomicity
    by acquiring a lock, loading state, applying your mutation function,
    and saving back - all while holding the lock.

    Args:
        fn: Function that mutates the state dict in-place

    Example:
        def mark_as_done(state):
            state["processed"]["B0123ABC"] = {...}

        update_state(mark_as_done)
    """
    state_file = _get_state_file()

    with _locked_state_file(state_file):
        state = _load_state_unsafe(state_file)
        fn(state)
        _save_state_unsafe(state_file, state)


def load_state() -> dict[str, Any]:
    """
    Load state from the JSON file with locking.

    Returns empty state if file doesn't exist.
    Validates state structure with Pydantic schema.

    Note: For read-only access, this is safe. For modifications,
    use update_state() instead to ensure atomicity.
    """
    state_file = _get_state_file()

    with _locked_state_file(state_file):
        return _load_state_unsafe(state_file)


def save_state(state: dict[str, Any]) -> None:
    """
    Save state to the JSON file atomically with locking.

    DEPRECATED: Prefer update_state() for modifications to ensure
    proper read-modify-write atomicity.

    Uses a temporary file and atomic rename to prevent corruption
    if the process crashes during write.
    """
    state_file = _get_state_file()

    with _locked_state_file(state_file):
        _save_state_unsafe(state_file, state)


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


def mark_processed(release: AudiobookRelease, infohash: str | None = None) -> None:
    """
    Add a release to the processed state with full checkpoint data.

    Uses ASIN as primary identifier, falls back to path.

    Args:
        release: The release to mark as processed
        infohash: Optional torrent infohash for idempotent upload checks
    """
    identifier = release.asin or str(release.source_dir)
    if not identifier:
        logger.warning("Cannot mark release processed: no identifier")
        return

    def _mark(state: dict[str, Any]) -> None:
        state["processed"][identifier] = {
            "asin": release.asin,
            "title": release.title,
            "author": release.author,
            "processed_at": datetime.now().isoformat(),
            "staging_dir": str(release.staging_dir) if release.staging_dir else None,
            "torrent_path": str(release.torrent_path) if release.torrent_path else None,
            "infohash": infohash,
            "status": release.status.name,
            "checkpoints": {
                "staged_at": None,  # Can be populated by checkpoint_stage()
                "metadata_at": None,
                "torrent_at": None,
                "uploaded_at": datetime.now().isoformat(),
            },
        }

        # Remove from failed if it was there
        if identifier in state.get("failed", {}):
            del state["failed"][identifier]

    update_state(_mark)
    logger.info(f"Marked as processed: {release.display_name}")


def mark_failed(release: AudiobookRelease, error: str) -> None:
    """Add a release to the failed state with error info."""
    identifier = release.asin or str(release.source_dir)
    if not identifier:
        logger.warning("Cannot mark release failed: no identifier")
        return

    def _mark(state: dict[str, Any]) -> None:
        state["failed"][identifier] = {
            "asin": release.asin,
            "title": release.title,
            "author": release.author,
            "failed_at": datetime.now().isoformat(),
            "error": error,
            "source_dir": str(release.source_dir) if release.source_dir else None,
        }

    update_state(_mark)
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
    removed = False

    def _clear(state: dict[str, Any]) -> None:
        nonlocal removed
        if identifier in state.get("failed", {}):
            del state["failed"][identifier]
            removed = True
            logger.info(f"Cleared failed state for: {identifier}")

    update_state(_clear)
    return removed


def get_stats() -> dict[str, int]:
    """Get count statistics from state."""
    state = load_state()
    return {
        "processed": len(state.get("processed", {})),
        "failed": len(state.get("failed", {})),
    }


# ============================================================================
# Checkpoint API - For tracking per-stage progress and enabling resume
# ============================================================================


def checkpoint_stage(
    release: AudiobookRelease,
    stage: str,
    *,
    infohash: str | None = None,
) -> None:
    """
    Record completion of a pipeline stage for resume capability.

    This enables the workflow to skip already-completed stages on retry.

    Args:
        release: The release being processed
        stage: Stage name ("staged", "metadata", "torrent", "uploaded")
        infohash: Optional infohash (for torrent stage)

    Example:
        checkpoint_stage(release, "staged")
        checkpoint_stage(release, "torrent", infohash="abc123...")
    """
    identifier = release.asin or str(release.source_dir)
    if not identifier:
        logger.warning(f"Cannot checkpoint {stage}: no identifier")
        return

    def _checkpoint(state: dict[str, Any]) -> None:
        # Initialize processed entry if it doesn't exist
        if identifier not in state["processed"]:
            state["processed"][identifier] = {
                "asin": release.asin,
                "title": release.title,
                "author": release.author,
                "processed_at": None,
                "staging_dir": str(release.staging_dir) if release.staging_dir else None,
                "torrent_path": str(release.torrent_path) if release.torrent_path else None,
                "infohash": None,
                "status": release.status.name,
                "checkpoints": {},
            }

        entry = state["processed"][identifier]

        # Ensure checkpoints dict exists (for backward compat)
        if "checkpoints" not in entry:
            entry["checkpoints"] = {}

        # Update checkpoint timestamp
        checkpoint_field = f"{stage}_at"
        entry["checkpoints"][checkpoint_field] = datetime.now().isoformat()

        # Update infohash if provided
        if infohash:
            entry["infohash"] = infohash

        # Update status
        entry["status"] = release.status.name

        # Update paths if they changed
        if release.staging_dir:
            entry["staging_dir"] = str(release.staging_dir)
        if release.torrent_path:
            entry["torrent_path"] = str(release.torrent_path)

    update_state(_checkpoint)
    logger.debug(f"Checkpointed {stage} for {release.display_name}")


def get_checkpoint(identifier: str, stage: str) -> str | None:
    """
    Get the timestamp of a completed stage, or None if not completed.

    Args:
        identifier: ASIN or path-based identifier
        stage: Stage name ("staged", "metadata", "torrent", "uploaded")

    Returns:
        ISO datetime string if stage completed, None otherwise
    """
    state = load_state()
    entry = state.get("processed", {}).get(identifier)

    if not entry:
        return None

    checkpoints = entry.get("checkpoints", {})
    result: str | None = checkpoints.get(f"{stage}_at")
    return result


def get_infohash(identifier: str) -> str | None:
    """
    Get the stored infohash for a release, if any.

    Used for idempotent upload checks.

    Args:
        identifier: ASIN or path-based identifier

    Returns:
        Infohash string or None
    """
    state = load_state()
    entry = state.get("processed", {}).get(identifier)

    if not entry:
        return None

    result: str | None = entry.get("infohash")
    return result


def should_skip_stage(release: AudiobookRelease, stage: str) -> bool:
    """
    Check if a stage can be skipped because it was already completed.

    Enables resume functionality - if a previous run completed staging
    and metadata but failed at torrent creation, we can skip the first
    two stages on retry.

    Args:
        release: The release being processed
        stage: Stage to check ("staged", "metadata", "torrent", "uploaded")

    Returns:
        True if the stage was already completed and can be skipped
    """
    identifier = release.asin or str(release.source_dir)
    if not identifier:
        return False

    checkpoint_time = get_checkpoint(identifier, stage)

    if not checkpoint_time:
        return False

    # Also verify the artifacts still exist
    if stage == "staged" and release.staging_dir and not release.staging_dir.exists():
        logger.warning(f"Staged dir missing, will re-stage: {release.staging_dir}")
        return False

    if stage == "torrent" and release.torrent_path and not release.torrent_path.exists():
        logger.warning(f"Torrent file missing, will recreate: {release.torrent_path}")
        return False

    logger.info(f"Skipping {stage} stage (already completed at {checkpoint_time})")
    return True
