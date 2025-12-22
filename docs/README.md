# MAMFast Documentation

This directory contains technical documentation, implementation plans, and reference materials for the MAMFast project.

## Directory Structure


### `/archive/` - Completed Implementation Reports

Historical documentation for completed migrations and refactoring work:
- `P0_UPGRADE_COMPLETE.md` - tenacity & platformdirs package upgrade (completed 2025-12-20)
- `P1_SH_LIBRARY_COMPLETE.md` - sh library integration for subprocess calls (completed 2025-12-20)
- `REFACTORING_SUMMARY.md` - P3 large file split (cli.py, naming.py) (completed 2025-12-20)
- `P0_INTEGRATION_COMPLETE.md` - Earlier integration work
- `PRODUCTION_SAFETY_IMPROVEMENTS.md` - Production safety enhancements
- `NAMING_PLAN_ORIGINAL.md` - Original naming implementation plan

### `/audiobookshelf/` - Audiobookshelf Integration

Documentation for ABS library management, import workflows, and metadata handling:
- `AUDIOBOOKSHELF_API.md` - ABS API reference and usage
- `AUDIOBOOKSHELF_IMPORT.md` - Import workflow implementation
- `AUDIOBOOKSHELF_IMPORT_PLAN.md` - Import feature planning
- `ABS_RENAME_TOOL.md` - Rename tool implementation
- `CLEANUP_PLAN.md` - Library cleanup strategies
- `TRUMPING.md` - Duplicate detection and trumping logic
- `UNKNOWN_ASIN_HANDLING.md` - Handling books without ASINs

### `/naming/` - File Naming System

Naming conventions, test cases, and validation documentation:
- Golden test samples for various edge cases
- Series handling and volume parsing logic
- Truncation and path validation rules

### `/tracked_issues/` - Issue Tracking

Active bug reports, feature requests, and technical investigations

### Root Documentation Files

#### Active Plans
- `MIGRATION_BACKLOG.md` - Deferred migrations (P2 sh library migrations)
- `PACKAGE_UPGRADE_PLAN.md` - Future package upgrades (P2 priorities)
- `IMPROVEMENTS_PLAN.md` - General improvement ideas
- `VALIDATION_PLAN.md` - Input validation enhancements
- `STATE_HARDENING_PLAN.md` - State management improvements

#### Reference

- `LIBATION_CLI.md` - Libation CLI integration guide

## Documentation Guidelines

### When to Archive

Move implementation docs to `/archive/` when:
- The work is **fully complete** and tested
- The document is primarily historical (not actively referenced)
- It describes a **completed migration or refactoring**

Keep in root `docs/` when:

- The document describes **active work** or future plans
- It's a **reference guide** actively used during development
- It tracks **ongoing issues** or backlog items

### Linking Between Docs

When referencing other documentation:
- Use **relative paths** for portability
- Root links to archive: `archive/P0_UPGRADE_COMPLETE.md`
- Archive links from archive: `P0_UPGRADE_COMPLETE.md`
- Root links from archive: `../MIGRATION_BACKLOG.md`

### File Naming

- Use `SCREAMING_SNAKE_CASE.md` for consistency
- Include status indicators: `_COMPLETE`, `_PLAN`, `_BACKLOG`
- Be descriptive: prefer `AUDIOBOOKSHELF_IMPORT.md` over `ABS.md`

## Root-Level User-Facing Documentation

The following docs stay in the **project root** for visibility:
- `README.md` - Project overview and quick start
- `CHANGELOG.md` - Version history and release notes
- `CONTRIBUTING.md` - Contribution guidelines
- `SECURITY.md` - Security policies
- `LICENSE` - Project license
- `CLAUDE.md` - Claude AI coding assistant instructions
