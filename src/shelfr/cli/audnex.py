"""Audnex commands (sub-app).

Commands for Audnex API diagnostics and observability (Phase 10.7).

Commands:
    shelfr audnex region-stats - Show region cache statistics
"""

from __future__ import annotations

import asyncio
import json
import logging

import typer
from rich.table import Table

from shelfr.console import console
from shelfr.metadata.audnex.region_cache import get_default_region_cache

logger = logging.getLogger(__name__)


# =============================================================================
# Command Registration
# =============================================================================


def register_audnex_commands(audnex_app: typer.Typer) -> None:
    """Register Audnex commands on the audnex sub-app."""

    @audnex_app.callback(invoke_without_command=True)
    def audnex_callback(ctx: typer.Context) -> None:
        """Audnex API diagnostics and statistics.

        Commands:
          shelfr audnex region-stats  Show region cache statistics

        These tools help monitor the parallel region lookup system.
        """
        if ctx.invoked_subcommand is None:
            console.print(ctx.get_help())
            raise typer.Exit(0)

    @audnex_app.command("region-stats")
    def region_stats_command(
        json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    ) -> None:
        """Show region cache statistics.

        Displays statistics about the ASIN → region cache, including:
        - Total cached entries
        - Region distribution (count and percentage)
        - Total cache hits
        - Entries with pending failures

        Use --json for machine-readable output.

        Example output:
          Region Distribution (1,234 entries):
          ┌────────┬───────┬─────────┐
          │ Region │ Count │ Percent │
          ├────────┼───────┼─────────┤
          │ us     │ 1,000 │ 81.0%   │
          │ uk     │   180 │ 14.6%   │
          │ de     │    54 │  4.4%   │
          └────────┴───────┴─────────┘

        Use this to verify cache effectiveness and debug region issues.
        """
        result = asyncio.run(_region_stats_async(json_output=json_output))
        raise typer.Exit(result)


async def _region_stats_async(*, json_output: bool = False) -> int:
    """Async implementation of region-stats command."""
    cache = get_default_region_cache()

    try:
        # Ensure cache is loaded
        await cache.load()
        stats = await cache.get_stats()

        # Extract stats values (inside try/except for KeyError safety)
        total_entries = stats["total_entries"]
        region_distribution = stats["region_distribution"]
        total_hits = stats["total_hits"]
        entries_with_failures = stats["entries_with_failures"]
    except Exception as e:
        logger.exception("Failed to load region cache stats")
        console.print(f"[red]Error reading region cache:[/] {e}")
        return 1

    # JSON output mode
    if json_output:
        output = {
            "total_entries": total_entries,
            "region_distribution": region_distribution,
            "total_hits": total_hits,
            "entries_with_failures": entries_with_failures,
        }
        console.print(json.dumps(output, indent=2))
        return 0

    if total_entries == 0:
        console.print(
            "[yellow]Region cache is empty.[/]\n"
            "[dim]Cache is populated when ASINs are looked up via parallel fetch.[/]"
        )
        return 0

    # Region distribution table
    console.print(f"\n[bold cyan]Region Distribution[/] ({total_entries:,} entries):\n")

    region_table = Table(show_header=True, header_style="bold")
    region_table.add_column("Region", style="cyan")
    region_table.add_column("Count", justify="right")
    region_table.add_column("Percent", justify="right")

    # Sort regions by count (descending)
    sorted_regions = sorted(region_distribution.items(), key=lambda x: x[1], reverse=True)

    for region, count in sorted_regions:
        pct = (count / total_entries) * 100
        region_table.add_row(region, f"{count:,}", f"{pct:.1f}%")

    console.print(region_table)

    # Cache performance table
    console.print("\n[bold cyan]Cache Performance:[/]\n")

    perf_table = Table(show_header=True, header_style="bold")
    perf_table.add_column("Metric", style="cyan")
    perf_table.add_column("Value", justify="right")

    perf_table.add_row("Total cache hits", f"{total_hits:,}")
    perf_table.add_row("Entries with failures", f"{entries_with_failures:,}")
    # TODO: Add hit rate calculation when miss tracking is implemented

    console.print(perf_table)
    console.print()

    return 0
