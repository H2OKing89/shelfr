# shelfr Validation & Verification Plan

## Overview

This document outlines the comprehensive validation and verification strategy for shelfr to ensure reliability, catch errors early, and provide confidence in the upload pipeline.

---

## Implementation Status

| Feature | Status | Notes |
|---------|--------|-------|
| Health Check (`shelfr check`) | ✅ Complete | Config, paths, services, categories checks |
| Dry Run Mode (`--dry-run`) | ✅ Complete | Full pipeline simulation |
| Validation Framework | ✅ Complete | `ValidationCheck`, `ValidationResult` classes |
| Validation Tests | ✅ Complete | 67 tests in `test_validation.py` |
| Folder Grouping | ✅ Complete | Per-release output folders for .torrent/.json |
| Runtime Validation | ✅ Complete | `DiscoveryValidation`, `MetadataValidation`, `PreUploadValidation` |
| Chapter Integrity | ✅ Complete | `ChapterIntegrityChecker` detects Libation bug |
| Validation Reports | ✅ Complete | `ValidationReport` with JSON export |
| Safety Utilities | ✅ Complete | Path sanitization, checksums, traversal protection |
| Validate CLI | ✅ Complete | `shelfr validate` with `--json` output |
| Naming Validation | ✅ Complete | 112 tests for title/series/subtitle cleaning |
| Audnex Normalization | ✅ Complete | 20 tests for title/subtitle swap detection |
| Golden File Tests | ✅ Complete | 68 tests for expected output comparisons |

---

## 1. Unit Tests

### Current Coverage

| Module | Status | Test File |
|--------|--------|-----------|
| `discovery.py` | ✅ Complete | `tests/test_discovery.py` |
| `naming.py` | ✅ Complete | `tests/test_naming.py` |
| `metadata.py` | ✅ Complete | `tests/test_metadata.py` |
| `config.py` | ✅ Complete | `tests/test_config.py` |
| `hardlinker.py` | ✅ Complete | `tests/test_hardlinker.py` |
| `mkbrr.py` | ✅ Complete | `tests/test_mkbrr.py` |
| `qbittorrent.py` | ✅ Complete | `tests/test_qbittorrent.py` |
| `models.py` | ✅ Complete | `tests/test_models.py` |
| `utils/state.py` | ✅ Complete | `tests/test_state.py` |
| `utils/paths.py` | ✅ Complete | `tests/test_paths.py` |
| `validation.py` | ✅ Complete | `tests/test_validation.py` |
| `integration` | ✅ Complete | `tests/test_integration.py` |

**Total: 655 tests passing**

### Test Structure

```
tests/
├── __init__.py
├── conftest.py              # Shared fixtures
├── test_config.py           # ✅ 41 tests
├── test_console.py          # ✅ 50 tests
├── test_discovery.py        # ✅ 42 tests
├── test_golden.py           # ✅ 68 tests (golden file comparisons)
├── test_hardlinker.py       # ✅ 16 tests
├── test_integration.py      # ✅ 15 tests
├── test_libation.py         # ✅ 16 tests
├── test_metadata.py         # ✅ 75 tests
├── test_mkbrr.py            # ✅ 28 tests
├── test_models.py           # ✅ 27 tests
├── test_naming.py           # ✅ 112 tests (title/series/subtitle cleaning)
├── test_normalization.py    # ✅ 20 tests (Audnex title/subtitle swap detection)
├── test_paths.py            # ✅ 23 tests
├── test_qbittorrent.py      # ✅ 22 tests
├── test_retry.py            # ✅ 13 tests
├── test_state.py            # ✅ 20 tests
└── test_validation.py       # ✅ 67 tests (runtime validation, chapters, safety)
```

---

## 2. Integration Tests

Test components working together in realistic scenarios.

### Test Scenarios

| Scenario | Components | Description |
|----------|------------|-------------|
| Discovery Pipeline | discovery → metadata → models | Find release, fetch metadata, create AudiobookRelease |
| Config Resolution | config → paths | Load config and resolve all paths correctly |
| State Persistence | workflow → state | Process release, save state, verify on reload |
| Torrent Creation | hardlinker → mkbrr | Create hardlink, generate torrent |

### Integration Test File

```
tests/
└── integration/
    ├── __init__.py
    ├── test_discovery_pipeline.py
    ├── test_config_resolution.py
    └── test_torrent_pipeline.py
```

---

## 3. Runtime Validation Checks ✅ IMPLEMENTED

Validation at key pipeline stages to catch issues before they cause problems.

All three validation classes are now implemented in `src/shelfr/validation.py`:

### Stage 1: Discovery Validation ✅

```python
class DiscoveryValidation:
    """Validate discovered releases before processing."""

    def validate(self, release: AudiobookRelease) -> ValidationResult:
        # Checks: asin_format, m4b_exists, cover_exists, not_duplicate
```

### Stage 2: Metadata Validation ✅

```python
class MetadataValidation:
    """Validate fetched metadata before using."""

    def validate(self, release, audnex_data, mediainfo_data) -> ValidationResult:
        # Checks: required_fields, authors_present, narrators_present, runtime_match
```

### Stage 3: Pre-Upload Validation ✅

```python
class PreUploadValidation:
    """Validate everything before committing to upload."""

    def validate(self, release: AudiobookRelease) -> ValidationResult:
        # Checks: torrent_valid, staging_exists, filename_length, category_resolved, seed_path_valid
```

### Validation Result Model ✅

```python
@dataclass
class ValidationCheck:
    name: str
    passed: bool
    message: str
    severity: Literal["error", "warning", "info"]

@dataclass
class ValidationResult:
    checks: list[ValidationCheck]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks if c.severity == "error")

    @property
    def warnings(self) -> list[ValidationCheck]:
        return [c for c in self.checks if c.severity == "warning" and not c.passed]
```

---

## 4. Dry Run Mode ✅ COMPLETE

Safe testing mode that simulates the full pipeline without making changes.

### CLI Interface

```bash
# Dry run - show what would happen
shelfr run --dry-run

# Dry run with verbose output
shelfr run --dry-run --verbose

# Dry run specific ASIN
shelfr run --dry-run --asin B0G4NFQDWR
```

### Behavior

| Action | Normal Mode | Dry Run Mode |
|--------|-------------|--------------|
| Discover releases | ✅ Execute | ✅ Execute |
| Fetch metadata | ✅ Execute | ✅ Execute |
| Validate | ✅ Execute | ✅ Execute |
| Create hardlinks | ✅ Execute | ⏸️ Simulate (log only) |
| Create torrent | ✅ Execute | ⏸️ Simulate (log only) |
| Add to qBittorrent | ✅ Execute | ⏸️ Simulate (log only) |
| Update state | ✅ Execute | ⏸️ Simulate (log only) |

### Output Example

```
=== DRY RUN MODE ===

[DISCOVERED] 3 new releases found

[1/3] Kuma Kuma Kuma Bear Vol. 7
  ASIN: B0G4NFQDWR
  ✅ Validation passed
  📁 Would create hardlink: /seed/audiobooks/Kuma Kuma...
  📦 Would create torrent: /torrents/Kuma Kuma....torrent
  📤 Would add to qBittorrent

[2/3] Toradora! Vol. 9
  ASIN: B0G4NC6XY8
  ✅ Validation passed
  📁 Would create hardlink: /seed/audiobooks/Toradora...
  📦 Would create torrent: /torrents/Toradora....torrent
  📤 Would add to qBittorrent

[3/3] A Most Unlikely Hero Vol. 7
  ASIN: B0FT4PHYYL
  ⚠️ Warning: Chapter count mismatch (embedded: 24, API: 12)
  📁 Would create hardlink: /seed/audiobooks/A Most...
  📦 Would create torrent: /torrents/A Most....torrent
  📤 Would add to qBittorrent

=== SUMMARY ===
Releases: 3 discovered, 3 would be processed
Warnings: 1
Errors: 0
```

---

## 5. Health Check Command ✅ COMPLETE

`shelfr check` command to verify environment setup.

### CLI Interface

```bash
# Run all health checks
shelfr check

# Run specific check category
shelfr check --config-only
shelfr check --paths-only
shelfr check --services-only
```

### Health Checks

#### Configuration Checks ✅
- [x] Config file exists and is valid YAML
- [x] All required fields present (libation_container, docker_bin)
- [x] UID/GID are valid
- [x] qBittorrent host configured

#### Path Checks ✅
- [x] `library_root` exists and is readable
- [x] `seed_root` exists and is writable
- [x] `torrent_output` exists and is writable
- [x] `library_root` and `seed_root` on same filesystem (for hardlinks)
- [x] State file directory is writable

#### Service Checks ✅
- [x] Docker daemon running
- [x] mkbrr container image available
- [x] Libation container exists
- [x] qBittorrent API reachable
- [x] qBittorrent authentication successful
- [x] Audnex API reachable

#### Categories Check ✅
- [x] `categories.json` loaded with genre mappings
- [x] All category IDs are integers

### Output Example

```
$ shelfr check

shelfr Health Check
====================

Configuration
  ✅ Config file loaded: config/config.yaml
  ✅ All required fields present
  ✅ No unknown fields

Paths
  ✅ library_root: /mnt/user/data/audio/audiobook-import (exists, readable)
  ✅ seed_root: /mnt/user/data/downloads/torrents/seedvault/audiobooks (exists, writable)
  ✅ torrent_output: /mnt/user/data/downloads/torrents/torrentfiles (exists, writable)
  ✅ Same filesystem: library_root ↔ seed_root (hardlinks supported)

Services
  ✅ Docker: Running
  ✅ mkbrr: Image available (ghcr.io/autobrr/mkbrr:latest)
  ✅ qBittorrent: Connected (http://localhost:8080)
  ✅ Audnex API: Reachable (https://api.audnex.us)

Categories
  ✅ categories.json: Loaded (156 genre mappings)

Summary: All 17 checks passed ✅
```

---

## 6. Data Integrity Checks ✅ COMPLETE

### Chapter Verification

`ChapterIntegrityChecker` compares embedded M4B chapters against Audnex API chapters to detect issues like the Libation bug:

```python
class ChapterIntegrityChecker:
    """Detect chapter metadata issues like the Libation bug."""

    def compare_chapters(
        self,
        embedded_chapters: list[dict],
        api_chapters: list[dict]
    ) -> ChapterComparisonResult:
        # Returns: count_match, titles_match, durations_match,
        # embedded_count, api_count, duration_diff_seconds, mismatched_titles
```

### Runtime Verification

```python
def verify_runtime(embedded_duration: float, api_runtime: int) -> bool:
    """Check if embedded duration matches API runtime within tolerance."""
    tolerance = 0.05  # 5%
    return abs(embedded_duration - api_runtime) / api_runtime <= tolerance
```

### Checksum Logging

Store file checksums for tracking and verification:

```python
@dataclass
class FileIntegrity:
    m4b_md5: str
    m4b_size: int
    cover_md5: str | None
    torrent_md5: str | None
    verified_at: datetime
```

---

## 7. Logging & Reporting

### Validation Report

Each release generates a validation report:

```json
{
  "asin": "B0G4NFQDWR",
  "title": "Kuma Kuma Kuma Bear Vol. 7",
  "validated_at": "2025-12-02T06:49:00Z",
  "validation_result": {
    "passed": true,
    "checks": [
      {"name": "asin_format", "passed": true, "message": "Valid ASIN format"},
      {"name": "m4b_exists", "passed": true, "message": "M4B file found: 256.3 MB"},
      {"name": "chapters_valid", "passed": true, "message": "24 chapters, total 6:27:00"},
      {"name": "runtime_match", "passed": false, "severity": "warning", "message": "API: 23283s, Embedded: 23282s (diff: 1s)"}
    ],
    "warnings": 1,
    "errors": 0
  }
}
```

### Run Summary

End of each run shows summary:

```
═══════════════════════════════════════════════════════════════
                      shelfr Run Summary
═══════════════════════════════════════════════════════════════

Discovered:     4 releases
Validated:      4 passed, 0 failed
Processed:      4 releases
  - Staged:     4
  - Torrents:   4 created
  - Uploaded:   4 to qBittorrent

Warnings:       1
  - B0FT4PHYYL: Chapter count mismatch (embedded: 24, API: 12)

Errors:         0

Duration:       2m 34s
═══════════════════════════════════════════════════════════════
```

---

## 8. Implementation Priority

### Phase 1: Foundation ✅ COMPLETE
1. ✅ **Health Check Command** - `shelfr check` validates environment setup
2. ✅ **Dry Run Mode** - `shelfr --dry-run run` simulates full pipeline
3. ✅ **Basic Validation Framework** - `ValidationCheck`, `ValidationResult` classes

### Phase 2: Testing ✅ COMPLETE
4. ✅ **Unit Tests** - 655 tests covering all modules
5. ✅ **Integration Tests** - 15 tests for end-to-end scenarios

### Phase 3: Runtime Validation ✅ COMPLETE
6. ✅ **Discovery Validation** - `DiscoveryValidation` class validates ASIN, M4B, cover, duplicates
7. ✅ **Metadata Validation** - `MetadataValidation` class validates fields, authors, narrators, runtime
8. ✅ **Pre-Upload Validation** - `PreUploadValidation` class validates torrent, staging, filename length

### Phase 4: Advanced ✅ COMPLETE
9. ✅ **Chapter Integrity Checks** - `ChapterIntegrityChecker` detects Libation-style bugs
10. ✅ **Detailed Reporting** - `ValidationReport` with JSON export via `shelfr validate --json`

### Phase 5: Safety & Hardening ✅ PARTIAL (Utilities Complete, Advanced TODO)
11. ✅ **Path Traversal Protection** - `is_safe_path()` validates paths stay within allowed roots
12. ✅ **Filename Sanitization** - `sanitize_path_component()` removes `../`, null bytes, etc.
13. ✅ **Checksum Computation** - `compute_file_checksum()` for MD5/SHA256 verification
14. 📋 **File Locking** - Add file locking on `processed.json` (future enhancement)
15. 📋 **Concurrent Processing Guard** - Prevent processing same release twice (future enhancement)
16. 📋 **API Rate Limiting** - Add rate limiting for Audnex API calls (future enhancement)
17. 📋 **Circuit Breaker** - Auto-disable failing services (future enhancement)

### Phase 6: Naming Validation ✅ COMPLETE
18. ✅ **Filename Length Check** - `PreUploadValidation._check_filename_length()` validates 225 char limit
19. ✅ **Title/Series/Subtitle Cleaning** - 112 tests in `test_naming.py` covering all cleaning rules
20. ✅ **Audnex Normalization** - 20 tests in `test_normalization.py` for title/subtitle swap detection
21. ✅ **Author Filtering** - Tests for translator/illustrator/editor removal
22. ✅ **Japanese Transliteration** - Tests for pykakasi transliteration
23. ✅ **Preserve Exact** - Tests for bypass of cleaning rules
24. ✅ **Subtitle Redundancy** - Tests for series-in-subtitle detection

---

## 9. CLI Commands Summary

```bash
# Health check
shelfr check                    # Run all checks
shelfr check --config-only      # Config checks only
shelfr check --paths-only       # Path checks only
shelfr check --services-only    # Service checks only

# Dry run
shelfr --dry-run run            # Simulate full pipeline
shelfr --dry-run run --skip-scan  # Skip Libation scan

# Validation
shelfr validate                 # Validate all discovered releases
shelfr validate --asin B0G4NFQDWR  # Validate specific release
shelfr validate --json          # Output as JSON

# Testing
pytest                           # Run all tests (655 tests)
pytest tests/test_validation.py  # Run validation tests only (67 tests)
pytest tests/test_naming.py      # Run naming tests only (112 tests)
pytest tests/test_normalization.py  # Run normalization tests (20 tests)
pytest --cov=src/shelfr         # With coverage
```

---

## 10. Success Criteria

The validation system is complete when:

- [x] `shelfr check` passes on a correctly configured system
- [x] `shelfr --dry-run run` completes without errors
- [x] Unit test coverage ≥ 80% for critical modules (655 tests)
- [x] Validation framework implemented (`validation.py`)
- [x] Runtime validation checks at each pipeline stage
- [x] Chapter integrity check detects the Libation bug scenario
- [x] Clear error messages guide users to fix issues
- [x] `shelfr validate` command for pre-flight checks
- [x] JSON export for validation reports
- [x] Naming validation: title/series/subtitle cleaning (112 tests)
- [x] Audnex normalization: title/subtitle swap detection (20 tests)
- [x] Filename length validation within 225 char MAM limit
