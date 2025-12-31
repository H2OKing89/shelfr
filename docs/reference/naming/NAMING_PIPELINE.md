# Naming Processing Pipeline

> The full cleaning pipeline and order of operations for Shelfr naming.

## Related Documentation

| Document | Description |
|----------|-------------|
| [Naming Overview](./NAMING.md) | Quick reference and architecture |
| [Audnex Normalization](./NAMING_AUDNEX_NORMALIZATION.md) | Metadata normalization |
| [Rules Reference](./NAMING_RULES.md) | Matching rules and phrase removal |

---

## Pipeline Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Full Naming Pipeline                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Stage 1: Input Collection                                                  │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ Libation JSON → AudiobookRelease → fetch Audnex data                 │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                              │                                              │
│                              ▼                                              │
│  Stage 2: Audnex Normalization                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ Fix title/subtitle swaps → Extract series → NormalizedBook           │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                              │                                              │
│                              ▼                                              │
│  Stage 3: Text Cleaning                                                    │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ Phrase removal → Author map → Character transliteration              │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                              │                                              │
│                              ▼                                              │
│  Stage 4: Formatting                                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ Series formatting → Year formatting → ASIN tag                       │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                              │                                              │
│                              ▼                                              │
│  Stage 5: Path Building                                                    │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ Build folder name → Build file name → Truncation → MamPath           │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Stage 1: Input Collection

### Source Data

1. **Libation JSON** - Raw audiobook metadata from Audible
2. **Audnex API** - Enhanced metadata with series info

```python
# Discovery phase creates AudiobookRelease
release = AudiobookRelease(
    asin="B08G9PRS1K",
    title="Project Hail Mary (Unabridged)",
    authors=["Andy Weir"],
    narrators=["Ray Porter"],
    source_path=Path("/library/Andy Weir/Project Hail Mary"),
    # ... etc
)

# Metadata phase fetches Audnex data
audnex_data = fetch_audnex_metadata(release.asin)
```

---

## Stage 2: Audnex Normalization

See [Audnex Normalization](NAMING_AUDNEX_NORMALIZATION.md) for details.

### Key Operations

1. Detect title/subtitle swaps
2. Extract series name and position
3. Normalize series position (zero-pad)
4. Create `NormalizedBook` model

```python
normalized = NormalizedBook.from_audnex(audnex_data)
# NormalizedBook(
#     title="Project Hail Mary",
#     subtitle=None,
#     series_name=None,
#     series_position=None
# )
```

---

## Stage 3: Text Cleaning

### 3.1 Phrase Removal

Removes marketing text, edition info, and other noise:

```python
# Before
title = "Project Hail Mary (Unabridged)"

# After phrase removal
title = "Project Hail Mary"
```

**Phrase Categories (from `naming.json`):**

| Category | Examples |
|----------|----------|
| `edition_markers` | "(Unabridged)", "[Dramatized Adaptation]" |
| `marketing_phrases` | "A Novel", "An Audiobook Original" |
| `format_indicators` | "(Audio Download)", "[Audible Edition]" |
| `narrator_markers` | "Narrated by...", "Read by..." |

### 3.2 Author Name Mapping

Handles pseudonyms and name variations:

```python
# From naming.json author_map
"Stephen King writing as Richard Bachman" → "Stephen King"
"J.K. Rowling writing as Robert Galbraith" → "J.K. Rowling"
```

### 3.3 Character Transliteration

Converts non-ASCII characters for cross-platform compatibility:

```python
# Japanese transliteration
"東京" → "Tokyo"

# Accented characters
"José García" → "Jose Garcia"

# Special characters
"Rock & Roll" → "Rock and Roll"
```

### Cleaning Order

**Critical: Order matters for correct results!**

```python
def clean_title(raw_title: str) -> str:
    """Clean title in correct order."""
    result = raw_title

    # 1. Normalize unicode (NFC form)
    result = unicodedata.normalize("NFC", result)

    # 2. Remove phrase patterns (most specific first)
    result = remove_edition_markers(result)
    result = remove_marketing_phrases(result)
    result = remove_narrator_markers(result)

    # 3. Transliterate non-ASCII
    result = transliterate(result)

    # 4. Normalize whitespace
    result = " ".join(result.split())

    # 5. Strip and return
    return result.strip()
```

---

## Stage 4: Formatting

### 4.1 Series Formatting

```python
# With series
"Author - Series vol_01 - Title"

# Without series
"Author - Title"
```

**Volume Format:** `vol_XX` where XX is zero-padded

```python
"1"   → "vol_01"
"1.5" → "vol_01.5"
"12"  → "vol_12"
```

### 4.2 Year Formatting

```python
# Year in parentheses
"(2021)"

# Unknown year
"(Unknown)"  # or omitted based on config
```

### 4.3 ASIN Tag

```python
# Standard format
"{ASIN.B08G9PRS1K}"

# For folder names only (not files)
```

---

## Stage 5: Path Building

### 5.1 Folder Name

**Template:**
```
{author} - {series vol_XX - }{title} ({year}) {narrator} {ASIN.xxxxxxxxxx}
```

**Examples:**
```
Andy Weir - Project Hail Mary (2021) (Ray Porter) {ASIN.B08G9PRS1K}
Brandon Sanderson - Stormlight Archive vol_01 - The Way of Kings (2010) (Michael Kramer) {ASIN.B003ZWFO7E}
```

### 5.2 File Name

**Template:**
```
{author} - {series vol_XX - }{title}.m4b
```

**Examples:**
```
Andy Weir - Project Hail Mary.m4b
Brandon Sanderson - Stormlight Archive vol_01 - The Way of Kings.m4b
```

### 5.3 Truncation (225-char limit)

MAM has a 225-character path limit. When exceeded:

1. Calculate available space
2. Truncate title (preserve author, series, ASIN)
3. Add hash suffix for uniqueness

```python
# Original (too long)
"Very Long Author Name - Very Long Series Name vol_01 - Extremely Long Title That Goes On Forever (2021) (Narrator) {ASIN.B0123456789}"

# Truncated
"Very Long Author Name - Very Long Series Name vol_01 - Extremely Long Ti...[a1b2c3] (2021) (Narrator) {ASIN.B0123456789}"
```

**Hash Suffix:** 6-char hash of original title for uniqueness

### 5.4 MamPath Model

```python
class MamPath(BaseModel):
    """Tracks path with truncation metadata."""

    folder_name: str
    file_name: str
    was_truncated: bool
    original_length: int
    truncation_hash: str | None
```

---

## What Gets Cleaned

### Title Cleaning

| Before | After |
|--------|-------|
| `"Project Hail Mary (Unabridged)"` | `"Project Hail Mary"` |
| `"The Martian: A Novel"` | `"The Martian"` |
| `"Dune [Dramatized Adaptation]"` | `"Dune"` |

### Author Cleaning

| Before | After |
|--------|-------|
| `"Stephen King writing as Richard Bachman"` | `"Stephen King"` |
| `"J.K. Rowling"` | `"J.K. Rowling"` (unchanged) |
| `"José García"` | `"Jose Garcia"` |

### Series Cleaning

| Before | After |
|--------|-------|
| `"The Stormlight Archive, Book 1"` | `"Stormlight Archive"` |
| `"Mistborn: The Original Trilogy"` | `"Mistborn"` |
| `"A Song of Ice & Fire"` | `"A Song of Ice and Fire"` |

---

## Function Reference

### Core Functions (`Shelfr.utils.naming`)

| Function | Purpose |
|----------|---------|
| `build_mam_folder_name()` | Build complete folder name |
| `build_mam_file_name()` | Build complete file name |
| `clean_title()` | Apply all title cleaning |
| `clean_author()` | Apply author mapping and cleaning |
| `format_series()` | Format series with volume |
| `truncate_path()` | Handle 225-char limit |

### Entry Points

```python
from Shelfr.utils.naming import build_mam_folder_name, build_mam_file_name

folder = build_mam_folder_name(
    author="Andy Weir",
    title="Project Hail Mary",
    year=2021,
    narrator="Ray Porter",
    asin="B08G9PRS1K",
    series=None,
    series_position=None
)

file = build_mam_file_name(
    author="Andy Weir",
    title="Project Hail Mary",
    series=None,
    series_position=None
)
```

---

## See Also

- [Folder & File Schemas](NAMING_FOLDER_FILE_SCHEMAS.md) - Output format details
- [Rules Reference](NAMING_RULES.md) - Phrase removal rules
- [src/Shelfr/utils/naming/](/src/Shelfr/utils/naming/) - Implementation
