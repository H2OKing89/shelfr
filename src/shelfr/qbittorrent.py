"""
qBittorrent API wrapper for uploading torrents.

Uses the qbittorrent-api package with idempotent upload support
to prevent duplicate torrents.

Connection pooling: Reuses a single client instance per session
to avoid repeated authentication overhead.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from pathlib import Path
from typing import Any

import qbittorrentapi

from shelfr.config import get_settings
from shelfr.utils.retry import retry_with_backoff
from shelfr.utils.torrent import extract_infohash

logger = logging.getLogger(__name__)

# Network exceptions that should trigger retry
NETWORK_EXCEPTIONS = (
    qbittorrentapi.APIConnectionError,
    qbittorrentapi.HTTPError,
    OSError,
)

# Connection pool: Thread-safe cached client
_client: qbittorrentapi.Client | None = None
_client_lock = threading.Lock()


def _create_client() -> qbittorrentapi.Client:
    """
    Create a new authenticated qBittorrent client.

    Internal function - use get_client() for pooled access.
    """
    settings = get_settings()

    client = qbittorrentapi.Client(
        host=settings.qbittorrent.host,
        username=settings.qbittorrent.username,
        password=settings.qbittorrent.password,
    )

    # Authenticate
    client.auth_log_in()

    logger.debug(f"Connected to qBittorrent at {settings.qbittorrent.host}")
    logger.debug(f"qBittorrent version: {client.app.version}")

    return client


@retry_with_backoff(
    max_attempts=3,
    base_delay=2.0,
    max_delay=30.0,
    exceptions=NETWORK_EXCEPTIONS,
)
def get_client() -> qbittorrentapi.Client:
    """
    Get a pooled, authenticated qBittorrent API client.

    Uses connection pooling to reuse the same client across calls,
    reducing authentication overhead. Thread-safe.

    If the cached client is invalid (session expired, connection lost),
    a new client is created automatically.

    Returns:
        Connected and authenticated client.

    Raises:
        qbittorrentapi.LoginFailed: If authentication fails (not retried).
        qbittorrentapi.APIConnectionError: If connection fails after retries.
    """
    global _client

    with _client_lock:
        if _client is not None:
            # Verify existing client is still valid
            try:
                # Quick health check - if this fails, client is stale
                _ = _client.app.version
                return _client
            except (qbittorrentapi.APIConnectionError, qbittorrentapi.HTTPError):
                logger.debug("Cached qBittorrent client expired, reconnecting...")
                _client = None

        # Create new client
        _client = _create_client()
        return _client


def reset_client() -> None:
    """
    Reset the cached client connection.

    Call this after configuration changes or to force reconnection.
    """
    global _client
    with _client_lock:
        if _client is not None:
            with contextlib.suppress(Exception):
                _client.auth_log_out()
            _client = None
            logger.debug("qBittorrent client reset")


def upload_torrent(
    torrent_path: Path,
    save_path: Path | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    paused: bool | None = None,
    use_auto_tmm: bool | None = None,
) -> tuple[bool, str | None]:
    """
    Add a torrent file to qBittorrent (idempotent).

    **Idempotency**: Checks if torrent already exists by infohash before uploading.
    If it exists, returns success without re-uploading (prevents duplicates).

    Save path logic:
    - If auto_tmm=True: qBittorrent manages paths via category settings (save_path ignored)
    - If auto_tmm=False: Uses save_path from config (required)

    Args:
        torrent_path: Path to .torrent file
        save_path: Where content is located (only used when auto_tmm=False)
        category: Category to assign (default from config)
        tags: Tags to assign (default from config)
        paused: Start paused (default from config)
        use_auto_tmm: Enable Automatic Torrent Management (default from config)

    Returns:
        Tuple of (success: bool, infohash: str | None)
        - success=True if added or already exists
        - infohash is returned for state tracking
    """
    settings = get_settings()

    # Apply defaults from config
    if category is None:
        category = settings.qbittorrent.category
    if tags is None:
        tags = settings.qbittorrent.tags
    if paused is None:
        paused = not settings.qbittorrent.auto_start
    if use_auto_tmm is None:
        use_auto_tmm = settings.qbittorrent.auto_tmm

    if not torrent_path.exists():
        logger.error(f"Torrent file not found: {torrent_path}")
        return False, None

    # IDEMPOTENCY: Extract infohash and check if torrent already exists
    infohash = extract_infohash(torrent_path)
    if not infohash:
        logger.error(f"Could not extract infohash from {torrent_path}")
        return False, None

    try:
        # Check if torrent already exists
        if check_torrent_exists(infohash):
            logger.info(
                f"Torrent already exists in qBittorrent (infohash: {infohash})\n"
                f"  File: {torrent_path.name}\n"
                f"  This is SAFE - upload is idempotent, no duplicate created."
            )
            return True, infohash

        client = get_client()

        # Read torrent file
        with open(torrent_path, "rb") as f:
            torrent_data = f.read()

        # Build add parameters based on auto_tmm setting
        # Priority: auto_tmm > save_path (if auto_tmm is enabled, save_path is ignored)
        add_params: dict[str, Any] = {
            "torrent_files": torrent_data,
            "category": category,
            "tags": ",".join(tags) if tags else None,
            "is_paused": paused,
            "use_auto_tmm": use_auto_tmm,
        }

        if use_auto_tmm:
            # Auto TMM enabled: qBittorrent manages save path via category
            logger.debug("Auto TMM enabled - qBittorrent will manage save path")
        else:
            # Auto TMM disabled: use explicit save_path if provided
            if save_path is not None:
                add_params["save_path"] = str(save_path)
                logger.debug(f"Using explicit save_path: {save_path}")
            elif settings.qbittorrent.save_path:
                # Use configured save_path as fallback
                add_params["save_path"] = settings.qbittorrent.save_path
                logger.debug(f"Using config save_path: {settings.qbittorrent.save_path}")
            else:
                # No save_path configured - let qBittorrent use its default
                logger.debug("No save_path configured - qBittorrent will use default location")

        # Add to qBittorrent
        result = client.torrents_add(**add_params)

        if result == "Ok.":
            logger.info(f"Added torrent to qBittorrent: {torrent_path.name}")
            logger.debug(f"  Infohash: {infohash}")
            logger.debug(f"  Category: {category}")
            logger.debug(f"  Tags: {tags}")
            logger.debug(f"  Auto TMM: {use_auto_tmm}")
            if not use_auto_tmm:
                logger.debug(f"  Save path: {add_params.get('save_path')}")
            return True, infohash
        else:
            logger.warning(f"qBittorrent returned unexpected result: {result}")
            return False, infohash

    except qbittorrentapi.LoginFailed as e:
        logger.error(
            f"qBittorrent login failed: {e}\n"
            f"Troubleshooting:\n"
            f"  1. Verify credentials in config/.env:\n"
            f"     - QB_USERNAME: {settings.qbittorrent.username}\n"
            f"     - QB_PASSWORD: (check it's set correctly)\n"
            f"  2. Check if authentication is enabled in qBittorrent WebUI settings\n"
            f"  3. Try logging in manually: {settings.qbittorrent.host}"
        )
        return False, infohash

    except qbittorrentapi.APIConnectionError as e:
        logger.error(
            f"qBittorrent connection error: {e}\n"
            f"Troubleshooting:\n"
            f"  1. Verify qBittorrent is running\n"
            f"  2. Check QB_HOST in config/.env: {settings.qbittorrent.host}\n"
            f"  3. Verify WebUI is enabled in qBittorrent preferences\n"
            f"  4. Test connectivity: curl {settings.qbittorrent.host}/api/v2/app/version\n"
            f"  5. Check firewall/network settings"
        )
        return False, infohash

    except OSError as e:
        logger.error(f"Error reading torrent file: {e}")
        return False, infohash


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
