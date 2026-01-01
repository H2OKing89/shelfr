"""
mkbrr Docker wrapper for torrent creation.

Refactored from the interactive mkbrr wizard script to be fully automated.
Supports: create, inspect, check operations.
"""

from __future__ import annotations

import logging
import re
import shlex
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from shelfr.config import get_settings
from shelfr.utils.cmd import CmdError, CmdResult, run
from shelfr.utils.paths import host_to_container_data_path, host_to_container_torrent_path
from shelfr.utils.permissions import fix_directory_ownership
from shelfr.utils.retry import retry_with_backoff

if TYPE_CHECKING:
    from shelfr.schemas.mkbrr import CheckResult, TorrentInfo

logger = logging.getLogger(__name__)


@dataclass
class MkbrrResult:
    """Result of an mkbrr operation."""

    success: bool
    return_code: int
    torrent_path: Path | None = None
    error: str | None = None
    stdout: str = ""
    stderr: str = ""


def _docker_base_command() -> list[str]:
    """
    Build the common docker run prefix for all mkbrr commands.

    Sets up volume mounts for:
    - Data directory (/data)
    - Torrent output (/torrentfiles)
    - Config directory (presets.yaml)

    Note: We don't use `-it` flags because the sh library used for command
    execution doesn't properly pass through TTY, causing "input device is
    not a TTY" errors. Colors are handled by mkbrr's auto-detection.
    """
    settings = get_settings()
    mkbrr = settings.mkbrr

    return [
        settings.docker_bin,
        "run",
        "--rm",
        "-w",
        mkbrr.container_config_dir,
        "-v",
        f"{mkbrr.host_data_root}:{mkbrr.container_data_root}",
        "-v",
        f"{mkbrr.host_output_dir}:{mkbrr.container_output_dir}",
        "-v",
        f"{mkbrr.host_config_dir}:{mkbrr.container_config_dir}",
        mkbrr.image,
    ]


@retry_with_backoff(
    max_attempts=3,
    base_delay=2.0,
    max_delay=30.0,
    retry_exceptions=(CmdError, OSError, TimeoutError),
)
def _run_docker_command(
    cmd: list[str],
    timeout: int,
    capture_output: bool = True,
) -> CmdResult:
    """
    Run a Docker command with retry on transient failures.

    Args:
        cmd: Command and arguments to run
        timeout: Timeout in seconds
        capture_output: Whether to capture stdout/stderr (default: True)

    Returns:
        CmdResult with output and exit code

    Raises:
        CmdError: If command fails (after retries)
        OSError: If Docker daemon unreachable (after retries)
    """
    return run(
        cmd,
        timeout=timeout,
        ok_codes=(0, 1),  # mkbrr can return 1 for warnings
        capture_output=capture_output,
    )


def fix_torrent_permissions(root_dir: Path | str | None = None) -> int:
    """
    Recursively chown all .torrent and .json files to the target UID:GID.

    This fixes ownership after Docker creates files as root.
    Default ownership: Unraid's nobody:users (99:100)

    Args:
        root_dir: Directory to scan. Defaults to configured torrent output dir.

    Returns:
        Number of files fixed.
    """
    settings = get_settings()
    root_dir = Path(settings.mkbrr.host_output_dir) if root_dir is None else Path(root_dir)

    count = fix_directory_ownership(
        root_dir,
        settings.target_uid,
        settings.target_gid,
        recursive=True,
        file_extensions={".torrent", ".json"},
    )

    if count:
        logger.info(f"Fixed ownership on {count} item(s)")

    return count


def _cleanup_stale_torrents(output_dir: Path, content_name: str) -> int:
    """
    Remove existing torrents for content to prevent discovery race conditions.

    When we create a new torrent, we need to be certain we find the newly created
    file, not a stale one. This is especially important on filesystems with low
    mtime precision or during rapid re-runs.

    Args:
        output_dir: Directory to clean.
        content_name: Name of the content (folder/file name).

    Returns:
        Number of torrents removed.
    """
    patterns = [
        f"*{content_name}.torrent",  # With any prefix (e.g., "myanonamouse_")
        f"{content_name}.torrent",  # Without prefix
    ]

    removed = 0
    for pattern in patterns:
        for torrent in output_dir.glob(pattern):
            try:
                torrent.unlink()
                logger.debug(f"Removed stale torrent: {torrent}")
                removed += 1
            except OSError as e:
                logger.warning(f"Failed to remove stale torrent {torrent}: {e}")

    if removed:
        logger.info(f"Cleaned up {removed} stale torrent(s) before creation")

    return removed


def _find_torrent_deterministic(output_dir: Path, content_name: str) -> Path | None:
    """
    Find the torrent file for content with deterministic tie-breaking.

    Uses a two-level sort: mtime (newest first), then filename (alphabetically last).
    This ensures consistent results even when multiple files have identical mtimes.

    Args:
        output_dir: Directory to search.
        content_name: Name of the content (folder/file name).

    Returns:
        Path to the torrent file, or None if not found.
    """
    patterns = [
        f"*{content_name}.torrent",  # With any prefix
        f"{content_name}.torrent",  # Without prefix
    ]

    for pattern in patterns:
        matches = list(output_dir.glob(pattern))
        if matches:
            # Sort by: mtime descending (newest first), then name descending (for tie-break)
            # Using negative mtime for descending, reversed name for deterministic tie-break
            matches.sort(key=lambda p: (-p.stat().st_mtime, p.name), reverse=False)
            # After sort: first item is newest, and for same mtime, alphabetically last name
            # Actually let's use a clearer approach
            matches.sort(key=lambda p: (p.stat().st_mtime, p.name))
            return matches[-1]  # Take the last (newest mtime, then highest name)

    # Fallback: find any .torrent file with deterministic selection
    all_torrents = list(output_dir.glob("*.torrent"))
    if all_torrents:
        all_torrents.sort(key=lambda p: (p.stat().st_mtime, p.name))
        return all_torrents[-1]

    return None


def load_presets() -> list[str]:
    """
    Load available preset names from mkbrr's presets.yaml.

    Returns list of preset names, with configured default first.
    """
    settings = get_settings()
    presets_path = Path(settings.mkbrr.host_config_dir) / "presets.yaml"

    if not presets_path.exists():
        logger.warning(f"presets.yaml not found at {presets_path}")
        return [settings.mkbrr.preset]

    try:
        with open(presets_path, encoding="utf-8") as f:
            data: dict[str, object] = yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"Failed to parse {presets_path}: {e}")
        return [settings.mkbrr.preset]

    presets_node = data.get("presets") or {}

    if not isinstance(presets_node, dict) or not presets_node:
        logger.warning(f"No valid 'presets' mapping in {presets_path}")
        return [settings.mkbrr.preset]

    presets: list[str] = [str(k) for k in presets_node]

    # Put configured preset first
    default_preset = settings.mkbrr.preset
    if default_preset in presets:
        presets = [default_preset] + [p for p in presets if p != default_preset]

    return presets


def create_torrent(
    content_path: Path | str,
    output_dir: Path | str | None = None,
    preset: str | None = None,
    # NEW optional parameters for advanced torrent creation:
    output_filename: str | None = None,
    tracker: str | None = None,
    source: str | None = None,
    piece_length: int | None = None,
    max_piece_length: int | None = None,
    exclude_patterns: list[str] | None = None,
    include_patterns: list[str] | None = None,
    skip_prefix: bool = False,
    comment: str | None = None,
    private: bool | None = None,
    no_date: bool = False,
    no_creator: bool = False,
    web_seeds: list[str] | None = None,
    entropy: bool = False,
) -> MkbrrResult:
    """
    Create a .torrent file for the given content.

    Args:
        content_path: Path to file or directory to create torrent for.
        output_dir: Where to write .torrent file. Defaults to configured dir.
            Implementation: Uses Docker -w workdir to place output files there,
            preserving mkbrr's tracker prefix naming logic.
        preset: mkbrr preset name (-P). Defaults to configured preset.
        output_filename: Output filename (-o). If not set, mkbrr auto-generates
            with tracker domain prefix (unless skip_prefix is True).
        tracker: Tracker announce URL (-t). Overrides preset tracker.
        source: Source tag (-s). Overrides preset source.
        piece_length: Piece size exponent 16-27 (-l). e.g., 18 = 256KiB.
            Note: Tracker rules may override this for compliance.
        max_piece_length: Max piece size exponent 16-27 (-m).
            Note: Tracker rules may override this for compliance.
        exclude_patterns: Exclude file patterns (--exclude). Case-insensitive globs.
            Additive with preset patterns.
        include_patterns: Include file patterns (--include). Triggers whitelist mode.
            Only matching files are included. Additive with preset patterns.
        skip_prefix: Skip tracker domain prefix in output filename (--skip-prefix).
        comment: Torrent comment (-c).
        private: Set private flag (--private). Default True for most trackers.
        no_date: Omit creation date (--no-date).
        no_creator: Omit creator field (--no-creator).
        web_seeds: Web seed URLs (-w, --web-seed).
        entropy: Add random entropy to randomize info hash (-e).

    Returns:
        MkbrrResult with success status and torrent path.

    Note:
        - Piece size is auto-calculated if not specified (smart defaults)
        - Tracker-specific rules override manual -l/-m flags for compliance
        - Built-in exclusions always applied: .torrent, .ds_store, thumbs.db, etc.
    """
    settings = get_settings()

    # Use defaults
    if preset is None:
        preset = settings.mkbrr.preset
    output_dir = Path(settings.mkbrr.host_output_dir) if output_dir is None else Path(output_dir)

    # Ensure output directory exists (may be per-release subfolder)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Clean up any existing torrents for this content to avoid discovery race conditions
    # This ensures we always find the newly created torrent, not a stale one
    content_name = Path(content_path).name
    _cleanup_stale_torrents(output_dir, content_name)

    # Convert to container paths
    container_content = host_to_container_data_path(content_path)
    container_output = host_to_container_torrent_path(output_dir)

    # Build command - use output_dir as workdir so mkbrr creates files there
    # This preserves mkbrr's tracker prefix logic while letting us control output location
    cmd = _docker_base_command() + [
        "mkbrr",
        "create",
        container_content,
        "-P",
        preset,
        "--output-dir",
        container_output,
    ]

    # Add optional flags
    if output_filename is not None:
        cmd.extend(["-o", output_filename])

    if tracker is not None:
        cmd.extend(["-t", tracker])

    if source is not None:
        cmd.extend(["-s", source])

    if piece_length is not None:
        # Validate range 16-27
        if not 16 <= piece_length <= 27:
            return MkbrrResult(
                success=False,
                return_code=-1,
                error=f"piece_length must be 16-27 (got {piece_length})",
            )
        cmd.extend(["-l", str(piece_length)])

    if max_piece_length is not None:
        # Validate range 16-27
        if not 16 <= max_piece_length <= 27:
            return MkbrrResult(
                success=False,
                return_code=-1,
                error=f"max_piece_length must be 16-27 (got {max_piece_length})",
            )
        cmd.extend(["-m", str(max_piece_length)])

    if exclude_patterns:
        for pattern in exclude_patterns:
            cmd.extend(["--exclude", pattern])

    if include_patterns:
        for pattern in include_patterns:
            cmd.extend(["--include", pattern])

    if skip_prefix:
        cmd.append("--skip-prefix")

    if comment is not None:
        cmd.extend(["-c", comment])

    if private is not None:
        if private:
            cmd.append("--private")
        else:
            cmd.append("--private=false")

    if no_date:
        cmd.append("--no-date")

    if no_creator:
        cmd.append("--no-creator")

    if web_seeds:
        for seed in web_seeds:
            cmd.extend(["-w", seed])

    if entropy:
        cmd.append("-e")

    logger.info(f"Creating torrent for: {content_path}")
    logger.debug(f"Command: {shlex.join(cmd)}")

    # Default timeout: 5 minutes should be enough even for large audiobooks
    timeout_seconds = 300

    try:
        logger.debug(f"Running mkbrr with {timeout_seconds}s timeout (with retry)")

        # Run mkbrr with retry on transient Docker failures
        # Output streams to terminal for progress bars
        result = _run_docker_command(cmd, timeout=timeout_seconds, capture_output=False)

        if result.exit_code == 0:
            # Fix permissions first
            fix_torrent_permissions(output_dir)

            # Find the torrent file using deterministic discovery
            # Since we cleaned up stale torrents before creation, there should be
            # exactly one match, but we use deterministic selection as a safety net
            torrent_path = _find_torrent_deterministic(output_dir, content_name)

            if torrent_path is None:
                return MkbrrResult(
                    success=False,
                    return_code=0,
                    error=f"mkbrr succeeded but torrent file not found in {output_dir}",
                )

            logger.info(f"Torrent created: {torrent_path}")

            return MkbrrResult(
                success=True,
                return_code=0,
                torrent_path=torrent_path,
            )
        else:
            logger.error(f"mkbrr create failed with code {result.exit_code}")

            return MkbrrResult(
                success=False,
                return_code=result.exit_code,
                error=f"mkbrr exited with code {result.exit_code}",
            )

    except CmdError as e:
        if e.timed_out:
            logger.error(f"mkbrr timed out after {timeout_seconds}s")
            return MkbrrResult(
                success=False,
                return_code=e.exit_code,
                error=f"mkbrr timed out after {timeout_seconds}s",
            )
        else:
            logger.error(f"mkbrr failed: {e}")
            return MkbrrResult(
                success=False,
                return_code=e.exit_code,
                error=str(e),
            )

    except Exception as e:
        logger.exception(f"Exception running mkbrr: {e}")
        return MkbrrResult(
            success=False,
            return_code=-1,
            error=str(e),
        )


def inspect_torrent(
    torrent_path: Path | str,
    verbose: bool = False,
) -> MkbrrResult:
    """
    Inspect a .torrent file's metadata.

    Args:
        torrent_path: Path to .torrent file.
        verbose: Include all metadata fields.

    Returns:
        MkbrrResult with stdout containing inspection output.
    """
    container_path = host_to_container_torrent_path(torrent_path)

    cmd = _docker_base_command() + [
        "mkbrr",
        "inspect",
        container_path,
    ]

    if verbose:
        cmd.append("-v")

    logger.debug(f"Inspecting torrent: {torrent_path}")

    try:
        result = _run_docker_command(cmd, timeout=30, capture_output=True)

        return MkbrrResult(
            success=result.exit_code == 0,
            return_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            error=result.stderr if result.exit_code != 0 else None,
        )

    except Exception as e:
        logger.exception(f"Exception running mkbrr inspect: {e}")
        return MkbrrResult(
            success=False,
            return_code=-1,
            error=str(e),
        )


def check_torrent(
    torrent_path: Path | str,
    content_path: Path | str,
    verbose: bool = False,
    quiet: bool = False,
    workers: int | None = None,
) -> MkbrrResult:
    """
    Verify local content against a .torrent file.

    Args:
        torrent_path: Path to .torrent file.
        content_path: Path to local content to verify.
        verbose: Show detailed verification info.
        quiet: Only show final status/percent.
        workers: Number of worker threads (None for automatic).

    Returns:
        MkbrrResult with verification status.
    """
    container_torrent = host_to_container_torrent_path(torrent_path)
    container_content = host_to_container_data_path(content_path)

    cmd = _docker_base_command() + [
        "mkbrr",
        "check",
        container_torrent,
        container_content,
    ]

    if verbose and not quiet:
        cmd.append("-v")
    if quiet:
        cmd.append("--quiet")
    if workers is not None:
        cmd.extend(["--workers", str(workers)])

    logger.debug(f"Checking torrent: {torrent_path} against {content_path}")

    try:
        result = _run_docker_command(cmd, timeout=60, capture_output=True)

        return MkbrrResult(
            success=result.exit_code == 0,
            return_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            error=result.stderr if result.exit_code != 0 else None,
        )

    except Exception as e:
        logger.exception(f"Exception running mkbrr check: {e}")
        return MkbrrResult(
            success=False,
            return_code=-1,
            error=str(e),
        )


def modify_torrent(
    torrent_paths: Path | str | list[Path | str],
    output_path: Path | str | None = None,
    output_dir: Path | str | None = None,
    tracker: str | None = None,
    source: str | None = None,
    comment: str | None = None,
    private: bool | None = None,
    preset: str | None = None,
    entropy: bool = False,
    dry_run: bool = False,
) -> MkbrrResult:
    """
    Modify one or more existing torrent files.

    Changes torrent metadata without rehashing content. All non-standard
    metadata is stripped during modification.

    Args:
        torrent_paths: Path(s) to .torrent file(s) to modify.
        output_path: Output filename without extension (for single file).
            Default: prefixed filename based on tracker.
        output_dir: Output directory for batch modifications.
            Use this instead of output_path when modifying multiple files.
        tracker: New tracker announce URL (-t).
        source: New source tag (-s).
        comment: New comment (-c).
        private: Set private flag (True/False/None to keep existing).
        preset: Apply preset settings from presets.yaml (-P).
        entropy: Add random entropy to randomize info hash (-e).
        dry_run: Preview changes without saving (--dry-run).

    Returns:
        MkbrrResult with success status and output info.

    Note:
        - All non-standard metadata is stripped during modification.
        - When modifying multiple files, use output_dir not output_path.
        - Using --output with multiple files will overwrite to single file!

    Example:
        >>> # Change tracker for re-upload
        >>> result = modify_torrent("book.torrent", tracker="https://new.tracker/announce")
        >>> # Strip metadata and add source tag
        >>> result = modify_torrent("book.torrent", source="MAM")
        >>> # Preview changes without writing
        >>> result = modify_torrent("book.torrent", source="TEST", dry_run=True)
    """
    # Normalize to list
    if isinstance(torrent_paths, str | Path):
        paths_list = [Path(torrent_paths)]
    else:
        paths_list = [Path(p) for p in torrent_paths]

    # Validate: don't use output_path with multiple files (would overwrite)
    if len(paths_list) > 1 and output_path is not None:
        return MkbrrResult(
            success=False,
            return_code=-1,
            error="Cannot use output_path with multiple files. Use output_dir instead.",
        )

    # Convert paths to container paths
    container_paths = [host_to_container_torrent_path(p) for p in paths_list]

    # Build command
    cmd = _docker_base_command() + ["mkbrr", "modify"]

    # Add torrent paths
    cmd.extend(container_paths)

    # Add optional flags
    if output_path is not None:
        # mkbrr modify uses -o for filename without extension
        cmd.extend(["-o", str(output_path)])

    if output_dir is not None:
        container_output_dir = host_to_container_torrent_path(output_dir)
        cmd.extend(["--output-dir", container_output_dir])

    if tracker is not None:
        cmd.extend(["-t", tracker])

    if source is not None:
        cmd.extend(["-s", source])

    if comment is not None:
        cmd.extend(["-c", comment])

    if private is not None:
        # mkbrr uses --private (flag) or --private=false
        if private:
            cmd.append("--private")
        else:
            cmd.append("--private=false")

    if preset is not None:
        cmd.extend(["-P", preset])

    if entropy:
        cmd.append("-e")

    if dry_run:
        cmd.append("--dry-run")

    # Log what we're doing
    paths_str = ", ".join(str(p) for p in paths_list)
    if dry_run:
        logger.info(f"Dry-run modifying torrent(s): {paths_str}")
    else:
        logger.info(f"Modifying torrent(s): {paths_str}")
    logger.debug(f"Command: {shlex.join(cmd)}")

    try:
        # Capture output to show modification results
        # Modify is faster than create (no rehashing), use shorter timeout
        settings = get_settings()
        timeout = min(settings.mkbrr.timeout_seconds, 120)  # Cap at 2 min for modify
        result = _run_docker_command(cmd, timeout=timeout, capture_output=True)

        if result.exit_code == 0:
            # Fix permissions on output directory if we wrote files
            if not dry_run:
                if output_dir is not None:
                    fix_torrent_permissions(output_dir)
                else:
                    # Modified files go to same location with prefix
                    for p in paths_list:
                        fix_torrent_permissions(p.parent)

            return MkbrrResult(
                success=True,
                return_code=0,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        else:
            logger.error(f"mkbrr modify failed with code {result.exit_code}")
            return MkbrrResult(
                success=False,
                return_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
                error=result.stderr or f"mkbrr exited with code {result.exit_code}",
            )

    except CmdError as e:
        if e.timed_out:
            logger.error("mkbrr modify timed out")
            return MkbrrResult(
                success=False,
                return_code=e.exit_code,
                error="mkbrr modify timed out after 60s",
            )
        else:
            logger.error(f"mkbrr modify failed: {e}")
            return MkbrrResult(
                success=False,
                return_code=e.exit_code,
                error=str(e),
            )

    except Exception as e:
        logger.exception(f"Exception running mkbrr modify: {e}")
        return MkbrrResult(
            success=False,
            return_code=-1,
            error=str(e),
        )


def check_docker_available() -> bool:
    """Check if Docker is available on the system."""
    settings = get_settings()
    try:
        run(
            [settings.docker_bin, "--version"],
            timeout=5,  # Quick check
            ok_codes=(0,),
        )
        return True
    except CmdError:
        return False
    except Exception as e:
        logger.warning(f"Docker version check failed: {e}")
        return False


def get_mkbrr_version() -> str | None:
    """
    Get the mkbrr version from Docker container.

    Returns:
        Version string (e.g., "1.5.0") or None if unavailable.

    Example:
        >>> version = get_mkbrr_version()
        >>> print(version)  # "1.5.0" or None
    """
    cmd = _docker_base_command() + ["mkbrr", "version"]

    try:
        result = _run_docker_command(cmd, timeout=30, capture_output=True)

        if result.exit_code != 0:
            logger.warning(f"mkbrr version check failed: exit code {result.exit_code}")
            return None

        # mkbrr version outputs something like "mkbrr version 1.5.0"
        # Extract just the version number
        stdout = result.stdout.strip()
        if not stdout:
            return None

        # Handle formats like "mkbrr version 1.5.0" or just "1.5.0"
        parts = stdout.split()
        if len(parts) >= 3 and parts[0].lower() == "mkbrr" and parts[1].lower() == "version":
            return parts[2]
        elif len(parts) == 1:
            # Just the version string
            return parts[0]
        else:
            # Return the whole thing if we can't parse it
            logger.debug(f"Unexpected version format: {stdout}")
            return stdout

    except CmdError as e:
        logger.warning(f"mkbrr version command failed: {e}")
        return None
    except Exception as e:
        logger.warning(f"Exception getting mkbrr version: {e}")
        return None


# =============================================================================
# Bencode Parsing
# =============================================================================


def parse_torrent_file(torrent_path: Path | str) -> TorrentInfo:
    """
    Parse .torrent file via bencode (recommended approach).

    This is more robust than parsing mkbrr inspect output since it
    directly reads the torrent file format without Docker dependency.

    Args:
        torrent_path: Path to .torrent file.

    Returns:
        TorrentInfo model with structured metadata.

    Raises:
        FileNotFoundError: If torrent file doesn't exist.
        ValueError: If file is not a valid torrent.
        bencodepy.DecodingError: If bencode decoding fails.

    Example:
        >>> info = parse_torrent_file("/path/to/file.torrent")
        >>> print(f"{info.name}: {info.human_size()}, {info.piece_count} pieces")
    """
    import hashlib
    from datetime import datetime

    import bencodepy

    from shelfr.schemas.mkbrr import TorrentFileInfo, TorrentInfo

    torrent_path = Path(torrent_path)

    if not torrent_path.exists():
        raise FileNotFoundError(f"Torrent file not found: {torrent_path}")

    if torrent_path.suffix.lower() != ".torrent":
        logger.warning(f"File does not have .torrent extension: {torrent_path}")

    # Read and decode the torrent file
    with open(torrent_path, "rb") as f:
        raw_data = f.read()

    try:
        data = bencodepy.decode(raw_data)
    except Exception as e:
        raise ValueError(f"Failed to decode torrent file: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("Invalid torrent file: root is not a dictionary")

    # Info dict is required
    info_dict = data.get(b"info")
    if not isinstance(info_dict, dict):
        raise ValueError("Invalid torrent file: missing or invalid 'info' dictionary")

    # Calculate info hash (SHA1 of bencoded info dict)
    info_bencoded = bencodepy.encode(info_dict)
    info_hash = hashlib.sha1(info_bencoded).hexdigest()

    # Extract name (required)
    name_bytes = info_dict.get(b"name")
    if not name_bytes:
        raise ValueError("Invalid torrent file: missing 'name' in info dict")
    name = _decode_bytes(name_bytes)

    # Extract piece length (required)
    piece_length = info_dict.get(b"piece length")
    if not isinstance(piece_length, int) or piece_length <= 0:
        raise ValueError("Invalid torrent file: invalid 'piece length'")

    # Extract pieces (required) - used to calculate piece count
    pieces = info_dict.get(b"pieces")
    if not isinstance(pieces, bytes) or len(pieces) % 20 != 0:
        raise ValueError("Invalid torrent file: invalid 'pieces' data")
    piece_count = len(pieces) // 20  # Each SHA1 hash is 20 bytes

    # Private flag (optional, defaults to False)
    private = info_dict.get(b"private", 0) == 1

    # Source tag (optional)
    source_bytes = info_dict.get(b"source")
    source = _decode_bytes(source_bytes) if source_bytes else None

    # Handle single-file vs multi-file torrents
    files_list: list[TorrentFileInfo] = []
    total_size: int

    if b"files" in info_dict:
        # Multi-file torrent
        raw_files = info_dict[b"files"]
        if not isinstance(raw_files, list):
            raise ValueError("Invalid torrent file: 'files' is not a list")

        total_size = 0
        for file_entry in raw_files:
            if not isinstance(file_entry, dict):
                continue
            file_size = file_entry.get(b"length", 0)
            path_parts = file_entry.get(b"path", [])
            if isinstance(path_parts, list):
                path_str = "/".join(_decode_bytes(p) for p in path_parts if p)
            else:
                path_str = _decode_bytes(path_parts) if path_parts else ""
            files_list.append(TorrentFileInfo(path=path_str, size=file_size))
            total_size += file_size
    else:
        # Single-file torrent
        total_size = info_dict.get(b"length", 0)
        if not isinstance(total_size, int):
            raise ValueError("Invalid torrent file: invalid 'length' for single-file torrent")

    # Extract trackers
    trackers: list[str] = []

    # Primary announce URL
    announce = data.get(b"announce")
    if announce:
        trackers.append(_decode_bytes(announce))

    # announce-list (list of tiers, each tier is a list of trackers)
    announce_list = data.get(b"announce-list")
    if isinstance(announce_list, list):
        for tier in announce_list:
            if isinstance(tier, list):
                for tracker in tier:
                    tracker_url = _decode_bytes(tracker) if tracker else ""
                    if tracker_url and tracker_url not in trackers:
                        trackers.append(tracker_url)

    # Web seeds (BEP 19)
    web_seeds: list[str] = []
    url_list = data.get(b"url-list")
    if isinstance(url_list, list):
        for url in url_list:
            web_seeds.append(_decode_bytes(url))
    elif url_list:
        web_seeds.append(_decode_bytes(url_list))

    # Comment (optional)
    comment_bytes = data.get(b"comment")
    comment = _decode_bytes(comment_bytes) if comment_bytes else None

    # Created by (optional)
    created_by_bytes = data.get(b"created by")
    created_by = _decode_bytes(created_by_bytes) if created_by_bytes else None

    # Creation date (optional, unix timestamp)
    creation_date: datetime | None = None
    creation_date_raw = data.get(b"creation date")
    if isinstance(creation_date_raw, int):
        try:
            creation_date = datetime.fromtimestamp(creation_date_raw, tz=UTC)
        except (OSError, ValueError):
            logger.debug(f"Invalid creation date timestamp: {creation_date_raw}")

    # Collect extra/non-standard fields from info dict
    standard_info_keys = {
        b"name",
        b"piece length",
        b"pieces",
        b"private",
        b"source",
        b"length",
        b"files",
        b"md5sum",
        b"path",
    }
    extra_fields: dict[str, Any] = {}
    for key, value in info_dict.items():
        if key not in standard_info_keys:
            key_str = _decode_bytes(key)
            extra_fields[key_str] = _decode_value(value)

    return TorrentInfo(
        name=name,
        info_hash=info_hash,
        size=total_size,
        piece_length=piece_length,
        piece_count=piece_count,
        private=private,
        trackers=trackers,
        web_seeds=web_seeds,
        source=source,
        comment=comment,
        created_by=created_by,
        creation_date=creation_date,
        files=files_list,
        extra_fields=extra_fields if extra_fields else None,
    )


def _decode_bytes(value: bytes | str | Any) -> str:
    """Decode bytes to string, handling various encodings."""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            try:
                return value.decode("latin-1")
            except UnicodeDecodeError:
                return value.decode("utf-8", errors="replace")
    return str(value) if value is not None else ""


def _decode_value(value: Any) -> Any:
    """Recursively decode bencode values for extra_fields."""
    if isinstance(value, bytes):
        return _decode_bytes(value)
    elif isinstance(value, list):
        return [_decode_value(v) for v in value]
    elif isinstance(value, dict):
        return {_decode_bytes(k): _decode_value(v) for k, v in value.items()}
    return value


# =============================================================================
# Text Output Parsers (Step 6: Best-effort fallback for Docker inspect/check)
# =============================================================================


def parse_inspect_output(stdout: str) -> TorrentInfo:
    """
    Parse mkbrr inspect text output into TorrentInfo.

    This is a best-effort fallback parser for when bencode parsing isn't available.
    Prefer using parse_torrent_file() with the actual .torrent file when possible.

    Expected format (from mkbrr display.go ShowTorrentInfo):
        Torrent info:
          Name:         <name>
          Hash:         <info_hash>
          Size:         <size>
          Piece length: <piece_length>
          Pieces:       <num_pieces>
          Magnet:       <magnet_link>
          Tracker:      <tracker>  (or Trackers: with list)
          Web seeds:    (list)
          Private:      yes
          Source:       <source>
          Comment:      <comment>
          Created by:   <created_by>
          Created on:   <date>
          Files:        <count>

    Args:
        stdout: Raw stdout from mkbrr inspect command

    Returns:
        TorrentInfo with parsed fields (best-effort, some fields may be None)

    Raises:
        ValueError: If output cannot be parsed at all (missing required Name/Hash)
    """
    from shelfr.schemas.mkbrr import TorrentInfo

    # Strip ANSI color codes
    clean_output = _strip_ansi_codes(stdout)

    # Helper to extract field value
    def extract_field(pattern: str, text: str) -> str | None:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        return match.group(1).strip() if match else None

    # Required fields
    name = extract_field(r"Name:\s*(.+?)(?:\n|$)", clean_output)
    info_hash = extract_field(r"Hash:\s*([a-fA-F0-9]+)", clean_output)

    if not name or not info_hash:
        raise ValueError(
            f"Cannot parse inspect output: missing Name or Hash. "
            f"Got name={name!r}, hash={info_hash!r}"
        )

    # Parse size (handles formats like "1.5 GiB", "500 MiB", "1234567")
    size = _parse_size_string(extract_field(r"Size:\s*(.+?)(?:\n|$)", clean_output))

    # Parse piece length (default to 256KiB if unparseable)
    piece_length_str = extract_field(r"Piece length:\s*(.+?)(?:\n|$)", clean_output)
    piece_length = _parse_size_string(piece_length_str) or 262144

    # Parse piece count
    pieces_str = extract_field(r"Pieces:\s*(\d+)", clean_output)
    piece_count = int(pieces_str) if pieces_str else 1  # Default to 1 if unparseable

    # Parse trackers (single or multi-line)
    trackers = _parse_trackers(clean_output)

    # Parse web seeds
    web_seeds = _parse_web_seeds(clean_output)

    # Boolean/optional fields
    private_str = extract_field(r"Private:\s*(\w+)", clean_output)
    private = private_str.lower() == "yes" if private_str else False

    source = extract_field(r"Source:\s*(.+?)(?:\n|$)", clean_output)
    comment = extract_field(r"Comment:\s*(.+?)(?:\n|$)", clean_output)
    created_by = extract_field(r"Created by:\s*(.+?)(?:\n|$)", clean_output)

    # Parse creation date (format: "2024-01-15 10:30:45 UTC")
    creation_date = _parse_creation_date(
        extract_field(r"Created on:\s*(.+?)(?:\n|$)", clean_output)
    )

    # File count (we don't get individual files from inspect output)
    files_str = extract_field(r"Files:\s*(\d+)", clean_output)
    file_count = int(files_str) if files_str else None

    return TorrentInfo(
        name=name,
        info_hash=info_hash,
        size=size,
        piece_length=piece_length,
        piece_count=piece_count,
        private=private,
        trackers=trackers,
        web_seeds=web_seeds,
        source=source,
        comment=comment,
        created_by=created_by,
        creation_date=creation_date,
        files=[],  # Not available in text output
        extra_fields={"_parsed_file_count": file_count} if file_count else None,
    )


def parse_check_output(stdout: str) -> CheckResult:
    """
    Parse mkbrr check text output into CheckResult.

    Expected format (from mkbrr display.go ShowVerificationResult):
        Completion:     100.00%
        Good pieces:    1234
        Bad pieces:     0
        Missing files:  0
        Check time:     1.23s

    In quiet mode, only outputs: "100.00%"

    Args:
        stdout: Raw stdout from mkbrr check command

    Returns:
        CheckResult with parsed verification data

    Raises:
        ValueError: If output cannot be parsed
    """
    from shelfr.schemas.mkbrr import CheckResult

    # Strip ANSI color codes
    clean_output = _strip_ansi_codes(stdout)

    # Helper to extract field value
    def extract_field(pattern: str) -> str | None:
        match = re.search(pattern, clean_output, re.IGNORECASE | re.MULTILINE)
        return match.group(1).strip() if match else None

    # Try quiet mode first (just percentage)
    quiet_match = re.match(r"^\s*([\d.]+)%\s*$", clean_output.strip())
    if quiet_match:
        completion = float(quiet_match.group(1))
        # In quiet mode, we don't have piece counts - estimate total_pieces as 1
        return CheckResult(
            valid=completion >= 100.0,
            percent_complete=completion,
            good_pieces=1 if completion >= 100.0 else 0,
            bad_pieces=0 if completion >= 100.0 else 1,
            total_pieces=1,  # Unknown, use 1 as placeholder
        )

    # Parse completion percentage
    completion_str = extract_field(r"Completion:\s*([\d.]+)%?")
    if not completion_str:
        raise ValueError(
            f"Cannot parse check output: missing Completion. Output: {clean_output[:200]!r}"
        )

    completion = float(completion_str)

    # Parse piece counts
    good_str = extract_field(r"Good pieces:\s*(\d+)")
    bad_str = extract_field(r"Bad pieces:\s*(\d+)")

    good_pieces = int(good_str) if good_str else 0
    bad_pieces = int(bad_str) if bad_str else 0
    total_pieces = good_pieces + bad_pieces

    # Handle edge case where total is 0 (shouldn't happen, but be safe)
    if total_pieces == 0:
        total_pieces = 1

    # Parse missing files count and extract file names if in verbose mode
    missing_files_count_str = extract_field(r"Missing files:\s*(\d+)")
    missing_files_count = int(missing_files_count_str) if missing_files_count_str else 0

    # Try to extract missing file names from verbose output
    missing_files: list[str] = []
    if missing_files_count > 0:
        # Look for file names after "Missing files:" section
        # Format: "    ├─ filename.ext" or "    └─ filename.ext"
        file_pattern = r"[├└]─\s+(.+?)(?:\n|$)"
        # Find the Missing files section and extract entries
        missing_section = re.search(
            r"Missing files:.*?\n((?:\s+[├└]─.+?\n?)+)",
            clean_output,
            re.IGNORECASE | re.DOTALL,
        )
        if missing_section:
            for match in re.finditer(file_pattern, missing_section.group(1)):
                missing_files.append(match.group(1).strip())

    # Parse check duration
    duration_str = extract_field(r"Check time:\s*(.+?)(?:\n|$)")
    duration_seconds = _parse_duration_string(duration_str) if duration_str else None

    # Determine if valid: 100% complete, no bad pieces, no missing files
    valid = completion >= 100.0 and bad_pieces == 0 and missing_files_count == 0

    return CheckResult(
        valid=valid,
        percent_complete=completion,
        good_pieces=good_pieces,
        bad_pieces=bad_pieces,
        total_pieces=total_pieces,
        missing_files=missing_files,
        check_time_seconds=duration_seconds,
    )


def _strip_ansi_codes(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    ansi_pattern = re.compile(r"\x1b\[[0-9;]*m")
    return ansi_pattern.sub("", text)


def _parse_size_string(size_str: str | None) -> int:
    """
    Parse human-readable size string to bytes.

    Handles: "1.5 GiB", "500 MiB", "256 KiB", "1234" (raw bytes)
    """
    if not size_str:
        return 0

    size_str = size_str.strip()

    # Try raw integer first
    if size_str.isdigit():
        return int(size_str)

    # Parse with unit suffix
    match = re.match(r"([\d.]+)\s*([KMGTP]i?B?)?", size_str, re.IGNORECASE)
    if not match:
        return 0

    value = float(match.group(1))
    unit = (match.group(2) or "").upper().rstrip("B")

    multipliers = {
        "": 1,
        "K": 1024,
        "KI": 1024,
        "M": 1024**2,
        "MI": 1024**2,
        "G": 1024**3,
        "GI": 1024**3,
        "T": 1024**4,
        "TI": 1024**4,
        "P": 1024**5,
        "PI": 1024**5,
    }

    return int(value * multipliers.get(unit, 1))


def _parse_trackers(text: str) -> list[str]:
    """Extract tracker URLs from inspect output."""
    trackers: list[str] = []

    # Single tracker line
    single_match = re.search(r"Tracker:\s*(https?://\S+)", text, re.IGNORECASE)
    if single_match:
        trackers.append(single_match.group(1))
        return trackers

    # Multi-tracker (Trackers: header followed by indented URLs)
    trackers_section = re.search(
        r"Trackers:.*?\n((?:\s+https?://\S+\n?)+)", text, re.IGNORECASE | re.DOTALL
    )
    if trackers_section:
        for url_match in re.finditer(r"(https?://\S+)", trackers_section.group(1)):
            trackers.append(url_match.group(1))

    return trackers


def _parse_web_seeds(text: str) -> list[str]:
    """Extract web seed URLs from inspect output."""
    web_seeds: list[str] = []

    # Web seeds section (header followed by indented URLs)
    seeds_section = re.search(
        r"Web seeds:.*?\n((?:\s+https?://\S+\n?)+)", text, re.IGNORECASE | re.DOTALL
    )
    if seeds_section:
        for url_match in re.finditer(r"(https?://\S+)", seeds_section.group(1)):
            web_seeds.append(url_match.group(1))

    return web_seeds


def _parse_creation_date(date_str: str | None) -> datetime | None:
    """Parse creation date string to datetime."""
    if not date_str:
        return None

    # Expected format: "2024-01-15 10:30:45 MST"
    formats = [
        "%Y-%m-%d %H:%M:%S %Z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    logger.debug(f"Could not parse creation date: {date_str!r}")
    return None


def _parse_duration_string(duration_str: str | None) -> float | None:
    """
    Parse duration string to seconds.

    Handles: "1.23s", "2m30s", "1h2m3s", "500ms"
    """
    if not duration_str:
        return None

    duration_str = duration_str.strip()

    # Simple seconds format: "1.23s"
    simple_match = re.match(r"^([\d.]+)\s*s$", duration_str, re.IGNORECASE)
    if simple_match:
        return float(simple_match.group(1))

    # Milliseconds: "500ms"
    ms_match = re.match(r"^([\d.]+)\s*ms$", duration_str, re.IGNORECASE)
    if ms_match:
        return float(ms_match.group(1)) / 1000

    # Complex format: "1h2m3s" or "2m30s"
    total_seconds = 0.0
    hours_match = re.search(r"(\d+)\s*h", duration_str, re.IGNORECASE)
    mins_match = re.search(r"(\d+)\s*m(?!s)", duration_str, re.IGNORECASE)
    secs_match = re.search(r"([\d.]+)\s*s", duration_str, re.IGNORECASE)

    if hours_match:
        total_seconds += int(hours_match.group(1)) * 3600
    if mins_match:
        total_seconds += int(mins_match.group(1)) * 60
    if secs_match:
        total_seconds += float(secs_match.group(1))

    return total_seconds if total_seconds > 0 else None
