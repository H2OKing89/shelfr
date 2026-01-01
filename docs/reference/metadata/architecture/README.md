# Metadata Architecture Documentation

> **Date:** January 1, 2026  
> **Status:** Audit Complete - Refactor Recommended  
> **Related:** [JSON Sidecar Discovery](../../../implementation/json-sidecar-discovery.md) | [Naming System](../naming/NAMING.md)

---

## Overview

This folder contains the comprehensive metadata architecture documentation for shelfr. The documentation is organized into focused modules for easier navigation and maintenance.

## Quick Links

| Document | Description |
|----------|-------------|
| [Current State Audit](01-current-state-audit.md) | Analysis of existing files, duplicates, and issues |
| [Recommendations](02-recommendations.md) | Phased refactoring plan and migration strategy |
| [Plugin Architecture](03-plugin-architecture.md) | Provider system for extensible metadata sources |
| [Future-Proofing](04-future-proofing.md) | Exporters, caching, events, and infrastructure |
| [Implementation Checklist](05-implementation-checklist.md) | Actionable task list by phase |

---

## Executive Summary

The current metadata handling is **fragmented across 8+ files** with significant code duplication, unclear boundaries, and overlapping schemas. A refactor into a unified `src/shelfr/metadata/` package is recommended before adding JSON sidecar support.

### Key Issues

| Issue | Severity | Impact |
|-------|----------|--------|
| `metadata.py` is 2040 lines (god module) | 🔴 High | Hard to maintain, test, navigate |
| 3+ duplicate schema definitions | 🔴 High | Risk of drift, confusion |
| OPF module isolated from main metadata | 🟡 Medium | Can't share cleaners/helpers |
| No unified data flow | 🟡 Medium | Each feature reinvents transformations |
| Naming config scattered | 🟡 Medium | `opf/helpers.py` vs `utils/naming.py` |

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
|-------|-------|--------|------|
| **Providers** | ASIN, path, etc. | Partial canonical fragments | Each provider returns what it knows |
| **Aggregator** | Multiple fragments | Merged CanonicalMetadata | Precedence rules resolve conflicts |
| **Cleaning** | Raw CanonicalMetadata | Normalized CanonicalMetadata | Single entrypoint: `normalize_canonical()` |
| **Exporters** | Clean CanonicalMetadata | OPF, JSON, etc. | Assume input is already clean |

**Critical invariant:** Exporters should NEVER clean fields themselves. All normalization happens in one place (`cleaning.py`). This prevents duplicate logic, inconsistent behavior, and bugs where "OPF cleans differently than JSON."

---

## Precedence Rules

When multiple providers have data for the same field, use these rules:

| Field Category | Priority Order | Rationale |
|----------------|----------------|-----------|
| **Identifiers** (ASIN, ISBN) | Audnex > ABS local > Libation | Audnex is authoritative for ASINs |
| **Title/Subtitle/Series** | Audnex > ABS local (if trusted) > Libation | Audnex normalizes Audible's mess |
| **Authors** | Audnex > ABS local > Libation | Audnex has author ASINs |
| **Narrators** | MediaInfo (embedded) > Audnex > ABS local | Embedded tags are definitive |
| **Runtime/Chapters** | MediaInfo > Audnex | MediaInfo is ground truth for audio |
| **Cover** | Local folder > Audnex | Local may have higher-res |
| **Genres/Tags** | Merge all sources | More is better, dedupe later |
| **Description** | Audnex > ABS local | Audnex has full HTML descriptions |

**Trust levels:**
- `audnex`: High (authoritative API)
- `mediainfo`: High (ground truth for audio)
- `abs_local`: Medium (user-corrected, may be stale)
- `libation`: Low (folder structure, limited fields)

---

## Public API

The package exposes a clean, minimal API:

```python
from shelfr.metadata import (
    # Core pipeline
    get_metadata,       # Fetch + merge from providers
    normalize,          # Clean a CanonicalMetadata instance
    export,             # Render to one or more formats
    build_sidecars,     # Convenience: get + normalize + export
    
    # Types
    CanonicalMetadata,  # The canonical data model
    ProviderResult,     # What providers return
    ExportResult,       # What exporters return
)

# Simple usage
metadata = await get_metadata(asin="B08G9PRS1K", providers=["audnex", "mediainfo"])
metadata = normalize(metadata)
await export(metadata, formats=["opf", "abs_json"], output_dir=book_path)

# Or all-in-one
await build_sidecars(book_path, asin="B08G9PRS1K", formats=["opf", "abs_json"])
```

---

## Target Module Structure

```bash
src/shelfr/metadata/
├── __init__.py           # Public API (re-exports from submodules)
├── pipeline.py           # Orchestration: get_metadata, build_sidecars
├── cleaning.py           # normalize_canonical() - THE cleaning entrypoint
├── conventions.py        # Language mapping, series formatting, title casing
├── aggregator.py         # Multi-provider merge logic with precedence
│
├── schemas/              # All Pydantic schemas (SINGLE SOURCE OF TRUTH)
│   ├── __init__.py       # Re-exports CanonicalMetadata, Person, Series, etc.
│   ├── canonical.py      # CanonicalMetadata, Person, Series, Genre
│   ├── abs_json.py       # ABSJsonMetadata (versioned output schema)
│   ├── opf.py            # OPFMetadata, OPFCreator, etc.
│   └── results.py        # ProviderResult, AggregatedResult, ExportResult
│
├── providers/            # Pluggable metadata sources
│   ├── __init__.py       # ProviderRegistry, base protocol
│   ├── base.py           # MetadataProvider protocol
│   ├── audnex.py         # Primary provider (from metadata.py)
│   ├── mediainfo.py      # Technical metadata (from metadata.py)
│   ├── libation.py       # Folder structure parsing
│   └── abs_local.py      # Read existing ABS metadata.json
│
├── exporters/            # Pluggable output formats
│   ├── __init__.py       # ExporterRegistry, base protocol
│   ├── base.py           # MetadataExporter protocol
│   ├── opf.py            # OPF sidecar (from opf/)
│   └── abs_json.py       # ABS JSON sidecar (NEW)
│
└── mam/                  # MAM-specific (future extraction)
    ├── __init__.py
    ├── json_builder.py
    └── categories.py
```

**Key changes from original:**
- `helpers.py` → `conventions.py` (avoids junk drawer)
- `canonical.py` only in `schemas/` (re-exported from `__init__.py`)
- Added `pipeline.py` (orchestration entrypoint)
- Added `schemas/results.py` (provider/exporter result types)

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
|-----------|-----------|----------------|
| **Providers** | Unit | Given fixture input → correct canonical fragment |
| **Aggregator** | Unit | Precedence rules, merge determinism, conflict resolution |
| **Cleaning** | Unit + Golden | Normalization rules, edge cases, regression tests |
| **Exporters** | Snapshot | Output matches expected OPF/JSON exactly |
| **Pipeline** | Integration | End-to-end: input → sidecars on disk |

**Golden tests:** Use `tests/golden/` fixtures for real-world examples.

---

## Migration Strategy (Ship Value Fast)

Safest sequence that keeps momentum:

| Step | What | Why |
|------|------|-----|
| 1 | Create `schemas/canonical.py` | Single source of truth |
| 2 | Implement JSON exporter first | Core need (ABS JSON sidecar) |
| 3 | Write aggregator with 2 providers | Audnex + MediaInfo (minimum useful combo) |
| 4 | Add `cleaning.py` with `normalize_canonical()` | Central cleaning entrypoint |
| 5 | Move OPF into exporters | Reuse canonical + cleaning |
| 6 | Add `pipeline.py` | Orchestration entrypoint |
| 7 | Chip away at `metadata.py` | Replace call sites gradually |

**Rule:** Each step should be independently shippable and testable.

---

## Recommended Approach

1. **Don't refactor everything at once** - too risky
2. **Build JSON sidecar in new location** (`metadata/exporters/abs_json.py`)
3. **Create shared schemas** (`metadata/schemas/canonical.py`)
4. **Move OPF** after JSON works
5. **Break up `metadata.py`** incrementally over time

See [Implementation Checklist](05-implementation-checklist.md) for detailed tasks.

---

## File Size Summary

| Current Location | Lines | Status |
|-----------------|-------|--------|
| `metadata.py` | 2,040 | 🔴 Too large, split needed |
| `opf/` (total) | ~1,234 | 🟢 Well-structured |
| `schemas/*.py` | ~400 | 🟡 OK but duplicates |
| `abs/rename.py` | 1,145 | 🟡 Has schema duplicate |
| `models.py` | 316 | 🟢 OK |
| **Total metadata-related** | **~5,135** | Mix of good and problematic |
