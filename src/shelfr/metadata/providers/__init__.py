"""
Metadata providers package.

This package contains the pluggable provider system for fetching metadata
from multiple sources (Audnex, MediaInfo, ABS sidecars, etc.).

Architecture:
- providers/types.py: Core types (LookupContext, ProviderResult, FieldName)
- providers/base.py: MetadataProvider protocol
- providers/registry.py: ProviderRegistry for managing providers
- providers/*.py: Concrete provider implementations
"""

from __future__ import annotations

from .audnex import AudnexProvider
from .base import MetadataProvider, ProviderKind
from .hardcover import HardcoverProvider
from .mock import MockProvider
from .registry import ProviderRegistry, default_registry
from .types import FieldName, IdType, LookupContext, ProviderResult

__all__ = [
    # Providers
    "AudnexProvider",
    # Core types
    "FieldName",
    "HardcoverProvider",
    "IdType",
    "LookupContext",
    # Protocol
    "MetadataProvider",
    "MockProvider",
    "ProviderKind",
    # Registry
    "ProviderRegistry",
    "ProviderResult",
    "default_registry",
]
