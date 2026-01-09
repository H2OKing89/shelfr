# Shelfr Codebase Audit

This folder contains the comprehensive codebase audit and tracks progress on improvements.

## Structure

```
docs/audit/
├── README.md                 # This file - overview and progress
├── CODEBASE_AUDIT.md        # Full audit report (source of truth)
├── issues/                   # Individual issue tracking
│   ├── architecture/         # Design pattern issues
│   ├── organization/         # Code organization issues
│   └── cleanup/              # Low-priority cleanup items
└── completed/                # Resolved issues (moved here when done)
```

## Quick Links

- [Full Audit Report](CODEBASE_AUDIT.md)
- [Architecture Issues](issues/architecture/)
- [Organization Issues](issues/organization/)
- [Cleanup Items](issues/cleanup/)

---

## Progress Dashboard

### Architecture/Design (Medium Priority)

| # | Issue | Status | PR |
|---|-------|--------|-----|
| A1 | [Tight coupling via get_settings()](issues/architecture/A1-tight-coupling.md) | 🔴 Not Started | - |
| A2 | [Long functions (>100 lines)](issues/architecture/A2-long-functions.md) | 🔴 Not Started | - |
| A3 | [Boolean blindness](issues/architecture/A3-boolean-blindness.md) | 🔴 Not Started | - |
| A4 | [Circular import guards](issues/architecture/A4-circular-imports.md) | 🔴 Not Started | - |

### Organization (Medium Priority)

| # | Issue | Status | PR |
|---|-------|--------|-----|
| O1 | [Remove cli_argparse.py](issues/organization/O1-remove-cli-argparse.md) | 🔴 Not Started | - |
| O2 | [Split config.py](issues/organization/O2-split-config.md) | 🔴 Not Started | - |
| O3 | [Centralize constants](issues/organization/O3-centralize-constants.md) | 🔴 Not Started | - |
| O4 | [Improve exception catching](issues/organization/O4-exception-catching.md) | 🔴 Not Started | - |
| O5 | [Deprecation timeline](issues/organization/O5-deprecation-timeline.md) | 🔴 Not Started | - |
| O6 | [Integration tests](issues/organization/O6-integration-tests.md) | 🔴 Not Started | - |

### Cleanup (Low Priority)

| # | Issue | Status | PR |
|---|-------|--------|-----|
| C1 | [Fix stray print() calls](issues/cleanup/C1-print-calls.md) | 🔴 Not Started | - |
| C2 | [Consolidate subprocess usage](issues/cleanup/C2-subprocess.md) | 🔴 Not Started | - |
| C3 | [Document commands/ vs cli/](issues/cleanup/C3-commands-cli-docs.md) | 🔴 Not Started | - |
| C4 | [TUI module decision](issues/cleanup/C4-tui-module.md) | 🔴 Not Started | - |
| C5 | [Split workflow.py](issues/cleanup/C5-split-workflow.md) | 🔴 Not Started | - |
| C6 | [Fix __all__ duplicate](issues/cleanup/C6-all-duplicate.md) | 🔴 Not Started | - |
| C7 | [Standardize pathlib](issues/cleanup/C7-pathlib.md) | 🔴 Not Started | - |
| C8 | [Split abs/importer.py](issues/cleanup/C8-split-importer.md) | 🔴 Not Started | - |

---

## Status Legend

- 🔴 Not Started
- 🟡 In Progress
- 🟢 Complete
- ⏸️ On Hold

---

## How to Use This

1. __Pick an issue__ from the dashboard above
2. __Read the issue file__ for context, affected files, and suggested approach
3. __Create a branch__ named `audit/{issue-id}` (e.g., `audit/O3-centralize-constants`)
4. __Make changes__ following the guidance in the issue file
5. __Update status__ in this README when complete
6. __Move issue file__ to `completed/` folder

---

## Audit Metadata

- __Audit Date__: January 8-9, 2026
- __Version Audited__: 0.3.0
- __Auditor__: GitHub Copilot
- __Last Updated__: January 9, 2026
