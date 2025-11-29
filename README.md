# MAMFast

> Fast MAM audiobook upload automation tool

Automates the pipeline from Libation audiobook downloads to MAM-ready torrents seeding in qBittorrent.

## Features

- 🔍 **Libation Integration** - Trigger scans via `libationcli` in Docker
- 📦 **Smart Staging** - Hardlink files to upload workspace with MAM-compliant naming (≤225 chars)
- 📋 **Metadata Enrichment** - Fetch from [Audnex API](https://api.audnex.us) + MediaInfo
- 🧲 **Torrent Creation** - Uses mkbrr with configurable presets
- ⬆️ **qBittorrent Upload** - Auto-add torrents with category/tags
- 📊 **State Tracking** - Prevents re-processing of already handled releases

## Pipeline

```
Libation Scan → Discover New → Stage (Hardlink) → Metadata → mkbrr → qBittorrent
```

## Installation

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
cp .env.example .env
cp config.yaml.example config.yaml

# Edit with your settings
$EDITOR .env config.yaml
```

## Configuration

### `.env` - Secrets (never commit)

```bash
LIBATION_CONTAINER=libation
QB_HOST=http://10.1.60.10:8080
QB_USERNAME=admin
QB_PASSWORD=secret
MAM_ANNOUNCE_URL=https://t.myanonamouse.net/announce/your-key
TARGET_UID=99
TARGET_GID=100
```

### `config.yaml` - Paths & Settings

```yaml
paths:
  libation_library_root: "/mnt/user/data/audio/LibationLibrary"
  staging_root: "/mnt/user/data/mam-staging"
  torrent_output: "/mnt/user/data/downloads/torrents/torrentfiles"

mkbrr:
  preset: "mam"
  host_data_root: "/mnt/user/data"
  container_data_root: "/data"

mam:
  max_filename_length: 225
  allowed_extensions: [".m4b", ".jpg", ".pdf", ".cue"]
```

## Usage

```bash
# Run full pipeline
mamfast run

# Or step by step:
mamfast scan           # Trigger Libation download
mamfast discover       # List new audiobooks
mamfast prepare        # Stage files (hardlink + rename)
mamfast metadata       # Fetch Audnex + MediaInfo
mamfast torrent        # Create .torrent files
mamfast upload         # Add to qBittorrent

# Utilities
mamfast status         # Show processing status
mamfast config         # Debug: print loaded config

# Options
mamfast run --skip-scan        # Skip Libation scan
mamfast run --dry-run          # Preview without changes
mamfast -v run                 # Verbose logging
```

## Project Structure

```
mamfast/
├── src/mamfast/
│   ├── cli.py            # Command-line interface
│   ├── config.py         # Configuration loading
│   ├── models.py         # Data models (AudiobookRelease, etc.)
│   ├── libation.py       # Libation Docker wrapper
│   ├── discovery.py      # Find new audiobooks
│   ├── hardlinker.py     # Stage files for upload
│   ├── metadata.py       # Audnex + MediaInfo
│   ├── mkbrr.py          # Torrent creation
│   ├── qbittorrent.py    # qBittorrent API
│   ├── workflow.py       # Pipeline orchestration
│   └── utils/
│       ├── naming.py     # Filename sanitization
│       ├── paths.py      # Host↔container mapping
│       └── state.py      # Processed tracking
├── config.yaml.example
├── .env.example
└── pyproject.toml
```

## Requirements

- Python 3.11+
- Docker (for Libation and mkbrr)
- qBittorrent with Web UI enabled
- mediainfo CLI tool

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check src/

# Type check
mypy src/
```

## License

MIT
