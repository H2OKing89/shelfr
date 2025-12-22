"""Tests for state management module."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mamfast.models import AudiobookRelease, ReleaseStatus
from mamfast.utils.state import (
    ALLOWED_TRANSITIONS,
    InvalidStatusTransitionError,
    checkpoint_stage,
    clear_failed,
    find_stale_entries,
    get_checkpoint,
    get_failed_identifiers,
    get_infohash,
    get_processed_identifiers,
    get_stats,
    is_failed,
    is_processed,
    load_state,
    mark_failed,
    mark_processed,
    prune_stale_entries,
    save_state,
    should_skip_stage,
    validate_status_transition,
)


@pytest.fixture
def temp_state_file(tmp_path: Path):
    """Create a temporary state file using pytest's tmp_path fixture."""
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"version": 1, "processed": {}, "failed": {}}))
    return state_file


@pytest.fixture
def mock_settings(temp_state_file):
    """Mock settings with temp state file."""
    settings = MagicMock()
    settings.paths.state_file = temp_state_file
    return settings


class TestLoadState:
    """Tests for load_state function."""

    def test_load_empty_state(self, mock_settings, tmp_path):
        """Test loading when no state file exists."""
        # Use a valid temp directory but non-existent file
        mock_settings.paths.state_file = tmp_path / "nonexistent_state.json"
        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            state = load_state()

        assert state["version"] == 2  # Current schema version
        assert state["processed"] == {}
        assert state["failed"] == {}

    def test_load_existing_state(self, mock_settings, temp_state_file):
        """Test loading existing state file."""
        # Write some state
        state_data = {
            "version": 1,
            "processed": {"B09TEST123": {"title": "Test Book"}},
            "failed": {},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            state = load_state()

        assert "B09TEST123" in state["processed"]


class TestSaveState:
    """Tests for save_state function."""

    def test_save_state(self, mock_settings, temp_state_file):
        """Test saving state to file."""
        state = {
            "version": 1,
            "processed": {"B09NEW123": {"title": "New Book"}},
            "failed": {},
        }

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            save_state(state)

        with open(temp_state_file) as f:
            saved = json.load(f)

        assert "B09NEW123" in saved["processed"]


class TestIsProcessed:
    """Tests for is_processed function."""

    def test_not_processed(self, mock_settings, temp_state_file):
        """Test checking unprocessed release."""
        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            assert is_processed("B09UNKNOWN") is False

    def test_is_processed(self, mock_settings, temp_state_file):
        """Test checking processed release."""
        state_data = {
            "version": 1,
            "processed": {"B09DONE123": {"title": "Done Book"}},
            "failed": {},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            assert is_processed("B09DONE123") is True


class TestMarkProcessed:
    """Tests for mark_processed function."""

    def test_mark_processed_with_asin(self, mock_settings, temp_state_file):
        """Test marking release as processed using ASIN."""
        release = AudiobookRelease(
            asin="B09MARK123",
            title="Marked Book",
            author="Test Author",
        )

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            mark_processed(release)
            assert is_processed("B09MARK123") is True

    def test_mark_processed_without_asin(self, mock_settings, temp_state_file):
        """Test marking release without ASIN uses path."""
        release = AudiobookRelease(
            title="No ASIN Book",
            source_dir=Path("/tmp/audiobooks/test"),
        )

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            mark_processed(release)
            assert is_processed("/tmp/audiobooks/test") is True


class TestGetProcessedIdentifiers:
    """Tests for get_processed_identifiers function."""

    def test_get_processed_identifiers(self, mock_settings, temp_state_file):
        """Test getting set of processed identifiers."""
        state_data = {
            "version": 1,
            "processed": {
                "B09ONE123": {},
                "B09TWO456": {},
            },
            "failed": {},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            identifiers = get_processed_identifiers()

        assert "B09ONE123" in identifiers
        assert "B09TWO456" in identifiers
        assert len(identifiers) == 2


class TestIsFailed:
    """Tests for is_failed function."""

    def test_not_failed(self, mock_settings, temp_state_file):
        """Test checking non-failed release."""
        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            assert is_failed("B09UNKNOWN") is False

    def test_is_failed(self, mock_settings, temp_state_file):
        """Test checking failed release."""
        state_data = {
            "version": 1,
            "processed": {},
            "failed": {"B09FAIL123": {"error": "Some error"}},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            assert is_failed("B09FAIL123") is True


class TestMarkFailed:
    """Tests for mark_failed function."""

    def test_mark_failed_with_asin(self, mock_settings, temp_state_file):
        """Test marking release as failed using ASIN."""
        release = AudiobookRelease(
            asin="B09FAIL123",
            title="Failed Book",
            author="Test Author",
        )

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            mark_failed(release, "Test error message")
            assert is_failed("B09FAIL123") is True

    def test_mark_failed_without_asin(self, mock_settings, temp_state_file):
        """Test marking release without ASIN uses path."""
        release = AudiobookRelease(
            title="No ASIN Book",
            source_dir=Path("/tmp/audiobooks/failed"),
        )

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            mark_failed(release, "Error occurred")
            assert is_failed("/tmp/audiobooks/failed") is True

    def test_mark_failed_no_identifier(self, mock_settings, temp_state_file):
        """Test marking fails without identifier."""
        release = AudiobookRelease(title="No ID Book")

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            # Should not raise, just log warning
            mark_failed(release, "Error")

    def test_mark_failed_increments_retry_count(self, mock_settings, temp_state_file):
        """Test that marking the same release failed multiple times increments retry_count."""
        release = AudiobookRelease(
            asin="B09RETRY01",
            title="Retry Book",
            author="Test Author",
        )

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            # First failure
            mark_failed(release, "First error")
            state = load_state()
            entry = state["failed"]["B09RETRY01"]
            assert entry["retry_count"] == 1
            first_failed = entry["first_failed_at"]

            # Second failure
            mark_failed(release, "Second error")
            state = load_state()
            entry = state["failed"]["B09RETRY01"]
            assert entry["retry_count"] == 2
            assert entry["error"] == "Second error"  # Updated
            assert entry["first_failed_at"] == first_failed  # Preserved

            # Third failure
            mark_failed(release, "Third error")
            state = load_state()
            entry = state["failed"]["B09RETRY01"]
            assert entry["retry_count"] == 3

    def test_mark_failed_with_error_type(self, mock_settings, temp_state_file):
        """Test that error_type is stored when provided."""
        release = AudiobookRelease(
            asin="B09ERRTYPE",
            title="Error Type Book",
        )

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            mark_failed(release, "Network timeout", error_type="NetworkError")
            state = load_state()

        entry = state["failed"]["B09ERRTYPE"]
        assert entry["error_type"] == "NetworkError"

    def test_mark_failed_preserves_first_failed_at(self, mock_settings, temp_state_file):
        """Test that first_failed_at is preserved across multiple failures."""
        # Pre-populate with existing failure
        state_data = {
            "version": 1,
            "processed": {},
            "failed": {
                "B09PRESERVE": {
                    "asin": "B09PRESERVE",
                    "title": "Old Failure",
                    "failed_at": "2024-01-01T00:00:00",
                    "first_failed_at": "2023-06-15T12:00:00",
                    "retry_count": 5,
                }
            },
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        release = AudiobookRelease(
            asin="B09PRESERVE",
            title="Preserved Book",
        )

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            mark_failed(release, "New error")
            state = load_state()

        entry = state["failed"]["B09PRESERVE"]
        assert entry["first_failed_at"] == "2023-06-15T12:00:00"  # Original preserved
        assert entry["retry_count"] == 6  # Incremented


class TestMarkProcessedRemovesFailed:
    """Test that mark_processed removes from failed."""

    def test_removes_from_failed(self, mock_settings, temp_state_file):
        """Test marking processed removes from failed state."""
        # First mark as failed
        state_data = {
            "version": 1,
            "processed": {},
            "failed": {"B09RETRY123": {"error": "Previous error"}},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        release = AudiobookRelease(asin="B09RETRY123", title="Retry Book")

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            mark_processed(release)
            assert is_processed("B09RETRY123") is True
            assert is_failed("B09RETRY123") is False

    def test_mark_processed_no_identifier(self, mock_settings, temp_state_file):
        """Test marking processed fails without identifier."""
        release = AudiobookRelease(title="No ID Book")

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            # Should not raise, just log warning
            mark_processed(release)


class TestClearFailed:
    """Tests for clear_failed function."""

    def test_clear_failed_success(self, mock_settings, temp_state_file):
        """Test clearing failed state."""
        state_data = {
            "version": 1,
            "processed": {},
            "failed": {"B09CLEAR123": {"error": "Some error"}},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            result = clear_failed("B09CLEAR123")
            assert result is True
            assert is_failed("B09CLEAR123") is False

    def test_clear_failed_not_found(self, mock_settings, temp_state_file):
        """Test clearing non-existent failed entry."""
        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            result = clear_failed("B09NOTFOUND")
            assert result is False


class TestGetFailedIdentifiers:
    """Tests for get_failed_identifiers function."""

    def test_get_failed_identifiers(self, mock_settings, temp_state_file):
        """Test getting set of failed identifiers."""
        state_data = {
            "version": 1,
            "processed": {},
            "failed": {
                "B09FAIL1": {"error": "Error 1"},
                "B09FAIL2": {"error": "Error 2"},
            },
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            identifiers = get_failed_identifiers()

        assert "B09FAIL1" in identifiers
        assert "B09FAIL2" in identifiers
        assert len(identifiers) == 2


class TestGetStats:
    """Tests for get_stats function."""

    def test_get_stats(self, mock_settings, temp_state_file):
        """Test getting state statistics."""
        state_data = {
            "version": 1,
            "processed": {"B001": {}, "B002": {}, "B003": {}},
            "failed": {"B004": {}, "B005": {}},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            stats = get_stats()

        assert stats["processed"] == 3
        assert stats["failed"] == 2


class TestLoadStateCorruptedFile:
    """Tests for handling corrupted state file with backup recovery."""

    def test_recovers_from_backup_when_main_corrupt(self, mock_settings, temp_state_file):
        """Test recovery from backup when main file is corrupt."""
        # Create valid backup
        backup_file = temp_state_file.with_suffix(".json.bak")
        backup_data = {
            "version": 1,
            "processed": {"B09BACKUP": {"title": "Recovered Book"}},
            "failed": {},
        }
        with open(backup_file, "w") as f:
            json.dump(backup_data, f)

        # Corrupt main file
        with open(temp_state_file, "w") as f:
            f.write("not valid json {{{")

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            state = load_state()

        # Should recover from backup
        assert "B09BACKUP" in state["processed"]
        assert state["processed"]["B09BACKUP"]["title"] == "Recovered Book"

    def test_raises_when_both_corrupt(self, mock_settings, temp_state_file):
        """Test that StateCorruptionError is raised when both files corrupt."""
        from mamfast.exceptions import StateCorruptionError

        # Corrupt main file
        with open(temp_state_file, "w") as f:
            f.write("not valid json {{{")

        # Corrupt backup file
        backup_file = temp_state_file.with_suffix(".json.bak")
        with open(backup_file, "w") as f:
            f.write("also not valid {{{")

        with (
            patch("mamfast.utils.state.get_settings", return_value=mock_settings),
            pytest.raises(StateCorruptionError) as exc_info,
        ):
            load_state()

        # Error message should contain recovery instructions
        assert "corrupt" in str(exc_info.value).lower()
        assert "rm" in str(exc_info.value)

    def test_raises_when_main_corrupt_no_backup(self, mock_settings, temp_state_file):
        """Test that StateCorruptionError is raised when main corrupt and no backup."""
        from mamfast.exceptions import StateCorruptionError

        # Corrupt main file
        with open(temp_state_file, "w") as f:
            f.write("not valid json {{{")

        # Ensure no backup exists
        backup_file = temp_state_file.with_suffix(".json.bak")
        if backup_file.exists():
            backup_file.unlink()

        with (
            patch("mamfast.utils.state.get_settings", return_value=mock_settings),
            pytest.raises(StateCorruptionError) as exc_info,
        ):
            load_state()

        assert "no backup" in str(exc_info.value).lower()

    def test_recovers_from_backup_when_main_missing(self, mock_settings, tmp_path):
        """Test recovery from backup when main file doesn't exist."""
        # Use non-existent main file path
        state_file = tmp_path / "missing_state.json"
        mock_settings.paths.state_file = state_file

        # Create backup at expected location
        backup_file = state_file.with_suffix(".json.bak")
        backup_data = {
            "version": 1,
            "processed": {"B09ORPHAN": {"title": "Orphan Recovery"}},
            "failed": {},
        }
        with open(backup_file, "w") as f:
            json.dump(backup_data, f)

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            state = load_state()

        # Should recover from orphaned backup
        assert "B09ORPHAN" in state["processed"]


class TestSaveStateBackup:
    """Tests for backup preservation during save."""

    def test_creates_backup_on_save(self, mock_settings, temp_state_file):
        """Test that saving state creates a backup of the previous version."""
        # Write initial state
        initial_data = {
            "version": 1,
            "processed": {"B09OLD": {"title": "Old Book"}},
            "failed": {},
        }
        with open(temp_state_file, "w") as f:
            json.dump(initial_data, f)

        # Save new state
        new_state = {
            "version": 1,
            "processed": {"B09NEW": {"title": "New Book"}},
            "failed": {},
        }
        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            save_state(new_state)

        # Backup should contain old data
        backup_file = temp_state_file.with_suffix(".json.bak")
        assert backup_file.exists()
        with open(backup_file) as f:
            backup_data = json.load(f)
        assert "B09OLD" in backup_data["processed"]

        # Main file should have new data
        with open(temp_state_file) as f:
            main_data = json.load(f)
        assert "B09NEW" in main_data["processed"]


# =============================================================================
# Checkpoint/Resume Tests (Step 1)
# =============================================================================


class TestCheckpointStage:
    """Tests for checkpoint_stage function."""

    def test_creates_checkpoint_structure(self, mock_settings, temp_state_file):
        """Test that checkpoint_stage creates proper entry structure."""
        release = AudiobookRelease(
            asin="B09CHECK01",
            title="Checkpoint Book",
            author="Test Author",
            status=ReleaseStatus.STAGED,
        )

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            checkpoint_stage(release, "staged")
            state = load_state()

        entry = state["processed"]["B09CHECK01"]
        assert entry["asin"] == "B09CHECK01"
        assert entry["title"] == "Checkpoint Book"
        assert entry["status"] == "STAGED"
        assert "checkpoints" in entry
        assert "staged_at" in entry["checkpoints"]
        # Verify timestamp is valid ISO format
        datetime.fromisoformat(entry["checkpoints"]["staged_at"])

    def test_updates_existing_entry(self, mock_settings, temp_state_file):
        """Test that checkpoint_stage updates existing entry without overwriting."""
        # Create initial entry
        state_data = {
            "version": 1,
            "processed": {
                "B09UPDATE": {
                    "asin": "B09UPDATE",
                    "title": "Original Title",
                    "author": "Original Author",
                    "processed_at": "2024-01-01T00:00:00",
                    "status": "STAGED",
                    "checkpoints": {"staged_at": "2024-01-01T00:00:00"},
                }
            },
            "failed": {},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        release = AudiobookRelease(
            asin="B09UPDATE",
            title="Updated Title",
            status=ReleaseStatus.METADATA_FETCHED,
        )

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            checkpoint_stage(release, "metadata")
            state = load_state()

        entry = state["processed"]["B09UPDATE"]
        # Original checkpoint preserved
        assert "staged_at" in entry["checkpoints"]
        # New checkpoint added
        assert "metadata_at" in entry["checkpoints"]
        # Status updated
        assert entry["status"] == "METADATA_FETCHED"

    def test_handles_missing_identifier(self, mock_settings, temp_state_file):
        """Test that checkpoint_stage handles release without identifier gracefully."""
        release = AudiobookRelease(title="No ID Book")

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            # Should not raise, just log warning
            checkpoint_stage(release, "staged")
            state = load_state()

        # No entry should be created
        assert state["processed"] == {}

    def test_stores_infohash_when_provided(self, mock_settings, temp_state_file):
        """Test that infohash is stored when provided."""
        release = AudiobookRelease(
            asin="B09HASH01",
            title="Hash Book",
            status=ReleaseStatus.TORRENT_CREATED,
        )

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            checkpoint_stage(release, "torrent", infohash="abc123def456")
            state = load_state()

        entry = state["processed"]["B09HASH01"]
        assert entry["infohash"] == "abc123def456"

    def test_updates_paths(self, mock_settings, temp_state_file, tmp_path):
        """Test that paths are updated when changed."""
        staging_dir = tmp_path / "staging" / "book"
        staging_dir.mkdir(parents=True)
        torrent_path = tmp_path / "torrents" / "book.torrent"
        torrent_path.parent.mkdir(parents=True)
        torrent_path.touch()

        release = AudiobookRelease(
            asin="B09PATHS",
            title="Path Book",
            status=ReleaseStatus.TORRENT_CREATED,
            staging_dir=staging_dir,
            torrent_path=torrent_path,
        )

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            checkpoint_stage(release, "torrent")
            state = load_state()

        entry = state["processed"]["B09PATHS"]
        assert entry["staging_dir"] == str(staging_dir)
        assert entry["torrent_path"] == str(torrent_path)


class TestGetCheckpoint:
    """Tests for get_checkpoint function."""

    def test_returns_none_when_missing_entry(self, mock_settings, temp_state_file):
        """Test that get_checkpoint returns None for non-existent entry."""
        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            result = get_checkpoint("B09NONEXIST", "staged")
        assert result is None

    def test_returns_none_when_missing_stage(self, mock_settings, temp_state_file):
        """Test that get_checkpoint returns None for missing stage."""
        state_data = {
            "version": 1,
            "processed": {
                "B09NOSTAGE": {
                    "asin": "B09NOSTAGE",
                    "checkpoints": {"staged_at": "2024-01-01T00:00:00"},
                }
            },
            "failed": {},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            result = get_checkpoint("B09NOSTAGE", "metadata")
        assert result is None

    def test_returns_datetime_when_present(self, mock_settings, temp_state_file):
        """Test that get_checkpoint returns timestamp when stage exists."""
        timestamp = "2024-06-15T10:30:00"
        state_data = {
            "version": 1,
            "processed": {
                "B09HASSTAGE": {
                    "asin": "B09HASSTAGE",
                    "checkpoints": {"staged_at": timestamp},
                }
            },
            "failed": {},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            result = get_checkpoint("B09HASSTAGE", "staged")
        assert result == timestamp

    def test_handles_legacy_entry_without_checkpoints(self, mock_settings, temp_state_file):
        """Test that get_checkpoint handles entries without checkpoints key."""
        state_data = {
            "version": 1,
            "processed": {
                "B09LEGACY": {
                    "asin": "B09LEGACY",
                    "title": "Legacy Book",
                    # No checkpoints key at all
                }
            },
            "failed": {},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            result = get_checkpoint("B09LEGACY", "staged")
        assert result is None


class TestGetInfohash:
    """Tests for get_infohash function."""

    def test_returns_none_when_missing_entry(self, mock_settings, temp_state_file):
        """Test that get_infohash returns None for non-existent entry."""
        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            result = get_infohash("B09NONEXIST")
        assert result is None

    def test_returns_none_when_missing_infohash(self, mock_settings, temp_state_file):
        """Test that get_infohash returns None when infohash not set."""
        state_data = {
            "version": 1,
            "processed": {
                "B09NOHASH": {
                    "asin": "B09NOHASH",
                    "infohash": None,
                }
            },
            "failed": {},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            result = get_infohash("B09NOHASH")
        assert result is None

    def test_returns_infohash_when_present(self, mock_settings, temp_state_file):
        """Test that get_infohash returns hash when present."""
        state_data = {
            "version": 1,
            "processed": {
                "B09HASHPRES": {
                    "asin": "B09HASHPRES",
                    "infohash": "deadbeef12345678",
                }
            },
            "failed": {},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            result = get_infohash("B09HASHPRES")
        assert result == "deadbeef12345678"


class TestShouldSkipStage:
    """Tests for should_skip_stage function."""

    def test_returns_false_no_identifier(self, mock_settings, temp_state_file):
        """Test that should_skip_stage returns False when no identifier."""
        release = AudiobookRelease(title="No ID Book")

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            result = should_skip_stage(release, "staged")
        assert result is False

    def test_returns_false_no_checkpoint(self, mock_settings, temp_state_file):
        """Test that should_skip_stage returns False when no checkpoint."""
        release = AudiobookRelease(asin="B09NOCHECK", title="No Checkpoint")

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            result = should_skip_stage(release, "staged")
        assert result is False

    def test_returns_true_when_checkpoint_exists(self, mock_settings, temp_state_file):
        """Test that should_skip_stage returns True when checkpoint exists."""
        state_data = {
            "version": 1,
            "processed": {
                "B09SKIPIT": {
                    "asin": "B09SKIPIT",
                    "checkpoints": {"staged_at": "2024-01-01T00:00:00"},
                }
            },
            "failed": {},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        release = AudiobookRelease(asin="B09SKIPIT", title="Skip Me")

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            result = should_skip_stage(release, "staged")
        assert result is True

    def test_returns_false_when_staging_dir_missing(self, mock_settings, temp_state_file, tmp_path):
        """Test that should_skip_stage returns False when staging_dir doesn't exist."""
        missing_dir = tmp_path / "nonexistent" / "staging"

        state_data = {
            "version": 1,
            "processed": {
                "B09MISSDIR": {
                    "asin": "B09MISSDIR",
                    "staging_dir": str(missing_dir),
                    "checkpoints": {"staged_at": "2024-01-01T00:00:00"},
                }
            },
            "failed": {},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        release = AudiobookRelease(asin="B09MISSDIR", title="Missing Dir", staging_dir=missing_dir)

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            result = should_skip_stage(release, "staged")
        assert result is False

    def test_returns_false_when_torrent_path_missing(
        self, mock_settings, temp_state_file, tmp_path
    ):
        """Test that should_skip_stage returns False when torrent_path doesn't exist."""
        missing_torrent = tmp_path / "nonexistent" / "file.torrent"

        state_data = {
            "version": 1,
            "processed": {
                "B09MISSTORR": {
                    "asin": "B09MISSTORR",
                    "torrent_path": str(missing_torrent),
                    "checkpoints": {"torrent_at": "2024-01-01T00:00:00"},
                }
            },
            "failed": {},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        release = AudiobookRelease(
            asin="B09MISSTORR", title="Missing Torrent", torrent_path=missing_torrent
        )

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            result = should_skip_stage(release, "torrent")
        assert result is False


class TestLegacyEntries:
    """Tests for handling legacy state entries with missing fields."""

    def test_entry_missing_checkpoints_key(self, mock_settings, temp_state_file):
        """Test that entries missing checkpoints key don't crash."""
        state_data = {
            "version": 1,
            "processed": {
                "B09NOCP": {
                    "asin": "B09NOCP",
                    "title": "No Checkpoints",
                    # Missing checkpoints key entirely
                }
            },
            "failed": {},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            # Should not crash
            assert is_processed("B09NOCP") is True
            assert get_checkpoint("B09NOCP", "staged") is None
            assert get_infohash("B09NOCP") is None

    def test_entry_missing_torrent_path(self, mock_settings, temp_state_file):
        """Test that entries missing torrent_path don't crash."""
        state_data = {
            "version": 1,
            "processed": {
                "B09NOTP": {
                    "asin": "B09NOTP",
                    "title": "No Torrent Path",
                    "checkpoints": {},
                    # Missing torrent_path
                }
            },
            "failed": {},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            release = AudiobookRelease(asin="B09NOTP", title="No Torrent Path")
            # Should not crash
            result = should_skip_stage(release, "torrent")
            assert result is False

    def test_entry_missing_staging_dir(self, mock_settings, temp_state_file):
        """Test that entries missing staging_dir don't crash."""
        state_data = {
            "version": 1,
            "processed": {
                "B09NOSD": {
                    "asin": "B09NOSD",
                    "title": "No Staging Dir",
                    "checkpoints": {},
                    # Missing staging_dir
                }
            },
            "failed": {},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            release = AudiobookRelease(asin="B09NOSD", title="No Staging Dir")
            # Should not crash
            result = should_skip_stage(release, "staged")
            assert result is False

    def test_entry_missing_infohash(self, mock_settings, temp_state_file):
        """Test that entries missing infohash don't crash."""
        state_data = {
            "version": 1,
            "processed": {
                "B09NOIH": {
                    "asin": "B09NOIH",
                    "title": "No Infohash",
                    # Missing infohash key
                }
            },
            "failed": {},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            result = get_infohash("B09NOIH")
            assert result is None


# =============================================================================
# Stale Entry Detection Tests (Step 3)
# =============================================================================


class TestFindStaleEntries:
    """Tests for status-aware stale entry detection."""

    def test_returns_empty_for_complete_entries(self, mock_settings, temp_state_file):
        """Test that COMPLETE entries with missing paths are NOT stale."""
        state_data = {
            "version": 1,
            "processed": {
                "B09COMPLETE": {
                    "asin": "B09COMPLETE",
                    "title": "Complete Book",
                    "status": "COMPLETE",
                    "staging_dir": "/nonexistent/staging",  # Missing but OK
                    "torrent_path": "/nonexistent/torrent.torrent",  # Missing but OK
                }
            },
            "failed": {},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            stale = find_stale_entries()

        # COMPLETE entries shouldn't be flagged even with missing paths
        assert len(stale) == 0

    def test_detects_stale_staged_entry(self, mock_settings, temp_state_file):
        """Test that STAGED entries with missing staging_dir are stale."""
        state_data = {
            "version": 1,
            "processed": {
                "B09STALE01": {
                    "asin": "B09STALE01",
                    "title": "Stale Staged Book",
                    "status": "STAGED",
                    "staging_dir": "/nonexistent/staging/book",
                }
            },
            "failed": {},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            stale = find_stale_entries()

        assert len(stale) == 1
        identifier, _title, status, missing = stale[0]
        assert identifier == "B09STALE01"
        assert status == "STAGED"
        assert missing == "staging_dir"

    def test_detects_stale_torrent_entry(self, mock_settings, temp_state_file, tmp_path):
        """Test that TORRENT_CREATED entries need both staging_dir and torrent_path."""
        # Create staging_dir but not torrent_path
        staging_dir = tmp_path / "staging" / "book"
        staging_dir.mkdir(parents=True)

        state_data = {
            "version": 1,
            "processed": {
                "B09STALE02": {
                    "asin": "B09STALE02",
                    "title": "Missing Torrent",
                    "status": "TORRENT_CREATED",
                    "staging_dir": str(staging_dir),
                    "torrent_path": "/nonexistent/missing.torrent",
                }
            },
            "failed": {},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            stale = find_stale_entries()

        assert len(stale) == 1
        _identifier, _title, _status, missing = stale[0]
        assert missing == "torrent_path"

    def test_uploaded_only_needs_torrent_path(self, mock_settings, temp_state_file, tmp_path):
        """Test that UPLOADED entries only need torrent_path (staging may be gone)."""
        # Create torrent_path but not staging_dir
        torrent_path = tmp_path / "torrents" / "book.torrent"
        torrent_path.parent.mkdir(parents=True)
        torrent_path.touch()

        state_data = {
            "version": 1,
            "processed": {
                "B09UPLOAD": {
                    "asin": "B09UPLOAD",
                    "title": "Uploaded Book",
                    "status": "UPLOADED",
                    "staging_dir": "/nonexistent/staging",  # Missing but OK for UPLOADED
                    "torrent_path": str(torrent_path),
                }
            },
            "failed": {},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            stale = find_stale_entries()

        # UPLOADED with existing torrent_path should NOT be stale
        assert len(stale) == 0

    def test_handles_null_paths(self, mock_settings, temp_state_file):
        """Test that null/None paths don't cause crashes."""
        state_data = {
            "version": 1,
            "processed": {
                "B09NULL": {
                    "asin": "B09NULL",
                    "title": "Null Paths",
                    "status": "STAGED",
                    "staging_dir": None,  # Null path
                }
            },
            "failed": {},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            # Should not crash
            stale = find_stale_entries()

        # Null path is not "missing" - it's just not set
        assert len(stale) == 0


class TestPruneStaleEntries:
    """Tests for stale entry pruning."""

    def test_prune_dry_run(self, mock_settings, temp_state_file):
        """Test that dry_run doesn't actually remove entries."""
        state_data = {
            "version": 1,
            "processed": {
                "B09PRUNE01": {
                    "asin": "B09PRUNE01",
                    "title": "Stale Book",
                    "status": "STAGED",
                    "staging_dir": "/nonexistent/path",
                }
            },
            "failed": {},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            removed = prune_stale_entries(dry_run=True)
            assert len(removed) == 1
            assert removed[0][0] == "B09PRUNE01"

            # Entry should still exist
            assert is_processed("B09PRUNE01") is True

    def test_prune_removes_stale(self, mock_settings, temp_state_file):
        """Test that prune actually removes stale entries."""
        state_data = {
            "version": 1,
            "processed": {
                "B09PRUNE02": {
                    "asin": "B09PRUNE02",
                    "title": "Stale Book",
                    "status": "STAGED",
                    "staging_dir": "/nonexistent/path",
                }
            },
            "failed": {},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            removed = prune_stale_entries(dry_run=False)
            assert len(removed) == 1

            # Entry should be gone
            assert is_processed("B09PRUNE02") is False

    def test_prune_preserves_valid_entries(self, mock_settings, temp_state_file, tmp_path):
        """Test that pruning preserves valid entries."""
        # Create real staging dir
        staging_dir = tmp_path / "staging" / "valid"
        staging_dir.mkdir(parents=True)

        state_data = {
            "version": 1,
            "processed": {
                "B09VALID": {
                    "asin": "B09VALID",
                    "title": "Valid Book",
                    "status": "STAGED",
                    "staging_dir": str(staging_dir),
                },
                "B09STALE": {
                    "asin": "B09STALE",
                    "title": "Stale Book",
                    "status": "STAGED",
                    "staging_dir": "/nonexistent/path",
                },
            },
            "failed": {},
        }
        with open(temp_state_file, "w") as f:
            json.dump(state_data, f)

        with patch("mamfast.utils.state.get_settings", return_value=mock_settings):
            removed = prune_stale_entries(dry_run=False)

            # Only stale entry removed
            assert len(removed) == 1
            assert removed[0][0] == "B09STALE"

            # Valid entry preserved
            assert is_processed("B09VALID") is True
            assert is_processed("B09STALE") is False


# =============================================================================
# Status Transition Validation Tests (Step 5)
# =============================================================================


class TestStatusTransitionValidation:
    """Tests for status transition state machine."""

    def test_allowed_transitions_map_is_complete(self):
        """Test that all ReleaseStatus values have allowed transitions defined."""
        for status in ReleaseStatus:
            assert status in ALLOWED_TRANSITIONS, f"Missing transitions for {status.name}"

    def test_valid_forward_transition(self):
        """Test that valid forward transitions are allowed."""
        assert validate_status_transition(ReleaseStatus.DISCOVERED, ReleaseStatus.STAGED) is True
        assert (
            validate_status_transition(ReleaseStatus.STAGED, ReleaseStatus.METADATA_FETCHED) is True
        )
        assert (
            validate_status_transition(
                ReleaseStatus.METADATA_FETCHED, ReleaseStatus.TORRENT_CREATED
            )
            is True
        )
        assert (
            validate_status_transition(ReleaseStatus.TORRENT_CREATED, ReleaseStatus.UPLOADED)
            is True
        )
        assert validate_status_transition(ReleaseStatus.UPLOADED, ReleaseStatus.COMPLETE) is True

    def test_idempotent_same_status(self):
        """Test that same-status writes are allowed (idempotent)."""
        for status in ReleaseStatus:
            assert validate_status_transition(status, status) is True

    def test_invalid_backward_transition_non_strict(self):
        """Test that invalid backward transitions return False when strict=False."""
        # COMPLETE -> STAGED is not allowed
        assert validate_status_transition(ReleaseStatus.COMPLETE, ReleaseStatus.STAGED) is False
        # UPLOADED -> DISCOVERED is not allowed
        assert validate_status_transition(ReleaseStatus.UPLOADED, ReleaseStatus.DISCOVERED) is False

    def test_invalid_transition_strict_raises(self):
        """Test that invalid transitions raise when strict=True."""
        with pytest.raises(InvalidStatusTransitionError) as exc_info:
            validate_status_transition(
                ReleaseStatus.COMPLETE,
                ReleaseStatus.STAGED,
                identifier="B09TEST",
                strict=True,
            )

        assert "COMPLETE" in str(exc_info.value)
        assert "STAGED" in str(exc_info.value)
        assert "B09TEST" in str(exc_info.value)

    def test_new_entry_allows_any_status(self):
        """Test that new entries (current=None) allow any status."""
        assert validate_status_transition(None, ReleaseStatus.DISCOVERED) is True
        assert validate_status_transition(None, ReleaseStatus.COMPLETE) is True

    def test_string_status_conversion(self):
        """Test that string status values are converted to enums."""
        assert validate_status_transition("DISCOVERED", "STAGED") is True
        assert validate_status_transition("COMPLETE", "STAGED") is False

    def test_unknown_status_passes_through(self):
        """Test that unknown status strings don't crash."""
        # Unknown statuses should pass through with warning, not crash
        assert validate_status_transition("UNKNOWN_STATUS", ReleaseStatus.STAGED) is True
        assert validate_status_transition(ReleaseStatus.STAGED, "UNKNOWN_STATUS") is True

    def test_skip_uploaded_to_complete(self):
        """Test that TORRENT_CREATED can skip directly to COMPLETE."""
        # Some workflows may not use UPLOADED status
        assert (
            validate_status_transition(ReleaseStatus.TORRENT_CREATED, ReleaseStatus.COMPLETE)
            is True
        )

    def test_failed_can_retry(self):
        """Test that FAILED status can transition back to DISCOVERED for retry."""
        assert validate_status_transition(ReleaseStatus.FAILED, ReleaseStatus.DISCOVERED) is True


class TestInvalidStatusTransitionError:
    """Tests for the InvalidStatusTransitionError exception."""

    def test_error_message_format(self):
        """Test that error message contains useful information."""
        error = InvalidStatusTransitionError(
            ReleaseStatus.COMPLETE,
            ReleaseStatus.STAGED,
            identifier="B09ERROR",
        )

        msg = str(error)
        assert "COMPLETE" in msg
        assert "STAGED" in msg
        assert "B09ERROR" in msg
        assert "Allowed" in msg

    def test_error_attributes(self):
        """Test that error has expected attributes."""
        error = InvalidStatusTransitionError(
            ReleaseStatus.COMPLETE,
            ReleaseStatus.STAGED,
            identifier="B09ATTR",
        )

        assert error.current == ReleaseStatus.COMPLETE
        assert error.new == ReleaseStatus.STAGED
        assert error.identifier == "B09ATTR"
