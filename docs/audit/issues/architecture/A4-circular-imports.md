# A4: Circular Import Guards

**Priority**: Medium
**Effort**: Medium
**Risk**: Low

---

## Problem

60+ files use `TYPE_CHECKING` guards to avoid circular imports. While the guards work, they indicate tangled dependencies that make the codebase harder to understand and refactor.

## Indicators

```python
# Found in many files
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shelfr.config import Settings
    from shelfr.abs.cleanup import CleanupPrefs
```

## Key Circular Patterns

1. **config.py ↔ abs/cleanup.py, abs/trumping.py**
   - `config.py` has builder functions that return types from `abs/`
   - `abs/` modules need config types

2. **abs/importer.py** has TWO `TYPE_CHECKING` blocks
   - Imports from `abs/client.py`, `abs/prefetch.py`
   - Complex internal dependency web

3. **workflow.py ↔ multiple abs/ modules**
   - Orchestrates everything, needs all types

## Target Pattern

Extract shared types to a central module that others can import without cycles:

```python
# src/shelfr/types.py - shared types, no dependencies
from dataclasses import dataclass

@dataclass
class TrumpPrefs:
    ...

@dataclass
class CleanupPrefs:
    ...

# Now both config.py and abs/*.py can import from types.py
from shelfr.types import TrumpPrefs, CleanupPrefs
```

## Implementation Strategy

### Step 1: Identify Shared Types

Types used across module boundaries:

- `TrumpPrefs` (config ↔ abs/trumping)
- `CleanupPrefs` (config ↔ abs/cleanup)
- `Settings` (everywhere)
- `AbsClient` (abs/ internal)

### Step 2: Create Types Module

```python
# src/shelfr/types.py
"""Shared types to avoid circular imports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class CleanupStrategy(str, Enum):
    NONE = "none"
    HIDE = "hide"
    MOVE = "move"
    DELETE = "delete"


@dataclass(frozen=True)
class CleanupPrefs:
    strategy: CleanupStrategy = CleanupStrategy.NONE
    cleanup_path: Path | None = None
    ...


@dataclass(frozen=True)
class TrumpPrefs:
    enabled: bool = False
    aggressiveness: str = "balanced"
    ...
```

### Step 3: Update Imports

```python
# Before (in config.py)
if TYPE_CHECKING:
    from shelfr.abs.cleanup import CleanupPrefs

# After
from shelfr.types import CleanupPrefs  # No guard needed
```

### Step 4: Use Protocols for Complex Types

For types like `AbsClient` that have methods:

```python
# src/shelfr/protocols.py
from typing import Protocol

class AbsClientProtocol(Protocol):
    def authorize(self) -> AbsUser: ...
    def get_libraries(self) -> list[AbsLibrary]: ...
```

## Files to Create

1. `src/shelfr/types.py` - shared dataclasses
2. `src/shelfr/protocols.py` - interface protocols (optional)

## Files to Update

1. `src/shelfr/config.py` - remove TYPE_CHECKING guards
2. `src/shelfr/abs/cleanup.py` - move types to shared
3. `src/shelfr/abs/trumping.py` - move types to shared
4. `src/shelfr/abs/importer.py` - simplify imports
5. `src/shelfr/workflow.py` - simplify imports

## Acceptance Criteria

- [ ] Shared types module created
- [ ] No more than 20 TYPE_CHECKING guards (down from 60+)
- [ ] No circular import errors
- [ ] All tests pass

---

## Notes

This is interconnected with A1 (tight coupling). Doing A4 first may make A1 easier.
