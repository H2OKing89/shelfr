"""Tests for libation module."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mamfast.exceptions import LibationError
from mamfast.libation import (
    LibationStatus,
    ScanResult,
    check_container_running,
    get_libation_status,
    run_liberate,
    run_scan,
)
from mamfast.utils.cmd import CmdError, CmdResult
from tests.conftest import make_cmd_result

# Alias for backwards compatibility with existing tests
_make_cmd_result = make_cmd_result


class TestScanResult:
    """Tests for ScanResult dataclass."""

    def test_success_when_returncode_zero(self) -> None:
        """Test success property is True when returncode is 0."""
        result = ScanResult(returncode=0, stdout="OK")
        assert result.success is True

    def test_failure_when_returncode_nonzero(self) -> None:
        """Test success property is False when returncode is non-zero."""
        result = ScanResult(returncode=1, stderr="Error")
        assert result.success is False


class TestCheckContainerRunning:
    """Tests for check_container_running function."""

    def test_container_running(self) -> None:
        """Test detecting running container."""
        mock_result = _make_cmd_result(stdout="true\n")

        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"
        mock_settings.libation_container = "Libation"

        with (
            patch("mamfast.libation.docker", return_value=mock_result),
            patch("mamfast.libation.get_settings", return_value=mock_settings),
        ):
            assert check_container_running() is True

    def test_container_not_running(self) -> None:
        """Test detecting stopped container."""
        mock_result = _make_cmd_result(stdout="false\n")

        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"
        mock_settings.libation_container = "Libation"

        with (
            patch("mamfast.libation.docker", return_value=mock_result),
            patch("mamfast.libation.get_settings", return_value=mock_settings),
        ):
            assert check_container_running() is False

    def test_docker_command_fails(self) -> None:
        """Test handling docker command failure."""
        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"
        mock_settings.libation_container = "Libation"

        with (
            patch(
                "mamfast.libation.docker",
                side_effect=CmdError(
                    argv=["docker"],
                    exit_code=1,
                    stdout="",
                    stderr="Error",
                ),
            ),
            patch("mamfast.libation.get_settings", return_value=mock_settings),
        ):
            assert check_container_running() is False

    def test_exception_returns_false(self) -> None:
        """Test that exceptions return False."""
        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"
        mock_settings.libation_container = "Libation"

        with (
            patch("mamfast.libation.docker", side_effect=OSError("Docker not found")),
            patch("mamfast.libation.get_settings", return_value=mock_settings),
        ):
            assert check_container_running() is False


class TestRunScan:
    """Tests for run_scan function."""

    def test_scan_success(self) -> None:
        """Test successful scan."""
        mock_result = _make_cmd_result(stdout="Scanned 5 books", exit_code=0)

        mock_settings = MagicMock()
        mock_settings.libation_container = "Libation"
        mock_settings.docker_bin = "/usr/bin/docker"

        with (
            patch("mamfast.libation.run", return_value=mock_result),
            patch("mamfast.libation.get_settings", return_value=mock_settings),
        ):
            result = run_scan()
            assert result.success is True
            assert result.returncode == 0

    def test_scan_failure(self) -> None:
        """Test failed scan."""
        with (
            patch(
                "mamfast.libation.run",
                side_effect=CmdError(
                    argv=["docker", "exec"],
                    exit_code=1,
                    stdout="",
                    stderr="Error",
                ),
            ),
            patch("mamfast.libation.get_settings", return_value=MagicMock()),
        ):
            result = run_scan()
            assert result.success is False

    def test_scan_docker_not_found(self) -> None:
        """Test scan when docker binary is missing."""
        mock_settings = MagicMock()
        mock_settings.docker_bin = "/nonexistent/docker"
        mock_settings.libation_container = "Libation"

        with (
            patch(
                "mamfast.libation.run",
                side_effect=CmdError(
                    argv=["docker"],
                    exit_code=127,
                    stdout="",
                    stderr="Command not found: docker",
                ),
            ),
            patch("mamfast.libation.get_settings", return_value=mock_settings),
        ):
            result = run_scan()
            assert result.success is False
            assert result.returncode == 127


class TestRunLiberate:
    """Tests for run_liberate function."""

    def test_liberate_success(self) -> None:
        """Test successful liberate."""
        mock_result = _make_cmd_result(stdout="Downloaded 3 books", exit_code=0)

        mock_settings = MagicMock()
        mock_settings.libation_container = "Libation"
        mock_settings.docker_bin = "/usr/bin/docker"

        with (
            patch("mamfast.libation.docker", return_value=mock_result),
            patch("mamfast.libation.get_settings", return_value=mock_settings),
        ):
            result = run_liberate()
            assert result.success is True

    def test_liberate_with_asin(self) -> None:
        """Test liberate with specific ASIN."""
        mock_result = _make_cmd_result(stdout="Downloaded 1 book", exit_code=0)

        mock_settings = MagicMock()
        mock_settings.libation_container = "Libation"
        mock_settings.docker_bin = "/usr/bin/docker"

        with (
            patch("mamfast.libation.docker", return_value=mock_result) as mock_docker,
            patch("mamfast.libation.get_settings", return_value=mock_settings),
        ):
            result = run_liberate(asin="B01234567X")
            assert result.success is True
            # Verify ASIN was passed to command
            call_args = mock_docker.call_args[0]
            assert "B01234567X" in call_args

    def test_liberate_failure(self) -> None:
        """Test failed liberate."""
        mock_settings = MagicMock()
        mock_settings.libation_container = "Libation"
        mock_settings.docker_bin = "/usr/bin/docker"

        with (
            patch(
                "mamfast.libation.docker",
                side_effect=CmdError(
                    argv=["docker", "exec"],
                    exit_code=1,
                    stdout="",
                    stderr="Error downloading",
                ),
            ),
            patch("mamfast.libation.get_settings", return_value=mock_settings),
        ):
            result = run_liberate()
            assert result.success is False

    def test_liberate_exception(self) -> None:
        """Test liberate when exception occurs."""
        mock_settings = MagicMock()
        mock_settings.libation_container = "Libation"
        mock_settings.docker_bin = "/usr/bin/docker"

        with (
            patch(
                "mamfast.libation.docker",
                side_effect=RuntimeError("Unexpected error"),
            ),
            patch("mamfast.libation.get_settings", return_value=mock_settings),
        ):
            result = run_liberate()
            assert result.success is False
            assert result.returncode == -1
            assert "Unexpected error" in result.stderr


class TestRunScanInteractive:
    """Tests for run_scan interactive mode."""

    def test_scan_interactive_success(self) -> None:
        """Test successful interactive scan."""
        mock_result = _make_cmd_result(exit_code=0)

        mock_settings = MagicMock()
        mock_settings.libation_container = "Libation"
        mock_settings.docker_bin = "/usr/bin/docker"

        with (
            patch("mamfast.libation.run", return_value=mock_result) as mock_run,
            patch("mamfast.libation.get_settings", return_value=mock_settings),
        ):
            result = run_scan(interactive=True)
            assert result.success is True
            # Verify -i flag is passed (interactive mode)
            call_args = mock_run.call_args[0][0]
            assert "-i" in call_args

    def test_scan_interactive_failure(self) -> None:
        """Test failed interactive scan."""
        with (
            patch(
                "mamfast.libation.run",
                side_effect=CmdError(
                    argv=["docker", "exec"],
                    exit_code=1,
                    stdout="",
                    stderr="Error",
                ),
            ),
            patch("mamfast.libation.get_settings", return_value=MagicMock()),
        ):
            result = run_scan(interactive=True)
            assert result.success is False

    def test_scan_exception_generic(self) -> None:
        """Test scan with generic exception."""
        mock_settings = MagicMock()
        mock_settings.libation_container = "Libation"
        mock_settings.docker_bin = "/usr/bin/docker"

        with (
            patch("mamfast.libation.run", side_effect=RuntimeError("Docker crash")),
            patch("mamfast.libation.get_settings", return_value=mock_settings),
        ):
            result = run_scan()
            assert result.success is False
            assert result.returncode == -1
            assert "Docker crash" in result.stderr


class TestLibationStatus:
    """Tests for LibationStatus dataclass."""

    def test_has_pending_true_when_not_liberated(self) -> None:
        """Test has_pending is True when not_liberated > 0."""
        status = LibationStatus(
            total=100,
            liberated=80,
            not_liberated=20,
        )
        assert status.has_pending is True

    def test_has_pending_false_when_all_liberated(self) -> None:
        """Test has_pending is False when not_liberated == 0."""
        status = LibationStatus(
            total=100,
            liberated=100,
            not_liberated=0,
        )
        assert status.has_pending is False

    def test_other_statuses_included(self) -> None:
        """Test that other status types are captured."""
        status = LibationStatus(
            total=105,
            liberated=100,
            not_liberated=2,
            error=1,
            other_statuses={"Unknown": 2},
        )
        assert status.total == 105
        assert status.error == 1
        assert status.other_statuses == {"Unknown": 2}

    def test_default_values(self) -> None:
        """Test default values for optional fields."""
        status = LibationStatus(
            total=10,
            liberated=10,
            not_liberated=0,
        )
        assert status.error == 0
        assert status.other_statuses == {}


class TestGetLibationStatus:
    """Tests for get_libation_status function."""

    def _create_mock_settings(self) -> MagicMock:
        """Create mock settings for tests."""
        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"
        mock_settings.libation_container = "Libation"
        return mock_settings

    def _make_export_json(
        self,
        liberated: int = 0,
        not_liberated: int = 0,
        error: int = 0,
        other: dict[str, int] | None = None,
    ) -> str:
        """Create mock export JSON with given status counts."""
        books = []
        for _ in range(liberated):
            books.append({"BookStatus": "Liberated", "Title": "Book"})
        for _ in range(not_liberated):
            books.append({"BookStatus": "NotLiberated", "Title": "Book"})
        for _ in range(error):
            books.append({"BookStatus": "Error", "Title": "Book"})
        if other:
            for status, count in other.items():
                for _ in range(count):
                    books.append({"BookStatus": status, "Title": "Book"})
        return json.dumps(books)

    def test_get_status_all_liberated(self) -> None:
        """Test status check when all books are liberated."""
        mock_settings = self._create_mock_settings()
        export_json = self._make_export_json(liberated=100)

        # Mock docker() - returns CmdResult for export, then JSON for cat
        def side_effect(*args: str, **kwargs: Any) -> CmdResult:
            if "export" in args:
                return _make_cmd_result(stdout="Library exported")
            elif "cat" in args:
                return _make_cmd_result(stdout=export_json)
            else:  # cleanup rm
                return _make_cmd_result()

        with (
            patch("mamfast.libation.docker", side_effect=side_effect),
            patch("mamfast.libation.get_settings", return_value=mock_settings),
        ):
            status = get_libation_status()
            assert status.total == 100
            assert status.liberated == 100
            assert status.not_liberated == 0
            assert status.has_pending is False

    def test_get_status_with_pending(self) -> None:
        """Test status check when books are pending."""
        mock_settings = self._create_mock_settings()
        export_json = self._make_export_json(liberated=80, not_liberated=20)

        def side_effect(*args: str, **kwargs: Any) -> CmdResult:
            if "export" in args:
                return _make_cmd_result()
            elif "cat" in args:
                return _make_cmd_result(stdout=export_json)
            else:
                return _make_cmd_result()

        with (
            patch("mamfast.libation.docker", side_effect=side_effect),
            patch("mamfast.libation.get_settings", return_value=mock_settings),
        ):
            status = get_libation_status()
            assert status.total == 100
            assert status.liberated == 80
            assert status.not_liberated == 20
            assert status.has_pending is True

    def test_get_status_with_errors(self) -> None:
        """Test status check with error books."""
        mock_settings = self._create_mock_settings()
        export_json = self._make_export_json(liberated=95, not_liberated=3, error=2)

        def side_effect(*args: str, **kwargs: Any) -> CmdResult:
            if "export" in args:
                return _make_cmd_result()
            elif "cat" in args:
                return _make_cmd_result(stdout=export_json)
            else:
                return _make_cmd_result()

        with (
            patch("mamfast.libation.docker", side_effect=side_effect),
            patch("mamfast.libation.get_settings", return_value=mock_settings),
        ):
            status = get_libation_status()
            assert status.total == 100
            assert status.liberated == 95
            assert status.not_liberated == 3
            assert status.error == 2

    def test_get_status_with_unknown_status(self) -> None:
        """Test status check with unknown status types."""
        mock_settings = self._create_mock_settings()
        export_json = self._make_export_json(
            liberated=90,
            not_liberated=5,
            other={"SomeNewStatus": 3, "AnotherStatus": 2},
        )

        def side_effect(*args: str, **kwargs: Any) -> CmdResult:
            if "export" in args:
                return _make_cmd_result()
            elif "cat" in args:
                return _make_cmd_result(stdout=export_json)
            else:
                return _make_cmd_result()

        with (
            patch("mamfast.libation.docker", side_effect=side_effect),
            patch("mamfast.libation.get_settings", return_value=mock_settings),
        ):
            status = get_libation_status()
            assert status.total == 100
            assert status.liberated == 90
            assert status.not_liberated == 5
            assert status.other_statuses == {"SomeNewStatus": 3, "AnotherStatus": 2}

    def test_get_status_export_fails(self) -> None:
        """Test error when export command fails."""
        mock_settings = self._create_mock_settings()

        def side_effect(*args: str, **kwargs: Any) -> CmdResult:
            if "export" in args:
                raise CmdError(
                    argv=["docker", "exec"],
                    exit_code=1,
                    stdout="",
                    stderr="Export failed",
                )
            return _make_cmd_result()

        with (
            patch("mamfast.libation.docker", side_effect=side_effect),
            patch("mamfast.libation.get_settings", return_value=mock_settings),
            pytest.raises(LibationError, match="Docker command failed"),
        ):
            get_libation_status()

    def test_get_status_cat_fails(self) -> None:
        """Test error when reading export file fails."""
        mock_settings = self._create_mock_settings()
        call_count = [0]

        def side_effect(*args: str, **kwargs: Any) -> CmdResult:
            call_count[0] += 1
            if "export" in args:
                return _make_cmd_result()
            elif "cat" in args:
                raise CmdError(
                    argv=["docker", "exec"],
                    exit_code=1,
                    stdout="",
                    stderr="No such file",
                )
            return _make_cmd_result()

        with (
            patch("mamfast.libation.docker", side_effect=side_effect),
            patch("mamfast.libation.get_settings", return_value=mock_settings),
            pytest.raises(LibationError, match="Docker command failed"),
        ):
            get_libation_status()

    def test_get_status_invalid_json(self) -> None:
        """Test error when JSON is invalid."""
        mock_settings = self._create_mock_settings()

        def side_effect(*args: str, **kwargs: Any) -> CmdResult:
            if "export" in args:
                return _make_cmd_result()
            elif "cat" in args:
                return _make_cmd_result(stdout="not valid json {{")
            return _make_cmd_result()

        with (
            patch("mamfast.libation.docker", side_effect=side_effect),
            patch("mamfast.libation.get_settings", return_value=mock_settings),
            pytest.raises(LibationError, match="Failed to parse Libation export JSON"),
        ):
            get_libation_status()

    def test_get_status_json_not_list(self) -> None:
        """Test error when JSON is not a list."""
        mock_settings = self._create_mock_settings()

        def side_effect(*args: str, **kwargs: Any) -> CmdResult:
            if "export" in args:
                return _make_cmd_result()
            elif "cat" in args:
                return _make_cmd_result(stdout='{"not": "a list"}')
            return _make_cmd_result()

        with (
            patch("mamfast.libation.docker", side_effect=side_effect),
            patch("mamfast.libation.get_settings", return_value=mock_settings),
            pytest.raises(LibationError, match="Expected list from export"),
        ):
            get_libation_status()

    def test_get_status_docker_not_found(self) -> None:
        """Test error when docker binary is missing."""
        mock_settings = self._create_mock_settings()

        def side_effect(*args: str, **kwargs: Any) -> CmdResult:
            raise CmdError(
                argv=["docker"],
                exit_code=127,
                stdout="",
                stderr="Command not found: docker",
            )

        with (
            patch("mamfast.libation.docker", side_effect=side_effect),
            patch("mamfast.libation.get_settings", return_value=mock_settings),
            pytest.raises(LibationError, match="Docker command failed"),
        ):
            get_libation_status()

    def test_get_status_cleanup_runs_even_on_error(self) -> None:
        """Test that cleanup runs even when export fails."""
        mock_settings = self._create_mock_settings()
        cleanup_called = []

        def side_effect(*args: str, **kwargs: Any) -> CmdResult:
            if "export" in args:
                raise CmdError(
                    argv=["docker", "exec"],
                    exit_code=1,
                    stdout="",
                    stderr="Export failed",
                )
            elif "rm" in args:
                cleanup_called.append(True)
                return _make_cmd_result()
            return _make_cmd_result()

        with (
            patch("mamfast.libation.docker", side_effect=side_effect),
            patch("mamfast.libation.get_settings", return_value=mock_settings),
        ):
            with pytest.raises(LibationError):
                get_libation_status()
            # Cleanup should have been called
            assert len(cleanup_called) == 1

    def test_get_status_empty_library(self) -> None:
        """Test status check with empty library."""
        mock_settings = self._create_mock_settings()
        export_json = "[]"

        def side_effect(*args: str, **kwargs: Any) -> CmdResult:
            if "export" in args:
                return _make_cmd_result()
            elif "cat" in args:
                return _make_cmd_result(stdout=export_json)
            return _make_cmd_result()

        with (
            patch("mamfast.libation.docker", side_effect=side_effect),
            patch("mamfast.libation.get_settings", return_value=mock_settings),
        ):
            status = get_libation_status()
            assert status.total == 0
            assert status.liberated == 0
            assert status.not_liberated == 0
            assert status.has_pending is False


# =============================================================================
# Parse Libation Output Tests
# =============================================================================


class TestParseLibationOutput:
    """Tests for _parse_libation_output function."""

    def test_parses_completed_books(self) -> None:
        """Should extract completed book entries from stdout."""
        from mamfast.libation import _parse_libation_output

        stdout = """DownloadDecryptBook Begin: 12/21/2025 [B0FHHH1FVQ] Book Title
DownloadDecryptBook Completed: 12/21/2025 [B0FHHH1FVQ] Book Title
Done. All books have been processed"""
        stderr = ""

        result = _parse_libation_output(stdout, stderr)
        assert len(result["completed"]) == 1
        assert "B0FHHH1FVQ" in result["completed"][0]
        assert result["has_book_errors"] is False
        assert len(result["errors"]) == 0

    def test_detects_error_in_stderr(self) -> None:
        """Should detect error messages in stderr."""
        from mamfast.libation import _parse_libation_output

        stdout = """DownloadDecryptBook Begin: 12/21/2025 [B0FHHH1FVQ] Book Title
DownloadDecryptBook Completed: 12/21/2025 [B0FHHH1FVQ] Book Title
Done. All books have been processed"""
        # Real Libation error message (truncated for line length)
        stderr = "Error processing book. Skipping. This book will be tried again."

        result = _parse_libation_output(stdout, stderr)
        assert result["has_book_errors"] is True
        assert len(result["errors"]) > 0

    def test_handles_empty_output(self) -> None:
        """Should handle empty stdout and stderr."""
        from mamfast.libation import _parse_libation_output

        result = _parse_libation_output("", "")
        assert len(result["completed"]) == 0
        assert len(result["errors"]) == 0
        assert result["has_book_errors"] is False

    def test_multiple_completed_books(self) -> None:
        """Should track multiple completed books."""
        from mamfast.libation import _parse_libation_output

        stdout = """DownloadDecryptBook Completed: 12/21/2025 [ASIN1] Book One
DownloadDecryptBook Completed: 12/21/2025 [ASIN2] Book Two
DownloadDecryptBook Completed: 12/21/2025 [ASIN3] Book Three"""
        stderr = ""

        result = _parse_libation_output(stdout, stderr)
        assert len(result["completed"]) == 3

    def test_detects_failed_keyword(self) -> None:
        """Should detect 'failed' keyword in stderr."""
        from mamfast.libation import _parse_libation_output

        stdout = ""
        stderr = "Download failed for book ASIN123"

        result = _parse_libation_output(stdout, stderr)
        assert result["has_book_errors"] is True


class TestLiberateProgressResult:
    """Tests for LiberateProgressResult dataclass."""

    def test_default_values(self) -> None:
        """Test default field values."""
        from mamfast.libation import LiberateProgressResult

        result = LiberateProgressResult(success=True, returncode=0)
        assert result.success is True
        assert result.returncode == 0
        assert result.downloaded_count == 0
        assert result.skipped_count == 0
        assert result.log_path is None
        assert result.error_message == ""
        assert result.has_book_errors is False

    def test_with_book_errors(self) -> None:
        """Test result with book-level errors."""
        from mamfast.libation import LiberateProgressResult

        result = LiberateProgressResult(
            success=True,
            returncode=0,
            downloaded_count=5,
            skipped_count=1,
            error_message="Error processing book",
            has_book_errors=True,
        )
        assert result.success is True  # Command succeeded
        assert result.has_book_errors is True  # But some books failed
        assert result.skipped_count == 1


class TestRunLiberateWithProgressTimeout:
    """Tests for timeout handling in run_liberate_with_progress."""

    def test_passthrough_timeout_returns_failure(self) -> None:
        """Test that passthrough mode returns failure on timeout."""
        import subprocess

        from rich.console import Console

        from mamfast.libation import LiberateProgressResult, run_liberate_with_progress

        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"
        mock_settings.libation_container = "Libation"

        mock_console = MagicMock(spec=Console)

        with (
            patch("mamfast.libation.get_settings", return_value=mock_settings),
            patch("mamfast.libation._is_tty", return_value=True),  # Force TTY
            patch(
                "mamfast.libation.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=3600),
            ),
        ):
            result = run_liberate_with_progress(
                pending_count=1,
                console=mock_console,
                verbose=True,  # verbose + TTY = passthrough mode
            )
            assert isinstance(result, LiberateProgressResult)
            assert result.success is False
            assert result.returncode == -1
            assert "timed out" in result.error_message.lower()

    def test_spinner_timeout_returns_failure(self) -> None:
        """Test that spinner mode returns failure on timeout."""
        import subprocess

        from rich.console import Console

        from mamfast.libation import LiberateProgressResult, run_liberate_with_progress

        mock_settings = MagicMock()
        mock_settings.docker_bin = "/usr/bin/docker"
        mock_settings.libation_container = "Libation"

        mock_console = MagicMock(spec=Console)

        with (
            patch("mamfast.libation.get_settings", return_value=mock_settings),
            patch("mamfast.libation._is_tty", return_value=False),  # Force non-TTY
            patch(
                "mamfast.libation.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=3600),
            ),
        ):
            result = run_liberate_with_progress(
                pending_count=1,
                console=mock_console,
                verbose=False,
            )
            assert isinstance(result, LiberateProgressResult)
            assert result.success is False
            assert result.returncode == -1
            assert "timed out" in result.error_message.lower()
