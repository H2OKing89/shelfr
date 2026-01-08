# Dead Code Removal Guide

> Part of [Metadata Architecture Documentation](README.md)
>
> **Purpose:** Systematic approach to identifying, deprecating, and removing unused code during migrations.

---

## Why This Matters

Dead code accumulates during migrations and refactors. It causes:

- **Confusion** — "Is this still used? Should I update it?"
- **Maintenance burden** — Tests, linting, type-checking still run on dead code
- **Security risk** — Unmaintained code may have vulnerabilities
- **Cognitive load** — More code to read and understand

This guide provides a structured process to safely remove dead code.

---

## The Deprecation Lifecycle

```
┌─────────────┐    ┌───────────────┐    ┌─────────────┐    ┌─────────────┐
│   Active    │───▶│  Deprecated   │───▶│  Warning    │───▶│  Removed    │
│  (in use)   │    │ (still works) │    │ (noisy)     │    │  (gone)     │
└─────────────┘    └───────────────┘    └─────────────┘    └─────────────┘
     v1.x              v1.x+1             v2.0-rc           v2.0
```

| Stage | What It Means | User Impact |
| ------- | --------------- | ------------- |
| **Active** | Code is in use, maintained | None |
| **Deprecated** | Code still works, but has a replacement | Docstring/log says "use X instead" |
| **Warning** | Emits `DeprecationWarning` on use | Users see warning, should migrate |
| **Removed** | Code is deleted | Import fails, forces migration |

**Rule of thumb:** Give users at least **one minor version** with warnings before removal.

---

## Step 1: Identify Dead Code

### 1.1 Automated Tools

```bash
# Find unused imports (fast, catches obvious issues)
ruff check --select F401 src/

# Find unused variables and functions
ruff check --select F841,F811 src/

# Vulture finds unused code (more aggressive, may have false positives)
pip install vulture
vulture src/shelfr/ --min-confidence 80
```

### 1.2 Manual Grep Checks

```bash
# Check if a function is ever called (outside its definition)
grep -rn "function_name" src/ --include="*.py" | grep -v "def function_name"

# Check if a class is ever instantiated or referenced
grep -rn "ClassName" src/ --include="*.py" | grep -v "class ClassName"

# Check if a module is ever imported
grep -rn "from shelfr.module import\|import shelfr.module" src/ tests/
```

### 1.3 Test Coverage Analysis

```bash
# Run tests with coverage
pytest --cov=src/shelfr --cov-report=html

# Look for code with 0% coverage — often dead
open htmlcov/index.html
```

### 1.4 IDE Features

- **VS Code:** Right-click a function → "Find All References"
- **PyCharm:** Ctrl+Alt+F7 → "Find Usages"
- If no references outside the definition → likely dead

---

## Step 2: Categorize What You Found

| Category | Action | Example |
| ---------- | -------- | --------- |
| **Internal helper** (no external users) | Delete immediately | `_parse_internal_format()` |
| **Public function** (might have users) | Deprecate first | `fetch_metadata()` |
| **Entire module** | Deprecation shim | `shelfr.opf` → `shelfr.metadata.opf` |
| **Config option** | Deprecate + warn | `old_setting_name` |

---

## Step 3: Deprecation Patterns

### 3.1 Function Deprecation

```python
import warnings
from functools import wraps

def deprecated(reason: str, removal_version: str = "2.0"):
    """Decorator to mark functions as deprecated."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            warnings.warn(
                f"{func.__name__} is deprecated and will be removed in v{removal_version}. "
                f"{reason}",
                DeprecationWarning,
                stacklevel=2,  # Points to caller, not this wrapper
            )
            return func(*args, **kwargs)
        return wrapper
    return decorator

# Usage
@deprecated("Use fetch_metadata_async() instead")
def fetch_metadata_sync(asin: str) -> dict:
    ...
```

### 3.2 Module Deprecation (Shim Pattern)

When you move a module, leave a shim at the old location:

```python
# src/shelfr/opf/__init__.py (OLD location - now a shim)
"""
DEPRECATED: This module has moved to shelfr.metadata.opf

This shim exists for backwards compatibility and will be removed in v2.0.
Update your imports:
    # Old (deprecated)
    from shelfr.opf import write_opf

    # New (preferred)
    from shelfr.metadata.opf import write_opf
"""
import warnings
import os

# Allow disabling warning for gradual migration
if not os.environ.get("SHELFR_ENABLE_LEGACY_OPF"):
    warnings.warn(
        "shelfr.opf is deprecated. Use shelfr.metadata.opf instead. "
        "Set SHELFR_ENABLE_LEGACY_OPF=1 to suppress this warning.",
        DeprecationWarning,
        stacklevel=2,
    )

# Re-export from new location so old imports still work
from shelfr.metadata.opf import write_opf, read_opf, OPFGenerator

__all__ = ["write_opf", "read_opf", "OPFGenerator"]
```

### 3.3 Class Deprecation

```python
class OldClassName:
    """
    DEPRECATED: Use NewClassName instead.

    This class will be removed in v2.0.
    """

    def __init__(self, *args, **kwargs):
        warnings.warn(
            "OldClassName is deprecated. Use NewClassName instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Delegate to new class
        self._delegate = NewClassName(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._delegate, name)
```

---

## Step 4: Safe Removal Checklist

Before deleting code, verify:

- [ ] **No grep hits** in `src/` (excluding the definition itself)
- [ ] **No grep hits** in `tests/` (or update tests first)
- [ ] **No grep hits** in docs (`docs/`, `README.md`, docstrings)
- [ ] **Deprecation warning** was shipped in at least one release
- [ ] **CHANGELOG** documents the removal
- [ ] **Tests pass** after removal

### Removal Command Template

```bash
# 1. Verify no usage
grep -rn "function_to_remove" src/ tests/ docs/ --include="*.py" --include="*.md"

# 2. Remove the code
# (edit file manually or use sed)

# 3. Run tests
pytest

# 4. Run linters
ruff check src/ tests/

# 5. Commit with clear message
git commit -m "chore: remove deprecated function_to_remove (deprecated in v1.5)"
```

---

## Step 5: Document Removals

### In CHANGELOG.md

```markdown
## [2.0.0] - 2026-XX-XX

### Removed

- **BREAKING:** Removed `shelfr.opf` module. Use `shelfr.metadata.opf` instead.
- **BREAKING:** Removed `fetch_metadata_sync()`. Use `fetch_metadata_async()` instead.
- Removed deprecated `OldClassName` class.
```

### In Code (Before Removal)

Add a `# REMOVAL:` comment when deprecating, so future you knows when to delete:

```python
# REMOVAL: v2.0 - Delete this entire function after v2.0 release
@deprecated("Use new_function() instead", removal_version="2.0")
def old_function():
    ...
```

---

## Current Deprecation Inventory (shelfr)

| Item | Deprecated In | Remove In | Replacement | Status |
| ------- | --------------- | ----------- | ------------- | -------- |
| `shelfr.opf` module | v1.x | v2.0 | `shelfr.metadata.opf` | Shim active |
| `cli_argparse.py` | v1.x | v2.0 | Typer CLI (`cli/`) | Deprecated |
| `cli_legacy.py` | — | — | `cli/` package | **Removed** |

---

## Tools Reference

| Tool | Purpose | Command |
| ------- | --------- | --------- |
| **ruff** | Lint for unused imports/vars | `ruff check --select F401,F841 src/` |
| **vulture** | Find dead code | `vulture src/ --min-confidence 80` |
| **pytest-cov** | Coverage (find untested code) | `pytest --cov=src/shelfr` |
| **grep** | Manual reference search | `grep -rn "pattern" src/` |
| **git log** | When was code last touched? | `git log -1 --format="%ai" -- path/to/file.py` |

---

## Common Mistakes to Avoid

### ❌ Deleting Without Deprecation Warning

```python
# BAD: Just delete it
# (users' code breaks with no warning)
```

```python
# GOOD: Deprecate first, remove in next major version
@deprecated("Use X instead", removal_version="2.0")
def old_function():
    ...
```

### ❌ Breaking Import Paths Without Shims

```python
# BAD: Move module, old imports fail immediately
# from shelfr.old_location import thing  # ImportError!
```

```python
# GOOD: Leave a shim that warns and re-exports
# Old location still works, but warns
```

### ❌ Removing Code That Tests Depend On

```bash
# Always check tests BEFORE removing
grep -rn "function_name" tests/
```

### ❌ Keeping Dead Code "Just In Case"

If code hasn't been used in 6+ months and has a replacement:

- It's in git history if you need it
- Delete it now, or it becomes someone else's problem

---

## Summary Workflow

```
1. IDENTIFY    → ruff, vulture, grep, coverage
2. CATEGORIZE  → internal (delete) vs public (deprecate)
3. DEPRECATE   → Add warning, document replacement
4. WAIT        → Ship at least one release with warning
5. REMOVE      → Verify no usage, delete, update CHANGELOG
6. VERIFY      → Tests pass, linters pass
```

---

## Related Documents

- [Phase 7: Cleanup & Hygiene](05-implementation-checklist.md#phase-7-cleanup--hygiene) — Specific hygiene tasks for this migration
- [Deprecation Tracking](05-implementation-checklist.md#deprecation-tracking) — Current deprecation timeline
