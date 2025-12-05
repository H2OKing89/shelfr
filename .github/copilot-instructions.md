# Copilot Instructions for MAMFast

## Project Overview
MAMFast automates audiobook uploads to MyAnonaMouse (MAM): Libation discovery → staging → metadata → torrent → qBittorrent → Audiobookshelf import. Python 3.11+, strict typing, Pydantic validation, Docker integrations.

## Architecture

### Two Pipelines
1. **MAM Upload** (`workflow.py`): `DISCOVERED → STAGED → METADATA_FETCHED → TORRENT_CREATED → UPLOADED → COMPLETE`
2. **ABS Import** (`abs/importer.py`): Moves staged books to Audiobookshelf library with ASIN-based duplicate detection

### Core Data Flow
```
AudiobookRelease (models.py) - flows through all stages
    ↓
NormalizedBook (models.py) - fixes Audible's title/subtitle swaps using seriesPrimary
    ↓
MamPath (models.py) - tracks 225-char path limit compliance with truncation metadata
```

### Module Map
| Module | Purpose |
|--------|---------|
| `workflow.py` | MAM pipeline orchestration |
| `abs/importer.py` | ABS import with duplicate detection |
| `abs/client.py` | Audiobookshelf API client |
| `abs/asin.py` | ASIN extraction and in-memory index |
| `utils/naming.py` | Filename sanitization, Japanese transliteration (~1900 lines) |
| `schemas/*.py` | Pydantic validation for config, API responses, state |
| `console.py` | Rich CLI output (use these helpers, don't write raw print) |

## CLI Usage

### Global Flags (BEFORE subcommand)
```bash
mamfast --dry-run abs-import    # ✓ Correct: global flag before subcommand
mamfast abs-import --dry-run    # ✗ Wrong: subcommand doesn't have own --dry-run
mamfast -v run                  # Verbose logging
mamfast -c /path/config.yaml discover  # Custom config
```

### Key Commands
```bash
mamfast run                     # Full MAM pipeline
mamfast --dry-run run           # Preview full pipeline
mamfast abs-import              # Import staged books to ABS
mamfast --dry-run abs-import    # Preview ABS import
mamfast abs-check-duplicate B0123456789  # Check if ASIN exists
mamfast validate-config         # Validate all config files
```

## Development Commands
```bash
source .venv/bin/activate         # ALWAYS first
pip install -e ".[dev]"           # Install with dev deps
pytest                            # Run tests (~900 tests)
pytest --cov=src/mamfast          # With coverage
ruff check src/ tests/ && mypy src/  # Lint + type check
pre-commit run --all-files        # All quality checks
```

## Code Conventions

### Required in Every File
```python
from __future__ import annotations  # ALWAYS first import

import logging
from pathlib import Path  # ALWAYS use Path, never string concatenation

logger = logging.getLogger(__name__)  # Module-level logger
```

### Network Calls - Always Retry
```python
from mamfast.utils.retry import retry_with_backoff, NETWORK_EXCEPTIONS

@retry_with_backoff(max_attempts=3, base_delay=2.0, exceptions=NETWORK_EXCEPTIONS)
def fetch_data() -> dict: ...
```

### Console Output - Use Helpers
```python
from mamfast.console import print_step, print_success, print_error, print_warning, print_info
print_step(1, 5, "Staging files")  # Not print() or logger for user-facing output
```

### Validation - Use Pydantic
```python
from pydantic import ValidationError
try:
    validated = MySchema.model_validate(raw_data)
except ValidationError as e:
    logger.error(f"Invalid data: {e}")
```

## Critical Constraints

### MAM 225-char Path Limit
- `utils/naming.py` handles truncation with hash suffix: `Title...[abc123].m4b`
- Use `build_mam_folder_name()` and `build_mam_file_name()`, never manual path building
- `pathvalidate` wraps all filename generation for cross-platform safety

### Docker Path Mapping
```python
# mkbrr runs in Docker - convert paths
from mamfast.utils.paths import host_to_container_path
container_path = host_to_container_path(host_path)  # /mnt/user/data/... → /data/...
```

### Same-Filesystem Hardlinks
- `library_root`, `seed_root`, and ABS library must be on same mount for hardlinks
- Falls back to copy if different filesystems (logged as warning)

### Config Precedence
`config/config.yaml` > `config/.env` > defaults

**Never commit**: `config/.env`, `config/config.yaml`, `data/`, `logs/`

## Adding Features

### New CLI Command
```python
# In cli.py build_parser():
parser = subparsers.add_parser("yourcommand", help="...")
# DON'T add --dry-run here - use global flag from parent parser
parser.set_defaults(func=cmd_yourcommand)

# Create handler - args.dry_run comes from global parser:
def cmd_yourcommand(args: argparse.Namespace) -> int:
    """Docstring becomes --help."""
    if args.dry_run:
        print_dry_run("Would do something")
    return 0  # Exit code
```

### New Config Option
1. Add to dataclass in `config.py` (e.g., `MamConfig`)
2. Add Pydantic schema in `schemas/config.py`
3. Update `config.yaml.example`
4. Add tests in `tests/test_config.py`

### New Pydantic Schema
```python
# schemas/yourschema.py
from pydantic import BaseModel, Field, field_validator

class YourSchema(BaseModel):
    name: str = Field(..., min_length=1)

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        return v.strip()
```

### Filename Processing
1. Update patterns in `config/naming.json` (preferred) or `utils/naming.py`
2. Add golden tests: `tests/golden/naming_inputs.json` → `naming_expected.json`
3. Run `pytest tests/test_golden.py`

## Testing Patterns
```python
class TestFeatureName:
    """Group related tests."""
    def test_normal_case(self): ...
    def test_edge_case(self): ...
    def test_error_handling(self):
        with pytest.raises(SpecificError):
            function(invalid_input)
```
- One test file per module (`test_discovery.py` ↔ `discovery.py`)
- Mock external services: Docker, qBittorrent, Audnex API, ABS API

## ABS Import Folder Naming
The importer expects MAM-style folder names with metadata:
```
Author - Series vol_01 - Title (YYYY) (Author) {ASIN.B0123456789} [RipperTag]
```
- **ASIN required** for duplicate detection - folders without `{ASIN.xxx}` go to `Unknown/`
- Series extracted from folder structure or parsed from name
- Duplicate policy: `skip` (default), `warn`, or `overwrite`

## Key Files
- `models.py` - `AudiobookRelease`, `NormalizedBook`, `ReleaseStatus`, `MamPath`
- `config.py` - Config loading (~950 lines, complex precedence)
- `cli.py` - All CLI commands (~2300 lines)
- `utils/naming.py` - All filename logic (~1900 lines)
- `abs/` - Audiobookshelf integration (client, importer, ASIN extraction)
- `schemas/` - Pydantic validation (config, audnex, state, naming)
- `CLAUDE.md` - Extended reference (~900 lines)
