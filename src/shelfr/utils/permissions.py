"""Utility functions for fixing file and directory ownership.

Provides shared logic for chown operations used by hardlinker and mkbrr modules.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def fix_ownership(path: Path, target_uid: int, target_gid: int) -> bool:
    """
    Fix ownership on a single path (file or directory).

    Only changes ownership if current UID/GID differs from target.

    Args:
        path: Path to the file or directory
        target_uid: Target user ID to set
        target_gid: Target group ID to set

    Returns:
        True if ownership was changed, False otherwise (already correct or error)
    """
    try:
        stat = path.stat()
        if stat.st_uid != target_uid or stat.st_gid != target_gid:
            os.chown(path, target_uid, target_gid)
            logger.debug(f"Fixed ownership: {path}")
            return True
        return False
    except FileNotFoundError:
        return False
    except PermissionError as e:
        logger.warning(f"Permission error on {path}: {e}")
        return False


def fix_directory_ownership(
    root_dir: Path,
    target_uid: int,
    target_gid: int,
    *,
    recursive: bool = True,
    file_extensions: set[str] | None = None,
) -> int:
    """
    Fix ownership on a directory and optionally its contents.

    Args:
        root_dir: Root directory to fix ownership on
        target_uid: Target user ID to set
        target_gid: Target group ID to set
        recursive: If True, traverse subdirectories; if False, only immediate contents
        file_extensions: If provided, only fix files with these extensions
                        (e.g., {".torrent", ".json"}). If None, fix all files.

    Returns:
        Number of items (directories + files) with ownership changed
    """
    if not root_dir.is_dir():
        logger.warning(f"Directory does not exist: {root_dir}")
        return 0

    fixed_count = 0
    logger.debug(f"Fixing ownership in {root_dir} to {target_uid}:{target_gid}")

    if recursive:
        # Recursive traversal with os.walk
        for dirpath, _dirnames, filenames in os.walk(root_dir):
            dir_path = Path(dirpath)

            # Fix directory ownership
            if fix_ownership(dir_path, target_uid, target_gid):
                fixed_count += 1

            # Fix file ownership
            for name in filenames:
                if file_extensions is not None and not any(
                    name.lower().endswith(ext) for ext in file_extensions
                ):
                    continue

                file_path = dir_path / name
                if fix_ownership(file_path, target_uid, target_gid):
                    fixed_count += 1
    else:
        # Non-recursive: just the directory and its immediate files
        if fix_ownership(root_dir, target_uid, target_gid):
            fixed_count += 1

        for item in root_dir.iterdir():
            if not item.is_file():
                continue

            if file_extensions is not None and not any(
                item.name.lower().endswith(ext) for ext in file_extensions
            ):
                continue

            if fix_ownership(item, target_uid, target_gid):
                fixed_count += 1

    if fixed_count:
        logger.debug(f"Fixed ownership on {fixed_count} item(s) to {target_uid}:{target_gid}")

    return fixed_count
