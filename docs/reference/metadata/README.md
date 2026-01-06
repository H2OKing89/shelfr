<div align="center">

# Metadata Reference

**Comprehensive documentation for shelfr's metadata system**

Naming conventions · Architecture · Data flow

---

[Naming](#naming-system) · [Architecture](#architecture) · [Key Concepts](#key-concepts) · [Glossary](#glossary)

</div>

<br>

## Overview

Shelfr's metadata system transforms raw audiobook data from various sources into clean, standardized outputs for MAM uploads and Audiobookshelf imports.

> [!TIP]
> **New to this system?** Your entry point depends on your focus — see [Where to Start](#where-to-start) below.

---

## Where to Start

<table>
<tr>
<td width="33%" valign="top">

### Working on Naming

<sub>Folder/file names, truncation, ASIN tags</sub>

1. Start → [NAMING.md](naming/NAMING.md)
2. Then → [NAMING_PIPELINE.md](naming/NAMING_PIPELINE.md)
3. Then → [NAMING_RULES.md](naming/NAMING_RULES.md)

</td>
<td width="33%" valign="top">

### Working on Architecture

<sub>Sidecars, metadata merging, providers</sub>

1. Start → [architecture/README.md](architecture/README.md)
2. Then → [03-plugin-architecture.md](architecture/03-plugin-architecture.md)
3. Then → [07-content-flags.md](architecture/07-content-flags.md)

</td>
<td width="34%" valign="top">

### Working on Providers

<sub>Hardcover, local flags, new sources</sub>

1. Start → [providers/README.md](providers/README.md)
2. Then → [providers/hardcover.md](providers/hardcover.md)
3. Then → [07-content-flags.md](architecture/07-content-flags.md)

</td>
</tr>
</table>

---

## System Diagram

```bash
┌─────────────────────────────────────────────────────────────────────────────┐
│                         METADATA SYSTEM OVERVIEW                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   SOURCES                                                                   │
│   ├── Libation                                                              │
│   ├── Audnex                                                                │
│   ├── MediaInfo                                                             │
│   └── abs_sidecar                                                           │
│            │                                                                │
│            ▼                                                                │
│   PIPELINE                                                                  │
│   Providers ──▶ Aggregator ──▶ CanonicalMetadata ──▶ Cleaning             │
│                                        │                                    │
│                                        ├──▶ Exporters (OPF / JSON)         │
│                                        │                                    │
│                                        └──▶ Naming View (NormalizedBook)   │
│                                             └──▶ folder/file naming        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

<sub>* Target: NormalizedBook becomes a derived view from CanonicalMetadata</sub>

---

## Documentation Structure

| Folder | Purpose | Entry Point |
|:-------|:--------|:------------|
| [`naming/`](naming/README.md) | MAM folder/file naming rules, phrase removal, truncation | [NAMING.md](naming/NAMING.md) |
| [`architecture/`](architecture/README.md) | Provider/exporter plugin system, refactoring plan | [README.md](architecture/README.md) |

---

## Key Concepts

### NormalizedBook vs CanonicalMetadata

| Model | Purpose | Location | Used By |
|:------|:--------|:---------|:--------|
| `NormalizedBook` | Fixes Audible's title/subtitle swaps for naming | `models.py` | Naming pipeline (MAM paths) |
| `CanonicalMetadata` | Full metadata for sidecars and aggregation | `metadata/schemas/` | OPF/JSON exporters, providers |

<details>
<summary><strong>View relationship diagram</strong></summary>

<br>

```bash
Providers → Aggregator → CanonicalMetadata → Cleaning
                                  │
                                  ├──▶ Exporters (OPF/JSON)
                                  │
                                  └──▶ Naming View (NormalizedBook) → paths
```

</details>

<br>

### Normalization vs Cleaning

<table>
<tr>
<th width="50%">Normalization</th>
<th width="50%">Cleaning</th>
</tr>
<tr>
<td>Fix structural issues</td>
<td>Apply naming.json rules</td>
</tr>
<tr>
<td>

- Title/subtitle swaps
- Series extraction
- Position parsing

</td>
<td>

- Phrase removal
- Text normalization
- Format stripping

</td>
</tr>
</table>

<details>
<summary><strong>Post-refactor vision</strong></summary>

<br>

> [!IMPORTANT]
> Both models remain with separate responsibilities:

- **NormalizedBook** stays intentionally minimal (title, subtitle, series, authors) for fast path building
- **CanonicalMetadata** carries the full payload for rich sidecars and provider merging
- Cleaning rules live in `cleaning.py` and are reused by both exporters and naming
- **Target direction:** `NormalizedBook` becomes a derived naming view built from `CanonicalMetadata`

</details>

---

### Data Flow

```bash
┌──────────────┐     ┌────────────┐     ┌───────────────────┐     ┌──────────┐     ┌────────────┐
│  Providers   │────▶│ Aggregator │────▶│ CanonicalMetadata │────▶│ Cleaning │────▶│ Exporters  │
│ (fetch data) │     │  (merge)   │     │ (single truth)    │     │ (rules)  │     │ (output)   │
└──────────────┘     └────────────┘     └───────────────────┘     └──────────┘     └────────────┘
                                                                        │
                                                                        ▼
                                                              ┌─────────────────┐
                                                              │  Naming View    │
                                                              │ (NormalizedBook)│
                                                              │ → folder/file   │
                                                              └─────────────────┘
```

See [architecture/](architecture/README.md) for the full pipeline design.

---

### Cleaning Pipeline

> [!NOTE]
> Shared cleaning rules apply to **all outputs**: folder names, file names, sidecars, BBCode.

| Field | Cleaning Applied |
|:------|:-----------------|
| **Title** | Remove `(Unabridged)`, `A Novel`, format indicators |
| **Authors** | Remove translators/editors, transliterate Japanese names |
| **Series** | Remove format indicators, normalize position |
| **Subtitle** | Remove text redundant with title/series |

<kbd>See</kbd> [naming/NAMING_RULES.md](naming/NAMING_RULES.md) for the full rule set.

---

## Quick Links

<details open>
<summary><strong>Naming System</strong></summary>

<br>

| Document | Description |
|:---------|:------------|
| [Overview](naming/NAMING.md) | Architecture diagram, key concepts |
| [Pipeline](naming/NAMING_PIPELINE.md) | 5-stage processing flow |
| [Rules](naming/NAMING_RULES.md) | `naming.json` configuration |
| [Schemas](naming/NAMING_FOLDER_FILE_SCHEMAS.md) | Output formats, truncation |
| [Audnex Normalization](naming/NAMING_AUDNEX_NORMALIZATION.md) | Title/subtitle fix logic |
| [Implementation](naming/NAMING_IMPLEMENTATION.md) | Phases, testing, changelog |

</details>

<details open>
<summary><strong>Architecture</strong></summary>

<br>

| Document | Description |
|:---------|:------------|
| [Current State Audit](architecture/01-current-state-audit.md) | What exists today |
| [Recommendations](architecture/02-recommendations.md) | Phased refactoring plan |
| [Plugin Architecture](architecture/03-plugin-architecture.md) | Provider/exporter design |
| [Future-Proofing](architecture/04-future-proofing.md) | Caching, events, versioning |
| [Implementation Checklist](architecture/05-implementation-checklist.md) | Task list |

</details>

---

## Related Documents

| Document | Location | Purpose |
|:---------|:---------|:--------|
| JSON Sidecar Discovery | [`docs/implementation/json-sidecar-discovery.md`](../../implementation/json-sidecar-discovery.md) | Active feature planning |
| Migration Backlog | [`docs/implementation/MIGRATION_BACKLOG.md`](../../implementation/MIGRATION_BACKLOG.md) | Tech debt tracking |
| naming.json Config | [`config/naming.json`](../../../config/naming.json) | Phrase removal rules |

---

## Glossary

<details>
<summary><strong>Click to expand glossary</strong></summary>

<br>

<dl>
  <dt><strong>ABS</strong></dt>
  <dd>Audiobookshelf — self-hosted audiobook server</dd>

  <dt><strong>abs_sidecar</strong></dt>
  <dd>Existing <code>metadata.json</code> from Audiobookshelf (user-corrected override provider)</dd>

  <dt><strong>Aggregator</strong></dt>
  <dd>System component that merges and prioritizes metadata from multiple providers</dd>

  <dt><strong>ASIN</strong></dt>
  <dd>Amazon Standard Identification Number (10-char alphanumeric)</dd>

  <dt><strong>Audnex</strong></dt>
  <dd>API service providing normalized Audible metadata</dd>

  <dt><strong>CanonicalMetadata</strong></dt>
  <dd>Single source of truth for all metadata fields</dd>

  <dt><strong>Exporter</strong></dt>
  <dd>Module that renders metadata to an output format</dd>

  <dt><strong>Libation</strong></dt>
  <dd>Desktop app for downloading Audible audiobooks</dd>

  <dt><strong>MAM</strong></dt>
  <dd>MyAnonaMouse — private audiobook tracker</dd>

  <dt><strong>MediaInfo</strong></dt>
  <dd>Command-line utility for extracting audio format, duration, and codec info</dd>

  <dt><strong>NormalizedBook</strong></dt>
  <dd>Corrected title/subtitle/series for naming</dd>

  <dt><strong>OPF</strong></dt>
  <dd>Open Packaging Format — ebook/audiobook metadata standard</dd>

  <dt><strong>Provider</strong></dt>
  <dd>Module that fetches metadata from a source</dd>

  <dt><strong>Sidecar</strong></dt>
  <dd>Metadata file placed alongside audiobook files</dd>
</dl>

</details>

---

<div align="center">

<sub>Part of the <a href="../../../README.md">Shelfr</a> project</sub>

</div>
