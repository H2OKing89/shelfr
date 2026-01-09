# O2: Split config.py

**Priority**: Medium
**Effort**: High
**Risk**: Medium (many imports to update)

---

## Problem

`src/shelfr/config.py` is 1518 lines handling too many responsibilities:

- 15+ `@dataclass` definitions
- File loading logic
- YAML parsing
- Builder functions
- Global singleton management
- Validation helpers

## Target Structure

```
src/shelfr/config/
├── __init__.py          # Re-exports for backward compat
├── dataclasses.py       # PathsConfig, MamConfig, etc.
├── loader.py            # load_settings(), YAML parsing
├── builders.py          # build_trump_prefs(), build_cleanup_prefs()
├── settings.py          # Global get_settings() singleton
└── validation.py        # validate_settings(), path checks
```

## Implementation Strategy

### Phase 1: Create Package Structure

```bash
mkdir -p src/shelfr/config
touch src/shelfr/config/__init__.py
```

### Phase 2: Extract Dataclasses

Move all `@dataclass` definitions to `dataclasses.py`:

- `PathsConfig`
- `MamConfig`
- `DescriptionConfig`
- `MkbrrConfig`
- `FFmpegConfig`
- `QBittorrentConfig`
- `AudnexConfig`
- `MediaInfoConfig`
- `LibationConfig`
- `NamingConfig`
- `FiltersConfig`
- `CategoriesConfig`
- `AudiobookshelfConfig`
- `TrumpingConfig`
- `CleanupConfig`
- `WorkflowConfig`
- `Settings`

### Phase 3: Extract Validation

Move to `validation.py`:

- `validate_url()`
- `validate_path_exists()`
- `validate_same_filesystem()`
- `validate_required_env_vars()`
- `validate_paths()`
- `validate_settings()`

### Phase 4: Extract Builders

Move to `builders.py`:

- `build_trump_prefs()`
- `build_cleanup_prefs()`

### Phase 5: Extract Loader

Move to `loader.py`:

- `load_yaml_config()`
- `load_settings()`
- `_load_categories()`
- `_load_naming_config()`
- `_parse_*_config()` functions

### Phase 6: Extract Singleton

Move to `settings.py`:

- `_settings` global
- `get_settings()`
- `reload_settings()`
- `clear_settings()`

### Phase 7: Create **init**.py

```python
"""Configuration management for shelfr."""

from shelfr.config.dataclasses import (
    PathsConfig,
    MamConfig,
    Settings,
    # ... all others
)
from shelfr.config.settings import (
    get_settings,
    reload_settings,
    clear_settings,
)
from shelfr.config.loader import load_settings
from shelfr.config.validation import validate_settings
from shelfr.config.builders import (
    build_trump_prefs,
    build_cleanup_prefs,
)

__all__ = [
    # Dataclasses
    "PathsConfig",
    "MamConfig",
    "Settings",
    # ... all exports
]
```

## Backward Compatibility

The `__init__.py` re-exports ensure existing code continues to work:

```python
# This still works
from shelfr.config import Settings, get_settings
```

## Files to Change

1. Create `src/shelfr/config/` package
2. Rename `src/shelfr/config.py` → `src/shelfr/config.py.bak` (temporary)
3. Create all new modules
4. Update any relative imports within config
5. Test thoroughly
6. Delete backup

## Acceptance Criteria

- [ ] Config split into logical modules
- [ ] All existing imports still work
- [ ] All tests pass
- [ ] No module exceeds 500 lines
