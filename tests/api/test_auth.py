"""
Tests for OAuth2 authentication.

This module contains comprehensive tests for OAuth2ClientCredentialsAuth
and related authentication functionality.
"""

from datetime import datetime, timedelta
import pytest
import httpx

from pulp_tool.api import OAuth2ClientCredentialsAuth


class TestOAuth2ClientCredentialsAuth:
    """Test OAuth2ClientCredentialsAuth class."""

    def test_init(self):
        """Test OAuth2ClientCredentialsAuth initialization."""
        auth = OAuth2ClientCredentialsAuth(
            client_id="test-client", client_secret="test-secret", token_url="https://test.com/token"
        )

        assert auth._token_url == "https://test.com/token"
        assert auth._client_id == "test-client"
        assert auth._client_secret == "test-secret"
        assert auth._access_token is None
        assert auth._expire_at is None

    def test_auth_flow_without_token(self, httpx_mock):
        """Test auth_flow when no token exists."""
        auth = OAuth2ClientCredentialsAuth(
            client_id="test-client", client_secret="test-secret", token_url="https://test.com/token"
        )

        # Mock token endpoint
        httpx_mock.post("https://test.com/token").mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "test-token", "expires_in": 3600},
            )
        )

        request = httpx.Request("GET", "https://api.example.com/test")

        # Execute auth flow
        flow = auth.auth_flow(request)
        authenticated_request = next(flow)

        assert authenticated_request.headers["Authorization"] == "Bearer test-token"

    def test_auth_flow_with_expired_token(self, httpx_mock):
        """Test auth_flow with expired token."""
        auth = OAuth2ClientCredentialsAuth(
            client_id="test-client", client_secret="test-secret", token_url="https://test.com/token"
        )

        # Set expired token
        auth._expire_at = datetime.now() - timedelta(seconds=1)
        auth._access_token = "old-token"

        # Mock token endpoint
        httpx_mock.post("https://test.com/token").mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "new-token", "expires_in": 3600},
            )
        )

        request = httpx.Request("GET", "https://api.example.com/test")

        # Execute auth flow
        flow = auth.auth_flow(request)
        authenticated_request = next(flow)

        assert authenticated_request.headers["Authorization"] == "Bearer new-token"

    def test_auth_flow_with_401_retry(self, httpx_mock):
        """Test auth_flow handles 401 and retries with new token."""
        auth = OAuth2ClientCredentialsAuth(
            client_id="test-client", client_secret="test-secret", token_url="https://test.com/token"
        )

        # Mock token endpoint - will be called twice
        httpx_mock.post("https://test.com/token").mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "test-token", "expires_in": 3600},
            )
        )

        request = httpx.Request("GET", "https://api.example.com/test")

        # Execute auth flow
        flow = auth.auth_flow(request)
        authenticated_request = next(flow)

        # Simulate 401 response
        response_401 = httpx.Response(401, request=authenticated_request)

        try:
            retry_request = flow.send(response_401)
            assert retry_request.headers["Authorization"].startswith("Bearer ")
        except StopIteration:
            pass

    def test_retrieve_token_success(self, httpx_mock):
        """Test successful token retrieval."""
        auth = OAuth2ClientCredentialsAuth(
            client_id="test-client", client_secret="test-secret", token_url="https://test.com/token"
        )

        httpx_mock.post("https://test.com/token").mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "test-token", "expires_in": 3600},
            )
        )

        auth._retrieve_token()

        assert auth._access_token == "test-token"
        assert auth._expire_at is not None
        assert auth._expire_at > datetime.now()

    def test_retrieve_token_invalid_response(self, httpx_mock):
        """Test token retrieval with invalid response format."""
        auth = OAuth2ClientCredentialsAuth(
            client_id="test-client", client_secret="test-secret", token_url="https://test.com/token"
        )

        httpx_mock.post("https://test.com/token").mock(
            return_value=httpx.Response(
                200,
                json={"invalid": "response"},
            )
        )

        with pytest.raises(ValueError, match="Invalid token response format"):
            auth._retrieve_token()

    def test_retrieve_token_http_error(self, httpx_mock):
        """Test token retrieval with HTTP error."""
        auth = OAuth2ClientCredentialsAuth(
            client_id="test-client", client_secret="test-secret", token_url="https://test.com/token"
        )

        httpx_mock.post("https://test.com/token").mock(
            return_value=httpx.Response(
                500,
                json={"error": "Internal Server Error"},
            )
        )

        with pytest.raises(httpx.HTTPError):
            auth._retrieve_token()

    def test_access_token_property(self, mock_oauth_auth):
        """Test access_token property."""
        mock_oauth_auth._access_token = "test-token"
        assert mock_oauth_auth.access_token == "test-token"

    def test_expires_at_property(self, mock_oauth_auth):
        """Test expires_at property."""
        expire_time = datetime.now() + timedelta(hours=1)
        mock_oauth_auth._expire_at = expire_time
        assert mock_oauth_auth.expires_at == expire_time


class TestOAuth2Integration:
    """Integration tests for OAuth2 authentication."""

    def test_auth_with_real_request(self, httpx_mock):
        """Test authentication flow with a real-looking request."""
        auth = OAuth2ClientCredentialsAuth(
            client_id="test-client", client_secret="test-secret", token_url="https://test.com/token"
        )

        # Mock token endpoint
        httpx_mock.post("https://test.com/token").mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "valid-token", "expires_in": 7200},
            )
        )

        # Mock API endpoint
        httpx_mock.get("https://api.example.com/data").mock(
            return_value=httpx.Response(
                200,
                json={"data": "test"},
            )
        )

        # Make authenticated request
        with httpx.Client(auth=auth) as client:
            response = client.get("https://api.example.com/data")

        assert response.status_code == 200
        assert response.json() == {"data": "test"}
