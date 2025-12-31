"""mkbrr CLI commands (sub-app).

Commands: mkbrr create, mkbrr inspect, mkbrr check, mkbrr modify,
          mkbrr presets, mkbrr version, mkbrr update
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from shelfr.console import console, print_error, print_info, print_success, print_warning
from shelfr.ui.icons import icons

logger = logging.getLogger(__name__)

# =============================================================================
# Panel name for help grouping
# =============================================================================

MKBRR_COMMANDS = "Torrent Tools"

# =============================================================================
# Epilog for mkbrr sub-app
# =============================================================================

MKBRR_EPILOG = f"""
[bold cyan]Common Tasks:[/]
  shelfr mkbrr create <path>     [dim]# Create torrent from file/folder[/]
  shelfr mkbrr inspect <file>    [dim]# View torrent metadata[/]
  shelfr mkbrr check <t> <path>  [dim]# Verify content integrity[/]

[bold cyan]Tips:[/]
  {icons.bullet} Use [green]--preset mam[/] for MAM-compliant torrents
  {icons.bullet} Run [green]shelfr mkbrr presets[/] to see available presets
  {icons.bullet} mkbrr runs in Docker - ensure Docker is available
"""


def make_mkbrr_app() -> typer.Typer:
    """Create the mkbrr sub-app."""
    return typer.Typer(
        name="mkbrr",
        help="Torrent creation and management via mkbrr",
        epilog=MKBRR_EPILOG,
        rich_markup_mode="rich",
        no_args_is_help=True,
    )


def register_mkbrr_commands(mkbrr_app: typer.Typer) -> None:
    """Register mkbrr commands on the mkbrr sub-app."""

    @mkbrr_app.callback(invoke_without_command=True)
    def mkbrr_callback(ctx: typer.Context) -> None:
        """Torrent creation and management via mkbrr.

        [bold]Commands:[/]
          shelfr mkbrr create    Create torrent from file/directory
          shelfr mkbrr inspect   View torrent metadata
          shelfr mkbrr check     Verify content against torrent
          shelfr mkbrr modify    Modify existing torrent file
          shelfr mkbrr presets   List available presets
          shelfr mkbrr version   Show mkbrr version
          shelfr mkbrr update    Update mkbrr Docker image
        [dim]mkbrr is a fast torrent creation tool from autobrr.[/]
        """
        if ctx.invoked_subcommand is None:
            console.print(ctx.get_help())
            raise typer.Exit(0)

    # =========================================================================
    # create command
    # =========================================================================

    @mkbrr_app.command("create")
    def mkbrr_create(
        ctx: typer.Context,
        path: Annotated[
            Path,
            typer.Argument(
                help="Path to file or directory to create torrent from.",
                exists=True,
            ),
        ],
        preset: Annotated[
            str | None,
            typer.Option("--preset", "-P", help="Use preset from presets.yaml."),
        ] = None,
        tracker: Annotated[
            str | None,
            typer.Option("--tracker", "-t", help="Tracker announce URL."),
        ] = None,
        source: Annotated[
            str | None,
            typer.Option("--source", "-s", help="Source tag (e.g., MAM)."),
        ] = None,
        output: Annotated[
            str | None,
            typer.Option("--output", "-o", help="Output filename (without extension)."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Output directory."),
        ] = None,
        piece_length: Annotated[
            int | None,
            typer.Option(
                "--piece-length",
                "-l",
                help="Piece size exponent (16-27, e.g., 18 = 256 KiB).",
                min=16,
                max=27,
            ),
        ] = None,
        max_piece_length: Annotated[
            int | None,
            typer.Option(
                "--max-piece-length",
                "-m",
                help="Max piece size exponent (16-27).",
                min=16,
                max=27,
            ),
        ] = None,
        exclude: Annotated[
            list[str] | None,
            typer.Option("--exclude", help="Exclude files matching pattern."),
        ] = None,
        include: Annotated[
            list[str] | None,
            typer.Option("--include", help="Include only files matching pattern."),
        ] = None,
        comment: Annotated[
            str | None,
            typer.Option("--comment", "-c", help="Torrent comment."),
        ] = None,
        private: Annotated[
            bool | None,
            typer.Option("--private/--no-private", help="Set private flag."),
        ] = None,
        skip_prefix: Annotated[
            bool,
            typer.Option("--skip-prefix", help="Don't add tracker domain prefix."),
        ] = False,
        entropy: Annotated[
            bool,
            typer.Option("--entropy", "-e", help="Add entropy to randomize info hash."),
        ] = False,
        no_date: Annotated[
            bool,
            typer.Option("--no-date", help="Omit creation date."),
        ] = False,
        no_creator: Annotated[
            bool,
            typer.Option("--no-creator", help="Omit created-by field."),
        ] = False,
        web_seed: Annotated[
            list[str] | None,
            typer.Option("--web-seed", "-w", help="Web seed URL (can repeat)."),
        ] = None,
    ) -> None:
        """Create a torrent from file or directory.

        [bold]Examples:[/]
          shelfr mkbrr create ./audiobook -P mam
          shelfr mkbrr create ./file.m4b -t https://tracker/announce
          shelfr mkbrr create ./folder --source MAM --private

        [bold]Features:[/]
          - Auto piece size based on content size
          - Tracker-specific rules for compliance
          - File filtering with --include/--exclude
        """
        from shelfr import mkbrr

        # Check Docker availability
        if not mkbrr.check_docker_available():
            print_error("Docker is not available. mkbrr requires Docker to run.")
            raise typer.Exit(1)

        # Get dry_run from context
        dry_run = ctx.obj.get("dry_run", False) if ctx.obj else False

        if dry_run:
            print_info(f"[DRY RUN] Would create torrent from: {path}")
            _show_create_preview(
                path=path,
                preset=preset,
                tracker=tracker,
                source=source,
                output=output,
                output_dir=output_dir,
            )
            raise typer.Exit(0)

        # Create the torrent
        result = mkbrr.create_torrent(
            content_path=path,
            output_dir=output_dir,
            preset=preset,
            output_filename=output,
            tracker=tracker,
            source=source,
            piece_length=piece_length,
            max_piece_length=max_piece_length,
            exclude_patterns=exclude,
            include_patterns=include,
            skip_prefix=skip_prefix,
            comment=comment,
            private=private,
            no_date=no_date,
            no_creator=no_creator,
            web_seeds=web_seed,
            entropy=entropy,
        )

        if result.success and result.torrent_path:
            print_success(f"Created torrent: {result.torrent_path}")

            # Show torrent info
            try:
                info = mkbrr.parse_torrent_file(result.torrent_path)
                _display_torrent_info(info)
            except Exception as e:
                logger.debug(f"Could not parse created torrent: {e}")

            raise typer.Exit(0)
        else:
            print_error(f"Failed to create torrent: {result.error or 'Unknown error'}")
            if result.stderr:
                console.print(f"[dim]{result.stderr}[/dim]")
            raise typer.Exit(1)

    # =========================================================================
    # inspect command
    # =========================================================================

    @mkbrr_app.command("inspect")
    def mkbrr_inspect(
        ctx: typer.Context,
        torrents: Annotated[
            list[Path],
            typer.Argument(
                help="Path(s) to .torrent file(s) to inspect.",
            ),
        ],
        verbose: Annotated[
            bool,
            typer.Option("--verbose", "-v", help="Show all metadata fields."),
        ] = False,
        json_output: Annotated[
            bool,
            typer.Option("--json", "-j", help="Output as JSON."),
        ] = False,
    ) -> None:
        """Inspect torrent file metadata.

        [bold]Examples:[/]
          shelfr mkbrr inspect my-audiobook.torrent
          shelfr mkbrr inspect *.torrent --verbose
          shelfr mkbrr inspect file.torrent --json

        [bold]Shows:[/]
          - Name, size, piece count
          - Info hash and trackers
          - File list (multi-file torrents)
        """
        import json

        from shelfr import mkbrr

        results = []

        for torrent_path in torrents:
            if not torrent_path.exists():
                print_error(f"File not found: {torrent_path}")
                continue

            try:
                # Use bencode parsing (more reliable than Docker inspect output)
                info = mkbrr.parse_torrent_file(torrent_path)
                results.append(info)

                if json_output:
                    continue  # Collect all, output at end

                _display_torrent_info(info, verbose=verbose)

                if len(torrents) > 1:
                    console.print()  # Separator between torrents

            except Exception as e:
                print_error(f"Failed to parse {torrent_path}: {e}")
                logger.exception(f"Error inspecting {torrent_path}")

        if json_output and results:
            output_data = [
                {
                    "name": info.name,
                    "info_hash": info.info_hash,
                    "size": info.size,
                    "piece_length": info.piece_length,
                    "piece_count": info.piece_count,
                    "private": info.private,
                    "trackers": info.trackers,
                    "source": info.source,
                    "comment": info.comment,
                    "created_by": info.created_by,
                    "creation_date": (
                        info.creation_date.isoformat() if info.creation_date else None
                    ),
                    "files": [{"path": f.path, "size": f.size} for f in info.files],
                }
                for info in results
            ]
            console.print_json(json.dumps(output_data, indent=2))

        if not results:
            raise typer.Exit(1)

    # =========================================================================
    # check command
    # =========================================================================

    @mkbrr_app.command("check")
    def mkbrr_check(
        ctx: typer.Context,
        torrent: Annotated[
            Path,
            typer.Argument(help="Path to .torrent file."),
        ],
        content: Annotated[
            Path,
            typer.Argument(help="Path to content file or directory."),
        ],
        verbose: Annotated[
            bool,
            typer.Option("--verbose", "-v", help="Show bad piece indices."),
        ] = False,
        quiet: Annotated[
            bool,
            typer.Option("--quiet", "-q", help="Output only completion percentage."),
        ] = False,
        workers: Annotated[
            int | None,
            typer.Option("--workers", help="Verification worker threads."),
        ] = None,
    ) -> None:
        """Verify content integrity against torrent file.

        [bold]Examples:[/]
          shelfr mkbrr check my.torrent ./content/
          shelfr mkbrr check my.torrent ./file.m4b --verbose
          shelfr mkbrr check my.torrent ./folder -q

        [bold]Output:[/]
          - Completion percentage
          - Good/bad piece counts
          - Missing files (if any)
          - Verification time
        """
        from shelfr import mkbrr

        if not torrent.exists():
            print_error(f"Torrent file not found: {torrent}")
            raise typer.Exit(1)

        if not content.exists():
            print_error(f"Content path not found: {content}")
            raise typer.Exit(1)

        # Check Docker availability
        if not mkbrr.check_docker_available():
            print_error("Docker is not available. mkbrr requires Docker to run.")
            raise typer.Exit(1)

        # Run verification
        result = mkbrr.check_torrent(
            torrent_path=torrent,
            content_path=content,
            verbose=verbose,
            quiet=quiet,
            workers=workers,
        )

        if not result.success:
            print_error(f"Verification failed: {result.error or 'Unknown error'}")
            raise typer.Exit(1)

        # Parse and display results
        if quiet:
            # Just show the raw output (percentage)
            console.print(result.stdout.strip())
        else:
            try:
                check_result = mkbrr.parse_check_output(result.stdout)
                _display_check_result(check_result, verbose=verbose)

                # Exit with error if not complete
                if not check_result.valid:
                    raise typer.Exit(1)
            except ValueError as e:
                # Fallback to raw output if parsing fails
                logger.debug(f"Could not parse check output: {e}")
                console.print(result.stdout)

    # =========================================================================
    # modify command
    # =========================================================================

    @mkbrr_app.command("modify")
    def mkbrr_modify(
        ctx: typer.Context,
        torrents: Annotated[
            list[Path],
            typer.Argument(help="Path(s) to .torrent file(s) to modify."),
        ],
        tracker: Annotated[
            str | None,
            typer.Option("--tracker", "-t", help="New tracker URL."),
        ] = None,
        source: Annotated[
            str | None,
            typer.Option("--source", "-s", help="New source tag."),
        ] = None,
        comment: Annotated[
            str | None,
            typer.Option("--comment", "-c", help="New comment."),
        ] = None,
        private: Annotated[
            bool | None,
            typer.Option("--private/--no-private", help="Set private flag."),
        ] = None,
        output: Annotated[
            Path | None,
            typer.Option("--output", "-o", help="Output path (single file only)."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Output directory (for batch)."),
        ] = None,
        preset: Annotated[
            str | None,
            typer.Option("--preset", "-P", help="Apply preset settings."),
        ] = None,
        entropy: Annotated[
            bool,
            typer.Option("--entropy", "-e", help="Add entropy to change info hash."),
        ] = False,
        dry_run_local: Annotated[
            bool,
            typer.Option("--dry-run", "-n", help="Preview changes without saving."),
        ] = False,
    ) -> None:
        """Modify existing torrent file(s).

        [bold]Examples:[/]
          shelfr mkbrr modify my.torrent -t https://newtracker/announce
          shelfr mkbrr modify *.torrent --source MAM --output-dir ./modified/
          shelfr mkbrr modify old.torrent -P mam --entropy

        [bold]Note:[/]
          - Original files are preserved
          - All non-standard metadata is stripped
          - For multiple files, use --output-dir
        """
        from shelfr import mkbrr

        # Check Docker availability
        if not mkbrr.check_docker_available():
            print_error("Docker is not available. mkbrr requires Docker to run.")
            raise typer.Exit(1)

        # Get dry_run from context or local flag
        dry_run = dry_run_local or (ctx.obj.get("dry_run", False) if ctx.obj else False)

        if len(torrents) > 1 and output:
            print_warning(
                "Using --output with multiple files will overwrite. " "Use --output-dir instead."
            )

        # Validate torrent paths exist
        valid_torrents: list[Path | str] = []
        for t in torrents:
            if t.exists():
                valid_torrents.append(t)
            else:
                print_error(f"File not found: {t}")

        if not valid_torrents:
            raise typer.Exit(1)

        # Modify torrents
        result = mkbrr.modify_torrent(
            torrent_paths=valid_torrents,
            output_path=output,
            output_dir=output_dir,
            tracker=tracker,
            source=source,
            comment=comment,
            private=private,
            preset=preset,
            entropy=entropy,
            dry_run=dry_run,
        )

        if result.success:
            if dry_run:
                print_info("[DRY RUN] Would modify torrent(s)")
            else:
                print_success(
                    f"Modified {len(valid_torrents)} torrent(s)"
                    + (f" → {result.torrent_path}" if result.torrent_path else "")
                )
            raise typer.Exit(0)
        else:
            print_error(f"Failed to modify torrent(s): {result.error or 'Unknown error'}")
            raise typer.Exit(1)

    # =========================================================================
    # presets command
    # =========================================================================

    @mkbrr_app.command("presets")
    def mkbrr_presets(ctx: typer.Context) -> None:
        """List available mkbrr presets.

        Shows presets defined in mkbrr's presets.yaml configuration.
        Use [cyan]-P <preset>[/] with create/modify commands.
        """
        from shelfr import mkbrr

        presets = mkbrr.load_presets()

        if not presets:
            print_warning("No presets found in presets.yaml")
            raise typer.Exit(0)

        table = Table(title="Available Presets", show_header=True, header_style="bold cyan")
        table.add_column("Preset Name", style="green")
        table.add_column("Usage", style="dim")

        for preset_name in sorted(presets):
            table.add_row(preset_name, f"-P {preset_name}")

        console.print(table)

    # =========================================================================
    # version command
    # =========================================================================

    @mkbrr_app.command("version")
    def mkbrr_version(ctx: typer.Context) -> None:
        """Show mkbrr version.

        Displays the version of mkbrr running in Docker.
        """
        from shelfr import mkbrr

        if not mkbrr.check_docker_available():
            print_error("Docker is not available.")
            raise typer.Exit(1)

        version = mkbrr.get_mkbrr_version()

        if version:
            console.print(f"[bold]mkbrr[/] version [cyan]{version}[/]")
        else:
            print_error("Could not determine mkbrr version")
            raise typer.Exit(1)

    # =========================================================================
    # update command
    # =========================================================================

    @mkbrr_app.command("update")
    def mkbrr_update(ctx: typer.Context) -> None:
        """Update mkbrr Docker image.

        Pulls the latest ghcr.io/autobrr/mkbrr image from GitHub Container Registry.
        """
        from shelfr.config import get_settings
        from shelfr.utils.cmd import run

        settings = get_settings()
        image = settings.mkbrr.image

        print_info(f"Pulling latest image: {image}")

        try:
            run(
                [settings.docker_bin, "pull", image],
                timeout=300,
                ok_codes=(0,),
            )
            print_success(f"Updated mkbrr image: {image}")

            # Show new version
            from shelfr import mkbrr

            version = mkbrr.get_mkbrr_version()
            if version:
                console.print(f"Current version: [cyan]{version}[/]")

        except Exception as e:
            print_error(f"Failed to update image: {e}")
            raise typer.Exit(1) from None


# =============================================================================
# Helper display functions
# =============================================================================


def _show_create_preview(
    path: Path,
    preset: str | None,
    tracker: str | None,
    source: str | None,
    output: str | None,
    output_dir: Path | None,
) -> None:
    """Show preview of what would be created."""
    from rich.tree import Tree

    tree = Tree(f"[bold]Create torrent from:[/] {path}")

    if preset:
        tree.add(f"[cyan]Preset:[/] {preset}")
    if tracker:
        tree.add(f"[cyan]Tracker:[/] {tracker}")
    if source:
        tree.add(f"[cyan]Source:[/] {source}")
    if output:
        tree.add(f"[cyan]Output:[/] {output}.torrent")
    if output_dir:
        tree.add(f"[cyan]Output dir:[/] {output_dir}")

    console.print(tree)


def _display_torrent_info(info: TorrentInfo, verbose: bool = False) -> None:
    """Display torrent info in a nice panel."""

    # Build info lines
    lines = [
        f"[bold]{info.name}[/]",
        "",
        f"[cyan]Hash:[/]         {info.info_hash}",
        f"[cyan]Size:[/]         {info.human_size()}",
        f"[cyan]Pieces:[/]       {info.piece_count:,} × {info.human_piece_length()}",
    ]

    if info.private:
        lines.append("[cyan]Private:[/]      [green]yes[/]")

    if info.trackers:
        lines.append(f"[cyan]Trackers:[/]     {len(info.trackers)}")
        if verbose:
            for t in info.trackers:
                lines.append(f"                 [dim]{t}[/dim]")

    if info.source:
        lines.append(f"[cyan]Source:[/]       {info.source}")

    if info.comment:
        lines.append(f"[cyan]Comment:[/]      {info.comment}")

    if info.created_by:
        lines.append(f"[cyan]Created by:[/]   {info.created_by}")

    if info.creation_date:
        lines.append(f"[cyan]Created:[/]      {info.creation_date.strftime('%Y-%m-%d %H:%M:%S')}")

    if info.files:
        lines.append(f"[cyan]Files:[/]        {len(info.files)}")
        if verbose:
            for f in info.files[:20]:  # Limit to 20 files
                lines.append(f"                 [dim]{f.path}[/dim] ({_format_size(f.size)})")
            if len(info.files) > 20:
                lines.append(f"                 [dim]... and {len(info.files) - 20} more[/dim]")

    if verbose and info.extra_fields:
        lines.append("[cyan]Extra fields:[/]")
        for k, v in info.extra_fields.items():
            lines.append(f"                 [dim]{k}: {v}[/dim]")

    panel = Panel(
        "\n".join(lines),
        title="[bold cyan]Torrent Info[/]",
        border_style="cyan",
        padding=(0, 1),
    )
    console.print(panel)


def _display_check_result(result: CheckResult, verbose: bool = False) -> None:
    """Display check result in a nice format."""

    # Status color
    if result.valid:
        status_color = "green"
        status_icon = "✓"
    elif result.percent_complete >= 99.0:
        status_color = "yellow"
        status_icon = "⚠"
    else:
        status_color = "red"
        status_icon = "✗"

    lines = [
        f"[{status_color}]{status_icon} Completion: {result.percent_complete:.2f}%[/]",
        "",
        f"[cyan]Good pieces:[/]  {result.good_pieces:,}",
        f"[cyan]Bad pieces:[/]   {result.bad_pieces:,}",
        f"[cyan]Total pieces:[/] {result.total_pieces:,}",
    ]

    if result.missing_files:
        lines.append(f"[red]Missing files:[/] {len(result.missing_files)}")
        if verbose:
            for f in result.missing_files[:10]:
                lines.append(f"  [dim]• {f}[/dim]")
            if len(result.missing_files) > 10:
                lines.append(f"  [dim]... and {len(result.missing_files) - 10} more[/dim]")

    if result.check_time_seconds:
        lines.append(f"[cyan]Check time:[/]   {result.check_time_seconds:.2f}s")

    if verbose and result.bad_piece_indices:
        indices_str = ", ".join(str(i) for i in result.bad_piece_indices[:20])
        lines.append(f"[cyan]Bad indices:[/]  {indices_str}")
        if len(result.bad_piece_indices) > 20:
            lines.append(f"  [dim]... and {len(result.bad_piece_indices) - 20} more[/dim]")

    panel = Panel(
        "\n".join(lines),
        title=f"[bold {status_color}]Verification Result[/]",
        border_style=status_color,
        padding=(0, 1),
    )
    console.print(panel)


def _format_size(size_bytes: int) -> str:
    """Format bytes as human-readable size."""
    if size_bytes >= 1024**3:
        return f"{size_bytes / (1024**3):.2f} GiB"
    elif size_bytes >= 1024**2:
        return f"{size_bytes / (1024**2):.2f} MiB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.2f} KiB"
    return f"{size_bytes} B"


# Type imports at module level for type hints
if True:  # TYPE_CHECKING equivalent that works at runtime for display functions
    from shelfr.schemas.mkbrr import CheckResult, TorrentInfo
