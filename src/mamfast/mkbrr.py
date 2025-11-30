"""
mkbrr Docker wrapper for torrent creation.

Refactored from the interactive mkbrr wizard script to be fully automated.
Supports: create, inspect, check operations.
"""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

from mamfast.config import get_settings
from mamfast.utils.paths import host_to_container_data_path, host_to_container_torrent_path

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


def fix_torrent_permissions(root_dir: Path | str | None = None) -> int:
    """
    Recursively chown all .torrent files to the target UID:GID.

    This fixes ownership after Docker creates files as root.
    Default ownership: Unraid's nobody:users (99:100)

    Args:
        root_dir: Directory to scan. Defaults to configured torrent output dir.

    Returns:
        Number of files fixed.
    """
    settings = get_settings()
    target_uid = settings.target_uid
    target_gid = settings.target_gid

    root_dir = Path(settings.mkbrr.host_output_dir) if root_dir is None else Path(root_dir)

    if not root_dir.is_dir():
        logger.warning(f"Torrent directory does not exist: {root_dir}")
        return 0

    fixed_count = 0
    logger.debug(f"Fixing .torrent ownership in {root_dir} to {target_uid}:{target_gid}")

    for dirpath, _, filenames in os.walk(root_dir):
        for name in filenames:
            if not name.lower().endswith(".torrent"):
                continue

            full_path = Path(dirpath) / name
            try:
                stat = full_path.stat()
                if stat.st_uid != target_uid or stat.st_gid != target_gid:
                    os.chown(full_path, target_uid, target_gid)
                    logger.debug(f"Fixed ownership: {full_path}")
                    fixed_count += 1
            except FileNotFoundError:
                continue
            except PermissionError as e:
                logger.warning(f"Permission error on {full_path}: {e}")

    if fixed_count:
        logger.info(f"Fixed ownership on {fixed_count} .torrent file(s)")

    return fixed_count


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
            data = yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"Failed to parse {presets_path}: {e}")
        return [settings.mkbrr.preset]

    presets_node = data.get("presets") or {}

    if not isinstance(presets_node, dict) or not presets_node:
        logger.warning(f"No valid 'presets' mapping in {presets_path}")
        return [settings.mkbrr.preset]

    presets = list(presets_node.keys())

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

    try:
        # Run mkbrr and let output stream to terminal (like interactive mode)
        # This allows progress bars and feedback to display
        result = subprocess.run(
            cmd,
            text=True,
            check=False,
        )

        if result.returncode == 0:
            # Fix permissions first
            fix_torrent_permissions(output_dir)

            # Figure out the output torrent filename
            # mkbrr may add a preset prefix (e.g., "myanonamouse_") to the filename
            content_name = Path(content_path).name

            # Look for the actual torrent file - try with and without prefix
            torrent_path = None
            possible_patterns = [
                f"*{content_name}.torrent",  # With any prefix
                f"{content_name}.torrent",  # Without prefix
            ]

            for pattern in possible_patterns:
                matches = list(output_dir.glob(pattern))
                if matches:
                    # Take the most recently modified one
                    torrent_path = max(matches, key=lambda p: p.stat().st_mtime)
                    break

            if torrent_path is None:
                # Fallback: find any recently created .torrent file
                all_torrents = list(output_dir.glob("*.torrent"))
                if all_torrents:
                    torrent_path = max(all_torrents, key=lambda p: p.stat().st_mtime)

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
            logger.error(f"mkbrr create failed with code {result.returncode}")

            return MkbrrResult(
                success=False,
                return_code=result.returncode,
                error=f"mkbrr exited with code {result.returncode}",
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
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )

        return MkbrrResult(
            success=result.returncode == 0,
            return_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            error=result.stderr if result.returncode != 0 else None,
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
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )

        return MkbrrResult(
            success=result.returncode == 0,
            return_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            error=result.stderr if result.returncode != 0 else None,
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
        result = subprocess.run(
            [settings.docker_bin, "--version"],
            capture_output=True,
            check=False,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False
