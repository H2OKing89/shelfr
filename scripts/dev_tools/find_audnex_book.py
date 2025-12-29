#!/usr/bin/env python3
"""Quick script: query Audnex book metadata for an ASIN across regions.

Usage:
  python scripts/find_audnex_book.py B0FDCW8SS7 --regions us,uk --seed-authors --update

This is intentionally small and dependency-light. Uses httpx and rich.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from typing import Any, cast

import httpx
from rich import box
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.traceback import install

install()
console = Console()

API_BASE = "https://api.audnex.us/books"
DEFAULT_REGIONS = ["au", "ca", "de", "es", "fr", "in", "it", "jp", "us", "uk"]


def query_region(
    asin: str,
    region: str,
    seed_authors: bool = False,
    update: bool = False,
    timeout: float = 10.0,
) -> dict[str, Any] | None:
    params = {"region": region}
    if seed_authors:
        params["seedAuthors"] = "1"
    if update:
        params["update"] = "1"

    url = f"{API_BASE}/{asin}"
    try:
        with httpx.Client(timeout=timeout, http2=True) as client:
            r = client.get(url, params=params)
        if r.status_code == 200:
            # r.json() returns Any; ensure we return a dict when possible
            payload = r.json()
            if isinstance(payload, dict):
                return cast(dict[str, Any], payload)
            # Unexpected non-dict JSON
            return {"_status_code": r.status_code, "_payload": str(payload)[:512]}
        # Return a small object with status for non-200 so caller can differentiate
        return {"_status_code": r.status_code, "_text": r.text[:512]}
    except httpx.HTTPError as exc:
        return {"_error": str(exc)}


def run(
    asin: str,
    regions: Iterable[str],
    seed_authors: bool,
    update: bool,
    timeout: float,
    json_out: bool,
) -> int:
    results: dict[str, dict[str, Any] | None] = {}
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=True) as progress:
        task = progress.add_task("Querying Audnex…", total=len(list(regions)))
        for region in regions:
            progress.update(task, description=f"Querying region: {region}")
            res = query_region(
                asin,
                region,
                seed_authors=seed_authors,
                update=update,
                timeout=timeout,
            )
            results[region] = res
            progress.advance(task)

    # Table summary
    table = Table(title=f"Audnex lookup for {asin}", box=box.SIMPLE)
    table.add_column("region", no_wrap=True)
    table.add_column("status", no_wrap=True)
    table.add_column("title/short", overflow="fold")
    table.add_column("authors", overflow="fold")

    found_any = False
    for region in regions:
        res = results.get(region)
        if res is None:
            status = "error"
            title = ""
            authors = ""
        elif isinstance(res, dict) and res.get("_status_code"):
            sc = res.get("_status_code")
            status = f"HTTP {sc}"
            title = str(res.get("_text", ""))[:60]
            authors = ""
        elif isinstance(res, dict) and res.get("_error"):
            status = "err"
            title = str(res.get("_error", ""))
            authors = ""
        else:
            status = "OK"
            # Try to extract title/authors from likely keys
            title_val: Any = res.get("title")
            if not title_val and isinstance(res.get("data"), dict):
                title_val = res["data"].get("title")
            title = str(title_val) if title_val else "(no title)"

            authors_list: list[str] = []
            if isinstance(res.get("authors"), list):
                authors_list = [
                    str(a.get("name")) for a in res.get("authors", []) if a and a.get("name")
                ]
            elif isinstance(res.get("data"), dict) and isinstance(res["data"].get("authors"), list):
                authors_list = [
                    str(a.get("name"))
                    for a in res["data"].get("authors", [])
                    if a and a.get("name")
                ]

            authors = ", ".join(authors_list) if authors_list else ""
            found_any = True

        table.add_row(region, status, str(title), authors)

    console.print(table)

    if json_out:
        console.print_json(data={"asin": asin, "results": results})

    # Return status code for scripting
    return 0 if found_any else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query Audnex book metadata across regions.")
    parser.add_argument("asin", help="ASIN of the book (e.g. B0XXXXXX)")
    parser.add_argument(
        "--regions",
        default=",".join(DEFAULT_REGIONS),
        help="Comma-separated regions or 'all' (default: all)",
    )
    parser.add_argument("--seed-authors", action="store_true", help="Request seeding of authors")
    parser.add_argument("--update", action="store_true", help="Ask server to update data upstream")
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout seconds")
    parser.add_argument(
        "--json",
        dest="json_out",
        action="store_true",
        help="Print JSON output after table",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    regions = [r.strip() for r in args.regions.split(",") if r.strip()]
    if "all" in regions:
        regions = DEFAULT_REGIONS
    raise SystemExit(
        run(
            args.asin,
            regions,
            args.seed_authors,
            args.update,
            args.timeout,
            args.json_out,
        )
    )
