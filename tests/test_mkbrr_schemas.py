"""Tests for mkbrr Pydantic schemas."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from shelfr.schemas.mkbrr import (
    CheckResult,
    TorrentFileInfo,
    TorrentInfo,
    validate_check_result,
    validate_torrent_info,
)

# =============================================================================
# TorrentFileInfo Tests
# =============================================================================


class TestTorrentFileInfo:
    """Tests for TorrentFileInfo model."""

    def test_valid_single_file(self) -> None:
        """Single file with just filename."""
        info = TorrentFileInfo(path="audiobook.m4b", size=1024000)
        assert info.path == "audiobook.m4b"
        assert info.size == 1024000

    def test_valid_nested_path(self) -> None:
        """File with directory path components."""
        info = TorrentFileInfo(path="Book Name/Part 1/chapter01.mp3", size=5000000)
        assert info.path == "Book Name/Part 1/chapter01.mp3"
        assert info.size == 5000000

    def test_zero_size_allowed(self) -> None:
        """Zero-byte files are valid (e.g., placeholder files)."""
        info = TorrentFileInfo(path="empty.txt", size=0)
        assert info.size == 0

    def test_negative_size_rejected(self) -> None:
        """Negative file size should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            TorrentFileInfo(path="file.txt", size=-1)
        assert "greater than or equal to 0" in str(exc_info.value)

    def test_extra_fields_ignored(self) -> None:
        """Unknown fields should be ignored (forward compat)."""
        info = TorrentFileInfo(path="file.mp3", size=1000, unknown_field="ignored")
        assert info.path == "file.mp3"
        assert not hasattr(info, "unknown_field")


# =============================================================================
# TorrentInfo Tests
# =============================================================================


class TestTorrentInfo:
    """Tests for TorrentInfo model."""

    @pytest.fixture
    def valid_torrent_data(self) -> dict:
        """Valid torrent metadata for testing."""
        return {
            "name": "Test Audiobook",
            "info_hash": "a" * 40,  # Valid 40-char hex
            "size": 1024 * 1024 * 500,  # 500 MiB
            "piece_length": 262144,  # 256 KiB (2^18)
            "piece_count": 2000,
            "private": True,
            "trackers": ["https://tracker.example.com/announce"],
            "source": "MAM",
        }

    def test_valid_minimal(self, valid_torrent_data: dict) -> None:
        """Valid torrent with minimal required fields."""
        info = TorrentInfo.model_validate(valid_torrent_data)
        assert info.name == "Test Audiobook"
        assert info.info_hash == "a" * 40
        assert info.size == 1024 * 1024 * 500
        assert info.piece_length == 262144
        assert info.private is True
        assert info.source == "MAM"

    def test_valid_full(self) -> None:
        """Torrent with all optional fields populated."""
        now = datetime.now(UTC)
        info = TorrentInfo(
            name="Complete Audiobook",
            info_hash="0123456789abcdef" * 2 + "01234567",  # 40 chars
            size=1024**3,  # 1 GiB
            piece_length=1048576,  # 1 MiB
            piece_count=1024,
            private=True,
            trackers=["https://t1.example.com/a", "https://t2.example.com/a"],
            web_seeds=["https://cdn.example.com/files/"],
            source="BTN",
            comment="Uploaded by shelfr",
            created_by="mkbrr/1.5.0",
            creation_date=now,
            files=[
                TorrentFileInfo(path="chapter01.mp3", size=100000000),
                TorrentFileInfo(path="chapter02.mp3", size=100000000),
            ],
            extra_fields={"x_custom": "value"},
        )
        assert info.name == "Complete Audiobook"
        assert len(info.trackers) == 2
        assert len(info.web_seeds) == 1
        assert info.comment == "Uploaded by shelfr"
        assert info.creation_date == now
        assert len(info.files) == 2
        assert info.extra_fields == {"x_custom": "value"}

    def test_info_hash_lowercase(self) -> None:
        """Info hash should be normalized to lowercase."""
        info = TorrentInfo(
            name="Test",
            info_hash="ABCDEF0123456789" + "abcdef0123456789" + "01234567",
            size=1000,
            piece_length=16384,
            piece_count=1,
        )
        assert info.info_hash == info.info_hash.lower()

    def test_info_hash_invalid_hex(self) -> None:
        """Info hash with non-hex characters should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            TorrentInfo(
                name="Test",
                info_hash="g" * 40,  # 'g' is not hex
                size=1000,
                piece_length=16384,
                piece_count=1,
            )
        assert "not hex" in str(exc_info.value)

    def test_info_hash_wrong_length(self) -> None:
        """Info hash with wrong length should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            TorrentInfo(
                name="Test",
                info_hash="a" * 39,  # Too short
                size=1000,
                piece_length=16384,
                piece_count=1,
            )
        assert "40" in str(exc_info.value)

    def test_computed_file_count_multi(self) -> None:
        """File count for multi-file torrent."""
        info = TorrentInfo(
            name="Test",
            info_hash="a" * 40,
            size=3000,
            piece_length=16384,
            piece_count=1,
            files=[
                TorrentFileInfo(path="a.mp3", size=1000),
                TorrentFileInfo(path="b.mp3", size=1000),
                TorrentFileInfo(path="c.mp3", size=1000),
            ],
        )
        assert info.file_count == 3
        assert info.is_multi_file is True

    def test_computed_file_count_single(self) -> None:
        """File count for single-file torrent (empty files list)."""
        info = TorrentInfo(
            name="single.m4b",
            info_hash="a" * 40,
            size=1000000,
            piece_length=16384,
            piece_count=62,
        )
        assert info.file_count == 1
        assert info.is_multi_file is False

    def test_computed_piece_length_exponent(self) -> None:
        """Piece length exponent calculation."""
        info = TorrentInfo(
            name="Test",
            info_hash="a" * 40,
            size=1000,
            piece_length=262144,  # 2^18 = 256 KiB
            piece_count=1,
        )
        assert info.piece_length_exponent == 18

    def test_human_piece_length_kib(self) -> None:
        """Human-readable piece length in KiB."""
        info = TorrentInfo(
            name="Test",
            info_hash="a" * 40,
            size=1000,
            piece_length=262144,  # 256 KiB
            piece_count=1,
        )
        assert info.human_piece_length() == "256 KiB"

    def test_human_piece_length_mib(self) -> None:
        """Human-readable piece length in MiB."""
        info = TorrentInfo(
            name="Test",
            info_hash="a" * 40,
            size=1000,
            piece_length=1048576,  # 1 MiB
            piece_count=1,
        )
        assert info.human_piece_length() == "1 MiB"

    def test_human_size_gib(self) -> None:
        """Human-readable size in GiB."""
        info = TorrentInfo(
            name="Test",
            info_hash="a" * 40,
            size=1610612736,  # 1.5 GiB
            piece_length=16384,
            piece_count=98305,
        )
        assert info.human_size() == "1.50 GiB"

    def test_human_size_mib(self) -> None:
        """Human-readable size in MiB."""
        info = TorrentInfo(
            name="Test",
            info_hash="a" * 40,
            size=524288000,  # 500 MiB
            piece_length=16384,
            piece_count=32000,
        )
        assert info.human_size() == "500.00 MiB"

    def test_human_size_kib(self) -> None:
        """Human-readable size in KiB."""
        info = TorrentInfo(
            name="Test",
            info_hash="a" * 40,
            size=512000,  # 500 KiB
            piece_length=16384,
            piece_count=32,
        )
        assert info.human_size() == "500.00 KiB"

    def test_human_size_bytes(self) -> None:
        """Human-readable size in bytes for small files."""
        info = TorrentInfo(
            name="Test",
            info_hash="a" * 40,
            size=500,
            piece_length=16384,
            piece_count=1,
        )
        assert info.human_size() == "500 B"

    def test_default_private_false(self) -> None:
        """Default private flag is False."""
        info = TorrentInfo(
            name="Test",
            info_hash="a" * 40,
            size=1000,
            piece_length=16384,
            piece_count=1,
        )
        assert info.private is False

    def test_extra_fields_ignored(self) -> None:
        """Unknown fields should be ignored."""
        info = TorrentInfo(
            name="Test",
            info_hash="a" * 40,
            size=1000,
            piece_length=16384,
            piece_count=1,
            unknown="ignored",
        )
        assert not hasattr(info, "unknown")


# =============================================================================
# CheckResult Tests
# =============================================================================


class TestCheckResult:
    """Tests for CheckResult model."""

    def test_valid_complete(self) -> None:
        """Valid check result for complete torrent."""
        result = CheckResult(
            valid=True,
            percent_complete=100.0,
            good_pieces=1000,
            bad_pieces=0,
            total_pieces=1000,
            check_time_seconds=5.25,
        )
        assert result.valid is True
        assert result.percent_complete == 100.0
        assert result.is_complete is True
        assert result.has_missing_files is False

    def test_valid_incomplete(self) -> None:
        """Valid check result for incomplete torrent."""
        result = CheckResult(
            valid=False,
            percent_complete=95.5,
            good_pieces=955,
            bad_pieces=45,
            total_pieces=1000,
            bad_piece_indices=[10, 20, 30, 40, 50],
            missing_files=["chapter10.mp3"],
        )
        assert result.valid is False
        assert result.percent_complete == 95.5
        assert result.is_complete is False
        assert result.has_missing_files is True
        assert len(result.missing_files) == 1
        assert result.bad_piece_indices == [10, 20, 30, 40, 50]

    def test_size_mismatch_in_missing_files(self) -> None:
        """Missing files can include size mismatch indicator."""
        result = CheckResult(
            valid=False,
            percent_complete=99.0,
            good_pieces=990,
            bad_pieces=10,
            total_pieces=1000,
            missing_files=["chapter05.mp3 (size mismatch)"],
        )
        assert "size mismatch" in result.missing_files[0]
        assert result.has_missing_files is True

    def test_percent_complete_bounds(self) -> None:
        """Percent complete must be 0-100."""
        # Valid at bounds
        CheckResult(
            valid=True, percent_complete=0.0, good_pieces=0, bad_pieces=100, total_pieces=100
        )
        CheckResult(
            valid=True, percent_complete=100.0, good_pieces=100, bad_pieces=0, total_pieces=100
        )

        # Invalid below 0
        with pytest.raises(ValidationError):
            CheckResult(
                valid=False,
                percent_complete=-1.0,
                good_pieces=0,
                bad_pieces=0,
                total_pieces=100,
            )

        # Invalid above 100
        with pytest.raises(ValidationError):
            CheckResult(
                valid=False,
                percent_complete=101.0,
                good_pieces=0,
                bad_pieces=0,
                total_pieces=100,
            )

    def test_total_pieces_must_be_positive(self) -> None:
        """Total pieces must be > 0."""
        with pytest.raises(ValidationError):
            CheckResult(
                valid=True, percent_complete=100.0, good_pieces=0, bad_pieces=0, total_pieces=0
            )

    def test_check_time_optional(self) -> None:
        """Check time is optional."""
        result = CheckResult(
            valid=True, percent_complete=100.0, good_pieces=100, bad_pieces=0, total_pieces=100
        )
        assert result.check_time_seconds is None

    def test_check_time_non_negative(self) -> None:
        """Check time cannot be negative."""
        with pytest.raises(ValidationError):
            CheckResult(
                valid=True,
                percent_complete=100.0,
                good_pieces=100,
                bad_pieces=0,
                total_pieces=100,
                check_time_seconds=-1.0,
            )

    def test_is_complete_requires_all_conditions(self) -> None:
        """is_complete requires valid=True, 100%, and no missing files."""
        # Valid but not 100%
        result1 = CheckResult(
            valid=True, percent_complete=99.9, good_pieces=999, bad_pieces=0, total_pieces=1000
        )
        assert result1.is_complete is False

        # 100% but not valid
        result2 = CheckResult(
            valid=False, percent_complete=100.0, good_pieces=1000, bad_pieces=0, total_pieces=1000
        )
        assert result2.is_complete is False

        # Valid and 100% but has missing files
        result3 = CheckResult(
            valid=True,
            percent_complete=100.0,
            good_pieces=1000,
            bad_pieces=0,
            total_pieces=1000,
            missing_files=["file.txt"],
        )
        assert result3.is_complete is False

    def test_extra_fields_ignored(self) -> None:
        """Unknown fields should be ignored."""
        result = CheckResult(
            valid=True,
            percent_complete=100.0,
            good_pieces=100,
            bad_pieces=0,
            total_pieces=100,
            unknown="ignored",
        )
        assert not hasattr(result, "unknown")


# =============================================================================
# Validation Helper Tests
# =============================================================================


class TestValidationHelpers:
    """Tests for validation helper functions."""

    def test_validate_torrent_info(self) -> None:
        """validate_torrent_info creates TorrentInfo from dict."""
        data = {
            "name": "Test",
            "info_hash": "a" * 40,
            "size": 1000,
            "piece_length": 16384,
            "piece_count": 1,
            "private": True,
        }
        info = validate_torrent_info(data)
        assert isinstance(info, TorrentInfo)
        assert info.name == "Test"
        assert info.private is True

    def test_validate_torrent_info_invalid(self) -> None:
        """validate_torrent_info raises on invalid data."""
        with pytest.raises(ValidationError):
            validate_torrent_info({"name": "Test"})  # Missing required fields

    def test_validate_check_result(self) -> None:
        """validate_check_result creates CheckResult from dict."""
        data = {
            "valid": True,
            "percent_complete": 100.0,
            "good_pieces": 100,
            "bad_pieces": 0,
            "total_pieces": 100,
        }
        result = validate_check_result(data)
        assert isinstance(result, CheckResult)
        assert result.valid is True

    def test_validate_check_result_invalid(self) -> None:
        """validate_check_result raises on invalid data."""
        with pytest.raises(ValidationError):
            validate_check_result({"valid": True})  # Missing required fields
