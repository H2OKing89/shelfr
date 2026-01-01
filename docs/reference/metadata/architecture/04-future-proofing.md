# Future-Proofing Considerations

> Part of [Metadata Architecture Documentation](README.md)

---

## 1. Output Exporters (Inverse of Providers)

Providers fetch metadata **in**, but we also need pluggable **exporters** for output formats:

```python
# metadata/exporters/base.py
from typing import Protocol
from pathlib import Path

class MetadataExporter(Protocol):
    """Protocol for pluggable output formats.
    
    Mirrors provider architecture with registry pattern.
    """
    
    name: str  # "opf", "json", "nfo", "cue"
    file_extension: str  # ".opf", ".json", ".nfo"
    
    def render(self, metadata: CanonicalMetadata, **options) -> str | bytes:
        """Generate output content from canonical metadata.
        
        Returns str for text formats (OPF, JSON, NFO, MD),
        bytes for binary formats (future: zip, images).
        """
        ...
    
    def output_path(self, base_dir: Path, **options) -> Path:
        """Compute default output path for this exporter.
        
        Different exporters may use different naming conventions:
        - OPF: {asin}.opf
        - JSON: metadata.json
        - NFO: {title}.nfo
        """
        ...
    
    def write(self, metadata: CanonicalMetadata, base_dir: Path, **options) -> Path:
        """Write to file with atomic write + proper encoding, return final path.
        
        Implementation note: use a shared helper for atomic writes:
        - Write to tmp file in same directory
        - os.replace(tmp, final) for atomicity
        - Text encoding for str, binary mode for bytes
        """
        ...


# metadata/exporters/registry.py
from __future__ import annotations

from dataclasses import dataclass, field

from .base import MetadataExporter


@dataclass
class ExporterRegistry:
    """Registry for exporters (mirrors ProviderRegistry pattern)."""
    _exporters: dict[str, MetadataExporter] = field(default_factory=dict)
    
    def register(self, exporter: MetadataExporter) -> None:
        self._exporters[exporter.name] = exporter
    
    def get(self, name: str) -> MetadataExporter | None:
        return self._exporters.get(name)
    
    def all(self) -> list[MetadataExporter]:
        # Stable order: by name
        return sorted(self._exporters.values(), key=lambda e: e.name)
```

**Potential exporters:**

- `OPFExporter` - Current OPF generator
- `JsonExporter` - ABS metadata.json
- `NFOExporter` - Kodi/Plex NFO format
- `CueExporter` - CUE sheets for chapter markers
- `M3UExporter` - Playlist generation
- `MarkdownExporter` - Human-readable summary

> **When to build:** Extract to this pattern when you add a third format. Current OPF/JSON generation works fine.

---

## 2. Caching Layer (Shared Infrastructure)

Don't let each provider implement caching differently:

```python
# metadata/cache.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from .providers.types import FieldName, IdType
from .schemas.versioning import SCHEMA_VERSION


def make_cache_key(provider: str, id_type: IdType, identifier: str, region: str = "us") -> str:
    """Build versioned cache key — auto-invalidates when schema changes.
    
    Note: region param is intentional for providers like Audnex that
    return different results per region.
    """
    return f"{SCHEMA_VERSION}:{provider}:{id_type}:{identifier}:{region}"


@dataclass(frozen=True)
class CachedResult:
    """What we store in cache — enough to reconstruct ProviderResult."""
    fields: dict[FieldName, Any]
    confidence: dict[FieldName, float]
    fetched_at: datetime  # Should be timezone-aware: datetime.now(timezone.utc)
    schema_version: str = SCHEMA_VERSION


class MetadataCache(Protocol):
    """Abstract caching interface."""
    
    async def get(self, key: str) -> CachedResult | None: ...
    async def set(self, key: str, value: CachedResult, ttl_seconds: int) -> None: ...
    async def invalidate(self, key: str) -> None: ...
    async def invalidate_pattern(self, pattern: str) -> None: ...


# Implementations
class FileCache(MetadataCache):
    """JSON file-based cache (current approach)."""

class SqliteCache(MetadataCache):
    """SQLite for larger datasets."""

class RedisCache(MetadataCache):
    """Redis for distributed/multi-instance setups."""
```

**Key design decisions:**

1. **Schema version in cache key** — old entries auto-invalidate when `CanonicalMetadata` changes
2. **Cache stores provenance** — `confidence`, `fetched_at` survive cache round-trip
3. **Apply cache at provider boundary** — network providers get most benefit
4. **Migration lives in IO layer** — readers/writers migrate, aggregator stays dumb

---

## 3. Event Hooks / Middleware

> **YAGNI Note:** Structured logging gives you 80% of this. Add events when you actually need Discord alerts or external integrations.

Allow instrumentation without modifying core code:

```python
# metadata/events.py
import inspect
import logging
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class EventBus:
    """Event system for metadata operations.
    
    Instance-based (not class-level globals) for test isolation.
    Pass into ProviderRegistry / Aggregator / Orchestration.
    """
    _handlers: dict[str, list[Callable]] = field(default_factory=dict)
    
    # Event type constants
    PROVIDER_FETCH_START = "provider.fetch.start"
    PROVIDER_FETCH_SUCCESS = "provider.fetch.success"
    PROVIDER_FETCH_ERROR = "provider.fetch.error"
    AGGREGATION_CONFLICT = "aggregation.conflict"
    EXPORT_COMPLETE = "export.complete"
    
    def on(self, event: str, handler: Callable) -> None:
        """Register event handler."""
        self._handlers.setdefault(event, []).append(handler)
    
    async def emit(self, event: str, data: dict) -> None:
        """Emit event to all handlers (with error isolation)."""
        for handler in self._handlers.get(event, []):
            try:
                result = handler(data)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception("Event handler failed", extra={"event": event})


# Usage (instance-based, not global)
event_bus = EventBus()
event_bus.on("provider.fetch.error", send_discord_alert)
event_bus.on("aggregation.conflict", log_conflict_for_review)

# Pass to aggregator
aggregator = MetadataAggregator(registry=registry, event_bus=event_bus)
```

---

## 4. Schema Versioning & Migration

When `CanonicalMetadata` changes, we need to handle old cached data:

```python
# metadata/schemas/versioning.py
SCHEMA_VERSION = "2.0.0"

class VersionedMetadata(BaseModel):
    """Wrapper with version tracking."""
    
    schema_version: str = SCHEMA_VERSION
    data: CanonicalMetadata
    migrated_from: str | None = None  # Previous version if migrated


def migrate_metadata(data: dict, from_version: str) -> CanonicalMetadata:
    """Migrate old schema versions to current."""
    migrations = {
        "1.0.0": migrate_v1_to_v2,
        "1.5.0": migrate_v1_5_to_v2,
    }
    # Apply migrations in order...
```

**Best places to enforce versioning:**

1. **Cache reads** — migrate old entries on read
2. **Sidecar IO** — write `schema_version` to `metadata.json`/`.opf`
3. **Provider sidecar readers** — migrate old sidecars → emit canonical fields

Aggregator stays version-agnostic.

---

## 5. Field Mapping Configuration

> **Defer this.** Hardcoded mappings in each provider are fine until you have 5+ providers or non-developers configuring them. Nested mapping like `authors[].name` becomes a mini-language that's harder to debug than code.

External config for provider → canonical field mapping (optional convenience layer):

```yaml
# config/provider_mappings.yaml (FUTURE - not required for v1)
hardcover:
  title: title
  subtitle: subtitle
  series.name: series_primary.name
  series.position: series_primary.position
  authors[].name: authors[].name
  published_date: release_date  # Different field name
```

**If you build it later:**

```python
# JsonMappingProvider for "simple JSON API" providers
class JsonMappingProvider(BaseProvider):
    """Quick wins for simple APIs via config-driven mapping."""
    
    def __init__(self, name: str, mapping: dict[str, str], ...):
        self.mapping = mapping
        ...
```

---

## 6. Data Provenance / Audit Trail

Your `AggregatedResult` already tracks `sources[field] = provider` and `conflicts[]`. Extend it rather than adding a separate tracker:

```python
@dataclass
class FieldProvenance:
    """Detailed origin info for a single field."""
    provider: str
    confidence: float
    fetched_at: datetime | None = None
    cached: bool = False


@dataclass
class AggregatedResult:
    """Aggregated metadata from multiple providers."""
    metadata: CanonicalMetadata
    sources: dict[FieldName, str]           # field -> winning provider
    provenance: dict[FieldName, list[FieldProvenance]]  # field -> all candidates (descending confidence)
    conflicts: list[FieldConflict]          # Fields where providers disagreed
    missing: list[FieldName]                # Fields no provider had
    
    # Timing info for debugging
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    provider_timings: dict[str, float] = field(default_factory=dict)  # provider -> seconds


# Usage: debugging UI can show "why did series_name come from libation?"
# provenance["series_name"][0] is always the winner (highest confidence)
for candidate in result.provenance["series_name"]:
    print(f"  {candidate.provider}: confidence={candidate.confidence}")
```

This keeps provenance co-located with the result rather than requiring a separate tracking system.

---

## 7. Batch Operations

Some APIs support bulk lookups — design for it using `LookupContext`:

```python
class MetadataProvider(Protocol):
    # ... existing attributes ...
    
    supports_batch: bool = False  # Add now, default False
    max_batch_size: int = 1
    
    async def fetch_batch(
        self, 
        ctxs: list[LookupContext],
        id_type: IdType,
    ) -> list[ProviderResult]:
        """Fetch multiple items in one request (if supported).
        
        Only network providers meaningfully implement this.
        MediaInfo is "batch" by just running local scans in parallel.
        """
        ...
```

> **When to build:** Add `supports_batch` to protocol now (defaults to False). Implement when you hit an API that supports bulk lookup.

---

## 8. Custom User Fields

Let users add their own fields that flow through the system:

```python
class CanonicalMetadata(BaseModel):
    # ... standard fields ...
    
    # User-defined extras (preserved through pipeline)
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    
    # Example usage:
    # metadata.custom_fields["my_rating"] = 5
    # metadata.custom_fields["read_date"] = "2024-01-15"
```

> **Build now:** One-line addition, future-proofs without complexity.

---

## 9. Sync/Async Design

> **Already solved.** Your current provider architecture handles this cleanly:
> - All providers implement `async fetch()`
> - Sync providers (MediaInfo) wrap their work with `asyncio.to_thread()` internally
> - Aggregator doesn't care who's sync vs async

**Don't** add `is_async` + dual `fetch_async`/`fetch_sync` methods — it complicates the protocol for no gain.

```python
# This is already the correct pattern (from 03-plugin-architecture.md)
class MediaInfoProvider:
    async def fetch(self, ctx: LookupContext, id_type: IdType) -> ProviderResult:
        return await asyncio.to_thread(self._fetch_sync, ctx, id_type)
    
    def _fetch_sync(self, ctx, id_type) -> ProviderResult:
        # Actual sync work here
        ...
```

---

## 10. Rate Limiting & Circuit Breakers

> **Architecture goal:** Treat rate limiting + circuit breakers as **composable middleware**, not global dicts.

```python
# Conceptual goal (don't need to implement decorators now):
provider = Cached(RateLimited(CircuitBroken(HardcoverProvider(...))))
```

**For now:** Use existing `CircuitBreaker` infrastructure, wire per-provider:

```python
# metadata/providers/resilience.py
class ProviderResilience:
    """Per-provider rate limiting + circuit breakers."""
    
    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}
        self._limiters: dict[str, RateLimiter] = {}
    
    def get_breaker(self, provider_name: str) -> CircuitBreaker:
        if provider_name not in self._breakers:
            self._breakers[provider_name] = CircuitBreaker(
                failure_threshold=5,
                recovery_timeout=60,
                name=f"provider:{provider_name}"
            )
        return self._breakers[provider_name]
    
    def get_limiter(self, provider_name: str) -> RateLimiter:
        # Config-driven rates
        rates = {
            "audnex": (5.0, 10),    # 5 req/s, burst 10
            "hardcover": (2.0, 5),  # 2 req/s, burst 5
            "goodreads": (1.0, 1),  # 1 req/s, no burst
        }
        if provider_name not in self._limiters:
            rate, burst = rates.get(provider_name, (10.0, 20))
            self._limiters[provider_name] = RateLimiter(rate, burst)
        return self._limiters[provider_name]


# Usage in aggregator (adapt to your actual CircuitBreaker API)
async def _safe_fetch(self, provider, ctx, id_type):
    breaker = self.resilience.get_breaker(provider.name)
    limiter = self.resilience.get_limiter(provider.name)
    
    await limiter.acquire()
    async with breaker:  # Or breaker.call(...) depending on your implementation
        return await provider.fetch(ctx, id_type)
```

> **RateLimiter note:** If you don't already have one, `aiolimiter` is a solid off-the-shelf option, or a token bucket implementation is ~30 lines.

---

## 11. Testing Infrastructure

Make providers easy to mock:

```python
# metadata/providers/mock.py
class MockProvider:
    """Mock provider for testing."""
    
    name = "mock"
    priority = 999
    kind = "local"
    is_override = False
    supports_batch = False
    max_batch_size = 1
    
    def __init__(self, responses: dict[str, ProviderResult]):
        self.responses = responses
        self.call_log: list[LookupContext] = []
    
    def can_lookup(self, ctx: LookupContext, id_type: IdType) -> bool:
        # Safely check if we have a response for this id_type
        key = ctx.ids.get(id_type)
        return key is not None and key in self.responses
    
    async def fetch(self, ctx: LookupContext, id_type: IdType) -> ProviderResult:
        self.call_log.append(ctx)
        key = ctx.ids.get(id_type, "")
        return self.responses.get(key, ProviderResult(provider=self.name, success=False))


# In tests (instance-based registry = no leaking between tests)
def test_aggregator_merges_correctly():
    mock = MockProvider({
        "B0CJ1234": ProviderResult(
            provider="mock",
            success=True,
            fields={"title": "Test Book", "authors": ["Test Author"]},
            confidence={"title": 1.0, "authors": 1.0},
        )
    })
    
    registry = ProviderRegistry()
    registry.register(mock)
    
    aggregator = MetadataAggregator(registry=registry)
    # ... test assertions
```

> **Build now:** High value, low cost. Essential for testing the aggregator.

---

## 12. Implementation Priority

### Build Now (low cost, high value)

| Item | Effort | Why Now |
|------|--------|---------|
| **MockProvider** (§11) | 30 min | Essential for aggregator tests |
| **custom_fields dict** (§8) | 5 min | One-line future-proofing |
| **supports_batch = False** (§7) | 5 min | Add to protocol, implement later |
| **Circuit breakers per-provider** (§10) | 1 hr | Already have infrastructure |

### Design For, Defer Implementation

| Item | When to Build |
|------|---------------|
| **Exporters** (§1) | When adding 3rd output format |
| **Caching layer** (§2) | When network calls become pain point |
| **Batch operations** (§7) | When hitting API that supports bulk |
| **Full provenance** (§6) | When debugging "why this value?" becomes frequent |

### Likely YAGNI

| Item | Alternative |
|------|-------------|
| **Event hooks** (§3) | Structured logging covers 80% |
| **Field mapping YAML** (§5) | Code mappings are more debuggable |
| **Redis cache** (§2) | File/SQLite cache sufficient for single-user tool |
