"""Legacy helpers for backward compatibility.

This module provides the ArgsNamespace and get_args helper for existing
command handlers that expect argparse-style namespaces.

NOTE: This is deprecated. New commands should use RuntimeContext from ctx.obj.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import typer


class ArgsNamespace(argparse.Namespace):
    """Namespace compatible with argparse for existing command handlers.

    DEPRECATED: New commands should use RuntimeContext from ctx.obj instead.
    This exists only for backward compatibility with existing handlers.
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)


def get_args(ctx: typer.Context, **kwargs: Any) -> ArgsNamespace:
    """Create args namespace from context and keyword arguments.

    DEPRECATED: New commands should use RuntimeContext from ctx.obj instead.

    This bridge function exists to maintain compatibility with existing
    command handlers that expect argparse.Namespace-like objects.

    Args:
        ctx: Typer context with global options in ctx.obj
        **kwargs: Command-specific arguments

    Returns:
        ArgsNamespace with both global and command-specific args
    """
    ctx_obj = ctx.obj if isinstance(ctx.obj, dict) else {}
    args = ArgsNamespace(
        verbose=ctx_obj.get("verbose", False),
        config=ctx_obj.get("config", Path("config/config.yaml")),
        dry_run=ctx_obj.get("dry_run", False),
        **kwargs,
    )
    return args
