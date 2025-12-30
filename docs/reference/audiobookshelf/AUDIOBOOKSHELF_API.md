# Audiobookshelf API Reference

> **Version:** 1.0.0 | **Last Updated:** 2025-12-03 | **Status:** Reference Doc

This document covers the ABS API endpoints used by MAMFast for the import feature.

---

## Table of Contents

1. [Authentication](#authentication)
2. [Core Endpoints](#core-endpoints)
   - [GET /api/authorize](#get-apiauthorize)
   - [GET /api/libraries](#get-apilibraries)
   - [GET /api/libraries/{id}/items](#get-apilibrariesiditems)
   - [GET /api/items/{id}](#get-apiitemsid)
   - [POST /api/libraries/{id}/scan](#post-apilibrariesidscan)
   - [GET /api/search/books](#get-apisearchbooks)
3. [Response Schemas](#response-schemas)
4. [Error Handling](#error-handling)
5. [Rate Limiting](#rate-limiting)

---

## Authentication

ABS uses Bearer token authentication. The API token can be found in:
**ABS Web UI → Config → Users → [Your Account]**

### Request Header

```http
Authorization: Bearer <API_TOKEN>
```

> **Security Note:** Authentication is only supported via the `Authorization: Bearer <API_TOKEN>` header.
> Passing tokens in URL query strings is not supported due to security risks (tokens may leak via logs, browser history, or Referer headers).

### Token from Environment

```bash
# config/.env
AUDIOBOOKSHELF_API_KEY=eyJhbGciOiJ.............................
```

---

## Core Endpoints

### GET /api/authorize

Validates the API token and returns user/server information.

**Use Case:** `mamfast abs-init` - Validate connection and get server version.

```bash
curl -X POST "https://abs.example.com/api/authorize" \
  -H "Authorization: Bearer <TOKEN>"
```

**Response:**

```json
{
  "user": {
    "id": "root",
    "username": "root",
    "type": "root",
    "token": "...",
    "permissions": {
      "download": true,
      "update": true,
      "delete": true,
      "upload": true,
      "accessAllLibraries": true
    }
  },
  "userDefaultLibraryId": "lib_c1u6t4p45c35rf0nzd",
  "serverSettings": {
    "version": "2.7.2"
  },
  "Source": "docker"
}
```

**Key Fields for MAMFast:**
- `user.permissions.accessAllLibraries` - Check user has library access
- `serverSettings.version` - Log for debugging
- `Source` - "docker" indicates we need path mapping

---

### GET /api/libraries

Lists all libraries the user has access to.

**Use Case:** `mamfast abs-init` - Discover libraries and their root paths.

```bash
curl "https://abs.example.com/api/libraries" \
  -H "Authorization: Bearer <TOKEN>"
```

**Response:**

```json
{
  "libraries": [
    {
      "id": "lib_c1u6t4p45c35rf0nzd",
      "name": "Audiobooks",
      "folders": [
        {
          "id": "fol_bev1zuxhb0j0s1wehr",
          "fullPath": "/audiobooks",
          "libraryId": "lib_c1u6t4p45c35rf0nzd"
        }
      ],
      "displayOrder": 1,
      "icon": "audiobookshelf",
      "mediaType": "book",
      "provider": "audible",
      "settings": {
        "coverAspectRatio": 1,
        "disableWatcher": false,
        "skipMatchingMediaWithAsin": false
      },
      "createdAt": 1633522963509,
      "lastUpdate": 1646520916818
    }
  ]
}
```

**Key Fields for MAMFast:**
- `id` - Library ID for config
- `name` - Display name for CLI output
- `folders[].fullPath` - Container path (needs mapping to host)
- `mediaType` - Must be "book" for audiobook libraries

---

### GET /api/libraries/{id}/items

Lists all items in a library. This is the **primary endpoint** for indexing.

**Use Case:** `mamfast abs-import` - Build in-memory ASIN index for duplicate detection.

```bash
# Get all items (no pagination for full index)
curl "https://abs.example.com/api/libraries/lib_xxx/items?limit=0" \
  -H "Authorization: Bearer <TOKEN>"

# With minified response (smaller payload)
curl "https://abs.example.com/api/libraries/lib_xxx/items?limit=0&minified=1" \
  -H "Authorization: Bearer <TOKEN>"
```

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | Integer | varies | Items per page. **Use 0 for all items.** |
| `page` | Integer | 0 | Page number (0-indexed) |
| `sort` | String | - | Sort by field (e.g., `media.metadata.title`) |
| `minified` | Binary | 0 | Return minified objects (1=true) |
| `filter` | String | - | Filter results (Base64 encoded) |

**Response (Full):**

```json
{
  "results": [
    {
      "id": "li_8gch9ve09orgn4fdz8",
      "ino": "649641337522215266",
      "libraryId": "lib_c1u6t4p45c35rf0nzd",
      "folderId": "fol_bev1zuxhb0j0s1wehr",
      "path": "/audiobooks/Terry Goodkind/Sword of Truth/Wizards First Rule",
      "relPath": "Terry Goodkind/Sword of Truth/Wizards First Rule",
      "isFile": false,
      "mtimeMs": 1650621074299,
      "ctimeMs": 1650621074299,
      "birthtimeMs": 0,
      "addedAt": 1650621073750,
      "updatedAt": 1650621110769,
      "isMissing": false,
      "isInvalid": false,
      "mediaType": "book",
      "media": {
        "metadata": {
          "title": "Wizards First Rule",
          "titleIgnorePrefix": "Wizards First Rule",
          "subtitle": null,
          "authorName": "Terry Goodkind",
          "narratorName": "Sam Tsoutsouvas",
          "seriesName": "Sword of Truth",
          "genres": ["Fantasy"],
          "publishedYear": "2008",
          "publisher": "Brilliance Audio",
          "isbn": null,
          "asin": "B002V0QK4C",
          "language": null,
          "explicit": false
        },
        "coverPath": "/audiobooks/Terry Goodkind/Sword of Truth/Wizards First Rule/cover.jpg",
        "tags": [],
        "numTracks": 2,
        "numAudioFiles": 2,
        "numChapters": 2,
        "duration": 12000.946,
        "size": 96010240
      },
      "numFiles": 3,
      "size": 96335771
    }
  ],
  "total": 1327,
  "limit": 0,
  "page": 0,
  "mediaType": "book"
}
```

**Key Fields for MAMFast Index:**

| Field | Use |
|-------|-----|
| `id` | ABS item ID |
| `path` | Container path (map to host) |
| `relPath` | Relative path for parsing |
| `mtimeMs` | For incremental sync detection |
| `media.metadata.asin` | Primary key for duplicate detection |
| `media.metadata.title` | Book title |
| `media.metadata.authorName` | Author (display name from ABS) |
| `media.metadata.seriesName` | Series name |
| `media.size` | File size for stats |
| `media.duration` | Duration for stats |

**Response (Minified):**

When `minified=1`, response is smaller but still includes all key fields we need.

---

### GET /api/items/{id}

Get detailed information about a single library item.

**Use Case:** Optional - Get full details for a specific book.

```bash
curl "https://abs.example.com/api/items/li_xxx?expanded=1" \
  -H "Authorization: Bearer <TOKEN>"
```

**Note:** We typically don't need this - the items list has enough info.

---

### POST /api/libraries/{id}/scan

Triggers a library scan to detect new/changed files.

**Use Case:** `mamfast abs-import` - After moving files, trigger ABS to pick them up.

```bash
# Normal scan (detects changes)
curl -X POST "https://abs.example.com/api/libraries/lib_xxx/scan" \
  -H "Authorization: Bearer <TOKEN>"

# Force rescan all items
curl -X POST "https://abs.example.com/api/libraries/lib_xxx/scan?force=1" \
  -H "Authorization: Bearer <TOKEN>"
```

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `force` | Binary | 0 | Force rescan all items (1=true) |

**Response:**

```
200 OK
```

**Important Notes:**
- Scan runs asynchronously - endpoint returns immediately
- No response body - just 200 OK
- Use `force=0` for normal post-import scans (faster)
- Requires admin user permissions

---

### GET /api/search/books

Search for book metadata from external providers (Audible, Google, iTunes, etc.).

**Use Case:** `mamfast abs-resolve-asins` - Resolve unknown ASINs via Audible search.

```bash
# Search Audible for a book by title and author
curl "https://abs.example.com/api/search/books?title=Wizards%20First%20Rule&author=Terry%20Goodkind&provider=audible" \
  -H "Authorization: Bearer <TOKEN>"
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `title` | String | Yes | Book title to search for |
| `author` | String | No | Author name (improves results) |
| `provider` | String | No | Metadata provider: `audible`, `google`, `itunes`, `openlibrary`, `fantlab` |

**Response (Audible Provider):**

```json
[
  {
    "title": "Wizard's First Rule",
    "subtitle": null,
    "author": "Terry Goodkind",
    "narrator": "Sam Tsoutsouvas",
    "publisher": "Brilliance Audio",
    "publishedYear": "2008",
    "description": "The masterpiece that started...",
    "cover": "https://m.media-amazon.com/images/I/...",
    "asin": "B002V0QK4C",
    "series": [
      {
        "series": "Sword of Truth",
        "sequence": "1"
      }
    ],
    "language": "English",
    "duration": 34200,
    "region": "us",
    "rating": "4.5"
  }
]
```

**Key Fields for MAMFast:**

| Field | Use |
|-------|-----|
| `asin` | **Primary** - The ASIN we need for unknown resolution |
| `title` | For fuzzy matching against folder name |
| `author` | For fuzzy matching confidence |
| `series` | Array with series name and sequence number |
| `narrator` | Secondary metadata |

**Provider Notes:**
- `audible` - Returns ASIN, best for audiobook resolution
- `google` - Returns ISBN, no ASIN
- Other providers vary in metadata completeness

**Important Notes:**
- ABS proxies the request to the external provider
- No separate Audible credentials needed - uses ABS's built-in support
- Results may be cached by ABS
- Rate limits handled by ABS

---

## Response Schemas

### Library Object

```python
@dataclass
class AbsLibrary:
    id: str                    # "lib_c1u6t4p45c35rf0nzd"
    name: str                  # "Audiobooks"
    folders: list[AbsFolder]   # Library folders
    mediaType: str             # "book" or "podcast"
    provider: str              # "audible", "google", etc.
```

### Library Item Object

```python
@dataclass
class AbsLibraryItem:
    id: str                    # "li_8gch9ve09orgn4fdz8"
    path: str                  # Container path
    relPath: str               # Relative path
    mtimeMs: int               # Modification time (ms)
    isMissing: bool            # File missing on disk
    isInvalid: bool            # No media files found
    media: AbsBookMedia        # Book metadata
```

### Book Media Object

```python
@dataclass
class AbsBookMedia:
    metadata: AbsBookMetadata
    coverPath: str | None
    duration: float            # Seconds
    size: int                  # Bytes
```

### Book Metadata Object

```python
@dataclass
class AbsBookMetadata:
    title: str
    subtitle: str | None
    authorName: str            # Display name
    narratorName: str | None
    seriesName: str | None
    asin: str | None           # Key for duplicate detection
    isbn: str | None
    publishedYear: str | None
    genres: list[str]
```

---

## Error Handling

### HTTP Status Codes

| Code | Meaning | MAMFast Action |
|------|---------|----------------|
| 200 | Success | Continue |
| 400 | Bad Request | Log error, abort |
| 401 | Unauthorized | Check API token |
| 403 | Forbidden | Check user permissions |
| 404 | Not Found | Library/item doesn't exist |
| 500 | Server Error | Retry with backoff |

### Retry Strategy

```python
from mamfast.utils.retry import retry_with_backoff, NETWORK_EXCEPTIONS

@retry_with_backoff(max_attempts=3, base_delay=2.0, exceptions=NETWORK_EXCEPTIONS)
def get_library_items(self, library_id: str) -> list[dict]:
    resp = self._client.get(f"/api/libraries/{library_id}/items", params={"limit": 0})
    resp.raise_for_status()
    return resp.json()["results"]
```

---

## Rate Limiting

ABS doesn't have strict rate limiting, but be respectful:

- **Index operations:** One full sync at a time
- **Scan triggers:** Wait for scan to complete before triggering another
- **Batch mode:** Use `trigger_scan: batch` to consolidate scans

### Recommended Delays

| Operation | Delay |
|-----------|-------|
| Between API calls | 100ms (httpx default) |
| After scan trigger | 2-5 seconds |
| Retry after error | Exponential backoff (2s, 4s, 8s) |

---

## Example: Full Index Flow

```python
from mamfast.abs_client import AbsClient

client = AbsClient(
    base_url="https://audiobookshelf.domain.com",
    api_token=os.environ["AUDIOBOOKSHELF_API_KEY"],
)

# 1. Validate connection
user_info = client.authorize()
print(f"Connected as: {user_info['user']['username']}")
print(f"Server version: {user_info['serverSettings']['version']}")

# 2. Get libraries
libraries = client.get_libraries()
for lib in libraries:
    if lib["mediaType"] == "book":
        print(f"Library: {lib['name']} ({lib['id']})")
        print(f"  Root: {lib['folders'][0]['fullPath']}")

# 3. Fetch all items
items = client.get_library_items("lib_c1u6t4p45c35rf0nzd")
print(f"Found {len(items)} items")

# 4. Extract data for index
for item in items:
    asin = item["media"]["metadata"].get("asin")
    title = item["media"]["metadata"]["title"]
    author = item["media"]["metadata"]["authorName"]
    path = item["path"]  # Container path - needs mapping!
    print(f"  {asin or 'NO-ASIN'}: {title} by {author}")
```

---

## Path Mapping Example

ABS runs in Docker, so paths are container paths. We need to map them:

```yaml
# config.yaml
audiobookshelf:
  docker_mode: true
  path_map:
    - container: "/audiobooks"
      host: "/mnt/user/data/audio/audiobooks"
```

```python
def abs_path_to_host(container_path: str, path_map: list[dict]) -> str:
    """Convert ABS container path to host path."""
    # Sort by length (longest prefix first)
    sorted_maps = sorted(path_map, key=lambda m: len(m["container"]), reverse=True)

    for mapping in sorted_maps:
        if container_path.startswith(mapping["container"]):
            return container_path.replace(
                mapping["container"],
                mapping["host"],
                1  # Only first occurrence
            )

    # No mapping found - return as-is (non-Docker mode)
    return container_path
```

---

## References

- [Audiobookshelf API Docs](https://api.audiobookshelf.org/) (Note: May be outdated)
- [Audiobookshelf GitHub](https://github.com/advplyr/audiobookshelf)
- [MAMFast Import Plan](./AUDIOBOOKSHELF_IMPORT_PLAN.md)
