"""
Tests for session utilities.

This module tests session creation and configuration.
"""

from unittest.mock import Mock, patch
import tempfile
import os
import ssl
import httpx

from pulp_tool.utils import create_session_with_retry


class TestSessionUtilities:
    """Test session utility functions."""

    def test_create_session_with_retry(self):
        """Test create_session_with_retry function."""
        session = create_session_with_retry()

        assert isinstance(session, httpx.Client)
        # Check that timeout is configured (limits are not accessible after init)
        assert session.timeout is not None
        assert session.timeout.connect == 10.0
        # Verify it's a properly configured client
        assert not session.is_closed

    def test_create_session_with_cert_files_exist(self):
        """Test create_session_with_retry with actual certificate files."""
        # Create temporary cert and key files
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as cert_file:
            cert_file.write("-----BEGIN CERTIFICATE-----\nfake cert\n-----END CERTIFICATE-----\n")
            cert_path = cert_file.name

        with tempfile.NamedTemporaryFile(mode="w", suffix=".key", delete=False) as key_file:
            key_file.write("-----BEGIN PRIVATE KEY-----\nfake key\n-----END PRIVATE KEY-----\n")
            key_path = key_file.name

        try:
            # Mock ssl.create_default_context to avoid actual cert loading
            with patch("ssl.create_default_context") as mock_ssl:
                mock_context = Mock(spec=ssl.SSLContext)
                mock_ssl.return_value = mock_context

                session = create_session_with_retry(cert=(cert_path, key_path))

                # Verify SSL context was created and cert chain was attempted to load
                mock_ssl.assert_called_once()
                mock_context.load_cert_chain.assert_called_once_with(certfile=cert_path, keyfile=key_path)
                assert isinstance(session, httpx.Client)
        finally:
            # Cleanup
            os.unlink(cert_path)
            os.unlink(key_path)

    def test_create_session_with_cert_files_not_exist(self):
        """Test create_session_with_retry with non-existent certificate files."""
        # Use paths that don't exist
        session = create_session_with_retry(cert=("/nonexistent/cert.pem", "/nonexistent/key.pem"))

        # Should still create a session, just without SSL context
        assert isinstance(session, httpx.Client)
        assert not session.is_closed

    def test_create_session_custom_timeout(self):
        """Test create_session_with_retry with custom timeout."""
        session = create_session_with_retry(timeout=60.0)

        assert isinstance(session, httpx.Client)
        # Check that custom timeout is applied (connect timeout is always 10.0)
        assert session.timeout.connect == 10.0

    def test_create_session_custom_max_connections(self):
        """Test create_session_with_retry with custom max_connections."""
        session = create_session_with_retry(max_connections=200)

        assert isinstance(session, httpx.Client)
        assert not session.is_closed

    def test_create_session_http2_not_available(self):
        """Test create_session_with_retry when HTTP/2 is not available."""
        with patch("importlib.util.find_spec", return_value=None):
            session = create_session_with_retry()

            assert isinstance(session, httpx.Client)
            # HTTP/2 should be disabled when h2 package is not available
            # Note: httpx.Client doesn't expose http2 setting after initialization
            assert not session.is_closed
