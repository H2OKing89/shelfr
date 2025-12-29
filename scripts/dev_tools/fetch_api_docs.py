#!/usr/bin/env python3
"""Fetch and sync API documentation from external sources.

Automatically pulls the latest API docs from:
  - Audiobookshelf: GitHub API docs repository
  - Audnex: Audnex API specification

Uses ETags and Last-Modified headers to check for updates before downloading.
Over-the-top beautiful terminal output with rich.

Usage:
    python scripts/dev_tools/fetch_api_docs.py
    python scripts/dev_tools/fetch_api_docs.py --force
    python scripts/dev_tools/fetch_api_docs.py --abs-only
    python scripts/dev_tools/fetch_api_docs.py --audnex-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table
from rich.text import Text

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

console = Console()

# Configuration
DOCS_DIR = Path(__file__).parent.parent.parent / "docs"
ABS_DOCS_DIR = DOCS_DIR / "audiobookshelf" / "api"
AUDNEX_DOCS_DIR = DOCS_DIR / "audnex" / "api"
METADATA_FILE = DOCS_DIR / ".api_docs_metadata.json"

# API Sources
ABS_API_DOCS_URL = (
    "https://raw.githubusercontent.com/audiobookshelf/audiobookshelf-api-docs/main/source/includes"
)
AUDNEX_API_REPO_URL = "https://raw.githubusercontent.com/laxamentumtech/audnexus/master"

# Try these Audnex endpoints in order
AUDNEX_ENDPOINTS = [
    (
        "AUDNEX_README.md",
        "https://raw.githubusercontent.com/laxamentumtech/audnexus/master/README.md",
    ),
    (
        "AUDNEX_API_DOCS.md",
        "https://raw.githubusercontent.com/laxamentumtech/audnexus/master/docs/api.md",
    ),
    (
        "AUDNEX_ARCHITECTURE.md",
        "https://raw.githubusercontent.com/laxamentumtech/audnexus/master/docs/architecture.md",
    ),
    (
        "AUDNEX_OPENAPI.json",
        "https://raw.githubusercontent.com/laxamentumtech/audnexus/master/openapi.json",
    ),
]

# ABS API doc files to fetch
ABS_API_FILES = [
    "_authors.md",
    "_backups.md",
    "_cache.md",
    "_collections.md",
    "_filesystem.md",
    "_filtering.md",
    "_items.md",
    "_libraries.md",
    "_me.md",
    "_metadata_providers.md",
    "_misc.md",
    "_notifications.md",
    "_playlists.md",
    "_podcasts.md",
    "_rss_feeds.md",
    "_schemas.md",
    "_search.md",
    "_series.md",
    "_server.md",
    "_sessions.md",
    "_socket.md",
    "_tools.md",
    "_users.md",
]


def load_metadata() -> dict[str, Any]:
    """Load metadata about previously fetched docs."""
    if METADATA_FILE.exists():
        with open(METADATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"abs": {}, "audnex": {}, "last_updated": None}


def save_metadata(metadata: dict[str, Any]) -> None:
    """Save metadata about fetched docs."""
    metadata["last_updated"] = datetime.now().isoformat()
    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)


def get_file_hash(content: str) -> str:
    """Calculate SHA256 hash of content."""
    return hashlib.sha256(content.encode()).hexdigest()


def create_styled_header(title: str, emoji: str) -> Panel:
    """Create a beautiful styled header panel."""
    text = Text(f"{emoji} {title}", style="bold magenta", justify="center")
    return Panel(
        text,
        border_style="cyan",
        padding=(1, 2),
        title="[bold cyan]API Docs Fetcher[/bold cyan]",
        title_align="center",
    )


def create_status_table(statuses: list[dict[str, Any]]) -> Table:
    """Create a beautiful status table."""
    table = Table(title="[bold]Fetch Results[/bold]", show_header=True, header_style="bold cyan")
    table.add_column("Source", style="magenta")
    table.add_column("File/Spec", style="green")
    table.add_column("Status", style="yellow")
    table.add_column("Details", style="dim")

    for status in statuses:
        table.add_row(
            status["source"],
            status["file"],
            status["status"],
            status.get("details", ""),
        )

    return table


async def fetch_abs_docs(client: httpx.AsyncClient, force: bool = False) -> list[dict[str, Any]]:
    """Fetch Audiobookshelf API documentation."""
    console.print(create_styled_header("Fetching Audiobookshelf API Docs", "📚"))

    metadata = load_metadata()
    statuses = []

    ABS_DOCS_DIR.mkdir(parents=True, exist_ok=True)

    with Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=30, style="cyan"),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Fetching ABS docs...", total=len(ABS_API_FILES))

        for filename in ABS_API_FILES:
            url = f"{ABS_API_DOCS_URL}/{filename}"

            try:
                # Check headers first
                head_resp = await client.head(url, follow_redirects=True, timeout=10.0)

                if head_resp.status_code != 200:
                    statuses.append(
                        {
                            "source": "Audiobookshelf",
                            "file": filename,
                            "status": "❌ Not Found",
                            "details": f"HTTP {head_resp.status_code}",
                        }
                    )
                    progress.advance(task)
                    continue

                # Get current hash from metadata
                old_hash = metadata["abs"].get(filename, {}).get("hash")
                new_etag = head_resp.headers.get("etag", "").strip('"')

                # Fetch full content
                resp = await client.get(url, follow_redirects=True, timeout=10.0)
                resp.raise_for_status()
                content = resp.text

                # Calculate hash
                content_hash = get_file_hash(content)

                # Check if updated
                if not force and old_hash == content_hash:
                    statuses.append(
                        {
                            "source": "Audiobookshelf",
                            "file": filename,
                            "status": "⏭️  Unchanged",
                            "details": "Skipped",
                        }
                    )
                    progress.advance(task)
                    continue

                # Save file
                file_path = ABS_DOCS_DIR / filename
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)

                # Update metadata
                metadata["abs"][filename] = {
                    "hash": content_hash,
                    "etag": new_etag,
                    "size": len(content),
                    "fetched_at": datetime.now().isoformat(),
                }

                statuses.append(
                    {
                        "source": "Audiobookshelf",
                        "file": filename,
                        "status": "✅ Downloaded",
                        "details": f"{len(content):,} bytes",
                    }
                )

            except httpx.RequestError as e:
                statuses.append(
                    {
                        "source": "Audiobookshelf",
                        "file": filename,
                        "status": "⚠️  Error",
                        "details": str(e)[:40],
                    }
                )

            progress.advance(task)

    save_metadata(metadata)
    return statuses


async def fetch_audnex_docs(client: httpx.AsyncClient, force: bool = False) -> list[dict[str, Any]]:
    """Fetch Audnex API documentation."""
    console.print(create_styled_header("Fetching Audnex API Docs", "🌐"))

    metadata = load_metadata()
    statuses = []

    AUDNEX_DOCS_DIR.mkdir(parents=True, exist_ok=True)

    with Progress(
        SpinnerColumn(style="magenta"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=30, style="magenta"),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Fetching Audnex docs...", total=len(AUDNEX_ENDPOINTS))

        for filename, url in AUDNEX_ENDPOINTS:
            try:
                # Check headers first
                head_resp = await client.head(url, follow_redirects=True, timeout=10.0)

                if head_resp.status_code != 200:
                    statuses.append(
                        {
                            "source": "Audnex",
                            "file": filename,
                            "status": "❌ Not Found",
                            "details": f"HTTP {head_resp.status_code}",
                        }
                    )
                    progress.advance(task)
                    continue

                # Fetch full content
                resp = await client.get(url, follow_redirects=True, timeout=10.0)
                resp.raise_for_status()
                content = resp.text

                # Calculate hash
                content_hash = get_file_hash(content)

                # Get old hash
                old_hash = metadata["audnex"].get(filename, {}).get("hash")

                # Check if updated
                if not force and old_hash == content_hash:
                    statuses.append(
                        {
                            "source": "Audnex",
                            "file": filename,
                            "status": "⏭️  Unchanged",
                            "details": "Skipped",
                        }
                    )
                    progress.advance(task)
                    continue

                # Save file
                file_path = AUDNEX_DOCS_DIR / filename

                # Pretty-print JSON if applicable
                if filename.endswith(".json"):
                    try:
                        parsed = json.loads(content)
                        content = json.dumps(parsed, indent=2)
                    except json.JSONDecodeError:
                        pass  # Keep original if not valid JSON

                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)

                # Update metadata
                metadata["audnex"][filename] = {
                    "hash": content_hash,
                    "size": len(content),
                    "url": url,
                    "fetched_at": datetime.now().isoformat(),
                }

                statuses.append(
                    {
                        "source": "Audnex",
                        "file": filename,
                        "status": "✅ Downloaded",
                        "details": f"{len(content):,} bytes",
                    }
                )

            except httpx.RequestError as e:
                statuses.append(
                    {
                        "source": "Audnex",
                        "file": filename,
                        "status": "⚠️  Error",
                        "details": str(e)[:40],
                    }
                )

            progress.advance(task)

    save_metadata(metadata)
    return statuses


async def main(
    force: bool = False,
    abs_only: bool = False,
    audnex_only: bool = False,
) -> int:
    """Main entry point."""
    # Beautiful startup
    console.print(
        Panel(
            Text(
                "✨ [bold cyan]API Documentation Fetcher[/bold cyan] ✨\n"
                "[dim]Pulling the latest docs from Audiobookshelf & Audnex[/dim]",
                justify="center",
            ),
            border_style="magenta",
            padding=(1, 2),
        )
    )
    console.print()

    all_statuses = []

    # Use HTTP/2 with SSL verification
    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    timeout = httpx.Timeout(30.0)

    async with httpx.AsyncClient(
        http2=True,
        verify=True,
        limits=limits,
        timeout=timeout,
    ) as client:
        # Fetch ABS docs
        if not audnex_only:
            try:
                abs_statuses = await fetch_abs_docs(client, force=force)
                all_statuses.extend(abs_statuses)
            except Exception as e:
                console.print(f"[red]Error fetching ABS docs: {e}[/red]")
                logger.exception("ABS fetch failed")
                return 1

        console.print()

        # Fetch Audnex docs
        if not abs_only:
            try:
                audnex_statuses = await fetch_audnex_docs(client, force=force)
                all_statuses.extend(audnex_statuses)
            except Exception as e:
                console.print(f"[red]Error fetching Audnex docs: {e}[/red]")
                logger.exception("Audnex fetch failed")
                return 1

    console.print()

    # Display results table
    table = create_status_table(all_statuses)
    console.print(table)
    console.print()

    # Count results
    successful = sum(1 for s in all_statuses if "✅" in s["status"])
    unchanged = sum(1 for s in all_statuses if "⏭️" in s["status"])
    failed = sum(1 for s in all_statuses if "❌" in s["status"] or "⚠️" in s["status"])

    # Summary panel
    summary_text = Text()
    summary_text.append(f"✅ Downloaded: {successful}\n", style="green bold")
    summary_text.append(f"⏭️  Unchanged: {unchanged}\n", style="yellow bold")
    summary_text.append(f"❌ Failed: {failed}", style="red bold")

    console.print(
        Panel(
            summary_text,
            title="[bold cyan]Summary[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        )
    )

    console.print()
    console.print(
        Panel(
            Text(
                f"📂 Docs saved to: [cyan]{DOCS_DIR}[/cyan]\n"
                f"📋 Metadata: [cyan]{METADATA_FILE}[/cyan]",
                style="dim",
                justify="center",
            ),
            border_style="magenta",
            padding=(1, 2),
        )
    )

    return 0 if failed == 0 else 1


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Fetch and sync API documentation from Audiobookshelf and Audnex",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/dev_tools/fetch_api_docs.py              # Fetch with update checks
    python scripts/dev_tools/fetch_api_docs.py --force      # Force re-fetch everything
    python scripts/dev_tools/fetch_api_docs.py --abs-only   # Only fetch ABS docs
    python scripts/dev_tools/fetch_api_docs.py --audnex-only # Only fetch Audnex docs
        """,
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Force fetch all docs even if unchanged (skip hash checks)",
    )
    parser.add_argument(
        "--abs-only",
        action="store_true",
        help="Only fetch Audiobookshelf API docs",
    )
    parser.add_argument(
        "--audnex-only",
        action="store_true",
        help="Only fetch Audnex API docs",
    )

    return parser.parse_args()


if __name__ == "__main__":
    import asyncio

    args = parse_args()
    exit_code = asyncio.run(
        main(
            force=args.force,
            abs_only=args.abs_only,
            audnex_only=args.audnex_only,
        )
    )
    sys.exit(exit_code)
