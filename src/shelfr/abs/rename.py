"""Rename audiobook folders in Audiobookshelf library to match MAM schema.

This module handles renaming existing ABS library folders to follow
the MAM naming convention for consistency and better organization.

See docs/audiobookshelf/ABS_RENAME_TOOL.md for full design documentation.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import ValidationError

from shelfr.abs.asin import (
    is_valid_asin,
    resolve_asin_from_folder_with_mediainfo,
    resolve_asin_via_abs_search,
)
from shelfr.abs.importer import ParsedFolderName, parse_mam_folder_name
from shelfr.console import (
    confirm,
    print_dry_run,
    print_step,
    print_success,
    print_warning,
    progress_context,
)
from shelfr.schemas.abs_metadata import AbsMetadataJson
from shelfr.utils.fuzzy import is_suspicious_change, similarity_ratio
from shelfr.utils.naming import (
    build_mam_folder_name,
    filter_series,
    filter_subtitle,
    format_volume_number,
)
from shelfr.utils.paths import safe_dirname

if TYPE_CHECKING:
    from shelfr.abs.client import AbsClient
    from shelfr.config import NamingConfig
    from shelfr.models import NormalizedBook

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

# Audio extensions (shared with asin.py)
AUDIO_EXTS = frozenset({".m4b", ".mp3", ".m4a", ".flac", ".ogg", ".opus"})

# Edition flags to detect and preserve
EDITION_FLAGS = [
    "Full-Cast",
    "Full Cast",
    "Dolby Atmos",
    "Atmos",
    "Unabridged",
    "Abridged",
    "Dramatized",
    "Graphic Audio",
    "Publisher's Pack",
    "Publishers Pack",
]

# Patterns for edition flag extraction (case-insensitive)
_EDITION_FLAG_PATTERN = re.compile(
    r"\((" + "|".join(re.escape(f) for f in EDITION_FLAGS) + r")\)",
    re.IGNORECASE,
)

_FOLDER_SCHEMA_PATTERN = re.compile(r"^.+ \(\d{4}\) \([^)]+\) \{ASIN\.[^}]+\}(?: \[[^]]+\])?$")


# =============================================================================
# Rename Policy / Manifest Types
# =============================================================================


@dataclass(frozen=True)
class RenamePolicy:
    """Canonical naming policy used by rename planning/apply.

    IMPORTANT: Rename is for ORGANIZING existing library folders.
    It must NEVER inject ripper tags onto folders that don't already have them.
    The default ripper_tag_policy is 'preserve_if_in_allowlist' — only keep
    tags that are already present AND in the allowlist.
    """

    profile: str = "default"
    hierarchy_mode: str = "preserve"  # preserve | author_series_book
    standalone_mode: str = "author_book"  # author_book
    arc_policy: str = "optional"  # optional | infer | manual
    asin_policy: str = "preserve"  # preserve | prefer_b | strict_b
    # preserve_if_in_allowlist | strip_all
    # NOTE: "import_override" is intentionally NOT the default here.
    # Rename organizes existing folders; it must never inject tags.
    ripper_tag_policy: str = "preserve_if_in_allowlist"
    allowed_ripper_tags: tuple[str, ...] = ("H2OKing",)
    non_allowlisted_tag_action: str = "drop"  # keep | drop
    # Series metadata source policy:
    #   preserve_existing - lock series name to existing parent folder
    #   folder_first      - prefer parsed folder fields over ABS metadata
    #   abs_first          - prefer ABS metadata (original behavior)
    series_source: str = "preserve_existing"
    transaction_backup_root: Path = Path("data/reports/rename_backups")

    def as_dict(self) -> dict[str, Any]:
        """Serialize policy for JSON reports/manifests."""
        return {
            "profile": self.profile,
            "hierarchy_mode": self.hierarchy_mode,
            "standalone_mode": self.standalone_mode,
            "arc_policy": self.arc_policy,
            "asin_policy": self.asin_policy,
            "ripper_tag_policy": self.ripper_tag_policy,
            "allowed_ripper_tags": list(self.allowed_ripper_tags),
            "non_allowlisted_tag_action": self.non_allowlisted_tag_action,
            "series_source": self.series_source,
            "transaction_backup_root": str(self.transaction_backup_root),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RenamePolicy:
        """Deserialize policy from manifest JSON."""
        return cls(
            profile=str(data.get("profile", "default")),
            hierarchy_mode=str(data.get("hierarchy_mode", "preserve")),
            standalone_mode=str(data.get("standalone_mode", "author_book")),
            arc_policy=str(data.get("arc_policy", "optional")),
            asin_policy=str(data.get("asin_policy", "preserve")),
            ripper_tag_policy=str(data.get("ripper_tag_policy", "preserve_if_in_allowlist")),
            allowed_ripper_tags=tuple(data.get("allowed_ripper_tags", ("H2OKing",))),
            non_allowlisted_tag_action=str(data.get("non_allowlisted_tag_action", "drop")),
            series_source=str(data.get("series_source", "preserve_existing")),
            transaction_backup_root=Path(
                str(data.get("transaction_backup_root", "data/reports/rename_backups"))
            ),
        )


@dataclass
class RenamePlanItem:
    """Single item in plan manifest."""

    source_path: str
    target_path: str | None
    status: str
    reasons: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    fingerprint: str | None = None
    components: dict[str, Any] = field(default_factory=dict)
    similarity_percent: float | None = None
    conformance: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Serialize for manifest JSON."""
        return {
            "source_path": self.source_path,
            "target_path": self.target_path,
            "status": self.status,
            "reasons": self.reasons,
            "risk_flags": self.risk_flags,
            "fingerprint": self.fingerprint,
            "components": self.components,
            "similarity_percent": self.similarity_percent,
            "conformance": self.conformance,
        }


@dataclass
class RenamePlanV1:
    """Deterministic rename plan manifest."""

    generated_at: str
    source_dir: str
    policy: RenamePolicy
    summary: dict[str, Any]
    conflicts: dict[str, Any]
    items: list[RenamePlanItem]

    def as_dict(self) -> dict[str, Any]:
        """Serialize manifest to JSON-friendly dict."""
        return {
            "version": "RenamePlanV1",
            "generated_at": self.generated_at,
            "source_dir": self.source_dir,
            "policy": self.policy.as_dict(),
            "summary": self.summary,
            "conflicts": self.conflicts,
            "items": [item.as_dict() for item in self.items],
        }


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class AbsMetadata:
    """Parsed ABS metadata.json (post-validation)."""

    title: str | None = None
    subtitle: str | None = None
    authors: list[str] | None = None
    series: str | None = None
    series_position: str | None = None  # String to preserve "1.5", "1-3", "1p1"
    year: int | None = None
    asin: str | None = None
    narrators: list[str] | None = None


# Rename status type
RenameStatus = Literal[
    "needs_rename",  # Folder name differs from target
    "up_to_date",  # Already matches target schema
    "missing_asin",  # No ASIN found, cannot rename
    "duplicate_asin",  # Same ASIN in multiple folders (conflict)
    "target_exists",  # Target folder name already exists
    "error",  # Parse or other error
]


@dataclass
class RenameCandidate:
    """A folder that may need renaming."""

    source_path: Path
    current_name: str
    parsed: ParsedFolderName | None = None
    target_name: str | None = None
    target_path: Path | None = None
    status: RenameStatus = "needs_rename"
    abs_metadata: AbsMetadata | None = None
    normalized_book: NormalizedBook | None = None
    edition_flags: list[str] = field(default_factory=list)
    asin_source: str | None = None
    error_message: str | None = None
    components: dict[str, Any] = field(default_factory=dict)


@dataclass
class RenameResult:
    """Result of a rename operation."""

    source_path: Path
    target_path: Path | None
    status: Literal["success", "skipped", "failed", "dry_run"]
    files_renamed: list[str] | None = None
    error: str | None = None


@dataclass
class RenameSummary:
    """Summary of rename operations."""

    total_candidates: int = 0
    renamed: int = 0
    skipped_up_to_date: int = 0
    skipped_missing_asin: int = 0
    skipped_duplicate_asin: int = 0
    skipped_target_exists: int = 0
    errors: int = 0


def resolve_rename_policy(
    *,
    policy_profile: str | None = None,
    config_policy: Any | None = None,
) -> RenamePolicy:
    """Resolve effective rename policy from profile + config overrides."""
    profile = (
        policy_profile or getattr(config_policy, "policy_profile", None) or "default"
    ).strip()

    if profile == "sao_gold":
        policy = RenamePolicy(
            profile="sao_gold",
            hierarchy_mode="author_series_book",
            standalone_mode="author_book",
            arc_policy="optional",
            asin_policy="preserve",
            ripper_tag_policy="preserve_if_in_allowlist",
            allowed_ripper_tags=("H2OKing",),
            non_allowlisted_tag_action="drop",
            series_source="preserve_existing",
            transaction_backup_root=Path("data/reports/rename_backups"),
        )
    else:
        policy = RenamePolicy()

    if config_policy is None:
        return policy

    # When a named profile is explicitly requested, it takes precedence.
    # Only apply config overrides for fields the user explicitly set
    # (not schema defaults). We detect this by checking if the config
    # value differs from the schema default — if it matches the schema
    # default AND a profile is active, the profile wins.
    _schema_defaults = {
        "hierarchy_mode": "preserve",
        "arc_policy": "optional",
        "asin_policy": "preserve",
        "ripper_tag_policy": "import_override",
        "allowed_ripper_tags": [],
        "non_allowlisted_tag_action": "keep",
        "series_source": "preserve_existing",
    }

    def _resolve(field: str, profile_val: Any) -> Any:
        """Use config value only if it differs from schema default."""
        cfg_val = getattr(config_policy, field, None)
        if cfg_val is None:
            return profile_val
        schema_default = _schema_defaults.get(field)
        # If config matches schema default AND a profile overrode it,
        # keep the profile value (user didn't explicitly set this field).
        if profile != "default" and cfg_val == schema_default:
            return profile_val
        return cfg_val

    allowed_tags = tuple(_resolve("allowed_ripper_tags", list(policy.allowed_ripper_tags)))
    tx_root = getattr(config_policy, "transaction_backup_root", str(policy.transaction_backup_root))

    return RenamePolicy(
        profile=profile,
        hierarchy_mode=_resolve("hierarchy_mode", policy.hierarchy_mode),
        standalone_mode=getattr(config_policy, "standalone_mode", policy.standalone_mode),
        arc_policy=_resolve("arc_policy", policy.arc_policy),
        asin_policy=_resolve("asin_policy", policy.asin_policy),
        ripper_tag_policy=_resolve("ripper_tag_policy", policy.ripper_tag_policy),
        allowed_ripper_tags=allowed_tags,
        non_allowlisted_tag_action=_resolve(
            "non_allowlisted_tag_action",
            policy.non_allowlisted_tag_action,
        ),
        series_source=_resolve("series_source", policy.series_source),
        transaction_backup_root=Path(str(tx_root)),
    )


# =============================================================================
# Discovery Functions
# =============================================================================


def has_audio_files(path: Path) -> bool:
    """Check if directory contains audio files.

    Args:
        path: Directory to check

    Returns:
        True if directory contains at least one audio file
    """
    try:
        return any(p.is_file() and p.suffix.lower() in AUDIO_EXTS for p in path.iterdir())
    except PermissionError:
        return False


def _is_within(path: Path, parent: Path) -> bool:
    """Return True if path is inside parent (or equal)."""
    return path == parent or parent in path.parents


def discover_rename_candidates(
    source_dir: Path,
    pattern: str = "*",
) -> list[Path]:
    """Find canonical book folders to rename.

    Discovery order:
    1. Prefer folders containing ``metadata.json`` when they have audio in subtree.
    2. Fallback to leaf audio folders when no metadata root covers that subtree.

    Args:
        source_dir: Root directory to scan
        pattern: Glob pattern to filter folder names

    Returns:
        Sorted list of canonical book folder paths
    """
    import fnmatch

    audio_dirs: list[Path] = []
    metadata_dirs: list[Path] = []

    for root, _dirs, files in os.walk(source_dir):
        root_path = Path(root)
        if "metadata.json" in files:
            metadata_dirs.append(root_path)

        if any(Path(f).suffix.lower() in AUDIO_EXTS for f in files):
            audio_dirs.append(root_path)

    # Keep deepest metadata roots first to avoid overlapping parent+child picks.
    metadata_roots: list[Path] = []
    for meta_dir in sorted(metadata_dirs, key=lambda p: len(p.parts), reverse=True):
        has_audio_descendant = any(_is_within(audio_dir, meta_dir) for audio_dir in audio_dirs)
        if not has_audio_descendant:
            continue
        if any(_is_within(selected, meta_dir) for selected in metadata_roots):
            continue
        metadata_roots.append(meta_dir)

    # Leaf audio dirs (no deeper audio descendants), used when no metadata root covers the subtree.
    leaf_audio_dirs: list[Path] = []
    for audio_dir in audio_dirs:
        has_audio_descendant = any(
            _is_within(other_dir, audio_dir) and other_dir != audio_dir for other_dir in audio_dirs
        )
        if not has_audio_descendant:
            leaf_audio_dirs.append(audio_dir)

    candidates: set[Path] = set(metadata_roots)
    for leaf_dir in leaf_audio_dirs:
        if any(
            _is_within(leaf_dir, meta_dir) and leaf_dir != meta_dir for meta_dir in metadata_roots
        ):
            continue
        candidates.add(leaf_dir)

    # Optional glob filter by candidate folder name.
    filtered = [
        candidate
        for candidate in candidates
        if pattern == "*" or fnmatch.fnmatch(candidate.name, pattern)
    ]
    return sorted(filtered)


# =============================================================================
# Metadata Parsing
# =============================================================================


def parse_abs_metadata(folder: Path) -> AbsMetadata | None:
    """Parse and validate ABS metadata.json if present.

    Args:
        folder: Folder path that may contain metadata.json

    Returns:
        AbsMetadata with parsed fields, or None if not present/invalid
    """
    meta_path = folder / "metadata.json"
    if not meta_path.exists():
        return None

    try:
        with open(meta_path, encoding="utf-8") as f:
            data = json.load(f)

        # Validate with Pydantic (using unified schema from schemas/)
        schema = AbsMetadataJson.model_validate(data)

        # Parse series from "Series Name #N" format
        series_name = None
        series_pos = None
        if schema.series:
            series_str = schema.series[0]
            if "#" in series_str:
                parts = series_str.rsplit("#", 1)
                series_name = parts[0].strip()
                pos_str = parts[1].strip()
                # Keep as string to preserve decimal/part/range notation
                series_pos = pos_str
            else:
                series_name = series_str

        # Parse year (can be int or string via published_year alias)
        year = None
        if schema.published_year:
            with contextlib.suppress(ValueError, TypeError):
                year = int(schema.published_year)

        return AbsMetadata(
            title=schema.title,
            subtitle=schema.subtitle,
            authors=schema.authors or None,
            series=series_name,
            series_position=series_pos,
            year=year,
            asin=schema.asin,
            narrators=schema.narrators or None,
        )
    except (json.JSONDecodeError, ValidationError) as e:
        logger.debug(f"Failed to parse ABS metadata.json in {folder}: {e}")
        return None
    except Exception as e:
        logger.debug(f"Unexpected error parsing ABS metadata.json in {folder}: {e}")
        return None


def detect_edition_flags(name: str) -> list[str]:
    """Detect edition flags in folder name.

    Args:
        name: Folder name to check

    Returns:
        List of detected edition flags (e.g., ["Full-Cast", "Dolby Atmos"])
    """
    flags: list[str] = []
    # Check for flags in parentheses
    for match in _EDITION_FLAG_PATTERN.finditer(name):
        flag = match.group(1)
        # Normalize some variants
        if flag.lower() == "full cast":
            flag = "Full-Cast"
        elif flag.lower() == "atmos":
            flag = "Dolby Atmos"
        elif flag.lower() == "publishers pack":
            flag = "Publisher's Pack"
        flags.append(flag)
    return flags


# =============================================================================
# Candidate Processing
# =============================================================================


def parse_candidate(folder: Path) -> RenameCandidate:
    """Parse folder name and create a RenameCandidate.

    Args:
        folder: Path to the folder

    Returns:
        RenameCandidate with parsed information
    """
    name = folder.name

    # Parse folder name using existing parser
    parsed = parse_mam_folder_name(name)

    # Detect edition flags
    flags = detect_edition_flags(name)

    return RenameCandidate(
        source_path=folder,
        current_name=name,
        parsed=parsed,
        edition_flags=flags,
    )


def enrich_from_abs_metadata(candidate: RenameCandidate) -> RenameCandidate:
    """Enrich candidate with ABS metadata.json if available.

    This is Stage 2.5 of the pipeline - ABS metadata is authoritative.

    Args:
        candidate: Candidate to enrich

    Returns:
        Updated candidate with ABS metadata
    """
    abs_meta = parse_abs_metadata(candidate.source_path)
    if not abs_meta:
        return candidate

    candidate = dataclasses.replace(candidate, abs_metadata=abs_meta)

    # If we have ASIN from metadata.json and candidate doesn't have one, use it
    if (
        abs_meta.asin
        and is_valid_asin(abs_meta.asin)
        and candidate.parsed
        and not candidate.parsed.asin
    ):
        # Update parsed with ASIN from metadata.json
        candidate.parsed = dataclasses.replace(candidate.parsed, asin=abs_meta.asin)
        candidate = dataclasses.replace(candidate, asin_source="abs_metadata.json")

    return candidate


def resolve_asin_cascade(
    candidate: RenameCandidate,
    abs_client: AbsClient | None = None,
    abs_search_confidence: float = 0.75,
) -> RenameCandidate:
    """Resolve ASIN using cascade: folder → files → metadata → mediainfo → ABS search.

    Args:
        candidate: Candidate needing ASIN resolution
        abs_client: Optional ABS client for search fallback
        abs_search_confidence: Minimum confidence for ABS search matches

    Returns:
        Updated candidate with resolved ASIN (or missing_asin status)
    """
    # If we already have ASIN from folder parse or ABS metadata, skip cascade
    if candidate.parsed and candidate.parsed.asin:
        if not candidate.asin_source:
            candidate = dataclasses.replace(candidate, asin_source="folder_name")
        return candidate

    # Phase 3+4: Local resolution (folder name, filenames, metadata.json, mediainfo)
    resolution = resolve_asin_from_folder_with_mediainfo(
        candidate.source_path,
        parsed_asin=candidate.parsed.asin if candidate.parsed else None,
    )

    if resolution.found and resolution.asin:
        # Update parsed with resolved ASIN
        if candidate.parsed:
            candidate.parsed = dataclasses.replace(candidate.parsed, asin=resolution.asin)
        return dataclasses.replace(candidate, asin_source=resolution.source)

    # Phase 5: ABS search (opt-in, requires abs_client)
    if abs_client and candidate.parsed:
        title = candidate.abs_metadata.title if candidate.abs_metadata else candidate.parsed.title
        author = None
        if candidate.abs_metadata and candidate.abs_metadata.authors:
            author = candidate.abs_metadata.authors[0]
        elif candidate.parsed.author:
            author = candidate.parsed.author

        if title:
            search_result = resolve_asin_via_abs_search(
                client=abs_client,
                title=title,
                author=author,
                confidence_threshold=abs_search_confidence,
            )
            if search_result.found and search_result.asin:
                candidate.parsed = dataclasses.replace(candidate.parsed, asin=search_result.asin)
                return dataclasses.replace(candidate, asin_source="abs_search")

    # No ASIN found
    return dataclasses.replace(candidate, status="missing_asin")


def detect_duplicates(candidates: list[RenameCandidate]) -> list[RenameCandidate]:
    """Mark candidates with duplicate ASINs.

    Args:
        candidates: List of candidates to check

    Returns:
        Updated list with duplicate_asin status on conflicts
    """
    # Group by ASIN
    asin_to_candidates: dict[str, list[int]] = {}
    for i, c in enumerate(candidates):
        if c.parsed and c.parsed.asin:
            asin = c.parsed.asin
            if asin not in asin_to_candidates:
                asin_to_candidates[asin] = []
            asin_to_candidates[asin].append(i)

    # Mark duplicates
    result = list(candidates)
    for asin, indices in asin_to_candidates.items():
        if len(indices) > 1:
            for idx in indices:
                result[idx] = dataclasses.replace(result[idx], status="duplicate_asin")
            logger.warning(
                f"Duplicate ASIN {asin} found in {len(indices)} folders: "
                f"{[candidates[i].current_name for i in indices]}"
            )

    return result


# =============================================================================
# Target Name Building
# =============================================================================


def _infer_author_from_path(source_path: Path, source_dir: Path | None) -> str | None:
    """Infer author folder from current path layout."""
    if source_dir is None:
        return None

    with contextlib.suppress(ValueError):
        rel = source_path.relative_to(source_dir)
        if len(rel.parts) >= 2:
            return rel.parts[0]
    return None


def _detect_series_root(source_path: Path, source_dir: Path | None) -> str | None:
    """Detect the existing series root from the book's immediate parent folder.

    Uses ``rel.parts[-2]`` (the parent directory of the book folder) when the
    book sits at depth ≥ 3 below ``source_dir`` (i.e. Author/Series/Book).
    At depth ≤ 2 (book sits directly under author dir), there is no series
    root to preserve.

    Returns:
        The series root folder name, or None if no series root detected.
    """
    if source_dir is None:
        return None

    with contextlib.suppress(ValueError):
        rel = source_path.relative_to(source_dir)
        # depth 2+ → parts[-2] is the immediate parent (series dir)
        # Works for both library-root scope (Author/Series/Book = depth 3)
        # and author-dir scope (Series/Book = depth 2).
        if len(rel.parts) >= 2:
            return rel.parts[-2]
    return None


def _resolve_series(
    *,
    parsed: ParsedFolderName | None,
    abs_meta: AbsMetadata | None,
    source_path: Path,
    source_dir: Path | None,
    policy: RenamePolicy,
) -> tuple[str | None, bool]:
    """Single source of truth for series name resolution.

    Applies the ``series_source`` policy to pick the canonical series name:

    * **preserve_existing** (default) — Use the existing parent folder as the
      series root.  If the book already lives under a series directory, that
      directory name wins even when ABS metadata disagrees.  Falls back to
      ABS → parsed when no existing root is detected.
    * **folder_first** — Prefer the parsed folder series name over ABS.
    * **abs_first** — Prefer ABS metadata (original behavior).

    Returns:
        A tuple of (resolved_series_name, series_root_changed) where
        ``series_root_changed`` is True when the policy prevented a
        series root move that ABS metadata would have caused.
    """
    existing_root = _detect_series_root(source_path, source_dir)
    abs_series = abs_meta.series if abs_meta and abs_meta.series else None
    parsed_series = parsed.series if parsed else None

    if policy.series_source == "abs_first":
        # Original behavior: ABS wins
        resolved = abs_series or parsed_series
        changed = bool(existing_root and resolved and resolved != existing_root)
        return resolved, changed

    if policy.series_source == "folder_first":
        # Parsed folder name wins over ABS
        resolved = parsed_series or abs_series
        changed = bool(existing_root and resolved and resolved != existing_root)
        return resolved, changed

    # preserve_existing (default):
    # If the book already lives under a series directory, keep that name.
    # Guard: only trust existing_root if at least one metadata source
    # also says this is a series book.  This prevents depth-2 standalone
    # books (library_root/Author/Book) from misinterpreting the author
    # directory as a series root.
    if existing_root and (abs_series or parsed_series):
        # The book is in a series dir — lock to it.
        # Flag if ABS would have moved it to a different series root.
        changed = bool(abs_series and abs_series != existing_root)
        return existing_root, changed

    # No existing series root: fall back to ABS → parsed.
    resolved = abs_series or parsed_series
    return resolved, False


def _select_ripper_tag(
    parsed_tag: str | None,
    import_ripper_tag: str | None,
    policy: RenamePolicy,
) -> str | None:
    """Apply policy to determine final ripper tag."""
    if policy.ripper_tag_policy == "strip_all":
        return None

    if policy.ripper_tag_policy == "import_override":
        return import_ripper_tag if import_ripper_tag else parsed_tag

    if policy.ripper_tag_policy == "preserve_if_in_allowlist":
        if not parsed_tag:
            return None
        if parsed_tag in policy.allowed_ripper_tags:
            return parsed_tag
        if policy.non_allowlisted_tag_action == "drop":
            return None
        return parsed_tag

    return parsed_tag


def _strip_edition_tags(text: str) -> str:
    """Strip edition tags like (Full-Cast) from a string."""
    return _EDITION_FLAG_PATTERN.sub("", text).strip()


def _extract_arc_from_libation_title(
    title: str,
    series: str,
    series_position: str | None,
) -> str:
    """Extract just the arc/subtitle portion from a Libation-format parsed title.

    For Libation-format folders (no ``" - "`` separator),
    ``parse_mam_folder_name`` sets ``parsed.title`` to the **entire**
    remaining string including the series name, volume number, and any
    leftover parentheticals (e.g. author).  Before using this as an arc
    candidate we must strip those prefixes and suffixes so that only the
    arc text remains.

    Examples::

        >>> _extract_arc_from_libation_title(
        ...     "Harry Potter vol_01 and the Philosopher's Stone (J.K. Rowling)",
        ...     "Harry Potter", "01")
        "and the Philosopher's Stone"

        >>> _extract_arc_from_libation_title(
        ...     "Harry Potter vol_04 and the Goblet of Fire",
        ...     "Harry Potter", "04")
        "and the Goblet of Fire"
    """
    result = title

    # Strip leading series name (case-insensitive)
    if result.lower().startswith(series.lower()):
        result = result[len(series) :].strip()

    # Strip leading volume token (vol_01, vol.2, vol 3, etc.)
    result = re.sub(r"^vol[_.]?\s*\d+(?:\.\d+)?\s*", "", result, flags=re.IGNORECASE).strip()

    # Strip trailing parentheticals — leftover (Author) from Libation parser
    result = re.sub(r"\s*\([^)]*\)\s*$", "", result).strip()

    return result


def _resolve_arc_name(
    *,
    candidate: RenameCandidate,
    title: str | None,
    series: str | None,
    naming_config: NamingConfig | None,
    policy: RenamePolicy,
) -> str | None:
    """Resolve optional arc/subtitle token based on policy.

    With folder-first policies (preserve_existing, folder_first), the
    parsed folder title is tried first before ABS subtitle.  Edition
    tags like ``(Full-Cast)`` are stripped before using a parsed title
    as an arc name since they duplicate the edition_flags field.

    For Libation-format folders, ``parsed.title`` includes the series
    name and volume prefix (e.g.
    ``"Harry Potter vol_01 and the Philosopher's Stone (J.K. Rowling)"``).
    The series+volume prefix and trailing parentheticals are stripped via
    :func:`_extract_arc_from_libation_title` before the candidate is
    tested, so that the arc resolves to just ``"and the Philosopher's
    Stone"``.
    """
    if policy.arc_policy == "manual":
        return None

    abs_meta = candidate.abs_metadata
    parsed = candidate.parsed
    use_folder_first = policy.series_source in ("preserve_existing", "folder_first")

    # ── Folder-first arc sourcing ────────────────────────────────────
    if use_folder_first and parsed and parsed.series and parsed.title:
        candidate_arc = _strip_edition_tags(parsed.title)

        # Libation-format folders set parsed.title to the full remaining
        # string including series+vol prefix.  Strip that prefix so we
        # get only the arc portion (e.g. "and the Philosopher's Stone").
        if candidate_arc.lower().startswith(parsed.series.lower()):
            candidate_arc = _extract_arc_from_libation_title(
                candidate_arc, parsed.series, parsed.series_position
            )

        if candidate_arc and (
            not series or candidate_arc.strip().lower() != series.strip().lower()
        ):
            filtered = filter_subtitle(
                candidate_arc,
                title=title,
                series=series,
                naming_config=naming_config,
            )
            if filtered:
                return filtered

    # ── ABS subtitle (original default source) ───────────────────────
    if abs_meta and abs_meta.subtitle:
        filtered = filter_subtitle(
            abs_meta.subtitle,
            title=title,
            series=series,
            naming_config=naming_config,
        )
        if filtered:
            return filtered

    # ── Infer mode: fallback to parsed title as arc ──────────────────
    if (
        policy.arc_policy == "infer"
        and not use_folder_first
        and parsed
        and parsed.series
        and parsed.title
        and (not series or parsed.title.strip().lower() != series.strip().lower())
    ):
        return parsed.title

    return None


def _build_target_path(
    *,
    source_dir: Path | None,
    source_path: Path,
    target_name: str,
    author: str,
    series: str | None,
    naming_config: NamingConfig | None,
    policy: RenamePolicy,
) -> Path:
    """Build destination path under selected hierarchy policy.

    Detects the hierarchy level that ``source_dir`` represents by measuring
    the depth of ``source_path`` relative to ``source_dir``:

    * **depth ≥ 3** (e.g. ``library/Author/Series/Book``) →
      ``source_dir`` is the **library root**; build full
      ``Author/Series/Book`` hierarchy.
    * **depth 1-2** (e.g. ``AuthorDir/Book`` or ``AuthorDir/Series/Book``) ->
      ``source_dir`` is an **author directory**; for series books always
      build ``Series/Book`` (creating the series dir if needed); for
      standalone books place directly under ``source_dir``.
    """
    if source_dir is None or policy.hierarchy_mode != "author_series_book":
        return source_path.parent / target_name

    clean_author = safe_dirname(author) if author else "Unknown Author"

    # Determine what level source_dir represents by measuring depth.
    try:
        rel = source_path.relative_to(source_dir)
    except ValueError:
        return source_path.parent / target_name
    depth = len(rel.parts)  # components below source_dir

    if series:
        clean_series = safe_dirname(filter_series(series, naming_config=naming_config))
        if depth >= 3:
            # source_dir is library root → Author/Series/Book
            return source_dir / clean_author / clean_series / target_name
        # depth 1-2: source_dir is author-level; always group into Series/Book
        # (covers both items already in a series subdir AND flat items that
        # need a series directory created for them, e.g. Fantastic Beasts
        # sitting directly under the author folder)
        return source_dir / clean_series / target_name

    # Standalone (no series)
    if depth >= 2:
        # source_dir is library root → Author/Book
        return source_dir / clean_author / target_name
    # source_dir is already the author dir
    return source_dir / target_name


def _compute_conformance(
    *,
    target_path: Path | None,
    components: dict[str, Any],
    policy: RenamePolicy,
) -> dict[str, Any]:
    """Compute schema conformance checks for a planned target."""
    if target_path is None:
        return {
            "score": 0,
            "checks": {},
            "violations": ["missing_target_path"],
        }

    folder_name = target_path.name
    checks: dict[str, bool] = {}
    violations: list[str] = []

    checks["token_order"] = bool(_FOLDER_SCHEMA_PATTERN.match(folder_name))
    if not checks["token_order"]:
        violations.append("token_order")

    checks["asin_placement"] = "{ASIN." in folder_name and folder_name.rfind("{ASIN.") > 0
    if not checks["asin_placement"]:
        violations.append("asin_placement")

    tag = components.get("ripper_tag")
    if policy.ripper_tag_policy == "preserve_if_in_allowlist" and tag:
        checks["tag_policy"] = tag in policy.allowed_ripper_tags
    elif policy.ripper_tag_policy == "strip_all":
        checks["tag_policy"] = "[" not in folder_name
    else:
        checks["tag_policy"] = True
    if not checks["tag_policy"]:
        violations.append("tag_policy")

    arc = components.get("arc")
    if policy.arc_policy == "optional":
        checks["arc_policy"] = True
    else:
        checks["arc_policy"] = bool(arc)
    if not checks["arc_policy"]:
        violations.append("arc_policy")

    if policy.hierarchy_mode == "author_series_book":
        series = components.get("series")
        author = str(components.get("author") or "Unknown Author")
        author_dir = safe_dirname(author) if author else "Unknown Author"
        if series:
            series_dir = safe_dirname(filter_series(str(series)))
            checks["hierarchy"] = (
                len(target_path.parents) >= 2
                and target_path.parent.name == series_dir
                and target_path.parent.parent.name == author_dir
            )
        else:
            checks["hierarchy"] = target_path.parent.name == author_dir
    else:
        checks["hierarchy"] = True
    if not checks["hierarchy"]:
        violations.append("hierarchy")

    passed = sum(1 for ok in checks.values() if ok)
    score = round((passed / len(checks)) * 100) if checks else 0

    return {
        "score": score,
        "checks": checks,
        "violations": violations,
    }


def compute_target_name(
    candidate: RenameCandidate,
    naming_config: NamingConfig | None = None,
    import_ripper_tag: str | None = None,
    *,
    source_dir: Path | None = None,
    policy: RenamePolicy | None = None,
) -> RenameCandidate:
    """Compute the target folder name using MAM naming schema.

    Args:
        candidate: Candidate to compute target for
        naming_config: Optional naming configuration
        import_ripper_tag: Ripper tag to add during import (overrides parsed tag)

    Returns:
        Updated candidate with target_name set
    """
    effective_policy = policy or RenamePolicy()

    # Skip if already processed (error, missing ASIN, etc.)
    if candidate.status not in ("needs_rename", "up_to_date"):
        return candidate

    # Need either parsed data or ABS metadata
    parsed = candidate.parsed
    abs_meta = candidate.abs_metadata

    if not parsed:
        return dataclasses.replace(
            candidate,
            status="error",
            error_message="Failed to parse folder name",
        )

    # Get ASIN (required)
    asin = parsed.asin
    if not asin:
        return dataclasses.replace(candidate, status="missing_asin")

    # ── Series resolution (single source of truth) ───────────────────
    series, series_root_changed = _resolve_series(
        parsed=parsed,
        abs_meta=abs_meta,
        source_path=candidate.source_path,
        source_dir=source_dir,
        policy=effective_policy,
    )

    # ── Title / Year resolution (folder-first when applicable) ───────
    use_folder_first = effective_policy.series_source in (
        "preserve_existing",
        "folder_first",
    )

    if use_folder_first:
        title = parsed.title or (abs_meta.title if abs_meta else None)
        year = parsed.year or (str(abs_meta.year) if abs_meta and abs_meta.year else None)
    else:
        # abs_first: original behavior
        title = abs_meta.title if abs_meta and abs_meta.title else parsed.title
        year = str(abs_meta.year) if abs_meta and abs_meta.year else parsed.year

    # Author precedence: ABS metadata -> parsed -> inferred from path -> fallback
    author: str | None = None
    if abs_meta and abs_meta.authors:
        author = abs_meta.authors[0]
    elif parsed.author and parsed.author != "Unknown":
        author = parsed.author
    elif inferred_author := _infer_author_from_path(candidate.source_path, source_dir):
        author = inferred_author
    else:
        author = "Unknown Author"

    # Volume number
    vol_num = None
    if abs_meta and abs_meta.series_position:
        vol_num = abs_meta.series_position
    elif parsed.series_position:
        vol_num = parsed.series_position

    # Format volume number
    vol_str = format_volume_number(vol_num) if vol_num else None

    # Arc/subtitle token (optional for sao_gold policy)
    arc = _resolve_arc_name(
        candidate=candidate,
        title=title,
        series=series,
        naming_config=naming_config,
        policy=effective_policy,
    )

    # Ripper tag policy
    ripper_tag = _select_ripper_tag(
        parsed.ripper_tag,
        import_ripper_tag,
        effective_policy,
    )

    # Build edition flags string
    edition_str = None
    if candidate.edition_flags:
        edition_str = ", ".join(candidate.edition_flags)

    # Build target name using existing function
    # Note: build_mam_folder_name doesn't support edition flags in middle,
    # so we'll need to inject them manually after author
    target = build_mam_folder_name(
        series=series,
        title=title or "",
        volume_number=vol_str.replace("vol_", "") if vol_str else None,
        arc=arc,
        year=year,
        author=author,
        asin=asin,
        ripper_tag=ripper_tag,
        naming_config=naming_config,
    )

    # Inject edition flags between author and ASIN if present
    if edition_str:
        # Find ASIN position and insert before it
        asin_pos = target.find("{ASIN.")
        if asin_pos > 0:
            # Insert edition flags before ASIN
            target = f"{target[:asin_pos]}({edition_str}) {target[asin_pos:]}"

    # Apply pathvalidate safety
    target = safe_dirname(target)

    target_path = _build_target_path(
        source_dir=source_dir,
        source_path=candidate.source_path,
        target_name=target,
        author=author,
        series=series,
        naming_config=naming_config,
        policy=effective_policy,
    )

    components: dict[str, Any] = {
        "author": author,
        "series": series,
        "volume": vol_str,
        "title": title,
        "year": year,
        "asin": asin,
        "arc": arc,
        "ripper_tag": ripper_tag,
    }
    components["conformance"] = _compute_conformance(
        target_path=target_path,
        components=components,
        policy=effective_policy,
    )

    if series_root_changed:
        components["series_root_changed"] = True

    # Check if rename is needed (path-aware, not just folder name).
    if target_path == candidate.source_path:
        return dataclasses.replace(
            candidate,
            target_name=target,
            target_path=target_path,
            components=components,
            status="up_to_date",
        )

    # Check for suspicious changes (too different)
    if is_suspicious_change(candidate.current_name, target, threshold=30):
        logger.warning(
            f"Large change detected for {candidate.current_name}: "
            f"similarity={similarity_ratio(candidate.current_name, target):.1f}%"
        )

    return dataclasses.replace(
        candidate,
        target_name=target,
        target_path=target_path,
        components=components,
    )


def check_target_exists(
    candidates: list[RenameCandidate],
) -> list[RenameCandidate]:
    """Check if any target names already exist (name collision).

    Args:
        candidates: List of candidates with computed target names

    Returns:
        Updated list with target_exists status on collisions
    """
    result = list(candidates)

    for i, c in enumerate(result):
        if c.status != "needs_rename" or c.target_path is None:
            continue

        target_path = c.target_path

        # Check if target path exists and is different from source
        if target_path.exists() and target_path != c.source_path:
            result[i] = dataclasses.replace(c, status="target_exists")

    return result


# =============================================================================
# Rename Execution
# =============================================================================

# Files to skip when renaming files inside folder
SKIP_FILES = frozenset({"cover.jpg", "cover.png", "metadata.json", "desc.txt", "reader.txt"})


def _rename_files_inside(target_path: Path, new_stem: str) -> list[str]:
    """Rename media files inside folder to match new folder name.

    Preserves cover.jpg, metadata.json and other sidecar files.
    For multi-file layouts (multiple audio files), appends a numeric suffix
    to prevent collisions.

    Args:
        target_path: The renamed folder path
        new_stem: New filename stem (folder name)

    Returns:
        List of original filenames that were renamed
    """
    renamed: list[str] = []

    try:
        # Collect all media files (non-sidecar files)
        media_files = [
            f for f in target_path.iterdir() if f.is_file() and f.name.lower() not in SKIP_FILES
        ]

        # Sort by name for deterministic ordering
        media_files.sort(key=lambda f: f.name)

        # Count actual audio files to determine if multi-file layout
        audio_file_count = sum(1 for f in media_files if f.suffix.lower() in AUDIO_EXTS)

        # Use suffix only for true multi-file audiobooks (multiple audio files)
        use_suffix = audio_file_count > 1

        for idx, f in enumerate(media_files, start=1):
            if use_suffix:
                # Multi-file: "Folder Name - Part 01.m4b", "Folder Name - Part 02.m4b"
                new_name = f"{new_stem} - Part {idx:02d}{f.suffix}"
            else:
                # Single file: "Folder Name.m4b"
                new_name = f"{new_stem}{f.suffix}"

            # Skip if already named correctly
            if f.name == new_name:
                continue

            try:
                f.rename(f.with_name(new_name))
                renamed.append(f.name)
                logger.debug(f"Renamed file: {f.name} → {new_name}")
            except OSError as e:
                logger.warning(f"Failed to rename file {f.name}: {e}")
    except PermissionError as e:
        logger.warning(f"Cannot read folder {target_path}: {e}")

    return renamed


def rename_folder(
    candidate: RenameCandidate,
    dry_run: bool = False,
    force: bool = False,
) -> RenameResult:
    """Execute folder rename.

    Media files inside the folder are automatically renamed to match the new
    folder name. Sidecar files (cover.jpg, metadata.json, etc.) are preserved.

    Args:
        candidate: Candidate to rename
        dry_run: If True, don't actually rename
        force: If True, rename files inside even when folder is up-to-date

    Returns:
        RenameResult with operation status
    """
    # Special handling for force mode with up-to-date folders
    if force and candidate.status == "up_to_date" and candidate.target_name:
        # Folder is already correct, but force rename files inside
        if dry_run:
            return RenameResult(
                source_path=candidate.source_path,
                target_path=candidate.source_path,
                status="dry_run",
            )

        try:
            # Rename files inside using current folder name
            files_renamed = _rename_files_inside(candidate.source_path, candidate.target_name)
            return RenameResult(
                source_path=candidate.source_path,
                target_path=candidate.source_path,
                status="success",
                files_renamed=files_renamed if files_renamed else None,
            )
        except OSError as e:
            return RenameResult(
                source_path=candidate.source_path,
                target_path=candidate.source_path,
                status="failed",
                error=str(e),
            )

    if candidate.status != "needs_rename":
        return RenameResult(
            source_path=candidate.source_path,
            target_path=None,
            status="skipped",
            error=f"Status: {candidate.status}",
        )

    if not candidate.target_name:
        return RenameResult(
            source_path=candidate.source_path,
            target_path=None,
            status="failed",
            error="No target name computed",
        )

    target_path = candidate.target_path or (candidate.source_path.parent / candidate.target_name)

    if dry_run:
        return RenameResult(
            source_path=candidate.source_path,
            target_path=target_path,
            status="dry_run",
        )

    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        candidate.source_path.rename(target_path)

        # Always rename media files inside the folder to match new folder name
        files_renamed = _rename_files_inside(target_path, target_path.name)

        return RenameResult(
            source_path=candidate.source_path,
            target_path=target_path,
            status="success",
            files_renamed=files_renamed if files_renamed else None,
        )
    except OSError as e:
        return RenameResult(
            source_path=candidate.source_path,
            target_path=target_path,
            status="failed",
            error=str(e),
        )


# =============================================================================
# Pipeline Orchestration
# =============================================================================


def run_rename_pipeline(
    source_dir: Path,
    *,
    pattern: str = "*",
    fetch_metadata: bool = False,  # Reserved for future Audnex integration
    abs_client: AbsClient | None = None,
    abs_search_confidence: float = 0.75,
    naming_config: NamingConfig | None = None,
    import_ripper_tag: str | None = None,
    policy: RenamePolicy | None = None,
    dry_run: bool = False,
    interactive: bool = False,
    force: bool = False,
) -> tuple[list[RenameResult], RenameSummary, list[RenameCandidate]]:
    """Run the full rename pipeline.

    Media files inside renamed folders are automatically renamed to match the
    new folder name. Sidecar files (cover.jpg, metadata.json, etc.) are preserved.

    Args:
        source_dir: Directory to scan for folders to rename
        pattern: Glob pattern to filter folders
        fetch_metadata: Reserved for future Audnex metadata integration (not yet implemented)
        abs_client: Optional ABS client for search fallback
        abs_search_confidence: Minimum confidence for ABS search
        naming_config: Optional naming configuration
        import_ripper_tag: Ripper tag to add during import (overrides parsed tag)
        policy: Canonical naming policy
        dry_run: If True, don't actually rename
        interactive: If True, prompt for each rename
        force: If True, rename files inside even when folder names are up-to-date

    Returns:
        Tuple of (list of results, summary, list of candidates)
    """
    # Note: fetch_metadata is reserved for future Audnex integration
    _ = fetch_metadata  # Suppress unused parameter warning

    results: list[RenameResult] = []
    summary = RenameSummary()

    # Stage 1: Discovery (use spinner - count unknown during walk)
    print_step(1, 6, "Discovering folders")
    with progress_context("Scanning directories", total=None) as (progress, task):
        folders = discover_rename_candidates(source_dir, pattern)
        progress.update(task, description=f"Found {len(folders)} folders")
    summary.total_candidates = len(folders)
    logger.info(f"Found {len(folders)} folders to process")

    if not folders:
        return results, summary, []

    # Determine worker count (I/O bound, so more workers help)
    max_workers = min(32, (os.cpu_count() or 4) * 4)

    # Stage 2: Parse existing names (parallel - fast but many items)
    print_step(2, 6, "Parsing folder names")
    candidates: list[RenameCandidate] = []
    with (
        progress_context("Parsing names", total=len(folders)) as (progress, task),
        ThreadPoolExecutor(max_workers=max_workers) as executor,
    ):
        futures = {executor.submit(parse_candidate, f): i for i, f in enumerate(folders)}
        results_map: dict[int, RenameCandidate] = {}
        for future in as_completed(futures):
            idx = futures[future]
            results_map[idx] = future.result()
            progress.update(task, advance=1)
        candidates = [results_map[i] for i in range(len(folders))]

    # Stage 2.5: Enrich with ABS metadata (parallel - reads metadata.json)
    print_step(3, 6, "Reading ABS metadata")
    with (
        progress_context("Reading metadata", total=len(candidates)) as (progress, task),
        ThreadPoolExecutor(max_workers=max_workers) as executor,
    ):
        futures = {
            executor.submit(enrich_from_abs_metadata, c): i for i, c in enumerate(candidates)
        }
        results_map = {}
        for future in as_completed(futures):
            idx = futures[future]
            results_map[idx] = future.result()
            progress.update(task, advance=1)
        candidates = [results_map[i] for i in range(len(candidates))]

    # Stage 3: ASIN resolution (parallel - may call mediainfo subprocess)
    print_step(4, 6, "Resolving ASINs")

    def resolve_one(c: RenameCandidate) -> RenameCandidate:
        return resolve_asin_cascade(c, abs_client, abs_search_confidence)

    with (
        progress_context("Resolving ASINs", total=len(candidates)) as (progress, task),
        ThreadPoolExecutor(max_workers=max_workers) as executor,
    ):
        futures = {executor.submit(resolve_one, c): i for i, c in enumerate(candidates)}
        results_map = {}
        for future in as_completed(futures):
            idx = futures[future]
            results_map[idx] = future.result()
            progress.update(task, advance=1)
        candidates = [results_map[i] for i in range(len(candidates))]

    # Stage 4: Duplicate detection
    candidates = detect_duplicates(candidates)

    # Stage 5: Build target names
    print_step(5, 6, "Computing target names")
    effective_policy = policy or RenamePolicy()
    candidates = [
        compute_target_name(
            c,
            naming_config,
            import_ripper_tag,
            source_dir=source_dir,
            policy=effective_policy,
        )
        for c in candidates
    ]
    candidates = check_target_exists(candidates)

    # Stage 6: Execute renames
    print_step(6, 6, "Renaming folders" if not dry_run else "Previewing renames")

    for candidate in candidates:
        # Interactive mode
        should_prompt = interactive and (
            (candidate.status == "needs_rename" and candidate.target_name)
            or (force and candidate.status == "up_to_date" and candidate.target_name)
        )

        if should_prompt:
            if candidate.status == "up_to_date":
                print(f"\n{candidate.current_name}")
                print("  → (rename files inside only)")
            else:
                print(f"\n{candidate.current_name}")
                target_preview = (
                    str(candidate.target_path)
                    if candidate.target_path is not None
                    else str(candidate.target_name)
                )
                print(f"  → {target_preview}")

            if not confirm("Rename this folder?"):
                result = RenameResult(
                    source_path=candidate.source_path,
                    target_path=None,
                    status="skipped",
                    error="User declined",
                )
                results.append(result)
                continue

        result = rename_folder(candidate, dry_run=dry_run, force=force)
        results.append(result)

        # Update summary
        match result.status:
            case "success" | "dry_run":
                summary.renamed += 1
            case "skipped":
                if candidate.status == "up_to_date":
                    summary.skipped_up_to_date += 1
                elif candidate.status == "missing_asin":
                    summary.skipped_missing_asin += 1
                elif candidate.status == "duplicate_asin":
                    summary.skipped_duplicate_asin += 1
                elif candidate.status == "target_exists":
                    summary.skipped_target_exists += 1
            case "failed":
                summary.errors += 1

    # Print summary
    if dry_run:
        print_dry_run(f"Would rename {summary.renamed} folders")
    else:
        print_success(f"Renamed {summary.renamed} folders")

    if summary.skipped_up_to_date:
        logger.info(f"Already up-to-date: {summary.skipped_up_to_date}")
    if summary.skipped_missing_asin:
        print_warning(f"Missing ASIN: {summary.skipped_missing_asin}")
    if summary.skipped_duplicate_asin:
        print_warning(f"Duplicate ASIN conflicts: {summary.skipped_duplicate_asin}")
    if summary.skipped_target_exists:
        print_warning(f"Target exists: {summary.skipped_target_exists}")
    if summary.errors:
        print_warning(f"Errors: {summary.errors}")

    return results, summary, candidates


def _compute_path_fingerprint(path: Path) -> str | None:
    """Compute a stable fingerprint for stale-manifest detection."""
    if not path.exists():
        return None

    hasher = hashlib.sha256()
    file_count = 0
    total_size = 0
    latest_mtime_ns = 0

    if path.is_file():
        stat = path.stat()
        hasher.update(path.name.encode("utf-8", "ignore"))
        hasher.update(str(stat.st_size).encode("ascii"))
        hasher.update(str(stat.st_mtime_ns).encode("ascii"))
        return hasher.hexdigest()

    for file_path in sorted(path.rglob("*")):
        if not file_path.is_file():
            continue
        try:
            stat = file_path.stat()
        except OSError:
            continue

        rel = file_path.relative_to(path)
        hasher.update(str(rel).encode("utf-8", "ignore"))
        hasher.update(str(stat.st_size).encode("ascii"))
        hasher.update(str(stat.st_mtime_ns).encode("ascii"))
        file_count += 1
        total_size += stat.st_size
        latest_mtime_ns = max(latest_mtime_ns, stat.st_mtime_ns)

    hasher.update(str(file_count).encode("ascii"))
    hasher.update(str(total_size).encode("ascii"))
    hasher.update(str(latest_mtime_ns).encode("ascii"))
    return hasher.hexdigest()


def _derive_plan_reasons(candidate: RenameCandidate) -> list[str]:
    """Generate deterministic reason codes for plan review."""
    reasons: list[str] = []
    if candidate.status == "missing_asin":
        reasons.append("missing_asin")
    if candidate.status == "duplicate_asin":
        reasons.append("duplicate_asin")
    if candidate.status == "target_exists":
        reasons.append("target_exists")
    if candidate.status == "up_to_date":
        reasons.append("already_canonical")
    if candidate.status == "needs_rename":
        reasons.append("canonicalization_required")

    if candidate.target_path and candidate.target_path.parent != candidate.source_path.parent:
        reasons.append("hierarchy_move")
    if candidate.target_name and candidate.target_name != candidate.current_name:
        reasons.append("name_change")
    return reasons


def _derive_risk_flags(candidate: RenameCandidate) -> list[str]:
    """Assign risk flags used for canary stratification."""
    flags: list[str] = []
    if candidate.target_name:
        sim = similarity_ratio(candidate.current_name, candidate.target_name)
        if sim < 30:
            flags.append("low_similarity")

    if candidate.target_path and candidate.target_path.parent != candidate.source_path.parent:
        flags.append("hierarchy_move")

    parsed_tag = candidate.parsed.ripper_tag if candidate.parsed else None
    planned_tag = candidate.components.get("ripper_tag")
    if parsed_tag and not planned_tag:
        flags.append("tag_removed")

    asin = candidate.parsed.asin if candidate.parsed else None
    if asin and asin.isdigit():
        flags.append("edge_case_numeric_asin")

    if candidate.components.get("series_root_changed"):
        flags.append("series_root_change")

    return sorted(set(flags))


def build_rename_plan(
    *,
    source_dir: Path,
    candidates: list[RenameCandidate],
    summary: RenameSummary,
    policy: RenamePolicy,
) -> RenamePlanV1:
    """Build deterministic plan manifest from pipeline candidates."""
    items: list[RenamePlanItem] = []
    conflicts: dict[str, Any] = {
        "missing_asin": [],
        "duplicate_asin": {},
        "target_exists": [],
    }

    for candidate in sorted(candidates, key=lambda c: str(c.source_path)):
        if candidate.status in {"missing_asin", "target_exists"}:
            conflicts[candidate.status].append(str(candidate.source_path))
        elif candidate.status == "duplicate_asin":
            asin = candidate.parsed.asin if candidate.parsed else None
            key = asin or "UNKNOWN_ASIN"
            duplicate_groups = conflicts["duplicate_asin"]
            duplicate_groups.setdefault(key, []).append(str(candidate.source_path))

        similarity = None
        if candidate.target_name:
            similarity = round(similarity_ratio(candidate.current_name, candidate.target_name), 1)

        item = RenamePlanItem(
            source_path=str(candidate.source_path),
            target_path=str(candidate.target_path) if candidate.target_path else None,
            status=candidate.status,
            reasons=_derive_plan_reasons(candidate),
            risk_flags=_derive_risk_flags(candidate),
            fingerprint=_compute_path_fingerprint(candidate.source_path),
            components={
                **candidate.components,
                "current_name": candidate.current_name,
                "target_name": candidate.target_name,
                "asin_source": candidate.asin_source,
            },
            similarity_percent=similarity,
            conformance=(
                candidate.components.get("conformance", {})
                if candidate.components
                else _compute_conformance(
                    target_path=candidate.target_path,
                    components={"ripper_tag": None, "arc": None},
                    policy=policy,
                )
            ),
        )
        items.append(item)

    manifest_summary = {
        "total_candidates": summary.total_candidates,
        "needs_rename": sum(1 for c in candidates if c.status == "needs_rename"),
        "up_to_date": sum(1 for c in candidates if c.status == "up_to_date"),
        "missing_asin": summary.skipped_missing_asin,
        "duplicate_asin": summary.skipped_duplicate_asin,
        "target_exists": summary.skipped_target_exists,
        "errors": summary.errors,
    }

    return RenamePlanV1(
        generated_at=datetime.now(UTC).isoformat(),
        source_dir=str(source_dir),
        policy=policy,
        summary=manifest_summary,
        conflicts=conflicts,
        items=items,
    )


def write_rename_plan(plan: RenamePlanV1, output_path: Path) -> dict[str, Any]:
    """Write rename plan manifest JSON to disk."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = plan.as_dict()
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return payload


def _select_canary_items(
    items: list[dict[str, Any]],
    *,
    canary_size: int | None,
    canary_strategy: str,
) -> list[dict[str, Any]]:
    """Select a deterministic canary subset."""
    if not canary_size or canary_size <= 0 or canary_size >= len(items):
        return items

    ordered = sorted(items, key=lambda item: str(item.get("source_path", "")))
    if canary_strategy != "stratified":
        return ordered[:canary_size]

    buckets: dict[str, list[dict[str, Any]]] = {
        "high": [],
        "tag": [],
        "hierarchy": [],
        "edge": [],
        "low": [],
    }
    for item in ordered:
        flags = set(item.get("risk_flags", []))
        if "low_similarity" in flags:
            buckets["high"].append(item)
        elif "tag_removed" in flags:
            buckets["tag"].append(item)
        elif "hierarchy_move" in flags:
            buckets["hierarchy"].append(item)
        elif any(flag.startswith("edge_case_") for flag in flags):
            buckets["edge"].append(item)
        else:
            buckets["low"].append(item)

    selected: list[dict[str, Any]] = []
    order = ("high", "tag", "hierarchy", "edge", "low")
    idx = 0
    while len(selected) < canary_size and any(buckets.values()):
        bucket_name = order[idx % len(order)]
        idx += 1
        if not buckets[bucket_name]:
            continue
        selected.append(buckets[bucket_name].pop(0))
    return selected


def apply_rename_plan(
    plan_path: Path,
    *,
    dry_run: bool = False,
    canary_size: int | None = None,
    canary_strategy: str = "stratified",
) -> dict[str, Any]:
    """Apply renames from an approved plan manifest."""
    with open(plan_path, encoding="utf-8") as f:
        plan_payload = json.load(f)

    if plan_payload.get("version") != "RenamePlanV1":
        raise ValueError(f"Unsupported plan version: {plan_payload.get('version')}")

    policy = RenamePolicy.from_dict(plan_payload.get("policy", {}))
    all_items = [
        item
        for item in plan_payload.get("items", [])
        if item.get("status") == "needs_rename" and item.get("target_path")
    ]
    selected_items = _select_canary_items(
        all_items,
        canary_size=canary_size,
        canary_strategy=canary_strategy,
    )
    duplicate_asin_groups = plan_payload.get("conflicts", {}).get("duplicate_asin", {})
    if not isinstance(duplicate_asin_groups, dict):
        duplicate_asin_groups = {}
    suspicious_changes = [
        {
            "source_path": item.get("source_path"),
            "target_path": item.get("target_path"),
            "similarity_percent": item.get("similarity_percent"),
        }
        for item in selected_items
        if "low_similarity" in set(item.get("risk_flags", []))
    ]

    backup_root = policy.transaction_backup_root / datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

    # Preflight all selected items before mutating filesystem.
    apply_results: list[dict[str, Any]] = []
    target_to_rows: dict[str, list[int]] = {}
    for idx, item in enumerate(selected_items):
        target_to_rows.setdefault(str(item.get("target_path", "")), []).append(idx)

    blocked_rows: set[int] = set()
    for _target, rows in target_to_rows.items():
        if len(rows) <= 1:
            continue
        for row_num in rows:
            blocked_rows.add(row_num)
            item = selected_items[row_num]
            apply_results.append(
                {
                    "source_path": str(item["source_path"]),
                    "target_path": str(item["target_path"]),
                    "status": "failed",
                    "error": "duplicate_target_in_plan",
                    "rollback_ok": True,
                }
            )

    for row_idx, item in enumerate(selected_items):
        if row_idx in blocked_rows:
            continue

        source_path = Path(item["source_path"])
        target_path = Path(item["target_path"])
        expected_fingerprint = item.get("fingerprint")
        current_fingerprint = _compute_path_fingerprint(source_path)

        if not source_path.exists():
            apply_results.append(
                {
                    "source_path": str(source_path),
                    "target_path": str(target_path),
                    "status": "failed",
                    "error": "source_missing",
                    "rollback_ok": True,
                }
            )
            blocked_rows.add(row_idx)
            continue

        if expected_fingerprint and current_fingerprint != expected_fingerprint:
            apply_results.append(
                {
                    "source_path": str(source_path),
                    "target_path": str(target_path),
                    "status": "failed",
                    "error": "fingerprint_mismatch",
                    "rollback_ok": True,
                }
            )
            blocked_rows.add(row_idx)
            continue

        if target_path.exists() and target_path != source_path:
            apply_results.append(
                {
                    "source_path": str(source_path),
                    "target_path": str(target_path),
                    "status": "failed",
                    "error": "target_conflict",
                    "rollback_ok": True,
                }
            )
            blocked_rows.add(row_idx)

    # Reliability-first: abort apply if any preflight issue exists.
    if blocked_rows:
        by_status: dict[str, list[dict[str, Any]]] = {}
        for result_row in apply_results:
            by_status.setdefault(result_row["status"], []).append(result_row)

        summary = {
            "selected": len(selected_items),
            "success": 0,
            "dry_run": 0,
            "failed": len(by_status.get("failed", [])),
        }

        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "plan_path": str(plan_path),
            "dry_run": dry_run,
            "policy": policy.as_dict(),
            "canary": {
                "strategy": canary_strategy,
                "requested_size": canary_size,
                "selected_size": len(selected_items),
            },
            "summary": summary,
            "warnings": {
                "preflight_failed": True,
                "suspicious_changes_count": len(suspicious_changes),
                "suspicious_changes": suspicious_changes,
                "duplicate_asin_groups": duplicate_asin_groups,
            },
            "by_status": by_status,
            "results": apply_results,
        }

    if not dry_run:
        backup_root.mkdir(parents=True, exist_ok=True)

    for index, item in enumerate(selected_items, start=1):
        source_path = Path(item["source_path"])
        target_path = Path(item["target_path"])

        if dry_run:
            apply_results.append(
                {
                    "source_path": str(source_path),
                    "target_path": str(target_path),
                    "status": "dry_run",
                    "error": None,
                    "rollback_ok": True,
                }
            )
            continue

        item_backup_dir = backup_root / f"{index:05d}"
        source_backup = item_backup_dir / "source_backup"
        target_backup = item_backup_dir / "target_backup"
        target_was_displaced = False
        rollback_ok = True

        try:
            item_backup_dir.mkdir(parents=True, exist_ok=True)
            target_path.parent.mkdir(parents=True, exist_ok=True)

            if target_path.exists() and target_path != source_path:
                target_path.rename(target_backup)
                target_was_displaced = True

            source_path.rename(source_backup)
            source_backup.rename(target_path)
            files_renamed = _rename_files_inside(target_path, target_path.name)

            # Cleanup empty per-item backup dir after successful commit.
            with contextlib.suppress(OSError):
                if item_backup_dir.exists() and not any(item_backup_dir.iterdir()):
                    item_backup_dir.rmdir()

            apply_results.append(
                {
                    "source_path": str(source_path),
                    "target_path": str(target_path),
                    "status": "success",
                    "error": None,
                    "files_renamed": files_renamed,
                    "rollback_ok": True,
                }
            )
        except OSError as e:
            # Best-effort rollback per item transaction.
            if target_path.exists() and not source_path.exists():
                with contextlib.suppress(OSError):
                    target_path.rename(source_path)
                rollback_ok = rollback_ok and source_path.exists()
            elif source_backup.exists() and not source_path.exists():
                with contextlib.suppress(OSError):
                    source_backup.rename(source_path)
                rollback_ok = rollback_ok and source_path.exists()

            if target_was_displaced and target_backup.exists():
                if not target_path.exists():
                    with contextlib.suppress(OSError):
                        target_backup.rename(target_path)
                    rollback_ok = rollback_ok and target_path.exists()
                else:
                    rollback_ok = False

            apply_results.append(
                {
                    "source_path": str(source_path),
                    "target_path": str(target_path),
                    "status": "failed",
                    "error": str(e),
                    "rollback_ok": rollback_ok,
                }
            )

    final_by_status: dict[str, list[dict[str, Any]]] = {}
    for result_row in apply_results:
        final_by_status.setdefault(result_row["status"], []).append(result_row)

    summary = {
        "selected": len(selected_items),
        "success": len(final_by_status.get("success", [])),
        "dry_run": len(final_by_status.get("dry_run", [])),
        "failed": len(final_by_status.get("failed", [])),
    }

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "plan_path": str(plan_path),
        "dry_run": dry_run,
        "policy": policy.as_dict(),
        "canary": {
            "strategy": canary_strategy,
            "requested_size": canary_size,
            "selected_size": len(selected_items),
        },
        "summary": summary,
        "warnings": {
            "suspicious_changes_count": len(suspicious_changes),
            "suspicious_changes": suspicious_changes,
            "duplicate_asin_groups": duplicate_asin_groups,
        },
        "by_status": final_by_status,
        "results": apply_results,
    }


# =============================================================================
# Report Generation
# =============================================================================


def generate_report(
    results: list[RenameResult],
    candidates: list[RenameCandidate],
    summary: RenameSummary,
    output_path: Path,
    *,
    source_dir: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Generate JSON report of rename operations.

    Args:
        results: List of rename results
        candidates: List of candidates (for ASIN info)
        summary: Summary statistics
        output_path: Path to write JSON report
        source_dir: Source directory scanned
        dry_run: Whether this was a dry run
    """
    from datetime import UTC, datetime

    # Collect duplicate ASIN groups for debugging
    asin_to_folders: dict[str, list[str]] = {}
    for candidate in candidates:
        if candidate.parsed and candidate.parsed.asin:
            asin = candidate.parsed.asin
            if asin not in asin_to_folders:
                asin_to_folders[asin] = []
            asin_to_folders[asin].append(candidate.current_name)
    duplicate_groups = {k: v for k, v in asin_to_folders.items() if len(v) > 1}

    # Build results with full candidate info for debugging
    result_items = []
    for result, candidate in zip(results, candidates, strict=False):
        # Calculate similarity if we have both names
        # similarity_ratio already returns 0-100
        sim_score = None
        if candidate.target_name and candidate.current_name:
            sim_score = round(similarity_ratio(candidate.current_name, candidate.target_name), 1)

        item: dict[str, object] = {
            "source_path": str(result.source_path),
            "source_name": result.source_path.name,
            "target_name": result.target_path.name if result.target_path else None,
            "target_path": str(result.target_path) if result.target_path else None,
            "status": result.status,
            "error": result.error,
            "files_renamed": result.files_renamed,
            # ASIN info
            "asin": candidate.parsed.asin if candidate.parsed else None,
            "asin_source": candidate.asin_source,
            # Parsed metadata for debugging
            "parsed": {
                "author": candidate.parsed.author if candidate.parsed else None,
                "series": candidate.parsed.series if candidate.parsed else None,
                "series_position": candidate.parsed.series_position if candidate.parsed else None,
                "title": candidate.parsed.title if candidate.parsed else None,
                "year": candidate.parsed.year if candidate.parsed else None,
            }
            if candidate.parsed
            else None,
            # ABS metadata if available
            "abs_metadata": {
                "title": candidate.abs_metadata.title if candidate.abs_metadata else None,
                "authors": candidate.abs_metadata.authors if candidate.abs_metadata else None,
                "series": candidate.abs_metadata.series if candidate.abs_metadata else None,
            }
            if candidate.abs_metadata
            else None,
            # Warnings for debugging
            "similarity_percent": sim_score,
            "is_suspicious_change": sim_score is not None and sim_score < 30,
        }
        result_items.append(item)

    # Separate results by status for easier review
    by_status: dict[str, list[dict[str, object]]] = {}
    for item in result_items:
        status = str(item["status"])
        if status not in by_status:
            by_status[status] = []
        by_status[status].append(item)

    # Find suspicious changes (low similarity)
    suspicious = [r for r in result_items if r.get("is_suspicious_change")]

    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "source_dir": str(source_dir) if source_dir else None,
        "dry_run": dry_run,
        "summary": {
            "total": summary.total_candidates,
            "renamed": summary.renamed,
            "skipped_up_to_date": summary.skipped_up_to_date,
            "skipped_missing_asin": summary.skipped_missing_asin,
            "skipped_duplicate_asin": summary.skipped_duplicate_asin,
            "skipped_target_exists": summary.skipped_target_exists,
            "errors": summary.errors,
        },
        # Debugging sections
        "warnings": {
            "suspicious_changes_count": len(suspicious),
            "suspicious_changes": suspicious,
            "duplicate_asin_groups": duplicate_groups,
        },
        # Results grouped by status
        "by_status": by_status,
        # Full results list
        "results": result_items,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    logger.info(f"Report written to {output_path}")

    return report


def generate_html_report(
    report_data: dict[str, Any],
    output_path: Path,
) -> None:
    """Generate an HTML report from the JSON report data.

    Uses Jinja2 templating to create a visually appealing HTML report
    with collapsible sections, search/filter, and status indicators.

    Args:
        report_data: The report dictionary (from generate_report)
        output_path: Path to write HTML report
    """
    from importlib.resources import files

    try:
        from jinja2 import Environment, FileSystemLoader
    except ImportError:
        logger.warning("jinja2 not installed, skipping HTML report generation")
        return

    # Load template
    template_dir = files("shelfr.templates")
    # Get the actual path for FileSystemLoader
    template_path = Path(str(template_dir))

    if not template_path.exists():
        # Fallback: try relative to this file
        template_path = Path(__file__).parent.parent / "templates"

    if not template_path.exists():
        logger.warning(f"Template directory not found: {template_path}")
        return

    env = Environment(
        loader=FileSystemLoader(str(template_path)),
        autoescape=True,
    )

    # Add custom filter to classify duplicate types
    def classify_duplicate(folders: list[str]) -> dict[str, str]:
        """Classify the type of duplicate ASIN."""
        if any("xHE" in f or "[126]" in f for f in folders):
            return {"class": "codec", "label": "Codec Variant"}
        if any("Dolby Atmos" in f for f in folders):
            return {"class": "edition", "label": "Edition Variant"}
        if any("[H2OKing]" in f for f in folders) and any("[H2OKing]" not in f for f in folders):
            return {"class": "ripper-tag", "label": "Ripper Tag"}
        # Check for different volume numbers (wrong ASIN)
        vol_numbers = set()
        for f in folders:
            match = re.search(r"vol[_\s]*(\d+)", f, re.IGNORECASE)
            if match:
                vol_numbers.add(match.group(1))
        if len(vol_numbers) > 1:
            return {"class": "wrong-asin", "label": "WRONG ASIN"}
        return {"class": "", "label": "Duplicate"}

    env.globals["classify_duplicate"] = classify_duplicate  # pyright: ignore[reportArgumentType]

    try:
        template = env.get_template("rename_report.html")
    except Exception as e:
        logger.warning(f"Failed to load HTML template: {e}")
        return

    # Render template
    html_content = template.render(
        timestamp=report_data.get("timestamp", ""),
        source_dir=report_data.get("source_dir", ""),
        dry_run=report_data.get("dry_run", False),
        summary=report_data.get("summary", {}),
        warnings=report_data.get("warnings", {}),
        by_status=report_data.get("by_status", {}),
        results=report_data.get("results", []),
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    logger.info(f"HTML report written to {output_path}")
