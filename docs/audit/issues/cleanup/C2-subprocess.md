# C2: Consolidate Subprocess Usage

**Priority**: Low
**Effort**: Medium
**Risk**: Low

---

## Problem

Some modules use raw `subprocess.run()` while `src/shelfr/utils/cmd.py` provides a cleaner wrapper.

## Current State

Raw subprocess in:

- `src/shelfr/validation.py`
- `src/shelfr/libation.py`
- `src/shelfr/abs/trumping.py`
- `src/shelfr/abs/asin.py`
- `src/shelfr/metadata/mediainfo/extractor.py`
- `src/shelfr/wizard.py`
- `src/shelfr/utils/editor.py`

## Target Pattern

Use `utils.cmd` wrapper where appropriate:

```python
# Before
result = subprocess.run(
    ["docker", "exec", container, "ls"],
    capture_output=True,
    text=True,
    check=True,
)

# After
from shelfr.utils.cmd import run
result = run(["docker", "exec", container, "ls"])
```

## When to Keep subprocess

Keep `subprocess` for:

- Shell commands requiring `shell=True`
- Complex stdin/stdout handling
- Cases where `sh` library doesn't fit

## Acceptance Criteria

- [ ] Standard commands use `utils.cmd.run()`
- [ ] Document exceptions in code comments
