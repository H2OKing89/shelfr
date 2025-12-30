# ABS Rename Tool

> Tool to rename audiobook folders in the Audiobookshelf library to match MAM naming schema.

## Related Documentation

| Document | Description |
|----------|-------------|
| [Folder & File Schemas](../naming/NAMING_FOLDER_FILE_SCHEMAS.md) | MAM naming format reference |
| [Audiobookshelf Import](./AUDIOBOOKSHELF_IMPORT.md) | ABS import workflow |
| [Naming Pipeline](../naming/NAMING_PIPELINE.md) | Full cleaning pipeline |

---

## Library Analysis (2025-12-07)

Scan of `/mnt/user/data/audio/audiobooks`:

| Metric | Count | % |
|--------|-------|---|
| Total folders | 1,775 | - |
| Leaf folders (books) | 1,303 | 100% |
| With ASIN detected | 823 | 63% |
| Without ASIN | 480 | 37% |
| With modern `{ASIN.xxx}` | 788 | 60% |
| With legacy `[ASIN.xxx]` | 35 | 3% |
| With year | 806 | 62% |
| With ripper tag | 217 | 17% |
| With volume number | 987 | 76% |
| With edition flags | 23 | 2% |
| **Duplicate ASINs** | 4 conflicts | - |
| **Legacy format** | 177 | 14% |

**Key findings:**
- 37% of books need ASIN lookup (missing from folder name)
- 14% use legacy bracket format needing conversion
- 4 duplicate ASIN conflicts to handle
- 23 books have edition flags (Full-Cast, Dramatized, etc.)

### Mediainfo Analysis

Audio format statistics from library scan:

| Codec | Count | Notes |
|-------|-------|-------|
| AAC | 1,295 | Standard AAC LC |
| USAC (xHE-AAC) | 5 | Higher quality, ABS-incompatible |
| MPEG Audio (MP3) | 1 | Legacy format |
| E-AC-3 | 2 | Dolby Atmos releases |

**Bitrate Distribution (AAC only):**

| Range | Count | % |
|-------|-------|---|
| 96-127 kbps | 997 | 76% |
| 32-63 kbps | 188 | 14% |
| 128-159 kbps | 62 | 5% |
| Other | 48 | 4% |

**Sample Rate Distribution:**

| Rate | Count | % |
|------|-------|---|
| 44.1 kHz | 1,096 | 84% |
| 22.05 kHz | 195 | 15% |
| Other | 12 | 1% |

**Multi-file folders:** 10 (chapter-split audiobooks)

**Total library duration:** 15,662 hours (~652 days)

### Duplicate ASINs - Codec Analysis

| ASIN | Folder 1 | Folder 2 | Issue |
|------|----------|----------|-------|
| B0F6VVC8QX | Wandering Inn vol_16 (AAC @ 62kbps) | Wandering Inn vol_16 [126] (USAC @ 127kbps) | Codec duplicate |
| B0DK9SRYST | Baccano vol_03 (AAC @ 109kbps) | Baccano vol_04 (AAC @ 125kbps) | **Wrong ASIN** on vol_04 |
| B0D1DPR1X3 | HWFWM vol_11 (AAC @ 62kbps) | HWFWM vol_11 [H2OKing] (USAC @ 124kbps) | Codec duplicate |
| B0F14RPXHR | Harry Potter (AAC @ 125kbps) | Harry Potter (Dolby Atmos) (E-AC-3 @ 768kbps) | Edition duplicate |

**Resolution strategy:**
- Codec duplicates: User decides which to keep (AAC for ABS compatibility)
- Edition duplicates: Both valid, need different ASINs or manual resolution
- Data errors: Manual ASIN correction required

### xHE-AAC (USAC) Files

Files with xHE-AAC codec (often marked with `[126]` bitrate or `xHE-ACC` typo suffix):

| Folder | Bitrate | Duration |
|--------|---------|----------|
| Wandering Inn vol_16 [126] | 127 kbps | 39.4h |
| Wandering Inn vol_01 | 135 kbps | 48.1h |
| Ready Player One `xHE-ACC` | 117 kbps | 15.7h |
| HWFWM vol_01 | 118 kbps | 28.9h |
| HWFWM vol_11 [H2OKing] | 124 kbps | 26.3h |

**Note:** xHE-AAC files may not play correctly in Audiobookshelf. Consider keeping AAC version for ABS playback.

---

## Problem Statement

Books in the Audiobookshelf library may have inconsistent folder naming:
- Legacy folder names from previous versions
- Manually added books with non-standard names
- Books imported from other sources
- Folders missing required components (ASIN, year, author)

The `abs-rename` tool will normalize these folders to match the MAM naming schema.

> **Source Directory:** Uses the ABS library path from `audiobookshelf.path_map[].host` in config (e.g., `/mnt/user/data/audio/audiobooks`).

---

## Target Schema

### Series Books
```
{Series} vol_{NN} {Arc} ({Year}) ({Author}) ({EditionFlags}) {ASIN.xxxxx} [{Tag}]
```

### Standalone Books
```
{Title} ({Year}) ({Author}) ({EditionFlags}) {ASIN.xxxxx} [{Tag}]
```

### Components

| Component | Required | Notes |
|-----------|----------|-------|
| `{Series}` | Series only | Series name |
| `vol_{NN}` | Series only | Zero-padded volume number. See [Volume Notation](#16-volume-notation-parts-vs-ranges-vs-novellas) for `vol_01.5`, `vol_01p1`, `vol_01-03` variants. |
| `{Arc}` | No | Arc name or title for series books |
| `{Title}` | Standalone | Title for standalone books |
| `({Year})` | Yes | Release year in parentheses |
| `({Author})` | Yes | Primary author in parentheses |
| `({EditionFlags})` | **No** | Edition qualifiers like `(Full-Cast)`, `(Dolby Atmos)` - preserved/normalized |
| `{ASIN.xxx}` | Yes | ASIN tag in braces |
| `[{Tag}]` | **No** | Ripper tag - **preserved if present**, not added |

### Examples

| Type | Example |
|------|---------|
| Standalone | `Project Hail Mary (2021) (Andy Weir) {ASIN.B08G9PRS1K} [H2OKing]` |
| Standalone (no tag) | `Project Hail Mary (2021) (Andy Weir) {ASIN.B08G9PRS1K}` |
| Series | `Stormlight Archive vol_01 The Way of Kings (2010) (Brandon Sanderson) {ASIN.B003ZWFO7E} [H2OKing]` |
| Series with Arc | `Sword Art Online vol_09 Alicization Beginning (2020) (Reki Kawahara) {ASIN.B08XXXXX} [H2OKing]` |
| Decimal Volume | `Old Mans War vol_01.5 Questions for a Soldier (2008) (John Scalzi) {ASIN.B001D2XXXX}` |
| With Edition Flags | `Harry Potter vol_01 and the Sorcerer's Stone (2025) (J.K. Rowling) (Full-Cast, Dolby Atmos) {ASIN.B0F14RPXHR} [H2OKing]` |

> **Ripper Tags:** Tags like `[H2OKing]` are **preserved** from the source folder if present, not automatically added. See [Future: Libation Integration](#future-libation-integration-for-ripper-tags) for plans to look up missing tags from previous rips.

> **Edition Flags:** Qualifiers like `(Full-Cast)`, `(Dolby Atmos)`, `(Unabridged)` are **preserved and normalized** into an optional `({EditionFlags})` block between author and ASIN. They are never stripped.

---

## CLI Interface

### Command
```bash
mamfast abs-rename [OPTIONS]
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--source` | PATH | ABS library from `path_map` | Directory containing folders to rename |
| `--pattern` | TEXT | `*` | Glob pattern to filter folders |
| `--fetch-metadata` | FLAG | False | Fetch missing metadata from Audnex API |
| `--abs-search` | FLAG | False | Use ABS Audible search for ASIN resolution (network calls) |
| `--abs-search-confidence` | FLOAT | 0.75 | Minimum confidence for ABS search matches |
| `--interactive` | FLAG | False | Prompt for confirmation on each rename |
| `--report` | PATH | None | Output JSON report of changes |

### Global Flags (before subcommand)
```bash
mamfast --dry-run abs-rename        # Preview renames without executing
mamfast -v abs-rename               # Verbose logging
```

### Examples

```bash
# Preview all renames (dry run)
mamfast --dry-run abs-rename

# Rename all folders in ABS library
mamfast abs-rename

# Rename specific pattern with metadata fetch
mamfast abs-rename --pattern "Project*" --fetch-metadata

# Use ABS search for ASIN resolution (slower, but finds more)
mamfast --dry-run abs-rename --abs-search

# Full pipeline: local cascade + ABS search + Audnex metadata
mamfast abs-rename --abs-search --fetch-metadata

# Interactive mode with report
mamfast --dry-run abs-rename --interactive --report rename_report.json
```

---

## Architecture

### Module Structure

```
src/mamfast/abs/
├── rename.py          # NEW: Rename logic (this tool)
├── importer.py        # Existing: Import workflow
├── client.py          # Existing: ABS API client
├── asin.py            # Existing: ASIN extraction & resolution
├── cleanup.py         # Existing: Cleanup logic
├── trumping.py        # Existing: Quality comparison
└── paths.py           # Existing: Path mapping
```

### Existing Module Reuse

This tool heavily reuses existing modules to avoid duplication:

| Module | Functions We'll Use | Purpose |
|--------|---------------------|---------|
| **`abs/asin.py`** | `extract_asin()`, `is_valid_asin()`, `resolve_asin_from_folder_with_mediainfo()`, `resolve_asin_via_abs_search()`, `AsinResolution` | ASIN extraction & cascade resolution |
| **`abs/importer.py`** | `ParsedFolderName`, `parse_mam_folder_name()`, `discover_staged_books()` | Folder name parsing, discovery |
| **`abs/client.py`** | `AbsClient`, `AbsLibrary` | ABS API for search fallback |
| **`abs/paths.py`** | `PathMapper`, `abs_path_to_host()` | Path translation |
| **`utils/naming.py`** | `build_mam_folder_name()`, `normalize_audnex_book()`, `sanitize_filename()`, `NormalizedBook` | Name building & normalization |
| **`metadata.py`** | `fetch_audnex_book()` | Audnex API for metadata fetch |
| **`console.py`** | `print_step()`, `print_success()`, `print_dry_run()`, `print_warning()`, `confirm()` | Rich CLI output |
| **`config.py`** | `Config`, `load_config()` | Configuration loading |

### Imports Template

```python
# abs/rename.py - imports from existing codebase

from __future__ import annotations

import dataclasses
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

# ASIN resolution (existing)
from mamfast.abs.asin import (
    AsinResolution,
    extract_asin,
    is_valid_asin,
    resolve_asin_from_folder_with_mediainfo,
    resolve_asin_via_abs_search,
)

# Folder parsing (existing)
from mamfast.abs.importer import (
    ParsedFolderName,
    parse_mam_folder_name,
)

# Name building (existing)
from mamfast.utils.naming import (
    NormalizedBook,
    build_mam_folder_name,
    normalize_audnex_book,
    sanitize_filename,
)

# Metadata fetch (existing)
from mamfast.metadata import fetch_audnex_book

# Console output (existing)
from mamfast.console import (
    print_dry_run,
    print_step,
    print_success,
    print_warning,
    print_duplicate_pairs,
    confirm,
)

# Fuzzy matching (existing - Phase 4 from IMPROVEMENTS_PLAN.md)
from mamfast.utils.fuzzy import (
    find_duplicates,
    similarity_ratio,
    is_suspicious_change,
)

# Path safety (existing - Phase 2 from IMPROVEMENTS_PLAN.md)
from mamfast.utils.paths import safe_dirname

if TYPE_CHECKING:
    from mamfast.abs.client import AbsClient

logger = logging.getLogger(__name__)

# Audio extensions (reuse from asin.py)
AUDIO_EXTS = {".m4b", ".mp3", ".m4a", ".flac", ".ogg", ".opus"}
```

### Enhanced Packages Used

All packages from IMPROVEMENTS_PLAN.md are already integrated and will be used:

| Package | Used For | Functions |
|---------|----------|-----------|
| **`pydantic`** | ABS metadata.json validation | `AbsMetadataSchema.model_validate()` |
| **`pathvalidate`** | Safe folder renaming | `safe_dirname()` from `utils/paths.py` |
| **`rapidfuzz`** | Duplicate detection, suspicious changes | `find_duplicates()`, `similarity_ratio()`, `is_suspicious_change()` |
| **`rich`** | CLI output tables, progress | `print_duplicate_pairs()`, `print_step()`, `confirm()` |

### New Code (rename.py only)

The new `rename.py` module only needs to implement:

1. **`AbsMetadataSchema`** - Pydantic model for ABS metadata.json validation
2. **`AbsMetadata`** - Dataclass for parsed ABS metadata
3. **`parse_abs_metadata()`** - Parse & validate ABS metadata.json sidecar
4. **`RenameCandidate`** - Dataclass for rename pipeline state
5. **`RenameResult`** - Dataclass for rename operation result
6. **`discover_rename_candidates()`** - Find leaf folders with audio
7. **`detect_edition_flags()`** - Extract edition flags from name
8. **`detect_duplicates()`** - Mark duplicate ASINs (uses `rapidfuzz`)
9. **`compute_target_name()`** - Build target name using existing `build_mam_folder_name()`
10. **`rename_folder()`** - Execute the actual rename (uses `pathvalidate` via `safe_dirname()`)

Everything else is reused from existing modules!

### Core Components

```python
# abs/rename.py

@dataclass
class RenameCandidate:
    """A folder that may need renaming."""
    source_path: Path
    current_name: str
    parsed: ParsedFolderName | None  # Existing parser from naming.py
    target_name: str | None = None   # Computed MAM-compliant name
    status: RenameStatus = "needs_rename"  # See RenameStatus for all values
    metadata: NormalizedBook | None = None  # Fetched from Audnex if needed
    edition_flags: list[str] = field(default_factory=list)  # Detected edition qualifiers
    asin_source: str | None = None  # How ASIN was resolved: folder, filename, metadata, mediainfo, abs_search


RenameStatus = Literal[
    "needs_rename",      # Folder name differs from target
    "up_to_date",        # Already matches target schema
    "missing_asin",      # No ASIN found, cannot rename
    "duplicate_asin",    # Same ASIN in multiple folders (conflict)
    "target_exists",     # Target folder name already exists
    "error",             # Parse or other error
]


@dataclass
class RenameResult:
    """Result of a rename operation."""
    source_path: Path
    target_path: Path | None
    status: Literal["success", "skipped", "failed", "dry_run"]
    files_renamed: list[str] | None = None  # Files renamed inside folder
    error: str | None = None
```

### Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         ABS Rename Pipeline                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Stage 1: Discovery                                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ Scan ABS library → Filter leaf folders with audio files              │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                              │                                              │
│                              ▼                                              │
│  Stage 2: Parse Existing Names                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ ParsedFolderName.from_string() → Extract ASIN, series, author, etc.  │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                              │                                              │
│                              ▼                                              │
│  Stage 2.5: ABS metadata.json (Authoritative)                              │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ Parse ABS metadata.json → Get ASIN, title, series, year (if exists)  │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                              │                                              │
│                              ▼                                              │
│  Stage 3: ASIN Resolution (Cascade)                                        │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ folder name → file names → Libation metadata → mediainfo → ABS search│  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                              │                                              │
│                              ▼                                              │
│  Stage 3.5: Metadata Fetch (Optional)                                      │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ If --fetch-metadata: Audnex API lookup by ASIN → NormalizedBook      │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                              │                                              │
│                              ▼                                              │
│  Stage 4: Duplicate ASIN Detection                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ Check for same ASIN in multiple folders → Mark duplicate_asin        │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                              │                                              │
│                              ▼                                              │
│  Stage 5: Build Target Names                                               │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ build_mam_folder_name() → Apply naming schema → Compare to current   │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                              │                                              │
│                              ▼                                              │
│  Stage 6: Execute Renames                                                  │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ If not --dry-run: Path.rename() → Update internal files if needed    │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Implementation Details

### Stage 1: Discovery

A candidate is any directory that contains audio files and is **not** a parent of another directory with audio files (leaf-only).

```python
import os
import fnmatch
from pathlib import Path

AUDIO_EXTS = {".m4b", ".mp3", ".m4a", ".flac", ".ogg", ".opus"}

def has_audio_files(path: Path) -> bool:
    """Check if directory contains audio files."""
    return any(
        p.is_file() and p.suffix.lower() in AUDIO_EXTS
        for p in path.iterdir()
    )

def discover_rename_candidates(
    source_dir: Path,
    pattern: str = "*",
) -> list[Path]:
    """Find leaf folders that contain audio files.

    Leaf = has audio AND no subdirectory also has audio.
    This preserves Author/Series hierarchy while only renaming book folders.
    """
    candidates: list[Path] = []

    for root, dirs, _files in os.walk(source_dir):
        root_path = Path(root)

        # Only consider dirs that match pattern
        if not fnmatch.fnmatch(root_path.name, pattern):
            continue

        # Must have audio files
        if not has_audio_files(root_path):
            continue

        # Skip if any subdir also has audio (not a leaf)
        if any(has_audio_files(root_path / d) for d in dirs):
            continue

        candidates.append(root_path)

    return sorted(candidates)
```

### Stage 2: Parse Existing Names

Reuse existing `ParsedFolderName` from `naming.py`:

```python
from mamfast.utils.naming import ParsedFolderName

def detect_edition_flags(name: str) -> list[str]:
    """Detect edition flags in folder name."""
    FLAGS = [
        "Full-Cast", "Full Cast", "Dolby Atmos", "Atmos",
        "Unabridged", "Abridged", "Dramatized", "Graphic Audio",
    ]
    return [f for f in FLAGS if f.lower() in name.lower()]

def parse_candidate(folder: Path) -> RenameCandidate:
    """Parse folder name and determine rename status."""
    try:
        parsed = ParsedFolderName.from_string(folder.name)
        flags = detect_edition_flags(folder.name)
        return RenameCandidate(
            source_path=folder,
            current_name=folder.name,
            parsed=parsed,
            edition_flags=flags if flags else None,
        )
    except ValueError as e:
        return RenameCandidate(
            source_path=folder,
            current_name=folder.name,
            parsed=None,
            status="error",
        )
```

### Stage 2.5: ABS metadata.json (Authoritative Source)

**NEW DISCOVERY:** ABS creates a `metadata.json` sidecar in each book folder with authoritative metadata, including ASIN even when not in folder name!

```python
# Sample ABS metadata.json structure
{
    "title": "The Rising of the Shield Hero, Volume 14",
    "subtitle": None,
    "authors": ["Aneko Yusagi"],
    "narrators": ["Shea Taylor"],
    "series": ["Rising of the Shield Hero #14"],  # Series with position!
    "genres": ["Science Fiction & Fantasy"],
    "publishedYear": 2025,
    "publisher": "One Peace Books",
    "asin": "B0FLYN3KN3",  # ASIN even when not in folder name
    "isbn": "9781642735567",
    "language": "English",
    "explicit": False,
    "abridged": False,
    "description": "<p>...</p>",
    "tags": ["Fantasy", "Action & Adventure", "Epic"],
    "chapters": [...]  # Chapter markers
}
```

**Key insight:** Check `metadata.json` FIRST before parsing folder name - it's more authoritative and often has ASIN when folder doesn't.

```python
import json
from pathlib import Path
from dataclasses import dataclass

from pydantic import BaseModel, Field

# Pydantic schema for validation (Phase 1 from IMPROVEMENTS_PLAN.md)
class AbsMetadataSchema(BaseModel):
    """Pydantic schema for ABS metadata.json validation."""
    title: str | None = None
    subtitle: str | None = None
    authors: list[str] = Field(default_factory=list)
    narrators: list[str] = Field(default_factory=list)
    series: list[str] = Field(default_factory=list)  # ["Series Name #N"]
    genres: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    publishedYear: int | str | None = None
    publisher: str | None = None
    asin: str | None = None
    isbn: str | None = None
    language: str | None = None
    explicit: bool = False
    abridged: bool = False
    description: str | None = None

    model_config = {"extra": "ignore"}  # ABS may add new fields


@dataclass
class AbsMetadata:
    """Parsed ABS metadata.json (post-validation)."""
    title: str | None = None
    authors: list[str] | None = None
    series: str | None = None
    series_position: float | None = None
    year: int | None = None
    asin: str | None = None
    narrators: list[str] | None = None


def parse_abs_metadata(folder: Path) -> AbsMetadata | None:
    """Parse and validate ABS metadata.json if present."""
    meta_path = folder / "metadata.json"
    if not meta_path.exists():
        return None

    try:
        with open(meta_path) as f:
            data = json.load(f)

        # Validate with Pydantic
        schema = AbsMetadataSchema.model_validate(data)

        # Parse series from "Series Name #N" format
        series_name = None
        series_pos = None
        if schema.series:
            series_str = schema.series[0]
            if "#" in series_str:
                parts = series_str.rsplit("#", 1)
                series_name = parts[0].strip()
                try:
                    series_pos = float(parts[1].strip())
                except ValueError:
                    pass
            else:
                series_name = series_str

        # Parse year (can be int or string)
        year = None
        if schema.publishedYear:
            try:
                year = int(schema.publishedYear)
            except (ValueError, TypeError):
                pass

        return AbsMetadata(
            title=schema.title,
            authors=schema.authors or None,
            series=series_name,
            series_position=series_pos,
            year=year,
            asin=schema.asin,
            narrators=schema.narrators or None,
        )
    except Exception as e:
        logger.debug(f"Failed to parse ABS metadata.json: {e}")
        return None


def enrich_candidate_from_abs_metadata(candidate: RenameCandidate) -> RenameCandidate:
    """Enrich candidate with ABS metadata.json if available."""
    abs_meta = parse_abs_metadata(candidate.source_path)
    if not abs_meta:
        return candidate

    # If we have ASIN from metadata.json, use it
    if abs_meta.asin and candidate.parsed:
        if not candidate.parsed.asin:
            candidate.parsed.asin = abs_meta.asin
            return dataclasses.replace(candidate, asin_source="abs_metadata.json")

    return candidate
```

### Stage 3: ASIN Resolution (Cascade)

Reuse the same resolution cascade from `abs-import` (see `abs/asin.py`), but **after** checking ABS metadata.json:

```
Resolution Cascade (stops at first match):
0. ABS metadata.json → authoritative, check FIRST (new!)
1. Folder name  → extract {ASIN.xxx} from folder name
2. File names   → check audio file names for embedded ASIN (e.g., B0123456789.m4b)
3. Libation metadata.json → check sidecar files for ASIN field
4. mediainfo    → probe audio files for embedded metadata tags
5. ABS search   → query Audiobookshelf's Audible provider (opt-in, --abs-search)
```

```python
from mamfast.abs.asin import (
    resolve_asin_from_folder_with_mediainfo,
    resolve_asin_via_abs_search,
    AsinResolution,
)
from mamfast.abs.client import AbsClient

def resolve_asin(
    candidate: RenameCandidate,
    abs_client: AbsClient | None = None,
    abs_search_confidence: float = 0.75,
) -> RenameCandidate:
    """Resolve ASIN using cascade: folder → files → metadata → mediainfo → ABS search.

    This mirrors the resolution logic in abs/importer.py for consistency.
    """
    # If we already have ASIN from folder parse, skip cascade
    if candidate.parsed and candidate.parsed.asin:
        return candidate

    # Phase 3+4: Local resolution (folder name, filenames, metadata.json, mediainfo)
    resolution = resolve_asin_from_folder_with_mediainfo(
        candidate.source_path,
        parsed_asin=candidate.parsed.asin if candidate.parsed else None
    )

    if resolution.found:
        # Update parsed with resolved ASIN
        if candidate.parsed:
            candidate.parsed.asin = resolution.asin
        return dataclasses.replace(
            candidate,
            asin_source=resolution.source,  # Track how we found it
        )

    # Phase 5: ABS Metadata Search (opt-in via --abs-search flag)
    if abs_client is not None:
        search_title = candidate.parsed.title if candidate.parsed else candidate.current_name
        search_author = candidate.parsed.author if candidate.parsed else None

        resolution = resolve_asin_via_abs_search(
            abs_client,
            search_title,
            search_author,
            abs_search_confidence,
        )

        if resolution.found:
            if candidate.parsed:
                candidate.parsed.asin = resolution.asin
                # Update author if resolved from search
                if resolution.resolved_author and not candidate.parsed.author:
                    candidate.parsed.author = resolution.resolved_author
            return dataclasses.replace(
                candidate,
                asin_source="abs_search",
            )

    # No ASIN found after full cascade
    return dataclasses.replace(candidate, status="missing_asin")
```

### Stage 3.5: Metadata Fetch (Audnex)

```python
from mamfast.metadata import fetch_audnex_metadata
from mamfast.utils.naming import normalize_audnex_book

async def fetch_metadata(
    candidate: RenameCandidate,
    fetch: bool = False,
) -> RenameCandidate:
    """Fetch full metadata from Audnex API."""
    if candidate.status == "missing_asin":
        return candidate  # Can't fetch without ASIN

    asin = candidate.parsed.asin if candidate.parsed else None
    if not asin:
        return dataclasses.replace(candidate, status="missing_asin")

    if fetch:
        audnex_data = await fetch_audnex_metadata(asin)
        if audnex_data:
            normalized = normalize_audnex_book(audnex_data)
            return dataclasses.replace(candidate, metadata=normalized)

    return candidate
```

### Stage 4: Duplicate ASIN Detection

Detect folders that would produce the same target name (same ASIN):

```python
from collections import defaultdict

def detect_duplicates(candidates: list[RenameCandidate]) -> list[RenameCandidate]:
    """Mark candidates with duplicate ASINs.

    If multiple folders have the same ASIN, we can't auto-rename them
    because they'd produce identical target names. Mark as duplicate_asin
    for manual resolution.
    """
    # Group by ASIN
    asin_groups: dict[str, list[int]] = defaultdict(list)
    for i, c in enumerate(candidates):
        asin = c.parsed.asin if c.parsed else None
        if asin:
            asin_groups[asin].append(i)

    # Mark duplicates
    result = list(candidates)
    for asin, indices in asin_groups.items():
        if len(indices) > 1:
            for i in indices:
                result[i] = dataclasses.replace(
                    result[i],
                    status="duplicate_asin",
                )

    return result


def detect_similar_titles(
    candidates: list[RenameCandidate],
    threshold: int = 90,
) -> list[tuple[RenameCandidate, RenameCandidate, float]]:
    """Find candidates with suspiciously similar titles (using rapidfuzz).

    This catches potential duplicates that have different ASINs but same content,
    e.g., different editions, codec variants, or data errors.
    """
    from mamfast.utils.fuzzy import similarity_ratio

    similar = []
    for i, c1 in enumerate(candidates):
        title1 = c1.parsed.title if c1.parsed else c1.current_name
        for c2 in candidates[i + 1:]:
            title2 = c2.parsed.title if c2.parsed else c2.current_name
            ratio = similarity_ratio(title1, title2)
            if ratio >= threshold:
                similar.append((c1, c2, ratio))

    return similar
```

### Stage 5: Build Target Names

```python
from mamfast.utils.naming import build_mam_folder_name
from mamfast.utils.paths import safe_dirname  # pathvalidate wrapper

def compute_target_name(candidate: RenameCandidate) -> RenameCandidate:
    """Compute the MAM-compliant target name."""
    # Skip candidates already marked with terminal status
    if candidate.status in {"error", "missing_asin", "duplicate_asin"}:
        return candidate

    # Preserve existing ripper tag from parsed folder name
    ripper_tag = candidate.parsed.ripper_tag if candidate.parsed else None

    # Use metadata if available, otherwise fall back to parsed data
    if candidate.metadata:
        target = build_mam_folder_name(
            normalized=candidate.metadata,
            ripper_tag=ripper_tag,  # Preserve existing tag
            edition_flags=candidate.edition_flags,
        )
    elif candidate.parsed:
        # Build from parsed data (may be incomplete)
        target = build_mam_folder_name_from_parsed(
            parsed=candidate.parsed,
            ripper_tag=ripper_tag,  # Preserve existing tag
            edition_flags=candidate.edition_flags,
        )
    else:
        return dataclasses.replace(candidate, status="missing_asin")

    # Apply pathvalidate for cross-platform safety (Phase 2 from IMPROVEMENTS_PLAN.md)
    target = safe_dirname(target)

    # Compare to current name
    if target == candidate.current_name:
        return dataclasses.replace(candidate, status="up_to_date", target_name=target)

    return dataclasses.replace(candidate, status="needs_rename", target_name=target)
```

### Stage 6: Execute Renames

```python
def rename_folder(
    candidate: RenameCandidate,
    dry_run: bool = False,
) -> RenameResult:
    """Execute a single folder rename."""
    if candidate.status != "needs_rename" or not candidate.target_name:
        return RenameResult(
            source_path=candidate.source_path,
            target_path=None,
            status="skipped",
        )

    target_path = candidate.source_path.parent / candidate.target_name

    if dry_run:
        return RenameResult(
            source_path=candidate.source_path,
            target_path=target_path,
            status="dry_run",
        )

    try:
        candidate.source_path.rename(target_path)
        return RenameResult(
            source_path=candidate.source_path,
            target_path=target_path,
            status="success",
        )
    except OSError as e:
        return RenameResult(
            source_path=candidate.source_path,
            target_path=target_path,
            status="failed",
            error=str(e),
        )
```

---

## Edge Cases

### 1. Nested Directories (Author/Series/Book)

**Decision:** Keep hierarchy, rename only leaf folders.

The ABS library uses nested structure like `Author/Series/Book`. We:
- **Keep** the `Author/` and `Series/` parent folders as-is
- **Rename only** the leaf "book" folder (the one containing audio files)
- **Never flatten** the hierarchy

**Discovery rule:** A candidate is any directory that contains audio files (`.m4b`, etc.) and is **not** a parent of another directory with audio files.

**Example:**
```
J.K. Rowling/                           ← NOT renamed (author folder)
├── Fantastic Beasts... [2017]...       ← RENAMED (leaf, contains .m4b)
└── Harry Potter/                       ← NOT renamed (series folder)
    ├── Harry Potter vol_01...          ← RENAMED (leaf, contains .m4b)
    └── Harry Potter vol_02...          ← RENAMED (leaf, contains .m4b)
```

---

### 2. Duplicate ASINs (Same ASIN in Multiple Folders)

**Decision:** Treat as conflicts, skip with warning.

When the same ASIN appears in multiple folders:
- **Mark all as `status="duplicate_asin"`**
- **Skip all conflicting candidates** for that ASIN
- **Report in a "Conflicts" section** for manual review
- Do NOT auto-decide which is "the real" edition

**Common causes of duplicate ASINs:**

| Cause | Example | Resolution |
|-------|---------|------------|
| Different editions | `(Full-Cast)` vs `(Full-Cast, Dolby Atmos)` | Manual: pick preferred edition |
| Codec variants | `[H2OKing]` vs `[H2OKing] [126]` | Manual: keep ABS-compatible version |
| With/without ripper tag | `{ASIN.xxx}` vs `{ASIN.xxx} [H2OKing]` | Auto-merge possible (keep tagged) |
| Data error | vol_03 and vol_04 share same ASIN | Manual: fix ASIN lookup |

**Library scan found 4 duplicate ASIN conflicts:**
```
B0F6VVC8QX - Wandering Inn vol_16 (codec variants: AAC vs xHE-AAC [126])
B0DK9SRYST - Baccano vol_03 & vol_04 (data error - same ASIN on different books)
B0D1DPR1X3 - HWFWM vol_11 (with/without ripper tag)
B0F14RPXHR - Harry Potter Full-Cast (different Atmos editions)
```

**Output:**
```
⚠️  Duplicate ASIN B0F14RPXHR found in 2 folders - skipping both:
    - Harry Potter vol_01... (Full-Cast) {ASIN.B0F14RPXHR}
    - Harry Potter vol_01... (Full-Cast, Dolby Atmos) {ASIN.B0F14RPXHR}
```

**Future:** `--allow-duplicate-asins` flag could enable renaming with explicit edition differentiation.

---

### 3. Edition Flags (Full-Cast, Dolby Atmos, etc.)

**Decision:** Preserve and normalize, never strip.

Edition qualifiers are meaningful for distinguishing versions:
- `(Full-Cast)`, `(Dolby Atmos)`, `(Unabridged)`, `(Dramatized)`
- **Preserve** them in the folder name
- **Normalize** into an `({EditionFlags})` block between author and ASIN
- **Combine multiple flags** with comma: `(Full-Cast, Dolby Atmos)`

**Before:**
```
Harry Potter vol_01 and the Sorcerer's Stone (2025) (J.K. Rowling) (Full-Cast) (Dolby Atmos) {ASIN.B0F14RPXHR}
```

**After (normalized):**
```
Harry Potter vol_01 and the Sorcerer's Stone (2025) (J.K. Rowling) (Full-Cast, Dolby Atmos) {ASIN.B0F14RPXHR}
```

**Known edition flags to detect:**
- `Full-Cast`, `Full Cast`, `Full-Cast Edition`
- `Dolby Atmos`
- `Unabridged`, `Abridged`
- `Dramatized`, `Dramatized Adaptation`
- `Graphic Audio`

---

### 4. File Renaming (Folder + Contents)

**Decision:** Rename both folder AND files, skip `cover.jpg` and `metadata.json`.

When renaming a book folder:
- **Rename the folder** to the target MAM name
- **Rename all content files** inside to match the new folder base name
- **Skip these files unchanged:**
  - `cover.jpg`
  - `metadata.json`

**Before:**
```
Harry Potter vol_01... {ASIN.B017V4IM1G}/
├── Harry Potter vol_01... {ASIN.B017V4IM1G}.m4b
├── Harry Potter vol_01... {ASIN.B017V4IM1G}.cue
├── cover.jpg
└── metadata.json
```

**After:**
```
Harry Potter vol_01 and the Sorcerer's Stone (2015) (J.K. Rowling) (Jim Dale) {ASIN.B017V4IM1G}/
├── Harry Potter vol_01 and the Sorcerer's Stone (2015) (J.K. Rowling) (Jim Dale) {ASIN.B017V4IM1G}.m4b
├── Harry Potter vol_01 and the Sorcerer's Stone (2015) (J.K. Rowling) (Jim Dale) {ASIN.B017V4IM1G}.cue
├── cover.jpg          ← unchanged
└── metadata.json      ← unchanged
```

**Implementation:**
```python
SKIP_FILES = {"cover.jpg", "metadata.json"}

for f in target_folder.iterdir():
    if not f.is_file() or f.name in SKIP_FILES:
        continue
    new_name = f"{target_stem}{f.suffix}"
    f.rename(f.with_name(new_name))
```

---

### 5. Legacy Format (Brackets Instead of Braces)

**Decision:** Parse and convert to standard format.

Old folder names may use `[brackets]` instead of `(parentheses)` and `{braces}`:
```
Fantastic Beasts and Where to Find Them [2017] [J.K. Rowling] [B01N4S7VVP]
```

The parser should:
- Recognize `[ASIN]` pattern (10-char alphanumeric starting with B)
- Convert to `{ASIN.xxx}` format
- Recognize `[Year]` (4 digits) and convert to `(Year)`
- Recognize `[Author]` and convert to `(Author)`

**After rename:**
```
Fantastic Beasts and Where to Find Them (2017) (J.K. Rowling) {ASIN.B01N4S7VVP}
```

---

### 6. Missing ASIN

Folders without identifiable ASIN cannot be auto-renamed:
- **Skip with warning**
- Mark as `status="missing_asin"`
- In `--interactive` mode: optionally prompt for manual ASIN entry

**Library scan found:** 480 folders without detected ASIN (37% of library)

---

### 7. ASIN Format Variations

Handle different ASIN formats found in the wild:

| Format | Example | Count in Library |
|--------|---------|------------------|
| Modern braces | `{ASIN.B0123456789}` | 788 |
| Brackets with prefix | `[ASIN.B0123456789]` | 35 |
| Bare brackets | `[B0123456789]` | ~35 |
| ISBN-style (numeric) | `{ASIN.1774240327}` | ~18 |
| Typos | `[AISN.B0F2B4LWF7]` | 1 |
| Brace mismatch | `{ASIN.B0CYJN13ZH]` | 1 |

All should be normalized to `{ASIN.B0123456789}`.

**ISBN-style ASINs:** Some audiobooks use ISBN-10 as ASIN (numeric, not starting with B):
```
The Wandering Inn vol_01 (2019) (Pirateaba) {ASIN.1774240327}
Solo Leveling vol_01 (2021) (Chugong) {ASIN.1975325885}
```

---

### 8. Duplicate Target Names

If the computed target name already exists on disk:
- **Skip with warning**
- Mark as `status="target_exists"`
- Report for manual resolution

---

### 9. Special Characters

Handled by existing `pathvalidate` integration:
- Cross-platform safe characters
- Unicode normalization (NFC)
- Japanese transliteration (kanji → romaji)

---

### 10. Completely Bare Folder Names

Some folders have no metadata at all:
```
Project Hail Mary
Vol. 01 - Gravesong
Amelia the Level Zero Hero - vol_01
```

**Library scan found:** ~309 folders with no year, no parens, no brackets.

These require `--fetch-metadata` with ASIN lookup from ABS or manual intervention.

---

### 11. Multi-Part Volumes (Parts vs Ranges)

> **Full specification:** See [Edge Case #16](#16-volume-notation-parts-vs-ranges-vs-novellas) for the canonical volume notation spec.

Some series have split volumes or omnibus editions:

| Current | Normalized | Type |
|---------|------------|------|
| `vol_01-1` | `vol_01p1` | Part (GA split) |
| `vol_01_01` | `vol_01p1` | Part (legacy) |
| `vol_01-03` | `vol_01-03` | Range (Publisher Pack) |
| `vol_01.5` | `vol_01.5` | Novella |

**Key distinction:**
- `p` = **part** (same book split into releases)
- `-NN` where NN > base = **range** (multiple books combined)
- `.N` = **novella** (side story between books)

---

### 12. Ripper Tags vs Edition/Codec Indicators

**Decision:** Only preserve the configured ripper tag (`H2OKing`). Strip all other bracket suffixes.

Various suffix formats found in library:

| Suffix | Meaning | Action |
|--------|---------|--------|
| `[H2OKing]` | Your ripper tag | **PRESERVE** |
| `[PP]` | Publisher's Pack (omnibus edition) | **MOVE TO EDITION FLAGS** |
| `[GA]` | Graphic Audio production | **MOVE TO EDITION FLAGS** |
| `[126]` | Bitrate indicator (126kbps xHE-AAC) | **STRIP** |
| `ACC` | Codec suffix (bare, no brackets) | **STRIP** |
| `xHE-ACC` | Codec suffix (typo for xHE-AAC) | **STRIP** |

> **Note:** The correct codec name is **xHE-AAC** (Extended HE-AAC). The suffix `xHE-ACC` is a common typo found in-the-wild that we need to handle.

**Why codec duplicates exist:** ABS doesn't support xHE-AAC codec, so some books have both:
- High quality xHE-AAC version (e.g., 126kbps) - marked with `[126]` or `xHE-ACC`
- Legacy AAC version (e.g., 64kbps) - for ABS compatibility

**Edition indicators vs Ripper tags:**
- `[PP]` (Publisher's Pack) and `[GA]` (Graphic Audio) are **edition indicators**, not ripper tags
- These should be normalized into the `({EditionFlags})` block, not stripped entirely
- Example: `Book vol_01-02 [PP] {ASIN.xxx}` → `Book vol_01-02 (2022) (Author) (Publisher's Pack) {ASIN.xxx}`

**Config setting:**
```yaml
audiobookshelf:
  import:
    ripper_tag_preserve: ["H2OKing"]  # Only these tags are preserved as ripper tags
```

**Known edition indicators to convert:**
```python
EDITION_INDICATORS = {
    "PP": "Publisher's Pack",
    "GA": "Graphic Audio",
}
```

**Implementation:**
```python
def classify_bracket_suffix(tag: str, preserve_tags: list[str]) -> str:
    """Classify a bracket suffix as ripper_tag, edition, or strip."""
    tag_upper = tag.upper()

    # Check if it's a preserved ripper tag
    if any(tag.lower() == t.lower() for t in preserve_tags):
        return "ripper_tag"

    # Check if it's an edition indicator
    if tag_upper in EDITION_INDICATORS:
        return "edition"

    # Check if it's a codec/bitrate indicator (strip these)
    if tag.isdigit() or tag_upper in ("ACC", "XHE-ACC", "HE-ACC"):
        return "strip"

    # Unknown - strip by default
    return "strip"
```

---

### 13. Same ASIN, Different Codec Versions

When same ASIN appears multiple times due to codec variants:

```
The Wandering Inn vol_16... {ASIN.B0F6VVC8QX} [H2OKing]       ← Legacy AAC
The Wandering Inn vol_16... {ASIN.B0F6VVC8QX} [H2OKing] [126] ← xHE-AAC @ 126kbps
```

**Why codec variants exist:**
- Audible serves different codec versions (xHE-AAC vs HE-AAC vs AAC)
- xHE-AAC (`[126]`, `xHE-ACC`) is higher quality but has compatibility issues
- Some users keep both: xHE-AAC for archival, legacy AAC for ABS playback
- The `[126]` suffix indicates bitrate, not a ripper tag

**Decision:** Treat as `duplicate_asin` conflicts requiring manual resolution.
- Tool detects and reports these as conflicts
- User decides which codec version to keep (usually legacy AAC for ABS compatibility)
- Codec suffixes (`[126]`, `ACC`, `xHE-ACC`) are stripped during rename anyway

**Conflict report:**
```
⚠️  Duplicate ASIN B0F6VVC8QX found in 2 folders - skipping both:
    - The Wandering Inn vol_16... {ASIN.B0F6VVC8QX} [H2OKing]
    - The Wandering Inn vol_16... {ASIN.B0F6VVC8QX} [H2OKing] [126]
    Likely cause: codec variants (delete unwanted version and retry)
```

---

### 14. Legacy All-Brackets Format

Some folders use brackets `[]` for everything instead of the correct format:

```
Current:  The Empyrean - vol_01 - Fourth Wing [2023] [Rebecca Yarros] [ASIN.B0BVD25SYT]
Expected: The Empyrean vol_01 Fourth Wing (2023) (Rebecca Yarros) {ASIN.B0BVD25SYT}
```

**Issues to fix:**
| Component | Wrong | Correct |
|-----------|-------|---------|
| Year | `[2023]` | `(2023)` |
| Author | `[Rebecca Yarros]` | `(Rebecca Yarros)` |
| ASIN | `[ASIN.xxx]` | `{ASIN.xxx}` |
| Title separator | ` - ` | ` ` (space) |

**Decision:** Full rename to correct schema. Parser must handle both formats.

**Implementation:** The existing `ParsedFolderName` regex should match brackets for ASIN extraction, then `build_mam_folder_name()` outputs correct braces format.

---

### 15. Brace/Bracket Mismatch Typos

Folders with opening brace but closing bracket (or vice versa):

```
Wrong: {ASIN.B0CYJN13ZH]   ← Opens with { but closes with ]
Right: {ASIN.B0CYJN13ZH}
```

**Real example from library:**
```
The Empyrean - vol_02-1 - Iron Flame [2024] [Rebecca Yarros] {ASIN.B0CYJN13ZH] [Dramatized Adaptation]
```

**Decision:** Parser should be lenient on extraction, output should use correct braces `{ASIN.xxx}`.

**Implementation:**
```python
# Lenient ASIN extraction (handles mismatched braces/brackets)
ASIN_PATTERN = re.compile(r'[{\[]ASIN\.([A-Z0-9]{10})[}\]]')
```

---

### 16. Volume Notation: Parts vs Ranges vs Novellas

> **Canonical spec:** See [NAMING_FOLDER_FILE_SCHEMAS.md#volume-notation](../naming/NAMING_FOLDER_FILE_SCHEMAS.md#volume-notation)

Different volume notations have **distinct semantic meaning**:

| Pattern | Notation | Meaning | Example |
|---------|----------|---------|---------|
| `vol_01` | Single | Standard volume | Normal audiobook |
| `vol_01.5` | Decimal | Novella/side story | Story between books 1 and 2 |
| `vol_01-03` | Range | Publisher Pack (books 1-3) | Multi-book omnibus |
| `vol_01p1` | Part | Split release (Part 1) | Graphic Audio Part 1 of 2 |

**Why `p` for parts?**
- Avoids ambiguity: `vol_01-2` could mean "books 1-2" or "book 1, part 2"
- `vol_01p1` is unambiguous: volume 1, part 1
- `.` is reserved for novellas (`.5` = between books)

---

### 17. Audnex API: Part Number in Title, Not Position

**Problem:** The Audnex API stores part numbers **in the title**, not as a separate field.

**API Response Examples:**

| ASIN | Title | `seriesPrimary.position` |
|------|-------|-------------------------|
| B0CKS42KQH | "Fourth Wing (Part 1 of 2) (Dramatized Adaptation)" | `"1"` |
| B0CQQ6ZV5J | "Fourth Wing (Part 2 of 2) (Dramatized Adaptation)" | `"1"` |

Both parts have `position: "1"` because they're both **book 1** in the series. The part number is only in the title.

**Solution:** Parse the title to extract part number:

```python
import re

def extract_part_from_title(title: str) -> tuple[str, int | None]:
    """Extract part number from title and return cleaned title.

    Args:
        title: Raw title like "Fourth Wing (Part 1 of 2) (Dramatized Adaptation)"

    Returns:
        Tuple of (cleaned_title, part_number or None)
    """
    # Match "(Part N of M)" pattern
    match = re.search(r'\s*\(Part\s+(\d+)\s+of\s+\d+\)', title)
    if match:
        part_num = int(match.group(1))
        # Remove the part marker from title
        cleaned = title[:match.start()] + title[match.end():]
        cleaned = cleaned.strip()
        return (cleaned, part_num)
    return (title, None)

# Examples:
# "Fourth Wing (Part 1 of 2) (Dramatized Adaptation)" → ("Fourth Wing (Dramatized Adaptation)", 1)
# "Fourth Wing (Part 2 of 2) (Dramatized Adaptation)" → ("Fourth Wing (Dramatized Adaptation)", 2)
# "Fourth Wing (Dramatized Adaptation)" → ("Fourth Wing (Dramatized Adaptation)", None)
```

**Building volume notation from API data:**

```python
def build_volume_notation(series_position: str | None, title: str) -> str:
    """Build volume notation including part if present in title.

    Args:
        series_position: From seriesPrimary.position (e.g., "1", "1.5")
        title: Raw title (may contain "Part N of M")

    Returns:
        Volume notation like "vol_01", "vol_01p1", "vol_01.5"
    """
    if not series_position:
        return ""

    # Parse position (handles "1", "1.5", etc.)
    try:
        vol = float(series_position)
    except ValueError:
        return ""

    # Check for part in title
    _, part = extract_part_from_title(title)

    # Build notation
    if vol == int(vol):
        vol_int = int(vol)
        if part:
            return f"vol_{vol_int:02d}p{part}"  # vol_01p1
        return f"vol_{vol_int:02d}"  # vol_01
    else:
        # Decimal volume (novella)
        int_part = int(vol)
        dec_part = str(vol).split('.')[1]
        return f"vol_{int_part:02d}.{dec_part}"  # vol_01.5
```

**Workflow for metadata fetch:**

```
1. Fetch from Audnex: GET /books/{ASIN}
2. Extract: seriesPrimary.position → "1"
3. Extract: title → "Fourth Wing (Part 1 of 2) (Dramatized Adaptation)"
4. Parse title: part = 1, cleaned_title = "Fourth Wing (Dramatized Adaptation)"
5. Build: vol_01p1
6. Final folder name: The Empyrean vol_01p1 Fourth Wing (2023) (Rebecca Yarros) (Graphic Audio) {ASIN.B0CKS42KQH}
```

---

### 18. Library Examples: Legacy Notation Normalization

**Library examples to normalize:**

| Current (Legacy) | Normalized | Reason |
|------------------|------------|--------|
| `vol_01-1` | `vol_01p1` | Part, not range |
| `vol_01-2` | `vol_01p2` | Part, not range |
| `vol_01_01` | `vol_01p1` | Underscore → p |
| `vol_01-02` | `vol_01-02` | Keep as range (02 > 01) |
| `vol_01.5` | `vol_01.5` | Keep as novella |

**Real examples from library:**

```
# Current (wrong notation)
The Empyrean - vol_01-1 - Fourth Wing [2023] (Dramatized Adaptation)
The Empyrean - vol_01-2 - Fourth Wing [2024] (Dramatized Adaptation)
Pierce Brown Red Rising - vol_01_01 - Red Rising [2023] [Dramatized Adaptation]

# Normalized (correct notation)
The Empyrean vol_01p1 Fourth Wing (2023) (Rebecca Yarros) (Graphic Audio) {ASIN.B0CKS42KQH}
The Empyrean vol_01p2 Fourth Wing (2024) (Rebecca Yarros) (Graphic Audio) {ASIN.B0CQQ6ZV5J}
Pierce Brown Red Rising vol_01p1 Red Rising (2023) (Pierce Brown) (Dramatized Adaptation) {ASIN.xxx}
```

**Implementation for legacy folder parsing:**

```python
import re

def normalize_volume_notation(vol_str: str) -> str:
    """Normalize volume notation to canonical format.

    - vol_01.5 → vol_01.5 (novella - keep)
    - vol_01-03 → vol_01-03 (range - keep if end > start)
    - vol_01-1 → vol_01p1 (part - convert)
    - vol_01_01 → vol_01p1 (legacy part - convert)
    """
    # Match volume with optional suffix
    match = re.match(r'^vol_(\d+)(?:([._-])(\d+))?$', vol_str)
    if not match:
        return vol_str

    base = int(match.group(1))
    sep = match.group(2)
    suffix = match.group(3)

    if not suffix:
        return f"vol_{base:02d}"

    suffix_num = int(suffix)

    # Decimal = novella
    if sep == '.':
        return f"vol_{base:02d}.{suffix}"

    # Dash or underscore
    if sep in ('-', '_'):
        # If suffix > base, it's a range (publisher pack)
        if suffix_num > base:
            return f"vol_{base:02d}-{suffix_num:02d}"
        # Otherwise it's a part
        return f"vol_{base:02d}p{suffix_num}"

    return vol_str
```

**Parsed fields:**

```python
class VolumeInfo(TypedDict, total=False):
    volume: float              # 1, 1.5, etc
    volume_range_end: int      # only for ranges (vol_01-03 → 3)
    volume_part: int           # only for parts (vol_01p1 → 1)
```

---

## Configuration

### Config Options

Add to `config.yaml`:

```yaml
abs:
  # Existing options...

  rename:
    # Skip folders matching these patterns
    exclude_patterns:
      - "Unknown*"
      - ".hidden*"

    # Automatically fetch metadata for folders missing info
    auto_fetch_metadata: false
```

> **Note:** No `default_ripper_tag` option - ripper tags are preserved from source folders, not auto-added. Future Libation integration may provide tag lookup.

### Schema Addition

Add to `schemas/config.py`:

```python
class AbsRenameConfig(BaseModel):
    """Configuration for abs-rename command."""
    exclude_patterns: list[str] = Field(default_factory=list)
    auto_fetch_metadata: bool = False
```

---

## Testing Strategy

### Unit Tests

```python
# tests/test_abs_rename.py

class TestDiscoverCandidates:
    """Test folder discovery."""
    def test_finds_all_folders(self, tmp_path): ...
    def test_pattern_filtering(self, tmp_path): ...
    def test_excludes_files(self, tmp_path): ...

class TestParseCandidate:
    """Test folder name parsing."""
    def test_valid_mam_format(self): ...
    def test_legacy_format(self): ...
    def test_missing_asin(self): ...
    def test_malformed_name(self): ...

class TestComputeTargetName:
    """Test target name generation."""
    def test_standalone_book(self): ...
    def test_series_book(self): ...
    def test_series_with_arc(self): ...
    def test_already_correct(self): ...

class TestRenameFolder:
    """Test rename execution."""
    def test_dry_run(self, tmp_path): ...
    def test_successful_rename(self, tmp_path): ...
    def test_target_exists(self, tmp_path): ...
    def test_permission_error(self, tmp_path): ...
```

### Integration Tests

```python
class TestAbsRenameIntegration:
    """Full pipeline integration tests."""
    def test_full_rename_workflow(self, tmp_path): ...
    def test_with_metadata_fetch(self, tmp_path, mock_audnex): ...
```

### Golden Tests

Add samples to `tests/golden/`:
- `rename_inputs.json` - Various folder name formats
- `rename_expected.json` - Expected target names

---

## Real-World Test Cases (J.K. Rowling Library)

Based on actual library structure for golden test development:

### Input Tree
```
J.K. Rowling/
├── Fantastic Beasts and Where to Find Them [2017] [J.K. Rowling] [B01N4S7VVP]
│   └── Fantastic Beasts... .m4b
└── Harry Potter/
    ├── Harry Potter vol_01 and the Philosopher's Stone (2024) (J.K. Rowling) (Stephen Fry) {ASIN.B0D1CSXB3Z}
    ├── Harry Potter vol_01 and the Sorcerer's Stone (2015) (J.K. Rowling) (Jim Dale) {ASIN.B017V4IM1G}
    ├── Harry Potter vol_01 and the Sorcerer's Stone (2025) (J.K. Rowling) (Full-Cast) (Dolby Atmos) {ASIN.B0F14RPXHR} [H2OKing]
    ├── Harry Potter vol_01 and the Sorcerer's Stone (2025) (J.K. Rowling) (Full-Cast) {ASIN.B0F14RPXHR} [H2OKing]
    └── ... (more volumes)
```

### Expected Behavior

| Input | Action | Output/Reason |
|-------|--------|---------------|
| `Fantastic Beasts... [2017] [J.K. Rowling] [B01N4S7VVP]` | **RENAME** | `Fantastic Beasts and Where to Find Them (2017) (J.K. Rowling) {ASIN.B01N4S7VVP}` |
| `Harry Potter vol_01... (Stephen Fry) {ASIN.B0D1CSXB3Z}` | **UP_TO_DATE** | Already matches schema |
| `Harry Potter vol_01... (Jim Dale) {ASIN.B017V4IM1G}` | **UP_TO_DATE** | Already matches schema |
| `Harry Potter vol_01... (Full-Cast) (Dolby Atmos) {ASIN.B0F14RPXHR}` | **DUPLICATE_ASIN** | Same ASIN as next entry |
| `Harry Potter vol_01... (Full-Cast) {ASIN.B0F14RPXHR}` | **DUPLICATE_ASIN** | Same ASIN as prev entry |
| `J.K. Rowling/` | **IGNORED** | Author folder, not a leaf |
| `Harry Potter/` | **IGNORED** | Series folder, not a leaf |

### Test Case: Legacy Bracket Format

**Input:**
```
Fantastic Beasts and Where to Find Them [2017] [J.K. Rowling] [B01N4S7VVP]
```

**Parsed:**
```python
ParsedFolderName(
    title="Fantastic Beasts and Where to Find Them",
    year="2017",
    author="J.K. Rowling",
    asin="B01N4S7VVP",
    series=None,
    volume=None,
    ripper_tag=None,
    edition_flags=[],
)
```

**Target:**
```
Fantastic Beasts and Where to Find Them (2017) (J.K. Rowling) {ASIN.B01N4S7VVP}
```

### Test Case: Edition Flags Normalization

**Input:**
```
Harry Potter vol_01 and the Sorcerer's Stone (2025) (J.K. Rowling) (Full-Cast) (Dolby Atmos) {ASIN.B0F14RPXHR} [H2OKing]
```

**Parsed:**
```python
ParsedFolderName(
    title="and the Sorcerer's Stone",
    series="Harry Potter",
    volume="01",
    year="2025",
    author="J.K. Rowling",
    asin="B0F14RPXHR",
    ripper_tag="H2OKing",
    edition_flags=["Full-Cast", "Dolby Atmos"],
)
```

**Target (normalized):**
```
Harry Potter vol_01 and the Sorcerer's Stone (2025) (J.K. Rowling) (Full-Cast, Dolby Atmos) {ASIN.B0F14RPXHR} [H2OKing]
```

### Test Case: Duplicate ASIN Detection

**Inputs (same ASIN B0F14RPXHR):**
```
Harry Potter vol_01... (Full-Cast) (Dolby Atmos) {ASIN.B0F14RPXHR} [H2OKing]
Harry Potter vol_01... (Full-Cast) {ASIN.B0F14RPXHR} [H2OKing]
```

**Expected:**
- Both marked as `status="duplicate_asin"`
- Both skipped in rename
- Report shows conflict:
  ```
  ⚠️  Duplicate ASIN B0F14RPXHR in 2 folders - skipping both
  ```

### Test Case: File Renaming

**Input folder:**
```
Harry Potter vol_01... {ASIN.B017V4IM1G}/
├── Harry Potter vol_01... {ASIN.B017V4IM1G}.m4b
├── Harry Potter vol_01... {ASIN.B017V4IM1G}.cue
├── cover.jpg
└── metadata.json
```

**After rename:**
```
Harry Potter vol_01 and the Sorcerer's Stone (2015) (J.K. Rowling) (Jim Dale) {ASIN.B017V4IM1G}/
├── Harry Potter vol_01 and the Sorcerer's Stone (2015) (J.K. Rowling) (Jim Dale) {ASIN.B017V4IM1G}.m4b
├── Harry Potter vol_01 and the Sorcerer's Stone (2015) (J.K. Rowling) (Jim Dale) {ASIN.B017V4IM1G}.cue
├── cover.jpg          ← UNCHANGED
└── metadata.json      ← UNCHANGED
```

---

## CLI Implementation

### Add to cli.py

```python
def build_parser() -> argparse.ArgumentParser:
    # ... existing code ...

    # abs-rename command
    abs_rename = subparsers.add_parser(
        "abs-rename",
        help="Rename audiobook folders in ABS library to MAM naming schema",
    )
    abs_rename.add_argument(
        "--source",
        type=Path,
        help="Source directory (default: ABS library from audiobookshelf.path_map)",
    )
    abs_rename.add_argument(
        "--pattern",
        default="*",
        help="Glob pattern to filter folders (default: *)",
    )
    abs_rename.add_argument(
        "--fetch-metadata",
        action="store_true",
        help="Fetch missing metadata from Audnex API",
    )
    abs_rename.add_argument(
        "--interactive",
        action="store_true",
        help="Prompt for confirmation on each rename",
    )
    abs_rename.add_argument(
        "--report",
        type=Path,
        help="Output JSON report of changes",
    )
    abs_rename.set_defaults(func=cmd_abs_rename)


def cmd_abs_rename(args: argparse.Namespace) -> int:
    """Rename staged audiobook folders to MAM schema."""
    # Implementation
    ...
```

---

## Output Examples

### Dry Run Output

```
$ mamfast --dry-run abs-rename

ABS Rename - Dry Run Mode
========================

Scanning: /mnt/user/data/audio/audiobooks
Found: 15 folders

[1/15] Project Hail Mary (Andy Weir) {ASIN.B08G9PRS1K}
  → Project Hail Mary (2021) (Andy Weir) {ASIN.B08G9PRS1K}
  Status: WOULD RENAME (missing year)

[2/15] Stormlight Archive vol_01 The Way of Kings (2010) (Brandon Sanderson) {ASIN.B003ZWFO7E} [H2OKing]
  Status: UP TO DATE

[3/15] Unknown-Book-12345
  Status: SKIPPED (no ASIN found)

...

Summary
-------
Would rename: 8
Up to date: 5
Skipped: 2
Errors: 0
```

### JSON Report

```json
{
  "timestamp": "2025-12-07T10:30:00Z",
  "source_dir": "/mnt/user/data/audio/audiobooks",
  "dry_run": true,
  "results": [
    {
      "source": "Project Hail Mary (Andy Weir) {ASIN.B08G9PRS1K}",
      "target": "Project Hail Mary (2021) (Andy Weir) {ASIN.B08G9PRS1K}",
      "status": "dry_run",
      "changes": ["added_year"]
    }
  ],
  "summary": {
    "total": 15,
    "renamed": 0,
    "would_rename": 8,
    "up_to_date": 5,
    "skipped": 2,
    "errors": 0
  }
}
```

---

## Implementation Checklist

### Core Module (`src/mamfast/abs/rename.py`)
- [ ] Create `RenameCandidate` dataclass with `edition_flags` field
- [ ] Create `RenameResult` dataclass with `files_renamed` field
- [ ] Define `RenameStatus` Literal type with all statuses
- [ ] Implement `discover_rename_candidates()` - recursive leaf discovery
- [ ] Implement `parse_candidate()` - handle legacy bracket format
- [ ] Implement `detect_edition_flags()` - extract Full-Cast, Dolby Atmos, etc.
- [ ] Implement `detect_duplicate_asins()` - mark conflicts
- [ ] Implement `resolve_metadata()` with Audnex integration
- [ ] Implement `compute_target_name()` with edition flag normalization
- [ ] Implement `rename_folder()` with file renaming (skip cover.jpg, metadata.json)

### CLI (`cli.py`)
- [ ] Add `abs-rename` subcommand with all options
- [ ] Implement `cmd_abs_rename()` handler
- [ ] Add conflict reporting in dry-run output
- [ ] Add JSON report generation

### Parser Updates (`utils/naming.py`)
- [ ] Update `ParsedFolderName` to handle legacy `[bracket]` format
- [ ] Add `edition_flags` field to `ParsedFolderName`
- [ ] Add `parse_legacy_format()` helper
- [ ] Add `normalize_edition_flags()` helper

### Config
- [ ] Add `AbsRenameConfig` schema to `schemas/config.py`
- [ ] Update `config.yaml.example` with rename options

### Tests
- [ ] Unit tests for legacy format parsing
- [ ] Unit tests for edition flag detection
- [ ] Unit tests for duplicate ASIN detection
- [ ] Unit tests for file renaming (skip cover.jpg, metadata.json)
- [ ] Golden tests from J.K. Rowling library examples
- [ ] Integration tests for full pipeline

### Documentation
- [ ] Update `abs/__init__.py` exports
- [ ] Update CLI help text

---

## Future Enhancements

### Future: Libation Integration for Ripper Tags

Many audiobooks may be missing ripper tags. A future enhancement will:

1. **Query Libation database** for the ASIN to find previous rips
2. **Extract ripper tag** from Libation's stored metadata or filename history
3. **Optionally apply** the discovered ripper tag during rename

This would be enabled via a `--lookup-ripper-tags` flag:
```bash
mamfast abs-rename --lookup-ripper-tags
```

### Other Future Enhancements

1. **Batch undo**: Save rename history for reverting changes
2. **ABS library sync**: Update ABS library after renames (via API)
3. **Watch mode**: Auto-rename new folders as they appear
4. **`--allow-duplicate-asins`**: Enable renaming with explicit edition differentiation
