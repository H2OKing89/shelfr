# Shelfr Development Scripts

Collection of standalone utilities for data gathering, analysis, and development.

## Directory Structure

```bash
scripts/
├── data_gathering/     Data collection from ABS/Audnex/filesystem
├── analysis/           Test data analysis and reporting
├── dev_tools/          Debugging and utility tools
└── README.md           This file
```

---

## 📊 Data Gathering

### `fetch_test_data.py`

**Purpose:** Fetch comprehensive test data from Audiobookshelf + Audnex API.

**Features:**

- Async HTTP/2 fetching with rate limiting
- SSL verification and proper error handling
- JSON schema headers with generation metadata
- Saves to `samples/test_data/` (gitignored)

**Output Files:**

- `abs_library.json` - Extracted ABS metadata
- `audnex_metadata.json` - Audnex API responses by ASIN
- `combined_metadata.json` - Combined view for easy lookup

**Usage:**

```bash
python scripts/data_gathering/fetch_test_data.py
```

**Requirements:**

- `config/.env` with `AUDIOBOOKSHELF_HOST` and `AUDIOBOOKSHELF_API_KEY`

---

### `scan_abs_library.py`

**Purpose:** Filesystem scanner for audiobook library structure analysis.

**Features:**

- Recursive folder scanning with component detection (ASIN, year, volume, etc.)
- MediaInfo extraction (codec, bitrate, duration)
- Async processing with configurable workers
- Rich progress display

**Output:** `samples/abs_library_scan.json` with filesystem + MediaInfo data

**Usage:**

```bash
python scripts/data_gathering/scan_abs_library.py
```

---

### `build_golden_samples.py`

**Purpose:** Build golden test fixtures from ABS + Audnex for unit tests.

**Features:**

- Fetches specific set of books for test fixtures
- Filters by criteria (series, authors, etc.)
- Rate-limited Audnex requests

**Output:** `tests/golden/` test fixtures

**Usage:**

```bash
python scripts/data_gathering/build_golden_samples.py
python scripts/data_gathering/build_golden_samples.py --limit 50
python scripts/data_gathering/build_golden_samples.py --output custom.json
```

---

## 📈 Analysis

### `analyze_test_data.py`

**Purpose:** CLI tool to analyze test data collected by `fetch_test_data.py`.

**Commands:**

- `duplicates` - Find books with duplicate series entries
- `variants` - Show books with different primary/secondary series
- `missing` - List books without Audnex metadata
- `stats` - Show summary statistics
- `search <query>` - Search by title/author/ASIN

**Usage:**

```bash
python scripts/analysis/analyze_test_data.py duplicates
python scripts/analysis/analyze_test_data.py search "Project Hail Mary"
python scripts/analysis/analyze_test_data.py stats
```

**Supports:** Both new schema format (with `_schema` header) and legacy flat arrays

---

## 🔍 Dev Tools

### `find_audnex_book.py`

**Purpose:** Quick ASIN lookup across multiple Audnex regions.

**Features:**

- Multi-region queries (US, UK, CA, AU, etc.)
- Optional `--seed-authors` and `--update` flags
- Rich table output with region comparison

**Usage:**

```bash
python scripts/dev_tools/find_audnex_book.py B0FDCW8SS7
python scripts/dev_tools/find_audnex_book.py B0FDCW8SS7 --regions us,uk,ca
python scripts/dev_tools/find_audnex_book.py B0FDCW8SS7 --seed-authors --update
```

---

### `test_bbcode.py`

**Purpose:** Test BBCode rendering from Audnex data for MAM descriptions.

**Features:**

- HTML-to-BBCode conversion testing
- Full description rendering with preview
- Audnex data fetch and cache

**Usage:**

```bash
python scripts/dev_tools/test_bbcode.py
# Interactive prompts for ASIN and testing options
```

---

### `fetch_api_docs.py`

**Purpose:** Automatically pull and sync API documentation from external sources.

**Features:**

- Fetches Audiobookshelf API docs from GitHub repository
- Fetches Audnex API OpenAPI specification
- Smart update detection using SHA256 hashes
- HTTP/2 with SSL verification for secure downloads
- Beautiful over-the-top rich terminal output with progress bars
- Metadata tracking (last updated, file hashes, sizes)
- Selective fetching (ABS only, Audnex only, or both)

**Sources:**

- **Audiobookshelf:** Official API documentation files from GitHub
  - `books.md`, `libraries.md`, `podcasts.md`, `series.md`, `authors.md`, etc.
- **Audnex:** OpenAPI 3.0 specification and API spec JSON

**Output:** `docs/audiobookshelf/api/` and `docs/audnex/api/`

**Usage:**

```bash
# Fetch with smart update checks (only downloads if changed)
python scripts/dev_tools/fetch_api_docs.py

# Force fetch everything (skip hash checks)
python scripts/dev_tools/fetch_api_docs.py --force

# Only fetch Audiobookshelf docs
python scripts/dev_tools/fetch_api_docs.py --abs-only

# Only fetch Audnex docs
python scripts/dev_tools/fetch_api_docs.py --audnex-only
```

**Output:**

- Saves docs to `docs/audiobookshelf/api/` and `docs/audnex/api/`
- Creates `.api_docs_metadata.json` with:
  - Last fetch timestamps
  - SHA256 hashes for change detection
  - File sizes and descriptions
  - ETag values for HTTP caching

---

## Schema Format

All data gathering scripts now use standardized JSON schema headers:

```json
{
  "_schema": {
    "version": "1.0.0",
    "generated_at": "2025-12-28T17:58:00Z",
    "data_type": "combined_metadata",
    "record_count": 1330,
    "source": "Audiobookshelf + Audnex",
    "description": "Combined ABS and Audnex metadata for each book",
    "tool": "Shelfr/fetch_test_data.py"
  },
  "items": [...]
}
```

**Benefits:**

- Track when data was generated
- Know the source and format version
- Easy to identify stale data
- Version migration support

---

## Development Workflow

**1. Collect Test Data:**

```bash
python scripts/data_gathering/fetch_test_data.py
```

**2. Analyze for Edge Cases:**

```bash
python scripts/analysis/analyze_test_data.py duplicates
python scripts/analysis/analyze_test_data.py variants
```

**3. Debug Specific Issues:**

```bash
# Find Audnex metadata for an ASIN
python scripts/dev_tools/find_audnex_book.py B0FDCW8SS7

# Test BBCode rendering
python scripts/dev_tools/test_bbcode.py
```

**4. Build Test Fixtures:**

```bash
python scripts/data_gathering/build_golden_samples.py
```

---

## Dependencies

Most scripts use minimal dependencies for easy standalone use:

- `httpx` - HTTP client with HTTP/2 support
- `python-dotenv` - Config loading
- `rich` - Terminal output formatting

Heavy dependencies (like full Shelfr stack) are only needed for specific scripts.

---

## Best Practices

1. **Always re-fetch test data** after major library changes
2. **Check schema version** when loading old data files
3. **Use rate limiting** for Audnex requests (10/sec max)
4. **Respect gitignore** - test_data/ should never be committed
5. **Update this README** when adding new scripts
