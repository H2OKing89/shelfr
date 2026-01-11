# Data Gathering Scripts

Tools for collecting audiobook metadata from external sources to build comprehensive test datasets.

## Audible Catalog Script

**File:** `audible_catalog.py`

Fetches audiobook metadata from Audible's catalog API using authenticated access.

### Features

- 🔐 **Encrypted credentials** - Auth stored encrypted with password from `config/.env`
- 📚 **Multiple search strategies** - Pre-built patterns for LitRPG, Fantasy, SciFi, etc.
- 📊 **Structured output** - Pydantic schemas + JSONL format
- 🔄 **Pagination support** - Fetch thousands of titles
- ⚡ **Async client** - Fast, efficient API calls

### Setup

#### 1. Install Dependencies

The `audible` package is required (already installed if you ran the initial setup):

```bash
source .venv/bin/activate
pip install git+https://github.com/mkb79/Audible.git
```

#### 2. Configure Encryption Password

The Audible auth file is encrypted for security. Set the password in `config/.env`:

```dotenv
# Already added:
AUDIBLE_PASSWORD=shelfr-audible-2026
```

**Note:** `config/.env` is gitignored - credentials stay private.

#### 3. Login to Audible

Register a virtual device (one-time):

```bash
python scripts/data_gathering/audible_catalog.py login
```

You'll be prompted for:

- Amazon email
- Amazon password
- 2FA code (if enabled)

Auth file saved to `data/audible_auth.json` (encrypted, gitignored).

### Usage

#### Test Connection

```bash
python scripts/data_gathering/audible_catalog.py test
```

Verifies API access with a sample search.

#### Search by Keywords

```bash
python scripts/data_gathering/audible_catalog.py search \
  --keywords "progression fantasy" \
  --pages 5 \
  --output data/progression_fantasy.jsonl
```

#### List Available Strategies

```bash
python scripts/data_gathering/audible_catalog.py list
```

Shows pre-built search strategies:

- `litrpg` - LitRPG, GameLit, cultivation novels
- `fantasy` - Epic, urban, paranormal fantasy
- `scifi` - Space opera, cyberpunk, hard SF
- `romance` - Contemporary, paranormal, historical
- `thriller` - Crime, psychological thrillers
- `nonfiction` - Biography, self-help, business
- `light_novel` - Japanese light novels

#### Gather by Strategy (Recommended)

```bash
# Gather 500 LitRPG/progression fantasy titles
python scripts/data_gathering/audible_catalog.py gather \
  --strategy litrpg \
  --max-items 500 \
  --output data/litrpg_titles.jsonl

# Gather light novels
python scripts/data_gathering/audible_catalog.py gather \
  --strategy light_novel \
  --max-items 300

# Output defaults to data/audible_catalog_samples.jsonl
```

**What it does:**

1. Searches all keywords in the strategy
2. Fetches all category IDs in the strategy
3. De-duplicates by ASIN
4. Appends to JSONL output (safe for resuming)

### Output Schema

Each line in the JSONL is an `AudibleProduct` with:

```json
{
  "asin": "B0CTXKB2R6",
  "title": "Beware of Chicken: A Xianxia Cultivation Novel",
  "authors": [{"name": "Casualfarmer", "asin": "B09XXXX"}],
  "narrators": [{"name": "Travis Baldree"}],
  "series": [{"title": "Beware of Chicken", "sequence": "1"}],
  "category_ladders": [...],
  "runtime_length_min": 1083,
  "language": "english",
  "format_type": "unabridged",
  "release_date": "2022-04-26",
  "fetched_at": "2026-01-09T18:30:00Z",
  "marketplace": "us"
}
```

### Building a Comprehensive Dataset

To gather a large, diverse pool for title pattern analysis:

```bash
#!/bin/bash
# Gather multiple strategies (5000+ titles total)

python scripts/data_gathering/audible_catalog.py gather -s litrpg --max-items 800
python scripts/data_gathering/audible_catalog.py gather -s fantasy --max-items 600
python scripts/data_gathering/audible_catalog.py gather -s light_novel --max-items 400
python scripts/data_gathering/audible_catalog.py gather -s scifi --max-items 500
python scripts/data_gathering/audible_catalog.py gather -s romance --max-items 400
python scripts/data_gathering/audible_catalog.py gather -s thriller --max-items 400
python scripts/data_gathering/audible_catalog.py gather -s nonfiction --max-items 300

# Results in data/audible_catalog_samples.jsonl (~3400 unique titles)
```

### Analysis

Once you have the JSONL data:

```python
import json
from pathlib import Path

# Load all products
products = []
for line in Path("data/audible_catalog_samples.jsonl").read_text().splitlines():
    products.append(json.loads(line))

# Analyze title patterns
titles_with_tags = [p for p in products if ":" in p["title"]]
print(f"Titles with reading lines: {len(titles_with_tags)}/{len(products)}")

# Extract unique patterns
patterns = set()
for p in titles_with_tags:
    if ":" in p["title"]:
        tag = p["title"].split(":", 1)[1].strip()
        patterns.add(tag)

for pattern in sorted(patterns)[:50]:
    print(f"  - {pattern}")
```

### API Rate Limits

Audible doesn't publish official limits, but be respectful:

- Default delay: 0.5s between requests
- Adjust with `--delay` flag if needed
- The script uses async for efficiency

### Troubleshooting

**Auth file not found:**

```
Run: python scripts/data_gathering/audible_catalog.py login
```

**AUDIBLE_PASSWORD not set warning:**

```
Add AUDIBLE_PASSWORD to config/.env
```

**Login fails / 2FA issues:**

- Check your Amazon credentials
- If 2FA enabled, append OTP to password: `password123456`
- Or use the interactive 2FA prompt

**Marketplace-specific searches:**

```bash
python scripts/data_gathering/audible_catalog.py -m uk login
python scripts/data_gathering/audible_catalog.py -m uk gather -s fantasy
```

### Related Scripts

- `fetch_test_data.py` - Fetches from Audiobookshelf + Audnex
- `hardcover_enrich.py` - Enriches with Hardcover metadata
- `build_golden_samples.py` - Builds golden test samples

### References

- [Audible Python Library](https://github.com/mkb79/Audible)
- [API Documentation](../../docs/reference/audible/Audible/upstream/misc_external_api.rst.txt)
- [Encrypted Auth](../../docs/reference/audible/Audible/upstream/misc_load_save.rst.txt)
