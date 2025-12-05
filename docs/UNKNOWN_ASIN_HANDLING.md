# Unknown ASIN Handling Plan

> **Document Version:** 1.0.0 | **Last Updated:** 2025-12-05 | **Status:** 📋 Planning

This document outlines the plan for handling audiobooks without ASINs during import.

---

## Problem Statement

The current importer has two issues with unknown-ASIN content:

### Critical Bug: Multi-File Data Loss

When importing a multi-file audiobook without ASIN, all files get renamed to the same base name:

```
Renamed: Title - 01.m4b → Title (Unknown).m4b
Renamed: Title - 02.m4b → Title (Unknown).m4b  # Overwrites previous!
Renamed: Title - 41.m4b → Title (Unknown).m4b  # Last one wins
```

**Result:** 40 files become 1. Data destroyed.

### Design Issue: No Policy for Unknowns

Currently all unknown-ASIN content goes to `Unknown/` with aggressive renaming. This doesn't distinguish between:

1. **Audible content missing ASIN** - Could be resolved via metadata
2. **Homebrew/self-pub** - ASIN not applicable, just needs filing
3. **Malformed imports** - Need manual review

---

## Three Classes of Unknown ASIN

| Class | Example | ASIN Status | Handling |
|-------|---------|-------------|----------|
| **Missing ASIN** | `A Most Unlikely Hero, Volume 8` | Probably exists, just not in name | Try to resolve |
| **Homebrew** | `Quentin Kilgore - Primal Imperative 2` | Not applicable | Import as-is |
| **Multi-file chaos** | `Title - 01.m4b` through `Title - 41.m4b` | Unknown | Preserve structure |

---

## Implementation Phases

### Phase 1: Fix Critical Bug (Immediate)

**Goal:** Never destroy data by renaming multiple files to same name.

```python
def rename_files_in_folder(folder_path: Path, parsed: ParsedFolderName, *, dry_run: bool = False):
    audio_files = [f for f in folder_path.iterdir() if f.suffix.lower() in AUDIO_EXTENSIONS]

    # SAFETY: Multi-file books without ASIN keep original names
    if len(audio_files) > 1 and not parsed.asin:
        logger.warning(
            "Multi-file book without ASIN (%d files) - preserving original filenames: %s",
            len(audio_files), folder_path.name
        )
        return []  # Don't rename

    # ... existing rename logic for single-file or ASIN-known books
```

**Acceptance criteria:**
- [ ] Multi-file folders without ASIN: no file renames
- [ ] Single-file folders without ASIN: can still rename
- [ ] Folders with ASIN: normal behavior

---

### Phase 2: Unknown ASIN Policy (Future PR)

**Goal:** Configurable handling for unknown-ASIN content.

#### Configuration

```yaml
# config.yaml
audiobookshelf:
  import_settings:
    unknown_asin_policy: "import"  # import | quarantine | skip
    quarantine_path: "/mnt/user/data/audio/quarantine"
```

#### Policy Enum

```python
class UnknownAsinPolicy(str, Enum):
    IMPORT = "import"           # Import to Unknown/ with minimal changes
    QUARANTINE = "quarantine"   # Move to quarantine folder for manual review
    SKIP = "skip"               # Leave in staging, log warning only
```

#### Behavior by Policy

| Policy | Action | Use Case |
|--------|--------|----------|
| `import` | Move to `Unknown/Author/Title/`, minimal renames | Default - handles homebrew |
| `quarantine` | Move to quarantine folder, no renames | Strict - only import known content |
| `skip` | Leave in staging, log warning | Manual review workflow |

---

### Phase 3: Enhanced ASIN Resolution (Future PR)

**Goal:** Find ASINs from more sources before giving up.

#### Resolution Cascade

```python
def resolve_asin(folder: Path) -> tuple[str | None, str]:
    """Try multiple sources to find ASIN.

    Returns:
        (asin, source) where source is "folder", "filename", "metadata", or "unknown"
    """
    # 1. Folder name (current behavior)
    if asin := extract_asin(folder.name):
        return asin, "folder"

    # 2. File names within folder
    for f in folder.iterdir():
        if f.is_file() and (asin := extract_asin(f.name)):
            return asin, "filename"

    # 3. Sidecar metadata.json
    for meta_file in folder.glob("*.metadata.json"):
        try:
            data = json.loads(meta_file.read_text())
            if asin := data.get("asin") or data.get("audible_asin"):
                return asin, "metadata"
        except (json.JSONDecodeError, OSError):
            continue

    return None, "unknown"
```

#### Sources (Priority Order)

| Source | Cost | Reliability | Notes |
|--------|------|-------------|-------|
| Folder name | Free | High | Current implementation |
| File names | Free | High | Same patterns as folder |
| metadata.json | Free | High | From MAM workflow |
| mediainfo tags | Low | Medium | Requires mediainfo binary |
| Audible API | High | Medium | Rate limits, fuzzy matching |

---

### Phase 4: mediainfo Probe (Future Enhancement)

**Goal:** Extract ASIN from embedded file metadata.

**Deferred because:**
- Requires `mediainfo` binary installed
- Adds subprocess overhead
- Most MAM content already has ASIN in name

**Implementation sketch:**

```python
def asin_from_mediainfo(audio_file: Path) -> str | None:
    """Extract ASIN from audio file metadata tags."""
    try:
        result = subprocess.run(
            ["mediainfo", "--Output=JSON", str(audio_file)],
            capture_output=True, text=True, check=True
        )
        data = json.loads(result.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return None

    # Search all string fields for ASIN pattern
    blob = json.dumps(data)
    if match := re.search(r"\bB0[A-Z0-9]{8}\b", blob):
        return match.group(0)
    return None
```

---

### Phase 5: Audible API Lookup (Future Enhancement)

**Goal:** Last-resort ASIN resolution via Audible search.

**Explicitly deferred because:**
- Rate limits and API complexity
- Fuzzy title matching is error-prone
- Should be a separate batch job, not in import hot path

**Recommendation:** If implemented, make it a separate command:
```bash
mamfast abs-resolve-asins  # Batch job to resolve unknown ASINs
```

---

## Decision: What NOT to Build

Based on feedback analysis, explicitly **not** implementing:

1. **SQLite tracking for unknowns** - We removed SQLite indexer; don't reintroduce
2. **Confidence scores** - ASIN either matches regex or doesn't
3. **Audible API in import path** - Too slow, too risky
4. **Automatic homebrew detection** - Too many false positives

---

## Testing Requirements

### Phase 1 Tests

```python
class TestMultiFileProtection:
    def test_multi_file_no_asin_preserves_names(self, tmp_path):
        """Multi-file book without ASIN keeps original filenames."""
        folder = tmp_path / "Unknown Book"
        folder.mkdir()
        (folder / "Book - 01.m4b").touch()
        (folder / "Book - 02.m4b").touch()
        (folder / "Book - 03.m4b").touch()

        parsed = parse_mam_folder_name(folder.name)
        renamed = rename_files_in_folder(folder, parsed)

        assert renamed == []  # No renames
        assert (folder / "Book - 01.m4b").exists()
        assert (folder / "Book - 02.m4b").exists()
        assert (folder / "Book - 03.m4b").exists()

    def test_single_file_no_asin_can_rename(self, tmp_path):
        """Single-file book without ASIN can be renamed."""
        folder = tmp_path / "Unknown Book"
        folder.mkdir()
        (folder / "Unknown Book.m4b").touch()

        parsed = parse_mam_folder_name(folder.name)
        renamed = rename_files_in_folder(folder, parsed)

        # Single file can be renamed (implementation decides)
        assert len(renamed) <= 1
```

---

## Summary

| Phase | Priority | Effort | Status |
|-------|----------|--------|--------|
| 1. Multi-file protection | **Critical** | 1-2 hrs | Ready to implement |
| 2. Unknown ASIN policy | High | 3-4 hrs | Planned |
| 3. Enhanced resolution | Medium | 2-3 hrs | Planned |
| 4. mediainfo probe | Low | 2-3 hrs | Deferred |
| 5. Audible API | Low | 4-5 hrs | Deferred |

**Immediate action:** Fix the multi-file data loss bug in Phase 1.
