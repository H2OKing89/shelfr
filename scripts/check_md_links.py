#!/usr/bin/env python3
"""Check for broken internal markdown links in docs/.

This script is intentionally simple and fast.

It treats these as internal links:
- Relative links (e.g. `../reference/naming/`)
- Repo-root links (e.g. `src/mamfast/...`)
- Repo-root absolute links (e.g. `/CLAUDE.md`)

It skips external URLs, mailto links, and pure fragments (e.g. `#section`).
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")


def is_url(s: str) -> bool:
    """Check if string is an external URL."""
    return s.startswith(("http://", "https://", "mailto:", "#"))


def _split_target(target: str) -> tuple[str, str | None]:
    """Split a markdown target into (path_part, fragment)."""
    target = target.strip()
    if not target:
        return "", None
    if "#" in target:
        path_part, fragment = target.split("#", 1)
        return path_part.strip(), fragment.strip() or None
    return target, None


def resolve_target(md_file: Path, target: str, *, repo_root: Path) -> Path | None:
    """Resolve a markdown link target to an actual path.

    Resolution strategy:
    1) If the link is absolute-from-repo (starts with `/`), resolve from repo root.
    2) Try resolving relative to the markdown file.
    3) If that fails, try resolving from repo root (helps for links like `src/...`).
    """
    if not target or is_url(target):
        return None

    path_part, _fragment = _split_target(target)

    # Pure fragment (e.g. "#section") is skipped by is_url(), but be defensive.
    if not path_part:
        return None

    # Treat `/foo/bar` as repo-root-relative
    if path_part.startswith("/"):
        candidate = (repo_root / path_part.lstrip("/")).resolve()
        return candidate if candidate.exists() else None

    # 1) Relative to the markdown file
    candidate = (md_file.parent / path_part).resolve()
    if candidate.exists():
        return candidate

    # 2) Fallback: relative to repo root
    candidate = (repo_root / path_part).resolve()
    if candidate.exists():
        return candidate

    return None


def _is_mirrored_hardcover_api_doc(md_file: Path, *, docs_dir: Path) -> bool:
    """Return True if md_file is within docs/reference/hardcover/api.

    The mirrored Hardcover docs include many site-relative links like `/api/...` that
    are valid on the upstream website but don't correspond to files in this repo.
    """
    try:
        rel_path = md_file.relative_to(docs_dir)
    except ValueError:
        return False

    return rel_path.parts[:3] == ("reference", "hardcover", "api")


def check_links() -> int:
    """Check all markdown links in docs/ folder."""
    repo_root = Path.cwd()
    docs_dir = repo_root / "docs"
    if not docs_dir.exists():
        logger.error("docs/ not found. Run from repo root.")
        return 2

    broken = []
    checked = 0

    for md_file in sorted(list(docs_dir.rglob("*.md")) + list(docs_dir.rglob("*.mdx"))):
        try:
            text = md_file.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            logger.error(f"Encoding error reading {md_file}: {e}")
            continue
        except (FileNotFoundError, PermissionError) as e:
            logger.error(f"Cannot read {md_file}: {e}")
            continue

        for display, target in LINK_RE.findall(text):
            checked += 1

            # The upstream Hardcover API docs use site-relative URLs that don't map
            # to repo files once mirrored into this workspace.
            if _is_mirrored_hardcover_api_doc(md_file, docs_dir=docs_dir):
                stripped = target.strip()
                if stripped.startswith("/") and not stripped.startswith("//"):
                    continue

                path_part, _fragment = _split_target(stripped)

                # Many links in these docs are route-like (no extension) and map to
                # the upstream site's router, not a real file path in this repo.
                if path_part and not is_url(path_part):
                    p = Path(path_part)
                    if p.suffix == "" and not path_part.endswith("/"):
                        continue

            resolved = resolve_target(md_file, target, repo_root=repo_root)

            if resolved is None and not is_url(target) and target.strip():
                # This might be a broken link
                rel_path = md_file.relative_to(docs_dir)
                broken.append((rel_path, target, display))

    if broken:
        logger.error(f"Found {len(broken)} broken link(s):")
        for file_path, target, display in broken:
            logger.error(f"  {file_path}: [{display}]({target})")
        return 1

    logger.info(f"OK: checked {checked} links, all valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(check_links())
