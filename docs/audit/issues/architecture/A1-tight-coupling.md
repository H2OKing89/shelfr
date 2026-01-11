# A1: Tight Coupling via get_settings()

**Priority**: Medium
**Effort**: High (many files affected)
**Risk**: Low (refactoring, not behavior change)

---

## Problem

70+ locations call `get_settings()` directly inside function bodies instead of receiving settings as a parameter. This creates tight coupling that makes testing difficult and hides dependencies.

## Affected Files (Top Offenders)

| File | Occurrences |
|------|-------------|
| `src/shelfr/workflow.py` | 7 |
| `src/shelfr/abs/importer.py` | 7 |
| `src/shelfr/mkbrr.py` | 6 |
| `src/shelfr/qbittorrent.py` | 6 |
| `src/shelfr/hardlinker.py` | 5 |
| `src/shelfr/sanitize.py` | 4 |

## Current Pattern

```python
def upload_torrent(torrent_path: Path) -> bool:
    settings = get_settings()  # Hidden dependency
    client = connect(settings.qbittorrent.host)
    ...
```

## Target Pattern

```python
def upload_torrent(torrent_path: Path, config: QBittorrentConfig) -> bool:
    client = connect(config.host)  # Explicit dependency
    ...
```

## Implementation Strategy

### Phase 1: Entry Points (CLI)

Keep `get_settings()` only at CLI entry points where config is loaded once.

### Phase 2: Core Functions

Refactor high-level functions to accept config as parameter:

- `workflow.py` → `run_pipeline(releases, settings: Settings)`
- `mkbrr.py` → `create_torrent(path, config: MkbrrConfig)`

### Phase 3: Utility Functions

Pass only the specific config section needed:

- `qbittorrent.py` → `upload_torrent(path, config: QBittorrentConfig)`

## Testing Benefit

```python
# Before: Hard to test, needs global state mocking
def test_upload():
    with patch('shelfr.config.get_settings'):
        ...

# After: Easy to test with explicit config
def test_upload():
    config = QBittorrentConfig(host="test", ...)
    result = upload_torrent(path, config)
```

## Files to Change

1. `src/shelfr/workflow.py`
2. `src/shelfr/mkbrr.py`
3. `src/shelfr/qbittorrent.py`
4. `src/shelfr/hardlinker.py`
5. `src/shelfr/sanitize.py`
6. `src/shelfr/abs/importer.py`
7. All callers of above functions

## Acceptance Criteria

- [ ] Top-level pipeline functions accept `Settings` or specific config sections
- [ ] `get_settings()` only called in CLI entry points
- [ ] Tests pass without mocking global settings
- [ ] No functional changes to behavior

---

## Notes

This is a large refactoring effort. Consider doing it incrementally, one module at a time.
