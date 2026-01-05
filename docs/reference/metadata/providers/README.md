# Metadata Providers

This folder contains documentation for individual metadata providers - external data sources that feed the metadata aggregation system.

## Provider Categories

### Network Providers (API-based)

| Provider | Status | Priority | Data Provided |
|----------|--------|----------|---------------|
| [Audnex](audnex.md) | ✅ Production | 60 | Title, authors, narrators, series, chapters, `isAdult`, `formatType` |
| [Hardcover](hardcover.md) | 📋 Planned | 70 | Genres, moods, content warnings, ratings |

### Local Providers (File/Cache-based)

| Provider | Status | Priority | Data Provided |
|----------|--------|----------|---------------|
| MediaInfo | ✅ Production | 90 | Audio format, bitrate, duration, codec |
| AbsSidecar | 📋 Planned | 80 | Pre-existing `metadata.json` from ABS |
| LocalFlags | 📋 Planned | 95 | User-curated content flags (JSONL import) |

## Provider Priority

Higher priority = wins conflicts at same confidence level.

**Precedence numbers:** Higher number = wins conflicts.

```text
LocalFlags (95)     ← Manual overrides always win
  ↓
MediaInfo (90)      ← Local file analysis
  ↓
AbsSidecar (80)     ← Existing ABS metadata
  ↓
Hardcover (70)      ← Network: rich content warnings
  ↓
Audnex (60)         ← Network: audiobook-specific (foundation)
```

> **Note:** Audnex is the **foundation provider** — the only source for narrator data,
> chapter timing, and audiobook runtime. Other providers supplement, not replace.

## Adding a New Provider

See [Plugin Architecture](../architecture/03-plugin-architecture.md) for the `MetadataProvider` protocol and registration system.

Key requirements:

1. Implement `MetadataProvider` protocol
2. Define `provider_name`, `priority`, `provides_fields`
3. Register with `ProviderRegistry`
4. Add tests with mock data
5. Document in this folder

## Related Documentation

- [Plugin Architecture](../architecture/03-plugin-architecture.md) - Provider protocol and aggregation
- [Content Flags](../architecture/07-content-flags.md) - Flag resolution and precedence
- [Implementation Checklist](../architecture/05-implementation-checklist.md) - Phase tracking
