"""Tests for torrent utilities."""

from __future__ import annotations

from pathlib import Path

from shelfr.utils.torrent import (
    bdecode,
    bencode,
    extract_infohash,
    get_torrent_name,
)


class TestBdecode:
    """Tests for bdecode function."""

    def test_decode_integer(self):
        """Test decoding bencoded integers."""
        assert bdecode(b"i42e") == 42
        assert bdecode(b"i0e") == 0
        assert bdecode(b"i-5e") == -5

    def test_decode_bytes(self):
        """Test decoding bencoded strings."""
        assert bdecode(b"5:hello") == b"hello"
        assert bdecode(b"0:") == b""
        assert bdecode(b"4:test") == b"test"

    def test_decode_list(self):
        """Test decoding bencoded lists."""
        assert bdecode(b"le") == []
        assert bdecode(b"l5:helloi42ee") == [b"hello", 42]
        assert bdecode(b"li1ei2ei3ee") == [1, 2, 3]

    def test_decode_dict(self):
        """Test decoding bencoded dictionaries."""
        assert bdecode(b"de") == {}
        result = bdecode(b"d3:key5:valuee")
        assert result == {b"key": b"value"}

    def test_decode_nested(self):
        """Test decoding nested structures."""
        # Dict with nested list
        result = bdecode(b"d4:listli1ei2ee3:numi42ee")
        assert result[b"list"] == [1, 2]
        assert result[b"num"] == 42


class TestBencode:
    """Tests for bencode function."""

    def test_encode_integer(self):
        """Test encoding integers."""
        assert bencode(42) == b"i42e"
        assert bencode(0) == b"i0e"
        assert bencode(-5) == b"i-5e"

    def test_encode_bytes(self):
        """Test encoding bytes."""
        assert bencode(b"hello") == b"5:hello"
        assert bencode(b"") == b"0:"

    def test_encode_string(self):
        """Test encoding strings (converted to bytes)."""
        assert bencode("hello") == b"5:hello"

    def test_encode_list(self):
        """Test encoding lists."""
        assert bencode([]) == b"le"
        assert bencode([1, 2, 3]) == b"li1ei2ei3ee"

    def test_encode_dict(self):
        """Test encoding dictionaries."""
        assert bencode({}) == b"de"
        # Keys are sorted
        assert bencode({b"b": 2, b"a": 1}) == b"d1:ai1e1:bi2ee"

    def test_roundtrip(self):
        """Test decode(encode(x)) == x."""
        original = {b"info": {b"name": b"test", b"length": 1234}}
        encoded = bencode(original)
        decoded = bdecode(encoded)
        assert decoded == original


class TestExtractInfohash:
    """Tests for extract_infohash function."""

    def test_extract_infohash_valid_torrent(self, tmp_path: Path):
        """Test extracting infohash from a valid torrent file."""
        # Create a minimal valid torrent structure
        torrent_data = bencode(
            {
                b"info": {
                    b"name": b"test-file.txt",
                    b"length": 12345,
                    b"piece length": 16384,
                    b"pieces": b"01234567890123456789",  # 20 bytes (1 SHA1 hash)
                },
                b"announce": b"http://tracker.example.com/announce",
            }
        )

        torrent_file = tmp_path / "test.torrent"
        torrent_file.write_bytes(torrent_data)

        infohash = extract_infohash(torrent_file)
        assert infohash is not None
        assert len(infohash) == 40  # SHA1 hex string is 40 chars
        assert all(c in "0123456789abcdef" for c in infohash)

    def test_extract_infohash_same_content_same_hash(self, tmp_path: Path):
        """Test that same info dict produces same infohash."""
        info_dict = {
            b"name": b"my-audiobook",
            b"length": 54321,
            b"piece length": 16384,
            b"pieces": b"x" * 20,
        }

        torrent1 = tmp_path / "file1.torrent"
        torrent2 = tmp_path / "file2.torrent"

        # Different announce URLs, same info dict
        torrent1.write_bytes(bencode({b"info": info_dict, b"announce": b"http://tracker1.com"}))
        torrent2.write_bytes(bencode({b"info": info_dict, b"announce": b"http://tracker2.com"}))

        assert extract_infohash(torrent1) == extract_infohash(torrent2)

    def test_extract_infohash_different_content_different_hash(self, tmp_path: Path):
        """Test that different info dicts produce different infohashes."""
        torrent1 = tmp_path / "file1.torrent"
        torrent2 = tmp_path / "file2.torrent"

        torrent1.write_bytes(
            bencode(
                {
                    b"info": {
                        b"name": b"audiobook1",
                        b"length": 1000,
                        b"piece length": 16384,
                        b"pieces": b"x" * 20,
                    }
                }
            )
        )
        torrent2.write_bytes(
            bencode(
                {
                    b"info": {
                        b"name": b"audiobook2",
                        b"length": 2000,
                        b"piece length": 16384,
                        b"pieces": b"x" * 20,
                    }
                }
            )
        )

        assert extract_infohash(torrent1) != extract_infohash(torrent2)

    def test_extract_infohash_nonexistent_file(self, tmp_path: Path):
        """Test handling of nonexistent file."""
        result = extract_infohash(tmp_path / "nonexistent.torrent")
        assert result is None

    def test_extract_infohash_invalidbencode(self, tmp_path: Path):
        """Test handling of invalid bencode data."""
        torrent_file = tmp_path / "invalid.torrent"
        torrent_file.write_bytes(b"this is not bencode")

        result = extract_infohash(torrent_file)
        assert result is None

    def test_extract_infohash_missing_info_dict(self, tmp_path: Path):
        """Test handling of torrent missing info dict."""
        torrent_file = tmp_path / "missing_info.torrent"
        torrent_file.write_bytes(bencode({b"announce": b"http://tracker.com"}))

        result = extract_infohash(torrent_file)
        assert result is None


class TestGetTorrentName:
    """Tests for get_torrent_name function."""

    def test_get_name_valid_torrent(self, tmp_path: Path):
        """Test extracting name from a valid torrent file."""
        torrent_data = bencode(
            {
                b"info": {
                    b"name": b"Test Audiobook - Author",
                    b"length": 12345,
                    b"piece length": 16384,
                    b"pieces": b"x" * 20,
                }
            }
        )

        torrent_file = tmp_path / "test.torrent"
        torrent_file.write_bytes(torrent_data)

        name = get_torrent_name(torrent_file)
        assert name == "Test Audiobook - Author"

    def test_get_name_unicode(self, tmp_path: Path):
        """Test extracting unicode name."""
        torrent_data = bencode(
            {
                b"info": {
                    b"name": "日本語タイトル".encode(),
                    b"length": 12345,
                    b"piece length": 16384,
                    b"pieces": b"x" * 20,
                }
            }
        )

        torrent_file = tmp_path / "test.torrent"
        torrent_file.write_bytes(torrent_data)

        name = get_torrent_name(torrent_file)
        assert name == "日本語タイトル"

    def test_get_name_nonexistent_file(self, tmp_path: Path):
        """Test handling of nonexistent file."""
        result = get_torrent_name(tmp_path / "nonexistent.torrent")
        assert result is None

    def test_get_name_missing_info(self, tmp_path: Path):
        """Test handling of torrent missing info dict."""
        torrent_file = tmp_path / "missing_info.torrent"
        torrent_file.write_bytes(bencode({b"announce": b"http://tracker.com"}))

        result = get_torrent_name(torrent_file)
        assert result is None
