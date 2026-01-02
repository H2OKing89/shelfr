# MAM Destination Notes

> Part of [Tracker Architecture Documentation](README.md)

---

## Overview

MyAnonamouse (MAM) is the primary upload destination. It has **no API upload** — shelfr prepares artifacts for manual upload via the web form.

---

## Upload Support

| Feature | Status |
| --- | --- |
| API upload | ❌ Not available |
| Torrent creation | ✅ mkbrr |
| Description generation | ✅ BBCode |
| Category mapping | ✅ Heuristic |
| Dupe checking | ⏳ Manual / planned |

### What Shelfr Produces

For each release, shelfr generates:

1. **Torrent file** — via mkbrr (Docker) ✅
2. **BBCode description** — formatted synopsis, chapter list, technical info ✅
3. **MAM JSON payload** — form field helpers (category, tags, etc.) ✅ (extraction to `metadata/mam/` in Phase 4)
4. **Validation warnings** — issues that may cause upload rejection ⏳ (basic validation exists; enhanced in Phase 4)

The user then manually uploads via MAM's web form.

---

## Naming Constraints

### Path Length Limit

MAM enforces a **225-character limit** on relative paths within the torrent.

```text
Author Name - Book Title (Year) [Narrator Name]/Author Name - Book Title (Year) [Narrator Name].m4b
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
                                        Must be ≤ 225 characters
```

**Handled by:** `MamPath` validation + `utils/naming.py` truncation (hash suffix when needed).

### Folder Naming Convention

```text
{Author} - {Title} ({Year}) [{Narrator}]
```

Components:

- **Author**: Primary author, cleaned (no roles like "PhD")
- **Title**: Full title, subtitle after colon if present
- **Year**: Original publication year
- **Narrator**: Primary narrator(s)

### File Naming Convention

```text
{Author} - {Title} ({Year}) [{Narrator}].{ext}
```

Single-file audiobooks match folder name. Multi-file uses part numbering.

---

## Required Fields (Minimum Viable)

| Field | Required | Notes |
| --- | --- | --- |
| Title | ✅ Yes | |
| Author(s) | ✅ Yes | At least one |
| Narrator(s) | ⚠️ Recommended | MAM expects this for audiobooks |
| Language | ✅ Yes | |
| Runtime | ✅ Yes | Total duration |
| Description | ✅ Yes | Synopsis/summary |
| Cover | ⚠️ Recommended | Higher quality preferred |
| ASIN | ⚠️ Recommended | Enables deduplication |

---

## Category Mapping

MAM has a category/subcategory taxonomy for audiobooks.

### Current Implementation

Heuristic mapping based on:

1. Genre keywords (fiction vs nonfiction)
2. Audnex categories
3. Fallback to "General" if uncertain

**Config:** `config/audiobook_categories.json`, `config/mam_categories_reference.json`

### Category Flow

```text
Audnex genres → _infer_fiction_or_nonfiction() → MAM category ID
```

---

## Description Format (BBCode)

MAM descriptions use BBCode with specific conventions.

### Template Structure

```bbcode
[b]Summary[/b]
{synopsis}

[b]Narrator(s)[/b]
{narrators}

[b]Duration[/b]
{runtime}

[b]Release Info[/b]
{technical details}
```

**Implementation:** `metadata/formatting/bbcode.py` (Jinja2 templates)

### BBCode Rules

- Standard tags: `[b]`, `[i]`, `[u]`, `[url]`, `[img]`
- Lists: `[list]`, `[*]`
- No raw HTML
- Newlines: `\n` (not `<br>`)

See [BBCode Reference](../mam/BBCODE.md) for full details.

---

## Dupe Checking

### Current State (Pre-Phase 4)

Manual — user checks MAM search before uploading.

### Planned Approach (Post-Phase 4)

> **Prerequisite:** ASIN lookup available via Audnex extraction (Phase 3 complete).

1. Search MAM by ASIN (if available from Audnex metadata)
2. Search by title + author fuzzy match
3. Return potential dupes with match confidence

**Timeline:** Planned for post-Phase 4 work. Phase 3 Audnex extraction enables ASIN-based lookup.

### Trumping Policy

MAM allows "trumping" (replacing) existing uploads under certain conditions:

- Higher quality (bitrate, source)
- Better metadata
- Fixing errors

Shelfr should emit a **validation warning** (not an error) if a potential trump situation is detected. This is advisory — the user decides whether to proceed with upload.

---

## Validation Rules

Before upload, validate:

| Rule | Severity | Check |
| --- | --- | --- |
| Path ≤ 225 chars | 🔴 Error | `MamPath.validate()` |
| Has title | 🔴 Error | Required field |
| Has author | 🔴 Error | Required field |
| Has duration | 🔴 Error | Required for audiobooks |
| Has narrator | 🟡 Warning | Expected for audiobooks |
| Has cover | 🟡 Warning | Recommended |
| ASIN present | 🟡 Warning | Enables dupe detection |
| Description non-empty | 🟡 Warning | Better UX |

---

## Current Code Locations

| Component | Location | Notes |
| --- | --- | --- |
| MAM JSON builder | `metadata.py` → `metadata/mam/` (Phase 4) | `build_mam_json()` |
| Category mapping | `metadata.py` → `metadata/mam/` (Phase 4) | `_infer_fiction_or_nonfiction()` |
| BBCode rendering | `metadata/formatting/bbcode.py` | Extracted in Phase 2 |
| Path validation | `models.py` | `MamPath` class |
| Naming/truncation | `utils/naming.py` | 225-char enforcement |
| Category config | `config/audiobook_categories.json` | Mapping rules |

---

## Future Improvements

1. **Automated dupe checking** — search MAM before upload prep
2. **Better category inference** — ML or keyword expansion
3. **Upload queue** — batch multiple releases
4. **Form autofill** — browser extension or userscript integration
