"""Runtime context for CLI commands.

This module provides a typed runtime context that is initialized once
in the main callback and available to all commands via ctx.obj.

The RuntimeContext replaces the legacy ArgsNamespace pattern, providing:
- Type-safe access to global flags (dry_run, verbose, json_output)
- Lazy-loaded clients (AbsClient) to avoid overhead when not needed
- Centralized configuration access
- Easier testing via dependency injection
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shelfr.abs.client import AbsClient
    from shelfr.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class RuntimeContext:
    """Typed runtime context available to all commands via ctx.obj.

    This context is initialized once in the main callback and provides:
    - Global flags (dry_run, verbose, json_output)
    - Lazy-loaded clients (AbsClient)
    - Configuration access

    Example:
        @app.command()
        def my_command(ctx: typer.Context) -> None:
            runtime: RuntimeContext = ctx.obj
            if runtime.dry_run:
                print_dry_run("Would do something...")
                return
            client = runtime.abs_client  # Lazy-loaded
            ...
    """

    config_path: Path
    settings: Settings | None = None
    dry_run: bool = False
    verbose: bool = False
    json_output: bool = False

    # Lazy-loaded clients (initialized on first use)
    _abs_client: AbsClient | None = field(default=None, repr=False)

    @property
    def abs_client(self) -> AbsClient:
        """Get or create ABS client (lazy-loaded).

        Returns:
            Initialized ABS client.

        Raises:
            ValueError: If ABS configuration is missing from settings.
            ConnectionError: If ABS server is unreachable.
        """
        if self._abs_client is None:
            if not self.settings:
                raise ValueError("Settings not loaded - cannot create ABS client")
            if not self.settings.audiobookshelf:
                raise ValueError("ABS configuration not found in settings")
            if not self.settings.audiobookshelf.host:
                raise ValueError("ABS host not configured. Set audiobookshelf.host in config.yaml")
            if not self.settings.audiobookshelf.api_key:
                raise ValueError(
                    "ABS API key not configured. Set audiobookshelf.api_key in config.yaml"
                )

            try:
                # Heavy import deferred to runtime
                from shelfr.abs.client import AbsClient

                self._abs_client = AbsClient.from_config(self.settings.audiobookshelf)
                logger.debug("ABS client initialized for %s", self.settings.audiobookshelf.host)
            except Exception as e:
                logger.warning("Failed to initialize ABS client: %s", e)
                raise

        return self._abs_client

    def close(self) -> None:
        """Cleanup resources (close HTTP clients, etc.)."""
        if self._abs_client is not None:
            try:
                self._abs_client.close()
                logger.debug("ABS client closed")
            except Exception as e:
                logger.warning("Error closing ABS client: %s", e)
            finally:
                self._abs_client = None

    def __enter__(self) -> RuntimeContext:
        """Context manager entry."""
        return self

    def __exit__(self, *args: object) -> None:
        """Context manager exit - cleanup resources."""
        self.close()


def get_runtime_context(ctx_obj: object) -> RuntimeContext:
    """Extract RuntimeContext from typer context object.

    This helper supports both the new RuntimeContext pattern and
    the legacy dict-based pattern for gradual migration.

    Args:
        ctx_obj: The ctx.obj from typer.Context

    Returns:
        RuntimeContext instance

    Raises:
        TypeError: If ctx_obj is not a RuntimeContext or compatible dict
    """
    if isinstance(ctx_obj, RuntimeContext):
        return ctx_obj

    # Legacy dict support for gradual migration
    if isinstance(ctx_obj, dict):
        # Import here to avoid circular dependency
        from shelfr.config import reload_settings

        config_path = ctx_obj.get("config", Path("config/config.yaml"))
        try:
            settings = reload_settings(config_file=config_path)
        except FileNotFoundError:
            settings = None  # Config doesn't exist yet
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning("Failed to load settings: %s", e)
            settings = None

        return RuntimeContext(
            config_path=config_path,
            settings=settings,
            dry_run=ctx_obj.get("dry_run", False),
            verbose=ctx_obj.get("verbose", False),
            json_output=ctx_obj.get("json_output", False),
        )

    raise TypeError(
        f"Expected RuntimeContext or dict, got {type(ctx_obj).__name__}. "
        "Ensure the main callback initializes ctx.obj properly."
    )
