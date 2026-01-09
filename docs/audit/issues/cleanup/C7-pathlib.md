# C7: Standardize pathlib Usage

**Priority**: Low
**Effort**: Low
**Risk**: Low

---

## Problem

While `pathlib.Path` is the standard, some modules still use `os.path`:

```python
# src/shelfr/abs/metadata_builder.py
if temp_path and os.path.exists(temp_path):
    os.remove(temp_path)

# src/shelfr/utils/paths.py
abs_path = os.path.abspath(path_str)
```

## Target Pattern

```python
# Before
os.path.exists(path) → path.exists()
os.path.abspath(path) → Path(path).resolve()
os.remove(path) → path.unlink()
os.makedirs(path) → path.mkdir(parents=True)
```

## Find Occurrences

```bash
grep -rn "os.path" src/shelfr/ --include="*.py"
grep -rn "os.remove\|os.makedirs" src/shelfr/ --include="*.py"
```

## Acceptance Criteria

- [ ] No `os.path.*` calls (prefer `Path` methods)
- [ ] No `os.remove/makedirs` (prefer `Path.unlink/mkdir`)
