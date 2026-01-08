# Phase 09: Content Flags Architecture

> **Status:** ✅ Complete | **Content warning resolution system**

## Overview

MAM requires content flags (`cLang`, `vio`, `sSex`, `eSex`, `abridged`, `lgbt`) for audiobook uploads. No single provider has complete data, so we use a **multi-source resolver** with clear precedence rules.

---

## MAM Content Flags

| Flag | Meaning | MAM Description |
| ------ | --------- | ----------------- |
| `cLang` | Crude Language | Profanity, slurs, vulgar language |
| `vio` | Violence | Combat, gore, graphic injury |
| `sSex` | Suggestive Sexual | Sexual themes, innuendo, fade-to-black |
| `eSex` | Explicit Sexual | Graphic sex scenes |
| `abridged` | Abridged Version | Shortened/condensed audiobook |
| `lgbt` | LGBT Themes | LGBTQ+ characters, relationships, themes |

---

## Precedence Rules

```
Manual overrides (LocalFlags) > Hardcover warnings > Audnex signals
     precedence=95                 precedence=70       precedence=60
```

### Why This Order?

| Source | Precedence | Rationale |
| -------- | ---------- | --------- |
| Manual/LocalFlags | 95 | User-curated flags are authoritative |
| Hardcover | 70 | Community-sourced, granular warnings |
| Audnex | 60 | `isAdult` is blunt; lacks granularity |

---

## Critical: Audnex `isAdult` Mapping

> ⚠️ **DO NOT map `Audnex.isAdult: true → eSex`**

This creates false "explicit sex" flags. A book marked `isAdult` might be adult for violence, language, or mature themes — not necessarily explicit sex.

**Correct mapping:**

| Audnex Field | MAM Flag | Rationale |
| -------------- | ---------- | ----------- |
| `isAdult: true` | `sSex` | Weak fallback; at most suggestive |
| `formatType: "Abridged"` | `abridged` | Clean, unambiguous |
| `genres[].name contains "LGBTQ+"` | `lgbt` | Audnex tracks as genre |

If Hardcover provides a more specific warning (e.g., `Sexual assault`), it upgrades to `eSex` and wins.

---

## Hardcover Content Warnings

Hardcover provides granular content warnings. Mapping file: `config/content_flags.json`

### Example Mappings

| Hardcover Warning | MAM Flag |
| ----------------- | -------- |
| "Strong language", "Cursing" | `cLang` |
| "Violence", "Gore", "Torture" | `vio` |
| "Sexual content", "Nudity" | `sSex` |
| "Rape", "Sexual assault" | `eSex` |
| "LGBTQ+", "Queer" | `lgbt` |

---

## Resolution Flow

```
1. Collect signals from all providers
2. Group by flag type (vio, sSex, etc.)
3. For each flag: highest precedence source wins
4. If conflict: more specific (eSex) > less specific (sSex)
5. Return merged ContentFlags object
```

---

## Files

| File | Purpose |
| ------ | --------- |
| `config/content_flags.json` | Hardcover → MAM mappings |
| `schemas/content_flags.py` | `ContentFlags` Pydantic model |
| `providers/flags.py` | `FlagResolver` class |

---

## Related Documentation

- **Master:** [CHECKLIST.md](../CHECKLIST.md)
- **Previous:** [01-06-migration.md](01-06-migration.md)
- **Next:** [10-parallel-region-lookup.md](10-parallel-region-lookup.md)
