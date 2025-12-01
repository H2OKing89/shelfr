<div align="center">

# 🎧 MAMFast

**Fast MAM audiobook upload automation tool**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

Automates the pipeline from Libation audiobook downloads to MAM-ready torrents seeding in qBittorrent.

</div>

---

## ✨ Features

<table>
<tr>
<td>🔍</td>
<td><strong>Libation Integration</strong></td>
<td>Trigger scans via <code>libationcli</code> in Docker</td>
</tr>
<tr>
<td>📦</td>
<td><strong>Smart Staging</strong></td>
<td>Hardlink files to upload workspace with MAM-compliant naming (≤225 chars)</td>
</tr>
<tr>
<td>🌏</td>
<td><strong>Japanese Transliteration</strong></td>
<td>Auto-converts Japanese author names using pykakasi</td>
</tr>
<tr>
<td>📋</td>
<td><strong>Metadata Enrichment</strong></td>
<td>Fetch from <a href="https://api.audnex.us">Audnex API</a> + MediaInfo</td>
</tr>
<tr>
<td>🧲</td>
<td><strong>Torrent Creation</strong></td>
<td>Uses mkbrr with configurable presets</td>
</tr>
<tr>
<td>⬆️</td>
<td><strong>qBittorrent Upload</strong></td>
<td>Auto-add torrents with category/tags</td>
</tr>
<tr>
<td>🔄</td>
<td><strong>Retry Logic</strong></td>
<td>Exponential backoff for network operations</td>
</tr>
<tr>
<td>📊</td>
<td><strong>State Tracking</strong></td>
<td>Prevents re-processing of already handled releases</td>
</tr>
</table>

## 🔄 Pipeline

```
Libation Scan → Discover New → Stage (Hardlink) → Metadata → mkbrr → qBittorrent
```

## 📥 Installation

```bash
# Clone the repo
git clone <your-repo-url> mamfast
cd mamfast

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install in development mode
pip install -e ".[dev]"

# Copy config templates
cp config.yaml.example config/config.yaml
mkdir -p config
echo "# See .env.example for available variables" > config/.env

# Edit with your settings
$EDITOR config/.env config/config.yaml
```

## ⚙️ Configuration

MAMFast uses three configuration sources:

<details>
<summary><strong>1. <code>config/.env</code> - Secrets (never commit)</strong></summary>

```bash
# qBittorrent credentials
QB_HOST=http://10.1.60.10:8080
QB_USERNAME=admin
QB_PASSWORD=secret


# Optional overrides
LIBATION_CONTAINER=libation
DOCKER_BIN=/usr/bin/docker
TARGET_UID=99
TARGET_GID=100
LOG_LEVEL=INFO
```

</details>

<details>
<summary><strong>2. <code>config/config.yaml</code> - Paths & Settings</strong></summary>

```yaml
paths:
  library_root: "/mnt/user/data/audio/LibationLibrary"
  seed_root: "/mnt/user/data/seedvault/audiobooks"
  torrent_output: "/mnt/user/data/downloads/torrents/torrentfiles"
  state_file: "./data/processed.json"
  log_file: "./logs/mamfast.log"

mam:
  max_filename_length: 225
  allowed_extensions: [".m4b", ".jpg", ".jpeg", ".png", ".pdf", ".cue"]

filters:
  remove_phrases:
    - "(Light Novel)"
    - "Unabridged"
  remove_book_numbers: true
  author_map:
    "日本語名": "Romanized Name"
  transliterate_japanese: true

mkbrr:
  image: "ghcr.io/autobrr/mkbrr:latest"
  preset: "mam"
  host_data_root: "/mnt/user/data"
  container_data_root: "/data"

qbittorrent:
  category: "mam-audiobooks"
  tags: ["mamfast"]
  auto_start: true

audnex:
  base_url: "https://api.audnex.us"
  timeout_seconds: 30
```

</details>

<details>
<summary><strong>3. <code>config/categories.json</code> - MAM Genre Mappings</strong></summary>

Maps audiobook genres to MAM category IDs:

```json
{
  "fantasy": 39,
  "science fiction": 40,
  "mystery": 41
}
```

</details>

## 🚀 Usage

### Full Pipeline

```bash
mamfast run                   # Run everything
mamfast run --skip-scan       # Skip Libation scan
mamfast run --skip-metadata   # Skip metadata fetching
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

### Utilities

```bash
mamfast status            # Show processing status
mamfast config            # Debug: print loaded config
```

### Global Options

| Option | Description |
|--------|-------------|
| `-v, --verbose` | Enable DEBUG logging |
| `-c, --config PATH` | Custom config.yaml path |
| `--dry-run` | Preview without changes |
| `-V, --version` | Show version |

## 📁 Project Structure

```
mamfast/
├── src/mamfast/
│   ├── __init__.py
│   ├── cli.py              # Command-line interface
│   ├── config.py           # Configuration loading (.env, yaml, json)
│   ├── models.py           # Data models (AudiobookRelease, etc.)
│   ├── libation.py         # Libation Docker wrapper
│   ├── discovery.py        # Find new audiobooks
│   ├── hardlinker.py       # Stage files for upload
│   ├── metadata.py         # Audnex + MediaInfo
│   ├── mkbrr.py            # Torrent creation
│   ├── qbittorrent.py      # qBittorrent API
│   ├── workflow.py         # Pipeline orchestration
│   ├── logging_setup.py    # Logging configuration
│   ├── templates/          # Jinja2 templates for MAM BBCode
│   └── utils/
│       ├── naming.py       # Filename sanitization & transliteration
│       ├── paths.py        # Host↔container path mapping
│       ├── retry.py        # Exponential backoff decorator
│       └── state.py        # Processed tracking
├── config/
│   ├── config.yaml         # Your config (gitignored)
│   ├── .env                # Your secrets (gitignored)
│   └── categories.json     # MAM genre → category ID mapping
├── data/                   # State files (gitignored)
├── logs/                   # Log files (gitignored)
├── tests/                  # Test suite
├── config.yaml.example     # Config template
├── pyproject.toml
├── LICENSE
└── README.md
```

## 📋 Requirements

| Requirement | Notes |
|-------------|-------|
| Python 3.11+ | Required |
| Docker | For Libation and mkbrr containers |
| qBittorrent | With Web UI enabled |
| `mediainfo` | CLI tool for audio metadata |

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

## 📄 License

[MIT](LICENSE)
