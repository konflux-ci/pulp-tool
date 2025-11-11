"""
Tests for error handling and edge cases.

This module contains comprehensive tests for error handling,
edge cases, and exception scenarios across the pulp-tool package.
"""

import os
import tempfile
from unittest.mock import Mock, patch
import pytest
import httpx
from httpx import HTTPError, ConnectError, TimeoutException

from pulp_tool.api import PulpClient, OAuth2ClientCredentialsAuth
from pulp_tool.utils import PulpHelper, validate_file_path


class TestPulpClientErrorHandling:
    """Test PulpClient error handling."""

    def test_check_response_server_error(self, mock_config, httpx_mock):
        """Test _check_response method with server error."""
        client = PulpClient(mock_config)

        # Mock server error responses for chunked_get - need to mock each chunk separately
        httpx_mock.get(
            "https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/?test_param=value1%2Cvalue2"
        ).mock(
            return_value=httpx.Response(
                500, json={"error": "Internal Server Error"}, headers={"content-type": "application/json"}
            )
        )

        with patch("pulp_tool.api.pulp_client.logging") as mock_logging:
            with pytest.raises(HTTPError, match="Failed to chunked request"):
                client._chunked_get(
                    "https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/",
                    {"test_param": "value1,value2,value3"},
                    chunk_param="test_param",
                    chunk_size=2,  # Small chunk size to force chunking
                )

            # Verify error logging
            mock_logging.error.assert_called()

    def test_check_response_client_error(self, mock_config, httpx_mock):
        """Test _check_response method with client error."""
        client = PulpClient(mock_config)

        # Mock client error responses for chunked_get - need to mock each chunk separately
        httpx_mock.get(
            "https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/?test_param=value1%2Cvalue2"
        ).mock(return_value=httpx.Response(400, text="Bad Request", headers={}))

        with pytest.raises(HTTPError, match="Failed to chunked request"):
            client._chunked_get(
                "https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/",
                {"test_param": "value1,value2,value3"},
                chunk_param="test_param",
                chunk_size=2,  # Small chunk size to force chunking
            )

    def test_upload_content_file_not_found(self, mock_config):
        """Test upload_content method with non-existent file."""
        client = PulpClient(mock_config)

        labels = {"build_id": "test-build"}

        with pytest.raises(FileNotFoundError):
            client.upload_content("/non/existent/file.rpm", labels, file_type="RPM", arch="x86_64")

    def test_upload_content_permission_error(self, mock_config):
        """Test upload_content method with permission error."""
        client = PulpClient(mock_config)

        # Create a file without read permissions
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name

        try:
            os.chmod(temp_path, 0o000)  # No permissions

            labels = {"build_id": "test-build"}

            with pytest.raises(PermissionError):
                client.upload_content(temp_path, labels, file_type="RPM", arch="x86_64")
        finally:
            os.chmod(temp_path, 0o644)
            os.unlink(temp_path)

    def test_upload_content_empty_file(self, mock_config):
        """Test upload_content method with empty file."""
        client = PulpClient(mock_config)

        # Create an empty file
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name

        try:
            labels = {"build_id": "test-build"}

            with pytest.raises(ValueError, match="RPM file is empty"):
                client.upload_content(temp_path, labels, file_type="RPM", arch="x86_64")
        finally:
            os.unlink(temp_path)

    def test_upload_content_request_exception(self, mock_config, temp_rpm_file, httpx_mock):
        """Test upload_content method with request exception."""
        client = PulpClient(mock_config)

        # Mock the upload endpoint to raise an exception
        httpx_mock.post("https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/rpm/packages/upload/").mock(
            side_effect=HTTPError("Network error")
        )

        labels = {"build_id": "test-build"}

        with patch("pulp_tool.api.content_manager.validate_file_path"), patch(
            "pulp_tool.api.content_manager.logging"
        ) as mock_logging:

            with pytest.raises(HTTPError):
                client.upload_content(temp_rpm_file, labels, file_type="RPM", arch="x86_64")

            mock_logging.error.assert_called()

    def test_wait_for_finished_task_error_response(self, mock_config, httpx_mock):
        """Test wait_for_finished_task method with HTTP error response."""
        client = PulpClient(mock_config)

        # Mock a task endpoint that returns an HTTP error
        httpx_mock.get("https://pulp.example.com/pulp/api/v3/tasks/12345/").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        # HTTP errors now raise exceptions
        with patch("time.sleep"), pytest.raises(HTTPError):
            client.wait_for_finished_task("/pulp/api/v3/tasks/12345/")

    def test_chunked_get_request_exception(self, mock_config, httpx_mock):
        """Test _chunked_get method with request exception."""
        client = PulpClient(mock_config)

        # Mock the API endpoint to raise an exception
        httpx_mock.get("https://test.com/api").mock(side_effect=HTTPError("Network error"))

        params = {"large_param": ",".join([f"item{i}" for i in range(100)])}

        with pytest.raises(HTTPError):
            client._chunked_get("https://test.com/api", params, chunk_param="large_param", chunk_size=20)

    def test_gather_content_data_exception(self, mock_config):
        """Test gather_content_data method with exception."""
        client = PulpClient(mock_config)
        client.find_content = Mock()
        client.find_content.side_effect = HTTPError("API error")

        with patch("pulp_tool.api.content_query.logging") as mock_logging:
            with pytest.raises(HTTPError):
                client.gather_content_data("test-build-123")

            mock_logging.error.assert_called()


class TestOAuth2ErrorHandling:
    """Test OAuth2ClientCredentialsAuth error handling."""

    def test_retrieve_token_http_error(self):
        """Test _retrieve_token method with HTTP error."""
        auth = OAuth2ClientCredentialsAuth(
            client_id="test-client", client_secret="test-secret", token_url="https://test.com/token"
        )

        with patch("httpx.post", side_effect=HTTPError("401 Unauthorized")):
            with pytest.raises(HTTPError):
                auth._retrieve_token()

    def test_retrieve_token_connection_error(self):
        """Test _retrieve_token method with connection error."""
        auth = OAuth2ClientCredentialsAuth(
            client_id="test-client", client_secret="test-secret", token_url="https://test.com/token"
        )

        with patch("httpx.post", side_effect=ConnectError("Connection failed")):
            with pytest.raises(ConnectError):
                auth._retrieve_token()

    def test_retrieve_token_timeout(self):
        """Test _retrieve_token method with timeout."""
        auth = OAuth2ClientCredentialsAuth(
            client_id="test-client", client_secret="test-secret", token_url="https://test.com/token"
        )

        with patch("httpx.post", side_effect=TimeoutException("Request timeout")):
            with pytest.raises(TimeoutException):
                auth._retrieve_token()

    def test_retrieve_token_invalid_json(self, httpx_mock):
        """Test _retrieve_token method with invalid JSON response."""
        auth = OAuth2ClientCredentialsAuth(
            client_id="test-client", client_secret="test-secret", token_url="https://test.com/token"
        )

        # Mock the token endpoint to return invalid JSON
        httpx_mock.post("https://test.com/token").mock(
            return_value=httpx.Response(200, text="Invalid JSON response", headers={"content-type": "text/plain"})
        )

        with pytest.raises(ValueError):
            auth._retrieve_token()


class TestPulpHelperErrorHandling:
    """Test PulpHelper error handling."""

    def test_setup_repositories_invalid_build_id(self, mock_pulp_client):
        """Test setup_repositories method with invalid build ID."""
        helper = PulpHelper(mock_pulp_client)

        with pytest.raises(ValueError, match="Invalid build ID"):
            helper.setup_repositories("")

    def test_setup_repositories_validation_failure(self, mock_pulp_client):
        """Test setup_repositories method with validation failure."""
        helper = PulpHelper(mock_pulp_client)

        with patch.object(helper, "_setup_repositories_impl", return_value={}), patch(
            "pulp_tool.utils.validation.validate_repository_setup", return_value=(False, ["Missing repo"])
        ):

            with pytest.raises(RuntimeError, match="Repository setup validation failed"):
                helper.setup_repositories("test-build-123")

    def test_create_or_get_repository_invalid_type(self, mock_pulp_client):
        """Test create_or_get_repository method with invalid repository type."""
        helper = PulpHelper(mock_pulp_client)

        with pytest.raises(ValueError, match="Invalid repository type"):
            helper.create_or_get_repository("test-build-123", "invalid")

    def test_create_or_get_repository_invalid_build_id(self, mock_pulp_client):
        """Test create_or_get_repository method with invalid build ID."""
        helper = PulpHelper(mock_pulp_client)

        with pytest.raises(ValueError, match="Invalid build ID"):
            helper.create_or_get_repository("", "rpms")

    def test_get_distribution_urls_invalid_build_id(self, mock_pulp_client):
        """Test get_distribution_urls method with invalid build ID."""
        helper = PulpHelper(mock_pulp_client)

        with pytest.raises(ValueError, match="Invalid build ID"):
            helper.get_distribution_urls("")

    def test_get_distribution_urls_config_error(self, mock_pulp_client):
        """Test get_distribution_urls method with config error."""
        helper = PulpHelper(mock_pulp_client, "/non/existent/config.toml")

        with patch("pulp_tool.utils.url.get_pulp_content_base_url", side_effect=ValueError("Config error")):
            with pytest.raises(ValueError):
                helper.get_distribution_urls("test-build-123")


class TestUtilityErrorHandling:
    """Test utility function error handling."""

    def test_validate_file_path_not_found(self):
        """Test validate_file_path function with non-existent file."""
        with pytest.raises(FileNotFoundError, match="Test file not found"):
            validate_file_path("/non/existent/file.txt", "Test")

    def test_validate_file_path_permission_error(self):
        """Test validate_file_path function with permission error."""
        # Create a file without read permissions
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name

        try:
            os.chmod(temp_path, 0o000)  # No permissions

            with pytest.raises(PermissionError, match="Cannot read Test file"):
                validate_file_path(temp_path, "Test")
        finally:
            os.chmod(temp_path, 0o644)
            os.unlink(temp_path)

    def test_validate_file_path_empty_file(self):
        """Test validate_file_path function with empty file."""
        # Create an empty file
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name

        try:
            with pytest.raises(ValueError, match="Test file is empty"):
                validate_file_path(temp_path, "Test")
        finally:
            os.unlink(temp_path)


class TestConfigErrorHandling:
    """Test configuration error handling."""

    def test_get_pulp_content_base_url_file_not_found(self):
        """Test get_pulp_content_base_url function with non-existent file."""
        from pulp_tool.utils import get_pulp_content_base_url

        with pytest.raises(ValueError, match="Cannot determine Pulp content base URL"):
            get_pulp_content_base_url("/non/existent/config.toml")

    def test_get_pulp_content_base_url_invalid_config(self):
        """Test get_pulp_content_base_url function with invalid config."""
        from pulp_tool.utils import get_pulp_content_base_url

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".toml") as f:
            f.write("invalid toml content")
            temp_path = f.name

        try:
            with pytest.raises(ValueError, match="Cannot determine Pulp content base URL"):
                get_pulp_content_base_url(temp_path)
        finally:
            os.unlink(temp_path)

    def test_get_pulp_content_base_url_missing_keys(self):
        """Test get_pulp_content_base_url function with missing config keys."""
        from pulp_tool.utils import get_pulp_content_base_url

        with pytest.raises(ValueError, match="Cannot determine Pulp content base URL"):
            get_pulp_content_base_url("/path/to/config.toml")


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_sanitize_build_id_edge_cases(self):
        """Test sanitize_build_id_for_repository function with edge cases."""
        from pulp_tool.utils import sanitize_build_id_for_repository

        # Test None
        assert sanitize_build_id_for_repository(None) == "default-build"

        # Test empty string
        assert sanitize_build_id_for_repository("") == "default-build"

        # Test only invalid characters
        assert sanitize_build_id_for_repository("///") == "default-build"

        # Test very long string - should be truncated
        long_string = "a" * 1000
        result = sanitize_build_id_for_repository(long_string)
        assert len(result) <= len(long_string)  # Should be same length or shorter
        assert result != "default-build"

    def test_create_labels_edge_cases(self):
        """Test create_labels function with edge cases."""
        from pulp_tool.utils import create_labels

        # Test with empty strings
        labels = create_labels("", "", "", "", "")
        assert labels["build_id"] == ""
        assert labels["arch"] == ""
        assert labels["namespace"] == ""
        assert labels["parent_package"] == ""
        assert labels["date"] == ""

        # Test with special characters
        labels = create_labels("test/build:123", "x86_64", "test-namespace", "test-package", "2024-01-01")
        assert labels["build_id"] == "test/build:123"

    def test_chunked_get_edge_cases(self, mock_config, httpx_mock):
        """Test _chunked_get method with edge cases."""
        client = PulpClient(mock_config)

        # Mock response for all requests
        httpx_mock.get("https://test.com/api").mock(return_value=httpx.Response(200, json={"results": []}))

        # Test with empty params
        response = client._chunked_get("https://test.com/api", {})
        assert response.status_code == 200
        assert response.json()["results"] == []

        # Test with None params
        response = client._chunked_get("https://test.com/api", None)
        assert response.status_code == 200
        assert response.json()["results"] == []

        # Test with chunk_param not in params
        params = {"other_param": "value"}
        response = client._chunked_get("https://test.com/api", params, chunk_param="missing_param")
        assert response.status_code == 200
        assert response.json()["results"] == []

        # Test with non-string param value
        params = {"chunk_param": 123}
        response = client._chunked_get("https://test.com/api", params, chunk_param="chunk_param")
        assert response.status_code == 200
        assert response.json()["results"] == []

        # Test with string without commas
        params = {"chunk_param": "single_value"}
        response = client._chunked_get("https://test.com/api", params, chunk_param="chunk_param")
        assert response.status_code == 200
        assert response.json()["results"] == []

    def test_wait_for_finished_task_edge_cases(self, mock_config, httpx_mock):
        """Test wait_for_finished_task method with edge cases."""
        client = PulpClient(mock_config)

        # Test with immediate completion
        httpx_mock.get("https://pulp.example.com/pulp/api/v3/tasks/12345/").mock(
            return_value=httpx.Response(200, json={"pulp_href": "/pulp/api/v3/tasks/12345/", "state": "completed"})
        )

        with patch("time.sleep"):
            result = client.wait_for_finished_task("/pulp/api/v3/tasks/12345/", timeout=1)

        # Now returns a TaskResponse model
        from pulp_tool.models.pulp_api import TaskResponse

        assert isinstance(result, TaskResponse)
        assert result.state == "completed"

        # Test with failed state
        httpx_mock.get("https://pulp.example.com/pulp/api/v3/tasks/12345/").mock(
            return_value=httpx.Response(200, json={"pulp_href": "/pulp/api/v3/tasks/12345/", "state": "failed"})
        )

        with patch("time.sleep"):
            result = client.wait_for_finished_task("/pulp/api/v3/tasks/12345/")

        # Now returns a TaskResponse model
        assert isinstance(result, TaskResponse)
        assert result.state == "failed"

    def test_gather_content_data_edge_cases(self, mock_config, httpx_mock):
        """Test gather_content_data method with edge cases."""
        client = PulpClient(mock_config)

        # Test with empty results
        httpx_mock.get(
            "https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/?pulp_label_select=build_id~test-build-123"
        ).mock(return_value=httpx.Response(200, json={"results": []}, headers={"content-type": "application/json"}))

        content_data = client.gather_content_data("test-build-123")

        assert content_data.content_results == []
        assert content_data.artifacts == []

        # Test with None extra_artifacts
        httpx_mock.get(
            "https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/?pulp_label_select=build_id~test-build-123"
        ).mock(return_value=httpx.Response(200, json={"results": []}, headers={"content-type": "application/json"}))

        content_data = client.gather_content_data("test-build-123", None)

        assert content_data.content_results == []
        assert content_data.artifacts == []

    def test_build_results_structure_edge_cases(self, mock_config):
        """Test build_results_structure method with edge cases."""
        from pulp_tool.models import PulpResultsModel, RepositoryRefs

        client = PulpClient(mock_config)

        # Create results model for testing
        repositories = RepositoryRefs(
            rpms_href="/rpms/",
            rpms_prn="rpms-prn",
            logs_href="/logs/",
            logs_prn="logs-prn",
            sbom_href="/sbom/",
            sbom_prn="sbom-prn",
            artifacts_href="/artifacts/",
            artifacts_prn="artifacts-prn",
        )

        # Test with empty content_results
        results_model = PulpResultsModel(build_id="test-build", repositories=repositories)
        result = client.build_results_structure(results_model, [], {})
        assert result.artifact_count == 0

        # Test with content_results but empty file_info_map
        results_model = PulpResultsModel(build_id="test-build", repositories=repositories)
        content_results = [{"artifacts": {"file": "/pulp/api/v3/artifacts/12345/"}}]
        result = client.build_results_structure(results_model, content_results, {})
        assert result.artifact_count == 0

        # Test with content_results missing artifacts
        results_model = PulpResultsModel(build_id="test-build", repositories=repositories)
        content_results = [{"pulp_labels": {"build_id": "test"}}]
        result = client.build_results_structure(results_model, content_results, {})
        assert result.artifact_count == 0


class TestMemoryErrorHandling:
    """Test memory-related error handling."""

    def test_upload_content_large_file(self, mock_config, httpx_mock):
        """Test upload_content method with very large file."""
        client = PulpClient(mock_config)

        # Mock the upload endpoint to raise a memory error
        httpx_mock.post("https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/file/files/").mock(
            side_effect=MemoryError("Out of memory")
        )

        # Create a large file (simulate)
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x" * (1024 * 1024))  # 1MB
            temp_path = f.name

        try:
            labels = {"build_id": "test-build"}

            with patch("pulp_tool.api.content_manager.validate_file_path"), patch(
                "pulp_tool.api.content_manager.logging"
            ) as mock_logging:

                # Simulate memory error during upload
                with pytest.raises(MemoryError):
                    client.upload_content(temp_path, labels, file_type="File")

                mock_logging.error.assert_called()
        finally:
            os.unlink(temp_path)
