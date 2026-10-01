"""
Tests for DistributionClient class.

This module contains comprehensive tests for the DistributionClient class
and related distribution functionality.
"""

from unittest.mock import mock_open, patch

import httpx
import pytest
from httpx import HTTPError

from pulp_tool.api import DistributionClient
from pulp_tool.exceptions import PulpToolChecksumError


class TestDistributionClient:
    """Test DistributionClient class functionality."""

    def test_init(self) -> None:
        """Test DistributionClient initialization with cert/key."""
        client = DistributionClient(cert="cert.pem", key="key.pem")
        assert client.cert == "cert.pem"
        assert client.key == "key.pem"
        assert client.session is not None

    def test_init_username_password(self) -> None:
        """Test DistributionClient initialization with username/password."""
        client = DistributionClient(username="user", password="pass")
        assert client.username == "user"
        assert client.password == "pass"
        assert client.cert is None
        assert client.key is None
        assert client.session is not None

    def test_init_no_auth_raises(self) -> None:
        """Test DistributionClient raises when no auth provided."""
        with pytest.raises(ValueError, match="Provide either"):
            DistributionClient()

    def test_init_both_auth_raises(self) -> None:
        """Test DistributionClient raises when both cert and username/password provided."""
        with pytest.raises(ValueError, match="not both"):
            DistributionClient(cert="c.pem", key="k.pem", username="u", password="p")

    def test_create_session(self) -> None:
        """Test _create_session method."""
        client = DistributionClient(cert="cert.pem", key="key.pem")
        session = client._create_session()
        assert session is not None

    def test_pull_artifact(self, httpx_mock) -> None:
        """Test pull_artifact method."""
        client = DistributionClient(cert="cert.pem", key="key.pem")
        httpx_mock.get("https://example.com/artifacts.json").mock(
            return_value=httpx.Response(200, json={"artifacts": {"test.rpm": {"pulp_labels": {"build_id": "test"}}}})
        )
        response = client.pull_artifact("https://example.com/artifacts.json")
        assert response.status_code == 200
        assert response.json()["artifacts"]["test.rpm"]["pulp_labels"]["build_id"] == "test"

    def test_pull_artifact_raises_on_http_error(self, httpx_mock) -> None:
        """Non-success responses fail immediately (raise_for_status)."""
        httpx_mock.get("https://example.com/missing.json").mock(return_value=httpx.Response(404))
        client = DistributionClient(cert="cert.pem", key="key.pem")
        with pytest.raises(httpx.HTTPStatusError):
            client.pull_artifact("https://example.com/missing.json")

    def test_pull_data(self, httpx_mock) -> None:
        """Test pull_data method."""
        httpx_mock.get("https://example.com/file.rpm").mock(
            return_value=httpx.Response(200, content=b"file content", headers={"content-length": "12"})
        )
        with (
            patch("os.makedirs"),
            patch("builtins.open", mock_open(read_data=b"file content")) as mock_open_func,
            patch("pulp_tool.api.distribution_client.logging") as mock_logging,
        ):
            client = DistributionClient(cert="cert.pem", key="key.pem")
            result = client.pull_data("file.rpm", "https://example.com/file.rpm", "x86_64", "rpm")
            assert result == "file.rpm"
            mock_logging.info.assert_called()
            mock_open_func.assert_called_once_with("file.rpm", "wb")

    def test_pull_data_verifies_sha256(self, httpx_mock) -> None:
        import hashlib

        content = b"rpm payload"
        digest = hashlib.sha256(content).hexdigest()
        httpx_mock.get("https://example.com/file.rpm").mock(
            return_value=httpx.Response(200, content=content, headers={"content-length": str(len(content))})
        )
        with (
            patch("os.makedirs"),
            patch("builtins.open", mock_open()) as mock_open_func,
        ):
            client = DistributionClient(cert="cert.pem", key="key.pem")
            result = client.pull_data("file.rpm", "https://example.com/file.rpm", "x86_64", "rpm", digest)
            assert result == "file.rpm"
            mock_open_func.assert_called_once_with("file.rpm", "wb")

    def test_pull_data_sha256_mismatch(self, httpx_mock) -> None:
        httpx_mock.get("https://example.com/file.rpm").mock(
            return_value=httpx.Response(200, content=b"wrong", headers={"content-length": "5"})
        )
        with patch("os.makedirs"), patch("builtins.open", mock_open()), patch("pathlib.Path.unlink"):
            client = DistributionClient(cert="cert.pem", key="key.pem")
            with pytest.raises(PulpToolChecksumError, match="mismatch"):
                client.pull_data("file.rpm", "https://example.com/file.rpm", "x86_64", "rpm", "a" * 64)

    def test_pull_data_async_success(self) -> None:
        """Test successful async data pull."""
        client = DistributionClient(cert="/tmp/cert.pem", key="/tmp/key.pem")
        download_info = ("test.rpm", "https://example.com/test.rpm", "x86_64", "rpm")
        with patch.object(client, "pull_data", return_value="/tmp/test.rpm"):
            result = client.pull_data_async(download_info)
            assert result == ("test.rpm", "/tmp/test.rpm")

    def test_pull_data_async_exception(self) -> None:
        """Test async data pull with exception."""
        client = DistributionClient(cert="/tmp/cert.pem", key="/tmp/key.pem")
        download_info = ("test.rpm", "https://example.com/test.rpm", "x86_64", "rpm")
        with patch.object(client, "pull_data", side_effect=HTTPError("Network error")):
            with pytest.raises(HTTPError):
                client.pull_data_async(download_info)

    def test_pull_data_log_file(self, httpx_mock) -> None:
        """Test pull_data method for log files."""
        httpx_mock.get("https://example.com/test.log").mock(
            return_value=httpx.Response(200, content=b"log content", headers={"content-length": "12"})
        )
        with (
            patch("os.makedirs") as mock_makedirs,
            patch("builtins.open", mock_open(read_data=b"log content")) as mock_open_func,
            patch("pulp_tool.api.distribution_client.logging") as mock_logging,
        ):
            client = DistributionClient(cert="cert.pem", key="key.pem")
            result = client.pull_data("test.log", "https://example.com/test.log", "x86_64", "log")
            assert result == "logs/x86_64/test.log"
            mock_logging.info.assert_called()
            mock_makedirs.assert_called_once_with("logs/x86_64", exist_ok=True)
            mock_open_func.assert_called_once_with("logs/x86_64/test.log", "wb")

    def test_pull_artifact_enforces_fetch_policy_when_base_url_set(self, httpx_mock) -> None:
        """SSRF mitigation: remote URLs must match cli.base_url and /api/pulp-content/."""
        client = DistributionClient(
            cert="cert.pem",
            key="key.pem",
            pulp_api_base_url="https://pulp.example.com",
        )
        good = "https://pulp.example.com/api/pulp-content/ns/build/artifacts/pulp_results.json"
        httpx_mock.get(good).mock(return_value=httpx.Response(200, json={"artifacts": {}}))
        assert client.pull_artifact(good).status_code == 200

        with pytest.raises(ValueError, match="host other than"):
            client.pull_artifact("https://other.example/api/pulp-content/ns/x")

    def test_pull_artifact_with_username_password(self, httpx_mock) -> None:
        """Test pull_artifact with Basic Auth (username/password)."""
        httpx_mock.get("https://example.com/artifacts.json").mock(
            return_value=httpx.Response(200, json={"artifacts": {"test.rpm": {"pulp_labels": {"build_id": "test"}}}})
        )
        client = DistributionClient(username="user", password="pass")
        response = client.pull_artifact("https://example.com/artifacts.json")
        assert response.status_code == 200

    def test_pull_data_sbom_file(self, httpx_mock) -> None:
        """Test pull_data method for SBOM files."""
        httpx_mock.get("https://example.com/test.sbom").mock(
            return_value=httpx.Response(200, content=b"sbom content", headers={"content-length": "12"})
        )
        with (
            patch("builtins.open", mock_open(read_data=b"sbom content")) as mock_open_func,
            patch("pulp_tool.api.distribution_client.logging") as mock_logging,
        ):
            client = DistributionClient(cert="cert.pem", key="key.pem")
            result = client.pull_data("test.sbom", "https://example.com/test.sbom", "noarch", "sbom")
            assert result == "test.sbom"
            mock_logging.info.assert_called()
            mock_open_func.assert_called_once_with("test.sbom", "wb")
