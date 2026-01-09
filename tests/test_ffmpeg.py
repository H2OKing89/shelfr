"""Tests for FFmpeg Docker wrapper module."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from shelfr.ffmpeg import (
    FFmpegResult,
    FFprobeResult,
    HardwareAccel,
    _build_volume_mounts,
    _docker_base_command,
    extract_audio,
    get_bitrate,
    get_duration,
    is_available,
    probe,
    pull_image,
    transcode,
    version,
)

# =============================================================================
# Data Class Tests
# =============================================================================


class TestFFprobeResult:
    """Tests for FFprobeResult dataclass."""

    def test_audio_streams_filters_correctly(self) -> None:
        """Test audio_streams property filters by codec_type."""
        result = FFprobeResult(
            success=True,
            streams=[
                {"codec_type": "audio", "codec_name": "aac"},
                {"codec_type": "video", "codec_name": "h264"},
                {"codec_type": "audio", "codec_name": "mp3"},
            ],
        )
        assert len(result.audio_streams) == 2
        assert all(s["codec_type"] == "audio" for s in result.audio_streams)

    def test_video_streams_filters_correctly(self) -> None:
        """Test video_streams property filters by codec_type."""
        result = FFprobeResult(
            success=True,
            streams=[
                {"codec_type": "audio", "codec_name": "aac"},
                {"codec_type": "video", "codec_name": "h264"},
            ],
        )
        assert len(result.video_streams) == 1
        assert result.video_streams[0]["codec_name"] == "h264"

    def test_has_chapters_true(self) -> None:
        """Test has_chapters returns True when chapters exist."""
        result = FFprobeResult(
            success=True,
            chapters=[{"start": 0, "end": 100}],
        )
        assert result.has_chapters is True

    def test_has_chapters_false(self) -> None:
        """Test has_chapters returns False when no chapters."""
        result = FFprobeResult(success=True, chapters=[])
        assert result.has_chapters is False

    def test_empty_streams(self) -> None:
        """Test with empty streams list."""
        result = FFprobeResult(success=True)
        assert result.audio_streams == []
        assert result.video_streams == []


class TestFFmpegResult:
    """Tests for FFmpegResult dataclass."""

    def test_success_result(self) -> None:
        """Test successful result."""
        result = FFmpegResult(
            success=True,
            exit_code=0,
            output_path=Path("/output/file.m4b"),
        )
        assert result.success is True
        assert result.exit_code == 0
        assert result.output_path == Path("/output/file.m4b")

    def test_failure_result(self) -> None:
        """Test failure result."""
        result = FFmpegResult(
            success=False,
            exit_code=1,
            error="Conversion failed",
        )
        assert result.success is False
        assert result.exit_code == 1
        assert result.error == "Conversion failed"


class TestHardwareAccel:
    """Tests for HardwareAccel enum."""

    def test_enum_values(self) -> None:
        """Test all hardware acceleration values exist."""
        assert HardwareAccel.NONE.value == "none"
        assert HardwareAccel.VAAPI.value == "vaapi"
        assert HardwareAccel.QSV.value == "qsv"
        assert HardwareAccel.NVENC.value == "nvenc"
        assert HardwareAccel.VULKAN.value == "vulkan"


# =============================================================================
# Volume Mount Tests
# =============================================================================


class TestBuildVolumeMounts:
    """Tests for _build_volume_mounts function."""

    def test_single_file(self, tmp_path: Path) -> None:
        """Test mounting a single file."""
        file_path = tmp_path / "test.m4b"
        file_path.touch()

        mounts, path_map = _build_volume_mounts([file_path])

        assert len(mounts) == 2  # -v, path:container_path
        assert file_path in path_map
        assert path_map[file_path].startswith("/config/mount")

    def test_multiple_files_same_dir(self, tmp_path: Path) -> None:
        """Test mounting multiple files from same directory."""
        file1 = tmp_path / "test1.m4b"
        file2 = tmp_path / "test2.m4b"
        file1.touch()
        file2.touch()

        mounts, path_map = _build_volume_mounts([file1, file2])

        # Should only have one mount for the shared parent
        assert len(mounts) == 2
        assert file1 in path_map
        assert file2 in path_map

    def test_multiple_files_different_dirs(self, tmp_path: Path) -> None:
        """Test mounting files from different directories."""
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        file1 = dir1 / "test1.m4b"
        file2 = dir2 / "test2.m4b"
        file1.touch()
        file2.touch()

        mounts, path_map = _build_volume_mounts([file1, file2])

        # Should have two mounts for different parents
        assert len(mounts) == 4  # Two -v pairs
        assert file1 in path_map
        assert file2 in path_map
        # Container paths should be different
        assert path_map[file1] != path_map[file2]


# =============================================================================
# Docker Command Building Tests
# =============================================================================


class TestDockerBaseCommand:
    """Tests for _docker_base_command function."""

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create mock settings."""
        settings = MagicMock()
        settings.docker_bin = "docker"
        settings.ffmpeg.image = "lscr.io/linuxserver/ffmpeg:latest"
        return settings

    def test_basic_command(self, mock_settings: MagicMock) -> None:
        """Test basic command without hardware acceleration."""
        with patch("shelfr.ffmpeg.get_settings", return_value=mock_settings):
            cmd = _docker_base_command()

        assert "docker" in cmd
        assert "run" in cmd
        assert "--rm" in cmd
        assert "lscr.io/linuxserver/ffmpeg:latest" in cmd

    def test_vaapi_acceleration(self, mock_settings: MagicMock) -> None:
        """Test VAAPI hardware acceleration adds device."""
        with patch("shelfr.ffmpeg.get_settings", return_value=mock_settings):
            cmd = _docker_base_command(hwaccel=HardwareAccel.VAAPI)

        assert "--device=/dev/dri:/dev/dri" in cmd

    def test_qsv_acceleration(self, mock_settings: MagicMock) -> None:
        """Test QSV hardware acceleration adds device."""
        with patch("shelfr.ffmpeg.get_settings", return_value=mock_settings):
            cmd = _docker_base_command(hwaccel=HardwareAccel.QSV)

        assert "--device=/dev/dri:/dev/dri" in cmd

    def test_nvenc_acceleration(self, mock_settings: MagicMock) -> None:
        """Test NVENC hardware acceleration adds nvidia runtime."""
        with patch("shelfr.ffmpeg.get_settings", return_value=mock_settings):
            cmd = _docker_base_command(hwaccel=HardwareAccel.NVENC)

        assert "--runtime=nvidia" in cmd

    def test_extra_env_vars(self, mock_settings: MagicMock) -> None:
        """Test extra environment variables are added."""
        with patch("shelfr.ffmpeg.get_settings", return_value=mock_settings):
            cmd = _docker_base_command(extra_env={"MY_VAR": "value"})

        assert "-e" in cmd
        assert "MY_VAR=value" in cmd


# =============================================================================
# Probe Tests
# =============================================================================


class TestProbe:
    """Tests for probe function."""

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create mock settings."""
        settings = MagicMock()
        settings.docker_bin = "docker"
        settings.ffmpeg.image = "lscr.io/linuxserver/ffmpeg:latest"
        settings.ffmpeg.timeout_seconds = 60
        return settings

    def test_probe_file_not_found(self, tmp_path: Path, mock_settings: MagicMock) -> None:
        """Test probe returns error for non-existent file."""
        with patch("shelfr.ffmpeg.get_settings", return_value=mock_settings):
            result = probe(tmp_path / "nonexistent.m4b")

        assert result.success is False
        assert "not found" in result.error.lower()

    def test_probe_success(self, tmp_path: Path, mock_settings: MagicMock) -> None:
        """Test successful probe."""
        test_file = tmp_path / "test.m4b"
        test_file.touch()

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = '{"format": {"duration": "3600.0"}, "streams": []}'
        mock_result.stderr = ""

        with (
            patch("shelfr.ffmpeg.get_settings", return_value=mock_settings),
            patch("shelfr.ffmpeg._run_docker_command", return_value=mock_result),
        ):
            result = probe(test_file)

        assert result.success is True

    def test_probe_extracts_duration(self, tmp_path: Path, mock_settings: MagicMock) -> None:
        """Test probe extracts duration correctly."""
        test_file = tmp_path / "test.m4b"
        test_file.touch()

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = '{"format": {"duration": "3661.5"}, "streams": []}'
        mock_result.stderr = ""

        with (
            patch("shelfr.ffmpeg.get_settings", return_value=mock_settings),
            patch("shelfr.ffmpeg._run_docker_command", return_value=mock_result),
        ):
            result = probe(test_file)

        assert result.success is True
        assert result.duration == 3661.5
        assert result.duration_str == "01:01:01"  # 1h 1m 1s

    def test_probe_extracts_audio_info(self, tmp_path: Path, mock_settings: MagicMock) -> None:
        """Test probe extracts audio stream info."""
        test_file = tmp_path / "test.m4b"
        test_file.touch()

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = """{
            "format": {},
            "streams": [
                {"codec_type": "audio", "codec_name": "aac", "sample_rate": "44100", "channels": 2}
            ]
        }"""
        mock_result.stderr = ""

        with (
            patch("shelfr.ffmpeg.get_settings", return_value=mock_settings),
            patch("shelfr.ffmpeg._run_docker_command", return_value=mock_result),
        ):
            result = probe(test_file)

        assert result.success is True
        assert result.codec_name == "aac"
        assert result.sample_rate == 44100
        assert result.channels == 2


# =============================================================================
# Utility Function Tests
# =============================================================================


class TestUtilityFunctions:
    """Tests for utility functions."""

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create mock settings."""
        settings = MagicMock()
        settings.docker_bin = "docker"
        settings.ffmpeg.image = "lscr.io/linuxserver/ffmpeg:latest"
        settings.ffmpeg.timeout_seconds = 60
        return settings

    def test_get_duration(self, tmp_path: Path, mock_settings: MagicMock) -> None:
        """Test get_duration convenience function."""
        test_file = tmp_path / "test.m4b"
        test_file.touch()

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = '{"format": {"duration": "1800.0"}, "streams": []}'
        mock_result.stderr = ""

        with (
            patch("shelfr.ffmpeg.get_settings", return_value=mock_settings),
            patch("shelfr.ffmpeg._run_docker_command", return_value=mock_result),
        ):
            duration = get_duration(test_file)

        assert duration == 1800.0

    def test_get_bitrate(self, tmp_path: Path, mock_settings: MagicMock) -> None:
        """Test get_bitrate convenience function."""
        test_file = tmp_path / "test.m4b"
        test_file.touch()

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = '{"format": {"bit_rate": "128000"}, "streams": []}'
        mock_result.stderr = ""

        with (
            patch("shelfr.ffmpeg.get_settings", return_value=mock_settings),
            patch("shelfr.ffmpeg._run_docker_command", return_value=mock_result),
        ):
            bitrate = get_bitrate(test_file)

        assert bitrate == 128000

    def test_is_available_true(self, mock_settings: MagicMock) -> None:
        """Test is_available returns True when image exists."""
        mock_result = MagicMock()
        mock_result.stdout = "abc123"  # Non-empty image ID

        with (
            patch("shelfr.ffmpeg.get_settings", return_value=mock_settings),
            patch("shelfr.ffmpeg.run", return_value=mock_result),
        ):
            assert is_available() is True

    def test_is_available_false(self, mock_settings: MagicMock) -> None:
        """Test is_available returns False when image doesn't exist."""
        mock_result = MagicMock()
        mock_result.stdout = ""  # Empty = no image

        with (
            patch("shelfr.ffmpeg.get_settings", return_value=mock_settings),
            patch("shelfr.ffmpeg.run", return_value=mock_result),
        ):
            assert is_available() is False

    def test_pull_image_success(self, mock_settings: MagicMock) -> None:
        """Test pull_image returns True on success."""
        mock_result = MagicMock()
        mock_result.exit_code = 0

        with (
            patch("shelfr.ffmpeg.get_settings", return_value=mock_settings),
            patch("shelfr.ffmpeg.run", return_value=mock_result),
        ):
            assert pull_image() is True

    def test_pull_image_failure(self, mock_settings: MagicMock) -> None:
        """Test pull_image returns False on failure."""
        mock_result = MagicMock()
        mock_result.exit_code = 1

        with (
            patch("shelfr.ffmpeg.get_settings", return_value=mock_settings),
            patch("shelfr.ffmpeg.run", return_value=mock_result),
        ):
            assert pull_image() is False

    def test_version_parses_correctly(self, mock_settings: MagicMock) -> None:
        """Test version extracts version string."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = "ffmpeg version 7.1.1 Copyright (c) 2000-2024"

        with (
            patch("shelfr.ffmpeg.get_settings", return_value=mock_settings),
            patch("shelfr.ffmpeg.run", return_value=mock_result),
        ):
            ver = version()

        assert ver == "7.1.1"

    def test_version_returns_none_on_failure(self, mock_settings: MagicMock) -> None:
        """Test version returns None on failure."""
        mock_result = MagicMock()
        mock_result.exit_code = 1
        mock_result.stdout = ""

        with (
            patch("shelfr.ffmpeg.get_settings", return_value=mock_settings),
            patch("shelfr.ffmpeg.run", return_value=mock_result),
        ):
            ver = version()

        assert ver is None


# =============================================================================
# Transcode Tests
# =============================================================================


class TestTranscode:
    """Tests for transcode function."""

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create mock settings."""
        settings = MagicMock()
        settings.docker_bin = "docker"
        settings.ffmpeg.image = "lscr.io/linuxserver/ffmpeg:latest"
        settings.ffmpeg.timeout_seconds = 1800
        return settings

    def test_transcode_input_not_found(self, tmp_path: Path, mock_settings: MagicMock) -> None:
        """Test transcode fails for non-existent input."""
        with patch("shelfr.ffmpeg.get_settings", return_value=mock_settings):
            result = transcode(
                tmp_path / "nonexistent.m4b",
                tmp_path / "output.m4b",
            )

        assert result.success is False
        assert "not found" in result.error.lower()

    def test_transcode_output_exists_no_overwrite(
        self, tmp_path: Path, mock_settings: MagicMock
    ) -> None:
        """Test transcode fails when output exists and overwrite=False."""
        input_file = tmp_path / "input.m4b"
        output_file = tmp_path / "output.m4b"
        input_file.touch()
        output_file.touch()

        with patch("shelfr.ffmpeg.get_settings", return_value=mock_settings):
            result = transcode(input_file, output_file, overwrite=False)

        assert result.success is False
        assert "exists" in result.error.lower()

    def test_transcode_success(self, tmp_path: Path, mock_settings: MagicMock) -> None:
        """Test successful transcode operation."""
        input_file = tmp_path / "input.m4b"
        output_file = tmp_path / "output.m4b"
        input_file.touch()

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        def create_output_and_return(*args: Any, **kwargs: Any) -> MagicMock:
            """Side effect that creates output file like FFmpeg would."""
            output_file.touch()
            return mock_result

        with (
            patch("shelfr.ffmpeg.get_settings", return_value=mock_settings),
            patch("shelfr.ffmpeg._run_docker_command", side_effect=create_output_and_return),
        ):
            result = transcode(input_file, output_file)

        assert result.success is True
        assert result.exit_code == 0
        assert result.output_path == output_file


class TestExtractAudio:
    """Tests for extract_audio function."""

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create mock settings."""
        settings = MagicMock()
        settings.docker_bin = "docker"
        settings.ffmpeg.image = "lscr.io/linuxserver/ffmpeg:latest"
        settings.ffmpeg.timeout_seconds = 1800
        return settings

    def test_extract_audio_calls_transcode(self, tmp_path: Path, mock_settings: MagicMock) -> None:
        """Test extract_audio uses transcode with correct args."""
        input_file = tmp_path / "input.mkv"
        output_file = tmp_path / "output.m4a"
        input_file.touch()

        with (
            patch("shelfr.ffmpeg.get_settings", return_value=mock_settings),
            patch("shelfr.ffmpeg.transcode") as mock_transcode,
        ):
            mock_transcode.return_value = FFmpegResult(success=True, exit_code=0)
            extract_audio(input_file, output_file)

            mock_transcode.assert_called_once()
            call_kwargs = mock_transcode.call_args[1]
            assert call_kwargs["audio_codec"] == "copy"
            assert "-vn" in call_kwargs["extra_args"]


# =============================================================================
# Audiobook / Audio-Focused Tests
# =============================================================================


class TestCopyAudio:
    """Tests for copy_audio function."""

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create mock settings."""
        settings = MagicMock()
        settings.docker_bin = "docker"
        settings.ffmpeg.image = "lscr.io/linuxserver/ffmpeg:latest"
        settings.ffmpeg.timeout_seconds = 1800
        return settings

    def test_copy_audio_input_not_found(self, tmp_path: Path, mock_settings: MagicMock) -> None:
        """Test copy_audio fails for non-existent input."""
        from shelfr.ffmpeg import copy_audio

        with patch("shelfr.ffmpeg.get_settings", return_value=mock_settings):
            result = copy_audio(
                tmp_path / "nonexistent.m4b",
                tmp_path / "output.m4b",
            )

        assert result.success is False
        assert result.error is not None
        assert "not found" in result.error.lower()

    def test_copy_audio_output_exists_no_overwrite(
        self, tmp_path: Path, mock_settings: MagicMock
    ) -> None:
        """Test copy_audio fails when output exists and overwrite=False."""
        from shelfr.ffmpeg import copy_audio

        input_file = tmp_path / "input.m4b"
        output_file = tmp_path / "output.m4b"
        input_file.touch()
        output_file.touch()

        with patch("shelfr.ffmpeg.get_settings", return_value=mock_settings):
            result = copy_audio(input_file, output_file, overwrite=False)

        assert result.success is False
        assert result.error is not None
        assert "exists" in result.error.lower()

    def test_copy_audio_builds_correct_command(
        self, tmp_path: Path, mock_settings: MagicMock
    ) -> None:
        """Test copy_audio builds correct FFmpeg command."""
        from shelfr.ffmpeg import copy_audio

        input_file = tmp_path / "input.m4b"
        output_file = tmp_path / "output.m4b"
        input_file.touch()
        # Output needs to exist after the "run" for verification
        output_file.touch()

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with (
            patch("shelfr.ffmpeg.get_settings", return_value=mock_settings),
            patch("shelfr.ffmpeg._run_docker_command", return_value=mock_result),
        ):
            result = copy_audio(input_file, output_file, overwrite=True)
            assert result.success is True

    def test_copy_audio_with_strip_tags(self, tmp_path: Path, mock_settings: MagicMock) -> None:
        """Test copy_audio includes strip_tags in command."""
        from shelfr.ffmpeg import copy_audio

        input_file = tmp_path / "input.m4b"
        output_file = tmp_path / "output.m4b"
        input_file.touch()
        output_file.touch()

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        captured_cmd: list[str] = []

        def capture_cmd(cmd: list[str], **kwargs: Any) -> MagicMock:
            captured_cmd.extend(cmd)
            return mock_result

        with (
            patch("shelfr.ffmpeg.get_settings", return_value=mock_settings),
            patch("shelfr.ffmpeg._run_docker_command", side_effect=capture_cmd),
        ):
            copy_audio(
                input_file,
                output_file,
                strip_tags=["AUDIBLE_ACR", "AUDIBLE_ASIN"],
                overwrite=True,
            )

        # Verify strip tags are in command
        cmd_str = " ".join(captured_cmd)
        assert "-metadata AUDIBLE_ACR=" in cmd_str
        assert "-metadata AUDIBLE_ASIN=" in cmd_str

    def test_copy_audio_with_set_tags(self, tmp_path: Path, mock_settings: MagicMock) -> None:
        """Test copy_audio includes set_tags in command."""
        from shelfr.ffmpeg import copy_audio

        input_file = tmp_path / "input.m4b"
        output_file = tmp_path / "output.m4b"
        input_file.touch()
        output_file.touch()

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        captured_cmd: list[str] = []

        def capture_cmd(cmd: list[str], **kwargs: Any) -> MagicMock:
            captured_cmd.extend(cmd)
            return mock_result

        with (
            patch("shelfr.ffmpeg.get_settings", return_value=mock_settings),
            patch("shelfr.ffmpeg._run_docker_command", side_effect=capture_cmd),
        ):
            copy_audio(
                input_file,
                output_file,
                set_tags={"title": "My Audiobook", "artist": "Author Name"},
                overwrite=True,
            )

        # Verify set tags are in command
        cmd_str = " ".join(captured_cmd)
        assert "-metadata title=My Audiobook" in cmd_str
        assert "-metadata artist=Author Name" in cmd_str

    def test_copy_audio_adds_format_for_nonstandard_extension(
        self, tmp_path: Path, mock_settings: MagicMock
    ) -> None:
        """Test copy_audio adds -f ipod when output has non-standard extension."""
        from shelfr.ffmpeg import copy_audio

        input_file = tmp_path / "input.m4b"
        # Simulate sanitize temp file naming: .m4b.sanitizing.12345
        output_file = tmp_path / "output.m4b.sanitizing.12345"
        input_file.touch()

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        captured_cmd: list[str] = []

        def capture_cmd(cmd: list[str], **kwargs: Any) -> MagicMock:
            captured_cmd.extend(cmd)
            return mock_result

        with (
            patch("shelfr.ffmpeg.get_settings", return_value=mock_settings),
            patch("shelfr.ffmpeg._run_docker_command", side_effect=capture_cmd),
        ):
            copy_audio(input_file, output_file, overwrite=True)

        # Verify -f ipod is in command for non-standard output extension
        cmd_str = " ".join(captured_cmd)
        assert "-f ipod" in cmd_str

    def test_copy_audio_no_format_for_standard_extension(
        self, tmp_path: Path, mock_settings: MagicMock
    ) -> None:
        """Test copy_audio does NOT add -f when output has standard .m4b extension."""
        from shelfr.ffmpeg import copy_audio

        input_file = tmp_path / "input.m4b"
        output_file = tmp_path / "output.m4b"  # Standard extension
        input_file.touch()

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        captured_cmd: list[str] = []

        def capture_cmd(cmd: list[str], **kwargs: Any) -> MagicMock:
            captured_cmd.extend(cmd)
            return mock_result

        with (
            patch("shelfr.ffmpeg.get_settings", return_value=mock_settings),
            patch("shelfr.ffmpeg._run_docker_command", side_effect=capture_cmd),
        ):
            copy_audio(input_file, output_file, overwrite=True)

        # Verify -f ipod is NOT in command for standard output extension
        cmd_str = " ".join(captured_cmd)
        assert "-f ipod" not in cmd_str


class TestStripAudibleTags:
    """Tests for strip_audible_tags function."""

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create mock settings."""
        settings = MagicMock()
        settings.docker_bin = "docker"
        settings.ffmpeg.image = "lscr.io/linuxserver/ffmpeg:latest"
        settings.ffmpeg.timeout_seconds = 1800
        return settings

    def test_strip_audible_tags_calls_copy_audio(
        self, tmp_path: Path, mock_settings: MagicMock
    ) -> None:
        """Test strip_audible_tags uses copy_audio with correct tags."""
        from shelfr.ffmpeg import strip_audible_tags

        input_file = tmp_path / "input.m4b"
        output_file = tmp_path / "output.m4b"
        input_file.touch()

        with (
            patch("shelfr.ffmpeg.get_settings", return_value=mock_settings),
            patch("shelfr.ffmpeg.copy_audio") as mock_copy,
        ):
            mock_copy.return_value = FFmpegResult(success=True, exit_code=0)
            strip_audible_tags(input_file, output_file)

            mock_copy.assert_called_once()
            call_kwargs = mock_copy.call_args[1]
            assert "AUDIBLE_ACR" in call_kwargs["strip_tags"]
            assert len(call_kwargs["strip_tags"]) == 1  # Only AUDIBLE_ACR for now


class TestGetAudioTags:
    """Tests for get_audio_tags function."""

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create mock settings."""
        settings = MagicMock()
        settings.docker_bin = "docker"
        settings.ffmpeg.image = "lscr.io/linuxserver/ffmpeg:latest"
        settings.ffmpeg.timeout_seconds = 60
        return settings

    def test_get_audio_tags_success(self, tmp_path: Path, mock_settings: MagicMock) -> None:
        """Test get_audio_tags returns tags dict."""
        from shelfr.ffmpeg import get_audio_tags

        test_file = tmp_path / "test.m4b"
        test_file.touch()

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = """{
            "format": {
                "tags": {
                    "title": "My Audiobook",
                    "artist": "Author",
                    "AUDIBLE_ACR": "some_value"
                }
            },
            "streams": []
        }"""
        mock_result.stderr = ""

        with (
            patch("shelfr.ffmpeg.get_settings", return_value=mock_settings),
            patch("shelfr.ffmpeg._run_docker_command", return_value=mock_result),
        ):
            tags = get_audio_tags(test_file)

        assert tags is not None
        assert tags["title"] == "My Audiobook"
        assert tags["artist"] == "Author"
        assert tags["AUDIBLE_ACR"] == "some_value"

    def test_get_audio_tags_failure(self, tmp_path: Path, mock_settings: MagicMock) -> None:
        """Test get_audio_tags returns None on failure."""
        from shelfr.ffmpeg import get_audio_tags

        with patch("shelfr.ffmpeg.get_settings", return_value=mock_settings):
            tags = get_audio_tags(tmp_path / "nonexistent.m4b")

        assert tags is None


class TestGetChapters:
    """Tests for get_chapters function."""

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create mock settings."""
        settings = MagicMock()
        settings.docker_bin = "docker"
        settings.ffmpeg.image = "lscr.io/linuxserver/ffmpeg:latest"
        settings.ffmpeg.timeout_seconds = 60
        return settings

    def test_get_chapters_success(self, tmp_path: Path, mock_settings: MagicMock) -> None:
        """Test get_chapters returns chapter list."""
        from shelfr.ffmpeg import get_chapters

        test_file = tmp_path / "test.m4b"
        test_file.touch()

        mock_result = MagicMock()
        mock_result.exit_code = 0
        # Note: chapters are at top level in ffprobe JSON, not in format
        mock_result.stdout = """{
            "chapters": [
                {"start": 0, "end": 1000, "title": "Chapter 1"},
                {"start": 1000, "end": 2000, "title": "Chapter 2"}
            ],
            "format": {},
            "streams": []
        }"""
        mock_result.stderr = ""

        with (
            patch("shelfr.ffmpeg.get_settings", return_value=mock_settings),
            patch("shelfr.ffmpeg._run_docker_command", return_value=mock_result),
        ):
            chapters = get_chapters(test_file)

        assert chapters is not None
        assert len(chapters) == 2
        assert chapters[0]["title"] == "Chapter 1"

    def test_get_chapters_failure(self, tmp_path: Path, mock_settings: MagicMock) -> None:
        """Test get_chapters returns None on failure."""
        from shelfr.ffmpeg import get_chapters

        with patch("shelfr.ffmpeg.get_settings", return_value=mock_settings):
            chapters = get_chapters(tmp_path / "nonexistent.m4b")

        assert chapters is None
