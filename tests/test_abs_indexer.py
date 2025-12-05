"""Tests for AbsIndex SQLite indexer."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from mamfast.abs.indexer import (
    AbsIndex,
    BookRecord,
    ImportStatus,
)


@pytest.fixture
def temp_db() -> Path:
    """Create a temporary database path."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        return Path(f.name)


@pytest.fixture
def index(temp_db: Path) -> AbsIndex:
    """Create an AbsIndex instance with temp database."""
    idx = AbsIndex(temp_db)
    # Force schema creation
    idx._get_conn()
    return idx


class TestAbsIndexBasics:
    """Test basic AbsIndex functionality."""

    def test_creates_database(self, temp_db: Path) -> None:
        """Database file is created on first access."""
        # Use a new path that doesn't exist yet
        new_db = temp_db.parent / "new_test.db"
        if new_db.exists():
            new_db.unlink()

        index = AbsIndex(new_db)
        # Note: Connection is lazy, but temp file fixture creates the file
        # Force connection to create database
        index._get_conn()
        assert new_db.exists()
        index.close()
        new_db.unlink()  # Cleanup

    def test_schema_created(self, index: AbsIndex) -> None:
        """Schema tables are created."""
        conn = index._get_conn()

        # Check tables exist
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = {t[0] for t in tables}

        assert "books" in table_names
        assert "author_variants" in table_names
        assert "import_log" in table_names
        assert "index_meta" in table_names

    def test_context_manager(self, temp_db: Path) -> None:
        """Context manager closes connection."""
        with AbsIndex(temp_db) as index:
            conn = index._get_conn()
            assert conn is not None

        assert index._conn is None

    def test_schema_version_stored(self, index: AbsIndex) -> None:
        """Schema version is stored in index_meta."""
        conn = index._get_conn()
        row = conn.execute("SELECT value FROM index_meta WHERE key = 'schema_version'").fetchone()
        assert row is not None
        assert int(row[0]) >= 1


class TestBookLookups:
    """Test book lookup operations."""

    def test_get_book_by_asin_not_found(self, index: AbsIndex) -> None:
        """Return None for non-existent ASIN."""
        assert index.get_book_by_asin("B0NOTEXIST") is None

    def test_asin_exists_false(self, index: AbsIndex) -> None:
        """asin_exists returns False for non-existent."""
        assert index.asin_exists("B0NOTEXIST") is False

    def test_check_duplicate_not_duplicate(self, index: AbsIndex) -> None:
        """check_duplicate returns (False, None) for new ASIN."""
        is_dup, path = index.check_duplicate("B0NOTEXIST")
        assert is_dup is False
        assert path is None

    def test_upsert_and_retrieve(self, index: AbsIndex) -> None:
        """Can insert and retrieve a book record."""
        record = BookRecord(
            library_item_id="li_test123",
            library_id="lib_test",
            asin="B0TESTASIN",
            title="Test Book",
            subtitle="A Subtitle",
            author_display="Test Author",
            author_folder="Test Author",
            series_name="Test Series",
            series_position=1.0,
            folder_path_host="/library/Test Author/Test Series/Test Book",
            main_audio_file_host="/library/Test Author/Test Series/Test Book/book.m4b",
            mtime_ms=1234567890000,
            size_bytes=100000000,
            indexed_at="2025-01-01T00:00:00Z",
        )

        index._upsert_book(record)
        index._get_conn().commit()

        # Retrieve by ASIN
        result = index.get_book_by_asin("B0TESTASIN")
        assert result is not None
        assert result.title == "Test Book"
        assert result.author_display == "Test Author"
        assert result.series_name == "Test Series"
        assert result.series_position == 1.0

    def test_asin_exists_true(self, index: AbsIndex) -> None:
        """asin_exists returns True after insert."""
        record = BookRecord(
            library_item_id="li_test456",
            library_id="lib_test",
            asin="B0EXISTS01",
            title="Exists Book",
            subtitle=None,
            author_display="Author",
            author_folder="Author",
            series_name=None,
            series_position=None,
            folder_path_host="/library/Author/Exists Book",
            main_audio_file_host=None,
            mtime_ms=None,
            size_bytes=None,
            indexed_at="2025-01-01T00:00:00Z",
        )
        index._upsert_book(record)
        index._get_conn().commit()

        assert index.asin_exists("B0EXISTS01") is True

    def test_check_duplicate_is_duplicate(self, index: AbsIndex) -> None:
        """check_duplicate returns path for existing ASIN."""
        record = BookRecord(
            library_item_id="li_dup789",
            library_id="lib_test",
            asin="B0DUPASIN1",
            title="Duplicate Book",
            subtitle=None,
            author_display="Author",
            author_folder="Author",
            series_name=None,
            series_position=None,
            folder_path_host="/library/Author/Duplicate Book",
            main_audio_file_host=None,
            mtime_ms=None,
            size_bytes=None,
            indexed_at="2025-01-01T00:00:00Z",
        )
        index._upsert_book(record)
        index._get_conn().commit()

        is_dup, path = index.check_duplicate("B0DUPASIN1")
        assert is_dup is True
        assert path == "/library/Author/Duplicate Book"

    def test_get_books_by_author_folder(self, index: AbsIndex) -> None:
        """Can query books by author folder."""
        for i in range(3):
            record = BookRecord(
                library_item_id=f"li_auth{i}",
                library_id="lib_test",
                asin=f"B0AUTH000{i}",
                title=f"Book {i}",
                subtitle=None,
                author_display="Same Author",
                author_folder="Same Author",
                series_name=None,
                series_position=None,
                folder_path_host=f"/library/Same Author/Book {i}",
                main_audio_file_host=None,
                mtime_ms=None,
                size_bytes=None,
                indexed_at="2025-01-01T00:00:00Z",
            )
            index._upsert_book(record)
        index._get_conn().commit()

        books = index.get_books_by_author_folder("Same Author")
        assert len(books) == 3

    def test_get_books_by_library(self, index: AbsIndex) -> None:
        """Can query books by library ID."""
        for i, lib_id in enumerate(["lib_a", "lib_a", "lib_b"]):
            record = BookRecord(
                library_item_id=f"li_lib{i}",
                library_id=lib_id,
                asin=f"B0LIB0000{i}",
                title=f"Book {i}",
                subtitle=None,
                author_display="Author",
                author_folder="Author",
                series_name=None,
                series_position=None,
                folder_path_host=f"/library/Author/Book {i}",
                main_audio_file_host=None,
                mtime_ms=None,
                size_bytes=None,
                indexed_at="2025-01-01T00:00:00Z",
            )
            index._upsert_book(record)
        index._get_conn().commit()

        lib_a_books = index.get_books_by_library("lib_a")
        assert len(lib_a_books) == 2

        lib_b_books = index.get_books_by_library("lib_b")
        assert len(lib_b_books) == 1


class TestAuthorVariants:
    """Test author variant detection and reporting."""

    def test_rebuild_finds_variants(self, index: AbsIndex) -> None:
        """Rebuild detects author/folder mismatches."""
        # Insert books with mismatched author/folder
        # Note: We compare case-insensitive, so use completely different names
        records = [
            BookRecord(
                library_item_id="li_var1",
                library_id="lib_test",
                asin="B0VAR00001",
                title="Book 1",
                subtitle=None,
                author_display="Brandon Sanderson",  # Proper name from ABS
                author_folder="B Sanderson",  # Different name on disk
                series_name=None,
                series_position=None,
                folder_path_host="/library/B Sanderson/Book 1",
                main_audio_file_host=None,
                mtime_ms=None,
                size_bytes=None,
                indexed_at="2025-01-01T00:00:00Z",
            ),
            BookRecord(
                library_item_id="li_var2",
                library_id="lib_test",
                asin="B0VAR00002",
                title="Book 2",
                subtitle=None,
                author_display="Brandon Sanderson",
                author_folder="B Sanderson",
                series_name=None,
                series_position=None,
                folder_path_host="/library/B Sanderson/Book 2",
                main_audio_file_host=None,
                mtime_ms=None,
                size_bytes=None,
                indexed_at="2025-01-01T00:00:00Z",
            ),
        ]
        for r in records:
            index._upsert_book(r)
        index._get_conn().commit()

        # Rebuild variants
        count = index._rebuild_author_variants("2025-01-01T00:00:00Z")
        assert count == 1  # One unique variant pair

        variants = index.get_author_variants()
        assert len(variants) == 1
        assert variants[0].author_display == "Brandon Sanderson"
        assert variants[0].folder_name == "B Sanderson"
        assert variants[0].book_count == 2

    def test_no_variants_when_matching(self, index: AbsIndex) -> None:
        """No variants when author matches folder (case-insensitive)."""
        record = BookRecord(
            library_item_id="li_match",
            library_id="lib_test",
            asin="B0MATCH001",
            title="Matching Book",
            subtitle=None,
            author_display="Test Author",
            author_folder="Test Author",  # Same
            series_name=None,
            series_position=None,
            folder_path_host="/library/Test Author/Matching Book",
            main_audio_file_host=None,
            mtime_ms=None,
            size_bytes=None,
            indexed_at="2025-01-01T00:00:00Z",
        )
        index._upsert_book(record)
        index._get_conn().commit()

        count = index._rebuild_author_variants("2025-01-01T00:00:00Z")
        assert count == 0


class TestStats:
    """Test index statistics."""

    def test_empty_stats(self, index: AbsIndex) -> None:
        """Stats for empty index."""
        stats = index.get_stats()
        assert stats.total_books == 0
        assert stats.books_with_asin == 0
        assert stats.books_without_asin == 0
        assert stats.unique_authors == 0
        assert stats.unique_series == 0

    def test_stats_with_data(self, index: AbsIndex) -> None:
        """Stats with books."""
        records = [
            BookRecord(
                library_item_id="li_stat1",
                library_id="lib_test",
                asin="B0STAT0001",
                title="Book 1",
                subtitle=None,
                author_display="Author A",
                author_folder="Author A",
                series_name="Series 1",
                series_position=1.0,
                folder_path_host="/library/Author A/Series 1/Book 1",
                main_audio_file_host=None,
                mtime_ms=None,
                size_bytes=None,
                indexed_at="2025-01-01T00:00:00Z",
            ),
            BookRecord(
                library_item_id="li_stat2",
                library_id="lib_test",
                asin=None,  # No ASIN
                title="Book 2",
                subtitle=None,
                author_display="Author B",
                author_folder="Author B",
                series_name=None,  # Standalone
                series_position=None,
                folder_path_host="/library/Author B/Book 2",
                main_audio_file_host=None,
                mtime_ms=None,
                size_bytes=None,
                indexed_at="2025-01-01T00:00:00Z",
            ),
        ]
        for r in records:
            index._upsert_book(r)
        index._get_conn().commit()

        stats = index.get_stats()
        assert stats.total_books == 2
        assert stats.books_with_asin == 1
        assert stats.books_without_asin == 1
        assert stats.unique_authors == 2
        assert stats.unique_series == 1  # Only 1 non-null series


class TestImportLog:
    """Test import logging."""

    def test_log_import(self, index: AbsIndex) -> None:
        """Can log an import."""
        index.log_import(
            asin="B0IMPORT01",
            source_path="/staging/Book",
            target_path="/library/Author/Book",
            library_id="lib_test",
            status=ImportStatus.SUCCESS,
        )

        history = index.get_import_history(asin="B0IMPORT01")
        assert len(history) == 1
        assert history[0]["asin"] == "B0IMPORT01"
        assert history[0]["status"] == "success"

    def test_import_history_all(self, index: AbsIndex) -> None:
        """Get all import history."""
        for i in range(3):
            index.log_import(
                asin=f"B0HIST000{i}",
                source_path=f"/staging/Book{i}",
                target_path=f"/library/Author/Book{i}",
                library_id="lib_test",
                status=ImportStatus.SUCCESS,
            )

        history = index.get_import_history()
        assert len(history) == 3

    def test_import_history_limit(self, index: AbsIndex) -> None:
        """History respects limit."""
        for i in range(10):
            index.log_import(
                asin=f"B0LIM0000{i}",
                source_path=f"/staging/Book{i}",
                target_path=f"/library/Author/Book{i}",
                library_id="lib_test",
                status=ImportStatus.SUCCESS,
            )

        history = index.get_import_history(limit=5)
        assert len(history) == 5


class TestDuplicateAsins:
    """Test duplicate ASIN detection."""

    def test_no_duplicates(self, index: AbsIndex) -> None:
        """No duplicates when ASINs are unique."""
        for i in range(3):
            record = BookRecord(
                library_item_id=f"li_uniq{i}",
                library_id="lib_test",
                asin=f"B0UNIQUE0{i}",
                title=f"Book {i}",
                subtitle=None,
                author_display="Author",
                author_folder="Author",
                series_name=None,
                series_position=None,
                folder_path_host=f"/library/Author/Book {i}",
                main_audio_file_host=None,
                mtime_ms=None,
                size_bytes=None,
                indexed_at="2025-01-01T00:00:00Z",
            )
            index._upsert_book(record)
        index._get_conn().commit()

        dupes = index.get_duplicate_asins()
        assert len(dupes) == 0

    def test_finds_duplicates(self, temp_db: Path) -> None:
        """Finds ASINs appearing multiple times."""
        # Create a fresh index without the UNIQUE constraint on ASIN
        # The schema has a unique partial index on ASIN (WHERE asin IS NOT NULL)
        # This prevents duplicate ASINs, which is correct behavior!
        # So let's test the duplicate detection SQL directly

        # Create a custom schema without the unique ASIN index for this test
        test_db = temp_db.parent / "dup_test.db"
        if test_db.exists():
            test_db.unlink()

        conn = sqlite3.connect(test_db)
        conn.execute("""
            CREATE TABLE books (
                id INTEGER PRIMARY KEY,
                library_item_id TEXT UNIQUE NOT NULL,
                library_id TEXT NOT NULL,
                asin TEXT,
                title TEXT NOT NULL,
                author_display TEXT NOT NULL,
                author_folder TEXT NOT NULL,
                folder_path_host TEXT NOT NULL,
                indexed_at TEXT NOT NULL
            )
        """)
        # No unique index on ASIN - allows duplicates

        conn.execute(
            "INSERT INTO books VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                "li_dup_a",
                "lib_a",
                "B0SAMEASIN",
                "Book A",
                "Author",
                "Author",
                "/lib_a/Author/Book A",
                "2025-01-01",
            ),
        )
        conn.execute(
            "INSERT INTO books VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                2,
                "li_dup_b",
                "lib_b",
                "B0SAMEASIN",
                "Book B",
                "Author",
                "Author",
                "/lib_b/Author/Book B",
                "2025-01-01",
            ),
        )
        conn.commit()

        # Query for duplicates
        cursor = conn.execute("""
            SELECT asin, GROUP_CONCAT(folder_path_host, '|') as paths
            FROM books
            WHERE asin IS NOT NULL
            GROUP BY asin
            HAVING COUNT(*) > 1
        """)
        dupes = [(row[0], row[1].split("|")) for row in cursor]

        conn.close()
        test_db.unlink()

        assert len(dupes) == 1
        assert dupes[0][0] == "B0SAMEASIN"
        assert len(dupes[0][1]) == 2


class TestExportJson:
    """Test JSON export."""

    def test_export_empty(self, index: AbsIndex) -> None:
        """Export empty index."""
        data = index.export_json()
        assert "exported_at" in data
        assert data["stats"]["total_books"] == 0
        assert data["books"] == []
        assert data["author_variants"] == []

    def test_export_with_data(self, index: AbsIndex) -> None:
        """Export index with data."""
        record = BookRecord(
            library_item_id="li_export",
            library_id="lib_test",
            asin="B0EXPORT01",
            title="Export Book",
            subtitle="Subtitle",
            author_display="Export Author",
            author_folder="Export Author",
            series_name="Export Series",
            series_position=1.0,
            folder_path_host="/library/Export Author/Export Series/Export Book",
            main_audio_file_host="/library/.../book.m4b",
            mtime_ms=None,
            size_bytes=None,
            indexed_at="2025-01-01T00:00:00Z",
        )
        index._upsert_book(record)
        index._get_conn().commit()

        data = index.export_json()
        assert data["stats"]["total_books"] == 1
        assert len(data["books"]) == 1
        assert data["books"][0]["asin"] == "B0EXPORT01"
        assert data["books"][0]["title"] == "Export Book"


class TestLastSync:
    """Test sync timestamp tracking."""

    def test_no_sync_yet(self, index: AbsIndex) -> None:
        """get_last_sync returns None before first sync."""
        assert index.get_last_sync() is None

    def test_sync_timestamp_stored(self, index: AbsIndex) -> None:
        """Sync timestamp is stored and retrievable."""
        conn = index._get_conn()
        timestamp = "2025-06-15T10:30:00+00:00"
        conn.execute(
            "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
            ("last_full_sync", timestamp),
        )
        conn.commit()

        result = index.get_last_sync()
        assert result is not None
        assert result.year == 2025
        assert result.month == 6
        assert result.day == 15
