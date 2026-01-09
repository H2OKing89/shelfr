"""
Hardcover metadata client package.

Phase 12: Hardcover API client for content warnings and rich metadata.

This package provides:
- HardcoverAsyncClient: Async GraphQL client with rate limiting
- Search and matching utilities
- Pydantic schemas for API responses

Usage:
    async with HardcoverAsyncClient() as client:
        book = await client.search_book(title="It", author="Stephen King")
        if book:
            print(book.content_warnings)
"""

from __future__ import annotations

from .async_client import HardcoverAsyncClient
from .schemas import HardcoverBook, HardcoverSearchResult

__all__ = [
    "HardcoverAsyncClient",
    "HardcoverBook",
    "HardcoverSearchResult",
]
