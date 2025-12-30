#!/usr/bin/env python3
"""
Version management utilities for shelfr.

Usage:
    python tools/version.py              # Show current version
    python tools/version.py 0.2.0        # Set specific version
    python tools/version.py patch        # Bump patch (0.1.0 -> 0.1.1)
    python tools/version.py minor        # Bump minor (0.1.0 -> 0.2.0)
    python tools/version.py major        # Bump major (0.1.0 -> 1.0.0)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Paths to version files (we update both for consistency)
REPO_ROOT = Path(__file__).parent.parent
INIT_FILE = REPO_ROOT / "src" / "shelfr" / "__init__.py"
PYPROJECT_FILE = REPO_ROOT / "pyproject.toml"

# Patterns to match version strings
INIT_PATTERN = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
PYPROJECT_PATTERN = re.compile(r'^version\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)


def get_version() -> str:
    """Get current version from src/shelfr/__init__.py."""
    content = INIT_FILE.read_text()
    match = INIT_PATTERN.search(content)
    if not match:
        raise ValueError(f"Could not find __version__ in {INIT_FILE}")
    return match.group(1)


def set_version(new_version: str) -> None:
    """Set version in both __init__.py and pyproject.toml."""
    # Update __init__.py
    init_content = INIT_FILE.read_text()
    new_init_content, init_subs = INIT_PATTERN.subn(f'__version__ = "{new_version}"', init_content)
    if init_subs == 0:
        raise ValueError(f"Could not find __version__ pattern in {INIT_FILE}")
    INIT_FILE.write_text(new_init_content)

    # Update pyproject.toml
    pyproject_content = PYPROJECT_FILE.read_text()
    new_pyproject_content, pyproject_subs = PYPROJECT_PATTERN.subn(
        f'version = "{new_version}"', pyproject_content
    )
    if pyproject_subs == 0:
        raise ValueError(f"Could not find version pattern in {PYPROJECT_FILE}")
    PYPROJECT_FILE.write_text(new_pyproject_content)

    print(f"✅ Updated version to {new_version}")
    print(f"   - {INIT_FILE.relative_to(REPO_ROOT)}")
    print(f"   - {PYPROJECT_FILE.relative_to(REPO_ROOT)}")


def bump_version(part: str) -> str:
    """Bump version by part (major, minor, patch)."""
    current = get_version()
    parts = current.split(".")

    if len(parts) != 3:
        raise ValueError(f"Invalid version format: {current}")

    major, minor, patch = map(int, parts)

    if part == "major":
        major += 1
        minor = 0
        patch = 0
    elif part == "minor":
        minor += 1
        patch = 0
    elif part == "patch":
        patch += 1
    else:
        raise ValueError(f"Invalid part: {part}. Use major, minor, or patch")

    return f"{major}.{minor}.{patch}"


def main() -> int:
    """Main entry point."""
    if len(sys.argv) == 1:
        # Show current version
        print(f"Current version: {get_version()}")
        return 0

    arg = sys.argv[1]

    if arg in ("major", "minor", "patch"):
        # Bump version
        old_version = get_version()
        new_version = bump_version(arg)
        set_version(new_version)
        print(f"\n   {old_version} → {new_version}")
        print("\n📦 To release, run:")
        print("   git add src/shelfr/__init__.py pyproject.toml")
        print(f"   git commit -m 'chore: bump version to {new_version}'")
        print(f"   git tag v{new_version}")
        print("   git push origin main --tags")
        return 0
    elif re.match(r"^\d+\.\d+\.\d+$", arg):
        # Set specific version
        old_version = get_version()
        set_version(arg)
        print(f"\n   {old_version} → {arg}")
        return 0
    else:
        print(f"❌ Invalid argument: {arg}")
        print(__doc__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
