# ABS Rename Edge Cases

Documented edge cases from abs-rename analysis. These require systematic solutions.

---

## ✅ Audio Format Detection (IMPLEMENTED)

**Status**: Complete - `detect_audio_format()` in `src/mamfast/metadata.py`

Automatically detects audio format from m4b files using mediainfo to disambiguate duplicate ASINs.

### Detected Formats:

| Format | Detection Method | Edition Tag | Quality Tier |
|--------|-----------------|-------------|--------------|
| **Dolby Atmos** | E-AC-3 codec + JOC features | `(Dolby Atmos)` | `atmos` |
| **xHE-AAC** | USAC codec / mp4a-40-42 | `(xHE-AAC)` | `high` |
| **High Bitrate AAC** | ≥256kbps AAC | `(256kbps)` | `high` |
| **Standard AAC** | 96-255kbps | *(none)* | `standard` |
| **Low Bitrate** | <96kbps | *(none)* | `low` |

### Usage:

```python
from mamfast.metadata import detect_audio_format, run_mediainfo

# From file
mediainfo_data = run_mediainfo(Path("/path/to/file.m4b"))
audio_format = detect_audio_format(mediainfo_data)

# Check format
if audio_format.is_dolby_atmos:
    print("Dolby Atmos detected!")

# Get edition tag for folder naming
tag = audio_format.get_edition_tag()  # "(Dolby Atmos)" or "(xHE-AAC)" or None

# Get human-readable description
desc = audio_format.get_format_description()  # "Dolby Atmos 5.1 768kbps"
```

### Real-World Examples:

**Harry Potter (same ASIN B0F14RPXHR, different editions):**
| File | Format | Bitrate | Channels | Edition Tag |
|------|--------|---------|----------|-------------|
| Full-Cast (Dolby Atmos) | E-AC-3 | 768kbps | 6 (5.1) | `(Dolby Atmos)` |
| Full-Cast (Standard) | AAC | 125kbps | 2 | *(none)* |

**He Who Fights With Monsters (same ASIN, different quality):**
| File | Format | Bitrate | Edition Tag |
|------|--------|---------|-------------|
| vol_01 [H2OKing] | xHE-AAC | 118kbps | `(xHE-AAC)` |
| vol_01 (PP) | AAC | 62kbps | *(none)* |
| vol_11 [H2OKing] | xHE-AAC | 124kbps | `(xHE-AAC)` |
| vol_11 (PP) | AAC | 62kbps | *(none)* |

---

## Real-World Example: Harry Potter Collection

Your folder structure is the **ideal naming convention** that we want to preserve:

```
Harry Potter/
├── Harry Potter vol_01 and the Philosopher's Stone (2024) (J.K. Rowling) (Stephen Fry) {ASIN.B0D1CSXB3Z}
├── Harry Potter vol_01 and the Philosopher's Stone (2025) (J.K. Rowling) (Full-Cast) {ASIN.B0F14RFHS6}
├── Harry Potter vol_01 and the Sorcerer's Stone (2015) (J.K. Rowling) (Jim Dale) {ASIN.B017V4IM1G}
├── Harry Potter vol_01 and the Sorcerer's Stone (2025) (J.K. Rowling) (Full-Cast) {ASIN.B0F14RPXHR} [H2OKing]
├── Harry Potter vol_01 and the Sorcerer's Stone (2025) (J.K. Rowling) (Full-Cast) (Dolby Atmos) {ASIN.B0F14RPXHR} [H2OKing]
...
```

### What abs-rename would do (PROBLEMS):

| Your Folder | abs-rename Output | Issue |
|------------|-------------------|-------|
| `Harry Potter vol_01 and the Sorcerer's Stone (2015) (J.K. Rowling) (Jim Dale)` | `Wizarding World Collection vol_01 (2015) (J.K. Rowling)` | **Wrong series name**, loses book title, loses narrator |
| `Harry Potter vol_01 and the Philosopher's Stone (2024) (J.K. Rowling) (Stephen Fry)` | `Harry Potter (Narrated by Stephen Fry) vol_01 (2024) (J.K. Rowling)` | Loses book title "Philosopher's Stone" |
| `Harry Potter vol_01 and the Philosopher's Stone (2025) (J.K. Rowling) (Full-Cast)` | `Harry Potter (Full-Cast Editions) vol_01 (2025) (J.K. Rowling) (Full-Cast)` | Loses book title, "(Full-Cast)" duplicated |
| Dolby Atmos + Regular edition (same ASIN) | **DETECTED via mediainfo** | ✅ Can auto-add `(Dolby Atmos)` tag |

### Key Issues Identified:

1. **ABS metadata uses different series names** - Jim Dale editions are in "Wizarding World Collection" on Audible
2. **Book title ("Sorcerer's Stone", "Philosopher's Stone") is lost** - only series+vol remains
3. **Narrator info restructured** - moves from end to series name parenthetical
4. **Edition variants lose differentiation** - Dolby Atmos vs standard ~~can't be distinguished~~ **NOW DETECTABLE** via `detect_audio_format()`

### Your Format vs ABS Metadata Format:

```
YOUR FORMAT (PREFERRED):
  Series vol_XX and Book Title (Year) (Author) (Narrator) [Edition] {ASIN}
  Harry Potter vol_01 and the Sorcerer's Stone (2015) (J.K. Rowling) (Jim Dale) {ASIN.B017V4IM1G}

ABS METADATA FORMAT:
  Series (Edition) vol_XX (Year) (Author) {ASIN}
  Wizarding World Collection vol_01 (2015) (J.K. Rowling) {ASIN.B017V4IM1G}
```

**Your format is superior because it:**
- Preserves the actual book title
- Keeps narrator in consistent position
- Maintains "Harry Potter" as the recognizable series
- Allows edition tags like (Dolby Atmos) without breaking the structure

---


---

## Categories

### 1. ✅ Title-Only → Series (Expected Behavior)
**Status**: Working correctly - these are NOT bugs

Books where the original folder only has the title, but ABS metadata provides series info:
- `The Creeping Darkness` → `Black Summoner vol_07`
- `61 Hours` → `Jack Reacher vol_14`
- `Killing Floor` → `Jack Reacher - Killing Floor`

Low similarity is expected because we're adding significant new information.

---

### 2. 🔧 Series Name Cleaning
**Status**: Partially fixed in naming.json

#### Fixed:
- `(Publication Order)`, `(Reading Order)` → stripped from series names
- `Terminal List Book` → `Terminal List` (trailing " Book" stripped)

#### Pattern Added:
```json
"\\s*\\((?:Publication|Reading|Chronological|Release)\\s*Order\\)$",
"\\s+Book$"
```

---

### 3. ⚠️ Narrator Edition Detection
**Status**: Needs implementation

Different narrator editions creating separate series:
```
Harry Potter vol_01 (Stephen Fry)  → Harry Potter (Narrated by Stephen Fry) vol_01
Harry Potter vol_01 (Jim Dale)     → Wizarding World Collection vol_01
Harry Potter vol_01 (Full-Cast)    → Harry Potter (Full-Cast Editions) vol_01
```

**Proposed Solution**:
- Detect narrator in parentheses at end of folder name
- Match against known narrator patterns in ABS metadata
- Preserve original series name, add narrator as edition tag

---

### 4. ⚠️ Arc/Volume Title Preservation
**Status**: Needs `--preserve-arc-title` option

Books losing arc titles:
```
Spice and Wolf vol_15 The Coin of the Sun I → Spice and Wolf vol_15
```

**Proposed Solution**:
- Add CLI flag `--preserve-arc-title`
- When set, preserve text after `vol_XX` in original folder name
- Only apply when original has arc title AND new name would lose it

---

### 5. ⚠️ Omnibus/Box Set Detection
**Status**: Needs special handling

Multi-volume releases:
```
The Path of Ascension vol_01-3.5 → The Path of Ascension - Books 1-3.5
System Reborn Vol 1 & 2          → (no series, keeps as-is)
System Reborn Vol 5, 6, 7        → System Reborn Vol 4 (WRONG!)
```

**Issues**:
- Volume ranges (`1-3.5`, `1 & 2`, `5, 6, 7`) need detection
- ABS metadata may not properly represent omnibus volumes
- Current vol_XX format can't represent ranges

**Proposed Solutions**:
1. Detect omnibus patterns, keep original volume format
2. Use `vol_01-03` format for ranges
3. Add `(Omnibus)` or `(Box Set)` edition tag

---

### 6. ⚠️ Localized/Alternate Titles
**Status**: May need manual mapping

Same book with different titles in different regions:
```
Peddler in Another World → I Can Go Back to My World Whenever I Want
```

**Proposed Solution**:
- Build title alias database
- Allow user to choose preferred title variant
- Respect original folder title if it's a known alias

---

### 7. ⚠️ "An" Prefix Inconsistency
**Status**: Minor, low priority

```
An Outcast in Another World → Outcast In Another World
```

**Cause**: ABS metadata doesn't include "An" prefix

**Proposed Solution**:
- Add "An" preservation rule similar to "The" inheritance
- Check if original starts with "An " but series doesn't

---

### 8. ⚠️ Duplicate Narrator Tags
**Status**: Needs deduplication

When author = narrator:
```
[Daoist Enigma] [ASIN.xxx] → {ASIN.xxx} [Daoist Enigma]
```

The narrator tag `[Daoist Enigma]` duplicates the author when they're the same person.

**Proposed Solution**:
- Compare narrator tag to author name
- Skip narrator tag if it matches author (exact or fuzzy)

---

### 9. 🔧 Genre Subtitle Patterns
**Status**: Fixed in naming.json

Added patterns:
```json
"^[Aa] Xianxia(?: Cultivation)?(?: Novel)?$",
"^[Aa] Cultivation(?: Novel)?$",
"^[Aa]n? Isekai(?: LitRPG| Adventure| Novel)?$",
"^[Aa] GameLit(?: Adventure| Novel)?$",
"^From Hero-King to Extraordinary Squire[\\s-]*$"
```

Also added to genre_tags phrases:
```json
"A Xianxia Cultivation Novel",
"A Xianxia Novel",
"- A Slice of Life Harem LitRPG",
"- A Slice-of-Life Urban Fantasy"
```

---

## Priority Matrix

| Issue | Impact | Frequency | Effort | Priority | Status |
|-------|--------|-----------|--------|----------|--------|
| Audio format detection | High | Medium | Medium | P0 | ✅ Done |
| Arc title loss | High | Medium | Medium | P1 | ⏳ Pending |
| Omnibus detection | High | Low | High | P2 | ⏳ Pending |
| Narrator editions | Medium | Low | Medium | P2 | ⏳ Pending |
| Duplicate narrator | Low | Low | Low | P3 | ⏳ Pending |
| "An" prefix | Low | Low | Low | P4 | ⏳ Pending |
| Localized titles | Medium | Low | High | P4 | ⏳ Pending |

---

## Implementation Plan

### Phase 1: Quick Wins (Done)
- [x] Add order indicator patterns to series_suffixes
- [x] Add " Book" suffix pattern to series_suffixes
- [x] Add Xianxia/Cultivation subtitle patterns
- [x] Add genre tag phrase variants

### Phase 2: Audio Format Detection (Done)
- [x] Implement `AudioFormat` dataclass in `metadata.py`
- [x] Detect Dolby Atmos (E-AC-3 + JOC)
- [x] Detect xHE-AAC (USAC codec)
- [x] Add `get_edition_tag()` for folder naming
- [x] Add `get_format_description()` for human-readable output
- [x] Add `get_quality_tier()` for sorting/comparison

### Phase 3: Arc Title Preservation
- [ ] Add `--preserve-arc-title` CLI flag
- [ ] Detect arc title in original folder name (text after vol_XX)
- [ ] Preserve arc title in target name when flag set

### Phase 4: Omnibus Handling
- [ ] Detect volume range patterns (`vol_01-03`, `Books 1-3`)
- [ ] Parse and preserve ranges instead of single volume
- [ ] Add `(Omnibus)` edition tag option

### Phase 5: Narrator Edition Detection
- [ ] Detect narrator in parentheses from folder name
- [ ] Match known narrator edition patterns
- [ ] Preserve original series name with narrator edition

---

## Test Cases to Add

```python
# Arc title preservation
("Spice and Wolf vol_15 The Coin of the Sun I", preserve=True)
    → "Spice and Wolf vol_15 - The Coin of the Sun I"

# Omnibus detection
("The Path of Ascension vol_01-3.5", ...)
    → "The Path of Ascension vol_01-03.5" or keep range

# Series suffix stripping
("Terminal List Book vol_01", ...)
    → "Terminal List vol_01"

# Order indicator stripping
("Chronicles of Narnia (Publication Order) vol_01", ...)
    → "Chronicles of Narnia vol_01"
```
