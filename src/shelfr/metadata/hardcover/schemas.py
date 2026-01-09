"""
Pydantic schemas for Hardcover API responses.

Phase 12.1: Type-safe parsing of Hardcover GraphQL responses.

These schemas validate and normalize API responses. The Hardcover API
uses GraphQL with Typesense search backend, returning slightly different
shapes for search vs direct book queries.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HardcoverAuthor(BaseModel):
    """Author from Hardcover API."""

    name: str


class HardcoverGenre(BaseModel):
    """Genre/mood/tag from Hardcover API."""

    name: str


class HardcoverContentWarning(BaseModel):
    """Content warning from Hardcover API."""

    name: str


class HardcoverBook(BaseModel):
    """Book metadata from Hardcover API.

    This schema handles both search results (flattened arrays) and
    direct book queries (nested objects).

    Attributes:
        id: Hardcover book ID
        title: Book title
        authors: List of authors
        genres: Genre classifications
        moods: Mood/atmosphere tags
        tags: User-contributed tags
        content_warnings: Content warnings (the key value from Hardcover)
        rating: Average rating (0-5 scale)
        rating_count: Number of ratings
        description: Book description/blurb
    """

    id: int | str
    title: str
    authors: list[HardcoverAuthor] = Field(default_factory=list)
    genres: list[HardcoverGenre] = Field(default_factory=list)
    moods: list[HardcoverGenre] = Field(default_factory=list)
    tags: list[HardcoverGenre] = Field(default_factory=list)
    content_warnings: list[HardcoverContentWarning] = Field(default_factory=list)
    rating: float | None = None
    rating_count: int | None = None
    description: str | None = None

    @property
    def author_names(self) -> list[str]:
        """Get list of author names."""
        return [a.name for a in self.authors]

    @property
    def genre_names(self) -> list[str]:
        """Get list of genre names."""
        return [g.name for g in self.genres]

    @property
    def mood_names(self) -> list[str]:
        """Get list of mood names."""
        return [m.name for m in self.moods]

    @property
    def tag_names(self) -> list[str]:
        """Get list of tag names."""
        return [t.name for t in self.tags]

    @property
    def warning_names(self) -> list[str]:
        """Get list of content warning names."""
        return [w.name for w in self.content_warnings]

    @classmethod
    def from_search_hit(cls, doc: dict[str, Any]) -> HardcoverBook:
        """Create from Typesense search hit document.

        Search results have flattened arrays (author_names, genres as strings)
        rather than nested objects.

        Args:
            doc: The "document" from a Typesense hit

        Returns:
            HardcoverBook instance
        """
        return cls(
            id=doc.get("id", 0),
            title=doc.get("title", ""),
            authors=[HardcoverAuthor(name=name) for name in (doc.get("author_names") or [])],
            genres=[HardcoverGenre(name=genre) for genre in (doc.get("genres") or [])],
            moods=[HardcoverGenre(name=mood) for mood in (doc.get("moods") or [])],
            tags=[HardcoverGenre(name=tag) for tag in (doc.get("tags") or [])],
            content_warnings=[
                HardcoverContentWarning(name=warning)
                for warning in (doc.get("content_warnings") or [])
            ],
            rating=doc.get("rating"),
            rating_count=doc.get("ratings_count"),
            description=doc.get("description"),
        )


class HardcoverSearchResult(BaseModel):
    """Result of a Hardcover search with match metadata.

    Attributes:
        book: The matched book
        match_score: Fuzzy match score (0.0-1.0)
        search_query: Original search query used
        confidence_threshold: Threshold for confident match (default: 0.70)
    """

    book: HardcoverBook
    match_score: float
    search_query: str
    confidence_threshold: float = 0.70

    @property
    def is_confident_match(self) -> bool:
        """Check if match score exceeds confidence threshold."""
        return self.match_score >= self.confidence_threshold
