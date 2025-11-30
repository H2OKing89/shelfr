"""Integration tests for the MAMFast pipeline."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from mamfast.models import AudiobookRelease, ReleaseStatus
from mamfast.workflow import PipelineResult, full_run, process_single_release


class TestProcessSingleRelease:
    """Integration tests for processing a single release through the pipeline."""

    @patch("mamfast.workflow.upload_torrent")
    @patch("mamfast.workflow.create_torrent")
    @patch("mamfast.workflow.fetch_all_metadata")
    @patch("mamfast.workflow.stage_release")
    @patch("mamfast.workflow.mark_processed")
    def test_full_pipeline_success(
        self,
        mock_mark_processed: Mock,
        mock_stage: Mock,
        mock_metadata: Mock,
        mock_torrent: Mock,
        mock_upload: Mock,
    ) -> None:
        """Test successful processing of a single release through all steps."""
        # Arrange
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            staging_dir = tmppath / "staged"
            staging_dir.mkdir()
            torrent_path = tmppath / "test.torrent"
            torrent_path.touch()

            release = AudiobookRelease(
                title="Test Book",
                author="Test Author",
                asin="B000TEST01",
                source_dir=tmppath / "source",
            )

            # Mock the pipeline steps
            mock_stage.return_value = staging_dir
            mock_metadata.return_value = ({"title": "Test"}, {"media": {}})

            mock_torrent_result = MagicMock()
            mock_torrent_result.success = True
            mock_torrent_result.torrent_path = torrent_path
            mock_torrent.return_value = mock_torrent_result

            mock_upload.return_value = True

            # Act
            result = process_single_release(release)

            # Assert
            assert result.success
            assert result.release.status == ReleaseStatus.COMPLETE
            assert result.torrent_path == torrent_path

            # Verify all steps were called
            mock_stage.assert_called_once_with(release)
            mock_metadata.assert_called_once()
            mock_torrent.assert_called_once()
            mock_upload.assert_called_once()
            mock_mark_processed.assert_called_once_with(release)

    @patch("mamfast.workflow.upload_torrent")
    @patch("mamfast.workflow.create_torrent")
    @patch("mamfast.workflow.stage_release")
    @patch("mamfast.workflow.mark_failed")
    def test_pipeline_failure_in_torrent_creation(
        self,
        mock_mark_failed: Mock,
        mock_stage: Mock,
        mock_torrent: Mock,
        mock_upload: Mock,
    ) -> None:
        """Test that pipeline handles torrent creation failure correctly."""
        # Arrange
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            staging_dir = tmppath / "staged"
            staging_dir.mkdir()

            release = AudiobookRelease(
                title="Test Book",
                author="Test Author",
                asin="B000TEST02",
            )

            mock_stage.return_value = staging_dir

            mock_torrent_result = MagicMock()
            mock_torrent_result.success = False
            mock_torrent_result.error = "mkbrr failed"
            mock_torrent.return_value = mock_torrent_result

            # Act
            result = process_single_release(release, skip_metadata=True)

            # Assert
            assert not result.success
            assert result.error is not None
            assert "mkbrr failed" in result.error
            assert result.release.status == ReleaseStatus.FAILED

            # Verify failure was recorded
            mock_mark_failed.assert_called_once()
            # Upload should not be called if torrent creation fails
            mock_upload.assert_not_called()

    @patch("mamfast.workflow.upload_torrent")
    @patch("mamfast.workflow.create_torrent")
    @patch("mamfast.workflow.stage_release")
    @patch("mamfast.workflow.mark_failed")
    def test_pipeline_failure_in_upload(
        self,
        mock_mark_failed: Mock,
        mock_stage: Mock,
        mock_torrent: Mock,
        mock_upload: Mock,
    ) -> None:
        """Test that pipeline handles upload failure correctly."""
        # Arrange
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            staging_dir = tmppath / "staged"
            staging_dir.mkdir()
            torrent_path = tmppath / "test.torrent"
            torrent_path.touch()

            release = AudiobookRelease(
                title="Test Book",
                author="Test Author",
                asin="B000TEST03",
            )

            mock_stage.return_value = staging_dir

            mock_torrent_result = MagicMock()
            mock_torrent_result.success = True
            mock_torrent_result.torrent_path = torrent_path
            mock_torrent.return_value = mock_torrent_result

            mock_upload.return_value = False  # Upload fails

            # Act
            result = process_single_release(release, skip_metadata=True)

            # Assert
            assert not result.success
            assert result.error is not None
            assert "qBittorrent" in result.error
            assert result.release.status == ReleaseStatus.FAILED

            # Verify failure was recorded
            mock_mark_failed.assert_called_once()


class TestFullPipeline:
    """Integration tests for the full pipeline."""

    @patch("mamfast.discovery.get_new_releases")
    @patch("mamfast.workflow.run_liberate")
    @patch("mamfast.workflow.run_scan")
    def test_full_run_with_no_releases(
        self,
        mock_scan: Mock,
        mock_liberate: Mock,
        mock_get_releases: Mock,
    ) -> None:
        """Test full run when no new releases are found."""
        # Arrange
        mock_scan_result = MagicMock()
        mock_scan_result.success = True
        mock_scan.return_value = mock_scan_result

        mock_liberate_result = MagicMock()
        mock_liberate_result.success = True
        mock_liberate.return_value = mock_liberate_result

        mock_get_releases.return_value = []

        # Act
        result = full_run()

        # Assert
        assert isinstance(result, PipelineResult)
        assert result.total == 0
        assert result.successful == 0
        assert result.failed == 0
        assert result.skipped == 0

        # Verify scan was called
        mock_scan.assert_called_once()
        mock_liberate.assert_called_once()

    @patch("mamfast.workflow.is_processed")
    @patch("mamfast.workflow.process_single_release")
    @patch("mamfast.discovery.get_new_releases")
    @patch("mamfast.workflow.run_liberate")
    @patch("mamfast.workflow.run_scan")
    def test_full_run_skips_already_processed(
        self,
        mock_scan: Mock,
        mock_liberate: Mock,
        mock_get_releases: Mock,
        mock_process: Mock,
        mock_is_processed: Mock,
    ) -> None:
        """Test that full run skips already processed releases."""
        # Arrange
        mock_scan_result = MagicMock()
        mock_scan_result.success = True
        mock_scan.return_value = mock_scan_result

        mock_liberate_result = MagicMock()
        mock_liberate_result.success = True
        mock_liberate.return_value = mock_liberate_result

        release1 = AudiobookRelease(
            title="Already Processed",
            asin="B000TEST04",
        )
        release2 = AudiobookRelease(
            title="New Release",
            asin="B000TEST05",
        )

        mock_get_releases.return_value = [release1, release2]
        mock_is_processed.side_effect = lambda x: x == "B000TEST04"

        mock_result = MagicMock()
        mock_result.success = True
        mock_process.return_value = mock_result

        # Act
        result = full_run()

        # Assert
        assert result.total == 2
        assert result.successful == 1
        assert result.skipped == 1

        # process_single_release should only be called for the new release
        mock_process.assert_called_once()

    def test_full_run_dry_run_mode(self) -> None:
        """Test that dry run mode shows what would happen without making changes."""
        # This is a smoke test - just ensure dry run doesn't crash
        with (
            patch("mamfast.workflow.run_scan") as mock_scan,
            patch("mamfast.workflow.run_liberate") as mock_liberate,
            patch("mamfast.discovery.get_new_releases") as mock_releases,
        ):
            mock_scan.return_value = MagicMock(success=True)
            mock_liberate.return_value = MagicMock(success=True)
            mock_releases.return_value = []

            result = full_run(dry_run=True)

            assert result.total == 0
            # In dry run mode, scan should be skipped
            mock_scan.assert_not_called()
            mock_liberate.assert_not_called()


class TestConfigurationValidation:
    """Integration tests for configuration validation."""

    def test_missing_required_env_vars(self) -> None:
        """Test that missing required environment variables are detected."""
        from mamfast.config import ConfigurationError, validate_required_env_vars

        with (
            patch.dict("os.environ", {}, clear=True),
            pytest.raises(ConfigurationError) as exc_info,
        ):
            validate_required_env_vars()

        assert "QB_HOST" in str(exc_info.value)
        assert "QB_USERNAME" in str(exc_info.value)

    def test_invalid_url_format(self) -> None:
        """Test that invalid URLs are rejected."""
        from mamfast.config import ConfigurationError, validate_url

        with pytest.raises(ConfigurationError) as exc_info:
            validate_url("not-a-url", "TEST_URL")

        assert "http://" in str(exc_info.value) or "https://" in str(exc_info.value)


class TestAtomicStateWrites:
    """Integration tests for atomic state file writes."""

    def test_state_file_atomicity(self) -> None:
        """Test that state files are written atomically."""
        from mamfast.utils.state import save_state

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            with patch("mamfast.utils.state._get_state_file", return_value=tmppath / "state.json"):
                # Save a state
                state = {
                    "version": 1,
                    "processed": {"test": {"title": "Test"}},
                    "failed": {},
                }

                save_state(state)

                # Verify the state file exists and temp file doesn't
                assert (tmppath / "state.json").exists()
                assert not (tmppath / "state.tmp").exists()

                # Verify contents
                import json

                with open(tmppath / "state.json") as f:
                    loaded = json.load(f)

                assert loaded == state
