#!/usr/bin/env python3
"""Fetch and sync API documentation from external sources.

Automatically pulls the latest API docs from:
  - Audiobookshelf: GitHub API docs repository
  - Audnex: Audnex API specification
  - Hardcover: Hardcover GraphQL API docs

Uses GitHub API for dynamic file discovery (no hardcoded file lists).
Uses ETags and content hashing to check for updates before downloading.
Beautiful terminal output with rich + typer.

Usage:
    python scripts/dev_tools/fetch_api_docs.py
    python scripts/dev_tools/fetch_api_docs.py --force
    python scripts/dev_tools/fetch_api_docs.py --source abs
    python scripts/dev_tools/fetch_api_docs.py --source hardcover
    python scripts/dev_tools/fetch_api_docs.py -v  # verbose mode
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sys
from dataclasses import dataclass
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
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from rich.text import Text
from rich.traceback import install as install_rich_traceback

# Add mamfast to path for retry utilities
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
from mamfast.utils.retry import NETWORK_EXCEPTIONS, retry_with_backoff

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Configuration
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DOCS_DIR = Path(__file__).parent.parent.parent / "docs"
METADATA_FILE = DOCS_DIR / ".api_docs_metadata.json"

# GitHub API base
GITHUB_API_BASE = "https://api.github.com"
GITHUB_RAW_BASE = "https://raw.githubusercontent.com"


@dataclass(frozen=True)
class GitHubSource:
    """Configuration for a GitHub-based documentation source."""

    name: str
    short_name: str
    owner: str
    repo: str
    branch: str
    source_path: str  # Path in repo to fetch from
    target_subdir: str  # Subdirectory under docs/reference/
    icon: str
    style: str
    recursive: bool = True  # Whether to recursively fetch subdirectories
    file_extensions: tuple[str, ...] = (".md", ".mdx", ".yaml", ".yml", ".json")


# Source configurations - dynamic discovery via GitHub API
SOURCES: dict[str, GitHubSource] = {
    "abs": GitHubSource(
        name="Audiobookshelf",
        short_name="ABS",
        owner="audiobookshelf",
        repo="audiobookshelf-api-docs",
        branch="main",
        source_path="source/includes",
        target_subdir="audiobookshelf/api",
        icon="📚",
        style="cyan",
        recursive=False,  # Flat directory
    ),
    "audnex": GitHubSource(
        name="Audnex",
        short_name="Audnex",
        owner="laxamentumtech",
        repo="audnexus",
        branch="main",
        source_path="",  # Special handling - specific files only
        target_subdir="audnex/api",
        icon="🌐",
        style="magenta",
        recursive=False,
    ),
    "hardcover": GitHubSource(
        name="Hardcover",
        short_name="HC",
        owner="hardcoverapp",
        repo="hardcover-docs",
        branch="main",
        source_path="src/content/docs/api",
        target_subdir="hardcover/api",
        icon="📖",
        style="yellow",
        recursive=True,  # Has nested GraphQL/Schemas, guides/
    ),
}

# Audnex has specific files (not a directory to scan)
AUDNEX_SPECIFIC_FILES = [
    ("AUDNEX_README.md", "main/README.md"),
    ("AUDNEXUS_SPEC.yaml", "refs/heads/main/docs/spec/audnexus.yaml"),
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
        force=True,
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
        suppress=[httpx, typer],
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


@dataclass
class FetchResult:
    """Result of fetching a single file."""

    source: str
    filename: str
    status: FetchStatus
    details: str = ""
    size: int | None = None

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


@dataclass
class FileInfo:
    """Information about a file to fetch."""

    name: str
    path: str  # Relative path from source root
    download_url: str
    size: int


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
    # Use source keys to match what gets written during fetch
    return {key: {} for key in SOURCES} | {"last_updated": None}


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
# GitHub API Operations
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@retry_with_backoff(max_attempts=3, base_delay=1.0, exceptions=NETWORK_EXCEPTIONS)
async def list_github_directory(
    client: httpx.AsyncClient,
    source: GitHubSource,
    path: str = "",
) -> list[FileInfo]:
    """List files in a GitHub repository directory using the API.

    Args:
        client: HTTP client
        source: GitHub source configuration
        path: Subdirectory path (relative to source.source_path)

    Returns:
        List of FileInfo objects for files found
    """
    full_path = f"{source.source_path}/{path}".strip("/") if path else source.source_path
    api_url = f"{GITHUB_API_BASE}/repos/{source.owner}/{source.repo}/contents/{full_path}"

    logger.debug(f"Listing directory: {api_url}")

    try:
        resp = await client.get(
            api_url,
            params={"ref": source.branch},
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=15.0,
        )

        if resp.status_code == 404:
            logger.warning(f"Directory not found: {full_path}")
            return []

        resp.raise_for_status()
        contents = resp.json()

        if not isinstance(contents, list):
            # Single file, not a directory
            return []

        files: list[FileInfo] = []

        for item in contents:
            item_type = item.get("type")
            item_name = item.get("name", "")
            item_path = item.get("path", "")

            if item_type == "file":
                # Check if file has valid extension
                if any(item_name.endswith(ext) for ext in source.file_extensions):
                    # Calculate relative path from source_path
                    rel_path = item_path
                    if source.source_path and item_path.startswith(source.source_path):
                        rel_path = item_path[len(source.source_path) :].lstrip("/")

                    files.append(
                        FileInfo(
                            name=item_name,
                            path=rel_path,
                            download_url=item.get("download_url", ""),
                            size=item.get("size", 0),
                        )
                    )

            elif item_type == "dir" and source.recursive:
                # Recursively list subdirectory
                subpath = f"{path}/{item_name}".lstrip("/") if path else item_name
                subfiles = await list_github_directory(client, source, subpath)
                files.extend(subfiles)

        return files

    except httpx.RequestError as e:
        logger.error(f"Failed to list directory {full_path}: {e}")
        return []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# UI Components
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def print_banner() -> None:
    """Print the application banner."""
    title = Text()
    title.append("📚 ", style="")
    title.append("API Docs Fetcher", style="bold magenta")
    title.append(" 📚", style="")

    subtitle = Text("Audiobookshelf • Audnex • Hardcover", style="dim")

    banner_content = Text()
    banner_content.append("\n")
    banner_content.append(title)
    banner_content.append("\n")
    banner_content.append(subtitle)
    banner_content.append("\n")

    console.print(
        Panel(
            banner_content,
            border_style="cyan",
            box=box.ROUNDED,
            padding=(0, 2),
        )
    )
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
    table.add_column("File", style="white", no_wrap=False, max_width=50)
    table.add_column("Status", justify="center")
    table.add_column("Details", style="dim", max_width=30)

    for result in results:
        size_str = f"{result.size:,} bytes" if result.size else ""
        details = result.details or size_str

        table.add_row(
            result.icon,
            f"[cyan]{result.filename}[/cyan]",
            result.status_text,
            details[:30] if details else "",
        )

    return table


def print_summary(results: list[FetchResult]) -> None:
    """Print a summary panel."""
    downloaded = sum(1 for r in results if r.status == FetchStatus.DOWNLOADED)
    unchanged = sum(1 for r in results if r.status == FetchStatus.UNCHANGED)
    failed = sum(1 for r in results if r.status in (FetchStatus.NOT_FOUND, FetchStatus.ERROR))
    total_size = sum(r.size or 0 for r in results if r.status == FetchStatus.DOWNLOADED)

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
    footer.append(str(DOCS_DIR / "reference"), style="cyan")
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


@retry_with_backoff(max_attempts=3, base_delay=1.0, exceptions=NETWORK_EXCEPTIONS)
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
        logger.debug(f"GET {url}")
        resp = await client.get(url, follow_redirects=True, timeout=30.0)

        if resp.status_code != 200:
            logger.debug(f"Not found: {url} -> {resp.status_code}")
            return FetchResult(
                source=source_name,
                filename=filename,
                status=FetchStatus.NOT_FOUND,
                details=f"HTTP {resp.status_code}",
            )

        content = resp.text

        # Calculate hash
        content_hash = get_file_hash(content)
        old_hash = metadata_section.get(filename, {}).get("hash")

        # Check if changed
        if not force and old_hash == content_hash:
            logger.debug(f"Unchanged: {filename}")
            return FetchResult(source=source_name, filename=filename, status=FetchStatus.UNCHANGED)

        # Pretty-print JSON if applicable
        if filename.endswith(".json"):
            try:
                parsed = json.loads(content)
                content = json.dumps(parsed, indent=2)
            except json.JSONDecodeError:
                pass

        # Save file (create subdirectories as needed)
        file_path = target_dir / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        # Update metadata
        metadata_section[filename] = {
            "hash": content_hash,
            "size": len(content),
            "url": url,
            "fetched_at": datetime.now().isoformat(),
        }

        logger.debug(f"Downloaded: {filename} ({len(content)} bytes)")
        return FetchResult(
            source=source_name,
            filename=filename,
            status=FetchStatus.DOWNLOADED,
            size=len(content),
        )

    except httpx.RequestError as e:
        logger.warning(f"Request error for {filename}: {e}")
        return FetchResult(
            source=source_name,
            filename=filename,
            status=FetchStatus.ERROR,
            details=str(e)[:50],
        )
    except OSError as e:
        logger.error(f"File error for {filename}: {e}")
        return FetchResult(
            source=source_name,
            filename=filename,
            status=FetchStatus.ERROR,
            details=f"IO: {e}",
        )


async def fetch_github_source(
    client: httpx.AsyncClient,
    source: GitHubSource,
    source_key: str,
    metadata: dict[str, Any],
    force: bool,
) -> list[FetchResult]:
    """Fetch documentation from a GitHub source using dynamic file discovery."""
    print_section_header(f"{source.name} API Docs", source.icon, source.style)

    target_dir = DOCS_DIR / "reference" / source.target_subdir
    results: list[FetchResult] = []

    # Discover files via GitHub API
    console.print(f"[dim]Discovering files in {source.owner}/{source.repo}...[/dim]")
    files = await list_github_directory(client, source)

    if not files:
        console.print(f"[yellow]No files found in {source.source_path}[/yellow]")
        return results

    console.print(f"[dim]Found {len(files)} files[/dim]")

    with Progress(
        SpinnerColumn("dots", style=source.style),
        TextColumn(f"[{source.style}]{{task.description}}[/{source.style}]"),
        BarColumn(bar_width=30, style=source.style, complete_style="green"),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("Fetching...", total=len(files))

        for file_info in files:
            result = await fetch_single_file(
                client=client,
                url=file_info.download_url,
                filename=file_info.path,  # Use relative path to preserve structure
                target_dir=target_dir,
                metadata_section=metadata.setdefault(source_key, {}),
                source_name=source.short_name,
                force=force,
            )
            results.append(result)
            progress.advance(task)

    console.print()
    console.print(create_results_table(results, f"{source.name} Files"))

    return results


async def fetch_audnex_docs(
    client: httpx.AsyncClient,
    metadata: dict[str, Any],
    force: bool,
) -> list[FetchResult]:
    """Fetch Audnex API documentation (specific files, not directory scan)."""
    source = SOURCES["audnex"]
    print_section_header(f"{source.name} API Docs", source.icon, source.style)

    target_dir = DOCS_DIR / "reference" / source.target_subdir
    results: list[FetchResult] = []

    with Progress(
        SpinnerColumn("dots", style=source.style),
        TextColumn(f"[{source.style}]{{task.description}}[/{source.style}]"),
        BarColumn(bar_width=30, style=source.style, complete_style="green"),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("Fetching...", total=len(AUDNEX_SPECIFIC_FILES))

        for filename, path in AUDNEX_SPECIFIC_FILES:
            url = f"{GITHUB_RAW_BASE}/{source.owner}/{source.repo}/{path}"
            result = await fetch_single_file(
                client=client,
                url=url,
                filename=filename,
                target_dir=target_dir,
                metadata_section=metadata.setdefault("audnex", {}),
                source_name=source.short_name,
                force=force,
            )
            results.append(result)
            progress.advance(task)

    console.print()
    console.print(create_results_table(results, f"{source.name} Files"))

    return results


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLI Application
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

app = typer.Typer(
    name="fetch-api-docs",
    help="Fetch and sync API documentation from Audiobookshelf, Audnex, and Hardcover.",
    add_completion=False,
    rich_markup_mode="rich",
    no_args_is_help=False,
    pretty_exceptions_enable=True,
    pretty_exceptions_show_locals=False,
)


class SourceChoice(str, Enum):
    """Available documentation sources."""

    ALL = "all"
    ABS = "abs"
    AUDNEX = "audnex"
    HARDCOVER = "hardcover"


async def run_fetch(
    force: bool,
    source: SourceChoice,
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
        if source in (SourceChoice.ALL, SourceChoice.ABS):
            results = await fetch_github_source(client, SOURCES["abs"], "abs", metadata, force)
            all_results.extend(results)

        # Fetch Audnex docs (special handling - specific files)
        if source in (SourceChoice.ALL, SourceChoice.AUDNEX):
            results = await fetch_audnex_docs(client, metadata, force)
            all_results.extend(results)

        # Fetch Hardcover docs
        if source in (SourceChoice.ALL, SourceChoice.HARDCOVER):
            results = await fetch_github_source(client, SOURCES["hardcover"], "hardcover", metadata, force)
            all_results.extend(results)

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
    source: Annotated[
        SourceChoice,
        typer.Option(
            "--source",
            "-s",
            help="Which documentation source to fetch.",
            case_sensitive=False,
        ),
    ] = SourceChoice.ALL,
) -> None:
    """
    [bold cyan]Fetch API documentation from external sources.[/bold cyan]

    Pulls the latest API docs from GitHub repositories using dynamic file discovery.
    Uses content hashing to detect changes and skip unchanged files.

    [dim]Sources:[/dim]
      • [cyan]abs[/cyan]       - Audiobookshelf API docs
      • [magenta]audnex[/magenta]    - Audnex API specification
      • [yellow]hardcover[/yellow] - Hardcover GraphQL API docs

    [dim]Examples:[/dim]
      [green]$[/green] python fetch_api_docs.py              [dim]# Fetch all sources[/dim]
      [green]$[/green] python fetch_api_docs.py --force      [dim]# Force re-fetch everything[/dim]
      [green]$[/green] python fetch_api_docs.py -s abs       [dim]# Only ABS docs[/dim]
      [green]$[/green] python fetch_api_docs.py -s hardcover [dim]# Only Hardcover docs[/dim]
      [green]$[/green] python fetch_api_docs.py -v           [dim]# Verbose mode[/dim]
    """
    if ctx.invoked_subcommand is not None:
        return

    setup_logging(verbose)
    setup_tracebacks(verbose)

    if verbose:
        console.print("[dim]Verbose mode enabled[/dim]")

    try:
        exit_code = asyncio.run(run_fetch(force, source))
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

    # Show each source
    for _key, source in SOURCES.items():
        section_key = source.short_name.lower()
        if metadata.get(section_key):
            title = f"[bold {source.style}]{source.name}[/bold {source.style}]"
            table = Table(title=title, box=box.SIMPLE)
            table.add_column("File", style="white", max_width=40)
            table.add_column("Size", justify="right", style="cyan")
            table.add_column("Hash", style="dim")
            table.add_column("Fetched", style="dim")

            for filename, info in sorted(metadata[section_key].items()):
                table.add_row(
                    filename[:40],
                    f"{info.get('size', 0):,}",
                    info.get("hash", "")[:8],
                    info.get("fetched_at", "")[:10],
                )

            console.print()
            console.print(table)


@app.command()
def clean(
    source: Annotated[
        SourceChoice,
        typer.Option(
            "--source",
            "-s",
            help="Which source's docs to clean (default: all).",
            case_sensitive=False,
        ),
    ] = SourceChoice.ALL,
) -> None:
    """Remove fetched docs and metadata."""
    from shutil import rmtree

    console.print()

    removed = []
    ref_dir = DOCS_DIR / "reference"

    # Determine which directories to clean
    dirs_to_clean: list[Path] = []
    if source == SourceChoice.ALL:
        dirs_to_clean = [ref_dir / s.target_subdir for s in SOURCES.values()]
    else:
        src = SOURCES.get(source.value)
        if src:
            dirs_to_clean = [ref_dir / src.target_subdir]

    for dir_path in dirs_to_clean:
        if dir_path.exists():
            rmtree(dir_path)
            removed.append(str(dir_path))
            console.print(f"[red]✗[/red] Removed [cyan]{dir_path}[/cyan]")

    # Clean metadata if removing all
    if source == SourceChoice.ALL and METADATA_FILE.exists():
        METADATA_FILE.unlink()
        removed.append(str(METADATA_FILE))
        console.print(f"[red]✗[/red] Removed [cyan]{METADATA_FILE}[/cyan]")
    elif source != SourceChoice.ALL:
        # Remove just this source's metadata
        metadata = load_metadata()
        src = SOURCES.get(source.value)
        if src and src.short_name.lower() in metadata:
            del metadata[src.short_name.lower()]
            save_metadata(metadata)
            console.print(f"[yellow]○[/yellow] Cleaned metadata for [cyan]{source.value}[/cyan]")

    if removed:
        console.print()
        console.print(f"[green]Cleaned {len(removed)} items.[/green]")
    else:
        console.print("[yellow]Nothing to clean.[/yellow]")


@app.command()
def list_sources() -> None:
    """List available documentation sources."""
    console.print()

    table = Table(
        title="[bold magenta]Available Sources[/bold magenta]",
        box=box.ROUNDED,
        header_style="bold cyan",
    )
    table.add_column("Key", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("Repository", style="dim")
    table.add_column("Path", style="dim")

    for key, source in SOURCES.items():
        table.add_row(
            key,
            f"{source.icon} {source.name}",
            f"{source.owner}/{source.repo}",
            source.source_path or "(specific files)",
        )

    console.print(table)


if __name__ == "__main__":
    app()
