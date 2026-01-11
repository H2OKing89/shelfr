# O5: Deprecation Timeline

**Priority**: Medium
**Effort**: Low
**Risk**: Low

---

## Problem

Multiple deprecated items exist without clear removal dates:

| Location | Item | Current Status |
|----------|------|----------------|
| `cli_argparse.py` | Entire module | "Removed in v2.0" |
| `cli/_helpers.py` | `ArgsNamespace`, `get_args()` | Deprecated |
| `metadata/formatting/html.py` | `_clean_html()` | Deprecated |
| `metadata/orchestration.py` | `region` parameter | Deprecated |
| `schemas/config.py` | `filters.remove_phrases` | Deprecated |
| `__init__.py` | Duplicate `ShelfrError` | Should be immediate |

## Target State

1. Clear timeline document
2. Deprecation warnings in code
3. CI enforcement (optional)

## Implementation

### Step 1: Create Deprecation Document

Create `docs/DEPRECATION.md`:

```markdown
# Deprecation Timeline

This document tracks deprecated features and their planned removal dates.

## Removal in v1.0 (Current Development)

| Item | Location | Alternative | Notes |
|------|----------|-------------|-------|
| `_clean_html()` | `metadata/formatting/html.py` | Use `clean_html()` | Internal function |
| `region` param | `metadata/orchestration.py` | Use `regions` list | Pluralized |
| `filters.remove_phrases` | Config | Use `naming.json` | New location |

## Removal in v2.0

| Item | Location | Alternative | Notes |
|------|----------|-------------|-------|
| `cli_argparse.py` | Module | Use Typer CLI | Full module removal |
| `ArgsNamespace` | `cli/_helpers.py` | Use `RuntimeContext` | Type alias |
| `get_args()` | `cli/_helpers.py` | Use context | Function |

## How to Deprecate

1. Add `warnings.warn()` with `DeprecationWarning`
2. Document in this file with removal version
3. Add test that warning is raised
```

### Step 2: Add Deprecation Warnings

```python
# In cli/_helpers.py
import warnings

def get_args() -> ArgsNamespace:
    """Get CLI arguments.

    .. deprecated:: 0.3.0
        Use RuntimeContext instead. Will be removed in v2.0.
    """
    warnings.warn(
        "get_args() is deprecated, use RuntimeContext instead. "
        "Will be removed in v2.0.",
        DeprecationWarning,
        stacklevel=2,
    )
    # ... existing implementation
```

### Step 3: Add Deprecation Tests

```python
# tests/test_deprecations.py
import warnings
import pytest

def test_get_args_deprecation_warning():
    """Verify get_args() raises deprecation warning."""
    with pytest.warns(DeprecationWarning, match="get_args.*deprecated"):
        from shelfr.cli._helpers import get_args
        get_args()
```

### Step 4: Fix Immediate Issues

Some items should be fixed immediately:

- Remove duplicate `ShelfrError` from `__all__`

## Files to Create

1. `docs/DEPRECATION.md`
2. `tests/test_deprecations.py`

## Files to Change

1. `src/shelfr/__init__.py` - fix duplicate
2. `src/shelfr/cli/_helpers.py` - add warnings
3. `src/shelfr/metadata/formatting/html.py` - add warnings
4. `src/shelfr/metadata/orchestration.py` - add warnings

## Acceptance Criteria

- [ ] `docs/DEPRECATION.md` created with timeline
- [ ] All deprecated items have `warnings.warn()`
- [ ] Tests verify warnings are raised
- [ ] Immediate fixes applied (duplicate `ShelfrError`)
