# O6: Integration Tests

**Priority**: Medium
**Effort**: High
**Risk**: Low

---

## Problem

Test markers show limited integration testing:

- Only 6 `@pytest.mark.skipif` tests found
- No `@pytest.mark.integration` markers in use
- No `@pytest.mark.slow` markers used (despite being defined)

Key untested integration paths:

- qBittorrent upload flow
- Full ABS import pipeline
- Docker/mkbrr torrent creation
- Libation CLI wrapper

## Current Test Configuration

From `pyproject.toml`:

```toml
[tool.pytest.ini_options]
markers = [
    "slow: marks tests as slow",
    "integration: marks tests requiring external services",
]
```

Markers are defined but not used.

## Target State

```
tests/
├── unit/                    # Fast, no external deps
├── integration/             # Require services (marked)
│   ├── test_qbittorrent_integration.py
│   ├── test_abs_integration.py
│   ├── test_mkbrr_integration.py
│   └── test_libation_integration.py
└── conftest.py              # Shared fixtures
```

## Implementation Strategy

### Step 1: Create Integration Test Structure

```bash
mkdir -p tests/integration
touch tests/integration/__init__.py
touch tests/integration/conftest.py
```

### Step 2: Create Integration Fixtures

```python
# tests/integration/conftest.py
import pytest
import os

def pytest_configure(config):
    """Skip integration tests unless explicitly requested."""
    if not config.getoption("--run-integration"):
        setattr(config.option, "markexpr", "not integration")

def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests",
    )

@pytest.fixture
def qbittorrent_client():
    """Real qBittorrent client for integration tests."""
    host = os.environ.get("QB_HOST")
    if not host:
        pytest.skip("QB_HOST not set")
    # ... setup client

@pytest.fixture
def abs_client():
    """Real Audiobookshelf client for integration tests."""
    host = os.environ.get("AUDIOBOOKSHELF_HOST")
    if not host:
        pytest.skip("AUDIOBOOKSHELF_HOST not set")
    # ... setup client
```

### Step 3: Create Sample Integration Tests

```python
# tests/integration/test_qbittorrent_integration.py
import pytest
from pathlib import Path

@pytest.mark.integration
class TestQBittorrentIntegration:
    """Integration tests for qBittorrent."""

    def test_client_connection(self, qbittorrent_client):
        """Verify we can connect to qBittorrent."""
        version = qbittorrent_client.app.version
        assert version is not None

    def test_upload_torrent(self, qbittorrent_client, tmp_path):
        """Test uploading a torrent file."""
        # Create test torrent
        # Upload
        # Verify exists
        # Clean up
```

### Step 4: Document Test Setup

Create `tests/README.md`:

```markdown
# Testing Guide

## Unit Tests

Run all unit tests:
```bash
pytest tests/ -m "not integration"
```

## Integration Tests

Integration tests require external services. Set up:

1. Configure environment:

   ```bash
   export QB_HOST=http://localhost:8080
   export AUDIOBOOKSHELF_HOST=http://localhost:13378
   ```

2. Run integration tests:

   ```bash
   pytest tests/ --run-integration -m integration
   ```

## Test Markers

- `@pytest.mark.slow` - Tests taking >5 seconds
- `@pytest.mark.integration` - Require external services

```

### Step 5: Update CI Configuration

Add integration test job (optional, runs on schedule):

```yaml
# .github/workflows/integration.yml
name: Integration Tests

on:
  schedule:
    - cron: '0 0 * * 0'  # Weekly
  workflow_dispatch:

jobs:
  integration:
    runs-on: ubuntu-latest
    services:
      qbittorrent:
        image: linuxserver/qbittorrent
        ...
```

## Files to Create

1. `tests/integration/__init__.py`
2. `tests/integration/conftest.py`
3. `tests/integration/test_qbittorrent_integration.py`
4. `tests/integration/test_abs_integration.py`
5. `tests/README.md`

## Acceptance Criteria

- [ ] Integration test directory structure created
- [ ] At least one integration test per external service
- [ ] Tests properly skip when services unavailable
- [ ] `--run-integration` flag works
- [ ] Documentation in `tests/README.md`
