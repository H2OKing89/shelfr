# Metadata Reference

> Comprehensive documentation for shelfr's metadata system: naming conventions, architecture, and data flow.

---

## Overview

Shelfr's metadata system transforms raw audiobook data from various sources into clean, standardized outputs for MAM uploads and Audiobookshelf imports.

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Metadata System Overview                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────────┐     ┌──────────────────┐     ┌─────────────────────────┐ │
│   │   Sources   │────▶│   Normalization  │────▶│       Outputs           │ │
│   │             │     │                  │     │                         │ │
│   │ • Libation  │     │ • NormalizedBook │     │ • MAM folder/file names │ │
│   │ • Audnex    │     │ • CanonicalMeta  │     │ • metadata.opf          │ │
│   │ • MediaInfo │     │                  │     │ • metadata.json         │ │
│   │ • ABS local │     │                  │     │ • MAM JSON payload      │ │
│   └─────────────┘     └──────────────────┘     └─────────────────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Documentation Structure

| Folder | Purpose | Start Here |
|--------|---------|------------|
| [naming/](naming/README.md) | MAM folder/file naming rules, phrase removal, truncation | [NAMING.md](naming/NAMING.md) |
| [architecture/](architecture/README.md) | Provider/exporter plugin system, refactoring plan | [README.md](architecture/README.md) |

---

## Key Concepts

### NormalizedBook vs CanonicalMetadata

| Model | Purpose | Location | Used By |
|-------|---------|----------|---------|
| `NormalizedBook` | Fixes Audible's title/subtitle swaps | `models.py` | Naming pipeline (MAM paths) |
| `CanonicalMetadata` | Full metadata for sidecars | `opf/schemas.py` | OPF/JSON exporters |

**Relationship:**

```text
Audnex API Response
       │
       ├──→ NormalizedBook ──→ MAM folder/file naming
       │
       └──→ CanonicalMetadata ──→ OPF sidecar
                              ──→ JSON sidecar (planned)
```

Both models solve the same problem (Audible's inconsistent metadata) but for different outputs:

- **NormalizedBook**: Minimal fields for path building
- **CanonicalMetadata**: Full fields for rich metadata sidecars

### Data Flow

```text
┌──────────────┐     ┌────────────┐     ┌───────────────────┐     ┌───────────┐     ┌───────────┐
│  Providers   │────▶│ Aggregator │────▶│ CanonicalMetadata │────▶│ Cleaning  │────▶│ Exporters │
│ (fetch data) │     │  (merge)   │     │ (single truth)    │     │(normalize)│     │ (output)  │
└──────────────┘     └────────────┘     └───────────────────┘     └───────────┘     └───────────┘
```

See [architecture/](architecture/README.md) for the full pipeline design.

### Cleaning Pipeline

Shared cleaning rules apply to ALL outputs (folder names, file names, sidecars, BBCode):

| Field | Cleaning |
|-------|----------|
| **Title** | Remove "(Unabridged)", "A Novel", format indicators |
| **Authors** | Remove translators/editors, transliterate Japanese names |
| **Series** | Remove format indicators, normalize position |
| **Subtitle** | Remove text redundant with title/series |

See [naming/NAMING_RULES.md](naming/NAMING_RULES.md) for the full rule set.

---

## Quick Links

### Naming System

- [Overview](naming/NAMING.md) - Architecture diagram, key concepts
- [Pipeline](naming/NAMING_PIPELINE.md) - 5-stage processing flow
- [Rules](naming/NAMING_RULES.md) - `naming.json` configuration
- [Schemas](naming/NAMING_FOLDER_FILE_SCHEMAS.md) - Output formats, truncation
- [Audnex Normalization](naming/NAMING_AUDNEX_NORMALIZATION.md) - Title/subtitle fix logic
- [Implementation](naming/NAMING_IMPLEMENTATION.md) - Phases, testing, changelog

### Architecture

- [Current State Audit](architecture/01-current-state-audit.md) - What exists today
- [Recommendations](architecture/02-recommendations.md) - Phased refactoring plan
- [Plugin Architecture](architecture/03-plugin-architecture.md) - Provider/exporter design
- [Future-Proofing](architecture/04-future-proofing.md) - Caching, events, versioning
- [Implementation Checklist](architecture/05-implementation-checklist.md) - Task list

---

## Related Documents

| Document | Location | Purpose |
|----------|----------|---------|
| JSON Sidecar Discovery | [docs/implementation/json-sidecar-discovery.md](../../implementation/json-sidecar-discovery.md) | Active feature planning |
| Migration Backlog | [docs/implementation/MIGRATION_BACKLOG.md](../../implementation/MIGRATION_BACKLOG.md) | Tech debt tracking |
| naming.json Config | [config/naming.json](../../../config/naming.json) | Phrase removal rules |

---

## Glossary

| Term | Definition |
|------|------------|
| **ABS** | Audiobookshelf - self-hosted audiobook server |
| **Aggregator** | System component that merges and prioritizes metadata from multiple providers |
| **ASIN** | Amazon Standard Identification Number (10-char alphanumeric) |
| **Audnex** | API service providing normalized Audible metadata |
| **CanonicalMetadata** | Single source of truth for all metadata fields |
| **Exporter** | Module that renders metadata to an output format |
| **Libation** | Desktop app for downloading Audible audiobooks |
| **MAM** | MyAnonaMouse - private audiobook tracker |
| **MediaInfo** | Command-line utility for extracting audio format, duration, and codec info |
| **NormalizedBook** | Corrected title/subtitle/series for naming |
| **OPF** | Open Packaging Format - ebook/audiobook metadata standard |
| **Provider** | Module that fetches metadata from a source |
| **Sidecar** | Metadata file placed alongside audiobook files |
