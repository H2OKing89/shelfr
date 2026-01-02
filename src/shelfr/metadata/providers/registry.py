"""
Provider registry for managing metadata providers.

The registry maintains a collection of providers and provides methods
to retrieve them in priority order or filtered by context.

Design decisions:
- Instance-based (not global state) for testability
- Stable sort order: (priority, name) prevents jitter when priorities tie
- default_registry provided for CLI runtime (tests should create their own)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import field as dataclass_field

from .base import MetadataProvider, ProviderKind
from .types import IdType, LookupContext

logger = logging.getLogger(__name__)


@dataclass
class ProviderRegistry:
    """Registry for metadata providers.

    Instance-based for testability - each test can create its own registry
    without leaking state between tests.

    Attributes:
        _providers: Internal mapping of provider name to provider instance

    Example:
        registry = ProviderRegistry()
        registry.register(AudnexProvider())
        registry.register(MediaInfoProvider())

        # Get all providers in priority order
        for provider in registry.all():
            print(f"{provider.name}: priority={provider.priority}")

        # Get providers for specific context
        ctx = LookupContext.from_asin(asin="B08G9PRS1K")
        for provider in registry.get_for_context(ctx, "asin"):
            result = await provider.fetch(ctx, "asin")
    """

    _providers: dict[str, MetadataProvider] = dataclass_field(default_factory=dict)

    def register(self, provider: MetadataProvider) -> None:
        """Register a provider.

        Args:
            provider: Provider instance to register

        Note:
            If a provider with the same name already exists, it will be
            overwritten and a warning will be logged.
        """
        if provider.name in self._providers:
            logger.warning("Overwriting existing provider %s with new instance", provider.name)
        self._providers[provider.name] = provider
        logger.debug("Registered provider: %s (priority=%d)", provider.name, provider.priority)

    def unregister(self, name: str) -> bool:
        """Unregister a provider by name.

        Args:
            name: Provider name to unregister

        Returns:
            True if provider was found and removed, False otherwise
        """
        if name in self._providers:
            del self._providers[name]
            logger.debug("Unregistered provider: %s", name)
            return True
        return False

    def get(self, name: str) -> MetadataProvider | None:
        """Get provider by name.

        Args:
            name: Provider name

        Returns:
            Provider instance or None if not found
        """
        return self._providers.get(name)

    def all(self) -> list[MetadataProvider]:
        """Get all registered providers in priority order.

        Returns providers sorted by (priority, name) for deterministic ordering.
        Lower priority number = higher priority (fetched first).

        Returns:
            List of providers sorted by priority (lowest first)
        """
        return sorted(self._providers.values(), key=lambda p: (p.priority, p.name))

    def get_for_context(
        self,
        ctx: LookupContext,
        id_type: IdType,
    ) -> list[MetadataProvider]:
        """Get all providers that can handle this context, in priority order.

        Filters providers by their can_lookup() method and returns
        applicable ones in priority order.

        Args:
            ctx: Lookup context with identifiers and paths
            id_type: Identifier type to use for lookup

        Returns:
            List of applicable providers in priority order
        """
        return [p for p in self.all() if p.can_lookup(ctx, id_type)]

    def get_by_kind(self, kind: ProviderKind) -> list[MetadataProvider]:
        """Get all providers of a specific kind.

        Args:
            kind: Provider kind ("local" or "network")

        Returns:
            List of matching providers in priority order
        """
        return [p for p in self.all() if p.kind == kind]

    def clear(self) -> None:
        """Remove all registered providers."""
        self._providers.clear()
        logger.debug("Cleared all providers from registry")

    def __len__(self) -> int:
        """Get number of registered providers."""
        return len(self._providers)

    def __contains__(self, name: str) -> bool:
        """Check if provider is registered."""
        return name in self._providers


# Default registry for CLI runtime.
# WARNING: Tests should always instantiate their own registry to avoid leaking state.
default_registry = ProviderRegistry()
