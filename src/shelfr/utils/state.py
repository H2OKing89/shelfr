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
import shutil
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from shelfr.config import get_settings
from shelfr.exceptions import StateCorruptionError, StateLockError
from shelfr.models import AudiobookRelease, ReleaseStatus

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
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
    except PermissionError as e:
        raise StateLockError(
            f"Cannot create state directory: {state_file.parent}\n"
            "Check permissions or configure a valid state file path.",
            lock_file=state_file,
        ) from e
    lock_path = state_file.with_suffix(state_file.suffix + ".lock")

    with open(lock_path, "a+") as lockf:
        fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)


# ============================================================================
# Schema Migration
# ============================================================================

CURRENT_SCHEMA_VERSION = 2  # Bump when schema changes


def _migrate_state(data: dict[str, Any]) -> dict[str, Any]:
    """
    Migrate state data to current schema version.

    Applies incremental migrations from the data's version to CURRENT_SCHEMA_VERSION.
    Each migration function handles one version bump.

    Args:
        data: State data (may be older version)

    Returns:
        Migrated state data at CURRENT_SCHEMA_VERSION
    """
    version = data.get("version", 1)

    if version >= CURRENT_SCHEMA_VERSION:
        return data

    logger.info(f"Migrating state from v{version} to v{CURRENT_SCHEMA_VERSION}")

    # Apply migrations sequentially
    if version < 2:
        data = _migrate_v1_to_v2(data)

    # Future migrations:
    # - Introduce a new migration function (e.g., _migrate_v2_to_v3).
    # - Add another conditional here (e.g., "if version < 3:") that calls
    #   the new migration function.

    # Set final version after all migrations complete
    data["version"] = CURRENT_SCHEMA_VERSION
    return data


def _migrate_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """
    Migrate from v1 to v2 schema.

    Changes:
    - Add checkpoints dict to processed entries if missing
    - Add infohash field to processed entries if missing
    - Add first_failed_at to failed entries (copy from failed_at)
    - Add error_type to failed entries
    """
    # Migrate processed entries
    for _identifier, entry in data.get("processed", {}).items():
        if "checkpoints" not in entry:
            entry["checkpoints"] = {}
        if "infohash" not in entry:
            entry["infohash"] = None

    # Migrate failed entries
    for _identifier, entry in data.get("failed", {}).items():
        if "first_failed_at" not in entry:
            entry["first_failed_at"] = entry.get("failed_at")
        if "error_type" not in entry:
            entry["error_type"] = None
        if "author" not in entry:
            entry["author"] = None

    logger.debug("Completed v1 -> v2 migration")
    return data


def _parse_json_file(file_path: Path) -> dict[str, Any]:
    """Parse JSON file, raising JSONDecodeError on failure."""
    with open(file_path, encoding="utf-8") as f:
        result: dict[str, Any] = json.load(f)
        return result


def _load_state_unsafe(state_file: Path) -> dict[str, Any]:
    """
    Load state from JSON file without locking.

    Internal use only - use load_state() or update_state() instead.

    Recovery strategy:
    1. Try main state file
    2. If corrupt, try .bak backup
    3. If both fail, raise StateCorruptionError with recovery instructions
    4. Migrate data to current schema version
    """
    backup_file = state_file.with_suffix(".json.bak")
    empty_state: dict[str, Any] = {
        "version": CURRENT_SCHEMA_VERSION,
        "processed": {},
        "failed": {},
    }

    if not state_file.exists():
        # No state file yet - check if backup exists (unusual but possible)
        if backup_file.exists():
            try:
                data = _parse_json_file(backup_file)
                data = _migrate_state(data)  # Migrate if needed
                logger.warning(f"Main state missing, recovered from backup: {backup_file}")
                return data
            except json.JSONDecodeError:
                logger.warning(f"Orphaned corrupt backup found: {backup_file}")
        return empty_state

    # Try main file
    main_error: Exception | None = None
    try:
        data = _parse_json_file(state_file)

        # Migrate to current schema version
        data = _migrate_state(data)

        # Validate state structure (warns but doesn't fail)
        try:
            from shelfr.schemas.state import validate_state

            validate_state(data)
            logger.debug("State file validated successfully")
        except Exception as validation_error:
            logger.warning(f"State file validation warning: {validation_error}")

        return data

    except json.JSONDecodeError as e:
        main_error = e
        logger.warning(f"Corrupt JSON in main state file: {e}")

    # Main file corrupt - try backup
    if backup_file.exists():
        try:
            data = _parse_json_file(backup_file)
            data = _migrate_state(data)  # Migrate backup data to current schema
            logger.warning(
                "Main state corrupt, recovered from backup and migrated: %s",
                backup_file,
            )
            # Persist migrated state to main file (atomic write)
            _save_state_unsafe(state_file, data)
            return data
        except json.JSONDecodeError as backup_error:
            # Both files corrupt - this is serious
            raise StateCorruptionError(
                f"State file corrupt and backup also corrupt.\n\n"
                f"Main file: {state_file}\n"
                f"  Error: {main_error}\n\n"
                f"Backup file: {backup_file}\n"
                f"  Error: {backup_error}\n\n"
                f"Recovery options:\n"
                f"1. Restore from external backup if available\n"
                f"2. Delete both files to start fresh:\n"
                f"   rm '{state_file}' '{backup_file}'\n\n"
                f"WARNING: Starting fresh will lose all processed/failed state!"
            ) from backup_error

    # Main corrupt, no backup exists
    raise StateCorruptionError(
        f"State file corrupt and no backup found.\n\n"
        f"File: {state_file}\n"
        f"Error: {main_error}\n\n"
        f"Recovery options:\n"
        f"1. Restore from external backup if available\n"
        f"2. Delete the file to start fresh:\n"
        f"   rm '{state_file}'\n\n"
        f"WARNING: Starting fresh will lose all processed/failed state!"
    )


def _save_state_unsafe(state_file: Path, state: dict[str, Any]) -> None:
    """
    Save state atomically without locking.

    Internal use only - use update_state() instead.

    Safety guarantees:
    1. Preserves last-known-good as .bak before any write
    2. Writes to .tmp file first
    3. fsync() ensures data is on disk (not just in kernel buffer)
    4. Atomic os.replace() swaps in the new file
    5. Interrupted write never leaves partial JSON
    """
    state_file.parent.mkdir(parents=True, exist_ok=True)

    backup_file = state_file.with_suffix(".json.bak")
    temp_file = state_file.with_suffix(".tmp")

    try:
        # Step 1: Preserve last-known-good as backup
        if state_file.exists():
            shutil.copy2(state_file, backup_file)
            logger.debug(f"Preserved backup: {backup_file}")

        # Step 2: Write to temporary file with fsync
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())  # Force data to disk

        # Step 3: Atomic rename (POSIX guarantee)
        os.replace(temp_file, state_file)

        logger.debug(f"Saved state to {state_file}")

    except Exception as e:
        # Clean up temp file on error
        if temp_file.exists():
            with contextlib.suppress(OSError):
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
    identifier = release.asin or (str(release.source_dir) if release.source_dir else None)
    if not identifier:
        logger.warning("Cannot mark release processed: no identifier (missing ASIN and source_dir)")
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


def mark_failed(
    release: AudiobookRelease,
    error: str,
    *,
    error_type: str | None = None,
) -> None:
    """
    Add a release to the failed state with error info.

    Tracks retry count and timestamps for debugging/auditing.
    If called multiple times for the same release, increments retry_count
    and preserves first_failed_at while updating failed_at.

    Args:
        release: The release that failed
        error: Human-readable error message
        error_type: Optional exception class name (e.g., "NetworkError")
    """
    identifier = release.asin or (str(release.source_dir) if release.source_dir else None)
    if not identifier:
        logger.warning("Cannot mark release failed: no identifier (missing ASIN and source_dir)")
        return

    now = datetime.now().isoformat()

    def _mark(state: dict[str, Any]) -> None:
        existing = state.get("failed", {}).get(identifier, {})

        state["failed"][identifier] = {
            "asin": release.asin,
            "title": release.title,
            "author": release.author,
            "failed_at": now,
            "first_failed_at": existing.get("first_failed_at", now),
            "error": error,
            "error_type": error_type,
            "source_dir": str(release.source_dir) if release.source_dir else None,
            "retry_count": existing.get("retry_count", 0) + 1,
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
# Stale Entry Detection - Find entries with missing required paths
# ============================================================================

# Path requirements vary by status - after completion, paths may legitimately disappear
REQUIRED_PATHS_BY_STATUS: dict[str, list[str]] = {
    "DISCOVERED": [],  # No paths required yet
    "STAGED": ["staging_dir"],
    "METADATA_FETCHED": ["staging_dir"],
    "TORRENT_CREATED": ["staging_dir", "torrent_path"],
    "UPLOADED": ["torrent_path"],  # staging_dir may be gone after upload
    "COMPLETE": [],  # All paths may be gone after completion
    "FAILED": [],  # Failed entries don't require path validation
}


def find_stale_entries() -> list[tuple[str, str, str, str]]:
    """
    Find entries with missing required paths (status-aware).

    Only flags entries where paths that should exist for that status
    are actually missing. For example, a COMPLETE entry with missing
    staging_dir is NOT stale, but a STAGED entry with missing
    staging_dir IS stale.

    Returns:
        List of (identifier, title, status, missing_path) tuples

    Example:
        stale = find_stale_entries()
        for identifier, title, status, missing in stale:
            print(f"{identifier}: {title} ({status}) missing {missing}")
    """
    stale: list[tuple[str, str, str, str]] = []
    state = load_state()

    for identifier, entry in state.get("processed", {}).items():
        status = entry.get("status", "COMPLETE")
        title = entry.get("title", "Unknown")
        required = REQUIRED_PATHS_BY_STATUS.get(status, [])

        for path_key in required:
            path_str = entry.get(path_key)
            if path_str and not Path(path_str).exists():
                stale.append((identifier, title, status, path_key))

    return stale


def prune_stale_entries(*, dry_run: bool = False) -> list[tuple[str, str]]:
    """
    Remove stale entries from processed state.

    Args:
        dry_run: If True, only report what would be removed

    Returns:
        List of (identifier, title) tuples that were (or would be) removed
    """
    stale = find_stale_entries()
    if not stale:
        return []

    # Deduplicate by identifier (entry might have multiple missing paths)
    to_remove: dict[str, str] = {}
    for identifier, title, _status, _missing_path in stale:
        if identifier not in to_remove:
            to_remove[identifier] = title

    if dry_run:
        return list(to_remove.items())

    def _prune(state: dict[str, Any]) -> None:
        for identifier in to_remove:
            if identifier in state.get("processed", {}):
                del state["processed"][identifier]
                logger.info(f"Pruned stale entry: {identifier}")

    update_state(_prune)
    return list(to_remove.items())


# ============================================================================
# Status Transition Validation
# ============================================================================

# Define allowed status transitions (state machine)
# Each status can transition to itself (idempotent) or forward
ALLOWED_TRANSITIONS: dict[ReleaseStatus, set[ReleaseStatus]] = {
    ReleaseStatus.DISCOVERED: {ReleaseStatus.DISCOVERED, ReleaseStatus.STAGED},
    ReleaseStatus.STAGED: {ReleaseStatus.STAGED, ReleaseStatus.METADATA_FETCHED},
    ReleaseStatus.METADATA_FETCHED: {
        ReleaseStatus.METADATA_FETCHED,
        ReleaseStatus.TORRENT_CREATED,
    },
    ReleaseStatus.TORRENT_CREATED: {
        ReleaseStatus.TORRENT_CREATED,
        ReleaseStatus.UPLOADED,
        ReleaseStatus.COMPLETE,  # Can skip UPLOADED in some workflows
    },
    ReleaseStatus.UPLOADED: {ReleaseStatus.UPLOADED, ReleaseStatus.COMPLETE},
    ReleaseStatus.COMPLETE: {ReleaseStatus.COMPLETE},
    ReleaseStatus.FAILED: {ReleaseStatus.FAILED, ReleaseStatus.DISCOVERED},  # Can retry from start
}


class InvalidStatusTransitionError(Exception):
    """Raised when an invalid status transition is attempted."""

    def __init__(
        self,
        current: ReleaseStatus,
        new: ReleaseStatus,
        identifier: str | None = None,
    ) -> None:
        allowed = ALLOWED_TRANSITIONS.get(current, set())
        allowed_names = ", ".join(s.name for s in allowed) if allowed else "none"
        msg = (
            f"Invalid status transition: {current.name} → {new.name}\n"
            f"Allowed transitions from {current.name}: {allowed_names}"
        )
        if identifier:
            msg = f"[{identifier}] {msg}"
        super().__init__(msg)
        self.current = current
        self.new = new
        self.identifier = identifier


def validate_status_transition(
    current: ReleaseStatus | str | None,
    new: ReleaseStatus | str,
    *,
    identifier: str | None = None,
    strict: bool = False,
) -> bool:
    """
    Validate that a status transition is allowed.

    Args:
        current: Current status (None means new entry)
        new: Target status
        identifier: Optional identifier for error messages
        strict: If True, raise InvalidStatusTransitionError; otherwise log warning

    Returns:
        True if valid, False if invalid (when strict=False)

    Raises:
        InvalidStatusTransitionError: If strict=True and transition is invalid
    """
    # Convert strings to enum if needed
    if isinstance(new, str):
        try:
            new = ReleaseStatus[new]
        except KeyError:
            logger.warning(f"Unknown status: {new}")
            return True  # Don't block unknown statuses

    if current is None:
        # New entry - allow any status (but DISCOVERED is expected)
        if new != ReleaseStatus.DISCOVERED:
            logger.debug(f"New entry starting at non-DISCOVERED status: {new.name}")
        return True

    if isinstance(current, str):
        try:
            current = ReleaseStatus[current]
        except KeyError:
            logger.warning(f"Unknown current status: {current}")
            return True  # Don't block unknown statuses

    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if new in allowed:
        return True

    # Invalid transition
    if strict:
        raise InvalidStatusTransitionError(current, new, identifier)

    logger.warning(
        f"Invalid status transition: {current.name} → {new.name} "
        f"(allowed: {', '.join(s.name for s in allowed)})"
    )
    return False


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
    identifier = release.asin or (str(release.source_dir) if release.source_dir else None)
    if not identifier:
        logger.warning(f"Cannot checkpoint {stage}: no identifier (missing ASIN and source_dir)")
        return

    def _checkpoint(state: dict[str, Any]) -> None:
        # Initialize processed entry if it doesn't exist
        if identifier not in state["processed"]:
            state["processed"][identifier] = {
                "asin": release.asin,
                "title": release.title,
                "author": release.author,
                "processed_at": datetime.now().isoformat(),
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
    identifier = release.asin or (str(release.source_dir) if release.source_dir else None)
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
