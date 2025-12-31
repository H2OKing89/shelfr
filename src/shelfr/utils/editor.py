"""External editor integration.

Launch user's preferred editor for file editing. Zero UI complexity,
maximum compatibility.

Environment Variables:
    $VISUAL: GUI-friendly editor (checked first)
    $EDITOR: Traditional editor (checked second)

Example:
    >>> from shelfr.utils.editor import edit_file, edit_yaml
    >>> edit_file(Path("config.yaml"))  # Opens in $EDITOR
    True
    >>> content = edit_temp("initial text", suffix=".md")  # Edit temp file
    'modified text'
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

# Editor fallback chain (in order of preference)
EDITOR_FALLBACKS: tuple[str, ...] = ("nano", "vim", "vi", "notepad.exe", "notepad")

# Default timeout for editor processes (None = wait indefinitely)
DEFAULT_TIMEOUT: int | None = None


class EditorError(Exception):
    """Raised when editor operations fail."""

    pass


class NoEditorError(EditorError):
    """Raised when no editor is available."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message or "No editor found. Set $EDITOR or $VISUAL environment variable."
        )


def get_editor(override: str | None = None) -> str | None:
    """
    Get the user's preferred editor.

    Priority:
        1. Override parameter (if provided)
        2. $VISUAL (GUI-friendly)
        3. $EDITOR (traditional)
        4. First available fallback (nano, vim, vi, notepad)

    Args:
        override: Explicit editor command to use.

    Returns:
        Editor command string or None if none found.

    Example:
        >>> get_editor()
        'nano'
        >>> get_editor(override='code --wait')
        'code --wait'
    """
    # Check explicit override
    if override:
        return override

    # Check environment variables
    for env_var in ("VISUAL", "EDITOR"):
        if editor := os.environ.get(env_var):
            logger.debug("Found editor from $%s: %s", env_var, editor)
            return editor

    # Try fallbacks
    for fallback in EDITOR_FALLBACKS:
        if shutil.which(fallback):
            logger.debug("Found fallback editor: %s", fallback)
            return fallback

    logger.warning("No editor found in environment or fallbacks")
    return None


def _build_editor_command(editor: str, file_path: Path) -> list[str]:
    """
    Build the command list to invoke the editor.

    Handles editors with arguments like "code --wait" or "subl -w".

    Args:
        editor: Editor command (may include arguments).
        file_path: Path to file to edit.

    Returns:
        Command list suitable for subprocess.run().
    """
    # Split on spaces to handle "code --wait" style commands
    parts = editor.split()
    return [*parts, str(file_path)]


def edit_file(
    file_path: Path | str,
    *,
    wait: bool = True,
    editor: str | None = None,
    timeout: int | None = DEFAULT_TIMEOUT,
) -> bool:
    """
    Open a file in the user's editor.

    Args:
        file_path: Path to file to edit.
        wait: Wait for editor to close before returning.
        editor: Override editor command (default: auto-detect).
        timeout: Maximum seconds to wait (None = no limit).

    Returns:
        True if editor exited successfully (returncode 0).

    Raises:
        FileNotFoundError: If file doesn't exist.
        NoEditorError: If no editor available.
        EditorError: If editor process fails unexpectedly.

    Example:
        >>> edit_file(Path("config.yaml"))
        True
        >>> edit_file("notes.md", editor="code --wait")
        True
    """
    file_path = Path(file_path).resolve()

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    editor_cmd = get_editor(editor)
    if not editor_cmd:
        raise NoEditorError()

    cmd = _build_editor_command(editor_cmd, file_path)
    logger.info("Opening %s with: %s", file_path.name, " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            check=False,
            timeout=timeout if wait else 0.1,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        if wait:
            logger.warning("Editor timed out after %d seconds", timeout)
            return False
        # For non-wait mode, timeout is expected
        return True
    except OSError as e:
        logger.exception("Failed to launch editor: %s", e)
        raise EditorError(f"Failed to launch editor '{editor_cmd}': {e}") from e


def edit_temp(
    content: str = "",
    *,
    suffix: str = ".txt",
    prefix: str = "shelfr_",
    editor: str | None = None,
    timeout: int | None = DEFAULT_TIMEOUT,
) -> str | None:
    """
    Edit content in a temporary file.

    Creates a temp file with initial content, opens editor,
    returns modified content after editor closes. Returns None
    if the file wasn't modified (user cancelled).

    Args:
        content: Initial content for the file.
        suffix: File extension (e.g., ".yaml", ".md", ".j2").
        prefix: Temp file prefix for identification.
        editor: Override editor command (default: auto-detect).
        timeout: Maximum seconds to wait (None = no limit).

    Returns:
        Modified content string, or None if cancelled/unchanged.

    Raises:
        NoEditorError: If no editor available.
        EditorError: If editor process fails.

    Example:
        >>> result = edit_temp("# Title\\n\\nContent here", suffix=".md")
        >>> if result:
        ...     print("User saved:", result)
        ... else:
        ...     print("User cancelled")
    """
    editor_cmd = get_editor(editor)
    if not editor_cmd:
        raise NoEditorError()

    # Create temp file with content
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=suffix,
        prefix=prefix,
        delete=False,
        encoding="utf-8",
    ) as f:
        f.write(content)
        temp_path = Path(f.name)

    logger.debug("Created temp file: %s", temp_path)

    try:
        original_mtime = temp_path.stat().st_mtime

        cmd = _build_editor_command(editor_cmd, temp_path)
        logger.info("Opening temp file with: %s", " ".join(cmd))

        result = subprocess.run(cmd, check=False, timeout=timeout)

        if result.returncode != 0:
            logger.warning("Editor exited with code %d", result.returncode)
            return None

        # Check if file was actually modified
        new_mtime = temp_path.stat().st_mtime
        if new_mtime == original_mtime:
            logger.debug("File unchanged (mtime same), treating as cancel")
            return None

        new_content = temp_path.read_text(encoding="utf-8")

        # Also check if content is actually different
        if new_content == content:
            logger.debug("File content unchanged, treating as cancel")
            return None

        return new_content

    except subprocess.TimeoutExpired:
        logger.warning("Editor timed out after %d seconds", timeout)
        return None
    except OSError as e:
        logger.exception("Editor operation failed: %s", e)
        raise EditorError(f"Editor operation failed: {e}") from e
    finally:
        # Clean up temp file
        try:
            temp_path.unlink(missing_ok=True)
            logger.debug("Cleaned up temp file: %s", temp_path)
        except OSError:
            pass  # Best effort cleanup


def edit_yaml(
    file_path: Path | str,
    *,
    validate: bool = True,
    backup: bool = True,
    editor: str | None = None,
    timeout: int | None = DEFAULT_TIMEOUT,
) -> bool:
    """
    Edit a YAML file with optional validation.

    Opens file in editor, optionally validates YAML syntax after save.
    Creates a backup before editing if backup=True.

    Args:
        file_path: Path to YAML file.
        validate: Whether to validate YAML after editing.
        backup: Create .bak backup before editing.
        editor: Override editor command (default: auto-detect).
        timeout: Maximum seconds to wait (None = no limit).

    Returns:
        True if file was saved (and valid if validate=True).

    Raises:
        FileNotFoundError: If file doesn't exist.
        NoEditorError: If no editor available.
        EditorError: If editor process fails.

    Example:
        >>> if edit_yaml("config.yaml"):
        ...     print("Config saved successfully")
        ... else:
        ...     print("Edit cancelled or invalid YAML")
    """
    file_path = Path(file_path).resolve()

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Create backup
    backup_path: Path | None = None
    if backup:
        backup_path = file_path.with_suffix(file_path.suffix + ".bak")
        try:
            import shutil

            shutil.copy2(file_path, backup_path)
            logger.debug("Created backup: %s", backup_path)
        except OSError as e:
            logger.warning("Failed to create backup: %s", e)
            backup_path = None

    # Get original content for comparison
    original_content = file_path.read_text(encoding="utf-8")

    # Edit the file
    if not edit_file(file_path, editor=editor, timeout=timeout):
        logger.debug("Editor returned non-zero, restoring backup if available")
        if backup_path and backup_path.exists():
            shutil.copy2(backup_path, file_path)
        return False

    # Check if content changed
    new_content = file_path.read_text(encoding="utf-8")
    if new_content == original_content:
        logger.debug("File unchanged")
        # Clean up backup since no changes
        if backup_path:
            backup_path.unlink(missing_ok=True)
        return False

    # Validate YAML if requested
    if validate:
        import yaml as pyyaml

        try:
            pyyaml.safe_load(new_content)
            logger.debug("YAML validation passed")
        except pyyaml.YAMLError as e:
            logger.error("Invalid YAML: %s", e)
            # Restore from backup
            if backup_path and backup_path.exists():
                logger.info("Restoring from backup due to invalid YAML")
                shutil.copy2(backup_path, file_path)
            return False

    # Success - clean up backup
    if backup_path:
        backup_path.unlink(missing_ok=True)
        logger.debug("Removed backup after successful edit")

    return True


def edit_yaml_temp(
    content: str = "",
    *,
    validate: bool = True,
    editor: str | None = None,
    timeout: int | None = DEFAULT_TIMEOUT,
) -> str | None:
    """
    Edit YAML content in a temporary file with validation.

    Combines edit_temp() with YAML validation. Useful for creating
    new YAML content or editing content not yet saved to a file.

    Args:
        content: Initial YAML content.
        validate: Whether to validate YAML before returning.
        editor: Override editor command (default: auto-detect).
        timeout: Maximum seconds to wait (None = no limit).

    Returns:
        Valid YAML content string, or None if cancelled/invalid.

    Example:
        >>> template = "version: 1\\npresets:\\n  mam:\\n    private: true"
        >>> result = edit_yaml_temp(template)
        >>> if result:
        ...     Path("presets.yaml").write_text(result)
    """
    result = edit_temp(content, suffix=".yaml", editor=editor, timeout=timeout)

    if result is None:
        return None

    if validate:
        import yaml as pyyaml

        try:
            pyyaml.safe_load(result)
        except pyyaml.YAMLError as e:
            logger.error("Invalid YAML in temp edit: %s", e)
            return None

    return result


# Convenience functions for common file types


def edit_jinja2(
    file_path: Path | str,
    *,
    editor: str | None = None,
    timeout: int | None = DEFAULT_TIMEOUT,
) -> bool:
    """
    Edit a Jinja2 template file.

    Simple wrapper around edit_file() for .j2 templates.
    No validation is performed (Jinja2 syntax is complex).

    Args:
        file_path: Path to .j2 template file.
        editor: Override editor command.
        timeout: Maximum seconds to wait.

    Returns:
        True if editor exited successfully.
    """
    return edit_file(file_path, editor=editor, timeout=timeout)


def edit_json(
    file_path: Path | str,
    *,
    validate: bool = True,
    backup: bool = True,
    editor: str | None = None,
    timeout: int | None = DEFAULT_TIMEOUT,
) -> bool:
    """
    Edit a JSON file with optional validation.

    Args:
        file_path: Path to JSON file.
        validate: Whether to validate JSON after editing.
        backup: Create .bak backup before editing.
        editor: Override editor command.
        timeout: Maximum seconds to wait.

    Returns:
        True if file was saved (and valid if validate=True).
    """
    import json
    import shutil

    file_path = Path(file_path).resolve()

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Create backup
    backup_path: Path | None = None
    if backup:
        backup_path = file_path.with_suffix(file_path.suffix + ".bak")
        try:
            shutil.copy2(file_path, backup_path)
        except OSError as e:
            logger.warning("Failed to create backup: %s", e)
            backup_path = None

    original_content = file_path.read_text(encoding="utf-8")

    if not edit_file(file_path, editor=editor, timeout=timeout):
        if backup_path and backup_path.exists():
            shutil.copy2(backup_path, file_path)
        return False

    new_content = file_path.read_text(encoding="utf-8")
    if new_content == original_content:
        if backup_path:
            backup_path.unlink(missing_ok=True)
        return False

    if validate:
        try:
            json.loads(new_content)
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON: %s", e)
            if backup_path and backup_path.exists():
                shutil.copy2(backup_path, file_path)
            return False

    if backup_path:
        backup_path.unlink(missing_ok=True)

    return True
