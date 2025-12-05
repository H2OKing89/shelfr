"""SQLite index for Audiobookshelf library items.

Provides fast ASIN lookups for duplicate detection and author variant reporting.
Populated from ABS API via sync_from_abs().
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mamfast.abs.client import AbsClient, AbsLibraryItem
    from mamfast.abs.paths import PathMapper

logger = logging.getLogger(__name__)

# Current schema version - increment when schema changes
SCHEMA_VERSION = 1

# SQL statements for schema creation
SCHEMA_SQL = """
-- Books: core table populated from ABS API
CREATE TABLE IF NOT EXISTS books (
    id                    INTEGER PRIMARY KEY,
    library_item_id       TEXT UNIQUE NOT NULL,   -- ABS "li_xxx" ID
    library_id            TEXT NOT NULL,          -- ABS "lib_xxx" ID
    asin                  TEXT,                   -- nullable for legacy
    title                 TEXT NOT NULL,
    subtitle              TEXT,
    author_display        TEXT NOT NULL,          -- "Brandon Sanderson" from ABS
    author_folder         TEXT NOT NULL,          -- Folder name on disk
    series_name           TEXT,
    series_position       REAL,                   -- Can be 1.5 for novellas
    folder_path_host      TEXT NOT NULL,          -- Host path after mapping
    main_audio_file_host  TEXT,                   -- Primary .m4b path
    mtime_ms              INTEGER,                -- For change detection
    size_bytes            INTEGER,
    indexed_at            TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_books_asin ON books(asin) WHERE asin IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_books_author_folder ON books(author_folder);
CREATE INDEX IF NOT EXISTS idx_books_library ON books(library_id);
CREATE INDEX IF NOT EXISTS idx_books_series ON books(series_name);

-- Author variants: for reporting, not enforcement
CREATE TABLE IF NOT EXISTS author_variants (
    id              INTEGER PRIMARY KEY,
    author_display  TEXT NOT NULL,        -- What ABS says: "Brandon Sanderson"
    folder_name     TEXT NOT NULL,        -- What's on disk: "brandon sanderson"
    book_count      INTEGER NOT NULL,
    first_seen      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_variants_display ON author_variants(author_display);
CREATE INDEX IF NOT EXISTS idx_variants_folder ON author_variants(folder_name);

-- Import log: track what MAMFast imported
CREATE TABLE IF NOT EXISTS import_log (
    id              INTEGER PRIMARY KEY,
    asin            TEXT NOT NULL,
    source_path     TEXT NOT NULL,        -- Where it came from (staging)
    target_path     TEXT NOT NULL,        -- Where it went (library)
    library_id      TEXT NOT NULL,
    imported_at     TEXT NOT NULL,
    status          TEXT NOT NULL         -- "success", "skipped", "failed", "duplicate"
);

CREATE INDEX IF NOT EXISTS idx_import_asin ON import_log(asin);

-- Index metadata: track sync state
CREATE TABLE IF NOT EXISTS index_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class ImportStatus(str, Enum):
    """Status of an import operation."""

    SUCCESS = "success"  # Import completed
    SKIPPED = "skipped"  # User chose to skip
    FAILED = "failed"  # Error during move
    DUPLICATE = "duplicate"  # Already exists by ASIN


@dataclass
class BookRecord:
    """A book record from the index."""

    library_item_id: str
    library_id: str
    asin: str | None
    title: str
    subtitle: str | None
    author_display: str
    author_folder: str
    series_name: str | None
    series_position: float | None
    folder_path_host: str
    main_audio_file_host: str | None
    mtime_ms: int | None
    size_bytes: int | None
    indexed_at: str


@dataclass
class AuthorVariant:
    """Detected author name variant (for reporting)."""

    author_display: str  # What ABS metadata says
    folder_name: str  # What's on disk
    book_count: int
    first_seen: str


@dataclass
class SyncResult:
    """Result of sync_from_abs() operation."""

    books_indexed: int
    with_asin: int
    without_asin: int
    author_variants_found: int
    libraries_synced: int
    errors: list[str]


@dataclass
class IndexStats:
    """Statistics about the index."""

    total_books: int
    books_with_asin: int
    books_without_asin: int
    unique_authors: int
    unique_series: int
    author_variants: int
    last_sync: str | None
    schema_version: int


class AbsIndex:
    """SQLite index for ABS library items.

    Provides fast ASIN lookups and author variant reporting.

    Note:
        This class is NOT thread-safe. Each thread should use its own
        AbsIndex instance. The underlying SQLite connection is created
        lazily and shared across all operations on a single instance.
    """

    def __init__(self, db_path: Path) -> None:
        """Initialize index with database path.

        Args:
            db_path: Path to SQLite database file (created if not exists)
        """
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._init_schema()
        return self._conn

    def _init_schema(self) -> None:
        """Initialize database schema if needed."""
        conn = self._conn
        if conn is None:
            return

        # Check if schema needs to be created
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='books'")
        if cursor.fetchone() is None:
            conn.executescript(SCHEMA_SQL)
            conn.execute(
                "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            conn.commit()
            logger.info("Created index schema version %d", SCHEMA_VERSION)

    def close(self) -> None:
        """Close database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> AbsIndex:
        """Context manager entry."""
        return self

    def __exit__(self, *args: object) -> None:
        """Context manager exit."""
        self.close()

    # === Lookup operations ===

    def get_book_by_asin(self, asin: str) -> BookRecord | None:
        """Get book record by ASIN (O(1) via index).

        Args:
            asin: ASIN to lookup

        Returns:
            BookRecord if found, None otherwise
        """
        conn = self._get_conn()
        cursor = conn.execute(
            """
            SELECT library_item_id, library_id, asin, title, subtitle,
                   author_display, author_folder, series_name, series_position,
                   folder_path_host, main_audio_file_host, mtime_ms, size_bytes,
                   indexed_at
            FROM books WHERE asin = ?
            """,
            (asin,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return BookRecord(
            library_item_id=row["library_item_id"],
            library_id=row["library_id"],
            asin=row["asin"],
            title=row["title"],
            subtitle=row["subtitle"],
            author_display=row["author_display"],
            author_folder=row["author_folder"],
            series_name=row["series_name"],
            series_position=row["series_position"],
            folder_path_host=row["folder_path_host"],
            main_audio_file_host=row["main_audio_file_host"],
            mtime_ms=row["mtime_ms"],
            size_bytes=row["size_bytes"],
            indexed_at=row["indexed_at"],
        )

    def asin_exists(self, asin: str) -> bool:
        """Check if ASIN exists in index.

        Args:
            asin: ASIN to check

        Returns:
            True if exists, False otherwise
        """
        conn = self._get_conn()
        cursor = conn.execute("SELECT 1 FROM books WHERE asin = ? LIMIT 1", (asin,))
        return cursor.fetchone() is not None

    def check_duplicate(self, asin: str) -> tuple[bool, str | None]:
        """Check if ASIN exists and return existing path.

        Args:
            asin: ASIN to check

        Returns:
            (is_duplicate, existing_path_or_none)
        """
        book = self.get_book_by_asin(asin)
        if book:
            return True, book.folder_path_host
        return False, None

    def get_books_by_author_folder(self, folder_name: str) -> list[BookRecord]:
        """Get all books in an author folder.

        Args:
            folder_name: Author folder name on disk

        Returns:
            List of BookRecord for books in that folder
        """
        conn = self._get_conn()
        cursor = conn.execute(
            """
            SELECT library_item_id, library_id, asin, title, subtitle,
                   author_display, author_folder, series_name, series_position,
                   folder_path_host, main_audio_file_host, mtime_ms, size_bytes,
                   indexed_at
            FROM books WHERE author_folder = ?
            """,
            (folder_name,),
        )
        return [
            BookRecord(
                library_item_id=row["library_item_id"],
                library_id=row["library_id"],
                asin=row["asin"],
                title=row["title"],
                subtitle=row["subtitle"],
                author_display=row["author_display"],
                author_folder=row["author_folder"],
                series_name=row["series_name"],
                series_position=row["series_position"],
                folder_path_host=row["folder_path_host"],
                main_audio_file_host=row["main_audio_file_host"],
                mtime_ms=row["mtime_ms"],
                size_bytes=row["size_bytes"],
                indexed_at=row["indexed_at"],
            )
            for row in cursor
        ]

    def get_books_by_library(self, library_id: str) -> list[BookRecord]:
        """Get all books in a library.

        Args:
            library_id: ABS library ID

        Returns:
            List of BookRecord for books in that library
        """
        conn = self._get_conn()
        cursor = conn.execute(
            """
            SELECT library_item_id, library_id, asin, title, subtitle,
                   author_display, author_folder, series_name, series_position,
                   folder_path_host, main_audio_file_host, mtime_ms, size_bytes,
                   indexed_at
            FROM books WHERE library_id = ?
            """,
            (library_id,),
        )
        return [
            BookRecord(
                library_item_id=row["library_item_id"],
                library_id=row["library_id"],
                asin=row["asin"],
                title=row["title"],
                subtitle=row["subtitle"],
                author_display=row["author_display"],
                author_folder=row["author_folder"],
                series_name=row["series_name"],
                series_position=row["series_position"],
                folder_path_host=row["folder_path_host"],
                main_audio_file_host=row["main_audio_file_host"],
                mtime_ms=row["mtime_ms"],
                size_bytes=row["size_bytes"],
                indexed_at=row["indexed_at"],
            )
            for row in cursor
        ]

    # === Reporting ===

    def get_author_variants(self) -> list[AuthorVariant]:
        """Get all detected author variants.

        Returns:
            List of AuthorVariant records
        """
        conn = self._get_conn()
        cursor = conn.execute(
            """
            SELECT author_display, folder_name, book_count, first_seen
            FROM author_variants
            ORDER BY author_display
            """
        )
        return [
            AuthorVariant(
                author_display=row["author_display"],
                folder_name=row["folder_name"],
                book_count=row["book_count"],
                first_seen=row["first_seen"],
            )
            for row in cursor
        ]

    def get_duplicate_asins(self) -> list[tuple[str, list[str]]]:
        """Find ASINs that appear in multiple locations.

        Returns:
            List of (asin, [path1, path2, ...]) tuples
        """
        conn = self._get_conn()
        # Find ASINs with multiple entries
        cursor = conn.execute(
            """
            SELECT asin, GROUP_CONCAT(folder_path_host, '|') as paths
            FROM books
            WHERE asin IS NOT NULL
            GROUP BY asin
            HAVING COUNT(*) > 1
            """
        )
        return [(row["asin"], row["paths"].split("|")) for row in cursor]

    def get_stats(self) -> IndexStats:
        """Get index statistics.

        Returns:
            IndexStats with counts and metadata
        """
        conn = self._get_conn()

        total = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        with_asin = conn.execute("SELECT COUNT(*) FROM books WHERE asin IS NOT NULL").fetchone()[0]
        authors = conn.execute("SELECT COUNT(DISTINCT author_display) FROM books").fetchone()[0]
        series = conn.execute(
            "SELECT COUNT(DISTINCT series_name) FROM books WHERE series_name IS NOT NULL"
        ).fetchone()[0]
        variants = conn.execute("SELECT COUNT(*) FROM author_variants").fetchone()[0]

        last_sync_row = conn.execute(
            "SELECT value FROM index_meta WHERE key = 'last_full_sync'"
        ).fetchone()
        last_sync = last_sync_row[0] if last_sync_row else None

        schema_row = conn.execute(
            "SELECT value FROM index_meta WHERE key = 'schema_version'"
        ).fetchone()
        schema = int(schema_row[0]) if schema_row else 0

        return IndexStats(
            total_books=total,
            books_with_asin=with_asin,
            books_without_asin=total - with_asin,
            unique_authors=authors,
            unique_series=series,
            author_variants=variants,
            last_sync=last_sync,
            schema_version=schema,
        )

    def get_last_sync(self) -> datetime | None:
        """Get timestamp of last sync.

        Returns:
            datetime of last sync, or None if never synced
        """
        conn = self._get_conn()
        row = conn.execute("SELECT value FROM index_meta WHERE key = 'last_full_sync'").fetchone()
        if row is None:
            return None
        try:
            return datetime.fromisoformat(row[0])
        except (ValueError, TypeError):
            return None

    # === Sync from ABS API ===

    def sync_from_abs(
        self,
        client: AbsClient,
        path_mapper: PathMapper,
        library_ids: list[str] | None = None,
        *,
        full_rebuild: bool = False,
    ) -> SyncResult:
        """Sync index from ABS API.

        Fetches all items from specified libraries and updates the index.

        Args:
            client: AbsClient instance
            path_mapper: PathMapper for container → host path translation
            library_ids: Specific library IDs to sync, or None for all
            full_rebuild: If True, clear existing data first

        Returns:
            SyncResult with statistics
        """
        conn = self._get_conn()
        errors: list[str] = []
        now = datetime.now(UTC).isoformat()

        if full_rebuild:
            conn.execute("DELETE FROM books")
            conn.execute("DELETE FROM author_variants")
            logger.info("Cleared existing index for full rebuild")

        # Get libraries to sync
        try:
            libraries = client.get_libraries()
        except Exception as e:
            logger.error("Failed to get libraries: %s", e)
            return SyncResult(
                books_indexed=0,
                with_asin=0,
                without_asin=0,
                author_variants_found=0,
                libraries_synced=0,
                errors=[f"Failed to get libraries: {e}"],
            )

        if library_ids:
            libraries = [lib for lib in libraries if lib.id in library_ids]

        books_indexed = 0
        with_asin = 0
        without_asin = 0
        libraries_synced = 0

        for library in libraries:
            try:
                items = client.get_all_library_items(library.id)
                libraries_synced += 1
                logger.info("Fetched %d items from library '%s'", len(items), library.name)
            except Exception as e:
                msg = f"Failed to fetch library '{library.name}': {e}"
                logger.error(msg)
                errors.append(msg)
                continue

            for item in items:
                try:
                    record = self._process_abs_item(item, library.id, path_mapper, now)
                    if record:
                        self._upsert_book(record)
                        books_indexed += 1
                        if record.asin:
                            with_asin += 1
                        else:
                            without_asin += 1
                except Exception as e:
                    item_id = getattr(item, "id", "unknown")
                    msg = f"Failed to process item {item_id}: {e}"
                    logger.warning(msg)
                    errors.append(msg)

        # Rebuild author variants table
        variants_found = self._rebuild_author_variants(now)

        # Update sync timestamp
        conn.execute(
            "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
            ("last_full_sync", now),
        )
        conn.commit()

        logger.info(
            "Sync complete: %d books (%d with ASIN), %d variants",
            books_indexed,
            with_asin,
            variants_found,
        )

        return SyncResult(
            books_indexed=books_indexed,
            with_asin=with_asin,
            without_asin=without_asin,
            author_variants_found=variants_found,
            libraries_synced=libraries_synced,
            errors=errors,
        )

    def _process_abs_item(
        self,
        item: AbsLibraryItem,
        library_id: str,
        path_mapper: PathMapper,
        indexed_at: str,
    ) -> BookRecord | None:
        """Process a single ABS library item into a BookRecord.

        Args:
            item: AbsLibraryItem dataclass from client
            library_id: Library ID this item belongs to
            path_mapper: For path translation
            indexed_at: Timestamp string

        Returns:
            BookRecord or None if item cannot be processed
        """
        # Get basic item info
        if not item.id or not item.title:
            return None

        title = item.title
        subtitle = item.subtitle

        # Get author - AbsLibraryItem has author_name directly
        author_display = item.author_name or "Unknown"

        # Get series info - AbsLibraryItem has series_name directly
        series_name = item.series_name
        series_position = None  # AbsLibraryItem doesn't expose sequence

        # Get ASIN - directly from AbsLibraryItem
        asin = item.asin

        # Get paths
        container_path = item.path
        host_path = path_mapper.to_host(container_path)
        host_path_str = str(host_path)

        # Extract author folder from path
        # Path structure: /root/Author/[Series/]Book
        # We want the Author folder name
        # Use Path.parts for robust parsing (handles trailing slashes, redundant separators)
        path_obj = Path(host_path_str)
        path_parts = path_obj.parts  # e.g., ('/', 'mnt', 'data', 'Author', 'Series', 'Book')
        # Find author folder - it's typically 2nd level under library root
        # But we'll use a simpler approach: get parent of series or book folder
        # Validate path structure before extracting author folder
        author_folder = "Unknown"
        if series_name:
            # With series: /root/Author/Series/Book → need at least 4 parts (/, root, Author, ...)
            if len(path_parts) >= 4:
                author_folder = path_parts[-3]
            else:
                logger.warning(
                    "Cannot reliably extract author folder for path '%s' "
                    "(series_name present, path_parts=%s). Setting author_folder='Unknown'.",
                    host_path_str,
                    path_parts,
                )
        else:
            # Standalone: /root/Author/Book → need at least 3 parts (/, root, Author, Book)
            if len(path_parts) >= 3:
                author_folder = path_parts[-2]
            else:
                logger.warning(
                    "Cannot reliably extract author folder for path '%s' "
                    "(no series_name, path_parts=%s). Setting author_folder='Unknown'.",
                    host_path_str,
                    path_parts,
                )

        # Size and duration from AbsLibraryItem
        size_bytes = item.size if item.size > 0 else None
        mtime_ms = item.updated_at if item.updated_at > 0 else None

        return BookRecord(
            library_item_id=item.id,
            library_id=library_id,
            asin=asin,
            title=title,
            subtitle=subtitle,
            author_display=author_display,
            author_folder=author_folder,
            series_name=series_name,
            series_position=series_position,
            folder_path_host=host_path_str,
            main_audio_file_host=None,  # Not available from AbsLibraryItem
            mtime_ms=mtime_ms,
            size_bytes=size_bytes,
            indexed_at=indexed_at,
        )

    def _upsert_book(self, record: BookRecord) -> None:
        """Insert or update a book record.

        Args:
            record: BookRecord to upsert
        """
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO books (
                library_item_id, library_id, asin, title, subtitle,
                author_display, author_folder, series_name, series_position,
                folder_path_host, main_audio_file_host, mtime_ms, size_bytes,
                indexed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(library_item_id) DO UPDATE SET
                asin = excluded.asin,
                title = excluded.title,
                subtitle = excluded.subtitle,
                author_display = excluded.author_display,
                author_folder = excluded.author_folder,
                series_name = excluded.series_name,
                series_position = excluded.series_position,
                folder_path_host = excluded.folder_path_host,
                main_audio_file_host = excluded.main_audio_file_host,
                mtime_ms = excluded.mtime_ms,
                size_bytes = excluded.size_bytes,
                indexed_at = excluded.indexed_at
            """,
            (
                record.library_item_id,
                record.library_id,
                record.asin,
                record.title,
                record.subtitle,
                record.author_display,
                record.author_folder,
                record.series_name,
                record.series_position,
                record.folder_path_host,
                record.main_audio_file_host,
                record.mtime_ms,
                record.size_bytes,
                record.indexed_at,
            ),
        )

    def _rebuild_author_variants(self, timestamp: str) -> int:
        """Rebuild author_variants table from books table.

        Finds cases where author_display != author_folder (case-insensitive).

        Args:
            timestamp: Timestamp for first_seen

        Returns:
            Number of variants found
        """
        conn = self._get_conn()

        # Clear existing variants
        conn.execute("DELETE FROM author_variants")

        # Find author/folder mismatches
        # We consider it a variant if the folder name doesn't match author display
        # (case-insensitive comparison)
        conn.execute(
            """
            INSERT INTO author_variants (author_display, folder_name, book_count, first_seen)
            SELECT
                author_display,
                author_folder,
                COUNT(*) as book_count,
                ? as first_seen
            FROM books
            WHERE LOWER(author_display) != LOWER(author_folder)
            GROUP BY author_display, author_folder
            """,
            (timestamp,),
        )

        result = conn.execute("SELECT COUNT(*) FROM author_variants").fetchone()
        count: int = result[0] if result else 0
        return count

    # === Import logging ===

    def log_import(
        self,
        asin: str,
        source_path: str,
        target_path: str,
        library_id: str,
        status: ImportStatus,
    ) -> None:
        """Log an import operation.

        Args:
            asin: ASIN of the book
            source_path: Where it came from (staging)
            target_path: Where it went (library)
            library_id: Target library ID
            status: Import status
        """
        conn = self._get_conn()
        now = datetime.now(UTC).isoformat()
        conn.execute(
            """
            INSERT INTO import_log (asin, source_path, target_path, library_id, imported_at, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (asin, source_path, target_path, library_id, now, status.value),
        )
        conn.commit()

    def get_import_history(self, asin: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Get import history.

        Args:
            asin: Filter by ASIN, or None for all
            limit: Max records to return

        Returns:
            List of import log dicts
        """
        conn = self._get_conn()
        if asin:
            cursor = conn.execute(
                """
                SELECT asin, source_path, target_path, library_id, imported_at, status
                FROM import_log
                WHERE asin = ?
                ORDER BY imported_at DESC
                LIMIT ?
                """,
                (asin, limit),
            )
        else:
            cursor = conn.execute(
                """
                SELECT asin, source_path, target_path, library_id, imported_at, status
                FROM import_log
                ORDER BY imported_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        return [dict(row) for row in cursor]

    # === Export ===

    def export_json(self) -> dict[str, Any]:
        """Export full index as JSON.

        Returns:
            Dict with books, variants, and metadata
        """
        conn = self._get_conn()

        # Get all books
        cursor = conn.execute(
            """
            SELECT library_item_id, library_id, asin, title, subtitle,
                   author_display, author_folder, series_name, series_position,
                   folder_path_host, main_audio_file_host, indexed_at
            FROM books
            ORDER BY author_display, series_name, series_position
            """
        )
        books = [dict(row) for row in cursor]

        # Get variants
        variants = [
            {
                "author_display": v.author_display,
                "folder_name": v.folder_name,
                "book_count": v.book_count,
            }
            for v in self.get_author_variants()
        ]

        # Get stats
        stats = self.get_stats()

        return {
            "exported_at": datetime.now(UTC).isoformat(),
            "stats": {
                "total_books": stats.total_books,
                "books_with_asin": stats.books_with_asin,
                "books_without_asin": stats.books_without_asin,
                "unique_authors": stats.unique_authors,
                "unique_series": stats.unique_series,
                "author_variants": stats.author_variants,
            },
            "books": books,
            "author_variants": variants,
        }
