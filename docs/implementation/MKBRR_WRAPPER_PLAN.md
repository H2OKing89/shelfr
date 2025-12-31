# mkbrr Wrapper Enhancement Plan

> **Branch:** `feature/mkbrr-wrapper`
> **Status:** Planning
> **Created:** 2024-12-30

## Overview

Enhance the existing `src/shelfr/mkbrr.py` Docker wrapper to expose more mkbrr features and add CLI commands for direct user interaction.

---

## Current State Analysis

The existing `src/shelfr/mkbrr.py` provides:

| Function | Description | Status |
|----------|-------------|--------|
| `create_torrent()` | Create torrents with presets | ✅ |
| `inspect_torrent()` | View torrent metadata | ✅ |
| `check_torrent()` | Verify content against torrent | ✅ |
| `load_presets()` | Load preset names from presets.yaml | ✅ |
| `fix_torrent_permissions()` | Fix Docker-created file ownership | ✅ |
| `check_docker_available()` | Verify Docker is accessible | ✅ |

### Missing Features (from mkbrr docs)

| Feature | mkbrr CLI | Current Wrapper | Priority |
|---------|-----------|-----------------|----------|
| `modify` command | ✅ | ❌ | **High** |
| `update` command | ✅ | ❌ | Low (Docker) |
| Custom piece size (`-l`, `--piece-length`) | ✅ | ❌ | Medium |
| Max piece size (`-m`, `--max-piece-length`) | ✅ | ❌ | Medium |
| Source tag override (`-s`, `--source`) | ✅ | ❌ | Medium |
| Output filename (`-o`, `--output`) | ✅ | ❌ | Medium |
| Output directory (`--output-dir`) | ✅ | ❌ | Medium |
| Exclude patterns (`-x`, `--exclude`) | ✅ | ❌ | Medium |
| Include patterns (`-n`, `--include`) | ✅ | ❌ | Low |
| Comment override (`-c`, `--comment`) | ✅ | ❌ | Low |
| Skip prefix (`--skip-prefix`) | ✅ | ❌ | Low |
| Tracker URL (`-t`, `--tracker`) | ✅ | ❌ | Medium |
| Private flag (`--private`) | ✅ | ❌ | Low |
| Web seeds (`-w`, `--web-seed`) | ✅ | ❌ | Low |
| Entropy source (`-e`, `--entropy`) | ✅ | ❌ | Low |
| No date (`--no-date`) | ✅ | ❌ | Low |
| No creator (`--no-creator`) | ✅ | ❌ | Low |
| Workers (`--workers`) | ✅ (check) | ❌ | Low |
| Dry run (`--dry-run`) | ✅ (modify) | ❌ | Low |
| Version command | ✅ | ❌ | Low |
| Batch mode (`-b`) | ✅ | ❌ | Low (complex) |
| Batch config (batch.yaml) | ✅ | ❌ | Low (complex) |
| Season pack detection | ✅ (auto) | ❌ | Low (info only) |
| Preset file path (`--preset-file`) | ✅ | ❌ | Low |

---

## Phase 1: Core Enhancements (High Priority)

### 1.1 Add `modify_torrent()` Function

The `modify` command allows changing torrent metadata without recreating:

```python
def modify_torrent(
    torrent_paths: Path | str | list[Path | str],
    output_path: Path | str | None = None,
    output_dir: Path | str | None = None,
    tracker: str | None = None,
    source: str | None = None,
    comment: str | None = None,
    private: bool | None = None,
    preset: str | None = None,
    entropy: bool = False,
    dry_run: bool = False,
) -> MkbrrResult:
    """
    Modify one or more existing torrent files.

    Args:
        torrent_paths: Path(s) to .torrent file(s) to modify.
        output_path: Output path for single file (default: prefixed filename).
        output_dir: Output directory for batch modifications.
        tracker: New tracker URL (-t).
        source: New source tag (-s).
        comment: New comment (-c).
        private: Set private flag (--private).
        preset: Apply preset settings (-P).
        entropy: Add random entropy (-e).
        dry_run: Preview changes without saving (--dry-run).

    Returns:
        MkbrrResult with modified torrent path(s).

    Note:
        - All non-standard metadata is stripped during modification.
        - When modifying multiple files, use output_dir not output_path.
    """
```

**Use cases:**

- Re-upload to different tracker
- Fix source tag
- Strip unnecessary metadata
- Batch update multiple torrents

### 1.2 Extend `create_torrent()` Parameters

Add optional parameters for advanced torrent creation:

```python
def create_torrent(
    content_path: Path | str,
    output_dir: Path | str | None = None,
    preset: str | None = None,
    # NEW optional parameters:
    output_filename: str | None = None,  # -o, --output
    tracker: str | None = None,          # -t, --tracker (override preset)
    source: str | None = None,           # -s, --source (override preset)
    piece_length: int | None = None,     # -l, --piece-length (exponent, e.g., 18 = 256KiB)
    max_piece_length: int | None = None, # -m, --max-piece-length
    exclude_patterns: list[str] | None = None,  # -x, --exclude
    include_patterns: list[str] | None = None,  # -n, --include
    skip_prefix: bool = False,           # --skip-prefix
    preset_file: Path | str | None = None,  # --preset-file (custom presets.yaml path)
    workers: int | None = None,          # --workers (hashing concurrency)
    comment: str | None = None,          # -c, --comment
    private: bool | None = None,         # --private (default: True)
    no_date: bool = False,               # --no-date
    no_creator: bool = False,            # --no-creator
    web_seeds: list[str] | None = None,  # -w, --web-seed
    entropy: bool = False,               # -e, --entropy (randomize info hash)
) -> MkbrrResult:
```

**Notes from mkbrr docs:**

- Piece size is auto-calculated based on content size (smart defaults)
- When tracker URL provided, output filename prefixed with tracker domain
- `--skip-prefix` disables the tracker domain prefix
- Tracker-specific rules override manual `-l`/`-m` flags for compliance
- Filtering patterns are additive with preset patterns
- **Season pack detection:** mkbrr auto-detects incomplete TV season packs by analyzing `S01E01` patterns in `.mkv`/`.mp4` files (warning only, doesn't block creation)
- **Symbolic links:** Links are followed (target content hashed), but link path is stored in torrent metadata. When checking, verifies against original target content at creation time.

### 1.3 Add `get_mkbrr_version()` Function

```python
def get_mkbrr_version() -> str | None:
    """
    Get the mkbrr version from Docker container.

    Returns:
        Version string (e.g., "1.5.0") or None if unavailable.
    """
```

### 1.4 Add `update_mkbrr()` Function

```python
def update_mkbrr() -> MkbrrResult:
    """
    Update mkbrr Docker image to the latest version.

    For Docker-based usage, this pulls the latest image rather than
    running mkbrr's self-update (which updates the binary).

    Returns:
        MkbrrResult with success status.

    Note:
        This runs `docker pull ghcr.io/autobrr/mkbrr:latest`.
        The native `mkbrr update` command is not used since we
        run mkbrr in a container.
    """
```

---

## Phase 2: CLI Integration

### 2.1 New CLI Subcommand Group

Add `shelfr mkbrr` command group:

```bash
# Create torrent
shelfr mkbrr create <path> [--preset mam] [--source TAG] [--output FILE]

# Inspect torrent metadata
shelfr mkbrr inspect <torrent> [--verbose]

# Verify content against torrent
shelfr mkbrr check <torrent> <content-path> [--verbose] [--quiet]

# Modify existing torrent
shelfr mkbrr modify <torrent> [--tracker URL] [--source TAG] [--output FILE]

# List available presets
shelfr mkbrr presets

# Show mkbrr version
shelfr mkbrr version

# Update mkbrr Docker image
shelfr mkbrr update
```

### 2.2 CLI File Structure

```text
src/shelfr/cli/
├── __init__.py
├── main.py          # Main app with subcommand groups
├── abs.py           # Existing ABS commands
├── libation.py      # Existing Libation commands
├── tools.py         # Existing tools
└── mkbrr.py         # NEW: mkbrr CLI commands
```

### 2.3 CLI Implementation

```python
# src/shelfr/cli/mkbrr.py
"""CLI commands for mkbrr torrent operations."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer

from shelfr import mkbrr
from shelfr.console import console, print_error, print_success

logger = logging.getLogger(__name__)

app = typer.Typer(
    name="mkbrr",
    help="Torrent creation and management via mkbrr.",
    no_args_is_help=True,
)


@app.command()
def create(
    path: Annotated[Path, typer.Argument(help="Path to file/directory")],
    preset: Annotated[str | None, typer.Option("--preset", "-P")] = None,
    tracker: Annotated[str | None, typer.Option("--tracker", "-t")] = None,
    source: Annotated[str | None, typer.Option("--source", "-s")] = None,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    output_dir: Annotated[Path | None, typer.Option("--output-dir")] = None,
    piece_length: Annotated[int | None, typer.Option("--piece-length", "-l")] = None,
    exclude: Annotated[list[str] | None, typer.Option("--exclude", "-x")] = None,
    include: Annotated[list[str] | None, typer.Option("--include", "-n")] = None,
    comment: Annotated[str | None, typer.Option("--comment", "-c")] = None,
    skip_prefix: Annotated[bool, typer.Option("--skip-prefix")] = False,
    preset_file: Annotated[Path | None, typer.Option("--preset-file")] = None,
    workers: Annotated[int | None, typer.Option("--workers")] = None,
    entropy: Annotated[bool, typer.Option("--entropy", "-e")] = False,
) -> None:
    """Create a torrent from file or directory."""
    ...


@app.command()
def inspect(
    torrent: Annotated[Path, typer.Argument(help="Path to .torrent file")],
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Inspect torrent metadata."""
    ...


@app.command()
def check(
    torrent: Annotated[Path, typer.Argument(help="Path to .torrent file")],
    content: Annotated[Path, typer.Argument(help="Path to content")],
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q")] = False,
    workers: Annotated[int | None, typer.Option("--workers")] = None,
) -> None:
    """Verify content against torrent file.

    Outputs: completion %, good/bad pieces, missing files, check time.
    Exit code non-zero if bad pieces > 0 or missing files > 0.

    Quiet mode (-q) outputs only completion percentage (e.g., "99.50%").
    Verbose mode (-v) includes bad piece indices.
    """
    ...


@app.command()
def modify(
    torrents: Annotated[list[Path], typer.Argument(help="Path(s) to .torrent file(s)")],
    tracker: Annotated[str | None, typer.Option("--tracker", "-t")] = None,
    source: Annotated[str | None, typer.Option("--source", "-s")] = None,
    comment: Annotated[str | None, typer.Option("--comment", "-c")] = None,
    private: Annotated[bool | None, typer.Option("--private")] = None,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    output_dir: Annotated[Path | None, typer.Option("--output-dir")] = None,
    preset: Annotated[str | None, typer.Option("--preset", "-P")] = None,
    entropy: Annotated[bool, typer.Option("--entropy", "-e")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Modify existing torrent file(s).

    Note: All non-standard metadata is stripped during modification.
    For multiple files, use --output-dir instead of --output.
    """
    ...


@app.command()
def presets() -> None:
    """List available mkbrr presets."""
    ...


@app.command()
def version() -> None:
    """Show mkbrr version."""
    ...


@app.command()
def update() -> None:
    """Update mkbrr Docker image to latest version.

    Pulls the latest ghcr.io/autobrr/mkbrr image.
    Note: This updates the Docker image, not the mkbrr binary directly.
    """
    ...
```

---

## Phase 3: Structured Data Models

### 3.1 New Schema File

```python
# src/shelfr/schemas/mkbrr.py
"""Pydantic models for mkbrr data structures."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TorrentFileInfo(BaseModel):
    """Single file in a torrent."""

    path: str
    size: int


class TorrentInfo(BaseModel):
    """Parsed torrent metadata from mkbrr inspect.

    Note: Use --verbose flag to capture non-standard metadata fields
    in both root and info dictionaries.
    """

    name: str
    info_hash: str
    size: int
    piece_length: int
    piece_count: int
    private: bool
    trackers: list[str] = Field(default_factory=list)
    web_seeds: list[str] = Field(default_factory=list)
    source: str | None = None
    comment: str | None = None
    created_by: str | None = None
    creation_date: datetime | None = None
    files: list[TorrentFileInfo] = Field(default_factory=list)
    file_count: int = 1  # For multi-file torrents
    extra_fields: dict[str, Any] | None = None  # Non-standard fields (verbose mode)


class CheckResult(BaseModel):
    """Result of torrent verification."""

    valid: bool
    percent_complete: float
    good_pieces: int
    bad_pieces: int
    bad_piece_indices: list[int] | None = None  # Only with --verbose
    total_pieces: int
    missing_files: list[str] = Field(default_factory=list)  # Includes "(size mismatch)" suffix if applicable
    check_time_seconds: float | None = None
```

### 3.2 Parse Inspect Output

Add function to parse `mkbrr inspect` output into structured data:

```python
def parse_inspect_output(stdout: str) -> TorrentInfo:
    """Parse mkbrr inspect output into TorrentInfo model."""
    ...
```

---

## Phase 4: Config Schema Updates

### 4.1 Extended MkbrrSchema

```python
# In schemas/config.py
class MkbrrSchema(BaseModel):
    """mkbrr Docker configuration."""

    # Existing fields
    image: str = "ghcr.io/autobrr/mkbrr:latest"
    preset: str = "mam"
    host_data_root: str = "/mnt/user/data"
    container_data_root: str = "/data"
    host_config_dir: str = "/mnt/cache/appdata/mkbrr"
    container_config_dir: str = "/root/.config/mkbrr"

    # Already exists but documenting
    host_output_dir: str = "/mnt/cache/appdata/mkbrr/torrents"
    container_output_dir: str = "/torrentfiles"

    # NEW: Default create options
    default_exclude_patterns: list[str] = Field(default_factory=list)
    default_include_patterns: list[str] = Field(default_factory=list)
    skip_prefix: bool = False
    timeout_seconds: int = Field(default=300, ge=60, le=3600)
```

---

## Key mkbrr Features to Note

### Filtering (--include / --exclude)

From [filtering.mdx](../reference/mkbrr/features/filtering.mdx):

- **Built-in exclusions:** `.torrent`, `.ds_store`, `thumbs.db`, `desktop.ini`, `zone.identifier` (case-insensitive)
- **Pattern matching:** Filename only (not full path), case-insensitive, glob patterns
- **Processing order:**
  1. Built-in exclusions always applied first
  2. If `--include` patterns exist → whitelist mode (only matching files kept)
  3. If no `--include` → `--exclude` patterns applied
- **Additive with presets:** CLI patterns combine with preset patterns

### Tracker Rules

From [tracker-rules.mdx](../reference/mkbrr/features/tracker-rules.mdx):

- mkbrr auto-detects tracker requirements from announce URL
- **Rules override manual settings** (`-l`/`-m` flags) to ensure compliance
- Enforces: max piece size, size ranges, max torrent file size
- Known trackers include: ANT, HDB, BHD, PTP, MTV, GGN, BTN, etc.

### Presets

From [presets.mdx](../reference/mkbrr/features/presets.mdx):

- Location search order:
  1. `--preset-file` flag
  2. `./presets.yaml` (current directory)
  3. `~/.config/mkbrr/presets.yaml`
  4. `~/.mkbrr/presets.yaml` (legacy)
- Supports `default` section for settings applied to ALL presets
- CLI flags override preset values (except filtering which is additive)
- Additional preset options: `workers` (hashing concurrency), `entropy` (randomize info hash), `max_piece_length`

### Batch Mode

From [batch-mode.mdx](../reference/mkbrr/features/batch-mode.mdx):

- Create multiple torrents in one command: `mkbrr create -b batch.yaml`
- YAML config defines list of jobs with individual settings
- Each job can specify: `output`, `path`, `trackers`, `private`, `piece_length`, `source`, `comment`, `exclude_patterns`, `include_patterns`, `webseeds`, `no_date`
- Cannot provide source path argument with `-b` flag (paths must be in batch file)
- JSON schema available for validation

**Example batch.yaml structure:**

```yaml
version: 1
jobs:
  - output: /torrents/book1.torrent
    path: /media/audiobooks/book1/
    trackers:
      - https://tracker.example.com/announce
    private: true
    source: "MAM"
```

### Season Pack Detection

From [season-packs.mdx](../reference/mkbrr/features/season-packs.mdx):

- Auto-detects potentially incomplete TV season packs
- Analyzes `.mkv` and `.mp4` files only
- Recognizes episode patterns: `S01E01`, `S01E01-E03`, `S01E01E02`
- Season patterns: `Show.S01`, `Season 01`, `[S01]`, `/Season 01/`
- **Warning only** - doesn't block torrent creation
- Use case: Prevents accidental upload of incomplete season packs

### Smart Defaults (create)

- **Piece size:** Auto-calculated based on content size
- **Output filename:** Prefixed with tracker domain when `-t` provided
- **Private flag:** Enabled by default (use `--private=false` for public)

---

## File Structure Summary

```text
src/shelfr/
├── mkbrr.py                    # Enhanced core wrapper
├── cli/
│   ├── __init__.py
│   ├── main.py                 # Register mkbrr subcommand
│   └── mkbrr.py                # NEW: CLI commands
└── schemas/
    ├── __init__.py             # Export new models
    ├── config.py               # Extended MkbrrSchema
    └── mkbrr.py                # NEW: TorrentInfo, CheckResult
```

---

## Implementation Order

| Step | Task | Files | Est. Effort |
|------|------|-------|-------------|
| 1 | Add `modify_torrent()` | `mkbrr.py` | Small |
| 2 | Add `get_mkbrr_version()` | `mkbrr.py` | Small |
| 3 | Extend `create_torrent()` params | `mkbrr.py` | Medium |
| 4 | Add Pydantic models | `schemas/mkbrr.py` | Small |
| 5 | Parse inspect output | `mkbrr.py` | Medium |
| 6 | Create CLI commands | `cli/mkbrr.py` | Medium |
| 7 | Register CLI subcommand | `cli/main.py` | Small |
| 8 | Update config schema | `schemas/config.py` | Small |
| 9 | Write tests | `tests/test_mkbrr.py` | Medium |
| 10 | Documentation | `docs/cli/mkbrr.md` | Small |

---

## Testing Strategy

### Unit Tests (Mocked)

- Mock Docker commands using existing `make_cmd_result()` helper
- Test each function with various parameter combinations
- Test error handling (timeout, Docker unavailable, etc.)

### Integration Tests (Optional)

- Require real Docker + mkbrr container
- Mark with `@pytest.mark.integration`
- Skip by default in CI

### Golden Tests

- Capture real `mkbrr inspect` output
- Test parsing against golden files
- Ensure structured data matches expected

---

## References

- [mkbrr CLI Reference](../reference/mkbrr/cli-reference/)
- [mkbrr Features](../reference/mkbrr/features/)
- [mkbrr Guides](../reference/mkbrr/guides/)
- [mkbrr GitHub](https://github.com/autobrr/mkbrr)

---

## Changelog

| Date | Change |
|------|--------|
| 2024-12-30 | Initial planning document |
| 2024-12-30 | Updated with complete CLI flags from mkbrr docs |
| 2024-12-30 | Added key features section (filtering, tracker rules, presets) |
| 2024-12-30 | Enhanced modify_torrent() to support multiple files, dry-run, entropy |
| 2024-12-30 | Added workers flag for check, output-dir for batch operations |
| 2024-12-30 | Added update command (pulls latest Docker image) |
| 2024-12-30 | Added batch mode docs, season pack detection, preset-file flag |
| 2024-12-30 | Added workers and entropy params to create, expanded presets section |
| 2024-12-30 | Cross-referenced guides: symlink handling, size mismatch, quiet mode, verbose metadata |
