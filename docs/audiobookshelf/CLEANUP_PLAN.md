# Staging Cleanup Feature Plan

## Problem Statement

After `abs-import` successfully moves audiobooks from staging (`seed_root`) to the ABS library, the original Libation source files (`library_root`) are still present. Users need a way to clean these up safely.

## Current Flow

```
Libation downloads → library_root (source)
                          ↓
mamfast prepare     → seed_root (staging/hardlinks for seeding)
                          ↓
mamfast abs-import  → ABS library (final destination)
```

After import:
- ✅ ABS library has the book
- ✅ seed_root has hardlinks (for continued seeding)
- ❌ library_root still has original files (wasting space)

---

## Library Structure Analysis

The `library_root` contains **three classes** of folders:

### Class 1: Libation+mamfast style, fully tagged (SAFE TO AUTOMATE)

```text
Aneko Yusagi/
  Rising of the Shield Hero/
    The Rising of the Shield Hero Volume 04 ... {ASIN.B0BN2GGTCK} [H2OKing]/
      ├── *.m4b
      ├── *.metadata.json
      └── *.jpg / *.cue
```

**Eligibility criteria:**
- Contains at least one `.m4b`
- AND has a `.metadata.json` file
- AND/OR has `{ASIN.XXXXXXXXXX}` pattern in folder name
- AND we have a record of successful import for that ASIN

### Class 2: Raw/legacy folders (SKIP)

```text
A Most Unlikely Hero, Volume 8/
  └── A Most Unlikely Hero, Volume 8.m4b   # No .metadata.json
```

These might not have gone through mamfast yet, or use old Libation layout.

### Class 3: Special/scratch folders (ALWAYS IGNORE)

```text
__import_test/
.git/
```

**For the first-pass cleanup system, only Class 1 folders are eligible.**

---

## Proposed Solution: Cleanup Strategies

### Configuration

```yaml
audiobookshelf:
  import:
    # ───────────────────────────────────────────────────────────────────────
    # Post-Import Cleanup
    # Controls what happens to Libation source files after successful import
    # ───────────────────────────────────────────────────────────────────────
    cleanup:
      # Cleanup strategy for successfully imported books
      # - none: Leave source files in place (default, safest)
      # - hide: Add hidden marker file (for Libation to ignore)
      # - move: Move source to cleanup_path
      # - delete: Remove source files (DANGEROUS - data loss if seeding fails)
      strategy: none

      # Path for moved files (required if strategy=move)
      # cleanup_path: "/mnt/user/data/audio/imported-cleanup"

      # Only cleanup if seeding hardlink still exists?
      # Prevents deletion if torrent was removed from qBittorrent
      require_seed_exists: true

      # Delay cleanup until after ABS scan confirms book exists
      verify_in_abs: false

      # Hidden marker file name (for strategy=hide)
      hide_marker: ".mamfast_imported"

      # Age-based filter: only cleanup sources older than N days (0 = disabled)
      min_age_days: 0

      # Directories to always ignore during standalone cleanup
      ignore_dirs:
        - "__import_test"
        - ".git"
        - ".venv"

      # Glob patterns to ignore
      ignore_glob:
        - "*/__*"
        - "*/.#*"
```

### Strategy Descriptions

| Strategy | Action | Risk Level | Use Case |
|----------|--------|------------|----------|
| `none` | No cleanup | None | Default, manual cleanup preferred |
| `hide` | Add `.mamfast_imported` marker | Very Low | Prevent Libation re-download detection |
| `move` | Move to `cleanup_path` | Low | Preserve files but free up space |
| `delete` | Remove source folder | **HIGH** | Trusted setup, space-critical |

---

## Import Tracking Table

A persistent record of imports enables safe, targeted cleanup:

```sql
CREATE TABLE abs_imports (
    id INTEGER PRIMARY KEY,
    asin TEXT NOT NULL,
    source_path TEXT NOT NULL,      -- /mnt/user/data/audio/audiobook-import/Author/Series/Book
    seed_path TEXT,                 -- per-book staging folder from prepare step
    abs_library_path TEXT,          -- final location in ABS library
    status TEXT NOT NULL,           -- success / failed / trump_replaced / duplicate / skipped
    imported_at DATETIME NOT NULL,
    cleanup_status TEXT NOT NULL DEFAULT 'pending',
        -- pending / cleaned / skipped / failed
    cleanup_at DATETIME,
    cleanup_error TEXT,
    cleanup_destination TEXT        -- for move strategy
);

CREATE INDEX idx_abs_imports_asin ON abs_imports(asin);
CREATE INDEX idx_abs_imports_cleanup ON abs_imports(cleanup_status);
```

**Benefits:**
- `abs-import` can immediately trigger cleanup for that specific book
- `mamfast abs-cleanup` can later re-process pending/failed items
- Only touches books that were actually imported (no guessing)
- Enables undo for move strategy

---

## Safety Guardrails

### 1. Hardlink Verification (`require_seed_exists`)

Before any cleanup, verify the seed folder still has hardlinked files:

```python
def verify_seed_exists(source_path: Path, seed_root: Path) -> bool:
    """Check that seed hardlinks exist for the source files."""
    # Find corresponding seed folder by ASIN or folder name
    # Verify at least one hardlink exists (inode match)
    pass
```

**Why:** If the torrent was removed from qBittorrent and seed files deleted, cleaning up source would cause data loss.

### 2. ABS Verification (`verify_in_abs`)

Optional extra safety - query ABS API to confirm book is visible:

```python
def verify_in_abs(asin: str, client: AbsClient, asin_index: dict) -> bool:
    """Check that book exists in ABS library."""
    return asin in asin_index
```

**Why:** Catches edge cases where move succeeded but ABS hasn't scanned yet.

### 3. Status-Gated Cleanup

Only cleanup on successful imports:

```python
# Only these statuses trigger cleanup
CLEANUP_ELIGIBLE_STATUSES = {"success", "trump_replaced"}

# Never cleanup on:
# - "failed", "duplicate", "skipped", "trump_kept_existing"
```

### 4. Dry-Run Support

All cleanup operations respect `--dry-run`:

```python
if dry_run:
    logger.info("[DRY RUN] Would cleanup source: %s", source_path)
    return CleanupResult(status="dry_run", source_path=source_path)
```

### 5. Never Touch Seed Files

Cleanup only affects `library_root` (source), never `seed_root` (staging):

```python
def cleanup_source(source_path: Path, seed_root: Path, ...) -> CleanupResult:
    # Safety: Refuse to cleanup anything under seed_root
    if source_path.is_relative_to(seed_root):
        raise CleanupError(f"Refusing to cleanup seed path: {source_path}")
```

### 6. Full Path Logging

Every cleanup action logged with complete paths:

```
INFO  | Cleanup (hide): /mnt/user/data/audio/audiobook-import/Author/Book
INFO  | Created marker: /mnt/user/data/audio/audiobook-import/Author/Book/.mamfast_imported
```

## Implementation Phases

### Phase 1: Core Cleanup Module (`abs/cleanup.py`)

```python
"""Post-import cleanup for Libation source files."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class CleanupStrategy(Enum):
    """Strategy for cleaning up source files after import."""
    NONE = "none"      # Leave source files in place
    HIDE = "hide"      # Add marker file
    MOVE = "move"      # Move to cleanup_path
    DELETE = "delete"  # Remove source files


@dataclass
class CleanupPrefs:
    """Cleanup preferences from config."""
    strategy: CleanupStrategy = CleanupStrategy.NONE
    cleanup_path: Path | None = None
    require_seed_exists: bool = True
    verify_in_abs: bool = False
    hide_marker: str = ".mamfast_imported"


@dataclass
class CleanupResult:
    """Result of a cleanup operation."""
    source_path: Path
    status: str  # "success", "skipped", "failed", "dry_run"
    strategy: CleanupStrategy
    error: str | None = None
    destination: Path | None = None  # For move strategy


def verify_seed_exists(
    source_path: Path,
    seed_root: Path,
    asin: str | None = None,
) -> tuple[bool, Path | None]:
    """Check that seed hardlinks exist for source files.

    Args:
        source_path: Original source folder (library_root)
        seed_root: Seed/staging root folder
        asin: Optional ASIN to help locate seed folder

    Returns:
        Tuple of (exists: bool, seed_path: Path | None)
    """
    pass


def cleanup_source(
    source_path: Path,
    prefs: CleanupPrefs,
    *,
    seed_root: Path | None = None,
    asin: str | None = None,
    dry_run: bool = False,
) -> CleanupResult:
    """Execute cleanup on source folder.

    Args:
        source_path: Path to source folder to clean up
        prefs: Cleanup preferences
        seed_root: Seed root for hardlink verification
        asin: ASIN for the book (for verification)
        dry_run: If True, don't actually modify files

    Returns:
        CleanupResult with status and details
    """
    pass
```

### Phase 2: Integration with `import_single`

Add cleanup to the import flow:

```python
def import_single(
    staging_folder: Path,
    library_root: Path,
    asin_index: dict[str, AsinEntry],
    *,
    # ... existing params ...
    cleanup_prefs: CleanupPrefs | None = None,  # NEW
    source_path: Path | None = None,  # NEW - original Libation path
    seed_root: Path | None = None,  # Already exists
    dry_run: bool = False,
) -> ImportResult:
    """Import a single audiobook from staging to library."""

    # ... existing import logic ...

    # Post-import cleanup (only on success)
    if (
        result.status in CLEANUP_ELIGIBLE_STATUSES
        and cleanup_prefs
        and cleanup_prefs.strategy != CleanupStrategy.NONE
        and source_path
    ):
        cleanup_result = cleanup_source(
            source_path=source_path,
            prefs=cleanup_prefs,
            seed_root=seed_root,
            asin=asin,
            dry_run=dry_run,
        )
        result.cleanup = cleanup_result

    return result
```

### Phase 3: Standalone Command

Add `mamfast abs-cleanup` for manual cleanup of previously imported books:

```bash
# Clean up all imported books in library_root
mamfast abs-cleanup

# Dry run first
mamfast --dry-run abs-cleanup

# Override strategy
mamfast abs-cleanup --strategy move --cleanup-path /path/to/cleanup

# Only specific paths
mamfast abs-cleanup /path/to/author/book1 /path/to/author/book2
```

### Phase 4: Config & CLI

#### Config Schema Addition

```python
@dataclass
class CleanupConfig:
    """Cleanup configuration."""
    strategy: str = "none"
    cleanup_path: str | None = None
    require_seed_exists: bool = True
    verify_in_abs: bool = False
    hide_marker: str = ".mamfast_imported"
```

#### CLI Arguments

```python
# In build_parser() for abs-import
parser.add_argument(
    "--cleanup-strategy",
    choices=["none", "hide", "move", "delete"],
    help="Override cleanup strategy (default: from config)",
)
parser.add_argument(
    "--skip-cleanup",
    action="store_true",
    help="Skip post-import cleanup even if configured",
)
```

## Risk Mitigation Matrix

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Delete before seed exists | Medium | High | `require_seed_exists: true` (default) |
| Delete failed import | Low | High | Only cleanup on `status="success"` |
| Delete wrong files | Low | Critical | Full path logging, dry-run first |
| Libation re-downloads | Medium | Low | `hide` strategy adds marker file |
| User regret | Medium | Medium | `move` strategy preserves files |
| ABS hasn't scanned yet | Low | Low | `verify_in_abs: true` option |

## Default Behavior

The feature is **opt-in** with safe defaults:

```yaml
cleanup:
  strategy: none              # No automatic cleanup
  require_seed_exists: true   # Always verify hardlinks
  verify_in_abs: false        # Skip ABS verification (faster)
  hide_marker: ".mamfast_imported"
```

Users must explicitly enable cleanup:

```yaml
cleanup:
  strategy: hide  # or move, delete
```

## Testing Strategy

### Unit Tests (`test_abs_cleanup.py`)

```python
class TestCleanupStrategies:
    def test_strategy_none_does_nothing(self): ...
    def test_strategy_hide_creates_marker(self): ...
    def test_strategy_move_relocates_folder(self): ...
    def test_strategy_delete_removes_folder(self): ...

class TestSafetyGuardrails:
    def test_require_seed_exists_blocks_cleanup(self): ...
    def test_verify_in_abs_blocks_cleanup(self): ...
    def test_refuses_cleanup_under_seed_root(self): ...
    def test_only_cleanup_on_success_status(self): ...
    def test_dry_run_no_changes(self): ...

class TestIntegration:
    def test_import_single_with_cleanup(self): ...
    def test_import_batch_with_cleanup(self): ...
```

## Future Enhancements

1. **Undo command**: `mamfast abs-cleanup --undo` to restore moved files
2. ~~**Cleanup report**: Summary of what was cleaned and space saved~~ ✅ Implemented via `--report`
3. **Age-based cleanup**: Only cleanup sources older than N days
4. **Verification scan**: `mamfast abs-verify` to check all imports have seeds

---

## Orphan Detection & Cleanup ✅ (2025-12-07)

New `abs-orphans` command to find and clean up orphaned ABS folders.

### Problem

Audiobookshelf sometimes creates duplicate library entries that leave behind orphaned folders with `metadata.json` and `cover.jpg` but no audio files. These waste space and clutter the library.

### Solution

```bash
# Scan for orphans (safe - no changes)
mamfast abs-orphans --source /path/to/abs/library

# Preview cleanup
mamfast --dry-run abs-orphans --cleanup

# Clean up orphans with matching audio folders (safe)
mamfast abs-orphans --cleanup

# Clean up ALL orphans (dangerous - prompts for confirmation)
mamfast abs-orphans --cleanup-all

# Generate JSON report
mamfast abs-orphans --report orphans.json
```

### Implementation

Added to `abs/cleanup.py`:
- `OrphanedFolder` dataclass - path, files, matching_folder, match_score
- `OrphanScanResult` dataclass - orphaned_with_match, orphaned_no_match, totals
- `scan_orphaned_folders()` - finds folders with metadata.json but no audio
- `cleanup_orphaned_folders()` - removes orphaned folders
- Progress callback support for spinner display

### Matching Logic

1. Scan all folders with `metadata.json`
2. Classify as "has audio" or "orphaned"
3. For each orphan, find sibling folders with audio
4. Calculate name similarity using `difflib.SequenceMatcher`
5. Match if similarity >= `min_match_score` (default 0.5)

### Safety

- `--cleanup` only removes orphans with confirmed matches
- `--cleanup-all` requires confirmation prompt: `? Are you sure? [y/N]`
- Dry-run mode shows what would be removed

## Changelog

| Date | Change |
|------|--------|
| 2025-12-07 | **Orphan detection**: Added `abs-orphans` command with `--cleanup`, `--cleanup-all`, `--report` flags; progress spinner; confirmation prompt with `[y/N]` hint |
| 2025-12-07 | **Phase 3 complete**: CLI integration with `--cleanup-strategy`, `--cleanup-path`, `--no-cleanup` flags for `abs-import`; standalone `abs-cleanup` command; `CleanupConfig` dataclass and `build_cleanup_prefs()` function; 19 new CLI tests |
| 2025-01-16 | **Phase 2 complete**: Cleanup integration in `import_single()` and `import_batch()` |
| 2025-01-16 | **Phase 1 complete**: Core `abs/cleanup.py` module, `CleanupSchema` config, 50 tests |
| 2025-01-15 | Initial plan created |
