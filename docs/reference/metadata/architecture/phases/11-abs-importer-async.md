# Phase 11: ABS Importer Async

> **Status:** ✅ Complete
> **Goal:** Migrate sync ABS importer to async for better performance with large libraries
> **Branch:** `feature/phase-11-abs-async`

---

## Overview

The current ABS importer processes books **sequentially**, making one API call at a time. For libraries with 100+ books in staging, this creates unnecessary latency. Phase 11 introduces an async ABS client following the patterns established in Phase 10 (Audnex async client).

### Key Insight

Unlike Audnex (purely network-bound), ABS import is **filesystem-heavy**. The async win comes from:

1. **Parallel ABS API calls** — authorize, get_libraries, search_books
2. **Parallel ASIN index building** — fetch library items concurrently
3. **Parallel metadata prefetch** — resolve ASINs before sequential filesystem ops
4. **Concurrent library scans** — trigger multiple library scans in parallel

Filesystem operations (rename, move, hardlink) remain sync — async provides no benefit for local I/O.

---

## Current Architecture

| Component | File | Lines | Pattern |
| ----------- | ------ | ------- | --------- |
| Sync Client | `abs/client.py` | 605 | `httpx.Client` |
| Sync Importer | `abs/importer.py` | 2059 | Sequential loop |
| CLI Handler | `commands/abs/import_.py` | 921 | Sync orchestration |

### Pain Points

1. **Sequential API calls** — `get_all_library_items()` pages through results one at a time
2. **Blocking search** — ABS metadata search blocks the main thread
3. **No parallelism** — Large batches process books one-by-one
4. **Scan triggering** — Library scans are sequential

---

## Sub-phases

### 11.1: Async ABS Client ✅

Create `abs/async_client.py` with async equivalents:

| Sync Method | Async Method | Notes |
| ------------- | -------------- | ------- |
| `authorize()` | `authorize_async()` | Connection test |
| `get_libraries()` | `get_libraries_async()` | Library list |
| `get_library_items()` | `get_library_items_async()` | Paginated fetch |
| `get_all_library_items()` | `get_all_library_items_async()` | Parallel pages |
| `search_books()` | `search_books_async()` | Metadata search |
| `scan_library()` | `scan_library_async()` | Trigger scan |

**Pattern:** Follow Phase 10's `AudnexAsyncClient`:

- `httpx.AsyncClient` with connection pooling
- `aiolimiter.AsyncLimiter` for rate limiting
- `asyncio.Semaphore` for concurrency control
- Context manager (`async with`)

### 11.2: Async ASIN Index Builder

Replace sequential pagination with parallel page fetching:

```python
# Current (sync)
while True:
    items, total = client.get_library_items(library_id, page=page)
    all_items.extend(items)
    if len(all_items) >= total:
        break
    page += 1

# New (async)
async def build_asin_index_async(client, library_id):
    # Fetch first page to get total
    items, total = await client.get_library_items_async(library_id, page=0)

    # Calculate remaining pages
    pages_needed = (total - len(items)) // batch_size + 1

    # Fetch remaining pages in parallel
    tasks = [
        client.get_library_items_async(library_id, page=p)
        for p in range(1, pages_needed + 1)
    ]
    results = await asyncio.gather(*tasks)
    # ... combine results
```

### 11.3: Parallel Metadata Prefetch

Before batch import, prefetch metadata for all books concurrently:

```python
async def prefetch_metadata_async(staging_folders: list[Path]):
    """Prefetch Audnex metadata for all staged books in parallel."""
    asins = [extract_asin(f.name) for f in staging_folders]
    valid_asins = [a for a in asins if a]

    # Fetch all metadata in parallel (uses Phase 10 async client)
    async with AudnexAsyncClient() as client:
        results = await asyncio.gather(*[
            client.fetch_book_parallel(asin)
            for asin in valid_asins
        ], return_exceptions=True)

    return dict(zip(valid_asins, results))
```

### 11.4: Hybrid Batch Import

Keep filesystem operations sync, but use async for API calls:

```python
async def import_batch_async(
    staging_folders: list[Path],
    library_root: Path,
    asin_index: dict[str, AsinEntry],
    *,
    abs_client: AbsAsyncClient,
    # ... other params
) -> BatchImportResult:
    """Async batch import with parallel API, sync filesystem."""

    # Phase 1: Parallel metadata prefetch
    metadata_cache = await prefetch_metadata_async(staging_folders)

    # Phase 2: Sequential filesystem operations (no async benefit)
    batch_result = BatchImportResult()
    for folder in staging_folders:
        result = import_single(  # Still sync
            staging_folder=folder,
            metadata_cache=metadata_cache,  # Pre-fetched
            # ...
        )
        batch_result.add(result)

    # Phase 3: Parallel library scans (if multiple libraries)
    await asyncio.gather(*[
        abs_client.scan_library_async(lib_id)
        for lib_id in libraries_to_scan
    ])

    return batch_result
```

### 11.5: CLI Integration

Update `commands/abs/import_.py` to use async client:

```python
def cmd_abs_import(args: argparse.Namespace) -> int:
    """Import staged audiobooks to Audiobookshelf library."""
    # ... setup code ...

    # Run async import in sync context
    result = asyncio.run(_import_async(args, settings))
    return result

async def _import_async(args, settings) -> int:
    """Async implementation of import command."""
    async with AbsAsyncClient.from_config(settings.audiobookshelf) as client:
        # ... async operations ...
```

---

## Performance Expectations

| Scenario | Current | Phase 11 | Improvement |
| ---------- | --------- | ---------- | ------------- |
| ASIN index (1000 books) | ~10s (10 pages × 1s) | ~2s (parallel pages) | **5×** |
| Metadata prefetch (50 books) | N/A (on-demand) | ~3s (parallel) | **N/A** |
| Batch import (50 books) | ~150s (3s × 50) | ~60s (prefetch + sequential FS) | **2.5×** |

---

## Files to Create/Modify

| File | Action | Description |
| ------ | -------- | ------------- |
| `abs/async_client.py` | **CREATE** | Async ABS client |
| `abs/importer.py` | MODIFY | Add `import_batch_async()` |
| `abs/__init__.py` | MODIFY | Export async client |
| `commands/abs/import_.py` | MODIFY | Use async import |
| `tests/test_abs_async_client.py` | **CREATE** | Async client tests |

---

## Implementation Checklist

### 11.1: Async ABS Client

- [x] Create `abs/async_client.py` with `AbsAsyncClient`
- [x] Implement `authorize_async()` → `authorize()`
- [x] Implement `get_libraries_async()` → `get_libraries()`
- [x] Implement `get_library_items_async()` → `get_library_items()`
- [x] Implement `get_all_library_items_async()` with parallel pages → `get_all_library_items()`
- [x] Implement `search_books_async()` → `search_books()`, `search_books_batch()`
- [x] Implement `scan_library_async()` → `scan_library()`, `scan_libraries()`
- [x] Add rate limiting with `aiolimiter`
- [x] Add connection pooling
- [x] Add context manager support

### 11.2: Async ASIN Index

- [x] Create `build_asin_index_async()` in `abs/asin.py`
- [x] Parallel page fetching
- [x] Progress callback support

### 11.3: Metadata Prefetch

- [x] Create `prefetch_metadata_async()` in `abs/prefetch.py`
- [x] Integration with Phase 10 Audnex async client
- [x] Cache results for batch import (`MetadataCache` type alias)

### 11.4: Hybrid Batch Import

- [x] Create `import_batch_async()` wrapper in `abs/importer.py`
- [x] Keep `import_single()` sync (filesystem ops)
- [x] Parallel library scans via `scan_libraries()`

### 11.5: CLI Integration

- [x] Update `cmd_abs_import()` to use async (`asyncio.run(import_batch_async(...))`)
- [x] Maintain backward compatibility (sync still default, `--parallel` for async)
- [x] Progress bar updates

### Tests

- [x] Unit tests for `AbsAsyncClient` (`tests/test_abs_async_client.py`)
- [x] Integration tests for async import
- [x] Mock ABS API responses

### Documentation

- [x] Update CHECKLIST.md status
- [x] Add async client to Quick Reference
- [x] CHANGELOG entry

---

## Dependencies

- `httpx` (already installed) — async HTTP client
- `aiolimiter` (already installed) — async rate limiting
- `asyncio` (stdlib) — async runtime

No new dependencies required.

---

## Risk Mitigation

| Risk | Mitigation |
| ------ | ------------ |
| Breaking existing sync imports | Keep sync client, add async as alternative |
| Rate limiting ABS server | Use `AsyncLimiter` (10 req/s default) |
| Connection exhaustion | Limit concurrent connections (20 max) |
| Error handling complexity | Follow Phase 10 patterns (circuit breaker optional) |

---

## Related Docs

- [Phase 10: Parallel Region Lookup](10-parallel-region-lookup.md) — Reference implementation
- [Async Race Pattern](../patterns/async-race-pattern.md) — Pattern documentation
- [Rate Limiting Pattern](../patterns/rate-limiting-pattern.md) — Rate limiter docs
