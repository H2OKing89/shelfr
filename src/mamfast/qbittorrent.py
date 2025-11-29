"""
qBittorrent API wrapper for uploading torrents.

Uses the qbittorrent-api package.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import qbittorrentapi

from mamfast.config import get_settings

logger = logging.getLogger(__name__)


def get_client() -> qbittorrentapi.Client:
    """
    Create an authenticated qBittorrent API client.

    Returns:
        Connected and authenticated client.

    Raises:
        qbittorrentapi.LoginFailed: If authentication fails.
        qbittorrentapi.APIConnectionError: If connection fails.
    """
    settings = get_settings()

    client = qbittorrentapi.Client(
        host=settings.qbittorrent.host,
        username=settings.qbittorrent.username,
        password=settings.qbittorrent.password,
    )

    # This will raise on auth failure
    client.auth_log_in()

    logger.debug(f"Connected to qBittorrent at {settings.qbittorrent.host}")
    logger.debug(f"qBittorrent version: {client.app.version}")

    return client


def upload_torrent(
    torrent_path: Path,
    save_path: Path,
    category: str | None = None,
    tags: list[str] | None = None,
    paused: bool | None = None,
) -> bool:
    """
    Add a torrent file to qBittorrent.

    Args:
        torrent_path: Path to .torrent file
        save_path: Where to save downloaded/seeded content
        category: Category to assign (default from config)
        tags: Tags to assign (default from config)
        paused: Start paused (default from config)

    Returns:
        True if added successfully, False otherwise.
    """
    settings = get_settings()

    # Apply defaults from config
    if category is None:
        category = settings.qbittorrent.category
    if tags is None:
        tags = settings.qbittorrent.tags
    if paused is None:
        paused = not settings.qbittorrent.auto_start

    if not torrent_path.exists():
        logger.error(f"Torrent file not found: {torrent_path}")
        return False

    try:
        client = get_client()

        # Read torrent file
        with open(torrent_path, "rb") as f:
            torrent_data = f.read()

        # Add to qBittorrent
        result = client.torrents_add(
            torrent_files=torrent_data,
            save_path=str(save_path),
            category=category,
            tags=",".join(tags) if tags else None,
            is_paused=paused,
        )

        if result == "Ok.":
            logger.info(f"Added torrent to qBittorrent: {torrent_path.name}")
            logger.debug(f"  Save path: {save_path}")
            logger.debug(f"  Category: {category}")
            logger.debug(f"  Tags: {tags}")
            return True
        else:
            logger.warning(f"qBittorrent returned unexpected result: {result}")
            return False

    except qbittorrentapi.LoginFailed as e:
        logger.error(f"qBittorrent login failed: {e}")
        return False

    except qbittorrentapi.APIConnectionError as e:
        logger.error(f"qBittorrent connection error: {e}")
        return False

    except OSError as e:
        logger.error(f"Error reading torrent file: {e}")
        return False


def check_torrent_exists(info_hash: str) -> bool:
    """
    Check if a torrent with the given info hash already exists.

    Args:
        info_hash: Torrent info hash (lowercase hex)

    Returns:
        True if torrent exists in client.
    """
    try:
        client = get_client()
        torrents = client.torrents_info(hashes=info_hash)
        return len(torrents) > 0

    except (qbittorrentapi.LoginFailed, qbittorrentapi.APIConnectionError) as e:
        logger.warning(f"Error checking for existing torrent: {e}")
        return False


def get_torrent_info(info_hash: str) -> dict[str, Any] | None:
    """Get info about a torrent by hash."""
    try:
        client = get_client()
        torrents = client.torrents_info(hashes=info_hash)
        if torrents:
            info: dict[str, Any] = torrents[0].info
            return info
        return None

    except (qbittorrentapi.LoginFailed, qbittorrentapi.APIConnectionError) as e:
        logger.warning(f"Error getting torrent info: {e}")
        return None


def test_connection() -> bool:
    """
    Test connection to qBittorrent.

    Returns:
        True if connection and auth successful.
    """
    try:
        client = get_client()
        _ = client.app.version
        return True

    except Exception as e:
        logger.error(f"qBittorrent connection test failed: {e}")
        return False
