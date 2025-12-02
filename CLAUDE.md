# CLAUDE.md - AI Assistant Guide for MAMFast

This document provides AI assistants with essential context about the MAMFast codebase, development workflows, and key conventions to follow when making changes.

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
- Docker (for Libation and mkbrr containers)
- External services: qBittorrent API, Audnex API
- CLI interface with Rich for pretty output

## Project Structure

```
mam_tool/
├── src/mamfast/               # Main package
│   ├── __init__.py           # Version: 0.1.0
│   ├── cli.py                # Command-line interface (argparse)
│   ├── config.py             # Configuration loading (.env, YAML, JSON)
│   ├── models.py             # Data models (AudiobookRelease, ProcessingResult, etc.)
│   ├── workflow.py           # Pipeline orchestration
│   ├── discovery.py          # Find audiobooks in Libation library
│   ├── hardlinker.py         # Stage files (hardlink + MAM-compliant rename)
│   ├── metadata.py           # Audnex + MediaInfo fetching
│   ├── mkbrr.py              # Torrent creation via Docker
│   ├── qbittorrent.py        # qBittorrent API client
│   ├── libation.py           # Libation Docker wrapper
│   ├── logging_setup.py      # Logging configuration
│   ├── templates/            # Jinja2 templates for MAM BBCode
│   │   └── mam_description.j2
│   └── utils/
│       ├── naming.py         # Filename sanitization & Japanese transliteration
│       ├── paths.py          # Host↔container path mapping
│       ├── retry.py          # Exponential backoff decorator
│       └── state.py          # Processed release tracking (JSON)
├── tests/                     # Pytest test suite
│   ├── test_discovery.py     # Discovery module tests
│   ├── test_models.py        # Data model tests
│   ├── test_config.py        # Configuration loading tests
│   ├── test_naming.py        # Filename sanitization tests
│   ├── test_hardlinker.py    # Hardlinking tests
│   ├── test_metadata.py      # Metadata fetching tests
│   ├── test_mkbrr.py         # Torrent creation tests
│   ├── test_qbittorrent.py   # qBittorrent API tests
│   ├── test_libation.py      # Libation wrapper tests
│   ├── test_retry.py         # Retry logic tests
│   ├── test_paths.py         # Path mapping tests
│   ├── test_state.py         # State tracking tests
│   └── test_integration.py   # End-to-end tests
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
└── MAMFAST_PROJECT_PLAN.md  # Project roadmap
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

    # Timestamps
    discovered_at: datetime | None
    processed_at: datetime | None
```

**Key Properties**:
- `display_name` - Human-readable name for logging: "Author - Title"
- `safe_dirname` - Filesystem-safe directory name with sanitized characters

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

Network operations use exponential backoff:

```python
@retry_with_backoff(
    max_retries=3,
    base_delay=2.0,
    max_delay=30.0,
    exceptions=NETWORK_EXCEPTIONS  # httpx, qbittorrent, OSError
)
def network_operation():
    ...
```

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

1. **Update `cli.py`**: Add subparser in `build_parser()`
2. **Create command function**: `def cmd_yourcommand(args, settings) -> int`
3. **Set function in parser**: `yourcommand_parser.set_defaults(func=cmd_yourcommand)`
4. **Update help text** in `cli.py` epilog
5. **Add tests** in `tests/test_cli.py` or new test file
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
3. **Add retry decorator** for network calls
4. **Handle errors gracefully** with specific exceptions
5. **Add comprehensive tests** with mocked responses
6. **Update dependencies** in `pyproject.toml` if needed

### Modifying the Pipeline

1. **Update `ReleaseStatus` enum** in `models.py` if adding stages
2. **Add processing function** in appropriate module
3. **Update `workflow.py`** orchestration logic
4. **Update state tracking** in `utils/state.py` if needed
5. **Add tests** for new stage
6. **Update README.md** pipeline diagram

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

# Application
mamfast --help                       # Show all commands
mamfast config                       # Debug: print loaded config
mamfast discover                     # List new audiobooks
mamfast run --dry-run                # Preview full pipeline
mamfast run --skip-scan              # Run without Libation scan

# Debugging
mamfast -v discover                  # Verbose logging
mamfast -c /path/to/config.yaml run  # Custom config
```

## Resources & Documentation

- **User Guide**: README.md
- **Contributing**: CONTRIBUTING.md
- **Security**: SECURITY.md
- **Changelog**: CHANGELOG.md
- **Project Plan**: MAMFAST_PROJECT_PLAN.md
- **CI Workflows**: `.github/workflows/`

## Version Information

- **Current Version**: 0.1.0
- **Python Requirement**: 3.11+
- **License**: MIT

---

**Last Updated**: 2025-11-30
**Maintained By**: MAMFast Project
**For AI Assistants**: This document is regularly updated. Check git history for changes.
