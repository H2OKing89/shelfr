# mkbrr CLI Commands

> Torrent creation and management via mkbrr Docker wrapper.

mkbrr is a fast, efficient torrent creation tool from the autobrr project. shelfr wraps mkbrr in Docker for easy, consistent usage without requiring local installation.

## Quick Start

```bash
# Create a torrent with MAM preset
shelfr mkbrr create /path/to/audiobook --preset mam

# View torrent metadata
shelfr mkbrr inspect file.torrent

# Verify content matches torrent
shelfr mkbrr check file.torrent /path/to/content

# List available presets
shelfr mkbrr presets
```

## Commands

### `shelfr mkbrr create`

Create a torrent from a file or directory.

```bash
shelfr mkbrr create <path> [options]
```

**Arguments:**
- `PATH` - Path to file or directory to create torrent from (required)

**Options:**
| Option | Short | Description |
|--------|-------|-------------|
| `--preset` | `-P` | Use preset from presets.yaml |
| `--tracker` | `-t` | Tracker announce URL |
| `--source` | `-s` | Source tag (e.g., MAM) |
| `--output` | `-o` | Output filename (without extension) |
| `--output-dir` | | Output directory |
| `--piece-length` | `-l` | Piece size exponent (16-27) |
| `--max-piece-length` | `-m` | Maximum piece size exponent |
| `--exclude` | | Exclude pattern (repeatable) |
| `--include` | | Include pattern (whitelist mode) |
| `--skip-prefix` | | Don't prefix filename with tracker domain |
| `--comment` | `-c` | Torrent comment |
| `--private/--no-private` | | Set private flag (default: private) |
| `--no-date` | | Omit creation date |
| `--no-creator` | | Omit creator field |
| `--web-seed` | `-w` | Add web seed URL (repeatable) |
| `--entropy` | `-e` | Add random entropy to info hash |

**Examples:**

```bash
# Basic creation with MAM preset
shelfr mkbrr create /media/audiobooks/MyBook --preset mam

# Create with custom tracker and source
shelfr mkbrr create /media/audiobooks/MyBook \
  --tracker "https://tracker.example.com/announce" \
  --source "MAM"

# Custom output location
shelfr mkbrr create /media/audiobooks/MyBook \
  --preset mam \
  --output-dir /torrents/staging

# Exclude specific patterns
shelfr mkbrr create /media/audiobooks/MyBook \
  --preset mam \
  --exclude "*.nfo" \
  --exclude "*.txt"
```

### `shelfr mkbrr inspect`

View torrent metadata.

```bash
shelfr mkbrr inspect <torrent> [options]
```

**Arguments:**
- `TORRENT` - Path to .torrent file(s) (required, multiple allowed)

**Options:**
| Option | Short | Description |
|--------|-------|-------------|
| `--verbose` | `-v` | Show extra metadata fields |
| `--json` | | Output as JSON |

**Examples:**

```bash
# View torrent details
shelfr mkbrr inspect mybook.torrent

# Verbose output with all metadata
shelfr mkbrr inspect mybook.torrent --verbose

# JSON output for scripting
shelfr mkbrr inspect mybook.torrent --json

# Inspect multiple torrents
shelfr mkbrr inspect *.torrent
```

**Output includes:**
- Name, size, piece count
- Info hash (SHA1)
- Trackers
- Private flag
- Source tag
- File list (multi-file torrents)
- Creation date and creator

### `shelfr mkbrr check`

Verify content integrity against a torrent file.

```bash
shelfr mkbrr check <torrent> <content> [options]
```

**Arguments:**
- `TORRENT` - Path to .torrent file (required)
- `CONTENT` - Path to content file/directory (required)

**Options:**
| Option | Short | Description |
|--------|-------|-------------|
| `--verbose` | `-v` | Show bad piece indices |
| `--quiet` | `-q` | Output only completion percentage |
| `--workers` | | Number of parallel workers |

**Examples:**

```bash
# Basic verification
shelfr mkbrr check mybook.torrent /media/audiobooks/MyBook

# Quiet mode (just percentage)
shelfr mkbrr check mybook.torrent /media/audiobooks/MyBook --quiet

# Verbose with bad piece details
shelfr mkbrr check mybook.torrent /media/audiobooks/MyBook --verbose
```

**Output includes:**
- Completion percentage
- Good/bad piece counts
- Missing files
- Check time

**Exit codes:**
- `0` - Content matches torrent (100%, no bad pieces, no missing files)
- `1` - Content mismatch or missing files

### `shelfr mkbrr modify`

Modify existing torrent file(s) without re-hashing.

```bash
shelfr mkbrr modify <torrent> [options]
```

**Arguments:**
- `TORRENT` - Path to .torrent file(s) (required, multiple allowed)

**Options:**
| Option | Short | Description |
|--------|-------|-------------|
| `--tracker` | `-t` | New tracker announce URL |
| `--source` | `-s` | New source tag |
| `--comment` | `-c` | New comment |
| `--private/--no-private` | | Set private flag |
| `--preset` | `-P` | Apply preset settings |
| `--output` | `-o` | Output path (single file) |
| `--output-dir` | | Output directory (batch) |
| `--entropy` | `-e` | Add random entropy |
| `--dry-run` | | Preview changes only |

**Examples:**

```bash
# Change source tag
shelfr mkbrr modify mybook.torrent --source "MAM"

# Re-upload to different tracker
shelfr mkbrr modify mybook.torrent \
  --tracker "https://new-tracker.com/announce" \
  --output retracked.torrent

# Preview changes without saving
shelfr mkbrr modify mybook.torrent --source "TEST" --dry-run

# Batch modify multiple torrents
shelfr mkbrr modify *.torrent --source "MAM" --output-dir /torrents/fixed
```

> **Note:** All non-standard metadata is stripped during modification.

### `shelfr mkbrr presets`

List available mkbrr presets from presets.yaml.

```bash
shelfr mkbrr presets
```

**Example output:**
```
Available Presets
┌─────────┬───────────────────────────────────────────┐
│ Name    │ Tracker                                   │
├─────────┼───────────────────────────────────────────┤
│ mam     │ https://libble.me/announce                │
│ red     │ https://flacsfor.me/announce              │
│ btn     │ https://landof.tv/announce                │
└─────────┴───────────────────────────────────────────┘
```

### `shelfr mkbrr version`

Show mkbrr version from Docker container.

```bash
shelfr mkbrr version
```

**Example output:**
```
mkbrr version: 1.5.0
```

### `shelfr mkbrr update`

Pull latest mkbrr Docker image.

```bash
shelfr mkbrr update
```

This pulls `ghcr.io/autobrr/mkbrr:latest` from GitHub Container Registry.

## Configuration

mkbrr settings are configured in `config/config.yaml`:

```yaml
mkbrr:
  # Docker image
  image: "ghcr.io/autobrr/mkbrr:latest"

  # Default preset for torrent creation
  preset: "mam"

  # Host path mappings (for Docker volume mounts)
  host_data_root: "/mnt/user/data"
  container_data_root: "/data"

  # Config directory (contains presets.yaml)
  host_config_dir: "/mnt/cache/appdata/mkbrr"
  container_config_dir: "/root/.config/mkbrr"

  # Output directory for torrents
  host_output_dir: "/mnt/cache/appdata/mkbrr/torrents"
  container_output_dir: "/torrentfiles"

  # Docker command timeout (seconds)
  timeout_seconds: 300
```

### Presets Configuration

Create `~/.config/mkbrr/presets.yaml` (or the path specified in `host_config_dir`):

```yaml
# Default settings applied to all presets
default:
  private: true
  exclude_patterns:
    - "*.nfo"
    - "*.txt"
    - "*.url"

# MAM preset
mam:
  tracker: "https://libble.me/YOUR_PASSKEY/announce"
  source: "MAM"

# Custom preset
custom:
  tracker: "https://tracker.example.com/announce"
  source: "CUSTOM"
  piece_length: 18  # 256 KiB
```

## Piece Length Reference

| Exponent | Size | Recommended For |
|----------|------|-----------------|
| 16 | 64 KiB | Very small files |
| 17 | 128 KiB | Small files |
| 18 | 256 KiB | Small audiobooks |
| 19 | 512 KiB | Medium audiobooks |
| 20 | 1 MiB | Large audiobooks |
| 21 | 2 MiB | Very large files |
| 22 | 4 MiB | Huge files |
| 23-27 | 8-128 MiB | Extremely large content |

mkbrr auto-calculates optimal piece size based on content size. Manual override with `--piece-length` is rarely needed.

> **Note:** Tracker-specific rules may override manual settings to ensure compliance.

## Troubleshooting

### Docker not available

```
Error: Docker not available
```

**Solution:** Ensure Docker is running and accessible:
```bash
docker --version
docker ps
```

### Permission denied on torrent file

```
Error: Permission denied: /torrentfiles/mybook.torrent
```

**Solution:** shelfr automatically fixes permissions after torrent creation. If issues persist, check Docker volume mount permissions.

### Presets not loading

```
Warning: No presets found
```

**Solution:** Verify `presets.yaml` exists at the configured `host_config_dir`:
```bash
ls -la /mnt/cache/appdata/mkbrr/presets.yaml
```

### Timeout errors

```
Error: Command timed out after 300 seconds
```

**Solution:** Increase `timeout_seconds` in config for large content:
```yaml
mkbrr:
  timeout_seconds: 600  # 10 minutes
```

## See Also

- [mkbrr GitHub](https://github.com/autobrr/mkbrr) - Official mkbrr repository
- [mkbrr Documentation](https://autobrr.com/mkbrr) - Full mkbrr documentation
- [shelfr Configuration](../README.md) - Main shelfr configuration guide
