# C8: Split abs/importer.py

**Priority**: Low
**Effort**: High
**Risk**: Medium

---

## Problem

`src/shelfr/abs/importer.py` is 2193 lines - the largest module in the codebase.

## Target Structure

```
src/shelfr/abs/importer/
├── __init__.py         # Re-exports
├── core.py             # Main import logic
├── duplicates.py       # Duplicate detection
├── batch.py            # Batch async operations
├── parsing.py          # Folder name parsing
├── unknown_asin.py     # Unknown ASIN handling
└── results.py          # ImportResult, BatchImportResult
```

## Key Classes/Functions to Extract

- `ParsedFolderName`, `parse_mam_folder_name()` → `parsing.py`
- `UnknownAsinPolicy`, `UnknownAsinContext` → `unknown_asin.py`
- `ImportResult`, `BatchImportResult` → `results.py`
- `import_batch_async()` → `batch.py`
- Duplicate detection logic → `duplicates.py`

## Acceptance Criteria

- [ ] Module split into logical sub-modules
- [ ] All existing imports still work
- [ ] No sub-module exceeds 500 lines
