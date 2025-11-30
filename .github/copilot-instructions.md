# Copilot Instructions for MAMFast

## Project Overview
MAMFast automates audiobook uploads to MyAnonaMouse (MAM): Libation discovery → staging → metadata → torrent → qBittorrent. Built with Python 3.11+, strict typing, and Docker integrations.

## Architecture
- **Pipeline flow**: `workflow.py` orchestrates stages via `ReleaseStatus` enum (DISCOVERED → STAGED → METADATA_FETCHED → TORRENT_CREATED → UPLOADED → COMPLETE)
- **Core data model**: `AudiobookRelease` in `models.py` flows through all stages
- **Config sources** (precedence): `config/config.yaml` > `config/.env` > defaults
- **State tracking**: `data/processed.json` prevents reprocessing (keyed by ASIN)

## Development Commands
```bash
pip install -e ".[dev]"           # Install with dev dependencies
pytest                            # Run tests
pytest --cov=src/mamfast          # With coverage
ruff check src/ tests/            # Lint
ruff check --fix src/             # Auto-fix lint
mypy src/                         # Type check (strict mode)
pre-commit run --all-files        # Run all quality checks
```

## Code Patterns
- **Type hints required** on all function signatures
- **Imports**: `from __future__ import annotations` first, then stdlib → third-party → local
- **Paths**: Always use `pathlib.Path`, never string concatenation
- **Logging**: Module-level `logger = logging.getLogger(__name__)`
- **Network calls**: Wrap with `@retry_with_backoff()` from `utils/retry.py`
- **Tests**: Mock external services (Docker, qBittorrent, Audnex API); one test file per module

## Critical Constraints
- **MAM filename limit**: 225 chars max. Use `utils/naming.py` for sanitization/truncation
- **Docker path mapping**: `utils/paths.py` converts host↔container paths for mkbrr
- **Secrets**: Never commit `config/.env` or `config/config.yaml` (gitignored)
- **Hardlinks**: `library_root` and `seed_root` must be on same filesystem

## Adding Features
1. **New CLI command**: Add subparser in `cli.py` → create `cmd_yourcommand()` → add tests
2. **New config option**: Update dataclass in `config.py` → update `config.yaml.example` → add tests
3. **New pipeline stage**: Update `ReleaseStatus` enum → add to `workflow.py` → update state tracking

## Key Files
- `src/mamfast/workflow.py` - Pipeline orchestration
- `src/mamfast/models.py` - `AudiobookRelease`, `ReleaseStatus`
- `src/mamfast/config.py` - Config loading and validation
- `src/mamfast/utils/naming.py` - Filename sanitization, Japanese transliteration
- `config/categories.json` - MAM genre → category ID mappings
