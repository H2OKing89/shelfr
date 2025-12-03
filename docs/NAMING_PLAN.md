yoy# Naming & Cleaning Plan

> **Document Version:** 1.6.0 | **Last Updated:** 2025-12-03 | **Status:** Phase 8 Pending (Full Path Truncation Fix) 🔧

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
   - [Separate Naming Config](#separate-naming-config-confignamingjson)
   - [Glossary of Actions](#glossary-of-actions)
3. [Audnex Normalization Layer](#audnex-normalization-layer)
   - [The Problem](#the-problem)
   - [Solution: Rebuild from Series Data](#solution-rebuild-from-series-data)
   - [Detection Logic](#detection-logic)
   - [Arc Name Extraction](#arc-name-extraction)
   - [Configuration](#configuration)
   - [Edge Cases](#edge-cases)
4. [Processing Pipeline](#full-processing-pipeline)
   - [Pipeline Diagram](#full-processing-pipeline)
   - [Cleaning Pipeline Order](#cleaning-pipeline-order)
   - [What Gets Cleaned](#what-gets-cleaned)
5. [Folder & File Naming](#folder--file-naming-schemas)
   - [Audiobookshelf Library Structure](#audiobookshelf-library-structure-future-feature)
   - [Book Folder Schema](#book-folder-schema-audiobookshelf)
   - [MAM Staging Paths](#mam-staging-paths-torrent-uploads)
   - [Character Limits & Truncation](#character-limits)
   - [MAM JSON Output Schema](#mam-json-output-schema)
6. [Matching Rules](#matching-rules-by-category)
7. [Phrase Removal Rules](#phrase-removal-rules)
   - [Format Indicators](#category-format-indicators)
   - [Genre Tags](#category-genre-tags)
   - [Series Suffixes](#category-series-suffixes)
   - [Publisher Tags](#category-publisher-tags-new)
   - [Preserve Exact](#category-preserve-exact-new)
   - [Subtitle Patterns](#category-subtitle-patterns)
   - [Subtitle Redundancy Rules](#category-subtitle-redundancy-rules-new)
8. [Author Map & Transliteration](#author-map-transliteration)
9. [Vol/Book Normalization](#volbook-normalization)
10. [naming.json Schema](#namingjson-schema)
11. [Sample Data Sources](#sample-data-sources)
12. [Library Analysis Results](#library-analysis-results)
    - [Audiobookshelf Library](#audiobookshelf-library-2025-12-02)
    - [Libation Export](#libation-export-2025-12-01)
13. [Implementation Phases](#implementation-phases)
14. [Testing Strategy](#testing-strategy)
15. [Questions Resolved](#questions-resolved)
16. [Future Enhancements](#future-enhancements-nice-to-have)
17. [Changelog](#changelog)

---

## Overview

This document tracks the naming/cleaning rules for MAMFast. The goal is consistent, clean naming across:
- Folder names (staging)
- File names (staging)
- MAM JSON output (title, subtitle, series, description)

---

## Architecture

### Separate Naming Config (`config/naming.json`)


Instead of cluttering the main `config.yaml`, naming rules will live in a dedicated JSON file:

```
config/
├── config.yaml          # Main settings (paths, services, etc.)
└── naming.json          # Naming rules (phrases, patterns, author map)
```

**Benefits:**
- Easier to share/update naming rules independently
- Can add lots of entries without cluttering main config
- JSON is easier for programmatic updates
- Could potentially fetch community-maintained naming rules
- Version field allows tracking rule updates

---

## Glossary of Actions

| Action | Description |
|--------|-------------|
| **`filter_title`** | Remove configured phrases/tags/suffixes (format indicators, genre tags, subtitle patterns). Case-insensitive matching. |
| **`transliterate`** | Normalize non-ASCII characters to ASCII. For **titles/series/folders**: generic transliteration only (pykakasi → unidecode). For **authors/narrators**: first check `author_map`, then fall back to transliteration. |
| **`filter_series`** | Like `filter_title` but also removes series suffixes (e.g., " Series", " Trilogy"). |
| **`normalize_audnex`** | Fix Audible's inconsistent title/subtitle and extract canonical series data. See [Audnex Normalization](#audnex-normalization-layer). |
| **Keep Vol/Book** | Whether volume/book indicators stay as human-readable text (JSON) or are normalized to `vol_XX` format (folders/files). |

---

## Audnex Normalization Layer

### The Problem

Audible/Audnex metadata is notoriously inconsistent. The same series can have different title/subtitle arrangements across volumes:

| ASIN | Title | Subtitle | Series | Problem |
|------|-------|----------|--------|---------|
| B0BHLHRMJH | `Sword Art Online 7` | `Mother's Rosary` | `Sword Art Online #7` | ✅ Correct |
| B0D6C6H1LS | `Sword Art Online 14` | `Alicization Uniting` | `Sword Art Online #14` | ✅ Correct |
| B0DK9TS6D9 | `Alicization Exploding` | `Sword Art Online 16` | `Sword Art Online #16` | ❌ **Swapped!** |

**Key insight:** `seriesPrimary.name` and `seriesPrimary.position` are **always reliable**. The title/subtitle fields are the problem.

### Solution: Rebuild from Series Data

Instead of trying to detect and swap title/subtitle, we **rebuild canonical metadata from the authoritative source** (`seriesPrimary`):

```
Raw Audnex JSON
    ↓
normalize_audnex_book()  ← Fix swaps, derive series/vol, extract arc
    ↓
NormalizedBook (canonical view)
    ↓
Cleaning Pipeline (filter_title, transliterate, etc.)
    ↓
Folder/File/MAM JSON
```

### Normalized Book Structure

```python
@dataclass
class NormalizedBook:
    """Canonical book metadata after Audnex normalization."""
    asin: str

    # Raw values (preserved for debugging)
    raw_title: str
    raw_subtitle: str | None

    # Canonical values (source of truth)
    series_name: str | None      # From seriesPrimary.name
    series_position: int | None  # From seriesPrimary.position
    arc_name: str | None         # Extracted from title OR subtitle

    # Constructed display values
    display_title: str           # "{Series}, Vol. {N}" or raw_title if no series
    display_subtitle: str | None # Arc name if exists, else None
```

### Detection Logic

The normalization uses a hybrid approach:

```python
def detect_swapped_title_subtitle(data: dict) -> tuple[str, str | None]:
    """Detect and fix swapped title/subtitle using series data as ground truth."""
    title = data.get("title", "")
    subtitle = data.get("subtitle")
    series = data.get("seriesPrimary", {})
    series_name = series.get("name", "").strip()
    series_pos = series.get("position")

    # Can't detect swap without series data or subtitle
    if not subtitle or not series_name:
        return title, subtitle

    title_lower = title.lower()
    subtitle_lower = subtitle.lower()
    series_lower = series_name.lower()

    subtitle_has_series = series_lower in subtitle_lower
    title_has_series = series_lower in title_lower

    # Heuristic 1: subtitle has series name, title doesn't → swapped
    if subtitle_has_series and not title_has_series:
        return subtitle, title

    # Heuristic 2: subtitle ends with series number, title doesn't have series
    if series_pos and not title_has_series:
        if re.search(rf"\b{series_pos}\b", subtitle_lower):
            return subtitle, title

    # No swap detected
    return title, subtitle
```

### Arc Name Extraction

Once title/subtitle are corrected, extract the arc name:

```python
def extract_arc_name(title: str, subtitle: str | None, series_name: str | None) -> str | None:
    """Determine which field contains the arc name (e.g., 'Alicization Exploding')."""
    if not series_name:
        return subtitle  # No series → subtitle is arc (if any)

    series_lower = series_name.lower()

    # If title doesn't have series name, title IS the arc
    # (This happens when we didn't swap because both had series name)
    if series_lower not in title.lower():
        return clean_arc_name(title)

    # Otherwise subtitle is the arc (if it exists and isn't just series info)
    if subtitle and series_lower not in subtitle.lower():
        return clean_arc_name(subtitle)

    return None
```

### Resulting Field Mapping

After normalization, downstream naming uses these canonical sources:

| Output Field | Source | Example |
|--------------|--------|---------|
| Folder series | `series_name` | `Sword Art Online` |
| Folder vol | `series_position` → `vol_16` | `vol_16` |
| Folder arc | `arc_name` | `Alicization Exploding` |
| MAM title | `display_title` | `Sword Art Online, Vol. 16` |
| MAM subtitle | `arc_name` | `Alicization Exploding` |
| MAM series | `series_name` | `Sword Art Online` |
| MAM series_number | `series_position` | `16` |

### Configuration

```yaml
# config.yaml
audnex:
  normalize_title_subtitle: true  # Use series data as source of truth (default: true)
```

Or in `naming.json`:

```json
"title_subtitle_normalization": {
  "enabled": true,
  "arc_whitelist": []  // Optional: known arc names for edge cases
}
```

### Edge Cases

| Case | Handling |
|------|----------|
| No `seriesPrimary` | Skip normalization, use title-based parsing |
| Both title AND subtitle have series name | Don't swap, let cleaning rules handle |
| Multi-series books (`seriesSecondary`) | Ignore secondary, use primary only |
| Standalone books | No series data → use raw title/subtitle |

### Test Fixtures

Golden test data is available in `tests/fixtures/audnex_normalization_samples.json`:
- **correct_mapping**: 5 SAO volumes with correct title/subtitle (no swap needed)
- **swapped_mapping**: 6 real examples where Audnex has title/subtitle swapped
- **no_series**: Standalone books without series data
- **edge_cases**: Tricky patterns (both have series, short titles, "Light Novel" subtitles)

All test data verified against live Audnex API on 2025-12-02.

### Debug Logging

When normalization detects a swap:

```
[normalize] B0DK9TS6D9: Detected swapped title/subtitle
  - Raw: title="Alicization Exploding", subtitle="Sword Art Online 16"
  - Series: "Sword Art Online #16"
  - Fixed: title="Sword Art Online 16", subtitle="Alicization Exploding"
  - Arc: "Alicization Exploding"
```

[↑ Back to top](#table-of-contents)

---

## Full Processing Pipeline

The complete data flow from raw Audnex to final output:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            AUDNEX API RESPONSE                              │
│  (title, subtitle, authors, narrators, seriesPrimary, genres, etc.)        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     0. AUDNEX NORMALIZATION (New!)                          │
│  - Detect title/subtitle swaps using seriesPrimary as source of truth      │
│  - Extract arc name from the "wrong" field                                 │
│  - Build NormalizedBook with canonical title, subtitle, series_name, arc   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PER-FIELD CLEANING PIPELINE                         │
│  1. Preserve Check  → Skip cleaning if in `preserve_exact` list            │
│  2. Author Map      → Replace known author names (exact match)             │
│  3. Transliteration → Non-ASCII → ASCII (pykakasi → unidecode fallback)    │
│  4. Phrase Removal  → Remove format indicators, genre tags, etc.           │
│  5. Series Suffix   → Remove " Series", " Trilogy", etc. (series only)     │
│  6. Vol/Book        → Normalize or remove based on context                 │
│  7. Cleanup         → Fix double spaces, trim, dangling punctuation        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              OUTPUT GENERATION                              │
│  - MAM JSON: Clean title, subtitle (arc), series, authors                  │
│  - Folder name: {series}_vol_{position}_-_{arc}_-_{authors}_-_{year}       │
│  - File names: {book_num}_{chapter_title}.m4b                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Cleaning Pipeline Order

Steps 1-7 are the per-field cleaning pipeline (after normalization):

```
1. Preserve Check     → Skip cleaning if title/series is in `preserve_exact` list
2. Author Map         → Replace known author names (exact match)
3. Transliteration    → Non-ASCII → ASCII (pykakasi → unidecode fallback)
4. Phrase Removal     → Remove format indicators, genre tags, publisher tags
5. Series Suffix      → Remove " Series", " Trilogy", etc. (series names only)
6. Vol/Book Handling  → Normalize or remove based on context
7. Cleanup            → Fix double spaces, trim, remove dangling punctuation
```

> **Field scope:** The pipeline is applied per field. Some steps are no-ops depending on the field:
> - `author_map` → only for authors/narrators
> - `series_suffixes` → only for series
> - `vol/book handling` → only for title/series/folders/files (not authors)
> - `phrase removal` → not applied to description

**Step 7 Cleanup details:**
- Remove double/triple spaces → single space
- Trim leading/trailing whitespace
- Remove dangling punctuation (e.g., trailing `,`, `:`, `-`)
- Normalize punctuation: em-dash (`—`) → hyphen (`-`), curly quotes → straight quotes
- Remove empty parentheses `()` or brackets `[]` left after phrase removal

**Example transformation:**
```
Input:  "Overlord (Light Novel), Vol. 3"
Step 4: "Overlord, Vol. 3"           (removed format indicator)
Step 6: "Overlord vol_03"            (folder) or "Overlord, Vol. 3" (JSON)
Step 7: "Overlord vol_03"            (no changes needed)
```

---

## What Gets Cleaned

| Target | filter_title | transliterate | Keep Vol/Book | Notes |
|--------|-------------|---------------|---------------|-------|
| Folder Name | ✅ | ✅ | ❌ Remove (uses vol_XX) | |
| File Name | ✅ | ✅ | ❌ Remove (uses vol_XX) | |
| MAM JSON: Title | ✅ | ✅ | ✅ Keep Vol. X | |
| MAM JSON: Subtitle | ✅ | ✅ | ✅ *if non-redundant* | Drop if just "Series, Book X" |
| MAM JSON: Series | ✅ + suffixes | ✅ | ❌ Remove | |
| MAM JSON: Description | ❌ (minimal) | ✅ | ✅ Keep | |
| MAM JSON: Authors | ❌ | ✅ | N/A | |
| MAM JSON: Narrators | ❌ | ✅ | N/A | |

**Description cleaning policy:** Minimal - transliteration only, plus optional trailing format-stripping (e.g., "(Unabridged Audiobook)" at end). Description is **excluded** from `format_indicators`, `genre_tags`, `series_suffixes`, and subtitle redundancy rules. Only transliteration and very light trailing cruft removal are allowed.

**Subtitle redundancy policy:** Drop subtitle entirely if it only contains "Series, Book X" or "Title, Book X" pattern - this info is already in the series/title fields.

[↑ Back to top](#table-of-contents)

---

## Folder & File Naming Schemas

> **Scope Note:** This section documents two different naming contexts:
> 1. **Audiobookshelf Library** - 3-level nesting for personal library organization (future feature)
> 2. **MAM/Torrent Staging** - Flat folder structure for uploads

---

### Audiobookshelf Library Structure (Future Feature)

The personal audiobook library uses a 3-level nesting hierarchy optimized for Audiobookshelf:

```
{Author}/
└── {Series}/
    └── {Book Folder}/
        ├── {Book}.m4b
        ├── cover.jpg
        └── metadata.json
```

**Level 1: Author Folder**
- Format: `{First} {Last}` or `{Single Name}`
- Examples: `Reki Kawahara`, `Brandon Sanderson`, `Actus`

**Level 2: Series Folder**
- Format: `{Series Name}` (cleaned, no suffixes)
- For standalone books: `{Series}` is the book title
- Examples: `Sword Art Online`, `Skyward`, `Project Hail Mary`

**Level 3: Book Folder**
- Format varies by book type (see below)
- **Standalone exception:** For standalone books, there is **no separate book folder** – files live directly under `{Author}/{Title}/`

### Book Folder Schema (Audiobookshelf)

#### Series Books (with arc/subtitle)
```
{Series} vol_{NN} {Arc} ({Year}) ({Author}) {ASIN.xxxxx} [{Tag}]
```

**Real examples from library:**
```
Sword Art Online vol_01 Aincrad (2021) (Reki Kawahara) {ASIN.1975337182}
Sword Art Online vol_03 Fairy Dance (2021) (Reki Kawahara) {ASIN.B09MJK5V9M}
Mushoku Tensei - Jobless Reincarnation vol_27 Recollections (2024) (Rifujin na Magonote) {ASIN.B0DP3CQC6N} [H2OKing]
Mushoku Tensei - Jobless Reincarnation vol_28 A Journey of Two Lifetimes (2025) (Rifujin na Magonote) {ASIN.B0F393V818} [H2OKing]
```

#### Series Books (no arc/subtitle)
```
{Series} vol_{NN} ({Year}) ({Author}) {ASIN.xxxxx} [{Tag}]
```

**Real examples:**
```
Skyward vol_01 (2018) (Brandon Sanderson) {ASIN.B07H7Q5D3M}
Mushoku Tensei - Jobless Reincarnation vol_01 (2023) (Rifujin na Magonote) {ASIN.B0CJWTXLPJ} [H2OKing]
Mushoku Tensei - Redundant Reincarnation vol_02 (2025) (Rifujin na Magonote) {ASIN.B0F3982MBX} [H2OKing]
```

#### Standalone Books
```
{Title}
```

**Real examples:**
```
Project Hail Mary/
└── Project Hail Mary.m4b    (files directly in series-level folder)
```

### Components Reference

| Component | Format | Required | Notes |
|-----------|--------|----------|-------|
| `{Series}` | Cleaned string | If series | Series name, suffixes removed |
| `vol_{NN}` | Zero-padded 2 digits | If series | `vol_01`, `vol_12`, `vol_99` |
| `{Arc}` | Cleaned subtitle | If exists | Arc/subtitle from metadata |
| `({Year})` | 4-digit year in parens | Always | Audiobook release year |
| `({Author})` | Cleaned author name | Always | Primary author |
| `{ASIN.xxxxx}` | ASIN in braces | Always | Amazon identifier |
| `[{Tag}]` | Ripper tag in brackets | Optional | Your username/group tag (e.g., `[H2OKing]`) |

### Ripper Tag

The `[{Tag}]` component identifies who ripped/uploaded the audiobook. This is:
- **Optional** - only added if configured
- **Configurable** - set your tag in `config.yaml`
- **Position** - always last, after ASIN
- **Used in both** - Audiobookshelf library AND MAM uploads

```yaml
# config.yaml
naming:
  ripper_tag: "H2OKing"  # Set to your username, or null/empty to disable
```

### File Name Schema

File name matches folder name with extension (but **without** the ripper tag):

```
{Series} vol_{NN} {Arc} ({Year}) ({Author}) {ASIN.xxxxx}.m4b
```

> **Note:** The ripper tag `[{Tag}]` is only on the **folder name**, not the file name. This keeps the m4b filename cleaner while still crediting the ripper in the folder structure.

**Real examples:**
```
Sword Art Online vol_01 Aincrad (2021) (Reki Kawahara) {ASIN.1975337182}.m4b
Mushoku Tensei - Jobless Reincarnation vol_27 Recollections (2024) (Rifujin na Magonote) {ASIN.B0DP3CQC6N}.m4b
```

For multi-file audiobooks (rare):
```
{Series} vol_{NN} {Arc} ({Year}) ({Author}) {ASIN.xxxxx} - Part {N}.m4b
```

### Full Path Examples (Audiobookshelf Library)

> These examples show the **Audiobookshelf library organization** structure, NOT the MAM torrent staging paths. MAM uploads use flat folder structure per the MAM upload requirements.

**Series book with arc and ripper tag:**
```
/audiobooks/Rifujin na Magonote/Mushoku Tensei - Jobless Reincarnation/Mushoku Tensei - Jobless Reincarnation vol_27 Recollections (2024) (Rifujin na Magonote) {ASIN.B0DP3CQC6N} [H2OKing]/
├── Mushoku Tensei - Jobless Reincarnation vol_27 Recollections (2024) (Rifujin na Magonote) {ASIN.B0DP3CQC6N}.m4b
├── Mushoku Tensei - Jobless Reincarnation vol_27 Recollections (2024) (Rifujin na Magonote) {ASIN.B0DP3CQC6N}.cue
├── cover.jpg
└── metadata.json
```

**Series book without arc (with ripper tag):**
```
/audiobooks/Rifujin na Magonote/Mushoku Tensei - Jobless Reincarnation/Mushoku Tensei - Jobless Reincarnation vol_01 (2023) (Rifujin na Magonote) {ASIN.B0CJWTXLPJ} [H2OKing]/
├── Mushoku Tensei - Jobless Reincarnation vol_01 (2023) (Rifujin na Magonote) {ASIN.B0CJWTXLPJ}.m4b
├── Mushoku Tensei - Jobless Reincarnation vol_01 (2023) (Rifujin na Magonote) {ASIN.B0CJWTXLPJ}.cue
├── Mushoku Tensei - Jobless Reincarnation vol_01 (2023) (Rifujin na Magonote) {ASIN.B0CJWTXLPJ}.epub
├── cover.jpg
└── metadata.json
```

**Series book (no ripper tag):**
```
/audiobooks/Reki Kawahara/Sword Art Online/Sword Art Online vol_03 Fairy Dance (2021) (Reki Kawahara) {ASIN.B09MJK5V9M}/
├── Sword Art Online vol_03 Fairy Dance (2021) (Reki Kawahara) {ASIN.B09MJK5V9M}.m4b
├── cover.jpg
└── metadata.json
```

**Standalone book:**
```
/audiobooks/Andy Weir/Project Hail Mary/
├── Project Hail Mary.m4b
├── cover.jpg
└── metadata.json
```

---

### MAM Staging Paths (Torrent Uploads)

MAM torrent staging uses a **flat folder structure** (no Author/Series nesting) with a single book folder containing all files:

```
{staging_root}/{Book Folder}/
├── {filename}.m4b
├── {filename}.cue (optional)
├── cover.jpg
└── metadata.json (optional)
```

**Key differences from Audiobookshelf library:**

| Aspect | Audiobookshelf Library | MAM Staging |
|--------|------------------------|-------------|
| Nesting | `Author/Series/Book/` | Flat: `Book/` only |
| Root | `/audiobooks/` (library) | `{staging_root}/` (config) |
| Ripper tag | `[{Tag}]` in folder name | `[{Tag}]` in folder name |
| Purpose | Long-term organization | Temporary upload staging |

**MAM staging example:**
```
/staging/Mushoku Tensei - Jobless Reincarnation vol_27 Recollections (2024) (Rifujin na Magonote) {ASIN.B0DP3CQC6N} [H2OKing]/
├── Mushoku Tensei - Jobless Reincarnation vol_27 Recollections (2024) (Rifujin na Magonote) {ASIN.B0DP3CQC6N}.m4b
├── cover.jpg
└── metadata.json
```

> Note: The ripper tag `[{Tag}]` appears in the **folder name only**, not in the `.m4b` filename. This keeps files clean while still crediting the ripper.

---

### Character Limits

- MAM path limit: **225 characters max** for the **full relative path** (`folder/filename`)
- This is NOT per-component - it's the combined `{folder}/{filename}` length
- Truncation priority (preserve most important first):
  1. `{Series}` + `vol_{NN}` (identity - NEVER drop)
  2. `{ASIN.xxxxx}` (lookup key - NEVER drop)
  3. `[{Tag}]` (ripper credit - drop 4th, folder only)
  4. `({Year})` (sorting - drop 3rd)
  5. `({Author})` (attribution - drop 2nd)
  6. `{Arc}` (subtitle/arc - drop 1st)

**Why full path matters:** MAM validates the torrent's internal path structure. The path `folder/filename.m4b` must be ≤225 chars total.

**Path structure:**
```
{Folder Name} [Tag]/
└── {Filename}.m4b

Example:
Trapped in a Dating Sim vol_01 ... [H2OKing]/Trapped in a Dating Sim vol_01 ....m4b
└─────────────────────── Full path must be ≤225 chars ───────────────────────────┘
```

**Truncation strategy:** Components are dropped from BOTH folder and filename simultaneously. `{Arc}` is dropped first, then `({Author})`, then `({Year})`, then `[{Tag}]` (folder only). **`{Series}`, `vol_{NN}`, and `{ASIN}` are never dropped.** If the path is still too long after dropping all optional components, truncate `{Series}` with `...` but never break the ASIN.

#### Truncation Examples

**Example 1: Long series name with all components (fits)**
```
Sword Art Online vol_16 Alicization Exploding (2025) (Reki Kawahara) {ASIN.B0DK9TS6D9} [H2OKing]
└─ 95 chars ✅ OK
```

**Example 2: Very long series + arc that exceeds 225 chars**
```
Input (240 chars):
The Extraordinarily Long Light Novel Series Name That Just Keeps Going vol_12 The Equally Long Arc Subtitle Name (2025) (Author With A Very Long Name Indeed) {ASIN.B0ABC12345} [H2OKing]

Step 1 - Drop Arc (still 195 chars):
The Extraordinarily Long Light Novel Series Name That Just Keeps Going vol_12 (2025) (Author With A Very Long Name Indeed) {ASIN.B0ABC12345} [H2OKing]

Step 2 - Drop Author (still 140 chars - but let's say we need more):
The Extraordinarily Long Light Novel Series Name That Just Keeps Going vol_12 (2025) {ASIN.B0ABC12345} [H2OKing]

Final (fits at ~115 chars):
The Extraordinarily Long Light Novel Series Name That Just Keeps Going vol_12 (2025) {ASIN.B0ABC12345} [H2OKing]
```

**Example 3: Extreme case - series name alone is too long**
```
Input:
The Most Ridiculously Extraordinarily Impossibly Long Light Novel Series Name That Someone Actually Published vol_01 {ASIN.B0XYZ98765}

If series alone + vol + ASIN exceeds 225:
The Most Ridiculously Extraordinarily Impossibly Long Light Novel Series Na... vol_01 {ASIN.B0XYZ98765}
└─ Series truncated with "..." to fit, ASIN preserved intact
```

**Example 4: Standalone book (no series)**
```
Schema: {Title} ({Year}) ({Author}) {ASIN.xxxxx} [{Tag}]

Full:
A Very Long Standalone Book Title That Goes On And On (2025) (Some Author Name) {ASIN.B0DEF67890} [H2OKing]

If too long, drop order: Author → Year → Tag → Truncate Title
```

#### Real-World Examples (from Library)

These examples come from actual `samples/library_full.json` data:

**Example A: "I Parry Everything" Series (Light Novel with extremely long series name)**

Source metadata:
```
Title:  "I Parry Everything: What Do You Mean I'm the Strongest? I'm Not Even an Adventurer Yet!, Volume 2"
Series: "What Do You Mean I'm the Strongest? I'm Not Even an Adventurer Yet!"
ASIN:   B0F259867P
Author: Nabeshiki
Year:   2025
```

Expected raw folder (230+ chars - exceeds 225 limit):
```
What Do You Mean I'm the Strongest? I'm Not Even an Adventurer Yet! vol_02 (2025) (Nabeshiki) {ASIN.B0F259867P} [H2OKing]
```

Actual result (120 chars ✅):
```
What Do You Mean I'm the Strongest I'm Not Even an Adventurer Yet! vol_02 (2025) (Nabeshiki) {ASIN.B0F259867P} [H2OKing]
```

> **Note:** Punctuation (`?`, `!`) is normalized/removed by `sanitize_filename()`, making the series name significantly shorter. No truncation needed.

**Example B: "Campfire Cooking" Series (Long but fits)**

Source metadata:
```
Title:  "Campfire Cooking in Another World with My Absurd Skill: Vol. 3"
Series: "Campfire Cooking in Another World with My Absurd Skill"
ASIN:   B0CL5FYFPS
Author: Ren Eguchi
Year:   2021
```

Actual result (109 chars ✅):
```
Campfire Cooking in Another World with My Absurd Skill vol_03 (2021) (Ren Eguchi) {ASIN.B0CL5FYFPS} [H2OKing]
```

**Example C: "Space Mercenary" Series (Subtitle in series name)**

Source metadata:
```
Title:  "Reborn as a Space Mercenary: I Woke Up Piloting the Strongest Starship!, Vol. 10"
Series: "Reborn as a Space Mercenary: I Woke Up Piloting the Strongest Starship!"
ASIN:   B0DP1LDBYV
Author: Ryuto
Year:   2024
```

Actual result (122 chars ✅):
```
Reborn as a Space Mercenary - I Woke Up Piloting the Strongest Starship! vol_10 (2024) (Ryuto) {ASIN.B0DP1LDBYV} [H2OKing]
```

> **Note:** Colon (`:`) is replaced with ` - ` for filesystem safety.

#### Progressive Truncation Demonstration

Using a synthetic example to show the full truncation cascade:

```python
series = "The Chronicles of the Mystical Adventures in the Enchanted Realm of the Ancient Dragons and Their Legendary Treasures Across the Seven Kingdoms of Eternal Light"
# Series alone: 160 chars
```

| max_length | Result Length | What's Dropped |
|------------|---------------|----------------|
| 300 | 224 | Nothing (full name) |
| 225 | 224 | Nothing (fits MAM limit ✅) |
| 200 | 195 | Author, Year dropped |
| 150 | 150 | + Tag dropped, Series truncated with `...` |
| 100 | 100 | Series further truncated |

```
max=225: ...Kingdoms of Eternal Light vol_05 (2024) (John Smith-Williams) {ASIN.B0ABCDEFGH} [H2OKing]
max=200: ...Kingdoms of Eternal Light vol_05 {ASIN.B0ABCDEFGH} [H2OKing]
max=150: ...Across the Seven Kingdoms of Eternal Light vol_05 {ASIN.B0ABCDEFGH}  (series truncated)
max=100: ...the Enchanted Realm of the ... vol_05 {ASIN.B0ABCDEFGH}  (hard truncation)
```

#### What's Preserved vs Dropped

| Component | Priority | Action if Too Long |
|-----------|----------|-------------------|
| `{Series}` | 1 (highest) | Truncate with `...` as last resort |
| `vol_{NN}` | 1 (highest) | NEVER drop or truncate |
| `{ASIN.xxx}` | 2 | NEVER drop or truncate |
| `[{Tag}]` | 3 | Drop 4th |
| `({Year})` | 4 | Drop 3rd |
| `({Author})` | 5 | Drop 2nd |
| `{Arc}` | 6 (lowest) | Drop 1st |

> **Why ASIN is sacred:** The ASIN is the unique identifier for MAM lookups and duplicate detection. Breaking or truncating it makes the upload useless for the tracker's systems.

### MAM JSON Output Schema

```json
{
  "title": "{Title}, Vol. {N}",
  "subtitle": "{Subtitle}",
  "series": "{Series}",
  "series_number": "{N}",
  "authors": ["{Author1}", "{Author2}"],
  "narrators": ["{Narrator1}"],
  "year": "{Year}",
  "description": "{Description}"
}
```

> **`series_number` source of truth:** If `series_number` is missing from source metadata, it is derived from the detected Vol/Book number in the title. The folder `vol_{NN}` and JSON `series_number` must stay in sync.

**Key differences from folder/file naming:**

| Field | Folder/File | JSON |
|-------|-------------|------|
| Volume format | `vol_03` | `Vol. 3` (human-readable) |
| Year format | `(2021)` | `2021` (no parens) |
| Author format | `(Reki Kawahara)` | `["Reki Kawahara"]` |
| ASIN | `{ASIN.xxxxx}` | Separate field |
| Arc/Subtitle | In folder name | `subtitle` field |

**JSON Title examples:**
```
Sword Art Online, Vol. 3              # Series book
Project Hail Mary                     # Standalone
Sword Art Online: Progressive, Vol. 2  # Nested series (colon preserved via preserve_exact)
```

[↑ Back to top](#table-of-contents)

---

## Matching Rules by Category

Each category has specific matching behavior:

| Category | Case | Position | Type | Notes |
|----------|------|----------|------|-------|
| `format_indicators` | Insensitive | Anywhere | Whole phrase | Won't match partial words |
| `genre_tags` | Insensitive | End/Suffix | Whole phrase | Often at end of title |
| `series_suffixes` | Insensitive | End only | Suffix | Must be at end of string |
| `subtitle_patterns` | Insensitive | Regex | Pattern | Uses regex anchors |
| `publisher_tags` | Insensitive | Anywhere | Whole phrase | Usually in brackets |
| `preserve_exact` | Sensitive | Exact | Full match | Bypass all cleaning |
| `author_map` | Sensitive | Exact | Full match | Key must match exactly |

---

## Phrase Removal Rules

### Category: Format Indicators
**Matching:** Case-insensitive, anywhere in string, whole phrase only

```json
{
  "format_indicators": {
    "_comment": "Remove from titles, subtitles, series. Case-insensitive matching.",
    "phrases": [
      "(Light Novel)", "Light Novel",
      "(Manga)", "(Graphic Novel)",
      "(Unabridged)", "Unabridged",
      "(Audiobook)", "Audiobook"
    ]
  }
}
```

> **Note:** Case variants (e.g., `"(light novel)"`) are NOT listed separately since matching is case-insensitive.

### Category: Genre Tags
**Matching:** Case-insensitive, typically at end, whole phrase only

```json
{
  "genre_tags": {
    "_comment": "Remove genre tags from titles/subtitles.",
    "phrases": [
      "A LitRPG Adventure", "LitRPG Adventure", "A LitRPG",
      "An Isekai LitRPG", "A Fantasy Adventure",
      "A Sci-Fi Light Novel", "A Sci-Fi Adventure",
      "A Novel", "A GameLit Novel", "A Cultivation Novel",
      "A Progression Fantasy Epic", "A Progression Fantasy",
      "An Urban Fantasy", "A Slice-of-Life Urban Fantasy",
      ": A LitRPG Adventure", ": A Fantasy Adventure"
    ]
  }
}
```

### Category: Series Suffixes
**Matching:** Case-insensitive, end of string only, regex pattern

```json
{
  "series_suffixes": {
    "_comment": "Remove from series names only. Regex pattern.",
    "patterns": [
      "[\\s—-]?[Ss]eries$",
      "[\\s—-]?[Tt]rilogy$",
      "[\\s—-]?[Ss]aga$",
      "[\\s—-]?[Cc]hronicles$",
      "\\s*\\([Ll]ight [Nn]ovel\\)$",
      "\\s+[Ll]ight [Nn]ovel$"
    ]
  }
}
```

**Examples:**
- `"A Most Unlikely Hero Series"` → `"A Most Unlikely Hero"`
- `"Kuma Kuma Kuma Bear Light Novel"` → `"Kuma Kuma Kuma Bear"`
- `"The Stormlight Archive"` → Keep (no suffix match)

### Category: Publisher Tags (NEW)
**Matching:** Case-insensitive, anywhere in string

```json
{
  "publisher_tags": {
    "_comment": "Remove publisher cruft sometimes embedded in titles.",
    "phrases": [
      "[Yen Audio]", "[J-Novel Club]", "[Seven Seas]",
      "(Yen Audio)", "(J-Novel Club)", "(Seven Seas)"
    ]
  }
}
```

### Category: Preserve Exact (NEW)
**Matching:** Case-sensitive, exact full match - bypasses ALL cleaning

**Scope:** When a title OR series matches an entry in `preserve_exact`, the cleaning pipeline is skipped entirely for BOTH the title AND series fields. This prevents partial cleaning from breaking intentional formatting (e.g., `Re:ZERO` shouldn't have the colon removed even when it appears in the series name).

```json
{
  "preserve_exact": {
    "_comment": "Titles that should bypass cleaning rules entirely.",
    "titles": [
      "Re:ZERO",
      "86--EIGHTY-SIX",
      "Sword Art Online: Progressive",
      "Is It Wrong to Try to Pick Up Girls in a Dungeon?"
    ]
  }
}
```

### Category: Subtitle Patterns
**Matching:** Regex-based, typically suffix position

```json
{
  "subtitle_patterns": {
    "_comment": "Two-tier subtitle handling.",
    "remove_if_matches_series": true,
    "remove_patterns": [
      "^[Ll]ight [Nn]ovel$",
      "^[Nn]ovel$",
      "^[Uu]nabridged$"
    ],
    "keep_patterns": [
      ".*Aria.*",
      ".*Chronicle.*"
    ]
  }
}
```

**Subtitle Strategy (Two-Tier):**
1. If subtitle matches a `remove_patterns` entry → Remove entirely
2. If subtitle matches `keep_patterns` → Preserve as-is
3. If subtitle duplicates series name → Remove (if `remove_if_matches_series: true`)
4. Otherwise → Keep the subtitle (preserve unknown/useful subtitles)

### Category: Subtitle Redundancy Rules (NEW)
**Matching:** Dynamic regex with `{{series}}` and `{{title}}` placeholders

Based on library analysis: **55 books** have subtitles that are just "Series, Book X" - pure redundancy.

```json
{
  "subtitle_redundancy_rules": {
    "_comment": "Drop subtitle if it only repeats series/title + book number.",
    "enabled": true,
    "rules": [
      {
        "id": "series_book",
        "description": "Subtitle is just 'Series, Book N'",
        "pattern_template": "^{{series}},?\\s*Book\\s*\\d+$",
        "action": "drop_subtitle"
      },
      {
        "id": "series_volume",
        "description": "Subtitle is just 'Series, Vol/Volume N'",
        "pattern_template": "^{{series}},?\\s*Vol(?:ume)?\\.?\\s*\\d+$",
        "action": "drop_subtitle"
      },
      {
        "id": "title_book",
        "description": "Subtitle is just 'Title, Book N'",
        "pattern_template": "^{{title}},?\\s*Book\\s*\\d+$",
        "action": "drop_subtitle"
      },
      {
        "id": "series_in_parens",
        "description": "Subtitle contains '(Series, Book N)' pattern",
        "pattern_template": "\\({{series}},?\\s*Book\\s*\\d+\\)",
        "action": "strip_match"
      }
    ]
  }
}
```

**Action Types:**
- `drop_subtitle`: Remove the entire subtitle (for rules 1-3 where the whole subtitle is redundant)
- `strip_match`: Remove only the matching portion, keep the rest (for rule 4 where extra content may exist)

**How it works:**
1. At runtime, replace `{{series}}` with `re.escape(actual_series_name)`
2. Replace `{{title}}` with `re.escape(actual_title)`
3. **Skip rules with `{{series}}`** if series is empty/None
4. If subtitle matches a `drop_subtitle` rule → **remove subtitle entirely**
5. If subtitle matches a `strip_match` rule → **remove only matched portion, clean up spacing**

> **Rule design constraint:** `drop_subtitle` rules MUST use anchored patterns (`^...$`) that match the full subtitle. Partial matches should always use `strip_match` rules.

**Examples:**
| Title | Subtitle | Series | Action |
|-------|----------|--------|--------|
| `He Who Fights with Monsters 11` | `He Who Fights with Monsters, Book 11` | `He Who Fights...` | ❌ DROP (rule 1) |
| `The Wandering Inn` | `The Wandering Inn, Book 1` | `The Wandering Inn` | ❌ DROP (rule 1) |
| `Classroom of the Elite: Year 2, Vol. 11` | `Light Novel (Classroom of the Elite, Book 27)` | `Classroom of the Elite` | ⚠️ STRIP → `Light Novel` (rule 4) |
| `Dungeon Crawler Carl` | `A LitRPG Adventure` | `Dungeon Crawler Carl` | ✅ KEEP (no match) |
| `Solo Book` | `Solo Book, Book 1` | *(none)* | ✅ KEEP (skip rule 1, series empty) |

---

## Author Map (Transliteration)

**Matching:** Case-sensitive, exact full match on author name

```json
{
  "author_map": {
    "_comment": "Japanese/foreign author name → romanized. Exact match.",
    "猫子": "Necoco",
    "リュート": "Ryuto",
    "赤井まつり": "Matsuri Akai",
    "くまなの": "Kumanano",
    "理不尽な孫の手": "Rifujin na Magonote",
    "りゅうせんひろつぐ": "Ryusen Hirotsugu",
    "一色一凛": "Isshiki Ichirin",
    "三嶋与夢": "Mishima Yomu",
    "五示正司": "Goji Shoji",
    "橘 由華": "Tachibana Yuka",
    "澪亜": "Mio-A"
  }
}
```

**Fallback Behavior:**
1. Check `author_map` for exact match → use mapped value
2. If not in map and contains Japanese → use `pykakasi` transliteration
3. If not Japanese but non-ASCII → use `unidecode`
4. Otherwise → keep original

**Applied to:** MAM JSON authors and narrators fields only (not folder/file names)

[↑ Back to top](#table-of-contents)

---

## Vol/Book Normalization

**Detection patterns:**
```regex
Vol\.?\s*(\d+)
Volume\s+(\d+)
Book\s+(\d+)
Book\s+#(\d+)
,\s*Vol\.?\s*(\d+)
```

**Zero-padding rule:** All volume/book numbers are zero-padded to 2 digits (e.g., `1` → `01`, `5` → `05`, `12` → `12`). This ensures proper lexical sorting in file managers.

**Output formats by context:**

| Context | Input | Output |
|---------|-------|--------|
| Folder name | `Overlord, Vol. 3` | `Overlord vol_03` |
| Folder name | `Overlord, Vol. 12` | `Overlord vol_12` |
| File name | `Overlord, Vol. 3.m4b` | `Overlord vol_03.m4b` |
| MAM JSON Title | `Overlord, Vol. 3` | `Overlord, Vol. 3` |
| MAM JSON Series | `Overlord, Vol. 3` | `Overlord` |

---

## naming.json Schema

Complete schema with version tracking:

```json
{
  "_version": "1.1.0",
  "_comment": "Naming rules for MAMFast. See docs/NAMING_PLAN.md for details.",

  "format_indicators": {
    "_comment": "Remove from titles, subtitles, series. Case-insensitive.",
    "match_mode": "phrase",
    "case_sensitive": false,
    "phrases": ["(Light Novel)", "Unabridged", "..."]
  },

  "genre_tags": {
    "_comment": "Remove genre tags. Case-insensitive, typically suffix.",
    "match_mode": "phrase",
    "case_sensitive": false,
    "phrases": ["A LitRPG Adventure", "..."]
  },

  "series_suffixes": {
    "_comment": "Remove from series names. Regex, end-anchored.",
    "match_mode": "regex",
    "case_sensitive": false,
    "patterns": ["[\\s—-]?[Ss]eries$", "..."]
  },

  "publisher_tags": {
    "_comment": "Remove publisher cruft.",
    "match_mode": "phrase",
    "case_sensitive": false,
    "phrases": ["[Yen Audio]", "..."]
  },

  "subtitle_patterns": {
    "_comment": "Two-tier subtitle handling.",
    "remove_if_matches_series": true,
    "remove_patterns": ["^Light Novel$"],
    "keep_patterns": [".*Aria.*"]
  },

  "preserve_exact": {
    "_comment": "Bypass all cleaning for these titles.",
    "case_sensitive": true,
    "titles": ["Re:ZERO", "86--EIGHTY-SIX"]
  },

  "author_map": {
    "_comment": "Foreign name → romanized. Exact match.",
    "猫子": "Necoco"
  }
}
```

[↑ Back to top](#table-of-contents)

---

## Sample Data Sources

To refine these rules, we collected real samples from these sources:

### 1. Export Libation Library
```bash
docker exec Libation /libation/LibationCli export --json -p /tmp/library.json
docker cp Libation:/tmp/library.json ./samples/library_export.json
```

Fields to analyze:
- `Title`
- `Subtitle`
- `SeriesNames`
- `Description` (first 200 chars)

### 2. Existing Staging Folders
```bash
ls /mnt/user/data/downloads/torrents/qbittorrent/seedvault/audiobooks/ > samples/existing_folders.txt
```

### 3. Audnex API Responses
Save raw responses from metadata fetches for analysis.

---

## Library Analysis Results

### Audiobookshelf Library (2025-12-02)

**Source:** 1,295 books from Audiobookshelf API (`samples/audiobookshelf_library.json`)

#### Subtitle Patterns to Clean
| Pattern | Count | Action |
|---------|-------|--------|
| "Light Novel" (exact) | 52 | Drop subtitle entirely |
| "A LitRPG Adventure" | 21 | Drop subtitle entirely |
| "Novel" or "A Novel" | 6 | Drop subtitle entirely |
| "A Progression Fantasy" | 3 | Drop subtitle entirely |
| Series name in subtitle | 5 | Strip series portion only |

#### Title Patterns to Clean
| Pattern | Count | Action |
|---------|-------|--------|
| `(Unabridged)` in title | 57 | Remove |
| `Vol. X` in title | 428 | Keep but normalize to `Vol. X` |
| `Volume X` in title | 181 | Keep but normalize to `Vol. X` |
| `Light Novel` in title | 46 | Remove |

#### Non-ASCII Content
| Type | Count | Examples |
|------|-------|----------|
| Japanese titles | 7 | `ゴブリンスレイヤー`, `本好きの下剋上` |
| Polish titles | 3 | `Krew elfów`, `Ostatnie życzenie` |
| Smart quotes | 5 | `Harry Potter and the Philosopher's Stone` |

#### Series Metadata Quality
- Books with series: 1,274 (98.4%)
- Books with ASIN: 1,284 (99.2%)
- Books with subtitle: 743 (57.4%)

### Libation Export (2025-12-01)

**Source:** 368 books from Libation export (`samples/library_full.json`)

#### Title/Subtitle Overlap Analysis
| Issue Type | Count | Action |
|------------|-------|--------|
| Series in Title | 130 | ✅ Normal - don't touch |
| Series in Subtitle | 55 | ❌ Strip series portion |
| "Series, Book X" pattern | 53 | ❌ Drop subtitle |
| Title in Subtitle | 7 | ❌ Strip title portion |

[↑ Back to top](#table-of-contents)

---

## Implementation Phases

### Phase 1: Create naming.json Structure ✅
- [x] Create `config/naming.json` schema
- [x] Migrate existing `remove_phrases` from config.yaml
- [x] Migrate `author_map` from config.yaml
- [x] Update config.py to load naming.json
- [x] Add NamingConfig dataclass
- [x] Add tests for config loading
- [x] Add subtitle_patterns (remove + keep)
- [x] Add subtitle_redundancy_rules with action types
- [x] Add publisher_tags category
- [x] Add preserve_exact category
- [x] Document all rule categories in NAMING_PLAN.md

### Phase 1.5: Document Folder/File Schemas ✅ (NEW)
- [x] Define 3-level library nesting structure
- [x] Document book folder schema (with/without arc)
- [x] Document standalone book exception
- [x] Add `[{Tag}]` ripper tag component
- [x] Document file naming schema
- [x] Add truncation strategy and priority
- [x] Add MAM JSON output schema
- [x] Document real examples from library (SAO, Mushoku Tensei, Skyward)

### Phase 2: Update naming.py to Use Config ✅
- [x] Refactor `filter_title()` to use `settings.naming`
- [x] Add `filter_series()` function for series-specific cleaning
- [x] Implement `preserve_exact` bypass logic
- [x] Add publisher_tags support
- [x] Add verbose logging for transformations (with rule IDs)

### Phase 3: Implement MAM JSON Cleaning ✅
- [x] Add `filter_title()` to title field in metadata.py (with `keep_volume=True`)
- [x] Add `filter_title()` to subtitle field (with `keep_volume=True`)
- [x] Add `filter_series()` for series names (via `_build_series_list()`)
- [x] Handle Vol/Book differently for JSON vs folders (`keep_volume` parameter)
- [x] Add tests for MAM JSON cleaning (9 tests in `TestBuildMamJsonCleaning`)
- [x] Add tests for `keep_volume` parameter (8 tests)

### Phase 4: Testing & Validation ✅
- [x] Create `tests/golden/` with input/expected pairs (20 test cases)
- [x] Add validation script (`src/mamfast/utils/validate_naming.py`)
- [x] Add preserve-exact drift check (in `TestGoldenPreserveExact`)
- [x] Test against full library export (368 books, 0 issues!)
- [x] Fixed edge cases: trailing colons, trailing commas, space before punctuation
- [x] Added cleanup patterns for dangling punctuation (`_TRAILING_PUNCT_PATTERN`, etc.)

### Phase 5: Subtitle Handling ✅
- [x] Implement two-tier subtitle strategy (remove_patterns + keep_patterns)
- [x] Implement subtitle_redundancy_rules with {{series}}/{{title}} templates
- [x] Test remove_if_matches_series logic
- [x] Support both `drop_subtitle` and `strip_match` actions

### Phase 6: Folder/File Generation ✅
- [x] Implement `extract_volume_number()` and `format_volume_number()`
- [x] Implement `build_mam_folder_name()` using schema
- [x] Implement `build_mam_file_name()` using schema
- [x] Add ripper_tag config option
- [x] Implement truncation logic (225 char limit) with priority dropping
- [x] Handle standalone vs series books differently (title-only fallbacks)
- [x] Added 22 tests for folder/file generation
- [x] **Integrated into hardlinker.py** - `stage_release()` now uses `build_mam_folder_name()` and `build_mam_file_name()`

### Phase 7: Audnex Normalization ✅
- [x] Created `NormalizedBook` dataclass in `models.py` with raw/display fields
- [x] Implemented `detect_swapped_title_subtitle()` using seriesPrimary as source of truth
- [x] Implemented `extract_arc_name()` for extracting arc from the "wrong" field
- [x] Implemented `normalize_audnex_book()` main entry point in `naming.py`
- [x] Added config option `title_subtitle_normalization.enabled` in `naming.json` (default: true)
- [x] Updated `NamingConfig` with `normalize_title_subtitle` flag
- [x] Wired normalization into `build_mam_json()` in `metadata.py`
- [x] Created test fixtures (`tests/fixtures/audnex_normalization_samples.json`) with 18 verified samples
- [x] Added 20 tests for normalization (`tests/test_normalization.py`)
- [x] Verified against live Audnex API - SAO vol_16, TBATE vols 1-4, Multiverse vol_7 confirmed swapped

### Phase 8: Full Path Truncation (BUG FIX) ✅
**Status:** COMPLETE

**Problem discovered:** The 225-char limit applies to the **full relative path** (`folder/filename`), not individual components. Current implementation truncates folder and filename separately, which can result in paths exceeding 225 chars.

**Real-world impact:** Testing against actual library samples shows **7 out of 7 light novel titles exceed 225 chars** when the full path is calculated:

| Series | Path Length | Over By |
|--------|-------------|---------|
| The Haunted Bookstore - Gateway to a Parallel Universe | 299 | +74 |
| Campfire Cooking... (with arc) | 297 | +72 |
| Failure Frame: I Became the Strongest... | 289 | +64 |
| Disciple of the Lich: Or How I Was Cursed... | 271 | +46 |
| I Got a Cheat Skill in Another World... | 253 | +28 |
| Trapped in a Dating Sim (with arc) | 241 | +16 |
| Now I'm a Demon Lord! Happily Ever After... | 241 | +16 |

**Example of the bug (Trapped in a Dating Sim):**
```
Trapped in a Dating Sim vol_01 The World of Otome Games is Tough for Mobs (2024) (Yomu Mishima) {ASIN.B0DK27WWT8} [H2OKing]/Trapped in a Dating Sim vol_01 The World of Otome Games is Tough for Mobs (2024) (Yomu Mishima) {ASIN.B0DK27WWT8}.m4b
└─ 241 chars ❌ EXCEEDS 225 by 16 chars
```

**Example of the bug (Haunted Bookstore - worst case):**
```
The Haunted Bookstore - Gateway to a Parallel Universe vol_01 The Spirit Daughter and the Exorcist Son (2022) (Shinobumaru) {ASIN.B09EXAMPLE1} [H2OKing]/The Haunted Bookstore - Gateway to a Parallel Universe vol_01 The Spirit Daughter and the Exorcist Son (2022) (Shinobumaru) {ASIN.B09EXAMPLE1}.m4b
└─ 299 chars ❌ EXCEEDS 225 by 74 chars
```

**Why the current code fails:**
- `build_mam_folder_name()` truncates to 225 chars → produces ~150 char folder
- `build_mam_file_name()` truncates to 225 chars → produces ~145 char filename
- Combined: `150 + 1 + 145 = 296 chars` (the `/` adds 1 char)
- Both components fit individually but combined path exceeds limit

#### The Math: Calculate Budget Upfront

The key insight is that the **base name appears TWICE** in the path. This means we can derive the max base length directly instead of iterating:

```python
# Path structure: "{base} [{tag}]/{base}.m4b"
#
# Components:
#   folder   = base + " [" + tag + "]"  →  len(base) + 3 + len(tag)
#   filename = base + ext               →  len(base) + len(ext)
#   separator = "/"                     →  1
#
# Total length = len(folder) + 1 + len(filename)
#              = (len(base) + 3 + len(tag)) + 1 + (len(base) + len(ext))
#              = 2*len(base) + len(tag) + len(ext) + 4
#
# For no tag:    length = 2*len(base) + len(ext) + 1
#                       = 2*len(base) + 4 + 1  (for ".m4b")
#                       = 2*len(base) + 5
#
# To fit in 225 chars:
#   WITH tag:    2*base + len(tag) + len(ext) + 4 ≤ 225
#                base ≤ (225 - len(tag) - len(ext) - 4) / 2
#
#   NO tag:      2*base + len(ext) + 1 ≤ 225
#                base ≤ (225 - len(ext) - 1) / 2
#
# Examples with ".m4b" (4 chars):
#   With "H2OKing" (7 chars): base ≤ (225 - 7 - 4 - 4) / 2 = 105 chars
#   With no tag:              base ≤ (225 - 4 - 1) / 2     = 110 chars
#
# Multi-file adjustment for " - Part XX.m4b" (14 chars worst case):
#   With "H2OKing" (7 chars): base ≤ (225 - 7 - 14 - 4) / 2 = 100 chars
#   With no tag:              base ≤ (225 - 14 - 1) / 2     = 105 chars
```

**This formula goes in the code comments.** Calculate budget upfront, don't iterate.

#### Return Type: MamPath Dataclass

Instead of returning a tuple, return a result object for better debugging:

```python
@dataclass
class MamPath:
    """Result of MAM path generation with truncation metadata."""
    folder: str              # e.g., "Series vol_01 ... [H2OKing]"
    filename: str            # e.g., "Series vol_01 ....m4b"
    full_path: str           # folder + "/" + filename
    length: int              # len(full_path)
    truncated: bool          # True if any truncation occurred
    dropped_components: list[str]  # ["arc", "author"] for logging
```

The `dropped_components` list makes debug logging trivial:
```
[build_mam_path] Truncated path for B0DK27WWT8: 225 chars
  - Dropped: arc, author
  - Final: "Trapped in a Dating Sim vol_01 (2024) {ASIN.B0DK27WWT8} [H2OKing]/..."
```

#### Multi-File Support

Account for multi-part audiobooks with `part_count` parameter:

```python
# Extension lengths:
#   Single file:  ".m4b"           = 4 chars
#   Multi-file:   " - Part 01.m4b" = 14 chars (worst case: Part 99)
#   Other files:  ".cue"           = 4 chars
#                 ".epub"          = 5 chars
#                 ".metadata.json" = 14 chars (!)
#
# Budget with longest extension reduces base by ~5 chars vs .m4b

def build_mam_path(
    ...,
    part_count: int = 1,  # Number of parts (1 = single file)
) -> MamPath:
    # Use worst-case extension for budget calculation
    if part_count > 1:
        ext_len = 14  # " - Part XX.m4b"
    else:
        ext_len = 4   # ".m4b"
```

#### Minimum Viable Base (Floor)

What's the absolute minimum if we drop everything optional?

```
{Series...} vol_{NN} {ASIN.xxxxx}
```

Shortest realistic example:
```
X... vol_01 {ASIN.B0XXXXXXXX}
└─ 32 chars minimum
```

**Assert/warn if series truncation is triggered** - it probably means bad input data or an edge case worth investigating.

```python
MIN_SERIES_LEN = 3  # Absolute floor before ellipsis

if len(series) <= MIN_SERIES_LEN:
    logger.warning(
        f"Series truncation hit floor for {asin}: '{series}' - check input data"
    )
```

#### Implementation

**Completed:**
- [x] Add `MamPath` dataclass to `models.py`
- [x] Add `build_mam_path()` function in `naming.py` that:
  - [x] Calculates max base length upfront using the formula
  - [x] Builds base name to fit exactly within budget
  - [x] Drops components in priority order: arc → author → year → tag
  - [x] Truncates series with `...` only as last resort (with warning)
  - [x] Returns `MamPath` with truncation metadata
- [x] Add `part_count` parameter for multi-file support
- [x] Use worst-case extension length for budget calculation
- [x] Update `hardlinker.py` to use new `build_mam_path()` function
- [x] Separate `build_mam_folder_name()` / `build_mam_file_name()` retained for backwards compatibility
- [x] Add tests for full path length validation (13 tests in `TestBuildMamPath`)
- [x] Add specific test: Haunted Bookstore (299 chars) → truncates to exactly ≤225

```python
def build_mam_path(
    *,
    series: str | None,
    title: str,
    volume_number: str | None,
    arc: str | None,
    year: str | None,
    author: str | None,
    asin: str,
    ripper_tag: str | None = None,
    extension: str = ".m4b",
    part_count: int = 1,
    max_path_length: int = 225,
) -> MamPath:
    """
    Build folder and filename ensuring combined path ≤ max_path_length.

    Path structure: "{base} [{tag}]/{base}{ext}"

    Budget formula (with tag):
        2*len(base) + len(tag) + len(ext) + 4 ≤ max_path_length
        max_base = (max_path_length - len(tag) - len(ext) - 4) // 2

    Budget formula (no tag):
        2*len(base) + len(ext) + 1 ≤ max_path_length
        max_base = (max_path_length - len(ext) - 1) // 2

    Returns:
        MamPath with folder, filename, and truncation metadata.
    """
    # 1. Calculate extension length (worst case for multi-file)
    if part_count > 1:
        ext_len = 14  # " - Part XX.m4b"
    else:
        ext_len = len(extension)

    # 2. Calculate max base length using formula
    tag_overhead = len(f" [{ripper_tag}]") if ripper_tag else 0
    if ripper_tag:
        # With tag: folder = base + " [tag]", filename = base + ext
        # Total = 2*base + 3 + len(tag) + 1 + ext_len = 2*base + tag_overhead + ext_len + 1
        fixed_overhead = tag_overhead + ext_len + 1
    else:
        # No tag: folder = base, filename = base + ext
        # Total = 2*base + 1 + ext_len
        fixed_overhead = ext_len + 1

    max_base_len = (max_path_length - fixed_overhead) // 2

    # 3. Build base name to fit within max_base_len
    base = _build_base_name(
        series=series,
        title=title,
        volume_number=volume_number,
        arc=arc,
        year=year,
        author=author,
        asin=asin,
        max_length=max_base_len,
    )

    # 4. Construct folder and filename
    folder = f"{base} [{ripper_tag}]" if ripper_tag else base
    filename = f"{base}{extension}"
    full_path = f"{folder}/{filename}"

    return MamPath(
        folder=folder,
        filename=filename,
        full_path=full_path,
        length=len(full_path),
        truncated=base.truncated,
        dropped_components=base.dropped_components,
    )
```

#### Test Cases

**Required tests for Phase 8:**

1. **Barely over** - Trapped in a Dating Sim (241 chars)
   - Verify dropping `{Arc}` alone is sufficient
   - Confirm author/year/tag are NOT dropped

2. **Worst case** - Haunted Bookstore (299 chars)
   - Must drop arc, author, year, tag AND truncate series
   - Verify `series` ends with `...`
   - Verify `vol_XX` and `{ASIN}` are intact
   - Verify final path length ≤ 225

3. **Multi-file** - Same titles with `part_count=2`
   - Verify budget accounts for ` - Part XX.m4b` (14 chars)
   - Verify truncation triggers earlier

4. **No truncation needed** - Short series like "Overlord vol_01"
   - Verify `truncated=False`
   - Verify `dropped_components=[]`

5. **Edge case: minimum series**
   - Series that's already very short
   - Verify warning is logged
   - Verify floor of 3 chars is respected

---

## Current Status 🔧

Phase 8 (Full Path Truncation) is required before the naming implementation is complete.

[↑ Back to top](#table-of-contents)

---

## Testing Strategy

### Golden File Tests
Create `tests/golden/` directory with:
- `naming_inputs.json` - Raw titles/series/authors
- `naming_expected.json` - Expected cleaned output

```python
# Test validates:
# 1. Each input produces expected output
# 2. No regressions when rules change
```

### Validation Script
Run against full library to flag suspicious results:
```python
# Flags:
# - Empty result after cleaning
# - Result shorter than 3 characters
# - Leftover brackets [], ()
# - Dangling punctuation (trailing comma, colon)
# - Double spaces
# - Change too large: |len(output) - len(input)| / len(input) > 0.5
#   (losing more than 50% of the original string is suspicious)
# - Preserve-exact drift: if input in preserve_exact and output != input → ERROR
#   (guards against refactors accidentally cleaning protected strings)
```

### Verbose Logging Mode
When `LOG_LEVEL=DEBUG`, log with consistent rule IDs:
```
[filter_title] "Overlord (Light Novel)" -> "Overlord"
  - removed: "(Light Novel)" [format_indicators]
[filter_series] "A Most Unlikely Hero Series" -> "A Most Unlikely Hero"
  - removed: " Series" [series_suffixes]
[filter_subtitle] "He Who Fights with Monsters, Book 11" -> ""
  - matched rule: subtitle_redundancy_rules.series_book (drop_subtitle)
[filter_subtitle] "Light Novel (Classroom of the Elite, Book 27)" -> "Light Novel"
  - matched rule: subtitle_redundancy_rules.series_in_parens (strip_match)
```

[↑ Back to top](#table-of-contents)

---

## Questions Resolved

1. **Description cleaning** → Minimal: transliteration + trailing format stripping only

2. **Edge cases** → Use `preserve_exact` list:
   - `"Re:ZERO"` → preserved (colon is part of title)
   - `"86--EIGHTY-SIX"` → preserved (number is the title)
   - `"Sword Art Online: Progressive"` → preserved (Progressive is meaningful)

3. **Author fallback** → Map → pykakasi → unidecode → original

4. **Case sensitivity** → All phrase matching is case-insensitive except `preserve_exact` and `author_map`

5. **Matching position** → Explicitly defined per category (anywhere vs suffix-only)

[↑ Back to top](#table-of-contents)

---

## Future Enhancements (Nice-to-Have)

### Context-Based Rules
Eventually could extend naming.json to support context overrides:
```json
{
  "contexts": {
    "folder_name": {
      "apply": ["format_indicators", "genre_tags", "series_suffixes"],
      "keep_vol": false
    },
    "mam_title": {
      "apply": ["format_indicators", "genre_tags"],
      "keep_vol": true
    }
  }
}
```

### Community Rules
- Fetch remote naming.json updates
- Merge community patterns with local overrides

[↑ Back to top](#table-of-contents)

---

## Changelog

- **2025-12-02**: Initial planning document created
- **2025-12-02**: Added pipeline order, matching rules, glossary, preserve_exact, publisher_tags, testing strategy (feedback from ChatGPT/Claude review)
- **2025-12-02**: Added subtitle_redundancy_rules with template-based patterns ({{series}}/{{title}}) to remove "Series, Book X" redundancy - affects 55+ books
- **2025-12-02**: Added folder/file naming schemas with real library examples (SAO, Mushoku Tensei, Skyward)
- **2025-12-02**: Added `[{Tag}]` ripper tag component (e.g., `[H2OKing]`)
- **2025-12-02**: Clarified standalone book layout (no separate book folder), pipeline field scope, truncation strategy, series_number source of truth, description exclusions, logging rule IDs, preserve-exact drift validation (ChatGPT review round 2)
- **2025-12-02**: Implemented Phase 7 - Audnex Normalization Layer. Fixes title/subtitle swaps using `seriesPrimary` as source of truth. Added `NormalizedBook` dataclass, detection/extraction functions, 20 tests, and 18 verified API samples
- **2025-12-03**: Added real-world truncation examples from `samples/library_full.json` (I Parry Everything, Campfire Cooking, Space Mercenary)
- **2025-12-03**: **BUG DISCOVERED** - 225-char limit applies to full path (`folder/filename`), not individual components. Added Phase 8 to fix truncation logic. Example: "Trapped in a Dating Sim" path is 241 chars, exceeds limit. Updated Character Limits section with correct path calculation.
- **2025-12-03**: **Phase 8 refined** with external feedback: Added budget formula (calculate upfront, don't iterate), `MamPath` dataclass with `dropped_components` for logging, multi-file support (`part_count` parameter), minimum viable base floor (3 chars + warning), and specific test cases (Haunted Bookstore at 299 chars → must truncate to ≤225).
