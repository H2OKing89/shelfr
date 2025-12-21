#!/usr/bin/env python3
"""
Build golden test samples from Audiobookshelf library + Audnex API.

Fetches all audiobooks from your Audiobookshelf instance, extracts ASINs,
then fetches full metadata from Audnex API to create test fixtures.

Usage:
    python scripts/build_golden_samples.py
    python scripts/build_golden_samples.py --limit 50
    python scripts/build_golden_samples.py --output samples/my_samples.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, cast

import httpx
from dotenv import load_dotenv

# Load .env from config directory
ENV_PATH = Path(__file__).parent.parent / "config" / ".env"
load_dotenv(ENV_PATH)

# Configuration from .env
ABS_HOST = os.getenv("AUDIOBOOKSHELF_HOST", "").rstrip("/")
ABS_API_KEY = os.getenv("AUDIOBOOKSHELF_API_KEY", "")
AUDNEX_BASE_URL = "https://api.audnex.us"

# Rate limiting
AUDNEX_DELAY = 0.5  # seconds between Audnex requests (be nice to the API)


def fetch_abs_libraries(client: httpx.Client) -> list[dict[str, Any]]:
    """Fetch all libraries from Audiobookshelf."""
    response = client.get(
        f"{ABS_HOST}/api/libraries",
        headers={"Authorization": f"Bearer {ABS_API_KEY}"},
    )
    response.raise_for_status()
    payload = response.json()
    libs = payload.get("libraries", [])
    return cast(list[dict[str, Any]], libs)


def fetch_abs_library_items(client: httpx.Client, library_id: str) -> list[dict[str, Any]]:
    """Fetch all items from a specific library."""
    items: list[dict[str, Any]] = []
    page = 0
    limit = 100

    while True:
        response = client.get(
            f"{ABS_HOST}/api/libraries/{library_id}/items",
            headers={"Authorization": f"Bearer {ABS_API_KEY}"},
            params={"limit": limit, "page": page, "expanded": 1},
        )
        response.raise_for_status()
        data = response.json()

        results = data.get("results", [])
        items.extend(cast(list[dict[str, Any]], results))

        if len(results) < limit:
            break
        page += 1

    return items


def extract_asin(item: dict[str, Any]) -> str | None:
    """Extract ASIN from an Audiobookshelf item."""
    media = cast(dict[str, Any], item.get("media", {}))
    metadata = cast(dict[str, Any], media.get("metadata", {}))

    # Try direct ASIN field
    asin = metadata.get("asin")
    if isinstance(asin, str) and asin:
        return asin

    # Try parsing from folder name pattern {ASIN.XXXXXXXXXX}
    rel_path = str(item.get("relPath", ""))
    import re

    match = re.search(r"\{ASIN\.([A-Z0-9]{10})\}", rel_path)
    if match:
        return match.group(1)

    return None


def fetch_audnex_book(client: httpx.Client, asin: str) -> dict[str, Any] | None:
    """Fetch book metadata from Audnex API."""
    try:
        response = client.get(f"{AUDNEX_BASE_URL}/books/{asin}", timeout=10.0)
        if response.status_code == 200:
            payload = response.json()
            return cast(dict[str, Any], payload)
        elif response.status_code == 404:
            print(f"  ⚠ ASIN {asin} not found in Audnex")
            return None
        else:
            print(f"  ✗ Audnex error for {asin}: {response.status_code}")
            return None
    except httpx.RequestError as e:
        print(f"  ✗ Network error for {asin}: {e}")
        return None


def fetch_audnex_chapters(client: httpx.Client, asin: str) -> dict[str, Any] | None:
    """Fetch chapter data from Audnex API."""
    try:
        response = client.get(f"{AUDNEX_BASE_URL}/books/{asin}/chapters", timeout=10.0)
        if response.status_code == 200:
            return cast(dict[str, Any], response.json())
        return None
    except httpx.RequestError:
        return None


def categorize_sample(audnex_data: dict[str, Any]) -> str:
    """Determine which category a sample belongs to based on its data."""
    title = audnex_data.get("title", "")
    subtitle = audnex_data.get("subtitle")
    series_primary = audnex_data.get("seriesPrimary") or {}
    series_name = series_primary.get("name", "")

    # Check for series cleaning issues
    if series_name:
        series_lower = series_name.lower()
        if series_lower.endswith(" series"):
            return "series_suffix"
        if "[" in series_name and "order]" in series_lower:
            return "sorting_tag"
        if series_name.endswith(" Trilogy") or series_name.endswith(" Saga"):
            return "series_suffix"
        if series_name.endswith(" Light Novel"):
            return "series_suffix"

    # Check for "The" prefix inheritance
    if series_name and title:
        title_lower = title.lower()
        series_lower = series_name.lower()
        if (
            title_lower.startswith("the ")
            and not series_lower.startswith("the ")
            and series_lower in title_lower
        ):
            return "the_prefix"

    # Check for title/subtitle swap
    if subtitle and series_name:
        subtitle_lower = subtitle.lower()
        title_lower = title.lower()
        series_lower = series_name.lower()

        # Subtitle has series name but title doesn't = swapped
        if series_lower in subtitle_lower and series_lower not in title_lower:
            return "swapped_mapping"

    # Check for standalone (no series)
    if not series_name:
        return "standalone"

    return "correct_mapping"


def build_expected_output(
    audnex_data: dict[str, Any], category: str
) -> tuple[dict[str, Any], bool]:
    """
    Build expected normalization output using actual normalize_audnex_book.

    This ensures golden test expectations match actual function behavior.

    Returns:
        Tuple of (expected_dict, was_swapped)
    """
    # Import the actual function
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from mamfast.utils.naming import normalize_audnex_book

    # Call the actual normalization function
    result = normalize_audnex_book(audnex_data)

    return {
        "display_title": result.display_title,
        "display_subtitle": result.display_subtitle,
        "series_name": result.series_name,
        "series_position": result.series_position,
        "arc_name": result.arc_name,
        "was_swapped": result.was_swapped,
    }, result.was_swapped


def build_sample(
    audnex_data: dict[str, Any], abs_item: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build a complete sample entry."""
    # Get expected output and actual swap status from real function
    expected, actual_was_swapped = build_expected_output(audnex_data, "")

    # Determine category from special patterns first
    category = categorize_sample(audnex_data)

    # Override based on actual normalization behavior
    if actual_was_swapped and category == "correct_mapping":
        category = "swapped_mapping"
    elif not actual_was_swapped and category == "swapped_mapping":
        category = "correct_mapping"

    sample = {
        "_category": category,
        "_description": f"{audnex_data.get('title', 'Unknown')}",
        "asin": audnex_data.get("asin"),
        "title": audnex_data.get("title"),
        "subtitle": audnex_data.get("subtitle"),
        "seriesPrimary": audnex_data.get("seriesPrimary"),
        "authors": [
            {"asin": a.get("asin"), "name": a.get("name")} for a in audnex_data.get("authors", [])
        ],
        "expected": expected,
    }

    return sample


def main() -> None:
    parser = argparse.ArgumentParser(description="Build golden test samples from ABS + Audnex")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of books (0=all)")
    parser.add_argument(
        "--output",
        type=str,
        default="tests/fixtures/golden_samples_generated.json",
        help="Output file path",
    )
    parser.add_argument(
        "--categories-only", action="store_true", help="Only show category distribution, don't save"
    )
    args = parser.parse_args()

    if not ABS_HOST or not ABS_API_KEY:
        print("✗ Missing AUDIOBOOKSHELF_HOST or AUDIOBOOKSHELF_API_KEY in .env")
        sys.exit(1)

    print(f"📚 Audiobookshelf: {ABS_HOST}")
    print(f"🔗 Audnex API: {AUDNEX_BASE_URL}")
    print()

    # Collect all samples by category
    samples_by_category: dict[str, list[dict[str, Any]]] = {
        "correct_mapping": [],
        "swapped_mapping": [],
        "series_suffix": [],
        "sorting_tag": [],
        "the_prefix": [],
        "standalone": [],
        "edge_cases": [],
    }

    with httpx.Client(http2=True) as client:
        # Step 1: Get all libraries
        print("📖 Fetching Audiobookshelf libraries...")
        libraries = fetch_abs_libraries(client)
        print(f"   Found {len(libraries)} libraries")

        # Step 2: Get all items from each library
        all_items = []
        for lib in libraries:
            lib_id = lib.get("id")
            # Skip invalid library IDs
            if not isinstance(lib_id, str) or not lib_id:
                print(f"   ⚠ Skipping library with missing id: {lib.get('name', lib_id)}")
                continue
            lib_name = lib.get("name", "Unknown")
            print(f"   📁 {lib_name}...", end=" ", flush=True)
            items = fetch_abs_library_items(client, lib_id)
            print(f"{len(items)} items")
            all_items.extend(items)

        print(f"\n📚 Total items: {len(all_items)}")

        # Step 3: Extract ASINs
        asins: list[tuple[str, dict[str, Any]]] = []
        for item in all_items:
            asin = extract_asin(item)
            if asin:
                asins.append((asin, item))

        print(f"🔑 Items with ASIN: {len(asins)}")

        if args.limit > 0:
            asins = asins[: args.limit]
            print(f"⚡ Limited to {args.limit} items")

        print()

        # Step 4: Fetch Audnex data for each ASIN
        print("🌐 Fetching Audnex metadata...")
        processed = 0
        errors = 0

        for asin, abs_item in asins:
            processed += 1
            print(f"\r   [{processed}/{len(asins)}] {asin}...", end=" ", flush=True)

            audnex_data = fetch_audnex_book(client, asin)
            if not audnex_data:
                errors += 1
                continue

            sample = build_sample(audnex_data, abs_item)
            category = sample.pop("_category")
            samples_by_category[category].append(sample)

            # Rate limiting
            time.sleep(AUDNEX_DELAY)

        print(f"\n\n✓ Processed {processed} items ({errors} errors)")

    # Print category distribution
    print("\n📊 Category Distribution:")
    total = 0
    for category, samples in samples_by_category.items():
        count = len(samples)
        total += count
        if count > 0:
            print(f"   {category}: {count}")
    print("   ─────────────")
    print(f"   Total: {total}")

    if args.categories_only:
        print("\n⚡ Categories-only mode, not saving.")
        return

    # Build output structure
    output: dict[str, Any] = {
        "_comment": "Golden test samples generated from Audiobookshelf + Audnex API",
        "_generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "_source": f"Audiobookshelf: {ABS_HOST}",
        "_total_samples": total,
    }

    # Only include non-empty categories
    for category, samples in samples_by_category.items():
        if samples:
            output[category] = samples

    # Save to file
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n💾 Saved to: {output_path}")
    print(f"   File size: {output_path.stat().st_size / 1024:.1f} KB")

    # Show interesting samples
    interesting_categories = ["series_suffix", "sorting_tag", "the_prefix", "swapped_mapping"]
    for cat in interesting_categories:
        if samples_by_category[cat]:
            print(f"\n🔍 Sample {cat}:")
            sample = samples_by_category[cat][0]
            print(f"   ASIN: {sample['asin']}")
            print(f"   Title: {sample['title']}")
            print(f"   Series: {sample.get('seriesPrimary', {}).get('name', 'N/A')}")
            print(f"   Expected: {sample['expected'].get('series_name', 'N/A')}")


if __name__ == "__main__":
    main()
