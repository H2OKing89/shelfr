#!/usr/bin/env python3
"""
Standalone script to probe all audiobook files and collect metadata.
Uses Docker ffprobe to avoid dependency issues.
Output: JSONL file with metadata for each audiobook.

Key improvements:
- Worker queue pattern (bounded concurrency, scalable to 100k+ files)
- Mount audiobook root once (not per-parent dir)
- subprocess_exec with argv (no shell quoting issues)
- Single directory walk
- Correct failure attribution
- SIGTERM + graceful shutdown
- Rich metadata (size, mtime, relative path, probe version)
"""

from __future__ import annotations

import asyncio
import json
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    BarColumn,
    TaskProgressColumn,
    TimeRemainingColumn,
    TextColumn,
    MofNCompleteColumn,
)
from rich.table import Table
from rich.traceback import install as install_traceback

# Install Rich traceback for better error display
install_traceback(show_locals=True, width=120)

# Configuration
AUDIOBOOK_DIR = Path("/mnt/user/data/audio/audiobooks")
OUTPUT_FILE = Path("data/audiobook_metadata.jsonl")
DOCKER_IMAGE = "linuxserver/ffmpeg"
MAX_WORKERS = 12  # Optimal for Docker overhead (not CPU thread count)
PROBE_TIMEOUT = 90  # Seconds per file
FLUSH_INTERVAL = 50  # Flush output every N files

# Audio file extensions (case-insensitive)
AUDIO_EXTENSIONS = {".m4b", ".m4a", ".mp3", ".flac", ".wav", ".aac", ".ogg", ".wma"}

console = Console()

# Graceful shutdown
shutdown_event = asyncio.Event()


def signal_handler(sig, frame):
    """Handle SIGINT/SIGTERM gracefully."""
    console.print(f"\n[yellow]⚠ Received signal {sig}, shutting down...[/yellow]")
    shutdown_event.set()


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


async def check_docker_available() -> bool:
    """
    Preflight check: verify Docker is available and image works.
    Fails early instead of thousands of tasks in.
    """
    try:
        # Check docker command exists
        proc = await asyncio.create_subprocess_exec(
            "docker", "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        if proc.returncode != 0:
            console.print("[red]✗ Docker command not found or not working[/red]")
            return False
        
        # Check image exists and ffprobe works
        console.print(f"[cyan]Checking Docker image: {DOCKER_IMAGE}...[/cyan]")
        proc = await asyncio.create_subprocess_exec(
            "docker", "run", "--rm",
            "--entrypoint", "ffprobe",
            DOCKER_IMAGE,
            "-version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        
        if proc.returncode != 0:
            console.print(f"[red]✗ Docker image test failed:[/red] {stderr.decode(errors='replace')[:200]}")
            return False
        
        # Extract version info
        version_line = stdout.decode(errors="replace").split("\n")[0]
        console.print(f"[green]✓ {version_line}[/green]")
        return True
    
    except asyncio.TimeoutError:
        console.print("[red]✗ Docker image check timed out (may need to pull image)[/red]")
        return False
    except Exception as e:
        console.print(f"[red]✗ Docker preflight failed: {e}[/red]")
        return False


def get_audio_files() -> list[Path]:
    """Single directory walk, case-insensitive extension matching."""
    if not AUDIOBOOK_DIR.exists():
        console.print(f"[red]✗ Error:[/red] Directory not found: {AUDIOBOOK_DIR}")
        return []
    
    with console.status("[cyan]Scanning for audio files...[/cyan]", spinner="dots"):
        audio_files = [
            f for f in AUDIOBOOK_DIR.rglob("*")
            if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
        ]
    
    console.print(f"[green]✓ Found {len(audio_files):,} audio files[/green]")
    # Note: sorting gives deterministic output but can be slow for 100k+ files
    # Consider removing if you don't need stable ordering
    return sorted(audio_files)


async def probe_file(filepath: Path) -> tuple[Path, dict | None, str | None]:
    """
    Probe a single file using ffprobe in Docker.
    Returns (filepath, metadata_dict | None, error_msg | None).
    
    Note: Still runs one `docker run` per file (not truly "mounted once").
    For true mount-once, would need long-lived container + docker exec.
    We mount AUDIOBOOK_DIR root (not per-parent) to minimize overhead.
    """
    try:
        # Relative path from audiobook root
        rel_path = filepath.relative_to(AUDIOBOOK_DIR)
        container_path = f"/input/{rel_path}"
        
        # Use subprocess_exec with argv (no shell quoting needed)
        # Get all metadata (no -show_entries filter) for comprehensive data collection
        proc = await asyncio.create_subprocess_exec(
            "docker", "run", "--rm",
            "--entrypoint", "ffprobe",
            "-v", f"{AUDIOBOOK_DIR}:/input:ro",
            DOCKER_IMAGE,
            "-v", "error",
            "-of", "json",
            "-show_format",
            "-show_streams",
            "-show_chapters",
            container_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=PROBE_TIMEOUT)
        
        if proc.returncode != 0:
            return filepath, None, stderr.decode(errors="replace").strip()[:200]
        
        probe_data = json.loads(stdout.decode(errors="replace"))
        
        # Add rich metadata for incremental runs / deduplication
        stat = filepath.stat()
        metadata = {
            "file_path": str(filepath),
            "relative_path": str(rel_path),
            "file_name": filepath.name,
            "parent_dir": filepath.parent.name,
            "size_bytes": stat.st_size,
            "mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            "probe_timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "docker_image": DOCKER_IMAGE,
            "ffprobe_data": probe_data,
        }
        
        return filepath, metadata, None
    
    except asyncio.TimeoutError:
        return filepath, None, f"Timeout ({PROBE_TIMEOUT}s)"
    except json.JSONDecodeError as e:
        return filepath, None, f"Invalid JSON: {e}"
    except Exception as e:
        return filepath, None, str(e)[:200]


async def worker(
    queue: asyncio.Queue,
    results_queue: asyncio.Queue,
    progress: Progress,
    task_id,
):
    """
    Worker pulls files from queue, probes them, pushes results.
    Stops when it gets sentinel (None) or shutdown requested.
    
    Critical: ALWAYS puts a result (success or failure) so writer never stalls.
    """
    while not shutdown_event.is_set():
        try:
            filepath = await asyncio.wait_for(queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue  # Check shutdown flag
        
        try:
            if filepath is None:  # Sentinel
                return
            
            # Hardened: catch ALL exceptions so we always put a result
            try:
                result = await probe_file(filepath)
            except Exception as e:
                # Worker crash - still report it
                result = (filepath, None, f"Worker crash: {e}")
            
            await results_queue.put(result)
            progress.update(task_id, advance=1)
        
        finally:
            # ALWAYS task_done, even for sentinel
            queue.task_done()


async def result_writer(
    results_queue: asyncio.Queue,
    total_files: int,
) -> tuple[int, int, list[tuple[str, str]]]:
    """
    Consumes results, writes to JSONL, tracks stats.
    Flushes every FLUSH_INTERVAL records for performance.
    
    On shutdown: keeps draining for grace period to avoid losing results.
    """
    success_count = 0
    failed_count = 0
    failures: list[tuple[str, str]] = []
    
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    grace_timeout = 5.0  # Seconds to drain results after shutdown
    
    with open(OUTPUT_FILE, "w") as f:
        writes_since_flush = 0
        
        while success_count + failed_count < total_files:
            # After shutdown, give a grace period to drain in-flight results
            timeout = grace_timeout if shutdown_event.is_set() else None
            
            try:
                filepath, metadata, error = await asyncio.wait_for(
                    results_queue.get(), timeout=timeout or 1.0
                )
            except asyncio.TimeoutError:
                if shutdown_event.is_set():
                    # Grace period expired, stop draining
                    break
                continue
            
            if metadata:
                f.write(json.dumps(metadata) + "\n")
                writes_since_flush += 1
                success_count += 1
                
                if writes_since_flush >= FLUSH_INTERVAL:
                    f.flush()
                    writes_since_flush = 0
            else:
                failed_count += 1
                if len(failures) < 50 and error:
                    failures.append((filepath.name, error))
        
        f.flush()  # Final flush
    
    return success_count, failed_count, failures


async def process_all_files(audio_files: list[Path]) -> tuple[int, int, list[tuple[str, str]]]:
    """
    Queue-based worker pattern:
    - Bounded task creation (not 50k coroutines at once)
    - Correct failure attribution (workers return filepath)
    - Separate result writer for I/O optimization
    """
    work_queue: asyncio.Queue = asyncio.Queue()
    results_queue: asyncio.Queue = asyncio.Queue()
    
    # Fill work queue
    for filepath in audio_files:
        await work_queue.put(filepath)
    
    # Add sentinels for graceful worker shutdown
    for _ in range(MAX_WORKERS):
        await work_queue.put(None)
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=40),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("Probing", total=len(audio_files))
        
        # Spawn workers + result writer
        workers = [
            asyncio.create_task(worker(work_queue, results_queue, progress, task))
            for _ in range(MAX_WORKERS)
        ]
        writer = asyncio.create_task(result_writer(results_queue, len(audio_files)))
        
        # Wait for all workers to finish
        await asyncio.gather(*workers)
        
        # Wait for writer to drain results
        success, failed, failures = await writer
    
    return success, failed, failures


def display_summary(success: int, failed: int, failures: list[tuple[str, str]], total: int) -> None:
    """Display Rich summary table."""
    table = Table(title="Probe Summary", show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    
    table.add_row("Total Files", f"{total:,}")
    table.add_row("✓ Successful", f"[green]{success:,}[/green]")
    table.add_row("✗ Failed", f"[red]{failed:,}[/red]" if failed > 0 else "[dim]0[/dim]")
    table.add_row("Success Rate", f"{success/total*100:.1f}%" if total > 0 else "N/A")
    table.add_row("Output File", str(OUTPUT_FILE.absolute()))
    table.add_row("Docker Image", DOCKER_IMAGE)
    
    console.print(table)
    
    if failures:
        console.print("\n[bold red]Sample Failures:[/bold red]")
        fail_table = Table(show_header=True, header_style="bold red", width=120)
        fail_table.add_column("File", style="yellow", max_width=60)
        fail_table.add_column("Error", style="red", max_width=55)
        
        for filename, error in failures[:10]:
            fail_table.add_row(
                filename[:55] + "..." if len(filename) > 55 else filename,
                error[:50]
            )
        
        console.print(fail_table)
        if len(failures) > 10:
            console.print(f"[dim]... and {len(failures) - 10} more failures[/dim]")


def main() -> int:
    """Main probe routine."""
    console.print(Panel.fit(
        "[bold cyan]Audiobook Metadata Probe[/bold cyan]\n"
        f"[dim]Source: {AUDIOBOOK_DIR}[/dim]\n"
        f"[dim]Output: {OUTPUT_FILE}[/dim]\n"
        f"[dim]Workers: {MAX_WORKERS} | Timeout: {PROBE_TIMEOUT}s[/dim]",
        border_style="cyan"
    ))
    
    # Preflight: verify Docker works before scanning files
    try:
        if not asyncio.run(check_docker_available()):
            return 1
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted during preflight[/yellow]")
        return 130
    
    audio_files = get_audio_files()
    
    if not audio_files:
        console.print("[red]No audio files found to probe[/red]")
        return 1
    
    console.print(f"[yellow]Starting {MAX_WORKERS} concurrent workers...[/yellow]\n")
    
    try:
        success, failed, failures = asyncio.run(process_all_files(audio_files))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted![/yellow]")
        return 130
    
    console.print()
    display_summary(success, failed, failures, len(audio_files))
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
