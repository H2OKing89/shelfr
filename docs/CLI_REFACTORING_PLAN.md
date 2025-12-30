# CLI Refactoring Plan — MAMFast

**Date**: December 2025
**Author**: Code Review Analysis
**Scope**: CLI architecture review and scalability improvements

---

## Executive Summary

The MAMFast CLI has grown to **~8,800 lines** across CLI-related modules with **42 commands**. While functional and well-organized for its current size, continued growth will create maintenance challenges. This plan addresses:

1. Current architecture assessment
2. Scalability bottlenecks
3. Proposed refactoring strategies
4. Add-on extension patterns for future features

---

## Current State Analysis

### File Size Breakdown

| File | Lines | Purpose |
| --- | --- | --- |
| `cli.py` | 1,726 | Main Typer CLI definitions (42 commands) |
| `cli_argparse.py` | 868 | Legacy argparse (tests/backwards compat) |
| `commands/__init__.py` | 86 | Re-exports all handlers |
| `commands/abs.py` | 2,131 | Audiobookshelf commands (9 handlers) |
| `commands/core.py` | 572 | Core pipeline (7 handlers) |
| `commands/diagnostics.py` | 469 | Validation/analysis (3 handlers) |
| `commands/libation.py` | 1,970 | Libation integration (12+ handlers) |
| `commands/state.py` | 273 | State management (4 handlers) |
| `commands/tools.py` | 259 | Utility tools (2 handlers) |
| `commands/utility.py` | 483 | Status/check/config (5 handlers) |
| **Total** | **8,837** | |

### Command Categories

| Category | Commands | Panel |
| --- | --- | --- |
| Core Pipeline | `scan`, `discover`, `prepare`, `metadata`, `torrent`, `upload`, `run`, `status`, `config` | Core Pipeline |
| Diagnostics | `check`, `validate`, `validate-config`, `preview-naming`, `check-duplicates`, `check-suspicious` | Diagnostics |
| State Management | `state list`, `state prune`, `state retry`, `state clear`, `state export` | State Management |
| Audiobookshelf | `abs-init`, `abs-import`, `abs-check-duplicate`, `abs-trump-check`, `abs-restore`, `abs-cleanup`, `abs-rename`, `abs-orphans`, `abs-resolve-asins` | Audiobookshelf |
| Libation | `libation scan`, `libation liberate`, `libation status`, `libation search`, `libation export`, `libation settings`, `libation books`, `libation redownload`, `libation set-status`, `libation convert`, `libation guide` | (sub-app) |
| Tools | `tools mamff`, `tools bbcode` | Tools |

---

## Issues Identified

### 1. **Monolithic CLI Definition File (1,726 lines)**

**Problem**: All 42 command definitions live in a single `cli.py` file.

**Symptoms**:

- Long scroll to find commands
- Merge conflicts when multiple developers touch CLI
- Difficult to understand command relationships
- Large import overhead at startup

**Impact**: Medium-High as project grows

### 2. **Duplicate CLI Systems**

**Problem**: Two parallel CLI implementations (`cli.py` Typer + `cli_argparse.py` argparse).

**Current Rationale**: Tests and backwards compatibility

**Impact**:

- ~2,600 lines maintaining two CLIs
- Risk of drift between them
- Double maintenance burden

### 3. **Command Handler Sprawl**

**Problem**: `commands/abs.py` (2,131 lines) and `commands/libation.py` (1,970 lines) are becoming unwieldy.

**Symptoms**:

- Multiple responsibilities per file
- Hard to test individual handlers in isolation
- Related helpers mixed with command handlers

### 4. **Tight Coupling Between CLI and Handlers**

**Problem**: `cli.py` directly imports and calls command handlers with translated args.

**Pattern**:

```python
@app.command()
def some_command(ctx: typer.Context, ...):
    from mamfast.commands import cmd_some_command
    args = get_args(ctx, ...)
    result = cmd_some_command(args)
    raise typer.Exit(result)
```

**Issues**:

- `ArgsNamespace` bridge is a legacy shim
- No clear separation between "CLI layer" and "business logic"
- Makes testing CLI independently from handlers harder

### 5. **Inconsistent Sub-App Usage**

**Problem**: `libation` and `state` use Typer sub-apps, but `abs` commands are flat with prefix naming.

**Current**:

- `mamfast state list` (sub-app ✓)
- `mamfast libation scan` (sub-app ✓)
- `mamfast abs-import` (flat with prefix ✗)
- `mamfast abs-cleanup` (flat with prefix ✗)

---

## Proposed Refactoring

### Phase 1A: Typed Runtime Context (Priority: CRITICAL)

**Goal**: Introduce a single, typed "runtime context" object before splitting files.

**Why do this first?**

The current `ArgsNamespace` bridge is a legacy shim that every command re-implements. Before splitting handler modules, establish a stable foundation that:

- Kills `ArgsNamespace` slowly without breaking everything
- Prevents "every command re-loads config / re-builds clients"
- Makes `--verbose`, `--dry-run`, `--json` consistent across all commands
- Makes testing easier (inject a fake context)

**Implementation**:

```python
# src/mamfast/cli/_context.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mamfast.abs.client import AbsClient
    from mamfast.config import Settings

@dataclass
class RuntimeContext:
    """Typed runtime context available to all commands via ctx.obj."""

    config_path: Path
    settings: Settings | None = None
    dry_run: bool = False
    verbose: bool = False
    json_output: bool = False

    # Lazy-loaded clients (initialized on first use)
    _abs_client: AbsClient | None = field(default=None, repr=False)

    @property
    def abs_client(self) -> AbsClient:
        """Get or create ABS client.

        Returns:
            Initialized ABS client (lazy-loaded on first access).

        Raises:
            ValueError: If ABS configuration is missing.
            ConnectionError: If ABS server is unreachable.
        """
        if self._abs_client is None:
            if not self.settings or not self.settings.audiobookshelf:
                raise ValueError("ABS configuration not found in settings")
            try:
                from mamfast.abs.client import AbsClient
                self._abs_client = AbsClient.from_config(self.settings.audiobookshelf)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    f"Failed to initialize ABS client: {e}"
                )
                raise
        return self._abs_client

    def close(self) -> None:
        """Cleanup resources."""
        if self._abs_client:
            self._abs_client.close()
```

**Updated callback**:

```python
@app.callback()
def main_callback(ctx: typer.Context, ...) -> None:
    from mamfast.cli._context import RuntimeContext
    from mamfast.config import reload_settings

    settings = reload_settings(config_file=config)
    ctx.obj = RuntimeContext(
        config_path=config,
        settings=settings,
        dry_run=dry_run,
        verbose=verbose,
    )
    _setup_logging(verbose, config)
```

**Commands then use**:

```python
@app.command()
def abs_import(ctx: typer.Context, ...) -> None:
    runtime: RuntimeContext = ctx.obj
    if runtime.dry_run:
        ...
    client = runtime.abs_client  # Lazy-loaded, shared
```

**Acceptance Criteria**:

- [x] `RuntimeContext` dataclass created with typed fields ✅ (Dec 2025)
- [x] `@app.callback()` initializes context once ✅ (Dec 2025)
- [x] At least one command migrated to use `ctx.obj` directly ✅ (Dec 2025)
- [x] All tests still pass ✅ (2,125 tests passing)
- [x] No user-facing CLI changes ✅

**Status**: ✅ COMPLETE (Dec 29, 2025) - Commit `d474308`

---

### Phase 1B: Split CLI Definitions (Priority: HIGH)

**Goal**: Break `cli.py` into focused modules per command category.

**Proposed Structure**:

```bash
src/mamfast/cli/
├── __init__.py          # Main app factory + entry point
├── _app.py              # App configuration, callbacks, shared types
├── _context.py          # RuntimeContext dataclass
├── _helpers.py          # get_args(), ArgsNamespace (legacy shim, deprecated)
├── core.py              # Core pipeline commands
├── diagnostics.py       # Validation/analysis commands
├── state.py             # State sub-app
├── abs.py               # ABS sub-app (promotes to sub-app!)
├── libation.py          # Libation sub-app
└── tools.py             # Tools sub-app
```

**Migration Steps**:

1. Create `src/mamfast/cli/` directory
2. Create `_context.py` with `RuntimeContext` (Phase 1A)
3. Extract `_app.py` with app factory, callbacks, shared Enums
4. Extract command definitions by category
5. Main `__init__.py` assembles the app
6. Keep `cli.py` as thin re-export for backwards compatibility

**Import Performance Rule**: CLI modules should be cheap to import. Heavy imports (httpx clients, mediainfo wrappers, ABS libs) happen **inside** command functions or in lazy-loaded properties, never at module top-level.

**Benefits**:

- Each file < 400 lines
- Focused code reviews
- Easier to locate commands
- Reduced merge conflicts

**Acceptance Criteria**:

- [x] `mamfast --help` output unchanged ✅
- [x] Command import time stays within ~200ms ✅
- [x] All tests pass ✅ (2,125 tests passing)
- [x] `cli.py` renamed to `cli_legacy.py` (package takes precedence) ✅
- [x] Each `cli/<category>.py` file < 400 lines ✅

**Status**: ✅ COMPLETE (Dec 29, 2025) - Commit `d474308`

**Files Created**:

- `cli/__init__.py` (~150 lines) - Main entry point, app assembly
- `cli/_app.py` (~290 lines) - Factories, callbacks, shared enums
- `cli/_context.py` (~150 lines) - RuntimeContext dataclass
- `cli/_helpers.py` (~50 lines) - Legacy ArgsNamespace bridge
- `cli/core.py` (~270 lines) - Pipeline commands
- `cli/diagnostics.py` (~190 lines) - Validation/check commands
- `cli/state.py` (~120 lines) - State management
- `cli/abs.py` (~365 lines) - Audiobookshelf commands
- `cli/libation.py` (~285 lines) - Libation subcommands
- `cli/tools.py` (~100 lines) - Utility tools

---

### Phase 2: Promote ABS to Sub-App (Priority: MEDIUM)

**Goal**: Consistency with `state` and `libation`.

**Before**:

```bash
mamfast abs-init
mamfast abs-import
mamfast abs-cleanup
```

**After**:

```bash
mamfast abs init
mamfast abs import
mamfast abs cleanup
mamfast abs resolve-asins
```

**Command Renames** (consider while migrating):

| Old | New | Rationale |
| --- | --- | --- |
| `abs-check-duplicate` | `abs check-asin` | It's ASIN existence lookup, not duplicate detection |
| `abs-trump-check` | `abs trump-preview` | Clearer that it's a preview |

**Global Flag Ordering**: Global flags (`--dry-run`, `--verbose`, `--config`) must continue to go **BEFORE** the subcommand:

```bash
# Old syntax (still works via aliases):
mamfast --dry-run abs-import

# New syntax (after migration):
mamfast --dry-run abs import  # Flag BEFORE subcommand

# ❌ WRONG - Flag goes before subcommand, not after:
mamfast abs import --dry-run  # This won't work
```

**Migration**:

1. Create `abs_app = typer.Typer()` sub-app
2. Move commands to sub-app
3. Add hidden aliases for old names with deprecation warning:

```python
# Hidden alias with deprecation warning
@app.command("abs-import", hidden=True)
def abs_import_deprecated(ctx: typer.Context, ...) -> None:
    """Deprecated: Use 'mamfast abs import' instead."""
    from mamfast.console import print_warning
    print_warning("Deprecated: 'abs-import' is now 'abs import'. Update your scripts.")
    return _abs_import_impl(ctx, ...)
```

1. Update docs and tests
2. Remove aliases after 2 releases

**Acceptance Criteria**:

- [x] All ABS commands work under `abs <verb>` syntax ✅ (Dec 2025)
- [x] Old `abs-*` commands still work (hidden, with warning) ✅ (Dec 2025)
- [x] `mamfast abs --help` shows all ABS subcommands ✅ (Dec 2025)
- [x] Global flags remain BEFORE subcommand (e.g., `mamfast --dry-run abs import`) ✅
- [x] Tests updated to use new syntax and verify flag ordering ✅ (Dec 2025)
- [x] Documentation and examples updated with correct flag placement ✅ (Dec 2025)

**Status**: ✅ COMPLETE (Dec 29, 2025)

**Changes Made**:

- `cli/_app.py`: Added `make_abs_app()` factory function
- `cli/__init__.py`: Creates and registers `abs_app` as sub-app
- `cli/abs.py`: Refactored to use sub-app pattern with new command names:
  - `init`, `import`, `check-asin`, `trump-preview`, `restore`, `cleanup`, `rename`, `orphans`, `resolve-asins`
- Added `register_abs_deprecated_aliases()` for backward compatibility:
  - Old commands (`abs-init`, `abs-import`, `abs-check-duplicate`, etc.) are hidden but functional
  - Deprecation warnings printed when using old syntax
- Command renames applied:
  - `abs-check-duplicate` → `abs check-asin`
  - `abs-trump-check` → `abs trump-preview`
- `tests/test_cli_typer.py`: Updated to use new syntax, added deprecated alias tests, flag ordering test
- `README.md`: Updated examples to use new `abs <verb>` syntax
- All 2,132 tests pass

---

### Phase 3: Deprecate argparse CLI (Priority: LOW)

**Goal**: Eliminate dual-CLI maintenance.

**⚠️ Before removing, audit actual usage**:

Hidden dependencies often include:

- Shell scripts / cron jobs
- CI tooling calling `python -m mamfast.cli_argparse ...`
- Undocumented user workflows
- Test fixtures

**Discovery Steps**:

1. Add usage tracking (log when argparse entrypoint runs):

   ```python
   # cli_argparse.py - add at entry
   import logging
   logging.getLogger("mamfast.deprecation").warning(
       "argparse CLI is deprecated; migrate to 'mamfast' command"
   )
   ```

2. Grep repo + docs + known scripts for `cli_argparse` references
3. Check if any tests *require* argparse vs just *use* it

**Recommended Strategy: Freeze as Compat Mode**:

Rather than maintain parity:

1. Freeze argparse CLI — no new features added
2. It calls into the *same* service layer (handlers)
3. Document as "deprecated; removed in vX.Y"
4. Add deprecation banner on every run

```python
# cli_argparse.py entry point
def main():
    console.print("[yellow]⚠️ argparse CLI is deprecated. Use 'mamfast' instead.[/]")
    console.print("[dim]This interface will be removed in v2.0[/]\n")
    # ... existing logic
```

**Acceptance Criteria**:

- [ ] Usage audit completed (document findings)
- [ ] Deprecation warning added to argparse entry point
- [ ] All tests migrated to Typer's `CliRunner` OR explicitly marked as argparse-compat tests
- [ ] Timeline documented (remove in vX.Y)

---

### Phase 4: Command Handler Refactoring (Priority: MEDIUM)

**Goal**: Break up large handler files.

**For `commands/abs.py` (2,131 lines)**:

```tree
commands/abs/
├── __init__.py        # Re-exports
├── import_.py         # cmd_abs_import + helpers
├── cleanup.py         # cmd_abs_cleanup + helpers
├── trump.py           # cmd_abs_trump_check + helpers
├── orphans.py         # cmd_abs_orphans
├── rename.py          # cmd_abs_rename
└── resolve.py         # cmd_abs_resolve_asins
```

**For `commands/libation.py` (1,970 lines)**:

```tree
commands/libation/
├── __init__.py        # Re-exports
├── core.py            # scan, liberate, status
├── search.py          # search, books
├── export_.py         # export
├── management.py      # redownload, set-status, convert
└── guide.py           # guide command + help text
```

---

## Add-On Extension Pattern

### Plugin Architecture (Future)

For truly extensible CLI, consider a plugin system:

```python
# src/mamfast/cli/plugins.py
from importlib.metadata import entry_points

def load_plugins(app: typer.Typer) -> None:
    """Load CLI plugins from entry points."""
    eps = entry_points(group="mamfast.cli.plugins")
    for ep in eps:
        try:
            plugin_app = ep.load()
            app.add_typer(plugin_app, name=ep.name)
        except Exception as e:
            # Safe loading: skip broken plugins, show errors
            import logging
            logging.getLogger("mamfast.plugins").warning(
                f"Failed to load plugin '{ep.name}': {e}"
            )
```

**Plugin Guardrails** (add when implementing):

1. **Discovery command**: `mamfast plugins list` — shows loaded plugins and status
2. **Safe loading**: Skip broken plugins, log errors, don't break `--help`
3. **Config allowlist** (optional):

   ```yaml
   # config.yaml
   plugins:
     enabled:
       - hardcover
       - mam-search
     # Unlisted plugins are ignored
   ```

**Plugin Example** (in separate package):

```python
# mamfast-hardcover/src/mamfast_hardcover/cli.py
import typer

hardcover_app = typer.Typer(name="hardcover", help="Hardcover.app integration")

@hardcover_app.command("search")
def hardcover_search(query: str) -> None:
    """Search Hardcover.app for books."""
    ...
```

**Registration** (in plugin's pyproject.toml):

```toml
[project.entry-points."mamfast.cli.plugins"]
hardcover = "mamfast_hardcover.cli:hardcover_app"
```

### Near-Term Add-On Patterns

Without full plugins, use consistent patterns for new features:

#### Pattern A: New Sub-App

```python
# src/mamfast/cli/hardcover.py
import typer

hardcover_app = typer.Typer(
    name="hardcover",
    help="📚 Hardcover.app integration",
    rich_markup_mode="rich",
    no_args_is_help=True,
)

@hardcover_app.command("search")
def search(query: str) -> None:
    ...

@hardcover_app.command("match")
def match(asin: str) -> None:
    ...
```

Then in `cli/__init__.py`:

```python
from mamfast.cli.hardcover import hardcover_app
app.add_typer(hardcover_app, name="hardcover", rich_help_panel="Integrations")
```

#### Pattern B: Feature Flag Gated Commands

```python
# For experimental features
@app.command("experimental-feature", hidden=True)
def experimental_feature() -> None:
    """Experimental: New feature in development."""
    ...
```

---

## CLI UX Polish (Quick Wins)

These improvements can be done alongside or after the refactor:

### Global Options Consistency

| Option | Meaning | Notes |
| --- | --- | --- |
| `--dry-run` | No side effects | Global flag, all commands respect it |
| `--yes` / `-y` | Skip confirmation prompts | For automation/CI |
| `--json` / `-j` | JSON output | For scripting, where applicable |
| `--verbose` / `-v` | Debug logging | Already exists |

### Command Aliases

| Alias | Target | Rationale |
| --- | --- | --- |
| `mamfast doctor` | `mamfast check` | Intuitive for users |
| `mamfast dupes` | `mamfast check-duplicates` | Shorter (already exists as hidden) |
| `mamfast lint` | `mamfast validate-config` | Developer familiarity |

### Missing `--yes` Flag

Add to commands that prompt for confirmation:

- `mamfast libation liberate`
- `mamfast state clear`
- `mamfast abs cleanup --cleanup-all`

---

## Recommended Implementation Order

### Immediate (Next Sprint)

1. **Phase 1A: RuntimeContext** — Foundation for everything else
2. **Phase 1B: Split `cli.py`** into `cli/` package — HIGH impact, low risk

### Short-Term (1-2 Sprints)

1. **Phase 2: Promote ABS to sub-app** — Consistency improvement
2. **CLI UX Polish** — Add `--yes`, aliases, etc.

### Medium-Term (2-3 Sprints)

1. **Phase 4: Split large handlers** — `abs.py` and `libation.py`
2. **Phase 3: Audit argparse** — Determine if deprecation is feasible

### Long-Term (Future)

1. **Plugin architecture** — If external integrations needed
2. **Config-driven commands** — Enable/disable features via config

---

## New Feature Checklist

When adding a new command:

### Pre-Implementation

- [ ] Determine category (Core, ABS, Libation, Tools, or new sub-app?)
- [ ] Check if related command exists to extend
- [ ] Review naming consistency (`mamfast <noun> <verb>` vs `mamfast <verb>-<noun>`)

### Implementation

- [ ] Add to appropriate `cli/<category>.py` file
- [ ] Add handler in `commands/<category>.py`
- [ ] Use `RuntimeContext` from `ctx.obj` (not legacy `ArgsNamespace`)
- [ ] Use `rich_help_panel` for help organization
- [ ] Add `--dry-run` support if command makes changes
- [ ] Add `--yes` / `-y` if command prompts for confirmation
- [ ] Add `--json` output if produces structured data
- [ ] Use `AsinArg` type for ASIN arguments
- [ ] Include examples in docstring
- [ ] Use emojis consistently (one emoji prefix per command)
- [ ] Keep imports lightweight (heavy imports inside function body)

### Documentation

- [ ] Update README if user-facing
- [ ] Add to CLI_AUDIT_REPORT.md command table
- [ ] Update CHANGELOG.md

### Testing

- [ ] Add unit tests for handler
- [ ] Add CLI integration test using `CliRunner`
- [ ] Test `--help` output
- [ ] Test `--dry-run` behavior (if applicable)

---

## Appendix A: Command Naming Conventions

### Current Conventions

| Pattern | Example | Notes |
| --- | --- | --- |
| Single verb | `scan`, `discover`, `run` | Core pipeline |
| Noun-verb (sub-app) | `state list`, `libation scan` | Grouped features |
| Prefix-verb | `abs-import`, `abs-cleanup` | Should migrate to sub-app |
| Verb-noun | `check-duplicates`, `validate-config` | Diagnostic actions |

### Recommended Convention

```bash
mamfast <noun> <verb>      # For grouped features (sub-apps)
mamfast <verb>             # For core pipeline single actions
mamfast <verb>-<modifier>  # For variants (check-duplicates)
```

---

## Appendix B: Potential Future Commands

Based on project direction, these might be added:

| Command | Category | Purpose |
| --- | --- | --- |
| `mamfast hardcover search` | New sub-app | Search Hardcover.app |
| `mamfast hardcover match` | New sub-app | Match ASIN to Hardcover ID |
| `mamfast hardcover enrich` | New sub-app | Pull Hardcover metadata |
| `mamfast mam search` | New sub-app | Search MAM for existing uploads |
| `mamfast mam check-dup` | New sub-app | Check if release exists on MAM |
| `mamfast tools mediainfo` | Tools | Extract MediaInfo JSON |
| `mamfast tools asin-lookup` | Tools | Lookup ASIN metadata |
| `mamfast batch import` | Core | Batch import from file list |
| `mamfast watch` | Core | Watch directory for new files |

---

## Summary

The MAMFast CLI is well-designed but reaching a size where proactive refactoring will pay dividends. The key recommendations:

1. **Add RuntimeContext first** — Foundation that makes everything else easier
2. **Split `cli.py` now** — Prevents further growth pain
3. **Standardize on sub-apps** — Promote `abs-*` commands to `abs <verb>`
4. **Plan for plugins** — Future-proof architecture with guardrails
5. **Maintain consistency** — Follow checklist for new commands

Total estimated effort: ~2-3 sprints for Phase 1A-2, minimal disruption to users with deprecation aliases.

---

## Appendix C: Quick Reference

### Import Performance Rule

Distinguish between **type-only imports** and **runtime imports**:

```python
# ✅ GOOD - Type-only imports at module level (guarded by TYPE_CHECKING)
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mamfast.abs.client import AbsClient  # Type annotation only

@app.command()
def my_command(ctx: typer.Context) -> None:
    # Heavy runtime import happens inside function
    from mamfast.abs.client import AbsClient
    client = AbsClient(...)

# ❌ BAD - Heavy runtime import at module level
from mamfast.abs.client import AbsClient  # Imported even if command never runs
from httpx import Client  # Slow startup

@app.command()
def my_command():
    client = AbsClient(...)  # Already imported, but could have failed earlier
```

**Rule**: Type-only imports may use `TYPE_CHECKING` guard at module level; all heavy runtime imports must defer to inside command functions or lazy-loaded properties.

### RuntimeContext Usage

```python
# ✅ Preferred pattern after Phase 1A
@app.command()
def abs_import(ctx: typer.Context, ...) -> None:
    from mamfast.cli._context import RuntimeContext
    runtime: RuntimeContext = ctx.obj

    if runtime.dry_run:
        print_dry_run("Would import...")
        return

    client = runtime.abs_client  # Lazy-loaded, shared
    ...
```

### Deprecation Warning Pattern

```python
# For deprecated command aliases
@app.command("old-name", hidden=True)
def old_name_deprecated(ctx: typer.Context) -> None:
    from mamfast.console import print_warning
    print_warning(
        "Deprecated: 'mamfast old-name' is now 'mamfast new name'. "
        "This alias will be removed in v2.0."
    )
    return new_name_impl(ctx)
```
