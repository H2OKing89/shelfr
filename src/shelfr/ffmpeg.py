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
from typing import TYPE_CHECKING, Any

from shelfr.config import get_settings
from shelfr.utils.cmd import CmdError, CmdResult, run
from shelfr.utils.permissions import fix_ownership
from shelfr.utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from shelfr.config import Settings


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
    chapters: list[dict[str, Any]] = field(default_factory=list)  # Top-level chapters
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
        return bool(self.chapters)


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
    entrypoint: str | None = None,
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
        entrypoint: Override default entrypoint (e.g., 'ffprobe')

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

    # Override entrypoint if specified (e.g., for ffprobe)
    if entrypoint:
        cmd.extend(["--entrypoint", entrypoint])

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
    user_env = {
        "PUID": str(settings.target_uid),
        "PGID": str(settings.target_gid),
    }
    if extra_env:
        user_env.update(extra_env)

    for key, value in user_env.items():
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

    cmd = _docker_base_command(entrypoint="ffprobe")
    # Insert mounts before image name
    image_idx = len(cmd) - 1
    for mount in mounts:
        cmd.insert(image_idx, mount)
        image_idx += 1

    # ffprobe arguments (entrypoint already set to ffprobe)
    cmd.extend(
        [
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

    logger.debug("Running probe: %s", " ".join(cmd))

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
    chapters = data.get("chapters", [])  # Chapters are at top level, not in format

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
        chapters=chapters,
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

    # Ensure output directory exists and is writable by container user
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fix_ownership(output_path.parent, settings.target_uid, settings.target_gid)
    if output_path.exists():
        fix_ownership(output_path, settings.target_uid, settings.target_gid)

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

    # Video settings (skip -c:v if video_codec is 'none' since -vn handles it)
    if video_codec != "none":
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

    logger.debug("Running transcode: %s", " ".join(cmd))

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
        logger.error("Failed to pull FFmpeg image: %s", e)
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


# =============================================================================
# Audiobook / Audio-Focused Functions
# =============================================================================


def copy_audio(
    input_path: Path | str,
    output_path: Path | str,
    *,
    strip_tags: list[str] | None = None,
    set_tags: dict[str, str] | None = None,
    preserve_chapters: bool = True,
    preserve_cover: bool = True,
    overwrite: bool = False,
    timeout: int | None = None,
    verbose: bool = False,
) -> FFmpegResult:
    """
    Copy audio file with metadata manipulation (no re-encoding).

    This is a lossless operation using stream copy. Useful for:
    - Stripping unwanted tags (e.g., AUDIBLE_ACR, AUDIBLE_ASIN)
    - Adding/modifying metadata tags
    - Preserving chapters and cover art

    Example command this generates:
        ffmpeg -i input.m4b -map 0:a -map 0:v? -map_metadata 0 -map_chapters 0
               -metadata AUDIBLE_ACR= -c copy output.m4b

    Args:
        input_path: Path to input audio file
        output_path: Path for output file
        strip_tags: List of tag names to remove (set to empty)
        set_tags: Dict of tag_name -> value to set
        preserve_chapters: Keep chapter markers (default: True)
        preserve_cover: Keep embedded cover art (default: True)
        overwrite: Whether to overwrite existing output
        timeout: Timeout in seconds
        verbose: If True, stream FFmpeg output to terminal (like mkbrr)

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

    # Ensure output directory exists and is writable by target user
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fix_ownership(output_path.parent, settings.target_uid, settings.target_gid)
    if output_path.exists():
        fix_ownership(output_path, settings.target_uid, settings.target_gid)

    # Build command
    mounts, path_map = _build_volume_mounts([input_path, output_path])
    container_input = path_map[input_path]
    container_output = path_map[output_path]

    cmd = _docker_base_command()
    # Insert mounts before image name
    image_idx = len(cmd) - 1
    for mount in mounts:
        cmd.insert(image_idx, mount)
        image_idx += 1

    # Build ffmpeg args for audio copy
    ffmpeg_args = [
        "-i",
        container_input,
        "-map",
        "0:a",  # Map audio streams
    ]

    # Optionally preserve cover art (video stream in M4B)
    if preserve_cover:
        ffmpeg_args.extend(["-map", "0:v?"])  # ? = optional

    # Preserve metadata
    ffmpeg_args.extend(["-map_metadata", "0"])

    # Preserve chapters
    if preserve_chapters:
        ffmpeg_args.extend(["-map_chapters", "0"])

    # Strip specific tags (set to empty value)
    if strip_tags:
        for tag in strip_tags:
            ffmpeg_args.extend(["-metadata", f"{tag}="])

    # Set specific tags
    if set_tags:
        for tag, value in set_tags.items():
            ffmpeg_args.extend(["-metadata", f"{tag}={value}"])

    # Stream copy (no re-encoding)
    ffmpeg_args.extend(["-c", "copy"])

    # Explicitly set output format if output filename has non-standard extension
    # (e.g., ".m4b.sanitizing.12345" won't be recognized by ffmpeg)
    # Use input file extension to determine format
    input_ext = input_path.suffix.lower()
    output_ext = output_path.suffix.lower()
    if input_ext in (".m4b", ".m4a", ".mp4") and output_ext not in (
        ".m4b",
        ".m4a",
        ".mp4",
        ".mov",
    ):
        # Force ipod/m4a format for M4B audiobooks
        ffmpeg_args.extend(["-f", "ipod"])

    # Output
    if overwrite:
        ffmpeg_args.append("-y")
    ffmpeg_args.append(container_output)

    cmd.extend(ffmpeg_args)

    logger.debug("Running copy_audio: %s", " ".join(cmd))

    try:
        # In verbose mode, stream FFmpeg output to terminal (like mkbrr does)
        result = _run_docker_command(cmd, timeout=timeout, capture_output=not verbose)
    except (CmdError, OSError, TimeoutError) as e:
        return FFmpegResult(
            success=False,
            exit_code=1,
            error=str(e),
        )

    success = result.exit_code == 0 and output_path.exists()

    if not success:
        stderr_preview = (result.stderr or "")[:2000]
        logger.warning(
            "copy_audio failed (exit %s). stderr head:%s%s",
            result.exit_code,
            "\n" if stderr_preview else " ",
            stderr_preview,
        )

    return FFmpegResult(
        success=success,
        exit_code=result.exit_code,
        output_path=output_path if success else None,
        error=result.stderr if not success else None,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def strip_audible_tags(
    input_path: Path | str,
    output_path: Path | str,
    *,
    overwrite: bool = False,
    timeout: int | None = None,
) -> FFmpegResult:
    """
    Strip Audible-specific tags from an audiobook file.

    Removes Audible DRM-related metadata tags while preserving
    all other metadata, chapters, and cover art.

    Tags stripped:
    - AUDIBLE_ACR (Audible Content Reference)

    Args:
        input_path: Path to input M4B/M4A file
        output_path: Path for output file
        overwrite: Whether to overwrite existing output
        timeout: Timeout in seconds

    Returns:
        FFmpegResult with operation status
    """
    audible_tags = [
        "AUDIBLE_ACR",
    ]

    return copy_audio(
        input_path,
        output_path,
        strip_tags=audible_tags,
        overwrite=overwrite,
        timeout=timeout,
    )


def get_audio_tags(input_path: Path | str) -> dict[str, str] | None:
    """
    Get all metadata tags from an audio file.

    Args:
        input_path: Path to audio file

    Returns:
        Dict of tag_name -> value, or None if probe failed
    """
    result = probe(input_path)
    if not result.success:
        return None

    tags: dict[str, str] = result.format.get("tags", {})
    return tags


def get_chapters(input_path: Path | str) -> list[dict[str, Any]] | None:
    """
    Get chapter list from an audio file.

    Args:
        input_path: Path to audio file

    Returns:
        List of chapter dicts with start, end, title, or None if failed
    """
    result = probe(input_path)
    if not result.success:
        return None

    return result.chapters
