# Migration Backlog

This document tracks deferred migrations and technical debt that should be addressed during future maintenance windows.

## P2: sh Library Subprocess Migrations

### Overview

The P1 package upgrade (see [P1_SH_LIBRARY_COMPLETE.md](../archive/P1_SH_LIBRARY_COMPLETE.md)) migrated critical subprocess calls in `libation.py` and `mkbrr.py` to the sh library wrapper (`utils/cmd.py`). Two lower-priority files were deferred.

### Deferred Files

#### 1. metadata.py - MediaInfo Calls

**File**: `src/shelfr/metadata.py`
**Function**: `run_mediainfo()` (line ~990)
**Current Implementation**: Direct `subprocess.run()` call to `mediainfo --Output=JSON`
**Migration Target**: Use `utils/cmd.run()` wrapper

**Rationale for Deferral**:

- Single subprocess call in a large file (1851 lines)
- Low impact - mediainfo is stable and rarely fails
- No TTY or complex I/O requirements
- Current implementation works reliably

**Estimated Effort**: 10-15 minutes
**Priority**: P2 (Nice to have)

**Trigger Conditions** (when to migrate):

- Bug fix or feature work touching `run_mediainfo()`
- Need for consistent timeout handling across all subprocess calls
- Adding retry logic or better error messages to mediainfo calls
- Next major refactoring of metadata.py

**Migration Notes**:

- Replace `subprocess.run()` with `cmd.run()`
- Add timeout parameter to `run()` call (currently hardcoded at 60s)
- Handle `CmdError` exception instead of `subprocess.SubprocessError`
- Keep JSON parsing and error handling logic intact

---

#### 2. abs/asin.py - MediaInfo Calls

**File**: `src/shelfr/abs/asin.py`
**Function**: `extract_asin_from_mediainfo()` (line ~430)
**Current Implementation**: Direct `subprocess.run()` call to `mediainfo --Output=JSON`
**Migration Target**: Use `utils/cmd.run()` wrapper

**Rationale for Deferral**:

- Single subprocess call for niche use case (extracting ASIN from audio file metadata)
- Rarely called - only used when ASIN can't be found in folder name or ABS metadata
- Low impact - most books have ASINs in folder names already
- Current implementation is defensive and handles errors well

**Estimated Effort**: 10-15 minutes
**Priority**: P2 (Nice to have)

**Trigger Conditions** (when to migrate):

- Bug fix or feature work in ASIN extraction logic
- Performance profiling reveals subprocess overhead
- Adding retry logic for flaky mediainfo calls
- Next major refactoring of asin.py

**Migration Notes**:

- Replace `subprocess.run()` with `cmd.run()`
- Handle `CmdError` with `timed_out` attribute instead of `subprocess.TimeoutExpired`
- Keep JSON parsing and ASIN extraction logic intact
- Maintain existing defensive checks (file exists, binary available, etc.)

---

## Migration Guidelines

When migrating subprocess calls to sh library:

1. **Import changes**:

   ```python
   # Remove:
   import subprocess

   # Add:
   from shelfr.utils.cmd import run, CmdError
   ```

2. **Function call**:

   ```python
   # Before:
   result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)

   # After:
   result = run(cmd, timeout=60, ok_codes=(0,))
   ```

3. **Error handling**:

   ```python
   # Before:
   except subprocess.TimeoutExpired:
       logger.warning("Command timed out")
   except subprocess.SubprocessError as e:
       logger.error(f"Command failed: {e}")

   # After:
   except CmdError as e:
       if e.timed_out:
           logger.warning("Command timed out")
       else:
           logger.error(f"Command failed: {e}")
   ```

4. **Test coverage**: Ensure existing tests still pass after migration

---

## Other Deferred Items

(This section reserved for future technical debt entries)

---

## Review Schedule

- **Quarterly**: Review backlog during planning sessions
- **Before Major Releases**: Assess if any P2 items should be promoted to P1
- **During Refactors**: Check if touching related code presents opportunity to clear debt

---

**Last Updated**: 2025-12-20
**Maintained By**: Development team
**Related Documents**:

- [P1_SH_LIBRARY_COMPLETE.md](../archive/P1_SH_LIBRARY_COMPLETE.md) - P1 migration completion report
- [PACKAGE_UPGRADE_PLAN.md](PACKAGE_UPGRADE_PLAN.md) - Overall package upgrade roadmap
