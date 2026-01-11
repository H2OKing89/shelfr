# Codebase Audit Report

**Date**: January 8, 2026
**Version Audited**: 0.3.0
**Auditor**: GitHub Copilot

---

## Executive Summary

The shelfr codebase is **well-architected** for a complex audiobook automation tool. It follows modern Python standards (3.11+, strict typing, Pydantic v2) and has good separation of concerns. The main issues identified are organizational (oversized modules, duplicate patterns, deprecated code) rather than fundamental design flaws.

**Overall Assessment**: ✅ Production-ready with recommended improvements

---

## ✅ Things Done Well

### 1. Modern Python Standards

- Properly uses `from __future__ import annotations` throughout
- Python 3.11+ with strict typing (`py.typed` marker present)
- Pydantic v2 for schema validation
- `pathlib.Path` used consistently instead of string paths

### 2. Well-Organized Package Structure

```
src/shelfr/
├── abs/          # Audiobookshelf integration
├── cli/          # Typer-based CLI
├── commands/     # Command implementations
├── metadata/     # Metadata providers & aggregation
├── schemas/      # Pydantic validation schemas
├── ui/           # Rich console components
├── utils/        # Shared utilities
└── tui/          # Optional TUI (textual)
```

- Clear separation of concerns
- Provider pattern for metadata sources (`metadata/providers/`)
- Dedicated exception hierarchy in `exceptions.py`

### 3. Excellent Exception Design

The exception hierarchy in `src/shelfr/exceptions.py` is comprehensive and well-documented:

```
ShelfrError (base)
├── ConfigurationError
├── ValidationError
│   ├── DiscoveryValidationError
│   └── PreUploadValidationError
├── PipelineError
│   ├── StagingError
│   ├── MetadataError
│   ├── TorrentError
│   └── UploadError
├── NetworkError
│   ├── AudnexError
│   ├── QBittorrentError
│   └── AudiobookshelfError
├── StateError
│   ├── StateLockError
│   └── StateCorruptionError
└── ExternalToolError
    ├── DockerError
    ├── MkbrrError
    └── LibationError
```

Each exception includes:

- Typed `details` dict for structured logging
- Clear docstrings explaining use cases
- Proper inheritance chain

### 4. CLI Implementation

- Modern Typer-based CLI with Rich integration
- Proper sub-app organization (`state`, `abs`, `libation`, `tools`, `mam`, `edit`, `mkbrr`, `audnex`)
- Global flags (`--dry-run`, `--verbose`, `--config`) handled correctly at app level
- Beautiful help output with Rich panels

### 5. Testing & Tooling

| Metric | Value |
| -------- | ------- |
| Test files | 67 |
| Source modules | 138 |
| File coverage ratio | ~49% |

Pre-commit configuration includes:

- ruff (linting + formatting)
- mypy (strict type checking)
- bandit (security scanning)
- markdownlint
- shellcheck
- pytest

Standard `Makefile` with:

- `make test` - Run pytest
- `make lint` - Run pre-commit
- `make fmt` - Format code
- `make dev` - Install with dev deps
- `make release-*` - Version bumping

### 6. Configuration Management

- Layered precedence: `config.yaml` > `.env` > defaults
- Pydantic schemas for validation (`schemas/config.py`)
- Separate `env_settings.py` for secrets (QB credentials, API keys)
- Comprehensive validation with helpful error messages

---

## ⚠️ Issues & Recommendations

### 1. Deprecated Module Still Present

**File**: `src/shelfr/cli_argparse.py` (787 lines)

**Problem**: The legacy argparse CLI is deprecated but still in the source tree:

```python
"""⚠ DEPRECATED: This module is deprecated and will be removed in v2.0.
Use the Typer-based CLI via `Shelfr` command instead.
"""
```

It's also re-exported from `cli/__init__.py` for backward compatibility.

**Recommendation**:

- Move to `src/shelfr/_deprecated/cli_argparse.py`
- Or remove entirely and document migration path in CHANGELOG
- Set a concrete removal date (not just "v2.0")

**Priority**: Medium

---

### 2. Massive Config Module

**File**: `src/shelfr/config.py` (1518 lines)

**Problem**: Single file handles too many responsibilities:

- 15+ `@dataclass` definitions
- File loading logic
- YAML parsing
- Builder functions (`build_trump_prefs`, `build_cleanup_prefs`)
- Global singleton management
- Validation helpers

**Recommendation**: Split into multiple modules:

```
src/shelfr/config/
├── __init__.py          # Re-exports for backward compat
├── dataclasses.py       # PathsConfig, MamConfig, etc.
├── loader.py            # load_settings(), YAML parsing
├── builders.py          # build_trump_prefs(), build_cleanup_prefs()
├── settings.py          # Global get_settings() singleton
└── validation.py        # validate_settings(), path checks
```

**Priority**: Medium

---

### 3. Global State Pattern Overuse

**Problem**: Multiple modules use mutable global singletons:

```python
# config.py
_settings: Settings | None = None

# qbittorrent.py
_client: qbittorrentapi.Client | None = None

# metadata/cache.py
_default_cache = None

# metadata/audnex/region_cache.py
_default_cache = None
```

This makes testing harder and can cause issues with module reloading.

**Recommendation**:

- Consider dependency injection for major components
- Use context managers where appropriate
- Ensure ALL globals have corresponding `clear_*()` functions
- Document global state in module docstrings

**Priority**: Low (functional but not ideal)

---

### 4. Inconsistent Command Module Structure

**Problem**: Two parallel systems for CLI commands:

1. `src/shelfr/commands/` - Handler implementations (business logic)
2. `src/shelfr/cli/` - Typer command registration (CLI glue)

This creates confusion about where to add new functionality.

**Recommendation**: Consolidate to one clear pattern:

**Option A**: Keep separation (recommended for large CLIs)

```
cli/           # Thin Typer wrappers, argument parsing only
commands/      # Pure business logic, no CLI imports
```

**Option B**: Merge into cli/

```
cli/
├── abs.py     # Both registration AND implementation
├── libation.py
└── ...
```

Document the chosen pattern in `CONTRIBUTING.md`.

**Priority**: Low

---

### 5. Stray `print()` Calls in Source

**Problem**: Project guidelines require using `shelfr.console` Rich helpers, but violations exist:

```python
# src/shelfr/metadata/orchestration.py:280
print(f"Title: {result.fields.get('title')}")

# src/shelfr/metadata/orchestration.py:317
print(f"Wrote: {files['json']}")

# src/shelfr/metadata/aggregator.py:88-89
print(f"Title: {result.fields.get('title')}")
print(f"From: {result.sources.get('title')}")
```

**Recommendation**:

- Replace with `console.print()` or `logger.debug()`
- Add ruff rule to flag bare `print()` calls in `src/`
- Consider a pre-commit hook to catch these

**Priority**: Low

---

### 6. Mixed subprocess and `sh` Library Usage

**Problem**: Some modules use raw `subprocess.run()`:

- `src/shelfr/validation.py`
- `src/shelfr/libation.py`
- `src/shelfr/abs/trumping.py`
- `src/shelfr/abs/asin.py`
- `src/shelfr/metadata/mediainfo/extractor.py`
- `src/shelfr/wizard.py`
- `src/shelfr/utils/editor.py`

While `src/shelfr/utils/cmd.py` provides a cleaner `sh`-based wrapper with better error handling.

**Recommendation**:

- Standardize on `utils.cmd.run()` for external commands
- Keep `subprocess` only where `sh` doesn't fit (e.g., shell=True requirements)
- Document the choice in code style guide

**Priority**: Low

---

### 7. Duplicate Constant Definitions

**Problem**: Same constants defined in multiple places:

```python
# src/shelfr/config.py
VALID_AUDNEX_REGIONS = frozenset(["us", "uk", "au", "ca", "de", "es", "fr", "in", "it", "jp"])
DEFAULT_ASIN_REGION = "us"

# src/shelfr/schemas/config.py
VALID_AUDNEX_REGIONS = frozenset(["us", "uk", "au", "ca", "de", "es", "fr", "in", "it", "jp"])
DEFAULT_ASIN_REGION = "us"
```

Comments say "must match" but nothing enforces this.

**Recommendation**:

- Create `src/shelfr/constants.py` for shared values
- Import from single source of truth
- Or use schema constants and import into config

**Priority**: Medium

---

### 8. `__all__` Has Duplicate Entry

**File**: `src/shelfr/__init__.py`

```python
__all__ = [
    "__version__",
    # Base exception
    "ShelfrError",
    "ShelfrError",  # Deprecated alias for backward compatibility
    ...
]
```

**Recommendation**: Remove duplicate. The comment about "deprecated alias" doesn't make sense for an `__all__` list.

**Priority**: Low (cosmetic)

---

### 9. TUI Module is Incomplete

**Files**: `src/shelfr/tui/` (only `__init__.py` and `app.py`)

**Problem**:

- Listed as optional dependency (`[tui]` extra)
- Coverage explicitly excluded in `pyproject.toml`
- mypy errors ignored for these files
- Import guards are complex due to optional deps

**Recommendation**:

- Either complete the TUI feature
- Or extract to separate package (`shelfr-tui`)
- Or remove if not planned for completion

**Priority**: Low

---

### 10. Large Workflow Module

**File**: `src/shelfr/workflow.py` (1223 lines)

**Problem**: Single file orchestrates entire pipeline with:

- Progress reporting classes
- Pipeline stages
- Stage execution logic
- Result aggregation

**Recommendation**: Split into focused modules:

```
src/shelfr/workflow/
├── __init__.py      # Re-exports
├── pipeline.py      # run_pipeline(), PipelineConfig
├── stages.py        # Individual stage functions
├── progress.py      # ProgressStage, ProgressInfo, callbacks
└── results.py       # ProcessingResult aggregation
```

**Priority**: Low

---

## 🔎 Extended Audit Findings

*Additional findings from deeper code analysis.*

---

### 11. Multiple Very Large Modules

**Analysis**: Line count analysis reveals several modules exceeding 1000+ lines:

| Module | Lines | Responsibility |
| -------- | ------- | ---------------- |
| `abs/importer.py` | 2193 | ABS import logic |
| `validation.py` | 1806 | Health checks + validation |
| `config.py` | 1517 | Configuration (already noted) |
| `mkbrr.py` | 1383 | Torrent creation |
| `abs/asin.py` | 1247 | ASIN resolution |
| `workflow.py` | 1222 | Pipeline orchestration |
| `abs/rename.py` | 1114 | ABS rename logic |
| `abs/trumping.py` | 901 | Trump decision logic |
| `utils/state.py` | 894 | State management |

**Recommendation**: Consider splitting modules >1000 lines into sub-packages. The `abs/` directory in particular could benefit from reorganization:

```
abs/
├── importer/
│   ├── __init__.py
│   ├── core.py          # Main import logic
│   ├── duplicates.py    # Duplicate detection
│   └── batch.py         # Batch import async
├── asin/
│   ├── __init__.py
│   ├── extraction.py    # ASIN extraction
│   ├── resolution.py    # Region resolution
│   └── index.py         # ASIN indexing
└── ...
```

**Priority**: Low (refactoring, no functional issues)

---

### 12. Broad Exception Catching

**Problem**: Many command handlers use bare `except Exception`:

```python
# src/shelfr/commands/libation/core.py:210
except Exception as e:
    print_error(f"Failed to scan library: {e}")
    return 1
```

Found in 20+ locations across `commands/`, particularly in:

- `commands/libation/core.py` (4 occurrences)
- `commands/utility.py` (3 occurrences)
- `commands/abs/import_.py`

**Recommendation**:

- Catch specific exceptions from the exception hierarchy
- Use `except ShelfrError as e:` for expected errors
- Log full traceback at DEBUG level for unexpected errors

```python
# Better pattern:
except (ConfigurationError, ValidationError) as e:
    print_error(str(e))
    return 1
except ShelfrError as e:
    print_error(f"Unexpected error: {e}")
    logger.exception("Full traceback:")
    return 1
```

**Priority**: Medium

---

### 13. Mixed `os.path` and `pathlib` Usage

**Problem**: While `pathlib.Path` is the standard, some modules still use `os.path`:

```python
# src/shelfr/abs/metadata_builder.py
if temp_path and os.path.exists(temp_path):
    os.remove(temp_path)

# src/shelfr/utils/paths.py
abs_path = os.path.abspath(path_str)
return os.path.exists(str(path))
```

**Recommendation**: Standardize on `pathlib.Path` operations:

- `path.exists()` instead of `os.path.exists()`
- `path.resolve()` instead of `os.path.abspath()`
- `path.unlink()` instead of `os.remove()`

**Priority**: Low

---

### 14. ASIN Validation Duplication

**Problem**: ASIN validation regex is defined in multiple places:

```python
# src/shelfr/discovery.py
ASIN_VALID_PATTERN = re.compile(r"^(?:B[0-9A-Z]{9}|[0-9]{10})$")

# src/shelfr/validation.py
ASIN_VALID_PATTERN = re.compile(r"^(?:B[0-9A-Z]{9}|[0-9]{10})$")
```

Also duplicated in `abs/asin.py` and `utils/validation.py`.

**Recommendation**: Centralize in `src/shelfr/constants.py` or `utils/validation.py` and import everywhere.

**Priority**: Medium

---

### 15. Deprecated Code Accumulation

**Problem**: Multiple deprecated items still in codebase:

| Location | Item | Status |
| ---------- | ------ | -------- |
| `cli_argparse.py` | Entire module | "Removed in v2.0" |
| `cli/_helpers.py` | `ArgsNamespace`, `get_args()` | Deprecated |
| `metadata/formatting/html.py` | `_clean_html()` | Deprecated |
| `metadata/orchestration.py` | `region` parameter | Deprecated |
| `schemas/config.py` | `filters.remove_phrases` | Deprecated |

**Recommendation**: Create a deprecation timeline document and enforce removal in CI:

```python
# Add to deprecated items:
import warnings
warnings.warn(
    "ArgsNamespace is deprecated, use RuntimeContext",
    DeprecationWarning,
    stacklevel=2,
)
```

**Priority**: Medium

---

### 16. Missing Integration Tests

**Problem**: Test markers show limited integration testing:

- Only 6 `@pytest.mark.skipif` tests found
- No `@pytest.mark.integration` markers in use
- No `@pytest.mark.slow` markers in use (despite being defined in pytest config)

Key untested integration paths:

- qBittorrent upload flow
- Full ABS import pipeline
- Docker/mkbrr torrent creation
- Libation CLI wrapper

**Recommendation**:

- Add integration test suite with proper markers
- Use `pytest.mark.integration` for tests requiring external services
- Document test setup in `tests/README.md`

**Priority**: Medium

---

### 17. Async/Sync Bridge Pattern

**Problem**: Several locations use `asyncio.run()` to call async code from sync context:

```python
# src/shelfr/workflow.py:254
return asyncio.run(_fetch_hardcover_data_async(asin, title, author))

# src/shelfr/commands/abs/import_.py:362
result, prefetch_summary = asyncio.run(import_batch_async(**import_kwargs))
```

This is fine for CLI entry points but can cause issues if called from async context.

**Recommendation**:

- Document that these functions must only be called from sync context
- Consider providing both sync and async versions of key APIs
- Use `anyio` or similar for context-aware execution

**Priority**: Low

---

### 18. Naming Module Sub-Package is Well-Structured

**Positive Finding**: The `utils/naming/` sub-package is an example of good organization:

```
utils/naming/
├── __init__.py         # Re-exports all public API
├── authors.py          # Author role detection
├── constants.py        # Shared constants
├── filters.py          # Title/series filtering
├── mam_paths.py        # MAM path building
├── normalization.py    # Audnex normalization
├── series_parsing.py   # Series extraction
├── string_utils.py     # String helpers
└── volume_parsing.py   # Volume number parsing
```

This pattern should be applied to other large modules like `config.py` and `abs/importer.py`.

---

### 19. Circuit Breaker Implementation

**Positive Finding**: The `utils/circuit_breaker.py` implements a proper circuit breaker pattern for external services. This is a mature pattern used for Audnex API calls.

However, it's only used for Audnex. Consider extending to:

- qBittorrent API
- Audiobookshelf API
- Hardcover API

---

### 20. Metadata Provider Architecture

**Positive Finding**: The `metadata/providers/` package implements a clean plugin architecture:

- `MetadataProvider` protocol for type-safe interfaces
- `ProviderRegistry` for dynamic provider management
- `ProviderResult` for standardized results

This is extensible and well-designed.

---

## 🏗️ Architecture & Design Pattern Analysis

*This section evaluates whether things are designed well, not just organized.*

---

### Design Pattern: Tight Coupling via Global Settings

**What is it?** When functions grab global settings directly using `get_settings()` inside their body instead of receiving settings as a parameter.

**Why it matters**: Makes testing hard (can't easily substitute mock settings) and hides dependencies.

**Found in 70+ locations**, including:

| File | Occurrences | Severity |
| ---- | ----------- | -------- |
| `workflow.py` | 7 | High |
| `abs/importer.py` | 7 | High |
| `mkbrr.py` | 6 | High |
| `qbittorrent.py` | 6 | High |
| `hardlinker.py` | 5 | Medium |
| `sanitize.py` | 4 | Medium |

**Better approach**: Pass settings (or specific config sections) as parameters:

```python
# ❌ Current (tight coupling)
def upload_torrent(torrent_path: Path) -> bool:
    settings = get_settings()
    client = connect(settings.qbittorrent.host)
    ...

# ✅ Better (dependency injection)
def upload_torrent(torrent_path: Path, config: QBittorrentConfig) -> bool:
    client = connect(config.host)
    ...
```

**Priority**: Medium

---

### Design Pattern: Long Functions

**What is it?** Functions that do too many things (over 100 lines), making them hard to test, understand, and modify.

**Found**:

| File | Function | Lines | What It Does |
| ---- | -------- | ----- | ------------ |
| `commands/abs/import_.py` | `cmd_abs_import()` | 270 | Everything! Validate, discover, import, cleanup, report |
| `cli/abs.py` | `cmd_abs_trump_check()` | 235 | Parse args, fetch, compare, display, decide |
| `workflow.py` | `run_pipeline()` | 189 | Entire pipeline orchestration |
| `commands/libation/core.py` | `cmd_libation_liberate()` | 179 | Container management + scanning |
| `abs/importer.py` | `import_batch_async()` | 169 | Batch import logic |

**Better approach**: Extract into smaller, focused functions:

```python
# ❌ Current: 270-line function
def cmd_abs_import(ctx: Context, library_id: str, ...) -> int:
    # validation logic (50 lines)
    # discovery logic (40 lines)
    # import logic (100 lines)
    # cleanup logic (30 lines)
    # reporting logic (50 lines)

# ✅ Better: Compose small functions
def cmd_abs_import(ctx: Context, library_id: str, ...) -> int:
    config = _validate_import_config(ctx, library_id)
    discoveries = _discover_audiobooks(config.source_path)
    results = _run_imports(discoveries, config)
    _cleanup_sources(results, config)
    return _report_results(results)
```

**Priority**: Medium

---

### Design Pattern: Boolean Blindness

**What is it?** Functions with multiple boolean parameters where call sites become unreadable.

**Found**:

```python
# workflow.py - What do these bools mean?
run_pipeline(releases, True, False, True, True, False)

# mkbrr.py - 5 boolean parameters
create_torrent(path, dry_run, verbose, force, recursive, no_cache)
```

**Problematic functions**:

| File | Function | Bool Params |
| ---- | -------- | ----------- |
| `workflow.py` | `run_pipeline()` | 5 |
| `mkbrr.py` | `create_batch()` | 5 |
| `abs/importer.py` | `import_folder_async()` | 4 |
| `abs/importer.py` | `import_batch_async()` | 4 |

**Better approach**: Use a config/options dataclass:

```python
# ❌ Current (boolean blindness)
def run_pipeline(releases, dry_run, verbose, force, cache, strict):
    ...

# ✅ Better (self-documenting)
@dataclass
class PipelineOptions:
    dry_run: bool = False
    verbose: bool = False
    force: bool = False
    use_cache: bool = True
    strict: bool = False

def run_pipeline(releases, options: PipelineOptions):
    ...

# Call site is now clear:
run_pipeline(releases, PipelineOptions(dry_run=True, force=True))
```

**Priority**: Medium

---

### Design Pattern: God Objects

**What is it?** Classes that do too many things, violating the Single Responsibility Principle.

**Found**:

| File | Class | Methods | Lines | Problem |
| ---- | ----- | ------- | ----- | ------- |
| `abs/async_client.py` | `AbsAsyncClient` | 20 | ~560 | Does everything: auth, items, search, scan |
| `validation.py` | `HealthChecker` | 17 | ~475 | Checks Docker, config, paths, network, all in one |
| `abs/importer.py` | `AsinEntry` | 12 | ~619 | Data + logic mixed |
| `opf.py` | `OPFGenerator` | 19 | ~298 | Building + writing + validation |

**Better approach**: Split by responsibility:

```python
# ❌ Current: One class does everything
class AbsAsyncClient:
    def authorize(self): ...
    def get_libraries(self): ...
    def get_items(self): ...
    def search(self): ...
    def scan(self): ...
    def match(self): ...

# ✅ Better: Focused classes
class AbsAuthClient:
    def authorize(self): ...

class AbsLibraryClient:
    def get_libraries(self): ...
    def scan(self): ...

class AbsSearchClient:
    def search(self): ...
    def match(self): ...
```

**Priority**: Low (works, but harder to maintain)

---

### Design Pattern: Deep Nesting

**What is it?** Code with many levels of indentation (if inside if inside for inside try...), hard to follow.

**Found**:

| File | Function | Depth | Location |
| ---- | -------- | ----- | -------- |
| `abs/asin.py` | `resolve_asin_from_folder_with_mediainfo()` | 7 levels | Line 1149 |
| `abs/asin.py` | `normalize_asin_to_preferred_region()` | 5 levels | Line 1617 |
| `abs/importer.py` | `_classify_unknown_asin()` | 5 levels | Line 482 |

**Example of problematic nesting**:

```python
def process():
    if condition1:
        for item in items:
            try:
                if condition2:
                    with open(file):
                        for line in file:
                            if condition3:  # 7 levels deep!
                                ...
```

**Better approach**: Use early returns (guard clauses):

```python
# ✅ Better: Guard clauses flatten the code
def process():
    if not condition1:
        return

    for item in items:
        if not _is_valid(item):
            continue
        _process_item(item)  # Extract complex logic
```

**Priority**: Low

---

### Design Pattern: Circular Import Guards

**What is it?** Using `TYPE_CHECKING` blocks to avoid import cycles. While necessary, many guards suggest tangled dependencies.

**Found**: 60+ files use `TYPE_CHECKING` guards, including:

- `config.py` imports from `abs/cleanup.py` and `abs/trumping.py` (via TYPE_CHECKING)
- `abs/importer.py` has TWO separate TYPE_CHECKING blocks
- `workflow.py` imports from multiple `abs/` modules

**Why it matters**: Circular dependencies make code harder to understand and refactor.

**Better approach**: Extract shared types to a central module:

```python
# ✅ Create src/shelfr/types.py with shared types
from shelfr.types import TrumpPrefs, CleanupPrefs, Settings

# Now both config.py and abs/*.py can import from types.py
# without circular dependencies
```

**Priority**: Low (technical debt, not a bug)

---

### Summary: Design Quality Score

| Design Principle | Score | Issue |
| ---------------- | ----- | ----- |
| Single Responsibility | ⭐⭐⭐ | Some God objects, long functions |
| Open/Closed | ⭐⭐⭐⭐ | Good provider pattern for extensibility |
| Dependency Inversion | ⭐⭐ | Heavy use of global `get_settings()` |
| Interface Segregation | ⭐⭐⭐⭐ | Good exception hierarchy, protocols |
| Don't Repeat Yourself | ⭐⭐⭐ | Duplicate constants, ASIN patterns |

**Overall Design**: ⭐⭐⭐ (3/5) - Functional but could benefit from refactoring

---

## 📊 Summary Scorecard

| Category | Score | Notes |
| ---------- | ------- | ------- |
| Project Structure | ⭐⭐⭐⭐ | Clean layout, good separation |
| Type Safety | ⭐⭐⭐⭐⭐ | Strict mypy, py.typed, Pydantic |
| Testing | ⭐⭐⭐ | Good foundation, could expand |
| CLI Design | ⭐⭐⭐⭐ | Modern Typer, deprecated code lingers |
| Config Management | ⭐⭐⭐ | Works well, file too large |
| Error Handling | ⭐⭐⭐⭐⭐ | Excellent exception hierarchy |
| Code Organization | ⭐⭐⭐ | Some modules too large |
| Dependencies | ⭐⭐⭐⭐⭐ | Modern, well-chosen |
| Documentation | ⭐⭐⭐⭐ | Good docs/, inline comments |

**Overall**: ⭐⭐⭐⭐ (4/5) - Well-architected, ready for production

---

## 🎯 Prioritized Action Items

### High Priority

*(None - codebase is functional)*

### Medium Priority (Architecture/Design)

1. **Reduce tight coupling**: Refactor top-level functions in `workflow.py`, `mkbrr.py`, `qbittorrent.py` to accept config as parameter
2. **Break up long functions**: Split `cmd_abs_import()` (270 lines) into validate/discover/import/cleanup/report phases
3. **Eliminate boolean blindness**: Create `PipelineOptions`, `TorrentOptions`, `ImportOptions` dataclasses
4. **Extract shared types**: Create `src/shelfr/types.py` to break circular imports

### Medium Priority (Organization)

5. Remove/relocate `cli_argparse.py`
6. Split `config.py` into smaller modules
7. Extract duplicate constants to shared module (ASIN patterns, regions)
8. Improve exception catching specificity (use typed exceptions)
9. Create deprecation timeline document
10. Add integration test suite with proper markers

### Low Priority

11. Fix stray `print()` calls → use console helpers
12. Consolidate subprocess usage → `utils.cmd`
13. Clarify commands/ vs cli/ structure in CONTRIBUTING.md
14. Complete or remove TUI module
15. Split `workflow.py` into focused modules
16. Remove `__all__` duplicate entry
17. Add `clear_*()` functions for all global singletons
18. Standardize on pathlib over os.path
19. Extend circuit breaker to other APIs (qBittorrent, ABS, Hardcover)
20. Split `abs/importer.py` (2193 lines) into sub-package
21. Refactor God objects (`AbsAsyncClient`, `HealthChecker`) into focused classes
22. Reduce nesting depth in `abs/asin.py` using guard clauses

---

## Appendix A: Module Size Analysis

| Module               | Lines | Recommendation          |
| -------------------- | ----- | ----------------------- |
| `abs/importer.py`    | 2193  | Split into sub-package  |
| `validation.py`      | 1806  | Split into sub-package  |
| `config.py`          | 1517  | Split into sub-package  |
| `mkbrr.py`           | 1383  | Consider splitting      |
| `abs/asin.py`        | 1247  | Consider splitting      |
| `workflow.py`        | 1222  | Split into sub-package  |
| `abs/rename.py`      | 1114  | OK (complex logic)      |
| `abs/trumping.py`    | 901   | OK (complex logic)      |
| `utils/state.py`     | 894   | Consider splitting      |
| `cli_argparse.py`    | 786   | Remove (deprecated)     |
| `cli/abs.py`         | 761   | OK (CLI definitions)    |
| `cli/mkbrr.py`       | 760   | OK (CLI definitions)    |

---

## Appendix B: Files With Deprecated Code

| File                           | Deprecated Item              | Target Removal |
| ------------------------------ | ---------------------------- | -------------- |
| `cli_argparse.py`              | Entire module                | v2.0           |
| `cli/_helpers.py`              | `ArgsNamespace`, `get_args`  | v2.0           |
| `metadata/formatting/html.py`  | `_clean_html()`              | v1.0           |
| `metadata/orchestration.py`    | `region` parameter           | v1.0           |
| `schemas/config.py`            | `filters.remove_phrases`     | v1.0           |
| `__init__.py`                  | Duplicate `ShelfrError`      | Immediate      |

---

## Appendix C: Duplicate Constants

| Constant              | Locations                                      |
| --------------------- | ---------------------------------------------- |
| `ASIN_VALID_PATTERN`  | `discovery.py`, `validation.py`, `abs/asin.py` |
| `VALID_AUDNEX_REGIONS`| `config.py`, `schemas/config.py`               |
| `DEFAULT_ASIN_REGION` | `config.py`, `schemas/config.py`               |

---

*This audit was conducted using static analysis and code review. Runtime testing may reveal additional issues.*
