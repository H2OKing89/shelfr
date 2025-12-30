# shelfr Documentation

Complete technical documentation, implementation plans, and reference materials for the shelfr project.

## 🚀 Quick Navigation

### 📌 Where Am I?

| Question | Answer |
| --- | --- |
| **What are we building?** | Start with main [README](../README.md) in project root |
| **What's the current focus?** | See [implementation/README.md](implementation/README.md) — active work tracker |
| **How does the CLI work?** | Check [cli/README.md](cli/README.md) |
| **I need to know about...** | See folder guide below |

## 📁 Folder Organization

### 🔨 [cli/](cli/) — CLI Architecture & Refactoring

**Status**: ✅ COMPLETE
**6-phase refactoring** with 2,132 passing tests.

- [cli/README.md](cli/README.md) — Overview & quick start
- [cli/REFACTORING_PLAN.md](cli/REFACTORING_PLAN.md) — Architecture & phases
- [cli/AUDIT_REPORT.md](cli/AUDIT_REPORT.md) — Test results & usage findings
- [cli/AUDIT_VERIFICATION.md](cli/AUDIT_VERIFICATION.md) — Detailed evidence

### 📋 [implementation/](implementation/) — Active Plans & Backlog

**Status**: 📊 IN PROGRESS (P1+ phases)
**What we're doing next** — see priority matrix in README.

- [implementation/README.md](implementation/README.md) — Priority dashboard
- [implementation/IMPROVEMENTS_PLAN.md](implementation/IMPROVEMENTS_PLAN.md) — P1+ feature roadmap
- [implementation/VALIDATION_PLAN.md](implementation/VALIDATION_PLAN.md) — Input validation (P1)
- [implementation/STATE_HARDENING_PLAN.md](implementation/STATE_HARDENING_PLAN.md) — State mgmt (P1)
- [implementation/PACKAGE_UPGRADE_PLAN.md](implementation/PACKAGE_UPGRADE_PLAN.md) — Dependencies (P2)
- [implementation/MIGRATION_BACKLOG.md](implementation/MIGRATION_BACKLOG.md) — Deferred work (P2+)

### 📖 [libation/](libation/) — Libation Integration

**Status**: ✅ OPERATIONAL
**CLI wrapper & discovery pipeline** working.

- [libation/README.md](libation/README.md) — Overview
- [libation/CLI.md](libation/CLI.md) — Command reference
- [libation/WRAPPER_REVIEW.md](libation/WRAPPER_REVIEW.md) — Implementation notes

### 📚 [reference/](reference/) — Static Reference Materials

**Status**: STABLE
**APIs, naming systems, troubleshooting** — rarely edited.

- [reference/README.md](reference/README.md) — Quick index
- [reference/naming/](reference/naming/) — File naming rules, edge cases, golden tests
- [reference/audiobookshelf/](reference/audiobookshelf/) — ABS API & workflows
- [reference/audnex/](reference/audnex/) — Audnex API schemas
- [reference/hardcover/](reference/hardcover/) — Hardcover GraphQL reference
- [reference/mam/](reference/mam/) — MAM torrent system
- [reference/tracking/](reference/tracking/) — Issue tracking (if present)

### 📦 [archive/](archive/) — Completed Work

**Status**: FROZEN
**P0 completed implementations** — reference only.

- [archive/README.md](archive/README.md) — Index & reading guide

- `P0_UPGRADE_COMPLETE.md` — Package upgrades (tenacity, platformdirs)
- `P1_SH_LIBRARY_COMPLETE.md` — sh library integration
- `REFACTORING_SUMMARY.md` — P3 file splits (cli.py, naming.py)
- `PRODUCTION_SAFETY_IMPROVEMENTS.md` — Safety enhancements

---

## 🎯 Workflows

### "I want to start a new feature"

1. Check [implementation/README.md](implementation/README.md) for priority
2. Pick a plan file (VALIDATION_PLAN, STATE_HARDENING_PLAN, etc.)
3. Review acceptance criteria & blockers
4. Start implementing; link PRs here

### "I need to understand the naming system"

→ [reference/naming/](reference/naming/)

### "How does ABS import work?"

→ [reference/audiobookshelf/](reference/audiobookshelf/)

### "What's in the backlog?"

→ [implementation/MIGRATION_BACKLOG.md](implementation/MIGRATION_BACKLOG.md)

### "Is the CLI refactoring done?"

→ [cli/README.md](cli/README.md) — Yes, see audit verification

---

## 🔍 Tools

### Check for broken markdown links

```bash
python3 scripts/check_md_links.py
```

### Reorganize docs (git history preserved)

```bash
./scripts/refactor_docs.sh
```

---

## 📊 Status Dashboard

| Component | Status | Phase | Docs |
| --- | --- | --- | --- |
| CLI Refactoring | ✅ COMPLETE | P0 | [cli/README.md](cli/README.md) |
| Input Validation | 📋 PLANNED | P1 | [implementation/VALIDATION_PLAN.md](implementation/VALIDATION_PLAN.md) |
| State Hardening | 📋 PLANNED | P1 | [implementation/STATE_HARDENING_PLAN.md](implementation/STATE_HARDENING_PLAN.md) |
| Package Upgrades | ⏳ BACKLOG | P2 | [implementation/PACKAGE_UPGRADE_PLAN.md](implementation/PACKAGE_UPGRADE_PLAN.md) |
| Subprocess Migration | ⏸️ DEFERRED | P2+ | [implementation/MIGRATION_BACKLOG.md](implementation/MIGRATION_BACKLOG.md) |

---

**Last Updated**: December 30, 2025
**Maintained By**: shelfr Team
