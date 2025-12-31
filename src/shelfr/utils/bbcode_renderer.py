"""BBCode to Rich rendering utilities.

Converts BBCode markup to Rich console output for visual preview.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from rich.align import Align
from rich.console import Group
from rich.panel import Panel
from rich.style import Style
from rich.text import Text

if TYPE_CHECKING:
    from rich.console import Console, RenderableType


def render_bbcode_to_rich(bbcode: str, console: Console | None = None) -> RenderableType:
    """Convert BBCode to Rich renderable for visual preview.

    This provides an approximate visual representation of how BBCode
    will render on MAM. Not pixel-perfect, but useful for previewing
    formatting and catching obvious issues.

    Args:
        bbcode: Raw BBCode string
        console: Optional console for width calculations

    Returns:
        Rich renderable object
    """
    # First, convert [br] tags to actual newlines for processing
    text = bbcode.replace("[br]", "\n")

    # Convert non-breaking spaces back to regular spaces for display
    text = text.replace("\u00a0", " ")

    # Parse and render
    rendered = _parse_bbcode(text)

    return rendered


def _parse_bbcode(text: str) -> RenderableType:
    """Parse BBCode and convert to Rich renderables.

    Handles nested tags and maintains formatting context.
    """
    # Split by top-level [center] blocks first
    center_pattern = re.compile(r"\[center\](.*?)\[/center\]", re.IGNORECASE | re.DOTALL)

    parts: list[RenderableType] = []
    last_end = 0

    for match in center_pattern.finditer(text):
        # Add any text before this center block
        before = text[last_end : match.start()]
        if before.strip():
            parts.append(_render_text_segment(before, centered=False))

        # Render the centered content - each line should be centered
        inner = match.group(1)
        centered_parts = _render_text_segment(inner, centered=True)
        parts.append(centered_parts)

        last_end = match.end()

    # Add remaining text after last center block
    after = text[last_end:]
    if after.strip():
        parts.append(_render_text_segment(after, centered=False))

    if len(parts) == 1:
        return parts[0]
    return Group(*parts)


def _render_text_segment(text: str, centered: bool = False) -> RenderableType:
    """Render a text segment, handling [pre] blocks specially.

    Args:
        text: The text segment to render
        centered: Whether this segment should be centered
    """
    # Check for [pre] blocks
    pre_pattern = re.compile(r"\[pre\](.*?)\[/pre\]", re.IGNORECASE | re.DOTALL)

    parts: list[RenderableType] = []
    last_end = 0

    for match in pre_pattern.finditer(text):
        # Add any text before this pre block
        before = text[last_end : match.start()]
        if before.strip():
            # For centered content, split by newlines and center each line
            if centered:
                for line in before.split("\n"):
                    if line.strip():
                        parts.append(Align.center(_render_inline_bbcode(line)))
            else:
                parts.append(_render_inline_bbcode(before))

        # Render the pre block (monospace, preserve whitespace)
        inner = match.group(1)
        pre_text = _render_inline_bbcode(inner, monospace=True)
        if centered:
            parts.append(Align.center(pre_text))
        else:
            parts.append(pre_text)

        last_end = match.end()

    # Add remaining text
    after = text[last_end:]
    if after.strip():
        # For centered content, split by newlines and center each line
        if centered:
            for line in after.split("\n"):
                if line.strip():
                    parts.append(Align.center(_render_inline_bbcode(line)))
        else:
            parts.append(_render_inline_bbcode(after))

    if len(parts) == 1:
        return parts[0]
    return Group(*parts)


def _render_inline_bbcode(text: str, monospace: bool = False) -> Text:
    """Render inline BBCode tags to Rich Text.

    Handles: [b], [i], [color], [size], [url], [hide], [font]
    """
    result = Text()

    # Stack to track current styles
    style_stack: list[Style] = []
    # Note: Rich doesn't support font family in Style, but we handle
    # monospace display through the [pre] block panel styling

    # Process character by character with tag detection
    i = 0
    while i < len(text):
        # Check for BBCode tag
        if text[i] == "[":
            tag_match = re.match(r"\[(/?)(\w+)(?:=([^\]]*))?\]", text[i:], re.IGNORECASE)
            if tag_match:
                is_closing = tag_match.group(1) == "/"
                tag_name = tag_match.group(2).lower()
                tag_value = tag_match.group(3)

                # Handle different tags
                if tag_name == "b":
                    if is_closing:
                        _pop_style(style_stack, "bold")
                    else:
                        style_stack.append(Style(bold=True))
                    i += tag_match.end()
                    continue

                elif tag_name == "i":
                    if is_closing:
                        _pop_style(style_stack, "italic")
                    else:
                        style_stack.append(Style(italic=True))
                    i += tag_match.end()
                    continue

                elif tag_name == "color":
                    if is_closing:
                        _pop_style(style_stack, "color")
                    elif tag_value:
                        # Convert hex color
                        color = tag_value.strip()
                        if color.startswith("#"):
                            style_stack.append(Style(color=color))
                        else:
                            style_stack.append(Style(color=color))
                    i += tag_match.end()
                    continue

                elif tag_name == "size":
                    # Rich doesn't support font sizes, skip
                    i += tag_match.end()
                    continue

                elif tag_name == "font":
                    # Skip font tags (Rich has limited font support)
                    i += tag_match.end()
                    continue

                elif tag_name == "url":
                    if is_closing:
                        _pop_style(style_stack, "link")
                    elif tag_value:
                        # Add underline and cyan for links
                        style_stack.append(Style(underline=True, color="cyan"))
                    i += tag_match.end()
                    continue

                elif tag_name == "hide":
                    if is_closing:
                        pass  # Handled below
                    else:
                        # Find the closing [/hide] and extract content
                        hide_end = text.lower().find("[/hide]", i)
                        if hide_end > 0:
                            hide_content = text[i + tag_match.end() : hide_end]
                            title = tag_value or "Spoiler"
                            # Add a collapsed indicator
                            result.append(f"\n▶ {title} ", style=Style(bold=True, color="yellow"))
                            result.append("[click to expand]\n", style=Style(dim=True))
                            # Show content in dim
                            hide_rendered = _render_inline_bbcode(hide_content, monospace=monospace)
                            result.append_text(hide_rendered)
                            i = hide_end + len("[/hide]")
                            continue
                    i += tag_match.end()
                    continue

        # Regular character - add with current combined style
        combined_style = _combine_styles(style_stack)
        result.append(text[i], style=combined_style)
        i += 1

    return result


def _combine_styles(style_stack: list[Style]) -> Style:
    """Combine multiple styles into one."""
    if not style_stack:
        return Style()

    result = Style()
    for style in style_stack:
        result = result + style
    return result


def _pop_style(style_stack: list[Style], style_type: str) -> None:
    """Pop the most recent style of a given type."""
    # Simple implementation - just pop last style
    # A more sophisticated version would track style types
    if style_stack:
        style_stack.pop()


def render_bbcode_preview(
    bbcode: str,
    console: Console,
    title: str = "BBCode Preview",
) -> None:
    """Render BBCode preview to console with a nice panel.

    Args:
        bbcode: Raw BBCode string to render
        console: Rich console to render to
        title: Panel title
    """
    rendered = render_bbcode_to_rich(bbcode, console)

    console.print()
    console.print(
        Panel(
            rendered,
            title=f"[bold]{title}[/]",
            border_style="cyan",
            padding=(1, 2),
        )
    )
    console.print()

    # Add note about MAM upload page bug
    console.print("[dim]⚠  Note: MAM's upload page preview renderer has a bug that may show[/]")
    console.print(
        "[dim]   ASCII art incorrectly. The actual torrent page will render correctly.[/]"
    )
    console.print()
