# C6: Fix __all__ Duplicate

__Priority__: Low
__Effort__: Trivial
__Risk__: None

---

## Problem

`src/shelfr/__init__.py` has duplicate entry:

```python
__all__ = [
    "__version__",
    "ShelfrError",
    "ShelfrError",  # Duplicate!
    ...
]
```

## Fix

Remove the duplicate line.

## Acceptance Criteria

- [ ] No duplicate entries in `__all__`
