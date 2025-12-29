#!/usr/bin/env python3
"""Quick analysis tools for test_data/combined_metadata.json.

Usage:
    python scripts/analyze_test_data.py duplicates
    python scripts/analyze_test_data.py series-variants
    python scripts/analyze_test_data.py missing-audnex
    python scripts/analyze_test_data.py stats
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def load_data() -> list[dict]:
    """Load combined metadata."""
    data_file = Path(__file__).parent.parent / "samples" / "test_data" / "combined_metadata.json"
    if not data_file.exists():
        print(f"❌ Test data not found: {data_file}")
        print("Run: python scripts/fetch_test_data.py")
        sys.exit(1)

    data = json.loads(data_file.read_text())

    # Handle new schema format with header
    if isinstance(data, dict) and "_schema" in data:
        # Print schema info
        schema = data["_schema"]
        version = schema["version"]
        date = schema["generated_at"][:10]
        count = schema["record_count"]
        print(f"\n[Schema] v{version} | {date} | {count} records\n")
        return data.get("items", [])

    # Legacy format (flat array)
    return data if isinstance(data, list) else []


def find_duplicates() -> None:
    """Find books with potential series duplicates."""
    data = load_data()

    duplicates = []
    for item in data:
        audnex = item.get("audnex")
        if not audnex:
            continue

        primary = audnex.get("seriesPrimary")
        secondary = audnex.get("seriesSecondary")

        if primary and secondary:
            p_name = primary.get("name", "")
            s_name = secondary.get("name", "")

            # Check if they'd be duplicates after stripping [*order]
            p_clean = re.sub(r"\s*\[[^\]]*[Oo]rder\]$", "", p_name)
            s_clean = re.sub(r"\s*\[[^\]]*[Oo]rder\]$", "", s_name)
            p_clean = re.sub(
                r"\s*\((?:Publication|Reading|Chronological|Release)\s*Order\)$",
                "",
                p_clean,
                flags=re.IGNORECASE,
            )
            s_clean = re.sub(
                r"\s*\((?:Publication|Reading|Chronological|Release)\s*Order\)$",
                "",
                s_clean,
                flags=re.IGNORECASE,
            )

            if p_clean.lower() == s_clean.lower():
                duplicates.append(
                    {
                        "title": audnex.get("title"),
                        "asin": audnex.get("asin"),
                        "primary": p_name,
                        "secondary": s_name,
                        "cleaned": p_clean,
                    }
                )

    print("\n📊 Books with duplicate series (after cleaning):")
    print(f"Found: {len(duplicates)}\n")
    for d in duplicates:
        print(f"  📖 {d['title']} ({d['asin']})")
        print(f"     Primary:   {d['primary']}")
        print(f"     Secondary: {d['secondary']}")
        print(f"     → Both become: {d['cleaned']}")
        print()


def find_series_variants() -> None:
    """Find books with different primary/secondary series."""
    data = load_data()

    variants = []
    for item in data:
        audnex = item.get("audnex")
        if not audnex:
            continue

        primary = audnex.get("seriesPrimary")
        secondary = audnex.get("seriesSecondary")

        if primary and secondary:
            p_name = primary.get("name", "")
            s_name = secondary.get("name", "")

            import re

            p_clean = re.sub(r"\s*\[[^\]]*[Oo]rder\]$", "", p_name)
            s_clean = re.sub(r"\s*\[[^\]]*[Oo]rder\]$", "", s_name)
            p_clean = re.sub(
                r"\s*\((?:Publication|Reading|Chronological|Release)\s*Order\)$",
                "",
                p_clean,
                flags=re.IGNORECASE,
            )
            s_clean = re.sub(
                r"\s*\((?:Publication|Reading|Chronological|Release)\s*Order\)$",
                "",
                s_clean,
                flags=re.IGNORECASE,
            )

            if p_clean.lower() != s_clean.lower():
                variants.append(
                    {
                        "title": audnex.get("title"),
                        "primary": p_name,
                        "secondary": s_name,
                    }
                )

    print("\n📚 Books with genuinely different series:")
    print(f"Found: {len(variants)}\n")
    for v in variants[:20]:
        print(f"  {v['title']}")
        print(f"    → Primary:   {v['primary']}")
        print(f"    → Secondary: {v['secondary']}")
        print()

    if len(variants) > 20:
        print(f"  ... and {len(variants) - 20} more")


def find_missing_audnex() -> None:
    """Find books without Audnex data."""
    data = load_data()

    missing = [item for item in data if not item.get("audnex")]

    print("\n❓ Books missing Audnex metadata:")
    print(f"Found: {len(missing)}\n")
    for item in missing[:20]:
        abs_data = item.get("abs", {})
        print(f"  {abs_data.get('title')} (ASIN: {abs_data.get('asin')})")
        print(f"    Path: {abs_data.get('path')}")
        print()

    if len(missing) > 20:
        print(f"  ... and {len(missing) - 20} more")


def show_stats() -> None:
    """Show overall statistics."""
    data = load_data()

    total = len(data)
    with_audnex = sum(1 for d in data if d.get("audnex"))
    with_both_series = sum(
        1 for d in data if d.get("audnex") and d.get("audnex").get("seriesSecondary")
    )

    # Count duplicates and variants
    duplicates = 0
    variants = 0
    for item in data:
        audnex = item.get("audnex")
        if not audnex:
            continue

        primary = audnex.get("seriesPrimary")
        secondary = audnex.get("seriesSecondary")

        if primary and secondary:
            p_name = primary.get("name", "")
            s_name = secondary.get("name", "")

            import re

            p_clean = re.sub(r"\s*\[[^\]]*[Oo]rder\]$", "", p_name)
            s_clean = re.sub(r"\s*\[[^\]]*[Oo]rder\]$", "", s_name)
            p_clean = re.sub(
                r"\s*\((?:Publication|Reading|Chronological|Release)\s*Order\)$",
                "",
                p_clean,
                flags=re.IGNORECASE,
            )
            s_clean = re.sub(
                r"\s*\((?:Publication|Reading|Chronological|Release)\s*Order\)$",
                "",
                s_clean,
                flags=re.IGNORECASE,
            )

            if p_clean.lower() == s_clean.lower():
                duplicates += 1
            else:
                variants += 1

    print("\n📊 Test Data Statistics:")
    print(f"  Total books: {total}")
    print(f"  With Audnex data: {with_audnex} ({100*with_audnex/total:.1f}%)")
    print(f"  With both series: {with_both_series}")
    print(f"  Duplicate series (order variants): {duplicates}")
    print(f"  Different series (genuinely dual): {variants}")
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    command = sys.argv[1]

    if command == "duplicates":
        find_duplicates()
    elif command == "series-variants":
        find_series_variants()
    elif command == "missing-audnex":
        find_missing_audnex()
    elif command == "stats":
        show_stats()
    else:
        print(f"Unknown command: {command}\n")
        print(__doc__)
        sys.exit(1)
