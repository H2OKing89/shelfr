"""Utility and status commands for MAMFast CLI.

These commands handle status display, health checks, validation,
and configuration inspection.
"""

from __future__ import annotations

import argparse
import json as json_module
import logging
from datetime import datetime
from pathlib import Path
from typing import cast

import yaml
from pydantic import ValidationError as PydanticValidationError

from shelfr.console import (
    console,
    fatal_error,
    print_check_category,
    print_config_section,
    print_directory_status,
    print_error,
    print_header,
    print_info,
    print_status_table,
    print_success,
    print_validation_summary,
    print_warning,
)

logger = logging.getLogger(__name__)


def cmd_status(args: argparse.Namespace) -> int:
    """Show status."""
    from shelfr.config import reload_settings
    from shelfr.utils.state import get_stats, load_state

    print_header("Status")

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    # Stats
    stats = get_stats()
    console.print("[title]Processing Stats[/]")
    console.print(f"  Processed: [success]{stats['processed']}[/]")
    console.print(f"  Failed: [error]{stats['failed']}[/]")

    # Directories
    console.print("\n[title]Directories[/]")

    lib_root = settings.paths.library_root
    if lib_root.exists():
        book_count = len([d for d in lib_root.iterdir() if d.is_dir()])
        print_directory_status("Library", lib_root, True, book_count)
    else:
        print_directory_status("Library", lib_root, False)

    seed_root = settings.paths.seed_root
    if seed_root.exists():
        seed_count = len([d for d in seed_root.iterdir() if d.is_dir()])
        print_directory_status("Seed Root", seed_root, True, seed_count)
    else:
        print_directory_status("Seed Root", seed_root, False)

    torrent_out = settings.paths.torrent_output
    if torrent_out.exists():
        torrent_count = len(list(torrent_out.glob("*.torrent")))
        print_directory_status("Torrents", torrent_out, True, torrent_count)
    else:
        print_directory_status("Torrents", torrent_out, False)

    # Recent processed/failed
    state = load_state()
    processed = state.get("processed", {})
    failed = state.get("failed", {})

    if processed or failed:
        console.print()
        print_status_table(processed, failed, limit=5)

    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Run health checks to verify environment setup."""
    from shelfr.config import reload_settings
    from shelfr.validation import (
        CheckCategory,
        ValidationResult,
        check_categories,
        check_config,
        check_paths,
        check_services,
    )

    print_header("MAMFast Health Check")

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1
    except PydanticValidationError as e:
        fatal_error(f"Config validation failed: {e}", "Fix validation errors in config.yaml")
        return 1
    except (ValueError, json_module.JSONDecodeError) as e:
        fatal_error(f"Config parse error: {e}", "Check YAML/JSON syntax in config files")
        return 1
    except Exception as e:
        fatal_error(f"Unexpected error loading config: {e}")
        return 1

    # Determine which checks to run
    run_config = args.config_only or not (args.paths_only or args.services_only)
    run_paths = args.paths_only or not (args.config_only or args.services_only)
    run_services = args.services_only or not (args.config_only or args.paths_only)
    run_categories = not (args.config_only or args.paths_only or args.services_only)

    result = ValidationResult()

    # Run selected checks using print_check_category helper
    if run_config:
        config_result = check_config(settings)
        result.merge(config_result)
        print_check_category(result, CheckCategory.CONFIG, "Configuration")

    if run_paths:
        paths_result = check_paths(settings)
        result.merge(paths_result)
        print_check_category(result, CheckCategory.PATHS, "Paths")

    if run_services:
        print_info("Checking connectivity (this may take a moment)...")
        services_result = check_services(settings)
        result.merge(services_result)
        print_check_category(result, CheckCategory.SERVICES, "Services")

    if run_categories:
        cat_result = check_categories(settings)
        result.merge(cat_result)
        print_check_category(result, CheckCategory.CATEGORIES, "Categories")

    # Summary using print_validation_summary helper
    console.print()
    print_validation_summary(result)

    return 0 if result.passed else 1


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate all discovered releases."""
    from shelfr.config import reload_settings
    from shelfr.discovery import get_new_releases, get_release_by_asin
    from shelfr.logging_setup import set_console_quiet
    from shelfr.utils.state import get_processed_identifiers
    from shelfr.validation import (
        DiscoveryValidation,
        ValidationReport,
    )

    set_console_quiet(True)

    output_json = getattr(args, "json", False)
    if not output_json:
        print_header("Validate Releases")

    try:
        reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        set_console_quiet(False)
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    # Get releases to validate
    if args.asin:
        release = get_release_by_asin(args.asin)
        if not release:
            set_console_quiet(False)
            print_error(f"Release not found: {args.asin}")
            return 1
        releases = [release]
    else:
        releases = get_new_releases()

    set_console_quiet(False)

    if not releases:
        if output_json:
            console.print(json_module.dumps({"releases": [], "summary": {"total": 0}}))
        else:
            print_info("No new releases found to validate")
        return 0

    # Run validation on each release
    processed = get_processed_identifiers()
    discovery_validator = DiscoveryValidation(processed_identifiers=processed)

    reports: list[ValidationReport] = []
    total_warnings = 0
    total_errors = 0

    for i, release in enumerate(releases, 1):
        # Create report
        report = ValidationReport(
            asin=release.asin,
            title=release.title or release.display_name,
            validated_at=datetime.now().isoformat(),
        )

        # Discovery validation
        discovery_result = discovery_validator.validate(release)
        report.discovery_result = discovery_result
        total_warnings += discovery_result.warning_count
        total_errors += discovery_result.error_count

        reports.append(report)

        # Print progress (non-JSON mode)
        if not output_json:
            status = "✅" if discovery_result.passed else "❌"
            console.print(f"\n[bold][{i}/{len(releases)}] {release.display_name}[/]")
            console.print(f"  ASIN: {release.asin or 'N/A'}")
            console.print(f"  Status: {status}")

            for check in discovery_result.checks:
                console.print(f"    {check.icon} {check.message}")

            if discovery_result.warning_count > 0:
                console.print(f"  [warning]⚠️ {discovery_result.warning_count} warning(s)[/]")
            if discovery_result.error_count > 0:
                console.print(f"  [error]❌ {discovery_result.error_count} error(s)[/]")

    # Output
    if output_json:
        output = {
            "releases": [r.to_dict() for r in reports],
            "summary": {
                "total": len(reports),
                "passed": sum(1 for r in reports if r.all_passed),
                "failed": sum(1 for r in reports if not r.all_passed),
                "total_warnings": total_warnings,
                "total_errors": total_errors,
            },
        }
        console.print(json_module.dumps(output, indent=2))
    else:
        # Summary
        console.print()
        passed_count = sum(1 for r in reports if r.all_passed)
        failed_count = len(reports) - passed_count

        if failed_count == 0 and total_warnings == 0:
            console.print(f"[success]Summary:[/] All {len(reports)} releases validated ✅")
        elif failed_count == 0:
            console.print(
                f"[success]Summary:[/] {passed_count}/{len(reports)} validated, "
                f"[warning]{total_warnings} warning(s)[/] ⚠️"
            )
        else:
            console.print(
                f"[error]Summary:[/] {passed_count}/{len(reports)} validated, "
                f"[error]{failed_count} failed[/], "
                f"[warning]{total_warnings} warning(s)[/]"
            )

    return 0 if total_errors == 0 else 1


def cmd_validate_config(args: argparse.Namespace) -> int:
    """Validate all configuration files."""
    from shelfr.schemas.naming import validate_naming_json

    print_header("Validate Configuration Files")

    # Determine where to look for supporting config files (naming.json, categories.json)
    # Priority: 1) Same directory as config file, 2) config/ subdirectory relative to parent
    if args.config:
        config_parent = args.config.parent
        # Check if files exist beside the config file first (standalone layout)
        if (config_parent / "naming.json").exists():
            config_dir = config_parent
            use_subdir = False
        else:
            # Fall back to config/ subdirectory (structured layout: project/config/config.yaml)
            config_dir = config_parent.parent
            use_subdir = True
    else:
        config_dir = Path(".")
        use_subdir = True

    errors_found = False

    # Validate naming.json
    if use_subdir:
        naming_path = config_dir / "config" / "naming.json"
    else:
        naming_path = config_dir / "naming.json"
    console.print(f"\n[bold]Checking:[/] {naming_path}")

    if not naming_path.exists():
        print_warning(f"naming.json not found at {naming_path}")
    else:
        try:
            with open(naming_path, encoding="utf-8") as f:
                data = json_module.load(f)

            schema = validate_naming_json(data)

            # Count rules for summary
            rule_count = (
                len(schema.format_indicators.phrases)
                + len(schema.genre_tags.phrases)
                + len(schema.series_suffixes.patterns)
                + len(schema.publisher_tags.phrases)
                + len(schema.subtitle_patterns.remove_patterns)
                + len(schema.subtitle_redundancy_rules.rules)
            )

            print_success(f"naming.json: valid (v{schema.version}, {rule_count} rules)")

            # Show breakdown
            print_info(f"  Format indicators: {len(schema.format_indicators.phrases)}")
            print_info(f"  Genre tags: {len(schema.genre_tags.phrases)}")
            print_info(f"  Series suffixes: {len(schema.series_suffixes.patterns)}")
            print_info(f"  Publisher tags: {len(schema.publisher_tags.phrases)}")
            print_info(
                f"  Subtitle remove patterns: {len(schema.subtitle_patterns.remove_patterns)}"
            )
            print_info(f"  Subtitle keep patterns: {len(schema.subtitle_patterns.keep_patterns)}")
            print_info(f"  Redundancy rules: {len(schema.subtitle_redundancy_rules.rules)}")
            print_info(f"  Author mappings: {len(schema.author_map)}")
            print_info(f"  Preserve exact: {len(schema.preserve_exact.titles)}")

        except json_module.JSONDecodeError as e:
            print_error(f"naming.json: invalid JSON - {e}")
            errors_found = True
        except PydanticValidationError as e:
            print_error("naming.json: validation failed")
            for error in e.errors():
                loc = " -> ".join(str(x) for x in error["loc"])
                print_error(f"  {loc}: {error['msg']}")
            errors_found = True

    # Validate config.yaml (basic check - loads without error)
    config_path = args.config if args.config else config_dir / "config" / "config.yaml"
    console.print(f"\n[bold]Checking:[/] {config_path}")

    if not config_path.exists():
        print_warning(f"config.yaml not found at {config_path}")
    else:
        try:
            from shelfr.config import reload_settings

            settings = reload_settings(config_file=config_path)
            print_success("config.yaml: valid (loaded successfully)")
            print_info(f"  Library root: {settings.paths.library_root}")
            print_info(f"  Seed root: {settings.paths.seed_root}")
        except FileNotFoundError as e:
            print_error(f"config.yaml: file not found - {e}")
            errors_found = True
        except PermissionError as e:
            print_error(f"config.yaml: permission denied - {e}")
            errors_found = True
        except yaml.YAMLError as e:
            print_error(f"config.yaml: YAML parsing error - {e}")
            errors_found = True
        except PydanticValidationError as e:
            print_error("config.yaml: validation failed")
            for error in e.errors():
                loc = " -> ".join(str(x) for x in error["loc"])
                print_error(f"  {loc}: {error['msg']}")
            errors_found = True
        except Exception as e:
            print_error(f"config.yaml: unexpected error - {e}")
            errors_found = True

    # Validate categories.json
    if use_subdir:
        categories_path = config_dir / "config" / "categories.json"
    else:
        categories_path = config_dir / "categories.json"
    console.print(f"\n[bold]Checking:[/] {categories_path}")

    if not categories_path.exists():
        print_warning(f"categories.json not found at {categories_path}")
    else:
        try:
            with open(categories_path, encoding="utf-8") as f:
                categories_data = json_module.load(f)
            if isinstance(categories_data, dict):
                categories = cast(dict[str, object], categories_data)
                print_success(f"categories.json: valid ({len(categories)} genre mappings)")
            else:
                print_error("categories.json: expected a dictionary")
                errors_found = True
        except json_module.JSONDecodeError as e:
            print_error(f"categories.json: invalid JSON - {e}")
            errors_found = True

    # Summary
    console.print()
    if errors_found:
        console.print("[error]Validation failed with errors[/]")
        return 1
    else:
        console.print("[success]All configuration files validated successfully ✅[/]")
        return 0


def cmd_config(args: argparse.Namespace) -> int:
    """Print loaded configuration."""
    from shelfr.config import reload_settings

    print_header("Configuration")

    try:
        settings = reload_settings(config_file=args.config)

        print_config_section(
            "Environment",
            {
                "Libation container": settings.libation_container,
                "Docker binary": settings.docker_bin,
                "Target UID:GID": f"{settings.target_uid}:{settings.target_gid}",
                "Environment": settings.env,
                "Log level": settings.log_level,
            },
        )

        print_config_section(
            "Paths",
            {
                "Library root": settings.paths.library_root,
                "Seed root": settings.paths.seed_root,
                "Torrent output": settings.paths.torrent_output,
            },
        )

        print_config_section(
            "mkbrr",
            {
                "Image": settings.mkbrr.image,
                "Preset": settings.mkbrr.preset,
                "Host data root": settings.mkbrr.host_data_root,
            },
        )

        print_config_section(
            "qBittorrent",
            {
                "Host": settings.qbittorrent.host,
                "Category": settings.qbittorrent.category,
                "Tags": ", ".join(settings.qbittorrent.tags),
                "Auto TMM": settings.qbittorrent.auto_tmm,
                "Save path": settings.qbittorrent.save_path or "(default)",
            },
        )

        print_config_section(
            "MAM",
            {
                "Max filename length": settings.mam.max_filename_length,
                "Allowed extensions": ", ".join(settings.mam.allowed_extensions),
            },
        )

        console.print("\n[success]✓[/] Configuration loaded successfully")
        return 0

    except FileNotFoundError as e:
        fatal_error(f"Config file not found: {e}")
        return 1
    except Exception as e:
        fatal_error(f"Error loading config: {e}")
        return 1
