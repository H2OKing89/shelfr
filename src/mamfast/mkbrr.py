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

from mamfast.config import get_settings
from mamfast.utils.cmd import CmdError, CmdResult, run
from mamfast.utils.paths import host_to_container_data_path, host_to_container_torrent_path
from mamfast.utils.permissions import fix_directory_ownership
from mamfast.utils.retry import retry_with_backoff

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
) -> MkbrrResult:
    """
    Create a .torrent file for the given content.

    Args:
        content_path: Path to file or directory to create torrent for.
        output_dir: Where to write .torrent file. Defaults to configured dir.
        preset: mkbrr preset name. Defaults to configured preset.

    Returns:
        MkbrrResult with success status and torrent path.
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

    # Build command
    cmd = _docker_base_command() + [
        "mkbrr",
        "create",
        container_content,
        "-P",
        preset,
        "--output-dir",
        container_output,
    ]

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
