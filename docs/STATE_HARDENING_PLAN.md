# State Management Hardening Plan

**Status**: Implemented
**Priority**: High (prevents data loss and silent corruption)
**Branch**: `feat/state-hardening`

---

## Executive Summary

This plan upgrades `processed.json` state management for production reliability:
- Atomic writes with `fsync()` to survive crashes
- Backup rotation for recovery
- Full test coverage for checkpoint/resume logic
- `mamfast state` CLI for operator tooling
- Status transition validation (state machine)

---

## Step 0: Harden File Operations (Atomic Write + Corruption Recovery)

### Current State

- ✅ Uses temp file + `os.replace()` (atomic on POSIX)
- ✅ Backs up corrupted JSON to `.bak`
- ⚠️ **Missing `fsync()`** - data in kernel buffer not flushed to disk
- ⚠️ **No `.bak` fallback on load** - if main file corrupt, doesn't try backup first
- ⚠️ **Backup only on corruption** - no last-known-good preservation

### Changes Required

#### `_save_state_unsafe()` improvements:

```python
# Before write: preserve last-known-good
if state_file.exists():
    backup = state_file.with_suffix(".json.bak")
    shutil.copy2(state_file, backup)

# Write atomically with fsync
with open(temp_file, "w", encoding="utf-8") as f:
    json.dump(state, f, indent=2, ensure_ascii=False, sort_keys=True)
    f.flush()
    os.fsync(f.fileno())  # Force to disk

# Atomic rename
os.replace(temp_file, state_file)
```

#### `_load_state_unsafe()` improvements:
```python
# Try main file first
if state_file.exists():
    try:
        return _parse_json(state_file)
    except json.JSONDecodeError:
        logger.warning(f"Corrupt JSON: {state_file}")

# Try backup
backup = state_file.with_suffix(".json.bak")
if backup.exists():
    try:
        data = _parse_json(backup)
        logger.warning(f"Recovered from backup: {backup}")
        # Restore from backup
        shutil.copy2(backup, state_file)
        return data
    except json.JSONDecodeError:
        logger.error(f"Backup also corrupt: {backup}")

# Both failed - raise loud error
raise StateCorruptionError(
    f"State file corrupt and no valid backup found.\n"
    f"Main: {state_file}\n"
    f"Backup: {backup}\n\n"
    f"Recovery options:\n"
    f"1. Restore from external backup\n"
    f"2. Delete both files to start fresh: rm {state_file} {backup}"
)
```

### Acceptance Criteria
- [ ] Interrupted write never leaves partial JSON
- [ ] Corrupt JSON produces helpful error with recovery steps
- [ ] `.bak` is preserved before each write
- [ ] Load tries `.bak` if main is corrupt

---

## Step 1: Add Tests for Checkpoint/Resume Logic

### Current State
- Zero test coverage for:
  - `checkpoint_stage()`
  - `get_checkpoint()`
  - `get_infohash()`
  - `should_skip_stage()`

### Tests to Add (in `test_state.py`)

```python
class TestCheckpointStage:
    def test_creates_checkpoint_structure(self)
    def test_updates_existing_entry(self)
    def test_handles_missing_identifier(self)
    def test_stores_infohash_when_provided(self)
    def test_updates_status(self)
    def test_updates_paths(self)

class TestGetCheckpoint:
    def test_returns_none_when_missing_entry(self)
    def test_returns_none_when_missing_stage(self)
    def test_returns_datetime_when_present(self)
    def test_handles_legacy_entry_without_checkpoints(self)

class TestGetInfohash:
    def test_returns_none_when_missing_entry(self)
    def test_returns_none_when_missing_infohash(self)
    def test_returns_infohash_when_present(self)

class TestShouldSkipStage:
    def test_returns_false_no_identifier(self)
    def test_returns_false_no_checkpoint(self)
    def test_returns_true_when_checkpoint_exists(self)
    def test_returns_false_when_staging_dir_missing(self)
    def test_returns_false_when_torrent_path_missing(self)

class TestLegacyEntries:
    def test_entry_missing_checkpoints_key(self)
    def test_entry_missing_torrent_path(self)
    def test_entry_missing_staging_dir(self)
    def test_entry_missing_infohash(self)
```

### Acceptance Criteria
- [ ] All checkpoint functions have test coverage
- [ ] Legacy entries (missing fields) don't crash anything

---

## Step 2: Fix or Remove `retry_count`

### Current State
- `retry_count: int = 0` exists in `FailedRelease` schema
- **Never incremented anywhere** - dead code

### Decision: **Implement Properly with Metadata**

If we're going to track retries, do it right:

```python
class FailedRelease(BaseModel):
    asin: str | None = None
    title: str | None = None
    path: str | None = None
    error: str | None = None
    error_type: str | None = None  # NEW: exception class name
    failed_at: str | None = None
    first_failed_at: str | None = None  # NEW: track duration
    retry_count: int = 0  # NOW USED

    model_config = {"extra": "ignore"}
```

Update `mark_failed()`:
```python
def mark_failed(release: AudiobookRelease, error: str, error_type: str | None = None) -> None:
    def _mark(state: dict[str, Any]) -> None:
        existing = state["failed"].get(identifier, {})
        state["failed"][identifier] = {
            "asin": release.asin,
            "title": release.title,
            "author": release.author,
            "failed_at": datetime.now().isoformat(),
            "first_failed_at": existing.get("first_failed_at", datetime.now().isoformat()),
            "error": error,
            "error_type": error_type or type(error).__name__ if isinstance(error, Exception) else None,
            "source_dir": str(release.source_dir) if release.source_dir else None,
            "retry_count": existing.get("retry_count", 0) + 1,
        }
    update_state(_mark)
```

### Acceptance Criteria
- [ ] `retry_count` increments on each failure
- [ ] `first_failed_at` preserved across retries
- [ ] `error_type` captured for debugging

---

## Step 3: Status-Aware `find_stale_entries()`

### Problem
After ABS import, staging_dir is expected to disappear. "Missing path" isn't always stale.

### Solution
Path requirements vary by status:

```python
REQUIRED_PATHS_BY_STATUS: dict[str, list[str]] = {
    "DISCOVERED": [],
    "STAGED": ["staging_dir"],
    "METADATA_FETCHED": ["staging_dir"],
    "TORRENT_CREATED": ["staging_dir", "torrent_path"],
    "UPLOADED": ["torrent_path"],  # staging may be gone
    "COMPLETE": [],  # all paths may be gone
}


def find_stale_entries() -> list[tuple[str, str, str]]:
    """
    Find entries with missing required paths.

    Returns:
        List of (identifier, status, missing_path) tuples
    """
    stale = []
    state = load_state()

    for identifier, entry in state.get("processed", {}).items():
        status = entry.get("status", "COMPLETE")
        required = REQUIRED_PATHS_BY_STATUS.get(status, [])

        for path_key in required:
            path_str = entry.get(path_key)
            if path_str and not Path(path_str).exists():
                stale.append((identifier, status, path_key))

    return stale
```

### Acceptance Criteria
- [ ] `state prune` does NOT delete valid entries just because files moved after completion
- [ ] Only flags entries where required-for-status paths are missing

---

## Step 4: `mamfast state` CLI Subcommand

### Design

```bash
mamfast state list [--failed|--processed] [--limit N] [--json]
mamfast state prune [--stale-only] [--failed-older-than DAYS]
mamfast state retry <ASIN>
mamfast state clear <ASIN>
mamfast state export [--output FILE]
```

### Implementation

#### `mamfast state list`
- Default: show counts + most recent 20 entries
- `--failed`: only failed entries
- `--processed`: only processed entries
- `--limit 50`: show more/fewer
- `--json`: machine-readable output

#### `mamfast state prune`
- Shows what would be removed
- Respects `--dry-run`
- `--stale-only` (default): entries with missing required paths
- `--failed-older-than 30d`: optional TTL cleanup

#### `mamfast state retry <ASIN>`
- Remove from failed (allows re-processing)
- Reset retry_count
- Print "not found" and exit 0 if missing

#### `mamfast state clear <ASIN>`
- Remove from processed (force full re-run)
- Also remove checkpoints
- Print "not found" and exit 0 if missing

### Acceptance Criteria
- [ ] All actions use `mamfast.console` helpers
- [ ] `--dry-run` respected for mutating actions
- [ ] "not found" is graceful (not an error)

---

## Step 5: Status Transition Validation

### Problem
Nothing prevents jumping from DISCOVERED → TORRENT_CREATED if code gets called out of order.

### Solution

```python
from mamfast.models import ReleaseStatus

ALLOWED_TRANSITIONS: dict[ReleaseStatus, set[ReleaseStatus]] = {
    ReleaseStatus.DISCOVERED: {ReleaseStatus.DISCOVERED, ReleaseStatus.STAGED},
    ReleaseStatus.STAGED: {ReleaseStatus.STAGED, ReleaseStatus.METADATA_FETCHED},
    ReleaseStatus.METADATA_FETCHED: {ReleaseStatus.METADATA_FETCHED, ReleaseStatus.TORRENT_CREATED},
    ReleaseStatus.TORRENT_CREATED: {ReleaseStatus.TORRENT_CREATED, ReleaseStatus.UPLOADED, ReleaseStatus.COMPLETE},
    ReleaseStatus.UPLOADED: {ReleaseStatus.UPLOADED, ReleaseStatus.COMPLETE},
    ReleaseStatus.COMPLETE: {ReleaseStatus.COMPLETE},
}


def validate_transition(current: ReleaseStatus, new: ReleaseStatus) -> None:
    """Validate status transition, raise if illegal."""
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if new not in allowed:
        raise InvalidStatusTransitionError(
            f"Invalid status transition: {current.name} → {new.name}\n"
            f"Allowed from {current.name}: {', '.join(s.name for s in allowed)}"
        )
```

Enforce in `checkpoint_stage()` and `mark_processed()`:
- Look up current status from state
- Validate before writing

### Acceptance Criteria
- [ ] Illegal transitions raise clear error
- [ ] Same-status writes allowed (idempotent)

---

## Step 6: Schema Migration Scaffolding

### Current State
- `version: int = 1` exists but unused

### Solution (Minimal Investment)

```python
CURRENT_SCHEMA_VERSION = 2  # Bump when schema changes


def _migrate_state(data: dict[str, Any]) -> dict[str, Any]:
    """Migrate state to current schema version."""
    version = data.get("version", 1)

    if version < 2:
        data = _migrate_v1_to_v2(data)
        data["version"] = 2

    # Future migrations go here
    # if version < 3:
    #     data = _migrate_v2_to_v3(data)
    #     data["version"] = 3

    return data


def _migrate_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """Add missing fields to v1 entries."""
    for identifier, entry in data.get("processed", {}).items():
        if "checkpoints" not in entry:
            entry["checkpoints"] = {}
        if "infohash" not in entry:
            entry["infohash"] = None

    for identifier, entry in data.get("failed", {}).items():
        if "first_failed_at" not in entry:
            entry["first_failed_at"] = entry.get("failed_at")
        if "error_type" not in entry:
            entry["error_type"] = None

    return data
```

Call `_migrate_state()` in `_load_state_unsafe()` after parsing.

### Acceptance Criteria
- [ ] Old v1 files auto-migrate on load
- [ ] Future migrations have clear pattern to follow

---

## Implementation Order

1. **Step 0**: Atomic write hardening (foundation)
2. **Step 6**: Schema migration scaffolding (needed before other changes)
3. **Step 2**: Fix retry_count (schema change)
4. **Step 1**: Add checkpoint tests (validate current behavior)
5. **Step 5**: Status transition validation
6. **Step 3**: find_stale_entries()
7. **Step 4**: CLI subcommand

---

## Edge Cases to Handle

### Duplicate Keys / Identity Drift
- `state clear <ASIN>` prints "not found" and exits 0 if missing
- Future: consider `--by-infohash` for torrent-based lookup

### Cross-Platform Locking
- **Decision**: Keep `fcntl.flock()` (Linux-only)
- Document in CONTRIBUTING.md that concurrent runs only supported on Linux
- If Windows/macOS support needed later, consider `filelock` package

### Failed Entry TTL
- **Default**: Keep forever (audit trail)
- **Optional**: `state prune --failed-older-than 30d`
