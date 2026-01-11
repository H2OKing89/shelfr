# O1: Remove cli_argparse.py

**Priority**: Medium
**Effort**: Low
**Risk**: Low (already deprecated)

---

## Problem

The legacy argparse CLI (`src/shelfr/cli_argparse.py`, 787 lines) is deprecated but still in the source tree. It's also re-exported from `cli/__init__.py` for backward compatibility.

## Current State

```python
# src/shelfr/cli_argparse.py
"""⚠ DEPRECATED: This module is deprecated and will be removed in v2.0.
Use the Typer-based CLI via `shelfr` command instead.
"""
```

## Options

### Option A: Remove Entirely (Recommended)

- Delete `cli_argparse.py`
- Remove re-export from `cli/__init__.py`
- Document migration in CHANGELOG

### Option B: Move to _deprecated/

- Move to `src/shelfr/_deprecated/cli_argparse.py`
- Update imports
- Add deprecation warnings when imported

## Implementation (Option A)

### Step 1: Check for Usage

```bash
# Search for any imports of cli_argparse
grep -r "cli_argparse" src/
grep -r "cli_argparse" tests/
```

### Step 2: Remove Files

```bash
rm src/shelfr/cli_argparse.py
```

### Step 3: Update cli/**init**.py

Remove backward compatibility exports:

```python
# Remove these lines
from shelfr.cli_argparse import main as argparse_main
```

### Step 4: Update CHANGELOG

```markdown
## [Unreleased]

### Removed
- Removed deprecated `cli_argparse.py` module. Use the Typer-based CLI (`shelfr` command) instead.
```

## Files to Change

1. Delete `src/shelfr/cli_argparse.py`
2. Update `src/shelfr/cli/__init__.py`
3. Update `CHANGELOG.md`
4. Update any tests that reference it

## Acceptance Criteria

- [ ] `cli_argparse.py` removed from codebase
- [ ] No import errors
- [ ] All tests pass
- [ ] CHANGELOG updated
- [ ] Migration documented if needed
