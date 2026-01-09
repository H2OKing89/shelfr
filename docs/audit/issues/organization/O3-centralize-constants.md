# O3: Centralize Constants

**Priority**: Medium
**Effort**: Low
**Risk**: Low

---

## Problem

Same constants are defined in multiple places:

```python
# src/shelfr/config.py
VALID_AUDNEX_REGIONS = frozenset(["us", "uk", "au", "ca", "de", "es", "fr", "in", "it", "jp"])
DEFAULT_ASIN_REGION = "us"

# src/shelfr/schemas/config.py
VALID_AUDNEX_REGIONS = frozenset(["us", "uk", "au", "ca", "de", "es", "fr", "in", "it", "jp"])
DEFAULT_ASIN_REGION = "us"

# src/shelfr/discovery.py
ASIN_VALID_PATTERN = re.compile(r"^(?:B[0-9A-Z]{9}|[0-9]{10})$")

# src/shelfr/validation.py
ASIN_VALID_PATTERN = re.compile(r"^(?:B[0-9A-Z]{9}|[0-9]{10})$")
```

Comments say "must match" but nothing enforces this.

## Target State

Single source of truth in `src/shelfr/constants.py`:

```python
"""Shared constants for shelfr.

This is the single source of truth for constants used across modules.
Do not duplicate these values elsewhere.
"""

from __future__ import annotations

import re
from typing import Final

# =============================================================================
# ASIN Constants
# =============================================================================

#: Valid ASIN pattern (10 alphanumeric starting with B, or 10 digits for ISBN-10)
ASIN_VALID_PATTERN: Final = re.compile(r"^(?:B[0-9A-Z]{9}|[0-9]{10})$")

#: ASIN pattern for folder name extraction
ASIN_FOLDER_PATTERN: Final = re.compile(r"\{ASIN[-_]?([A-Z0-9]{10})\}")

# =============================================================================
# Audnex Regions
# =============================================================================

#: Valid Audnex API regions
VALID_AUDNEX_REGIONS: Final[frozenset[str]] = frozenset([
    "us", "uk", "au", "ca", "de", "es", "fr", "in", "it", "jp"
])

#: Default ASIN region for lookups
DEFAULT_ASIN_REGION: Final[str] = "us"

# =============================================================================
# File Extensions
# =============================================================================

#: Audio file extensions recognized by the importer
AUDIO_EXTENSIONS: Final[frozenset[str]] = frozenset({
    ".m4b", ".m4a", ".mp3", ".ogg", ".flac", ".opus", ".wav"
})

#: MAM allowed extensions for uploads
MAM_ALLOWED_EXTENSIONS: Final[tuple[str, ...]] = (
    ".m4b", ".jpg", ".jpeg", ".png", ".pdf", ".cue"
)

# =============================================================================
# Path Limits
# =============================================================================

#: Maximum path length for MAM uploads
MAM_MAX_PATH_LENGTH: Final[int] = 225

#: Maximum filename length (filesystem limit)
MAX_FILENAME_LENGTH: Final[int] = 255
```

## Implementation Steps

### Step 1: Create Constants Module

Create `src/shelfr/constants.py` with all shared constants.

### Step 2: Update Imports

```python
# Before
ASIN_VALID_PATTERN = re.compile(r"^(?:B[0-9A-Z]{9}|[0-9]{10})$")

# After
from shelfr.constants import ASIN_VALID_PATTERN
```

### Step 3: Remove Duplicates

Delete duplicate definitions from:

- `src/shelfr/config.py`
- `src/shelfr/schemas/config.py`
- `src/shelfr/discovery.py`
- `src/shelfr/validation.py`
- `src/shelfr/abs/asin.py`
- `src/shelfr/abs/importer.py`

## Files to Change

1. Create `src/shelfr/constants.py`
2. Update `src/shelfr/config.py`
3. Update `src/shelfr/schemas/config.py`
4. Update `src/shelfr/discovery.py`
5. Update `src/shelfr/validation.py`
6. Update `src/shelfr/abs/asin.py`
7. Update `src/shelfr/abs/importer.py`

## Acceptance Criteria

- [ ] `constants.py` created with all shared constants
- [ ] No duplicate constant definitions in codebase
- [ ] All imports updated
- [ ] All tests pass
- [ ] `Final` type hints used for immutability
