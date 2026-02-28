#!/usr/bin/env python3
"""Batch scan all authors and produce a rename-plan report.

Runs `shelfr abs rename --source <author_dir> --plan-out <plan.json>`
for every author directory in the audiobooks library, then aggregates
results into a single summary report.

Usage:
    python scripts/dev_tools/batch_rename_scan.py
    python scripts/dev_tools/batch_rename_scan.py --library /path/to/audiobooks
    python scripts/dev_tools/batch_rename_scan.py --author "J.K. Rowling"
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

# Defaults
DEFAULT_LIBRARY = Path("/mnt/user/data/audio/audiobooks")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = PROJECT_ROOT / "data" / "reports"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Batch rename-plan scan")
    p.add_argument(
        "--library",
        type=Path,
        default=DEFAULT_LIBRARY,
        help=f"Path to audiobooks library (default: {DEFAULT_LIBRARY})",
    )
    p.add_argument(
        "--author",
        type=str,
        default=None,
        help="Scan only this author directory name (substring match)",
    )
    p.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Output report path (default: data/reports/rename_scan_<timestamp>.json)",
    )
    p.add_argument(
        "--plans-dir",
        type=Path,
        default=None,
        help="Directory for per-author plan files (default: data/reports/author_plans/)",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Per-author timeout in seconds (default: 120)",
    )
    return p.parse_args()


def scan_author(
    author_dir: Path,
    plan_file: Path,
    timeout: int,
) -> dict:
    """Run the rename planner for one author directory."""
    name = author_dir.name
    book_count = sum(1 for d in author_dir.iterdir() if d.is_dir())
    t0 = time.time()

    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "from shelfr.cli import app; app()",
                "abs",
                "rename",
                "--source",
                str(author_dir),
                "--plan-out",
                str(plan_file),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(PROJECT_ROOT),
        )
        elapsed = time.time() - t0

        if plan_file.exists():
            plan = json.loads(plan_file.read_text())
            items = plan.get("items", [])
            needs_rename = [it for it in items if it.get("status") == "needs_rename"]
            already_ok = [it for it in items if it.get("status") == "already_canonical"]
            skipped = [
                it for it in items if it.get("status") not in ("needs_rename", "already_canonical")
            ]
        else:
            items = []
            needs_rename = []
            already_ok = []
            skipped = []

        return {
            "author": name,
            "path": str(author_dir),
            "books": book_count,
            "total_items": len(items),
            "needs_rename": len(needs_rename),
            "already_canonical": len(already_ok),
            "skipped": len(skipped),
            "elapsed_s": round(elapsed, 1),
            "plan_file": str(plan_file) if plan_file.exists() else None,
            "stderr": proc.stderr.strip()[-500:] if proc.stderr.strip() else None,
            "rename_details": [
                {
                    "from": it["source_path"].split("audiobooks/")[-1],
                    "to": it["target_path"].split("audiobooks/")[-1],
                    "reasons": it.get("reasons", []),
                }
                for it in needs_rename
            ],
        }

    except subprocess.TimeoutExpired:
        return {
            "author": name,
            "path": str(author_dir),
            "books": book_count,
            "needs_rename": -1,
            "error": "timeout",
            "elapsed_s": round(time.time() - t0, 1),
        }
    except Exception as e:
        return {
            "author": name,
            "path": str(author_dir),
            "books": book_count,
            "needs_rename": -1,
            "error": str(e),
            "elapsed_s": round(time.time() - t0, 1),
        }


def print_summary(results: list[dict]) -> None:
    """Print a human-readable summary."""
    total = len(results)
    need_work = [r for r in results if r.get("needs_rename", 0) > 0]
    canonical = [r for r in results if r.get("needs_rename", 0) == 0]
    errors = [r for r in results if r.get("needs_rename", 0) < 0]

    print("\n" + "=" * 80)
    print("RENAME SCAN SUMMARY")
    print("=" * 80)
    print(f"\n  Total authors scanned: {total}")
    print(f"  Already canonical:     {len(canonical)}")
    print(
        f"  Need renames:          {len(need_work)}"
        f" ({sum(r['needs_rename'] for r in need_work)} total renames)"
    )
    if errors:
        print(f"  Errors/Timeouts:       {len(errors)}")

    if need_work:
        print(f"\n  {'Author':<40} {'Books':>5} {'Renames':>7}")
        print("  " + "-" * 55)
        for r in sorted(need_work, key=lambda x: -x["needs_rename"]):
            print(f"  {r['author']:<40} {r['books']:>5} {r['needs_rename']:>7}")

    if errors:
        print("\n  Errors:")
        for r in errors:
            print(f"    {r['author']}: {r.get('error', 'unknown')}")


def main() -> None:
    args = parse_args()

    library = args.library
    if not library.is_dir():
        print(f"ERROR: Library not found: {library}", file=sys.stderr)
        sys.exit(1)

    # Set up output directories
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    plans_dir = args.plans_dir or REPORT_DIR / "author_plans"
    plans_dir.mkdir(parents=True, exist_ok=True)

    # Discover authors
    authors = sorted(
        [d for d in library.iterdir() if d.is_dir()],
        key=lambda p: p.name.lower(),
    )

    if args.author:
        needle = args.author.lower()
        authors = [a for a in authors if needle in a.name.lower()]
        if not authors:
            print(f"No author matching '{args.author}'", file=sys.stderr)
            sys.exit(1)

    total = len(authors)
    results: list[dict] = []

    for i, author_dir in enumerate(authors, 1):
        name = author_dir.name
        book_count = sum(1 for d in author_dir.iterdir() if d.is_dir())
        plan_file = plans_dir / f"{name.replace(' ', '_').replace('.', '_')}.json"

        print(f"[{i:3d}/{total}] {name} ({book_count} books)...", end=" ", flush=True)

        result = scan_author(author_dir, plan_file, args.timeout)
        results.append(result)

        renames = result.get("needs_rename", -1)
        elapsed = result.get("elapsed_s", 0)
        if renames < 0:
            tag = f"✗ {result.get('error', 'unknown')}"
        elif renames == 0:
            tag = "✓"
        else:
            tag = f"⚠ {renames}"
        print(f"{tag}  ({elapsed:.1f}s)")

    # Save report
    if args.report:
        report_path = args.report
    else:
        ts = time.strftime("%Y%m%d_%H%M%S")
        report_path = REPORT_DIR / f"rename_scan_{ts}.json"

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(results, indent=2))

    print_summary(results)
    print(f"\nFull report: {report_path}")
    print(f"Per-author plans: {plans_dir}/")


if __name__ == "__main__":
    main()
