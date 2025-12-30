"""Settings command: view Libation settings.

This command displays Libation configuration.
"""

from __future__ import annotations

import argparse
import logging

from rich.panel import Panel
from rich.table import Table

from shelfr.console import console

from ._common import run_libation_cmd as _run_libation_cmd
from ._ui import print_hint_box, print_libation_header

logger = logging.getLogger(__name__)


def cmd_libation_settings(args: argparse.Namespace) -> int:
    """View Libation settings."""
    from shelfr.config import reload_settings

    print_libation_header(
        "Libation Settings",
        "Current configuration of your Libation installation",
    )

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        console.print(f"[red]✗ Configuration error:[/] {e}")
        return 1

    container = settings.libation_container

    # Check for specific setting
    setting_name = getattr(args, "setting", None)

    console.print("[bold]Fetching settings...[/]")

    cmd_args = ["get-setting"]
    if getattr(args, "list_enum", False):
        cmd_args.append("-l")
    if setting_name:
        cmd_args.append(setting_name)

    result = _run_libation_cmd(container, *cmd_args)

    if result.success:
        console.print()
        if result.stdout:
            # Parse and display settings nicely
            lines = result.stdout.strip().split("\n")

            if setting_name:
                # Single setting
                console.print(Panel(result.stdout.strip(), title=f"Setting: {setting_name}"))
            else:
                # Create a nice table for all settings
                table = Table(
                    title="Libation Settings",
                    show_header=True,
                    header_style="bold cyan",
                )
                table.add_column("Setting", style="cyan")
                table.add_column("Value")

                # Parse the table output from Libation
                for line in lines:
                    if "|" in line and "---" not in line:
                        parts = [p.strip() for p in line.split("|") if p.strip()]
                        if len(parts) >= 2:
                            table.add_row(parts[0], parts[1])

                console.print(table)

        console.print()
        print_hint_box(
            [
                "shelfr libation settings FileTemplate → View specific setting",
                "shelfr libation settings --list-enum  → Show enum options",
                "Override at runtime: -o SettingName=Value",
            ]
        )
    else:
        console.print(f"  [red]✗[/] Failed to get settings: {result.error_message}")
        return 1

    return 0


__all__ = ["cmd_libation_settings"]
