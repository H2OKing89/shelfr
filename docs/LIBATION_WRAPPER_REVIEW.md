# Libation CLI Wrapper Review

**Date:** December 27, 2025
**Reviewer:** Claude (GitHub Copilot)
**Files Reviewed:**

- `src/mamfast/libation.py` (496 lines)
- `src/mamfast/commands/libation.py` (1725 lines)
- `tests/test_libation.py` (785 lines)
- `tests/test_cli_libation.py` (344 lines)

---

## Executive Summary

The Libation CLI wrapper is well-designed with excellent Rich UI components and comprehensive help for novice users. However, several issues need attention:

- **Critical:** Custom `LibationError` exception exists but is never used
- **High:** Missing tests for several commands
- **Medium:** Hardcoded timeouts, missing ASIN validation, no confirmation prompts
- **Low:** Inconsistent result types, unsafe `getattr` patterns

---

## ✅ Strengths

### Design

1. **Two-module separation** - Clean separation between `libation.py` (core functions) and `commands/libation.py` (CLI interface)
2. **Rich UI components** - Excellent use of Rich library for formatted output, status dashboards, and progress spinners
3. **Comprehensive help system** - `cmd_libation_help()` provides excellent onboarding for novices
4. **Hint system** - `print_hint_box()` provides contextual tips throughout

### User Experience

1. **Default to status** - Running `mamfast libation` with no subcommand shows dashboard (novice-friendly)
2. **Dry-run support** - Every command supports `--dry-run` for safe exploration
3. **Combined workflows** - `--liberate` flag on scan for convenience
4. **Detailed epilogs** - Every subcommand has examples in help text

### Code Quality

1. **Type annotations** - Consistent use of type hints throughout
2. **Logging** - Proper logger setup with `logging.getLogger(__name__)`
3. **Dataclasses** - Clean data structures for results

---

## 🔴 Critical Issues

### Issue 1: LibationError Exception Not Used

**Location:** `src/mamfast/libation.py` lines 157-163, `src/mamfast/commands/libation.py` various

**Problem:** The custom `LibationError` exception exists in `exceptions.py` but is never raised. Both modules use generic `RuntimeError` instead.

```python
# Current (libation.py line 157):
except json.JSONDecodeError as e:
    raise RuntimeError(f"Failed to parse Libation export JSON: {e}") from e

# Should be:
from mamfast.exceptions import LibationError
raise LibationError(f"Failed to parse export JSON: {e}", exit_code=1) from e
```

**Impact:** Breaks exception hierarchy, makes error handling inconsistent with rest of codebase.

**Fix:** Replace all `RuntimeError` raises with `LibationError`.

---

### Issue 2: Inconsistent Return Types

**Location:** `src/mamfast/libation.py`

**Problem:** Two different result types for similar operations:

- `ScanResult` - used for both `run_scan()` AND `run_liberate()`
- `LiberateProgressResult` - used for `run_liberate_with_progress()`

The name `ScanResult` is misleading when returned from liberate functions.

**Fix:** Rename `ScanResult` to `LibationResult` or create unified type.

---

## 🟡 Logic Issues

### Issue 3: Duplicate Export Operations

**Location:** `src/mamfast/commands/libation.py` - `cmd_libation_liberate()`

**Problem:** The liberate command calls `_export_library()` twice - once before liberate to check pending count, once after to show updated status. For large libraries (1000+ books), this is slow.

```python
# Line ~505: First export
books = _export_library(container)
status = _get_library_status(books)
pending = status.get("NotLiberated", 0)

# ... liberate runs ...

# Line ~576: Second export
books = _export_library(container)
status = _get_library_status(books)
print_status_dashboard(status)
```

**Fix:** Cache the initial export or make second export optional with `--no-status` flag.

---

### Issue 4: Hardcoded Timeouts

**Location:** Multiple files

**Problem:** Timeouts are hardcoded throughout:

| Location | Timeout | Purpose |
|----------|---------|---------|
| `commands/libation.py:388` | 600s | Scan |
| `commands/libation.py:554` | 14400s (4h) | Liberate |
| `commands/libation.py:1185` | 7200s (2h) | Redownload per book |
| `libation.py:378` | 3600s (1h) | Progress liberate |
| `commands/libation.py:270` | 300s | Default |

**Fix:** Add to config schema:

```yaml
libation:
  scan_timeout: 600
  liberate_timeout: 14400
  command_timeout: 300
```

---

### Issue 5: Silent Container Check Failure

**Location:** `src/mamfast/libation.py` lines 285-287

**Problem:** Container check silently returns `False` on any exception:

```python
except Exception:
    return False
```

Novice users won't know WHY the check failed (Docker not installed? Container name wrong? Permission denied?)

**Fix:** Log the exception at debug level:

```python
except Exception as e:
    logger.debug(f"Container check failed: {e}")
    return False
```

---

### Issue 6: Missing ASIN Validation

**Location:** `src/mamfast/commands/libation.py` - argument parsers

**Problem:** ASINs are accepted without validation. Valid Audible ASINs follow pattern `B[0-9A-Z]{9}` (10 chars starting with B).

```python
# Currently accepts any string:
liberate_parser.add_argument("--asin", type=str, ...)
```

**Fix:** Add validation function:

```python
def validate_asin(value: str) -> str:
    """Validate Audible ASIN format."""
    if not re.match(r'^B[0-9A-Z]{9}$', value):
        raise argparse.ArgumentTypeError(
            f"Invalid ASIN format: {value}. ASINs are 10 characters starting with 'B'"
        )
    return value

# Usage:
liberate_parser.add_argument("--asin", type=validate_asin, ...)
```

---

## 🟠 Type Safety Issues

### Issue 7: Unsafe getattr Usage

**Location:** `src/mamfast/commands/libation.py` - multiple commands

**Problem:** Many places use `getattr(args, "attr", default)` pattern:

```python
asin = getattr(args, "asin", None)
force = getattr(args, "force", False)
limit = getattr(args, "limit", 50)
```

This masks potential attribute errors and makes refactoring risky.

**Fix:** Use `set_defaults()` in parser setup to ensure attributes always exist:

```python
liberate_parser.set_defaults(asin=None, force=False)
```

Then access directly: `args.asin`, `args.force`

---

### Issue 8: Untyped Any in Dataclasses

**Location:** `src/mamfast/commands/libation.py` line 261

**Problem:**

```python
@dataclass
class LibationCommandResult:
    parsed_data: Any = None  # What type is this?
```

**Fix:** Type properly:

```python
parsed_data: list[dict[str, Any]] | dict[str, Any] | None = None
```

---

## 🔵 Usability Issues

### Issue 9: No Confirmation for Destructive Operations

**Location:** `cmd_libation_redownload()`, `cmd_libation_set_status()`

**Problem:** These commands modify state without confirmation:

- `redownload` marks books as not-downloaded then re-downloads
- `set-status` can mark all books in library

**Fix:** Add confirmation prompt:

```python
from rich.prompt import Confirm

if not args.yes and not args.dry_run:
    if not Confirm.ask(f"Re-download {len(asins)} book(s)?"):
        console.print("[dim]Cancelled[/]")
        return 0
```

Add `--yes` / `-y` flag to skip prompt for automation.

---

### Issue 10: No Machine-Readable Output

**Problem:** All output is Rich-formatted text. Advanced users running scripts need JSON output.

**Fix:** Add `--json` flag that outputs structured data:

```python
if args.json:
    import json
    print(json.dumps({"status": status, "books": len(books)}))
    return 0
```

---

### Issue 11: Ambiguous Exit Codes

**Problem:** Commands return only 0 or 1, but partial success scenarios exist:

- Some books downloaded, some failed
- Scan succeeded but liberate failed

**Current:** `run_liberate_with_progress` tracks `has_book_errors` but CLI doesn't expose this.

**Fix:** Document exit codes:

- 0 = Complete success
- 1 = Complete failure
- 2 = Partial success (some operations failed)

---

## 🟣 Test Coverage Gaps

### Missing Command Tests

| Command | Test File | Status |
|---------|-----------|--------|
| `cmd_libation_scan` | test_cli_libation.py | ✅ Basic dry-run |
| `cmd_libation_liberate` | test_cli_libation.py | ✅ Basic dry-run |
| `cmd_libation_status` | test_cli_libation.py | ❌ Not tested |
| `cmd_libation_search` | test_cli_libation.py | ✅ Basic success |
| `cmd_libation_settings` | test_cli_libation.py | ✅ Basic success |
| `cmd_libation_books` | test_cli_libation.py | ❌ Not tested |
| `cmd_libation_redownload` | test_cli_libation.py | ❌ Not tested |
| `cmd_libation_set_status` | test_cli_libation.py | ❌ Not tested |
| `cmd_libation_convert` | test_cli_libation.py | ❌ Not tested |
| `cmd_libation_export` | test_cli_libation.py | ❌ Not tested |
| `cmd_libation_help` | test_cli_libation.py | ✅ Returns 0 |

### Missing Error Path Tests

- Container not running scenarios
- Export parse failures
- Partial download failures
- Network timeout scenarios

---

## 📊 Priority Matrix

| Issue | Severity | Effort | Priority |
|-------|----------|--------|----------|
| #1 LibationError not used | Critical | Low | P0 |
| #6 ASIN validation | Medium | Low | P1 |
| #9 Confirmation prompts | Medium | Low | P1 |
| #2 Inconsistent result types | Medium | Medium | P2 |
| #4 Hardcoded timeouts | Medium | Low | P2 |
| #5 Silent container failure | Low | Low | P2 |
| #7 Unsafe getattr | Low | Medium | P3 |
| #3 Duplicate exports | Medium | Medium | P3 |
| #10 JSON output mode | Medium | Medium | P3 |
| #8 Untyped Any | Low | Low | P3 |
| #11 Exit codes | Low | Low | P4 |
| Test coverage | High | Medium | P1 |

---

## Implementation Plan

### Phase 1: Critical Fixes (P0-P1) ✅ COMPLETED

1. ✅ Use `LibationError` throughout (libation.py, commands/libation.py)
2. ✅ Add ASIN validation (validate_asin function, applied to all ASIN args)
3. ✅ Add confirmation prompts with `--yes` flag (redownload, set-status)
4. ✅ Add missing command tests (ASIN validation, parser tests)
5. ✅ Log container check failures (debug level logging)
6. ✅ Update tests to expect LibationError instead of RuntimeError

### Phase 2: Medium Priority (P2) ✅ COMPLETED

5. ✅ Rename `ScanResult` to `LibationResult` (with backwards-compat alias)
6. ✅ Make timeouts configurable via `config.yaml` libation section
   - `scan_timeout` (default: 600s / 10 min)
   - `liberate_timeout` (default: 14400s / 4 hours)
   - `command_timeout` (default: 300s / 5 min)

### Phase 3: Enhancements (P3-P4)

8. Add `--json` output mode
2. Refactor getattr usage
3. Document exit codes
4. Optimize duplicate exports

---

## Appendix: Code Locations

### Main Files

- Core module: `src/mamfast/libation.py`
- CLI commands: `src/mamfast/commands/libation.py`
- Exception: `src/mamfast/exceptions.py` (line 388)
- Tests: `tests/test_libation.py`, `tests/test_cli_libation.py`

### Key Functions

- `get_libation_status()` - Get book counts from Libation
- `run_scan()` - Execute scan command
- `run_liberate()` - Execute liberate command
- `run_liberate_with_progress()` - Liberate with Rich progress
- `_run_libation_cmd()` - Generic command executor
- `_export_library()` - Export and parse library JSON
