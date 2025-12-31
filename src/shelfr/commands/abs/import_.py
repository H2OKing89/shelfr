"""ABS import command - import staged audiobooks to Audiobookshelf library.

This module contains the `cmd_abs_import` command handler.
"""

from __future__ import annotations

import argparse
import re as re_cli
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from shelfr.commands.abs._common import (
    console,
    fatal_error,
    print_dry_run,
    print_error,
    print_header,
    print_info,
    print_step,
    print_success,
    print_warning,
    should_ignore,
)

if TYPE_CHECKING:
    from rich.progress import TaskID


def cmd_abs_import(args: argparse.Namespace) -> int:
    """Import staged audiobooks to Audiobookshelf library.

    Moves staged books to ABS library structure with duplicate detection.
    Uses atomic rename to preserve hardlinks to seed folder.

    Duplicate detection uses in-memory ASIN index built from ABS API,
    always providing fresh data.
    """
    from rich.panel import Panel
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )
    from rich.table import Table
    from rich.tree import Tree

    from shelfr.abs import (
        AbsClient,
        build_asin_index,
        discover_staged_books,
        import_batch,
        trigger_scan_safe,
        validate_import_prerequisites,
    )
    from shelfr.abs.cleanup import CleanupStrategy, cleanup_source, prune_empty_dirs
    from shelfr.abs.client import AbsApiError, AbsAuthError, AbsConnectionError
    from shelfr.abs.importer import UnknownAsinPolicy, build_clean_file_name
    from shelfr.abs.paths import PathMapper
    from shelfr.config import build_cleanup_prefs, build_trump_prefs, reload_settings

    print_header("Audiobookshelf Import", dry_run=args.dry_run)

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    # Check if ABS is enabled
    if not hasattr(settings, "audiobookshelf") or not settings.audiobookshelf.enabled:
        print_warning("Audiobookshelf integration is not enabled in config")
        print_info("Set audiobookshelf.enabled: true in config.yaml")
        return 1

    abs_config = settings.audiobookshelf

    # Get managed library (for now, use first managed library)
    managed_libs = [lib for lib in abs_config.libraries if lib.mamfast_managed]
    if not managed_libs:
        fatal_error("No mamfast_managed libraries configured")
        print_info("Set mamfast_managed: true on a library in config.yaml")
        return 1

    # Use first managed library
    target_library = managed_libs[0]

    # Get ABS library root from path_map (destination for imports)
    if not abs_config.path_map:
        fatal_error("No path_map configured for Audiobookshelf")
        return 1

    # Use first path map's host path as ABS library root
    abs_library_root = Path(abs_config.path_map[0].host)

    # Get import source directory (library_root = where new audiobooks are staged)
    import_source = settings.paths.library_root

    # Validate prerequisites (no longer checks for index DB)
    print_step(1, 6, "Validating prerequisites")
    errors = validate_import_prerequisites(import_source, abs_library_root)
    if errors:
        for err in errors:
            print_error(err)
        return 1
    print_success("Prerequisites validated")

    # Discover books to import
    print_step(2, 6, "Discovering staged books")
    if args.paths:
        # Specific paths provided
        staging_folders = [p for p in args.paths if p.is_dir()]
        if not staging_folders:
            print_warning("No valid directories in provided paths")
            return 1
    else:
        staging_folders = discover_staged_books(import_source)

    if not staging_folders:
        print_info("No staged books to import")
        return 0

    print_info(f"Found {len(staging_folders)} audiobook(s) to import")

    # Determine duplicate policy
    dup_policy = args.duplicate_policy or abs_config.import_settings.duplicate_policy

    # Connect to ABS and build ASIN index
    print_step(3, 6, "Building ASIN index from ABS")
    try:
        client = AbsClient(
            host=abs_config.host,
            api_key=abs_config.api_key,
            timeout=abs_config.timeout_seconds,
        )
        # Test connection first
        user = client.authorize()
        print_success(f"Connected as {user.username}")
    except AbsAuthError as e:
        client.close()
        fatal_error(f"Authentication failed: {e}")
        return 1
    except (AbsConnectionError, ConnectionError, TimeoutError, OSError) as e:
        client.close()
        fatal_error(f"Failed to connect to ABS: {e}")
        return 1

    # Build in-memory ASIN index (fetches all items, caches for this session)
    try:
        asin_index = build_asin_index(client, target_library.id)
        print_success(f"Indexed {len(asin_index)} books with ASINs")
    except AbsApiError as e:
        client.close()
        fatal_error(f"Failed to fetch library items: {e}")
        return 1
    except (
        AbsConnectionError,
        AbsAuthError,
        ConnectionError,
        TimeoutError,
        OSError,
        ValueError,
    ) as e:
        client.close()  # Clean up on error
        fatal_error(f"Failed to build ASIN index: {e}")
        return 1

    # Determine if we should use ABS search for missing ASINs
    # Default from config (abs_search: true), can be disabled with --no-abs-search
    config_abs_search = abs_config.import_settings.abs_search
    no_abs_search_flag = getattr(args, "no_abs_search", False)
    use_abs_search = config_abs_search and not no_abs_search_flag

    # Use confidence from CLI if provided, else from config
    confidence = getattr(args, "confidence", None)
    if confidence is None:
        confidence = abs_config.import_settings.abs_search_confidence

    # Validate confidence threshold (common mistake: passing 75 instead of 0.75)
    if not 0.0 <= confidence <= 1.0:
        client.close()
        fatal_error(
            f"Invalid confidence value: {confidence}",
            "Confidence must be between 0.0 and 1.0 (e.g., 0.75 for 75%)",
        )
        return 1

    abs_client_for_import = client if use_abs_search else None
    if not use_abs_search:
        client.close()

    # Perform import
    print_step(4, 6, "Importing to library")
    print_info(f"Source: {import_source}")
    print_info(f"Target: {abs_library_root}")
    print_info(f"Duplicate policy: {dup_policy}")
    if use_abs_search:
        print_info(f"ABS search enabled (confidence: {confidence:.0%})")
    else:
        print_info("ABS search disabled (set abs_search: true in config or remove --no-abs-search)")

    # Get unknown ASIN policy from config
    unknown_asin_policy_str = abs_config.import_settings.unknown_asin_policy
    # UnknownAsinPolicy enum uses lowercase values (import, quarantine, skip)
    try:
        unknown_asin_policy = UnknownAsinPolicy(unknown_asin_policy_str.lower())
    except ValueError:
        allowed = ", ".join([p.value for p in UnknownAsinPolicy])
        if use_abs_search:
            client.close()
        fatal_error(
            f"Invalid unknown_asin_policy: '{unknown_asin_policy_str}'",
            f"Allowed values: {allowed}. Update import_settings.unknown_asin_policy in config.yaml",
        )
        return 1
    quarantine_path_str = abs_config.import_settings.quarantine_path
    quarantine_path = Path(quarantine_path_str) if quarantine_path_str else None

    # Get ignore patterns from config
    ignore_patterns = abs_config.import_settings.ignore_file_extensions or []

    print_info(f"Unknown ASIN policy: {unknown_asin_policy_str}")
    if quarantine_path:
        print_info(f"Quarantine path: {quarantine_path}")
    if ignore_patterns:
        print_info(f"Ignoring file patterns: {', '.join(ignore_patterns)}")

    # Handle --no-metadata CLI flag override (use local copy to avoid mutating global config)
    no_metadata = getattr(args, "no_metadata", False)
    import_settings = abs_config.import_settings
    if no_metadata:
        # Create modified copy with metadata generation disabled
        import_settings = replace(
            abs_config.import_settings,
            generate_metadata_json=False,
            metadata_json_fallback=False,
        )
        print_info("Metadata.json generation disabled (--no-metadata)")
    elif import_settings.generate_metadata_json:
        print_info("Metadata.json generation enabled")

    if args.dry_run:
        print_dry_run(f"Would import {len(staging_folders)} book(s)")

    # Build trumping preferences from config with CLI overrides
    trump_prefs = build_trump_prefs(
        import_settings.trumping,
        enabled_override=False if args.no_trump else None,
        aggressiveness_override=args.trump_aggressiveness,
    )
    if trump_prefs:
        print_info(f"Trumping enabled (aggressiveness: {trump_prefs.aggressiveness.value})")
    elif args.no_trump:
        print_info("Trumping disabled (--no-trump)")

    # Build cleanup preferences from config with CLI overrides
    # Cleanup will run as a separate Step 5 after import, not during import_batch
    no_cleanup = getattr(args, "no_cleanup", False)
    cleanup_strategy_override = "none" if no_cleanup else getattr(args, "cleanup_strategy", None)
    cleanup_path_override = getattr(args, "cleanup_path", None)
    cleanup_path_override_str = str(cleanup_path_override) if cleanup_path_override else None

    cleanup_prefs = build_cleanup_prefs(
        import_settings.cleanup,
        strategy_override=cleanup_strategy_override,
        cleanup_path_override=cleanup_path_override_str,
    )

    # Build path mapper for container↔host conversion (needed for trumping)
    path_mapper: PathMapper | None = None
    if abs_config.path_map:
        path_mappings = [{"container": pm.container, "host": pm.host} for pm in abs_config.path_map]
        path_mapper = PathMapper(mappings=path_mappings) if path_mappings else None

    # Track the progress task ID so callback can update it
    progress_task_id: TaskID | None = None
    progress_ctx: Progress | None = None

    def progress_callback(current: int, total: int, folder: Path) -> None:
        """Update progress bar with current book being processed."""
        nonlocal progress_task_id
        if progress_task_id is not None and progress_ctx is not None:
            # Truncate folder name to fit nicely
            book_name = folder.name[:50] + "..." if len(folder.name) > 50 else folder.name
            progress_ctx.update(progress_task_id, completed=current, current_book=book_name)

    try:
        # Create progress display
        progress_ctx = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TextColumn("[dim]{task.fields[current_book]}[/dim]"),
            console=console,
            transient=False,  # Keep visible after completion
        )

        with progress_ctx:
            progress_task_id = progress_ctx.add_task(
                "Importing",
                total=len(staging_folders),
                current_book="",
            )

            result = import_batch(
                staging_folders=staging_folders,
                library_root=abs_library_root,
                asin_index=asin_index,
                abs_client=abs_client_for_import,
                abs_search_confidence=confidence,
                staging_root=import_source,
                duplicate_policy=dup_policy,
                unknown_asin_policy=unknown_asin_policy,
                quarantine_path=quarantine_path,
                ignore_patterns=ignore_patterns,
                trump_prefs=trump_prefs,
                path_mapper=path_mapper,
                cleanup_prefs=None,  # Cleanup runs separately in Step 5
                source_paths={f: f for f in staging_folders},  # 1:1 mapping in staging
                seed_root=settings.paths.seed_root,
                preferred_asin_region=settings.audnex.preferred_asin_region,
                generate_metadata_json=import_settings.generate_metadata_json,
                metadata_json_fallback=import_settings.metadata_json_fallback,
                progress_callback=progress_callback,
                dry_run=args.dry_run,
            )

            # Mark as complete
            progress_ctx.update(
                progress_task_id,
                completed=len(staging_folders),
                current_book="Done!",
            )

    except (OSError, ValueError, RuntimeError) as e:
        if use_abs_search:
            client.close()  # Clean up on error
        fatal_error(f"Import failed: {e}")
        return 1

    # Close client if we kept it open for ABS search
    if use_abs_search:
        client.close()

    # Track categories for summary
    asin_count = 0
    no_asin_count = 0
    heur_count = 0

    # Display results
    if result.results:
        console.print()
        console.print("[bold]Import Results[/bold]")
        console.print()

        # Legend for status tags
        console.print("[dim]Legend:[/dim]")
        console.print("  [bold green][ASIN][/bold green]     Matched by ASIN in ABS index")
        console.print("  [bold yellow][NO-ASIN][/bold yellow]  No ASIN; imported under Unknown/")
        console.print(
            "  [bold magenta][HEUR][/bold magenta]     "
            "Heuristic path (no ASIN; guessed author/structure)"
        )
        console.print()

        # Build tree data for final layout preview
        tree_data: dict[str, dict[str, dict[str, list[str]]]] = {}

        for r in result.results:
            # Determine classification
            has_asin = bool(r.asin)
            is_unknown_author = False
            is_heuristic = False

            if r.parsed:
                is_unknown_author = r.parsed.author in ("Unknown", "", None)
                # Heuristic: no series info and no year typically means less metadata
                is_heuristic = not r.parsed.series and not r.parsed.year and not has_asin

            if has_asin and not is_unknown_author:
                asin_count += 1
                class_tag = "[bold green][ASIN][/bold green]"
                class_desc = "matched in ABS index"
                if r.asin:
                    class_desc = f"{r.asin} matched in ABS index"
            elif has_asin and is_unknown_author:
                asin_count += 1  # Still has ASIN, just unknown author
                class_tag = "[bold yellow][ASIN][/bold yellow]"
                class_desc = f"{r.asin} matched (author unknown)"
            elif is_heuristic:
                heur_count += 1
                class_tag = "[bold magenta][HEUR][/bold magenta]"
                class_desc = "heuristic path (no ASIN; guessed author/structure)"
            else:
                no_asin_count += 1
                class_tag = "[bold yellow][NO-ASIN][/bold yellow]"
                class_desc = "no ASIN in folder or mediainfo"

            # Status icon and color
            if r.status in ("success", "trump_replaced"):
                status_icon = "[green]✓[/green]"
            elif r.status in ("duplicate", "skipped", "trump_kept_existing", "trump_rejected"):
                status_icon = "[yellow]⏭[/yellow]"
            else:
                status_icon = "[red]✗[/red]"

            # Main line: status icon, folder name
            console.print(f"{status_icon} [cyan]{r.staging_path.name}[/cyan]")

            # Classification line with description
            console.print(f"  {class_tag} {class_desc}")

            # Source path
            console.print(f"  [dim][SRC][/dim] {r.staging_path}")

            # Destination path and file handling
            if r.status == "success" and r.target_path:
                console.print(f"  [dim][DST][/dim] {r.target_path}")

                # Build tree data for this book
                # Path structure: library_root/Author/[Series/]FolderName
                try:
                    rel_path = r.target_path.relative_to(abs_library_root)
                    parts = rel_path.parts

                    if len(parts) >= 1:
                        author = parts[0]
                        if len(parts) == 2:
                            # No series: Author/FolderName
                            series = ""
                            folder_name = parts[1]
                        elif len(parts) >= 3:
                            # With series: Author/Series/FolderName
                            series = parts[1]
                            folder_name = parts[2]
                        else:
                            # Just author folder somehow
                            series = ""
                            folder_name = author

                        if author not in tree_data:
                            tree_data[author] = {}
                        if series not in tree_data[author]:
                            tree_data[author][series] = {}
                        if folder_name not in tree_data[author][series]:
                            tree_data[author][series][folder_name] = []
                except ValueError:
                    pass  # Can't make relative path

                # List files with rename preview (excluding ignored files)
                source_folder = r.staging_path if args.dry_run else r.target_path
                if source_folder.exists():
                    files = sorted(
                        f.name
                        for f in source_folder.iterdir()
                        if f.is_file() and not should_ignore(f.name, ignore_patterns)
                    )

                    # In dry-run, compute what files would be renamed to
                    # Multi-file books preserve track numbers (e.g., " - 01")
                    rename_map: dict[str, str] = {}
                    audio_exts = {".m4b", ".m4a", ".mp3", ".ogg", ".flac", ".opus"}
                    audio_count = sum(
                        1
                        for f in source_folder.iterdir()
                        if f.is_file() and f.suffix.lower() in audio_exts
                    )
                    is_multi_file = audio_count > 1

                    if args.dry_run and r.parsed:
                        try:
                            parsed = r.parsed
                            base_clean = build_clean_file_name(parsed, extension="")
                            for f in source_folder.iterdir():
                                if not f.is_file() or should_ignore(f.name, ignore_patterns):
                                    continue
                                ext = f.suffix.lower()
                                if f.name.lower().endswith(".metadata.json"):
                                    ext = ".metadata.json"

                                # For multi-file audio, extract and preserve track suffix
                                track_suffix = ""
                                if is_multi_file and ext in audio_exts:
                                    track_match = re_cli.search(r"[\s_-]+(\d{1,3})$", f.stem)
                                    if track_match:
                                        track_num = track_match.group(1)
                                        track_suffix = f" - {int(track_num):02d}"
                                    else:
                                        # No track number - skip rename preview
                                        continue

                                clean_name = f"{base_clean}{track_suffix}{ext}"
                                if f.name != clean_name:
                                    rename_map[f.name] = clean_name
                        except (ValueError, KeyError):
                            pass  # Can't build clean file name; skip rename preview

                    # Show files
                    if files:
                        console.print("  [dim]Files:[/dim]")
                        for filename in files:
                            new_name = rename_map.get(filename)
                            if new_name and new_name != filename:
                                console.print(
                                    f"    [dim]{filename}[/dim]\n      → [green]{new_name}[/green]"
                                )
                            else:
                                console.print(f"    [dim]{filename}[/dim]")

                            # Add to tree data using path structure
                            if r.target_path:
                                try:
                                    rel_path = r.target_path.relative_to(abs_library_root)
                                    parts = rel_path.parts
                                    if len(parts) >= 2:
                                        author = parts[0]
                                        series = parts[1] if len(parts) >= 3 else ""
                                        folder_name = parts[-1]
                                        final_name = new_name or filename
                                        if folder_name in tree_data.get(author, {}).get(series, {}):
                                            tree_data[author][series][folder_name].append(
                                                final_name
                                            )
                                except ValueError:
                                    pass  # Can't make relative path; skip adding file to tree

            elif r.status == "trump_replaced":
                # Trumping: replaced existing with new (better quality)
                console.print(f"  [green]↻ TRUMPED:[/green] {r.error or 'Better quality'}")
                if r.target_path:
                    console.print(f"  [dim][DST][/dim] {r.target_path}")
            elif r.status == "trump_kept_existing":
                # Trumping: kept existing (no improvement)
                reason = r.error or "No quality improvement"
                console.print(f"  [dim]→  KEPT EXISTING:[/dim] {reason}")
            elif r.status == "trump_rejected":
                # Trumping: rejected incoming (worse quality)
                console.print(f"  [yellow]✗ REJECTED:[/yellow] {r.error or 'Lower quality'}")
            elif r.status == "duplicate" and r.error:
                if "Already exists at " in r.error:
                    existing_path = r.error.replace("Already exists at ", "")
                    console.print(f"  [dim][DST][/dim] [yellow]EXISTS:[/yellow] {existing_path}")
                else:
                    console.print("  [dim][DST][/dim] [yellow]Duplicate[/yellow]")
            elif r.error:
                console.print(f"  [red]Error:[/red] {r.error}")

            console.print()

        # Render library tree preview (dry-run only, and only if we have data)
        if args.dry_run and tree_data and result.success_count > 0:
            console.print()
            console.print("[bold]Planned Library Layout[/bold]")
            console.print()

            tree = Tree(f"[bold cyan]{abs_library_root}[/bold cyan]")

            for author in sorted(tree_data.keys()):
                # Highlight "Unknown" author branch as needing attention
                if author == "Unknown":
                    author_branch = tree.add(
                        f"[bold yellow]{author}[/bold yellow] [dim](needs ASIN)[/dim]"
                    )
                else:
                    author_branch = tree.add(f"[blue]{author}[/blue]")
                series_dict = tree_data[author]

                for series in sorted(series_dict.keys()):
                    if series:
                        series_branch = author_branch.add(f"[magenta]{series}[/magenta]")
                        parent = series_branch
                    else:
                        parent = author_branch

                    for folder_name in sorted(series_dict[series].keys()):
                        folder_branch = parent.add(f"[cyan]{folder_name}[/cyan]")
                        for file_name in sorted(series_dict[series][folder_name]):
                            folder_branch.add(f"[dim]{file_name}[/dim]")

            console.print(tree)
            console.print()

    # ─────────────────────────────────────────────────────────────────────────
    # Step 5: Post-import cleanup of source folders
    # ─────────────────────────────────────────────────────────────────────────
    cleanup_success_count = 0
    cleanup_skipped_count = 0
    cleanup_failed_count = 0
    # Track which source paths would be cleaned (for dry-run "remaining" simulation)
    cleanup_would_succeed_paths: set[Path] = set()
    cleanup_would_skip_paths: set[Path] = set()

    if cleanup_prefs.strategy != CleanupStrategy.NONE:
        print_step(5, 6, "Post-import cleanup")

        # Display cleanup settings
        print_info(f"Strategy: {cleanup_prefs.strategy.value}")
        if cleanup_prefs.strategy == CleanupStrategy.MOVE and cleanup_prefs.cleanup_path:
            print_info(f"Cleanup path: {cleanup_prefs.cleanup_path}")
        if cleanup_prefs.require_seed_exists:
            print_info("Requires seed hardlinks to exist")

        # Only cleanup successful imports that weren't trumped
        # Note: trump_replaced files were already MOVED during import (not hardlinked),
        # so their source paths no longer exist and cleanup should skip them
        cleanup_eligible = [r for r in result.results if r.status == "success"]

        if not cleanup_eligible:
            print_info("No eligible folders for cleanup (no successful imports)")
        else:
            if args.dry_run:
                print_dry_run(f"Would cleanup {len(cleanup_eligible)} source folder(s)")

            # Run cleanup with progress
            cleanup_progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                TextColumn("[dim]{task.fields[current_folder]}[/dim]"),
                console=console,
                transient=False,
            )

            with cleanup_progress:
                cleanup_task = cleanup_progress.add_task(
                    "Cleaning up",
                    total=len(cleanup_eligible),
                    current_folder="",
                )

                for i, r in enumerate(cleanup_eligible):
                    # Update progress
                    name = r.staging_path.name
                    folder_name = name[:40] + "..." if len(name) > 40 else name
                    cleanup_progress.update(cleanup_task, completed=i, current_folder=folder_name)

                    # Source path is the staging_path for direct staging imports
                    source_path = r.staging_path

                    # Skip cleanup if source was already moved during import
                    # This happens for direct staging imports where staging_folder == source
                    if not args.dry_run and not source_path.exists():
                        cleanup_success_count += 1  # Count as success (already moved)
                        cleanup_would_succeed_paths.add(source_path)
                        continue

                    cleanup_result = cleanup_source(
                        source_path=source_path,
                        prefs=cleanup_prefs,
                        seed_root=settings.paths.seed_root,
                        asin=r.asin,
                        dry_run=args.dry_run,
                    )

                    if cleanup_result.status in ("success", "dry_run"):
                        cleanup_success_count += 1
                        cleanup_would_succeed_paths.add(source_path)
                    elif cleanup_result.status == "skipped":
                        cleanup_skipped_count += 1
                        cleanup_would_skip_paths.add(source_path)
                    else:
                        cleanup_failed_count += 1

                # Mark complete
                cleanup_progress.update(
                    cleanup_task,
                    completed=len(cleanup_eligible),
                    current_folder="Done!",
                )

        # Prune empty directories from staging area
        # This handles empty author/series dirs left by shutil.move() during trumping
        pruned_count = 0
        if cleanup_prefs.prune_empty_dirs:
            if args.dry_run:
                pruned_count = prune_empty_dirs(import_source, dry_run=True)
                if pruned_count > 0:
                    print_dry_run(f"Would prune {pruned_count} empty director(y/ies)")
            else:
                pruned_count = prune_empty_dirs(import_source, dry_run=False)
                if pruned_count > 0:
                    print_info(f"Pruned {pruned_count} empty director(y/ies)")

        # Show remaining folders in source directory after cleanup
        # In dry-run: simulate what would remain (trumped + cleanup-skipped)
        # In real run: show actual filesystem state
        console.print()

        if args.dry_run:
            # Simulate: remaining = all sources - cleanup successes
            # Trumped folders stay (not imported), cleanup-skipped stay (no seed)
            trumped_paths = {
                r.staging_path
                for r in result.results
                if r.status in ("trump_kept_existing", "trump_rejected", "duplicate")
            }
            # Remaining = trumped + cleanup-skipped (cleanup successes would be moved)
            simulated_remaining = trumped_paths | cleanup_would_skip_paths

            print_info(f"Would remain in source directory ({len(simulated_remaining)} folder(s)):")

            if simulated_remaining:
                remaining_tree = Tree(f"[dim]{import_source}[/dim]")
                sorted_remaining = sorted(simulated_remaining, key=lambda p: p.name)
                for folder in sorted_remaining[:20]:
                    # Color-code by reason
                    if folder in trumped_paths:
                        remaining_tree.add(f"[dim]{folder.name}[/dim] [cyan](trumped)[/cyan]")
                    else:
                        remaining_tree.add(f"[yellow]{folder.name}[/yellow] [red](no seed)[/red]")
                if len(sorted_remaining) > 20:
                    remaining_tree.add(f"[dim]... and {len(sorted_remaining) - 20} more[/dim]")
                console.print(remaining_tree)
            else:
                print_success("Source directory would be empty (all folders cleaned up)")
        else:
            # Real run: show actual filesystem state
            print_info("Remaining in source directory:")
            remaining_folder_names: list[str] = []
            try:
                if import_source.exists():
                    for item in sorted(import_source.iterdir()):
                        if item.is_dir() and not item.name.startswith("."):
                            remaining_folder_names.append(item.name)
            except OSError:
                pass

            if remaining_folder_names:
                remaining_tree = Tree(f"[dim]{import_source}[/dim]")
                for folder_name in remaining_folder_names[:20]:
                    remaining_tree.add(f"[yellow]{folder_name}[/yellow]")
                if len(remaining_folder_names) > 20:
                    remaining_tree.add(
                        f"[dim]... and {len(remaining_folder_names) - 20} more[/dim]"
                    )
                console.print(remaining_tree)
            else:
                print_success("Source directory is empty (all folders cleaned up)")

        console.print()

    else:
        # No cleanup - skip to step 6
        if no_cleanup:
            print_info("Cleanup disabled (--no-cleanup), skipping Step 5")
        # Implicit: cleanup strategy is "none" in config

    # Summary
    print_step(6, 6, "Complete")

    # Build summary panel
    summary_table = Table(show_header=False, box=None, padding=(0, 2))
    summary_table.add_column("Label", style="dim")
    summary_table.add_column("Value", justify="right")

    total_books = len(result.results)
    needs_review_count = no_asin_count + heur_count

    summary_table.add_row("Books processed:", str(total_books))
    summary_table.add_row(
        "  [bold green][ASIN][/bold green]",
        f"[green]{asin_count}[/green]",
    )
    summary_table.add_row(
        "  [bold yellow][NO-ASIN][/bold yellow]",
        f"[yellow]{no_asin_count}[/yellow]",
    )
    summary_table.add_row(
        "  [bold magenta][HEUR][/bold magenta]",
        f"[magenta]{heur_count}[/magenta]",
    )
    summary_table.add_row("", "")
    summary_table.add_row("Duplicate policy:", dup_policy)
    summary_table.add_row("Destination root:", str(abs_library_root))
    summary_table.add_row("", "")

    if args.dry_run:
        summary_table.add_row("Ready to import:", f"[green]{result.success_count}[/green]")
    else:
        summary_table.add_row("Imported:", f"[green]{result.success_count}[/green]")

    if result.duplicate_count > 0:
        summary_table.add_row("Skipped (duplicate):", f"[yellow]{result.duplicate_count}[/yellow]")
    if result.failed_count > 0:
        summary_table.add_row("Failed:", f"[red]{result.failed_count}[/red]")

    # Trumping statistics (if any trumping occurred)
    if result.trump_replaced_count > 0:
        summary_table.add_row(
            "Trumped (replaced):", f"[green]{result.trump_replaced_count}[/green]"
        )
    if result.trump_kept_existing_count > 0:
        summary_table.add_row(
            "Trumped (kept existing):", f"[dim]{result.trump_kept_existing_count}[/dim]"
        )
    if result.trump_rejected_count > 0:
        summary_table.add_row(
            "Trumped (rejected):", f"[yellow]{result.trump_rejected_count}[/yellow]"
        )

    # Cleanup statistics (if cleanup was enabled)
    # Use "would" language in dry-run mode to make it clear these are predictions
    if cleanup_success_count > 0:
        if args.dry_run:
            summary_table.add_row(
                "Cleanup (would succeed):", f"[green]{cleanup_success_count}[/green]"
            )
        else:
            summary_table.add_row("Cleanup (success):", f"[green]{cleanup_success_count}[/green]")
    if cleanup_skipped_count > 0:
        if args.dry_run:
            summary_table.add_row("Cleanup (would skip):", f"[dim]{cleanup_skipped_count}[/dim]")
        else:
            summary_table.add_row("Cleanup (skipped):", f"[dim]{cleanup_skipped_count}[/dim]")
    if cleanup_failed_count > 0:
        if args.dry_run:
            summary_table.add_row("Cleanup (would fail):", f"[red]{cleanup_failed_count}[/red]")
        else:
            summary_table.add_row("Cleanup (failed):", f"[red]{cleanup_failed_count}[/red]")

    if needs_review_count > 0:
        # Build breakdown of what needs review
        review_parts: list[str] = []
        if no_asin_count > 0:
            review_parts.append(f"[NO-ASIN]={no_asin_count}")
        if heur_count > 0:
            review_parts.append(f"[HEUR]={heur_count}")
        review_breakdown = f" ({', '.join(review_parts)})" if review_parts else ""
        summary_table.add_row(
            "Needs review:",
            f"[yellow]{needs_review_count}[/yellow]{review_breakdown}",
        )

    if args.dry_run:
        panel_title = "[bold yellow]DRY RUN Summary[/bold yellow]"
        panel_border = "yellow"
        footer = "\n[yellow]⚠  DRY RUN: No files were moved or renamed[/yellow]"
    else:
        panel_title = "[bold green]Import Summary[/bold green]"
        panel_border = "green"
        footer = f"\n[green]✓ Import completed: {result.success_count} book(s) imported[/green]"

    console.print()
    console.print(Panel(summary_table, title=panel_title, border_style=panel_border))
    console.print(footer)
    console.print()

    # Trigger ABS scan (if not dry run and not --no-scan)
    if not args.dry_run and not args.no_scan and result.success_count > 0:
        trigger_mode = abs_config.import_settings.trigger_scan
        if trigger_mode != "none":
            try:
                with AbsClient(
                    host=abs_config.host,
                    api_key=abs_config.api_key,
                    timeout=abs_config.timeout_seconds,
                ) as scan_client:
                    if trigger_scan_safe(scan_client, target_library.id):
                        print_success("Triggered ABS library scan")
                    else:
                        print_warning(
                            "Failed to trigger ABS scan (files will appear on next scheduled scan)"
                        )
            except Exception as e:
                print_warning(f"Could not trigger ABS scan: {e}")

    return 1 if result.failed_count > 0 else 0


__all__ = ["cmd_abs_import"]
