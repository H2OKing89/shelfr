# Contributing to MAMFast

Thank you for your interest in contributing to MAMFast! This document provides guidelines and best practices.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/mamfast.git`
3. Create a virtual environment: `python -m venv .venv && source .venv/bin/activate`
4. Install dev dependencies: `pip install -e ".[dev]"`
5. Install pre-commit hooks: `pre-commit install`

## Development Workflow

### Before Committing

Always run the full check suite:

```bash
pre-commit run --all-files
```

This runs:
- **ruff** - Linting and import sorting
- **ruff-format** - Code formatting
- **mypy** - Type checking
- **pytest** - Unit tests

### Troubleshooting

#### mypy KeyError / cache mismatch

If mypy fails with a `KeyError` (e.g., `KeyError: 'is_type_form'`), the cache schema is stale from a mypy version change. Clear both caches:

```bash
rm -rf .mypy_cache .cache/mypy-precommit
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src/mamfast --cov-branch --cov-report=term

# Run specific test file
pytest tests/test_discovery.py

# Run specific test
pytest tests/test_discovery.py::TestDiscoverNewReleases::test_finds_new_releases
```

## Code Style

- Follow PEP 8 (enforced by ruff)
- Use type hints for all function signatures
- Write docstrings for public functions and classes
- Keep functions focused and small
- Prefer composition over inheritance

### Example

```python
def process_release(
    release: AudiobookRelease,
    *,
    dry_run: bool = False,
) -> ProcessingResult:
    """
    Process a single audiobook release through the pipeline.

    Args:
        release: The release to process
        dry_run: If True, simulate without making changes

    Returns:
        Result containing success status and any errors

    Raises:
        ValueError: If release has no source directory
    """
    ...
```

## Security Guidelines

### ⚠️ Critical Rules

1. **Never commit secrets** - No API keys, passwords, or announce URLs
2. **Check diffs before committing** - Ensure no sensitive data slipped in
3. **Use `.env` for secrets** - It's gitignored by default
4. **Don't log sensitive data** - Mask credentials in log output

### Before Submitting a PR

- [ ] No secrets in code or config files
- [ ] No hardcoded paths specific to your system
- [ ] Tests pass locally
- [ ] Pre-commit checks pass
- [ ] New features have tests
- [ ] Docstrings added for new public APIs

## Pull Request Process

1. Create a feature branch: `git checkout -b feature/my-feature`
2. Make your changes with clear, atomic commits
3. Push to your fork: `git push origin feature/my-feature`
4. Open a PR against `main`
5. Respond to review feedback
6. Once approved, maintainers will merge

### Commit Messages

Use clear, descriptive commit messages:

```
feat: add retry logic for Audnex API calls

- Implement exponential backoff with jitter
- Add configurable max retries
- Handle network timeouts gracefully
```

Prefixes:
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation only
- `test:` - Adding/updating tests
- `refactor:` - Code restructuring without behavior change
- `chore:` - Maintenance tasks

## Reporting Issues

When opening an issue:

1. Check existing issues first
2. Use a clear, descriptive title
3. Include steps to reproduce
4. Include expected vs actual behavior
5. Include Python version and OS
6. **Never include secrets or personal data**

## Questions?

Open a discussion or issue - we're happy to help!
