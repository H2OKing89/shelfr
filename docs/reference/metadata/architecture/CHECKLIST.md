# Metadata Architecture Checklist

> **The Orchestrator** — Track all phases at a glance. No code here, just status.
>
> For design details, see phase docs. For code examples, see [patterns/](patterns/).

---

## Migration Status

| Phase | Status | Details |
| ------- | -------- | --------- |
| **0: Package Scaffolding** | ✅ Complete | [phases/00-08-migration.md](phases/00-08-migration.md#phase-0) |
| **1: Extract MediaInfo** | ✅ Complete | [phases/00-08-migration.md](phases/00-08-migration.md#phase-1) |
| **2: Extract Formatting** | ✅ Complete | [phases/00-08-migration.md](phases/00-08-migration.md#phase-2) |
| **3: Extract Audnex** | ✅ Complete | [phases/00-08-migration.md](phases/00-08-migration.md#phase-3) |
| **4: Extract MAM** | ✅ Complete | [phases/00-08-migration.md](phases/00-08-migration.md#phase-4) |
| **5: Schemas + Providers** | ✅ Complete | [phases/00-08-migration.md](phases/00-08-migration.md#phase-5) |
| **6: Move OPF + Deprecations** | ✅ Complete | [phases/00-08-migration.md](phases/00-08-migration.md#phase-6) |
| **7: Cleanup & Hygiene** | ✅ Complete | [phases/00-08-migration.md](phases/00-08-migration.md#phase-7) |
| **8: Infrastructure** | ✅ Complete | [phases/00-08-migration.md](phases/00-08-migration.md#phase-8) |
| **8.5: Production Integration** | ✅ Complete | [phases/00-08-migration.md](phases/00-08-migration.md#phase-85) |
| **9: Content Flags** | ✅ Complete | [phases/09-content-flags.md](phases/09-content-flags.md) |
| **10: Parallel Region Lookup** | ✅ Complete | [phases/10-parallel-region-lookup.md](phases/10-parallel-region-lookup.md) |

---

## Phase 10: Parallel Region Lookup ✅ COMPLETE

> **Goal:** Replace sequential region fallback with parallel "race" semantics

| Sub-phase | Status | PR | Description |
| --------- | ------ | --- | ----------- |
| 10.1 Async Client | ✅ | #86 | Staged region racing with `asyncio.as_completed()` |
| 10.2 Region Cache | ✅ | #87 | ASIN→region cache with smart invalidation |
| 10.3 Source Provenance | ✅ | #87 | `source_region`, `source_url` fields |
| 10.4 Provider Lifecycle | ✅ | #88 | `startup()`/`shutdown()` pattern |
| 10.5 Templates | ✅ | #89 | Dynamic source URLs |
| 10.6 Concurrency Limits | ✅ | #91 | Dual rate limiters + ASIN semaphore |
| 10.7 Observability | ✅ | #92 | Structured logging + `shelfr audnex region-stats` |

**Code patterns:** [async-race](patterns/async-race-pattern.md) | [region-cache](patterns/region-cache-pattern.md) | [rate-limiting](patterns/rate-limiting-pattern.md)

**Details:** [phases/10-parallel-region-lookup.md](phases/10-parallel-region-lookup.md)

---

## Phase 9: Content Flags ✅ COMPLETE

> **Goal:** Multi-source content flag resolution for MAM

| Task | Status | Description |
| ------ | -------- | ------------- |
| Flag mapping | ✅ | Hardcover → MAM flag mapping |
| Precedence rules | ✅ | Local > Hardcover > Audnex |
| `isAdult` handling | ✅ | Maps to `sSex` (weak signal), never `eSex` |

**Details:** [phases/09-content-flags.md](phases/09-content-flags.md)

---

## Future Phases

| Phase | Status | Description |
| ------- | -------- | ------------- |
| **11: ABS Importer Async** | � In Progress | Migrate sync importer to async |
| **12: Hardcover Provider** | 📋 Planned | Add Hardcover as metadata source |

---

## Phase 11: ABS Importer Async 🚧 IN PROGRESS

> **Goal:** Migrate sync ABS importer to async for better performance with large libraries

| Sub-phase | Status | Description |
| --------- | ------ | ----------- |
| 11.1 Async Client | ✅ | `AbsAsyncClient` with parallel pagination |
| 11.2 Async ASIN Index | ✅ | `build_asin_index_async()` |
| 11.3 Metadata Prefetch | ✅ | `prefetch_metadata_async()` |
| 11.4 Hybrid Batch Import | ✅ | `import_batch_async()` |
| 11.5 CLI Integration | 📋 | Update `shelfr abs import` |

**Details:** [phases/11-abs-importer-async.md](phases/11-abs-importer-async.md)

---

## Quick Reference

### Key Files

| File | Purpose |
| ------- | --------- |
| `src/shelfr/metadata/audnex/async_client.py` | Async Audnex client |
| `src/shelfr/metadata/audnex/region_cache.py` | Region cache |
| `src/shelfr/metadata/providers/audnex.py` | AudnexProvider |
| `src/shelfr/cli/audnex.py` | `shelfr audnex` commands |

### Commands

```bash
shelfr audnex region-stats        # Show cache statistics
shelfr --no-cache run             # Bypass caching
```

### Config

```yaml
# config/config.yaml
audnex:
  regions: [us, uk, de, au, ca]   # Regions to try (in order for sync fallback)
```
