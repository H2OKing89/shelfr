# A3: Boolean Blindness

**Priority**: Medium
**Effort**: Low
**Risk**: Low

---

## Problem

Functions with multiple boolean parameters create unreadable call sites. When you see `run_pipeline(releases, True, False, True, True, False)`, you can't tell what those booleans mean.

## Affected Functions

| File | Function | Bool Params |
|------|----------|-------------|
| `workflow.py` | `run_pipeline()` | 5 |
| `mkbrr.py` | `create_batch()` | 5 |
| `abs/importer.py` | `import_folder_async()` | 4 |
| `abs/importer.py` | `import_batch_async()` | 4 |
| `abs/rename.py` | `run_rename_pipeline()` | 4 |

## Current Pattern

```python
# Unreadable - what do these booleans mean?
result = run_pipeline(
    releases,
    True,   # ???
    False,  # ???
    True,   # ???
    True,   # ???
    False,  # ???
)
```

## Target Pattern

```python
@dataclass(frozen=True)
class PipelineOptions:
    """Options for pipeline execution."""
    dry_run: bool = False
    verbose: bool = False
    force: bool = False
    use_cache: bool = True
    strict: bool = False

# Self-documenting call site
result = run_pipeline(
    releases,
    options=PipelineOptions(dry_run=True, force=True),
)
```

## Implementation Strategy

### Step 1: Create Options Dataclasses

Create in `src/shelfr/options.py`:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class PipelineOptions:
    dry_run: bool = False
    verbose: bool = False
    force: bool = False
    use_cache: bool = True
    strict: bool = False

@dataclass(frozen=True)
class TorrentOptions:
    dry_run: bool = False
    verbose: bool = False
    force: bool = False
    recursive: bool = True
    no_cache: bool = False

@dataclass(frozen=True)
class ImportOptions:
    dry_run: bool = False
    verbose: bool = False
    trigger_scan: bool = True
    skip_duplicates: bool = True
```

### Step 2: Update Function Signatures

```python
# Before
def run_pipeline(
    releases: list[AudiobookRelease],
    dry_run: bool = False,
    verbose: bool = False,
    force: bool = False,
    use_cache: bool = True,
    strict: bool = False,
) -> PipelineResult:

# After
def run_pipeline(
    releases: list[AudiobookRelease],
    options: PipelineOptions | None = None,
) -> PipelineResult:
    if options is None:
        options = PipelineOptions()
    ...
```

### Step 3: Update Call Sites

```python
# CLI layer creates the options object
options = PipelineOptions(
    dry_run=ctx.obj.dry_run,
    verbose=ctx.obj.verbose,
)
result = run_pipeline(releases, options=options)
```

## Files to Change

1. Create `src/shelfr/options.py`
2. Update `src/shelfr/workflow.py`
3. Update `src/shelfr/mkbrr.py`
4. Update `src/shelfr/abs/importer.py`
5. Update `src/shelfr/abs/rename.py`
6. Update all call sites

## Acceptance Criteria

- [ ] Options dataclasses created for major workflows
- [ ] Functions accept options objects instead of multiple booleans
- [ ] Call sites are self-documenting
- [ ] Backward compatibility maintained (optional parameter with default)

---

## Notes

Using `frozen=True` makes options immutable, which is safer and enables hashing.
