# C1: Fix Stray print() Calls

**Priority**: Low
**Effort**: Low
**Risk**: Low

---

## Problem

Project guidelines require using `shelfr.console` Rich helpers, but bare `print()` calls exist:

```python
# src/shelfr/metadata/orchestration.py:280
print(f"Title: {result.fields.get('title')}")

# src/shelfr/metadata/aggregator.py:88-89
print(f"Title: {result.fields.get('title')}")
print(f"From: {result.sources.get('title')}")
```

## Find All Occurrences

```bash
grep -rn "print(" src/shelfr/ --include="*.py" | grep -v "console.print" | grep -v "#"
```

## Target Pattern

```python
# Before
print(f"Title: {result.fields.get('title')}")

# After (for user output)
from shelfr.console import console
console.print(f"Title: {result.fields.get('title')}")

# Or (for debug output)
logger.debug(f"Title: {result.fields.get('title')}")
```

## Files to Change

1. `src/shelfr/metadata/orchestration.py`
2. `src/shelfr/metadata/aggregator.py`
3. Any others found

## Acceptance Criteria

- [ ] No bare `print()` calls in `src/shelfr/`
- [ ] All output uses `console.print()` or `logger.*`
