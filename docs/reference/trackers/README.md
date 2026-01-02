# Tracker / Destination Architecture

> **Status:** Design Phase
> **Related:** [Metadata Architecture](../metadata/architecture/README.md) | [MAM BBCode](../mam/BBCODE.md)

---

## Overview

Trackers (MAM, RED, etc.) are **upload destinations** — distinct from metadata providers and sidecar exporters.

| Concern | Direction | Examples |
| --- | --- | --- |
| **Providers** | Data IN | Audnex, MediaInfo, Libation, abs_sidecar |
| **Exporters** | Sidecars OUT | OPF, metadata.json |
| **Trackers** | Releases OUT | MAM, RED (future) |

This separation prevents "MAM assumptions" from leaking into core naming/cleaning logic.

---

## Documents

| Document | Description |
| --- | --- |
| [Tracker Architecture](01-tracker-architecture.md) | Core design: ReleaseDraft, plugin protocol, naming policies |
| [MAM Destination](mam.md) | MAM-specific rules, constraints, current implementation |
| [RED Destination](red.md) | RED placeholder (future API upload support) |

---

## Key Principle

**Trackers consume, they don't compute.**

The core pipeline produces a tracker-agnostic `ReleaseDraft`. Each tracker plugin transforms that into its site-specific payload. Trackers MUST NOT reach back into internal modules to recompute names or re-clean metadata.

> **⚠️ Protocol Stability:** This design is foundational for Phase 4 (MAM extraction) and future RED implementation. Changes to the `ReleaseDraft` boundary or `TrackerDestination` protocol may impact Phase 4+ schedules. The tracker plugin interface specification should be locked before Phase 4 begins.

```text
Providers → Aggregator → CanonicalMetadata → Cleaning → ReleaseDraft
                                                              │
                                                   ┌──────────┴──────────┐
                                                   │                     │
                                                   ▼                     ▼
                                             Exporters              Trackers
                                            (OPF/JSON)            (MAM/RED)
```

---

## Current vs Future

| Tracker | Upload Support | Status |
| --- | --- | --- |
| **MAM** | Manual (no API) | ✅ Implemented |
| **RED** | API upload | 📋 Future |

MAM has no API — shelfr prepares artifacts for manual upload. RED has API upload with stricter constraints and different title conventions.
