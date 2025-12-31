"""
mkbrr Docker wrapper for torrent creation.

Refactored from the interactive mkbrr wizard script to be fully automated.
Supports: create, inspect, check operations.
"""

from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass
from pathlib import Path

import yaml

from shelfr.config import get_settings
from shelfr.utils.cmd import CmdError, CmdResult, run
from shelfr.utils.paths import host_to_container_data_path, host_to_container_torrent_path
from shelfr.utils.permissions import fix_directory_ownership
from shelfr.utils.retry import retry_with_backoff

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
    logger.debug(f"Command: {' '.join(cmd)}")

    try:
        # Capture output to show modification results
        result = _run_docker_command(cmd, timeout=60, capture_output=True)

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
