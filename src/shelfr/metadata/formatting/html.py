"""
HTML to BBCode conversion utilities for MAM descriptions.
"""

from __future__ import annotations

import html as html_lib
import re

__all__ = ["html_to_bbcode"]


def html_to_bbcode(text: str) -> str:
    """
    Convert HTML tags to BBCode for MAM description.

    Supported MAM BBCode tags:
    - [b], [i], [u], [s] - Basic formatting
    - [size=N], [font=], [color=] - Font styling
    - [url], [url=] - Links (converted from <a href>)
    - [center], [sup], [sub] - Layout
    - [br] - Line breaks

    Converts:
    - <a href="URL">text</a> → [url=URL]text[/url]
    - <b>, <strong> → [b], [/b]
    - <i>, <em> → [i], [/i]
    - <u> → [u], [/u]
    - <s>, <strike> → [s], [/s]
    - </p> → [br][br] (paragraph break)
    - <br> → [br] (line break)

    MAM requires explicit [br] tags for line breaks - plain newlines
    in the JSON are ignored by their BBCode renderer.

    Also decodes HTML entities.
    """
    # Convert anchor tags to BBCode [url=...] format
    # Match <a href="URL"> or <a href='URL'> with optional other attributes
    text = re.sub(
        r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        r"[url=\1]\2[/url]",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # Handle anchor tags without href (just keep inner text)
    text = re.sub(r"<a\s+[^>]*>(.*?)</a>", r"\1", text, flags=re.IGNORECASE | re.DOTALL)

    # Convert bold tags to BBCode
    text = re.sub(r"<b\b[^>]*>", "[b]", text, flags=re.IGNORECASE)
    text = re.sub(r"</b>", "[/b]", text, flags=re.IGNORECASE)
    text = re.sub(r"<strong\b[^>]*>", "[b]", text, flags=re.IGNORECASE)
    text = re.sub(r"</strong>", "[/b]", text, flags=re.IGNORECASE)

    # Convert italic tags to BBCode
    text = re.sub(r"<i\b[^>]*>", "[i]", text, flags=re.IGNORECASE)
    text = re.sub(r"</i>", "[/i]", text, flags=re.IGNORECASE)
    text = re.sub(r"<em\b[^>]*>", "[i]", text, flags=re.IGNORECASE)
    text = re.sub(r"</em>", "[/i]", text, flags=re.IGNORECASE)

    # Convert underline tags to BBCode
    text = re.sub(r"<u\b[^>]*>", "[u]", text, flags=re.IGNORECASE)
    text = re.sub(r"</u>", "[/u]", text, flags=re.IGNORECASE)

    # Convert strikethrough tags to BBCode
    text = re.sub(r"<s\b[^>]*>", "[s]", text, flags=re.IGNORECASE)
    text = re.sub(r"</s>", "[/s]", text, flags=re.IGNORECASE)
    text = re.sub(r"<strike\b[^>]*>", "[s]", text, flags=re.IGNORECASE)
    text = re.sub(r"</strike>", "[/s]", text, flags=re.IGNORECASE)

    # Convert paragraph breaks to [br][br] for MAM
    # Handle both </p> and <p> as paragraph boundaries
    text = re.sub(r"</p>\s*", "[br][br]", text, flags=re.IGNORECASE)
    text = re.sub(r"<p[^>]*>", "", text, flags=re.IGNORECASE)

    # Convert <br> tags to [br]
    text = re.sub(r"<br\s*/?>", "[br]", text, flags=re.IGNORECASE)

    # Remove any remaining HTML tags (that we don't support)
    text = re.sub(r"<[^>]+>", "", text)

    # Decode HTML entities (handles &amp;, &lt;, &#39;, etc.)
    text = html_lib.unescape(text)

    # Clean up excessive whitespace
    text = re.sub(r"[ \t]+", " ", text)  # Collapse horizontal whitespace
    text = re.sub(r"(\[br\]){3,}", "[br][br]", text)  # Max 2 [br] tags
    return text.strip()


# Keep the old name as an alias for backward compatibility within the module
_html_to_bbcode = html_to_bbcode


def _clean_html(text: str) -> str:
    """
    Clean HTML tags from description text (strips all formatting).

    DEPRECATED: Use html_to_bbcode() for MAM descriptions to preserve formatting.

    Converts HTML paragraphs to newlines, strips remaining tags,
    and decodes HTML entities.
    """
    import warnings

    warnings.warn(
        "_clean_html is deprecated, use html_to_bbcode() instead",
        DeprecationWarning,
        stacklevel=2,
    )
    # Convert paragraph breaks to double newlines (before stripping tags)
    # Handle both </p> and <p> as paragraph boundaries
    text = re.sub(r"</p>\s*", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<p[^>]*>", "", text, flags=re.IGNORECASE)
    # Convert <br> tags to single newlines
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    # Remove remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Decode HTML entities (handles &amp;, &lt;, &#39;, etc.)
    text = html_lib.unescape(text)
    # Clean up excessive whitespace while preserving intentional newlines
    text = re.sub(r"[ \t]+", " ", text)  # Collapse horizontal whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)  # Max 2 newlines (1 blank line)
    return text.strip()
