# Naming Implementation Guide

> Implementation phases, testing strategy, and changelog for Shelfr naming system.

## Related Documentation

| Document | Description |
| --- | --- |
| [Naming Overview](./NAMING.md) | Quick reference and architecture |
| [Processing Pipeline](./NAMING_PIPELINE.md) | Full cleaning pipeline |
| [Rules Reference](./NAMING_RULES.md) | Matching rules |

---

## Implementation Phases

### Phase 1: Core Infrastructure ✅

**Goal:** Basic naming pipeline with Pydantic validation

**Completed:**

- [x] `NormalizedBook` model in `models.py`
- [x] `MamPath` model with truncation tracking
- [x] Basic `clean_title()` function
- [x] `build_mam_folder_name()` and `build_mam_file_name()`
- [x] Pydantic schema for `naming.json`

### Phase 2: Audnex Integration ✅

**Goal:** Automatic metadata normalization from Audnex API

**Completed:**

- [x] Title/subtitle swap detection
- [x] Series extraction from multiple patterns
- [x] Series position normalization (zero-padding)
- [x] Fuzzy matching for series name comparison
- [x] `NormalizedBook.from_audnex()` factory method

### Phase 3: Phrase Removal ✅

**Goal:** Comprehensive removal of marketing text

**Completed:**

- [x] Edition markers (Unabridged, Dramatized, etc.)
- [x] Marketing phrases (A Novel, A Thriller, etc.)
- [x] Format indicators (Audio Download, etc.)
- [x] Narrator markers (Narrated by, Read by)
- [x] Configurable rules in `naming.json`

### Phase 4: Character Handling ✅

**Goal:** Cross-platform filename safety

**Completed:**

- [x] pathvalidate integration
- [x] Unicode normalization (NFC)
- [x] Japanese transliteration (kanji → romaji)
- [x] Accent removal (José → Jose)
- [x] Special character handling (& → and)

### Phase 5: Truncation ✅

**Goal:** Handle MAM's 225-character path limit

**Completed:**

- [x] Length calculation for full path
- [x] Smart truncation (preserve author, ASIN, series)
- [x] Hash suffix for uniqueness
- [x] `MamPath` tracking of truncation metadata

### Phase 6: Golden Testing ✅

**Goal:** Regression testing with real-world examples

**Completed:**

- [x] Golden test framework in `test_golden.py`
- [x] Input fixtures: `golden/naming_inputs.json`
- [x] Expected fixtures: `golden/naming_expected.json`
- [x] Automated comparison and reporting

---

## Testing Strategy

### Test Levels

```text
┌─────────────────────────────────────────────────────────────────┐
│                     Testing Pyramid                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│                    ┌───────────────┐                            │
│                    │  Integration  │  ← Full pipeline tests     │
│                    └───────────────┘                            │
│               ┌─────────────────────────┐                       │
│               │     Golden Tests        │  ← Real-world samples │
│               └─────────────────────────┘                       │
│          ┌───────────────────────────────────┐                  │
│          │         Unit Tests                │  ← Function level│
│          └───────────────────────────────────┘                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Unit Tests

Test individual functions in isolation:

```python
# tests/test_naming.py

class TestCleanTitle:
    """Tests for clean_title() function."""

    def test_removes_unabridged(self):
        assert clean_title("Book (Unabridged)") == "Book"

    def test_removes_multiple_markers(self):
        assert clean_title("Book (Unabridged): A Novel") == "Book"

    def test_preserves_valid_parentheses(self):
        assert clean_title("Book (Part 1)") == "Book (Part 1)"

class TestBuildFolderName:
    """Tests for build_mam_folder_name() function."""

    def test_basic_folder(self):
        result = build_mam_folder_name(
            author="Author",
            title="Title",
            year=2021,
            narrator="Narrator",
            asin="B0123456789"
        )
        assert result == "Author - Title (2021) (Narrator) {ASIN.B0123456789}"

    def test_with_series(self):
        result = build_mam_folder_name(
            author="Author",
            title="Title",
            year=2021,
            narrator="Narrator",
            asin="B0123456789",
            series="Series",
            series_position="1"
        )
        assert "Series vol_01" in result
```

### Golden Tests

Test against known-good outputs:

```python
# tests/test_golden.py

import json
from pathlib import Path

def test_golden_naming():
    """All golden samples produce expected output."""
    inputs = json.loads(Path("tests/golden/naming_inputs.json").read_text())
    expected = json.loads(Path("tests/golden/naming_expected.json").read_text())

    for inp, exp in zip(inputs, expected):
        result = process_naming(inp)
        assert result == exp, f"Mismatch for {inp['id']}"
```

### Integration Tests

Test full pipeline:

```python
# tests/test_integration.py

def test_full_naming_pipeline():
    """Complete pipeline from discovery to MAM path."""
    release = discover_audiobook("/test/library/Book")
    metadata = fetch_metadata(release.asin)
    mam_path = build_mam_path(release, metadata)

    assert mam_path.path_length <= 225
    assert mam_path.folder_name.endswith(f"{{ASIN.{release.asin}}}")
```

### Coverage Goals

| Module | Target | Current |
| --- | --- | --- |
| `utils/naming/` | 95% | 94% |
| `models.py` (naming) | 90% | 92% |
| `schemas/naming.py` | 100% | 100% |

### Running Tests

```bash
# All naming tests
pytest tests/test_naming.py tests/test_golden.py -v

# With coverage
pytest tests/test_naming.py --cov=src/Shelfr/utils/naming --cov-report=term-missing

# Golden tests only
pytest tests/test_golden.py -v

# Normalization tests
pytest tests/test_normalization.py -v
```

---

## Adding New Features

### Adding a New Phrase Rule

1. **Edit `config/naming.json`:**

   ```json
   {
     "edition_markers": [
       // existing...
       "(New Marker)"
     ]
   }
   ```

2. **Add unit test:**

   ```python
   def test_new_marker_removal():
       assert clean_title("Book (New Marker)") == "Book"
   ```

3. **Add golden test case:**

   ```json
   // naming_inputs.json
   {"id": "new_marker", "title": "Book (New Marker)", ...}

   // naming_expected.json
   {"id": "new_marker", "cleaned_title": "Book", ...}
   ```

4. **Run tests:**

   ```bash
   pytest tests/test_naming.py tests/test_golden.py -v
   ```

### Adding Author Mapping

1. **Edit `config/naming.json`:**

   ```json
   {
     "author_map": {
       "Author Alias": "Canonical Name"
     }
   }
   ```

2. **Add test:**

   ```python
   def test_author_mapping():
       assert map_author("Author Alias") == "Canonical Name"
   ```

### Adding Series Pattern

1. **Edit `config/naming.json`:**

   ```json
   {
     "series_patterns": [
       // existing...
       "(?P<series>.+?)\\s*Episode\\s*(?P<position>\\d+)"
     ]
   }
   ```

2. **Add test:**

   ```python
   def test_episode_pattern():
       series, pos = extract_series("Show Episode 5")
       assert series == "Show"
       assert pos == "05"
   ```

---

## Troubleshooting

### Common Issues

#### Title Not Cleaned

**Symptom:** Marketing text remains in title

**Debug:**

```python
from Shelfr.utils.naming import clean_title, _apply_rules

# Check which rules match
result, applied = _apply_rules(title, debug=True)
print(f"Applied rules: {applied}")
```

**Solution:** Add missing pattern to `naming.json`

#### Series Not Detected

**Symptom:** Series info not extracted

**Debug:**

```python
from Shelfr.utils.naming import extract_series

series, pos = extract_series(subtitle, debug=True)
print(f"Series: {series}, Position: {pos}")
```

**Solution:** Check series patterns, may need new pattern

#### Path Too Long

**Symptom:** MamPath exceeds 225 chars

**Debug:**

```python
mam_path = build_mam_path(release, metadata)
print(f"Length: {mam_path.path_length}")
print(f"Truncated: {mam_path.was_truncated}")
```

**Solution:** Check truncation is working, may need longer hash

---

## Changelog

### v1.5.0 (Current)

- **BBCode description filtering**: Apply title/subtitle filtering to BBCode description header
- **Dry-run counter fix**: Increment success/skip counters in dry-run mode for accurate summaries
- **Documentation restructure**: Split monolithic NAMING_PLAN.md into focused modules
- Moved Audiobookshelf docs to dedicated `docs/audiobookshelf/` subdirectory

### v1.4.0

- Added ABS import with ASIN duplicate detection
- Unknown ASIN policy: homebrew routing
- Quarantine path validation

### v1.3.0

- Golden test framework
- Comprehensive phrase removal rules
- Japanese transliteration improvements

### v1.2.0

- Audnex integration for metadata normalization
- Title/subtitle swap detection
- Series position zero-padding

### v1.1.0

- MamPath model with truncation tracking
- 225-character path limit handling
- Hash suffix for uniqueness

### v1.0.0

- Initial naming pipeline
- Basic phrase removal
- Pydantic validation

---

## Future Improvements

### Planned

- [ ] Machine learning for title/subtitle detection
- [ ] Bulk rule testing interface
- [ ] Visual diff for golden test failures
- [ ] Performance optimization for large libraries

### Under Consideration

- [ ] Custom user rules in config
- [ ] Per-publisher rule overrides
- [ ] Automatic rule suggestion from failures
- [ ] Integration with external metadata sources

---

## Questions & Decisions

### Resolved

**Q: Should we preserve subtitle in output?**
A: No, subtitles are dropped. Series info in subtitle is extracted, marketing text is removed.

**Q: How to handle multiple authors?**
A: Use first author only in folder/file name. All authors in MAM JSON.

**Q: Truncation: title or author?**
A: Always truncate title. Author is critical for identification.

### Open

**Q: Should we support custom output templates?**
Status: Under consideration for v2.0

**Q: Support for non-English metadata?**
Status: Basic support exists (transliteration). Full i18n TBD.

---

## See Also

- [CLAUDE.md](/CLAUDE.md) - Full project reference
- [CONTRIBUTING.md](/CONTRIBUTING.md) - Contribution guidelines
- [tests/](/tests/) - Test suite
