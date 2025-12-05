# Audiobookshelf Import - Future Enhancements

> **Document Version:** 1.0.0 | **Last Updated:** 2025-12-05 | **Status:** 📋 Planning

This document describes **potential future enhancements** for the ABS import feature. These are NOT implemented in the current version.

---

## Table of Contents

1. [Audnex Author API](#audnex-author-api)
2. [Smart Author Folder Resolution](#smart-author-folder-resolution)

---

## Audnex Author API

> **⚠️ NOT IMPLEMENTED — Future Enhancement Only**
>
> In the current version, we use the `(Author)` from MAM folder names directly (already normalized by MAM workflow). This section documents the Audnex Author API for potential future use to resolve canonical author names.

### Overview

The Audnex API provides an author search endpoint that could help resolve canonical author names and handle spelling variations.

### API Endpoint

```
GET https://api.audnex.us/authors?name={author_name}&region={region}
```

**Parameters:**
| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `name` | Yes | - | Author name to search |
| `region` | No | `us` | Region code: `au`, `ca`, `de`, `es`, `fr`, `in`, `it`, `jp`, `us`, `uk` |

### Response Schema

```python
from dataclasses import dataclass

@dataclass
class AudnexGenre:
    asin: str
    name: str
    type: str

@dataclass
class AudnexSimilarAuthor:
    asin: str
    name: str

@dataclass
class AudnexAuthor:
    asin: str           # Author ASIN (different from book ASIN!)
    name: str           # Canonical author name
    description: str    # Author bio
    image: str | None   # Author photo URL
    region: str         # Region code
    genres: list[AudnexGenre]
    similar: list[AudnexSimilarAuthor]
```

### Example Response

```json
[
  {
    "asin": "B001H6UJO8",
    "name": "Brandon Sanderson",
    "description": "Brandon Sanderson is an American author of epic fantasy...",
    "image": "https://images-na.ssl-images-amazon.com/images/...",
    "region": "us",
    "genres": [
      {"asin": "18574426011", "name": "Fantasy", "type": "genre"}
    ],
    "similar": [
      {"asin": "B000APZNLQ", "name": "Robert Jordan"}
    ]
  }
]
```

### Potential Use Cases

**1. Canonical Name Resolution:**
```python
# Local folder: "brandon sanderson" or "Sanderson, Brandon"
# Audnex returns: "Brandon Sanderson"
# → Use "Brandon Sanderson" as canonical name
```

**2. Author ASIN for Future Matching:**
```python
# Store author ASIN in DB for faster future lookups
# Can cross-reference with book metadata
```

**3. Spelling Correction:**
```python
# Local: "Reki Kawahara" or "Kawahara Reki"
# Audnex: "Reki Kawahara"
# → Confirms correct spelling
```

### Implementation Considerations

If implemented, the feature could:
- Suggest canonical author names in `abs-report-authors` output
- Pre-populate author aliases for common variations
- Cross-reference author ASINs with book metadata
- Cache responses to avoid repeated API calls

### Configuration (Proposed)

```yaml
audiobookshelf:
  audnex:
    enabled: false                    # Disabled by default
    cache_ttl_days: 30               # Cache author lookups
    fallback_to_folder: true         # Use folder name if API fails
```

---

## Smart Author Folder Resolution

> **⚠️ NOT IMPLEMENTED — Future Enhancement Only**
>
> In the current version, author folder resolution uses simple normalized matching only. The layered fuzzy matching described here is for future consideration.

### The Problem

The library contains author name variations from different sources:

| Folder Name | Book `(Author)` | Issue Type |
|-------------|-----------------|------------|
| `J R Mathews` | `J.R. Mathews` | Periods vs spaces in initials |
| `Nekoko` | `Necoco` | Spelling variation (Audible inconsistency) |
| `Pirateaba` | `pirateaba` | Case variation |

**Root cause:** Audible metadata is inconsistent. The same author can appear with different spellings across releases.

### The Strategy: Layered Matching

Use a **4-layer resolution strategy** (cheap → expensive):

```
1. Explicit Alias     →  "J.R. Mathews" explicitly maps to "J R Mathews" (config file)
2. Normalized Exact   →  normalize("J.R. Mathews") == normalize("J R Mathews") ✓
3. Fuzzy Match        →  "Necoco" ≈ "Nekoko" (89% similarity)
4. Create New         →  No match found, create new folder
```

### Layer 1: Author Aliases File

Explicit overrides for known variations (no fuzzy guessing):

```yaml
# config/author_aliases.yaml
"J.R. Mathews": "J R Mathews"
"J R Mathews": "J R Mathews"
"Necoco": "Nekoko"
"NECOCO": "Nekoko"
"pirateaba": "Pirateaba"
"necoko": "Nekoko"
```

**Benefits:**
- Deterministic - no fuzzy surprises
- Grows over time as you encounter variations
- Can be auto-generated from fuzzy match suggestions

### Layer 2: Strong Normalization

Normalize author names before comparison (solves 90% of cases without fuzzy):

```python
import re
import unicodedata


def normalize_author_for_compare(name: str) -> str:
    """Normalize author name for comparison.

    Handles:
    - Case: "BRANDON SANDERSON" → "brandon sanderson"
    - Unicode: "café" → "cafe"
    - Initials: "J.R." → "j r", "J. R." → "j r"
    - Suffixes: "Brandon Sanderson Jr." → "brandon sanderson jr"
    - Common variations: "& " → " and "
    """
    result = name.lower()

    # Normalize unicode to ASCII
    result = unicodedata.normalize("NFKD", result)
    result = result.encode("ascii", "ignore").decode("ascii")

    # Expand common abbreviations
    result = result.replace("&", " and ")

    # Normalize initials: "J.R." → "j r"
    result = re.sub(r"\.(?=\s|$|\w)", " ", result)

    # Collapse whitespace
    result = re.sub(r"\s+", " ", result).strip()

    return result
```

**Examples:**
| Input | Normalized |
|-------|------------|
| `J.R. Mathews` | `j r mathews` |
| `J R Mathews` | `j r mathews` |
| `Brandon Sanderson` | `brandon sanderson` |
| `BRANDON SANDERSON` | `brandon sanderson` |

### Layer 3: Fuzzy Matching

For cases normalization can't handle (spelling variations):

```python
from rapidfuzz import fuzz

def find_best_author_match(
    incoming: str,
    existing_folders: list[str],
    threshold: float = 85.0
) -> str | None:
    """Find best matching author folder using fuzzy matching."""
    normalized_incoming = normalize_author_for_compare(incoming)

    best_match = None
    best_score = 0.0

    for folder in existing_folders:
        normalized_folder = normalize_author_for_compare(folder)
        score = fuzz.ratio(normalized_incoming, normalized_folder)

        if score > best_score and score >= threshold:
            best_score = score
            best_match = folder

    return best_match
```

**Threshold considerations:**
- 85%+ = Safe match (initials, minor spelling)
- 70-84% = Prompt user for confirmation
- <70% = Create new folder

### Layer 4: Create New

If no match found in layers 1-3, create a new author folder.

### Implementation Flow

```python
def resolve_author_folder(
    incoming_author: str,
    library_root: Path,
    aliases: dict[str, str],
) -> Path:
    """Resolve author name to folder path using 4-layer strategy."""

    # Layer 1: Check aliases
    if incoming_author in aliases:
        canonical = aliases[incoming_author]
        return library_root / canonical

    # Layer 2: Normalized exact match
    existing_folders = [f.name for f in library_root.iterdir() if f.is_dir()]
    normalized_incoming = normalize_author_for_compare(incoming_author)

    for folder in existing_folders:
        if normalize_author_for_compare(folder) == normalized_incoming:
            return library_root / folder

    # Layer 3: Fuzzy match
    fuzzy_match = find_best_author_match(incoming_author, existing_folders)
    if fuzzy_match:
        # Log for review
        logger.info(f"Fuzzy matched '{incoming_author}' → '{fuzzy_match}'")
        return library_root / fuzzy_match

    # Layer 4: Create new
    return library_root / incoming_author
```

### Author Variant Report

Generate a report of detected variations for manual review:

```bash
$ mamfast abs-report-authors

Author Folder Variants
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ Folder Name    ┃ Book (Author)  ┃ Score     ┃ Book Count   ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
│ J R Mathews    │ J.R. Mathews   │ 100 (norm)│ 4            │
│ Nekoko         │ Necoco         │ 89 (fuzzy)│ 1            │
│ Pirateaba      │ pirateaba      │ 100 (norm)│ 2            │
└────────────────┴────────────────┴───────────┴──────────────┘

Suggested additions to config/author_aliases.yaml:
  "J.R. Mathews": "J R Mathews"
  "Necoco": "Nekoko"
```

### Configuration (Proposed)

```yaml
audiobookshelf:
  author_resolution:
    enabled: true
    fuzzy_threshold: 85.0           # Minimum similarity for auto-match
    prompt_threshold: 70.0          # Below this, prompt user
    aliases_file: "config/author_aliases.yaml"
```

---

## Implementation Priority

If these features are implemented, suggested order:

| Feature | Priority | Effort | Impact |
|---------|----------|--------|--------|
| Author Aliases File | High | 2-3 hrs | Handles known variations |
| Normalized Matching | High | 2-3 hrs | Solves 90% of cases |
| Author Variant Report | Medium | 3-4 hrs | Helps identify issues |
| Fuzzy Matching | Low | 2-3 hrs | Edge cases only |
| Audnex Integration | Low | 4-5 hrs | Nice to have |

---

## Related Documentation

- [AUDIOBOOKSHELF_IMPORT.md](AUDIOBOOKSHELF_IMPORT.md) - Current import feature
- [AUDIOBOOKSHELF_REFERENCE.md](AUDIOBOOKSHELF_REFERENCE.md) - Technical reference, changelog
