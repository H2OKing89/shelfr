# Torrent Search API

## Overview

**Endpoint:** `/tor/js/loadSearchJSONbasic.php`

This API endpoint searches torrents on MyAnonamouse (MAM) and returns results in JSON format. It's the backend used by the main site search feature and can accept input via multiple content types.

## Request Methods & Content Types

The endpoint accepts requests via:

- **GET** query parameters
- **POST** with `application/x-www-form-urlencoded`
- **POST** with `application/json`
- **POST** with `application/xml`
- **POST** with `multipart/form-data`

## Request Parameters

### Optional Display Parameters

| Parameter | Data type | Description |
| --- | --- | --- |
| `description` | empty | If set, includes the full description field for each torrent |
| `dlLink` | blank | If set, returns hash for download link (prepend `/tor/download.php/` to use). Alternatively, use session cookie with `/tor/download.php?tid=<id>` |
| `isbn` | set | If set, returns the ISBN field (often blank) |
| `mediaInfo` | set | If set, returns key parts of mediaInfo |
| `my_snatched` | exists | If set, limits results to only torrents you have snatched |
| `perpage` | int | Number of results to return. Range: 5 to 1000 (default varies) |
| `thumbnail` | boolean | If set to `"true"`, includes thumbnail/cover image URLs |

### Required Search Parameters (tor object)

The `tor` object contains the core search criteria:

| Parameter | Data type | Description |
| --- | --- | --- |
| `text` | string | Text to search for |
| `srchIn` | array | Fields to search in. Options: `title`, `author`, `narrator`, `description`, `filenames`, `fileTypes`, `series`, `tags` |
| `searchType` | enum | Type of torrent activity to search. Options: `all`, `active` (1+ seeders), `inactive` (0 seeders), `fl` (Freeleech), `fl-VIP` (Freeleech or VIP), `VIP`, `nVIP` (not VIP), `nMeta` (missing metadata) |
| `searchIn` | string | Always set to `"torrents"` for standard torrent search |
| `cat` | array | List of category IDs (integers) to filter by. Use `"0"` for all categories |
| `main_cat` | array | Main category IDs: `13` = AudioBooks, `14` = E-Books, `15` = Musicology, `16` = Radio |
| `browse_lang` | array | List of language IDs (integers) to filter by |
| `browseFlagsHideVsShow` | string | Flag display preference (typically `"0"`) |
| `startDate` | date | Earliest torrent date (YYYY-MM-DD format or unix timestamp). Inclusive |
| `endDate` | date | Latest torrent date (YYYY-MM-DD format or unix timestamp). Exclusive |
| `hash` | hex string | Search by torrent file hash (hexadecimal) |
| `id` | int | Return data for a single torrent ID only |
| `sortType` | enum | Sort order for results. See [Sort Types](#sort-types) below |
| `startNumber` | int | Number of entries to skip (for pagination) |

### Sort Types

| Value | Description |
| --- | --- |
| `titleAsc` | By title, ascending order |
| `titleDesc` | By title, descending order |
| `fileAsc` | By number of files, ascending |
| `fileDesc` | By number of files, descending |
| `sizeAsc` | By torrent size, ascending |
| `sizeDesc` | By torrent size, descending |
| `seedersAsc` | By seeders, ascending |
| `seedersDesc` | By seeders, descending |
| `leechersAsc` | By leechers, ascending |
| `leechersDesc` | By leechers, descending |
| `snatchedAsc` | By times snatched, ascending |
| `snatchedDesc` | By times snatched, descending |
| `dateAsc` | By date added, ascending |
| `dateDesc` | By date added, descending |
| `bmkaAsc` | By bookmark date, ascending (may return odd results if not bookmarked) |
| `bmkaDesc` | By bookmark date, descending (may return odd results if not bookmarked) |
| `reseedAsc` | By reseed request date, ascending (may return odd results if no reseed request) |
| `reseedDesc` | By reseed request date, descending (may return odd results if no reseed request) |
| `categoryAsc` | By category ID ascending, then title ascending |
| `categoryDesc` | By category ID descending, then title ascending |
| `random` | Random order |
| `default` | Server default: if text search present, by relevance weight DESC then ID descending; if searchIn is 'myReseed' or 'allReseed', same as reseedAsc; if searchIn is Bookmarks, same as bmkaDesc; otherwise same as dateDesc |

## Example Requests

### JSON Format (Recommended)

```json
{
  "tor": {
    "text": "collection cookbooks food test kitchen",
    "srchIn": [
      "title",
      "author",
      "narrator"
    ],
    "searchType": "all",
    "searchIn": "torrents",
    "cat": ["0"],
    "browseFlagsHideVsShow": "0",
    "startDate": "",
    "endDate": "",
    "hash": "",
    "sortType": "default",
    "startNumber": "0"
  },
  "thumbnail": "true"
}
```

### URL Encoded Format (GET)

```text
tor[cat][]=0&tor[sortType]=default&tor[browseStart]=true&tor[startNumber]=0&bannerLink&bookmarks&dlLink&description&tor[text]=mp3%20m4a
```

### Search AudioBooks Only

```json
{
  "tor": {
    "text": "fantasy audiobook",
    "srchIn": ["title", "author", "narrator"],
    "searchType": "all",
    "searchIn": "torrents",
    "main_cat": ["13"],
    "cat": ["0"],
    "sortType": "dateDesc",
    "startNumber": "0",
    "perpage": "50"
  },
  "description": "",
  "dlLink": ""
}
```

### Search by ASIN or ISBN

```json
{
  "tor": {
    "text": "B003ZWFO7E",
    "srchIn": ["title"],
    "searchType": "all",
    "searchIn": "torrents",
    "sortType": "default",
    "startNumber": "0"
  },
  "isbn": ""
}
```

## Response Format

The API returns a JSON object with a `data` array containing torrent results and metadata.

### Response Root Level

| Parameter | Data type | Description |
| --- | --- | --- |
| `data` | array | List of torrent objects (see below) |
| `total` | int | Number of results loaded by the server (may increase as you request later results) |
| `total_found` | int | Total results found for the search (may be much larger than data array if using pagination) |

### Torrent Object (data[])

| Parameter | Data type | Description |
| --- | --- | --- |
| `id` | int | Torrent ID. Access via `/t/{id}` |
| `name` | string | Torrent name/title |
| `title` | string | Alternative title field |
| `language` | int | Internal language ID |
| `lang_code` | string | 3-letter ISO language code |
| `main_cat` | int | Main category: 13 = AudioBooks, 14 = E-Books, 15 = Musicology, 16 = Radio |
| `category` | int | Specific category ID |
| `catname` | string | Category display name (e.g., "Audiobooks - Urban Fantasy") |
| `cat` | string | HTML display for category (formatted with user preferences) |
| `size` | string | Torrent size in bytes |
| `numfiles` | int | Number of files in torrent |
| `filetype` | string | Space-separated file types (e.g., "m4a mp3") |
| `filetypes` | string | Concatenated string of file types |
| `seeders` | int | Current number of seeders |
| `leechers` | int | Current number of leechers |
| `times_completed` | int | Number of users who have fully snatched |
| `comments` | int | Number of user comments |
| `vip` | boolean | Whether torrent is VIP exclusive |
| `free` | boolean | Whether torrent is Freeleech |
| `fl_vip` | boolean | Whether torrent is Freeleech AND/OR VIP |
| `browseflags` | bitfield | Bit field of tags and flags (see MAM documentation) |
| `tags` | string | Space-separated tags |
| `author_info` | string | JSON object: `{"<id>": "<name>", ...}` |
| `narrator_info` | string | JSON object: `{"<id>": "<name>", ...}` |
| `series_info` | string | JSON object: `{"<id>": ["<series_name>", "<volume_numbers>"], ...}` |
| `added` | datetime | UTC datetime torrent was uploaded |
| `bookmarked` | datetime or null | UTC datetime bookmarked by user, or null if not bookmarked |
| `owner` | int | User ID of uploader |
| `owner_name` | string | Username of uploader |
| `my_snatched` | boolean | Whether you have snatched this torrent (5-20 min delay) |
| `personal_freeleech` | boolean | Whether you purchased personal freeleech for this (5-20 min delay) |
| `dl` | string | User-specific hash for downloading. Append to `/tor/download.php/` |
| `w` | string | Weight/relevance score for text search |
| `description` | string | Full BBCode description (if `description` parameter set) |
| `thumbnail` | string | URL to cover/thumbnail image (if `thumbnail` parameter set) |

## Example Response

```json
{
  "data": [
    {
      "id": "273200",
      "language": "1",
      "main_cat": "13",
      "category": "108",
      "catname": "Audiobooks - Urban Fantasy",
      "size": "6324306932",
      "numfiles": "149",
      "vip": "0",
      "free": "0",
      "fl_vip": "0",
      "name": "Love at Stake series",
      "w": "5527",
      "tags": "Love at Stake series unabridged 64–128 Kbps Fiction Paranormal Romance Fantasy Vampires Bestseller mp3 m4a",
      "author_info": "{\"8234\": \"Kerrelyn Sparks\"}",
      "narrator_info": "{\"1\": \"Abby Craden\", \"1220\": \"Deanna Hurst\", \"13716\": \"Lorna Bennett\"}",
      "series_info": "{\"67\": [\"Love at Stake\", \"01-16, 13.5\"]}",
      "filetype": "m4a mp3",
      "description": "[size=4][b]Love at Stake - Books 1–16 & 13.5 (Unabridged)[/b][/size]...",
      "dl": "k0S0Bxpdds1Q1vAvRI,ILhtA5UvR,qwPautWQCqh6,...",
      "bookmarked": null,
      "seeders": "5",
      "leechers": "2",
      "times_completed": "1250",
      "added": "2018-03-15 12:34:56",
      "owner": "12345",
      "owner_name": "uploader_username",
      "my_snatched": false,
      "personal_freeleech": false,
      "comments": "8"
    }
  ],
  "total": "1",
  "total_found": "1"
}
```

## Usage Tips

### Pagination

Use `startNumber` to paginate through results:

```json
{
  "tor": {
    "text": "audiobook",
    "startNumber": "0",
    "perpage": "50"
  }
}
```

Then for next page:

```json
{
  "tor": {
    "text": "audiobook",
    "startNumber": "50",
    "perpage": "50"
  }
}
```

### Downloading Torrents

Two methods:

1. **With session cookie** (if authenticated):
   - Use `/tor/download.php?tid={id}` where `{id}` is the torrent ID

2. **Without session** (public downloads):
   - Append the `dl` hash to `/tor/download.php/`
   - Full URL: `/tor/download.php/{dl_hash}`

### Parsing JSON Fields

Several fields return JSON strings that need to be parsed:

- `author_info` → `{"id": "name", ...}`
- `narrator_info` → `{"id": "name", ...}`
- `series_info` → `{"series_id": ["series_name", "volumes"], ...}`

### Size Field Format

The `size` field is returned as a string (bytes). Convert to human-readable format as needed (1 GB = 1,073,741,824 bytes).

### Tag Interpretation

The `tags` field is a space-separated string of keywords. Some common tags:

- **Format**: `mp3`, `m4a`, `m4b`, `flac`, `ogg`
- **Bitrate**: `64 Kbps`, `128 Kbps`, `192 Kbps`, `320 Kbps`, `lossless`
- **Content**: `Unabridged`, `Abridged`, `Full Cast`, `Dramatized`
- **Status**: `Bestseller`, `Award Winner`, `Series`

### Filtering Best Results

For audiobooks, a good search combines:

```json
{
  "tor": {
    "text": "your search term",
    "srchIn": ["title", "author", "narrator"],
    "searchType": "active",
    "main_cat": ["13"],
    "sortType": "seedersDesc",
    "perpage": "50"
  },
  "description": "",
  "dlLink": ""
}
```

This filters to:

- AudioBooks main category
- Active torrents (has seeders)
- Sort by seeders descending (most popular first)
- Include description and download links
