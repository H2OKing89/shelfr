# Plugin Architecture for Metadata Providers

> Part of [Metadata Architecture Documentation](README.md)

---

## Overview

To support future metadata sources (Hardcover, Goodreads, OpenLibrary, private databases), we should design a **pluggable provider system** from the start.

**Core principles:**

- Providers emit partial canonical fields → Aggregator merges deterministically
- Per-field provenance tracking (`sources[field] = provider`) for debugging
- Config-driven enable/priority + aggregation strategy
- Private DB can override any field (killer feature for power users)

---

## 1. Current Sources

| Source | Type | Strengths | Weaknesses |
|--------|------|-----------|------------|
| **Audnex** | API | ASIN, chapters, accurate narrator/author | US-centric, no reviews |
| **MediaInfo** | Local (sync) | Bitrate, codec, duration, embedded tags | No book metadata |
| **Libation** | Local | Folder structure, series heuristics | Limited fields |
| **ABS metadata.json** | Local | User-corrected data | May be stale |

---

## 2. Potential Future Sources

| Source | What It Offers | Use Case |
|--------|----------------|----------|
| **Hardcover** | Better series data, edition tracking, reviews | Series-heavy libraries |
| **Goodreads** | Reviews, ratings, popularity | Social metadata |
| **OpenLibrary** | ISBN data, covers, open data | Fallback, legal covers |
| **Google Books** | ISBN → metadata lookup | ISBN-based discovery |
| **Private DB** | Personal corrections, custom fields | Power users |
| **MAM API** | Existing uploads, group data | Dupe checking |

---

## 3. Core Types

> These types prevent schema drift and match our actual pipeline (ASIN + path + existing sidecar).

```python
# metadata/providers/types.py
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

IdType = Literal["asin", "isbn", "goodreads_id", "hardcover_id"]

FieldName = Literal[
    # Book metadata
    "title", "subtitle", "authors", "narrators", "publisher",
    "language", "release_date", "series_name", "series_position",
    "genres", "summary", "cover_url",
    # Audio metadata (MediaInfo)
    "chapters", "duration_seconds", "codec", "bitrate", "channels", "container",
]
# Note: Consider migrating FieldName to an Enum later for validation/iteration.
# Literal is fine for typing, but Enum enables runtime checks and iteration.


@dataclass(frozen=True)
class LookupContext:
    """Everything a provider might need to look up metadata.
    
    Why not just identifier + id_type? Our pipeline uses:
    - asin (primary lookup)
    - m4b_path (MediaInfo extraction)
    - source_dir (Libation path heuristics)
    - existing_abs_json (user corrections from ABS sidecar)
    
    The `ids` dict is future-proof: adding goodreads_id/hardcover_id
    doesn't require changing this class signature.
    """
    ids: dict[IdType, str] = field(default_factory=dict)
    path: Path | None = None              # m4b or folder
    source_dir: Path | None = None        # Libation path (series heuristics)
    existing_abs_json: dict[str, Any] | None = None
    
    # Convenience properties for common IDs
    @property
    def asin(self) -> str | None:
        return self.ids.get("asin")
    
    @property
    def isbn(self) -> str | None:
        return self.ids.get("isbn")
    
    # Ergonomic constructors (frozen dataclass needs classmethods)
    @classmethod
    def from_id(
        cls,
        *,
        id_type: IdType,
        identifier: str,
        path: Path | None = None,
        source_dir: Path | None = None,
        existing_abs_json: dict[str, Any] | None = None,
    ) -> "LookupContext":
        return cls(
            ids={id_type: identifier},
            path=path,
            source_dir=source_dir,
            existing_abs_json=existing_abs_json,
        )
    
    @classmethod
    def from_asin(cls, *, asin: str, **kwargs) -> "LookupContext":
        return cls.from_id(id_type="asin", identifier=asin, **kwargs)
    
    @classmethod
    def from_isbn(cls, *, isbn: str, **kwargs) -> "LookupContext":
        return cls.from_id(id_type="isbn", identifier=isbn, **kwargs)


@dataclass
class ProviderResult:
    """Result from a metadata provider lookup.
    
    Note: `fields` uses typed FieldName keys, not free-form strings.
    This prevents schema drift across providers.
    """
    provider: str
    success: bool
    fields: dict[FieldName, Any] = field(default_factory=dict)
    confidence: dict[FieldName, float] = field(default_factory=dict)
    error: str | None = None
    cached: bool = False
    cache_age_seconds: int | None = None
```

---

## 4. Provider Protocol

> Use `Protocol` (duck typing) for flexibility with mocks and plugins. Don't mix with `ABC`.
> 
> **Simplification:** One protocol, all providers implement `async fetch()`. Sync providers wrap their own sync work with `asyncio.to_thread()`. This keeps the aggregator dead simple.

```python
# metadata/providers/base.py
from typing import Literal, Protocol, runtime_checkable
from .types import LookupContext, ProviderResult, IdType

ProviderKind = Literal["local", "network"]


@runtime_checkable
class MetadataProvider(Protocol):
    """Protocol for pluggable metadata providers.
    
    Use Protocol (not ABC) for:
    - Easy mock providers in tests
    - Duck typing (no inheritance required)
    - Runtime checking with @runtime_checkable if needed
    
    All providers implement async fetch(). Sync providers (MediaInfo)
    wrap their subprocess work with asyncio.to_thread() internally.
    This keeps the aggregator simple — it doesn't care who's sync vs async.
    
    Conventional defaults (Protocol can't enforce, but providers should follow):
    - kind = "network"  (most providers are network-based)
    - is_override = False  (only abs_sidecar/private_db can clear fields)
    Consider creating a ProviderBase mixin if you want to avoid repeating these.
    """
    
    name: str              # "audnex", "hardcover", "mediainfo"
    priority: int          # Lower = higher priority (0 = primary)
    kind: ProviderKind     # "local" (cheap) or "network" (expensive)
    is_override: bool      # True for abs_sidecar/private_db (can clear fields)
    
    def can_lookup(self, ctx: LookupContext, id_type: IdType) -> bool:
        """Check if provider can handle this lookup context.
        
        Args:
            ctx: Full lookup context (ASIN, path, existing metadata, etc.)
            id_type: Which identifier to use for lookup
        """
        ...
    
    async def fetch(self, ctx: LookupContext, id_type: IdType) -> ProviderResult:
        """Fetch metadata from this provider.
        
        For sync providers (MediaInfo), implement as:
            async def fetch(self, ctx, id_type):
                return await asyncio.to_thread(self._fetch_sync, ctx, id_type)
        """
        ...
```

---

## 5. Provider Registry

> Instance-based (not class methods with global state) for testability.

```python
# metadata/providers/registry.py
from __future__ import annotations
from dataclasses import dataclass, field as dataclass_field
from .base import MetadataProvider
from .types import LookupContext, IdType


@dataclass
class ProviderRegistry:
    """Registry for metadata providers.
    
    Instance-based for testability (new registry per test).
    """
    _providers: dict[str, MetadataProvider] = dataclass_field(default_factory=dict)
    
    def register(self, provider: MetadataProvider) -> None:
        """Register a provider."""
        self._providers[provider.name] = provider
    
    def get(self, name: str) -> MetadataProvider | None:
        """Get provider by name."""
        return self._providers.get(name)
    
    def all(self) -> list[MetadataProvider]:
        """All registered providers in priority order (lowest first).
        
        Stable sort: (priority, name) prevents jitter when priorities tie.
        """
        return sorted(self._providers.values(), key=lambda p: (p.priority, p.name))
    
    def get_for_context(
        self, ctx: LookupContext, id_type: IdType
    ) -> list[MetadataProvider]:
        """Get all providers that can handle this context, in priority order."""
        return [p for p in self.all() if p.can_lookup(ctx, id_type)]


# Default registry for CLI runtime.
# WARNING: Tests should always instantiate their own registry to avoid leaking state.
default_registry = ProviderRegistry()
```

---

## 6. Metadata Aggregator

> Lives at `metadata/aggregator.py` (not in providers/) — it's core, not a plugin.

### 6.1 Core Merge Rules

Before looking at code, these rules prevent subtle bugs:

1. **Skip failed results:** `success=False` → ignore entirely (don't let errors overwrite good data)
2. **Skip empty values:** `None`, `""`, `[]` are not valid data (unless provider is an override provider)
3. **Override providers are special:** `abs_sidecar` and `private_db` can set empty values intentionally (user wants to clear a field)
4. **Deterministic tie-breakers:** confidence → priority → quality (no randomness)

### 6.2 Two-Stage Fetch (Efficient `stop_on_complete`)

To actually save work when `stop_on_complete=True`:

```
Stage 1: Run "cheap locals" first (ABS sidecar, MediaInfo, Libation)
         → Check if required_fields are filled
Stage 2: Run network providers only if still missing required fields
```

This avoids hammering Audnex/Hardcover when a sidecar already has needed values.

### 6.3 Implementation

```python
# metadata/aggregator.py
import asyncio
from dataclasses import dataclass, field
from typing import Any

from .providers.types import LookupContext, ProviderResult, FieldName, IdType
from .providers.base import MetadataProvider
from .providers.registry import ProviderRegistry, default_registry


@dataclass
class FieldConflict:
    """Record of a field conflict between providers."""
    field: FieldName
    values: dict[str, Any]      # provider_name -> value
    resolved_value: Any
    resolution_reason: str      # "priority", "confidence", "quality"


@dataclass
class AggregatedResult:
    """Aggregated metadata from multiple providers."""
    metadata: CanonicalMetadata
    sources: dict[FieldName, str]   # field -> provider that provided it
    conflicts: list[FieldConflict]  # Fields where providers disagreed
    missing: list[FieldName]        # Fields no provider had


class MetadataAggregator:
    """Aggregate metadata from multiple providers with conflict resolution.
    
    Merge strategy tie-breaker order (deterministic, no randomness):
    1. Higher confidence score
    2. Lower provider priority (more trusted)
    3. Value quality heuristic (non-empty > empty, longer summary > shorter)
    """
    
    def __init__(
        self,
        registry: ProviderRegistry | None = None,
        merge_strategy: str = "confidence",
        required_identifiers: set[IdType] | None = None,
    ):
        """
        Args:
            registry: Provider registry (defaults to global)
            merge_strategy: How to resolve conflicts
                - "priority": Use highest-priority provider's value
                - "confidence": Use highest-confidence value per field
            required_identifiers: At least one must be present to fetch.
                None means no requirement (useful for local-only operations).
        """
        self.registry = registry or default_registry
        self.merge_strategy = merge_strategy
        self.required_identifiers = required_identifiers  # None = no requirement
    
    async def fetch_all(
        self,
        ctx: LookupContext,
        id_type: IdType = "asin",
        *,
        providers: list[str] | None = None,
        stop_on_complete: bool = True,
        required_fields: list[FieldName] | None = None,
    ) -> AggregatedResult:
        """Fetch from multiple providers and merge results.
        
        Two-stage fetch when stop_on_complete=True:
        1. Run local providers first (cheap, parallelized)
        2. Run network providers only if required_fields still missing
        """
        # Validate identifiers early (if required_identifiers is set)
        if self.required_identifiers and not (self.required_identifiers & set(ctx.ids.keys())):
            raise ValueError(f"Missing required identifiers: {sorted(self.required_identifiers)}")
        
        required = set(required_fields or ["title"])
        
        # Get applicable providers
        if providers:
            provider_list = [self.registry.get(n) for n in providers if self.registry.get(n)]
        else:
            provider_list = self.registry.get_for_context(ctx, id_type)
        
        # Split by kind attribute (not hardcoded names)
        local_providers = [p for p in provider_list if p.kind == "local"]
        network_providers = [p for p in provider_list if p.kind == "network"]
        
        # Stage 1: Run local providers (cheap, can parallelize)
        results: list[ProviderResult] = []
        if local_providers:
            stage1 = await asyncio.gather(*(p.fetch(ctx, id_type) for p in local_providers))
            results.extend(stage1)
        
        # Check if we can skip network calls
        if stop_on_complete:
            filled = self._get_filled_fields(results)
            if required.issubset(filled):
                return self._merge(results, provider_list)
        
        # Stage 2: Run network providers
        for provider in network_providers:
            result = await provider.fetch(ctx, id_type)
            results.append(result)
        
        return self._merge(results, provider_list)
    
    def _merge(
        self,
        results: list[ProviderResult],
        providers: list[MetadataProvider],
    ) -> AggregatedResult:
        """Merge multiple provider results into canonical metadata.
        
        Core rules:
        - Skip success=False results
        - Skip empty values (unless from override provider via is_override flag)
        """
        # Build provider lookup for is_override check
        provider_map = {p.name: p for p in providers}
        # Implementation: iterate fields, apply strategy, track conflicts
        ...
    
    def _get_filled_fields(self, results: list[ProviderResult]) -> set[FieldName]:
        """Get all fields that have non-empty values."""
        filled: set[FieldName] = set()
        for result in results:
            if not result.success:
                continue
            for field, value in result.fields.items():
                if not self._is_empty(value):
                    filled.add(field)
        return filled
    
    def _is_empty(self, value: Any) -> bool:
        """Check if a value is considered empty."""
        return value is None or value == "" or value == []
    
    def _should_skip_empty(
        self,
        provider: MetadataProvider,
        field: FieldName,
        value: Any,
    ) -> bool:
        """Check if an empty value should be skipped.
        
        Override providers (is_override=True) can set empty values
        intentionally — user wants to clear a field.
        """
        if provider.is_override:
            return False  # Override providers can set empty
        return self._is_empty(value)
    
    def _resolve_conflict(
        self,
        field: FieldName,
        candidates: dict[str, tuple[Any, float, int]],  # provider -> (value, confidence, priority)
    ) -> tuple[Any, str]:
        """Resolve a field conflict using deterministic tie-breakers.
        
        Returns:
            (resolved_value, resolution_reason) where reason is one of:
            - "priority": priority was the deciding factor
            - "confidence": confidence score was the deciding factor
            - "quality": tie-breaker (e.g., longer summary wins)
        """
        if self.merge_strategy == "priority":
            # Lowest priority number wins
            winner = min(candidates.items(), key=lambda x: x[1][2])
            return winner[1][0], "priority"
        
        # Confidence strategy with tie-breakers
        # Track which factor actually broke the tie
        sorted_candidates = sorted(candidates.items(), key=lambda x: (-x[1][1], x[1][2]))
        
        if len(sorted_candidates) == 1:
            return sorted_candidates[0][1][0], "confidence"
        
        top = sorted_candidates[0]
        second = sorted_candidates[1]
        
        # What broke the tie?
        if top[1][1] != second[1][1]:
            reason = "confidence"
        elif top[1][2] != second[1][2]:
            reason = "priority"
        else:
            reason = "quality"
        
        return top[1][0], reason
    
    def _value_quality(self, field: FieldName, value: Any) -> int:
        """Heuristic quality score for tie-breaking."""
        if value is None or value == "" or value == []:
            return 0
        if field == "summary" and isinstance(value, str):
            return len(value)  # Longer summaries usually better
        return 1
```

---

## 7. Mapping Current Code to Providers

Your current `metadata.py` becomes **four providers** without changing behavior:

### 7.1 AudnexProvider

```python
# metadata/providers/audnex.py
class AudnexProvider:
    """Audnex API provider (primary source for audiobook metadata)."""
    
    name = "audnex"
    priority = 0  # Primary
    kind = "network"
    is_override = False
    
    EMITS: set[FieldName] = {
        "title", "subtitle", "authors", "narrators", "publisher",
        "language", "release_date", "genres", "summary", "cover_url",
        "series_name", "series_position", "chapters",
    }
    
    def can_lookup(self, ctx: LookupContext, id_type: IdType) -> bool:
        return id_type == "asin" and ctx.asin is not None
    
    async def fetch(self, ctx: LookupContext, id_type: IdType) -> ProviderResult:
        # Wraps: fetch_audnex_book, fetch_audnex_chapters, fetch_audnex_author
        ...
```

### 7.2 MediaInfoProvider

```python
# metadata/providers/mediainfo.py
import asyncio

class MediaInfoProvider:
    """MediaInfo provider (local, sync subprocess wrapped in async)."""
    
    name = "mediainfo"
    priority = 5
    kind = "local"
    is_override = False
    
    EMITS: set[FieldName] = {
        "duration_seconds", "codec", "bitrate", "channels", "container",
        "chapters",  # Fallback if Audnex chapters unavailable
    }
    
    def can_lookup(self, ctx: LookupContext, id_type: IdType) -> bool:
        return ctx.path is not None and ctx.path.exists()
    
    async def fetch(self, ctx: LookupContext, id_type: IdType) -> ProviderResult:
        # Wrap sync subprocess in threadpool
        return await asyncio.to_thread(self._fetch_sync, ctx, id_type)
    
    def _fetch_sync(self, ctx: LookupContext, id_type: IdType) -> ProviderResult:
        # Wraps: run_mediainfo, detect_audio_format, _parse_chapters_from_mediainfo
        ...
```

### 7.3 LibationProvider

```python
# metadata/providers/libation.py
import asyncio

class LibationProvider:
    """Libation path heuristics provider (series fallback)."""
    
    name = "libation"
    priority = 20  # Lower priority than Audnex
    kind = "local"
    is_override = False
    
    EMITS: set[FieldName] = {"series_name", "series_position"}
    
    def can_lookup(self, ctx: LookupContext, id_type: IdType) -> bool:
        return ctx.source_dir is not None
    
    async def fetch(self, ctx: LookupContext, id_type: IdType) -> ProviderResult:
        return await asyncio.to_thread(self._fetch_sync, ctx, id_type)
    
    def _fetch_sync(self, ctx: LookupContext, id_type: IdType) -> ProviderResult:
        # Wraps: resolve_series() + path heuristics
        # Lower confidence than Audnex, but valuable fallback
        return ProviderResult(
            provider=self.name,
            success=True,
            fields={"series_name": ..., "series_position": ...},
            confidence={"series_name": 0.6, "series_position": 0.6},
        )
```

### 7.4 AbsSidecarProvider

```python
# metadata/providers/abs_sidecar.py
class AbsSidecarProvider:
    """ABS metadata.json provider (user corrections).
    
    This is an OVERRIDE provider: it can intentionally set empty values
    (user wants to clear a field that Audnex got wrong).
    """
    
    name = "abs_sidecar"
    priority = 2  # High priority when enabled (user corrections are trusted)
    kind = "local"
    is_override = True  # Can intentionally clear fields
    
    def can_lookup(self, ctx: LookupContext, id_type: IdType) -> bool:
        return ctx.existing_abs_json is not None
    
    async def fetch(self, ctx: LookupContext, id_type: IdType) -> ProviderResult:
        # Sync operation, but trivial (just dict access)
        data = ctx.existing_abs_json
        # High confidence for fields that exist (user-corrected)
        ...
```

---

## 8. Provider Lifecycle

> Network providers need proper client management.

```python
# Option A: Context manager (recommended for long-running processes)
class HardcoverProvider:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None
    
    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            base_url="https://api.hardcover.app",
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        return self
    
    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

# Option B: Create client per-request (simpler, slower)
async def fetch(self, ctx, id_type):
    async with httpx.AsyncClient(...) as client:
        resp = await client.get(...)
```

> **Note:** For batch processing (shelfr's primary use case), Option A (context manager) is recommended. Creating a client per-request would hammer connection setup.

---

## 9. Configuration

> **Source of truth:** Provider classes define their own `kind`, `is_override`, and default `priority` as class attributes. Config **overrides** these defaults at runtime, allowing priority tuning without code changes. If a provider attribute isn't in config, the class default is used.

```yaml
# config/config.yaml
metadata:
  providers:
    audnex:
      enabled: true
      priority: 0       # Override class default if needed
      # kind: network   # Omit to use class default
      regions: ["us", "uk", "au"]
    
    mediainfo:
      enabled: true
      priority: 5
    
    libation:
      enabled: true
      priority: 20
    
    abs_sidecar:
      enabled: true
      priority: 2  # High priority (user corrections)
      # is_override: true is the class default
    
    hardcover:
      enabled: false
      priority: 10
      api_key: ${HARDCOVER_API_KEY}
    
    private_db:
      enabled: false
      priority: 1  # Highest priority when enabled
      # is_override: true is the class default
      connection_string: ${PRIVATE_DB_URL}
  
  aggregation:
    strategy: "confidence"  # priority | confidence
    # Identifiers are not FieldNames - they're lookup keys
    # Use null/empty for local-only operations (e.g., "analyze audio")
    required_identifiers: ["asin"]  # At least one must be present to fetch
    required_fields: ["title"]       # Merged result must have these
    stop_on_complete: true
    cache_ttl_hours: 24
```

---

## 10. Directory Structure

```bash
src/shelfr/metadata/
├── __init__.py           # Public API (facade re-exports)
├── models.py             # Chapter (shared small types); avoids collision with providers/types.py
├── aggregator.py         # Multi-provider merge logic (CORE, not in providers/)
├── cleaning.py           # Facade over utils/naming
├── orchestration.py      # fetch_all_metadata, etc.
│
├── schemas/
│   └── canonical.py      # Person, Series, Genre, CanonicalMetadata
│
├── providers/
│   ├── __init__.py       # Registry exports
│   ├── types.py          # LookupContext, ProviderResult, FieldName, IdType
│   ├── base.py           # MetadataProvider protocol
│   ├── registry.py       # ProviderRegistry (instance-based)
│   ├── audnex.py         # Audnex provider
│   ├── mediainfo.py      # MediaInfo provider (async wrapper around sync)
│   ├── libation.py       # Libation heuristics
│   ├── abs_sidecar.py    # ABS metadata.json reader
│   ├── hardcover.py      # Future: Hardcover
│   └── private_db.py     # Future: Private database
│
├── formatting/           # BBCode, HTML
├── mam/                  # MAM JSON builder (consumer of aggregator)
├── opf/                  # OPF sidecar
└── json/                 # JSON sidecar
```

---

## 11. Usage Example

```python
from shelfr.metadata.aggregator import MetadataAggregator
from shelfr.metadata.providers import (
    ProviderRegistry,
    AudnexProvider,
    MediaInfoProvider,
    LibationProvider,
)
from shelfr.metadata.providers.types import LookupContext

# Create registry (instance-based for testability)
registry = ProviderRegistry()
registry.register(AudnexProvider())
registry.register(MediaInfoProvider())
registry.register(LibationProvider())

# Create lookup context with ids dict (extensible for future ID types)
ctx = LookupContext(
    ids={"asin": "B0CJ1234"},
    path=Path("/path/to/book.m4b"),
    source_dir=Path("/libation/Author/Series/Book"),
)

# Or use convenience args that populate ids internally:
ctx = LookupContext.from_asin(
    asin="B0CJ1234",
    path=Path("/path/to/book.m4b"),
    source_dir=Path("/libation/Author/Series/Book"),
)

# Fetch with aggregation
aggregator = MetadataAggregator(registry=registry, merge_strategy="confidence")
result = await aggregator.fetch_all(ctx, id_type="asin")

# Use the merged metadata
print(result.metadata.title)
print(result.sources)      # {"title": "audnex", "chapters": "mediainfo", "series_name": "libation"}
print(result.conflicts)    # Any disagreements (with resolution reasons)
print(result.missing)      # Fields no provider had
```

---

## 12. Benefits

| Benefit | Description |
|---------|-------------|
| **Extensibility** | Add new sources without touching core code |
| **Fallback chain** | If Audnex fails, try Hardcover, then Libation heuristics |
| **Field-level sourcing** | Use best source for each field |
| **User corrections** | Private DB / ABS sidecar can override any field |
| **Testing** | Instance-based registry = new registry per test |
| **Debugging** | `sources` dict shows exactly where each field came from |
| **Deterministic** | Tie-breakers prevent "whoever ran last wins" |

---

## 13. Implementation Priority

| Phase | What to Build |
|-------|---------------|
| **Phase 5** | Define `LookupContext`, `ProviderResult`, `MetadataProvider` protocol |
| **Phase 5** | Create `ProviderRegistry` (instance-based) |
| **Phase 5** | Extract `AudnexProvider` from `metadata/__init__.py` |
| **Phase 5** | Create basic `MetadataAggregator` |
| **Phase 7** | Add `MediaInfoProvider`, `LibationProvider`, `AbsSidecarProvider` |
| **Future** | Add `HardcoverProvider`, `GoodreadsProvider`, `PrivateDbProvider`
