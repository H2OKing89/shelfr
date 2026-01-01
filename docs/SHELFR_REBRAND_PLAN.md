# Shelfr Rebrand Plan

**Date**: December 2025
**Status**: ✅ Phase 1 Complete
**Scope**: Rebrand `Shelfr` → `shelfr` + future CLI restructure

---

## Executive Summary

The project has evolved from a simple MAM upload script (`mam_tool`) into a comprehensive audiobook management suite. The rebrand to **shelfr** reflects this growth and positions the tool for future expansion.

**Rebrand happens in two phases:**

1. **Phase 1: Simple Rebrand** — ✅ COMPLETE - Renamed `Shelfr` → `shelfr`
2. **Phase 2: Suite Restructure** — Reorganize commands into domain-focused sub-apps (future)

---

## Phase 1: Simple Rebrand (✅ COMPLETE)

### What Changed

| Before | After |
|--------|-------|
| `Shelfr` | `shelfr` |
| `src/Shelfr/` | `src/shelfr/` |
| `from Shelfr import ...` | `from shelfr import ...` |

### What Stayed the Same

- All command names and structure
- All functionality
- Config file format (`config/config.yaml`)
- State file format (`data/processed.json`)
- Config keys like `Shelfr_managed` (backward compat)

### Rebrand Checklist

#### Repository

- [ ] Rename GitHub repo `mam_tool` → `shelfr` (manual step)
- [x] Update repo description in README
- [ ] Update topics/tags (after rename)

#### Package

- [x] Rename `src/Shelfr/` → `src/shelfr/`
- [x] Update `pyproject.toml`:
  - [x] `name = "shelfr"`
  - [x] `[project.scripts]` entry point
  - [x] Update all internal references
- [x] Update all internal imports (`from Shelfr.` → `from shelfr.`)
- [x] Update Jinja2 PackageLoader reference

#### CLI

- [x] Update CLI app name in `cli/_app.py`
- [x] Update help text and epilogs
- [x] Update version display
- [x] Add `Shelfr` as deprecated alias (entry point in pyproject.toml)

#### Documentation

- [x] Update README.md
- [x] Update copilot-instructions.md
- [ ] Update all docs references
- [ ] Update example commands in other docs
- [ ] Update CHANGELOG.md

#### Tests

- [x] Update test imports
- [x] Update mock patch strings referencing "Shelfr"
- [x] Verify all 2,124 tests pass

#### Config

- [x] Keep `config/config.yaml` format (no changes needed)
- [x] Keep backward compat config keys (`Shelfr_managed`, etc.)
- [ ] Update example config comments if they mention "Shelfr"

---

## Phase 2: Suite Restructure (In Progress)

> **📄 Full details moved to [CLI_ARCHITECTURE.md](cli/CLI_ARCHITECTURE.md)**

After the rebrand stabilizes, reorganize commands into a domain-focused suite.

### Summary of Changes

| Current | Future | Status |
|---------|--------|--------|
| `shelfr tools bbcode` | `shelfr mam bbcode` | ✅ Done |
| `shelfr tools mamff` | `shelfr mam ff` | 🔲 Planned |
| `shelfr libation *` | `shelfr lib *` | 🔲 Planned |
| `shelfr check` | `shelfr doctor check` | 🔲 Planned |
| `shelfr validate` | `shelfr doctor validate` | 🔲 Planned |
| (new) | `shelfr mkbrr create` | 🔲 Planned |
| (new) | `shelfr edit tui` | 🔲 Planned |

### New Sub-Apps

| Sub-App | Purpose | Implementation |
|---------|---------|----------------|
| `mkbrr` | Torrent operations | [MKBRR_WRAPPER_PLAN.md](implementation/MKBRR_WRAPPER_PLAN.md) |
| `edit` | Config editing & TUI | [TEXT_EDITOR_PLAN.md](implementation/TEXT_EDITOR_PLAN.md) |
| `meta` | Metadata operations | Future |
| `doctor` | Health & diagnostics | Future |

See [CLI_ARCHITECTURE.md](cli/CLI_ARCHITECTURE.md) for:

- Full current and planned command structure
- Sub-app details and implementation status
- Guidelines for adding new commands
- Migration path for restructuring

---

## Implementation Timeline

### Phase 1: Rebrand (✅ Complete)

1. ✅ Package rename (`Shelfr` → `shelfr`)
2. ✅ Update all imports and references
3. ✅ Documentation and README updates
4. ✅ Testing and release

### Phase 2: Restructure (In Progress)

1. ✅ Create `mam` sub-app (bbcode, render)
2. ✅ Create `edit` sub-app (all 3 tiers complete)
3. 🔲 Create `mkbrr` sub-app
4. 🔲 Rename `libation` → `lib` sub-app
5. 🔲 Create `doctor` sub-app, move diagnostics
6. 🔲 Create `meta` sub-app
7. 🔲 Add backward-compat aliases

---

## Design Principles

### Naming

- **Sub-apps are nouns** (`mam`, `lib`, `abs`, `doctor`)
- **Commands are verbs** (`run`, `scan`, `import`, `check`)
- **Short names for frequent commands** (`lib` not `libation`, `ff` not `fastfill`)
- **Descriptive help text** with full names in tooltips

### UX

- **Top-level shortcuts** for common tasks (`status`, `config`)
- **Consistent flags** across all commands (`--dry-run`, `--yes`, `--json`)
- **Rich output** with colors, emojis, and panels
- **Helpful errors** with suggestions

### Architecture

- **Lazy imports** — Heavy dependencies load only when needed
- **Shared context** — `RuntimeContext` passed through all commands
- **Modular handlers** — Each command has focused handler module

---

## Questions to Resolve

1. **`mam` sub-app name** — Is `mam` too short/cryptic? Alternatives: `upload`, `tracker`
2. **`lib` vs `libation`** — Decision made: use `lib` ✓
3. **GitHub repo rename timing** — Before or after package rename?
4. **PyPI package name** — Is `shelfr` available?

---

## Notes

- This document focuses on planning. Implementation happens in separate PRs.
- Phase 1 (rebrand) is the immediate priority.
- Phase 2 (restructure) can happen incrementally after Phase 1 stabilizes.
- Backward compatibility is important — deprecation warnings before removal.
