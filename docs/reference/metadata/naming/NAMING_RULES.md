# Naming Rules Reference

> Matching rules, phrase removal patterns, author map, and volume normalization for Shelfr.

## Related Documentation

| Document | Description |
| --- | --- |
| [Naming Overview](./NAMING.md) | Quick reference and architecture |
| [Processing Pipeline](./NAMING_PIPELINE.md) | Full cleaning pipeline |
| [Folder & File Schemas](./NAMING_FOLDER_FILE_SCHEMAS.md) | Output formats |

---

## Configuration File: `naming.json`

All rules are defined in `config/naming.json` and validated by `schemas/naming.py`.

### Structure

```json
{
  "edition_markers": [...],
  "marketing_phrases": [...],
  "format_indicators": [...],
  "narrator_markers": [...],
  "author_map": {...},
  "series_patterns": [...],
  "volume_aliases": {...}
}
```

---

## Phrase Removal Rules

### Edition Markers

Remove edition and format indicators:

```json
{
  "edition_markers": [
    "(Unabridged)",
    "[Unabridged]",
    "(Abridged)",
    "[Dramatized Adaptation]",
    "(Dramatized)",
    "[Full Cast Recording]",
    "(Anniversary Edition)",
    "[Remastered]"
  ]
}
```

**Pattern Type:** Case-insensitive literal match

**Examples:**

| Input | Output |
| --- | --- |
| `Project Hail Mary (Unabridged)` | `Project Hail Mary` |
| `Dune [Dramatized Adaptation]` | `Dune` |
| `The Stand (Unabridged)` | `The Stand` |

### Marketing Phrases

Remove common marketing text:

```json
{
  "marketing_phrases": [
    "A Novel",
    "An Audiobook Original",
    "A Thriller",
    "A Mystery",
    "A Romance",
    "A Memoir",
    "The Complete Novel",
    "The Unabridged Novel"
  ]
}
```

**Pattern Type:** Word-boundary regex match

**Examples:**

| Input | Output |
| --- | --- |
| `The Martian: A Novel` | `The Martian` |
| `Gone Girl: A Thriller` | `Gone Girl` |
| `An Audiobook Original: The Story` | `The Story` |

### Format Indicators

Remove format-specific text:

```json
{
  "format_indicators": [
    "(Audio Download)",
    "[Audible Edition]",
    "(Audible Audio Edition)",
    "[Kindle in Motion]",
    "(Premium Edition)"
  ]
}
```

### Narrator Markers

Remove embedded narrator credits:

```json
{
  "narrator_markers": [
    "Narrated by [^,]+,?",
    "Read by [^,]+,?",
    "Performed by [^,]+,?"
  ]
}
```

**Pattern Type:** Regex (matches narrator name)

**Examples:**

| Input | Output |
| --- | --- |
| `The Book, Narrated by John Smith` | `The Book` |
| `Title - Read by Jane Doe` | `Title` |

---

## Matching Rules

### Rule Application Order

1. **Edition Markers** - Most specific, literal match
2. **Format Indicators** - Bracketed/parenthesized
3. **Marketing Phrases** - Word-boundary match
4. **Narrator Markers** - Regex patterns
5. **Final Cleanup** - Whitespace normalization

### Regex Patterns

Complex patterns use regex with these conventions:

```python
# Word boundary matching
r"\b(A Novel)\b"  # Matches "A Novel" not "Anovella"

# Optional punctuation
r":?\s*A Novel"  # Matches ": A Novel" or "A Novel"

# Case insensitive
re.IGNORECASE  # Applied to all patterns
```

### Compound Removals

Some phrases chain together:

```text
Input:  "The Book: A Novel (Unabridged)"
Step 1: "The Book: A Novel"  (edition marker removed)
Step 2: "The Book"           (marketing phrase removed)
```

---

## Author Map

### Purpose

Map author name variations to canonical forms:

```json
{
  "author_map": {
    "Stephen King writing as Richard Bachman": "Stephen King",
    "J.K. Rowling writing as Robert Galbraith": "J.K. Rowling",
    "Nora Roberts writing as J.D. Robb": "Nora Roberts",
    "Dean Koontz writing as Leigh Nichols": "Dean Koontz",
    "Anne Rice writing as A.N. Roquelaure": "Anne Rice"
  }
}
```

### Author Matching Rules

1. **Exact Match**: Check full string first
2. **Pattern Match**: Check for "writing as" pattern
3. **Passthrough**: If no match, return unchanged

### Examples (Literal Match)

| Input | Output |
| --- | --- |
| `Stephen King writing as Richard Bachman` | `Stephen King` |
| `Stephen King` | `Stephen King` |
| `Richard Bachman` | `Richard Bachman` (no map) |

### Implementation

```python
def map_author(author: str, author_map: dict[str, str]) -> str:
    """Map author name to canonical form."""
    # Direct lookup
    if author in author_map:
        return author_map[author]

    # Pattern check for "writing as"
    for pattern, canonical in author_map.items():
        if "writing as" in pattern:
            base_author = pattern.split(" writing as ")[0]
            if author == base_author:
                return canonical

    return author
```

---

## Volume/Book Normalization

### Series Patterns

Detect and extract series information:

```json
{
  "series_patterns": [
    "(?P<series>.+?),?\\s*Book\\s*(?P<position>\\d+(?:\\.\\d+)?)",
    "(?P<series>.+?),?\\s*Volume\\s*(?P<position>\\d+(?:\\.\\d+)?)",
    "(?P<series>.+?),?\\s*Vol\\.?\\s*(?P<position>\\d+(?:\\.\\d+)?)",
    "(?P<series>.+?),?\\s*Part\\s*(?P<position>\\d+(?:\\.\\d+)?)",
    "(?P<series>.+?)\\s*#(?P<position>\\d+(?:\\.\\d+)?)"
  ]
}
```

**Matches:**

- "The Stormlight Archive, Book 1"
- "Mistborn Volume 2"
- "Red Rising #3"
- "The Expanse, Part 1.5"

### Volume Aliases

Map named positions to numbers:

```json
{
  "volume_aliases": {
    "prequel": "0",
    "prologue": "0",
    "prelude": "0",
    "origin": "0",
    "origins": "0",
    "introduction": "0",
    "omnibus": null
  }
}
```

### Position Normalization

```python
def normalize_position(position: str) -> str:
    """Normalize series position to vol_XX format."""
    # Handle aliases
    if position.lower() in VOLUME_ALIASES:
        mapped = VOLUME_ALIASES[position.lower()]
        if mapped is None:
            return ""  # Omnibus - no volume
        position = mapped

    # Extract number (handles decimals, ranges, and parts)
    # Examples: "1", "1.5", "1-3" (range), "1p1" (part)

    # Check for part notation: "1p1", "1 part 1", "1_01"
    part_match = re.search(r"(\d+)(?:p|\s*part\s*|_)(\d+)", position, re.IGNORECASE)
    if part_match:
        main = int(part_match.group(1))
        part = int(part_match.group(2))
        return f"vol_{main:02d}p{part}"

    # Check for range notation: "1-3", "01-03"
    range_match = re.search(r"(\d+)-(\d+)", position)
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        # Only treat as range if end > start (not a part)
        if end > start:
            return f"vol_{start:02d}-{end:02d}"

    # Standard number extraction
    match = re.search(r"(\d+(?:\.\d+)?)", position)
    if not match:
        return ""

    number = match.group(1)

    # Zero-pad integer part for decimals (novellas)
    if "." in number:
        integer, decimal = number.split(".")
        return f"vol_{int(integer):02d}.{decimal}"
    else:
        return f"vol_{int(number):02d}"
```

### Volume Notation Reference

See [Folder & File Schemas](./NAMING_FOLDER_FILE_SCHEMAS.md#volume-notation) for the canonical volume notation spec.

### Examples (Volume)

| Input | Output | Use Case |
| --- | --- | --- |
| `1` | `vol_01` | Standard volume |
| `12` | `vol_12` | Double-digit volume |
| `1.5` | `vol_01.5` | Novella/side story |
| `1p1` | `vol_01p1` | Part 1 of Graphic Audio split |
| `1p2` | `vol_01p2` | Part 2 of Graphic Audio split |
| `1 part 1` | `vol_01p1` | Alternate part notation |
| `01_01` | `vol_01p1` | Legacy part notation (normalized) |
| `1-3` | `vol_01-03` | Publisher Pack (books 1-3) |
| `1-02` | `vol_01-02` | Publisher Pack (books 1-2) |
| `Prequel` | `vol_00` | Special position mapping |
| `Omnibus` | `` (empty) | No volume number |

---

## Custom Rules

### Adding New Phrases

1. Edit `config/naming.json`
2. Add to appropriate category
3. Run tests: `pytest tests/test_naming.py`

```json
{
  "edition_markers": [
    // Existing markers...
    "(Special Edition)"  // New marker
  ]
}
```

### Adding Author Mappings

```json
{
  "author_map": {
    // Existing mappings...
    "New Author Alias": "Canonical Name"
  }
}
```

### Testing Custom Rules

```python
# tests/test_naming.py

def test_custom_edition_marker():
    """Custom edition marker is removed."""
    result = clean_title("Book Title (Special Edition)")
    assert result == "Book Title"

def test_custom_author_map():
    """Custom author mapping works."""
    result = map_author("New Author Alias")
    assert result == "Canonical Name"
```

---

## Golden Tests

### Input File: `tests/golden/naming_inputs.json`

```json
[
  {
    "id": "basic_unabridged",
    "title": "Project Hail Mary (Unabridged)",
    "author": "Andy Weir",
    "series": null,
    "position": null
  },
  {
    "id": "series_book",
    "title": "The Way of Kings",
    "author": "Brandon Sanderson",
    "series": "The Stormlight Archive",
    "position": "1"
  }
]
```

### Expected File: `tests/golden/naming_expected.json`

```json
[
  {
    "id": "basic_unabridged",
    "cleaned_title": "Project Hail Mary",
    "folder_name": "Andy Weir - Project Hail Mary (2021) (Ray Porter) {ASIN.B08G9PRS1K}"
  },
  {
    "id": "series_book",
    "cleaned_title": "The Way of Kings",
    "folder_name": "Brandon Sanderson - Stormlight Archive vol_01 - The Way of Kings (2010) (Michael Kramer) {ASIN.B003ZWFO7E}"
  }
]
```

### Running Golden Tests

```bash
pytest tests/test_golden.py -v
```

---

## Rule Precedence

When multiple rules could match, precedence is:

1. **Exact match** over pattern match
2. **Longer pattern** over shorter pattern
3. **Earlier in list** over later in list

### Example

```bash
Input: "The Book: A Novel (Unabridged)"

Rule 1: "(Unabridged)" - edition_markers[0]
Rule 2: "A Novel" - marketing_phrases[0]

Both apply, processed in order:
Step 1: "The Book: A Novel"
Step 2: "The Book"
```

---

## See Also

- [config/naming.json](/config/naming.json) - Rule definitions
- [schemas/naming.py](/src/Shelfr/schemas/naming.py) - Pydantic validation
- [src/Shelfr/utils/naming/](/src/Shelfr/utils/naming/) - Implementation
- [test_naming.py](/tests/test_naming.py) - Unit tests
