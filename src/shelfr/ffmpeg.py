"""
FFmpeg Docker wrapper for audio/video processing.

Uses linuxserver/ffmpeg container for portable, hardware-accelerated encoding.
Supports basic transcoding, probing, and audio extraction operations.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from shelfr.config import get_settings
from shelfr.utils.cmd import CmdError, CmdResult, run
from shelfr.utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


class HardwareAccel(str, Enum):
    """Hardware acceleration types supported by linuxserver/ffmpeg."""

    NONE = "none"
    VAAPI = "vaapi"  # Intel/AMD on Linux
    QSV = "qsv"  # Intel Quick Sync
    NVENC = "nvenc"  # NVIDIA
    VULKAN = "vulkan"  # Cross-platform (Intel/AMD)


@dataclass
class FFprobeResult:
    """Result from ffprobe operation."""

    success: bool
    format: dict[str, Any] = field(default_factory=dict)
    streams: list[dict[str, Any]] = field(default_factory=list)
    duration: float | None = None
    duration_str: str | None = None
    bitrate: int | None = None  # bits per second
    size: int | None = None  # bytes
    codec_name: str | None = None  # Primary audio/video codec
    sample_rate: int | None = None  # Audio sample rate
    channels: int | None = None  # Audio channels
    error: str | None = None
    raw_output: str = ""

    @property
    def audio_streams(self) -> list[dict[str, Any]]:
        """Get all audio streams."""
        return [s for s in self.streams if s.get("codec_type") == "audio"]

    @property
    def video_streams(self) -> list[dict[str, Any]]:
        """Get all video streams."""
        return [s for s in self.streams if s.get("codec_type") == "video"]

    @property
    def has_chapters(self) -> bool:
        """Check if media has chapters."""
        return bool(self.format.get("chapters"))


@dataclass
class FFmpegResult:
    """Result of an FFmpeg operation."""

    success: bool
    exit_code: int
    output_path: Path | None = None
    error: str | None = None
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float | None = None


# =============================================================================
# Docker Command Building
# =============================================================================


def _docker_base_command(
    *,
    hwaccel: HardwareAccel = HardwareAccel.NONE,
    extra_devices: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
) -> list[str]:
    """
    Build the common docker run prefix for all FFmpeg commands.

    The linuxserver/ffmpeg container:
    - Mounts files to /config inside container
    - Auto-detects hardware acceleration
    - Runs ephemerally (--rm)

    Args:
        hwaccel: Hardware acceleration type
        extra_devices: Additional devices to pass through (e.g., /dev/dri)
        extra_env: Additional environment variables

    Returns:
        List of docker command arguments
    """
    settings = get_settings()
    ffmpeg_config = settings.ffmpeg

    cmd = [
        settings.docker_bin,
        "run",
        "--rm",
    ]

    # Hardware acceleration devices
    if hwaccel in (HardwareAccel.VAAPI, HardwareAccel.QSV, HardwareAccel.VULKAN):
        cmd.extend(["--device=/dev/dri:/dev/dri"])
    elif hwaccel == HardwareAccel.NVENC:
        cmd.extend(["--runtime=nvidia"])

    # Extra devices
    if extra_devices:
        for device in extra_devices:
            cmd.extend([f"--device={device}"])

    # Environment variables
    if extra_env:
        for key, value in extra_env.items():
            cmd.extend(["-e", f"{key}={value}"])

    # Volume mounts - we'll add specific mounts per operation
    # The container expects input/output in /config

    cmd.append(ffmpeg_config.image)

    return cmd


def _build_volume_mounts(paths: list[Path]) -> tuple[list[str], dict[Path, str]]:
    """
    Build volume mount arguments for a set of paths.

    Mounts parent directories of input files to minimize mount points.

    Args:
        paths: List of file paths to make accessible in container

    Returns:
        Tuple of (mount arguments, path mapping from host to container)
    """
    mounts: list[str] = []
    path_map: dict[Path, str] = {}

    # Group by parent directory
    parents: dict[Path, list[Path]] = {}
    for path in paths:
        parent = path.parent.resolve()
        if parent not in parents:
            parents[parent] = []
        parents[parent].append(path)

    # Create mount for each unique parent
    for idx, (parent, files) in enumerate(parents.items()):
        container_dir = f"/config/mount{idx}"
        mounts.extend(["-v", f"{parent}:{container_dir}"])
        for file_path in files:
            path_map[file_path] = f"{container_dir}/{file_path.name}"

    return mounts, path_map


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
        capture_output: Whether to capture stdout/stderr

    Returns:
        CmdResult with output and exit code

    Raises:
        CmdError: If command fails after retries
    """
    return run(
        cmd,
        timeout=timeout,
        ok_codes=(0, 1),  # FFmpeg can return 1 for warnings
        capture_output=capture_output,
    )


# =============================================================================
# Probe Operations
# =============================================================================


def probe(
    input_path: Path | str,
    *,
    timeout: int | None = None,
) -> FFprobeResult:
    """
    Probe a media file to get format and stream information.

    Uses ffprobe in JSON output mode for structured data.

    Args:
        input_path: Path to media file
        timeout: Timeout in seconds (default from config)

    Returns:
        FFprobeResult with parsed media information
    """
    input_path = Path(input_path).resolve()
    settings = get_settings()
    timeout = timeout or settings.ffmpeg.timeout_seconds

    if not input_path.exists():
        return FFprobeResult(
            success=False,
            error=f"Input file not found: {input_path}",
        )

    # Build command
    mounts, path_map = _build_volume_mounts([input_path])
    container_input = path_map[input_path]

    cmd = _docker_base_command()
    # Insert mounts before image name
    image_idx = len(cmd) - 1
    for mount in mounts:
        cmd.insert(image_idx, mount)
        image_idx += 1

    # Use ffprobe instead of ffmpeg
    cmd[-1] = cmd[-1]  # Keep image
    cmd.extend(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            "-show_chapters",
            container_input,
        ]
    )

    logger.debug(f"Running probe: {' '.join(cmd)}")

    try:
        result = _run_docker_command(cmd, timeout=timeout)
    except (CmdError, OSError, TimeoutError) as e:
        return FFprobeResult(
            success=False,
            error=str(e),
        )

    if result.exit_code != 0:
        return FFprobeResult(
            success=False,
            error=result.stderr or f"ffprobe failed with code {result.exit_code}",
            raw_output=result.stdout,
        )

    # Parse JSON output
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        return FFprobeResult(
            success=False,
            error=f"Failed to parse ffprobe output: {e}",
            raw_output=result.stdout,
        )

    format_info = data.get("format", {})
    streams = data.get("streams", [])

    # Extract common fields
    duration = None
    duration_str = None
    if "duration" in format_info:
        try:
            duration = float(format_info["duration"])
            hours = int(duration // 3600)
            minutes = int((duration % 3600) // 60)
            seconds = int(duration % 60)
            duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        except (ValueError, TypeError):
            pass

    bitrate = None
    if "bit_rate" in format_info:
        with contextlib.suppress(ValueError, TypeError):
            bitrate = int(format_info["bit_rate"])

    size = None
    if "size" in format_info:
        with contextlib.suppress(ValueError, TypeError):
            size = int(format_info["size"])

    # Get primary audio stream info
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    codec_name = None
    sample_rate = None
    channels = None

    if audio_streams:
        primary_audio = audio_streams[0]
        codec_name = primary_audio.get("codec_name")
        if "sample_rate" in primary_audio:
            with contextlib.suppress(ValueError, TypeError):
                sample_rate = int(primary_audio["sample_rate"])
        if "channels" in primary_audio:
            with contextlib.suppress(ValueError, TypeError):
                channels = int(primary_audio["channels"])

    return FFprobeResult(
        success=True,
        format=format_info,
        streams=streams,
        duration=duration,
        duration_str=duration_str,
        bitrate=bitrate,
        size=size,
        codec_name=codec_name,
        sample_rate=sample_rate,
        channels=channels,
        raw_output=result.stdout,
    )


# =============================================================================
# Transcode Operations
# =============================================================================


def transcode(
    input_path: Path | str,
    output_path: Path | str,
    *,
    audio_codec: str = "copy",
    audio_bitrate: str | None = None,
    audio_channels: int | None = None,
    video_codec: str = "copy",
    video_bitrate: str | None = None,
    hwaccel: HardwareAccel = HardwareAccel.NONE,
    extra_args: list[str] | None = None,
    overwrite: bool = False,
    timeout: int | None = None,
) -> FFmpegResult:
    """
    Transcode a media file.

    Args:
        input_path: Path to input file
        output_path: Path for output file
        audio_codec: Audio codec (default: copy)
        audio_bitrate: Audio bitrate (e.g., "128k", "192k")
        audio_channels: Number of audio channels
        video_codec: Video codec (default: copy)
        video_bitrate: Video bitrate (e.g., "4M", "2000k")
        hwaccel: Hardware acceleration type
        extra_args: Additional FFmpeg arguments
        overwrite: Whether to overwrite existing output
        timeout: Timeout in seconds

    Returns:
        FFmpegResult with operation status
    """
    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()
    settings = get_settings()
    timeout = timeout or settings.ffmpeg.timeout_seconds

    if not input_path.exists():
        return FFmpegResult(
            success=False,
            exit_code=1,
            error=f"Input file not found: {input_path}",
        )

    if output_path.exists() and not overwrite:
        return FFmpegResult(
            success=False,
            exit_code=1,
            error=f"Output file exists: {output_path}",
        )

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build command
    mounts, path_map = _build_volume_mounts([input_path, output_path])
    container_input = path_map[input_path]
    container_output = path_map[output_path]

    cmd = _docker_base_command(hwaccel=hwaccel)
    # Insert mounts before image name
    image_idx = len(cmd) - 1
    for mount in mounts:
        cmd.insert(image_idx, mount)
        image_idx += 1

    # Build ffmpeg args
    ffmpeg_args = ["-i", container_input]

    # Hardware acceleration input args
    if hwaccel == HardwareAccel.VAAPI:
        ffmpeg_args = ["-vaapi_device", "/dev/dri/renderD128"] + ffmpeg_args
    elif hwaccel == HardwareAccel.QSV:
        ffmpeg_args = ["-hwaccel", "qsv"] + ffmpeg_args
    elif hwaccel == HardwareAccel.NVENC:
        ffmpeg_args = ["-hwaccel", "nvdec"] + ffmpeg_args

    # Audio settings
    ffmpeg_args.extend(["-c:a", audio_codec])
    if audio_bitrate:
        ffmpeg_args.extend(["-b:a", audio_bitrate])
    if audio_channels:
        ffmpeg_args.extend(["-ac", str(audio_channels)])

    # Video settings
    ffmpeg_args.extend(["-c:v", video_codec])
    if video_bitrate:
        ffmpeg_args.extend(["-b:v", video_bitrate])

    # Extra args
    if extra_args:
        ffmpeg_args.extend(extra_args)

    # Output
    if overwrite:
        ffmpeg_args.append("-y")
    ffmpeg_args.append(container_output)

    cmd.extend(ffmpeg_args)

    logger.debug(f"Running transcode: {' '.join(cmd)}")

    try:
        result = _run_docker_command(cmd, timeout=timeout)
    except (CmdError, OSError, TimeoutError) as e:
        return FFmpegResult(
            success=False,
            exit_code=1,
            error=str(e),
        )

    success = result.exit_code == 0 and output_path.exists()

    return FFmpegResult(
        success=success,
        exit_code=result.exit_code,
        output_path=output_path if success else None,
        error=result.stderr if not success else None,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def extract_audio(
    input_path: Path | str,
    output_path: Path | str,
    *,
    codec: str = "copy",
    bitrate: str | None = None,
    overwrite: bool = False,
    timeout: int | None = None,
) -> FFmpegResult:
    """
    Extract audio from a media file.

    Args:
        input_path: Path to input file
        output_path: Path for output audio file
        codec: Audio codec (default: copy for lossless extraction)
        bitrate: Audio bitrate (e.g., "192k")
        overwrite: Whether to overwrite existing output
        timeout: Timeout in seconds

    Returns:
        FFmpegResult with operation status
    """
    return transcode(
        input_path,
        output_path,
        audio_codec=codec,
        audio_bitrate=bitrate,
        video_codec="none",
        extra_args=["-vn"],  # No video
        overwrite=overwrite,
        timeout=timeout,
    )


# =============================================================================
# Utility Functions
# =============================================================================


def get_duration(input_path: Path | str) -> float | None:
    """
    Get duration of a media file in seconds.

    Convenience wrapper around probe().

    Args:
        input_path: Path to media file

    Returns:
        Duration in seconds, or None if probe failed
    """
    result = probe(input_path)
    return result.duration if result.success else None


def get_bitrate(input_path: Path | str) -> int | None:
    """
    Get bitrate of a media file in bits per second.

    Args:
        input_path: Path to media file

    Returns:
        Bitrate in bps, or None if probe failed
    """
    result = probe(input_path)
    return result.bitrate if result.success else None


def is_available() -> bool:
    """
    Check if FFmpeg Docker image is available.

    Returns:
        True if image exists locally
    """
    settings = get_settings()

    try:
        result = run(
            [settings.docker_bin, "images", "-q", settings.ffmpeg.image],
            timeout=30,
            capture_output=True,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def pull_image() -> bool:
    """
    Pull the FFmpeg Docker image.

    Returns:
        True if pull succeeded
    """
    settings = get_settings()

    try:
        result = run(
            [settings.docker_bin, "pull", settings.ffmpeg.image],
            timeout=300,
            capture_output=True,
        )
        return result.exit_code == 0
    except Exception as e:
        logger.error(f"Failed to pull FFmpeg image: {e}")
        return False


def version() -> str | None:
    """
    Get FFmpeg version from container.

    Returns:
        Version string, or None if failed
    """
    settings = get_settings()

    cmd = [
        settings.docker_bin,
        "run",
        "--rm",
        settings.ffmpeg.image,
        "-version",
    ]

    try:
        result = run(cmd, timeout=30, capture_output=True)
        if result.exit_code == 0:
            # Parse first line: "ffmpeg version N.N.N ..."
            match = re.match(r"ffmpeg version (\S+)", result.stdout)
            if match:
                return match.group(1)
        return None
    except Exception:
        return None
