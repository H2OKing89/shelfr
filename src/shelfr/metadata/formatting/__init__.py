"""
Formatting subpackage for MAM descriptions.

BBCode and HTML conversion utilities for rendering audiobook descriptions.
"""

from __future__ import annotations

# Private exports (for internal use / testing)
from shelfr.metadata.formatting.bbcode import (
    _convert_newlines_for_mam as _convert_newlines_for_mam,
)
from shelfr.metadata.formatting.bbcode import (
    _format_release_date as _format_release_date,
)

# Public exports
from shelfr.metadata.formatting.bbcode import (
    render_bbcode_description as render_bbcode_description,
)
from shelfr.metadata.formatting.html import (
    _clean_html as _clean_html,
)
from shelfr.metadata.formatting.html import (
    html_to_bbcode as html_to_bbcode,
)

__all__ = [
    "_clean_html",
    # Private (re-exported for backward compat)
    "_convert_newlines_for_mam",
    "_format_release_date",
    "html_to_bbcode",
    # Public
    "render_bbcode_description",
]
