# LibationCli Reference

**Version:** 12.8.0

LibationCli is the command-line interface for Libation, an Audible audiobook manager and liberator.

## Quick Reference

```bash
# Help
libationcli --help
libationcli scan --help          # Verb-specific help

# Scan
libationcli scan                 # Scan all libraries
libationcli scan nickname1 nickname2  # Scan specific accounts

# Liberate
libationcli liberate             # Liberate all books and PDFs
libationcli liberate -p          # PDFs only
libationcli liberate -f          # Force re-liberate
libationcli liberate --license /path/to/license.lic
libationcli liberate --license - < /path/to/license.lic

# Convert
libationcli convert              # Convert all m4b to mp3

# Settings
libationcli get-setting          # List all settings
libationcli get-setting -b       # Bare output (no table)
libationcli get-setting FileDownloadQuality  # Specific setting

# Override settings at runtime
libationcli liberate B017V4IM1G -o FileDownloadQuality=Normal
libationcli liberate B017V4IM1G -o FileDownloadQuality=normal -o UseWidevine=true -o Request_xHE_AAC=true -f

# Export
libationcli export -p "/path/to/library.json" -j   # JSON
libationcli export -p "/path/to/library.csv" -c    # CSV
libationcli export -p "/path/to/library.xlsx" -x   # Excel

# Set download status (based on whether audio files exist)
libationcli set-status -d        # Mark found files as 'Downloaded'
libationcli set-status -n        # Mark missing files as 'Not Downloaded'
libationcli set-status -d -n     # Both

# Get license without downloading
libationcli get-license B017V4IM1G

# Copy database to PostgreSQL
libationcli copydb -c "my postgres connection string"
```

---

## Commands

### scan
Scan your Audible library for new books.

```bash
LibationCli scan [--libationFiles PATH] [-o KEY=VALUE] [ACCOUNTS...]
```

| Option | Description |
|--------|-------------|
| `--libationFiles` | Path to Libation Files directory |
| `-o, --override` | Configuration setting override: `[SettingName]="Value"` |
| `ACCOUNTS` | (positional) Optional: user ID or nicknames of accounts to scan |

**Examples:**
```bash
# Scan all accounts
LibationCli scan

# Scan specific account
LibationCli scan "my-account-nickname"
```

---

### liberate
Download and decrypt audiobooks. Default: download and decrypt all un-liberated titles and download PDFs.

```bash
LibationCli liberate [-p] [-f] [-l LICENSE] [--libationFiles PATH] [-o KEY=VALUE] [ASINS...]
```

| Option | Description |
|--------|-------------|
| `-p, --pdf` | Only download PDFs (default: false) |
| `-f, --force` | Force re-download even if already liberated (default: false) |
| `-l, --license` | License file from `get-license` command (file path or `-` for stdin) |
| `--libationFiles` | Path to Libation Files directory |
| `-o, --override` | Configuration setting override |
| `ASINS` | (positional) Optional: product IDs of specific books to liberate |

**Examples:**
```bash
# Liberate all un-liberated books
LibationCli liberate

# Liberate specific book by ASIN
LibationCli liberate B0DK9T5P28

# Force re-download
LibationCli liberate -f B0DK9T5P28

# Only download PDFs
LibationCli liberate -p
```

---

### convert
Convert M4B (AAC) files to MP3 format.

```bash
LibationCli convert [--libationFiles PATH] [-o KEY=VALUE] [ASINS...]
```

| Option | Description |
|--------|-------------|
| `--libationFiles` | Path to Libation Files directory |
| `-o, --override` | Configuration setting override |
| `ASINS` | (positional) Optional: product IDs of books to convert |

---

### export
Export library data to file.

```bash
LibationCli export -p PATH {-x|-c|-j} [--libationFiles PATH] [-o KEY=VALUE]
```

| Option | Description |
|--------|-------------|
| `-p, --path` | **Required.** Path to save exported file |
| `-x, --xlsx` | Export as Microsoft Excel Spreadsheet |
| `-c, --csv` | Export as Comma-separated values |
| `-j, --json` | Export as JavaScript Object Notation |
| `--libationFiles` | Path to Libation Files directory |
| `-o, --override` | Configuration setting override |

**Examples:**
```bash
# Export to Excel
LibationCli export -p /data/library.xlsx -x

# Export to JSON
LibationCli export -p /data/library.json -j

# Export to CSV
LibationCli export -p /data/library.csv -c
```

---

### search
Search for books in your library using Lucene query syntax.

```bash
LibationCli search [-n COUNT] [--libationFiles PATH] [-o KEY=VALUE] QUERY
```

| Option | Description |
|--------|-------------|
| `-n` | Number of search results per page (default: 10) |
| `--libationFiles` | Path to Libation Files directory |
| `-o, --override` | Configuration setting override |
| `QUERY` | **Required.** Lucene search string |

**Examples:**
```bash
# Search by title
LibationCli search "Sword Art Online"

# Search by author
LibationCli search "author:Reki Kawahara"

# Show more results
LibationCli search -n 50 "fantasy"
```

---

### get-license
Get license information for a specific book (useful for manual decryption).

```bash
LibationCli get-license [--libationFiles PATH] [-o KEY=VALUE] ASIN
```

| Option | Description |
|--------|-------------|
| `--libationFiles` | Path to Libation Files directory |
| `-o, --override` | Configuration setting override |
| `ASIN` | **Required.** Product ID of book to request license for |

**Example:**
```bash
LibationCli get-license B0DK9T5P28
```

---

### set-status
Set download statuses throughout library based on whether each book's audio file can be found.

**Note:** Must include at least one flag: `--downloaded` or `--not-downloaded`.
- **Downloaded (`-d`)**: If the audio file can be found, set status to 'Downloaded'
- **Not Downloaded (`-n`)**: If the audio file cannot be found, set status to 'Not Downloaded'
- **UI vs CLI**: UI operates on visible books with prompt; CLI operates on full library without prompt

```bash
LibationCli set-status {-d|-n} [-f] [--libationFiles PATH] [-o KEY=VALUE] [ASINS...]
```

| Option | Description |
|--------|-------------|
| `-d, --downloaded` | Set download status to 'Downloaded' |
| `-n, --not-downloaded` | Set download status to 'Not Downloaded' |
| `-f, --force` | Set status regardless of whether audio file exists |
| `--libationFiles` | Path to Libation Files directory |
| `-o, --override` | Configuration setting override |
| `ASINS` | (positional) Optional: product IDs of books to update |

**Examples:**
```bash
# Mark files that exist as 'Downloaded'
LibationCli set-status -d

# Mark missing files as 'Not Downloaded'
LibationCli set-status -n

# Both operations at once
LibationCli set-status -d -n

# Force mark specific book as not downloaded
LibationCli set-status -n -f B0DK9T5P28
```

---

### get-setting
List current settings and their values.

```bash
LibationCli get-setting [-l] [-b] [--libationFiles PATH] [-o KEY=VALUE] [SETTING_NAMES...]
```

| Option | Description |
|--------|-------------|
| `-l, --listEnumValues` | List all possible values for enum types |
| `-b, --bare` | Print bare list without table decoration |
| `--libationFiles` | Path to Libation Files directory |
| `-o, --override` | Configuration setting override |
| `SETTING_NAMES` | (positional) Optional: specific setting names to display |

**Examples:**
```bash
# Show all settings
LibationCli get-setting

# Show enum options
LibationCli get-setting -l

# Show specific setting
LibationCli get-setting FileTemplate FolderTemplate
```

---

### copydb
Copy local SQLite database to PostgreSQL.

```bash
LibationCli copydb -c CONNECTION_STRING [--libationFiles PATH] [-o KEY=VALUE]
```

| Option | Description |
|--------|-------------|
| `-c, --connectionString` | PostgreSQL database connection string |
| `--libationFiles` | Path to Libation Files directory |
| `-o, --override` | Configuration setting override |

---

### version
Display version information.

```bash
LibationCli version
```

---

### help
Display help for a specific command.

```bash
LibationCli help [COMMAND]
```

---

## Configuration Settings

Settings can be overridden at runtime using `-o` or `--override`:

```bash
LibationCli liberate -o DecryptToLossy=True -o LameBitrate=256
```

### Boolean Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `AllowLibationFixup` | True | Allow Libation to fix audio issues |
| `AutoDownloadEpisodes` | False | Auto-download podcast episodes |
| `AutoScan` | True | Automatically scan on startup |
| `CombineNestedChapterTitles` | False | Merge nested chapter titles |
| `CreateCueSheet` | True | Generate .cue files |
| `DecryptToLossy` | False | Convert to MP3 instead of M4B |
| `DownloadClipsBookmarks` | False | Download clips and bookmarks |
| `DownloadCoverArt` | True | Download cover images |
| `DownloadEpisodes` | False | Download podcast episodes |
| `ImportEpisodes` | False | Import podcast episodes to library |
| `ImportPlusTitles` | True | Import Audible Plus titles |
| `LameConstantBitrate` | True | Use constant bitrate for MP3 |
| `LameDownsampleMono` | True | Downsample stereo to mono |
| `LameMatchSourceBR` | True | Match source bitrate |
| `LameTargetBitrate` | True | Use target bitrate setting |
| `MergeOpeningAndEndCredits` | False | Merge intro/outro credits |
| `MoveMoovToBeginning` | True | Move moov atom for streaming |
| `OverwriteExisting` | True | Overwrite existing files |
| `Request_xHE_AAC` | False | Request xHE-AAC codec |
| `RequestSpatial` | False | Request spatial audio |
| `RetainAaxFile` | False | Keep original AAX file |
| `SaveMetadataToFile` | True | Save .metadata.json files |
| `SplitFilesByChapter` | False | Create separate files per chapter |
| `StripAudibleBrandAudio` | False | Remove Audible intro/outro audio |
| `StripUnabridged` | True | Remove "Unabridged" from titles |
| `UseWidevine` | True | Use Widevine DRM decryption |

### String/Path Settings

| Setting | Description |
|---------|-------------|
| `Books` | Output directory for liberated books |
| `InProgress` | Temporary directory for downloads |
| `FileTemplate` | Template for audio filenames |
| `FolderTemplate` | Template for folder structure |
| `ChapterFileTemplate` | Template for chapter filenames |
| `ChapterTitleTemplate` | Template for chapter titles |

### Numeric Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `LameBitrate` | 320 | MP3 bitrate (kbps) |
| `LameVBRQuality` | 0 | VBR quality (0-9, 0=best) |
| `DownloadSpeedLimit` | 0 | Download speed limit (0=unlimited) |

### Enum Settings

| Setting | Options | Default |
|---------|---------|---------|
| `BadBook` | Ask, Abort, Retry, Ignore | Retry |
| `FileDownloadQuality` | High, Normal | High |
| `LameEncoderQuality` | High, Standard, Fast | High |
| `LogLevel` | Verbose, Debug, Information, Warning, Error, Fatal | Information |
| `MaxSampleRate` | Hz_7350 to Hz_96000 | Hz_48000 |
| `ClipsBookmarksFileFormat` | CSV, Xlsx, Json | Json |
| `CreationTime` | File, Published, Added | File |
| `LastWriteTime` | File, Published, Added | File |

---

## Template Variables

Templates support the following placeholders:

| Variable | Description |
|----------|-------------|
| `<id>` | ASIN/product ID |
| `<title>` | Full title |
| `<audible title>` | Audible title (may differ from title) |
| `<title short>` | Shortened title |
| `<series>` | Series name |
| `<series#>` | Series number (with format: `<series#[00.##]>`) |
| `<year>` | Publication year |
| `<first author>` | Primary author name |
| `<authors>` | All authors |
| `<narrators>` | Narrator names |
| `<ch#>` | Chapter number (with format: `<ch# 0>`) |
| `<ch title>` | Chapter title |

### Conditional Blocks

```
<if series->...content...<-if series>
```

Content only appears if book has a series.

### Example Templates

**FolderTemplate:**
```
<first author>/<if series-><series>/<-if series><audible title> vol_<series#[00.##]> (<year>) (<first author>) {ASIN.<id>} [H2OKing]
```

**FileTemplate:**
```
<audible title> vol_<series#[00.##]> (<year>) (<first author>) {ASIN.<id>}
```

---

## Docker Usage

When running in Docker, the CLI is located at `/libation/LibationCli`:

```bash
# Scan library
docker exec -it Libation /libation/LibationCli scan

# Liberate all books
docker exec -it Libation /libation/LibationCli liberate

# Liberate specific ASIN
docker exec -it Libation /libation/LibationCli liberate B0DK9T5P28

# Export library to JSON
docker exec -it Libation /libation/LibationCli export -p /data/library.json -j
```

The default Docker container also includes `liberate.sh` which wraps common operations.

---

## Debugging & Diagnostics

### Export Library JSON for Analysis

The JSON export contains comprehensive book metadata that's useful for debugging status issues:

```bash
# Export library to JSON (inside container)
docker exec Libation /libation/LibationCli export -p /tmp/lib.json -j

# Analyze on host
docker exec Libation cat /tmp/lib.json | python -c "
import json, sys
from collections import Counter
d = json.load(sys.stdin)
print(f'Total books: {len(d)}')
statuses = Counter(b.get('BookStatus', 'Unknown') for b in d)
for status, count in statuses.most_common():
    print(f'  {status}: {count}')
"
```

### Key JSON Fields

| Field | Description |
|-------|-------------|
| `AudibleProductId` | ASIN (NOT `Asin` - that field is null) |
| `BookStatus` | `Liberated`, `NotLiberated`, `Error` |
| `PdfStatus` | `Liberated`, `NotLiberated`, or empty |
| `LastDownloaded` | Timestamp when actually downloaded (null = never) |
| `ContentType` | Usually `Product` |
| `AuthorNames` | Author string (may be Japanese characters) |
| `SeriesNames` | Series name |
| `SeriesOrder` | Series position (e.g., "17 : Mushoku Tensei") |

### Understanding Book Status

```bash
# Show status breakdown
docker exec Libation cat /tmp/lib.json | python -c "
import json, sys
d = json.load(sys.stdin)

liberated = [b for b in d if b.get('BookStatus') == 'Liberated']
not_liberated = [b for b in d if b.get('BookStatus') == 'NotLiberated']
actually_downloaded = [b for b in d if b.get('LastDownloaded')]

print(f'BookStatus=Liberated: {len(liberated)}')
print(f'BookStatus=NotLiberated: {len(not_liberated)}')
print(f'Actually downloaded (LastDownloaded set): {len(actually_downloaded)}')
print(f'Marked Liberated but never downloaded: {len(liberated) - len([b for b in liberated if b.get(\"LastDownloaded\")])}')
"
```

**Important:** `BookStatus=Liberated` does NOT mean the file exists on disk. Check `LastDownloaded` for actual download confirmation. Books can be marked "Liberated" but have `LastDownloaded=null` if:
- Files were moved/deleted after liberation
- Status was manually set
- Files exist in a different location

### List Books Needing Liberation

```bash
# Show books that need to be downloaded
docker exec Libation cat /tmp/lib.json | python -c "
import json, sys
d = json.load(sys.stdin)
not_lib = [b for b in d if b.get('BookStatus') == 'NotLiberated']
print(f'{len(not_lib)} books need liberation:')
for b in not_lib[:20]:
    print(f\"  • {b.get('Title')[:50]} ({b.get('AudibleProductId')})\")
"
```

### Check Docker Volume Mounts

```bash
# See where Libation stores files
docker inspect Libation --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}'

# Typical output:
# /mnt/user/data/audio/audiobook-import -> /data
# /mnt/cache/appdata/Libation -> /config
```

The `Books` setting inside Libation (usually `/data`) maps to the host path shown above.

---

## MAMFast Integration Notes

### How Discovery Works

MAMFast's `discover` command scans `library_root` for `.m4b` files with `{ASIN.XXXXXXXXXX}` in the path. The flow is:

1. **Libation scans** Audible → adds to database (status: `NotLiberated`)
2. **Libation liberates** → downloads & decrypts to `Books` directory (status: `Liberated`)
3. **MAMFast discovers** → finds new files in `library_root`
4. **MAMFast processes** → stage → metadata → torrent → upload

### Common Issues

| Symptom | Cause | Solution |
|---------|-------|----------|
| "No new releases found" | `library_root` empty | Run `liberate` to download books |
| Books marked Liberated but not on disk | Files moved to ABS | Normal if you moved them |
| Wrong `library_root` | Config mismatch | Check `docker inspect` mounts |

### Recommended Workflow

```bash
# 1. Scan Audible for new books
mamfast scan
# or: docker exec Libation /libation/LibationCli scan

# 2. Liberate (download) new books
docker exec Libation /libation/LibationCli liberate

# 3. Run MAMFast pipeline on downloaded books
mamfast run

# 4. Move processed files to Audiobookshelf (manual or automated)
```

### Future Enhancement Ideas

1. **Auto-liberate integration**: MAMFast could call `liberate` before `discover`
2. **Status sync**: Query Libation JSON to show pending downloads in MAMFast
3. **Direct ABS import**: After upload, automatically move to ABS and trigger scan
4. **Libation webhook**: React to Libation liberation events

