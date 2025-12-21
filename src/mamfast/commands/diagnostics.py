"""Diagnostic commands for MAMFast CLI.

These commands help analyze and troubleshoot releases,
including duplicate detection and suspicious title changes.
"""

from __future__ import annotations

import argparse
import json as json_module
import logging
import re
from typing import TYPE_CHECKING

from mamfast.console import (
    console,
    fatal_error,
    print_dry_run_header,
    print_dry_run_release,
    print_dry_run_summary,
    print_error,
    print_suspicious_changes,
)

if TYPE_CHECKING:
    from mamfast.config import NamingConfig

logger = logging.getLogger(__name__)


def cmd_dry_run(args: argparse.Namespace) -> int:
    """Preview naming transformations without making changes."""
    from mamfast.config import reload_settings
    from mamfast.console import DryRunTransform
    from mamfast.discovery import get_new_releases, get_release_by_asin
    from mamfast.logging_setup import set_console_quiet
    from mamfast.utils.naming import filter_title, transliterate_text

    set_console_quiet(True)

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        set_console_quiet(False)
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    naming_config = settings.naming

    # Get releases to process
    if args.asin:
        release = get_release_by_asin(args.asin)
        if not release:
            set_console_quiet(False)
            fatal_error(f"Release not found with ASIN: {args.asin}")
            return 1
        releases = [release]
    else:
        releases = get_new_releases()
        if args.limit and args.limit > 0:
            releases = releases[: args.limit]

    set_console_quiet(False)

    if not releases:
        console.print("[dim]No new releases to preview[/]")
        return 0

    # Print header
    print_dry_run_header(len(releases))

    # Track stats
    would_change = 0
    no_change = 0

    # Process each release
    for release in releases:
        transforms: list[DryRunTransform] = []

        # Original folder name from source
        original_name = release.source_dir.name if release.source_dir else release.title
        final_name = original_name

        # Step 1: filter_title removes phrases
        filtered_name = filter_title(
            original_name,
            settings.filters.remove_phrases,
            naming_config=naming_config,
        )

        if original_name != filtered_name:
            # Determine which rule caused the change by re-running with verbose
            # For now, detect the rule type heuristically
            rule = _detect_rule(original_name, filtered_name, naming_config)
            transforms.append(
                DryRunTransform(
                    field="title",
                    before=original_name,
                    after=filtered_name,
                    rule=rule,
                )
            )
            final_name = filtered_name

        # Step 2: transliterate (Japanese characters, etc.)
        transliterated = transliterate_text(filtered_name, settings.filters)
        if filtered_name != transliterated:
            transforms.append(
                DryRunTransform(
                    field="title",
                    before=filtered_name,
                    after=transliterated,
                    rule="transliteration",
                )
            )
            final_name = transliterated

        # Track stats
        if transforms:
            would_change += 1
        else:
            no_change += 1

        # Always print release info (show what we're checking)
        release_label = f"{release.title}" if release.title else original_name
        if release.asin:
            release_label += f" [dim]({release.asin})[/dim]"

        print_dry_run_release(
            transforms,
            release_title=release_label,
            source_path=original_name,
            target_path=final_name,
        )

    # Print summary
    print_dry_run_summary(len(releases), would_change, no_change)
    return 0


def _detect_rule(original: str, filtered: str, naming_config: NamingConfig | None) -> str | None:
    """Detect which naming rule caused a transformation."""
    if not naming_config:
        return None

    # Check format indicators (e.g., "(Light Novel)")
    for phrase in naming_config.format_indicators:
        if phrase.lower() in original.lower() and phrase.lower() not in filtered.lower():
            return f"format_indicators: {phrase}"

    # Check genre tags
    for phrase in naming_config.genre_tags:
        if phrase.lower() in original.lower() and phrase.lower() not in filtered.lower():
            return f"genre_tags: {phrase}"

    # Check publisher tags
    for phrase in naming_config.publisher_tags:
        if phrase.lower() in original.lower() and phrase.lower() not in filtered.lower():
            return f"publisher_tags: {phrase}"

    # Check hardcoded patterns (Book XX, Vol XX, etc.)
    if re.search(r"\bBook\s+\d+", original, re.IGNORECASE) and not re.search(
        r"\bBook\s+\d+", filtered, re.IGNORECASE
    ):
        return "hardcoded_patterns: Book N"

    if re.search(r"\bVol(?:ume)?\.?\s+\d+", original, re.IGNORECASE) and not re.search(
        r"\bVol(?:ume)?\.?\s+\d+", filtered, re.IGNORECASE
    ):
        return "volume_patterns"

    return "naming_rules"


def cmd_check_duplicates(args: argparse.Namespace) -> int:
    """Find potential duplicate releases in library."""
    from rich.table import Table

    from mamfast.config import reload_settings
    from mamfast.discovery import get_new_releases, scan_library
    from mamfast.logging_setup import set_console_quiet
    from mamfast.utils.fuzzy import find_duplicates

    set_console_quiet(True)

    try:
        reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        set_console_quiet(False)
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    # Get releases - either all or just new
    releases = scan_library() if args.include_processed else get_new_releases()

    set_console_quiet(False)

    if not releases:
        console.print("[dim]No releases found to check[/]")
        return 0

    # Extract titles for duplicate detection
    titles = [r.title for r in releases if r.title]
    threshold = args.threshold

    console.print(
        f"[bold]Checking {len(releases)} releases for duplicates[/] "
        f"[dim](threshold: {threshold}%)[/]\n"
    )

    # Find duplicates
    duplicates = find_duplicates(titles, threshold=threshold)

    if not duplicates:
        console.print("[success]✓ No potential duplicates found[/]")
        return 0

    # Limit results
    limit = args.limit
    shown_duplicates = duplicates[:limit]

    # Build Rich table
    table = Table(
        title=f"[warning]Found {len(duplicates)} Potential Duplicate Pair(s)[/]",
        show_header=True,
        header_style="bold",
    )
    table.add_column("Release 1", style="cyan", overflow="fold")
    table.add_column("Release 2", style="cyan", overflow="fold")
    table.add_column("Similarity", style="yellow", justify="right")
    table.add_column("ASINs", style="dim")

    for dup in shown_duplicates:
        # Find the actual releases to get ASINs
        r1 = next((r for r in releases if r.title == dup.item1), None)
        r2 = next((r for r in releases if r.title == dup.item2), None)

        asin_info = ""
        if r1 and r2:
            if r1.asin == r2.asin:
                asin_info = f"Same: {r1.asin}"
            else:
                asin_info = f"{r1.asin or '?'} / {r2.asin or '?'}"

        table.add_row(
            dup.item1[:50] + "..." if len(dup.item1) > 50 else dup.item1,
            dup.item2[:50] + "..." if len(dup.item2) > 50 else dup.item2,
            f"{dup.similarity:.0f}%",
            asin_info,
        )

    console.print(table)

    if len(duplicates) > limit:
        console.print(
            f"\n[dim]Showing {limit} of {len(duplicates)} pairs. Use --limit to show more.[/]"
        )

    return 0


def cmd_check_suspicious(args: argparse.Namespace) -> int:
    """Check for over-aggressive title cleaning by naming rules."""
    from mamfast.config import reload_settings
    from mamfast.discovery import get_new_releases, get_release_by_asin, scan_library
    from mamfast.logging_setup import set_console_quiet
    from mamfast.utils.fuzzy import analyze_change
    from mamfast.utils.naming import filter_title

    set_console_quiet(True)

    output_json = getattr(args, "json", False)

    try:
        reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        set_console_quiet(False)
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    # Get releases
    if args.asin:
        release = get_release_by_asin(args.asin)
        if not release:
            set_console_quiet(False)
            print_error(f"Release not found: {args.asin}")
            return 1
        releases = [release]
    elif args.include_processed:
        releases = scan_library()
    else:
        releases = get_new_releases()

    set_console_quiet(False)

    if not releases:
        if output_json:
            console.print(json_module.dumps({"suspicious": [], "summary": {"total": 0}}))
        else:
            console.print("[dim]No releases found to check[/]")
        return 0

    threshold = args.threshold
    if not output_json:
        console.print(
            f"[bold]Checking {len(releases)} releases for suspicious title changes[/] "
            f"[dim](threshold: {threshold}% similarity)[/]\n"
        )

    # Check each release
    suspicious: list[tuple[str, str, str, float]] = []

    for release in releases:
        if not release.title:
            continue

        original = release.title
        cleaned = filter_title(original)

        # Use fuzzy analysis to detect suspicious changes
        # Pass CLI threshold so is_suspicious uses user-supplied value
        analysis = analyze_change(original, cleaned, threshold=threshold)

        if analysis.is_suspicious:
            suspicious.append(
                (
                    release.asin or "",
                    original,
                    cleaned,
                    analysis.similarity,
                )
            )

    # Output results
    if output_json:
        output = {
            "suspicious": [
                {
                    "asin": asin,
                    "original": orig,
                    "cleaned": clean,
                    "similarity": sim,
                }
                for asin, orig, clean, sim in suspicious
            ],
            "summary": {
                "total": len(releases),
                "suspicious_count": len(suspicious),
                "threshold": threshold,
            },
        }
        console.print(json_module.dumps(output, indent=2))
    else:
        print_suspicious_changes(suspicious)

        console.print()
        if suspicious:
            console.print(
                f"[warning]Found {len(suspicious)} suspicious change(s)[/] "
                f"out of {len(releases)} releases"
            )
        else:
            console.print(
                f"[success]✓ All {len(releases)} releases have safe title transformations[/]"
            )

    return 1 if suspicious else 0
