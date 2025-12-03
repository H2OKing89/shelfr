"""Pydantic schemas for processed.json state file validation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ProcessedRelease(BaseModel):
    """A single processed release entry in the state file."""

    asin: str
    title: str
    author: str | None = None
    series: str | None = None
    processed_at: str  # ISO format datetime string
    staging_dir: str | None = None
    torrent_path: str | None = None
    status: str = "COMPLETE"  # COMPLETE, FAILED, etc.

    @field_validator("processed_at")
    @classmethod
    def validate_datetime(cls, v: str) -> str:
        """Validate that processed_at is a valid ISO datetime string."""
        try:
            # Try to parse it - will raise ValueError if invalid
            datetime.fromisoformat(v)
        except ValueError as e:
            raise ValueError(f"Invalid datetime format: {v}") from e
        return v

    model_config = {"extra": "ignore"}  # Allow unknown fields for forward compat


class FailedRelease(BaseModel):
    """A failed release entry in the state file."""

    asin: str | None = None
    title: str | None = None
    path: str | None = None
    error: str | None = None
    failed_at: str | None = None
    retry_count: int = 0

    model_config = {"extra": "ignore"}


class ProcessedState(BaseModel):
    """
    Schema for processed.json state file.

    Validates state integrity on load, catches corruption.
    Version field allows for schema migrations.
    """

    version: int = 1
    processed: dict[str, ProcessedRelease] = Field(default_factory=dict)
    failed: dict[str, FailedRelease] = Field(default_factory=dict)

    model_config = {"extra": "ignore"}  # Allow unknown top-level keys


def validate_state(data: dict[str, Any]) -> ProcessedState:
    """
    Validate processed.json state data.

    Args:
        data: Raw dict loaded from processed.json

    Returns:
        Validated ProcessedState instance

    Raises:
        pydantic.ValidationError: If validation fails
    """
    return ProcessedState.model_validate(data)


def create_empty_state() -> ProcessedState:
    """Create a new empty state with default values."""
    return ProcessedState()
