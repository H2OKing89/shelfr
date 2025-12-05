#!/usr/bin/env python3
"""
Fetch complete audiobook library from Audiobookshelf for naming analysis.

Exports to samples/audiobookshelf_library.json with fields:
- Title, Subtitle, SeriesName, SeriesSequence
- Authors, Narrators
- Genres, Publisher, ASIN, ISBN
- Path (folder structure)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, cast

import httpx
from dotenv import load_dotenv

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def load_config() -> tuple[str, str]:
    """Load ABS config from .env file."""
    env_path = Path(__file__).parent.parent / "config" / ".env"
    load_dotenv(env_path)

    host = os.getenv("AUDIOBOOKSHELF_HOST", "").rstrip("/")
    api_key = os.getenv("AUDIOBOOKSHELF_API_KEY", "")

    if not host or not api_key:
        print("Error: AUDIOBOOKSHELF_HOST and AUDIOBOOKSHELF_API_KEY must be set in config/.env")
        sys.exit(1)

    return host, api_key


def get_libraries(host: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    """Get all libraries from ABS."""
    response = httpx.get(f"{host}/api/libraries", headers=headers, timeout=30)
    response.raise_for_status()
    data = response.json()
    libs = data.get("libraries", [])
    return cast(list[dict[str, Any]], libs)


def get_library_items(
    host: str,
    headers: dict[str, str],
    library_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Fetch all items from a library with pagination."""
    all_items = []
    page = 0

    while True:
        print(f"  Fetching page {page} (items {page * limit}-{(page + 1) * limit})...")

        response = httpx.get(
            f"{host}/api/libraries/{library_id}/items",
            headers=headers,
            params={"limit": limit, "page": page, "sort": "media.metadata.title"},
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()

        results = data.get("results", [])
        all_items.extend(cast(list[dict[str, Any]], results))

        total = data.get("total", 0)
        print(f"    Got {len(results)} items (total: {len(all_items)}/{total})")

        if len(all_items) >= total or len(results) == 0:
            break

        page += 1

    return all_items


def extract_book_data(item: dict[str, Any]) -> dict[str, Any] | None:
    """Extract relevant fields from a library item."""
    if item.get("mediaType") != "book":
        return None

    media = item.get("media", {})
    metadata = media.get("metadata", {})

    # Extract series info - check both 'series' array and 'seriesName' string
    series_list = metadata.get("series", [])
    series_name = metadata.get("seriesName")  # Often populated in list response
    series_sequence = None

    if series_list:
        first_series = series_list[0] if isinstance(series_list, list) else series_list
        if isinstance(first_series, dict):
            series_name = first_series.get("name") or series_name
            series_sequence = first_series.get("sequence")
        elif isinstance(first_series, str):
            series_name = first_series

    # Handle authors - can be array of objects or string
    authors = metadata.get("authors", [])
    if isinstance(authors, list) and authors and isinstance(authors[0], dict):
        author_names = [a.get("name", "") for a in authors]
    else:
        author_names = [metadata.get("authorName", "")] if metadata.get("authorName") else []

    # Handle narrators - can be array or string
    narrators = metadata.get("narrators", [])
    if isinstance(narrators, str):
        narrators = [narrators]
    narrator_name = metadata.get("narratorName", "")
    if narrator_name and not narrators:
        narrators = [narrator_name]

    return {
        "id": item.get("id"),
        "title": metadata.get("title"),
        "subtitle": metadata.get("subtitle"),
        "series": series_name if series_name else None,  # Normalize empty string to None
        "seriesSequence": series_sequence,
        "authors": author_names,
        "narrators": narrators,
        "genres": metadata.get("genres", []),
        "publisher": metadata.get("publisher"),
        "publishedYear": metadata.get("publishedYear"),
        "asin": metadata.get("asin"),
        "isbn": metadata.get("isbn"),
        "language": metadata.get("language"),
        "path": item.get("path"),
        "relPath": item.get("relPath"),
        "duration": media.get("duration"),
        "size": media.get("size"),
    }


def main() -> None:
    """Main entry point."""
    print("=" * 60)
    print("Audiobookshelf Library Fetcher")
    print("=" * 60)

    host, api_key = load_config()
    headers = {"Authorization": f"Bearer {api_key}"}

    print(f"\nConnecting to: {host}")

    # Get libraries
    print("\nFetching libraries...")
    libraries = get_libraries(host, headers)

    # Filter to book libraries only
    book_libraries = [lib for lib in libraries if lib.get("mediaType") == "book"]
    print(f"Found {len(book_libraries)} book libraries:")
    for lib in book_libraries:
        print(f"  - {lib.get('name')} (id: {lib.get('id')})")

    # Fetch all items from all book libraries
    all_books: list[dict[str, Any]] = []
    for lib in book_libraries:
        lib_id = lib.get("id")
        lib_name = lib.get("name")
        print(f"\nFetching items from '{lib_name}'...")

        # Ensure library id is a string
        if not isinstance(lib_id, str) or not lib_id:
            print(f"  ⚠ Skipping library with invalid id: {lib_id}")
            continue

        items = get_library_items(host, headers, lib_id)

        books_raw = [extract_book_data(item) for item in items]
        # Filter out None and cast to concrete dicts for static typing
        books: list[dict[str, Any]] = [b for b in books_raw if isinstance(b, dict)]

        print(f"  Extracted {len(books)} books")
        all_books.extend(books)

    print(f"\nTotal books: {len(all_books)}")

    # Save to samples directory
    samples_dir = Path(__file__).parent.parent / "samples"
    samples_dir.mkdir(exist_ok=True)

    output_path = samples_dir / "audiobookshelf_library.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "_comment": "Audiobookshelf library export for naming analysis",
                "_source": host,
                "_count": len(all_books),
                "books": all_books,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    print(f"\nSaved to: {output_path}")
    print(f"File size: {output_path.stat().st_size / 1024:.1f} KB")

    # Print some stats
    print("\n" + "=" * 60)
    print("Library Statistics")
    print("=" * 60)

    with_subtitle = sum(1 for b in all_books if bool(b.get("subtitle")))
    with_series = sum(1 for b in all_books if bool(b.get("series")))
    with_asin = sum(1 for b in all_books if bool(b.get("asin")))

    print(
        f"  Books with subtitle:  {with_subtitle:4d} ({with_subtitle / len(all_books) * 100:.1f}%)"
    )
    print(f"  Books with series:    {with_series:4d} ({with_series / len(all_books) * 100:.1f}%)")
    print(f"  Books with ASIN:      {with_asin:4d} ({with_asin / len(all_books) * 100:.1f}%)")

    # Sample some non-ASCII authors
    non_ascii_authors = set()
    for book in all_books:
        for author in book.get("authors", []):
            if author and any(ord(c) > 127 for c in author):
                non_ascii_authors.add(author)

    if non_ascii_authors:
        print(f"\nNon-ASCII authors found ({len(non_ascii_authors)}):")
        for author in sorted(non_ascii_authors)[:20]:
            print(f"    {author}")
        if len(non_ascii_authors) > 20:
            print(f"    ... and {len(non_ascii_authors) - 20} more")


if __name__ == "__main__":
    main()
