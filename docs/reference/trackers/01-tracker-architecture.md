# Tracker / Destination Plugin Architecture

> Part of [Tracker Architecture Documentation](README.md)

---

## Why This Exists

Trackers have requirements orthogonal to metadata handling:

| Concern | What It Means |
| --- | --- |
| **Authentication** | API keys, cookies, session handling |
| **Site formatting** | BBCode rules, allowed tags, description templates |
| **Upload mechanics** | API upload vs manual form submission |
| **Site rules** | Path length limits, title conventions, category mapping |
| **Dupe checking** | Trumping policies, existing upload detection |

These don't belong in the metadata layer. Mixing them creates "MAM-flavored naming" that breaks when adding RED.

---

## Core Principle: ReleaseDraft as Boundary

The core pipeline produces a **tracker-agnostic `ReleaseDraft`**. Each tracker plugin transforms that into a site-specific payload.

```text
Providers → Aggregator → CanonicalMetadata → Cleaning → ReleaseDraft
                                                              │
                                                   ┌──────────┴──────────┐
                                                   │                     │
                                                   ▼                     ▼
                                             Exporters              Trackers
                                            (OPF/JSON)            (MAM/RED)
```

**Critical rule:** Trackers MUST NOT reach back into internal modules to recompute names. They consume the draft and apply only site-specific transforms.

---

## ReleaseDraft (Tracker-Neutral)

`ReleaseDraft` is the boundary object between core logic and trackers.

### Contents

| Field | Description |
| --- | --- |
| `canonical_metadata` | Cleaned `CanonicalMetadata` (title, authors, series, etc.) |
| `local_layout` | Filesystem paths (folder name, file names, relative structure) |
| `torrent` | Torrent info (path, infohash, file list, total size) |
| `media` | Technical metadata (duration, bitrate, codec, channels, chapters) |
| `artifacts` | Generated sidecar paths (OPF, metadata.json, cover) |
| `warnings` | Pipeline warnings (title truncated, missing fields, etc.) |

### Why This Boundary Matters

Without `ReleaseDraft`:

- MAM code calls `build_mam_filename()` directly
- RED code would need to call `build_red_filename()` differently
- Core naming logic grows "if tracker == 'red'" branches

With `ReleaseDraft`:

- Core produces one clean object
- Each tracker maps it to site format
- Adding a tracker = adding a plugin, not surgery

---

## Tracker Plugin Protocol (Future)

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class TrackerDestination(Protocol):
    """Protocol for tracker upload destinations."""

    name: str  # "mam", "red"
    supports_upload: bool  # MAM=False, RED=True

    def validate(self, draft: ReleaseDraft) -> list[ValidationIssue]:
        """Check site rules: path limits, required fields, category mapping.

        Returns list of issues (errors block upload, warnings are advisory).
        """
        ...

    async def build_payload(self, draft: ReleaseDraft) -> TrackerPayload:
        """Build destination-specific payload (BBCode, JSON, API fields).

        This is where site-specific formatting happens:
        - MAM: BBCode description, category mapping, form field JSON
        - RED: API payload with title formatting, edition tokens
        """
        ...

    async def dupe_check(self, draft: ReleaseDraft) -> DupeResult | None:
        """Optional: check for duplicates on the destination.

        Returns None if no dupe found, DupeResult with details otherwise.
        """
        ...

    async def upload(self, payload: TrackerPayload) -> UploadResult:
        """Optional: for API-enabled trackers only.

        MAM returns NotImplemented (manual upload).
        RED performs actual API upload.
        """
        ...
```

---

## Two Naming Views

Naming has two audiences:

| View | Audience | Constraints |
| --- | --- | --- |
| **Local Layout Policy** | Your filesystem | Filesystem-safe chars, your preferred structure |
| **Tracker Display Policy** | Site UI/search | Site title rules, edition formatting, allowed tokens |

### Why Separate?

MAM and RED have different title conventions:

- MAM: `Author - Title (Year) [Narrator]` (example)
- RED: May require format tokens, stricter character rules

If you bake MAM's display rules into local naming, you'll either:

1. Force RED to use MAM conventions (wrong)
2. Add `if tracker == 'red'` branches everywhere (messy)

### Implementation Strategy

```python
@dataclass
class ReleaseDraft:
    canonical_metadata: CanonicalMetadata
    local_layout: LocalLayout  # Filesystem naming (current system)

    def display_title(self, policy: DisplayPolicy) -> str:
        """Format title for tracker display (site-specific)."""
        return policy.format_title(self.canonical_metadata)
```

Each tracker provides its own `DisplayPolicy`. Core naming remains tracker-agnostic.

---

## Constraints Belong in the Tracker Layer

### Examples of Tracker-Specific Constraints

| Constraint | MAM | RED |
| --- | --- | --- |
| Path length limit | 225 chars | TBD (likely stricter) |
| API upload | ❌ Manual only | ✅ Full API |
| Title format | Flexible | Edition/year tokens required |
| Category mapping | Audiobook subcategories | Different taxonomy |
| Description format | BBCode | BBCode (different allowed tags?) |

### Where Constraints Live

```text
Core (tracker-agnostic):
├── CanonicalMetadata (cleaned fields)
├── LocalLayout (filesystem paths)
└── ReleaseDraft (boundary object)

Tracker layer (site-specific):
├── MAMDestination
│   ├── validate() → 225-char path limit
│   ├── build_payload() → MAM BBCode + JSON
│   └── category_map() → MAM audiobook categories
└── REDDestination
    ├── validate() → stricter path limit
    ├── build_payload() → RED API payload
    └── title_format() → edition tokens
```

---

## Tracker Registry (Future)

```python
@dataclass
class TrackerRegistry:
    """Registry for tracker destinations."""

    _trackers: dict[str, TrackerDestination] = field(default_factory=dict)

    def register(self, tracker: TrackerDestination) -> None:
        self._trackers[tracker.name] = tracker

    def get(self, name: str) -> TrackerDestination | None:
        return self._trackers.get(name)

    @property
    def available(self) -> list[str]:
        return list(self._trackers.keys())


# Usage
registry = TrackerRegistry()
registry.register(MAMDestination())
registry.register(REDDestination())  # future

tracker = registry.get("mam")
issues = tracker.validate(draft)
if not any(i.is_error for i in issues):
    payload = await tracker.build_payload(draft)
```

---

## Migration Path

### Current State (MAM-only)

MAM logic is scattered:

- `metadata/mam/` (Phase 4 extraction target)
- `utils/naming.py` (some MAM-specific rules)
- BBCode in `metadata/formatting/`

### Target State (Multi-Tracker)

1. **Phase 4 (MAM extraction):** Move to `metadata/mam/` as planned
2. **Phase N (tracker abstraction):**
   - Introduce `ReleaseDraft` as boundary
   - Extract `TrackerDestination` protocol
   - Wrap existing MAM code in `MAMDestination` class
3. **Phase N+1 (RED support):**
   - Implement `REDDestination`
   - Add API upload mechanics
   - Document RED-specific constraints

### What to Do Now

1. ✅ **Document the boundary** (this doc)
2. ✅ **Keep MAM-specific logic in `mam/`** (not spread across core)
3. ✅ **Keep BBCode in `formatting/`** (reusable, not MAM-locked)
4. 🚫 **Don't implement tracker registry yet** (YAGNI until RED)
5. 🚫 **Don't rewrite naming policies** (current system works for MAM)

---

## Testing Strategy

| Component | Test Type | What to Verify |
| --- | --- | --- |
| **ReleaseDraft** | Unit | All fields populated correctly from pipeline |
| **Tracker.validate()** | Unit | Site constraints enforced (path limits, required fields) |
| **Tracker.build_payload()** | Snapshot | Output matches expected BBCode/JSON exactly |
| **Tracker.upload()** | Integration | API calls work (RED only, mocked in CI) |

---

## Open Questions

These design decisions are tracked as GitHub issues:

1. **ReleaseDraft: dataclass vs Pydantic model** — See [#70](https://github.com/H2OKing89/shelfr/issues/70)
2. **Category mapping config location** — See [#71](https://github.com/H2OKing89/shelfr/issues/71)
3. **TrackerDestination: Protocol vs base class** — See [#69](https://github.com/H2OKing89/shelfr/issues/69)
