# Audiobookshelf Import

> **Document Version:** 1.0.0 | **Last Updated:** 2025-12-05 | **Status:** ✅ Feature Complete

The ABS import feature moves staged audiobooks from the MAM workflow into your Audiobookshelf library with duplicate detection, file renaming, and automatic library scanning.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Architecture Overview](#architecture-overview)
3. [CLI Commands](#cli-commands)
4. [Configuration](#configuration)
5. [Docker Path Mapping](#docker-path-mapping)
6. [Duplicate Detection](#duplicate-detection)
7. [File Operations](#file-operations)
8. [Edge Cases](#edge-cases)
9. [Reusable Components](#reusable-components)

---

## Quick Start

```bash
# 1. Validate ABS connection and list libraries
mamfast abs-init

# 2. Preview what would be imported
mamfast --dry-run abs-import

# 3. Import staged books to library
mamfast abs-import

# 4. Check if a specific ASIN exists
mamfast abs-check-duplicate B0DK9TS6D9
```

---

## Architecture Overview

### The Big Idea: Let ABS Do the Heavy Lifting

Instead of parsing the filesystem ourselves, **use Audiobookshelf's API as the source of truth**.

ABS already has:
- Libraries with root paths
- Library items (books) with **normalized authors, series, and metadata**
- Library files with `fullPath` pointing at real folders/files

### Simplified Workflow (v4.1)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      IMPORT WORKFLOW (SIMPLIFIED)                           │
│                                                                             │
│   mamfast abs-import                                                        │
│       ↓                                                                     │
│   Connect to ABS API → Build in-memory ASIN index (~200ms for 500 books)   │
│       ↓                                                                     │
│   Check duplicates → Move books → Rename files → Trigger ABS scan          │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Why In-Memory Index?

| Benefit | Description |
|---------|-------------|
| Always fresh data | Built from live ABS API each session |
| No setup needed | No pre-indexing step required |
| Fast lookups | ~200ms one-time build + ~1µs per lookup |

### Integrated MAM Workflow

```
Libation → Discovery → Staging → Hardlink to Seed → Torrent → qBittorrent → ABS Import
                                                                              ↑
                                                                    (this feature)
```

**Key points:**
- **ABS API as source of truth**: Duplicate detection via in-memory index
- **MAM folder names as source of truth for new imports**: Author/series from staging folder
- **Docker path mapping**: Translate container paths ↔ host paths
- **Atomic move**: Instant, preserves hardlinks to seed folder

---

## CLI Commands

### `abs-init` — Test Connection

```bash
mamfast abs-init
```

Validates ABS connection, lists discovered libraries, shows path mapping configuration.

**Example output:**
```
╭────────────────────────────────────────────── MAMFast ───────────────────────────────────────────────╮
│  Audiobookshelf Setup                                                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────╯

Step 1/3: Testing connection
  ✓ Connected as quentin

Step 2/3: Fetching libraries
  → Found 1 library

Libraries:
  • Audiobooks (lib_c1u6t4p45c35rf0nzd)
    Path: /audiobooks
    Books: 1287

Step 3/3: Validating path mappings
  ✓ Path mappings configured correctly
```

### `abs-import` — Import Staged Books

```bash
mamfast abs-import                      # Import all staged books
mamfast --dry-run abs-import            # Preview without importing
mamfast abs-import --duplicate-policy warn    # Warn but don't skip duplicates
mamfast abs-import --no-scan            # Skip ABS library scan after import
```

**Options:**
| Flag | Description |
|------|-------------|
| `--dry-run` | Preview changes without moving files (global flag) |
| `--duplicate-policy` | `skip` (default), `warn`, or `overwrite` |
| `--no-scan` | Don't trigger ABS library scan after import |

**Example dry-run output:**
```
Import Results

✓ Sword Art Online vol_16 (2025) (Reki Kawahara) {ASIN.B0DK9TS6D9} [H2OKing] (B0DK9TS6D9)
  ├─ Ready → Reki Kawahara/Sword Art Online/Sword Art Online vol_16 (2025)...
  ├─ Sword Art Online vol_16....m4b
  └─ Sword Art Online vol_16....cue

⏭ Project Hail Mary (2021) (Andy Weir) {ASIN.B08G9PRS1K} [H2OKing] (B08G9PRS1K)
  └─ Exists → /audiobooks/Andy Weir/Project Hail Mary/...

Step 5/5: Import complete
  [DRY RUN] Would import 2 book(s)
  →   • 1 duplicate(s) would be skipped
```

### `abs-check-duplicate` — Quick ASIN Lookup

```bash
mamfast abs-check-duplicate B0DK9TS6D9
```

**Example output:**
```
Checking ASIN: B0DK9TS6D9

⏭ Exists in library:
  Title: Sword Art Online, Volume 16
  Author: Reki Kawahara
  Path: /audiobooks/Reki Kawahara/Sword Art Online/...
```

---

## Configuration

### Required Configuration

```yaml
# config/config.yaml

audiobookshelf:
  enabled: true
  host: "https://audiobookshelf.domain.com"
  api_key: "${ABS_API_KEY}"  # From .env file

  # Library configuration
  library_id: "lib_c1u6t4p45c35rf0nzd"  # Get from abs-init

  # Path mapping (if ABS runs in Docker)
  path_mappings:
    - container: "/audiobooks"
      host: "/mnt/user/data/audio/audiobooks"

  # Import settings
  import_settings:
    source_path: "/mnt/user/data/audio/audiobook-import"  # Staging directory
    duplicate_policy: "skip"   # skip, warn, or overwrite
    trigger_scan: "batch"      # none, batch, or immediate
```

### Environment Variables

```bash
# config/.env
ABS_API_KEY=your_api_key_here
```

### Key Path Definitions

| Config Key | Purpose | Example |
|------------|---------|---------|
| `import_settings.source_path` | Staging directory (input) | `/mnt/user/data/audio/audiobook-import` |
| `path_mappings[].host` | ABS library root (output) | `/mnt/user/data/audio/audiobooks` |
| Seed folder | Hardlink target (MAM config) | `/mnt/user/data/audio/seedvault` |

**Requirement:** Staging, library, and seed folder must be on the **same filesystem** for atomic moves and hardlink preservation.

---

## Docker Path Mapping

### The Problem

ABS runs in Docker and sees paths like `/audiobooks/Author/Series/Book/`.
MAMFast runs on the host and sees `/mnt/user/data/audio/audiobooks/Author/Series/Book/`.

### Configuration

```yaml
audiobookshelf:
  path_mappings:
    - container: "/audiobooks"
      host: "/mnt/user/data/audio/audiobooks"
```

### Same-Container Mode

If MAMFast runs inside the same container as ABS (or shares the same mounts):

```yaml
audiobookshelf:
  path_mappings: []  # No mapping needed
```

### Path Mapping Logic

Uses **longest-prefix matching** for nested mount scenarios:

```python
def abs_path_to_host(abs_path: str, path_maps: list[dict]) -> Path:
    """Convert ABS container path to host path."""
    # Sort by container prefix length (longest first)
    sorted_maps = sorted(path_maps, key=lambda m: len(m["container"]), reverse=True)

    for mapping in sorted_maps:
        if abs_path.startswith(mapping["container"]):
            return Path(abs_path.replace(mapping["container"], mapping["host"], 1))

    return Path(abs_path)  # Fallback: assume host-visible
```

---

## Duplicate Detection

### In-Memory ASIN Index

The import workflow builds an **in-memory dictionary** from the ABS API each session:

```python
@dataclass
class AsinEntry:
    """Lightweight record for duplicate detection."""
    asin: str                    # "B0DK9TS6D9"
    path: str                    # Host path to book folder
    library_item_id: str         # ABS "li_xxx" ID
    title: str | None            # For display
    author: str | None           # For display

# Built once per session
asin_index: dict[str, AsinEntry] = build_asin_index(client, library_id)

# O(1) duplicate check
exists, entry = asin_exists(asin_index, "B0DK9TS6D9")
```

### Performance

| Library Size | API Fetch Time | Memory Usage |
|--------------|----------------|--------------|
| 100 books | ~50ms | ~50KB |
| 500 books | ~200ms | ~250KB |
| 2000 books | ~800ms | ~1MB |

### ASIN Extraction

Handles multiple naming formats from different import eras:

| Format | Pattern | Example |
|--------|---------|---------|
| **Current** | `{ASIN.B0xxx}` | `{ASIN.B0DK9TS6D9}` |
| **Old Bracket** | `[ASIN.B0xxx]` | `[ASIN.B0DK9TS6D9]` |
| **Bare Bracket** | `[B0xxxxxxxx]` | `[B0DK9TS6D9]` |
| **Fallback** | `B0xxxxxxxx` | `B0DK9TS6D9` |

---

## File Operations

### Atomic Move

Since staging and library are on the same filesystem, we use **atomic move** (rename):

```python
def import_file(source: Path, dest: Path) -> None:
    """Atomic move - instant, preserves hardlinks."""
    source.rename(dest)
```

**Benefits:**
- ✅ Instant (no data copy)
- ✅ Preserves hardlinks to seed folder
- ✅ Torrents keep seeding from new location

### Hardlink Preservation

```
BEFORE IMPORT:
  Staging: /staging/Book/book.m4b  ──┐
  Seed:    /seedvault/Book/book.m4b ─┴── (same inode)

AFTER ATOMIC MOVE:
  Library: /audiobooks/Author/Series/Book/book.m4b ──┐
  Seed:    /seedvault/Book/book.m4b ─────────────────┴── (same inode!)
```

### File Renaming

Files are renamed to match the cleaned folder name:

```
Original: If the Villainess... Vol. 1 vol_01 (2025)....m4b
Cleaned:  If the Villainess... vol_01 (2025)....m4b
```

The `build_clean_file_name()` function normalizes:
- `Vol. X` → `vol_XX` (duplicate volume indicators removed)
- Consistent formatting across `.m4b`, `.cue`, `.jpg`, `.metadata.json`

---

## Edge Cases

### Folder Name Doesn't Match Pattern

Non-MAM folders in staging are skipped with a warning. They go to `Unknown/` folder.

### No ASIN in Folder Name

Books without `{ASIN.xxx}` pattern:
- Skipped from duplicate detection
- Imported to `Unknown/{title}` folder
- Warning logged

### Standalone vs Series

Books without `vol_XX` are detected as standalone:
- Use 2-level structure: `Author/Title/`
- No series subfolder

### Author Name Variations

The importer matches existing author folders using normalized comparison:
- `J.R. Mathews` matches existing `J R Mathews/`
- Case-insensitive matching

### Cross-Filesystem Import

**Not supported.** Pre-flight validation fails if staging and library are on different filesystems. This protects hardlinks required for seeding.

---

## Reusable Components

### Existing Modules Used

| Module | Import | Use For |
|--------|--------|---------|
| `utils/retry.py` | `retry_with_backoff, NETWORK_EXCEPTIONS` | ABS API calls |
| `utils/naming.py` | `build_mam_folder_name, build_mam_file_name` | Path building |
| `console.py` | `print_step, print_success, print_error` | CLI output |
| `schemas/abs.py` | Pydantic models | ABS API validation |

### ABS-Specific Modules

| Module | Purpose |
|--------|---------|
| `abs/client.py` | ABS API client with caching |
| `abs/asin.py` | ASIN extraction, in-memory index |
| `abs/importer.py` | Import workflow, folder parsing |
| `abs/paths.py` | Container ↔ host path mapping |

---

## Related Documentation

- [AUDIOBOOKSHELF_API.md](AUDIOBOOKSHELF_API.md) - ABS API reference
- [AUDIOBOOKSHELF_FUTURE.md](AUDIOBOOKSHELF_FUTURE.md) - Future enhancements (Audnex, Smart Author Resolution)
- [AUDIOBOOKSHELF_REFERENCE.md](AUDIOBOOKSHELF_REFERENCE.md) - Testing strategy, changelog
