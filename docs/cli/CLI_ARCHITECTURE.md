# CLI Architecture

> **Status:** Active
> **Last Updated:** December 2025

## Overview

The shelfr CLI is built with [Typer](https://typer.tiangolo.com/) and [Rich](https://rich.readthedocs.io/) for a modern, user-friendly command-line experience. Commands are organized into domain-focused sub-apps (command groups).

---

## Design Principles

### Naming Conventions

| Element | Convention | Examples |
|---------|------------|----------|
| Sub-apps | Short nouns | `abs`, `lib`, `mam`, `edit`, `mkbrr` |
| Commands | Action verbs | `run`, `scan`, `import`, `create`, `check` |
| Flags | Kebab-case | `--dry-run`, `--output-dir`, `--piece-length` |
| Arguments | Positional, clear names | `<path>`, `<asin>`, `<torrent>` |

### UX Guidelines

- **Global flags before subcommand**: `shelfr --dry-run abs import` ✅
- **Rich output**: Colors, emojis, panels for visual hierarchy
- **Consistent flags**: `--dry-run`, `--yes`, `--json`, `--verbose` across all commands
- **Helpful errors**: Show suggestions when commands fail
- **Progressive disclosure**: Basic commands simple, advanced options available

### Architecture

- **Lazy imports**: Heavy dependencies load only when command runs
- **Runtime context**: `RuntimeContext` dataclass passed through commands
- **Modular handlers**: Each command delegates to handler modules
- **Factory pattern**: `make_*_app()` functions create sub-apps

---

## Current Structure

```bash
shelfr
├── --version                # Show version
├── --verbose / -v           # Enable verbose logging
├── --config / -c            # Custom config file
├── --dry-run / -n           # Preview mode (no mutations)
│
├── status                   # 📊 Quick status overview
├── config                   # ⚙️  Show loaded configuration
├── run                      # 🚀 Full upload pipeline
├── check                    # 🩺 Run health checks
├── validate                 # ✅ Validate discovered releases
├── validate-config          # ✅ Validate configuration files
├── check-duplicates         # 🔍 Find duplicate releases
├── check-suspicious         # ⚠️  Check for naming issues
├── preview-naming           # 👁️  Preview naming transformations
│
├── mam                      # 📤 MAM tracker workflows
│   ├── bbcode               # Output raw BBCode (copyable)
│   └── render               # Preview BBCode visually
│
├── libation                 # 📚 Libation audiobook manager
│   ├── scan                 # Check Audible for new purchases
│   ├── liberate             # Download pending audiobooks
│   ├── convert              # Convert audio formats
│   ├── status               # Show Libation library status
│   ├── books                # List books in library
│   ├── search               # Search library
│   ├── export               # Export library data
│   ├── settings             # Show Libation settings
│   ├── redownload           # Re-download specific books
│   ├── set-status           # Change book download status
│   └── guide                # Libation setup guide
│
├── abs                      # 📚 Audiobookshelf management
│   ├── init                 # Test ABS connection
│   ├── import               # Import staged books to library
│   ├── check-asin           # Check if ASIN exists in library
│   ├── trump-preview        # Preview trumping decisions
│   ├── restore              # Restore archived books
│   ├── cleanup              # Clean up source files after import
│   ├── rename               # Rename folders to MAM schema
│   ├── orphans              # Find orphaned folders
│   └── resolve-asins        # Resolve missing ASINs
│
├── state                    # 📋 State management
│   ├── list                 # List state entries
│   ├── prune                # Remove stale entries
│   ├── retry                # Retry failed entries
│   ├── clear                # Clear specific entry
│   └── export               # Export state to file
│
├── edit                     # ✏️  Config & template editing
│   ├── config               # Edit config.yaml ($EDITOR)
│   ├── presets              # Edit mkbrr presets.yaml ($EDITOR)
│   ├── naming               # Edit naming.json ($EDITOR)
│   ├── sig                  # Edit signature template ($EDITOR)
│   ├── categories           # Edit categories.json ($EDITOR)
│   ├── file <path>          # Edit any file ($EDITOR)
│   ├── inline <path>        # Inline terminal editor (prompt_toolkit)
│   ├── preview <path>       # Syntax-highlighted file preview
│   ├── diff <f1> <f2>       # Show diff between files
│   └── yaml-tree <path>     # Show YAML as tree structure
│
└── tools                    # 🔧 Utility commands
    ├── prepare              # Stage audiobook for upload
    └── mamff                 # Generate MAM FastFill JSON
```

---

## Planned Structure (Phase 2)

The future CLI reorganizes commands into a more intuitive domain-focused structure:

```bash
shelfr
├── status                   # 📊 Quick status (stays top-level)
├── config                   # ⚙️  Configuration (stays top-level)
│
├── mam                      # 📤 MAM tracker workflows
│   ├── run                  # Full upload pipeline
│   ├── bbcode               # Output raw BBCode
│   ├── render               # Preview BBCode visually
│   └── ff                   # Generate FastFill JSON
│
├── lib                      # 📚 Libation (short alias)
│   ├── scan                 # Check for new purchases
│   ├── liberate             # Download audiobooks
│   ├── convert              # Convert formats
│   ├── status               # Library status
│   ├── books                # List books
│   ├── search               # Search library
│   └── ...                  # (other libation commands)
│
├── abs                      # 📚 Audiobookshelf
│   ├── init                 # Test connection
│   ├── import               # Import staged books
│   ├── cleanup              # Clean source files
│   └── ...                  # (other abs commands)
│
├── mkbrr                    # 🔧 Torrent operations
│   ├── create               # Create torrent file
│   ├── inspect              # View torrent metadata
│   ├── check                # Verify content vs torrent
│   ├── modify               # Modify existing torrent
│   ├── presets              # List available presets
│   ├── version              # Show mkbrr version
│   └── update               # Update Docker image
│
├── edit                     # ✏️  Editor & TUI
│   ├── config               # Edit config ($EDITOR / inline)
│   ├── presets              # Edit mkbrr presets
│   ├── file <path>          # Edit any file
│   ├── inline <path>        # Inline mini-editor
│   ├── preview <path>       # Syntax preview
│   ├── diff                 # Compare files
│   ├── yaml-tree            # YAML structure view
│   └── tui [path]           # Full Textual TUI dashboard
│
├── meta                     # 🏷️  Metadata operations
│   ├── preview              # Preview naming transformations
│   ├── enrich               # Enrich from Hardcover/Audnex
│   └── audit                # Audit metadata quality
│
├── doctor                   # 🩺 Health & diagnostics
│   ├── check                # Run all health checks
│   ├── validate             # Validate releases
│   ├── config               # Validate config files
│   ├── dupes                # Find duplicates
│   └── suspicious           # Check naming issues
│
└── state                    # 📋 State management (unchanged)
    ├── list
    ├── prune
    ├── retry
    ├── clear
    └── export
```

---

## Sub-App Details

### `mkbrr` - Torrent Operations

**Source:** `src/shelfr/cli/mkbrr.py`
**Handler:** `src/shelfr/mkbrr.py`
**Plan:** [MKBRR_WRAPPER_PLAN.md](../implementation/MKBRR_WRAPPER_PLAN.md)

Wraps mkbrr (Docker-based torrent creator) with CLI commands.

```bash
# Create torrent with preset
shelfr mkbrr create /path/to/audiobook --preset mam

# Inspect torrent metadata
shelfr mkbrr inspect book.torrent --verbose

# Verify content matches torrent
shelfr mkbrr check book.torrent /path/to/content

# Modify existing torrent (change tracker, source, etc.)
shelfr mkbrr modify book.torrent --tracker https://new.tracker/announce

# List presets from presets.yaml
shelfr mkbrr presets

# Update Docker image
shelfr mkbrr update
```

**Key Features:**

- Docker path translation (host ↔ container)
- Preset management
- Torrent inspection and verification
- Batch operations support

### `edit` - Editor & TUI

**Source:** `src/shelfr/cli/edit.py`
**Handlers:**

- `src/shelfr/utils/editor.py` (Tier 1: $EDITOR)
- `src/shelfr/utils/mini_editor.py` (Tier 2: prompt_toolkit)
- `src/shelfr/utils/preview.py` (Tier 2: Rich preview)
- `src/shelfr/tui/app.py` (Tier 3: Textual TUI)

**Plan:** [TEXT_EDITOR_PLAN.md](../implementation/TEXT_EDITOR_PLAN.md)

Three-tiered editing approach:

| Tier | Implementation | Status |
|------|----------------|--------|
| 1 | `$EDITOR` | ✅ Complete |
| 2 | prompt_toolkit | ✅ Complete |
| 3 | Textual TUI | ✅ Complete |

```bash
# Tier 1: External editor
shelfr edit config          # Opens config.yaml in $EDITOR
shelfr edit file path.yaml  # Edit any file

# Tier 2: Inline mini-editor
shelfr edit inline path.yaml    # prompt_toolkit editor
shelfr edit preview path.yaml   # Syntax-highlighted view
shelfr edit diff a.yaml b.yaml  # Show differences
shelfr edit yaml-tree path.yaml # Tree structure

# Tier 3: Full TUI
shelfr edit tui              # Launch dashboard
shelfr edit tui config/      # Open TUI at path
```

**Key Features:**

- Syntax highlighting (YAML, JSON, Jinja2, Markdown)
- YAML/JSON validation with re-edit loop
- Diff viewing
- Automatic backups (.bak files)

### `meta` - Metadata Operations (Planned)

**Purpose:** Centralize metadata preview, enrichment, and auditing.

```bash
shelfr meta preview          # Preview naming transformations
shelfr meta enrich <path>    # Enrich from Hardcover/Audnex
shelfr meta audit            # Audit metadata quality across library
```

### `doctor` - Health & Diagnostics (Planned)

**Purpose:** Consolidate health checks and validation commands.

```bash
shelfr doctor check          # Run all health checks
shelfr doctor validate       # Validate discovered releases
shelfr doctor config         # Validate configuration files
shelfr doctor dupes          # Find duplicate releases
shelfr doctor suspicious     # Check for naming issues
```

---

## File Organization

```
src/shelfr/cli/
├── __init__.py              # App creation, sub-app registration
├── _app.py                  # Factory functions, enums, shared types
├── _context.py              # RuntimeContext dataclass
├── _helpers.py              # CLI helper utilities
├── abs.py                   # Audiobookshelf commands
├── core.py                  # Core pipeline commands
├── diagnostics.py           # Health check commands
├── edit.py                  # Editor commands (Tier 1+2)
├── libation.py              # Libation commands
├── mam.py                   # MAM tracker commands
├── mkbrr.py                 # Torrent commands (planned)
├── state.py                 # State management commands
└── tools.py                 # Utility commands

src/shelfr/utils/
├── editor.py                # Tier 1: $EDITOR integration
├── mini_editor.py           # Tier 2: prompt_toolkit
└── preview.py               # Tier 2: Rich preview utilities

src/shelfr/tui/              # Tier 3: Textual TUI (planned)
├── __init__.py
├── app.py                   # Main Textual App
├── screens/                 # TUI screens
│   ├── editor.py
│   └── file_browser.py
└── widgets/                 # Custom widgets
    ├── yaml_tree.py
    └── preview_pane.py
```

---

## Implementation Status

| Sub-App | Status | Notes |
|---------|--------|-------|
| `abs` | ✅ Complete | All commands implemented |
| `libation` | ✅ Complete | All commands implemented |
| `state` | ✅ Complete | All commands implemented |
| `mam` | ✅ Complete | bbcode, render implemented |
| `tools` | ✅ Complete | prepare, mamff implemented |
| `edit` (Tier 1) | ✅ Complete | $EDITOR integration |
| `edit` (Tier 2) | ✅ Complete | prompt_toolkit mini-editor |
| `edit` (Tier 3) | ✅ Complete | Textual TUI dashboard |
| `mkbrr` | 🔲 Planned | See MKBRR_WRAPPER_PLAN.md |
| `meta` | 🔲 Planned | Future consolidation |
| `doctor` | 🔲 Planned | Future consolidation |
| `lib` alias | 🔲 Planned | Short alias for `libation` |

---

## Adding a New Sub-App

### 1. Create Command Module

```python
# src/shelfr/cli/myapp.py
"""CLI commands for myapp."""

from __future__ import annotations

import typer

def make_myapp_app() -> typer.Typer:
    """Create the myapp sub-app."""
    return typer.Typer(
        name="myapp",
        help="🎯 Description of myapp.",
        no_args_is_help=True,
    )

def register_myapp_commands(app: typer.Typer) -> None:
    """Register myapp commands."""

    @app.command()
    def subcommand(
        ctx: typer.Context,
        arg: str = typer.Argument(..., help="Description"),
    ) -> None:
        """Do something."""
        from shelfr.cli._context import get_runtime_context
        runtime = get_runtime_context(ctx)
        # Implementation...
```

### 2. Register in `__init__.py`

```python
# In src/shelfr/cli/__init__.py

from shelfr.cli.myapp import make_myapp_app, register_myapp_commands

myapp_app = make_myapp_app()
app.add_typer(myapp_app, name="myapp")
register_myapp_commands(myapp_app)
```

### 3. Add Help Panel Constant (Optional)

```python
# In src/shelfr/cli/_app.py
MYAPP_COMMANDS = "🎯 MyApp Commands"
```

---

## Migration Path (Phase 1 → Phase 2)

When restructuring, use hidden deprecated aliases:

```python
# Old command still works but warns
@app.command("check", hidden=True, deprecated=True)
def check_deprecated(ctx: typer.Context) -> None:
    """[deprecated] Use 'shelfr doctor check' instead."""
    from shelfr.console import print_warning
    print_warning("'shelfr check' is deprecated. Use 'shelfr doctor check'.")
    return doctor_check(ctx)
```

Deprecation timeline:

1. **v1.x**: Add new structure, keep old commands with warnings
2. **v2.0**: Remove deprecated commands, document breaking changes

---

## Related Documents

- [SHELFR_REBRAND_PLAN.md](../SHELFR_REBRAND_PLAN.md) - Rebrand background
- [MKBRR_WRAPPER_PLAN.md](../implementation/MKBRR_WRAPPER_PLAN.md) - mkbrr implementation
- [TEXT_EDITOR_PLAN.md](../implementation/TEXT_EDITOR_PLAN.md) - Editor tiers

---

## Changelog

| Date | Change |
|------|--------|
| 2024-12-30 | Initial document, extracted from SHELFR_REBRAND_PLAN.md |
| 2024-12-30 | Added edit sub-app with Tier 1+2 status |
| 2024-12-30 | Added mkbrr planned structure |
| 2024-12-30 | Added implementation status table |
