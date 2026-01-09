# A2: Long Functions (>100 lines)

**Priority**: Medium
**Effort**: Medium
**Risk**: Low (refactoring, not behavior change)

---

## Problem

Several functions exceed 100 lines, making them hard to understand, test, and modify. They violate the Single Responsibility Principle by doing too many things.

## Affected Functions

| File | Function | Lines | Responsibilities |
|------|----------|-------|------------------|
| `commands/abs/import_.py` | `cmd_abs_import()` | 270 | Validate, discover, import, cleanup, report |
| `cli/abs.py` | `cmd_abs_trump_check()` | 235 | Parse, fetch, compare, display, decide |
| `workflow.py` | `run_pipeline()` | 189 | Entire pipeline orchestration |
| `commands/libation/core.py` | `cmd_libation_liberate()` | 179 | Container management + scanning |
| `abs/importer.py` | `import_batch_async()` | 169 | Batch import logic |
| `cli/tools.py` | `cmd_preview_naming()` | 159 | Preview naming changes |

## Target Pattern

Break into smaller, focused functions:

```python
# Before: 270-line monolith
def cmd_abs_import(ctx, library_id, ...) -> int:
    # validation (50 lines)
    # discovery (40 lines)
    # import (100 lines)
    # cleanup (30 lines)
    # reporting (50 lines)

# After: Composed functions
def cmd_abs_import(ctx, library_id, ...) -> int:
    config = _validate_import_config(ctx, library_id)
    if config is None:
        return 1

    discoveries = _discover_audiobooks(config)
    results = _run_imports(discoveries, config)
    _cleanup_sources(results, config)
    return _report_results(results)
```

## Implementation Strategy

### Priority Order

1. **`cmd_abs_import()`** - Most impactful, 270 lines
2. **`run_pipeline()`** - Core workflow, 189 lines
3. **`cmd_abs_trump_check()`** - Complex logic, 235 lines
4. **`import_batch_async()`** - Async complexity, 169 lines

### Extraction Guidelines

- Each extracted function should have a single purpose
- Functions should be testable in isolation
- Use descriptive names that explain the "what"
- Keep error handling in the main function when possible

## Example Refactor: cmd_abs_import()

```python
def cmd_abs_import(ctx: Context, library_id: str, ...) -> int:
    """Import audiobooks to Audiobookshelf."""
    # Phase 1: Validation
    config = _build_import_config(ctx, library_id, source_path, ...)
    errors = _validate_import_prerequisites(config)
    if errors:
        _print_validation_errors(errors)
        return 1

    # Phase 2: Discovery
    discoveries = _discover_import_candidates(config.source_path, config.filters)
    if not discoveries:
        console.print("[yellow]No audiobooks found to import[/]")
        return 0

    # Phase 3: Import
    results = _execute_imports(discoveries, config, ctx.dry_run)

    # Phase 4: Cleanup
    if config.cleanup_enabled:
        _cleanup_imported_sources(results, config.cleanup_prefs)

    # Phase 5: Report
    return _print_import_summary(results)
```

## Acceptance Criteria

- [ ] No function exceeds 100 lines (soft limit)
- [ ] Extracted functions have clear single purposes
- [ ] All tests pass after refactoring
- [ ] No functional changes to behavior

---

## Notes

Focus on the top 4 functions first. The others can be addressed later.
