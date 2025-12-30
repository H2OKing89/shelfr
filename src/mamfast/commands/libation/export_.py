"""Export command: export library data.

This command exports Libation library to various formats.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
from pathlib import Path

from mamfast.console import console
from mamfast.utils.cmd import CmdError, docker

from ._common import run_libation_cmd as _run_libation_cmd
from ._ui import print_libation_header

logger = logging.getLogger(__name__)


def cmd_libation_export(args: argparse.Namespace) -> int:
    """Export Libation library data."""
    from mamfast.config import reload_settings

    if args.output is None:
        console.print("[red]✗ Output path is required:[/] Use -o/--output to specify output file")
        return 1

    output_path = Path(args.output)
    format_type = args.format

    print_libation_header(
        "Export Library",
        f"Exporting your library to {format_type.upper()}",
    )

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        console.print(f"[red]✗ Configuration error:[/] {e}")
        return 1

    container = settings.libation_container

    if args.dry_run:
        console.print("[yellow]Would export to:[/]")
        console.print(f"  {output_path}")
        return 0

    console.print(f"[bold]Exporting library to {output_path}...[/]")

    # Map format to flag
    format_flags = {"json": "-j", "csv": "-c", "xlsx": "-x"}
    flag = format_flags.get(format_type, "-j")

    # Export to container temp path first (use PID for uniqueness)
    import os

    container_path = f"/tmp/mamfast_export_{os.getpid()}.{format_type}"
    result = _run_libation_cmd(container, "export", "-p", container_path, flag)

    if not result.success:
        console.print(f"  [red]✗[/] Export failed: {result.error_message or result.stderr}")
        return 1

    # Copy from container to host
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        docker("cp", f"{container}:{container_path}", str(output_path), timeout=30)
        console.print(f"  [green]✓[/] Exported to: {output_path}")

        # Show file size
        if output_path.exists():
            size = output_path.stat().st_size
            size_str = f"{size / 1024:.1f} KB" if size > 1024 else f"{size} bytes"
            console.print(f"  [dim]Size: {size_str}[/]")

    except CmdError as e:
        console.print(f"  [red]✗[/] Failed to copy export: {e}")
        return 1
    finally:
        # Cleanup
        with contextlib.suppress(CmdError):
            docker("exec", container, "rm", "-f", container_path, timeout=10)

    return 0


__all__ = ["cmd_libation_export"]
