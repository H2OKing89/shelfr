"""Tests for logging_setup module."""

from __future__ import annotations

import logging
from pathlib import Path

from shelfr.logging_setup import set_console_quiet, setup_logging


class TestSetupLogging:
    """Tests for setup_logging function."""

    def test_default_setup(self) -> None:
        """Test default logging setup."""
        logger = setup_logging()
        assert logger.name == "mamfast"
        assert logger.level == logging.INFO
        assert len(logger.handlers) >= 1

    def test_custom_log_level(self) -> None:
        """Test setting custom log level."""
        logger = setup_logging(log_level="DEBUG")
        assert logger.level == logging.DEBUG

    def test_warning_log_level(self) -> None:
        """Test setting warning log level."""
        logger = setup_logging(log_level="WARNING")
        assert logger.level == logging.WARNING

    def test_error_log_level(self) -> None:
        """Test setting error log level."""
        logger = setup_logging(log_level="ERROR")
        assert logger.level == logging.ERROR

    def test_invalid_log_level_defaults_to_info(self) -> None:
        """Test that invalid log level defaults to INFO."""
        logger = setup_logging(log_level="INVALID")
        assert logger.level == logging.INFO

    def test_case_insensitive_log_level(self) -> None:
        """Test that log level is case insensitive."""
        logger = setup_logging(log_level="debug")
        assert logger.level == logging.DEBUG

    def test_with_log_file(self, tmp_path: Path) -> None:
        """Test logging with file output."""
        log_file = tmp_path / "test.log"
        logger = setup_logging(log_file=log_file)

        # Should have file handler
        file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) == 1

        # Log a message and verify it's in file
        logger.info("Test message")
        assert log_file.exists()
        content = log_file.read_text()
        assert "Test message" in content

    def test_log_file_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Test that log file creation creates parent directories."""
        log_file = tmp_path / "nested" / "dir" / "test.log"
        setup_logging(log_file=log_file)
        assert log_file.parent.exists()

    def test_log_file_as_string(self, tmp_path: Path) -> None:
        """Test log file path as string."""
        log_file = str(tmp_path / "test.log")
        logger = setup_logging(log_file=log_file)
        file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) == 1

    def test_rich_console_enabled(self) -> None:
        """Test rich console handler."""
        from rich.logging import RichHandler

        logger = setup_logging(rich_console=True)
        rich_handlers = [h for h in logger.handlers if isinstance(h, RichHandler)]
        assert len(rich_handlers) == 1

    def test_rich_console_disabled(self) -> None:
        """Test plain stream handler when rich is disabled."""
        from rich.logging import RichHandler

        logger = setup_logging(rich_console=False)
        rich_handlers = [h for h in logger.handlers if isinstance(h, RichHandler)]
        assert len(rich_handlers) == 0
        stream_handlers = [h for h in logger.handlers if isinstance(h, logging.StreamHandler)]
        assert len(stream_handlers) >= 1

    def test_quiet_console_mode(self) -> None:
        """Test quiet console mode sets WARNING level."""
        logger = setup_logging(quiet_console=True)
        console_handler = logger.handlers[0]
        assert console_handler.level == logging.WARNING

    def test_handlers_cleared_on_setup(self) -> None:
        """Test that handlers are cleared on each setup call."""
        logger1 = setup_logging()
        initial_count = len(logger1.handlers)

        logger2 = setup_logging()
        # Handlers should be same count, not doubled
        assert len(logger2.handlers) == initial_count


class TestSetConsoleQuiet:
    """Tests for set_console_quiet function."""

    def test_set_quiet_true(self) -> None:
        """Test setting console to quiet mode."""
        setup_logging()  # Initialize handler
        set_console_quiet(True)
        # Should not raise - function sets the level

    def test_set_quiet_false(self) -> None:
        """Test setting console to normal mode."""
        setup_logging()
        set_console_quiet(False)
        # Should not raise

    def test_quiet_before_setup(self) -> None:
        """Test calling set_console_quiet before setup_logging."""
        # Reset the global handler - access internal state for testing
        from shelfr import logging_setup as ls

        ls._console_handler = None

        # Should not raise even if handler is None
        set_console_quiet(True)

    def test_quiet_toggle(self) -> None:
        """Test toggling quiet mode."""
        setup_logging()
        set_console_quiet(True)
        set_console_quiet(False)
        set_console_quiet(True)
        # Should complete without error
