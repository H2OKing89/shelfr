# Metadata Architecture Documentation

> **Date:** January 2, 2026
> **Status:** Migration Complete ✅ — Phases 0-7 shipped
> **Related:** [JSON Sidecar Discovery](../../../implementation/json-sidecar-discovery.md) | [Naming System](../naming/NAMING.md)

---

## Overview

This folder contains the comprehensive metadata architecture documentation for shelfr. The documentation is organized into focused modules for easier navigation and maintenance.

## Quick Links

| Document | Description |
| --- | --- |
| [Current State Audit](01-current-state-audit.md) | Analysis of existing files, duplicates, and issues |
| [Recommendations](02-recommendations.md) | Phased refactoring plan and migration strategy |
| [Plugin Architecture](03-plugin-architecture.md) | Provider system for extensible metadata sources |
| [Future-Proofing](04-future-proofing.md) | Exporters, caching, events, and infrastructure |
| [Implementation Checklist](05-implementation-checklist.md) | Actionable task list by phase |

---

## Executive Summary

The metadata package has been fully refactored into a unified `src/shelfr/metadata/` package with clean architecture. The original 2040-line god module has been decomposed into focused submodules.

### Migration Complete ✅

| Achievement | Status |
| --- | --- |
| God module decomposed | ✅ `metadata.py` → `metadata/` package |
| Duplicate schemas unified | ✅ `AbsMetadataSchema` → `AbsMetadataJson` |
| Provider system implemented | ✅ Pluggable, deterministic merging |
| Exporter system implemented | ✅ JSON + OPF exporters |
| OPF module integrated | ✅ Moved to `metadata/opf/` |
| Deprecation shims in place | ✅ `shelfr.opf` → `shelfr.metadata.opf` |

---

## Data Flow Contract

**The single most important rule:** Data flows in one direction through well-defined stages.

```bash
┌──────────────┐     ┌────────────┐     ┌───────────────────┐     ┌───────────┐     ┌───────────┐
│  Providers   │────▶│ Aggregator │────▶│ CanonicalMetadata │────▶│ Cleaning  │────▶│ Exporters │
│ (fetch data) │     │  (merge)   │     │ (single truth)    │     │(normalize)│     │ (output)  │
└──────────────┘     └────────────┘     └───────────────────┘     └───────────┘     └───────────┘
```

| Stage | Input | Output | Rule |
| --- | --- | --- | --- |
| **Providers** | ASIN, path, etc. | Partial canonical fragments | Each provider returns what it knows |
| **Aggregator** | Multiple fragments | Merged CanonicalMetadata | Precedence rules resolve conflicts |
| **Cleaning** | Raw CanonicalMetadata | Normalized CanonicalMetadata | Single entrypoint: `normalize_canonical()` |
| **Exporters** | Clean CanonicalMetadata | OPF, JSON, etc. | Assume input is already clean |

**Critical invariant:** Exporters should NEVER clean fields themselves. All normalization happens in one place (`cleaning.py`). This prevents duplicate logic, inconsistent behavior, and bugs where "OPF cleans differently than JSON."

---

## Precedence Rules

When multiple providers have data for the same field, use these rules:

| Field Category | Priority Order | Rationale |
| --- | --- | --- |
| **Identifiers** (ASIN, ISBN) | Audnex > abs_sidecar > Libation | Audnex is authoritative for ASINs |
| **Title/Subtitle/Series** | Audnex > abs_sidecar (if trusted) > Libation | Audnex normalizes Audible's mess |
| **Authors** | Audnex > abs_sidecar > Libation | Audnex has author ASINs |
| **Narrators** | MediaInfo (embedded) > Audnex > abs_sidecar | Embedded tags are definitive |
| **Runtime/Chapters** | MediaInfo > Audnex | MediaInfo is ground truth for audio |
| **Cover** | Local folder > Audnex | Local may have higher-res |
| **Genres/Tags** | Merge all sources | More is better, dedupe later |
| **Description** | Audnex > abs_sidecar | Audnex has full HTML descriptions |

**Trust levels:**

- `audnex`: High (authoritative API)
- `mediainfo`: High (ground truth for audio)
- `abs_sidecar`: Medium (user-corrected, may be stale)
- `libation`: Low (folder structure, limited fields)

**Override providers:** `abs_sidecar` and `private_db` may intentionally set empty values to clear bad data. The aggregator respects these clears rather than filtering them out.

> **Note:** The plugin architecture implements precedence via per-provider `priority` + `confidence` scores with deterministic tie-breaking. These tables document the *default* behavior; see [Plugin Architecture](03-plugin-architecture.md) for the flexible system.

---

## Public API

The package exposes a clean, minimal API:

```python
from shelfr.metadata import (
    # Core orchestration
    fetch_metadata,          # Fetch + merge from providers
    normalize_canonical,     # Clean a CanonicalMetadata instance
    export_sidecars,         # Render to one or more formats
    build_sidecars,          # Convenience: fetch + normalize + export

    # Types
    CanonicalMetadata,       # The canonical data model
    ProviderResult,          # What providers return
    LookupContext,           # Provider lookup input
)

# Simple usage
ctx = LookupContext.from_asin(asin="B08G9PRS1K", path=book_path)
metadata = await fetch_metadata(ctx, providers=["audnex", "mediainfo"])
metadata = normalize_canonical(metadata)
await export_sidecars(metadata, formats=["opf", "json"], output_dir=book_path)

# Or all-in-one
await build_sidecars(book_path, asin="B08G9PRS1K", formats=["opf", "json"])
```

---

## Current Module Structure

> This is the **current architecture** — achieved through phases 0-7. See [Implementation Checklist](05-implementation-checklist.md) for history.

```bash
src/shelfr/metadata/
├── __init__.py              # Public API (facade re-exports)
├── aggregator.py            # Merge logic (deterministic precedence)
├── orchestration.py         # fetch_all_metadata, build_sidecars, etc.
├── cleaning.py              # normalize_canonical() — THE cleaning entrypoint
├── models.py                # Shared Chapter dataclass
│
├── schemas/
│   └── canonical.py         # CanonicalMetadata, Person, Series, Genre
│
├── providers/
│   ├── base.py              # MetadataProvider protocol
│   ├── types.py             # LookupContext, ProviderResult, FieldName, IdType, ProviderKind
│   ├── registry.py          # ProviderRegistry (instance-based, stable ordering)
│   ├── audnex.py            # Primary network provider
│   ├── mediainfo.py         # Local technical metadata
│   ├── libation.py          # Folder structure parsing
│   ├── abs_sidecar.py       # Read existing ABS metadata.json (override provider)
│   └── mock.py              # MockProvider for tests
│
├── exporters/
│   ├── base.py              # MetadataExporter protocol
│   ├── json.py              # ABS metadata.json sidecar
│   └── opf.py               # OPF sidecar (moved in Phase 6)
│
└── mam/                     # MAM-specific (future extraction)
    ├── json_builder.py
    └── categories.py
```

**Key changes from original `metadata.py`:**

- God module → package with focused submodules
- Provider results in `providers/types.py` (not scattered schemas)
- `orchestration.py` (renamed from `pipeline.py` to avoid overloading)

---

## Schema Versioning

ABS JSON schema can evolve. Build in version awareness:

```python
class ABSJsonMetadata(BaseModel):
    """ABS metadata.json output schema."""

    # Schema version for future migrations
    _schema_version: ClassVar[str] = "1.0.0"

    title: str
    # ... fields ...

    @classmethod
    def get_version(cls) -> str:
        return cls._schema_version
```

When ABS changes fields later, add an adapter layer rather than breaking existing code.

---

## Testing Strategy

| Component | Test Type | What to Verify |
| --- | --- | --- |
| **Providers** | Unit | Given fixture input → correct canonical fragment |
| **Aggregator** | Unit | Precedence rules, merge determinism, conflict resolution |
| **Cleaning** | Unit + Golden | Normalization rules, edge cases, regression tests |
| **Exporters** | Snapshot | Output matches expected OPF/JSON exactly |
| **Orchestration** | Integration | End-to-end: input → sidecars on disk |

**Golden tests:** Use `tests/golden/` fixtures for real-world examples.

---

## Migration Strategy (Ship Value Fast)

See [Implementation Checklist](05-implementation-checklist.md) for the detailed phased approach.

**Summary sequence:**

| Step | What | Why |
| --- | --- | --- |
| 0 | Package scaffolding (`metadata.py` → `metadata/__init__.py`) | Unblocks the package layout |
| 1 | Extract MediaInfo (leaf module) | Cleanest extraction, no dependencies |
| 2–4 | Extract Formatting, Audnex client, MAM | Incremental decomposition |
| 5a | Introduce canonical schema | Single source of truth |
| 5b | Add provider system + aggregator | Deterministic merges |
| 5c | Add JSON exporter | First deliverable value |
| 6 | Move OPF into exporters | Share canonical + cleaning |
| 7 | Infrastructure (cache, events) | As needed |

**Rule:** Each step should be independently shippable and testable.

> **Fast path for JSON sidecar:** If the immediate goal is JSON sidecar, you can do **0 → 5a → 5c** before extracting MediaInfo/Formatting/Audnex. Schemas don't depend on the extraction phases.

---

## Recommended Approach

1. **Don't refactor everything at once** — too risky
2. **Phase 0 first** — scaffolding unblocks everything
3. **Build JSON sidecar in new location** (`metadata/exporters/json.py`)
4. **Create shared schemas** (`metadata/schemas/canonical.py`)
5. **Move OPF** after JSON works
6. **Break up `metadata.py`** incrementally over time

See [Implementation Checklist](05-implementation-checklist.md) for the detailed phased approach.

---

## File Size Summary

| Location | Lines | Status |
| --- | --- | --- |
| `metadata/` (total package) | ~6,100 | 🟢 Well-organized |
| `metadata/schemas/` | ~260 | 🟢 Canonical types |
| `metadata/providers/` | ~650 | 🟢 Provider system |
| `metadata/exporters/` | ~400 | 🟢 Exporter system |
| `metadata/opf/` | ~1,200 | 🟢 OPF generation |
| `schemas/*.py` | ~960 | 🟢 Validation schemas |
| `abs/` | ~1,800 | 🟢 ABS integration |
| `models.py` | ~320 | 🟢 Pipeline models |
| **Total metadata-related** | **~11,690** | 🟢 Clean architecture |
