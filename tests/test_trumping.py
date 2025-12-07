"""Tests for trumping (quality-based replacement) module.

Tests cover:
- TrumpDecision enum
- TrumpableMeta dataclass and format_tier property
- TrumpPrefs defaults
- is_multi_file_layout() detection
- decide_trump() decision tree (all stages)
- adjust_for_aggressiveness() modifier
- archive_existing() function
- TrumpingSchema validation
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mamfast.abs.trumping import (
    TrumpableMeta,
    TrumpAggressiveness,
    TrumpDecision,
    TrumpingError,
    TrumpPrefs,
    adjust_for_aggressiveness,
    archive_existing,
    decide_trump,
    is_multi_file_layout,
)
from mamfast.schemas.config import TrumpingSchema


class TestTrumpDecision:
    """Test TrumpDecision enum."""

    def test_enum_values_exist(self) -> None:
        """All expected decision types exist."""
        assert TrumpDecision.KEEP_EXISTING
        assert TrumpDecision.KEEP_BOTH
        assert TrumpDecision.REPLACE_WITH_NEW
        assert TrumpDecision.REJECT_NEW

    def test_enum_are_distinct(self) -> None:
        """All decision types are distinct."""
        values = [d.value for d in TrumpDecision]
        assert len(values) == len(set(values))


class TestTrumpAggressiveness:
    """Test TrumpAggressiveness enum."""

    def test_enum_values(self) -> None:
        """Enum values match expected strings."""
        assert TrumpAggressiveness.CONSERVATIVE.value == "conservative"
        assert TrumpAggressiveness.BALANCED.value == "balanced"
        assert TrumpAggressiveness.AGGRESSIVE.value == "aggressive"

    def test_string_enum(self) -> None:
        """Can construct from string."""
        assert TrumpAggressiveness("balanced") == TrumpAggressiveness.BALANCED


class TestTrumpableMeta:
    """Test TrumpableMeta dataclass."""

    def test_minimal_creation(self) -> None:
        """Can create with just ASIN."""
        meta = TrumpableMeta(asin="B0TEST12345")
        assert meta.asin == "B0TEST12345"
        assert meta.format is None
        assert meta.bitrate_kbps is None
        assert meta.has_chapters is False

    def test_format_tier_m4b(self) -> None:
        """m4b has highest tier."""
        meta = TrumpableMeta(asin="B0TEST", format="m4b")
        assert meta.format_tier == 5

    def test_format_tier_m4a(self) -> None:
        """m4a has second highest tier."""
        meta = TrumpableMeta(asin="B0TEST", format="m4a")
        assert meta.format_tier == 4

    def test_format_tier_opus(self) -> None:
        """opus has third tier (modern efficient codec)."""
        meta = TrumpableMeta(asin="B0TEST", format="opus")
        assert meta.format_tier == 3

    def test_format_tier_mp3(self) -> None:
        """mp3 has fourth tier."""
        meta = TrumpableMeta(asin="B0TEST", format="mp3")
        assert meta.format_tier == 2

    def test_format_tier_flac(self) -> None:
        """flac has lowest tier (intentional for audiobooks)."""
        meta = TrumpableMeta(asin="B0TEST", format="flac")
        assert meta.format_tier == 1

    def test_format_tier_unknown(self) -> None:
        """Unknown format has tier 0."""
        meta = TrumpableMeta(asin="B0TEST", format=None)
        assert meta.format_tier == 0

    def test_format_tier_ranking(self) -> None:
        """m4b > m4a > opus > mp3 > flac > unknown."""
        m4b = TrumpableMeta(asin="B0TEST", format="m4b")
        m4a = TrumpableMeta(asin="B0TEST", format="m4a")
        opus = TrumpableMeta(asin="B0TEST", format="opus")
        mp3 = TrumpableMeta(asin="B0TEST", format="mp3")
        flac = TrumpableMeta(asin="B0TEST", format="flac")
        unknown = TrumpableMeta(asin="B0TEST", format=None)

        assert m4b.format_tier > m4a.format_tier
        assert m4a.format_tier > opus.format_tier
        assert opus.format_tier > mp3.format_tier
        assert mp3.format_tier > flac.format_tier
        assert flac.format_tier > unknown.format_tier

    def test_frozen(self) -> None:
        """Dataclass is immutable."""
        meta = TrumpableMeta(asin="B0TEST")
        with pytest.raises(AttributeError):
            meta.asin = "B0OTHER"  # type: ignore[misc]


class TestTrumpPrefs:
    """Test TrumpPrefs runtime dataclass."""

    def test_default_construction(self) -> None:
        """Can construct with no arguments (test convenience)."""
        prefs = TrumpPrefs()
        assert prefs.enabled is False
        assert prefs.aggressiveness == TrumpAggressiveness.BALANCED
        assert prefs.min_bitrate_increase_kbps == 64

    def test_defaults_match_schema(self) -> None:
        """TrumpPrefs defaults match TrumpingSchema defaults."""
        prefs = TrumpPrefs()
        schema = TrumpingSchema()

        assert prefs.enabled == schema.enabled
        assert prefs.aggressiveness.value == schema.aggressiveness
        assert prefs.min_bitrate_increase_kbps == schema.min_bitrate_increase_kbps
        assert prefs.prefer_chapters == schema.prefer_chapters
        assert prefs.prefer_stereo == schema.prefer_stereo
        assert prefs.min_duration_ratio == schema.min_duration_ratio
        assert prefs.max_duration_ratio == schema.max_duration_ratio
        assert prefs.archive_by_year == schema.archive_by_year

    def test_custom_values(self) -> None:
        """Can construct with custom values."""
        prefs = TrumpPrefs(
            enabled=True,
            aggressiveness=TrumpAggressiveness.CONSERVATIVE,
            min_bitrate_increase_kbps=128,
            archive_root=Path("/archive"),
        )
        assert prefs.enabled is True
        assert prefs.aggressiveness == TrumpAggressiveness.CONSERVATIVE
        assert prefs.min_bitrate_increase_kbps == 128
        assert prefs.archive_root == Path("/archive")

    def test_from_schema_basic(self) -> None:
        """from_schema creates TrumpPrefs from TrumpingSchema."""
        schema = TrumpingSchema(enabled=True, archive_root="/archive")
        prefs = TrumpPrefs.from_schema(schema)

        assert prefs.enabled is True
        assert prefs.aggressiveness == TrumpAggressiveness.BALANCED
        assert prefs.archive_root == Path("/archive")

    def test_from_schema_coerces_archive_root(self) -> None:
        """from_schema converts archive_root str to Path."""
        schema = TrumpingSchema(enabled=True, archive_root="/mnt/archive/trumped")
        prefs = TrumpPrefs.from_schema(schema)

        assert isinstance(prefs.archive_root, Path)
        assert prefs.archive_root == Path("/mnt/archive/trumped")

    def test_from_schema_handles_none_archive_root(self) -> None:
        """from_schema handles None archive_root (disabled trumping)."""
        schema = TrumpingSchema(enabled=False, archive_root=None)
        prefs = TrumpPrefs.from_schema(schema)

        assert prefs.archive_root is None

    def test_from_schema_aggressiveness_coercion(self) -> None:
        """from_schema converts aggressiveness str to enum."""
        schema = TrumpingSchema(
            enabled=True, archive_root="/archive", aggressiveness="conservative"
        )
        prefs = TrumpPrefs.from_schema(schema)

        assert prefs.aggressiveness == TrumpAggressiveness.CONSERVATIVE
        assert isinstance(prefs.aggressiveness, TrumpAggressiveness)

    def test_from_schema_all_fields(self) -> None:
        """from_schema maps all TrumpingSchema fields correctly."""
        schema = TrumpingSchema(
            enabled=True,
            archive_root="/archive",
            aggressiveness="aggressive",
            min_bitrate_increase_kbps=128,
            prefer_chapters=False,
            prefer_stereo=False,
            min_duration_ratio=0.85,
            max_duration_ratio=1.5,
            archive_by_year=False,
        )
        prefs = TrumpPrefs.from_schema(schema)

        assert prefs.enabled is True
        assert prefs.aggressiveness == TrumpAggressiveness.AGGRESSIVE
        assert prefs.min_bitrate_increase_kbps == 128
        assert prefs.prefer_chapters is False
        assert prefs.prefer_stereo is False
        assert prefs.min_duration_ratio == 0.85
        assert prefs.max_duration_ratio == 1.5
        assert prefs.archive_root == Path("/archive")
        assert prefs.archive_by_year is False


class TestIsMultiFileLayout:
    """Test is_multi_file_layout() detection."""

    def test_single_file(self, tmp_path: Path) -> None:
        """Single audio file is not multi-file."""
        (tmp_path / "book.m4b").touch()
        assert is_multi_file_layout(tmp_path) is False

    def test_multiple_files(self, tmp_path: Path) -> None:
        """Multiple audio files is multi-file."""
        (tmp_path / "disc1.mp3").touch()
        (tmp_path / "disc2.mp3").touch()
        assert is_multi_file_layout(tmp_path) is True

    def test_no_audio_files(self, tmp_path: Path) -> None:
        """No audio files is not multi-file."""
        (tmp_path / "cover.jpg").touch()
        (tmp_path / "metadata.json").touch()
        assert is_multi_file_layout(tmp_path) is False

    def test_audio_plus_non_audio(self, tmp_path: Path) -> None:
        """Single audio + non-audio files is not multi-file."""
        (tmp_path / "book.m4b").touch()
        (tmp_path / "cover.jpg").touch()
        assert is_multi_file_layout(tmp_path) is False

    def test_not_a_directory(self, tmp_path: Path) -> None:
        """Non-directory returns False."""
        file_path = tmp_path / "not_a_dir.txt"
        file_path.touch()
        assert is_multi_file_layout(file_path) is False

    def test_various_audio_extensions(self, tmp_path: Path) -> None:
        """All audio extensions are counted."""
        (tmp_path / "track1.m4b").touch()
        (tmp_path / "track2.mp3").touch()
        assert is_multi_file_layout(tmp_path) is True

        # Cleanup and test flac + m4a
        for f in tmp_path.iterdir():
            f.unlink()
        (tmp_path / "track.flac").touch()
        (tmp_path / "track.m4a").touch()
        assert is_multi_file_layout(tmp_path) is True


class TestDecideTrump:
    """Test decide_trump() decision tree."""

    def test_different_asin_keeps_both(self) -> None:
        """Different ASINs return KEEP_BOTH."""
        existing = TrumpableMeta(asin="B0AAAA0001", format="mp3")
        incoming = TrumpableMeta(asin="B0BBBB0002", format="m4b")
        prefs = TrumpPrefs()

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.KEEP_BOTH
        assert "Different ASIN" in reason

    def test_language_mismatch_keeps_both(self) -> None:
        """Different languages return KEEP_BOTH."""
        existing = TrumpableMeta(asin="B0TEST", format="mp3", language="en")
        incoming = TrumpableMeta(asin="B0TEST", format="m4b", language="de")
        prefs = TrumpPrefs()

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.KEEP_BOTH
        assert "Language mismatch" in reason

    def test_abridgement_mismatch_keeps_both(self) -> None:
        """Different abridgement status returns KEEP_BOTH."""
        existing = TrumpableMeta(asin="B0TEST", format="m4b", is_abridged=False)
        incoming = TrumpableMeta(asin="B0TEST", format="m4b", is_abridged=True)
        prefs = TrumpPrefs()

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.KEEP_BOTH
        assert "Abridgement" in reason

    def test_duration_too_short_rejects(self) -> None:
        """Significantly shorter incoming is rejected."""
        existing = TrumpableMeta(asin="B0TEST", format="m4b", duration_sec=36000)  # 10h
        incoming = TrumpableMeta(asin="B0TEST", format="m4b", duration_sec=30000)  # 8.3h
        prefs = TrumpPrefs(min_duration_ratio=0.9)

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.REJECT_NEW
        assert "shorter" in reason.lower()

    def test_duration_too_long_keeps_both(self) -> None:
        """Significantly longer incoming triggers KEEP_BOTH."""
        existing = TrumpableMeta(asin="B0TEST", format="m4b", duration_sec=36000)  # 10h
        incoming = TrumpableMeta(asin="B0TEST", format="m4b", duration_sec=50000)  # 13.9h
        prefs = TrumpPrefs(max_duration_ratio=1.25)

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.KEEP_BOTH
        assert "longer" in reason.lower()

    def test_format_upgrade_mp3_to_m4b(self) -> None:
        """mp3 → m4b is a format upgrade."""
        existing = TrumpableMeta(asin="B0TEST", format="mp3", bitrate_kbps=128)
        incoming = TrumpableMeta(asin="B0TEST", format="m4b", bitrate_kbps=128)
        prefs = TrumpPrefs()

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.REPLACE_WITH_NEW
        assert "Format upgrade" in reason

    def test_format_downgrade_rejected(self) -> None:
        """m4b → mp3 is a format downgrade."""
        existing = TrumpableMeta(asin="B0TEST", format="m4b", bitrate_kbps=128)
        incoming = TrumpableMeta(asin="B0TEST", format="mp3", bitrate_kbps=128)
        prefs = TrumpPrefs()

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.REJECT_NEW
        assert "Format downgrade" in reason

    def test_format_beats_bitrate(self) -> None:
        """Format tier wins over raw bitrate (m4b 64k > mp3 320k)."""
        existing = TrumpableMeta(asin="B0TEST", format="m4b", bitrate_kbps=64)
        incoming = TrumpableMeta(asin="B0TEST", format="mp3", bitrate_kbps=320)
        prefs = TrumpPrefs()

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.REJECT_NEW

    def test_bitrate_upgrade_same_format(self) -> None:
        """Significant bitrate increase trumps."""
        existing = TrumpableMeta(asin="B0TEST", format="m4b", bitrate_kbps=64)
        incoming = TrumpableMeta(asin="B0TEST", format="m4b", bitrate_kbps=256)
        prefs = TrumpPrefs(min_bitrate_increase_kbps=64)

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.REPLACE_WITH_NEW
        assert "Bitrate upgrade" in reason

    def test_bitrate_below_threshold(self) -> None:
        """Small bitrate increase doesn't trump."""
        existing = TrumpableMeta(asin="B0TEST", format="m4b", bitrate_kbps=128)
        incoming = TrumpableMeta(asin="B0TEST", format="m4b", bitrate_kbps=140)
        prefs = TrumpPrefs(min_bitrate_increase_kbps=64)

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.KEEP_EXISTING

    def test_bitrate_downgrade_rejected(self) -> None:
        """Significant bitrate decrease is rejected."""
        existing = TrumpableMeta(asin="B0TEST", format="m4b", bitrate_kbps=256)
        incoming = TrumpableMeta(asin="B0TEST", format="m4b", bitrate_kbps=64)
        prefs = TrumpPrefs(min_bitrate_increase_kbps=64)

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.REJECT_NEW
        assert "Bitrate downgrade" in reason

    def test_sample_rate_upgrade(self) -> None:
        """Higher sample rate trumps when formats and bitrates equal."""
        existing = TrumpableMeta(
            asin="B0TEST", format="m4b", bitrate_kbps=128, sample_rate_hz=22050
        )
        incoming = TrumpableMeta(
            asin="B0TEST", format="m4b", bitrate_kbps=128, sample_rate_hz=44100
        )
        prefs = TrumpPrefs()

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.REPLACE_WITH_NEW
        assert "Sample rate upgrade" in reason

    def test_chapters_tiebreaker(self) -> None:
        """Chapters trump non-chapters when other metrics equal."""
        existing = TrumpableMeta(asin="B0TEST", format="m4b", bitrate_kbps=128, has_chapters=False)
        incoming = TrumpableMeta(asin="B0TEST", format="m4b", bitrate_kbps=128, has_chapters=True)
        prefs = TrumpPrefs(prefer_chapters=True)

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.REPLACE_WITH_NEW
        assert "chapters" in reason.lower()

    def test_chapters_tiebreaker_disabled(self) -> None:
        """Chapters don't trump when prefer_chapters=False."""
        existing = TrumpableMeta(asin="B0TEST", format="m4b", bitrate_kbps=128, has_chapters=False)
        incoming = TrumpableMeta(asin="B0TEST", format="m4b", bitrate_kbps=128, has_chapters=True)
        prefs = TrumpPrefs(prefer_chapters=False)

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.KEEP_EXISTING

    def test_stereo_tiebreaker(self) -> None:
        """Stereo trumps mono when other metrics equal."""
        existing = TrumpableMeta(asin="B0TEST", format="m4b", bitrate_kbps=128, is_stereo=False)
        incoming = TrumpableMeta(asin="B0TEST", format="m4b", bitrate_kbps=128, is_stereo=True)
        prefs = TrumpPrefs(prefer_stereo=True)

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.REPLACE_WITH_NEW
        assert "Stereo" in reason

    def test_stereo_tiebreaker_disabled(self) -> None:
        """Stereo doesn't trump when prefer_stereo=False."""
        existing = TrumpableMeta(asin="B0TEST", format="m4b", bitrate_kbps=128, is_stereo=False)
        incoming = TrumpableMeta(asin="B0TEST", format="m4b", bitrate_kbps=128, is_stereo=True)
        prefs = TrumpPrefs(prefer_stereo=False)

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.KEEP_EXISTING

    def test_no_improvement_keeps_existing(self) -> None:
        """Equal quality defaults to KEEP_EXISTING."""
        existing = TrumpableMeta(asin="B0TEST", format="m4b", bitrate_kbps=128)
        incoming = TrumpableMeta(asin="B0TEST", format="m4b", bitrate_kbps=128)
        prefs = TrumpPrefs()

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.KEEP_EXISTING
        assert "No quality improvement" in reason

    def test_missing_metrics_keeps_existing(self) -> None:
        """Missing quality metrics default to KEEP_EXISTING."""
        existing = TrumpableMeta(asin="B0TEST", format="m4b")
        incoming = TrumpableMeta(asin="B0TEST", format="m4b")
        prefs = TrumpPrefs()

        decision, reason = decide_trump(existing, incoming, prefs)
        assert decision == TrumpDecision.KEEP_EXISTING


class TestAdjustForAggressiveness:
    """Test adjust_for_aggressiveness() modifier."""

    def test_conservative_demotes_bitrate_upgrade(self) -> None:
        """Conservative mode demotes bitrate-only upgrades."""
        decision = TrumpDecision.REPLACE_WITH_NEW
        reason = "Bitrate upgrade: 64→256 kbps (+192)"
        prefs = TrumpPrefs(aggressiveness=TrumpAggressiveness.CONSERVATIVE)

        new_decision, new_reason = adjust_for_aggressiveness(decision, reason, prefs)
        assert new_decision == TrumpDecision.KEEP_EXISTING
        assert "Conservative mode" in new_reason

    def test_conservative_keeps_format_upgrade(self) -> None:
        """Conservative mode keeps format upgrades."""
        decision = TrumpDecision.REPLACE_WITH_NEW
        reason = "Format upgrade: mp3 → m4b"
        prefs = TrumpPrefs(aggressiveness=TrumpAggressiveness.CONSERVATIVE)

        new_decision, new_reason = adjust_for_aggressiveness(decision, reason, prefs)
        assert new_decision == TrumpDecision.REPLACE_WITH_NEW
        assert new_reason == reason

    def test_balanced_no_change(self) -> None:
        """Balanced mode doesn't modify decisions."""
        decision = TrumpDecision.REPLACE_WITH_NEW
        reason = "Bitrate upgrade: 64→256 kbps"
        prefs = TrumpPrefs(aggressiveness=TrumpAggressiveness.BALANCED)

        new_decision, new_reason = adjust_for_aggressiveness(decision, reason, prefs)
        assert new_decision == decision
        assert new_reason == reason

    def test_aggressive_no_change_for_now(self) -> None:
        """Aggressive mode doesn't change anything (placeholder)."""
        decision = TrumpDecision.KEEP_EXISTING
        reason = "No quality improvement"
        prefs = TrumpPrefs(aggressiveness=TrumpAggressiveness.AGGRESSIVE)

        new_decision, new_reason = adjust_for_aggressiveness(decision, reason, prefs)
        assert new_decision == decision
        assert new_reason == reason


class TestArchiveExisting:
    """Test archive_existing() function."""

    def test_requires_archive_root(self, tmp_path: Path) -> None:
        """Raises TrumpingError without archive_root."""
        existing_meta = TrumpableMeta(asin="B0TEST")
        incoming_meta = TrumpableMeta(asin="B0TEST")
        prefs = TrumpPrefs(archive_root=None)

        with pytest.raises(TrumpingError, match="archive_root required"):
            archive_existing(
                tmp_path,
                existing_meta,
                incoming_meta,
                TrumpDecision.REPLACE_WITH_NEW,
                "Test reason",
                prefs,
            )

    def test_dry_run_no_move(self, tmp_path: Path) -> None:
        """Dry run doesn't move files."""
        # Setup
        existing_folder = tmp_path / "existing"
        existing_folder.mkdir()
        (existing_folder / "book.m4b").write_text("audio")

        archive_root = tmp_path / "archive"
        archive_root.mkdir()

        existing_meta = TrumpableMeta(asin="B0TEST12345")
        incoming_meta = TrumpableMeta(asin="B0TEST12345")
        prefs = TrumpPrefs(archive_root=archive_root)

        result = archive_existing(
            existing_folder,
            existing_meta,
            incoming_meta,
            TrumpDecision.REPLACE_WITH_NEW,
            "Test reason",
            prefs,
            dry_run=True,
        )

        assert result is None
        assert existing_folder.exists()  # Not moved

    def test_archive_moves_folder(self, tmp_path: Path) -> None:
        """Archive moves entire folder with sidecar."""
        # Setup
        existing_folder = tmp_path / "existing"
        existing_folder.mkdir()
        (existing_folder / "book.m4b").write_text("audio")
        (existing_folder / "cover.jpg").write_text("image")

        archive_root = tmp_path / "archive"
        archive_root.mkdir()

        existing_meta = TrumpableMeta(asin="B0TEST12345", format="mp3", bitrate_kbps=128)
        incoming_meta = TrumpableMeta(asin="B0TEST12345", format="m4b", bitrate_kbps=256)
        prefs = TrumpPrefs(archive_root=archive_root, archive_by_year=True)

        result = archive_existing(
            existing_folder,
            existing_meta,
            incoming_meta,
            TrumpDecision.REPLACE_WITH_NEW,
            "Format upgrade: mp3 → m4b",
            prefs,
        )

        # Verify
        assert result is not None
        assert not existing_folder.exists()  # Original moved
        assert result.exists()  # Archive exists
        assert (result / "book.m4b").exists()  # Files present
        assert (result / "cover.jpg").exists()
        assert (result / ".mamfast_trump.json").exists()  # Sidecar written

    def test_archive_by_year(self, tmp_path: Path) -> None:
        """Archive organizes by year when enabled."""
        existing_folder = tmp_path / "existing"
        existing_folder.mkdir()
        (existing_folder / "book.m4b").touch()

        archive_root = tmp_path / "archive"

        existing_meta = TrumpableMeta(asin="B0TEST12345")
        incoming_meta = TrumpableMeta(asin="B0TEST12345")
        prefs = TrumpPrefs(archive_root=archive_root, archive_by_year=True)

        result = archive_existing(
            existing_folder,
            existing_meta,
            incoming_meta,
            TrumpDecision.REPLACE_WITH_NEW,
            "Test",
            prefs,
        )

        assert result is not None
        # Path should include year
        import datetime

        year = datetime.datetime.now(datetime.UTC).strftime("%Y")
        assert year in str(result)

    def test_archive_no_year(self, tmp_path: Path) -> None:
        """Archive doesn't include year when disabled."""
        existing_folder = tmp_path / "existing"
        existing_folder.mkdir()
        (existing_folder / "book.m4b").touch()

        archive_root = tmp_path / "archive"

        existing_meta = TrumpableMeta(asin="B0TEST12345")
        incoming_meta = TrumpableMeta(asin="B0TEST12345")
        prefs = TrumpPrefs(archive_root=archive_root, archive_by_year=False)

        result = archive_existing(
            existing_folder,
            existing_meta,
            incoming_meta,
            TrumpDecision.REPLACE_WITH_NEW,
            "Test",
            prefs,
        )

        assert result is not None
        # Path should be archive_root/ASIN/timestamp
        assert str(result).startswith(str(archive_root / "B0TEST12345"))


class TestTrumpingSchema:
    """Test TrumpingSchema Pydantic validation."""

    def test_defaults(self) -> None:
        """Schema has sensible defaults."""
        schema = TrumpingSchema()
        assert schema.enabled is False
        assert schema.aggressiveness == "balanced"
        assert schema.min_bitrate_increase_kbps == 64
        assert schema.prefer_chapters is True
        assert schema.prefer_stereo is True

    def test_enabled_requires_archive_root(self) -> None:
        """Enabled trumping requires archive_root."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="archive_root is required"):
            TrumpingSchema(enabled=True)

    def test_enabled_with_archive_root(self) -> None:
        """Enabled trumping works with archive_root."""
        schema = TrumpingSchema(enabled=True, archive_root="/archive")
        assert schema.enabled is True
        assert schema.archive_root == "/archive"

    def test_archive_root_must_be_absolute(self) -> None:
        """archive_root must be absolute path."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="absolute path"):
            TrumpingSchema(enabled=True, archive_root="relative/path")

    def test_archive_root_trailing_slash_normalized(self) -> None:
        """Trailing slash is removed from archive_root."""
        schema = TrumpingSchema(enabled=True, archive_root="/archive/")
        assert schema.archive_root == "/archive"

    def test_aggressiveness_validation(self) -> None:
        """Invalid aggressiveness raises error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="aggressiveness"):
            TrumpingSchema(aggressiveness="invalid")

    def test_aggressiveness_case_insensitive(self) -> None:
        """Aggressiveness is normalized to lowercase."""
        schema = TrumpingSchema(aggressiveness="BALANCED")
        assert schema.aggressiveness == "balanced"

    def test_duration_ratio_bounds(self) -> None:
        """Duration ratios have valid bounds."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            TrumpingSchema(min_duration_ratio=0.3)  # Below 0.5

        with pytest.raises(ValidationError):
            TrumpingSchema(min_duration_ratio=1.5)  # Above 1.0

        with pytest.raises(ValidationError):
            TrumpingSchema(max_duration_ratio=0.5)  # Below 1.0

        with pytest.raises(ValidationError):
            TrumpingSchema(max_duration_ratio=3.0)  # Above 2.0
