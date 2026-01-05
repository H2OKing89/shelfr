# Metadata Providers

This folder contains documentation for individual metadata providers - external data sources that feed the metadata aggregation system.

## Provider Categories

### Network Providers (API-based)

| Provider | Status | Priority | Data Provided |
|----------|--------|----------|---------------|
| [Audnex](../architecture/03-plugin-architecture.md) | ✅ Production | 70 | Title, authors, narrators, series, `isAdult`, `formatType` |
| [Hardcover](hardcover.md) | 📋 Planned | 60 | Genres, moods, content warnings, ratings |

### Local Providers (File/Cache-based)

| Provider | Status | Priority | Data Provided |
|----------|--------|----------|---------------|
| MediaInfo | ✅ Production | 90 | Audio format, bitrate, duration, codec |
| AbsSidecar | 📋 Planned | 80 | Pre-existing `metadata.json` from ABS |
| LocalFlags | 📋 Planned | 95 | User-curated content flags (JSONL import) |

## Provider Priority

Higher priority = checked first, wins conflicts at same confidence level.

```text
LocalFlags (95)     ← Manual overrides always win
  ↓
MediaInfo (90)      ← Local file analysis
  ↓
AbsSidecar (80)     ← Existing ABS metadata
  ↓
Audnex (70)         ← Network: audiobook-specific
  ↓
Hardcover (60)      ← Network: book metadata enrichment
```

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
