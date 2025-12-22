# CLAUDE.md - AI Assistant Guide for MAMFast

This document provides AI assistants with essential context about the MAMFast codebase, development workflows, and key conventions to follow when making changes.

## Recent Updates (2025-12-22)

**Major changes since last update (2025-12-03)**:

### 🆕 Audiobookshelf Integration
- **New `abs/` module**: Complete ABS API integration for post-upload workflow
- **Import workflow**: Move staged audiobooks into ABS library with duplicate detection
- **Rename tool**: Bulk rename existing ABS library items to MAM conventions
- **Cleanup operations**: Post-import source file cleanup with safety checks
- **Trumping detection**: Identify when new uploads supersede existing library items
- **ASIN indexing**: Fast in-memory ASIN index for duplicate detection (~200ms build)

### 🏗️ Architecture Improvements
- **Command reorganization**: Split `cli.py` into organized modules (`commands/`)
  - `core.py` - Main workflow commands
  - `abs.py` - Audiobookshelf integration
  - `state.py` - State management
  - `utility.py` - Status and diagnostics
  - `diagnostics.py` - Analysis and validation
- **Exception hierarchy**: Typed exceptions in `exceptions.py` for better error handling
- **Circuit breaker pattern**: Prevent cascading failures in external API calls
- **Naming refactoring**: Split monolithic `naming.py` into focused modules

### 📦 Package Upgrades
- **tenacity**: Replaced custom retry logic with industry-standard library
- **sh library**: Better subprocess execution (replacing raw `subprocess`)
- **platformdirs**: Cross-platform directory handling
- **rapidfuzz**: Fuzzy string matching for duplicate detection
- **pydantic-settings**: Environment-based configuration

### 🔧 State Management
- **Schema v2**: Enhanced state file format with atomic writes
- **Migration support**: Automatic v1 → v2 migration
- **Validation**: Comprehensive validation with helpful error messages

### 📚 Documentation
- **Reorganized docs/**: Moved technical docs to `docs/` directory
- **ABS documentation**: Extensive guides in `docs/audiobookshelf/`
- **Archive directory**: Completed implementation reports in `docs/archive/`

## Repository Overview

**MAMFast** is a Python-based automation tool for preparing and uploading audiobooks to MyAnonaMouse (MAM). It orchestrates a complete pipeline from Libation audiobook library discovery to torrent creation and qBittorrent upload.

**Key Purpose**: Automate the tedious workflow of:
1. Discovering audiobooks in Libation library
2. Staging files with MAM-compliant naming (≤225 chars)
3. Fetching metadata from Audnex API and MediaInfo
4. Creating .torrent files via mkbrr
5. Uploading to qBittorrent with proper categories/tags

**Technology Stack**:
- Python 3.11+ (strict type checking with mypy)
- Pydantic 2.0+ for data validation and schemas (including pydantic-settings)
- pathvalidate for robust filename sanitization
- tenacity for retry logic with exponential backoff
- rapidfuzz for fuzzy string matching
- sh library for subprocess execution
- platformdirs for cross-platform directory handling
- Docker (for Libation, Audiobookshelf, and mkbrr containers)
- External services: qBittorrent API, Audnex API, Audiobookshelf API
- CLI interface with Rich for pretty output

## Project Structure

```
mam_tool/
├── src/mamfast/               # Main package
│   ├── __init__.py           # Version: 0.1.0
│   ├── cli.py                # Command-line interface (argparse)
│   ├── config.py             # Configuration loading (.env, YAML, JSON)
│   ├── env_settings.py       # Pydantic-based environment settings
│   ├── models.py             # Data models (AudiobookRelease, NormalizedBook, MamPath, etc.)
│   ├── workflow.py           # Pipeline orchestration
│   ├── discovery.py          # Find audiobooks in Libation library
│   ├── hardlinker.py         # Stage files (hardlink + MAM-compliant rename)
│   ├── metadata.py           # Audnex + MediaInfo fetching
│   ├── mkbrr.py              # Torrent creation via Docker
│   ├── qbittorrent.py        # qBittorrent API client
│   ├── libation.py           # Libation Docker wrapper
│   ├── logging_setup.py      # Logging configuration
│   ├── console.py            # Rich console output formatting
│   ├── validation.py         # Configuration and data validation
│   ├── exceptions.py         # Typed exception hierarchy
│   ├── paths.py              # Path utilities
│   ├── abs/                  # Audiobookshelf integration
│   │   ├── __init__.py       # ABS module exports
│   │   ├── client.py         # ABS API client
│   │   ├── asin.py           # ASIN extraction & in-memory indexing
│   │   ├── importer.py       # Import workflow (staged → ABS library)
│   │   ├── rename.py         # Bulk rename tool
│   │   ├── cleanup.py        # Post-import cleanup (delete/archive source)
│   │   ├── paths.py          # Host ↔ ABS container path mapping
│   │   └── trumping.py       # Duplicate detection & trumping logic
│   ├── commands/             # CLI command implementations (organized)
│   │   ├── __init__.py       # Command exports
│   │   ├── core.py           # Main workflow (scan, discover, prepare, run)
│   │   ├── abs.py            # ABS commands (import, rename, cleanup, etc.)
│   │   ├── state.py          # State management (list, prune, retry, clear)
│   │   ├── utility.py        # Status & validation (status, config, check)
│   │   └── diagnostics.py    # Analysis (duplicates, suspicious, dry-run)
│   ├── schemas/              # Pydantic validation schemas
│   │   ├── __init__.py       # Schema exports
│   │   ├── audnex.py         # Audnex API response validation
│   │   ├── config.py         # Configuration YAML validation
│   │   ├── naming.py         # Naming conventions validation
│   │   ├── state.py          # State file validation (v1 & v2 schemas)
│   │   └── abs.py            # ABS API response validation
│   ├── templates/            # Jinja2 templates for MAM BBCode
│   │   └── mam_description.j2
│   └── utils/
│       ├── __init__.py
│       ├── circuit_breaker.py # Circuit breaker pattern for network calls
│       ├── cmd.py            # Subprocess execution wrapper (using sh library)
│       ├── fuzzy.py          # Fuzzy string matching (rapidfuzz)
│       ├── paths.py          # Host↔container path mapping
│       ├── permissions.py    # File permission utilities
│       ├── retry.py          # Exponential backoff decorator (tenacity)
│       ├── state.py          # Processed release tracking (JSON, v2 schema)
│       ├── torrent.py        # Torrent utilities
│       ├── validate_naming.py # Naming validation utilities
│       └── naming/           # Naming system (refactored into modules)
│           ├── __init__.py   # Naming exports
│           ├── authors.py    # Author name processing
│           ├── constants.py  # Naming constants & patterns
│           ├── filters.py    # Title/author filtering
│           ├── mam_paths.py  # MAM path generation with truncation
│           ├── normalization.py # Audnex metadata normalization
│           ├── series_parsing.py # Series name extraction
│           ├── string_utils.py # String manipulation utilities
│           └── volume_parsing.py # Volume number parsing
├── tests/                     # Pytest test suite
│   ├── test_discovery.py     # Discovery module tests
│   ├── test_models.py        # Data model tests
│   ├── test_config.py        # Configuration loading tests
│   ├── test_env_settings.py  # Environment settings tests
│   ├── test_naming.py        # Filename sanitization tests
│   ├── test_hardlinker.py    # Hardlinking tests
│   ├── test_metadata.py      # Metadata fetching tests
│   ├── test_mkbrr.py         # Torrent creation tests
│   ├── test_qbittorrent.py   # qBittorrent API tests
│   ├── test_libation.py      # Libation wrapper tests
│   ├── test_retry.py         # Retry logic tests
│   ├── test_paths.py         # Path mapping tests
│   ├── test_state.py         # State tracking tests
│   ├── test_integration.py   # End-to-end tests
│   ├── test_console.py       # Console output tests
│   ├── test_validation.py    # Validation logic tests
│   ├── test_exceptions.py    # Exception hierarchy tests
│   ├── test_schemas.py       # Pydantic schema tests
│   ├── test_audnex_schema.py # Audnex schema validation tests
│   ├── test_config_schema.py # Config schema validation tests
│   ├── test_state_schema.py  # State schema validation tests
│   ├── test_normalization.py # Book normalization tests
│   ├── test_pathvalidate.py  # pathvalidate integration tests
│   ├── test_golden.py        # Golden file regression tests
│   ├── test_golden_normalization.py # Golden normalization tests
│   ├── test_circuit_breaker.py # Circuit breaker tests
│   ├── test_fuzzy.py         # Fuzzy matching tests
│   ├── test_series_resolution.py # Series resolution tests
│   ├── test_trumping.py      # Trumping logic tests
│   ├── test_abs_asin.py      # ABS ASIN extraction tests
│   ├── test_abs_client.py    # ABS API client tests
│   ├── test_abs_cleanup.py   # ABS cleanup tests
│   ├── test_abs_importer.py  # ABS importer tests
│   ├── test_abs_paths.py     # ABS path mapping tests
│   ├── test_abs_rename.py    # ABS rename tests
│   ├── test_abs_schemas.py   # ABS schema tests
│   ├── test_cli_abs.py       # ABS CLI command tests
│   ├── fixtures/             # Test fixtures directory
│   └── golden/               # Golden files for regression testing
├── config/
│   └── categories.json       # MAM genre → category ID mappings
├── .github/workflows/
│   ├── ci.yml               # CI: lint, type check, test (Python 3.11, 3.12, 3.13)
│   └── dependency-review.yml # Security: dependency scanning
├── pyproject.toml           # Build config, dependencies, tool settings
├── .pre-commit-config.yaml  # Pre-commit hooks (ruff, mypy, pytest)
├── .gitignore               # Ignores: .env, config/config.yaml, data/, logs/
├── config.yaml.example      # Template for user config
├── .env.example             # Template for secrets
├── README.md                # User documentation
├── CONTRIBUTING.md          # Contribution guidelines
├── SECURITY.md              # Security policy
├── CHANGELOG.md             # Version history
├── CLAUDE.md                # AI assistant guide (this file)
├── docs/                    # Technical documentation
│   ├── README.md            # Documentation directory overview
│   ├── archive/             # Completed implementation reports
│   │   ├── P0_UPGRADE_COMPLETE.md
│   │   ├── P1_SH_LIBRARY_COMPLETE.md
│   │   ├── REFACTORING_SUMMARY.md
│   │   └── ...
│   ├── audiobookshelf/      # ABS integration documentation
│   │   ├── AUDIOBOOKSHELF_IMPORT.md # Import workflow
│   │   ├── AUDIOBOOKSHELF_API.md    # API reference
│   │   ├── ABS_RENAME_TOOL.md       # Rename tool guide
│   │   ├── CLEANUP_PLAN.md          # Cleanup strategies
│   │   ├── TRUMPING.md              # Duplicate detection
│   │   └── ...
│   ├── naming/              # Naming system documentation
│   │   ├── NAMING.md
│   │   ├── NAMING_RULES.md
│   │   ├── NAMING_PIPELINE.md
│   │   └── ...
│   ├── tracked_issues/      # Active issue tracking
│   ├── MIGRATION_BACKLOG.md # Deferred migrations
│   ├── PACKAGE_UPGRADE_PLAN.md # Future upgrades
│   ├── STATE_HARDENING_PLAN.md # State management improvements
│   └── VALIDATION_PLAN.md   # Input validation enhancements
└── scripts/                 # Development scripts
    ├── build_golden_samples.py
    ├── fetch_abs_library.py
    ├── scan_abs_library.py
    └── test_abs_search.py
```

## Architecture & Core Concepts

### Pipeline Stages (workflow.py)

The application follows a linear pipeline model with distinct stages:

```
Libation Scan → Discovery → Staging → Metadata → Torrent → Upload → Complete
```

Each stage is represented by `ReleaseStatus` enum values:
- `DISCOVERED` - Found in Libation library
- `STAGED` - Files hardlinked to staging directory
- `METADATA_FETCHED` - Audnex + MediaInfo complete
- `TORRENT_CREATED` - .torrent file generated
- `UPLOADED` - Added to qBittorrent
- `COMPLETE` - Fully processed
- `FAILED` - Processing error occurred

### Core Data Model (models.py)

**`AudiobookRelease`** is the central data structure that flows through the pipeline:

```python
@dataclass
class AudiobookRelease:
    # Identity
    asin: str | None          # Audible ASIN (10-char primary ID)
    title: str
    author: str
    narrator: str | None
    series: str | None
    series_position: str | None
    year: str | None

    # Paths
    source_dir: Path | None   # Original Libation directory
    staging_dir: Path | None  # Hardlinked upload workspace
    main_m4b: Path | None     # Primary audiobook file

    # Files & State
    files: list[Path]
    status: ReleaseStatus
    torrent_path: Path | None
    error: str | None

    # Metadata
    audnex_metadata: dict[str, Any] | None
    mediainfo_data: dict[str, Any] | None
    audnex_chapters: dict[str, Any] | None  # Audnex chapters API response

    # Timestamps
    discovered_at: datetime | None
    processed_at: datetime | None
```

**Key Properties**:
- `display_name` - Human-readable name for logging: "Author - Title"
- `safe_dirname` - Filesystem-safe directory name with sanitized characters

**`NormalizedBook`** handles Audible's inconsistent title/subtitle swapping:

```python
@dataclass
class NormalizedBook:
    """
    Canonical book metadata after Audnex normalization.

    Fixes Audible's inconsistent title/subtitle swapping by using seriesPrimary
    as the source of truth.
    """
    asin: str
    raw_title: str                    # Original title from Audible
    raw_subtitle: str | None          # Original subtitle from Audible
    series_name: str | None           # From seriesPrimary
    series_position: str | None       # From seriesPrimary
    arc_name: str | None              # Extracted arc name
    display_title: str                # Corrected title for display
    display_subtitle: str | None      # Corrected subtitle for display
    was_swapped: bool                 # True if title/subtitle were swapped
```

**`MamPath`** tracks MAM path generation with truncation metadata:

```python
@dataclass
class MamPath:
    """
    Result of MAM path generation with truncation metadata.

    MAM enforces a 225-character limit for the full relative path
    (folder/filename combined).
    """
    folder: str                       # e.g., "Series vol_01 ... [H2OKing]"
    filename: str                     # e.g., "Series vol_01 ....m4b"
    full_path: str                    # folder + "/" + filename
    length: int                       # len(full_path)
    truncated: bool                   # True if truncation occurred
    dropped_components: list[str]     # Components dropped during truncation
```

**Key Property**:
- `over_limit` - Returns True if path exceeds 225 characters

### Configuration System (config.py)

Configuration is loaded from **three sources** with clear precedence:

1. **`config/config.yaml`** - Structured settings (paths, MAM compliance, service configs)
2. **`config/.env`** - Secrets (qBittorrent credentials)
3. **`config/categories.json`** - MAM genre → category ID mappings

**Configuration precedence for environment vars**:
```
config.yaml environment section > .env file > hardcoded defaults
```

**Critical Settings Classes**:
- `PathsConfig` - File paths (library_root, seed_root, torrent_output, state_file, log_file)
- `MamConfig` - MAM compliance (max_filename_length: 225, allowed_extensions)
- `QBittorrentConfig` - qBittorrent settings + credentials
- `MkbrrConfig` - mkbrr Docker configuration
- `AudnexConfig` - Audnex API settings
- `FiltersConfig` - Title filtering, author mapping, Japanese transliteration

**Path Resolution Rules**:
- Absolute paths used as-is
- Relative paths in config.yaml resolved relative to **project root** (parent of config/)

### State Tracking (utils/state.py)

Persistent state stored in `data/processed.json` to prevent re-processing:

```python
@dataclass
class ProcessedState:
    asin: str                 # Primary key
    title: str
    author: str
    processed_at: str         # ISO format datetime
    staging_dir: str
    torrent_path: str | None
    status: str               # ReleaseStatus name
```

Functions:
- `is_processed(asin: str) -> bool` - Check if ASIN already processed
- `mark_processed(release: AudiobookRelease)` - Save successful completion
- `mark_failed(release: AudiobookRelease)` - Record failure

### Retry Logic (utils/retry.py)

Network operations use **tenacity** library for exponential backoff:

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True
)
def network_operation():
    ...
```

**Key Features**:
- Configurable max retries and delay
- Exponential backoff with jitter
- Specific exception filtering
- Used for: Audnex API, qBittorrent API, ABS API, Docker operations

### Circuit Breaker Pattern (utils/circuit_breaker.py)

**NEW**: Circuit breaker pattern for external services to prevent cascading failures:

```python
from mamfast.utils.circuit_breaker import CircuitBreaker, CircuitState

breaker = CircuitBreaker(
    failure_threshold=5,      # Open after 5 failures
    recovery_timeout=60.0,    # Try again after 60 seconds
    expected_exception=AudnexError
)

@breaker
def call_external_api():
    # Will raise CircuitOpenError if circuit is open
    ...
```

**States**:
- `CLOSED` - Normal operation
- `OPEN` - Too many failures, reject all calls
- `HALF_OPEN` - Testing if service recovered

### Exception Hierarchy (exceptions.py)

**NEW**: Typed exception hierarchy for better error handling:

```
MAMFastError (base)
├── ConfigurationError - Config file issues
├── ValidationError - Pre-flight/runtime validation
│   ├── DiscoveryValidationError
│   └── PreUploadValidationError
├── PipelineError - Stage execution failures
│   ├── StagingError
│   ├── MetadataError
│   ├── TorrentError
│   └── UploadError
├── NetworkError - External service failures
│   ├── AudnexError
│   ├── QBittorrentError
│   └── AudiobookshelfError
├── StateError - State file operations
│   ├── StateLockError
│   └── StateCorruptionError
└── ExternalToolError - Docker/subprocess failures
    ├── DockerError
    ├── MkbrrError
    └── LibationError
```

**All exceptions include**:
- `message` - Human-readable error
- `details` - Structured metadata for logging

**Example**:
```python
from mamfast.exceptions import MetadataError, AudnexError

try:
    metadata = fetch_audnex_metadata(asin)
except AudnexError as e:
    raise MetadataError(
        f"Failed to fetch metadata for {asin}",
        release_asin=asin,
        details={"service": "audnex", "error": str(e)}
    ) from e
```

### Pydantic Validation (schemas/)

**Pydantic 2.0+ is used for comprehensive data validation** throughout the codebase:

**Configuration Validation** (`schemas/config.py`):
- `ConfigSchema` - Main configuration YAML structure
- `PathsSchema` - File path validation with existence checks
- `MamSchema` - MAM compliance settings
- `QBittorrentSchema` - qBittorrent configuration with URL validation
- `MkbrrSchema` - mkbrr Docker configuration
- `AudnexSchema` - Audnex API settings
- `LibationSchema` - Libation discovery configuration
- `MediaInfoSchema` - MediaInfo configuration
- `FiltersSchema` - Filtering and transliteration settings
- `EnvironmentSchema` - Environment variable validation

**Audnex API Validation** (`schemas/audnex.py`):
- `AudnexBook` - Book metadata from Audnex API
- `AudnexAuthor` - Author information
- `AudnexSeries` - Series metadata
- `AudnexGenre` - Genre information
- `AudnexChapter` - Chapter data
- `AudnexChaptersResponse` - Chapters API response

**State Management** (`schemas/state.py`):
- `ProcessedRelease` - Successfully processed release tracking
- `FailedRelease` - Failed release tracking
- `ProcessedState` - Complete state file structure

**Naming Conventions** (`schemas/naming.py`):
- `NamingSchema` - Naming rules and patterns validation

**Validation Functions**:
```python
from mamfast.schemas import validate_config_yaml, validate_audnex_book

# Validate configuration
config = validate_config_yaml(config_dict)

# Validate Audnex API response
book = validate_audnex_book(api_response)
```

**Benefits**:
- Early error detection with clear error messages
- Type safety at runtime
- Automatic data coercion where appropriate
- Prevents invalid data from propagating through pipeline

### pathvalidate Integration (utils/naming.py)

**pathvalidate library** provides robust, cross-platform filename sanitization:

**Key Features**:
- Validates filenames across Windows, macOS, Linux
- Handles Unicode normalization
- Sanitizes invalid characters per platform
- Respects MAM's 225-character path limit

**Usage**:
```python
from pathvalidate import sanitize_filename

# Sanitize with platform-aware rules
safe_name = sanitize_filename(
    user_input,
    platform="universal",  # Works on all platforms
    max_len=225           # MAM path limit
)
```

**Integration Points**:
- `utils/naming.py` - Filename sanitization with MAM compliance
- `utils/validate_naming.py` - Naming validation utilities
- `hardlinker.py` - File staging with validated names

### Audiobookshelf Integration (abs/)

**NEW: Post-upload workflow** for importing MAM-prepared audiobooks into your Audiobookshelf library.

**Architecture**:
- **ABS API as source of truth**: Uses Audiobookshelf API to discover existing books
- **In-memory ASIN indexing**: Fast duplicate detection (~200ms to build, ~1µs per lookup)
- **MAM folder parsing**: Extracts metadata from staging folder names
- **Docker path mapping**: Translates host paths ↔ ABS container paths
- **Atomic moves**: Instant file operations that preserve hardlinks to seed folder

**Key Modules**:

1. **`abs/client.py`** - Audiobookshelf API client
   ```python
   class AbsClient:
       def get_libraries() -> list[AbsLibrary]
       def get_library_items(library_id: str) -> list[AbsLibraryItem]
       def scan_library(library_id: str) -> bool
   ```

2. **`abs/asin.py`** - ASIN extraction and in-memory indexing
   ```python
   def build_asin_index(items: list[AbsLibraryItem]) -> dict[str, AsinEntry]
   def extract_asin(text: str) -> str | None
   def asin_exists(asin: str, index: dict) -> bool
   def resolve_asin_via_abs_search(client: AbsClient, title: str, author: str) -> str | None
   ```

3. **`abs/importer.py`** - Import workflow
   ```python
   def discover_staged_books(staging_dir: Path) -> list[ParsedFolderName]
   def import_single(source: Path, target: Path) -> ImportResult
   def import_batch(staging_dir: Path, target_lib: Path, client: AbsClient) -> BatchImportResult
   ```

4. **`abs/rename.py`** - Bulk rename tool for existing ABS library
   ```python
   def discover_rename_candidates(client: AbsClient, library_id: str) -> list[RenameCandidate]
   def run_rename_pipeline(client: AbsClient, library_id: str, dry_run: bool) -> RenameSummary
   ```

5. **`abs/cleanup.py`** - Post-import cleanup (delete/archive source)
   ```python
   def cleanup_source(source_path: Path, strategy: CleanupStrategy) -> CleanupResult
   def verify_seed_exists(abs_path: Path, seed_root: Path) -> bool
   ```

6. **`abs/trumping.py`** - Duplicate detection logic
   - Detects when new upload is better quality (trumps existing)
   - Compares bitrates, file formats, edition flags

**CLI Commands** (`commands/abs.py`):
- `mamfast abs-init` - Test ABS connection, list libraries
- `mamfast abs-import` - Import staged books into ABS library
- `mamfast abs-check-duplicate <ASIN>` - Check if ASIN exists in library
- `mamfast abs-rename` - Bulk rename existing ABS library items
- `mamfast abs-cleanup` - Delete/archive source files after import
- `mamfast abs-trump-check` - Detect trumpable duplicates
- `mamfast abs-orphans` - Find ABS items without corresponding seed files
- `mamfast abs-resolve-asins` - Find ASINs for books via search

**Configuration** (`config.yaml`):
```yaml
audiobookshelf:
  url: "http://localhost:13378"
  token: "${ABS_TOKEN}"
  library_id: "lib_xyz123"
  library_path: "/audiobooks"  # Path inside ABS container
  host_library_path: "/mnt/user/media/audiobooks"  # Host path

  # Path mapping for Docker
  path_mappings:
    - container: "/audiobooks"
      host: "/mnt/user/media/audiobooks"
```

**Integrated Workflow**:
```
Libation → Discovery → Staging → Torrent → qBittorrent → ABS Import → ABS Cleanup
                         ↓                                    ↓
                    seed_root/                         abs_library/
```

**Key Features**:
- **Duplicate detection**: Fast in-memory ASIN index prevents re-imports
- **Trumping logic**: Detects when new upload is better quality
- **Fuzzy matching**: Uses rapidfuzz for author/title matching when ASIN missing
- **Safe cleanup**: Verifies hardlink to seed folder before deletion
- **Bulk operations**: Process entire staging directory in one command

## Development Workflows

### Setting Up Development Environment

```bash
# Clone and setup
git clone <repo-url> mamfast
cd mamfast
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install

# Copy config templates
cp .env.example config/.env
cp config.yaml.example config/config.yaml

# Edit with your settings
$EDITOR config/.env config/config.yaml
```

### Pre-Commit Quality Checks

**Every commit runs**:
1. **ruff** - Linting + import sorting (`ruff check --fix`)
2. **ruff-format** - Code formatting
3. **mypy** - Strict type checking (`mypy src/`)
4. **pytest** - Full test suite

**Manual run**:
```bash
pre-commit run --all-files
```

### Testing

```bash
# Run all tests
pytest

# With coverage
pytest --cov=src/mamfast --cov-branch --cov-report=term

# Specific test file
pytest tests/test_discovery.py

# Specific test
pytest tests/test_discovery.py::TestDiscoverNewReleases::test_finds_new_releases

# Verbose output
pytest -v
```

**Test Organization**:
- One test file per module (e.g., `test_discovery.py` for `discovery.py`)
- Use classes to group related tests (e.g., `TestIsValidAsin`)
- Use descriptive test names (e.g., `test_valid_b_prefix_asin`)
- Mock external services (Docker, qBittorrent, Audnex API)

### Linting & Formatting

```bash
# Check linting
ruff check src/ tests/

# Auto-fix linting issues
ruff check --fix src/ tests/

# Format code
ruff format src/ tests/

# Type checking
mypy src/
```

**Ruff Configuration** (pyproject.toml):
- Line length: 100 characters
- Target: Python 3.11+
- Selected rules: E, F, I, N, W, UP, B, C4, SIM

**Mypy Configuration**:
- Strict mode enabled
- Python 3.11 target
- Ignore missing imports for `pykakasi`

### CI/CD Pipeline

**On every push/PR to main**:
1. **Test Matrix** (Python 3.11, 3.12, 3.13):
   - Install dependencies
   - Lint with ruff
   - Type check with mypy
   - Run tests with coverage
   - Upload coverage to Codecov
2. **Security Check**:
   - Run pip-audit for vulnerable dependencies

**Workflows**:
- `.github/workflows/ci.yml` - Main CI pipeline
- `.github/workflows/dependency-review.yml` - Dependency security scanning

## Code Conventions

### Style Guidelines

1. **Type Hints**: Mandatory for all function signatures
   ```python
   def process_release(
       release: AudiobookRelease,
       *,
       dry_run: bool = False,
   ) -> ProcessingResult:
       """Process a single audiobook release."""
       ...
   ```

2. **Docstrings**: Required for public functions and classes
   ```python
   def stage_release(release: AudiobookRelease) -> Path:
       """
       Stage files for upload using hardlinks.

       Args:
           release: The release to stage

       Returns:
           Path to staging directory

       Raises:
           ValueError: If release has no source directory
       """
       ...
   ```

3. **Imports**: Organized by ruff (stdlib → third-party → local)
   ```python
   from __future__ import annotations  # Always first

   import logging
   from pathlib import Path

   import httpx
   from rich.progress import Progress

   from mamfast.models import AudiobookRelease
   ```

4. **Error Handling**: Use specific exceptions
   ```python
   class ConfigurationError(Exception):
       """Raised when configuration is invalid."""
       pass
   ```

5. **Path Handling**: Always use `pathlib.Path`, never string concatenation
   ```python
   # Good
   torrent_path = output_dir / f"{release.asin}.torrent"

   # Bad
   torrent_path = output_dir + "/" + release.asin + ".torrent"
   ```

6. **Logging**: Use module-level logger
   ```python
   logger = logging.getLogger(__name__)
   logger.info(f"Processing {release.display_name}")
   logger.error(f"Failed to create torrent: {e}")
   ```

### Naming Conventions

- **Functions/Variables**: `snake_case`
- **Classes**: `PascalCase`
- **Constants**: `UPPER_SNAKE_CASE`
- **Private/Internal**: `_leading_underscore`

### File Organization Patterns

**Module Structure**:
```python
"""Module docstring explaining purpose."""

from __future__ import annotations

# Imports (stdlib, third-party, local)
import logging
from pathlib import Path

# Constants
ASIN_PATTERN = r"^[A-Z0-9]{10}$"

# Logger
logger = logging.getLogger(__name__)

# Exceptions
class ModuleError(Exception):
    """Module-specific exception."""
    pass

# Main implementation
def main_function() -> None:
    """Public API."""
    ...

def _helper_function() -> None:
    """Internal helper."""
    ...
```

## Security & Secrets Management

### Critical Security Rules

**NEVER commit these to Git**:
- `config/.env` - Contains QB credentials
- `config/config.yaml` - May contain user-specific paths or secrets
- `data/processed.json` - State file with ASINs
- `logs/*.log` - May contain sensitive data

**Gitignored by default**:
- `.env` (anywhere)
- `config/config.yaml`
- `config/.env`
- `data/`
- `logs/`

### Configuration File Security

**Template Files** (committed):
- `.env.example` - Template showing required env vars (no values)
- `config.yaml.example` - Template showing structure (no secrets)

**User Files** (gitignored):
- `config/.env` - Actual secrets
- `config/config.yaml` - Actual configuration

### Sensitive Data Handling

**Always validate URLs**:
```python
if not url.startswith(("http://", "https://")):
    raise ConfigurationError(f"{field_name} must start with http:// or https://")
```

**Never log credentials**:
```python
# Good
logger.info(f"Connecting to qBittorrent at {settings.qbittorrent.host}")

# Bad
logger.debug(f"QB password: {settings.qbittorrent.password}")  # NEVER DO THIS
```

## Common Tasks for AI Assistants

### Adding a New CLI Command

**Commands are now organized into modules** in `src/mamfast/commands/`:

1. **Choose the appropriate module**:
   - `commands/core.py` - Main workflow commands (scan, discover, run)
   - `commands/abs.py` - Audiobookshelf integration
   - `commands/state.py` - State management
   - `commands/utility.py` - Status and diagnostics
   - `commands/diagnostics.py` - Analysis and validation

2. **Create command function** in the chosen module:
   ```python
   def cmd_yourcommand(args: argparse.Namespace, settings: Settings) -> int:
       """Command implementation."""
       try:
           # Implementation here
           return 0  # Success
       except MAMFastError as e:
           logger.error(f"Error: {e}")
           return 1  # Failure
   ```

3. **Export from `commands/__init__.py`**:
   ```python
   from mamfast.commands.yourmodule import cmd_yourcommand

   __all__ = [
       # ... other exports
       "cmd_yourcommand",
   ]
   ```

4. **Register in `cli.py`**: Add subparser in `build_parser()`
   ```python
   yourcommand_parser = subparsers.add_parser(
       "yourcommand",
       help="Brief description"
   )
   yourcommand_parser.add_argument("--option", help="Option help")
   yourcommand_parser.set_defaults(func=cmd_yourcommand)
   ```

5. **Add tests** in appropriate test file (e.g., `tests/test_cli_yourmodule.py`)
6. **Update README.md** usage section

### Adding Configuration Options

1. **Update data class** in `config.py` (e.g., `MamConfig`)
2. **Add parsing logic** in `load_settings()`
3. **Add validation** in `validate_settings()` if needed
4. **Update `config.yaml.example`** with new field + comments
5. **Add tests** in `tests/test_config.py`
6. **Update README.md** configuration section

### Adding External API Integration

1. **Create module** `src/mamfast/newservice.py`
2. **Define config class** in `config.py` (e.g., `NewServiceConfig`)
3. **Define Pydantic schema** in `schemas/newservice.py` for API responses
4. **Add retry decorator** for network calls (use tenacity)
5. **Add circuit breaker** if the service is unreliable
6. **Define specific exceptions** in `exceptions.py` (inherit from `NetworkError`)
7. **Handle errors gracefully** with typed exceptions
8. **Add comprehensive tests** with mocked responses
9. **Update dependencies** in `pyproject.toml` if needed

### Adding Audiobookshelf Features

**For new ABS integration features**:

1. **Choose the appropriate module**:
   - `abs/client.py` - API client methods
   - `abs/asin.py` - ASIN extraction/indexing
   - `abs/importer.py` - Import workflow
   - `abs/rename.py` - Rename operations
   - `abs/cleanup.py` - Cleanup operations
   - `abs/trumping.py` - Duplicate detection

2. **Add the feature**:
   - Use `AbsClient` for API calls
   - Raise `AudiobookshelfError` for API failures
   - Use `PathMapper` for container ↔ host path translation
   - Add retry logic with tenacity
   - Add circuit breaker if needed

3. **Add CLI command** in `commands/abs.py`:
   ```python
   def cmd_abs_yourfeature(args: argparse.Namespace, settings: Settings) -> int:
       """Your ABS feature."""
       client = AbsClient(settings.audiobookshelf.url, settings.audiobookshelf.token)
       # Feature implementation
       return 0
   ```

4. **Add tests** in `tests/test_abs_yourmodule.py`:
   - Mock `AbsClient` API calls
   - Test path mapping
   - Test error handling

5. **Document in `docs/audiobookshelf/`**:
   - Add usage examples
   - Explain configuration
   - Document edge cases

### Modifying the Pipeline

1. **Update `ReleaseStatus` enum** in `models.py` if adding stages
2. **Add processing function** in appropriate module
3. **Update `workflow.py`** orchestration logic
4. **Update state tracking** in `utils/state.py` if needed
5. **Add tests** for new stage
6. **Update README.md** pipeline diagram

### Adding Pydantic Schema Validation

1. **Create schema** in appropriate `schemas/*.py` file
2. **Define Pydantic model** with Field validators
   ```python
   from pydantic import BaseModel, Field, field_validator

   class MySchema(BaseModel):
       name: str = Field(..., min_length=1, description="Display name")
       count: int = Field(ge=0, le=100, description="Item count")

       @field_validator('name')
       @classmethod
       def validate_name(cls, v: str) -> str:
           if not v.strip():
               raise ValueError("Name cannot be empty")
           return v.strip()
   ```
3. **Export from `schemas/__init__.py`**
4. **Add validation function** if needed (e.g., `validate_myschema()`)
5. **Add comprehensive tests** in `tests/test_*_schema.py`
6. **Update calling code** to use validation
7. **Document in CLAUDE.md** if it's a major schema

## Testing Patterns

### Mock External Services

```python
from unittest.mock import MagicMock, patch

@patch("mamfast.qbittorrent.qbittorrentapi.Client")
def test_upload_torrent(mock_client):
    """Test torrent upload to qBittorrent."""
    mock_qb = MagicMock()
    mock_client.return_value = mock_qb

    upload_torrent(torrent_path, release)

    mock_qb.torrents_add.assert_called_once()
```

### Test File Structure

```python
class TestFeatureGroup:
    """Tests for related feature."""

    def test_normal_case(self):
        """Test expected behavior."""
        assert function(valid_input) == expected_output

    def test_edge_case(self):
        """Test boundary condition."""
        assert function(edge_input) == edge_output

    def test_error_case(self):
        """Test error handling."""
        with pytest.raises(SpecificError):
            function(invalid_input)
```

### Fixtures for Common Setup

```python
import pytest
import tempfile
from pathlib import Path

@pytest.fixture
def temp_library():
    """Create temporary Libation library structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        library = Path(tmpdir)
        (library / "Author - Title").mkdir()
        yield library
```

## Important Gotchas & Constraints

### MAM Filename Length Limit

**CRITICAL**: MAM enforces a 225-character limit on filenames
- `max_filename_length` in config (default: 225)
- `utils/naming.py` handles truncation with `truncate_to_max_length()`
- Always test with long author/title combinations

### Docker Path Mapping

**Host vs. Container paths** must be correctly mapped:
- `utils/paths.py` provides `host_to_container_path()` and reverse
- mkbrr runs in Docker, needs container paths
- qBittorrent needs host paths for seeding

Example:
```python
# Host path
host_path = Path("/mnt/user/data/seedvault/audiobooks/release")

# Container path for mkbrr
container_path = "/data/seedvault/audiobooks/release"
```

### Japanese Name Transliteration

**pykakasi** is used for Japanese → Romaji conversion:
- `utils/naming.py` - `transliterate_japanese_text()`
- Only applies if `filters.transliterate_japanese = True`
- Author mapping in config takes precedence over auto-transliteration

### State File Concurrency

**`data/processed.json` is not thread-safe**:
- Current implementation uses simple file I/O
- Do NOT run multiple instances simultaneously
- Future: Consider using SQLite or file locking

### Hardlinking Requirements

**Hardlinks require same filesystem**:
- `library_root` and `seed_root` must be on same mount
- Falls back to copying if hardlink fails (slow!)
- Check logs for "Created hardlink" vs "Copied file"

### ASIN as Primary Key

**ASIN is the canonical identifier**:
- 10 alphanumeric characters (e.g., `B09GHD1R2R`)
- Used for deduplication in state tracking
- Some releases may lack ASIN (fallback: folder name)

### Pydantic Validation Strictness

**Pydantic validation is strict by default**:
- All schemas validate data at runtime
- Invalid data raises `ValidationError` with detailed messages
- Validation happens at configuration load, API response parsing, and state file reads
- **Always catch ValidationError** when parsing external data:
  ```python
  from pydantic import ValidationError

  try:
      config = validate_config_yaml(raw_data)
  except ValidationError as e:
      logger.error(f"Invalid configuration: {e}")
      # Handle error gracefully
  ```
- **Test with invalid data** to ensure error handling works
- **Validation errors are user-facing** - ensure messages are helpful

### pathvalidate Sanitization

**pathvalidate sanitization differs from manual sanitization**:
- Uses platform-specific rules (Windows, macOS, Linux, universal)
- Handles reserved filenames (CON, PRN, AUX on Windows)
- Validates max path lengths per platform
- **Always use `platform="universal"`** for MAM compatibility
- **Test with edge cases**: Unicode, emoji, long names, reserved names

### State File Schema v2

**State tracking now uses versioned schemas**:
- **v1 schema** (legacy): Simple flat structure
- **v2 schema** (current): Enhanced with validation, metadata
  - Atomic writes with `.tmp` files
  - Schema version tracking
  - Timestamp validation (ISO 8601 format)
  - Migration path from v1 → v2

**Important**:
```python
# State file automatically migrates from v1 to v2 on first write
from mamfast.utils.state import load_state, save_state

state = load_state(state_file)  # Auto-detects version
# Modify state
save_state(state, state_file)  # Saves as v2 with atomic write
```

**Schema validation** (`schemas/state.py`):
- `ProcessedStateV1` - Legacy schema
- `ProcessedStateV2` - Current schema with validation
- `ProcessedRelease` - Individual release entry
- `FailedRelease` - Failed release tracking

### Naming System Refactoring

**Naming logic split into focused modules**:
- **Old**: Monolithic `utils/naming.py` (~1000+ lines)
- **New**: Organized modules in `utils/naming/`:
  - `authors.py` - Author name processing (transliteration, mapping)
  - `filters.py` - Title/author filtering rules
  - `mam_paths.py` - MAM path generation with truncation
  - `normalization.py` - Audnex metadata normalization
  - `series_parsing.py` - Series name extraction
  - `volume_parsing.py` - Volume number parsing
  - `string_utils.py` - String manipulation utilities
  - `constants.py` - Naming constants and patterns

**When working with naming**:
- Import from `mamfast.utils.naming` (not submodules directly)
- Use `generate_mam_path()` for MAM-compliant paths
- Use `normalize_audnex_metadata()` for Audnex data
- Test with golden samples in `tests/golden/`

### Subprocess Execution

**Use `sh` library instead of `subprocess`**:
```python
# Old (deprecated)
import subprocess
result = subprocess.run(["docker", "ps"], capture_output=True)

# New (preferred)
from mamfast.utils.cmd import run

result = run(["docker", "ps"], capture_output=True)
# Raises ExternalToolError on failure
```

**Benefits**:
- Cleaner API
- Better error messages
- Automatic logging
- Type-safe return values

### Fuzzy Matching

**Use `rapidfuzz` for author/title matching**:
```python
from mamfast.utils.fuzzy import fuzzy_match_author, fuzzy_match_title

score = fuzzy_match_author("J.K. Rowling", "JK Rowling")  # → 95.0
is_match = score >= 90.0  # Threshold for matching
```

**Use cases**:
- Matching ABS items without ASIN to staged books
- Detecting duplicates with slightly different metadata
- Author name normalization

## Git Workflow for AI Assistants

### Branch Naming

- Feature branches: `feature/description`
- Bug fixes: `fix/description`
- AI assistant branches: Follow provided pattern (e.g., `claude/claude-md-...`)

### Commit Message Format

```
<type>: <short description>

<detailed explanation if needed>

<bullet points for multiple changes>
```

**Types**:
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation only
- `test:` - Adding/updating tests
- `refactor:` - Code restructuring without behavior change
- `chore:` - Maintenance tasks
- `ci:` - CI/CD changes

**Example**:
```
feat: add retry logic for Audnex API calls

- Implement exponential backoff with jitter
- Add configurable max retries in config.yaml
- Handle network timeouts gracefully

Fixes issue where network blips caused pipeline failures.
```

### Pre-Commit Checklist

- [ ] All tests pass (`pytest`)
- [ ] Linting passes (`ruff check`)
- [ ] Type checking passes (`mypy src/`)
- [ ] No secrets in code or config files
- [ ] Docstrings added for new public APIs
- [ ] README/docs updated if needed

## Questions to Ask Before Making Changes

1. **Does this change affect configuration?**
   - Update config.py data classes
   - Update config.yaml.example
   - Update README.md configuration section

2. **Does this add new dependencies?**
   - Add to pyproject.toml `dependencies` or `dev` section
   - Run `pip install -e ".[dev]"` to verify
   - Check for license compatibility

3. **Does this change the pipeline?**
   - Update workflow.py
   - Update ReleaseStatus enum if adding stages
   - Update README.md pipeline diagram

4. **Does this require Docker/external services?**
   - Ensure graceful degradation if service unavailable
   - Add retry logic for network operations
   - Mock in tests

5. **Does this handle user paths?**
   - Use pathlib.Path, not strings
   - Resolve relative paths correctly
   - Validate existence with helpful error messages

6. **Does this process filenames?**
   - Sanitize with `sanitize_for_filename()`
   - Check MAM 225-char limit
   - Handle Unicode and special characters

7. **Does this process external data (API responses, config files)?**
   - Add Pydantic schema validation
   - Handle ValidationError gracefully
   - Provide helpful error messages
   - Add tests for invalid data

8. **Does this add new configuration fields?**
   - Update `schemas/config.py` Pydantic schema
   - Update `config.py` parsing logic
   - Update `config.yaml.example` with examples
   - Add validation tests

## Useful Commands Reference

```bash
# Development
pip install -e ".[dev]"              # Install with dev dependencies
pre-commit install                   # Setup pre-commit hooks
pre-commit run --all-files           # Run all checks manually

# Testing
pytest                               # Run all tests
pytest -v                            # Verbose output
pytest --cov=src/mamfast            # With coverage
pytest tests/test_discovery.py      # Specific file
pytest -k test_valid_asin           # Matching pattern

# Code Quality
ruff check src/                      # Lint
ruff check --fix src/                # Auto-fix
ruff format src/                     # Format
mypy src/                            # Type check

# Application - Main Workflow
mamfast --help                       # Show all commands
mamfast config                       # Debug: print loaded config
mamfast discover                     # List new audiobooks
mamfast run --dry-run                # Preview full pipeline
mamfast run --skip-scan              # Run without Libation scan

# Audiobookshelf Integration
mamfast abs-init                     # Test ABS connection, list libraries
mamfast abs-import                   # Import staged books to ABS
mamfast abs-import --dry-run         # Preview import without changes
mamfast abs-check-duplicate B0ABC123 # Check if ASIN exists
mamfast abs-rename                   # Bulk rename ABS library
mamfast abs-rename --dry-run         # Preview rename changes
mamfast abs-cleanup                  # Delete/archive source files
mamfast abs-trump-check              # Detect trumpable duplicates
mamfast abs-orphans                  # Find ABS items without seed files
mamfast abs-resolve-asins            # Find ASINs via ABS search

# State Management
mamfast state list                   # List processed releases
mamfast state list --failed          # List failed releases
mamfast state prune                  # Remove old entries
mamfast state retry <ASIN>           # Retry failed release
mamfast state clear                  # Clear all state (dangerous!)

# Diagnostics
mamfast check                        # Check configuration
mamfast check-duplicates             # Find duplicate ASINs
mamfast check-suspicious             # Find suspicious metadata
mamfast validate                     # Validate all staged releases

# Debugging
mamfast -v discover                  # Verbose logging
mamfast -c /path/to/config.yaml run  # Custom config
```

## Resources & Documentation

### Root-Level Documentation
- **User Guide**: README.md
- **Contributing**: CONTRIBUTING.md
- **Security**: SECURITY.md
- **Changelog**: CHANGELOG.md
- **AI Assistant Guide**: CLAUDE.md (this file)

### Technical Documentation (`docs/`)
- **Overview**: docs/README.md
- **ABS Integration**: docs/audiobookshelf/
  - AUDIOBOOKSHELF_IMPORT.md - Import workflow guide
  - AUDIOBOOKSHELF_API.md - API reference
  - ABS_RENAME_TOOL.md - Rename tool documentation
  - CLEANUP_PLAN.md - Cleanup strategies
  - TRUMPING.md - Duplicate detection logic
- **Naming System**: docs/naming/
  - NAMING.md - Naming system overview
  - NAMING_RULES.md - Naming conventions
  - NAMING_PIPELINE.md - Pipeline stages
  - NAMING_AUDNEX_NORMALIZATION.md - Audnex normalization
- **Implementation History**: docs/archive/
  - P0_UPGRADE_COMPLETE.md - Package upgrades (tenacity, platformdirs)
  - P1_SH_LIBRARY_COMPLETE.md - sh library integration
  - REFACTORING_SUMMARY.md - Large file refactoring
- **Active Plans**:
  - docs/MIGRATION_BACKLOG.md - Deferred migrations
  - docs/PACKAGE_UPGRADE_PLAN.md - Future package upgrades
  - docs/STATE_HARDENING_PLAN.md - State management improvements
  - docs/VALIDATION_PLAN.md - Input validation enhancements

### CI/CD
- `.github/workflows/ci.yml` - Main CI pipeline
- `.github/workflows/dependency-review.yml` - Security scanning

## Version Information

- **Current Version**: 0.1.0
- **Python Requirement**: 3.11+
- **License**: MIT

---

**Last Updated**: 2025-12-22
**Maintained By**: MAMFast Project
**For AI Assistants**: This document is regularly updated. Check git history for changes.
