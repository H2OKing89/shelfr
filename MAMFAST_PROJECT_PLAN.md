# MAM Fast Upload Tool — Project Plan

> **Goal**: Automate the full pipeline from Libation audiobook acquisition → MAM-compliant staging → torrent creation → qBittorrent seeding, with metadata enrichment from Audnex and MediaInfo.

---

## 1. End-to-End Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              MAMFAST PIPELINE                               │
└─────────────────────────────────────────────────────────────────────────────┘

  ┌──────────────┐
  │  1. ACQUIRE  │  docker exec libation libationcli scan
  └──────┬───────┘
         │
         ▼
  ┌──────────────┐
  │  2. DISCOVER │  Scan library root, diff against processed state
  └──────┬───────┘  → yields list of AudiobookRelease objects
         │
         ▼
  ┌──────────────┐
  │  3. STAGE    │  Per release:
  └──────┬───────┘    • Create upload workspace dir
         │            • Hardlink .m4b, .jpg, .pdf, .cue
         │            • Truncate filenames to ≤225 chars (MAM limit)
         │
         ▼
  ┌──────────────┐
  │  4. METADATA │  Per release:
  └──────┬───────┘    • Query api.audnex.us (by ASIN) → audnex.json
         │            • Run mediainfo --Output=JSON   → mediainfo.json
         │
         ▼
  ┌──────────────┐
  │  5. TORRENT  │  docker run mkbrr create --preset mam <staging_dir>
  └──────┬───────┘  → outputs .torrent to torrent output dir
         │
         ▼
  ┌──────────────┐
  │  6. UPLOAD   │  qbittorrent-api: add torrent, set save_path to
  └──────┬───────┘  hardlinked staging dir, apply category/tags
         │
         ▼
  ┌──────────────┐
  │  7. RECORD   │  Mark release as processed in state store
  └──────────────┘  (prevents re-processing on next run)
```

---

## 2. Project Layout

```
mamfast/
├── pyproject.toml            # Project metadata, dependencies, entry points
├── README.md
├── .env.example              # Template for secrets
├── config.yaml.example       # Template for settings
│
├── src/
│   └── mamfast/
│       ├── __init__.py
│       ├── cli.py            # argparse/click CLI entrypoint
│       ├── config.py         # Load .env + config.yaml → typed Settings object
│       ├── logging_setup.py  # Structured logging (file + console)
│       │
│       ├── models.py         # Dataclasses: AudiobookRelease, TorrentJob, etc.
│       │
│       ├── libation.py       # docker exec libationcli scan
│       ├── discovery.py      # Scan library, detect new books, return releases
│       ├── hardlinker.py     # Create staging dir, hardlink files, rename
│       ├── metadata.py       # Audnex API client + mediainfo wrapper
│       ├── mkbrr.py          # Docker wrapper for mkbrr (from your existing script)
│       ├── qbittorrent.py    # qbittorrent-api wrapper
│       │
│       ├── workflow.py       # Orchestration: full_run(), prepare_only(), etc.
│       │
│       └── utils/
│           ├── __init__.py
│           ├── naming.py     # Filename sanitization + 225-char truncation
│           ├── paths.py      # Host ↔ container path mapping helpers
│           └── state.py      # Processed books state (JSON or SQLite)
│
├── data/
│   └── processed.json        # State: already-processed ASINs/paths
│
├── logs/
│   └── mamfast.log
│
└── tests/
    ├── __init__.py
    ├── test_discovery.py
    ├── test_hardlinker.py
    ├── test_naming.py
    └── ...
```

---

## 3. Configuration Strategy

### 3.1 `.env` — Secrets & Endpoints (never commit)

```bash
# ─────────────────────────────────────────────────────────────────────────────
# Docker / Libation
# ─────────────────────────────────────────────────────────────────────────────
LIBATION_CONTAINER=libation
DOCKER_BIN=/usr/bin/docker

# ─────────────────────────────────────────────────────────────────────────────
# qBittorrent
# ─────────────────────────────────────────────────────────────────────────────
QB_HOST=http://10.1.60.10:8080
QB_USERNAME=admin
QB_PASSWORD=supersecret

# ─────────────────────────────────────────────────────────────────────────────
# MAM
# ─────────────────────────────────────────────────────────────────────────────
MAM_ANNOUNCE_URL=https://t.myanonamouse.net/announce/your-key-here

# ─────────────────────────────────────────────────────────────────────────────
# Environment
# ─────────────────────────────────────────────────────────────────────────────
MAMFAST_ENV=production
LOG_LEVEL=INFO
```

### 3.2 `config.yaml` — Paths & Behavior (can commit with example values)

```yaml
# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────
paths:
  # Where Libation stores downloaded audiobooks
  libation_library_root: "/mnt/user/data/audio/LibationLibrary"
  
  # Where we hardlink + stage releases for upload
  staging_root: "/mnt/user/data/mam-staging"
  
  # Where .torrent files are written
  torrent_output: "/mnt/user/data/torrents/mamfast"
  
  # qBittorrent seed directory (save_path for added torrents)
  seed_root: "/mnt/user/data/downloads/torrents/qbittorrent/seedvault/mam"
  
  # State file for tracking processed releases
  state_file: "./data/processed.json"
  
  # Log file
  log_file: "./logs/mamfast.log"

# ─────────────────────────────────────────────────────────────────────────────
# MAM Compliance
# ─────────────────────────────────────────────────────────────────────────────
mam:
  max_filename_length: 225
  allowed_extensions:
    - ".m4b"
    - ".jpg"
    - ".jpeg"
    - ".png"
    - ".pdf"
    - ".cue"

# ─────────────────────────────────────────────────────────────────────────────
# mkbrr Docker Settings
# ─────────────────────────────────────────────────────────────────────────────
mkbrr:
  image: "ghcr.io/autobrr/mkbrr:latest"
  preset: "mam"
  
  # Path mapping: how host paths appear inside the mkbrr container
  host_data_root: "/mnt/user/data"
  container_data_root: "/data"
  
  # mkbrr config directory mapping
  host_config_dir: "/mnt/cache/appdata/mkbrr"
  container_config_dir: "/root/.config/mkbrr"

# ─────────────────────────────────────────────────────────────────────────────
# qBittorrent Behavior
# ─────────────────────────────────────────────────────────────────────────────
qbittorrent:
  category: "mam-audiobooks"
  tags:
    - "mamfast"
    - "auto-upload"
  auto_start: true
  
# ─────────────────────────────────────────────────────────────────────────────
# Audnex API
# ─────────────────────────────────────────────────────────────────────────────
audnex:
  base_url: "https://api.audnex.us"
  timeout_seconds: 30

# ─────────────────────────────────────────────────────────────────────────────
# MediaInfo
# ─────────────────────────────────────────────────────────────────────────────
mediainfo:
  binary: "mediainfo"  # or full path: /usr/bin/mediainfo
```

---

## 4. Core Data Models

```python
# src/mamfast/models.py
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from enum import Enum, auto

class ReleaseStatus(Enum):
    DISCOVERED = auto()
    STAGED = auto()
    TORRENT_CREATED = auto()
    UPLOADED = auto()
    COMPLETE = auto()
    FAILED = auto()

@dataclass
class AudiobookRelease:
    """Represents a single audiobook ready for processing."""
    
    # Identity
    asin: Optional[str]          # Audible ASIN (primary identifier)
    title: str
    author: str
    narrator: Optional[str] = None
    series: Optional[str] = None
    series_position: Optional[str] = None
    
    # Paths
    source_dir: Path = None      # Original Libation directory
    staging_dir: Path = None     # Hardlinked upload workspace
    main_m4b: Path = None        # Primary audiobook file
    
    # Files found
    files: list[Path] = field(default_factory=list)
    
    # Processing state
    status: ReleaseStatus = ReleaseStatus.DISCOVERED
    torrent_path: Optional[Path] = None
    
    # Metadata (populated later)
    audnex_metadata: Optional[dict] = None
    mediainfo_data: Optional[dict] = None


@dataclass  
class ProcessingResult:
    """Result of processing a single release."""
    release: AudiobookRelease
    success: bool
    error: Optional[str] = None
    torrent_path: Optional[Path] = None
```

---

## 5. Module Responsibilities

### 5.1 `config.py` — Configuration Loading

```python
# Loads .env via python-dotenv
# Loads config.yaml via PyYAML
# Exposes a typed Settings object (dataclass or pydantic model)
# Used by all other modules: from mamfast.config import settings
```

### 5.2 `libation.py` — Trigger Libation Scan

```python
def run_scan() -> subprocess.CompletedProcess:
    """Execute libationcli scan inside the Libation container."""
    # docker exec -it {container} libationcli scan
    # Returns completed process for exit code checking
```

### 5.3 `discovery.py` — Find New Audiobooks

```python
def scan_library() -> list[AudiobookRelease]:
    """Scan Libation library root, return all audiobook releases found."""

def get_new_releases() -> list[AudiobookRelease]:
    """Compare against processed state, return only unprocessed releases."""

def extract_asin(release_dir: Path) -> Optional[str]:
    """Extract ASIN from Libation's metadata or folder structure."""
```

### 5.4 `hardlinker.py` — Stage Releases for Upload

```python
def stage_release(release: AudiobookRelease) -> Path:
    """
    Create staging directory, hardlink allowed files, apply MAM naming rules.
    Returns path to staging directory.
    """

def hardlink_file(src: Path, dst: Path) -> None:
    """Create hardlink, handling cross-device fallback to copy."""

def should_include_file(path: Path) -> bool:
    """Check if file extension is in allowed list."""
```

### 5.5 `utils/naming.py` — MAM-Compliant Filenames

```python
def sanitize_filename(name: str) -> str:
    """Remove/replace illegal characters for filesystem + MAM."""

def truncate_filename(name: str, max_length: int = 225) -> str:
    """
    Intelligently truncate filename to max_length.
    Preserves extension, tries to keep author/title readable.
    """

def build_release_dirname(release: AudiobookRelease) -> str:
    """Build standardized directory name: 'Author - Title (Year)' format."""
```

### 5.6 `metadata.py` — Audnex + MediaInfo

```python
def fetch_audnex(asin: str) -> dict:
    """Query api.audnex.us/books/{asin}, return parsed JSON."""

def search_audnex(title: str, author: str) -> Optional[dict]:
    """Search Audnex by title/author if ASIN unknown."""

def save_audnex_json(data: dict, output_path: Path) -> None:
    """Write audnex.json to staging directory."""

def run_mediainfo(m4b_path: Path) -> dict:
    """Run mediainfo --Output=JSON, return parsed dict."""

def save_mediainfo_json(data: dict, output_path: Path) -> None:
    """Write mediainfo.json to staging directory."""
```

### 5.7 `mkbrr.py` — Torrent Creation

```python
def create_torrent(
    content_path: Path,
    output_path: Path,
    preset: str = "mam"
) -> Path:
    """
    Run mkbrr in Docker to create .torrent file.
    Handles host↔container path mapping.
    Returns path to created .torrent file.
    """

def map_to_container_path(host_path: Path) -> str:
    """Convert host path to container-visible path."""

def fix_permissions(torrent_path: Path) -> None:
    """Fix ownership after Docker creates file as root."""
```

### 5.8 `qbittorrent.py` — Upload to Client

```python
def get_client() -> qbittorrentapi.Client:
    """Create authenticated qBittorrent API client."""

def upload_torrent(
    torrent_path: Path,
    save_path: Path,
    category: str,
    tags: list[str],
    paused: bool = False
) -> None:
    """Add torrent to qBittorrent with specified settings."""

def check_existing(info_hash: str) -> bool:
    """Check if torrent already exists in client."""
```

### 5.9 `utils/state.py` — Track Processed Releases

```python
def load_state() -> dict:
    """Load processed.json state file."""

def save_state(state: dict) -> None:
    """Persist state to file."""

def is_processed(asin: str) -> bool:
    """Check if release has already been processed."""

def mark_processed(release: AudiobookRelease) -> None:
    """Add release to processed state."""
```

### 5.10 `workflow.py` — Orchestration

```python
def full_run() -> list[ProcessingResult]:
    """
    Complete pipeline:
    1. Libation scan
    2. Discover new releases  
    3. For each release: stage → metadata → torrent → upload → record
    """

def prepare_only() -> list[AudiobookRelease]:
    """Discover + stage releases without creating torrents."""

def create_torrents_only() -> list[Path]:
    """Create torrents for all staged but un-torrented releases."""

def upload_only() -> None:
    """Upload all .torrent files not yet in qBittorrent."""

def process_single(release: AudiobookRelease) -> ProcessingResult:
    """Process one release through the full pipeline."""
```

---

## 6. CLI Interface

```python
# src/mamfast/cli.py

Commands:
  mamfast scan           Run libationcli scan in Libation container
  mamfast discover       List new (unprocessed) audiobooks found
  mamfast prepare        Stage new audiobooks (hardlink + rename)
  mamfast metadata       Fetch Audnex + MediaInfo for staged releases
  mamfast torrent        Create .torrent files for staged releases
  mamfast upload         Upload torrents to qBittorrent
  mamfast run            Full pipeline: scan → discover → stage → metadata → torrent → upload
  mamfast status         Show processing status of all releases
  mamfast config         Print loaded configuration (debug)

Options:
  --dry-run             Show what would happen without making changes
  --verbose / -v        Increase log verbosity
  --config PATH         Use alternate config.yaml
  --release ASIN        Process specific release only
```

---

## 7. Logging Strategy

```python
# src/mamfast/logging_setup.py

- Console: INFO+ with colors (rich or colorlog)
- File: DEBUG+ with timestamps to logs/mamfast.log
- Per-release context: include ASIN/title in log messages
- Structured fields for later parsing if needed
```

Example output:
```
2024-01-15 10:23:45 | INFO  | [DISCOVER] Found 3 new releases
2024-01-15 10:23:46 | INFO  | [STAGE] Processing: Brandon Sanderson - Mistborn (B000SEI1RG)
2024-01-15 10:23:46 | DEBUG | [STAGE] Hardlinking: Mistborn.m4b → staging/Mistborn.m4b
2024-01-15 10:23:47 | INFO  | [MKBRR] Created torrent: Mistborn.torrent
2024-01-15 10:23:48 | INFO  | [UPLOAD] Added to qBittorrent: Mistborn.torrent
```

---

## 8. State Management

### `data/processed.json` structure:

```json
{
  "version": 1,
  "processed": {
    "B000SEI1RG": {
      "title": "Mistborn",
      "author": "Brandon Sanderson", 
      "processed_at": "2024-01-15T10:23:48Z",
      "staging_dir": "/mnt/user/data/mam-staging/Brandon Sanderson - Mistborn",
      "torrent_path": "/mnt/user/data/torrents/mamfast/Brandon Sanderson - Mistborn.torrent",
      "status": "complete"
    }
  },
  "failed": {
    "B00INVALID": {
      "title": "Unknown Book",
      "error": "ASIN not found in Audnex",
      "failed_at": "2024-01-15T10:25:00Z"
    }
  }
}
```

---

## 9. Error Handling Strategy

| Stage | Failure Mode | Handling |
|-------|--------------|----------|
| Libation scan | Container not running | Log error, exit with clear message |
| Discovery | Can't parse folder structure | Skip release, log warning, continue |
| Hardlink | Cross-device link | Fall back to copy, log info |
| Hardlink | Filename too long after truncation | Use hash suffix, log warning |
| Audnex | ASIN not found | Try search by title/author, or skip metadata |
| Audnex | API timeout/error | Retry 3x, then skip metadata with warning |
| MediaInfo | Binary not found | Log error, skip mediainfo step |
| mkbrr | Docker error | Log full error, mark release failed |
| qBittorrent | Connection refused | Retry 3x, then fail with clear message |
| qBittorrent | Torrent already exists | Skip upload, log info, mark complete |

---

## 10. Dependencies

```toml
# pyproject.toml
[project]
dependencies = [
    "python-dotenv>=1.0.0",
    "pyyaml>=6.0",
    "qbittorrent-api>=2024.1",
    "httpx>=0.27.0",          # or requests
    "rich>=13.0",             # nice console output
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov",
    "ruff",
    "mypy",
]
```

---

## 11. Implementation Status

| Module | Status | Description |
|--------|--------|-------------|
| `pyproject.toml` | ✅ Complete | Dependencies + `mamfast` CLI entry point |
| `.env.example` | ✅ Complete | All secrets template |
| `config.yaml.example` | ✅ Complete | All paths from mkbrr script |
| `config.py` | ✅ Complete | Loads .env + YAML into typed Settings |
| `models.py` | ✅ Complete | `AudiobookRelease`, `ProcessingResult` |
| `logging_setup.py` | ✅ Complete | Rich console + file logging |
| `libation.py` | ✅ Complete | `run_scan()` docker exec wrapper |
| `discovery.py` | ✅ Complete | Parses Libation folders + metadata.json |
| `mkbrr.py` | ✅ Complete | Refactored from original script (non-interactive) |
| `hardlinker.py` | ✅ Complete | Stage files with 225-char truncation |
| `metadata.py` | ✅ Complete | Audnex API + MediaInfo JSON output |
| `qbittorrent.py` | ✅ Complete | Upload via qbittorrent-api |
| `workflow.py` | ✅ Complete | `full_run()` orchestration |
| `cli.py` | ✅ Complete | All subcommands implemented |
| `utils/naming.py` | ✅ Complete | Filename sanitization + truncation |
| `utils/paths.py` | ✅ Complete | Host↔container path mapping |
| `utils/state.py` | ✅ Complete | `processed.json` tracking |

---

## 12. Open Questions / Future Enhancements

## 12. Open Questions / Future Enhancements

| # | Question | Status |
|---|----------|--------|
| 1 | **Libation folder structure** | ✅ Resolved: `Author/Series/Title vol_XX (Year) (Author) {ASIN.XXX} [Source]/` |
| 2 | **ASIN extraction** | ✅ Resolved: Regex from folder name `{ASIN.XXX}` + fallback to metadata.json |
| 3 | **mkbrr script** | ✅ Resolved: Refactored into `mkbrr.py` module |
| 4 | **Batch vs single mode** | ✅ Resolved: Batch by default, `--asin` flag for single |
| 5 | **MAM upload form** | 🔲 Future: Generate BBCode/description template |
| 6 | **Notifications** | 🔲 Future: Discord/Telegram alerts on completion/failure |

---

## 13. Implementation Complete

All phases have been implemented:

```
Phase 1: Foundation ✅
  ├─ config.py          ← Load .env + config.yaml
  ├─ logging_setup.py   ← Rich console + file logging
  └─ models.py          ← AudiobookRelease, ProcessingResult

Phase 2: Discovery ✅
  ├─ discovery.py       ← Scan library, parse Libation folders
  ├─ utils/state.py     ← Track processed releases
  └─ cli.py (discover)  ← mamfast discover [--all]

Phase 3: Staging ✅
  ├─ utils/naming.py    ← Filename sanitization + truncation
  ├─ hardlinker.py      ← Hardlink files to staging
  └─ cli.py (prepare)   ← mamfast prepare [--asin]

Phase 4: Metadata ✅
  ├─ metadata.py        ← Audnex API + MediaInfo
  └─ cli.py (metadata)  ← mamfast metadata

Phase 5: Torrent ✅
  ├─ mkbrr.py           ← Refactored Docker wrapper
  └─ cli.py (torrent)   ← mamfast torrent [--preset]

Phase 6: Upload ✅
  ├─ qbittorrent.py     ← qBittorrent API wrapper
  └─ cli.py (upload)    ← mamfast upload [--paused]

Phase 7: Integration ✅
  ├─ workflow.py        ← Full pipeline orchestration
  └─ cli.py (run)       ← mamfast run [--skip-scan] [--skip-metadata]
```

---

## 14. Getting Started

## 14. Getting Started

```bash
# 1. Extract the project
unzip mamfast.zip
cd mamfast

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -e ".[dev]"

# 4. Configure
cp .env.example .env
cp config.yaml.example config.yaml
# Edit both files with your settings

# 5. Test configuration
mamfast config

# 6. Discover audiobooks
mamfast discover --all

# 7. Run full pipeline
mamfast run
```
