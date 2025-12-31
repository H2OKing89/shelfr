"""Integration tests for the Shelfr pipeline."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from shelfr.models import AudiobookRelease, ReleaseStatus
from shelfr.validation import ValidationResult
from shelfr.workflow import PipelineResult, full_run, process_single_release


def _create_passing_validation_result() -> ValidationResult:
    """Create a ValidationResult that passes all checks."""
    result = ValidationResult()
    return result


class TestProcessSingleRelease:
    """Integration tests for processing a single release through the pipeline."""

    @patch("shelfr.workflow.get_processed_identifiers")
    @patch("shelfr.workflow.mark_failed")
    @patch("shelfr.workflow.checkpoint_stage")
    @patch("shelfr.workflow.should_skip_stage", return_value=False)
    @patch("shelfr.workflow.DiscoveryValidation")
    @patch("shelfr.workflow.PreUploadValidation")
    @patch("shelfr.workflow.get_settings")
    @patch("shelfr.workflow.generate_mam_json_for_release")
    @patch("shelfr.workflow.upload_torrent")
    @patch("shelfr.workflow.create_torrent")
    @patch("shelfr.workflow._fetch_metadata_with_retry")
    @patch("shelfr.workflow.stage_release")
    @patch("shelfr.workflow.mark_processed")
    def test_full_pipeline_success(
        self,
        mock_mark_processed: Mock,
        mock_stage: Mock,
        mock_metadata: Mock,
        mock_torrent: Mock,
        mock_upload: Mock,
        mock_mam_json: Mock,
        mock_settings: Mock,
        mock_pre_upload_validation: Mock,
        mock_discovery_validation: Mock,
        mock_should_skip_stage: Mock,
        mock_checkpoint_stage: Mock,
        mock_mark_failed: Mock,
        mock_get_processed: Mock,
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

            # Mock processed identifiers (empty set = nothing processed yet)
            mock_get_processed.return_value = set()

            # Mock validation to pass
            mock_discovery_validation.return_value.validate.return_value = (
                _create_passing_validation_result()
            )
            mock_pre_upload_validation.return_value.validate.return_value = (
                _create_passing_validation_result()
            )

            # Mock the pipeline steps
            mock_stage.return_value = staging_dir
            mock_metadata.return_value = ({"title": "Test"}, {"media": {}}, {"chapters": []})

            mock_torrent_result = MagicMock()
            mock_torrent_result.success = True
            mock_torrent_result.torrent_path = torrent_path
            mock_torrent.return_value = mock_torrent_result

            mock_upload.return_value = (True, "abc123def456")

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
            mock_mark_processed.assert_called_once_with(release, infohash="abc123def456")

    @patch("shelfr.workflow.get_processed_identifiers")
    @patch("shelfr.workflow.checkpoint_stage")
    @patch("shelfr.workflow.should_skip_stage", return_value=False)
    @patch("shelfr.workflow.DiscoveryValidation")
    @patch("shelfr.workflow.PreUploadValidation")
    @patch("shelfr.workflow.get_settings")
    @patch("shelfr.workflow.upload_torrent")
    @patch("shelfr.workflow.create_torrent")
    @patch("shelfr.workflow.stage_release")
    @patch("shelfr.workflow.mark_failed")
    def test_pipeline_failure_in_torrent_creation(
        self,
        mock_mark_failed: Mock,
        mock_stage: Mock,
        mock_torrent: Mock,
        mock_upload: Mock,
        mock_settings: Mock,
        mock_pre_upload_validation: Mock,
        mock_discovery_validation: Mock,
        mock_should_skip_stage: Mock,
        mock_checkpoint_stage: Mock,
        mock_get_processed: Mock,
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

            # Mock processed identifiers
            mock_get_processed.return_value = set()

            # Mock validation to pass
            mock_discovery_validation.return_value.validate.return_value = (
                _create_passing_validation_result()
            )
            mock_pre_upload_validation.return_value.validate.return_value = (
                _create_passing_validation_result()
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

    @patch("shelfr.workflow.get_processed_identifiers")
    @patch("shelfr.workflow.checkpoint_stage")
    @patch("shelfr.workflow.should_skip_stage", return_value=False)
    @patch("shelfr.workflow.DiscoveryValidation")
    @patch("shelfr.workflow.PreUploadValidation")
    @patch("shelfr.workflow.get_settings")
    @patch("shelfr.workflow.upload_torrent")
    @patch("shelfr.workflow.create_torrent")
    @patch("shelfr.workflow.stage_release")
    @patch("shelfr.workflow.mark_failed")
    def test_pipeline_failure_in_upload(
        self,
        mock_mark_failed: Mock,
        mock_stage: Mock,
        mock_torrent: Mock,
        mock_upload: Mock,
        mock_settings: Mock,
        mock_pre_upload_validation: Mock,
        mock_discovery_validation: Mock,
        mock_should_skip_stage: Mock,
        mock_checkpoint_stage: Mock,
        mock_get_processed: Mock,
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

            # Mock processed identifiers
            mock_get_processed.return_value = set()

            # Mock validation to pass
            mock_discovery_validation.return_value.validate.return_value = (
                _create_passing_validation_result()
            )
            mock_pre_upload_validation.return_value.validate.return_value = (
                _create_passing_validation_result()
            )

            mock_stage.return_value = staging_dir

            mock_torrent_result = MagicMock()
            mock_torrent_result.success = True
            mock_torrent_result.torrent_path = torrent_path
            mock_torrent.return_value = mock_torrent_result

            mock_upload.return_value = (False, None)  # Upload fails

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

    @patch("shelfr.workflow.PreflightValidation")
    @patch("shelfr.workflow.get_settings")
    @patch("shelfr.discovery.get_new_releases")
    @patch("shelfr.workflow.run_liberate")
    @patch("shelfr.workflow.run_scan")
    def test_full_run_with_no_releases(
        self,
        mock_scan: Mock,
        mock_liberate: Mock,
        mock_get_releases: Mock,
        mock_settings: Mock,
        mock_preflight: Mock,
    ) -> None:
        """Test full run when no new releases are found."""
        # Arrange - mock preflight validation to pass
        mock_preflight.return_value.validate.return_value = _create_passing_validation_result()
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

    @patch("shelfr.workflow.PreflightValidation")
    @patch("shelfr.workflow.get_settings")
    @patch("shelfr.workflow.DiscoveryValidation")
    @patch("shelfr.workflow.get_processed_identifiers")
    @patch("shelfr.workflow.is_processed")
    @patch("shelfr.workflow.process_single_release")
    @patch("shelfr.discovery.get_new_releases")
    @patch("shelfr.workflow.run_liberate")
    @patch("shelfr.workflow.run_scan")
    def test_full_run_skips_already_processed(
        self,
        mock_scan: Mock,
        mock_liberate: Mock,
        mock_get_releases: Mock,
        mock_process: Mock,
        mock_is_processed: Mock,
        mock_get_processed_ids: Mock,
        mock_discovery_validation: Mock,
        mock_settings: Mock,
        mock_preflight: Mock,
    ) -> None:
        """Test that full run skips already processed releases."""
        # Arrange - mock preflight validation to pass
        mock_preflight.return_value.validate.return_value = _create_passing_validation_result()

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
        mock_get_processed_ids.return_value = {"B000TEST04"}  # Mock processed identifiers

        # Mock validation to pass
        mock_validation_result = MagicMock()
        mock_validation_result.passed = True
        mock_validation_result.warning_count = 0
        mock_validation_result.checks = []
        mock_discovery_validation.return_value.validate.return_value = mock_validation_result

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
            patch("shelfr.workflow.get_settings"),
            patch("shelfr.workflow.run_scan") as mock_scan,
            patch("shelfr.workflow.run_liberate") as mock_liberate,
            patch("shelfr.discovery.get_new_releases") as mock_releases,
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
        from shelfr.config import ConfigurationError, validate_required_env_vars
        from shelfr.env_settings import clear_env_settings_cache

        # Clear cache to ensure fresh settings are loaded
        clear_env_settings_cache()

        with (
            patch.dict("os.environ", {}, clear=True),
            pytest.raises(ConfigurationError) as exc_info,
        ):
            validate_required_env_vars()

        assert "QB_HOST" in str(exc_info.value)
        assert "QB_USERNAME" in str(exc_info.value)

    def test_invalid_url_format(self) -> None:
        """Test that invalid URLs are rejected."""
        from shelfr.config import ConfigurationError, validate_url

        with pytest.raises(ConfigurationError) as exc_info:
            validate_url("not-a-url", "TEST_URL")

        assert "http://" in str(exc_info.value) or "https://" in str(exc_info.value)


class TestAtomicStateWrites:
    """Integration tests for atomic state file writes."""

    def test_state_file_atomicity(self) -> None:
        """Test that state files are written atomically."""
        from shelfr.utils.state import save_state

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            with patch("shelfr.utils.state._get_state_file", return_value=tmppath / "state.json"):
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


class TestWorkflowSavePathLogic:
    """Tests for qb_save_path logic in workflow functions."""

    @patch("shelfr.workflow.get_processed_identifiers")
    @patch("shelfr.workflow.mark_failed")
    @patch("shelfr.workflow.checkpoint_stage")
    @patch("shelfr.workflow.should_skip_stage", return_value=False)
    @patch("shelfr.workflow.DiscoveryValidation")
    @patch("shelfr.workflow.PreUploadValidation")
    @patch("shelfr.workflow.get_settings")
    @patch("shelfr.workflow.generate_mam_json_for_release")
    @patch("shelfr.workflow.upload_torrent")
    @patch("shelfr.workflow.create_torrent")
    @patch("shelfr.workflow._fetch_metadata_with_retry")
    @patch("shelfr.workflow.stage_release")
    @patch("shelfr.workflow.mark_processed")
    def test_auto_tmm_enabled_no_save_path(
        self,
        mock_mark_processed: Mock,
        mock_stage: Mock,
        mock_metadata: Mock,
        mock_torrent: Mock,
        mock_upload: Mock,
        mock_mam_json: Mock,
        mock_settings: Mock,
        mock_pre_upload_validation: Mock,
        mock_discovery_validation: Mock,
        mock_should_skip_stage: Mock,
        mock_checkpoint_stage: Mock,
        mock_mark_failed: Mock,
        mock_get_processed: Mock,
    ) -> None:
        """Test that save_path is None when auto_tmm is enabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            staging_dir = tmppath / "staged"
            staging_dir.mkdir()
            torrent_path = tmppath / "test.torrent"
            torrent_path.touch()

            release = AudiobookRelease(
                title="Test Book",
                author="Test Author",
                asin="B000TEST04",
                source_dir=tmppath / "source",
            )

            # Mock processed identifiers
            mock_get_processed.return_value = set()

            # Mock validation to pass
            mock_discovery_validation.return_value.validate.return_value = (
                _create_passing_validation_result()
            )
            mock_pre_upload_validation.return_value.validate.return_value = (
                _create_passing_validation_result()
            )

            mock_stage.return_value = staging_dir
            mock_metadata.return_value = ({"title": "Test"}, {"media": {}}, {"chapters": []})

            mock_torrent_result = MagicMock()
            mock_torrent_result.success = True
            mock_torrent_result.torrent_path = torrent_path
            mock_torrent.return_value = mock_torrent_result

            mock_upload.return_value = (True, "abc123")

            # Configure auto_tmm = True
            mock_settings.return_value.qbittorrent.auto_tmm = True
            mock_settings.return_value.qbittorrent.save_path = "/some/path"

            result = process_single_release(release)

            assert result.success
            # Verify upload was called with save_path=None
            mock_upload.assert_called_once()
            call_kwargs = mock_upload.call_args[1]
            assert call_kwargs["save_path"] is None

    @patch("shelfr.workflow.get_processed_identifiers")
    @patch("shelfr.workflow.mark_failed")
    @patch("shelfr.workflow.checkpoint_stage")
    @patch("shelfr.workflow.should_skip_stage", return_value=False)
    @patch("shelfr.workflow.DiscoveryValidation")
    @patch("shelfr.workflow.PreUploadValidation")
    @patch("shelfr.workflow.get_settings")
    @patch("shelfr.workflow.generate_mam_json_for_release")
    @patch("shelfr.workflow.upload_torrent")
    @patch("shelfr.workflow.create_torrent")
    @patch("shelfr.workflow._fetch_metadata_with_retry")
    @patch("shelfr.workflow.stage_release")
    @patch("shelfr.workflow.mark_processed")
    def test_auto_tmm_disabled_with_save_path(
        self,
        mock_mark_processed: Mock,
        mock_stage: Mock,
        mock_metadata: Mock,
        mock_torrent: Mock,
        mock_upload: Mock,
        mock_mam_json: Mock,
        mock_settings: Mock,
        mock_pre_upload_validation: Mock,
        mock_discovery_validation: Mock,
        mock_should_skip_stage: Mock,
        mock_checkpoint_stage: Mock,
        mock_mark_failed: Mock,
        mock_get_processed: Mock,
    ) -> None:
        """Test that save_path is constructed when auto_tmm is disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            staging_dir = tmppath / "staged"
            staging_dir.mkdir()
            torrent_path = tmppath / "test.torrent"
            torrent_path.touch()

            release = AudiobookRelease(
                title="Test Book",
                author="Test Author",
                asin="B000TEST05",
                source_dir=tmppath / "source",
            )

            # Mock processed identifiers
            mock_get_processed.return_value = set()

            # Mock validation to pass
            mock_discovery_validation.return_value.validate.return_value = (
                _create_passing_validation_result()
            )
            mock_pre_upload_validation.return_value.validate.return_value = (
                _create_passing_validation_result()
            )

            mock_stage.return_value = staging_dir
            mock_metadata.return_value = ({"title": "Test"}, {"media": {}}, {"chapters": []})

            mock_torrent_result = MagicMock()
            mock_torrent_result.success = True
            mock_torrent_result.torrent_path = torrent_path
            mock_torrent.return_value = mock_torrent_result

            mock_upload.return_value = (True, "abc123")

            # Configure auto_tmm = False with save_path
            mock_settings.return_value.qbittorrent.auto_tmm = False
            mock_settings.return_value.qbittorrent.save_path = "/config/save/path"

            result = process_single_release(release)

            assert result.success
            # Verify upload was called with constructed save_path
            mock_upload.assert_called_once()
            call_kwargs = mock_upload.call_args[1]
            expected_path = Path("/config/save/path") / staging_dir.name
            assert call_kwargs["save_path"] == expected_path

    @patch("shelfr.workflow.get_processed_identifiers")
    @patch("shelfr.workflow.mark_failed")
    @patch("shelfr.workflow.checkpoint_stage")
    @patch("shelfr.workflow.should_skip_stage", return_value=False)
    @patch("shelfr.workflow.DiscoveryValidation")
    @patch("shelfr.workflow.PreUploadValidation")
    @patch("shelfr.workflow.get_settings")
    @patch("shelfr.workflow.generate_mam_json_for_release")
    @patch("shelfr.workflow.upload_torrent")
    @patch("shelfr.workflow.create_torrent")
    @patch("shelfr.workflow._fetch_metadata_with_retry")
    @patch("shelfr.workflow.stage_release")
    @patch("shelfr.workflow.mark_processed")
    def test_auto_tmm_disabled_no_save_path_configured(
        self,
        mock_mark_processed: Mock,
        mock_stage: Mock,
        mock_metadata: Mock,
        mock_torrent: Mock,
        mock_upload: Mock,
        mock_mam_json: Mock,
        mock_settings: Mock,
        mock_pre_upload_validation: Mock,
        mock_discovery_validation: Mock,
        mock_should_skip_stage: Mock,
        mock_checkpoint_stage: Mock,
        mock_mark_failed: Mock,
        mock_get_processed: Mock,
    ) -> None:
        """Test that save_path is None when auto_tmm is disabled and no path configured."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            staging_dir = tmppath / "staged"
            staging_dir.mkdir()
            torrent_path = tmppath / "test.torrent"
            torrent_path.touch()

            release = AudiobookRelease(
                title="Test Book",
                author="Test Author",
                asin="B000TEST06",
                source_dir=tmppath / "source",
            )

            # Mock processed identifiers
            mock_get_processed.return_value = set()

            # Mock validation to pass
            mock_discovery_validation.return_value.validate.return_value = (
                _create_passing_validation_result()
            )
            mock_pre_upload_validation.return_value.validate.return_value = (
                _create_passing_validation_result()
            )

            mock_stage.return_value = staging_dir
            mock_metadata.return_value = ({"title": "Test"}, {"media": {}}, {"chapters": []})

            mock_torrent_result = MagicMock()
            mock_torrent_result.success = True
            mock_torrent_result.torrent_path = torrent_path
            mock_torrent.return_value = mock_torrent_result

            mock_upload.return_value = (True, "abc123")

            # Configure auto_tmm = False with empty save_path
            mock_settings.return_value.qbittorrent.auto_tmm = False
            mock_settings.return_value.qbittorrent.save_path = ""

            result = process_single_release(release)

            assert result.success
            # Verify upload was called with save_path=None
            mock_upload.assert_called_once()
            call_kwargs = mock_upload.call_args[1]
            assert call_kwargs["save_path"] is None


class TestUploadOnlyPresetStripping:
    """Tests for preset prefix stripping in upload_only function."""

    @patch("shelfr.workflow.get_settings")
    @patch("shelfr.workflow.upload_torrent")
    def test_strips_preset_prefix_from_torrent_name(
        self,
        mock_upload: Mock,
        mock_settings: Mock,
    ) -> None:
        """Test that mkbrr preset prefix is stripped from torrent name for save_path."""
        from shelfr.workflow import upload_only

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create torrent file with preset prefix
            torrent_file = tmppath / "myanonamouse_My Audiobook [2024].torrent"
            torrent_file.touch()

            mock_settings.return_value.paths.torrent_output = tmppath
            mock_settings.return_value.qbittorrent.auto_tmm = False
            mock_settings.return_value.qbittorrent.save_path = "/data/audiobooks"
            mock_settings.return_value.mkbrr.preset = "myanonamouse"
            mock_upload.return_value = (True, "abc123")

            upload_only([torrent_file])

            # Verify save_path uses the name without preset prefix
            call_kwargs = mock_upload.call_args[1]
            expected_path = Path("/data/audiobooks") / "My Audiobook [2024]"
            assert call_kwargs["save_path"] == expected_path

    @patch("shelfr.workflow.get_settings")
    @patch("shelfr.workflow.upload_torrent")
    def test_no_stripping_when_no_prefix_match(
        self,
        mock_upload: Mock,
        mock_settings: Mock,
    ) -> None:
        """Test that name is used as-is when no preset prefix matches."""
        from shelfr.workflow import upload_only

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create torrent file without preset prefix
            torrent_file = tmppath / "My Audiobook [2024].torrent"
            torrent_file.touch()

            mock_settings.return_value.paths.torrent_output = tmppath
            mock_settings.return_value.qbittorrent.auto_tmm = False
            mock_settings.return_value.qbittorrent.save_path = "/data/audiobooks"
            mock_settings.return_value.mkbrr.preset = "myanonamouse"
            mock_upload.return_value = (True, "abc123")

            upload_only([torrent_file])

            # Verify save_path uses the full name (no prefix to strip)
            call_kwargs = mock_upload.call_args[1]
            expected_path = Path("/data/audiobooks") / "My Audiobook [2024]"
            assert call_kwargs["save_path"] == expected_path

    @patch("shelfr.workflow.get_settings")
    @patch("shelfr.workflow.upload_torrent")
    def test_auto_tmm_enabled_no_save_path(
        self,
        mock_upload: Mock,
        mock_settings: Mock,
    ) -> None:
        """Test that save_path is None when auto_tmm is enabled in upload_only."""
        from shelfr.workflow import upload_only

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            torrent_file = tmppath / "test.torrent"
            torrent_file.touch()

            mock_settings.return_value.paths.torrent_output = tmppath
            mock_settings.return_value.qbittorrent.auto_tmm = True
            mock_settings.return_value.qbittorrent.save_path = "/data/audiobooks"
            mock_upload.return_value = (True, "abc123")

            upload_only([torrent_file])

            # Verify save_path is None when auto_tmm is enabled
            call_kwargs = mock_upload.call_args[1]
            assert call_kwargs["save_path"] is None
