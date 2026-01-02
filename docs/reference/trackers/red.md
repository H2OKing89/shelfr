# RED Destination Notes (Future)

> Part of [Tracker Architecture Documentation](README.md)
>
> **Status:** Placeholder — RED support is a future enhancement.

---

## Overview

RED (Redacted) supports **API upload** with stricter constraints and different conventions than MAM.

---

## Upload Support

| Feature | Status |
| --- | --- |
| API upload | ✅ Available |
| Torrent creation | ✅ mkbrr (same as MAM) |
| Description generation | ✅ BBCode (different rules?) |
| Category mapping | 📋 TBD (different taxonomy) |
| Dupe checking | 📋 TBD (API support?) |

### API Authentication

RED requires authenticated API access:

- API key or session token
- Rate limiting compliance
- Proper user-agent headers

**Implementation:** Will need `TrackerAuth` abstraction.

---

## Naming Constraints

### Path Length Limit

TBD — likely stricter than MAM's 225-char limit.

**Action:** Confirm exact limit before implementation.

### Title Format

RED has specific title formatting rules:

- Edition tokens required (e.g., year, format)
- Character restrictions
- Different handling of series/volume info

**Example (hypothetical):**

```text
Author - Title (Year) [Format]
```

This differs from MAM's `Author - Title (Year) [Narrator]` convention (see [MAM naming](mam.md#folder-naming-convention)).

### Tracker Display Policy

RED will need its own `DisplayPolicy` implementation:

```python
class REDDisplayPolicy(DisplayPolicy):
    """RED-specific title/edition formatting."""

    def format_title(self, meta: CanonicalMetadata) -> str:
        # RED-specific formatting
        ...

    def format_edition(self, meta: CanonicalMetadata) -> str:
        # Edition tokens (year, format, etc.)
        ...
```

---

## Required Fields (TBD)

| Field | Required | Notes |
| --- | --- | --- |
| Title | ✅ Yes | |
| Artist/Author | ✅ Yes | Field name may differ |
| Format | 📋 TBD | Audiobook format tokens? |
| Bitrate | 📋 TBD | May be required |
| Year | 📋 TBD | |
| Description | 📋 TBD | |

**Action:** Document actual requirements before implementation.

---

## Category Mapping

RED has a different category taxonomy than MAM.

**Action:** Document RED audiobook categories and mapping rules.

---

## Description Format

RED uses BBCode but may have:

- Different allowed tags
- Different formatting conventions
- Stricter length limits

**Action:** Confirm BBCode rules and whether existing templates need adaptation.

---

## Dupe Checking

If RED API supports dupe checking:

- Query by hash/infohash
- Query by title + artist
- Return existing torrent info

**Action:** Confirm API capabilities.

---

## Validation Rules

| Rule | Severity | Check |
| --- | --- | --- |
| Path within limit | 🔴 Error | TBD exact limit |
| Required fields present | 🔴 Error | TBD field list |
| Format tokens valid | 🔴 Error | TBD token rules |
| API auth valid | 🔴 Error | Session/key check |

---

## Implementation Plan

### Prerequisites

1. ✅ Tracker architecture docs (this doc)
2. ⏳ Phase 4 complete (MAM extraction)
3. ⏳ `ReleaseDraft` boundary object exists
4. ⏳ `TrackerDestination` protocol defined

### Implementation Steps

1. **Research phase:**
   - Document exact RED API requirements
   - Confirm path limits, title rules, required fields
   - Understand rate limiting

2. **Auth implementation:**
   - `REDAuth` class for API key/session handling
   - Secure credential storage (not in config.yaml)

3. **REDDestination class:**
   - `validate()` with RED-specific rules
   - `build_payload()` for API format
   - `upload()` for actual API call
   - `dupe_check()` if API supports it

4. **Display policy:**
   - `REDDisplayPolicy` for title formatting
   - Edition token generation

5. **Testing:**
   - Mock API for unit tests
   - Staging/sandbox upload for integration tests

---

## Open Questions

1. **What are RED's exact audiobook requirements?**
   - Path length limit?
   - Required metadata fields?
   - Category taxonomy?

2. **Does RED API support batch operations?**
   - Single upload vs queue?

3. **What's RED's trumping/replacement policy?**
   - Can uploads be updated?
   - Dupe handling?

4. **Should credentials be in config or separate secrets file?**
   - `config/.env` vs `~/.shelfr/secrets.yaml`?

---

## References

- RED API documentation (link when available)
- RED upload rules (link when available)
