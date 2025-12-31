"""Trumping (quality-based replacement) for audiobook imports.

This module implements the decision logic for automatically replacing
lower-quality audiobooks with higher-quality versions during ABS import.

Key concepts:
- Trumping only applies to single-file audiobook layouts
- Format tier (m4b > m4a > mp3 > flac) beats raw bitrate
- Old files are archived, never deleted
- Requires same ASIN, same language, same abridgement status

See docs/audiobookshelf/TRUMPING.md for full design documentation.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Any

from shelfr.abs.asin import AUDIO_EXTENSIONS
from shelfr.config import get_settings

if TYPE_CHECKING:
    from shelfr.config import TrumpingConfig
    from shelfr.schemas.config import TrumpingSchema

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────


class TrumpDecision(Enum):
    """Outcome of comparing existing vs incoming audiobook quality."""

    KEEP_EXISTING = auto()  # Existing is equal or better → reject new
    KEEP_BOTH = auto()  # Tie or incomparable → defer to duplicate_policy
    REPLACE_WITH_NEW = auto()  # New is strictly better → archive existing, import new
    REJECT_NEW = auto()  # New is strictly worse → skip import entirely


class TrumpAggressiveness(str, Enum):
    """How eager trumping should be."""

    CONSERVATIVE = "conservative"  # Major upgrades only (format tier changes)
    BALANCED = "balanced"  # Clear improvements (default)
    AGGRESSIVE = "aggressive"  # Any measurable improvement


# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────


class TrumpingError(Exception):
    """Base exception for trumping-related errors."""

    pass


# ─────────────────────────────────────────────────────────────────────────────
# Data Classes
# ─────────────────────────────────────────────────────────────────────────────


# Format tier ranking: higher = better for audiobooks
# Note: FLAC is intentionally ranked lowest - see TRUMPING.md Appendix
FORMAT_TIERS: dict[str | None, int] = {
    "m4b": 5,  # Native audiobook format, chapter support, best app compatibility
    "m4a": 4,  # AAC without chapters
    "opus": 3,  # Modern efficient codec, excellent quality/size ratio
    "mp3": 2,  # Universal playback but older codec
    "flac": 1,  # Lossless but huge, poor chapter support, overkill for speech
    None: 0,  # Unknown format
}


@dataclass(frozen=True)
class TrumpableMeta:
    """Quality metadata for trumping comparison.

    All values extracted via mediainfo from audio files.
    Fields are intentionally optional - missing data shouldn't block import.
    """

    asin: str  # Required - primary identity

    # Format hierarchy: m4b > m4a > mp3 > flac (for audiobooks)
    format: str | None = None  # "m4b", "m4a", "mp3", "flac"

    # Quality metrics
    bitrate_kbps: int | None = None  # e.g., 128, 256, 320
    sample_rate_hz: int | None = None  # e.g., 22050, 44100, 48000
    duration_sec: int | None = None  # Total duration for sanity checks

    # Tiebreakers (used when core metrics are equal)
    has_chapters: bool = False  # Embedded chapter markers
    is_stereo: bool = False  # True = stereo, False = mono

    # Identity guards (must match for trumping to apply)
    language: str | None = None  # ISO 639 code: "en", "de", etc.
    is_abridged: bool | None = None  # None = unknown
    narrator: str | None = None  # For multi-narrator comparison (future)

    # Source metadata
    source_path: Path | None = None  # For logging/debugging
    trusted_source: bool = False  # Future: trusted ripper/source flag
    ripper_tag: str | None = None  # e.g., "H2OKing" from folder name

    @property
    def format_tier(self) -> int:
        """Return format preference tier (higher = better for audiobooks)."""
        return FORMAT_TIERS.get(self.format, 0)


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

    # Own ripper tags: auto-trump if incoming has one of these (your uploads)
    own_ripper_tags: tuple[str, ...] = ()

    # Future: canonical ASIN prefs (v1 uses defaults)
    canonical_asin_strategy: str = "none"  # "none" | "preferred_market"
    canonical_preferred_market: str = "us"
    canonical_search_markets: tuple[str, ...] = ("us", "uk", "au")

    @classmethod
    def from_schema(cls, schema: TrumpingSchema) -> TrumpPrefs:
        """Create TrumpPrefs from validated TrumpingSchema.

        Handles type coercion (e.g., archive_root str → Path).

        Args:
            schema: Validated TrumpingSchema from config

        Returns:
            Runtime TrumpPrefs instance
        """
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
            own_ripper_tags=tuple(schema.own_ripper_tags) if schema.own_ripper_tags else (),
        )

    @classmethod
    def from_config(cls, config: TrumpingConfig) -> TrumpPrefs:
        """Create TrumpPrefs from runtime TrumpingConfig dataclass.

        Args:
            config: TrumpingConfig from shelfr.config

        Returns:
            Runtime TrumpPrefs instance
        """
        return cls(
            enabled=config.enabled,
            aggressiveness=TrumpAggressiveness(config.aggressiveness),
            min_bitrate_increase_kbps=config.min_bitrate_increase_kbps,
            prefer_chapters=config.prefer_chapters,
            prefer_stereo=config.prefer_stereo,
            min_duration_ratio=config.min_duration_ratio,
            max_duration_ratio=config.max_duration_ratio,
            archive_root=Path(config.archive_root) if config.archive_root else None,
            archive_by_year=config.archive_by_year,
            own_ripper_tags=tuple(config.own_ripper_tags) if config.own_ripper_tags else (),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Multi-File Detection
# ─────────────────────────────────────────────────────────────────────────────


def is_multi_file_layout(folder: Path) -> bool:
    """Check if folder contains multiple audio files (CD-style layout).

    Returns True if trumping should be skipped for this folder.
    Trumping v1 only applies to single-file audiobook layouts.

    Args:
        folder: Path to audiobook folder

    Returns:
        True if folder has more than one audio file
    """
    if not folder.is_dir():
        return False

    audio_files = [
        f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
    ]
    return len(audio_files) > 1


# ─────────────────────────────────────────────────────────────────────────────
# Metadata Extraction
# ─────────────────────────────────────────────────────────────────────────────


def _get_mediainfo_binary() -> str | None:
    """Get mediainfo binary path from config, checking availability.

    Uses the configured mediainfo.binary from settings. Returns the binary
    path if available (either in PATH or as absolute path), None otherwise.

    Falls back to checking for "mediainfo" in PATH if config is unavailable.

    Returns:
        Binary path if available, None if not found
    """
    # Try to get binary name from config, fall back to default
    binary = "mediainfo"
    try:
        settings = get_settings()
        binary = settings.mediainfo.binary
    except Exception:
        # Config unavailable (e.g., in tests without config file)
        logger.debug("Config unavailable, using default mediainfo binary")

    # If it's an absolute path, check it exists
    if Path(binary).is_absolute():
        if Path(binary).exists():
            return binary
        logger.debug("Configured mediainfo binary not found: %s", binary)
        return None

    # Otherwise check if it's in PATH
    found = shutil.which(binary)
    if found:
        return found

    logger.debug("mediainfo binary '%s' not found in PATH", binary)
    return None


def _parse_bitrate(track: dict[str, Any]) -> int | None:
    """Parse bitrate from mediainfo track, converting to kbps."""
    # mediainfo returns BitRate in bps as string: "128000"
    raw = track.get("BitRate")
    if raw:
        try:
            return int(raw) // 1000
        except (ValueError, TypeError):
            pass
    return None


def _parse_sample_rate(track: dict[str, Any]) -> int | None:
    """Parse sample rate from mediainfo track."""
    raw = track.get("SamplingRate")
    if raw:
        try:
            return int(float(raw))
        except (ValueError, TypeError):
            pass
    return None


def _parse_duration(track: dict[str, Any]) -> int | None:
    """Parse duration from mediainfo track, converting to seconds."""
    raw = track.get("Duration")
    if raw:
        try:
            return int(float(raw))
        except (ValueError, TypeError):
            pass
    return None


def _parse_channels(track: dict[str, Any]) -> int:
    """Parse channel count from mediainfo track."""
    raw = track.get("Channels")
    if raw:
        try:
            return int(raw)
        except (ValueError, TypeError):
            pass
    return 1  # Default to mono if unknown


def _detect_chapters(track: dict[str, Any]) -> bool:
    """Detect if file has embedded chapters."""
    # Check for MenuCount or chapters in general track
    menu_count = track.get("MenuCount")
    if menu_count:
        try:
            return int(menu_count) > 0
        except (ValueError, TypeError):
            pass
    return False


def _extract_ripper_tag(folder_name: str) -> str | None:
    """Extract ripper tag from folder name if present.

    Supports both bracket and brace formats:
    - [H2OKing] at the end
    - {H2OKing} at the end

    Args:
        folder_name: Folder name to extract from

    Returns:
        Ripper tag without brackets, or None if not found
    """
    # Try bracket format first [Tag] - must be at end, after stripping ASIN markers
    clean_name = re.sub(r"\s*\{ASIN\.[A-Z0-9]+\}\s*$", "", folder_name)
    clean_name = re.sub(r"\s*\[ASIN\.[A-Z0-9]+\]\s*$", "", clean_name)
    clean_name = re.sub(r"\s*\[B0[A-Z0-9]{8,9}\]\s*$", "", clean_name)

    # Look for ripper tag at end - brackets or braces
    match = re.search(r"\[([^\]]+)\]\s*$", clean_name)
    if not match:
        match = re.search(r"\{([^}]+)\}\s*$", clean_name)

    return match.group(1) if match else None


def extract_trumpable_meta(folder: Path, asin: str) -> TrumpableMeta:
    """Extract quality metadata from audio files in folder.

    Uses existing mediainfo infrastructure from abs/asin.py.
    Extends the pattern used by extract_asin_from_mediainfo().

    Falls back gracefully when metadata unavailable.

    Note: Caller should use is_multi_file_layout() first to skip trumping
    for multi-file layouts. This function still handles multi-file gracefully
    but the importer should short-circuit before calling decide_trump().

    Args:
        folder: Path to audiobook folder
        asin: ASIN for the book (used in returned metadata)

    Returns:
        TrumpableMeta with extracted quality metrics
    """
    # Extract ripper tag from folder name for own-upload detection
    ripper_tag = _extract_ripper_tag(folder.name)

    audio_files = sorted(
        f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
    )
    if not audio_files:
        return TrumpableMeta(asin=asin, source_path=folder, ripper_tag=ripper_tag)

    # v1 rule: only single-file layouts participate in trumping.
    # Caller should normally skip trumping for multi-file layouts using
    # is_multi_file_layout(). This fallback just returns minimal metadata
    # so decide_trump() behaves conservatively if it ever gets called.
    if len(audio_files) > 1:
        logger.debug(
            "Multi-file layout (%d files) - returning minimal metadata for %s",
            len(audio_files),
            folder.name,
        )
        return TrumpableMeta(
            asin=asin,
            source_path=folder,
            ripper_tag=ripper_tag,
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
            ripper_tag=ripper_tag,
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
            ripper_tag=ripper_tag,
        )

    # Parse mediainfo JSON (structure: {"media": {"track": [...]}})
    tracks = data.get("media", {}).get("track", [])
    if isinstance(tracks, dict):
        tracks = [tracks]

    # Find audio track for quality metrics
    audio_track: dict[str, Any] = next((t for t in tracks if t.get("@type") == "Audio"), {})
    general_track: dict[str, Any] = next((t for t in tracks if t.get("@type") == "General"), {})

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
        narrator=None,  # Would need metadata lookup
        source_path=folder,
        ripper_tag=ripper_tag,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Decision Logic
# ─────────────────────────────────────────────────────────────────────────────


def decide_trump(
    existing: TrumpableMeta,
    incoming: TrumpableMeta,
    prefs: TrumpPrefs,
) -> tuple[TrumpDecision, str]:
    """Compare existing vs incoming quality and decide action.

    This is the core decision tree for trumping. Stages are evaluated in order:
    1. Identity guards (ASIN, language, abridgement)
    2. Duration sanity check
    3. Format tier comparison
    4. Bitrate comparison
    5. Sample rate comparison
    6. Tiebreakers (chapters, stereo)

    Args:
        existing: Quality metadata of existing library item
        incoming: Quality metadata of incoming import
        prefs: Trumping preferences

    Returns:
        Tuple of (TrumpDecision, reason_string)
    """
    # ─────────────────────────────────────────────────────────────────────
    # Stage 1: Identity Guards (must be same "book")
    # ─────────────────────────────────────────────────────────────────────
    if existing.asin != incoming.asin:
        return TrumpDecision.KEEP_BOTH, "Different ASIN - not comparable"

    if existing.language and incoming.language and existing.language != incoming.language:
        return (
            TrumpDecision.KEEP_BOTH,
            f"Language mismatch: {existing.language} vs {incoming.language}",
        )

    if (
        existing.is_abridged is not None
        and incoming.is_abridged is not None
        and existing.is_abridged != incoming.is_abridged
    ):
        return TrumpDecision.KEEP_BOTH, "Abridgement status differs"

    # ─────────────────────────────────────────────────────────────────────
    # Stage 1.1: Own Ripper Tag Auto-Trump
    # If incoming has one of the user's own ripper tags, ALWAYS replace
    # regardless of quality. This maintains consistent naming/structure.
    # ─────────────────────────────────────────────────────────────────────
    if prefs.own_ripper_tags and incoming.ripper_tag:
        incoming_tag_lower = incoming.ripper_tag.lower()
        for own_tag in prefs.own_ripper_tags:
            if own_tag.lower() == incoming_tag_lower:
                return (
                    TrumpDecision.REPLACE_WITH_NEW,
                    f"Own ripper tag match: [{incoming.ripper_tag}]",
                )

    # ─────────────────────────────────────────────────────────────────────
    # Stage 1.5: Duration Sanity Check (catch truncated/extended versions)
    # ─────────────────────────────────────────────────────────────────────
    if existing.duration_sec and incoming.duration_sec:
        ratio = incoming.duration_sec / existing.duration_sec

        if ratio < prefs.min_duration_ratio:
            return (
                TrumpDecision.REJECT_NEW,
                f"Incoming significantly shorter ({ratio:.0%} of existing) - possibly truncated",
            )

        if ratio > prefs.max_duration_ratio:
            return (
                TrumpDecision.KEEP_BOTH,
                f"Incoming longer ({ratio:.0%} of existing) - different edition?",
            )

    # ─────────────────────────────────────────────────────────────────────
    # Stage 2: Format Tier (m4b > m4a > mp3 > flac for audiobooks)
    # Note: FLAC ranked last intentionally - see TRUMPING.md Appendix
    # ─────────────────────────────────────────────────────────────────────
    existing_tier = existing.format_tier
    incoming_tier = incoming.format_tier

    if incoming_tier > existing_tier:
        return (
            TrumpDecision.REPLACE_WITH_NEW,
            f"Format upgrade: {existing.format} → {incoming.format}",
        )

    if incoming_tier < existing_tier:
        return (
            TrumpDecision.REJECT_NEW,
            f"Format downgrade: {existing.format} → {incoming.format}",
        )

    # ─────────────────────────────────────────────────────────────────────
    # Stage 3: Bitrate Comparison (when format tiers equal)
    # ─────────────────────────────────────────────────────────────────────
    if existing.bitrate_kbps and incoming.bitrate_kbps:
        delta = incoming.bitrate_kbps - existing.bitrate_kbps

        if delta >= prefs.min_bitrate_increase_kbps:
            return (
                TrumpDecision.REPLACE_WITH_NEW,
                f"Bitrate upgrade: {existing.bitrate_kbps}→{incoming.bitrate_kbps} kbps (+{delta})",
            )

        if delta <= -prefs.min_bitrate_increase_kbps:
            return (
                TrumpDecision.REJECT_NEW,
                f"Bitrate downgrade: {existing.bitrate_kbps}→{incoming.bitrate_kbps} kbps",
            )

    # ─────────────────────────────────────────────────────────────────────
    # Stage 4: Sample Rate (when bitrates comparable)
    # ─────────────────────────────────────────────────────────────────────
    if existing.sample_rate_hz and incoming.sample_rate_hz:
        if incoming.sample_rate_hz > existing.sample_rate_hz:
            return (
                TrumpDecision.REPLACE_WITH_NEW,
                f"Sample rate upgrade: {existing.sample_rate_hz}→{incoming.sample_rate_hz} Hz",
            )

        if incoming.sample_rate_hz < existing.sample_rate_hz:
            # Sample rate downgrade alone isn't worth rejecting
            pass  # Continue to tiebreakers

    # ─────────────────────────────────────────────────────────────────────
    # Stage 5: Tiebreakers (when core metrics equal)
    # ─────────────────────────────────────────────────────────────────────

    # Chapter markers are valuable for navigation
    if prefs.prefer_chapters and incoming.has_chapters and not existing.has_chapters:
        return TrumpDecision.REPLACE_WITH_NEW, "Has chapters (existing does not)"

    # Stereo provides better listening experience
    if prefs.prefer_stereo and incoming.is_stereo and not existing.is_stereo:
        return TrumpDecision.REPLACE_WITH_NEW, "Stereo (existing is mono)"

    # ─────────────────────────────────────────────────────────────────────
    # Stage 6: No Clear Winner
    # ─────────────────────────────────────────────────────────────────────
    # If core quality metrics (format, bitrate, sample rate) are missing or
    # equal, and tiebreakers do not clearly favor the incoming version, the
    # decision defaults to KEEP_EXISTING for safety.
    return TrumpDecision.KEEP_EXISTING, "No quality improvement detected"


def adjust_for_aggressiveness(
    decision: TrumpDecision,
    reason: str,
    prefs: TrumpPrefs,
) -> tuple[TrumpDecision, str]:
    """Modify decision based on aggressiveness setting.

    Conservative mode demotes non-format upgrades to KEEP_EXISTING.
    Aggressive mode is a placeholder for future enhancements.

    Args:
        decision: Initial decision from decide_trump()
        reason: Reason string from decide_trump()
        prefs: Trumping preferences

    Returns:
        Tuple of (possibly modified decision, possibly modified reason)
    """
    match prefs.aggressiveness:
        case TrumpAggressiveness.CONSERVATIVE:
            # Only allow REPLACE_WITH_NEW for major upgrades
            if decision == TrumpDecision.REPLACE_WITH_NEW and "Format upgrade" not in reason:
                # Demote to KEEP_EXISTING unless format tier changed
                return (
                    TrumpDecision.KEEP_EXISTING,
                    f"Conservative mode: {reason} (not sufficient)",
                )

        case TrumpAggressiveness.AGGRESSIVE:
            # Convert KEEP_EXISTING to REPLACE_WITH_NEW for any tiebreaker win
            if decision == TrumpDecision.KEEP_EXISTING:
                # Check if incoming has any advantage at all
                # (This would require re-checking tiebreakers without prefs filter)
                pass  # Keep as-is for now - future enhancement

    return decision, reason


# ─────────────────────────────────────────────────────────────────────────────
# Archive Functions
# ─────────────────────────────────────────────────────────────────────────────


def _meta_to_dict(meta: TrumpableMeta) -> dict[str, Any]:
    """Convert TrumpableMeta to dict for JSON serialization."""
    return {
        "asin": meta.asin,
        "format": meta.format,
        "bitrate_kbps": meta.bitrate_kbps,
        "sample_rate_hz": meta.sample_rate_hz,
        "duration_sec": meta.duration_sec,
        "has_chapters": meta.has_chapters,
        "is_stereo": meta.is_stereo,
        "language": meta.language,
        "is_abridged": meta.is_abridged,
        "source_path": str(meta.source_path) if meta.source_path else None,
    }


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

    Raises:
        TrumpingError: If archive_root not configured
    """
    if not prefs.archive_root:
        raise TrumpingError("archive_root required for trumping")

    # Build archive path - use single datetime to avoid race condition at year boundary
    # Structure: archive_root/[year]/ASIN/timestamp/original_folder_name/
    # This preserves the original folder name for proper restoration
    now = datetime.now(UTC)
    timestamp = now.strftime("%Y-%m-%dT%H-%M-%S")
    original_folder_name = existing_path.name

    if prefs.archive_by_year:
        year = now.strftime("%Y")
        archive_parent = prefs.archive_root / year / existing_meta.asin / timestamp
    else:
        archive_parent = prefs.archive_root / existing_meta.asin / timestamp

    archive_dest = archive_parent / original_folder_name

    if dry_run:
        logger.info("[DRY RUN] Would archive %s → %s", existing_path, archive_dest)
        return None

    # Create parent directory
    archive_parent.mkdir(parents=True, exist_ok=True)

    # Atomically move the entire folder
    # This avoids partial-archive states if something fails mid-operation
    shutil.move(str(existing_path), str(archive_dest))

    # Write trump sidecar inside the archived folder
    sidecar = archive_dest / ".shelfr_trump.json"
    sidecar_data = {
        "schema_version": "1.0",
        "archived_at": datetime.now(UTC).isoformat(),
        "reason": reason,
        "decision": decision.name,
        "original_folder_name": original_folder_name,
        "original_path": str(existing_path),
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

    logger.info("Archived %s → %s", existing_path, archive_dest)
    return archive_dest


# ─────────────────────────────────────────────────────────────────────────────
# Archive Restoration
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ArchiveInfo:
    """Information about an archived book."""

    archive_path: Path
    archived_at: str
    reason: str
    decision: str
    asin: str
    original_format: str | None
    original_bitrate: int | None


def discover_archives(archive_root: Path, *, asin: str | None = None) -> list[ArchiveInfo]:
    """Discover archived books in the archive root.

    Scans for folders containing .shelfr_trump.json sidecar files.

    Args:
        archive_root: Root directory of the archive
        asin: Optional ASIN to filter by

    Returns:
        List of ArchiveInfo objects for found archives
    """
    archives: list[ArchiveInfo] = []

    if not archive_root.exists():
        logger.debug("Archive root does not exist: %s", archive_root)
        return archives

    # Scan recursively for trump sidecar files
    for sidecar_path in archive_root.rglob(".shelfr_trump.json"):
        archive_folder = sidecar_path.parent

        try:
            with sidecar_path.open() as f:
                sidecar_data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to read sidecar %s: %s", sidecar_path, e)
            continue

        # Extract ASIN from sidecar metadata
        existing_meta = sidecar_data.get("existing_meta", {})
        archive_asin = existing_meta.get("asin", "")

        # Filter by ASIN if specified
        if asin and archive_asin != asin:
            continue

        archives.append(
            ArchiveInfo(
                archive_path=archive_folder,
                archived_at=sidecar_data.get("archived_at", ""),
                reason=sidecar_data.get("reason", ""),
                decision=sidecar_data.get("decision", ""),
                asin=archive_asin,
                original_format=existing_meta.get("format"),
                original_bitrate=existing_meta.get("bitrate_kbps"),
            )
        )

    # Sort by archived_at (newest first)
    archives.sort(key=lambda a: a.archived_at, reverse=True)
    return archives


def restore_from_archive(
    archive_path: Path,
    library_root: Path,
    *,
    dry_run: bool = False,
) -> Path | None:
    """Restore an archived book back to the library.

    Reads the trump sidecar to find the original path and restores the folder
    to its original location within the library. If the original path is no
    longer valid (outside library_root), falls back to library_root directly.

    Note: This restoration does NOT remove the book that replaced it.
    Users should manually handle any conflicts or run a rescan.

    Args:
        archive_path: Path to the archived book folder (contains .shelfr_trump.json)
        library_root: Root of the ABS library to restore to
        dry_run: If True, log but don't actually move

    Returns:
        Restored path, or None if dry_run

    Raises:
        TrumpingError: If archive is invalid or restoration fails
    """
    sidecar_path = archive_path / ".shelfr_trump.json"

    if not sidecar_path.exists():
        raise TrumpingError(f"Invalid archive - missing sidecar: {archive_path}")

    try:
        with sidecar_path.open() as f:
            sidecar_data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise TrumpingError(f"Failed to read sidecar: {e}") from e

    # Get original path from sidecar if available (schema_version 1.0+)
    original_path_str = sidecar_data.get("original_path")
    original_folder_name = sidecar_data.get("original_folder_name", archive_path.name)

    # Determine restore destination
    # Try to restore to original location if it was within library_root
    if original_path_str:
        original_path = Path(original_path_str)
        try:
            # Check if original path was within library_root
            original_path.relative_to(library_root)
            restore_dest = original_path
        except ValueError:
            # Original path was outside library_root, use library_root directly
            logger.warning(
                "Original path %s is outside library root, restoring to %s",
                original_path,
                library_root / original_folder_name,
            )
            restore_dest = library_root / original_folder_name
    else:
        # Legacy archive without original_path - use folder name
        restore_dest = library_root / original_folder_name

    # Check for conflicts
    if restore_dest.exists():
        raise TrumpingError(f"Cannot restore - destination exists: {restore_dest}")

    if dry_run:
        logger.info("[DRY RUN] Would restore %s → %s", archive_path, restore_dest)
        return None

    # Ensure parent directory exists
    restore_dest.parent.mkdir(parents=True, exist_ok=True)

    # Move the archive folder to restored location
    shutil.move(str(archive_path), str(restore_dest))

    # Remove the sidecar from restored location
    restored_sidecar = restore_dest / ".shelfr_trump.json"
    if restored_sidecar.exists():
        restored_sidecar.unlink()

    logger.info("Restored %s → %s", archive_path, restore_dest)
    return restore_dest
