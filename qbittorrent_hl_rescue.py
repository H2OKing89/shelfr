#!/usr/bin/env python3
"""
qBittorrent Hardlink Rescue Tool

Two-phase tool for recovering missing torrent files:

Phase 1 (--plan): Sanity scan
  - Index all video files in qBittorrent download directory
  - For each torrent with missing files:
    - Check if file exists elsewhere in qBit tree (path mismatch)
    - If not found in qBit, lazily index Plex and search there
  - Output comprehensive analysis + rescue plan JSON

Phase 2 (--execute): Hardlink reconstruction
  - Read rescue plan from Phase 1
  - For each high-confidence match, create hardlink
  - Only acts on same-device files, never overwrites

Safety: Default is dry-run. Use --apply to actually create hardlinks.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import orjson
import qbittorrentapi
from dotenv import load_dotenv
from rapidfuzz import fuzz

# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load environment variables
# .env path detection - check multiple locations
env_path = Path(__file__).parent / "config" / ".env"
if not env_path.exists():
    env_path = Path(__file__).parent.parent / "config" / ".env"
load_dotenv(env_path)

# Paths
SCRIPT_DIR = Path(__file__).parent
ANALYSIS_JSON = SCRIPT_DIR / "qbittorrent_missing_files_analysis.json"
RESCUE_PLAN_JSON = SCRIPT_DIR / "qbittorrent_missing_rescue_plan.json"

# qBittorrent config
QB_HOST = os.getenv("QB_HOST", "http://localhost:8083")
QB_USERNAME = os.getenv("QB_USERNAME", "admin")
QB_PASSWORD = os.getenv("QB_PASSWORD", "adminadmin")
HOST_PATH = os.getenv("HOST_PATH", "/mnt/user/data/")
CONTAINER_PATH = os.getenv("CONTAINER_PATH", "/data/")

# Root directories (configurable via env)
QBIT_ROOT = Path(os.getenv("QBIT_ROOT", "/mnt/user/data/downloads/torrents/qbittorrent"))

# Plex media directories
PLEX_DIRS = {
    "movies": Path("/mnt/user/data/videos/movies"),
    "anime-movies": Path("/mnt/user/data/videos/anime-movies"),
    "tv-shows": Path("/mnt/user/data/videos/tv-shows"),
    "anime-shows": Path("/mnt/user/data/videos/anime-shows"),
}

# Video file extensions to index
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".m4v", ".wmv", ".ts", ".m2ts"}

# Metadata caches to avoid repeated regex parsing
FOLDER_META_CACHE: dict[str, dict[str, Any]] = {}
TORRENT_META_CACHE: dict[str, dict[str, Any]] = {}


# ═══════════════════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class RescueOp:
    """A single hardlink rescue operation."""

    torrent_hash: str
    torrent_name: str
    category: str
    file_index: int
    torrent_path: str  # Where qBit expects the file (destination)
    source_path: str  # Where the file actually is (source for hardlink)
    source_kind: str  # "qbittorrent" or "plex"
    size: int
    score: float
    match_reason: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "torrent_hash": self.torrent_hash,
            "torrent_name": self.torrent_name,
            "category": self.category,
            "file_index": self.file_index,
            "torrent_path": self.torrent_path,
            "source_path": self.source_path,
            "source_kind": self.source_kind,
            "size": self.size,
            "score": self.score,
            "match_reason": self.match_reason,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Path Utilities
# ═══════════════════════════════════════════════════════════════════════════════


def container_to_host_path(container_path: str) -> Path:
    """Convert Docker container path to host path."""
    container_path = str(container_path)
    if container_path.startswith(CONTAINER_PATH):
        relative = container_path[len(CONTAINER_PATH) :].lstrip("/")
        return Path(HOST_PATH) / relative
    return Path(container_path)


def same_inode(path_a: Path, path_b: Path) -> bool:
    """Check if two paths refer to the same inode on disk."""
    try:
        a = path_a.stat()
        b = path_b.stat()
    except FileNotFoundError:
        return False
    return a.st_dev == b.st_dev and a.st_ino == b.st_ino


def ensure_same_device(src: Path, dest_path: Path) -> bool:
    """Ensure src and dest parent live on same device before link."""
    try:
        src_dev = src.stat().st_dev
    except FileNotFoundError:
        return False

    # Walk up until we find an existing parent (in case dest dirs don't exist yet)
    check_path = dest_path.parent
    while not check_path.exists() and check_path != check_path.parent:
        check_path = check_path.parent

    if not check_path.exists():
        return False

    try:
        dest_dev = check_path.stat().st_dev
    except FileNotFoundError:
        return False

    return src_dev == dest_dev


# ═══════════════════════════════════════════════════════════════════════════════
# Metadata Extraction
# ═══════════════════════════════════════════════════════════════════════════════


def extract_metadata_from_name(name: str) -> dict[str, Any]:
    """Extract year, IMDB/TMDB IDs, and clean name from torrent/folder name."""
    metadata: dict[str, Any] = {
        "year": None,
        "imdb_id": None,
        "tmdb_id": None,
        "clean_name": name,
    }

    # Extract year (4 digits)
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", name)
    if year_match:
        metadata["year"] = int(year_match.group(1))

    # Extract IMDB ID
    imdb_match = re.search(r"\{?imdb-?(tt\d+)\}?", name, re.IGNORECASE)
    if imdb_match:
        metadata["imdb_id"] = imdb_match.group(1)

    # Extract TMDB ID
    tmdb_match = re.search(r"\{?tmdb-?(\d+)\}?", name, re.IGNORECASE)
    if tmdb_match:
        metadata["tmdb_id"] = tmdb_match.group(1)

    # Clean name - remove resolution, codec, release group, etc.
    clean = name
    patterns_to_remove = [
        r"\b(19\d{2}|20\d{2})\b",
        r"\b(480|576|720|1080|2160)p?\b",
        r"\b(HDTV|WEB-?DL|WEBRip|BluRay|BDRip|DVDRip|REMUX)\b",
        r"\b(x264|x265|H\.?264|H\.?265|HEVC|AVC)\b",
        r"\b(DTS(-HD)?|DD(P)?|TrueHD|AAC|AC3|FLAC|MA)[\s\.\d]*",
        r"\b(Atmos|5\.1|7\.1|2\.0)\b",
        r"\b(HDR|DV|SDR|10bit|8bit)\b",
        r"\{imdb-tt\d+\}",
        r"\{tmdb-\d+\}",
        r"-[A-Z][a-zA-Z]+$",
        r"\[.*?\]",
    ]
    for pattern in patterns_to_remove:
        clean = re.sub(pattern, "", clean, flags=re.IGNORECASE)

    clean = re.sub(r"[._]+", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    metadata["clean_name"] = clean

    return metadata


def get_folder_metadata(folder_name: str) -> dict[str, Any]:
    """Get metadata for folder, using cache to avoid repeated regex parsing."""
    if folder_name not in FOLDER_META_CACHE:
        FOLDER_META_CACHE[folder_name] = extract_metadata_from_name(folder_name)
    return FOLDER_META_CACHE[folder_name]


def get_torrent_metadata(torrent_name: str) -> dict[str, Any]:
    """Get metadata for torrent name, using cache to avoid repeated regex parsing."""
    if torrent_name not in TORRENT_META_CACHE:
        TORRENT_META_CACHE[torrent_name] = extract_metadata_from_name(torrent_name)
    return TORRENT_META_CACHE[torrent_name]


# ═══════════════════════════════════════════════════════════════════════════════
# File Indexing (shared for qBit and Plex)
# ═══════════════════════════════════════════════════════════════════════════════


def build_file_index(
    root: Path, label: str, extensions: set[str] | None = None
) -> dict[int, list[dict[str, Any]]]:
    """
    Build an index of files by size for fast lookup.

    Args:
        root: Directory to scan recursively
        label: Label for logging ("qbittorrent" or "plex")
        extensions: Optional set of extensions to include (e.g., {'.mkv', '.mp4'})

    Returns:
        Dict mapping file size -> list of file info dicts
    """
    logger.info(f"Indexing {label} under {root} ...")
    index: dict[int, list[dict[str, Any]]] = defaultdict(list)
    total = 0

    # Generic folder names that shouldn't be used for metadata
    generic_folders = {
        "season 01",
        "season 02",
        "season 03",
        "season 04",
        "season 05",
        "season 06",
        "season 07",
        "season 08",
        "season 09",
        "season 10",
        "season 1",
        "season 2",
        "season 3",
        "season 4",
        "season 5",
        "specials",
        "extras",
        "featurettes",
        "behind the scenes",
        "radarr",
        "sonarr",
        "completed",
        "downloading",
    }

    if not root.exists():
        logger.warning(f"{label} root does not exist: {root}")
        return index

    try:
        for path in root.rglob("*"):
            if not path.is_file():
                continue

            # Filter by extension if specified
            if extensions and path.suffix.lower() not in extensions:
                continue

            try:
                stat = path.stat()
                size = stat.st_size
            except (OSError, PermissionError):
                continue

            # Smart metadata merge: pull from file, folder, and series folder
            folder = path.parent
            file_meta = extract_metadata_from_name(path.name)
            folder_meta = get_folder_metadata(folder.name)

            # Try to pull series-level metadata from parent-of-parent
            # e.g., "7Seeds (2019) {imdb-tt...}" / "Season 01" / "episode.mkv"
            series_meta: dict[str, Any] = {
                "year": None,
                "imdb_id": None,
                "tmdb_id": None,
                "clean_name": None,
            }
            if folder.parent != root and folder.parent.parent != root:
                series_meta = get_folder_metadata(folder.parent.name)

            # Start with folder metadata, overlay series, then file-level hints
            metadata = dict(folder_meta)
            for key in ("year", "imdb_id", "tmdb_id"):
                # Prefer series metadata over generic folder
                if not metadata.get(key) and series_meta.get(key):
                    metadata[key] = series_meta[key]
                # Fall back to file name metadata (e.g., lone files in "radarr/")
                if not metadata.get(key) and file_meta.get(key):
                    metadata[key] = file_meta[key]

            # Prefer series/file clean_name if folder is generic like "Season 01"
            if (metadata.get("clean_name") or "").lower() in generic_folders:
                metadata["clean_name"] = (
                    series_meta.get("clean_name")
                    or file_meta.get("clean_name")
                    or folder_meta.get("clean_name")
                )

            index[size].append(
                {
                    "path": str(path),
                    "name": path.name,
                    "folder": folder.name,
                    "size": size,
                    "label": label,
                    "metadata": metadata,
                }
            )
            total += 1

            if total and total % 5000 == 0:
                logger.info(f"  {label}: indexed {total} files ...")

    except Exception as e:
        logger.warning(f"Error indexing {label}: {e}")

    logger.info(f"Finished indexing {label}: {total} files, {len(index)} unique sizes")
    return index


def build_plex_index() -> dict[int, list[dict[str, Any]]]:
    """Build combined index of all Plex directories."""
    logger.info("Building Plex file index...")
    combined: dict[int, list[dict[str, Any]]] = defaultdict(list)

    for category, plex_dir in PLEX_DIRS.items():
        if not plex_dir.exists():
            logger.warning(f"Plex directory not found: {plex_dir} ({category})")
            continue

        index = build_file_index(plex_dir, f"plex/{category}", VIDEO_EXTENSIONS)
        for size, files in index.items():
            for f in files:
                f["plex_category"] = category
            combined[size].extend(files)

    total_files = sum(len(files) for files in combined.values())
    logger.info(f"Total Plex files indexed: {total_files}")
    return combined


# ═══════════════════════════════════════════════════════════════════════════════
# Search Functions
# ═══════════════════════════════════════════════════════════════════════════════


def search_index_for_file(
    file_name: str,
    size: int,
    index: dict[int, list[dict[str, Any]]],
    torrent_name: str = "",
    *,
    threshold: int = 80,
    size_tolerance: float = 0.0,
) -> dict[str, Any] | None:
    """
    Find a candidate file by size + fuzzy name match in a prebuilt index.

    Args:
        file_name: Name of the file we're looking for
        size: Expected file size in bytes
        index: Prebuilt file index (size -> list of files)
        torrent_name: Torrent name for additional metadata matching
        threshold: Minimum fuzzy match score (0-100)
        size_tolerance: Allow size mismatch within this fraction (0.01 = 1%)

    Returns:
        Best matching file info dict with 'score' added, or None
    """
    if size <= 0:
        return None

    # Gather candidates by size
    candidates: list[dict[str, Any]] = []
    if size in index:
        candidates.extend(index[size])

    if size_tolerance > 0:
        delta = int(size * size_tolerance)
        # Iterate over index keys (O(unique_sizes)) instead of byte range (O(billions))
        for s, files in index.items():
            if s != size and abs(s - size) <= delta:
                candidates.extend(files)

    if not candidates:
        return None

    # Extract metadata for matching (use cached version)
    torrent_meta = get_torrent_metadata(torrent_name) if torrent_name else {}
    file_stem = Path(file_name).stem.lower()

    best = None
    best_score = 0.0
    best_reasons: list[str] = []

    for c in candidates:
        score = 0.0
        reasons: list[str] = []

        cand_stem = Path(c["name"]).stem.lower()
        folder = c.get("folder", "").lower()
        cand_meta = c.get("metadata", {})

        # Cheap substring check before expensive fuzzy operations
        # Skip candidates with no textual overlap
        has_overlap = (
            file_stem in cand_stem
            or cand_stem in file_stem
            or file_stem in folder
            or folder in file_stem
        )

        # Even if no substring overlap, still check if metadata matches (IMDB/TMDB)
        has_metadata_potential = (
            (torrent_meta.get("imdb_id") and cand_meta.get("imdb_id"))
            or (torrent_meta.get("tmdb_id") and cand_meta.get("tmdb_id"))
            or (torrent_meta.get("year") and cand_meta.get("year"))
        )

        if not has_overlap and not has_metadata_potential:
            continue

        # Name similarity scoring (only do fuzzy if we passed the cheap check)
        name_scores = [
            fuzz.ratio(file_stem, cand_stem),
            fuzz.partial_ratio(file_stem, cand_stem),
            fuzz.ratio(file_stem, folder),
            fuzz.partial_ratio(file_stem, folder),
        ]
        name_score = max(name_scores)
        score += name_score
        if name_score >= 80:
            reasons.append("name_match")

        # Metadata bonuses (matching hunt_missing_files.py scoring)
        if (
            torrent_meta.get("year")
            and cand_meta.get("year")
            and torrent_meta["year"] == cand_meta["year"]
        ):
            score += 50  # Strong signal
            reasons.append("year_match")

        if (
            torrent_meta.get("imdb_id")
            and cand_meta.get("imdb_id")
            and torrent_meta["imdb_id"].lower() == cand_meta["imdb_id"].lower()
        ):
            score += 200  # Very strong signal - IMDB ID match is nearly certain
            reasons.append("imdb_match")

        if (
            torrent_meta.get("tmdb_id")
            and cand_meta.get("tmdb_id")
            and torrent_meta["tmdb_id"] == cand_meta["tmdb_id"]
        ):
            score += 200  # Very strong signal
            reasons.append("tmdb_match")

        # Exact size bonus
        if c["size"] == size:
            score += 20
            reasons.append("exact_size")

        if score > best_score:
            best_score = score
            best = c
            best_reasons = reasons

            # Early exit for perfect matches - don't waste time on remaining candidates
            # A perfect match: exact size + (IMDB or TMDB match) + good name score
            if (
                "exact_size" in reasons
                and ("imdb_match" in reasons or "tmdb_match" in reasons)
                and name_score >= 80
            ):
                break

    # Apply dynamic threshold based on metadata presence
    # If we have IMDB/TMDB match, accept lower name similarity (matching hunt_missing_files.py)
    has_metadata_match = best_reasons and any(
        r in best_reasons for r in ("imdb_match", "tmdb_match")
    )
    effective_threshold = 150 if has_metadata_match else threshold

    if best and best_score >= effective_threshold:
        result = dict(best)
        result["score"] = float(best_score)
        result["match_reasons"] = best_reasons
        return result

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1: Plan Generation
# ═══════════════════════════════════════════════════════════════════════════════


def generate_plan(
    filter_state: str | None = "missingFiles",
    filter_tag: str | None = None,
) -> tuple[dict[str, Any], list[RescueOp]]:
    """
    Phase 1: Scan qBittorrent and Plex to generate rescue plan.

    Args:
        filter_state: Only process torrents in this state (e.g., "missingFiles")
        filter_tag: Only process torrents with this tag (e.g., "noHL")

    Returns:
        (analysis_data, rescue_ops)
    """
    logger.info("=" * 70)
    logger.info("PHASE 1: Generating Rescue Plan")
    logger.info("=" * 70)

    # Connect to qBittorrent
    logger.info(f"Connecting to qBittorrent at {QB_HOST}")
    try:
        qbt = qbittorrentapi.Client(
            host=QB_HOST,
            username=QB_USERNAME,
            password=QB_PASSWORD,
        )
        qbt.auth_log_in()
        logger.info(f"Connected! Version: {qbt.app.version}")
    except Exception as e:
        logger.error(f"Failed to connect to qBittorrent: {e}")
        return {}, []

    # Get torrents
    logger.info("Fetching torrents...")
    all_torrents = qbt.torrents_info()
    logger.info(f"Found {len(all_torrents)} total torrents")

    # Filter torrents
    torrents = all_torrents
    if filter_state:
        torrents = [t for t in torrents if t.state.lower() == filter_state.lower()]
        logger.info(f"Filtered to {len(torrents)} torrents with state '{filter_state}'")

    if filter_tag:
        torrents = [t for t in torrents if filter_tag in (t.tags or "")]
        logger.info(f"Filtered to {len(torrents)} torrents with tag '{filter_tag}'")

    if not torrents:
        logger.info("No torrents to process!")
        return {"summary": {"total": 0}}, []

    # Build qBit index (Plex is lazy-loaded only if needed)
    logger.info("\n" + "=" * 70)
    # Filter qBit index to video files only (skip .nfo, .srt, .jpg, etc)
    qbit_index = build_file_index(QBIT_ROOT, "qbittorrent", VIDEO_EXTENSIONS)
    plex_index: dict[int, list[dict[str, Any]]] | None = None  # lazy-load
    logger.info("=" * 70 + "\n")

    # Process torrents
    rescue_ops: list[RescueOp] = []
    analysis_results: list[dict[str, Any]] = []

    stats = {
        "total_torrents": len(torrents),
        "total_files": 0,
        "files_exist": 0,
        "files_missing": 0,
        "found_in_qbit": 0,
        "found_in_plex": 0,
        "not_found": 0,
    }

    for i, torrent in enumerate(torrents, 1):
        logger.info(f"[{i}/{len(torrents)}] {torrent.name[:60]}...")

        # Get torrent files
        try:
            files = qbt.torrents_files(torrent_hash=torrent.hash)
        except Exception as e:
            logger.warning(f"  Failed to get files: {e}")
            continue

        torrent_data = {
            "name": torrent.name,
            "hash": torrent.hash,
            "state": torrent.state,
            "category": torrent.category or "uncategorized",
            "tags": torrent.tags,
            "save_path": torrent.save_path,
            "size": torrent.size,
            "files": [],
        }

        for f in files:
            stats["total_files"] += 1

            # Build expected host path
            file_rel_path = f.name
            container_path = str(Path(torrent.save_path) / file_rel_path)
            host_path = container_to_host_path(container_path)

            file_data: dict[str, Any] = {
                "index": f.index,
                "name": f.name,
                "size": f.size,
                "host_path": str(host_path),
                "exists": host_path.exists(),
                "recovery_phase": "none",
                "qbit_candidate": None,
                "plex_candidate": None,
            }

            if file_data["exists"]:
                stats["files_exist"] += 1
                file_data["recovery_phase"] = "none"
            else:
                stats["files_missing"] += 1

                # Phase 1a: Check if file exists elsewhere in qBit tree
                qbit_match = search_index_for_file(
                    f.name,
                    f.size,
                    qbit_index,
                    torrent.name,
                    threshold=70,  # Lower threshold for qBit tree (same content)
                )

                if qbit_match:
                    stats["found_in_qbit"] += 1
                    file_data["recovery_phase"] = "qbit_relink"
                    file_data["qbit_candidate"] = {
                        "path": qbit_match["path"],
                        "score": qbit_match["score"],
                        "reasons": qbit_match.get("match_reasons", []),
                    }

                    rescue_ops.append(
                        RescueOp(
                            torrent_hash=torrent.hash,
                            torrent_name=torrent.name,
                            category=torrent.category or "uncategorized",
                            file_index=f.index,
                            torrent_path=str(host_path),
                            source_path=qbit_match["path"],
                            source_kind="qbittorrent",
                            size=f.size,
                            score=qbit_match["score"],
                            match_reason=qbit_match.get("match_reasons", []),
                        )
                    )
                else:
                    # Phase 1b: Check Plex (names will be different - Radarr/Sonarr renamed)
                    # Lazy-load Plex index on first need
                    if plex_index is None:
                        logger.info("Building Plex index (first Plex lookup needed)...")
                        plex_index = build_plex_index()
                    assert plex_index is not None  # mypy: we just built it

                    plex_match = search_index_for_file(
                        f.name,
                        f.size,
                        plex_index,
                        torrent.name,
                        threshold=70,  # Dynamic threshold kicks in for metadata matches
                        size_tolerance=0.01,  # Allow 1% size tolerance
                    )

                    if plex_match:
                        reasons = set(plex_match.get("match_reasons", []))

                        # Drop risky year-only Plex matches from the plan itself
                        # These are likely false positives (e.g., Blade II matching Goldmember)
                        if reasons == {"year_match"}:
                            logger.debug("  Weak Plex match (year-only) → treating as not_found")
                            stats["not_found"] += 1
                            file_data["recovery_phase"] = "not_found"
                            file_data["plex_candidate"] = {
                                "path": plex_match["path"],
                                "score": plex_match["score"],
                                "reasons": plex_match.get("match_reasons", []),
                                "plex_category": plex_match.get("plex_category"),
                                "rejected": "year_only_match",
                            }
                        else:
                            stats["found_in_plex"] += 1
                            file_data["recovery_phase"] = "plex_rebuild"
                            file_data["plex_candidate"] = {
                                "path": plex_match["path"],
                                "score": plex_match["score"],
                                "reasons": plex_match.get("match_reasons", []),
                                "plex_category": plex_match.get("plex_category"),
                            }

                            rescue_ops.append(
                                RescueOp(
                                    torrent_hash=torrent.hash,
                                    torrent_name=torrent.name,
                                    category=torrent.category or "uncategorized",
                                    file_index=f.index,
                                    torrent_path=str(host_path),
                                    source_path=plex_match["path"],
                                    source_kind="plex",
                                    size=f.size,
                                    score=plex_match["score"],
                                    match_reason=plex_match.get("match_reasons", []),
                                )
                            )
                    else:
                        stats["not_found"] += 1
                        file_data["recovery_phase"] = "not_found"

            torrent_data["files"].append(file_data)

        # Log summary for this torrent
        missing = sum(1 for f in torrent_data["files"] if not f["exists"])
        qbit_found = sum(1 for f in torrent_data["files"] if f["recovery_phase"] == "qbit_relink")
        plex_found = sum(1 for f in torrent_data["files"] if f["recovery_phase"] == "plex_rebuild")

        if missing > 0:
            logger.info(
                f"  Missing: {missing} | Found in qBit: {qbit_found} | Found in Plex: {plex_found}"
            )

        analysis_results.append(torrent_data)

    # Build final analysis
    analysis = {
        "summary": stats,
        "rescue_ops_count": len(rescue_ops),
        "torrents": analysis_results,
    }

    # Log summary
    logger.info("\n" + "=" * 70)
    logger.info("PHASE 1 SUMMARY")
    logger.info("=" * 70)
    logger.info(f"Total torrents processed: {stats['total_torrents']}")
    logger.info(f"Total files checked: {stats['total_files']}")
    logger.info(f"  Files exist: {stats['files_exist']}")
    logger.info(f"  Files missing: {stats['files_missing']}")
    logger.info(f"    → Found in qBit tree: {stats['found_in_qbit']}")
    logger.info(f"    → Found in Plex: {stats['found_in_plex']}")
    logger.info(f"    → Not found anywhere: {stats['not_found']}")
    logger.info(f"\nTotal rescue operations: {len(rescue_ops)}")
    logger.info("=" * 70)

    return analysis, rescue_ops


def save_plan(analysis: dict[str, Any], rescue_ops: list[RescueOp]) -> None:
    """Save analysis and rescue plan to JSON files."""
    # Save full analysis
    logger.info(f"Saving analysis to: {ANALYSIS_JSON}")
    with open(ANALYSIS_JSON, "wb") as f:
        f.write(orjson.dumps(analysis, option=orjson.OPT_INDENT_2))

    # Save rescue plan (just the operations)
    plan_data = {
        "summary": {
            "total_operations": len(rescue_ops),
            "by_source": {
                "qbittorrent": sum(1 for op in rescue_ops if op.source_kind == "qbittorrent"),
                "plex": sum(1 for op in rescue_ops if op.source_kind == "plex"),
            },
            "by_category": {},
        },
        "operations": [op.to_dict() for op in rescue_ops],
    }

    # Count by category
    for op in rescue_ops:
        cat = op.category
        plan_data["summary"]["by_category"][cat] = (
            plan_data["summary"]["by_category"].get(cat, 0) + 1
        )

    logger.info(f"Saving rescue plan to: {RESCUE_PLAN_JSON}")
    with open(RESCUE_PLAN_JSON, "wb") as f:
        f.write(orjson.dumps(plan_data, option=orjson.OPT_INDENT_2))

    logger.info("✓ Plan files saved")


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2: Execute Rescue Plan
# ═══════════════════════════════════════════════════════════════════════════════


def execute_plan(
    plan_path: Path,
    *,
    min_score: float = 120.0,
    dry_run: bool = True,
) -> None:
    """
    Phase 2: Execute hardlink rescue operations from plan file.

    Args:
        plan_path: Path to rescue plan JSON
        min_score: Minimum match score required to create hardlink
        dry_run: If True, only log what would be done
    """
    logger.info("=" * 70)
    logger.info("PHASE 2: Execute Rescue Plan")
    logger.info("=" * 70)
    logger.info(f"Plan file: {plan_path}")
    logger.info(f"Min score: {min_score}")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'APPLY'}")
    logger.info("=" * 70)

    if not plan_path.exists():
        logger.error(f"Plan file not found: {plan_path}")
        return

    # Load plan
    data = orjson.loads(plan_path.read_bytes())
    ops = [RescueOp(**op) for op in data.get("operations", [])]
    logger.info(f"Loaded {len(ops)} rescue operations")

    # Track stats
    applied = 0
    skipped_score = 0
    skipped_src_missing = 0
    skipped_dest_exists = 0
    skipped_already_linked = 0
    skipped_cross_device = 0
    skipped_weak_plex = 0  # year-only Plex matches
    failed = 0
    total_bytes = 0

    for i, op in enumerate(ops, 1):
        src = Path(op.source_path)
        dest = Path(op.torrent_path)

        prefix = f"[{i}/{len(ops)}]"
        reasons = set(op.match_reason)

        # Extra guardrail: reject weak Plex matches (year-only)
        # Defense in depth - these shouldn't be in the plan, but block them anyway
        if op.source_kind == "plex" and reasons == {"year_match"}:
            logger.warning(f"{prefix} Skip (Plex year-only match): {dest.name}")
            skipped_weak_plex += 1
            continue

        # Check score threshold
        if op.score < min_score:
            logger.debug(f"{prefix} Skip (score {op.score:.1f} < {min_score}): {dest.name}")
            skipped_score += 1
            continue

        # Check source exists
        if not src.exists():
            logger.warning(f"{prefix} Skip (source missing): {src}")
            skipped_src_missing += 1
            continue

        # Check dest doesn't exist (or is already linked)
        if dest.exists():
            if same_inode(src, dest):
                logger.debug(f"{prefix} Skip (already linked): {dest.name}")
                skipped_already_linked += 1
            else:
                logger.warning(f"{prefix} Skip (dest exists, different file): {dest}")
                skipped_dest_exists += 1
            continue

        # Check same device
        if not ensure_same_device(src, dest):
            logger.warning(f"{prefix} Skip (cross-device): {src} -> {dest}")
            skipped_cross_device += 1
            continue

        # Execute!
        if dry_run:
            logger.info(f"{prefix} [DRY] Would link: {dest.name}")
            logger.info(f"        src: {src}")
            logger.info(f"        dst: {dest}")
        else:
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                os.link(src, dest)
                logger.info(f"{prefix} [OK] Linked: {dest.name}")
            except Exception as e:
                logger.error(f"{prefix} [FAIL] {e}: {dest}")
                failed += 1
                continue

        applied += 1
        total_bytes += op.size

    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("PHASE 2 SUMMARY")
    logger.info("=" * 70)
    if dry_run:
        logger.info("DRY RUN - no changes made")
        logger.info(f"Would create: {applied} hardlinks ({total_bytes / 1e9:.2f} GB)")
    else:
        logger.info(f"Hardlinks created: {applied} ({total_bytes / 1e9:.2f} GB)")
        logger.info(f"Failed: {failed}")
    logger.info("Skipped:")
    logger.info(f"  Score below {min_score}: {skipped_score}")
    logger.info(f"  Source missing: {skipped_src_missing}")
    logger.info(f"  Dest exists (different): {skipped_dest_exists}")
    logger.info(f"  Already linked: {skipped_already_linked}")
    logger.info(f"  Cross-device: {skipped_cross_device}")
    logger.info(f"  Weak Plex (year-only): {skipped_weak_plex}")
    logger.info("=" * 70)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="qbittorrent-hl-rescue",
        description="Scan qBittorrent + Plex to plan or execute hardlink repairs.",
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Phase 1: Scan and generate rescue plan (no changes made)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Phase 2: Execute hardlink operations from rescue plan",
    )
    parser.add_argument(
        "--plan-file",
        type=Path,
        default=RESCUE_PLAN_JSON,
        help=f"Path to rescue plan JSON (default: {RESCUE_PLAN_JSON})",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=120.0,
        help="Minimum match score to create hardlink (default: 120)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes (default for execute)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually make changes (required to disable dry-run for execute)",
    )
    parser.add_argument(
        "--filter-state",
        type=str,
        default="missingFiles",
        help="Only process torrents in this state (default: missingFiles)",
    )
    parser.add_argument(
        "--filter-tag",
        type=str,
        default=None,
        help="Only process torrents with this tag (e.g., 'noHL')",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose/debug logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if not args.plan and not args.execute:
        parser.print_help()
        logger.error("\nError: Must specify --plan or --execute")
        return 1

    if args.plan:
        analysis, rescue_ops = generate_plan(
            filter_state=args.filter_state,
            filter_tag=args.filter_tag,
        )
        if analysis:
            save_plan(analysis, rescue_ops)

    if args.execute:
        # --dry-run flag wins if explicitly set, otherwise default to dry-run unless --apply
        dry_run = args.dry_run or not args.apply
        if not dry_run:
            logger.warning("=" * 70)
            logger.warning("APPLY MODE - Files will be created!")
            logger.warning("=" * 70)
            response = input("Continue? [y/N]: ")
            if response.lower() != "y":
                logger.info("Aborted by user")
                return 0

        execute_plan(
            args.plan_file,
            min_score=args.min_score,
            dry_run=dry_run,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
