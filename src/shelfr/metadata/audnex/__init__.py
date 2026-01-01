"""
Audnex API client for audiobook metadata.

Provides functions to fetch book, author, and chapter data from the Audnex API
with region fallback support.

Public API:
    fetch_audnex_book: Fetch book metadata by ASIN
    fetch_audnex_author: Fetch author metadata by ASIN
    fetch_audnex_chapters: Fetch chapter data by ASIN
    save_audnex_json: Save Audnex response to JSON file
"""

from __future__ import annotations

# Private helpers (exposed for testing and backward compatibility)
from shelfr.metadata.audnex.client import (
    _fetch_audnex_book_region as _fetch_audnex_book_region,
)
from shelfr.metadata.audnex.client import (
    _fetch_audnex_chapters_region as _fetch_audnex_chapters_region,
)
from shelfr.metadata.audnex.client import (
    fetch_audnex_author as fetch_audnex_author,
)
from shelfr.metadata.audnex.client import (
    fetch_audnex_book as fetch_audnex_book,
)
from shelfr.metadata.audnex.client import (
    fetch_audnex_chapters as fetch_audnex_chapters,
)
from shelfr.metadata.audnex.client import (
    save_audnex_json as save_audnex_json,
)

__all__ = [
    # Public API
    "fetch_audnex_author",
    "fetch_audnex_book",
    "fetch_audnex_chapters",
    "save_audnex_json",
    # Private (for testing/backward compat)
    "_fetch_audnex_book_region",
    "_fetch_audnex_chapters_region",
]
