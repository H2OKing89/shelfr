# Package Upgrade Implementation Plan

**Status**: ✅ P0 Complete (2025-12-20) | P1 Ready to implement
**Priority**: P0 (Do immediately) → P1 (Do soon) → P2 (Consider later)

> **Update 2025-12-20**: P0 upgrades (tenacity + platformdirs) successfully implemented.
> See [P0_UPGRADE_COMPLETE.md](archive/P0_UPGRADE_COMPLETE.md) for implementation details.

---

## ✅ P0: Quick Wins (Do Immediately)

### 1. Replace Custom Retry with `tenacity` ⭐⭐⭐⭐⭐

**Impact**: High | **Effort**: Low (30 minutes) | **Files**: 1

**Why**: Production-tested retry logic with better observability and more strategies.

**Implementation**:

1. Add dependency to `pyproject.toml`:
```toml
dependencies = [
    # ... existing ...
    "tenacity>=8.0",
]
```

2. Replace `src/mamfast/utils/retry.py` entirely with:

```python
"""Retry logic using tenacity library.

Provides exponential backoff with jitter for network operations.
"""

from __future__ import annotations

import logging
from typing import Callable, TypeVar

from tenacity import (
    before_sleep_log,
    retry as _retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

T = TypeVar("T")


def retry_with_backoff(
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: float = 1.0,
    retry_exceptions: tuple[type[BaseException], ...] = (Exception,),
    logger: logging.Logger | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Retry decorator with exponential backoff and jitter.

    Args:
        max_retries: Number of retries AFTER the first attempt (total = max_retries + 1)
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        jitter: Random jitter to add to delays (prevents thundering herd)
        retry_exceptions: Tuple of exception types to retry on
        logger: Logger for retry warnings (uses module logger if None)

    Returns:
        Decorator function
    """
    log = logger or logging.getLogger(__name__)

    return _retry(
        reraise=True,
        stop=stop_after_attempt(max_retries + 1),
        wait=wait_exponential_jitter(initial=base_delay, max=max_delay, jitter=jitter),
        retry=retry_if_exception_type(retry_exceptions),
        before_sleep=before_sleep_log(log, logging.WARNING),
    )
```

3. **Test** (add to `tests/test_retry.py`):

```python
def test_retry_with_backoff_attempts():
    """Test retry counts are correct."""
    calls = {"n": 0}

    @retry_with_backoff(max_retries=2, base_delay=0, max_delay=0, jitter=0)
    def flake():
        calls["n"] += 1
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        flake()

    assert calls["n"] == 3  # 1 initial + 2 retries
```

**No call sites need to change!** Existing code continues to work.

---

### 2. Add `platformdirs` for XDG-Compliant Paths ⭐⭐⭐⭐

**Impact**: Medium | **Effort**: Low (45 minutes) | **Files**: 3

**Why**: Cross-platform path handling, respects OS conventions, allows env var overrides.

**Implementation**:

1. Add dependency to `pyproject.toml`:
```toml
dependencies = [
    # ... existing ...
    "platformdirs>=4.0",
]
```

2. Create `src/mamfast/paths.py` (new file):

```python
"""Cross-platform path handling using platformdirs.

Provides XDG-compliant paths with environment variable overrides for flexibility.
"""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_cache_dir, user_data_dir, user_log_dir

APP_NAME = "mamfast"
APPAUTHOR = False  # Avoid "CompanyName/AppName" nesting on Windows


def _env_override(env_var: str) -> Path | None:
    """Check for environment variable override."""
    v = os.environ.get(env_var)
    return Path(v).expanduser() if v else None


def data_dir(*, ensure: bool = True) -> Path:
    """Get application data directory.

    Linux: ~/.local/share/mamfast
    macOS: ~/Library/Application Support/mamfast
    Windows: C:\\Users\\<user>\\AppData\\Local\\mamfast

    Override with MAMFAST_DATA_DIR env var.

    Args:
        ensure: Create directory if it doesn't exist

    Returns:
        Path to data directory
    """
    d = _env_override("MAMFAST_DATA_DIR") or Path(user_data_dir(APP_NAME, APPAUTHOR))
    if ensure:
        d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir(*, ensure: bool = True) -> Path:
    """Get application cache directory.

    Linux: ~/.cache/mamfast
    macOS: ~/Library/Caches/mamfast
    Windows: C:\\Users\\<user>\\AppData\\Local\\mamfast\\Cache

    Override with MAMFAST_CACHE_DIR env var.

    Args:
        ensure: Create directory if it doesn't exist

    Returns:
        Path to cache directory
    """
    d = _env_override("MAMFAST_CACHE_DIR") or Path(user_cache_dir(APP_NAME, APPAUTHOR))
    if ensure:
        d.mkdir(parents=True, exist_ok=True)
    return d


def log_dir(*, ensure: bool = True) -> Path:
    """Get application log directory.

    Linux: ~/.local/state/mamfast (or ~/.cache/mamfast if not available)
    macOS: ~/Library/Logs/mamfast
    Windows: C:\\Users\\<user>\\AppData\\Local\\mamfast\\Logs

    Override with MAMFAST_LOG_DIR env var.

    Args:
        ensure: Create directory if it doesn't exist

    Returns:
        Path to log directory
    """
    d = _env_override("MAMFAST_LOG_DIR") or Path(user_log_dir(APP_NAME, APPAUTHOR))
    if ensure:
        d.mkdir(parents=True, exist_ok=True)
    return d
```

3. Update `src/mamfast/utils/state.py`:

```python
# Add at top
from mamfast.paths import data_dir

# Replace _get_state_file function
def _get_state_file() -> Path:
    """Get path to state file."""
    return data_dir() / "processed.json"

def _get_run_lock_file() -> Path:
    """Get path to run lock file."""
    return data_dir() / "mamfast.lock"
```

4. Update `src/mamfast/logging_setup.py`:

```python
# Add at top
from mamfast.paths import log_dir

# Update default log_file parameter
def setup_logging(
    log_level: str = "INFO",
    log_file: Path | None = None,
    rich_console: bool = False,
    quiet_console: bool = False,
) -> None:
    """Setup logging configuration."""
    if log_file is None:
        log_file = log_dir() / "mamfast.log"

    # ... rest of function
```

5. **Update README** to document env var overrides:

```markdown
## Environment Variables

MAMFast respects the following environment variables for path customization:

- `MAMFAST_DATA_DIR` - Override data directory (default: OS-specific)
- `MAMFAST_CACHE_DIR` - Override cache directory (default: OS-specific)
- `MAMFAST_LOG_DIR` - Override log directory (default: OS-specific)

Example for Unraid:
```bash
export MAMFAST_DATA_DIR="/mnt/cache/appdata/mamfast/data"
export MAMFAST_LOG_DIR="/mnt/cache/appdata/mamfast/logs"
```
```

**Benefits**: Unraid users can set env vars, dev machines get OS-correct defaults.

---

## 🟡 P1: Do Soon (Significant Improvements)

### 3. Replace `subprocess` with `sh` (via wrapper) ⭐⭐⭐⭐

**Impact**: High | **Effort**: Medium (2-3 hours) | **Files**: 5

**Why**: Better error messages, cleaner syntax, automatic output handling.

**Implementation**:

1. Add dependency to `pyproject.toml`:
```toml
dependencies = [
    # ... existing ...
    "sh>=2.0",
]
```

2. Create `src/mamfast/utils/cmd.py` (new file):

```python
"""Command execution utilities using sh library.

Provides a consistent interface for running external commands
with better error handling than raw subprocess.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import sh  # type: ignore
from sh import CommandNotFound, ErrorReturnCode  # type: ignore


@dataclass(frozen=True)
class CmdResult:
    """Result of running a command."""

    argv: tuple[str, ...]
    stdout: str
    stderr: str
    exit_code: int


class CmdError(RuntimeError):
    """Raised when command execution fails."""

    def __init__(
        self,
        *,
        argv: Sequence[str],
        exit_code: int,
        stdout: str,
        stderr: str,
    ):
        self.argv = tuple(argv)
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        msg = f"Command failed (exit {exit_code}): {' '.join(self.argv)}"
        if stderr:
            msg += f"\n{stderr}"
        elif stdout:
            msg += f"\n{stdout}"
        super().__init__(msg)


def _to_text(v) -> str:
    """Convert bytes/str/None to str."""
    if v is None:
        return ""
    if isinstance(v, (bytes, bytearray)):
        return v.decode(errors="replace")
    return str(v)


def run(
    argv: Sequence[str],
    *,
    timeout: float | int | None = None,
    ok_codes: Iterable[int] = (0,),
) -> CmdResult:
    """Run external command via sh.

    Args:
        argv: Command and arguments as list
        timeout: Timeout in seconds (None for no timeout)
        ok_codes: Exit codes to consider successful

    Returns:
        CmdResult with stdout/stderr/exit_code

    Raises:
        CmdError: If command fails or returns non-zero exit code

    Example:
        >>> result = run(["docker", "exec", "Libation", "ls"], timeout=30)
        >>> print(result.stdout)
    """
    try:
        cmd = sh.Command(argv[0])
        out = cmd(
            *argv[1:],
            _timeout=timeout,
            _ok_code=list(ok_codes),
            _err_to_out=False,
        )
        return CmdResult(
            tuple(argv),
            _to_text(out),
            _to_text(getattr(out, "stderr", "")),
            0,
        )

    except CommandNotFound as e:
        raise CmdError(
            argv=argv,
            exit_code=127,
            stdout="",
            stderr=_to_text(e),
        ) from e

    except ErrorReturnCode as e:
        raise CmdError(
            argv=argv,
            exit_code=int(getattr(e, "exit_code", 1)),
            stdout=_to_text(getattr(e, "stdout", "")),
            stderr=_to_text(getattr(e, "stderr", "")),
        ) from e
```

3. **Migrate files one at a time**:

**Example - `src/mamfast/libation.py`**:

```python
# Before
result = subprocess.run(
    ["docker", "exec", "Libation", "/libation/LibationCli", "scan"],
    capture_output=True,
    text=True,
    timeout=300,
)

# After
from mamfast.utils.cmd import run

result = run(
    ["docker", "exec", "Libation", "/libation/LibationCli", "scan"],
    timeout=300,
)
stdout = result.stdout
```

4. **Test** (add to `tests/test_cmd.py`):

```python
def test_run_success():
    result = run(["echo", "hello"])
    assert result.exit_code == 0
    assert "hello" in result.stdout

def test_run_failure():
    with pytest.raises(CmdError) as exc_info:
        run(["ls", "/nonexistent"])
    assert exc_info.value.exit_code != 0
```

**Files to migrate**: `libation.py`, `mkbrr.py`, `metadata.py`, `abs/asin.py`

---

### 4. Add `pydantic-settings` for Better Config ⭐⭐⭐

**Impact**: Medium | **Effort**: Medium (3-4 hours) | **Files**: 2

**Why**: Type-safe config loading, automatic env var overlays, validation on load.

**Note**: Keep YAML loading (already works well), use pydantic-settings for env var overlay.

**Implementation**:

1. Add dependency:
```toml
dependencies = [
    # ... existing ...
    "pydantic-settings>=2.0",
]
```

2. Update `src/mamfast/config.py` to use `BaseSettings`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class QBittorrentSettings(BaseSettings):
    """qBittorrent configuration with env var support."""

    model_config = SettingsConfigDict(env_prefix="QB_")

    host: str = "http://localhost:8080"
    username: str = "admin"
    password: str = ""

    # Automatically loads from QB_HOST, QB_USERNAME, QB_PASSWORD env vars
```

3. **Keep YAML loading**, overlay env vars:

```python
def reload_settings(config_file: Path) -> Settings:
    """Load settings from YAML + env vars."""
    # Load YAML first
    yaml_config = yaml.safe_load(config_file.read_text())

    # Create settings with env var overlay
    qb_settings = QBittorrentSettings(**yaml_config.get("qbittorrent", {}))

    # ... rest of config loading
```

**Trade-off**: This is more work than tenacity/platformdirs, so consider P2 unless you need env var override for lots of settings.

---

## 🟢 P2: Consider Later

### 5. Replace `argparse` with `typer` ⭐⭐⭐

**Why NOT now**: cli.py just got refactored to 737 lines. Don't rewrite it immediately.

**When to consider**: If CLI complexity grows significantly, or if you want better help text auto-generation.

---

### 6. Add `hypothesis` for Property-Based Testing ⭐⭐

**Why NOT now**: Current test coverage (1747 tests) is adequate.

**When to consider**: P4, when you want to harden edge cases in naming/path logic.

---

## 📋 Summary: What to Add to `pyproject.toml`

```toml
[project]
dependencies = [
    "python-dotenv>=1.0.0",
    "pyyaml>=6.0",
    "qbittorrent-api>=2024.1",
    "httpx>=0.27.0",
    "rich>=13.0",
    "pykakasi>=2.2.0",
    "jinja2>=3.1.0",
    "pydantic>=2.0",
    "pathvalidate>=3.0",
    "rapidfuzz>=3.0",

    # NEW: P0 - Do immediately
    "tenacity>=8.0",        # Better retry logic
    "platformdirs>=4.0",    # Cross-platform paths

    # NEW: P1 - Do soon
    "sh>=2.0",              # Better subprocess handling
    # "pydantic-settings>=2.0",  # Uncomment when ready for P1 #4
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov",
    "ruff",
    "mypy",
    "types-PyYAML",
    "pre-commit>=3.0",
    # "hypothesis>=6.0",  # Uncomment for P4
]
```

---

## ✅ Implementation Checklist

### Phase 1 - P0 (✅ COMPLETE - 2025-12-20)
- [x] Add `tenacity>=8.0` to dependencies
- [x] Replace `utils/retry.py` with tenacity version
- [x] Add test for retry behavior
- [x] Run tests: `pytest tests/test_retry.py`
- [x] Add `platformdirs>=4.0` to dependencies
- [x] Create `paths.py` with data/cache/log dirs
- [x] Update `config.py` to use `data_dir()` and `log_dir()` for defaults
- [x] Test on dev machine + document env vars in README
- [x] Verify backward compatibility with existing code
- [x] Run integration tests

### Phase 2 - P1 (✅ sh library COMPLETE - 2025-12-20)
- [x] Add `sh>=2.0` to dependencies
- [x] Create `utils/cmd.py` wrapper
- [x] Migrate `libation.py` to use `cmd.run()`
- [x] Migrate `mkbrr.py` to use `cmd.run()`
- [x] Test integration and verify imports
- [ ] ⏭️ Migrate `metadata.py` to use `cmd.run()` (deferred - P2)
- [ ] ⏭️ Migrate `abs/asin.py` to use `cmd.run()` (deferred - P2)
- [ ] ⏭️ Add unit tests for `cmd.py` wrapper (deferred - P2)
- [ ] (Optional) Add `pydantic-settings` for env var config

> **Update 2025-12-20**: sh library core integration complete.
> See [P1_SH_LIBRARY_COMPLETE.md](P1_SH_LIBRARY_COMPLETE.md) for details.
> metadata.py and abs/asin.py migrations deferred to P2 (low priority, single calls each).

### Phase 3 - P2 (Future)
- [ ] Consider `typer` if CLI grows complex
- [ ] Consider `hypothesis` for edge case testing (P4)

---

## Migration Notes

1. **tenacity**: Zero breaking changes - existing code works as-is
2. **platformdirs**: Paths change locations - document env var overrides for Unraid
3. **sh**: Migrate files one at a time - test after each migration
4. **pydantic-settings**: Keep YAML loading - use for env var overlay only

---

**Estimated Total Time**:
- P0: 1.5 hours (high value, low effort)
- P1: 5-6 hours (high value, medium effort)
- P2: 10+ hours (medium value, high effort - consider later)

**Recommendation**: Do P0 immediately (tenacity + platformdirs), then P1 #3 (sh wrapper) when you have a 2-hour block.
