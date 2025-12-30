# abs-rename Implementation TODO

> Work breakdown for implementing `mamfast abs-rename` command.
> Based on design doc: [ABS_RENAME_TOOL.md](./ABS_RENAME_TOOL.md)

---

## Implementation Status

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 | ✅ Complete | Core Infrastructure (rename.py, discovery, ASIN resolution) |
| Phase 2 | ✅ Complete | Name Building (parsing, duplicate detection, target names) |
| Phase 3 | ✅ Complete | Execution (rename_folder, CLI command) |
| Phase 4 | ✅ Complete | Polish (interactive, report, file renaming) |

**Validation (2025-12-07):** 1707 tests pass, all linting (ruff, mypy, pre-commit) green.

---

## Phase 5: Performance & Debugging ✅ (2025-12-07)

### 5.1 Parallelization ✅

- [x] Added `ThreadPoolExecutor` for stages 2-4 (parse, enrich, resolve)
- [x] Worker count: `min(32, cpu_count * 4)` for I/O-bound operations
- [x] Result: ~2.6x speedup (2 min → 46 sec for 1300 folders)
- [x] Progress bars with Rich for each parallel stage

### 5.2 Enhanced JSON Report ✅

- [x] Added `warnings` section with:
  - `suspicious_changes_count` and `suspicious_changes` list
  - `duplicate_asin_groups` for debugging ASIN conflicts
- [x] Added `by_status` grouping for easier review
- [x] Per-result fields:
  - `source_path` and `target_path` (full paths)
  - `similarity_percent` for change magnitude
  - `is_suspicious_change` flag
  - `parsed` metadata block
  - `abs_metadata` block if available
- [x] Fixed similarity calculation (was 0-10000, now 0-100)

---

## Phase 4: Completed ✅

### 4.1 Interactive Mode (`--interactive`) ✅

- [x] Wired in `run_rename_pipeline()` - prompts per-folder with before/after names
- [x] Tracks `User declined` as skip reason in results
- [x] Test coverage in integration tests

---

### 4.2 JSON Report (`--report PATH`) ✅

- [x] Enhanced `generate_report()` with full metadata:
  - `timestamp` (ISO 8601 UTC)
  - `source_dir` and `dry_run` flags
  - Per-result: `asin`, `asin_source`, `files_renamed`
  - Summary statistics
- [x] Write JSON with `indent=2`
- [x] Test: `TestGenerateReport.test_generates_valid_json`

---

### 4.3 File Renaming Inside Folders (`--rename-files-inside`) ✅

- [x] Added `_rename_files_inside()` helper function
- [x] Skip list: `cover.jpg`, `cover.png`, `metadata.json`, `desc.txt`, `reader.txt`
- [x] Added `--rename-files-inside` CLI flag
- [x] `files_renamed: list[str]` already in `RenameResult`
- [x] Tests:
  - `TestRenameFilesInside.test_renames_media_files`
  - `TestRenameFilesInside.test_skips_cover_and_metadata`
  - `TestRenameFilesInside.test_idempotent_when_already_named`
  - `TestRenameWithFilesInside.test_rename_folder_with_files`

---

### 4.4 Optional: Trigger ABS Scan (`--trigger-scan`) ⏳ Deferred

- [ ] Add `--trigger-scan` CLI flag
- [ ] Reuse `trigger_scan_safe()` from importer
- [ ] Call once at end of batch (not per-folder)

---

## Integration Tests ✅ Complete

### `TestFullPipeline` (3 tests)

- [x] `test_full_pipeline_dry_run` - end-to-end with metadata.json
- [x] `test_full_pipeline_actual_rename` - real rename operation
- [x] `test_pipeline_skips_up_to_date` - correctly named folders skipped

---

## Config Schema (Optional) ⏳ Deferred

```python
class AbsRenameConfig(BaseModel):
    exclude_patterns: list[str] = Field(default_factory=list)
    auto_fetch_metadata: bool = False
    rename_files_inside: bool = False
```

**Tasks:**
- [ ] Add to config schema under `abs.rename`
- [ ] Wire config → CLI defaults
- [ ] CLI flags override config

---

## Decisions Made (Open Questions Resolved)

### 1. Rename files inside folders?
**Decision:** Yes, but opt-in via `--rename-files-inside` flag. ✅ Implemented
- Default: folder-only rename (safe)
- Opt-in: rename media files to match folder stem
- Skip: `cover.jpg`, `cover.png`, `metadata.json`, `desc.txt`, `reader.txt`

### 2. Handle `Unknown/` books (no ASIN)?
**Decision:** Mark as `status="missing_asin"` and skip. ✅ Implemented
- Clear reason in output: "no ASIN resolved after full cascade"
- In JSON report: `"error": "missing_asin"`
- Future: `--prompt-missing-asin` for interactive manual entry

### 3. ABS metadata.json vs folder ASIN conflict?
**Decision:** ABS metadata.json wins (authoritative). ✅ Implemented
- Log warning when ASINs differ
- Set `asin_source="abs_metadata"` for clarity in reports

### 4. Trigger ABS scan after rename?
**Decision:** Optional via `--trigger-scan` flag. ⏳ Deferred
- Calls `trigger_scan_safe()` once after batch
- Not per-folder (too noisy)
- Default off (not everyone wants auto-scan)

---

## Files Implemented

| File | Lines | Purpose |
|------|-------|---------|
| `src/mamfast/abs/rename.py` | ~999 | Core rename logic, pipeline, parallel processing, report generation |
| `src/mamfast/abs/cleanup.py` | ~878 | Post-import cleanup + orphan detection/cleanup |
| `src/mamfast/cli.py` | +280 | `abs-rename` + `abs-orphans` subcommands |
| `src/mamfast/console.py` | +fix | Fixed `confirm()` hint escaping for Rich |
| `src/mamfast/utils/naming.py` | +150 | Volume notation support |
| `tests/test_abs_rename.py` | ~600 | 41 unit + integration tests |
| `tests/test_abs_cleanup.py` | ~56 | Cleanup + orphan tests |
| `tests/test_naming.py` | +130 | 19 volume notation tests |

---

## CLI Reference

```bash
mamfast abs-rename [OPTIONS]

Options:
  --source PATH              Directory to scan (default: ABS library from config)
  --pattern GLOB             Glob pattern to filter folders (default: *)
  --fetch-metadata           Fetch missing metadata from Audnex API
  --abs-search               Use ABS Audible search for ASIN resolution
  --abs-search-confidence    Minimum confidence (default: 0.75)
  --interactive              Prompt for confirmation on each rename
  --rename-files-inside      Also rename media files to match folder name
  --report PATH              Output JSON report of changes

Global flags (before subcommand):
  mamfast --dry-run abs-rename    # Preview without renaming
  mamfast -v abs-rename           # Verbose logging
```

---

## New Command: `abs-orphans` ✅

Added command to find and clean up orphaned ABS folders (metadata.json but no audio).

```bash
mamfast abs-orphans [OPTIONS]

Options:
  --source PATH              Directory to scan (default: ABS library from config)
  --cleanup                  Remove orphans with matching audio folder (safe)
  --cleanup-all              Remove ALL orphans (DANGEROUS - prompts for confirmation)
  --min-match-score FLOAT    Minimum similarity to consider a match (default: 0.5)
  --report PATH              Output JSON report of orphaned folders

Global flags (before subcommand):
  mamfast --dry-run abs-orphans    # Preview without removing
```

**Features:**
- Scans library for folders with `metadata.json` but no audio files
- Matches orphans to sibling folders with audio (by name similarity)
- Progress spinner during scan
- Confirmation prompt for `--cleanup-all` with `[y/N]` hint

---

## Related Documentation

- [ABS_RENAME_TOOL.md](./ABS_RENAME_TOOL.md) - Full design doc
- [CLEANUP_PLAN.md](./CLEANUP_PLAN.md) - Cleanup + orphan detection
- [NAMING_FOLDER_FILE_SCHEMAS.md](../naming/NAMING_FOLDER_FILE_SCHEMAS.md) - Volume notation spec
- [NAMING_RULES.md](../naming/NAMING_RULES.md) - normalize_position() pseudocode
