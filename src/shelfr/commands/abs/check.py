"""ABS check command - check for duplicate ASINs in ABS library.

This module contains the `cmd_abs_check_duplicate` command handler.
"""

from __future__ import annotations

import argparse

from shelfr.abs import AbsClient, asin_exists, build_asin_index, is_valid_asin
from shelfr.abs.client import AbsApiError, AbsAuthError, AbsConnectionError
from shelfr.commands.abs._common import (
    fatal_error,
    print_error,
    print_info,
    print_success,
    print_warning,
)
from shelfr.config import reload_settings


def cmd_abs_check_duplicate(args: argparse.Namespace) -> int:
    """Check if an ASIN already exists in the ABS library.

    Quick lookup for duplicate detection using in-memory index from ABS API.
    This command makes a network call to ABS to retrieve the library metadata,
    builds an in-memory ASIN index, and checks if the specified ASIN exists.

    Args:
        args: Parsed command-line arguments with the following attributes:
            - asin (str): The ASIN to check (will be normalized to uppercase)
            - config (Path): Path to the configuration file
            - dry_run (bool, optional): Dry-run mode (not used in this command)

    Returns:
        int: Exit code indicating result:
            - 0: ASIN not found (safe to import)
            - 1: ASIN exists in library OR error occurred

    Raises:
        This function handles all exceptions internally and returns appropriate
        exit codes. Does not propagate exceptions to caller.

        Internally catches and handles:
            - FileNotFoundError: When config file doesn't exist
            - AbsApiError: ABS API errors during library query
            - AbsAuthError: ABS authentication/authorization failures
            - AbsConnectionError: Network/connection issues with ABS
            - Exception: Any other unexpected errors

    Side Effects:
        - Prints status messages to console using Rich formatting
        - Makes network call to ABS API to retrieve library metadata
        - Builds in-memory ASIN index from library items

    Examples:
        >>> # Typical usage via argparse namespace
        >>> args = argparse.Namespace(
        ...     asin="B09GHD1R2R",
        ...     config=Path("config/config.yaml"),
        ...     dry_run=False
        ... )
        >>> exit_code = cmd_abs_check_duplicate(args)
        >>> # Returns 0 if ASIN not found, 1 if exists or error
    """
    asin = args.asin.upper().strip()

    # Validate ASIN format
    if not is_valid_asin(asin):
        print_error(f"Invalid ASIN format: {asin}")
        print_info("ASIN: 10 chars (B + 9 alphanumeric e.g. B09GHD1R2R, or ISBN-10)")
        return 1

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    # Check if ABS is enabled
    if not hasattr(settings, "audiobookshelf") or not settings.audiobookshelf.enabled:
        print_warning("Audiobookshelf integration is not enabled in config")
        return 1

    abs_config = settings.audiobookshelf

    # Get managed library
    managed_libs = [lib for lib in abs_config.libraries if lib.mamfast_managed]
    if not managed_libs:
        fatal_error("No mamfast_managed libraries configured")
        return 1
    target_library = managed_libs[0]

    # Connect to ABS and build index
    print_info(f"Checking ASIN {asin} against ABS library...")
    try:
        with AbsClient(
            host=abs_config.host,
            api_key=abs_config.api_key,
            timeout=abs_config.timeout_seconds,
        ) as client:
            asin_index = build_asin_index(client, target_library.id)

            # Check index
            exists, _existing_path = asin_exists(asin_index, asin)

            if exists:
                entry = asin_index[asin]
                print_warning(f"ASIN {asin} already exists:")
                print_info(f"  Title: {entry.title}")
                if entry.author:
                    print_info(f"  Author: {entry.author}")
                print_info(f"  Path: {entry.path}")
                return 1
            else:
                print_success(f"ASIN {asin} not found in library - safe to import")
                return 0
    except (AbsApiError, AbsAuthError, AbsConnectionError) as e:
        fatal_error(f"ABS error: {e}")
        return 1
    except Exception as e:
        fatal_error(f"Unexpected error querying ABS: {e}")
        return 1


__all__ = ["cmd_abs_check_duplicate"]
