"""
Tests for logging utilities.

This module tests logging setup and formatter functionality.
"""

from unittest.mock import Mock, patch
import logging

from pulp_tool.utils import setup_logging, WrappingFormatter


class TestLoggingUtilities:
    """Test logging utility functions."""

    def test_setup_logging_debug(self):
        """Test setup_logging with debug level."""
        with patch("logging.basicConfig") as mock_basic_config:
            setup_logging(verbosity=2)  # DEBUG level
            mock_basic_config.assert_called_once()

    def test_setup_logging_info(self):
        """Test setup_logging with info level."""
        with patch("logging.basicConfig") as mock_basic_config:
            setup_logging(verbosity=1)  # INFO level
            mock_basic_config.assert_called_once()

    def test_setup_logging_with_wrapping(self):
        """Test setup_logging with wrapping enabled."""
        setup_logging(verbosity=2, use_wrapping=True)  # DEBUG with wrapping

        # Verify logging is configured with custom handler
        root_logger = logging.getLogger()
        assert root_logger.level == logging.DEBUG
        assert len(root_logger.handlers) > 0

    def test_wrapping_formatter(self):
        """Test WrappingFormatter class."""
        formatter = WrappingFormatter(width=50)

        # Test short message
        record = Mock()
        record.getMessage.return_value = "Short message"
        record.levelname = "INFO"
        record.name = "test"
        record.pathname = "/test/path"
        record.lineno = 1
        record.funcName = "test_func"
        record.exc_text = None
        record.exc_info = None
        record.stack_info = None
        formatted = formatter.format(record)
        assert len(formatted) <= 50

        # Test long message
        record.getMessage.return_value = (
            "This is a very long message that should be wrapped because it exceeds the specified width limit"
        )
        formatted = formatter.format(record)
        assert "\n" in formatted
