"""Pydantic models for mkbrr data structures.

These models provide structured access to torrent metadata and check results.
Prefer using parse_torrent_file() with bencode for robust .torrent parsing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, computed_field, field_validator


class TorrentFileInfo(BaseModel):
    """Single file in a torrent.

    For single-file torrents, path is just the filename.
    For multi-file torrents, path includes directory components.
    """

    path: str
    size: int = Field(ge=0, description="File size in bytes")

    model_config = {"extra": "ignore"}


class TorrentInfo(BaseModel):
    """Parsed torrent metadata (from bencode or mkbrr inspect).

    Recommended: Parse .torrent files directly using bencode for stable,
    format-independent access. mkbrr inspect is human-readable but not
    designed for machine parsing.

    Attributes:
        name: Torrent name (usually folder name or filename).
        info_hash: SHA1 hash of the info dictionary (hex string, 40 chars).
        size: Total content size in bytes.
        piece_length: Size of each piece in bytes.
        piece_count: Number of pieces in the torrent.
        private: Whether torrent is private (disables DHT/PEX).
        trackers: List of tracker announce URLs.
        web_seeds: List of web seed URLs (BEP 19).
        source: Source tag (e.g., "MAM", "BTN").
        comment: Torrent comment field.
        created_by: Creator software identification.
        creation_date: When the torrent was created.
        files: List of files in the torrent (empty for single-file).
        extra_fields: Non-standard fields from info dict (verbose mode).
    """

    name: str
    info_hash: str = Field(min_length=40, max_length=40)
    size: int = Field(ge=0, description="Total size in bytes")
    piece_length: int = Field(gt=0, description="Piece size in bytes")
    piece_count: int = Field(gt=0, description="Number of pieces")
    private: bool = False
    trackers: list[str] = Field(default_factory=list)
    web_seeds: list[str] = Field(default_factory=list)
    source: str | None = None
    comment: str | None = None
    created_by: str | None = None
    creation_date: datetime | None = None
    files: list[TorrentFileInfo] = Field(default_factory=list)
    extra_fields: dict[str, Any] | None = None

    model_config = {"extra": "ignore"}

    @field_validator("info_hash")
    @classmethod
    def validate_info_hash(cls, v: str) -> str:
        """Validate info hash is a valid hex string."""
        v = v.lower()
        if not all(c in "0123456789abcdef" for c in v):
            raise ValueError(f"Invalid info hash (not hex): {v}")
        return v

    @computed_field  # type: ignore[prop-decorator]
    @property
    def file_count(self) -> int:
        """Number of files in the torrent."""
        return len(self.files) if self.files else 1

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_multi_file(self) -> bool:
        """Whether this is a multi-file torrent."""
        return len(self.files) > 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def piece_length_exponent(self) -> int:
        """Piece length as power of 2 exponent (e.g., 18 for 256KiB)."""
        import math

        return int(math.log2(self.piece_length))

    def human_piece_length(self) -> str:
        """Return human-readable piece length (e.g., '256 KiB')."""
        if self.piece_length >= 1024 * 1024:
            return f"{self.piece_length // (1024 * 1024)} MiB"
        return f"{self.piece_length // 1024} KiB"

    def human_size(self) -> str:
        """Return human-readable total size (e.g., '1.5 GiB')."""
        if self.size >= 1024**3:
            return f"{self.size / (1024**3):.2f} GiB"
        elif self.size >= 1024**2:
            return f"{self.size / (1024**2):.2f} MiB"
        elif self.size >= 1024:
            return f"{self.size / 1024:.2f} KiB"
        return f"{self.size} B"


class CheckResult(BaseModel):
    """Result of torrent verification against content.

    Created from mkbrr check output. The check compares torrent
    piece hashes against actual content on disk.

    Attributes:
        valid: True if all pieces match and no files missing.
        percent_complete: Percentage of valid pieces (0.0-100.0).
        good_pieces: Number of pieces that match.
        bad_pieces: Number of pieces with hash mismatch.
        total_pieces: Total piece count in torrent.
        bad_piece_indices: Indices of bad pieces (verbose mode only).
        missing_files: Files missing or with size mismatch.
        check_time_seconds: Time taken for verification.

    Note:
        missing_files entries may include "(size mismatch)" suffix
        if file exists but has wrong size.
    """

    valid: bool
    percent_complete: float = Field(ge=0.0, le=100.0)
    good_pieces: int = Field(ge=0)
    bad_pieces: int = Field(ge=0)
    total_pieces: int = Field(gt=0)
    bad_piece_indices: list[int] | None = None
    missing_files: list[str] = Field(default_factory=list)
    check_time_seconds: float | None = Field(default=None, ge=0.0)

    model_config = {"extra": "ignore"}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_missing_files(self) -> bool:
        """Whether any files are missing or have wrong size."""
        return len(self.missing_files) > 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_complete(self) -> bool:
        """Whether content is 100% complete with no issues."""
        return self.valid and self.percent_complete == 100.0 and not self.has_missing_files


# Validation helper functions


def validate_torrent_info(data: dict[str, Any]) -> TorrentInfo:
    """
    Validate and create TorrentInfo from raw dict.

    Args:
        data: Dict with torrent metadata (from bencode or parsed output).

    Returns:
        Validated TorrentInfo instance.

    Raises:
        pydantic.ValidationError: If validation fails.
    """
    return TorrentInfo.model_validate(data)


def validate_check_result(data: dict[str, Any]) -> CheckResult:
    """
    Validate and create CheckResult from raw dict.

    Args:
        data: Dict with check results (from parsed mkbrr check output).

    Returns:
        Validated CheckResult instance.

    Raises:
        pydantic.ValidationError: If validation fails.
    """
    return CheckResult.model_validate(data)
