"""ABS init command - verify Audiobookshelf connection.

This module contains the `cmd_abs_init` command handler.
"""

from __future__ import annotations

import argparse

from shelfr.commands.abs._common import (
    console,
    fatal_error,
    print_error,
    print_header,
    print_info,
    print_step,
    print_success,
    print_warning,
)


def cmd_abs_init(args: argparse.Namespace) -> int:
    """Initialize and verify Audiobookshelf connection.

    Tests API connectivity and discovers available libraries.
    """
    import httpx

    from shelfr.abs.client import AbsApiError, AbsAuthError, AbsClient, AbsConnectionError
    from shelfr.abs.paths import PathMapper
    from shelfr.config import reload_settings

    print_header("Audiobookshelf Init", dry_run=args.dry_run)

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    # Check if ABS is enabled in config
    if not hasattr(settings, "audiobookshelf") or not settings.audiobookshelf.enabled:
        print_warning("Audiobookshelf integration is not enabled in config")
        print_info("Set audiobookshelf.enabled: true in config.yaml")
        return 1

    abs_config = settings.audiobookshelf

    # Step 1: Test connection
    print_step(1, 3, "Testing connection to Audiobookshelf")
    print_info(f"Host: {abs_config.host}")

    with AbsClient.from_config(abs_config) as client:
        try:
            user = client.authorize()
            print_success(f"Connected as: {user.username} ({user.user_type})")
            if user.has_admin:
                print_info("User has admin permissions")
        except AbsAuthError as e:
            print_error(f"Authentication failed: {e}")
            print_info("Check your API key in config/config.yaml or .env")
            return 1
        except AbsConnectionError as e:
            print_error(f"Connection failed: {e}")
            print_info("Check that Audiobookshelf is running and accessible")
            return 1

        # Step 2: List libraries
        print_step(2, 3, "Discovering libraries")

        try:
            libraries = client.get_libraries()
        except (AbsApiError, AbsAuthError, AbsConnectionError) as e:
            print_error(f"Failed to fetch libraries: {e}")
            return 1
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as e:
            print_error(f"Network error while fetching libraries: {e}")
            return 1

        # Filter to audiobook libraries only
        audiobook_libs = [lib for lib in libraries if lib.media_type == "book"]

        if not audiobook_libs:
            print_warning("No audiobook libraries found")
            return 1

        print_success(f"Found {len(audiobook_libs)} audiobook library(ies)")

        # Show configured vs discovered libraries
        configured_ids = {lib.id for lib in abs_config.libraries}

        for lib in audiobook_libs:
            is_configured = lib.id in configured_ids
            configured_lib = next((cl for cl in abs_config.libraries if cl.id == lib.id), None)
            managed = bool(configured_lib and configured_lib.mamfast_managed)

            status = ""
            if is_configured and managed:
                status = " [cyan](mamfast_managed)[/]"
            elif is_configured:
                status = " [dim](configured)[/]"
            else:
                status = " [yellow](not in config)[/]"

            folders_str = ", ".join(lib.folders) if lib.folders else "(no folders)"
            console.print(f"  • [bold]{lib.name}[/]{status}")
            console.print(f"    ID: [dim]{lib.id}[/]")
            console.print(f"    Folders: [dim]{folders_str}[/]")

        # Step 3: Show path mappings
        print_step(3, 3, "Path mapping configuration")

        if abs_config.docker_mode:
            if abs_config.path_map:
                print_info("Docker mode enabled with path mappings:")
                for pm in abs_config.path_map:
                    mapper = PathMapper(pm.container, pm.host)
                    console.print(f"  • Container: [cyan]{mapper.container_prefix}[/]")
                    console.print(f"    Host:      [cyan]{mapper.host_prefix}[/]")

                    # Test the mapping with a sample path
                    sample_container = f"{mapper.container_prefix}/Author/Book"
                    sample_host = mapper.to_host(sample_container)
                    console.print(f"    Example:   {sample_container} → [dim]{sample_host}[/]")
            else:
                print_warning("Docker mode enabled but no path_map configured")
                print_info("Add path_map to audiobookshelf config for path translation")
        else:
            print_info("Docker mode disabled (paths used as-is)")

        # Summary
        console.print()
        print_success("Audiobookshelf connection verified")

        # Show hints for next steps
        managed_libs = [lib for lib in abs_config.libraries if lib.mamfast_managed]
        if not managed_libs:
            print_info("Next: Add library IDs to config with mamfast_managed: true")
            print_info("Then run: shelfr abs-import")
        else:
            print_info(
                f"Next: Run 'shelfr abs-import' to import staged books "
                f"to {len(managed_libs)} managed library(ies)"
            )

    return 0


__all__ = ["cmd_abs_init"]
