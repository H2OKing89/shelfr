# O4: Improve Exception Catching

**Priority**: Medium
**Effort**: Low
**Risk**: Low

---

## Problem

Many command handlers use bare `except Exception:` which catches too broadly:

```python
# src/shelfr/commands/libation/core.py:210
except Exception as e:
    print_error(f"Failed to scan library: {e}")
    return 1
```

This hides the actual error type and makes debugging harder.

## Found In

- `commands/libation/core.py` (4 occurrences)
- `commands/utility.py` (3 occurrences)
- `commands/abs/import_.py` (2 occurrences)
- `commands/abs/resolve.py` (1 occurrence)
- And others (20+ total)

## Target Pattern

Use the typed exception hierarchy from `shelfr/exceptions.py`:

```python
# Before (bad)
try:
    result = do_something()
except Exception as e:
    print_error(f"Failed: {e}")
    return 1

# After (good)
try:
    result = do_something()
except ConfigurationError as e:
    # Expected error - user-friendly message
    print_error(str(e))
    return 1
except ValidationError as e:
    # Expected error - show details
    print_error(f"Validation failed: {e}")
    if e.details:
        for key, value in e.details.items():
            console.print(f"  {key}: {value}")
    return 1
except ShelfrError as e:
    # Unexpected shelfr error
    print_error(f"Unexpected error: {e}")
    logger.exception("Full traceback:")
    return 1
except Exception as e:
    # Truly unexpected - log full traceback
    print_error(f"Internal error: {e}")
    logger.exception("Unhandled exception:")
    return 1
```

## Exception Hierarchy Reference

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

## Implementation Strategy

### Step 1: Audit Each Location

For each `except Exception:`, determine:

1. What errors are expected from the code?
2. What's the appropriate handler?

### Step 2: Replace Broad Catches

```python
# Command that calls Audnex API
try:
    metadata = fetch_metadata(asin)
except AudnexError as e:
    print_error(f"Failed to fetch metadata: {e}")
    return 1
except NetworkError as e:
    print_error(f"Network error: {e}")
    return 1
```

### Step 3: Keep One Broad Catch at Top Level

Only CLI entry points should have a final `except Exception`:

```python
# In cli/abs.py (entry point)
@app.command()
def import_command(...):
    try:
        return cmd_abs_import(...)
    except ShelfrError as e:
        print_error(str(e))
        return 1
    except Exception as e:
        # Only at entry point - log for debugging
        logger.exception("Unhandled exception in import command")
        print_error(f"Internal error: {e}")
        return 1
```

## Files to Change

1. `src/shelfr/commands/libation/core.py`
2. `src/shelfr/commands/utility.py`
3. `src/shelfr/commands/abs/import_.py`
4. `src/shelfr/commands/abs/resolve.py`
5. Other command files as found

## Acceptance Criteria

- [ ] No bare `except Exception:` in business logic
- [ ] Appropriate typed exceptions caught
- [ ] One broad catch only at CLI entry points
- [ ] Logger.exception() used for unexpected errors
- [ ] All tests pass
