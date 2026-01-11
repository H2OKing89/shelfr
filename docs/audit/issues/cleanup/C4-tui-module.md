# C4: TUI Module Decision

**Priority**: Low
**Effort**: Varies
**Risk**: Low

---

## Problem

`src/shelfr/tui/` module is incomplete:

- Listed as optional dependency (`[tui]` extra)
- Coverage explicitly excluded
- mypy errors ignored
- Only `__init__.py` and `app.py` exist

## Options

### Option A: Complete the TUI

- Finish Textual-based TUI
- Add proper tests
- Document usage

### Option B: Extract to Separate Package

- Create `shelfr-tui` package
- Remove from main codebase
- Optional install: `pip install shelfr-tui`

### Option C: Remove (Recommended if not planned)

- Delete `src/shelfr/tui/`
- Remove `[tui]` extra from `pyproject.toml`
- Clean up coverage/mypy excludes

## Acceptance Criteria

- [ ] Decision made and documented
- [ ] Implementation completed based on decision
