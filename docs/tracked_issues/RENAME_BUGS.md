# ABS Rename — Bug Tracker

Identified from batch scan of 219 authors (716 proposed renames, 2025-07-14).

---

## BUG-1: Edition flags lost — Dramatized Adaptation / Graphic Audio

**Status:** ✅ Fixed (2025-07-15)
**Severity:** High — 14 entries affected (8 Pierce Brown, 6 Rebecca Yarros)
**Authors:** Pierce Brown, Rebecca Yarros

### Symptoms

Source folders contain `[Dramatized Adaptation]` or `(GA)` markers; target names drop
them entirely.

```
FROM: ...vol_01_01 - Red Rising [2023] [Pierce Brown] [Dramatized Adaptation] [ASIN.B0BVGTFDWN]
  TO: Red Rising vol_01.1 (2023) (Pierce Brown) {ASIN.B0BVGTFDWN}
                                                  ← no DA flag
```

### Root Causes

| # | Cause | Detail |
|---|-------|--------|
| A | `detect_edition_flags()` only matches `(parens)` | The regex `\((...)\)` ignores `[brackets]`. Old folder conventions use `[Dramatized Adaptation]`. |
| B | Parser treats last `[...]` as `ripper_tag` | `[Dramatized Adaptation]` at end of name is consumed as the ripper tag, never reaching the flag detector. |
| C | Missing aliases | `"GA"` → `"Graphic Audio"` and `"Dramatized Adaptation"` → `"Dramatized"` not in alias table. |

### Fix Applied

1. Extended `_build_edition_pattern()` to match both `(Flag)` and `[Flag]` via `[(\[]` / `[)\]]`.
2. Added aliases to both `naming.json` and code defaults: `"ga"` → `"Graphic Audio"`, `"da"` → `"Dramatized"`, `"dramatized adaptation"` → `"Dramatized"`.
3. Added `"Dramatized Adaptation"`, `"GA"`, `"DA"` to the flags list.
4. In `parse_candidate()`: clears `ripper_tag` when it matches a known edition flag/alias.

### Verified

- Pierce Brown: 8 DA entries all show `(Dramatized)` ✓
- Rebecca Yarros: 6 DA entries all show `(Dramatized)` ✓
- Pierce Brown vol_05: 2 GA entries show `(Graphic Audio)` ✓

---

## BUG-2: GA split volume notation — decimal instead of part

**Status:** ✅ Fixed (2025-07-15)
**Severity:** High — 16 entries affected (10 Pierce Brown, 6 Rebecca Yarros)
**Authors:** Pierce Brown, Rebecca Yarros

### Symptoms

GA splits should use `vol_NNpN` notation (e.g. `vol_01p1`), but output uses
novella-style decimal (`vol_01.1`) or drops the part entirely (`vol_01`).

```
FROM: vol_01_01 - Red Rising ...        →  vol_01.1   (SHOULD: vol_01p1)
FROM: vol_01-1 - Fourth Wing ...        →  vol_01     (SHOULD: vol_01p1)
FROM: vol_01-2 - Fourth Wing ...        →  vol_01.5   (SHOULD: vol_01p2)
```

### Root Cause

ABS metadata positions for GA splits are decimal (`1.1`, `1.5`) or plain integer
(`1`), which `normalize_position()` formats as novella volumes. The source folder
already has correct part notation (`vol_XX_YY`, `vol_XX-Y`) but is overridden by
ABS metadata.

### Fix Applied

1. Added GA/DA volume override in `compute_target_name()`: when edition flags
   indicate a GA/DA release, extracts `vol_XX_YY` or `vol_XX-Y` from the source
   folder name and rewrites as `NpM` format for `format_volume_number()`.
2. Fixed format string: was producing `"N_M"` (underscore) which
   `format_volume_number()` doesn't handle; changed to `"NpM"` which it does.
3. Extended `_resolve_arc_name()` condition to also enter the folder-first arc
   block when `parsed.title` starts with the resolved series name + vol token.
4. Added targeted author-in-parens stripping from arc candidates for already-
   formatted folders.

### Verified

- Pierce Brown: `vol_01_01` → `vol_01p1`, `vol_01_02` → `vol_01p2`, etc. ✓
- Pierce Brown vol_05: `vol_05_01` → `vol_05p1`, `vol_05_02` → `vol_05p2` ✓
- Pierce Brown vol_05: "Dark Age" arc now properly extracted ✓
- Rebecca Yarros: `vol_01-1` → `vol_01p1`, `vol_01-2` → `vol_01p2` ✓
- Standard entries (vol_01, vol_02, vol_03) not affected ✓

---

## BUG-3: Bracket tokens leak into arc/title

**Status:** ✅ Fixed (2025-07-14)
**Severity:** Medium — 23 target names affected
**Authors:** Pierce Brown (6), Rebecca Yarros (6), G.S. DMoore (2), Atekichi (1), Patora Fuyuhara (1), others

### Symptoms

Source `[Author]` or `[Flag]` tokens not stripped, leak through as part of
the arc text:

```
arc: "Fourth Wing [Rebecca Yarros]"
arc: "_01 - Golden Son [Pierce Brown]"
target: "...(GA) [Dramatized Adaptation]..."
```

### Root Cause

`parse_mam_folder_name()` only removes `[ASIN.*]`, `[YYYY]`, and the last
`[...]` (ripper tag). Any remaining `[brackets]` persist in the title/rest
string and propagate into arc resolution.

### Planned Fix

After extracting ripper_tag, bracket_year, and ASIN, strip all remaining
`[...]` tokens from the name.

---

## BUG-4: Pierce Brown garbage text in arc

**Status:** ✅ Fixed (2025-07-14) — resolved by BUG-3 + BUG-2 arc extraction fixes
**Severity:** Medium — 6 entries
**Author:** Pierce Brown

### Symptoms

For vol_02+, the arc contains raw leftovers like `_01 - Golden Son [Pierce Brown]`:

```
FROM: vol_02_01 - Golden Son [2023] [Pierce Brown] [Dramatized Adaptation]
  TO: Red Rising vol_02.1 _01 - Golden Son [Pierce Brown] (2023) (Pierce Brown) {ASIN.xxx}
```

### Root Cause

The parsed title is `vol_02_01 - Golden Son [Pierce Brown]`. After the volume
prefix `vol_02` is stripped (or series prefix removed), the remainder
`_01 - Golden Son [Pierce Brown]` becomes the arc. This is because:

- `[Pierce Brown]` not stripped from title (BUG-3)
- The volume part `_01` is in the parsed title, not extracted by the parser
- Series match regex can't handle `vol_XX_YY` format

---

## BUG-5: Malformed ASIN propagation

**Status:** ✅ Fixed (2025-07-14)
**Severity:** Low — 2 entries (Rebecca Yarros, Jaki)
**Authors:** Rebecca Yarros (`{ASIN.B0CYJN13ZH]`), Jaki (`{ASIN.B0FLKPL6SF)`)

### Symptoms

Source folders have malformed ASIN tags with mismatched brackets. The target
both preserves the malformed token AND adds a correct duplicate:

```
FROM: {ASIN.B0CYJN13ZH] [Dramatized Adaptation]
  TO: ...{ASIN.B0CYJN13ZH] (2024) (Rebecca Yarros) {ASIN.B0CYJN13ZH}
```

### Root Cause

`extract_asin()` correctly identifies the ASIN, but the malformed brackets
`{ASIN.xxx]` don't match the ASIN stripping regex `\{ASIN\.\w+\}` (expects
matching `}`). So the malformed string persists in the title and leaks through.

### Planned Fix

Extend ASIN stripping regex to also match `{ASIN.xxx]` and `[ASIN.xxx)` etc.

---

## BUG-6: Volume number override (Jack Carr, Sunsunsun)

**Status:** ✅ Fixed (2025-07-15)
**Severity:** Medium — 2 entries
**Authors:** Jack Carr (vol_04→03), Sunsunsun (vol_02→01)

### Symptoms

ABS metadata series position disagrees with the source folder's volume number.
The metadata override silently changes the volume.

```
FROM: Terminal List - vol_04 - Savage Son
  TO: Terminal List vol_03 Savage Son (2020) (Jack Carr) {ASIN.1508299625}
                    ^^^^^^ ABS says #3, folder says vol_04

FROM: Alya Sometimes Hides Her Feelings in Russian vol_02 (2024) (Sunsunsun) {ASIN.B0D6CJ6PTD}
  TO: ...vol_01...
       ^^^^^^ ABS says Vol. 1, folder says vol_02
```

### Root Cause

Volume resolution always tried ABS metadata first, then fell back to
`parsed.series_position` only when ABS had nothing.  With `preserve_existing`
policy, folder numbering should be authoritative.

Additionally, `parsed.series_position` was `None` for "Author - vol_XX - Title"
format folders (e.g. `Terminal List - vol_04 - Savage Son`) because the parser
treats "Terminal List" as an author, not a series — so there was no folder
volume to fall back to even if priority was correct.

### Fix Applied

1. When `preserve_existing` or `folder_first` policy is active, check
   `parsed.series_position` first and prefer it over ABS metadata.
2. When `parsed.series_position` is `None`, extract `vol_XX` directly from the
   folder name using regex fallback.  This handles "Author - vol_XX - Title"
   format folders where the parser doesn't set `series_position`.
3. ABS metadata position is only used when neither the parser nor the
   folder name contain a volume number.

### Verified

- Jack Carr `vol_04 - Savage Son` → `Terminal List vol_04 Savage Son` ✓ (was vol_03)
- Sunsunsun `vol_02` (B0D6CJ6PTD) → stays `vol_02` ✓ (was vol_01)
- All other entries unaffected (vol_01, vol_02, vol_05-07 unchanged)
- Pierce Brown GA entries: `vol_NNpN` notation still correct ✓
- Rebecca Yarros: all entries unchanged ✓
- 3084 tests passing ✓

---

## BUG-7: "The Empyrean" → "Empyrean" series name inconsistency

**Status:** ✅ Fixed
**Severity:** Low — 1 entry
**Author:** Rebecca Yarros

### Symptoms

`vol_02 Iron Flame` resolves series to "Empyrean" (without "The") while all
other entries keep "The Empyrean".

```
FROM: The Empyrean - vol_02 - Iron Flame [2023] [Rebecca Yarros] [ASIN.B0C9V5SLQQ]
  TO: Empyrean vol_02 Iron Flame (2023) (Rebecca Yarros) {ASIN.B0C9V5SLQQ}
```

### Root Cause

ABS metadata for this ASIN has series name "Empyrean" (without article).
Article inheritance / consolidation logic in `_resolve_series()` was choosing
the ABS canonical name when the series names differed only by a leading article.

### Fix

Changed `_resolve_series()` to keep the existing folder root name under
`preserve_existing` policy, even when the ABS name differs only by a leading
article.  Before: ABS canonical name won.  After: existing folder name wins.

### Verification

- All 9 Rebecca Yarros entries now consistently show `The Empyrean`
- 3084 tests passing ✓

---

## BUG-8: Nisio Isin garbage output

**Status:** ✅ Fixed
**Severity:** Medium — 5 entries
**Author:** Nisio Isin

### Symptoms

Target names contain `pt_01`/`pt_02`/`pt_03` as arc names instead of part
notation, `(White)` stripped from "Nekomonogatari (White) Cat Tale", and
ABS metadata position overrides.

### Root Cause

Three sub-issues:

1. **pt_XX as arc**: `_resolve_arc_name()` didn't recognise `pt_XX` tokens as
   part notation.  After volume stripping, `pt_01` was left as the arc text.
2. **`(White)` stripping**: `parse_mam_folder_name()` in importer.py treated
   `(White)` as a narrator parenthetical and removed it from the title.  The
   parenthetical extraction loop was too aggressive — it didn't check whether
   there was significant text after the closing paren.
3. **pt_XX + arc combo**: For "vol_04 - pt_01 - Nekomonogatari (White) Cat
   Tale", the arc was `pt_01 - Nekomonogatari Cat Tale` instead of just
   `Nekomonogatari (White) Cat Tale`.

### Fix

1. Added pt_XX → part notation logic in `compute_target_name()`: after arc
   resolution, detects `pt_\d+` prefix in arc, merges it into vol_num as
   `vol_NNpM`, and strips pt_XX from the arc text.
2. Fixed `parse_mam_folder_name()` parenthetical extraction: only treats a
   parenthetical as narrator if there is no significant text (word characters)
   after the closing paren.  Mid-title parens like `(White)` are preserved.

### Verification

```
vol_01 - pt_01                                    → vol_01p1              ✓
vol_01 - pt_02                                    → vol_01p2              ✓
vol_01 - pt_03                                    → vol_01p3              ✓
vol_02 - kizumonogatari Wound Tale                → vol_02 (arc=kizumonogatari Wound Tale) ✓
vol_04 - pt_01 - Nekomonogatari (White) Cat Tale  → vol_04p1 (arc=Nekomonogatari (White) Cat Tale) ✓
```

- Pierce Brown GA/DA entries: vol_NNpM notation still correct ✓
- 3084 tests passing ✓

---

## BUG-9: Translator/misc tags leaking

**Status:** ✅ Fixed
**Severity:** Low — 2+ entries
**Authors:** Hayaken, Sunsunsun

### Symptoms

Raw translator strings like `Mike Langwiser - translator Hayaken` appear in
author field. Redundant subtitle duplicated as arc name.  Also `vol_04.5`
was parsed as `vol_04` (decimal part lost).

### Root Cause

1. **Translator in author**: ABS metadata had compound author strings like
   `"Mike Langwiser - translator Hayaken"`.  The author resolution always
   used ABS metadata first, passing through the role tag verbatim.
2. **Decimal volume lost**: `parse_mam_folder_name()` vol regex in the
   Libation-format branch only captured integer digits (`\d+` without
   `(?:\.\d+)?`).

### Fix

1. Added `_clean_author()` helper that strips `- translator/editor/narrator`
   suffixes from ABS author strings.
2. Under `preserve_existing` policy, prefer qualified parsed author over ABS
   metadata (folder author wins), with a guard that rejects parsed.author
   when it matches the resolved series name (parser misidentified series
   as author in `Series - vol_XX - Title` format folders).
3. Fixed Libation-format vol regex to capture decimals: `(\d+(?:\.\d+)?)`.

### Verification

- Sunsunsun: all 7 entries `up_to_date`, author=Sunsunsun, vol_04.5 preserved ✓
- Hayaken vol_01: author=Hayaken (was `Mike Langwiser - translator Hayaken`) ✓
- Rebecca Yarros: author=Rebecca Yarros (not The Empyrean) ✓
- 3084 tests passing ✓

---

## Summary

| Bug | Description | Severity | Entries | Status |
|-----|-------------|----------|---------|--------|
| 1 | Edition flags lost (DA/GA) | High | 14 | ✅ Fixed |
| 2 | GA split vol decimal not part | High | 16 | ✅ Fixed |
| 3 | Bracket tokens leak into arc | Medium | 23 | ✅ Fixed |
| 4 | Pierce Brown garbage arc text | Medium | 6 | ✅ Fixed |
| 5 | Malformed ASIN propagation | Low | 2 | ✅ Fixed |
| 6 | Vol number override (Jack Carr) | Medium | 2 | ✅ Fixed |
| 7 | "The Empyrean" inconsistency | Low | 1 | ✅ Fixed |
| 8 | Nisio Isin garbage output | Medium | 5 | ✅ Fixed |
| 9 | Translator tag leaking | Low | 2+ | ✅ Fixed |

**All 9 bugs fixed.** ✅
