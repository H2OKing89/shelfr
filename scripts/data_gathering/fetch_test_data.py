#!/usr/bin/env python3
"""Fetch Audiobookshelf + Audnex metadata for testing.

Pulls all books from ABS library, then fetches full Audnex metadata for each ASIN.
Saves results to samples/test_data/ for troubleshooting (gitignored).

Usage:
    python scripts/fetch_test_data.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from shelfr.console import console

# Schema version for tracking format changes
SCHEMA_VERSION = "1.0.0"

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


class TestDataFetcher:
    """Fetch ABS + Audnex data for testing."""

    def __init__(self, abs_url: str, abs_token: str, output_dir: Path):
        self.abs_url = abs_url.rstrip("/")
        self.abs_token = abs_token
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Audnex rate limiter: 10 requests per second
        self.audnex_semaphore = asyncio.Semaphore(10)
        self.audnex_delay = 0.1  # 100ms between requests

    async def fetch_abs_library(self) -> list[dict]:
        """Fetch all items from ABS library."""
        console.print("\n[bold cyan]📚 Fetching Audiobookshelf Library[/bold cyan]")

        async with httpx.AsyncClient(
            http2=True,
            verify=True,
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
        ) as client:
            # Get libraries
            resp = await client.get(
                f"{self.abs_url}/api/libraries",
                headers={"Authorization": f"Bearer {self.abs_token}"},
            )
            resp.raise_for_status()
            libraries = resp.json()["libraries"]

            # Find audiobook library
            book_libs = [lib for lib in libraries if lib["mediaType"] == "book"]
            if not book_libs:
                console.print("[red]No audiobook libraries found[/red]")
                return []

            lib = book_libs[0]
            console.print(f"[dim]Library: {lib['name']} ({lib['id']})[/dim]")

            # Fetch all items (limit=0 means all)
            resp = await client.get(
                f"{self.abs_url}/api/libraries/{lib['id']}/items",
                params={"limit": 0, "minified": 0},
                headers={"Authorization": f"Bearer {self.abs_token}"},
            )
            resp.raise_for_status()
            data = resp.json()

            items = data["results"]
            console.print(f"[green]✓[/green] Fetched {len(items)} items")

            return items

    def extract_abs_metadata(self, items: list[dict]) -> list[dict]:
        """Extract key fields from ABS items."""
        console.print("\n[bold cyan]📋 Extracting Metadata[/bold cyan]")

        extracted = []
        for item in items:
            metadata = item.get("media", {}).get("metadata", {})

            extracted.append(
                {
                    "abs_id": item["id"],
                    "title": metadata.get("title"),
                    "subtitle": metadata.get("subtitle"),
                    "authors": [metadata.get("authorName")] if metadata.get("authorName") else [],
                    "narrators": [metadata.get("narratorName")]
                    if metadata.get("narratorName")
                    else [],
                    "asin": metadata.get("asin"),
                    "isbn": metadata.get("isbn"),
                    "series": metadata.get("seriesName"),
                    "path": item.get("relPath"),
                }
            )

        # Count ASINs
        with_asin = sum(1 for e in extracted if e["asin"])
        console.print(f"[green]✓[/green] {len(extracted)} books ({with_asin} with ASIN)")

        return extracted

    async def fetch_audnex_metadata(self, client: httpx.AsyncClient, asin: str) -> dict | None:
        """Fetch full metadata from Audnex API using shared client."""
        async with self.audnex_semaphore:
            await asyncio.sleep(self.audnex_delay)  # Rate limit

            try:
                resp = await client.get(f"https://api.audnex.us/books/{asin}")
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    logger.debug(f"ASIN not found in Audnex: {asin}")
                    return None
                logger.warning(f"Audnex error for {asin}: {e}")
                return None
            except Exception as e:
                logger.warning(f"Failed to fetch Audnex for {asin}: {e}")
                return None

    async def fetch_all_audnex(self, abs_items: list[dict]) -> dict[str, dict]:
        """Fetch Audnex metadata for all ASINs using shared AsyncClient."""
        console.print("\n[bold cyan]🌐 Fetching Audnex Metadata[/bold cyan]")

        # Get unique ASINs
        asins = {item["asin"] for item in abs_items if item.get("asin")}
        console.print(f"[dim]Fetching {len(asins)} unique ASINs...[/dim]")

        # Create shared client for all requests
        async with httpx.AsyncClient(
            http2=True,
            verify=True,
            timeout=httpx.Timeout(10.0),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
        ) as client:
            # Fetch in parallel with rate limiting
            tasks = [self.fetch_audnex_metadata(client, asin) for asin in asins]
            results = await asyncio.gather(*tasks)

        # Build ASIN -> metadata map
        audnex_map = {}
        for asin, result in zip(asins, results, strict=True):
            if result:
                audnex_map[asin] = result

        console.print(f"[green]✓[/green] Fetched {len(audnex_map)}/{len(asins)} from Audnex")

        return audnex_map

    def _build_schema_header(
        self,
        data_type: str,
        record_count: int,
        source: str,
        description: str,
    ) -> dict:
        """Build standardized JSON schema header with metadata."""
        return {
            "_schema": {
                "version": SCHEMA_VERSION,
                "generated_at": datetime.now(UTC).isoformat(),
                "data_type": data_type,
                "record_count": record_count,
                "source": source,
                "description": description,
                "tool": "shelfr/fetch_test_data.py",
            }
        }

    async def run(self) -> None:
        """Main execution flow."""
        # 1. Fetch ABS library
        abs_items = await self.fetch_abs_library()
        if not abs_items:
            return

        # 2. Extract metadata
        extracted = self.extract_abs_metadata(abs_items)

        # 3. Save ABS data with schema header
        abs_file = self.output_dir / "abs_library.json"
        abs_data = self._build_schema_header(
            data_type="abs_library",
            record_count=len(extracted),
            source=f"{self.abs_url}/api/libraries",
            description="Audiobookshelf library items with extracted metadata fields",
        )
        abs_data["items"] = extracted

        with open(abs_file, "w", encoding="utf-8") as f:
            json.dump(abs_data, f, indent=2, ensure_ascii=False)
        console.print(f"\n[green]✓[/green] Saved ABS data: {abs_file}")

        # 4. Fetch Audnex metadata
        audnex_map = await self.fetch_all_audnex(extracted)

        # 5. Save Audnex data with schema header
        audnex_file = self.output_dir / "audnex_metadata.json"
        audnex_data = self._build_schema_header(
            data_type="audnex_metadata",
            record_count=len(audnex_map),
            source="https://api.audnex.us/books",
            description="Audnex API responses mapped by ASIN",
        )
        audnex_data["metadata"] = audnex_map

        with open(audnex_file, "w", encoding="utf-8") as f:
            json.dump(audnex_data, f, indent=2, ensure_ascii=False)
        console.print(f"[green]✓[/green] Saved Audnex data: {audnex_file}")

        # 6. Create combined view (for easy lookup)
        combined = []
        for item in extracted:
            asin = item.get("asin")
            combined_item = {
                "abs": item,
                "audnex": audnex_map.get(asin) if asin else None,
            }
            combined.append(combined_item)

        combined_file = self.output_dir / "combined_metadata.json"
        combined_data = self._build_schema_header(
            data_type="combined_metadata",
            record_count=len(combined),
            source="Audiobookshelf + Audnex",
            description="Combined ABS and Audnex metadata for each book",
        )
        combined_data["items"] = combined

        with open(combined_file, "w", encoding="utf-8") as f:
            json.dump(combined_data, f, indent=2, ensure_ascii=False)
        console.print(f"[green]✓[/green] Saved combined data: {combined_file}")

        # Summary
        console.print(f"\n[bold green]Done![/bold green] Test data saved to: {self.output_dir}")
        console.print(f"  • ABS items: {len(extracted)}")
        console.print(f"  • Audnex metadata: {len(audnex_map)}")


async def main() -> int:
    """Main entry point."""
    # Load .env
    load_dotenv(Path(__file__).parent.parent / "config" / ".env")

    import os

    abs_url = os.getenv("AUDIOBOOKSHELF_HOST")
    abs_token = os.getenv("AUDIOBOOKSHELF_API_KEY")

    if not abs_url or not abs_token:
        console.print(
            "[red]Missing config:[/red] Set AUDIOBOOKSHELF_HOST and "
            "AUDIOBOOKSHELF_API_KEY in config/.env"
        )
        return 1

    # Output directory (gitignored)
    output_dir = Path(__file__).parent.parent.parent / "samples" / "test_data"

    fetcher = TestDataFetcher(abs_url, abs_token, output_dir)

    try:
        await fetcher.run()
        return 0
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        return 130
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        logger.exception("Fetch failed")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
