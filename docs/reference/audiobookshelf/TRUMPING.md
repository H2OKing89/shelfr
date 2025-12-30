# Trumping (Quality-Based Replacement) Plan

> **Document Version:** 1.5.0 | **Last Updated:** 2025-12-06 | **Status:** ✅ Implementation Complete

This document outlines the plan for implementing auto-replacement logic when importing higher-quality versions of audiobooks.

> **Scope:** Trumping applies to ABS import flow only - when a new version of an existing audiobook has objectively better quality. Trumping v1 compares **single-file** ABS imports only. Multi-file CD-style layouts are treated as separate works and are never auto-trumped.

---

## Current Behavior

| Scenario | Behavior |
|----------|----------|
| New book, no duplicate | Normal import |
| ASIN exists + `duplicate_policy=skip` | Skip import entirely |
| ASIN exists + `duplicate_policy=warn` | Import, log warning |
| ASIN exists + `duplicate_policy=overwrite` | Replace existing blindly |

### Problem: Blind Overwrite is Dangerous

Current `overwrite` policy replaces without quality comparison:
- Could replace 320kbps stereo with 64kbps mono (regression!)
- No audit trail - hard to recover if wrong choice made
- No intermediate option: "replace only if better"

---

## Core Philosophy

Three principles drive all trumping decisions:

1. **Safety First** – Never destroy data; always archive old files with reason sidecar
2. **Quality is Objective** – Format tier > bitrate > sample rate > chapters/stereo (tiebreakers)
3. **Configurable Aggression** – Let users control how eager trumping should be

**Decision: Trumping should be opt-in** with clear, auditable behavior:
- Default: disabled (preserve current behavior)
- When enabled: archive old version, never hard-delete
- Log every decision with full reasoning

---

## Key Assumptions & Constraints

| Assumption | Description | Impact if Violated |
|------------|-------------|-------------------|
| **Same ASIN required (v1)** | Trumping v1 only compares books with identical ASIN. See [Regional ASINs](#regional-asins) for future canonicalization. | Different content = different books, not trump candidates |
| **Single-file only (v1)** | Trumping v1 only applies to single-file audiobook layouts | Multi-file layouts skip trumping entirely |
| **Same language** | Must match language (abridged vs unabridged) | Language change = different book |
| **Same abridgement status** | Unabridged won't trump abridged or vice versa | User preference, not quality |
| **Similar duration** | Duration within ±10-25% tolerance | Truncated/extended = different content |
| **Archive filesystem accessible** | Archive root must be writable | Fall back to skip, log error |

### What Trumping is NOT

- **Cross-ASIN replacement** – Different ASINs are different books
- **Content normalization** – Not changing bit depth, channels, etc.
- **Metadata-only update** – This is about audio quality, not tags

### Regional ASINs

Audible uses **regional ASINs** – the same work can have different ASINs in different markets
(e.g. audible.com vs audible.co.uk).

To keep trumping deterministic and safe in v1:

- **Trumping only runs when `existing.asin == incoming.asin`.**
- Different ASINs are treated as different works, even if they represent the same title.
- Cross-region ASIN normalization is explicitly out-of-scope for the initial implementation.

This guarantees we never "merge" or auto-replace across potentially different editions /
recordings just because metadata *looks* similar.

> **See also:** [Regional ASINs & Canonical Identity (Future)](#regional-asins--canonical-identity-future) for the roadmap.

---

## Codebase Integration Notes

This section documents how trumping aligns with existing MAMFast patterns.

### Existing Components to Reuse

| Component | Location | Usage in Trumping |
|-----------|----------|-------------------|
| `AsinEntry` | `abs/asin.py` | Existing library item metadata - extend with quality fields |
| `extract_asin_from_mediainfo()` | `abs/asin.py` | Already probes audio files - extend to extract bitrate/etc. |
| `asin_exists()` | `abs/asin.py` | Duplicate detection - trumping hooks in here |
| `import_single()` | `abs/importer.py` | Main import flow - trumping inserts before duplicate handling |
| `AudiobookshelfImportSchema` | `schemas/config.py` | Parent schema - add `trumping: TrumpingSchema` field |
| `AUDIO_EXTENSIONS` | `abs/asin.py` | Consistent audio file detection |

### Schema Nesting Pattern

The existing codebase uses alias mapping for YAML `import:` → Python `import_settings`:

```python
# In schemas/config.py - AudiobookshelfSchema
import_settings: AudiobookshelfImportSchema = Field(
    default_factory=AudiobookshelfImportSchema,
    alias="import",  # YAML key is 'import', Python attr is 'import_settings'
    description="Import behavior settings",
)
```

Trumping schema nests inside `AudiobookshelfImportSchema`:

```python
# Add to AudiobookshelfImportSchema
trumping: TrumpingSchema = Field(
    default_factory=TrumpingSchema,
    description="Quality-based replacement settings",
)
```

### Mediainfo Integration

Existing `extract_asin_from_mediainfo()` parses mediainfo JSON output. For trumping, we extend this to extract quality metadata:

```python
# Relevant mediainfo JSON fields (from existing code analysis):
# - media.track[].Format         → "AAC LC" / "MPEG Audio"
# - media.track[].BitRate        → "128000" (bps)
# - media.track[].SamplingRate   → "44100"
# - media.track[].Channels       → "2"
# - media.track[].Duration       → "36000.123" (seconds)
# - media.track[].extra.asin     → ASIN (already extracted)
```

### Where Trumping Hooks In

In `import_single()`, trumping logic inserts **after** ASIN resolution but **before** the existing duplicate handling:

```python
# Current flow in import_single():
# 1. Parse folder name
# 2. Resolve ASIN (Phase 3+4+5)
# 3. >>> TRUMPING CHECK GOES HERE <<<
# 4. Check asin_exists() - existing duplicate handling
# 5. Enrich from Audnex
# 6. Build target path
# 7. Move files
```

---

## Trumping Decision Types

```python
from enum import Enum, auto

class TrumpDecision(Enum):
    """Outcome of comparing existing vs incoming audiobook quality."""

    KEEP_EXISTING = auto()     # Existing is equal or better → reject new
    KEEP_BOTH = auto()         # Tie or incomparable → keep both
    REPLACE_WITH_NEW = auto()  # New is strictly better → archive existing, import new
    REJECT_NEW = auto()        # New is strictly worse → skip import entirely
```

### Decision Mapping to Actions

| Decision | Action | Archive Old? | Import New? |
|----------|--------|--------------|-------------|
| `KEEP_EXISTING` | No change | No | No |
| `KEEP_BOTH` | Defer to `duplicate_policy` | Depends | Depends |
| `REPLACE_WITH_NEW` | Archive + import | Yes | Yes |
| `REJECT_NEW` | Skip | No | No |

---

## Quality Metadata

### TrumpableMeta Dataclass

Captures all quality-relevant attributes for comparison:

```python
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class TrumpableMeta:
    """Quality metadata for trumping comparison.

    All values extracted via mediainfo from audio files.
    Fields are intentionally optional - missing data shouldn't block import.
    """

    asin: str  # Required - primary identity

    # Format hierarchy: m4b > m4a > mp3 > flac (for audiobooks)
    # Note: For audiobooks, we deliberately rank FLAC below AAC/MP3 because of
    # size, chapter support, and app compatibility. This is opinionated but
    # matches this tool's focus on audiobook UX over raw signal quality.
    format: str | None = None  # "m4b", "m4a", "mp3", "flac"

    # Quality metrics
    bitrate_kbps: int | None = None      # e.g., 128, 256, 320
    sample_rate_hz: int | None = None    # e.g., 22050, 44100, 48000
    duration_sec: int | None = None      # Total duration for sanity checks

    # Tiebreakers (used when core metrics are equal)
    has_chapters: bool = False           # Embedded chapter markers
    is_stereo: bool = False              # True = stereo, False = mono

    # Identity guards (must match for trumping to apply)
    language: str | None = None          # ISO 639 code: "en", "de", etc.
    is_abridged: bool | None = None      # None = unknown
    narrator: str | None = None          # For multi-narrator comparison (future)

    # Source metadata
    source_path: Path | None = None      # For logging/debugging
    trusted_source: bool = False         # Future: trusted ripper/source flag

    @property
    def format_tier(self) -> int:
        """Return format preference tier (higher = better for audiobooks)."""
        tiers = {
            "m4b": 4,  # Native audiobook format, best support
            "m4a": 3,  # AAC without chapters
            "mp3": 2,  # Universal but older
            "flac": 1, # Lossless but huge, poor chapter support
            None: 0,   # Unknown format
        }
        return tiers.get(self.format, 0)
```

### Single-File Only (v1 Enforcement)

Trumping v1 is **only** applied to single-file audiobook layouts.

**Detection rule:**

- If a staging folder contains **more than one** audio file (as per `AUDIO_EXTENSIONS`),
  that folder is treated as a multi-file / CD-style layout.
- In that case, **trumping is skipped entirely** and normal `duplicate_policy`
  handling applies (no `TrumpDecision` is issued at all).

This keeps the comparison logic simple and avoids weird cases where we try to
infer "overall quality" from multiple disc-track files.

**Implementation:** The importer flow checks for multi-file layouts **before**
calling `decide_trump()`. If either the incoming or existing folder is multi-file,
trumping short-circuits and falls through to the existing `duplicate_policy` logic.

### Multi-File Detection Helper

```python
def is_multi_file_layout(folder: Path) -> bool:
    """Check if folder contains multiple audio files (CD-style layout).

    Returns True if trumping should be skipped for this folder.
    """
    from mamfast.abs.asin import AUDIO_EXTENSIONS

    audio_files = [
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
    ]
    return len(audio_files) > 1
```

### Extracting Metadata

```python
def extract_trumpable_meta(folder: Path, asin: str) -> TrumpableMeta:
    """Extract quality metadata from audio files in folder.

    Uses existing mediainfo infrastructure from abs/asin.py.
    Extends the pattern used by extract_asin_from_mediainfo().

    Falls back gracefully when metadata unavailable.

    Note: Caller should use is_multi_file_layout() first to skip trumping
    for multi-file layouts. This function still handles multi-file gracefully
    but the importer should short-circuit before calling decide_trump().
    """
    from mamfast.abs.asin import _get_mediainfo_binary, AUDIO_EXTENSIONS

    audio_files = sorted(
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
    )
    if not audio_files:
        return TrumpableMeta(asin=asin, source_path=folder)

    # v1 rule: only single-file layouts participate in trumping.
    # Caller should normally skip trumping for multi-file layouts using
    # is_multi_file_layout(). This fallback just returns minimal metadata
    # so decide_trump() behaves conservatively if it ever gets called.
    if len(audio_files) > 1:
        logger.debug(
            f"Multi-file layout ({len(audio_files)} files) - trumping disabled for {folder.name}"
        )
        return TrumpableMeta(
            asin=asin,
            source_path=folder,
            # No quality metrics → triggers KEEP_EXISTING fallback
        )

    # Single file - proceed with full metadata extraction
    probe_file = audio_files[0]

    # Reuse existing mediainfo binary detection
    binary = _get_mediainfo_binary()
    if binary is None:
        logger.warning("mediainfo not available, quality metadata unavailable")
        return TrumpableMeta(
            asin=asin,
            format=probe_file.suffix.lower().lstrip("."),
            source_path=folder,
        )

    # Run mediainfo (same pattern as extract_asin_from_mediainfo)
    try:
        result = subprocess.run(
            [binary, "--Output=JSON", str(probe_file)],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        data = json.loads(result.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError) as e:
        logger.debug("Failed to probe %s: %s", probe_file.name, e)
        return TrumpableMeta(
            asin=asin,
            format=probe_file.suffix.lower().lstrip("."),
            source_path=folder,
        )

    # Parse mediainfo JSON (structure: {"media": {"track": [...]}})
    tracks = data.get("media", {}).get("track", [])
    if isinstance(tracks, dict):
        tracks = [tracks]

    # Find audio track for quality metrics
    audio_track = next((t for t in tracks if t.get("@type") == "Audio"), {})
    general_track = next((t for t in tracks if t.get("@type") == "General"), {})

    return TrumpableMeta(
        asin=asin,
        format=probe_file.suffix.lower().lstrip("."),
        bitrate_kbps=_parse_bitrate(audio_track),
        sample_rate_hz=_parse_sample_rate(audio_track),
        duration_sec=_parse_duration(general_track),
        has_chapters=_detect_chapters(general_track),
        is_stereo=_parse_channels(audio_track) >= 2,
        language=audio_track.get("Language"),
        is_abridged=None,  # Difficult to detect automatically
        narrator=None,     # Would need metadata lookup
        source_path=folder,
    )


def _parse_bitrate(track: dict) -> int | None:
    """Parse bitrate from mediainfo track, converting to kbps."""
    # mediainfo returns BitRate in bps as string: "128000"
    raw = track.get("BitRate")
    if raw:
        try:
            return int(raw) // 1000
        except (ValueError, TypeError):
            pass
    return None


def _parse_sample_rate(track: dict) -> int | None:
    """Parse sample rate from mediainfo track."""
    raw = track.get("SamplingRate")
    if raw:
        try:
            return int(float(raw))
        except (ValueError, TypeError):
            pass
    return None


def _parse_duration(track: dict) -> int | None:
    """Parse duration from mediainfo track, converting to seconds."""
    raw = track.get("Duration")
    if raw:
        try:
            return int(float(raw))
        except (ValueError, TypeError):
            pass
    return None


def _parse_channels(track: dict) -> int:
    """Parse channel count from mediainfo track."""
    raw = track.get("Channels")
    if raw:
        try:
            return int(raw)
        except (ValueError, TypeError):
            pass
    return 1  # Default to mono if unknown


def _detect_chapters(track: dict) -> bool:
    """Detect if file has embedded chapters."""
    # Check for MenuCount or chapters in general track
    menu_count = track.get("MenuCount")
    if menu_count:
        try:
            return int(menu_count) > 0
        except (ValueError, TypeError):
            pass
    return False
```

---

## Configuration

### TrumpingSchema

> **Note on Schema vs Prefs:**
> - `TrumpingSchema` is the Pydantic configuration model, wired to YAML parsing
> - `TrumpPrefs` is a lightweight runtime dataclass derived from that schema
> - At runtime, config is parsed via `TrumpingSchema` and converted to `TrumpPrefs`
>   which gets passed into `decide_trump()` and `archive_existing()`

```yaml
# config.yaml
audiobookshelf:
  import:
    # ... existing settings (duplicate_policy, unknown_asin_policy, etc.) ...

    # Trumping: auto-replace when importing better quality versions
    trumping:
      # Master enable/disable
      enabled: false  # Default: off (opt-in feature)

      # How eager to replace existing content
      # - conservative: Only trump for major upgrades (format tier + significant bitrate)
      # - balanced: Trump for clear improvements (recommended when enabled)
      # - aggressive: Trump for any measurable improvement
      aggressiveness: balanced

      # Minimum bitrate improvement required for trumping (in kbps)
      # Only applies when format tier is equal
      # Set to 0 to allow any bitrate improvement
      min_bitrate_increase_kbps: 64

      # Chapter markers trump non-chaptered at same quality?
      prefer_chapters: true

      # Stereo trumps mono at same quality?
      prefer_stereo: true

      # Duration tolerance for sanity checks
      # Reject incoming if significantly shorter (truncated?)
      min_duration_ratio: 0.9   # Incoming must be >= 90% of existing duration
      # Keep both if incoming is significantly longer (different edition?)
      max_duration_ratio: 1.25  # Incoming > 125% triggers KEEP_BOTH

      # Where to archive replaced content (required if enabled)
      # Old files moved to: {archive_root}/{ASIN}/{timestamp}/
      archive_root: "/mnt/user/data/audio/archive"

      # Keep archive organized by year?
      archive_by_year: true
```

### Pydantic Schema

> **Implementation Note:** This schema nests inside `AudiobookshelfImportSchema`
> (which uses `alias="import"` to map YAML `import:` to `import_settings` attribute).
> See `schemas/config.py` for the pattern.

```python
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator

class TrumpAggressiveness(str, Enum):
    """How eager trumping should be."""

    CONSERVATIVE = "conservative"  # Major upgrades only
    BALANCED = "balanced"          # Clear improvements
    AGGRESSIVE = "aggressive"      # Any improvement


class TrumpingSchema(BaseModel):
    """Configuration for quality-based replacement.

    Nested under AudiobookshelfImportSchema.trumping in config.
    """

    enabled: bool = Field(default=False, description="Enable trumping")

    aggressiveness: str = Field(
        default="balanced",
        description="How eager to replace existing content"
    )

    min_bitrate_increase_kbps: int = Field(
        default=64,
        ge=0,
        description="Minimum bitrate improvement for trumping"
    )

    prefer_chapters: bool = Field(
        default=True,
        description="Chapters trump non-chaptered at same quality"
    )

    prefer_stereo: bool = Field(
        default=True,
        description="Stereo trumps mono at same quality"
    )

    min_duration_ratio: float = Field(
        default=0.9,
        ge=0.5,
        le=1.0,
        description="Minimum duration ratio (incoming/existing) - reject if below"
    )

    max_duration_ratio: float = Field(
        default=1.25,
        ge=1.0,
        le=2.0,
        description="Maximum duration ratio - keep both if exceeded"
    )

    archive_root: str | None = Field(
        default=None,
        description="Where to archive replaced content"
    )

    archive_by_year: bool = Field(
        default=True,
        description="Organize archive by year"
    )

    @field_validator("aggressiveness")
    @classmethod
    def validate_aggressiveness(cls, v: str) -> str:
        """Validate aggressiveness is a recognized value."""
        valid = {"conservative", "balanced", "aggressive"}
        if v.lower() not in valid:
            raise ValueError(f"Invalid aggressiveness '{v}'. Must be one of: {valid}")
        return v.lower()

    @field_validator("archive_root")
    @classmethod
    def validate_archive_root_absolute(cls, v: str | None) -> str | None:
        """Ensure archive_root is absolute when provided."""
        if v is not None and v.strip():
            if not v.startswith("/"):
                raise ValueError(
                    f"archive_root must be an absolute path (start with /), got: {v}"
                )
            return v.rstrip("/")  # Normalize: remove trailing slash
        return v

    @model_validator(mode="after")
    def validate_archive_required_when_enabled(self) -> "TrumpingSchema":
        """Ensure archive_root is set when trumping is enabled."""
        if self.enabled and (not self.archive_root or not self.archive_root.strip()):
            raise ValueError("archive_root is required when trumping is enabled")
        return self
```

### TrumpPrefs (Runtime Dataclass)

`TrumpPrefs` is a lightweight runtime dataclass derived from `TrumpingSchema`.
Config is parsed via `TrumpingSchema` and converted to `TrumpPrefs` which gets
passed into `decide_trump()` and `archive_existing()`.

```python
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class TrumpPrefs:
    """Runtime preferences for trumping, derived from TrumpingSchema.

    All fields have defaults matching TrumpingSchema so TrumpPrefs() works
    in tests without requiring full config.
    """

    enabled: bool = False
    aggressiveness: TrumpAggressiveness = TrumpAggressiveness.BALANCED
    min_bitrate_increase_kbps: int = 64
    prefer_chapters: bool = True
    prefer_stereo: bool = True
    min_duration_ratio: float = 0.9
    max_duration_ratio: float = 1.25
    archive_root: Path | None = None
    archive_by_year: bool = True

    # Future: canonical ASIN prefs (v1 uses defaults)
    canonical_asin_strategy: str = "none"  # "none" | "preferred_market"
    canonical_preferred_market: str = "us"
    canonical_search_markets: tuple[str, ...] = ("us", "uk", "au")

    @classmethod
    def from_schema(cls, schema: TrumpingSchema) -> "TrumpPrefs":
        """Convert Pydantic schema to runtime prefs."""
        return cls(
            enabled=schema.enabled,
            aggressiveness=TrumpAggressiveness(schema.aggressiveness),
            min_bitrate_increase_kbps=schema.min_bitrate_increase_kbps,
            prefer_chapters=schema.prefer_chapters,
            prefer_stereo=schema.prefer_stereo,
            min_duration_ratio=schema.min_duration_ratio,
            max_duration_ratio=schema.max_duration_ratio,
            archive_root=Path(schema.archive_root) if schema.archive_root else None,
            archive_by_year=schema.archive_by_year,
        )
```

### Interaction with `duplicate_policy`

When `trumping.enabled = true` and a duplicate ASIN is detected:

1. **Trumping runs first.**
2. The result controls behavior:

   | Trump Decision | Action | `duplicate_policy` consulted? |
   |----------------|--------|-------------------------------|
   | `REPLACE_WITH_NEW` | Archive old, import new | No |
   | `KEEP_EXISTING` | Skip import | No |
   | `REJECT_NEW` | Skip import | No |
   | `KEEP_BOTH` | Fall back to `duplicate_policy` | **Yes** |

**Practical implications:**

- When trumping is enabled, `duplicate_policy=overwrite` is **strongly discouraged**
  and is only consulted in `KEEP_BOTH` cases (identity mismatch, duration variance, etc.).
- `duplicate_policy=skip` + trumping enabled is a safe default:
  trumping can still replace on clear upgrades, everything else is skipped.
- Future versions may reject `duplicate_policy=overwrite` at config-parse time when
  trumping is enabled.

---

## Decision Tree

### Main Comparison Function

```python
def decide_trump(
    existing: TrumpableMeta,
    incoming: TrumpableMeta,
    prefs: TrumpPrefs,
) -> tuple[TrumpDecision, str]:
    """Compare existing vs incoming quality and decide action.

    Returns:
        Tuple of (decision, reason_string)
    """
    # ─────────────────────────────────────────────────────────────────────
    # Stage 1: Identity Guards (must be same "book")
    # ─────────────────────────────────────────────────────────────────────
    if existing.asin != incoming.asin:
        return TrumpDecision.KEEP_BOTH, "Different ASIN - not comparable"

    if existing.language and incoming.language:
        if existing.language != incoming.language:
            return TrumpDecision.KEEP_BOTH, f"Language mismatch: {existing.language} vs {incoming.language}"

    if existing.is_abridged is not None and incoming.is_abridged is not None:
        if existing.is_abridged != incoming.is_abridged:
            return TrumpDecision.KEEP_BOTH, "Abridgement status differs"

    # ─────────────────────────────────────────────────────────────────────
    # Stage 1.5: Duration Sanity Check (catch truncated/extended versions)
    # ─────────────────────────────────────────────────────────────────────
    if existing.duration_sec and incoming.duration_sec:
        ratio = incoming.duration_sec / existing.duration_sec

        if ratio < prefs.min_duration_ratio:
            return TrumpDecision.REJECT_NEW, f"Incoming significantly shorter ({ratio:.0%} of existing) - possibly truncated"

        if ratio > prefs.max_duration_ratio:
            return TrumpDecision.KEEP_BOTH, f"Incoming significantly longer ({ratio:.0%} of existing) - possibly different edition"

    # ─────────────────────────────────────────────────────────────────────
    # Stage 2: Format Tier (m4b > m4a > mp3 > flac for audiobooks)
    # Note: FLAC ranked last intentionally - see Appendix for rationale
    # ─────────────────────────────────────────────────────────────────────
    existing_tier = existing.format_tier
    incoming_tier = incoming.format_tier

    if incoming_tier > existing_tier:
        return TrumpDecision.REPLACE_WITH_NEW, f"Format upgrade: {existing.format} → {incoming.format}"

    if incoming_tier < existing_tier:
        return TrumpDecision.REJECT_NEW, f"Format downgrade: {existing.format} → {incoming.format}"

    # ─────────────────────────────────────────────────────────────────────
    # Stage 3: Bitrate Comparison (when format tiers equal)
    # ─────────────────────────────────────────────────────────────────────
    if existing.bitrate_kbps and incoming.bitrate_kbps:
        delta = incoming.bitrate_kbps - existing.bitrate_kbps

        if delta >= prefs.min_bitrate_increase_kbps:
            return TrumpDecision.REPLACE_WITH_NEW, f"Bitrate upgrade: {existing.bitrate_kbps}→{incoming.bitrate_kbps} kbps (+{delta})"

        if delta <= -prefs.min_bitrate_increase_kbps:
            return TrumpDecision.REJECT_NEW, f"Bitrate downgrade: {existing.bitrate_kbps}→{incoming.bitrate_kbps} kbps ({delta})"

    # ─────────────────────────────────────────────────────────────────────
    # Stage 4: Sample Rate (when bitrates comparable)
    # ─────────────────────────────────────────────────────────────────────
    if existing.sample_rate_hz and incoming.sample_rate_hz:
        if incoming.sample_rate_hz > existing.sample_rate_hz:
            return TrumpDecision.REPLACE_WITH_NEW, f"Sample rate upgrade: {existing.sample_rate_hz}→{incoming.sample_rate_hz} Hz"

        if incoming.sample_rate_hz < existing.sample_rate_hz:
            # Sample rate downgrade alone isn't worth rejecting
            pass  # Continue to tiebreakers

    # ─────────────────────────────────────────────────────────────────────
    # Stage 5: Tiebreakers (when core metrics equal)
    # ─────────────────────────────────────────────────────────────────────

    # Chapter markers are valuable for navigation
    if prefs.prefer_chapters:
        if incoming.has_chapters and not existing.has_chapters:
            return TrumpDecision.REPLACE_WITH_NEW, "Has chapters (existing does not)"

    # Stereo provides better listening experience
    if prefs.prefer_stereo:
        if incoming.is_stereo and not existing.is_stereo:
            return TrumpDecision.REPLACE_WITH_NEW, "Stereo (existing is mono)"

    # ─────────────────────────────────────────────────────────────────────
    # Stage 6: No Clear Winner
    # ─────────────────────────────────────────────────────────────────────
    # If core quality metrics (format, bitrate, sample rate) are missing or
    # equal, and tiebreakers do not clearly favor the incoming version, the
    # decision defaults to KEEP_EXISTING for safety.
    return TrumpDecision.KEEP_EXISTING, "No quality improvement detected"
```

### Aggressiveness Modifiers

```python
def adjust_for_aggressiveness(
    decision: TrumpDecision,
    reason: str,
    prefs: TrumpPrefs,
) -> tuple[TrumpDecision, str]:
    """Modify decision based on aggressiveness setting."""

    match prefs.aggressiveness:
        case TrumpAggressiveness.CONSERVATIVE:
            # Only allow REPLACE_WITH_NEW for major upgrades
            if decision == TrumpDecision.REPLACE_WITH_NEW:
                if "Format upgrade" not in reason:
                    # Demote to KEEP_EXISTING unless format tier changed
                    return TrumpDecision.KEEP_EXISTING, f"Conservative mode: {reason} (not sufficient)"

        case TrumpAggressiveness.AGGRESSIVE:
            # Convert KEEP_EXISTING to REPLACE_WITH_NEW for any tiebreaker win
            if decision == TrumpDecision.KEEP_EXISTING:
                # Check if incoming has any advantage at all
                # (This would require re-checking tiebreakers without prefs filter)
                pass  # Keep as-is for now

    return decision, reason
```

---

## Archive Behavior

### Archive Structure

```
{archive_root}/
├── 2025/                          # If archive_by_year enabled
│   └── B0DXXXXXXXXX/              # ASIN
│       └── 2025-07-15T14-30-00/   # ISO timestamp (filesystem-safe)
│           ├── Author - Title.m4b
│           ├── cover.jpg
│           └── .mamfast_trump.json  # Sidecar with reason
└── B0DYYYYYYYY/                   # If archive_by_year disabled
    └── 2025-07-15T16-45-00/
        └── ...
```

### Trump Sidecar Format

```json
{
  "schema_version": "1.0",
  "archived_at": "2025-12-06T14:30:00Z",
  "reason": "Format upgrade: mp3 → m4b",
  "decision": "REPLACE_WITH_NEW",
  "existing_meta": {
    "asin": "B0DXXXXXXXXX",
    "format": "mp3",
    "bitrate_kbps": 128,
    "sample_rate_hz": 44100,
    "duration_sec": 36000,
    "has_chapters": false,
    "is_stereo": false,
    "source_path": "/audiobooks/Author/Title/old.mp3"
  },
  "incoming_meta": {
    "asin": "B0DXXXXXXXXX",
    "format": "m4b",
    "bitrate_kbps": 256,
    "sample_rate_hz": 44100,
    "duration_sec": 36120,
    "has_chapters": true,
    "is_stereo": true,
    "source_path": "/staging/NewRip/book.m4b"
  },
  "config": {
    "aggressiveness": "balanced",
    "min_bitrate_increase_kbps": 64,
    "prefer_chapters": true,
    "prefer_stereo": true,
    "min_duration_ratio": 0.9,
    "max_duration_ratio": 1.25
  }
}
```

### Archive Function

Instead of moving individual files, the importer moves the **entire existing
book folder** into the archive path. This keeps the operation as atomic as
possible and avoids partially-archived states if something goes wrong.

```python
def archive_existing(
    existing_path: Path,
    existing_meta: TrumpableMeta,
    incoming_meta: TrumpableMeta,
    decision: TrumpDecision,
    reason: str,
    prefs: TrumpPrefs,
    *,
    dry_run: bool = False,
) -> Path | None:
    """Move existing book folder to archive with trump sidecar.

    Moves the ENTIRE folder atomically to avoid partial archive states.

    Args:
        existing_path: Current location of existing book folder
        existing_meta: Quality metadata of existing files
        incoming_meta: Quality metadata of incoming files
        decision: The trump decision made
        reason: Human-readable reason string
        prefs: Trumping preferences
        dry_run: If True, log but don't actually move

    Returns:
        Archive destination path, or None if dry_run
    """
    if not prefs.archive_root:
        raise TrumpingError("archive_root required for trumping")

    # Build archive path
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")

    if prefs.archive_by_year:
        year = datetime.now(UTC).strftime("%Y")
        archive_dest = prefs.archive_root / year / existing_meta.asin / timestamp
    else:
        archive_dest = prefs.archive_root / existing_meta.asin / timestamp

    if dry_run:
        logger.info(f"[DRY RUN] Would archive {existing_path} → {archive_dest}")
        return None

    # Create parent directory (archive_dest itself will be the moved folder)
    archive_parent = archive_dest.parent
    archive_parent.mkdir(parents=True, exist_ok=True)

    # Atomically move the entire folder
    # This avoids partial-archive states if something fails mid-operation
    shutil.move(str(existing_path), str(archive_dest))

    # Write trump sidecar inside the archived folder
    sidecar = archive_dest / ".mamfast_trump.json"
    sidecar_data = {
        "schema_version": "1.0",
        "archived_at": datetime.now(UTC).isoformat(),
        "reason": reason,
        "decision": decision.name,
        "existing_meta": _meta_to_dict(existing_meta),
        "incoming_meta": _meta_to_dict(incoming_meta),
        "config": {
            "aggressiveness": prefs.aggressiveness.value,
            "min_bitrate_increase_kbps": prefs.min_bitrate_increase_kbps,
            "prefer_chapters": prefs.prefer_chapters,
            "prefer_stereo": prefs.prefer_stereo,
            "min_duration_ratio": prefs.min_duration_ratio,
            "max_duration_ratio": prefs.max_duration_ratio,
        },
    }
    sidecar.write_text(json.dumps(sidecar_data, indent=2))

    logger.info(f"Archived {existing_path} → {archive_dest}")
    return archive_dest
```

---

## Integration Points

### Handling Multiple Existing Entries

> **Note:** The current `build_asin_index()` in `abs/asin.py` stores only the **first**
> occurrence of each ASIN (`dict[str, AsinEntry]`). For v1 trumping, this is sufficient.
> If we later need to handle multiple copies, we'd change to `dict[str, list[AsinEntry]]`.

For v1, we assume one entry per ASIN (current behavior). The trumping check compares incoming against that single existing entry.

### Importer Flow Modification

Trumping integrates into `import_single()` in `abs/importer.py`. The actual signature is:

```python
def import_single(
    staging_folder: Path,
    library_root: Path,
    asin_index: dict[str, AsinEntry],
    *,
    abs_client: AbsClient | None = None,
    abs_search_confidence: float = 0.75,
    staging_root: Path | None = None,
    duplicate_policy: str = "skip",
    unknown_asin_policy: UnknownAsinPolicy = UnknownAsinPolicy.IMPORT,
    quarantine_path: Path | None = None,
    # NEW: Add trumping prefs
    trump_prefs: TrumpPrefs | None = None,
    dry_run: bool = False,
) -> ImportResult:
```

Trumping inserts **after** ASIN resolution (Phase 3/4/5) but **before** the existing duplicate handling:

```python
    # ... existing ASIN resolution code ...

    # Still no ASIN → delegate to unknown ASIN handler
    if not asin:
        ctx = classify_unknown_asin(staging_folder, parsed)
        return handle_unknown_asin(...)

    # ─────────────────────────────────────────────────────────────────────
    # NEW: Trumping check BEFORE existing duplicate handling
    # ─────────────────────────────────────────────────────────────────────
    is_dup, existing_path = asin_exists(asin_index, asin)

    if is_dup and trump_prefs and trump_prefs.enabled:
        existing_entry = asin_index[asin]
        existing_folder = Path(existing_entry.path)

        # v1: Skip trumping entirely for multi-file layouts
        # Fall through to duplicate_policy handling instead
        if is_multi_file_layout(staging_folder) or is_multi_file_layout(existing_folder):
            logger.debug(
                f"Multi-file layout detected - skipping trumping, "
                f"falling back to duplicate_policy={duplicate_policy}"
            )
            # Don't return - fall through to existing duplicate handling below
        else:
            # Single-file layout - proceed with trumping
            existing_meta = extract_trumpable_meta(existing_folder, asin)
            incoming_meta = extract_trumpable_meta(staging_folder, asin)

            decision, reason = decide_trump(existing_meta, incoming_meta, trump_prefs)
            decision, reason = adjust_for_aggressiveness(decision, reason, trump_prefs)

            match decision:
                case TrumpDecision.REPLACE_WITH_NEW:
                    # Archive existing, then import new
                    archive_existing(
                        existing_folder,
                        existing_meta,
                        incoming_meta,
                        decision,
                        reason,
                        trump_prefs,
                        dry_run=dry_run,
                    )
                    # Continue with normal import (existing now archived)
                    logger.info(f"Trumping: {reason}")
                    # Fall through to normal import flow

                case TrumpDecision.KEEP_EXISTING:
                    return ImportResult(
                        staging_path=staging_folder,
                        target_path=None,
                        asin=asin,
                        status="skipped",
                        error=f"Trumping: {reason}",
                        parsed=parsed,
                    )

                case TrumpDecision.REJECT_NEW:
                    return ImportResult(
                        staging_path=staging_folder,
                        target_path=None,
                        asin=asin,
                        status="skipped",
                        error=f"Rejected: {reason}",
                        parsed=parsed,
                    )

                case TrumpDecision.KEEP_BOTH:
                    # Fall through to existing duplicate_policy handling
                    logger.info(f"Trumping inconclusive: {reason}")

    # ─────────────────────────────────────────────────────────────────────
    # Existing duplicate handling (unchanged)
    # ─────────────────────────────────────────────────────────────────────
    if is_dup:
        if duplicate_policy == "skip":
            return ImportResult(...)
        elif duplicate_policy == "warn":
            ...
        elif duplicate_policy == "overwrite":
            ...

    # ... rest of import logic (Audnex enrichment, build_target_path, move files) ...
```

### CLI Output

```python
# In console.py - add trumping-specific output helpers

def print_trump_decision(
    decision: TrumpDecision,
    reason: str,
    existing: TrumpableMeta,
    incoming: TrumpableMeta,
) -> None:
    """Display trump decision with quality comparison."""

    icon = {
        TrumpDecision.KEEP_EXISTING: "⏭️",
        TrumpDecision.KEEP_BOTH: "📁",
        TrumpDecision.REPLACE_WITH_NEW: "🔄",
        TrumpDecision.REJECT_NEW: "❌",
    }[decision]

    console.print(f"{icon} {decision.name}: {reason}")

    # Show comparison table for REPLACE_WITH_NEW
    if decision == TrumpDecision.REPLACE_WITH_NEW:
        table = Table(title="Quality Comparison")
        table.add_column("Metric", style="cyan")
        table.add_column("Existing", style="red")
        table.add_column("Incoming", style="green")

        table.add_row("Format", existing.format or "?", incoming.format or "?")
        table.add_row("Bitrate", f"{existing.bitrate_kbps or '?'} kbps", f"{incoming.bitrate_kbps or '?'} kbps")
        table.add_row("Sample Rate", f"{existing.sample_rate_hz or '?'} Hz", f"{incoming.sample_rate_hz or '?'} Hz")
        table.add_row("Duration", _format_duration(existing.duration_sec), _format_duration(incoming.duration_sec))
        table.add_row("Chapters", "✓" if existing.has_chapters else "✗", "✓" if incoming.has_chapters else "✗")
        table.add_row("Stereo", "✓" if existing.is_stereo else "✗", "✓" if incoming.is_stereo else "✗")

        console.print(table)
```

---

## Implementation Phases

### Phase 1: Foundation ✅

**Goal:** Core trumping types and metadata extraction.

**Deliverables:**
- [x] Create `src/mamfast/abs/trumping.py` with:
  - [x] `TrumpDecision` enum
  - [x] `TrumpableMeta` frozen dataclass
  - [x] `TrumpPrefs` runtime dataclass (with `from_schema()` factory)
  - [x] `extract_trumpable_meta()` function (uses existing mediainfo infra)
- [x] Add `TrumpingSchema` to `src/mamfast/schemas/config.py`
- [x] Add `trumping` field to `AudiobookshelfImportSchema`
- [x] Add trumping section to `config.yaml.example`
- [x] Create `tests/test_trumping.py` with metadata extraction tests

**Acceptance Criteria:**
- [x] Can extract quality metadata from any audiobook folder
- [x] Schema validates config correctly (enabled requires archive_root)
- [x] Tests pass for metadata extraction edge cases

**Commits:**
- `306b206` feat(trumping): Phase 1 - Foundation types and decision logic
- `e5415d3` fix(trumping): Address code review findings (mediainfo config, opus tier, from_schema)

---

### Phase 2: Decision Logic ✅

**Goal:** Implement comparison and decision tree.

**Deliverables:**
- [x] `decide_trump()` function in `abs/trumping.py`
- [x] `adjust_for_aggressiveness()` modifier
- [x] Duration guardrail checks
- [x] Unit tests for all decision paths

**Acceptance Criteria:**
- [x] Format tier comparison works correctly (m4b > m4a > opus > mp3 > flac)
- [x] Bitrate threshold respects config
- [x] Duration sanity checks catch truncated/extended files
- [x] Tiebreakers apply when enabled
- [x] Aggressiveness modifies decisions appropriately

**Note:** Decision logic was implemented alongside Phase 1 as both are in `trumping.py`.

---

### Phase 3: Archive System ✅

**Goal:** Implement safe archival of trumped content.

**Deliverables:**
- [x] `archive_existing()` function in `abs/trumping.py`
- [x] Inline sidecar JSON writing (TrumpSidecar schema not needed - simple dict)
- [x] Archive path building with year support
- [x] `TrumpingError` exception class

**Acceptance Criteria:**
- [x] Files moved to archive, not deleted
- [x] Sidecar contains full decision audit trail
- [x] Archive path handles collisions (timestamp uniqueness)
- [x] Works with dry_run mode
- [x] Respects `archive_by_year` setting

**Note:** Archive system was implemented alongside Phase 1-2 in initial commit.

---

### Phase 4: Import Integration ✅

**Goal:** Wire trumping into import flow.

**Deliverables:**
- [x] Add `trump_prefs` parameter to `import_single()` in `abs/importer.py`
- [x] Insert trumping check before existing duplicate handling
- [x] Add CLI output for trump decisions in `console.py`
- [x] Update `BatchImportResult` with trump counts

**Acceptance Criteria:**
- [x] Trumping runs automatically when enabled and duplicate detected
- [x] Import continues correctly after archiving
- [x] Statistics include trump counts (replaced, rejected, kept)
- [x] Dry run shows what would be trumped

**Tests:** 8 integration tests in `test_abs_importer.py`

---

### Phase 5: CLI & Polish ✅

**Goal:** User-facing commands and documentation.

**Deliverables:**
- [x] `mamfast abs-trump-check <folder>` command in `cli.py` - preview trumping for a folder
- [x] `mamfast abs-restore <archive-path>` command (stretch goal) - restore archived content
- [x] Update `config.yaml.example` with trumping section
- [x] Update README with trumping documentation

**Acceptance Criteria:**
- [x] Users can preview trumping before import
- [x] Archived content can be restored (if implemented)
- [x] Documentation is clear and complete

**Tests:** 21 tests for CLI commands in `test_cli_abs.py`, 10 tests for archive functions in `test_trumping.py`

---

## Testing Strategy

### Unit Tests

```python
class TestTrumpableMeta:
    """Test quality metadata extraction."""

    def test_format_tier_ranking(self):
        """m4b > m4a > mp3 > flac."""
        m4b = TrumpableMeta(asin="B0TEST", format="m4b")
        mp3 = TrumpableMeta(asin="B0TEST", format="mp3")
        assert m4b.format_tier > mp3.format_tier

    def test_extract_from_folder(self, tmp_path):
        """Extract metadata from real audio files."""
        # Use test fixtures with known metadata
        ...

class TestDecideTrump:
    """Test trump decision tree."""

    def test_format_upgrade(self):
        """mp3 → m4b should trump."""
        existing = TrumpableMeta(asin="B0TEST", format="mp3", bitrate_kbps=128)
        incoming = TrumpableMeta(asin="B0TEST", format="m4b", bitrate_kbps=128)
        prefs = TrumpPrefs()

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.REPLACE_WITH_NEW
        assert "Format upgrade" in reason

    def test_bitrate_upgrade(self):
        """Significant bitrate increase should trump."""
        existing = TrumpableMeta(asin="B0TEST", format="m4b", bitrate_kbps=64)
        incoming = TrumpableMeta(asin="B0TEST", format="m4b", bitrate_kbps=256)
        prefs = TrumpPrefs(min_bitrate_increase_kbps=64)

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.REPLACE_WITH_NEW

    def test_bitrate_below_threshold(self):
        """Small bitrate increase shouldn't trump."""
        existing = TrumpableMeta(asin="B0TEST", format="m4b", bitrate_kbps=128)
        incoming = TrumpableMeta(asin="B0TEST", format="m4b", bitrate_kbps=140)
        prefs = TrumpPrefs(min_bitrate_increase_kbps=64)

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.KEEP_EXISTING

    def test_different_asin_keeps_both(self):
        """Different ASINs can't trump each other."""
        existing = TrumpableMeta(asin="B0AAAA", format="mp3")
        incoming = TrumpableMeta(asin="B0BBBB", format="m4b")
        prefs = TrumpPrefs()

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.KEEP_BOTH

    def test_language_mismatch_keeps_both(self):
        """Different languages can't trump each other."""
        existing = TrumpableMeta(asin="B0TEST", format="mp3", language="en")
        incoming = TrumpableMeta(asin="B0TEST", format="m4b", language="de")
        prefs = TrumpPrefs()

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.KEEP_BOTH

    def test_duration_too_short_rejects(self):
        """Significantly shorter incoming is rejected (possibly truncated)."""
        existing = TrumpableMeta(asin="B0TEST", format="m4b", duration_sec=36000)  # 10 hours
        incoming = TrumpableMeta(asin="B0TEST", format="m4b", duration_sec=30000)  # 8.3 hours (83%)
        prefs = TrumpPrefs(min_duration_ratio=0.9)

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.REJECT_NEW
        assert "shorter" in reason.lower()

    def test_duration_too_long_keeps_both(self):
        """Significantly longer incoming triggers KEEP_BOTH (different edition?)."""
        existing = TrumpableMeta(asin="B0TEST", format="m4b", duration_sec=36000)  # 10 hours
        incoming = TrumpableMeta(asin="B0TEST", format="m4b", duration_sec=50000)  # 13.9 hours (139%)
        prefs = TrumpPrefs(max_duration_ratio=1.25)

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.KEEP_BOTH
        assert "longer" in reason.lower()

    def test_format_beats_bitrate(self):
        """Format tier wins over raw bitrate (M4B 64k > MP3 320k)."""
        existing = TrumpableMeta(asin="B0TEST", format="m4b", bitrate_kbps=64)
        incoming = TrumpableMeta(asin="B0TEST", format="mp3", bitrate_kbps=320)
        prefs = TrumpPrefs()

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.REJECT_NEW  # mp3 can't trump m4b

    def test_missing_metrics_keeps_existing(self):
        """Missing quality metrics default to KEEP_EXISTING for safety."""
        existing = TrumpableMeta(asin="B0TEST", format="m4b")  # No bitrate/sample rate
        incoming = TrumpableMeta(asin="B0TEST", format="m4b")  # No bitrate/sample rate
        prefs = TrumpPrefs()

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.KEEP_EXISTING

class TestArchive:
    """Test archive functionality."""

    def test_archive_creates_sidecar(self, tmp_path):
        """Archive writes .mamfast_trump.json sidecar."""
        ...

    def test_archive_dry_run(self, tmp_path):
        """Dry run doesn't move files."""
        ...

    def test_archive_by_year(self, tmp_path):
        """Archive organizes by year when enabled."""
        ...
```

### Integration Tests

```python
class TestTrumpingIntegration:
    """End-to-end trumping tests."""

    def test_import_with_trumping_replaces_lower_quality(self, tmp_path, mock_abs_client):
        """Full import flow archives and replaces lower quality."""
        # Set up existing library with mp3
        # Import m4b version
        # Verify: old archived, new in library, sidecar written
        ...

    def test_import_with_trumping_disabled_uses_duplicate_policy(self, tmp_path):
        """When trumping disabled, falls back to duplicate_policy."""
        ...
```

---

## Edge Cases & Design Decisions

These edge cases are either explicitly handled by the design or consciously deferred to future versions:

### 1. M4B 64kbps vs MP3 320kbps

**Scenario:** Existing is M4B at 64kbps, incoming is MP3 at 320kbps.

**Behavior:** Keep M4B (format tier wins over bitrate).

**Rationale:** For audiobook UX, chapter support and app compatibility outweigh raw signal quality. Speech content at 64kbps AAC is typically indistinguishable from 320kbps MP3. This is an opinionated choice that matches this tool's focus.

### 2. ASIN Match but Narrator Differs

**Scenario:** Same ASIN but different narrator (e.g., R.C. Bray vs random).

**Behavior:** v1 ignores narrator differences - trumping proceeds based on quality only.

**Future:** Add `keep_both_if_narrator_diff` flag for users who collect multiple narrator versions.

### 3. Multi-File CD-Style Layouts

**Scenario:** Incoming is a multi-file audiobook (e.g., one file per chapter/CD).

**Behavior:** Trumping v1 skips multi-file layouts entirely. They're treated as separate works.

**Rationale:** Comparing quality across file structures is complex. Defer to future version.

### 4. Missing Metadata Fields

**Scenario:** Existing or incoming is missing bitrate/sample rate/duration.

**Behavior:** Fall through to next stage. If all core metrics are missing or equal, default to `KEEP_EXISTING` for safety.

**Rationale:** Missing metadata shouldn't cause false positives. Conservative by default.

### 5. Trusted vs Untrusted Source (Future)

**Scenario:** Want to auto-trump if incoming is from a "trusted" ripper.

**Behavior:** v1 includes `trusted_source: bool = False` field in `TrumpableMeta` but doesn't act on it.

**Future:** Add `trust_beats_quality` config option.

---

## Regional ASINs & Canonical Identity (Future)

> **Status:** 📋 Planned / Not implemented in v1

Long term, we may want to treat different regional ASINs for the *same* work as one logical
book for trumping purposes. For example:

- US: `B002V0QK4C` (audible.com)
- UK: `B0XXXXXXX1` (audible.co.uk)

These can represent the same underlying audiobook and should be candidates for trumping
against each other once we have a safe way to normalize them.

### Concept: Canonical ASIN

Introduce a **canonical identity** separate from the raw ASIN:

```python
@dataclass(frozen=True)
class CanonicalAsinResult:
    """Result of ASIN canonicalization for cross-region matching."""

    original_asin: str          # ASIN from filename/metadata
    canonical_asin: str         # Normalized ASIN in preferred market
    market: str | None = None   # "us", "uk", "de", ...
    source: str = "original"    # "original", "preferred_market", "fallback"
```

Trumping would then use `canonical_asin` as the comparison key instead of the original ASIN.

### Proposed Config Surface

> **Note:** The `canonical_asin` block is a future extension to `TrumpingSchema`
> and is **not** accepted by v1 config parsing. It's documented here for planning purposes.

```yaml
audiobookshelf:
  import:
    trumping:
      enabled: false
      aggressiveness: balanced

      # Regional ASIN handling (future - NOT parsed in v1)
      canonical_asin:
        strategy: "none"          # none | preferred_market
        preferred_market: "us"    # Market whose ASIN becomes canonical
        search_markets:           # Markets we consult when cross-resolving
          - "us"
          - "uk"
          - "au"
```

- `strategy: "none"` (default) – Trumping key = `original_asin` only. No cross-region logic.
- `strategy: "preferred_market"` (future) – Canonical key = ASIN for `preferred_market` when resolvable.

### Resolution Sketch (Future)

When canonicalization is enabled:

1. You have an `original_asin` + parsed title/author.
2. Query ABS / Audible search for that work in `preferred_market`.
3. If a confident match is found:
   - Use that market's ASIN as `canonical_asin`.
4. If not:
   - Fall back to `original_asin` as its own `canonical_asin`.

This logic should **not** be in the hot import path in v1. Instead, it should be:

- A separate batch command, e.g.:

  ```bash
  mamfast abs-canonicalize-asins \
    --preferred-market us \
    --search-markets us uk au
  ```

- Or a maintenance job that walks the library and backfills `canonical_asin`.

### Why This Is Deferred

Regional ASIN mapping is:

- **Hard to get 100% correct** (risk of merging different recordings/editions).
- **More expensive** (extra ABS/Audible API calls).
- **Not required** for safe trumping v1 – worst case you keep both editions.

Because trumping is already a high-risk feature (it moves files), the initial release focuses on:

- Same-ASIN, same-language, same-abridgement only.
- No cross-region or fuzzy merging.
- Clear audit trail via archive sidecars.

### Future Code Shape

Minimal canonicalization function (for reference when implementing):

```python
def canonicalize_asin(
    original_asin: str,
    title: str,
    author: str | None,
    cfg: TrumpPrefs,
) -> CanonicalAsinResult:
    """Normalize ASIN to preferred market (future implementation)."""

    # v1: no canonicalization, use original as-is
    if cfg.canonical_asin_strategy == "none":
        return CanonicalAsinResult(
            original_asin=original_asin,
            canonical_asin=original_asin,
            market=None,
            source="original",
        )

    # strategy == "preferred_market" – future work
    # 1. Search ABS with provider="audible.{preferred_market}"
    # 2. Match results against title/author
    # 3. Return matched ASIN or fall back to original
    ...
```

Then in trumping comparison:

```python
# Today (v1)
# identity key = existing.asin / incoming.asin, plain string

# Future (when canonicalization enabled)
if existing.canonical_asin != incoming.canonical_asin:
    return TrumpDecision.KEEP_BOTH, "Different canonical ASIN"
```

---

## Future Enhancements

### Post-MVP Considerations

1. **Narrator comparison** – Same ASIN but different narrator = keep both
2. **Multi-narrator trumping** – Handle full cast vs single narrator
3. **Restore CLI** – `mamfast abs-restore <archive>` to undo trumping
4. **Archive cleanup** – Prune old archives after N days
5. **Import preview** – Show what would be trumped before confirming
6. **Regional ASIN canonicalization** – Cross-region trumping via canonical ASINs (see above)

### Out of Scope (Explicitly)

- **Automated quality improvement** – Re-encoding to improve quality
- **Cross-library trumping** – Only compares within same library
- **Metadata-only comparison** – Tags don't affect trumping
- **User ratings/preferences** – Purely objective quality metrics

---

## Appendix: Format Tier Rationale {#format-tier-rationale}

| Format | Tier | Why |
|--------|------|-----|
| m4b | 5 | Native audiobook format, chapter support, best app compatibility |
| m4a | 4 | Same codec as m4b but no chapter support |
| opus | 3 | Modern efficient codec, excellent quality/size ratio |
| mp3 | 2 | Universal playback but older codec, chapter support varies |
| flac | 1 | Lossless but huge files, poor chapter support, overkill for speech |

**Why not FLAC at top?**

For audiobooks (speech), lossless is rarely beneficial:
- Speech doesn't have the dynamic range that benefits from lossless
- File size is 5-10x larger
- Most audiobook apps handle AAC better than FLAC
- Chapter markers work best in m4b

If user has specific preference for FLAC, they can set `prefer_lossless: true` (future enhancement).
