"""Diagnostic commands for MAMFast CLI.

These commands analyze releases to identify potential issues
like duplicates, suspicious patterns, or preview naming changes.
"""

from __future__ import annotations

import argparse
import logging
from typing import TYPE_CHECKING

from mamfast.console import (
    console,
    fatal_error,
    print_dry_run_book,
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
    from mamfast.metadata import fetch_all_metadata
    from mamfast.staging import compute_release_transforms

    console.print("\n[bold cyan]Preview Mode: Showing what would be renamed[/]")

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    # Get releases to preview
    if args.asin:
        release = get_release_by_asin(args.asin)
        if not release:
            print_error(f"Release not found: {args.asin}")
            return 1
        releases = [release]
    else:
        releases = get_new_releases()
        if args.limit:
            releases = releases[: args.limit]

    if not releases:
        console.print("[dim]No releases to preview[/]")
        return 0

    console.print(f"\n[dim]Found {len(releases)} release(s) to preview[/]")

    # Get naming config
    naming_config: NamingConfig | None = None
    if settings.filters and settings.filters.naming:
        naming_config = settings.filters.naming

    all_transforms: list[DryRunTransform] = []

    # Process each release
    for release in releases:
        # Fetch metadata if needed
        metadata = fetch_all_metadata(release, settings)
        audnex_data = metadata.audnex or {}

        # Compute transforms
        transforms = compute_release_transforms(
            release=release,
            audnex_data=audnex_data,
            settings=settings,
            naming_config=naming_config,
            verbose=args.verbose if hasattr(args, "verbose") else False,
        )

        # Print results for this book
        print_dry_run_book(
            release=release,
            transforms=transforms,
            audnex_data=audnex_data,
        )
        all_transforms.extend(transforms)

    # Summary
    print_dry_run_summary(all_transforms)

    return 0


def cmd_check_duplicates(args: argparse.Namespace) -> int:
    """Check for duplicate releases."""
    from collections import Counter

    from mamfast.config import reload_settings
    from mamfast.discovery import get_all_releases

    console.print("\n[bold cyan]Duplicate Check[/]")

    try:
        reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    releases = get_all_releases()

    # Group by ASIN
    asin_counts = Counter(r.asin for r in releases if r.asin)
    duplicates = {asin: count for asin, count in asin_counts.items() if count > 1}

    if duplicates:
        console.print(f"\n[warning]Found {len(duplicates)} duplicate ASIN(s):[/]")
        for asin, count in sorted(duplicates.items(), key=lambda x: -x[1]):
            console.print(f"  {asin}: {count} copies")
            # Show paths
            for r in releases:
                if r.asin == asin:
                    console.print(f"    [dim]{r.source_path}[/]")
        return 1
    else:
        console.print("[success]✓[/] No duplicates found")
        return 0


def cmd_check_suspicious(args: argparse.Namespace) -> int:
    """Check for suspicious naming patterns."""
    from mamfast.config import reload_settings
    from mamfast.discovery import get_new_releases, get_release_by_asin
    from mamfast.metadata import fetch_all_metadata
    from mamfast.staging import compute_release_transforms

    console.print("\n[bold cyan]Suspicious Pattern Check[/]")

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    # Get releases
    if args.asin:
        release = get_release_by_asin(args.asin)
        if not release:
            print_error(f"Release not found: {args.asin}")
            return 1
        releases = [release]
    else:
        releases = get_new_releases()
        if args.limit:
            releases = releases[: args.limit]

    if not releases:
        console.print("[dim]No releases to check[/]")
        return 0

    # Get naming config
    naming_config: NamingConfig | None = None
    if settings.filters and settings.filters.naming:
        naming_config = settings.filters.naming

    suspicious_releases: list[tuple[str, str, list[str]]] = []

    for release in releases:
        issues: list[str] = []

        # Fetch metadata
        metadata = fetch_all_metadata(release, settings)
        audnex_data = metadata.audnex or {}

        # Compute transforms
        transforms = compute_release_transforms(
            release=release,
            audnex_data=audnex_data,
            settings=settings,
            naming_config=naming_config,
            verbose=False,
        )

        # Check for suspicious patterns
        for t in transforms:
            # Long filenames (close to MAM limit)
            if len(t.new) > 200:
                issues.append(f"Long filename ({len(t.new)} chars): {t.new[:50]}...")

            # Double dashes (cleanup issue)
            if "--" in t.new:
                issues.append(f"Double dash in: {t.new}")

            # Empty parens
            if "()" in t.new or "[]" in t.new:
                issues.append(f"Empty brackets in: {t.new}")

            # Multiple spaces
            if "  " in t.new:
                issues.append(f"Multiple spaces in: {t.new}")

            # Suspicious Unicode
            if any(ord(c) > 127 for c in t.new):
                non_ascii = [c for c in t.new if ord(c) > 127]
                issues.append(f"Non-ASCII chars {non_ascii[:5]} in: {t.new[:50]}...")

            # Missing ASIN tag
            if "{ASIN." not in t.new and t.transform_type == "folder":
                issues.append(f"Missing ASIN in folder: {t.new}")

        if issues:
            suspicious_releases.append(
                (release.asin or "no-asin", release.display_name, issues)
            )

    # Print results
    print_suspicious_changes(suspicious_releases)

    return 1 if suspicious_releases else 0
