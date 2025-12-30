"""ASCII banner and version display for shelfr CLI.

Provides the styled banner shown at startup and version information.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING

from rich.align import Align
from rich.panel import Panel
from rich.text import Text

if TYPE_CHECKING:
    from rich.console import Console


def get_version() -> str:
    """Get the current shelfr version.

    Tries importlib.metadata first (for installed package),
    falls back to __version__ in __init__.py.

    Returns:
        Version string like "0.1.0"
    """
    try:
        return version("shelfr")
    except PackageNotFoundError:
        # Fallback for development/editable installs
        from shelfr import __version__

        return __version__


# ASCII art with gradient colors (pink -> purple)
# Width: 48 characters
BANNER_WIDTH = 48
BANNER_ART = """\
[bold #FF10F0]███████╗██╗  ██╗███████╗██╗     ███████╗██████╗ [/]
[bold #EC4899]██╔════╝██║  ██║██╔════╝██║     ██╔════╝██╔══██╗[/]
[bold #C19EE0]███████╗███████║█████╗  ██║     █████╗  ██████╔╝[/]
[bold #9D4EDD]╚════██║██╔══██║██╔══╝  ██║     ██╔══╝  ██╔══██╗[/]
[bold #7C3AED]███████║██║  ██║███████╗███████╗██║     ██║  ██║[/]
[bold #6D28D9]╚══════╝╚═╝  ╚═╝╚══════╝╚══════╝╚═╝     ╚═╝  ╚═╝[/]"""


def make_banner_text() -> Text:
    """Create the full banner with version as Rich Text.

    Returns:
        Rich Text object with the complete banner
    """
    ver = get_version()
    # Build tagline and center it to match ASCII art width
    tagline_text = f"Ingest • Enrich • Seed   v{ver}   // shelfr"
    padding = (BANNER_WIDTH - len(tagline_text)) // 2
    tagline = f"[dim]Ingest • Enrich • Seed[/]   [bold #06B6D4]v{ver}[/]   [dim]// shelfr[/]"
    centered_tagline = " " * padding + tagline
    return Text.from_markup(f"{BANNER_ART}\n\n{centered_tagline}")


def print_banner(console: Console, *, border_style: str = "#6D28D9") -> None:
    """Print the shelfr banner to console.

    Args:
        console: Rich console to print to
        border_style: Color for the panel border
    """
    banner = make_banner_text()
    centered = Align.center(banner)
    panel = Panel(
        centered,
        border_style=border_style,
        padding=(1, 2),
    )
    console.print(panel)


def get_version_string() -> str:
    """Get formatted version string for display.

    Returns:
        Formatted string like "shelfr v0.1.0"
    """
    return f"shelfr v{get_version()}"
