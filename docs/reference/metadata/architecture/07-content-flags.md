# Content Flags Architecture

> **Status:** 🚧 Design Phase | **Phase:** 9

This document defines the content flag resolution system - how shelfr determines content warnings (`cLang`, `vio`, `sSex`, `eSex`, `abridged`, `lgbt`) for MAM uploads from multiple data sources.

## Overview

MAM requires content flags for audiobook uploads. The challenge: no single provider has complete, accurate data. We solve this with a **multi-source resolver** that combines signals from various providers with clear precedence rules.

```text
┌─────────────────────────────────────────────────────────────────┐
│                     FlagResolver                                │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ LocalFlags   │  │  Hardcover   │  │   Audnex     │          │
│  │ (manual/LLM) │  │ (warnings)   │  │ (isAdult)    │          │
│  │  priority=95 │  │  priority=60 │  │  priority=70 │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
│         │                 │                 │                   │
│         ▼                 ▼                 ▼                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              Precedence Resolution                       │   │
│  │  Manual > Hardcover granular > Audnex broad signals     │   │
│  └─────────────────────────────────────────────────────────┘   │
│                           │                                     │
│                           ▼                                     │
│                  content_flags: ["vio", "sSex"]                 │
└─────────────────────────────────────────────────────────────────┘
```

## MAM Content Flags

| Flag | Meaning | MAM Description |
| ------ | --------- | ----------------- |
| `cLang` | Crude Language | Profanity, slurs, vulgar language |
| `vio` | Violence | Combat, gore, graphic injury |
| `sSex` | Suggestive Sexual Content | Sexual themes, innuendo, fade-to-black |
| `eSex` | Explicit Sexual Content | Graphic sex scenes |
| `abridged` | Abridged Version | Shortened/condensed audiobook |
| `lgbt` | LGBT Themes | LGBTQ+ characters, relationships, themes |

---

## Precedence Rules

**The "don't nuke my flags" rule:**

```text
Manual overrides (LocalFlags) > Hardcover warnings > Audnex signals
```

### Why This Order?

1. **Manual/LocalFlags (highest)**: User-curated flags are authoritative. If you've manually flagged a book or used LLM analysis, that wins.

2. **Hardcover (middle)**: Community-sourced content warnings are *granular* - they distinguish Violence vs Gore vs Sexual Content vs Rape. This is the richest automated signal.

3. **Audnex (lowest)**: The `isAdult` flag is a blunt instrument. It catches some adult content but lacks granularity and has false positives.

### Critical: Audnex `isAdult` Mapping

**⚠️ DO NOT map `Audnex.isAdult: true → eSex`**

This creates false "explicit sex" upgrades. A book marked `isAdult` might be adult for violence, language, or mature themes - not necessarily explicit sex.

**Correct mapping:**

```python
# Audnex provides weak signals only
audnex_mapping = {
    "isAdult": "sSex",      # At most suggestive, not explicit
    "formatType": "abridged",  # Clean mapping, no ambiguity
    "genres[].name contains 'LGBTQ+'": "lgbt"  # Audnex has this as genre/tag!
}
```

If Hardcover later provides a more specific warning (e.g., `Sexual assault`), it upgrades to `eSex`. But Audnex alone should never trigger `eSex`.

---

## Source Mappings

### Hardcover Content Warnings → MAM Flags

The mapping file: `config/content_flags.json`

```json
{
  "hardcover_to_mam": {
    "cLang": [
      "Strong language",
      "Cursing"
    ],
    "vio": [
      "Violence",
      "Gore",
      "murder",
      "war",
      "Torture",
      "Blood",
      "violent imagery",
      "Gun violence",
      "body horror"
    ],
    "sSex": [
      "Sexual content",
      "Spicy"
    ],
    "eSex": [
      "Rape",
      "Sexual assault",
      "Sexual violence",
      "sexual harassment",
      "Adult/minor relationship"
    ],
    "lgbt": [
      "LGBTQ"
    ]
  },
  "audnex_to_mam": {
    "sSex": {
      "field": "isAdult",
      "value": true,
      "note": "Weak signal - only sSex, never eSex"
    },
    "abridged": {
      "field": "formatType",
      "value": "abridged"
    },
    "lgbt": {
      "field": "genres[].name",
      "match": "contains 'LGBTQ' or 'LGBT'",
      "note": "Audnex provides this as genre or tag type"
    }
  }
}
```

### Hardcover Genres → MAM Flags

Some flags come from genres, not warnings:

```json
{
  "hardcover_genres_to_mam": {
    "lgbt": ["LGBTQ", "LGBT", "Queer Fiction", "Gay Fiction", "Lesbian Fiction"]
  }
}
```

---

## Local Flags Provider

For manual overrides and external enrichment (e.g., LLM-based analysis from your SQLite database).

### Import/Export Contract

Your external system exports JSONL:

```jsonl
{"book_id": "B01H0IE2RQ", "flags": ["vio", "cLang"], "source": "local_llm", "confidence": 0.95}
{"book_id": "B0797FYNDC", "flags": ["vio", "eSex"], "source": "manual", "evidence": "Chapter 12 explicit scene"}
```

**Fields:**

| Field | Required | Description |
| ------ | --------- | ----------------- |
| `book_id` | Yes | ASIN, ISBN, or internal ID |
| `flags` | Yes | List of MAM flag codes |
| `source` | No | `"manual"`, `"local_llm"`, `"epub_scan"` |
| `confidence` | No | 0.0-1.0 score (optional) |
| `evidence` | No | Human-readable justification |

### LocalFlagsProvider Behavior

```python
class LocalFlagsProvider(MetadataProvider):
    provider_name = "local_flags"
    priority = 95  # Highest - manual overrides win
    provides_fields = frozenset(["content_flags"])

    def __init__(self, flags_file: Path):
        self.flags_db = self._load_jsonl(flags_file)

    async def fetch(self, query: MetadataQuery) -> ProviderResult | None:
        # Lookup by ASIN, ISBN, or title+author hash
        entry = self.flags_db.get(query.asin) or self.flags_db.get(query.isbn)
        if not entry:
            return None
        return ProviderResult(
            provider_name=self.provider_name,
            confidence=entry.get("confidence", 1.0),
            data={"content_flags": entry["flags"]},
        )
```

---

## Flag Resolver

The `FlagResolver` combines signals from all sources:

```python
class FlagResolver:
    """Resolves content flags from multiple providers with precedence."""

    def __init__(self, mapping_config: Path = Path("config/content_flags.json")):
        self.mappings = self._load_mappings(mapping_config)

    def resolve(
        self,
        local_flags: list[str] | None,
        hardcover_warnings: list[str] | None,
        hardcover_genres: list[str] | None,
        audnex_data: dict | None,
    ) -> FlagResult:
        """
        Resolve flags with precedence: local > hardcover > audnex.

        Returns FlagResult with:
        - flags: final list of MAM flags
        - sources: which provider contributed each flag
        - warnings: any resolution conflicts or missing data
        """
        result = FlagResult()

        # 1. Start with local/manual flags (highest priority)
        if local_flags:
            for flag in local_flags:
                result.add_flag(flag, source="local", confidence=1.0)

        # 2. Add Hardcover warnings (unless local already set)
        if hardcover_warnings:
            for warning in hardcover_warnings:
                mam_flag = self._map_hardcover_warning(warning)
                if mam_flag and mam_flag not in result.flags:
                    result.add_flag(mam_flag, source="hardcover", confidence=0.9)

        # 3. Add Hardcover genre signals
        if hardcover_genres:
            for genre in hardcover_genres:
                mam_flag = self._map_hardcover_genre(genre)
                if mam_flag and mam_flag not in result.flags:
                    result.add_flag(mam_flag, source="hardcover_genre", confidence=0.8)

        # 4. Add Audnex signals (lowest priority, weak signals only)
        if audnex_data:
            if audnex_data.get("isAdult") and "sSex" not in result.flags and "eSex" not in result.flags:
                result.add_flag("sSex", source="audnex", confidence=0.5)
            if audnex_data.get("formatType") == "abridged":
                result.add_flag("abridged", source="audnex", confidence=1.0)

        return result
```

---

## Error Handling: WARN + Continue

**Missing provider matches should be non-fatal.**

```python
# In orchestration.py or workflow.py

def resolve_content_flags(release: AudiobookRelease) -> FlagResult:
    result = FlagResult()

    # Try local flags
    local = local_flags_provider.fetch(release.asin)
    if local:
        result.merge(local)

    # Try Hardcover (may not match)
    try:
        hardcover = hardcover_provider.fetch(release.asin, release.title, release.authors)
        if hardcover:
            result.merge(hardcover)
        else:
            logger.warning(f"No Hardcover match for {release.title} - continuing with other sources")
            result.add_warning("hardcover_no_match")
    except HardcoverError as e:
        logger.warning(f"Hardcover API error for {release.title}: {e}")
        result.add_warning("hardcover_error")

    # Try Audnex (already have this data from metadata fetch)
    if release.audnex_data:
        result.merge_audnex(release.audnex_data)

    # Return whatever we have - never hard stop
    return result
```

**Behavior:**

- `WARN: No Hardcover match for "Book Title"` → Continue pipeline
- Return resolved flags from whatever sources *did* match
- Track "unresolved/missing" indicator for coverage reporting
- No hard stops, just good logging + metrics

---

## Implementation Plan

### Phase 9.1: Core Infrastructure

1. ✅ Add `content_flags` field to `CanonicalMetadata`
2. ✅ Update `AudnexProvider` to map `isAdult` → `sSex` (not `eSex`)
3. ✅ Update MAM JSON builder to use `content_flags`
4. [ ] Create `config/content_flags.json` mapping file
5. [ ] Implement `FlagResolver` class

### Phase 9.2: LocalFlagsProvider

1. [ ] Define JSONL import schema
2. [ ] Implement `LocalFlagsProvider`
3. [ ] Add to provider registry with priority=95
4. [ ] Test with sample data from your SQLite export

### Phase 9.3: HardcoverProvider (Later)

1. [ ] Implement `HardcoverProvider` with API calls
2. [ ] Add FileCache integration
3. [ ] Use sample JSON as test fixtures
4. [ ] Feature flag for gradual rollout

---

## Testing Strategy

| Component | Test Focus |
| --------- | ----------------- |
| Mapping JSON | Valid structure, all flags covered |
| FlagResolver | Precedence rules, conflict resolution |
| LocalFlagsProvider | JSONL parsing, missing file handling |
| HardcoverProvider | API mocking, cache behavior |
| Integration | End-to-end flag resolution |

### Test Cases

```python
def test_local_overrides_hardcover():
    """Local flags should override Hardcover warnings."""
    result = resolver.resolve(
        local_flags=["vio"],
        hardcover_warnings=["Violence", "Sexual content"],
    )
    # Local said "vio" only, so "sSex" from Hardcover should NOT appear
    assert result.flags == ["vio"]

def test_audnex_is_adult_only_ssex():
    """Audnex isAdult should map to sSex, never eSex."""
    result = resolver.resolve(
        audnex_data={"isAdult": True}
    )
    assert "sSex" in result.flags
    assert "eSex" not in result.flags

def test_hardcover_upgrades_to_esex():
    """Hardcover 'Sexual assault' should map to eSex."""
    result = resolver.resolve(
        hardcover_warnings=["Sexual assault"]
    )
    assert "eSex" in result.flags
    assert "sSex" not in result.flags
```

---

## Related Documentation

- [Providers Overview](../providers/README.md) - Provider registry and priorities
- [Hardcover Provider](../providers/hardcover.md) - Hardcover-specific details
- [Implementation Checklist](05-implementation-checklist.md) - Phase 9 tracking
- [Plugin Architecture](03-plugin-architecture.md) - Provider protocol
