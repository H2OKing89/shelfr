# Naming & Cleaning Plan

## Overview

This document tracks the naming/cleaning rules for MAMFast. The goal is consistent, clean naming across:
- Folder names (staging)
- File names (staging)
- MAM JSON output (title, subtitle, series, description)

## Architecture Decision

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
| **Keep Vol/Book** | Whether volume/book indicators stay as human-readable text (JSON) or are normalized to `vol_XX` format (folders/files). |

---

## Cleaning Pipeline Order

The cleaning steps are applied in this specific order to avoid issues (e.g., dangling commas, double spaces):

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
| Ripper tag | `[{Tag}]` in folder name | Not used (personal tag) |
| Purpose | Long-term organization | Temporary upload staging |

**MAM staging example:**
```
/staging/Mushoku Tensei - Jobless Reincarnation vol_27 Recollections (2024) (Rifujin na Magonote) {ASIN.B0DP3CQC6N}/
├── Mushoku Tensei - Jobless Reincarnation vol_27 Recollections (2024) (Rifujin na Magonote) {ASIN.B0DP3CQC6N}.m4b
├── cover.jpg
└── metadata.json
```

> Note: The ripper tag `[{Tag}]` is for personal library organization only and is NOT included in MAM uploads.

---

### Character Limits

- MAM filename limit: **225 characters max**
- Truncation priority (preserve most important first):
  1. `{Series}` + `vol_{NN}` (identity)
  2. `{ASIN.xxxxx}` (lookup key)
  3. `[{Tag}]` (ripper credit)
  4. `({Year})` (sorting)
  5. `({Author})` (can truncate)
  6. `{Arc}` (can truncate or omit)

**Truncation strategy:** Components are dropped right-to-left by priority. `{Arc}` is dropped first, then `({Author})`, then `({Year})`, then `[{Tag}]`. **`{Series}`, `vol_{NN}`, and `{ASIN}` are never truncated or broken mid-token.** If the name is still too long after dropping all optional components, truncate `{Series}` with `...` but never break the ASIN.

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

---

## Samples Needed

To refine these rules, we need real samples. Sources to check:

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

### Phase 2: Update naming.py to Use Config
- [ ] Refactor `filter_title()` to use `settings.naming`
- [ ] Add `filter_series()` function for series-specific cleaning
- [ ] Implement `preserve_exact` bypass logic
- [ ] Add publisher_tags support
- [ ] Add verbose logging for transformations (with rule IDs)

### Phase 3: Implement MAM JSON Cleaning
- [ ] Add `filter_title()` to title field in metadata.py
- [ ] Add `filter_title()` to subtitle field
- [ ] Add `filter_series()` for series names
- [ ] Handle Vol/Book differently for JSON vs folders

### Phase 4: Testing & Validation
- [ ] Create `tests/golden/` with input/expected pairs
- [ ] Add validation script to flag suspicious results
- [ ] Add preserve-exact drift check
- [ ] Test against full library export (1,295 books from ABS)
- [ ] Document any new edge cases found

### Phase 5: Subtitle Handling
- [ ] Implement two-tier subtitle strategy (remove_patterns + keep_patterns)
- [ ] Implement subtitle_redundancy_rules with {{series}}/{{title}} templates
- [ ] Test remove_if_matches_series logic
- [ ] Support both `drop_subtitle` and `strip_match` actions

### Phase 6: Folder/File Generation (NEW)
- [ ] Implement folder name builder using schema
- [ ] Implement file name builder
- [ ] Add ripper_tag config option
- [ ] Implement truncation logic (225 char limit)
- [ ] Handle standalone vs series books differently

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

---

## Changelog

- **2025-12-02**: Initial planning document created
- **2025-12-02**: Added pipeline order, matching rules, glossary, preserve_exact, publisher_tags, testing strategy (feedback from ChatGPT/Claude review)
- **2025-12-02**: Added subtitle_redundancy_rules with template-based patterns ({{series}}/{{title}}) to remove "Series, Book X" redundancy - affects 55+ books
- **2025-12-02**: Added folder/file naming schemas with real library examples (SAO, Mushoku Tensei, Skyward)
- **2025-12-02**: Added `[{Tag}]` ripper tag component (e.g., `[H2OKing]`)
- **2025-12-02**: Clarified standalone book layout (no separate book folder), pipeline field scope, truncation strategy, series_number source of truth, description exclusions, logging rule IDs, preserve-exact drift validation (ChatGPT review round 2)
