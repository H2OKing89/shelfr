#!/usr/bin/env python3
"""Fetch and sync API documentation from external sources.

Automatically pulls the latest API docs from:
  - Audiobookshelf: GitHub API docs repository
  - Audnex: Audnex API specification

Uses ETags and content hashing to check for updates before downloading.
Beautiful terminal output with rich + typer.

Usage:
    python scripts/dev_tools/fetch_api_docs.py
    python scripts/dev_tools/fetch_api_docs.py --force
    python scripts/dev_tools/fetch_api_docs.py --abs-only
    python scripts/dev_tools/fetch_api_docs.py --audnex-only
    python scripts/dev_tools/fetch_api_docs.py -v  # verbose mode
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer
from rich import box
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table
from rich.text import Text
from rich.traceback import install as install_rich_traceback

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Configuration
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DOCS_DIR = Path(__file__).parent.parent.parent / "docs"
ABS_DOCS_DIR = DOCS_DIR / "audiobookshelf" / "api"
AUDNEX_DOCS_DIR = DOCS_DIR / "audnex" / "api"
METADATA_FILE = DOCS_DIR / ".api_docs_metadata.json"

# API Sources
ABS_API_DOCS_URL = (
    "https://raw.githubusercontent.com/audiobookshelf/audiobookshelf-api-docs/main/source/includes"
)
AUDNEX_API_REPO_URL = "https://raw.githubusercontent.com/laxamentumtech/audnexus/master"

# Audnex endpoints
AUDNEX_ENDPOINTS = [
    (
        "AUDNEX_README.md",
        "https://raw.githubusercontent.com/laxamentumtech/audnexus/main/README.md",
    ),
    (
        "AUDNEXUS_SPEC.yaml",
        "https://raw.githubusercontent.com/laxamentumtech/audnexus/refs/heads/main/docs/spec/audnexus.yaml",
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

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Rich Console & Logging Setup
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

console = Console()
err_console = Console(stderr=True)

# Global state for verbose mode
_verbose: bool = False


def setup_logging(verbose: bool) -> None:
    """Configure logging with rich handler."""
    global _verbose
    _verbose = verbose

    level = logging.DEBUG if verbose else logging.WARNING

    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(
                console=err_console,
                rich_tracebacks=True,
                tracebacks_show_locals=verbose,
                show_time=verbose,
                show_path=verbose,
            )
        ],
    )


def setup_tracebacks(verbose: bool) -> None:
    """Install rich tracebacks with appropriate detail level."""
    install_rich_traceback(
        console=err_console,
        show_locals=verbose,
        width=console.width,
        extra_lines=3 if verbose else 1,
        theme="monokai",
        word_wrap=True,
        suppress=[httpx, typer],  # Suppress library frames unless verbose
    )


logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Enums & Types
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class FetchStatus(str, Enum):
    """Status of a fetch operation."""

    DOWNLOADED = "downloaded"
    UNCHANGED = "unchanged"
    NOT_FOUND = "not_found"
    ERROR = "error"


class FetchResult:
    """Result of fetching a single file."""

    __slots__ = ("source", "filename", "status", "details", "size")

    def __init__(
        self,
        source: str,
        filename: str,
        status: FetchStatus,
        details: str = "",
        size: int | None = None,
    ) -> None:
        self.source = source
        self.filename = filename
        self.status = status
        self.details = details
        self.size = size

    @property
    def icon(self) -> str:
        """Get status icon."""
        return {
            FetchStatus.DOWNLOADED: "[green]✓[/green]",
            FetchStatus.UNCHANGED: "[dim]○[/dim]",
            FetchStatus.NOT_FOUND: "[red]✗[/red]",
            FetchStatus.ERROR: "[yellow]⚠[/yellow]",
        }[self.status]

    @property
    def status_text(self) -> str:
        """Get styled status text."""
        return {
            FetchStatus.DOWNLOADED: "[green bold]Downloaded[/green bold]",
            FetchStatus.UNCHANGED: "[dim]Unchanged[/dim]",
            FetchStatus.NOT_FOUND: "[red]Not Found[/red]",
            FetchStatus.ERROR: "[yellow]Error[/yellow]",
        }[self.status]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Metadata Management
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def load_metadata() -> dict[str, Any]:
    """Load metadata about previously fetched docs."""
    if METADATA_FILE.exists():
        try:
            with open(METADATA_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load metadata: {e}")
    return {"abs": {}, "audnex": {}, "last_updated": None}


def save_metadata(metadata: dict[str, Any]) -> None:
    """Save metadata about fetched docs."""
    metadata["last_updated"] = datetime.now().isoformat()
    METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, sort_keys=True)
    logger.debug(f"Saved metadata to {METADATA_FILE}")


def get_file_hash(content: str) -> str:
    """Calculate SHA256 hash of content."""
    return hashlib.sha256(content.encode()).hexdigest()[:16]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# UI Components
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def print_banner() -> None:
    """Print the application banner."""
    banner = Text()
    banner.append("╭─────────────────────────────────────────╮\n", style="cyan")
    banner.append("│", style="cyan")
    banner.append("     📚 ", style="")
    banner.append("API Docs Fetcher", style="bold magenta")
    banner.append("     📚     ", style="")
    banner.append("│\n", style="cyan")
    banner.append("│", style="cyan")
    banner.append("   Audiobookshelf • Audnex   ", style="dim")
    banner.append("          │\n", style="cyan")
    banner.append("╰─────────────────────────────────────────╯", style="cyan")
    console.print(banner)
    console.print()


def print_section_header(title: str, icon: str, style: str = "cyan") -> None:
    """Print a styled section header."""
    console.print()
    console.rule(f"[{style} bold]{icon} {title}[/{style} bold]", style=style)
    console.print()


def create_results_table(results: list[FetchResult], title: str) -> Table:
    """Create a beautiful results table."""
    table = Table(
        title=f"[bold]{title}[/bold]",
        box=box.ROUNDED,
        header_style="bold cyan",
        border_style="dim cyan",
        title_style="bold magenta",
        show_lines=False,
        padding=(0, 1),
    )

    table.add_column("", width=3, justify="center")  # Icon
    table.add_column("File", style="white", no_wrap=True)
    table.add_column("Status", justify="center")
    table.add_column("Details", style="dim", max_width=40)

    for result in results:
        size_str = f"{result.size:,} bytes" if result.size else ""
        details = result.details or size_str

        table.add_row(
            result.icon,
            f"[cyan]{result.filename}[/cyan]",
            result.status_text,
            details[:40] if details else "",
        )

    return table


def print_summary(results: list[FetchResult]) -> None:
    """Print a summary panel."""
    downloaded = sum(1 for r in results if r.status == FetchStatus.DOWNLOADED)
    unchanged = sum(1 for r in results if r.status == FetchStatus.UNCHANGED)
    failed = sum(1 for r in results if r.status in (FetchStatus.NOT_FOUND, FetchStatus.ERROR))
    total_size = sum(r.size or 0 for r in results if r.status == FetchStatus.DOWNLOADED)

    # Build summary grid
    summary = Table.grid(padding=(0, 2))
    summary.add_column(justify="right", style="bold")
    summary.add_column(justify="left")

    summary.add_row("[green]✓ Downloaded[/green]", f"[green]{downloaded}[/green]")
    summary.add_row("[dim]○ Unchanged[/dim]", f"[dim]{unchanged}[/dim]")
    if failed > 0:
        summary.add_row("[red]✗ Failed[/red]", f"[red]{failed}[/red]")
    if total_size > 0:
        summary.add_row("[cyan]↓ Total Size[/cyan]", f"[cyan]{total_size:,} bytes[/cyan]")

    console.print()
    console.print(
        Panel(
            summary,
            title="[bold cyan]Summary[/bold cyan]",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 4),
        )
    )


def print_footer() -> None:
    """Print the footer with output locations."""
    footer = Text()
    footer.append("📂 ", style="")
    footer.append("Docs: ", style="dim")
    footer.append(str(DOCS_DIR), style="cyan")
    footer.append("\n📋 ", style="")
    footer.append("Meta: ", style="dim")
    footer.append(str(METADATA_FILE), style="cyan")

    console.print()
    console.print(
        Panel(
            footer,
            border_style="dim magenta",
            box=box.ROUNDED,
            padding=(0, 2),
        )
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Fetch Operations
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def fetch_single_file(
    client: httpx.AsyncClient,
    url: str,
    filename: str,
    target_dir: Path,
    metadata_section: dict[str, Any],
    source_name: str,
    force: bool,
) -> FetchResult:
    """Fetch a single file and return the result."""
    try:
        # Check if reachable
        logger.debug(f"HEAD {url}")
        head_resp = await client.head(url, follow_redirects=True, timeout=10.0)

        if head_resp.status_code != 200:
            logger.debug(f"Not found: {url} -> {head_resp.status_code}")
            return FetchResult(
                source_name,
                filename,
                FetchStatus.NOT_FOUND,
                f"HTTP {head_resp.status_code}",
            )

        # Fetch content
        logger.debug(f"GET {url}")
        resp = await client.get(url, follow_redirects=True, timeout=30.0)
        resp.raise_for_status()
        content = resp.text

        # Calculate hash
        content_hash = get_file_hash(content)
        old_hash = metadata_section.get(filename, {}).get("hash")

        # Check if changed
        if not force and old_hash == content_hash:
            logger.debug(f"Unchanged: {filename}")
            return FetchResult(source_name, filename, FetchStatus.UNCHANGED)

        # Pretty-print JSON if applicable
        if filename.endswith(".json"):
            try:
                parsed = json.loads(content)
                content = json.dumps(parsed, indent=2)
            except json.JSONDecodeError:
                pass

        # Save file
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / filename
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        # Update metadata
        new_etag = head_resp.headers.get("etag", "").strip('"')
        metadata_section[filename] = {
            "hash": content_hash,
            "etag": new_etag,
            "size": len(content),
            "url": url,
            "fetched_at": datetime.now().isoformat(),
        }

        logger.debug(f"Downloaded: {filename} ({len(content)} bytes)")
        return FetchResult(
            source_name,
            filename,
            FetchStatus.DOWNLOADED,
            size=len(content),
        )

    except httpx.RequestError as e:
        logger.warning(f"Request error for {filename}: {e}")
        return FetchResult(
            source_name,
            filename,
            FetchStatus.ERROR,
            str(e)[:50],
        )
    except OSError as e:
        logger.error(f"File error for {filename}: {e}")
        return FetchResult(
            source_name,
            filename,
            FetchStatus.ERROR,
            f"IO: {e}",
        )


async def fetch_abs_docs(
    client: httpx.AsyncClient,
    metadata: dict[str, Any],
    force: bool,
) -> list[FetchResult]:
    """Fetch Audiobookshelf API documentation."""
    print_section_header("Audiobookshelf API Docs", "📚", "cyan")

    results: list[FetchResult] = []

    with Progress(
        SpinnerColumn("dots", style="cyan"),
        TextColumn("[cyan]{task.description}[/cyan]"),
        BarColumn(bar_width=30, style="cyan", complete_style="green"),
        TaskProgressColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("Fetching...", total=len(ABS_API_FILES))

        for filename in ABS_API_FILES:
            url = f"{ABS_API_DOCS_URL}/{filename}"
            result = await fetch_single_file(
                client=client,
                url=url,
                filename=filename,
                target_dir=ABS_DOCS_DIR,
                metadata_section=metadata.setdefault("abs", {}),
                source_name="ABS",
                force=force,
            )
            results.append(result)
            progress.advance(task)

    # Show results table
    console.print()
    console.print(create_results_table(results, "Audiobookshelf Files"))

    return results


async def fetch_audnex_docs(
    client: httpx.AsyncClient,
    metadata: dict[str, Any],
    force: bool,
) -> list[FetchResult]:
    """Fetch Audnex API documentation."""
    print_section_header("Audnex API Docs", "🌐", "magenta")

    results: list[FetchResult] = []

    with Progress(
        SpinnerColumn("dots", style="magenta"),
        TextColumn("[magenta]{task.description}[/magenta]"),
        BarColumn(bar_width=30, style="magenta", complete_style="green"),
        TaskProgressColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("Fetching...", total=len(AUDNEX_ENDPOINTS))

        for filename, url in AUDNEX_ENDPOINTS:
            result = await fetch_single_file(
                client=client,
                url=url,
                filename=filename,
                target_dir=AUDNEX_DOCS_DIR,
                metadata_section=metadata.setdefault("audnex", {}),
                source_name="Audnex",
                force=force,
            )
            results.append(result)
            progress.advance(task)

    # Show results table
    console.print()
    console.print(create_results_table(results, "Audnex Files"))

    return results


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLI Application
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

app = typer.Typer(
    name="fetch-api-docs",
    help="Fetch and sync API documentation from Audiobookshelf and Audnex.",
    add_completion=False,
    rich_markup_mode="rich",
    no_args_is_help=False,
    pretty_exceptions_enable=True,
    pretty_exceptions_show_locals=False,
)


async def run_fetch(
    force: bool,
    abs_only: bool,
    audnex_only: bool,
) -> int:
    """Execute the fetch operations."""
    print_banner()

    metadata = load_metadata()
    all_results: list[FetchResult] = []

    # Configure HTTP client
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
            abs_results = await fetch_abs_docs(client, metadata, force)
            all_results.extend(abs_results)

        # Fetch Audnex docs
        if not abs_only:
            audnex_results = await fetch_audnex_docs(client, metadata, force)
            all_results.extend(audnex_results)

    # Save metadata
    save_metadata(metadata)

    # Print summary
    print_summary(all_results)
    print_footer()

    # Return exit code
    failed = sum(1 for r in all_results if r.status in (FetchStatus.NOT_FOUND, FetchStatus.ERROR))
    return 1 if failed > 0 else 0


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Enable verbose output with detailed logging and tracebacks.",
            is_eager=True,
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Force re-fetch all docs even if unchanged.",
        ),
    ] = False,
    abs_only: Annotated[
        bool,
        typer.Option(
            "--abs-only",
            help="Only fetch Audiobookshelf API docs.",
        ),
    ] = False,
    audnex_only: Annotated[
        bool,
        typer.Option(
            "--audnex-only",
            help="Only fetch Audnex API docs.",
        ),
    ] = False,
) -> None:
    """
    [bold cyan]Fetch API documentation from external sources.[/bold cyan]

    Pulls the latest API docs from Audiobookshelf and Audnex repositories.
    Uses content hashing to detect changes and skip unchanged files.

    [dim]Examples:[/dim]
      [green]$[/green] python fetch_api_docs.py           [dim]# Fetch with update checks[/dim]
      [green]$[/green] python fetch_api_docs.py --force   [dim]# Force re-fetch everything[/dim]
      [green]$[/green] python fetch_api_docs.py -v        [dim]# Verbose mode[/dim]
      [green]$[/green] python fetch_api_docs.py --abs-only [dim]# Only ABS docs[/dim]
    """
    # Skip if a subcommand is invoked
    if ctx.invoked_subcommand is not None:
        return

    # Setup logging and tracebacks based on verbose flag
    setup_logging(verbose)
    setup_tracebacks(verbose)

    if verbose:
        console.print("[dim]Verbose mode enabled[/dim]")

    # Validate options
    if abs_only and audnex_only:
        err_console.print("[red]Error:[/red] Cannot use --abs-only and --audnex-only together.")
        raise typer.Exit(1)

    # Run the async fetch
    try:
        exit_code = asyncio.run(run_fetch(force, abs_only, audnex_only))
        raise typer.Exit(exit_code)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user.[/yellow]")
        raise typer.Exit(130) from None


@app.command()
def status() -> None:
    """Show metadata about previously fetched docs."""
    metadata = load_metadata()

    if not metadata.get("last_updated"):
        console.print("[yellow]No docs have been fetched yet.[/yellow]")
        console.print("Run [cyan]fetch_api_docs.py[/cyan] to fetch docs.")
        raise typer.Exit(0)

    console.print()
    console.print(
        Panel(
            f"[bold]Last Updated:[/bold] [cyan]{metadata['last_updated']}[/cyan]",
            title="[bold magenta]API Docs Status[/bold magenta]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )

    # ABS files
    if metadata.get("abs"):
        table = Table(title="[bold cyan]Audiobookshelf[/bold cyan]", box=box.SIMPLE)
        table.add_column("File", style="white")
        table.add_column("Size", justify="right", style="cyan")
        table.add_column("Hash", style="dim")
        table.add_column("Fetched", style="dim")

        for filename, info in sorted(metadata["abs"].items()):
            table.add_row(
                filename,
                f"{info.get('size', 0):,}",
                info.get("hash", "")[:8],
                info.get("fetched_at", "")[:10],
            )

        console.print()
        console.print(table)

    # Audnex files
    if metadata.get("audnex"):
        table = Table(title="[bold magenta]Audnex[/bold magenta]", box=box.SIMPLE)
        table.add_column("File", style="white")
        table.add_column("Size", justify="right", style="cyan")
        table.add_column("Hash", style="dim")
        table.add_column("Fetched", style="dim")

        for filename, info in sorted(metadata["audnex"].items()):
            table.add_row(
                filename,
                f"{info.get('size', 0):,}",
                info.get("hash", "")[:8],
                info.get("fetched_at", "")[:10],
            )

        console.print()
        console.print(table)


@app.command()
def clean() -> None:
    """Remove all fetched docs and metadata."""
    from shutil import rmtree

    console.print()

    removed = []

    if ABS_DOCS_DIR.exists():
        rmtree(ABS_DOCS_DIR)
        removed.append(str(ABS_DOCS_DIR))
        console.print(f"[red]✗[/red] Removed [cyan]{ABS_DOCS_DIR}[/cyan]")

    if AUDNEX_DOCS_DIR.exists():
        rmtree(AUDNEX_DOCS_DIR)
        removed.append(str(AUDNEX_DOCS_DIR))
        console.print(f"[red]✗[/red] Removed [cyan]{AUDNEX_DOCS_DIR}[/cyan]")

    if METADATA_FILE.exists():
        METADATA_FILE.unlink()
        removed.append(str(METADATA_FILE))
        console.print(f"[red]✗[/red] Removed [cyan]{METADATA_FILE}[/cyan]")

    if removed:
        console.print()
        console.print(f"[green]Cleaned {len(removed)} items.[/green]")
    else:
        console.print("[yellow]Nothing to clean.[/yellow]")


if __name__ == "__main__":
    app()
