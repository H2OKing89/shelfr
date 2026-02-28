"""ABS rename command - rename audiobook folders to match MAM naming schema.

This module contains the `cmd_abs_rename` command handler.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from shelfr.commands.abs._common import (
    fatal_error,
    print_header,
    print_info,
    print_success,
    print_warning,
)

if TYPE_CHECKING:
    from shelfr.abs.rename_ollama_audit import OllamaAuditConfig


def _resolve_cli_ollama_endpoints(args: argparse.Namespace) -> list[str]:
    """Merge repeatable and comma-list endpoint flags with stable dedupe."""
    merged: list[str] = []
    if args.ollama_endpoint:
        merged.extend(str(row).strip() for row in args.ollama_endpoint if str(row).strip())
    if args.ollama_endpoints:
        merged.extend(row.strip() for row in str(args.ollama_endpoints).split(",") if row.strip())

    deduped: list[str] = []
    seen: set[str] = set()
    for endpoint in merged:
        cleaned = endpoint.rstrip("/")
        if cleaned in seen:
            continue
        deduped.append(cleaned)
        seen.add(cleaned)
    return deduped


def _resolve_ollama_audit_config(
    args: argparse.Namespace, policy_cfg: object | None
) -> tuple[bool, OllamaAuditConfig]:
    """Resolve advisory audit enablement and config with CLI>config>defaults precedence."""
    from shelfr.abs.rename_ollama_audit import (
        DEFAULT_OLLAMA_BATCH_SIZE,
        DEFAULT_OLLAMA_ENDPOINTS,
        DEFAULT_OLLAMA_MAX_ITEMS,
        DEFAULT_OLLAMA_MODEL,
        DEFAULT_OLLAMA_RETRY_COUNT,
        DEFAULT_OLLAMA_TIMEOUT_SECONDS,
        DEFAULT_OLLAMA_WORKERS,
        OllamaAuditConfig,
    )

    enabled = (
        bool(args.ollama_audit)
        if args.ollama_audit is not None
        else bool(getattr(policy_cfg, "ollama_enabled", False))
    )

    cli_endpoints = _resolve_cli_ollama_endpoints(args)
    if cli_endpoints:
        resolved_endpoints = cli_endpoints
    elif policy_cfg and hasattr(policy_cfg, "ollama_endpoints") and policy_cfg.ollama_endpoints:
        resolved_endpoints = list(policy_cfg.ollama_endpoints)
    else:
        resolved_endpoints = list(DEFAULT_OLLAMA_ENDPOINTS)

    debug_dump_dir_raw = (
        args.ollama_debug_dump_dir
        if args.ollama_debug_dump_dir is not None
        else getattr(policy_cfg, "ollama_debug_dump_dir", None)
    )
    debug_dump_dir = Path(debug_dump_dir_raw) if debug_dump_dir_raw else None

    cfg = OllamaAuditConfig(
        model=(
            args.ollama_model
            if args.ollama_model is not None
            else getattr(policy_cfg, "ollama_model", DEFAULT_OLLAMA_MODEL)
        ),
        endpoints=resolved_endpoints,
        timeout_seconds=(
            args.ollama_timeout_seconds
            if args.ollama_timeout_seconds is not None
            else int(getattr(policy_cfg, "ollama_timeout_seconds", DEFAULT_OLLAMA_TIMEOUT_SECONDS))
        ),
        max_items=(
            args.ollama_max_items
            if args.ollama_max_items is not None
            else int(getattr(policy_cfg, "ollama_max_items", DEFAULT_OLLAMA_MAX_ITEMS))
        ),
        batch_size=(
            args.ollama_batch_size
            if args.ollama_batch_size is not None
            else int(getattr(policy_cfg, "ollama_batch_size", DEFAULT_OLLAMA_BATCH_SIZE))
        ),
        workers=(
            args.ollama_workers
            if args.ollama_workers is not None
            else int(getattr(policy_cfg, "ollama_workers", DEFAULT_OLLAMA_WORKERS))
        ),
        retry_count=(
            args.ollama_retry_count
            if args.ollama_retry_count is not None
            else int(getattr(policy_cfg, "ollama_retry_count", DEFAULT_OLLAMA_RETRY_COUNT))
        ),
        debug_dump_dir=debug_dump_dir,
    )
    return enabled, cfg


def cmd_abs_rename(args: argparse.Namespace) -> int:
    """Rename audiobook folders in ABS library to match MAM naming schema.

    Normalizes folder names in your Audiobookshelf library to follow
    the MAM naming convention for consistency and better organization.
    """
    from shelfr.abs.rename import (
        apply_rename_plan,
        build_rename_plan,
        generate_html_report,
        generate_report,
        resolve_rename_policy,
        run_rename_pipeline,
        write_rename_plan,
    )
    from shelfr.config import reload_settings

    print_header("ABS Rename", dry_run=args.dry_run)

    try:
        settings = reload_settings(config_file=args.config)
    except FileNotFoundError as e:
        fatal_error(str(e), "Check that config/config.yaml exists")
        return 1

    abs_cfg = getattr(settings, "audiobookshelf", None)
    policy_cfg = getattr(abs_cfg, "rename", None) if abs_cfg else None
    policy = resolve_rename_policy(policy_profile=args.policy_profile, config_policy=policy_cfg)

    # Apply mode: execute from approved plan manifest.
    if args.apply_from:
        plan_path = Path(args.apply_from)
        if not plan_path.exists():
            fatal_error(f"Plan file does not exist: {plan_path}")
            return 1

        apply_report = apply_rename_plan(
            plan_path,
            dry_run=args.dry_run,
            canary_size=args.canary_size,
            canary_strategy="first" if args.canary_strategy == "first" else "stratified",
        )

        report_path = (
            Path(args.report)
            if args.report
            else Path("data/reports")
            / f"rename_apply_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json"
        )
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(apply_report, indent=2),
                encoding="utf-8",
            )
            print_success(f"Apply JSON report written to {report_path}")

            html_path = report_path.with_suffix(".html")
            generate_html_report(apply_report, html_path)
            print_success(f"Apply HTML report written to {html_path}")
        except OSError as e:
            print_warning(f"Failed to write apply report: {e}")

        failed = int(apply_report.get("summary", {}).get("failed", 0))
        return 1 if failed > 0 else 0

    # Get source directory
    source_dir: Path
    if args.source:
        source_dir = args.source
    else:
        # Use ABS library path from config
        if not hasattr(settings, "audiobookshelf") or not settings.audiobookshelf.enabled:
            fatal_error("Audiobookshelf integration is not enabled in config")
            print_info("Either enable ABS or specify --source PATH")
            return 1

        abs_config = settings.audiobookshelf
        if not abs_config.path_map:
            fatal_error("No path_map configured for Audiobookshelf")
            return 1

        # Use first path map's host path as source
        source_dir = Path(abs_config.path_map[0].host)

    if not source_dir.exists():
        fatal_error(f"Source directory does not exist: {source_dir}")
        return 1

    print_info(f"Source: {source_dir}")
    if args.pattern != "*":
        print_info(f"Pattern: {args.pattern}")

    if args.plan_out and not args.dry_run:
        print_warning("--plan-out requested; forcing dry-run planning mode")
    if args.ollama_audit and not args.plan_out:
        print_warning("--ollama-audit is only applied when --plan-out is used; skipping audit")

    # Optionally create ABS client for search
    abs_client = None
    if args.abs_search:
        from shelfr.abs import AbsClient

        if not hasattr(settings, "audiobookshelf") or not settings.audiobookshelf.enabled:
            print_warning("ABS search requested but Audiobookshelf is not enabled")
        else:
            abs_config = settings.audiobookshelf
            try:
                abs_client = AbsClient(
                    host=abs_config.host,
                    api_key=abs_config.api_key,
                    timeout=abs_config.timeout_seconds,
                )
                print_info("ABS search enabled")
            except (ConnectionError, TimeoutError, OSError) as e:
                print_warning(f"Failed to create ABS client: {e}")

    # Run the rename pipeline
    # NOTE: Rename is for ORGANIZING existing library folders.
    # import_ripper_tag is intentionally NOT passed here — rename must
    # never inject ripper tags onto folders that don't already have them.
    # Tag handling is governed solely by ripper_tag_policy (preserve/drop).
    try:
        results, summary, candidates = run_rename_pipeline(
            source_dir=source_dir,
            pattern=args.pattern,
            fetch_metadata=args.fetch_metadata,
            abs_client=abs_client,
            abs_search_confidence=args.abs_search_confidence,
            naming_config=getattr(settings, "naming", None),
            import_ripper_tag=None,
            policy=policy,
            dry_run=(True if args.plan_out else args.dry_run),
            interactive=args.interactive,
            force=args.force,
        )
    finally:
        if abs_client:
            abs_client.close()

    # Generate plan manifest if requested.
    if args.plan_out:
        plan_path = Path(args.plan_out)
        if plan_path.suffix.lower() != ".json":
            plan_path = plan_path.with_suffix(".json")
        plan_written = False
        try:
            plan = build_rename_plan(
                source_dir=source_dir,
                candidates=candidates,
                summary=summary,
                policy=policy,
            )
            plan_payload = write_rename_plan(plan, plan_path)
            plan_written = True
            print_success(f"Plan manifest written to {plan_path}")

            # Optional advisory-only Ollama review (never mutates plan/apply behavior).
            policy_cfg = getattr(abs_cfg, "rename", None) if abs_cfg else None
            ollama_enabled, audit_cfg = _resolve_ollama_audit_config(args, policy_cfg)
            if ollama_enabled:
                from shelfr.abs.rename_ollama_audit import audit_rename_plan_with_ollama

                try:
                    audit_report = audit_rename_plan_with_ollama(plan_path=plan_path, cfg=audit_cfg)
                    audit_report_path = (
                        Path(args.ollama_report_out)
                        if args.ollama_report_out
                        else Path("data/reports")
                        / (
                            f"rename_plan_"
                            f"{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.llm_audit.json"
                        )
                    )
                    audit_report_path.parent.mkdir(parents=True, exist_ok=True)
                    audit_report_path.write_text(
                        json.dumps(audit_report.as_dict(), indent=2),
                        encoding="utf-8",
                    )
                    print_success(f"Ollama advisory report written to {audit_report_path}")
                    if audit_report.warnings:
                        for warning in audit_report.warnings:
                            print_warning(f"Ollama advisory warning: {warning}")
                except OSError as e:
                    print_warning(f"Failed to write Ollama advisory report: {e}")
                except Exception as e:
                    # Advisory-only: never fail rename planning due to audit issues.
                    print_warning(f"Ollama advisory audit failed (non-blocking): {e}")

            html_path = plan_path.with_suffix(".html")
            plan_items = plan_payload.get("items", [])
            by_status: dict[str, list[dict[str, object]]] = {}
            report_rows: list[dict[str, object]] = []
            for row in plan_items:
                status = str(row.get("status", "unknown"))
                result_row = {
                    "source_path": row.get("source_path"),
                    "source_name": Path(str(row.get("source_path", ""))).name,
                    "target_name": (
                        Path(str(row["target_path"])).name if row.get("target_path") else None
                    ),
                    "target_path": row.get("target_path"),
                    "status": status,
                    "error": ", ".join(row.get("reasons", [])),
                    "similarity_percent": row.get("similarity_percent"),
                    "asin_source": row.get("components", {}).get("asin_source"),
                    "is_suspicious_change": "low_similarity" in set(row.get("risk_flags", [])),
                }
                by_status.setdefault(status, []).append(result_row)
                report_rows.append(result_row)

            duplicate_groups = plan_payload.get("conflicts", {}).get("duplicate_asin", {})
            if not isinstance(duplicate_groups, dict):
                duplicate_groups = {}
            suspicious_changes = [row for row in report_rows if row.get("is_suspicious_change")]

            plan_report = {
                "timestamp": plan_payload.get("generated_at"),
                "source_dir": plan_payload.get("source_dir"),
                "dry_run": True,
                "summary": {
                    "total": plan_payload.get("summary", {}).get("total_candidates", 0),
                    "renamed": plan_payload.get("summary", {}).get("needs_rename", 0),
                    "skipped_up_to_date": plan_payload.get("summary", {}).get("up_to_date", 0),
                    "skipped_missing_asin": plan_payload.get("summary", {}).get("missing_asin", 0),
                    "skipped_duplicate_asin": plan_payload.get("summary", {}).get(
                        "duplicate_asin", 0
                    ),
                    "skipped_target_exists": plan_payload.get("summary", {}).get(
                        "target_exists", 0
                    ),
                    "errors": plan_payload.get("summary", {}).get("errors", 0),
                },
                "warnings": {
                    "suspicious_changes_count": len(suspicious_changes),
                    "suspicious_changes": suspicious_changes,
                    "duplicate_asin_groups": duplicate_groups,
                },
                "by_status": by_status,
                "results": report_rows,
            }
            generate_html_report(plan_report, html_path)
            print_success(f"Plan HTML report written to {html_path}")
        except OSError as e:
            print_warning(f"Failed to write plan artifact: {e}")
        if args.ollama_audit and not plan_written:
            print_warning("Ollama advisory audit skipped because plan manifest was not written")

    # Generate report if requested
    if args.report:
        report_path = Path(args.report)
        try:
            report_data = generate_report(
                results,
                candidates,
                summary,
                report_path,
                source_dir=source_dir,
                dry_run=(True if args.plan_out else args.dry_run),
            )
            print_success(f"JSON report written to {report_path}")

            # Also generate HTML report
            html_path = report_path.with_suffix(".html")
            generate_html_report(report_data, html_path)
            print_success(f"HTML report written to {html_path}")
        except OSError as e:
            print_warning(f"Failed to write report: {e}")

    # Return error code if there were failures
    if summary.errors > 0:
        return 1
    return 0


__all__ = ["cmd_abs_rename"]
