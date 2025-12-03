# Copilot Instructions for MAMFast

## Project Overview
MAMFast automates audiobook uploads to MyAnonaMouse (MAM): Libation discovery → staging → metadata → torrent → qBittorrent. Built with Python 3.11+, strict typing, and Docker integrations.

## Architecture

### Pipeline Flow
`workflow.py` orchestrates stages via `ReleaseStatus` enum:
```
DISCOVERED → STAGED → METADATA_FETCHED → TORRENT_CREATED → UPLOADED → COMPLETE
```
**Validation checkpoints** run at discovery, post-metadata, and pre-upload stages.

### Core Components
- **`AudiobookRelease`** (`models.py`) - Central data structure flowing through all stages
- **`NormalizedBook`** (`models.py`) - Fixes Audible's title/subtitle swaps using `seriesPrimary` as truth
- **Config sources** (precedence): `config/config.yaml` > `config/.env` > defaults
- **State tracking**: `data/processed.json` prevents reprocessing (keyed by ASIN)
- **Naming rules**: `config/naming.json` - JSON-driven title/author cleanup rules

### Key Module Responsibilities
| Module | Purpose |
|--------|---------|
| `workflow.py` | Pipeline orchestration, retry wrapping |
| `discovery.py` | Find audiobooks in Libation library |
| `hardlinker.py` | Stage files via hardlink + MAM-compliant rename |
| `metadata.py` | Audnex API + MediaInfo fetching |
| `mkbrr.py` | Torrent creation via Docker |
| `validation.py` | Health checks, pre-upload validation, chapter integrity |
| `console.py` | Rich-based CLI output helpers |
| `utils/naming.py` | Filename sanitization, Japanese transliteration (~1900 lines) |

### Title/Subtitle Normalization
Audible often swaps title and subtitle for series books. `NormalizedBook` fixes this:
```python
# Raw from Audible: title="Alicization Exploding", subtitle="Sword Art Online 16"
# seriesPrimary: "Sword Art Online #16"
# Normalized: display_title="Sword Art Online 16", display_subtitle="Alicization Exploding"
# was_swapped=True
```
The `seriesPrimary` field from Audnex is the source of truth for series books.

### Validation Framework
`validation.py` provides structured health checks throughout the pipeline:
```python
from mamfast.validation import ValidationResult, ValidationCheck, CheckCategory

result = ValidationResult()
result.add(ValidationCheck(
    name="library_root",
    passed=path.exists(),
    message=f"Library: {path}",
    severity="error",  # "error" | "warning" | "info"
    category=CheckCategory.PATHS,
))
# result.passed → True only if all error-severity checks pass
```
**Categories**: `CONFIG`, `PATHS`, `SERVICES`, `CATEGORIES`

### Console Output
Use `console.py` helpers for consistent Rich-styled output:
```python
from mamfast.console import print_step, print_success, print_error, print_warning, print_info

print_step(1, 5, "Staging files")       # "Step 1/5: Staging files"
print_success("Hardlinked 3 files")     # "  ✓ Hardlinked 3 files"
print_error("Failed to connect")        # "  ✗ Failed to connect"
print_warning("No cover image")         # "  ! No cover image"
print_info("Using default preset")      # "  → Using default preset"
print_dry_run("Would create torrent")   # "  [DRY RUN] Would create torrent"
```

## Development Commands
```bash
source .venv/bin/activate         # ALWAYS activate venv for Python scripts
pip install -e ".[dev]"           # Install with dev dependencies
pytest                            # Run tests
pytest --cov=src/mamfast          # With coverage
ruff check src/ tests/            # Lint
ruff check --fix src/             # Auto-fix lint
mypy src/                         # Type check (strict mode)
pre-commit run --all-files        # Run all quality checks
```

## Code Patterns

### Required Conventions
```python
from __future__ import annotations  # ALWAYS first import

import logging
from pathlib import Path  # ALWAYS use Path, never string concatenation

logger = logging.getLogger(__name__)  # Module-level logger
```

### Network Calls - Always Use Retry
```python
from mamfast.utils.retry import retry_with_backoff, NETWORK_EXCEPTIONS

@retry_with_backoff(max_attempts=3, base_delay=2.0, exceptions=NETWORK_EXCEPTIONS)
def fetch_data() -> dict: ...
```

### Testing Pattern
- One test file per module (`test_discovery.py` ↔ `discovery.py`)
- Mock external services: Docker, qBittorrent, Audnex API
- Use descriptive class groupings:
```python
class TestFeatureName:
    def test_normal_case(self): ...
    def test_edge_case(self): ...
    def test_error_handling(self): ...
```

## Critical Constraints

### MAM Filename Limit (225 chars)
- **`utils/naming.py`** handles all sanitization and truncation
- Use `truncate_filename()` for files, `build_release_dirname()` for directories
- Long names get hash suffix: `Title...[abc123].m4b`

### Docker Path Mapping
- mkbrr runs in Docker and needs container paths
- `utils/paths.py` provides `host_to_container_path()` / `container_to_host_path()`
- Example: `/mnt/user/data/seedvault/...` → `/data/seedvault/...`

### Configuration Files
- **Never commit**: `config/.env`, `config/config.yaml`, `data/`, `logs/`
- **Templates exist**: `.env.example`, `config.yaml.example`

### Hardlinks Requirement
- `library_root` and `seed_root` must be on same filesystem
- Falls back to copy if hardlink fails (logged as warning)

## Adding Features

### New CLI Command
1. Add subparser in `cli.py` `build_parser()`
2. Create `cmd_yourcommand(args, settings) -> int`
3. Set `parser.set_defaults(func=cmd_yourcommand)`
4. Add tests in `tests/test_cli.py`

### New Config Option
1. Update dataclass in `config.py` (e.g., `MamConfig`)
2. Add parsing in `load_settings()`
3. Update `config.yaml.example`
4. Add tests in `tests/test_config.py`

### New Pipeline Stage
1. Add to `ReleaseStatus` enum in `models.py`
2. Add processing logic in `workflow.py`
3. Add validation checks in `validation.py` if needed
4. Update state tracking in `utils/state.py`

### Filename Processing Changes
1. Update patterns in `config/naming.json` (preferred) or `utils/naming.py`
2. Add golden tests: `tests/golden/naming_inputs.json` → `naming_expected.json`
3. Run `pytest tests/test_golden.py` to validate

## Phase 1 Complete: Pydantic Schema Validation
- **`src/mamfast/schemas/naming.py`** - Pydantic schema for `naming.json` validation
- **`src/mamfast/schemas/audnex.py`** - Pydantic schemas for Audnex API responses (AudnexBook, AudnexChapters)
- **`src/mamfast/schemas/state.py`** - Pydantic schema for `processed.json` state file
- **`src/mamfast/schemas/config.py`** - Pydantic schema for `config.yaml` validation
- **`mamfast validate-config`** - CLI command to validate all config files
- Validates regex patterns, required fields, and structure at config load time
- API responses validated with `extra="allow"` for forward compatibility
- Use `validate_naming_json(data)`, `validate_audnex_book(data)`, `validate_state_file(data)`, `validate_config_yaml(data)` programmatically
- **Note**: `filters.remove_phrases` and `filters.author_map` in `config.yaml` are deprecated - use `naming.json` instead

## Phase 2 Complete: Cross-Platform Filename Safety
- **`src/mamfast/utils/paths.py`** - Added `safe_filename()`, `safe_dirname()`, `safe_filepath()`
- **pathvalidate** wraps all filename generation as safety net
- Catches Windows reserved names (CON, PRN, NUL), trailing dots/spaces, Unicode edge cases
- Integrated into `build_mam_folder_name()` and `build_mam_file_name()` in `naming.py`

## Coming Soon (see docs/IMPROVEMENTS_PLAN.md)
- **Rich enhancements** for debug/dry-run output (Phase 3)
- **rapidfuzz** for fuzzy title matching and duplicate detection (Phase 4)

## Key Files Reference
- `src/mamfast/workflow.py` - Pipeline orchestration
- `src/mamfast/models.py` - `AudiobookRelease`, `ReleaseStatus`, `NormalizedBook`
- `src/mamfast/config.py` - Config loading (~950 lines, complex precedence)
- `src/mamfast/schemas/naming.py` - Pydantic schema for naming.json validation
- `src/mamfast/schemas/audnex.py` - Pydantic schemas for Audnex API responses
- `src/mamfast/schemas/state.py` - Pydantic schema for processed.json state
- `src/mamfast/schemas/config.py` - Pydantic schema for config.yaml validation
- `src/mamfast/utils/naming.py` - Filename sanitization (~1900 lines)
- `src/mamfast/utils/paths.py` - Path utilities + pathvalidate safety wrappers
- `config/naming.json` - Title/author/series cleanup rules (JSON-driven)
- `config/categories.json` - MAM genre → category ID mappings
- `CLAUDE.md` - Detailed AI assistant guide (730 lines)
