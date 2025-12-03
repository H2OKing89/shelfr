"""Tests for state file schema validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mamfast.schemas.state import (
    FailedRelease,
    ProcessedRelease,
    create_empty_state,
    validate_state,
)


class TestProcessedRelease:
    """Tests for ProcessedRelease schema."""

    def test_valid_release_full(self):
        """Test valid release with all fields."""
        release = ProcessedRelease(
            asin="B0G4NFQDWR",
            title="Kuma Kuma Kuma Bear (Light Novel) Vol. 7",
            author="くまなの",
            series="Kuma Kuma Kuma Bear",
            processed_at="2025-12-02T06:51:26.717690",
            staging_dir="/mnt/user/data/seedvault/audiobooks/Kuma Kuma Kuma Bear vol_07",
            torrent_path="/mnt/user/data/torrentfiles/kuma.torrent",
            status="COMPLETE",
        )
        assert release.asin == "B0G4NFQDWR"
        assert release.title == "Kuma Kuma Kuma Bear (Light Novel) Vol. 7"
        assert release.status == "COMPLETE"

    def test_valid_release_minimal(self):
        """Test valid release with minimal fields."""
        release = ProcessedRelease(
            asin="B0G4NFQDWR",
            title="Some Book",
            processed_at="2025-12-02T06:51:26.717690",
        )
        assert release.asin == "B0G4NFQDWR"
        assert release.author is None
        assert release.status == "COMPLETE"  # Default

    def test_invalid_datetime_rejected(self):
        """Test that invalid datetime format is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ProcessedRelease(
                asin="B0G4NFQDWR",
                title="Some Book",
                processed_at="not-a-date",
            )
        assert "datetime" in str(exc_info.value).lower()

    def test_missing_required_fields_rejected(self):
        """Test that missing required fields are rejected."""
        with pytest.raises(ValidationError):
            ProcessedRelease(asin="B0G4NFQDWR")  # Missing title, processed_at

    def test_extra_fields_ignored(self):
        """Test that extra fields are ignored for forward compatibility."""
        release = ProcessedRelease(
            asin="B0G4NFQDWR",
            title="Some Book",
            processed_at="2025-12-02T06:51:26.717690",
            unknown_field="should be ignored",
        )
        assert release.asin == "B0G4NFQDWR"


class TestFailedRelease:
    """Tests for FailedRelease schema."""

    def test_valid_failed_release(self):
        """Test valid failed release."""
        failed = FailedRelease(
            asin="B0ABC123",
            title="Failed Book",
            error="Network timeout",
            failed_at="2025-12-02T10:00:00",
            retry_count=3,
        )
        assert failed.asin == "B0ABC123"
        assert failed.error == "Network timeout"
        assert failed.retry_count == 3

    def test_empty_failed_release(self):
        """Test that failed release can be empty (all optional)."""
        failed = FailedRelease()
        assert failed.asin is None
        assert failed.retry_count == 0


class TestProcessedState:
    """Tests for ProcessedState schema."""

    def test_valid_state_full(self):
        """Test valid state with processed and failed entries."""
        data = {
            "version": 1,
            "processed": {
                "B0G4NFQDWR": {
                    "asin": "B0G4NFQDWR",
                    "title": "Kuma Kuma Kuma Bear (Light Novel) Vol. 7",
                    "author": "くまなの",
                    "processed_at": "2025-12-02T06:51:26.717690",
                    "staging_dir": "/mnt/user/data/seedvault/audiobooks/Kuma",
                    "torrent_path": "/mnt/user/data/torrentfiles/kuma.torrent",
                    "status": "COMPLETE",
                }
            },
            "failed": {
                "B0ABC123": {
                    "asin": "B0ABC123",
                    "title": "Failed Book",
                    "error": "Network timeout",
                }
            },
        }
        state = validate_state(data)
        assert state.version == 1
        assert len(state.processed) == 1
        assert len(state.failed) == 1
        assert state.processed["B0G4NFQDWR"].title == "Kuma Kuma Kuma Bear (Light Novel) Vol. 7"

    def test_empty_state(self):
        """Test empty state."""
        state = validate_state(
            {
                "version": 1,
                "processed": {},
                "failed": {},
            }
        )
        assert state.version == 1
        assert state.processed == {}
        assert state.failed == {}

    def test_create_empty_state(self):
        """Test create_empty_state helper."""
        state = create_empty_state()
        assert state.version == 1
        assert state.processed == {}
        assert state.failed == {}

    def test_missing_version_uses_default(self):
        """Test that missing version field uses default."""
        state = validate_state(
            {
                "processed": {},
                "failed": {},
            }
        )
        assert state.version == 1

    def test_real_processed_json_structure(self):
        """Test with structure matching actual processed.json from project."""
        staging = (
            "/mnt/user/data/downloads/torrents/qbittorrent/seedvault/audiobooks/"
            "Reincarnated in a Fantasy World with Murderous Intent (2025) "
            "(Neil Hartley) {ASIN.B0F56G77WS} [H2OKing]"
        )
        torrent = (
            "/mnt/user/data/downloads/torrents/torrentfiles/myanonamouse_"
            "Reincarnated in a Fantasy World with Murderous Intent (2025) "
            "(Neil Hartley) {ASIN.B0F56G77WS} [H2OKing].torrent"
        )
        data = {
            "processed": {
                "B0F56G77WS": {
                    "asin": "B0F56G77WS",
                    "title": "Reincarnated in a Fantasy World with Murderous Intent",
                    "author": "Neil Hartley",
                    "processed_at": "2025-11-30T01:36:44.555576",
                    "staging_dir": staging,
                    "torrent_path": torrent,
                    "status": "COMPLETE",
                }
            },
            "failed": {},
        }
        state = validate_state(data)
        assert len(state.processed) == 1
        release = state.processed["B0F56G77WS"]
        assert release.asin == "B0F56G77WS"
        assert release.author == "Neil Hartley"
        assert release.status == "COMPLETE"


class TestStateEdgeCases:
    """Test edge cases and error handling."""

    def test_invalid_processed_entry(self):
        """Test that invalid processed entry is rejected."""
        with pytest.raises(ValidationError):
            validate_state(
                {
                    "version": 1,
                    "processed": {
                        "B0G4NFQDWR": {
                            # Missing required 'asin', 'title', 'processed_at'
                            "author": "Some Author",
                        }
                    },
                    "failed": {},
                }
            )

    def test_extra_top_level_fields_ignored(self):
        """Test that extra top-level fields are ignored."""
        state = validate_state(
            {
                "version": 1,
                "processed": {},
                "failed": {},
                "unknown_section": {"foo": "bar"},
            }
        )
        assert state.version == 1

    def test_multiple_releases(self):
        """Test state with multiple releases."""
        data = {
            "version": 1,
            "processed": {
                f"B{i:09d}": {
                    "asin": f"B{i:09d}",
                    "title": f"Book {i}",
                    "processed_at": "2025-12-02T10:00:00",
                }
                for i in range(100)
            },
            "failed": {},
        }
        state = validate_state(data)
        assert len(state.processed) == 100
