#!/usr/bin/env python3
"""Interactive wizard for shelfr operations.

Rich UI edition ✨

This module provides an interactive menu-driven interface for common shelfr
operations, inspired by mkbrr-wizard. It can be run standalone or integrated
into the CLI via `shelfr wizard`.

Usage:
    shelfr wizard              # Start interactive wizard
    python -m shelfr.wizard    # Run directly
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from shelfr.ui import SHELFR_THEME
from shelfr.ui.icons import get_icons

if TYPE_CHECKING:
    pass

# Optional: prompt_toolkit for path history
try:
    from prompt_toolkit.history import InMemoryHistory

    _path_history: InMemoryHistory | None = InMemoryHistory()
    _asin_history: InMemoryHistory | None = InMemoryHistory()
    HAS_PROMPT_TOOLKIT = True
except ImportError:
    _path_history = None
    _asin_history = None
    HAS_PROMPT_TOOLKIT = False


console = Console(theme=SHELFR_THEME, highlight=False)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class WizardAction:
    """Represents a wizard menu action."""

    key: str
    label: str
    description: str
    command: list[str] | None = None  # shelfr subcommand to run


# =============================================================================
# Menu Definitions
# =============================================================================

MAIN_MENU_ACTIONS = [
    WizardAction("1", "Run Pipeline", "Full upload pipeline (scan → stage → upload)", ["run"]),
    WizardAction("2", "Check Status", "Show current processing status", ["status"]),
    WizardAction("3", "Libation", "Libation library operations →", None),
    WizardAction("4", "Audiobookshelf", "ABS import/management →", None),
    WizardAction("5", "Tools", "Utility tools →", None),
    WizardAction("6", "Diagnostics", "Health checks and validation →", None),
    WizardAction("q", "Quit", "Exit wizard", None),
]

LIBATION_MENU_ACTIONS = [
    WizardAction(
        "1", "Scan Library", "Discover new audiobooks from Libation", ["libation", "scan"]
    ),
    WizardAction(
        "2", "Liberate", "Download and decrypt pending audiobooks", ["libation", "liberate"]
    ),
    WizardAction(
        "3", "Redownload", "Re-download specific audiobook(s)", ["libation", "redownload"]
    ),
    WizardAction("4", "Search Books", "Search Libation library", ["libation", "search"]),
    WizardAction("5", "Show Status", "Library status dashboard", ["libation", "status"]),
    WizardAction("6", "List Books", "List all discovered books", ["libation", "books"]),
    WizardAction("b", "Back", "Return to main menu", None),
]

ABS_MENU_ACTIONS = [
    WizardAction("1", "Initialize", "Discover ABS libraries", ["abs", "init"]),
    WizardAction("2", "Import Books", "Import staged books to ABS", ["abs", "import"]),
    WizardAction("3", "Check ASIN", "Check if ASIN exists in ABS", ["abs", "check-asin"]),
    WizardAction("4", "Resolve ASINs", "Fix books with unknown ASINs", ["abs", "resolve-asins"]),
    WizardAction(
        "5", "Trump Preview", "Preview potential quality upgrades", ["abs", "trump-preview"]
    ),
    WizardAction("6", "Cleanup", "Clean up source files after import", ["abs", "cleanup"]),
    WizardAction("b", "Back", "Return to main menu", None),
]

TOOLS_MENU_ACTIONS = [
    WizardAction("1", "Prepare Release", "Prepare a folder for upload", ["tools", "prepare"]),
    WizardAction("2", "MAM Fill Form", "Auto-fill MAM upload form", ["tools", "mamff"]),
    WizardAction("3", "mkbrr", "Create/inspect torrents →", None),
    WizardAction("b", "Back", "Return to main menu", None),
]

MKBRR_MENU_ACTIONS = [
    WizardAction("1", "Create Torrent", "Create .torrent from file/folder", ["mkbrr", "create"]),
    WizardAction("2", "Inspect Torrent", "View .torrent file details", ["mkbrr", "inspect"]),
    WizardAction("3", "Check Data", "Verify data against .torrent", ["mkbrr", "check"]),
    WizardAction("b", "Back", "Return to tools menu", None),
]

DIAGNOSTICS_MENU_ACTIONS = [
    WizardAction("1", "Health Check", "Run system health checks", ["check"]),
    WizardAction("2", "Validate Config", "Validate configuration files", ["validate-config"]),
    WizardAction("3", "Preview Naming", "Preview folder naming rules", ["preview-naming"]),
    WizardAction("4", "Check Duplicates", "Find duplicate releases", ["check-duplicates"]),
    WizardAction("5", "Check Suspicious", "Find suspicious changes", ["check-suspicious"]),
    WizardAction("b", "Back", "Return to main menu", None),
]


# =============================================================================
# UI Helpers
# =============================================================================


def render_header() -> None:
    """Render the wizard startup header."""
    from shelfr.ui.banner import print_banner

    # Use the standard shelfr banner
    print_banner(console, border_style="cyan")

    # Show wizard mode info
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("key", style="dim")
    table.add_column("val")

    table.add_row("Mode", "[bold cyan]Interactive Wizard[/]")
    table.add_row(
        "Tip",
        "[dim]Use arrow keys for history in path prompts[/]"
        if HAS_PROMPT_TOOLKIT
        else "[dim]Install prompt_toolkit for path history[/]",
    )

    console.print(Panel(table, border_style="dim", box=box.ROUNDED))


def render_menu(title: str, actions: list[WizardAction]) -> None:
    """Render a menu panel."""
    icons = get_icons()
    lines = []
    for action in actions:
        if action.key == "q" or action.key == "b":
            lines.append(f"[dim][{action.key}][/] {action.label}")
        else:
            lines.append(f"[cyan][{action.key}][/] {action.label:<20} [dim]{action.description}[/]")

    console.print(
        Panel(
            "\n".join(lines),
            title=f"{icons.list_} {title}",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )


def choose_action(title: str, actions: list[WizardAction]) -> WizardAction | None:
    """Display menu and get user choice."""
    render_menu(title, actions)

    valid_keys = [a.key for a in actions]
    choice = Prompt.ask("Choose", choices=valid_keys, default="1")

    for action in actions:
        if action.key == choice:
            return action
    return None


def confirm_command(cmd: list[str], extra_args: list[str] | None = None) -> bool:
    """Show command preview and ask for confirmation."""
    icons = get_icons()
    full_cmd = ["shelfr"] + cmd
    if extra_args:
        full_cmd.extend(extra_args)

    cmd_str = " ".join(full_cmd)

    console.print(
        Panel(
            Group(
                Text("Command to execute:", style="dim"),
                Syntax(cmd_str, "bash", word_wrap=True),
            ),
            title=f"{icons.run} Command Preview",
            border_style="green",
            box=box.ROUNDED,
        )
    )

    return Confirm.ask("Proceed?", default=True)


def run_shelfr_command(cmd: list[str], extra_args: list[str] | None = None) -> int:
    """Run a shelfr command via subprocess."""
    icons = get_icons()
    # Use the shelfr CLI entry point directly
    full_cmd = ["shelfr"] + cmd
    if extra_args:
        full_cmd.extend(extra_args)

    console.print()
    console.rule("[dim]Output[/]", style="dim")

    # Preserve color output by ensuring TTY is passed through
    # and setting FORCE_COLOR for tools that respect it
    import os

    env = os.environ.copy()
    env["FORCE_COLOR"] = "1"
    env["CLICOLOR_FORCE"] = "1"

    result = subprocess.run(full_cmd, check=False, env=env)

    console.rule(style="dim")

    if result.returncode == 0:
        console.print(f"[success]{icons.ok} Command completed successfully.[/]")
    else:
        console.print(f"[error]{icons.fail} Command exited with code {result.returncode}[/]")

    return result.returncode


# =============================================================================
# Interactive Prompts
# =============================================================================


def ask_path(prompt: str, history: InMemoryHistory | None = None) -> str:
    """Ask for a path with optional history support."""
    if HAS_PROMPT_TOOLKIT and history is not None:
        from prompt_toolkit import PromptSession

        session: PromptSession[str] = PromptSession(history=history)
        try:
            raw = session.prompt(f"{prompt}: ")
        except (EOFError, KeyboardInterrupt):
            return ""
    else:
        raw = Prompt.ask(prompt)

    return raw.strip().strip("'\"") if raw else ""


def ask_asin(prompt: str = "ASIN") -> str:
    """Ask for an ASIN with validation."""
    if HAS_PROMPT_TOOLKIT and _asin_history is not None:
        from prompt_toolkit import PromptSession

        session: PromptSession[str] = PromptSession(history=_asin_history)
        try:
            raw = session.prompt(f"{prompt}: ")
        except (EOFError, KeyboardInterrupt):
            return ""
    else:
        raw = Prompt.ask(prompt)

    asin = raw.strip().upper() if raw else ""

    # Basic ASIN validation
    if asin and (len(asin) != 10 or not asin.isalnum()):
        icons = get_icons()
        msg = (
            f"[warning]{icons.warn} '{asin}' doesn't look like a valid ASIN "
            "(should be 10 alphanumeric chars)[/]"
        )
        console.print(msg)
        if not Confirm.ask("Continue anyway?", default=False):
            return ""

    return asin


def ask_dry_run() -> bool:
    """Ask if this should be a dry run."""
    return Confirm.ask("Dry run (preview only)?", default=True)


# =============================================================================
# Action Handlers
# =============================================================================


def handle_simple_command(action: WizardAction) -> None:
    """Handle a simple command that doesn't need extra input."""
    if not action.command:
        return

    extra_args: list[str] = []

    # Some commands benefit from asking about dry-run
    if (
        action.command[0] in ("run", "abs")
        and action.command[-1] in ("import", "cleanup")
        and ask_dry_run()
    ):
        extra_args = ["--dry-run"]

    if confirm_command(action.command, extra_args):
        run_shelfr_command(action.command, extra_args)


def handle_prepare() -> None:
    """Handle tools prepare with interactive prompts."""
    console.print("\n[info]📂 Prepare a release for upload[/]\n")

    folder = ask_path("Folder path", _path_history)
    if not folder:
        console.print("[warning]No folder provided, skipping.[/]")
        return

    asin = ask_asin("ASIN (optional, press Enter to skip)")

    cmd = ["tools", "prepare"]
    extra_args: list[str] = []

    if asin:
        extra_args.extend(["--asin", asin])

    extra_args.append(folder)

    if ask_dry_run():
        extra_args.insert(0, "--dry-run")

    if confirm_command(cmd, extra_args):
        run_shelfr_command(cmd, extra_args)


def handle_check_asin() -> None:
    """Handle abs check-asin with interactive prompt."""
    console.print("\n[info]🔍 Check if ASIN exists in Audiobookshelf[/]\n")

    asin = ask_asin()
    if not asin:
        console.print("[warning]No ASIN provided, skipping.[/]")
        return

    cmd = ["abs", "check-asin"]
    extra_args = ["--asin", asin]

    if confirm_command(cmd, extra_args):
        run_shelfr_command(cmd, extra_args)


def handle_search() -> None:
    """Handle libation search with interactive prompt."""
    console.print("\n[info]🔍 Search Libation library[/]\n")

    query = Prompt.ask("Search query")
    if not query:
        console.print("[warning]No query provided, skipping.[/]")
        return

    cmd = ["libation", "search"]
    extra_args = [query]

    if confirm_command(cmd, extra_args):
        run_shelfr_command(cmd, extra_args)


def pick_preset() -> str | None:
    """Display preset menu and get user choice."""
    try:
        from shelfr.config import get_settings
        from shelfr.mkbrr import load_presets

        presets = load_presets()
        settings = get_settings()
        presets_path = Path(settings.mkbrr.host_config_dir) / "presets.yaml"
    except Exception as e:
        console.print(f"[warning]Could not load presets: {e}[/]")
        return None

    if not presets:
        console.print("[dim]No presets found, skipping preset selection.[/]")
        return None

    # Build preset table
    table = Table(title="Presets (-P)", show_header=False, box=None, padding=(0, 2))
    table.add_column("idx", style="cyan")
    table.add_column("name")
    for i, p in enumerate(presets, 1):
        table.add_row(f"[{i}]", p)
    console.print(table)
    console.print(f"[dim](from {presets_path})[/]")

    choice = Prompt.ask(f"Choose preset [cyan][1-{len(presets)} or name][/]", default="1")

    if choice.isdigit():
        idx = int(choice)
        if 1 <= idx <= len(presets):
            return presets[idx - 1]

    # Allow typing preset name directly
    if choice:
        if choice not in presets:
            console.print(f"[warning]'{choice}' not found in presets.yaml; mkbrr may fail.[/]")
        return choice

    return presets[0] if presets else None


def handle_mkbrr_create() -> None:
    """Handle mkbrr create - create torrent from file/folder."""
    icons = get_icons()
    console.print(f"\n[info]{icons.create} Create torrent from file/folder[/]\n")

    # Step 1: Pick preset
    preset = pick_preset()

    # Step 2: Get content path
    content_path = ask_path("Content path (file or folder)", _path_history)
    if not content_path:
        console.print("[warning]No path provided, skipping.[/]")
        return

    # Check if path exists
    if not Path(content_path).exists():
        console.print(f"[error]{icons.fail} Path does not exist: {content_path}[/]")
        return

    cmd = ["mkbrr", "create"]
    extra_args: list[str] = []

    if preset:
        extra_args.extend(["-P", preset])

    extra_args.append(content_path)

    if confirm_command(cmd, extra_args):
        run_shelfr_command(cmd, extra_args)


def handle_mkbrr_inspect() -> None:
    """Handle mkbrr inspect - view torrent file details."""
    icons = get_icons()
    console.print(f"\n[info]{icons.inspect} Inspect .torrent file[/]\n")

    torrent_path = ask_path("Torrent file path (.torrent)", _path_history)
    if not torrent_path:
        console.print("[warning]No path provided, skipping.[/]")
        return

    # Check if file exists
    if not Path(torrent_path).is_file():
        console.print(f"[error]{icons.fail} File does not exist: {torrent_path}[/]")
        return

    verbose = Confirm.ask("Verbose output?", default=False)

    cmd = ["mkbrr", "inspect"]
    extra_args = [torrent_path]
    if verbose:
        extra_args.append("--verbose")

    if confirm_command(cmd, extra_args):
        run_shelfr_command(cmd, extra_args)


def handle_mkbrr_check() -> None:
    """Handle mkbrr check - verify data against torrent."""
    icons = get_icons()
    console.print(f"\n[info]{icons.check} Verify data against .torrent[/]\n")

    torrent_path = ask_path("Torrent file path (.torrent)", _path_history)
    if not torrent_path:
        console.print("[warning]No torrent path provided, skipping.[/]")
        return

    if not Path(torrent_path).is_file():
        console.print(f"[error]{icons.fail} Torrent file does not exist: {torrent_path}[/]")
        return

    content_path = ask_path("Content path to verify", _path_history)
    if not content_path:
        console.print("[warning]No content path provided, skipping.[/]")
        return

    if not Path(content_path).exists():
        console.print(f"[error]{icons.fail} Content path does not exist: {content_path}[/]")
        return

    verbose = Confirm.ask("Verbose output?", default=False)

    cmd = ["mkbrr", "check"]
    extra_args = [torrent_path, content_path]
    if verbose:
        extra_args.append("--verbose")

    if confirm_command(cmd, extra_args):
        run_shelfr_command(cmd, extra_args)


# =============================================================================
# Menu Navigation
# =============================================================================


def libation_menu() -> None:
    """Libation submenu loop."""
    while True:
        console.print()
        action = choose_action("Libation Operations", LIBATION_MENU_ACTIONS)

        if not action or action.key == "b":
            return

        if action.command == ["libation", "search"]:
            handle_search()
        elif action.command:
            handle_simple_command(action)

        console.print()
        if not Confirm.ask("Do another Libation operation?", default=False):
            return


def abs_menu() -> None:
    """Audiobookshelf submenu loop."""
    while True:
        console.print()
        action = choose_action("Audiobookshelf Operations", ABS_MENU_ACTIONS)

        if not action or action.key == "b":
            return

        if action.command == ["abs", "check-asin"]:
            handle_check_asin()
        elif action.command:
            handle_simple_command(action)

        console.print()
        if not Confirm.ask("Do another ABS operation?", default=False):
            return


def mkbrr_menu() -> None:
    """mkbrr submenu loop - similar to mkbrr-wizard."""
    while True:
        console.print()
        action = choose_action("mkbrr Torrent Tools", MKBRR_MENU_ACTIONS)

        if not action or action.key == "b":
            return

        if action.command == ["mkbrr", "create"]:
            handle_mkbrr_create()
        elif action.command == ["mkbrr", "inspect"]:
            handle_mkbrr_inspect()
        elif action.command == ["mkbrr", "check"]:
            handle_mkbrr_check()
        elif action.command:
            handle_simple_command(action)

        console.print()
        if not Confirm.ask("Do another mkbrr operation?", default=False):
            return


def tools_menu() -> None:
    """Tools submenu loop."""
    while True:
        console.print()
        action = choose_action("Tools", TOOLS_MENU_ACTIONS)

        if not action or action.key == "b":
            return

        if action.command == ["tools", "prepare"]:
            handle_prepare()
        elif action.key == "3":  # mkbrr submenu
            mkbrr_menu()
        elif action.command:
            handle_simple_command(action)

        console.print()
        if not Confirm.ask("Do another Tools operation?", default=False):
            return


def diagnostics_menu() -> None:
    """Diagnostics submenu loop."""
    while True:
        console.print()
        action = choose_action("Diagnostics", DIAGNOSTICS_MENU_ACTIONS)

        if not action or action.key == "b":
            return

        if action.command:
            handle_simple_command(action)

        console.print()
        if not Confirm.ask("Do another diagnostic?", default=False):
            return


# =============================================================================
# Main Loop
# =============================================================================


def main_menu() -> None:
    """Main menu loop."""
    while True:
        console.print()
        action = choose_action("Main Menu", MAIN_MENU_ACTIONS)

        if not action or action.key == "q":
            console.print("[dim]👋 Goodbye![/]")
            return

        # Handle submenus
        if action.label == "Libation":
            libation_menu()
        elif action.label == "Audiobookshelf":
            abs_menu()
        elif action.label == "Tools":
            tools_menu()
        elif action.label == "Diagnostics":
            diagnostics_menu()
        elif action.command:
            handle_simple_command(action)


def run_wizard() -> int:
    """Entry point for the wizard."""
    try:
        render_header()
        main_menu()
        return 0
    except KeyboardInterrupt:
        console.print("\n[dim]⏹ Interrupted. Goodbye![/]")
        return 130


def main() -> None:
    """CLI entry point."""
    sys.exit(run_wizard())


if __name__ == "__main__":
    main()
