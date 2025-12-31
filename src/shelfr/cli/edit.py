"""Edit commands (sub-app).

Commands for editing configuration files with $EDITOR integration.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer

from shelfr.console import console, print_error, print_success, print_warning

logger = logging.getLogger(__name__)


# =============================================================================
# Edit Command Group
# =============================================================================

EDIT_EPILOG = """
[bold cyan]Quick Edit Commands:[/]
  shelfr edit config     [dim]# Edit config/config.yaml[/]
  shelfr edit presets    [dim]# Edit mkbrr presets.yaml[/]
  shelfr edit naming     [dim]# Edit config/naming.json[/]

[bold cyan]Inline Editor (TUI):[/]
  shelfr edit inline <path>  [dim]# Edit in terminal (needs shelfr[tui])[/]

[bold cyan]Edit Any File:[/]
  shelfr edit file <path>  [dim]# Edit any file with $EDITOR[/]

[dim]💡 Set $EDITOR or $VISUAL to use your preferred editor.[/]
[dim]   YAML files are validated after editing.[/]
"""


def make_edit_app() -> typer.Typer:
    """Create the edit sub-app."""
    return typer.Typer(
        name="edit",
        help="📝 Edit configuration files",
        epilog=EDIT_EPILOG,
        rich_markup_mode="rich",
        no_args_is_help=True,
    )


def register_edit_commands(edit_app: typer.Typer) -> None:
    """Register edit commands on the edit sub-app."""

    @edit_app.callback(invoke_without_command=True)
    def edit_callback(ctx: typer.Context) -> None:
        """📝 Edit configuration files.

        Opens files in your $EDITOR (or $VISUAL) for editing.
        YAML and JSON files are validated after saving.

        [bold]Quick Commands:[/]
          shelfr edit config   [dim]# config/config.yaml[/]
          shelfr edit presets  [dim]# mkbrr presets.yaml[/]
          shelfr edit naming   [dim]# config/naming.json[/]
          shelfr edit sig      [dim]# signature template[/]

        [bold]Environment:[/]
          Set [cyan]$EDITOR[/] or [cyan]$VISUAL[/] to your preferred editor.
          Examples: nano, vim, code --wait, subl -w

        Running [cyan]shelfr edit[/] without a command shows this help.
        """
        if ctx.invoked_subcommand is None:
            console.print(ctx.get_help())
            raise typer.Exit(0)

    @edit_app.command("file")
    def edit_file_cmd(
        path: Annotated[
            Path,
            typer.Argument(
                help="Path to file to edit.",
                exists=True,
                readable=True,
            ),
        ],
        editor: Annotated[
            str | None,
            typer.Option(
                "--editor",
                "-e",
                help="Editor command (overrides $EDITOR).",
            ),
        ] = None,
        no_validate: Annotated[
            bool,
            typer.Option(
                "--no-validate",
                help="Skip validation for YAML/JSON files.",
            ),
        ] = False,
        no_backup: Annotated[
            bool,
            typer.Option(
                "--no-backup",
                help="Don't create .bak backup file.",
            ),
        ] = False,
    ) -> None:
        """📄 Edit any file.

        Opens the specified file in your editor. YAML and JSON files
        are validated after saving (unless --no-validate is used).

        [bold]Examples:[/]
          shelfr edit file config/config.yaml
          shelfr edit file batch.yaml --editor "code --wait"
          shelfr edit file data.json --no-validate
        """
        from shelfr.utils.editor import (
            EditorError,
            NoEditorError,
            edit_file,
            edit_json,
            edit_yaml,
        )

        suffix = path.suffix.lower()
        validate = not no_validate
        backup = not no_backup

        try:
            if suffix in (".yaml", ".yml"):
                success = edit_yaml(
                    path, validate=validate, backup=backup, editor=editor
                )
            elif suffix == ".json":
                success = edit_json(
                    path, validate=validate, backup=backup, editor=editor
                )
            else:
                success = edit_file(path, editor=editor)

            if success:
                print_success(f"Saved: {path}")
            else:
                print_warning("No changes made (or validation failed)")
                raise typer.Exit(1)

        except NoEditorError as e:
            print_error(str(e))
            console.print(
                "\n[dim]Set the EDITOR environment variable:[/]\n"
                "  [cyan]export EDITOR=nano[/]  [dim]# or vim, code --wait, etc.[/]"
            )
            raise typer.Exit(1) from None
        except EditorError as e:
            print_error(f"Editor error: {e}")
            raise typer.Exit(1) from None

    @edit_app.command("config")
    def edit_config(
        editor: Annotated[
            str | None,
            typer.Option("--editor", "-e", help="Editor command."),
        ] = None,
    ) -> None:
        """🔧 Edit shelfr config.yaml.

        Opens config/config.yaml in your editor. The file is validated
        after saving to catch YAML syntax errors.

        [bold]Example:[/]
          shelfr edit config
          shelfr edit config --editor vim
        """
        from shelfr.utils.editor import EditorError, NoEditorError, edit_yaml

        # Find config.yaml - check common locations
        config_paths = [
            Path("config/config.yaml"),
            Path("config.yaml"),
            Path.cwd() / "config" / "config.yaml",
        ]

        config_path = None
        for p in config_paths:
            if p.exists():
                config_path = p.resolve()
                break

        if not config_path:
            print_error("config.yaml not found")
            console.print(
                "[dim]Searched:[/]\n"
                + "\n".join(f"  • {p}" for p in config_paths)
            )
            raise typer.Exit(1)

        try:
            if edit_yaml(config_path, validate=True, backup=True, editor=editor):
                print_success(f"Saved: {config_path}")
                console.print(
                    "[dim]💡 Restart shelfr for config changes to take effect.[/]"
                )
            else:
                print_warning("No changes made (or invalid YAML)")
                raise typer.Exit(1)

        except NoEditorError as e:
            print_error(str(e))
            raise typer.Exit(1) from None
        except EditorError as e:
            print_error(f"Editor error: {e}")
            raise typer.Exit(1) from None

    @edit_app.command("presets")
    def edit_presets(
        editor: Annotated[
            str | None,
            typer.Option("--editor", "-e", help="Editor command."),
        ] = None,
    ) -> None:
        """🎯 Edit mkbrr presets.yaml.

        Opens the mkbrr presets configuration file for editing.
        Location is determined by mkbrr.host_config_dir in config.yaml.

        [bold]Example:[/]
          shelfr edit presets
        """
        from shelfr.config import config
        from shelfr.utils.editor import EditorError, NoEditorError, edit_yaml

        presets_path = Path(config.mkbrr.host_config_dir) / "presets.yaml"

        if not presets_path.exists():
            print_error(f"presets.yaml not found: {presets_path}")
            console.print(
                "\n[dim]Expected location from config.yaml mkbrr.host_config_dir:[/]\n"
                f"  {config.mkbrr.host_config_dir}\n\n"
                "[dim]Create the file or check your configuration.[/]"
            )
            raise typer.Exit(1)

        try:
            if edit_yaml(presets_path, validate=True, backup=True, editor=editor):
                print_success(f"Saved: {presets_path}")
            else:
                print_warning("No changes made (or invalid YAML)")
                raise typer.Exit(1)

        except NoEditorError as e:
            print_error(str(e))
            raise typer.Exit(1) from None
        except EditorError as e:
            print_error(f"Editor error: {e}")
            raise typer.Exit(1) from None

    @edit_app.command("naming")
    def edit_naming(
        editor: Annotated[
            str | None,
            typer.Option("--editor", "-e", help="Editor command."),
        ] = None,
    ) -> None:
        """📝 Edit naming.json rules.

        Opens config/naming.json for editing. This file controls
        title/author/series normalization rules.

        [bold]Example:[/]
          shelfr edit naming
        """
        from shelfr.utils.editor import EditorError, NoEditorError, edit_json

        naming_paths = [
            Path("config/naming.json"),
            Path.cwd() / "config" / "naming.json",
        ]

        naming_path = None
        for p in naming_paths:
            if p.exists():
                naming_path = p.resolve()
                break

        if not naming_path:
            print_error("naming.json not found")
            raise typer.Exit(1)

        try:
            if edit_json(naming_path, validate=True, backup=True, editor=editor):
                print_success(f"Saved: {naming_path}")
            else:
                print_warning("No changes made (or invalid JSON)")
                raise typer.Exit(1)

        except NoEditorError as e:
            print_error(str(e))
            raise typer.Exit(1) from None
        except EditorError as e:
            print_error(f"Editor error: {e}")
            raise typer.Exit(1) from None

    @edit_app.command("sig")
    def edit_signature(
        editor: Annotated[
            str | None,
            typer.Option("--editor", "-e", help="Editor command."),
        ] = None,
    ) -> None:
        """📜 Edit signature template.

        Opens config/templates/signature.j2 for editing.
        This Jinja2 template is used for BBCode signatures.

        [bold]Example:[/]
          shelfr edit sig
        """
        from shelfr.utils.editor import EditorError, NoEditorError, edit_jinja2

        sig_paths = [
            Path("config/templates/signature.j2"),
            Path.cwd() / "config" / "templates" / "signature.j2",
        ]

        sig_path = None
        for p in sig_paths:
            if p.exists():
                sig_path = p.resolve()
                break

        if not sig_path:
            print_error("signature.j2 not found")
            console.print(
                "[dim]Expected: config/templates/signature.j2[/]"
            )
            raise typer.Exit(1)

        try:
            if edit_jinja2(sig_path, editor=editor):
                print_success(f"Saved: {sig_path}")
            else:
                print_warning("No changes made")
                raise typer.Exit(1)

        except NoEditorError as e:
            print_error(str(e))
            raise typer.Exit(1) from None
        except EditorError as e:
            print_error(f"Editor error: {e}")
            raise typer.Exit(1) from None

    @edit_app.command("categories")
    def edit_categories(
        editor: Annotated[
            str | None,
            typer.Option("--editor", "-e", help="Editor command."),
        ] = None,
    ) -> None:
        """📂 Edit categories.json.

        Opens config/categories.json for editing.
        This maps genres to MAM category IDs.

        [bold]Example:[/]
          shelfr edit categories
        """
        from shelfr.utils.editor import EditorError, NoEditorError, edit_json

        cat_paths = [
            Path("config/categories.json"),
            Path.cwd() / "config" / "categories.json",
        ]

        cat_path = None
        for p in cat_paths:
            if p.exists():
                cat_path = p.resolve()
                break

        if not cat_path:
            print_error("categories.json not found")
            raise typer.Exit(1)

        try:
            if edit_json(cat_path, validate=True, backup=True, editor=editor):
                print_success(f"Saved: {cat_path}")
            else:
                print_warning("No changes made (or invalid JSON)")
                raise typer.Exit(1)

        except NoEditorError as e:
            print_error(str(e))
            raise typer.Exit(1) from None
        except EditorError as e:
            print_error(f"Editor error: {e}")
            raise typer.Exit(1) from None

    # =========================================================================
    # Inline Editor Commands (Tier 2 - requires shelfr[tui])
    # =========================================================================

    @edit_app.command("inline")
    def edit_inline(
        path: Annotated[
            Path,
            typer.Argument(
                help="Path to file to edit.",
                exists=True,
                readable=True,
            ),
        ],
        no_validate: Annotated[
            bool,
            typer.Option(
                "--no-validate",
                help="Skip validation for YAML/JSON files.",
            ),
        ] = False,
        no_backup: Annotated[
            bool,
            typer.Option(
                "--no-backup",
                help="Don't create .bak backup file.",
            ),
        ] = False,
    ) -> None:
        """💻 Edit file with inline terminal editor.

        Opens an embedded editor that stays in the terminal.
        Supports syntax highlighting for YAML, JSON, Markdown.

        [bold]Keybindings:[/]
          [cyan]Ctrl+D[/]  Save and exit
          [cyan]Ctrl+C[/]  Cancel

        [bold]Examples:[/]
          shelfr edit inline config/config.yaml
          shelfr edit inline presets.yaml --no-validate

        [bold]Requires:[/] pip install shelfr[tui]
        """
        try:
            from shelfr.utils.mini_editor import (
                MiniEditorNotAvailable,
                edit_file_inline,
            )
        except ImportError:
            print_error("Inline editor requires: pip install shelfr[tui]")
            raise typer.Exit(1) from None

        try:
            success = edit_file_inline(
                path,
                validate=not no_validate,
                backup=not no_backup,
            )
            if not success:
                raise typer.Exit(1)

        except MiniEditorNotAvailable:
            print_error("Inline editor requires: pip install shelfr[tui]")
            console.print(
                "\n[dim]Install the TUI extras:[/]\n"
                "  [cyan]pip install shelfr[tui][/]"
            )
            raise typer.Exit(1) from None
        except FileNotFoundError as e:
            print_error(str(e))
            raise typer.Exit(1) from None

    @edit_app.command("preview")
    def preview_file_cmd(
        path: Annotated[
            Path,
            typer.Argument(
                help="Path to file to preview.",
                exists=True,
                readable=True,
            ),
        ],
        lines: Annotated[
            int | None,
            typer.Option(
                "--lines",
                "-n",
                help="Maximum lines to show.",
            ),
        ] = 50,
    ) -> None:
        """👀 Preview file with syntax highlighting.

        Shows file content with syntax highlighting based on extension.

        [bold]Examples:[/]
          shelfr edit preview config.yaml
          shelfr edit preview README.md --lines 100
        """
        from shelfr.utils.preview import preview_file

        preview_file(path, max_lines=lines, console=console)

    @edit_app.command("diff")
    def diff_files(
        file1: Annotated[
            Path,
            typer.Argument(help="First file (before).", exists=True),
        ],
        file2: Annotated[
            Path,
            typer.Argument(help="Second file (after).", exists=True),
        ],
    ) -> None:
        """📊 Show diff between two files.

        Displays a unified diff with syntax highlighting.

        [bold]Example:[/]
          shelfr edit diff config.yaml config.yaml.bak
        """
        from shelfr.utils.preview import preview_diff

        before = file1.read_text(encoding="utf-8")
        after = file2.read_text(encoding="utf-8")

        title = f"{file1.name} → {file2.name}"
        if not preview_diff(before, after, title=title, console=console):
            console.print("[dim]Files are identical[/]")

    @edit_app.command("yaml-tree")
    def yaml_tree(
        path: Annotated[
            Path,
            typer.Argument(
                help="Path to YAML file.",
                exists=True,
            ),
        ],
        depth: Annotated[
            int,
            typer.Option("--depth", "-d", help="Maximum tree depth."),
        ] = 3,
    ) -> None:
        """🌳 Show YAML file as tree structure.

        Displays the structure of a YAML file as a tree,
        showing keys and value types.

        [bold]Example:[/]
          shelfr edit yaml-tree config/config.yaml
          shelfr edit yaml-tree presets.yaml --depth 2
        """
        from shelfr.utils.preview import preview_yaml_structure

        content = path.read_text(encoding="utf-8")
        preview_yaml_structure(
            content,
            title=path.name,
            max_depth=depth,
            console=console,
        )

    @edit_app.command("tui")
    def tui(
        path: Annotated[
            Path | None,
            typer.Argument(
                help="Directory or file to open. Defaults to config/.",
            ),
        ] = None,
    ) -> None:
        """💻 Launch full-screen TUI editor.

        Opens a full-screen terminal interface with file browser,
        editor, and validation preview. Supports YAML, JSON, and
        Jinja2 template files.

        [bold]Features:[/]
          • File tree navigation (left pane)
          • Syntax-highlighted editor (center)
          • Real-time validation (right pane)
          • Keyboard shortcuts (F1 for help)

        [bold]Keyboard Shortcuts:[/]
          Ctrl+S / F2  Save file
          F3           Validate content
          F5           Reload from disk
          Ctrl+O       Focus file tree
          Ctrl+E       Focus editor
          Ctrl+Q       Quit

        [bold]Examples:[/]
          shelfr edit tui                 [dim]# Open at config/[/]
          shelfr edit tui /path/to/dir    [dim]# Open at directory[/]
          shelfr edit tui config.yaml     [dim]# Open specific file[/]

        [bold]Requirements:[/]
          Requires [cyan]shelfr[tui][/] extras:
          [dim]pip install shelfr[tui][/]
        """
        try:
            from shelfr.tui import check_available

            if not check_available():
                print_error("Textual TUI not available")
                console.print(
                    "\n[dim]Install TUI dependencies:[/]\n"
                    "  [cyan]pip install shelfr[tui][/]\n"
                    "\n[dim]Or install textual directly:[/]\n"
                    "  [cyan]pip install textual[/]"
                )
                raise typer.Exit(1)

            from shelfr.tui.app import run_tui

            # Resolve path
            target_path: Path | None = None
            target_file: Path | None = None

            if path:
                resolved = Path(path).resolve()
                if resolved.is_file():
                    target_file = resolved
                    target_path = resolved.parent
                elif resolved.is_dir():
                    target_path = resolved
                else:
                    print_error(f"Path not found: {path}")
                    raise typer.Exit(1)

            run_tui(path=target_path, file=target_file)

        except ImportError as e:
            print_error(f"TUI dependencies not installed: {e}")
            console.print(
                "\n[dim]Install with:[/]\n"
                "  [cyan]pip install shelfr[tui][/]"
            )
            raise typer.Exit(1) from None

