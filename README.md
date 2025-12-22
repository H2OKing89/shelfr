<div align="center">

# 🎧 MAMFast

**Fast MAM audiobook upload automation tool**

<p>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License: MIT"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/code%20style-ruff-000000.svg" alt="Code style: ruff"></a>
  <a href="https://coderabbit.ai"><img src="https://img.shields.io/coderabbit/prs/github/H2OKing89/mam_tool?utm_source=oss&utm_medium=github&utm_campaign=H2OKing89%2Fmam_tool&labelColor=171717&color=FF570A&label=CodeRabbit+Reviews" alt="CodeRabbit Pull Request Reviews"></a>
</p>

<p>
  <strong>Automates the pipeline from Libation audiobook downloads to MAM-ready torrents seeding in qBittorrent</strong>
</p>

<p>
  <a href="#-features">Features</a> •
  <a href="#-pipeline">Pipeline</a> •
  <a href="#-installation">Installation</a> •
  <a href="#-usage">Usage</a> •
  <a href="#-audiobookshelf-integration">Audiobookshelf</a> •
  <a href="#-development">Development</a>
</p>

</div>

---

## ✨ Features

<table>
<tr>
<td width="50">🔍</td>
<td width="200"><strong>Libation Integration</strong></td>
<td>Trigger scans via <code>libationcli</code> in Docker with automatic book discovery</td>
</tr>
<tr>
<td>📦</td>
<td><strong>Smart Staging</strong></td>
<td>Hardlink files to upload workspace with MAM-compliant naming (≤225 chars, automatic truncation with hash suffix)</td>
</tr>
<tr>
<td>🌏</td>
<td><strong>Japanese Transliteration</strong></td>
<td>Auto-converts Japanese author names using pykakasi with intelligent romanization</td>
</tr>
<tr>
<td>📋</td>
<td><strong>Metadata Enrichment</strong></td>
<td>Fetch from <a href="https://api.audnex.us">Audnex API</a> + MediaInfo with series/volume detection</td>
</tr>
<tr>
<td>🧲</td>
<td><strong>Torrent Creation</strong></td>
<td>Uses mkbrr in Docker with configurable presets and piece sizes</td>
</tr>
<tr>
<td>⬆️</td>
<td><strong>qBittorrent Upload</strong></td>
<td>Auto-add torrents with category/tags, ready for cross-seeding</td>
</tr>
<tr>
<td>🔄</td>
<td><strong>Production-Grade Retry</strong></td>
<td>Powered by <a href="https://github.com/jd/tenacity">tenacity</a> with exponential backoff and jitter</td>
</tr>
<tr>
<td>📊</td>
<td><strong>Robust State Tracking</strong></td>
<td>Atomic writes, automatic backups, stale detection, and checkpoint recovery</td>
</tr>
<tr>
<td>📚</td>
<td><strong>Audiobookshelf Import</strong></td>
<td>Direct library import with duplicate detection and quality-based trumping</td>
</tr>
<tr>
<td>🛡️</td>
<td><strong>Type-Safe Architecture</strong></td>
<td>Strict typing with Pydantic v2 models and mypy verification</td>
</tr>
</table>

---

## 🔄 Pipeline

```mermaid
graph LR
    A[📖 Libation Scan] --> B[🔍 Discover New]
    B --> C[📦 Stage/Hardlink]
    C --> D[📋 Metadata]
    D --> E[🧲 mkbrr]
    E --> F[⬆️ qBittorrent]
    F --> G[📚 Audiobookshelf]
    style A fill:#e1f5fe
    style G fill:#e8f5e9
```

<details>
<summary><strong>Pipeline Details</strong></summary>

| Stage | Description | Command |
|-------|-------------|---------|
| **Scan** | Trigger Libation to check for new Audible books | `mamfast scan` |
| **Discover** | Find new audiobooks not yet processed | `mamfast discover` |
| **Stage** | Hardlink files with MAM-compliant naming | `mamfast prepare` |
| **Metadata** | Fetch Audnex data + extract MediaInfo | `mamfast metadata` |
| **Torrent** | Create .torrent files via mkbrr | `mamfast torrent` |
| **Upload** | Add to qBittorrent with tags | `mamfast upload` |
| **Import** | Import to Audiobookshelf (optional) | `mamfast abs-import` |

</details>

---

## 📥 Installation

> Repo name is `mam_tool`; the app name/CLI is `mamfast`.

```bash
# Clone the repo
git clone https://github.com/H2OKing89/mam_tool.git mamfast
cd mamfast

# Create virtual environment
python -m venv .venv

# Linux/macOS (bash/zsh)
source .venv/bin/activate

# Windows PowerShell
# .\.venv\Scripts\Activate.ps1

# Install in development mode
pip install -e ".[dev]"

# Copy config templates
mkdir -p config
cp config.yaml.example config/config.yaml
cp .env.example config/.env

# Edit with your settings
$EDITOR config/.env config/config.yaml
```

### Requirements

<table>
<tr>
<th>Requirement</th>
<th>Version</th>
<th>Notes</th>
</tr>
<tr>
<td>🐍 Python</td>
<td>3.11+</td>
<td>Required</td>
</tr>
<tr>
<td>🐳 Docker</td>
<td>Latest</td>
<td>For Libation and mkbrr containers</td>
</tr>
<tr>
<td>📥 qBittorrent</td>
<td>4.x+</td>
<td>With Web UI enabled</td>
</tr>
<tr>
<td>🎵 mediainfo</td>
<td>Latest</td>
<td>CLI tool for audio metadata (runs on host, not inside Docker)</td>
</tr>
</table>

---

## ⚙️ Configuration

MAMFast uses layered configuration with automatic validation:

> **Precedence**: `config.yaml` > `.env` > defaults
> Put secrets in `.env`, everything else in `config.yaml`.

<details>
<summary><strong>1. 🔐 <code>config/.env</code> - Secrets Only (never commit)</strong></summary>

```bash
# qBittorrent credentials (REQUIRED)
QB_HOST=http://192.168.1.100:8080
QB_USERNAME=admin
QB_PASSWORD=secret

# Audiobookshelf (only needed for abs-import command)
AUDIOBOOKSHELF_HOST=https://abs.example.com
AUDIOBOOKSHELF_API_KEY=your-api-token-here

# Optional runtime settings
MAMFAST_ENV=production
LOG_LEVEL=INFO
```

> **Note**: Docker/Libation settings (`LIBATION_CONTAINER`, `DOCKER_BIN`, `TARGET_UID`, `TARGET_GID`)
> belong in `config.yaml`'s `environment:` section, not here.

</details>

<details>
<summary><strong>2. 📝 <code>config/config.yaml</code> - Paths & Settings</strong></summary>

```yaml
# Docker/Libation settings (preferred location over .env)
environment:
  libation_container: "Libation"
  docker_bin: "/usr/bin/docker"
  target_uid: 99
  target_gid: 100

paths:
  library_root: "/mnt/user/data/audio/LibationLibrary"
  seed_root: "/mnt/user/data/seedvault/audiobooks"
  torrent_output: "/mnt/user/data/downloads/torrents/torrentfiles"
  # Optional: override the default XDG locations (platformdirs)
  # state_file: "./data/processed.json"
  # log_file: "./logs/mamfast.log"

mam:
  max_filename_length: 225
  allowed_extensions: [".m4b", ".jpg", ".jpeg", ".png", ".pdf", ".cue"]

filters:
  # Note: remove_phrases and author_map live in config/naming.json
  remove_book_numbers: true
  transliterate_japanese: true

naming:
  # Optional: "H2OKing" -> appends "[H2OKing]" to folder names
  ripper_tag: "H2OKing"

mkbrr:
  image: "ghcr.io/autobrr/mkbrr:latest"
  preset: "mam"
  host_data_root: "/mnt/user/data"
  container_data_root: "/data"

qbittorrent:
  category: "mam-audiobooks"
  tags: ["mamfast"]
  auto_start: true
  auto_tmm: false
  save_path: ""

audnex:
  base_url: "https://api.audnex.us"
  timeout_seconds: 30
  regions: ["us"]
```

</details>

<details>
<summary><strong>3. 🗂️ <code>config/categories.json</code> - MAM Genre Mappings</strong></summary>

Maps audiobook genres to MAM category IDs:

```json
{
  "fantasy": 39,
  "science fiction": 40,
  "mystery": 41
}
```

</details>

<details>
<summary><strong>4. 🌍 Environment Variables - XDG Path Overrides</strong></summary>

MAMFast uses XDG-compliant paths by default (via [platformdirs](https://github.com/platformdirs/platformdirs)):

```bash
# Override default data directory (for state files)
# Default: ~/.local/share/mamfast (Linux), ~/Library/Application Support/mamfast (macOS)
export MAMFAST_DATA_DIR="/mnt/cache/appdata/mamfast/data"

# Override default cache directory
# Default: ~/.cache/mamfast (Linux), ~/Library/Caches/mamfast (macOS)
export MAMFAST_CACHE_DIR="/mnt/cache/appdata/mamfast/cache"

# Override default log directory
# Default: ~/.local/state/mamfast (Linux), ~/Library/Logs/mamfast (macOS)
export MAMFAST_LOG_DIR="/mnt/cache/appdata/mamfast/logs"
```

> **Note**: Explicitly configured paths in `config.yaml` always take precedence over environment variables.

</details>

---

## 🚀 Usage

### Full Pipeline

```bash
mamfast run                   # Run everything
mamfast run --skip-scan       # Skip Libation scan
mamfast run --skip-metadata   # Skip metadata fetching
mamfast --dry-run run         # Preview without changes
```

### Step by Step

```bash
mamfast scan              # Trigger Libation download
mamfast scan --liberate   # Scan and download new books
mamfast discover          # List new audiobooks
mamfast discover --all    # List all audiobooks
mamfast prepare           # Stage files (hardlink + rename)
mamfast metadata          # Fetch Audnex + MediaInfo
mamfast torrent           # Create .torrent files
mamfast upload            # Add to qBittorrent
```

### State Management

```bash
mamfast state list            # View all processed entries
mamfast state list --failed   # Show only failed entries
mamfast state prune           # Remove stale entries (missing files)
mamfast state retry <asin-or-id>  # Clear failed status for retry
mamfast state clear <asin-or-id>  # Remove entry completely
```

### Utilities

```bash
mamfast status            # Show processing statistics
mamfast config            # Debug: print loaded config
mamfast validate          # Validate configuration
mamfast check-duplicates  # Find potential duplicate releases
```

### Global Options

| Option | Description |
|--------|-------------|
| `--dry-run` | Preview without making changes |
| `-v, --verbose` | Enable DEBUG logging |
| `-c, --config PATH` | Custom config.yaml path |
| `-V, --version` | Show version |

> ⚠️ **Important**: Global options like `--dry-run` must come **before** the subcommand:
> ```bash
> mamfast --dry-run abs-import  # ✅ Correct
> mamfast abs-import --dry-run  # ❌ Won't work
> ```

---

## 📚 Audiobookshelf Integration

MAMFast supports importing audiobooks directly to Audiobookshelf libraries with duplicate detection and quality-based replacement (trumping).

### Basic Commands

```bash
mamfast abs-init              # Initialize ABS connection
mamfast abs-import            # Import staged books to ABS library
mamfast abs-check-duplicate B0ASIN123  # Check if ASIN exists
mamfast abs-trump-check       # Preview trumping decisions
mamfast abs-cleanup           # Clean orphaned files
mamfast abs-restore           # List/restore archived books
```

### Trumping (Quality-Based Replacement)

When enabled, trumping automatically replaces lower-quality audiobooks with higher-quality versions:

```yaml
# config/config.yaml
audiobookshelf:
  enabled: true
  host: "http://localhost:13378"
  api_key: "your-api-key"
  import:
    trumping:
      enabled: true
      aggressiveness: balanced  # conservative | balanced | aggressive
      min_bitrate_increase_kbps: 64
      archive_root: "/mnt/user/data/audio/archive"
```

<details>
<summary><strong>Quality Hierarchy & Trumping Decisions</strong></summary>

**Format Ranking:** m4b > m4a > opus > mp3 > flac (for audiobooks)

> FLAC is ranked lowest because speech doesn't benefit from lossless encoding, FLAC lacks chapter support, and file sizes are significantly larger.

**Trumping Decisions:**

| Decision | Action |
|----------|--------|
| **REPLACE_WITH_NEW** | New file is better → archive old, import new |
| **KEEP_EXISTING** | Existing is equal or better → skip import |
| **KEEP_BOTH** | Incomparable (different language) → defer to policy |
| **REJECT_NEW** | New is worse quality → skip entirely |

</details>

---

## 📁 Project Structure

MAMFast uses a modular architecture with clean separation of concerns:

```
mamfast/
├── src/mamfast/
│   ├── cli.py                  # CLI parser + main entry point
│   ├── config.py               # Configuration loading
│   ├── models.py               # Pydantic data models
│   ├── workflow.py             # Pipeline orchestration
│   │
│   ├── commands/               # 🆕 CLI command handlers
│   │   ├── core.py             #    scan, discover, prepare, etc.
│   │   ├── utility.py          #    status, check, validate
│   │   ├── diagnostics.py      #    dry-run, check-duplicates
│   │   ├── state.py            #    state list/prune/retry/clear
│   │   └── abs.py              #    Audiobookshelf commands
│   │
│   ├── abs/                    # Audiobookshelf integration
│   │   ├── client.py           #    ABS API client
│   │   ├── importer.py         #    Import workflow
│   │   └── asin.py             #    ASIN extraction/resolution
│   │
│   ├── utils/
│   │   ├── naming/             # 🆕 Modular naming system
│   │   │   ├── filters.py      #    Title/series filtering
│   │   │   ├── mam_paths.py    #    MAM path building
│   │   │   ├── normalization.py#    Book normalization
│   │   │   └── ...             #    8 focused modules
│   │   ├── cmd.py              # 🆕 sh-library subprocess wrapper
│   │   ├── retry.py            # 🆕 tenacity-powered retries
│   │   ├── state.py            #    State management (v2 schema)
│   │   └── paths.py            #    Host↔container path mapping
│   │
│   └── schemas/                # Pydantic schemas
│       ├── config.py           #    Configuration validation
│       └── state.py            #    State file schema v2
│
├── config/                     # Configuration (gitignored)
├── docs/                       # Technical documentation
│   ├── archive/                #    Completed implementation reports
│   └── audiobookshelf/         #    ABS integration guides
├── tests/                      # Comprehensive test suite
└── pyproject.toml              # Project configuration
```

<details>
<summary><strong>Recent Architecture Improvements (December 2025)</strong></summary>

- **CLI Split**: `cli.py` reduced from 4,100 → 820 lines via `commands/` subpackage
- **Naming Refactor**: `naming.py` split into 9 focused modules for maintainability
- **State Hardening**: Schema v2 with atomic writes, checkpoints, and backup recovery
- **Production Dependencies**: Replaced custom code with battle-tested libraries:
  - `tenacity` for retry logic with exponential backoff
  - `platformdirs` for XDG-compliant paths
  - `sh` library wrapper for cleaner subprocess handling

  See `docs/README.md` for the documentation layout.

</details>

---

## 🛠️ Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=src/mamfast --cov-branch --cov-report=term

# Lint
ruff check src/

# Format
ruff format src/

# Type check
mypy src/

# Run all checks (pre-commit)
pre-commit run --all-files
```

### Pre-commit Hooks

MAMFast uses pre-commit for automated code quality:

```yaml
# .pre-commit-config.yaml (excerpt)

repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.0
    hooks:
      - id: ruff
      - id: ruff-format

  - repo: local
    hooks:
      - id: mypy
        name: mypy type checking
        entry: mypy
        language: system
        types: [python]
      - id: pytest
        name: pytest unit tests
        entry: pytest
        language: system
        types: [python]

```

---

## 📄 License

[MIT](LICENSE) © 2024-2025

---

<div align="center">
  <sub>Built with ❤️ for audiobook enthusiasts</sub>
</div>
