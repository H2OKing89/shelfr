# Audiobookshelf Import Plan

> **Document Version:** 3.3.1 | **Last Updated:** 2025-12-03 | **Status:** Ready to Implement ✅

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture Philosophy](#architecture-philosophy)
3. [Audiobookshelf API Integration](#audiobookshelf-api-integration)
4. [Goals & Requirements](#goals--requirements)
5. [Library Index (SQLite)](#library-index-sqlite)
6. [Docker Path Mapping](#docker-path-mapping)
7. [Smart ASIN Extraction](#smart-asin-extraction--internal-helper-for-abs-index) *(internal helper)*
8. [Audnex Author API](#audnex-author-api--not-in-v31--future-enhancement-only) *(future enhancement)*
9. [Naming Schema](#naming-schema)
10. [Directory Structure](#directory-structure)
11. [Processing Pipeline](#processing-pipeline)
12. [File Operations](#file-operations)
13. [Configuration](#configuration)
14. [CLI Commands](#cli-commands)
15. [Edge Cases](#edge-cases)
16. [Reusable Codebase Components](#reusable-codebase-components) *(existing libraries & modules)*
17. [Implementation Phases](#implementation-phases)
18. [Testing Strategy](#testing-strategy)
19. [Key Architectural Decisions](#key-architectural-decisions)
20. [Implementation Notes](#implementation-notes) *(v3.1 simplifications, pre-flight checks)*
21. [Smart Author Folder Resolution](#smart-author-folder-resolution--not-in-v31--future-enhancement) *(future enhancement)*

---

## Overview

### The Big Idea: Let ABS Do the Heavy Lifting

Instead of parsing the filesystem ourselves, **use Audiobookshelf's API as the source of truth**.

ABS already has:
- Libraries with root paths
- Library items (books) with **normalized authors, series, and metadata**
- Library files with `fullPath` pointing at real folders/files
- All already "resolved" in ABS's database

We get a **pre-built, strongly-typed library index for free**.

### What We Were Going To Do (Old Approach)

```
❌ Walk /mnt/user/data/audio/audiobooks
❌ Parse author/series/volume from folder names
❌ Extract ASIN from wildly different formats
❌ Fuzzy-match authors ourselves
❌ Build our own index (JSON/SQLite) on top
```

### What We'll Do Instead (New Approach)

```
✅ One API call to list libraries
✅ One API call per library to list items
✅ For each item: author, series, metadata, and disk path
✅ All already "resolved" by ABS
✅ Just translate container paths → host paths
```

### High-Level Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      PHASE 0: ABS INDEX (DO THIS FIRST)                     │
│                                                                             │
│   mamfast abs-init                                                          │
│       ↓                                                                     │
│   Validate ABS connection → List libraries → Generate config template      │
│       ↓                                                                     │
│   mamfast abs-index                                                         │
│       ↓                                                                     │
│   Fetch from ABS API → Map paths → Build SQLite index                      │
│       ↓                                                                     │
│   mamfast abs-report-authors                                                │
│       ↓                                                                     │
│   Detect author variants → Generate normalization report                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      PHASE 1+: IMPORT (NOW SIMPLE)                          │
│                                                                             │
│   mamfast abs-import                                                        │
│       ↓                                                                     │
│   Check ASIN in SQLite → If exists: skip/warn/overwrite (duplicate policy) │
│                        → If new: use (Author) from staging folder name     │
│       ↓                                                                     │
│   Atomic move → Trigger ABS scan → Re-index if needed                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Integrated MAM Workflow

```
Libation → Discovery → Staging → Hardlink to Seed → Torrent → qBittorrent → ABS Import
                                                                              ↑
                                                                    (this feature)
```

**Key points:**
- **ABS API as source of truth for indexing**: Duplicate detection, author reports
- **MAM folder names as source of truth for new imports**: Author/series from staging folder
- **Docker path mapping**: Translate container paths ↔ host paths
- **SQLite index**: Fast ASIN lookups, author reports, duplicate detection
- **Atomic move**: Instant, preserves hardlinks to seed folder

---

## Architecture Philosophy

### Why ABS API is Smarter Than Filesystem Parsing

| Filesystem Approach | ABS API Approach |
|---------------------|------------------|
| Walk thousands of folders | One API call per library |
| Parse folder names with regex | Metadata already structured |
| Handle 4+ naming eras | ABS normalizes for us |
| Fuzzy match authors ourselves | Author already resolved per book |
| Build index from scratch | Get pre-built index for free |

### The Two-Problem Split

| Concern | Solution | When |
|---------|----------|------|
| **Index existing library** | ABS API + SQLite | Phase 0 (one-time) |
| **Clean future imports** | SQLite lookups | Phase 1+ (ongoing) |

### Why Index First?

Without an index, every import must:
- Scan the entire library for duplicates
- Guess which author folder to use
- Handle naming era differences on the fly
- Risk creating new variations of existing authors

With an index (from ABS API):
- ASIN lookup is O(1) via SQLite index
- Canonical author already known (ABS resolved it)
- Import code is simple: check DB → move → ABS rescans

### JSON vs SQLite

| Aspect | JSON | SQLite |
|--------|------|--------|
| Simplicity | ✅ Easy to inspect (`less index.json`) | Needs helper commands |
| Querying | ❌ O(n) scans | ✅ Proper indexes |
| Updates | ❌ Full file rewrite | ✅ Incremental |
| Concurrency | ❌ Painful | ✅ ACID |
| Version control | ✅ Git-friendly diffs | ❌ Binary |

**Decision: SQLite as primary (`data/abs_index.db`), JSON as export/report format**

```bash
mamfast abs-init                        # validate ABS connection, list libraries
mamfast abs-index                       # build/update abs_index.db from ABS API
mamfast abs-report-authors              # generate author variants report
mamfast export-library > library.json   # snapshot for backup/testing
mamfast abs-import --staging /path/...  # uses DB to dedupe & place books
```

---

## Audiobookshelf API Integration

### Why Use the ABS API?

Audiobookshelf already does 80% of the work:

| What ABS Provides | API Endpoint |
|-------------------|--------------|
| Libraries (IDs, names, root paths) | `GET /api/libraries` |
| Library items (books) with metadata | `GET /api/libraries/{id}/items` |
| Normalized authors & series per book | `libraryItem.media.metadata` |
| File paths inside container | `libraryFiles[].fullPath` |

### Key API Endpoints

```python
# Base URL: https://audiobookshelf.kingpaging.com/api

# 1. List all libraries
GET /api/libraries
# Returns: { "libraries": [{ "id": "lib_xxx", "name": "Audiobooks", "folders": [...] }] }

# 2. Get items in a library
GET /api/libraries/{id}/items?mediaType=book
# Returns: { "results": [{ "id": "li_xxx", "media": {...}, "libraryFiles": [...] }] }

# 3. Get filesystem paths (for discovering roots)
GET /api/filesystem
# Returns available filesystem paths inside the container
```

### ABS Response Structure

```python
from dataclasses import dataclass

@dataclass
class AbsLibraryItem:
    """Key fields from ABS library item response."""
    id: str                      # "li_xxx" - unique item ID
    library_id: str              # "lib_xxx" - parent library
    path: str                    # Container path to book folder

    # From media.metadata
    title: str
    subtitle: str | None
    authors: list[dict]          # [{"id": "xxx", "name": "Brandon Sanderson"}]
    series: list[dict]           # [{"id": "xxx", "name": "Mistborn", "sequence": "1"}]
    asin: str | None             # If ABS has it stored

    # From libraryFiles[]
    library_files: list[dict]    # [{"fullPath": "/audiobooks/...", "name": "book.m4b"}]

@dataclass
class AbsBookRecord:
    """Processed record for our index.

    NOTE: Multi-author handling in v3.1:
    - `author_display` stores the PRIMARY author only (first in ABS list)
    - This is a known limitation; 99% of audiobooks have one primary author
    - Future: could add `additional_authors` field or junction table
    """
    library_id: str
    library_item_id: str
    asin: str | None
    title: str
    subtitle: str | None
    author_display: str          # "Brandon Sanderson" (primary author from ABS)
    author_folder: str           # Folder name on disk
    series_name: str | None
    series_position: float | None  # Can be 1.5 for novellas
    folder_path_host: str        # After path mapping
    main_audio_file_host: str | None
    mtime_ms: int | None         # For change detection
    size_bytes: int | None
```

### ABS Client Module

```python
# src/mamfast/abs_client.py

import httpx
from dataclasses import dataclass

@dataclass
class AbsConfig:
    base_url: str
    api_token: str
    docker_mode: bool
    libraries: list[dict]  # id, name, mamfast_managed, path_map

class AbsClient:
    """Audiobookshelf API client with retry support."""

    def __init__(self, config: AbsConfig, max_retries: int = 3):
        self.config = config
        # httpx retry transport for network resilience
        transport = httpx.HTTPTransport(retries=max_retries)
        self._client = httpx.Client(
            base_url=config.base_url.rstrip("/") + "/api",
            headers={"Authorization": f"Bearer {config.api_token}"},
            timeout=30.0,
            transport=transport,
        )

    def get_libraries(self) -> list[dict]:
        """Fetch all libraries."""
        resp = self._client.get("/libraries")
        resp.raise_for_status()
        return resp.json()["libraries"]

    def get_library_items(self, library_id: str) -> list[dict]:
        """Fetch all book items in a library.

        NOTE: Uses limit=0 which currently returns all items in ABS.
        If ABS changes this behavior, implement pagination via page/limit params.
        """
        resp = self._client.get(
            f"/libraries/{library_id}/items",
            params={"mediaType": "book", "limit": 0}  # 0 = no limit
        )
        resp.raise_for_status()
        return resp.json()["results"]

    def get_item_details(self, item_id: str) -> dict:
        """Fetch detailed info for a single item."""
        resp = self._client.get(f"/items/{item_id}")
        resp.raise_for_status()
        return resp.json()

    def trigger_library_scan(self, library_id: str, force: bool = False) -> None:
        """Trigger ABS to scan a library for new/changed items.

        Args:
            library_id: ABS library ID
            force: If True, re-scan all files. If False, only scan changed.
        """
        resp = self._client.post(
            f"/libraries/{library_id}/scan",
            params={"force": "1" if force else "0"},
        )
        resp.raise_for_status()
```

### API Resilience

**When ABS is unreachable during import:**

| Phase | ABS Unavailable Behavior |
|-------|--------------------------|
| `abs-index` | Fail with clear error |
| `abs-import` (dedupe check) | Skip dedupe, proceed with import (warn user) |
| `abs-import` (scan trigger) | Log warning, don't fail import |

This ensures imports aren't blocked by transient ABS issues—the scan will pick up files on ABS's next scheduled scan anyway.

```python
def trigger_scan_safe(client: AbsClient, library_id: str) -> bool:
    """Trigger scan, return False on failure instead of raising."""
    try:
        client.trigger_library_scan(library_id)
        return True
    except httpx.HTTPError as e:
        logger.warning(f"Failed to trigger ABS scan: {e}")
        return False
```

---

## Docker Path Mapping

### The Problem

ABS runs in Docker and sees paths like `/audiobooks/Author/Series/Book/`.
MAMFast runs on the host and sees `/mnt/user/data/audio/audiobooks/Author/Series/Book/`.

We need to translate between them.

### Configuration

```yaml
# config.yaml
abs:
  enabled: true
  base_url: "https://audiobookshelf.kingpaging.com"
  api_token: "${ABS_API_TOKEN}"   # From .env
  docker_mode: true               # Paths returned are container paths

  libraries:
    - id: "lib_c1u6t4p45c35rf0nzd"
      name: "Audiobooks"
      mamfast_managed: true       # Only index/import to managed libraries
      path_map:
        - container: "/audiobooks"
          host: "/mnt/user/data/audio/audiobooks"
```

### Path Mapping Functions

```python
# src/mamfast/utils/abs_paths.py

from pathlib import Path

def abs_path_to_host(abs_path: str, path_maps: list[dict]) -> Path:
    """
    Convert ABS container path to host path.

    Uses longest-prefix matching for nested mount scenarios.
    See Implementation Notes for algorithm details.

    Example:
        abs_path: "/audiobooks/Brandon Sanderson/Mistborn/..."
        returns:  Path("/mnt/user/data/audio/audiobooks/Brandon Sanderson/Mistborn/...")
    """
    if not path_maps:
        return Path(abs_path)

    # Sort by container prefix length (longest first) to handle nested mounts
    sorted_maps = sorted(path_maps, key=lambda m: len(m["container"]), reverse=True)

    for mapping in sorted_maps:
        container_prefix = mapping["container"]
        if abs_path.startswith(container_prefix):
            # Replace container prefix with host prefix
            return Path(
                abs_path.replace(container_prefix, mapping["host"], 1)
            )

    # Fallback: assume path is already host-visible
    return Path(abs_path)


def host_path_to_abs(host_path: Path, path_maps: list[dict]) -> str:
    """
    Convert host path to ABS container path.
    Used when telling ABS to scan a specific folder.
    """
    if not path_maps:
        return str(host_path)

    host_str = str(host_path)

    # Sort by host prefix length (longest first)
    sorted_maps = sorted(path_maps, key=lambda m: len(m["host"]), reverse=True)

    for mapping in sorted_maps:
        host_prefix = mapping["host"]
        if host_str.startswith(host_prefix):
            return host_str.replace(host_prefix, mapping["container"], 1)

    return host_str
```

### Same-Container Mode

If MAMFast runs inside the same container as ABS (or shares the same mounts):

```yaml
abs:
  docker_mode: false  # Paths are identical, no mapping needed
  libraries:
    - id: "lib_xxx"
      name: "Audiobooks"
      mamfast_managed: true
      # No path_map needed
```

---

## Goals & Requirements

### Primary Goals

1. **Use ABS API as source of truth** for library indexing
2. **Handle Docker path mapping** seamlessly
3. **Detect duplicates** via fast SQLite ASIN lookups
4. **Preserve quality** - hardlink or copy files without re-encoding
5. **Support author normalization** via ABS metadata

### Requirements

| Requirement | Priority | Notes |
|-------------|----------|-------|
| **ABS API integration** | **Must** | Source of truth for library state |
| **Docker path mapping** | **Must** | Container ↔ host path translation |
| **SQLite library index** | **Must** | Fast lookups, author reports |
| Atomic move (same filesystem) | **Must** | Instant, preserves hardlinks |
| Folder name parsing | **Must** | Extract author, series from MAM format |
| Duplicate detection (ASIN) | **Must** | Avoid reimporting existing books |
| Standalone book handling | **Must** | No series = Author/Title structure |
| Author normalization & merge | **Must** | Clean up existing library drift |
| Dry-run mode | **Should** | Preview changes before execution |
| Batch processing | **Should** | Process all staged books at once |
| JSON export for reports | **Should** | Snapshots for testing/backup |
| Auto-import after MAM workflow | **Could** | Trigger automatically |

---

## Library Index (SQLite)

The library index (`data/abs_index.db`) is populated from the **ABS API** and provides:
- Fast ASIN → path lookups for duplicate detection
- Author variant reporting
- Foundation for future tools (Listenarr integration, etc.)

### Database Schema

```sql
-- Books: core table populated from ABS API
CREATE TABLE books (
    id                    INTEGER PRIMARY KEY,
    library_item_id       TEXT UNIQUE NOT NULL,   -- ABS "li_xxx" ID
    library_id            TEXT NOT NULL,          -- ABS "lib_xxx" ID
    asin                  TEXT,                   -- nullable for legacy
    title                 TEXT NOT NULL,
    subtitle              TEXT,
    author_display        TEXT NOT NULL,          -- "Brandon Sanderson" from ABS
    author_folder         TEXT NOT NULL,          -- Folder name on disk
    series_name           TEXT,
    series_position       REAL,                   -- Can be 1.5 for novellas
    folder_path_host      TEXT NOT NULL,          -- Host path after mapping
    main_audio_file_host  TEXT,                   -- Primary .m4b path
    mtime_ms              INTEGER,                -- For change detection
    size_bytes            INTEGER,
    indexed_at            TEXT NOT NULL
);

CREATE UNIQUE INDEX idx_books_asin ON books(asin) WHERE asin IS NOT NULL;
CREATE INDEX idx_books_author_folder ON books(author_folder);
CREATE INDEX idx_books_library ON books(library_id);
CREATE INDEX idx_books_series ON books(series_name);

-- Author variants: for reporting, not enforcement
-- (ABS is the authority, we just report discrepancies)
CREATE TABLE author_variants (
    id              INTEGER PRIMARY KEY,
    author_display  TEXT NOT NULL,        -- What ABS says: "Brandon Sanderson"
    folder_name     TEXT NOT NULL,        -- What's on disk: "brandon sanderson"
    book_count      INTEGER NOT NULL,
    first_seen      TEXT NOT NULL
);

CREATE INDEX idx_variants_display ON author_variants(author_display);
CREATE INDEX idx_variants_folder ON author_variants(folder_name);

-- Import log: track what MAMFast imported
CREATE TABLE import_log (
    id              INTEGER PRIMARY KEY,
    asin            TEXT NOT NULL,
    source_path     TEXT NOT NULL,        -- Where it came from (staging)
    target_path     TEXT NOT NULL,        -- Where it went (library)
    library_id      TEXT NOT NULL,
    imported_at     TEXT NOT NULL,
    status          TEXT NOT NULL         -- "success", "skipped", "failed", "duplicate"
);

CREATE INDEX idx_import_asin ON import_log(asin);

-- Index metadata: track sync state
CREATE TABLE index_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- Example entries:
-- ('last_full_sync', '2025-12-03T10:30:00Z')
-- ('abs_version', '2.17.5')
-- ('schema_version', '1')
```

### Index Freshness

The `index_meta` table enables stale-index warnings:

```bash
$ mamfast abs-import

⚠️  Index is 3 days old (last sync: 2025-11-30T10:30:00Z)
    Consider running: mamfast abs-index --refresh

Importing 2 audiobooks...
```

### Simplified Schema Rationale

The old plan had complex `authors`, `series`, `author_conflicts`, `author_aliases`, `merge_history` tables.

With ABS as the source of truth:
- **We don't need to manage authors** - ABS already has them normalized
- **We don't need merge operations** - Just report variants, let user fix in ABS or on disk
- **We just need fast lookups** - ASIN → "does this exist?"

### Python Models

```python
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

class ImportStatus(str, Enum):
    SUCCESS = "success"         # Import completed
    SKIPPED = "skipped"         # Duplicate by ASIN
    FAILED = "failed"           # Error during move
    DUPLICATE = "duplicate"     # Already exists at target path

@dataclass
class ImportResult:
    """Result of a single import operation."""
    status: ImportStatus
    target: Path | None = None
    error: str | None = None

@dataclass
class SyncResult:
    """Result of sync_from_abs() operation."""
    books_indexed: int
    with_asin: int
    without_asin: int
    author_variants_found: int

# NOTE: AbsBookRecord is defined in the ABS API section above.
# It includes: library_item_id, library_id, asin, title, subtitle,
# author_display (primary only), author_folder, series_name, series_position,
# folder_path_host, main_audio_file_host, mtime_ms, size_bytes

@dataclass
class AuthorVariant:
    """Detected author name variant (for reporting only)."""
    author_display: str   # What ABS metadata says
    folder_name: str      # What's on disk
    book_count: int
```

### Index Operations (v3.1 Scope)

```python
class AbsIndex:
    """SQLite index populated from ABS API.

    v3.1 Scope: Read-only operations + import logging.
    Author merge/alias operations are NOT in v3.1.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    # === Lookup operations (fast) ===

    def get_book_by_asin(self, asin: str) -> AbsBookRecord | None:
        """O(1) lookup via index."""
        ...

    def asin_exists(self, asin: str) -> bool:
        """Quick duplicate check."""
        ...

    def get_books_by_author_folder(self, folder_name: str) -> list[AbsBookRecord]:
        """Find all books in an author folder."""
        ...

    # === Reporting ===

    def get_author_variants(self) -> list[AuthorVariant]:
        """
        Find cases where author_display != author_folder.
        Example: author_display="J.R. Mathews", folder="J R Mathews"
        """
        ...

    def get_duplicate_asins(self) -> list[tuple[str, list[str]]]:
        """Find ASINs that appear in multiple locations."""
        ...

    def get_stats(self) -> dict:
        """Return index statistics."""
        ...

    # === Sync from ABS API ===

    def sync_from_abs(self, abs_client: AbsClient, config: dict) -> SyncResult:
        """
        Fetch all items from ABS API and update index.

        1. For each managed library:
           - GET /api/libraries/{id}/items
        2. For each item:
           - Extract ASIN from metadata or folder name
           - Map container path → host path
        3. Upsert into SQLite
        4. Rebuild author_variants table (fully rebuilt each sync, not incremental)
        5. Return stats
        """
        ...

    # === Import support ===

    def check_duplicate(self, asin: str) -> tuple[bool, str | None]:
        """
        Check if ASIN exists.
        Returns: (is_duplicate, existing_path_if_duplicate)
        """
        existing = self.get_book_by_asin(asin)
        if existing:
            return True, str(existing.folder_path_host)
        return False, None

    def log_import(self, asin: str, source: str, target: str, status: str) -> None:
        """Record an import attempt."""
        ...

    # === Export ===

    def export_json(self) -> dict:
        """Export full index as JSON for inspection/backup."""
        ...
```

---

## Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         MAM WORKFLOW (ALREADY COMPLETE)                     │
│                                                                             │
│  Libation → Discovery → Staging → Hardlink to Seed → Torrent → qBittorrent │
│                            │                │                               │
│                            ▼                ▼                               │
│                     /staging/Book/    /seedvault/Book/                     │
│                     └── book.m4b ──────└── book.m4b (hardlinked)           │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │ ABS Import (this feature)
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         STAGING DIRECTORY (INPUT)                           │
│                           /staging/{Book Folder}/                           │
│                                                                             │
│  Files ready for import (already processed by MAM workflow):               │
│  ├── Series vol_01 Arc (Year) (Author) {ASIN.xxx} [Tag]/                   │
│  │   ├── Series vol_01 Arc (Year) (Author) {ASIN.xxx}.m4b                  │
│  │   ├── cover.jpg                                                          │
│  │   └── *.cue (optional)                                                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           METADATA EXTRACTION                               │
│                                                                             │
│  1. Parse folder name for ASIN, series, volume, author                     │
│  2. Optionally enrich from Audnex if needed                                │
│  3. Determine Author folder and Series folder names                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     SMART DUPLICATE DETECTION                               │
│                                                                             │
│  Library ASIN Index (handles ALL naming formats):                          │
│  - NEW: {ASIN.B0xxx}     → current MAMFast format                         │
│  - OLD: [ASIN.B0xxx]     → older bracket format                           │
│  - OLD: [B0xxxxxxxx]     → bare ASIN in brackets                          │
│  - FALLBACK: B0xxxxxxxx  → bare ASIN anywhere                             │
│                                                                             │
│  Actions: skip (default), warn, overwrite                                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         ATOMIC MOVE OPERATION                               │
│                                                                             │
│  1. Create Author directory (if needed)                                    │
│  2. Create Series directory (if needed)                                    │
│  3. Atomic move (rename) entire book folder:                               │
│     /staging/Book/ → /library/Author/Series/Book/                          │
│                                                                             │
│  ✓ Instant (no data copy)                                                  │
│  ✓ Preserves hardlinks to seed folder                                      │
│  ✓ Torrents keep seeding from new location                                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AUDIOBOOKSHELF LIBRARY                              │
│                    /mnt/user/data/audio/audiobooks/                         │
│                                                                             │
│  Organized 3-level structure:                                              │
│  └── Author Name/                                                          │
│      └── Series Name/                                                      │
│          └── Series vol_01 Arc (Year) (Author) {ASIN.xxx} [Tag]/          │
│              ├── Series vol_01 Arc (Year) (Author) {ASIN.xxx}.m4b         │
│              ├── cover.jpg                                                 │
│              └── *.cue                                                     │
│                    │                                                       │
│                    └── Still hardlinked to /seedvault/ (torrent seeding)  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Input Sources

### Source: MAM Staging Directory

Files in staging have **already been processed** by the MAM workflow:
- Metadata fetched from Audnex
- Names cleaned and normalized
- Hardlinked to seed folder
- Torrent created and uploaded

The folder structure is already MAM-compliant:

```
/staging/
├── Sword Art Online vol_16 Alicization Exploding (2025) (Reki Kawahara) {ASIN.B0DK9TS6D9} [H2OKing]/
│   ├── Sword Art Online vol_16 Alicization Exploding (2025) (Reki Kawahara) {ASIN.B0DK9TS6D9}.m4b
│   ├── Sword Art Online vol_16 Alicization Exploding (2025) (Reki Kawahara) {ASIN.B0DK9TS6D9}.cue
│   └── cover.jpg
├── Mushoku Tensei - Jobless Reincarnation vol_27 Recollections (2024) (Rifujin na Magonote) {ASIN.B0DP3CQC6N} [H2OKing]/
│   └── ...
└── Project Hail Mary (2021) (Andy Weir) {ASIN.B08G9PRS1K} [H2OKing]/
    └── ...
```

### Parsing Folder Names

Since folders are already named consistently, we parse the components:

```python
# Folder name pattern (from MAM workflow)
FOLDER_PATTERN = re.compile(
    r"^(?P<series_or_title>.+?)"           # Series name or standalone title
    r"(?:\s+vol_(?P<vol>\d+))?"            # Optional volume number
    r"(?:\s+(?P<arc>[^({\[]+?))?"          # Optional arc/subtitle
    r"\s+\((?P<year>\d{4})\)"              # Year
    r"\s+\((?P<author>[^)]+)\)"            # Author
    r"\s+\{ASIN\.(?P<asin>[A-Z0-9]+)\}"    # ASIN
    r"(?:\s+\[(?P<tag>[^\]]+)\])?$"        # Optional ripper tag
)

def parse_folder_name(folder: str) -> dict:
    """Extract metadata from MAM-formatted folder name."""
    match = FOLDER_PATTERN.match(folder)
    if not match:
        raise ValueError(f"Folder doesn't match expected pattern: {folder}")

    return {
        "series": match.group("series_or_title"),
        "volume": int(match.group("vol")) if match.group("vol") else None,
        "arc": match.group("arc").strip() if match.group("arc") else None,
        "year": match.group("year"),
        "author": match.group("author"),
        "asin": match.group("asin"),
        "tag": match.group("tag"),
        "is_standalone": match.group("vol") is None,
    }
```

### Detecting Series vs Standalone

| Folder Name | `vol_XX` Present? | Type |
|-------------|-------------------|------|
| `Series vol_01 ... {ASIN}` | Yes | Series book |
| `Title (Year) (Author) {ASIN}` | No | Standalone book |

---

## Smart ASIN Extraction — *Internal Helper for abs-index*

> 💡 **Internal utility.** This section documents ASIN extraction patterns used internally by `abs-index` when processing existing library entries. In v3.x, ABS API provides ASINs directly for newly indexed items, so this is primarily for historical library entries.

### The Problem: Legacy Naming Formats

The library contains books imported over time with different naming conventions:

| Era | Format | Example |
|-----|--------|---------|
| **Current** | `{ASIN.B0xxx}` | `Sword Art Online vol_16 (2025) (Reki Kawahara) {ASIN.B0DK9TS6D9}` |
| **Old** | `[ASIN.B0xxx]` | `Mushoku Tensei - vol_03 [2024] [Author] [ASIN.B0CNTY7LVH]` |
| **Older** | `[B0xxxxxxxx]` | `Azarinth Healer - vol_04 [Rhaegar] [B0DMQ2WP9F]` |
| **Legacy** | No ASIN | `Project Hail Mary.m4b` |

### Multi-Format ASIN Extraction

Use a cascade of patterns (most specific → least specific):

```python
# In src/mamfast/utils/asin.py

import re

# Pattern cascade for ASIN extraction
ASIN_PATTERNS = [
    # NEW: {ASIN.B0xxx} - current MAMFast format
    re.compile(r"\{ASIN\.([A-Z0-9]{10})\}"),

    # OLD: [ASIN.B0xxx] - older bracket format
    re.compile(r"\[ASIN\.([A-Z0-9]{10})\]"),

    # OLD: [B0xxxxxxxx] - bare ASIN in brackets (no prefix)
    # NOTE: B0 is literal "B0", not character class [B0]
    re.compile(r"\[(B0[A-Z0-9]{8})\]"),

    # FALLBACK: bare ASIN anywhere with word boundaries
    re.compile(r"(?<![A-Z0-9])(B0[A-Z0-9]{8})(?![A-Z0-9])"),
]


def extract_asin(text: str) -> str | None:
    """Extract ASIN from any naming format.

    Tries patterns in order of specificity. Returns first match.
    """
    if not text:
        return None
    for pattern in ASIN_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None
```

### Library ASIN Index

Build a one-time index of all ASINs in the library:

```python
# In src/mamfast/abs_import.py

from dataclasses import dataclass
from pathlib import Path

from mamfast.utils.asin import extract_asin
```

---

## Audnex Author API

> **⚠️ NOT IN v3.1 — Future Enhancement Only**
>
> This section documents the Audnex Author API for potential future use. **v3.1 does NOT call this API.** In v3.1, we use the `(Author)` from MAM folder names directly (already normalized by MAM workflow). Author variants are reported via `abs-report-authors` for manual cleanup.

The Audnex API provides an author search endpoint that could help resolve canonical author names in a future version.

### API Endpoint

```
GET https://api.audnex.us/authors?name={author_name}&region={region}
```

**Parameters:**
| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `name` | Yes | - | Author name to search |
| `region` | No | `us` | Region code: `au`, `ca`, `de`, `es`, `fr`, `in`, `it`, `jp`, `us`, `uk` |

### Response Schema

```python
from dataclasses import dataclass

@dataclass
class AudnexGenre:
    asin: str
    name: str
    type: str

@dataclass
class AudnexSimilarAuthor:
    asin: str
    name: str

@dataclass
class AudnexAuthor:
    asin: str           # Author ASIN (different from book ASIN!)
    name: str           # Canonical author name
    description: str    # Author bio
    image: str | None   # Author photo URL
    region: str         # Region code
    genres: list[AudnexGenre]
    similar: list[AudnexSimilarAuthor]
```

### Example Response

```json
[
  {
    "asin": "B001H6UJO8",
    "name": "Brandon Sanderson",
    "description": "Brandon Sanderson is an American author of epic fantasy...",
    "image": "https://images-na.ssl-images-amazon.com/images/...",
    "region": "us",
    "genres": [
      {"asin": "18574426011", "name": "Fantasy", "type": "genre"}
    ],
    "similar": [
      {"asin": "B000APZNLQ", "name": "Robert Jordan"}
    ]
  }
]
```

### Use Cases

**1. Canonical Name Resolution:**
```python
# Local folder: "brandon sanderson" or "Sanderson, Brandon"
# Audnex returns: "Brandon Sanderson"
# → Use "Brandon Sanderson" as canonical name
```

**2. Author ASIN for Future Matching:**
```python
# Store author ASIN in DB for faster future lookups
# Can cross-reference with book metadata
```

**3. Spelling Correction:**
```python
# Local: "Reki Kawahara" or "Kawahara Reki"
# Audnex: "Reki Kawahara"
# → Confirms correct spelling
```

### Potential Future Use Cases

If implemented in a future version (v3.2+), Audnex could be used to:
- Suggest canonical author names in `abs-report-authors` output
- Pre-populate author aliases for common variations
- Cross-reference author ASINs with book metadata

---

## Naming Schema

### Path Length Considerations

Unlike MAM (225-char limit), Audiobookshelf has **no practical limit**. We use the full naming schema without truncation:

```
{Series} vol_{NN} {Arc} ({Year}) ({Author}) {ASIN.xxxxx} [{Tag}]
```

> **Linux caveat:** While ABS doesn't limit path length, Linux has a 255-char limit
> per path component (filename/folder name) and a ~4096-char total path limit.
> Long light novel titles with series + arc + metadata can approach these limits.
> If this becomes a problem, we may add filename truncation in a future version.
> For now, the existing `truncate_filename()` from `utils/naming.py` can be applied
> to the final filename if needed.

### Schema Components

| Component | Format | Required | Example |
|-----------|--------|----------|---------|
| `{Series}` | Cleaned string | If series | `Sword Art Online` |
| `vol_{NN}` | Zero-padded 2 digits | If series | `vol_16` |
| `{Arc}` | Cleaned subtitle | If exists | `Alicization Exploding` |
| `({Year})` | 4-digit year | Always | `(2025)` |
| `({Author})` | Primary author | Always | `(Reki Kawahara)` |
| `{ASIN.xxx}` | Amazon ID | Always | `{ASIN.B0DK9TS6D9}` |
| `[{Tag}]` | Ripper tag | Optional | `[H2OKing]` |

### Standalone Books (No Series)

```
{Title} ({Year}) ({Author}) {ASIN.xxxxx} [{Tag}]
```

Example:
```
Project Hail Mary (2021) (Andy Weir) {ASIN.B08G9PRS1K} [H2OKing]
```

### Cleaning Pipeline

Same as MAM workflow (see NAMING_PLAN.md):

1. **Audnex Normalization** - Fix title/subtitle swaps
2. **Preserve Check** - Skip if in `preserve_exact` list
3. **Author Map** - Replace known author names
4. **Transliteration** - Non-ASCII → ASCII
5. **Phrase Removal** - Format indicators, genre tags, etc.
6. **Series Suffix Removal** - " Series", " Trilogy"
7. **Vol/Book Normalization** - `Volume 1` → `vol_01`
8. **Cleanup** - Double spaces, punctuation

---

## Directory Structure

### Key Path Definitions

| Variable | Source | Example |
|----------|--------|---------|
| `library_root` | `host` value from `abs.libraries[]` where `mamfast_managed: true` | `/mnt/user/data/audio/audiobooks` |
| `staging_root` | `paths.seed_root` (legacy name) | `/mnt/user/data/seedvault/staging` |
| `author_folder` | For **new imports**: `(Author)` from MAM folder name<br>For **existing entries**: folder name on disk | `Reki Kawahara` |

> **Note on `author_folder` source:**
> - When importing from staging → library: we use the `(Author)` component parsed from the MAM folder name
> - When indexing existing library → SQLite: we use the actual folder name on disk
> - `abs-report-authors` compares these two sources to find discrepancies

### Target Library Layout

```
{library_root}/
└── {Author}/
    └── {Series}/
        └── {Book Folder}/
            ├── {filename}.m4b
            ├── {filename}.cue (optional)
            ├── {filename}.epub (optional)
            ├── cover.jpg
            └── metadata.json (optional)
```

### Real Examples

**Series book with arc:**
```
/mnt/user/data/audio/audiobooks/
└── Reki Kawahara/
    └── Sword Art Online/
        └── Sword Art Online vol_16 Alicization Exploding (2025) (Reki Kawahara) {ASIN.B0DK9TS6D9} [H2OKing]/
            ├── Sword Art Online vol_16 Alicization Exploding (2025) (Reki Kawahara) {ASIN.B0DK9TS6D9}.m4b
            ├── Sword Art Online vol_16 Alicization Exploding (2025) (Reki Kawahara) {ASIN.B0DK9TS6D9}.cue
            └── cover.jpg
```

**Series book without arc:**
```
/mnt/user/data/audio/audiobooks/
└── Brandon Sanderson/
    └── Skyward/
        └── Skyward vol_01 (2018) (Brandon Sanderson) {ASIN.B07H7Q5D3M}/
            ├── Skyward vol_01 (2018) (Brandon Sanderson) {ASIN.B07H7Q5D3M}.m4b
            └── cover.jpg
```

**Standalone book:**
```
/mnt/user/data/audio/audiobooks/
└── Andy Weir/
    └── Project Hail Mary/
        ├── Project Hail Mary (2021) (Andy Weir) {ASIN.B08G9PRS1K}.m4b
        └── cover.jpg
```

> **Note:** Standalone books have **no book subfolder** - files go directly in the title folder.

---

## Processing Pipeline

### Pipeline Stages

```python
class ImportStage(Enum):
    """Import processing stages (for workflow tracking)."""
    DISCOVERED = "discovered"       # Found in staging directory
    PARSED = "parsed"               # Folder name parsed successfully
    VALIDATED = "validated"         # Duplicate check passed
    IMPORTED = "imported"           # Moved to library
    COMPLETE = "complete"           # State recorded
    FAILED = "failed"               # Error occurred
    SKIPPED = "skipped"             # Duplicate/invalid

# NOTE: ImportStatus (SUCCESS/SKIPPED/FAILED/DUPLICATE) is the result enum
# for import operations. ImportStage tracks workflow progress.
```

### Pipeline Flow

```python
def import_to_library(
    release: AudiobookRelease,
    dry_run: bool = False,
) -> ImportResult:
    """
    Import a single audiobook from staging to Audiobookshelf library.

    Called as final step in workflow, or manually via abs-import command.
    """
    staging_folder = release.staging_path

    # Stage 1: Parse folder name (should already be MAM-formatted)
    try:
        metadata = parse_folder_name(staging_folder.name)
    except ValueError as e:
        return ImportResult(status=ImportStatus.FAILED, error=str(e))

    # Stage 2: Build target path
    author_folder = metadata["author"]

    if metadata["is_standalone"]:
        # Standalone: Author/Title/
        series_folder = metadata["series"]
        target_path = library_root / author_folder / series_folder
    else:
        # Series: Author/Series/Book/
        series_folder = metadata["series"]
        target_path = library_root / author_folder / series_folder / staging_folder.name

    # Stage 3: Duplicate check
    if target_path.exists():
        action = handle_duplicate(target_path, metadata["asin"])
        if action == "skip":
            return ImportResult(status=ImportStatus.SKIPPED, target=target_path)
        elif action == "overwrite" and not dry_run:
            shutil.rmtree(target_path)

    # Stage 4: Dry-run check
    if dry_run:
        print_dry_run(f"Would move: {staging_folder.name} → {target_path}")
        # Return SUCCESS for dry-run - the operation *would* succeed
        return ImportResult(status=ImportStatus.SUCCESS, target=target_path)

    # Stage 5: Create directory structure
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Stage 6: Atomic move
    staging_folder.rename(target_path)

    # Stage 7: Update release and record state
    release.library_path = target_path
    record_import(metadata["asin"], target_path)

    return ImportResult(status=ImportStatus.SUCCESS, target=target_path)
```

### Workflow Integration

```python
# In workflow.py - process_release()

def process_release(release: AudiobookRelease, dry_run: bool = False) -> bool:
    """Process a single release through the full pipeline."""

    # ... existing stages: staging, metadata, torrent, qbittorrent ...

    # Final stage: ABS Import (if enabled)
    if settings.audiobookshelf.auto_import:
        print_step(6, 7, "Importing to Audiobookshelf library")
        result = import_to_library(release, dry_run=dry_run)

        if result.status == ImportStatus.SUCCESS:
            if dry_run:
                pass  # Dry-run message already printed
            else:
                print_success(f"Imported: {release.folder_name}")
        elif result.status == ImportStatus.SKIPPED:
        else:
            print_error(f"Import failed: {result.error}")
            return False

    release.status = ReleaseStatus.COMPLETE
    return True
```

### Batch Processing (Manual Command)

```python
def cmd_abs_import(args: argparse.Namespace) -> int:
    """Import staged books to Audiobookshelf library.

    Usage:
        mamfast abs-import                    # Import all staged books
        mamfast abs-import path/to/book       # Import specific book(s)
        mamfast abs-import --dry-run          # Preview without importing
    """
    dry_run = args.dry_run

    # Determine which folders to process
    if args.paths:
        # Specific paths provided on command line
        staging_folders = [Path(p) for p in args.paths if Path(p).is_dir()]
    else:
        # Default: all folders in staging directory
        staging_folders = [f for f in settings.paths.seed_root.iterdir() if f.is_dir()]

    if not staging_folders:
        print_info("No staged books to import")
        return 0

    if dry_run:
        console.print(f"[DRY RUN] Found {len(staging_folders)} books to import:\\n")

    results = []
    for folder in staging_folders:
        # Create minimal release object for import
        # extract_asin() is from utils/asin.py - see Smart ASIN Extraction section
        release = AudiobookRelease(
            asin=extract_asin(folder.name),
            title=folder.name,
            staging_path=folder,
        )
        result = import_to_library(release, dry_run=dry_run)
        results.append(result)

    # Summary
    success = sum(1 for r in results if r.status == ImportStatus.SUCCESS)
    skipped = sum(1 for r in results if r.status == ImportStatus.SKIPPED)
    failed = sum(1 for r in results if r.status == ImportStatus.FAILED)

    if dry_run:
        console.print(f"\n[DRY RUN] Would import {success} books")
    else:
        console.print(f"\n✅ Imported {success} books ({skipped} skipped, {failed} failed)")

    return 0 if failed == 0 else 1
```

---

## File Operations

### Workflow Context

This import happens **after** the MAM workflow has completed:
1. **MAM Workflow**: Libation → staging → hardlink to seed folder → torrent → upload
2. **ABS Import**: Move staged files → organized library (atomic move, same filesystem)

Since the staging folder and library are on the same filesystem, we use **atomic move** (rename) which is instant and preserves hardlinks to the seed folder.

### Atomic Move (Primary)

```python
def import_file(source: Path, dest: Path) -> None:
    """Import a file using atomic move (rename).

    REQUIREMENT: staging and library MUST be on same filesystem.
    This is enforced by validate_import_prerequisites() at startup.

    Benefits of same-filesystem atomic move:
    - Instant (no data copy)
    - Preserves hardlinks to seed folder (torrent keeps seeding)
    - Atomic (no partial states)
    """
    # Atomic move - instant, preserves hardlinks
    source.rename(dest)
    logger.info(f"Moved: {source.name} → {dest}")
```

> **Note:** Cross-filesystem imports are NOT supported in v3.1. The pre-flight
> check in `validate_import_prerequisites()` will fail if staging and library
> are on different filesystems. This protects hardlinks which are required
> for continued seeding.

### Why This Works

```
BEFORE IMPORT:

  Staging Folder                    Seed Folder (hardlinked)
  /staging/Book/                    /seedvault/Book/
  └── book.m4b  ─────────────────── └── book.m4b
      (inode 12345)                     (same inode 12345)

AFTER ATOMIC MOVE:

  Library                           Seed Folder (still hardlinked!)
  /audiobooks/Author/Series/Book/   /seedvault/Book/
  └── book.m4b  ─────────────────── └── book.m4b
      (inode 12345)                     (same inode 12345)

  Staging Folder
  /staging/Book/  → (folder no longer exists - entire directory was renamed)
```

**Key insight:** `rename()` only changes the directory entry, not the inode. The hardlink in the seed folder still points to the same data, so torrents keep seeding without interruption.
```

### Files to Import

| File Type | Pattern | Required | Notes |
|-----------|---------|----------|-------|
| Audio | `*.m4b`, `*.m4a`, `*.mp3` | Yes | Main audiobook file(s) |
| Cover | `cover.jpg`, `cover.png`, `folder.jpg` | No | Renamed to `cover.jpg` |
| CUE | `*.cue` | No | Chapter markers |
| EPUB | `*.epub` | No | Companion ebook |
| NFO | `*.nfo` | No | Release info (optional) |

### Cover Image Handling

```python
COVER_PATTERNS = [
    "cover.jpg", "cover.jpeg", "cover.png",
    "folder.jpg", "folder.png",
    "album.jpg", "albumart.jpg",
    "*cover*.jpg", "*cover*.png",
]

def find_cover(source_dir: Path) -> Path | None:
    """Find cover image in source directory."""
    for pattern in COVER_PATTERNS:
        matches = list(source_dir.glob(pattern))
        if matches:
            return matches[0]
    return None
```

---

## Configuration

### Unified Config Structure

```yaml
# config.yaml

# ═══════════════════════════════════════════════════════════════════════════════
# ABS API CONNECTION (abs:)
# Used for: API calls, authentication, library discovery, path mapping
# ═══════════════════════════════════════════════════════════════════════════════
abs:
  enabled: true
  base_url: "https://audiobookshelf.kingpaging.com"
  api_token: "${ABS_API_TOKEN}"
  docker_mode: true

  # Libraries to manage (discovered via `mamfast abs-init`)
  libraries:
    - id: "lib_c1u6t4p45c35rf0nzd"
      name: "Audiobooks"
      mamfast_managed: true
      path_map:
        - container: "/audiobooks"
          host: "/mnt/user/data/audio/audiobooks"

  # ─────────────────────────────────────────────────────────────────────────────
  # SCAN TRIGGER OPTIONS
  # ─────────────────────────────────────────────────────────────────────────────
  # When to trigger ABS library scan after imports:
  #   - "none":      Don't trigger (let ABS's scheduled scan pick it up)
  #   - "batch":     Single scan after all imports complete (default, recommended)
  #   - "immediate": Scan after each book (slower, but shows up in ABS faster)
  trigger_scan: "batch"

  # force=0: Only scan for new/changed files (fast)
  # force=1: Re-scan all files, useful for metadata refresh (slow)
  # Implementation: POST /api/libraries/{library_id}/scan?force=0
```

### Scan Trigger Behavior

| Mode | Behavior | CLI Output |
|------|----------|------------|
| `none` | No scan triggered. Rely on ABS's periodic scan. | `Note: ABS scan skipped (trigger_scan=none)` |
| `batch` | Single scan after all imports complete. Fast. | `Note: ABS scan scheduled (batch mode)` |
| `immediate` | Scan after each successful import. Slow but immediate visibility in ABS. | `Note: Triggered ABS scan` (per book) |

> **`abs_version` note:** The `index_meta` table stores ABS version if exposed via
> API (e.g., `X-ABS-Version` header or `/api/status` endpoint). This is optional
> and used for diagnostics only.

```yaml
# (continued from above)

# ═══════════════════════════════════════════════════════════════════════════════
# IMPORT BEHAVIOR (audiobookshelf:)
# Used for: import logic, duplicate handling, workflow integration
# ═══════════════════════════════════════════════════════════════════════════════
audiobookshelf:
  # Enable automatic import after MAM workflow completes
  auto_import: true

  # Duplicate handling: "skip" (default), "warn", "overwrite"
  duplicate_policy: "skip"

# NOTE: If auto_import=true but abs_index.db doesn't exist,
# the import phase will fail fast with a clear error message:
#   "Run 'mamfast abs-index' first to build the library index"

# Existing paths config
# ─────────────────────────────────────────────────────────────────────────────
# NAMING NOTE: "seed_root" is a legacy name from MAMFast's original design.
# It now points to the staging directory where completed uploads land.
# qBittorrent's actual seeding location is /mnt/user/data/seedvault/seeding/
# The "staging" folder is where MAMFast places files after hardlinking.
# ─────────────────────────────────────────────────────────────────────────────
paths:
  seed_root: "/mnt/user/data/seedvault/staging"  # Source for ABS import

# Existing naming config still applies
naming:
  ripper_tag: "H2OKing"
```

### Config Key Summary

| Block | Purpose | Example Keys |
|-------|---------|--------------|
| `abs:` | API connection & path mapping | `base_url`, `api_token`, `libraries`, `path_map`, `trigger_scan` |
| `audiobookshelf:` | Import behavior & policies | `auto_import`, `duplicate_policy` |

### Database Location

The SQLite index is stored at `data/abs_index.db`:

```
data/
├── abs_index.db            # SQLite library index (from ABS API)
├── processed.json          # MAM workflow state (existing)
```

### Duplicate Policy Explained

| Policy | Behavior | Use Case |
|--------|----------|----------|
| `skip` | Silently skip if ASIN exists | Default, safe for automation |
| `warn` | Log warning, then skip | Debugging, visibility into skips |
| `overwrite` | Delete existing, import new | Re-ripping, quality upgrades |

**Note:** Duplicate detection is O(1) via SQLite index, works across ALL naming formats.

### Workflow Behavior

| `audiobookshelf.auto_import` | `--abs-import` flag | `--no-abs-import` flag | Result |
|------------------------------|---------------------|------------------------|--------|
| `true` | (not set) | (not set) | **Import runs** |
| `true` | `--abs-import` | (not set) | **Import runs** |
| `true` | (not set) | `--no-abs-import` | Import skipped |
| `false` | (not set) | (not set) | Import skipped |
| `false` | `--abs-import` | (not set) | **Import runs** |

**First-time setup:** Run `mamfast abs-index` before enabling auto-import to build the initial index.

### Filesystem Requirement

**IMPORTANT:** `paths.seed_root` (staging) and ABS library root **must be on the same filesystem** for atomic move to work and preserve hardlinks.

```
Same filesystem (required):
  /mnt/user/data/
  ├── seedvault/staging/    ← paths.seed_root
  ├── seedvault/seeding/    ← seed folder (hardlinks here)
  └── audio/audiobooks/     ← ABS library root (from path_map.host)
```

### State Tracking

**Primary state is SQLite** (`data/abs_index.db`).

The `import_log` table tracks import history:
- `status = "success"` - import completed
- `status = "skipped"` - duplicate by ASIN
- `status = "failed"` - error during move
- `status = "duplicate"` - already exists at target path

> Note: `books` stores current library state; `import_log` records how entries got there.

**JSON export** available via `mamfast export-library > library.json` for inspection/backup.

---

## CLI Commands

### Phase 0: ABS Setup & Indexing (Run First!)

```bash
# 1. Initialize ABS connection - validates token, lists libraries
mamfast abs-init

# Example output:
# [ABS] Connected to https://audiobookshelf.kingpaging.com
# [ABS] Found Libraries:
#   - lib_c1u6t4p45c35rf0nzd "Audiobooks" (root: /audiobooks)
#   - lib_xxxxxxxxxxxxx     "Podcasts"   (root: /podcasts)
#
# Add to config.yaml:
#   abs:
#     libraries:
#       - id: "lib_c1u6t4p45c35rf0nzd"
#         name: "Audiobooks"
#         mamfast_managed: true

# 2. Build/update SQLite index from ABS API
mamfast abs-index
mamfast abs-index --verbose  # Show progress

# Example output:
# 🔍 Fetching from Audiobookshelf API...
#
# Indexed 1,327 books from Audiobookshelf
#   - 1,280 with ASIN
#   - 47 without ASIN
#   - 5 suspected duplicate ASINs (see abs_index_dupes.log)
#
# Database: data/abs_index.db (2.4 MB)

# 3. Export to JSON for inspection
mamfast export-library > library.json
```

### Phase 0: Author Reports

```bash
# Generate author variants report
mamfast abs-report-authors

# Example output:
# 📊 Author Variants Report
# ────────────────────────────────────────────────────────────
#
# The following authors have folder names that differ from ABS metadata:
#
# ┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┓
# ┃ ABS Display Name   ┃ Folder Name        ┃ Books   ┃
# ┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━┩
# │ J.R. Mathews       │ J R Mathews        │ 12      │
# │ Pirateaba          │ pirateaba          │ 8       │
# │ Necoco             │ Nekoko             │ 5       │
# └────────────────────┴────────────────────┴─────────┘
#
# To fix: rename folders on disk, then re-run 'mamfast abs-index'

# Quick duplicate check
mamfast abs-check-duplicate --asin B0DK27WWT8

# Example output:
# ASIN B0DK27WWT8 already exists at:
#   /mnt/user/data/audio/audiobooks/J R Mathews/Jake's Magical Market vol_04 ...
```

### Phase 1+: Import Commands

```bash
# Import all books from staging to library
mamfast abs-import

# Dry-run mode (preview without changes)
mamfast abs-import --dry-run

# Import a specific folder
mamfast abs-import "/staging/Sword Art Online vol_16..."

# Override duplicate policy
mamfast abs-import --duplicate-policy overwrite
mamfast abs-import -d skip  # Short form
```

### Workflow Integration

```bash
# Full workflow with ABS import (when abs.enabled = true)
mamfast run

# Explicit ABS import control
mamfast run --abs-import
mamfast run --no-abs-import

# Dry-run everything
mamfast run --dry-run
```

### Example Output

**ABS init:**
```bash
$ mamfast abs-init

[ABS] Connecting to https://audiobookshelf.domain.com...
[ABS] ✓ Authentication successful (user: admin)
[ABS] ✓ API version: 2.7.2

Found Libraries:
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┓
┃ ID                        ┃ Name          ┃ Root Path         ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━┩
│ lib_c1u6t4p45c35rf0nzd    │ Audiobooks    │ /audiobooks       │
│ lib_p2x8y7z9a1b3c4d5e6    │ Podcasts      │ /podcasts         │
└───────────────────────────┴───────────────┴───────────────────┘

💡 Add to config.yaml:

abs:
  enabled: true
  base_url: "https://audiobookshelf.kingpaging.com"
  api_token: "${ABS_API_TOKEN}"
  docker_mode: true
  libraries:
    - id: "lib_c1u6t4p45c35rf0nzd"
      name: "Audiobooks"
      mamfast_managed: true
      path_map:
        - container: "/audiobooks"
          host: "/mnt/user/data/audio/audiobooks"
```

**ABS index:**
```bash
$ mamfast abs-index

🔍 Fetching from Audiobookshelf API...

Library: Audiobooks (lib_c1u6t4p45c35rf0nzd)
  Fetching items... 1,327 books found
  Processing...
    ✓ Brandon Sanderson (45 books)
    ✓ Andy Weir (12 books)
    ✓ J R Mathews (15 books)
    ...

📊 Index Complete
────────────────────────────────────────────────────────────
Books indexed:     1,327
With ASIN:         1,280 (96.5%)
Without ASIN:      47 (3.5%)
Author variants:   3 (see 'mamfast abs-report-authors')
Duplicate ASINs:   0

Database: data/abs_index.db (2.4 MB)
```

**ABS import:**
```bash
$ mamfast abs-import --dry-run

[DRY RUN] Scanning /mnt/user/data/seedvault/staging/

Found 3 audiobooks to import:

┏━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┓
┃ ASIN         ┃ Target Path                                       ┃ Status        ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━┩
│ B0DK9TS6D9   │ Reki Kawahara/Sword Art Online/...                │ ✅ Ready      │
│ B0DP3CQC6N   │ Rifujin na Magonote/Mushoku Tensei/...            │ ✅ Ready      │
│ B08G9PRS1K   │ Andy Weir/Project Hail Mary/                       │ ⏭️ Exists     │
└──────────────┴───────────────────────────────────────────────────┴───────────────┘

Note: 1 book skipped (ASIN found in abs_index.db)

[DRY RUN] No files moved. Run without --dry-run to import.
```

**Audit authors:**
```bash
$ mamfast abs-report-authors

📊 Author Variants Report
────────────────────────────────────────────────────────────

The following authors have folder names that differ from ABS metadata:

┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┓
┃ ABS Display Name   ┃ Folder Name        ┃ Books   ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━┩
│ J.R. Mathews       │ J R Mathews        │ 12      │
│ Pirateaba          │ pirateaba          │ 8       │
│ Necoco             │ Nekoko             │ 5       │
└────────────────────┴────────────────────┴─────────┘

To fix: rename folders on disk, then re-run 'mamfast abs-index'
```

> **Note:** In v3.x, we report variants but don't auto-merge. ABS is the authority—fix folder names manually and re-index.

**Import (with index):**
```bash
$ mamfast abs-import --dry-run

[DRY RUN] Scanning /mnt/user/data/seedvault/staging/

Found 3 audiobooks to import:

┏━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┓
┃ ASIN         ┃ Target Path                                       ┃ Status        ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━┩
│ B0DK9TS6D9   │ Reki Kawahara/Sword Art Online/Sword Art Online…  │ ✅ Ready      │
│ B0DP3CQC6N   │ Rifujin na Magonote/Mushoku Tensei.../Mushoku...  │ ✅ Ready      │
│ B08G9PRS1K   │ Andy Weir/Project Hail Mary/                       │ ⏭️ Exists     │
└──────────────┴───────────────────────────────────────────────────┴───────────────┘

Note: 1 book skipped (already in library by ASIN lookup)

[DRY RUN] No files moved. Run without --dry-run to import.
```

**Actual import:**
```bash
$ mamfast abs-import

Processing 3 audiobooks...

  ✓ Sword Art Online vol_16... → Reki Kawahara/Sword Art Online/
  ✓ Mushoku Tensei vol_27... → Rifujin na Magonote/Mushoku Tensei.../
  ⏭️ Project Hail Mary (skipped - exists)

✅ Imported 2 books (1 skipped, 0 failed)

Note: ABS scan scheduled (batch mode)
```

**As part of workflow:**
```bash
$ mamfast run

Step 1/7: Discovering new releases...
  ✓ Found 2 new releases

Step 2/7: Staging files...
  ✓ Staged: Sword Art Online vol_16...

Step 3/7: Fetching metadata...
  ✓ Metadata fetched for 2 releases

Step 4/7: Creating torrents...
  ✓ Created: Sword Art Online vol_16....torrent

Step 5/7: Uploading to qBittorrent...
  ✓ Added to qBittorrent: Sword Art Online vol_16...

Step 6/7: Importing to Audiobookshelf library...
  ✓ Imported: Sword Art Online vol_16... → Reki Kawahara/Sword Art Online/

Step 7/7: Cleanup...
  ✓ Workflow complete

✅ Processed 2 releases (2 complete, 0 failed)
```

---

## Edge Cases

### Folder Name Doesn't Match Pattern

```
Scenario: Non-MAM folder in staging (manually added)
Solution:
  - Skip with warning
  - Suggest running through MAM workflow first
```

### Duplicate Detection

```
Scenario: Book with same ASIN already in library
Solution:
  - skip (default): Log and continue
  - overwrite: Remove existing, move new
```

### Standalone vs Series

```
Scenario: Book has no vol_XX in folder name
Solution:
  - Detected as standalone
  - Use 2-level structure: Author/Title/
  - Files go directly in title folder (no book subfolder)
```

### Different Filesystem

```
Scenario: Staging and library on different filesystems
Solution:
  - Pre-flight validation fails fast with a clear error
  - Cross-filesystem imports are NOT supported in v3.1
  - This is intentional to preserve hardlinks for seeding
  - If you need cross-FS, use a different import method (manual copy)
```

### Author Name Variations

```
Scenario: Same author with different name formats across books
Solution:
  - MAM workflow already cleaned author names
  - Author folder name comes from cleaned (Author) component
  - Consistent naming maintained
```

---

## Reusable Codebase Components

### Existing Libraries (Already in pyproject.toml)

These libraries are **already installed** and should be used:

| Library | Import | Use For |
|---------|--------|---------|
| `httpx` | `import httpx` | ABS API client (already in deps) |
| `pydantic` | `from pydantic import BaseModel` | ABS API response validation |
| `rapidfuzz` | `from rapidfuzz import fuzz` | Author variant detection in `abs-report-authors` |
| `rich` | Via `console.py` | CLI output (tables, progress, colors) |
| `pathvalidate` | Via `utils/paths.py` | Filename safety (already integrated) |

### Existing Modules to Reuse

| Module | Import | Use For |
|--------|--------|---------|
| `utils/retry.py` | `from mamfast.utils.retry import retry_with_backoff, NETWORK_EXCEPTIONS` | Wrap ABS API calls |
| `utils/fuzzy.py` | `from mamfast.utils.fuzzy import similarity_ratio, find_best_match` | Author matching in reports |
| `utils/naming.py` | `from mamfast.utils.naming import build_mam_folder_name, sanitize_filename` | Build target paths |
| `utils/paths.py` | `from mamfast.utils.paths import safe_filename, safe_dirname` | Cross-platform safety |
| `console.py` | `from mamfast.console import print_step, print_success, print_error, print_warning` | CLI output |
| `validation.py` | `from mamfast.validation import ValidationResult, ValidationCheck` | Pre-flight checks |
| `schemas/audnex.py` | Pattern reference | Model for ABS API Pydantic schemas |
| `models.py` | `from mamfast.models import AudiobookRelease, ReleaseStatus` | Extend for ABS import |
| `config.py` | `from mamfast.config import load_settings, Settings` | Add `abs:` config section |

### New Modules to Create

| Module | Purpose |
|--------|---------|
| `src/mamfast/abs_client.py` | ABS API client (uses `httpx`, `retry_with_backoff`) |
| `src/mamfast/abs_index.py` | SQLite index operations |
| `src/mamfast/utils/abs_paths.py` | Container ↔ host path mapping |
| `src/mamfast/schemas/abs.py` | Pydantic models for ABS API responses |

### Example: Using Existing Retry Logic

```python
# src/mamfast/abs_client.py
from mamfast.utils.retry import retry_with_backoff, NETWORK_EXCEPTIONS

class AbsClient:
    @retry_with_backoff(max_attempts=3, base_delay=2.0, exceptions=NETWORK_EXCEPTIONS)
    def get_library_items(self, library_id: str) -> list[dict]:
        resp = self._client.get(f"/libraries/{library_id}/items", ...)
        resp.raise_for_status()
        return resp.json()["results"]
```

### Example: Using Existing Fuzzy Matching

```python
# In abs-report-authors command
from mamfast.utils.fuzzy import similarity_ratio, normalize_author_name

def find_similar_authors(authors: list[str]) -> list[tuple[str, str, float]]:
    """Find author names that are likely the same person."""
    similar = []
    for i, a1 in enumerate(authors):
        for a2 in authors[i+1:]:
            score = similarity_ratio(
                normalize_author_name(a1),
                normalize_author_name(a2),
            )
            if score >= 85:
                similar.append((a1, a2, score))
    return similar
```

### Example: Using Existing Console Helpers

```python
# In cmd_abs_import
from mamfast.console import (
    print_step, print_success, print_error, print_warning,
    print_info, print_dry_run,
)

def cmd_abs_import(args):
    print_step(1, 3, "Scanning staging directory")
    # ...
    print_success(f"Imported: {book.title}")
    print_warning(f"Skipped (duplicate): {book.title}")
    print_error(f"Failed: {error}")
```

---

## Implementation Phases

### Suggested Order of Operations (Revised with ABS API)

1. **Phase 0a:** ABS client + path mapping
2. **Phase 0b:** ABS indexer (SQLite from API)
3. **Phase 0c:** Author variant reporting
4. **Phase 1:** ABS import (use index for dedup)
5. **Phase 2:** Polish (workflow integration, Rich output)

**Key simplification:** No more complex author merge logic - ABS is the authority. We just report variants and let user fix them.

---

### Phase 0a: ABS Client & Path Mapping

**Goal:** Connect to ABS API, handle Docker path translation

**New Modules:**
- [ ] `src/mamfast/abs_client.py` - ABS API client with httpx
- [ ] Path mapping in `src/mamfast/utils/paths.py`

**Features:**
- [ ] `AbsClient` class:
  - `get_libraries()` - list all libraries
  - `get_library_items(library_id)` - list books in a library
  - `get_item_details(item_id)` - detailed book info (optional)
- [ ] `map_abs_path_to_host()` - container → host path
- [ ] `map_host_path_to_abs()` - host → container path
- [ ] Config validation (URL, token, path_map)

**CLI:**
- [ ] `mamfast abs-init` command:
  - Validate connection
  - List libraries
  - Generate config template

**Config:**
```yaml
abs:
  enabled: true
  base_url: "https://audiobookshelf.kingpaging.com"
  api_token: "${ABS_API_TOKEN}"
  docker_mode: true
  libraries:
    - id: "lib_xxx"
      name: "Audiobooks"
      mamfast_managed: true
      path_map:
        - container: "/audiobooks"
          host: "/mnt/user/data/audio/audiobooks"
```

**Tests:**
- [ ] Unit tests for path mapping (both directions)
- [ ] Unit tests for config parsing
- [ ] Mock tests for API client
- [ ] Integration test with real ABS (optional, needs credentials)

**Estimated Effort:** 3-4 hours

---

### Phase 0b: ABS Indexer

**Goal:** Populate SQLite from ABS API

**New Modules:**
- [ ] `src/mamfast/abs_index.py` - `AbsIndex` class
- [ ] `src/mamfast/db.py` - SQLite helpers

**Database Schema:** See [Library Index (SQLite)](#library-index-sqlite) for canonical schema.

> The `books` table includes `subtitle`, `mtime_ms`, `size_bytes` for completeness.

**Features:**
- [ ] `sync_from_abs()` - fetch all items, populate DB
- [ ] ASIN extraction from:
  1. ABS metadata (if stored there)
  2. Folder name (Smart ASIN extractor)
- [ ] Incremental sync (detect changes via mtime)
- [ ] Stats reporting

**CLI:**
- [ ] `mamfast abs-index` command
- [ ] `--verbose` flag
- [ ] `mamfast export-library` command (JSON dump)

**Tests:**
- [ ] Unit tests for DB operations
- [ ] Unit tests for ASIN extraction
- [ ] Mock tests for API → DB flow

**Estimated Effort:** 4-5 hours

---

### Phase 0c: Author Variant Reporting

**Goal:** Report author name discrepancies for manual fix

**Features:**
- [ ] `get_author_variants()` - find author_display ≠ author_folder cases
- [ ] Rich table output
- [ ] Export to CSV/JSON

**CLI:**
- [ ] `mamfast abs-report-authors` command
- [ ] `mamfast abs-check-duplicate --asin XXX` command

**Key insight:** We DON'T manage authors ourselves. We just report:
- "ABS says author is 'J.R. Mathews' but folder is 'J R Mathews'"
- User renames folder manually (or via script)
- User triggers ABS rescan
- User re-runs `mamfast abs-index`

**Tests:**
- [ ] Unit tests for variant detection
- [ ] Golden tests with sample data

**Estimated Effort:** 2-3 hours

---

### Phase 1: ABS Import

**Goal:** Import books from staging using index for dedup

**New Module:**
- [ ] `src/mamfast/abs_import.py`

**Features:**
- [ ] `check_duplicate(asin)` - O(1) SQLite lookup
- [ ] `import_book(staging_path, library_config)`:
  1. Parse folder name for ASIN
  2. Check if ASIN exists in index
  3. If new: atomic move to library
  4. Log import
- [ ] `DuplicatePolicy` enum (skip, warn, overwrite)
- [ ] Dry-run mode

**CLI:**
- [ ] `mamfast abs-import` command
- [ ] `--dry-run` flag
- [ ] `--duplicate-policy` / `-d` flag

**Workflow Integration:**
- [ ] Add to `workflow.py` as optional final stage
- [ ] `--abs-import` / `--no-abs-import` flags

**Tests:**
- [ ] Unit tests for duplicate detection
- [ ] Unit tests for path building
- [ ] Integration tests with mock filesystem

**Estimated Effort:** 4-5 hours

---

### Phase 2: Polish & Advanced Features

**Goal:** Rich output, workflow integration, edge cases

**Features:**
- [ ] Rich progress displays (Live tables)
- [ ] Standalone book detection & handling
- [ ] (Optional) Audnex author lookup for new imports
- [ ] (Optional) Trigger ABS scan after import

**Documentation:**
- [ ] Update README.md
- [ ] Update CLAUDE.md
- [ ] Add config.yaml.example updates

**Estimated Effort:** 2-3 hours

---

### Total Estimated Effort (Revised)

| Phase | Description | Hours |
|-------|-------------|-------|
| 0a | ABS Client & Path Mapping | 3-4 |
| 0b | ABS Indexer (SQLite) | 4-5 |
| 0c | Author Variant Reporting | 2-3 |
| 1 | ABS Import | 4-5 |
| 2 | Polish | 2-3 |
| **Total** | | **15-20** |

**Savings vs Old Plan:** ~4-6 hours by not implementing complex author merge logic!

---

## Testing Strategy

### Test Fixtures

ABS API response mocks should live in `tests/fixtures/abs_responses/`:

```
tests/fixtures/abs_responses/
├── libraries.json           # GET /api/libraries
├── library_items.json       # GET /api/libraries/{id}/items
├── library_item_detail.json # GET /api/items/{id}
└── scan_response.json       # POST /api/libraries/{id}/scan
```

### Unit Tests

```python
class TestAbsClient:
    def test_get_libraries_returns_list(self): ...
    def test_get_library_items_returns_books(self): ...
    def test_auth_failure_raises(self): ...
    def test_connection_error_handled(self): ...

class TestPathMapping:
    def test_abs_path_to_host_mapping(self): ...
    def test_host_to_container_mapping(self): ...
    def test_no_mapping_returns_original(self): ...
    def test_nested_path_mapping(self): ...

class TestASINExtraction:
    def test_new_format_curly_braces(self): ...
    def test_old_format_brackets(self): ...
    def test_bare_asin_brackets(self): ...
    def test_bare_asin_anywhere(self): ...
    def test_no_asin_returns_none(self): ...

class TestAbsIndex:
    def test_sync_from_abs_populates_db(self): ...
    def test_get_book_by_asin(self): ...
    def test_asin_exists(self): ...
    def test_get_author_variants(self): ...
    def test_export_json(self): ...

class TestFolderNameParsing:
    def test_parse_series_with_arc(self): ...
    def test_parse_series_no_arc(self): ...
    def test_parse_standalone(self): ...
    def test_parse_with_tag(self): ...
    def test_parse_without_tag(self): ...
    def test_invalid_format_raises(self): ...

class TestTargetPathBuilder:
    def test_series_book_path(self): ...
    def test_standalone_book_path(self): ...
    def test_creates_parent_dirs(self): ...

class TestDuplicateDetection:
    def test_asin_exists_in_library(self): ...
    def test_no_duplicate(self): ...

class TestAtomicMove:
    def test_move_same_filesystem(self): ...
    def test_cross_device_fails_validation(self): ...  # NOT supported in v3.1
```

### Integration Tests

```python
class TestAbsImportWorkflow:
    def test_import_series_book(self, tmp_path): ...
    def test_import_standalone(self, tmp_path): ...
    def test_import_all_batch(self, tmp_path): ...
    def test_dry_run_no_changes(self, tmp_path): ...
    def test_skip_duplicate(self, tmp_path): ...
```

---

## Library Analysis Report (Reference)

> **Note:** This section documents the library state as of initial analysis. Use `mamfast abs-report-authors` to generate current reports.

> **Scan Date:** 2025-12-03 | **Library:** `/mnt/user/data/audio/audiobooks/`

### Naming Format Inventory

The library contains audiobooks from multiple import eras with different naming conventions:

| Format | Pattern | Count | Example |
|--------|---------|-------|---------|
| **Current (MAMFast)** | `{ASIN.B0xxx}` | Majority | `Sword Art Online vol_16 (2025) (Reki Kawahara) {ASIN.B0DK9TS6D9} [H2OKing]` |
| **Old Bracket** | `[ASIN.B0xxx]` | Some | `Mushoku Tensei - vol_03 [2024] [Author] [ASIN.B0CNTY7LVH]` |
| **Old Bare ASIN** | `[B0xxxxxxxx]` | Some | `Azarinth Healer - vol_04 [Rhaegar] [B0DMQ2WP9F]` |
| **Legacy** | No ASIN | Few | `Project Hail Mary.m4b` |
| **Random** | Various | Few | `Vol. 01 - Title {Narrator} [B0xxx]` |

### Directory Structure Patterns

| Type | Structure | Status |
|------|-----------|--------|
| **Series (new)** | `Author/Series/Book Folder/files` | ✅ Consistent |
| **Series (old)** | `Author/Series/Book Folder/files` | ⚠️ Varied naming |
| **Standalone (new)** | `Author/Title Folder/files` | ✅ With ASIN |
| **Standalone (old)** | `Author/Title/files` | ⚠️ No ASIN, no subfolder |

### Author Name Variations Found

Scanned library found **7 author name mismatches** between folder names and `(Author)` in book names:

| Folder Name | Book `(Author)` | Issue Type |
|-------------|-----------------|------------|
| `J R Mathews` | `J.R. Mathews` | Periods vs spaces in initials |
| `Nekoko` | `Necoco` | Spelling variation (Audible inconsistency) |
| `Pirateaba` | `pirateaba` | Case variation |

**Root cause:** Audible metadata is inconsistent. The same author can appear with different spellings across releases.

### Duplicate Detection Requirements

Based on the findings, duplicate detection must handle:

1. **ASIN in multiple formats** (solved by Smart ASIN Extraction)
   - `{ASIN.B0DK9TS6D9}` (new)
   - `[ASIN.B0DK9TS6D9]` (old)
   - `[B0DK9TS6D9]` (bare)

2. **Author folder matching** (new requirement)
   - Must fuzzy-match author names to prevent duplicate folders
   - Example: `(J.R. Mathews)` should map to existing `J R Mathews/` folder
   - Example: `(Necoco)` should map to existing `Nekoko/` folder

---

## Smart Author Folder Resolution — **NOT IN v3.1 — Future Enhancement**

> ⚠️ **This section describes a post-v3.1 enhancement.** In v3.1, author folder resolution uses simple normalization only. The layered fuzzy matching described here is for future consideration. Moved from core spec to appendix.

### The Strategy: Layered Matching

Use a **4-layer resolution strategy** (cheap → expensive):

```
1. Explicit Alias     →  "J.R. Mathews" explicitly maps to "J R Mathews" (config file)
2. Normalized Exact   →  normalize("J.R. Mathews") == normalize("J R Mathews") ✓
3. Fuzzy Match        →  "Necoco" ≈ "Nekoko" (89% similarity)
4. Create New         →  No match found, create new folder
```

### Layer 1: Author Aliases File

Explicit overrides for known variations (no fuzzy guessing):

```yaml
# config/author_aliases.yaml
"J.R. Mathews": "J R Mathews"
"J R Mathews": "J R Mathews"
"Necoco": "Nekoko"
"NECOCO": "Nekoko"
"pirateaba": "Pirateaba"
"necoko": "Nekoko"
```

**Benefits:**
- Deterministic - no fuzzy surprises
- Grows over time as you encounter variations
- Can be auto-generated from fuzzy match suggestions

### Layer 2: Strong Normalization

Normalize author names before comparison (solves 90% of cases without fuzzy):

```python
import re
import unicodedata


def normalize_author_for_compare(name: str) -> str:
    """Normalize author name for comparison.

    Handles:
    - "J.R. Mathews" → "j r mathews"
    - "J R Mathews" → "j r mathews"
    - "J-R Mathews" → "j r mathews"
    - "Pirateaba" / "pirateaba" → "pirateaba"
    - "Néçòčô" → "necoco" (unicode normalization)
    """
    # 1) Unicode normalize, remove accents
    name = unicodedata.normalize("NFKD", name)
    name = "".join(ch for ch in name if not unicodedata.combining(ch))

    # 2) Replace punctuation between name segments with spaces
    # "J.R." → "J R", "J-R" → "J R", "Smith, John" → "Smith John"
    name = re.sub(r"[.,;:/\-]+", " ", name)

    # 3) Collapse whitespace
    name = re.sub(r"\s+", " ", name)

    # 4) Strip and lowercase
    return name.strip().lower()
```

Build a normalized index once per run:

```python
def build_normalized_author_map(library_root: Path) -> dict[str, Path]:
    """Build normalized_name → folder_path index."""
    index = {}
    for author_dir in library_root.iterdir():
        if author_dir.is_dir():
            normalized = normalize_author_for_compare(author_dir.name)
            index[normalized] = author_dir
    return index
```

### Layer 3: Fuzzy Matching (Last Resort)

Only used for genuinely weird variations like `Nekoko` vs `Necoco`:

```python
from rapidfuzz import fuzz


def author_match_threshold(name: str) -> int:
    """Dynamic threshold based on name length.

    Short names need higher threshold (one char is significant).
    """
    n = len(name)
    if n <= 6:
        return 90   # "Necoco" vs "Nekoko" - high bar
    if n <= 12:
        return 88
    return 85       # Longer names can tolerate more variation


def find_existing_author_folder_fuzzy(
    author: str,
    library_root: Path,
    normalized_map: dict[str, Path],
) -> tuple[Path | None, int]:
    """Find existing author folder using fuzzy matching.

    Uses token_sort_ratio for robustness to word reordering.

    Returns:
        (matched_folder, similarity_score) or (None, 0)
    """
    normalized = normalize_author_for_compare(author)
    threshold = author_match_threshold(normalized)

    best_match = None
    best_score = 0

    for folder_normalized, folder_path in normalized_map.items():
        # token_sort_ratio handles word reordering better
        score = fuzz.token_sort_ratio(normalized, folder_normalized)

        if score > best_score and score >= threshold:
            best_score = score
            best_match = folder_path

    return best_match, best_score
```

### Layer 4: Complete Resolution Function

Combines all layers with ASIN-first logic:

```python
def resolve_author_folder(
    author_raw: str,
    library_root: Path,
    aliases: dict[str, str],
    normalized_map: dict[str, Path],
    asin_index: dict[str, LibraryEntry] | None = None,
    candidate_asin: str | None = None,
) -> tuple[Path, str]:
    """Resolve author folder using layered matching.

    Returns:
        (folder_path, resolution_method)
    """
    # 0) ASIN-first: if we already have this ASIN, use its author folder
    if asin_index and candidate_asin:
        existing = asin_index.get(candidate_asin)
        if existing:
            # Extract author folder from existing path
            # /audiobooks/Author/Series/Book → Author
            author_dir = existing.path.parents[1] if existing.kind == "series_book" else existing.path.parent
            return author_dir, "asin_existing"

    # 1) Apply explicit alias
    canonical_name = aliases.get(author_raw, author_raw)

    # 2) Try exact folder match with canonical name
    exact = library_root / canonical_name
    if exact.exists():
        return exact, "exact"

    # 3) Try normalized exact match
    normalized = normalize_author_for_compare(canonical_name)
    if normalized in normalized_map:
        return normalized_map[normalized], "normalized"

    # 4) Fuzzy match as last resort
    fuzzy_match, score = find_existing_author_folder_fuzzy(
        canonical_name, library_root, normalized_map
    )
    if fuzzy_match:
        logger.info(
            f"Fuzzy author match: '{author_raw}' → '{fuzzy_match.name}' "
            f"(score: {score})"
        )
        # Optionally: suggest adding to aliases file
        suggest_alias(author_raw, fuzzy_match.name, score)
        return fuzzy_match, f"fuzzy_{score}"

    # 5) No match → create new folder using canonical name
    return library_root / canonical_name, "new"
```

### Auto-Suggest Aliases

When fuzzy matching succeeds, suggest an alias for future determinism:

```python
def suggest_alias(author_raw: str, matched_name: str, score: int) -> None:
    """Log a suggested alias for review."""
    suggestion = {
        "from": author_raw,
        "to": matched_name,
        "score": score,
        "timestamp": datetime.now().isoformat(),
    }

    # Append to suggestions file for later review
    suggestions_file = Path("data/author_alias_suggestions.json")
    suggestions = json.loads(suggestions_file.read_text()) if suggestions_file.exists() else []

    # Don't duplicate
    if not any(s["from"] == author_raw for s in suggestions):
        suggestions.append(suggestion)
        suggestions_file.write_text(json.dumps(suggestions, indent=2))
        logger.info(f"Suggested alias: '{author_raw}' → '{matched_name}'")
```

### Import Flow with ASIN-First Logic

```
New book: "Jake's Magical Market vol_04 (2025) (J.R. Mathews) {ASIN.B0NEW123}"

1. Check ASIN index: B0NEW123 not found → proceed to author resolution
2. Check aliases: "J.R. Mathews" not in author_aliases.yaml
3. Normalized match: normalize("J.R. Mathews") = "j r mathews"
   → Found! "j r mathews" maps to /audiobooks/J R Mathews/
4. Result: Book goes to /audiobooks/J R Mathews/Jake's Magical Market/ ✅

---

Existing book re-rip: "Jake's Magical Market vol_03 (2024) (J.R. Mathews) {ASIN.B0CX299KW4}"

1. Check ASIN index: B0CX299KW4 exists at /audiobooks/J R Mathews/...
2. ASIN-first: Use existing author folder "J R Mathews"
3. Skip all fuzzy logic entirely ✅
4. Result: Duplicate policy applied (skip/warn/overwrite)
```

### CLI: Author Audit Command

New command to report author folder variations:

```bash
mamfast audit-authors
```

Output:
```
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ Canonical      ┃ Variant        ┃ Similarity┃ Books Count  ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
│ J R Mathews    │ J.R. Mathews   │ 100 (norm)│ 4            │
│ Nekoko         │ Necoco         │ 89 (fuzzy)│ 1            │
│ Pirateaba      │ pirateaba      │ 100 (norm)│ 2            │
└────────────────┴────────────────┴───────────┴──────────────┘

Suggested actions:
  → Add to config/author_aliases.yaml:
    "J.R. Mathews": "J R Mathews"
    "Necoco": "Nekoko"
```

---

## Key Architectural Decisions

### Why Use Audiobookshelf API?

| Filesystem Parsing | ABS API |
|--------------------|---------|
| Complex ASIN regex (4+ eras) | API returns ASIN directly |
| Parse folder names for authors | API returns normalized author |
| Manual author merging | ABS already handles this |
| Fragile to naming changes | Stable API contract |
| Scan entire library (slow) | Paginated queries (fast) |

**ABS is already doing 80% of the work** - it indexes books, extracts metadata, normalizes authors, and handles library organization. Using the API means we get all this for free.

### Why Cache to SQLite?

| Direct API | SQLite Cache |
|------------|--------------|
| Network call per lookup | O(1) local lookup |
| Rate limit concerns | Unlimited queries |
| ABS must be online | Works offline |
| ~200ms per query | ~1ms per query |

**Decision:** ABS API → SQLite cache → Import operations

### Why Docker Path Mapping?

ABS typically runs in Docker with different mount paths than the host:

```
Container: /audiobooks/Brandon Sanderson/...
Host:      /mnt/user/data/audio/audiobooks/Brandon Sanderson/...
```

The `path_map` config translates paths so MAMFast can access files correctly.

### Why Separate Index from Import?

1. **Index phase** - fetch/cache ABS data (one-time, fast refresh)
2. **Import phase** - use cached data for placement decisions (ongoing)

This keeps import logic simple and enables duplicate checking without network calls.

---

## Implementation Notes

### v3.1 Simplifications

These decisions keep v3.1 scope manageable:

1. **Full rebuild indexing**
   - `abs-index` does `DELETE FROM books` then reinserts all
   - With ~1.3k books, full rebuild is <5 seconds
   - Incremental sync via `mtime_ms` is a future optimization

2. **Exactly one managed library**
   - If `auto_import=true`, exactly one library must have `mamfast_managed: true`
   - Multiple managed libraries → config validation error
   - Explicit `--library-id` flag could be added later

3. **ASIN is the only dedupe key**
   - Legacy books without ASIN are not dedupe-checked
   - This is documented as a known limitation

4. **Primary author only**
   - Multi-author books store only the first author
   - 99%+ of audiobooks have one primary author
   - Future enhancement: junction table

### Pre-flight Checks

```python
def validate_import_prerequisites(settings: Settings) -> None:
    """Fail fast with clear errors before import."""

    # 1. Index must exist
    if not settings.abs_index_path.exists():
        raise ConfigError(
            "Index not found. Run 'mamfast abs-index' first."
        )

    # 2. Same filesystem check (required for hardlinks)
    staging_dev = os.stat(settings.staging_root).st_dev
    library_dev = os.stat(settings.library_root).st_dev
    if staging_dev != library_dev:
        raise ConfigError(
            f"Staging ({settings.staging_root}) and library "
            f"({settings.library_root}) must be on same filesystem "
            "for hardlinks to work."
        )

    # 3. Exactly one managed library
    managed = [lib for lib in settings.abs_libraries if lib.mamfast_managed]
    if len(managed) != 1:
        raise ConfigError(
            f"Expected exactly 1 mamfast_managed library, found {len(managed)}"
        )
```

### Path Mapping: Longest Prefix Wins

When multiple path_map entries could match, use longest prefix:

```python
def abs_path_to_host(abs_path: str, path_maps: list[dict]) -> Path:
    """Convert ABS container path to host path.

    Uses longest matching prefix for nested mount scenarios.
    """
    # Sort by container prefix length (longest first)
    sorted_maps = sorted(
        path_maps,
        key=lambda m: len(m["container"]),
        reverse=True,
    )

    for mapping in sorted_maps:
        if abs_path.startswith(mapping["container"]):
            return Path(
                abs_path.replace(mapping["container"], mapping["host"], 1)
            )

    raise ValueError(f"No path mapping found for: {abs_path}")
```

### Author Report Caveats

The `abs-report-authors` command shows cases where `author_display != author_folder`. However:

> ⚠️ **ABS might be wrong.** Audible metadata is inconsistent. If your folder says "Nekoko" and ABS says "Necoco", your folder might actually be correct.

**Recommendation:** Review the report before making changes. The report shows discrepancies; it doesn't tell you which side is right.

Future enhancement: `--trust-folders` flag that assumes folder names are canonical and flags ABS entries that differ.

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025-12-03 | Initial planning document |
| 1.1.0 | 2025-12-03 | Added Smart ASIN Extraction section |
| 1.2.0 | 2025-12-03 | Added Library Analysis Report with fuzzy author matching |
| 1.3.0 | 2025-12-03 | Enhanced author matching: 4-layer resolution, aliases, ASIN-first logic |
| 2.0.0 | 2025-12-03 | Major restructure: Index-first architecture with SQLite |
| 2.1.0 | 2025-12-03 | Added Audnex Author API integration for canonical name resolution |
| 3.0.0 | 2025-12-03 | Major pivot: Use Audiobookshelf API as source of truth |
| 3.1.0 | 2025-12-03 | Document cleanup: unified config, answered open questions, marked legacy sections |
| 3.2.0 | 2025-12-03 | Addressed reviewer feedback: schema consolidation, API resilience, implementation notes |
| 3.3.0 | 2025-12-03 | Final review fixes: enum conflicts, cross-FS policy, path mapping, CLI consistency |
| **3.3.1** | **2025-12-03** | **Final cleanup: removed VALIDATED from results, added test fixtures, author_variants rebuild note** |

### Version 3.3.1 Changes (Final Cleanup)

- Fixed `ImportStatus.VALIDATED` → `ImportStatus.SUCCESS` for dry-run returns (VALIDATED only exists in ImportStage)
- Added Test Fixtures section with `tests/fixtures/abs_responses/` directory structure
- Added note that `author_variants` table is fully rebuilt on each sync (not incremental)
- Fixed `test_cross_device_fallback` → `test_cross_device_fails_validation` to match policy

### Version 3.3.0 Changes (Final Review)

Based on second round of detailed reviews:

**Enum & Type Fixes:**
- Renamed pipeline stages enum to `ImportStage` (was conflicting `ImportStatus`)
- `ImportStatus` (SUCCESS/SKIPPED/FAILED/DUPLICATE) is now the only result enum
- Changed all `ImportStatus.COMPLETE` references to `ImportStatus.SUCCESS`
- Added `SyncResult` dataclass for `sync_from_abs()` return type

**Cross-Filesystem Policy:**
- Removed contradictory EXDEV fallback code from `import_file()`
- Cross-filesystem imports are NOT supported in v3.1 (enforced by pre-flight check)
- Clear note that this protects hardlinks required for seeding

**Path Mapping:**
- Consolidated to single canonical implementation using longest-prefix matching
- Renamed functions: `abs_path_to_host()`, `host_path_to_abs()`
- Moved to dedicated module: `utils/abs_paths.py`

**CLI Consistency:**
- Fixed "Importing 2" header → "Processing 3" to match actual items
- Added `args.paths` handling to `cmd_abs_import()` for selective imports
- Fixed phantom `extract_asin_from_folder()` → `extract_asin()`
- Added scan trigger status to CLI output examples

**Documentation Improvements:**
- Added "Key Path Definitions" table: `library_root`, `staging_root`, `author_folder`
- Clarified `author_folder` source: MAM folder for new imports, disk for existing
- Added path length caveat (Linux 255-char limit per component)
- Added scan trigger behavior table with CLI output examples
- Closed unclosed code fence in AbsClient section
- Added `abs_version` source note (optional, from API headers)

### Version 3.2.0 Changes (Reviewer Feedback)

Based on detailed reviews from Claude and ChatGPT:

**Schema & Model Fixes:**
- Consolidated `books` table to single canonical schema with all fields (`subtitle`, `mtime_ms`, `size_bytes`)
- Consolidated `AbsBookRecord` to single definition with multi-author note
- Fixed `import_source` references → now correctly refers to `import_log` table
- Added `ImportStatus` enum and `ImportResult` dataclass
- Added `index_meta` table for tracking `last_full_sync`, `abs_version`
- Documented `import_log.status` valid values: `success`, `skipped`, `failed`, `duplicate`

**API Resilience:**
- Added `httpx.HTTPTransport(retries=max_retries)` to `AbsClient`
- Documented ABS unavailable behavior: fail index, warn on scan trigger failure
- Added `trigger_scan_safe()` example for graceful degradation
- Added pagination note for `limit=0` behavior

**Config Improvements:**
- Expanded `trigger_scan` to support modes: `none`, `batch`, `immediate`
- Documented `force=0` vs `force=1` scan behavior
- Added `seed_root` naming clarification note (legacy name for staging)

**New Implementation Notes Section:**
- v3.1 simplifications: full rebuild indexing, single managed library, ASIN-only dedupe
- Pre-flight validation code: index exists, same filesystem, exactly one managed library
- Path mapping: longest prefix wins algorithm
- Author report caveats: ABS might be wrong, review before acting

**CLI Example Fixes:**
- Fixed Project Hail Mary inconsistency (was "Exists" in dry-run, then "Imported")
- Fixed "Importing 2" but "3 imported" mismatch

### Version 3.1.0 Changes (Doc Cleanup)

- **Unified config keys:** `abs:` for API/connection, `audiobookshelf:` for import behavior
- **Answered open questions:**
  - Auto-import timing: run immediately (seedvault handles seeding)
  - qBittorrent path: no update needed (seedvault stays put)
  - ABS rescan: yes, trigger via `POST /api/libraries/{id}/scan?force=0`
  - First-run: fail fast with clear error if `auto_import=true` but `abs_index.db` missing
- **Marked sections as optional/internal:**
  - Smart ASIN Extraction → labeled as "internal helper used by abs-index"
  - Audnex Author API → labeled as "NOT IN v3.1 — Future Enhancement Only"
  - Smart Author Folder Resolution → labeled as "NOT IN v3.1 — Future Enhancement"
- **Removed v2.x author merge logic from core:**
  - Removed `merge_authors`, `create_alias`, `AuthorSource`, `ConflictStatus` from AbsIndex API
  - Removed "Integration in Author Resolution" section with 5-layer merge logic
  - v3.1 is report-only: `abs-report-authors` shows variants, user fixes manually
- **Fixed import diagram wording:** "author from folder name" (not "canonical from ABS")
- **Removed legacy CLI commands from main flow:**
  - `review-authors`, `apply-author-merges` → not in v3.x (report-only approach)
  - `index-library` → renamed to `abs-index`
- **Updated database path:** `data/abs_index.db` (was `mamfast.db`)
- **Updated Table of Contents:** section names now reflect markers

### Version 3.0.0 Changes

- **Architecture pivot:** Use ABS API instead of filesystem parsing
- **New data flow:** ABS API → SQLite cache → Import operations
- **Docker path mapping:** Translate container paths to host paths
- **New config structure:**
  - `abs.base_url` - Audiobookshelf server URL
  - `abs.api_token` - Bearer token for authentication
  - `abs.docker_mode` - Enable path translation
  - `abs.libraries[].path_map` - Container ↔ host path mappings
- **New CLI commands:**
  - `mamfast abs-init` - Validate connectivity, list libraries
  - `mamfast abs-index` - Build SQLite index from ABS API
  - `mamfast abs-check-duplicate --asin BXXX` - Quick duplicate check
- **Simplified phases:**
  - Phase 0a: ABS Client & Path Mapping (3-4 hrs)
  - Phase 0b: ABS Indexer (SQLite) (4-5 hrs)
  - Phase 0c: Author Variant Reporting (2-3 hrs)
  - Phase 1: ABS Import (4-5 hrs)
  - Phase 2: Polish (2-3 hrs)
- **Reduced effort:** 15-20 hours (was 19-24) by leveraging ABS
- **Removed:** Complex filesystem parsing, author merge workflow, Audnex author lookup (ABS already normalizes)

### Version 2.1.0 Changes

- **New section:** Audnex Author API documentation
- **5-layer author resolution:** Added Audnex API lookup as layer 5
- **New features:**
  - `lookup_author_from_audnex(name)` - search Audnex for canonical author name
  - Author response caching (`data/audnex_author_cache.json`)
  - `--no-audnex` flag to skip API lookups
- **New config options:**
  - `audiobookshelf.use_audnex_authors` - enable/disable API lookups
  - `audiobookshelf.audnex_cache_ttl` - cache duration in days
- **Updated Phase 1 estimate:** 5-6 hours (was 4-5)
- **Total estimated effort:** 19-24 hours (was 18-23)

---

## Appendix: Legacy Changelog (v2.x)

> The following versions document approaches that have been **superseded by v3.x**. They are preserved for historical reference.

### Version 2.0.0 Changes (Historical - Superseded by v3.x)

- **New architecture:** "Index first, normalize, then import"
- **SQLite as primary storage:** `data/mamfast.db` replaces JSON state files
- **New database schema:** `authors`, `series`, `books`, `author_conflicts`, `author_aliases`, `merge_history`
- **New CLI commands (legacy - use v3.x equivalents):**
  - `mamfast index-library` → use `mamfast abs-index`
  - `mamfast audit-authors` → use `mamfast abs-report-authors`
  - `mamfast review-authors` - (not in v3.x)
  - `mamfast apply-author-merges` - (not in v3.x)
- **Restructured phases:**
  - Phase 0a: Library Indexer (5-6 hrs)
  - Phase 0b: Author Audit (3-4 hrs)
  - Phase 0c: Author Merge (3-4 hrs)
  - Phase 1: ABS Import + Audnex (5-6 hrs)
  - Phase 2: Polish (3-4 hrs)
- **Total estimated effort:** 19-24 hours (was 11-12)
