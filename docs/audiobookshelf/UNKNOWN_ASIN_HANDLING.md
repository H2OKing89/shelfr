# Unknown ASIN Handling Plan

> **Document Version:** 3.0.0 | **Last Updated:** 2025-07-01 | **Status:** ✅ Phase 3 Complete

This document outlines the plan for handling audiobooks without ASINs during import.

> **Scope:** Phases 1-3 are complete. Phases 4-5 are planned for future PRs.

---

## Current Behavior (Phase 3)

| Scenario | Behavior |
|----------|----------|
| Folder has ASIN | Normal MAM-style import with renames |
| ASIN found in files | Enhanced resolution finds it (Phase 3) |
| ASIN found in metadata.json | Enhanced resolution finds it (Phase 3) |
| No ASIN + policy=import | Route by classification (see below) |
| No ASIN + policy=quarantine | Move to quarantine folder, no renames |
| No ASIN + policy=skip | Leave in staging, log warning only |

### Phase 3 ASIN Resolution Cascade

Before classifying as unknown, we try multiple sources:

1. **Folder name** - Primary source, already parsed
2. **Audio file names** - `Book {ASIN.B0xxx}.m4b`
3. **Sidecar JSON** - `*.metadata.json` or `metadata.json` with `asin` field

This catches cases where ASIN exists but wasn't in folder name.

### Classification & Routing (policy=import)

| Content Type | Multi-File? | Target Path | Audio Rename | Sidecar Created |
|--------------|-------------|-------------|--------------|----------------|
| **MISSING_ASIN** | No | `Unknown/<OriginalFolder>/` | Yes | Yes |
| **MISSING_ASIN** | Yes | `Unknown/<OriginalFolder>/` | **Never** | Yes |
| **HOMEBREW** | No | `<Author>/<Title (Author)>/` | Yes | Yes |
| **HOMEBREW** | Yes | `<Author>/<Title (Author)>/` | **Never** | Yes |

### Configuration

```yaml
audiobookshelf:
  import:
    unknown_asin_policy: import  # import | quarantine | skip
    quarantine_path: "/path/to/quarantine"  # Required if policy=quarantine
```

---

## Core Philosophy

Three questions drive all decisions:

1. **Safety** – Never lose data (multi-file nuke bug fixed ✅)
2. **Organization** – Unknowns shouldn't turn the library into a landfill
3. **Future Recovery** – Be able to come back later and resolve ASINs

**Decision: Always import unknowns by default** with clear policies:
- Preserve multi-file folder structure and filenames
- Keep them in clearly-namespaced "unknown" areas
- Drop metadata breadcrumbs for future batch resolution

---

## Key Assumptions & Constraints

These apply throughout all phases:

| Assumption | Description | Impact if Violated |
|------------|-------------|-------------------|
| **Single-level folders** | Each staging folder contains audio files directly (no `Disc 1/` subfolders) | Nested audio files not discovered |
| **Same filesystem** | Staging, library, and seed paths on same mount | Falls back to copy (slow), logs warning |
| **Idempotent re-runs** | Running import twice on same content is safe | N/A - this is a guarantee we provide |
| **No cross-folder files** | One audiobook = one folder | Multi-folder books not supported |

### What We Don't Support (Explicitly)

- **Nested disc structures** (`Disc 1/Track01.m4b`, `CD2/Chapter01.mp3`) – flatten first
- **Multi-folder books** (sequel split across folders) – treat as separate books
- **Symbolic links as audio** – hardlink or copy only

---

## Problem Statement

The importer had two issues with unknown-ASIN content:

### ~~Critical Bug: Multi-File Data Loss~~ ✅ FIXED

When importing a multi-file audiobook without ASIN, all files got renamed to the same base name:

```
Renamed: Title - 01.m4b → Title (Unknown).m4b
Renamed: Title - 02.m4b → Title (Unknown).m4b  # Overwrites previous!
Renamed: Title - 41.m4b → Title (Unknown).m4b  # Last one wins
```

**Result:** 40 files become 1. Data destroyed.

**Fix:** Phase 1 implemented - multi-file books without ASIN preserve original filenames.

### Design Issue: No Policy for Unknowns

Currently all unknown-ASIN content goes to `Unknown/` with aggressive renaming. This doesn't distinguish between:

1. **Audible content missing ASIN** - Could be resolved via metadata
2. **Homebrew/self-pub** - ASIN not applicable, just needs filing
3. **Malformed imports** - Need manual review

---

## Unknown ASIN Classification

### Two Orthogonal Dimensions

Unknown-ASIN folders vary in two independent ways:

| Dimension | Values | Meaning |
|-----------|--------|---------|
| **Content type** | `MISSING_ASIN`, `HOMEBREW` | *Why* is ASIN unknown? (Semantic) |
| **File structure** | `single_file`, `multi_file` | *How many* audio files? (Structural) |

These are **orthogonal** – a folder can be `HOMEBREW + multi_file` (homebrew with chapter splits).

```python
from enum import Enum
from dataclasses import dataclass
from pathlib import Path

class UnknownAsinContentType(str, Enum):
    MISSING_ASIN = "missing_asin"  # Likely Audible, ASIN just not found yet
    HOMEBREW = "homebrew"          # No ASIN expected (self-pub, personal rips)

@dataclass
class UnknownAsinContext:
    folder: Path
    parsed: ParsedFolderName
    content_type: UnknownAsinContentType
    file_count: int
    original_folder_name: str  # For collision-safe destination naming

    @property
    def is_multi_file(self) -> bool:
        return self.file_count > 1
```

### Routing by Content Type (Regardless of File Count)

| Content Type | Target Path | Why |
|--------------|-------------|-----|
| **MISSING_ASIN** | `Unknown/<OriginalFolderName>/` | Avoids title collision; keeps provenance |
| **HOMEBREW** | `<Author>/<Title (Author)>/` | Author-based organization even without ASIN |

**Important:** Multi-file status affects **rename behavior**, not routing:
- Multi-file + no ASIN → preserve original audio filenames
- Single-file + no ASIN → can rename safely

### Why Use Original Folder Name for Unknown/?

Using parsed title for destination risks collision:

```
# Collision risk:
Staging: "My Book (2020)/"  →  Unknown/My Book (Unknown)/
Staging: "My Book (2023)/"  →  Unknown/My Book (Unknown)/  ← overwrites!

# Safe (using original folder name):
Staging: "My Book (2020)/"  →  Unknown/My Book (2020)/
Staging: "My Book (2023)/"  →  Unknown/My Book (2023)/
```

### Homebrew Pattern Heuristic

```python
def matches_homebrew_pattern(folder_name: str, parsed: ParsedFolderName) -> bool:
    """Detect 'Author - Title' pattern suggesting homebrew/self-pub."""
    # Explicit author AND no ASIN AND no series/year suggests homebrew
    # These often come from personal rips: "Joe Smith - My Podcast"
    if parsed.author and not parsed.asin:
        # Simple heuristic: folder starts with "Author - " or "Author_-_"
        normalized = folder_name.replace("_", " ").strip()
        return normalized.lower().startswith(f"{parsed.author.lower()} - ")
    return False
```

---

## Implementation Phases

### Phase 1: Fix Critical Bug ✅ COMPLETE

**Goal:** Never destroy data by renaming multiple files to same name.

**Conservative approach:** When multi-file + no ASIN, rename **nothing** (audio OR sidecars).

```python
AUDIO_EXTENSIONS = {".m4b", ".mp3", ".flac", ".m4a"}
SIDECAR_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf", ".cue", ".json"}

def rename_files_in_folder(
    folder_path: Path,
    parsed: ParsedFolderName,
    *,
    dry_run: bool = False,
) -> list[tuple[Path, Path]]:
    audio_files = [f for f in folder_path.iterdir()
                   if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS]

    # SAFETY: Multi-file + no ASIN → DO NOT TOUCH ANY FILENAMES
    if len(audio_files) > 1 and not parsed.asin:
        logger.warning(
            "Multi-file book without ASIN (%d audio files), preserving names: %s",
            len(audio_files),
            folder_path.name,
        )
        return []  # Empty list = no renames at all (audio OR sidecars)

    # Single-file or ASIN-known: normal rename logic...
```

**Why `return []` (no renames at all)?**

1. **Simpler reasoning:** Either we rename everything or nothing
2. **Sidecar naming often depends on audio:** `Title - 01.cue` pairs with `Title - 01.m4b`
3. **Future flexibility:** Phase 2 can add sidecar-only rename if needed

> **Note:** We previously considered Option B (rename sidecars but not audio).
> Chose Option A (rename nothing) for simplicity. Revisit in Phase 2 if needed.

**Acceptance criteria:**
- [x] Multi-file folders without ASIN: **no file renames** (audio or sidecar)
- [x] Single-file folders without ASIN: can still rename
- [x] Folders with ASIN: normal behavior
- [x] Tests added: `TestMultiFileProtection` (4 tests)

---

### Phase 2: Unknown ASIN Policy ✅ COMPLETE

**Goal:** Configurable handling for unknown-ASIN content.

#### Configuration

```yaml
# config.yaml
audiobookshelf:
  import_settings:
    unknown_asin_policy: "import"  # import | quarantine | skip
    quarantine_path: "/mnt/user/data/audio/quarantine"
```

#### Policy Enum

```python
class UnknownAsinPolicy(str, Enum):
    IMPORT = "import"           # Default - import to Unknown/ or Author/
    QUARANTINE = "quarantine"   # Move to quarantine folder for manual review
    SKIP = "skip"               # Leave in staging, log warning only
```

#### Behavior by Policy

| Policy | Action | Use Case |
|--------|--------|----------|
| `import` | Move to `Unknown/<OriginalFolder>/` or `Author/Title (Author)/` | **Default** - safe home for all unknowns |
| `quarantine` | Move to quarantine folder, no renames | Strict - only import known content |
| `skip` | Leave in staging, log warning | Manual review workflow |

**Why `import` is the default:**
- **Skipping creates permanent "staging clutter"** - same folders nagging every run
- **Importing to controlled "unknown" zone** gives stable location for future batch resolution
- **Homebrew/self-pub gets a proper home** instead of languishing forever

#### Classifier: Content Type + File Structure

```python
def classify_unknown_asin(folder: Path, parsed: ParsedFolderName) -> UnknownAsinContext:
    audio_files = [f for f in folder.iterdir()
                   if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS]
    file_count = len(audio_files)

    # Heuristic: "Author - Title" pattern suggests homebrew
    if matches_homebrew_pattern(folder.name, parsed):
        content_type = UnknownAsinContentType.HOMEBREW
    else:
        content_type = UnknownAsinContentType.MISSING_ASIN

    # NOTE: is_multi_file is derived from file_count, not a separate class
    return UnknownAsinContext(
        folder=folder,
        parsed=parsed,
        content_type=content_type,
        file_count=file_count,
        original_folder_name=folder.name,
    )
```

#### Import Routing Table

| Content Type | Multi-File? | Target Path | Audio Rename | Sidecar Rename |
|--------------|-------------|-------------|--------------|----------------|
| **MISSING_ASIN** | No | `Unknown/<OriginalFolder>/` | Yes | Yes |
| **MISSING_ASIN** | Yes | `Unknown/<OriginalFolder>/` | **Never** | Optional |
| **HOMEBREW** | No | `<Author>/<Title (Author)>/` | Yes | Yes |
| **HOMEBREW** | Yes | `<Author>/<Title (Author)>/` | **Never** | Optional |

**Key insight:** Multi-file homebrew still goes to author path, just keeps original filenames.

#### Handler Flow

```python
def handle_unknown_asin(ctx: UnknownAsinContext, cfg: Config, *, dry_run: bool = False) -> ImportResult:
    policy = cfg.audiobookshelf.import_settings.unknown_asin_policy

    if policy is UnknownAsinPolicy.SKIP:
        logger.warning("Skipping import for unknown ASIN: %s (type=%s, files=%d)",
                       ctx.folder.name, ctx.content_type, ctx.file_count)
        return ImportResult.skipped(reason="unknown_asin")

    if policy is UnknownAsinPolicy.QUARANTINE:
        return quarantine_unknown(ctx, cfg, dry_run=dry_run)

    # Default: IMPORT
    return import_unknown(ctx, cfg, dry_run=dry_run)
```

---

### Phase 3: Enhanced ASIN Resolution ✅ COMPLETE

**Goal:** Find ASINs from more sources before giving up.

**Key:** Run resolution **before** classification - if we find an ASIN, we don't need the unknown handler.

#### Implementation: `asin.py`

```python
@dataclass
class AsinResolution:
    """Result of ASIN resolution from multiple sources."""
    asin: str | None
    source: str  # "folder" | "filename" | "metadata" | "unknown"
    source_detail: str | None = None  # e.g., which file contained the ASIN

    @property
    def found(self) -> bool:
        return self.asin is not None


def resolve_asin_from_folder(
    folder: Path,
    parsed_asin: str | None = None,
) -> AsinResolution:
    """Try to resolve ASIN from multiple sources within a folder.

    Resolution cascade (stops at first match):
        1. Folder name - use parsed ASIN if provided, else re-extract
        2. File names - check audio file names for embedded ASIN
        3. metadata.json - check sidecar files for ASIN field
    """
    # 1. Check parsed ASIN from folder name (fastest path)
    if parsed_asin and is_valid_asin(parsed_asin):
        return AsinResolution(asin=parsed_asin, source="folder", source_detail=folder.name)

    # 2. Try extracting from folder name again
    folder_asin = extract_asin(folder.name)
    if folder_asin:
        return AsinResolution(asin=folder_asin, source="folder", source_detail=folder.name)

    # 3. Check file names within folder
    if folder.is_dir():
        for f in folder.iterdir():
            if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS:
                file_asin = extract_asin(f.name)
                if file_asin:
                    return AsinResolution(asin=file_asin, source="filename", source_detail=f.name)

        # 4. Check metadata.json sidecars
        for meta_file in folder.glob("*.metadata.json"):
            asin = _extract_asin_from_metadata_file(meta_file)
            if asin:
                return AsinResolution(asin=asin, source="metadata", source_detail=meta_file.name)

        # Also check plain metadata.json
        plain_metadata = folder / "metadata.json"
        if plain_metadata.exists():
            asin = _extract_asin_from_metadata_file(plain_metadata)
            if asin:
                return AsinResolution(asin=asin, source="metadata", source_detail="metadata.json")

    return AsinResolution(asin=None, source="unknown")
```

#### Integration in `importer.py`

```python
def import_single(staging_folder: Path, ...) -> ImportResult:
    parsed = parse_mam_folder_name(folder_name)
    asin = parsed.asin

    # Phase 3: Enhanced ASIN resolution - try multiple sources before giving up
    if not asin:
        resolution = resolve_asin_from_folder(staging_folder, parsed_asin=None)
        if resolution.found:
            asin = resolution.asin
            logger.info("Resolved ASIN %s from %s (%s)",
                        asin, resolution.source, resolution.source_detail or "N/A")

    # Still no ASIN → delegate to unknown ASIN handler
    if not asin:
        ctx = classify_unknown_asin(staging_folder, parsed)
        return handle_unknown_asin(ctx, ...)

    # Continue with normal ASIN-based import...
```

#### Resolution Sources (Priority Order)

| Source | Cost | Reliability | Implementation |
|--------|------|-------------|----------------|
| Folder name | Free | High | `extract_asin(folder.name)` |
| File names | Free | High | Loop over audio files |
| `*.metadata.json` | Free | High | Check common ASIN fields |
| `metadata.json` | Free | High | Check common ASIN fields |

**Acceptance criteria:**
- [x] `AsinResolution` dataclass with `found` property
- [x] `resolve_asin_from_folder()` cascade function
- [x] `_extract_asin_from_metadata_file()` helper
- [x] Integration in `import_single()` before unknown handler
- [x] Tests added: `TestAsinResolution`, `TestResolveAsinFromFolder` (20 tests)

---

### Phase 4: mediainfo Probe (Future Enhancement)

**Goal:** Extract ASIN from embedded file metadata.

**Keep out of hot path** - make it opt-in or batch-only:

```yaml
audiobookshelf:
  import_settings:
    use_mediainfo_for_unknown_asin: false  # Opt-in for slower but thorough resolution
```

Or as a separate command:
```bash
mamfast abs-resolve-asins --use-mediainfo  # Walks Unknown/, probes files, writes sidecars
```

**Implementation sketch:**

```python
def asin_from_mediainfo(audio_file: Path) -> str | None:
    """Extract ASIN from audio file metadata tags."""
    try:
        result = subprocess.run(
            ["mediainfo", "--Output=JSON", str(audio_file)],
            capture_output=True, text=True, check=True
        )
        data = json.loads(result.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return None

    # Search all string fields for ASIN pattern
    blob = json.dumps(data)
    if match := re.search(r"\bB0[A-Z0-9]{8}\b", blob):
        return match.group(0)
    return None
```

---

### Phase 5: Audible API Lookup (Future Enhancement)

**Goal:** Last-resort ASIN resolution via Audible search.

**Keep completely separate from import path:**

```bash
mamfast abs-resolve-asins --use-audible-api
```

**Flow:**
1. Scan `Unknown/` for MISSING_ASIN books
2. Build queries from folder name + embedded metadata
3. Call Audible search API
4. When confidence high, write ASIN sidecar or rename folder to MAM-style

This keeps import runs **fast and deterministic** while letting you nerd out later.

---

## Metadata Breadcrumbs

Drop a tiny sidecar for future tooling:

```python
def write_unknown_asin_sidecar(dst_folder: Path, ctx: UnknownAsinContext):
    # Use underscore prefix instead of dot - some tools hide dotfiles
    sidecar = dst_folder / "_mamfast_unknown_asin.json"
    payload = {
        "content_type": ctx.content_type.value,
        "is_multi_file": ctx.is_multi_file,
        "original_folder": ctx.original_folder_name,
        "file_count": ctx.file_count,
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "policy": "import",
    }
    sidecar.write_text(json.dumps(payload, indent=2, sort_keys=True))
```

**Why underscore prefix (`_mamfast_`) instead of dotfile (`.mamfast_`)?**
- Some file managers/tools hide dotfiles by default
- Less likely to be accidentally excluded from backups
- Still sorts to top in directory listings

**Benefits:**
- `mamfast abs-resolve-asins` can easily find and batch-process these
- See at a glance *why* a folder lives under `Unknown/`
- Track when it was imported for debugging

---

## Edge Cases & Explicit Behaviors

This section documents specific scenarios and their expected outcomes.

### Zero Audio Files

**Scenario:** Folder contains only sidecars (`.jpg`, `.cue`, `.pdf`), no audio.

```
My Book/
├── cover.jpg
└── notes.pdf
```

**Behavior:**
- `file_count = 0`
- Log warning: "No audio files found in folder"
- Skip import entirely (don't move empty audiobook folder)
- NOT an error – just log and continue

**Rationale:** Folder is incomplete or leftover; don't clutter library.

### Mixed Audio Formats

**Scenario:** Folder contains multiple audio files of different formats.

```
My Book/
├── chapter1.m4b
├── chapter2.mp3
└── chapter3.flac
```

**Behavior:**
- All recognized audio extensions count toward `file_count`
- Treated as multi-file (3 audio files)
- Multi-file protection applies if no ASIN

**Rationale:** Different formats don't change the collision risk.

### Single Audio + Multiple Meaningful Sidecars

**Scenario:** Single `.m4b` with chapter-per-track `.cue` and multiple covers.

```
Audiobook/
├── book.m4b
├── book.cue
├── cover_front.jpg
└── cover_back.jpg
```

**Behavior:**
- `file_count = 1` (only `.m4b` is audio)
- Single-file rename rules apply
- Sidecars renamed to match new audio filename if single-file
- For sidecars with numbered suffixes, attempt to preserve relationships

**Rationale:** Safe to rename since collision isn't possible with 1 audio file.

### Nested Disc/CD Structure

**Scenario:** Audio files in subfolders.

```
My Audiobook/
├── Disc 1/
│   ├── Track01.m4b
│   └── Track02.m4b
└── Disc 2/
    ├── Track01.m4b
    └── Track02.m4b
```

**Behavior:**
- **NOT SUPPORTED** in current implementation
- Only top-level files scanned: `file_count = 0`
- Triggers "no audio files" warning
- Folder skipped

**Workaround:** User must flatten folder structure before import.

**Future consideration:** Phase 6+ could add `recursive_scan` option.

### Unicode and Special Characters

**Scenario:** Folder or file names with non-ASCII characters.

```
日本語の本/
├── 第一章.m4b
└── cover.jpg
```

**Behavior:**
- Handled via `utils/naming.py` sanitization
- Japanese transliterated using existing romaji conversion
- Invalid filesystem chars replaced per `pathvalidate`
- Original folder name preserved in sidecar for recovery

**Existing code handles this – no special unknown-ASIN logic needed.**

### Quarantine Path Validation (Phase 2)

**Scenario:** `quarantine_path` configured but doesn't exist or not writable.

**Behavior:**
- Validate at config load time
- If invalid and policy=QUARANTINE: raise `ConfigurationError`
- If valid: create directory if missing (like library_root)

```python
def validate_quarantine_path(cfg: Config) -> None:
    if cfg.audiobookshelf.import_settings.unknown_asin_policy == "quarantine":
        qpath = Path(cfg.audiobookshelf.import_settings.quarantine_path)
        if not qpath.exists():
            qpath.mkdir(parents=True, exist_ok=True)
        if not os.access(qpath, os.W_OK):
            raise ConfigurationError(f"Quarantine path not writable: {qpath}")
```

### Collision in Unknown/ (Already Addressed)

**Scenario:** Two books with same parsed title imported without ASIN.

**Behavior:**
- Use `original_folder_name` for destination, not parsed title
- `Unknown/My Book (2020)/` and `Unknown/My Book (2023)/` coexist
- If exact folder name collision: append incrementing suffix

```python
def get_unique_destination(base_path: Path) -> Path:
    if not base_path.exists():
        return base_path
    # Append suffix: "My Book (2020)" → "My Book (2020)_2"
    counter = 2
    while True:
        candidate = base_path.parent / f"{base_path.name}_{counter}"
        if not candidate.exists():
            return candidate
        counter += 1
```

### Re-import / Idempotence

**Scenario:** Same folder imported twice (e.g., after failed first run).

**Behavior:**
- If destination already exists with matching sidecar: skip with info log
- If destination exists without sidecar: warn, skip (don't overwrite)
- If source folder is now in library (not staging): skip (already imported)

**Guarantee:** Running import twice never duplicates or corrupts data.

> **Note for Phase 2+:** Partial import detection (crash mid-run) is out of scope for Phase 1. Re-runs are conservative and will not attempt auto-repair of incomplete imports.

### Single Main File + Sample/Trailer (Known Limitation)

**Scenario:** One main audiobook + small sample/trailer files.

```
My Book/
├── My Book.m4b        # main file (500 MB)
├── My Book (sample).mp3  # tiny (2 MB)
└── trailer.mp3           # tiny (1 MB)
```

**Behavior:**
- `file_count = 3` → treated as multi-file → **no renames**
- This is conservative but safe

**Known limitation:** Phase 1 does not distinguish "one big file + noise" from "true multi-file."

**Future consideration:** Could add heuristic (if one file is >90% of total size, treat as single-file). But "simple == safe" for now.

### Homebrew Misclassification (Future Consideration)

**Scenario:** Folder looks like `Author - Title` but is actually Audible content.

**Current behavior:** Classified as `HOMEBREW`, routed to `Author/Title (Author)/`.

**Future note:** If Phase 3+ ASIN resolution finds an ASIN that contradicts the `HOMEBREW` guess, library tools are allowed to "upgrade" it to normal Audible content. The sidecar tracks original classification for debugging.

### Foreign/Legacy Unknown Folders

**Scenario:** `Unknown/` contains folders from other tools (not imported by mamfast).

**Behavior:**
- Folders **with** `_mamfast_unknown_asin.json` → mamfast's responsibility
- Folders **without** sidecar → treated as foreign/legacy, won't be auto-touched by future resolution tools unless explicitly configured

---

## Decision: What NOT to Build

Based on feedback analysis, explicitly **not** implementing:

1. **SQLite tracking for unknowns** - We removed SQLite indexer; don't reintroduce
2. **Confidence scores** - ASIN either matches regex or doesn't
3. **Audible API in import path** - Too slow, too risky for hot path
4. **Complex homebrew detection** - Simple "Author - Title" heuristic is enough

---

## Testing Requirements

### Phase 1 Tests ✅ IMPLEMENTED

```python
class TestMultiFileProtection:
    def test_multifile_no_asin_skips_rename(self, tmp_path):
        """Multi-file book without ASIN keeps original filenames."""
        # ✅ Implemented in test_abs_importer.py

    def test_multifile_with_asin_renames(self, tmp_path):
        """Multi-file book WITH ASIN still gets renamed."""
        # ✅ Implemented in test_abs_importer.py

    def test_single_file_no_asin_renames(self, tmp_path):
        """Single-file book without ASIN can be renamed safely."""
        # ✅ Implemented in test_abs_importer.py

    def test_single_file_with_asin_renames(self, tmp_path):
        """Single-file book with ASIN gets renamed normally."""
        # ✅ Implemented in test_abs_importer.py
```

### Phase 2 Tests ✅ IMPLEMENTED

#### Core Policy Tests

| Test | Description | Status |
|------|-------------|--------|
| `test_policy_skip_returns_skipped` | policy=SKIP leaves folder in staging | ✅ |
| `test_policy_quarantine_moves_to_quarantine_path` | policy=QUARANTINE moves to quarantine | ✅ |
| `test_policy_quarantine_requires_path` | QUARANTINE fails without path | ✅ |
| `test_policy_import_missing_asin_to_unknown` | MISSING_ASIN → `Unknown/` | ✅ |
| `test_policy_import_homebrew_to_author` | HOMEBREW → `Author/` | ✅ |
| `test_dry_run_does_not_move` | Dry-run preview only | ✅ |

#### Classification Tests

| Test | Description | Status |
|------|-------------|--------|
| `test_matches_homebrew_pattern_basic` | "Author - Title" detected | ✅ |
| `test_not_homebrew_with_asin` | ASIN present = not homebrew | ✅ |
| `test_not_homebrew_with_year` | Year present = not homebrew | ✅ |
| `test_classify_single_file_missing_asin` | Single-file classification | ✅ |
| `test_classify_multi_file_missing_asin` | Multi-file classification | ✅ |
| `test_classify_homebrew_pattern` | Homebrew classification | ✅ |

#### Edge Case Tests

| Test | Description | Status |
|------|-------------|--------|
| `test_unique_destination_no_collision` | No collision handling | ✅ |
| `test_unique_destination_with_collision` | `_2` suffix on collision | ✅ |
| `test_unique_destination_multiple_collisions` | Increment suffix | ✅ |
| `test_sidecar_written_correctly` | Sidecar has correct fields | ✅ |
| `test_classify_zero_audio_files` | Zero audio = file_count=0 | ✅ |
| `test_mixed_formats_counted_as_multi_file` | Mixed formats counted | ✅ |

#### Integration Tests

| Test | Description | Status |
|------|-------------|--------|
| `test_import_single_no_asin_uses_policy` | import_single uses policy | ✅ |
| `test_import_single_no_asin_skip_policy` | import_single respects SKIP | ✅ |
| `test_import_single_with_asin_ignores_unknown_policy` | ASIN present ignores policy | ✅ |

### Phase 3 Tests (Future)

| Test | Description | Assertions |
|------|-------------|------------|
| `test_resolve_asin_from_folder` | ASIN in folder name | Returns (asin, "folder") |
| `test_resolve_asin_from_filename` | ASIN in audio filename | Returns (asin, "filename") |
| `test_resolve_asin_from_metadata` | ASIN in .metadata.json | Returns (asin, "metadata") |
| `test_resolve_asin_cascade` | All sources checked in order | First match wins |
| `test_resolve_asin_not_found` | No ASIN anywhere | Returns (None, "unknown") |
| `test_metadata_json_has_asin` | Folder missing ASIN, metadata.json has it | Resolved from metadata, normal import |

---

## Summary

| Phase | Priority | Effort | Status |
|-------|----------|--------|--------|
| 1. Multi-file protection | **Critical** | 1-2 hrs | ✅ **Complete** |
| 2. Unknown ASIN policy | High | 4-5 hrs | ✅ **Complete** |
| 3. Enhanced resolution | Medium | 2-3 hrs | 📋 Planned |
| 4. mediainfo probe | Low | 2-3 hrs | ⏸️ Deferred |
| 5. Audible API | Low | 4-5 hrs | ⏸️ Deferred |

**Phase 2 complete:** Unknown ASIN policy with homebrew routing and sidecar metadata.

**Next:** Phase 3 (enhanced resolution from filenames and metadata.json).

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025-12-05 | Initial plan with Phase 1 implementation |
| 1.1.0 | 2025-12-05 | Added core philosophy, first-class unknowns, test matrix |
| 1.2.0 | 2025-12-05 | Decoupled content type from file structure; added edge cases section; collision handling; assumptions/constraints; expanded test matrix |
| 1.3.0 | 2025-12-05 | Added quick-start behavior summary; scope clarification; linked from importer.py |
| 1.4.0 | 2025-12-05 | Added edge cases from review: sample/trailer files, partial imports, homebrew misclassification, foreign folders |
| 2.0.0 | 2025-12-05 | **Phase 2 complete:** Added UnknownAsinPolicy enum, homebrew classification, sidecar writer, config schema, tests |
