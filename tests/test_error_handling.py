"""
Tests for error handling and edge cases.

This module contains comprehensive tests for error handling,
edge cases, and exception scenarios across the pulp-tool package.
"""

import os
import tempfile
from unittest.mock import Mock, patch

import httpx
import pytest
from httpx import ConnectError, HTTPError, TimeoutException

from pulp_tool.api import OAuth2ClientCredentialsAuth, PulpClient
from pulp_tool.models.pulp_results import PulpResultsDocument
from pulp_tool.utils import PulpHelper, validate_file_path


class TestPulpClientErrorHandling:
    """Test PulpClient error handling."""

    def test_check_response_server_error(self, mock_config, httpx_mock) -> None:
        """Test _check_response method with server error."""
        client = PulpClient(mock_config)
        httpx_mock.get(
            "https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/?test_param=value1%2Cvalue2"
        ).mock(
            return_value=httpx.Response(
                500, json={"error": "Internal Server Error"}, headers={"content-type": "application/json"}
            )
        )
        with patch("pulp_tool.api.pulp_client.client.logging") as mock_logging:
            with pytest.raises(HTTPError, match="Failed to chunked request"):
                client._chunked_get(
                    "https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/",
                    {"test_param": "value1,value2,value3"},
                    chunk_param="test_param",
                    chunk_size=2,
                )
            mock_logging.error.assert_called()

    def test_check_response_client_error(self, mock_config, httpx_mock) -> None:
        """Test _check_response method with client error."""
        client = PulpClient(mock_config)
        httpx_mock.get(
            "https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/?test_param=value1%2Cvalue2"
        ).mock(return_value=httpx.Response(400, text="Bad Request", headers={}))
        with pytest.raises(HTTPError, match="Failed to chunked request"):
            client._chunked_get(
                "https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/",
                {"test_param": "value1,value2,value3"},
                chunk_param="test_param",
                chunk_size=2,
            )

    def test_upload_content_file_not_found(self, mock_config) -> None:
        """Test upload_content method with non-existent file."""
        client = PulpClient(mock_config)
        labels = {"build_id": "test-build"}
        with pytest.raises(FileNotFoundError):
            client.upload_content("/non/existent/file.rpm", labels, file_type="RPM", arch="x86_64")

    def test_upload_content_permission_error(self, mock_config) -> None:
        """Test upload_content method with permission error."""
        client = PulpClient(mock_config)
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name
        try:
            os.chmod(temp_path, 0)
            labels = {"build_id": "test-build"}
            with pytest.raises(PermissionError):
                client.upload_content(temp_path, labels, file_type="RPM", arch="x86_64")
        finally:
            os.chmod(temp_path, 420)
            os.unlink(temp_path)

    def test_upload_content_empty_file(self, mock_config) -> None:
        """Test upload_content method with empty file."""
        client = PulpClient(mock_config)
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name
        try:
            labels = {"build_id": "test-build"}
            with pytest.raises(ValueError, match="RPM file is empty"):
                client.upload_content(temp_path, labels, file_type="RPM", arch="x86_64")
        finally:
            os.unlink(temp_path)

    def test_upload_content_request_exception(self, mock_config, temp_rpm_file, httpx_mock) -> None:
        """Test upload_content method with request exception."""
        client = PulpClient(mock_config)
        httpx_mock.post("https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/rpm/packages/upload/").mock(
            side_effect=HTTPError("Network error")
        )
        labels = {"build_id": "test-build"}
        with (
            patch("pulp_tool.utils.validation.file.validate_file_path"),
            patch("pulp_tool.api.pulp_client.client.logging") as mock_logging,
        ):
            with pytest.raises(HTTPError):
                client.upload_content(temp_rpm_file, labels, file_type="RPM", arch="x86_64")
            mock_logging.error.assert_called()

    def test_wait_for_finished_task_error_response(self, mock_config, httpx_mock) -> None:
        """Test wait_for_finished_task method with HTTP error response."""
        client = PulpClient(mock_config)
        httpx_mock.get("https://pulp.example.com/pulp/api/v3/tasks/12345/").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        with patch("time.sleep"), pytest.raises(HTTPError):
            client.wait_for_finished_task("/pulp/api/v3/tasks/12345/")

    def test_chunked_get_request_exception(self, mock_config, httpx_mock) -> None:
        """Test _chunked_get method with request exception."""
        client = PulpClient(mock_config)
        httpx_mock.get("https://test.com/api").mock(side_effect=HTTPError("Network error"))
        params = {"large_param": ",".join([f"item{i}" for i in range(100)])}
        with pytest.raises(HTTPError):
            client._chunked_get("https://test.com/api", params, chunk_param="large_param", chunk_size=20)

    def test_gather_content_data_exception(self, mock_config) -> None:
        """Test gather_content_data method with exception."""
        client = PulpClient(mock_config)
        client.find_content = Mock()
        client.find_content.side_effect = HTTPError("API error")
        with patch("pulp_tool.api.pulp_client.results.logging") as mock_logging:
            with pytest.raises(HTTPError):
                client.gather_content_data("test-build-123")
            mock_logging.error.assert_called()


class TestOAuth2ErrorHandling:
    """Test OAuth2ClientCredentialsAuth error handling."""

    def test_retrieve_token_http_error(self) -> None:
        """Test _retrieve_token method with HTTP error."""
        auth = OAuth2ClientCredentialsAuth(
            client_id="test-client", client_secret="test-secret", token_url="https://test.com/token"
        )
        with patch("httpx.post", side_effect=HTTPError("401 Unauthorized")), pytest.raises(HTTPError):
            auth._retrieve_token()

    def test_retrieve_token_connection_error(self) -> None:
        """Test _retrieve_token method with connection error."""
        auth = OAuth2ClientCredentialsAuth(
            client_id="test-client", client_secret="test-secret", token_url="https://test.com/token"
        )
        with patch("httpx.post", side_effect=ConnectError("Connection failed")), pytest.raises(ConnectError):
            auth._retrieve_token()

    def test_retrieve_token_timeout(self) -> None:
        """Test _retrieve_token method with timeout."""
        auth = OAuth2ClientCredentialsAuth(
            client_id="test-client", client_secret="test-secret", token_url="https://test.com/token"
        )
        with patch("httpx.post", side_effect=TimeoutException("Request timeout")):
            with pytest.raises(TimeoutException):
                auth._retrieve_token()

    def test_retrieve_token_invalid_json(self, httpx_mock) -> None:
        """Test _retrieve_token method with invalid JSON response."""
        auth = OAuth2ClientCredentialsAuth(
            client_id="test-client", client_secret="test-secret", token_url="https://test.com/token"
        )
        httpx_mock.post("https://test.com/token").mock(
            return_value=httpx.Response(200, text="Invalid JSON response", headers={"content-type": "text/plain"})
        )
        with pytest.raises(ValueError):
            auth._retrieve_token()


class TestPulpHelperErrorHandling:
    """Test PulpHelper error handling."""

    def test_setup_repositories_invalid_build_id(self, mock_pulp_client) -> None:
        """Test setup_repositories method with invalid build ID."""
        helper = PulpHelper(mock_pulp_client)
        with pytest.raises(ValueError, match="Invalid build ID"):
            helper.setup_repositories("")

    def test_setup_repositories_validation_failure(self, mock_pulp_client) -> None:
        """Test setup_repositories method with validation failure."""
        helper = PulpHelper(mock_pulp_client)
        with (
            patch.object(helper._repository_manager, "_setup_repositories_impl", return_value={}),
            patch("pulp_tool.utils.validation.validate_repository_setup", return_value=(False, ["Missing repo"])),
        ):
            with pytest.raises(RuntimeError, match="Repository setup validation failed"):
                helper.setup_repositories("test-build-123")

    def test_create_or_get_repository_invalid_type(self, mock_pulp_client) -> None:
        """Test create_or_get_repository method with invalid repository type."""
        helper = PulpHelper(mock_pulp_client)
        with pytest.raises(ValueError, match="Invalid repository or API type"):
            helper.create_or_get_repository("test-build-123", "invalid")

    def test_create_or_get_repository_invalid_build_id(self, mock_pulp_client) -> None:
        """Test create_or_get_repository method with invalid build ID."""
        helper = PulpHelper(mock_pulp_client)
        with pytest.raises(ValueError, match="Invalid build ID"):
            helper.create_or_get_repository("", "rpms")

    def test_get_distribution_urls_invalid_build_id(self, mock_pulp_client) -> None:
        """Test get_distribution_urls method with invalid build ID."""
        helper = PulpHelper(mock_pulp_client)
        with pytest.raises(ValueError, match="Invalid build ID"):
            helper.get_distribution_urls("")

    def test_get_distribution_urls_config_error(self, mock_pulp_client) -> None:
        """Test get_distribution_urls method with missing base_url in config."""
        helper = PulpHelper(mock_pulp_client)
        with patch.dict(mock_pulp_client.config, {}, clear=True), pytest.raises(KeyError):
            helper.get_distribution_urls("test-build-123")


class TestUtilityErrorHandling:
    """Test utility function error handling."""

    def test_validate_file_path_not_found(self) -> None:
        """Test validate_file_path function with non-existent file."""
        with pytest.raises(FileNotFoundError, match="Test file not found"):
            validate_file_path("/non/existent/file.txt", "Test")

    def test_validate_file_path_permission_error(self) -> None:
        """Test validate_file_path function with permission error."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name
        try:
            os.chmod(temp_path, 0)
            with pytest.raises(PermissionError, match="Cannot read Test file"):
                validate_file_path(temp_path, "Test")
        finally:
            os.chmod(temp_path, 420)
            os.unlink(temp_path)

    def test_validate_file_path_empty_file(self) -> None:
        """Test validate_file_path function with empty file."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name
        try:
            with pytest.raises(ValueError, match="Test file is empty"):
                validate_file_path(temp_path, "Test")
        finally:
            os.unlink(temp_path)


class TestConfigErrorHandling:
    """Test configuration error handling."""

    def test_get_pulp_content_base_url_file_not_found(self) -> None:
        """Test get_pulp_content_base_url function with non-existent file."""
        from pulp_tool.utils import get_pulp_content_base_url

        with pytest.raises(ValueError, match="Cannot determine Pulp content base URL"):
            get_pulp_content_base_url("/non/existent/config.toml")

    def test_get_pulp_content_base_url_invalid_config(self) -> None:
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

    def test_get_pulp_content_base_url_missing_keys(self) -> None:
        """Test get_pulp_content_base_url function with missing config keys."""
        from pulp_tool.utils import get_pulp_content_base_url

        with pytest.raises(ValueError, match="Cannot determine Pulp content base URL"):
            get_pulp_content_base_url("/path/to/config.toml")


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_sanitize_build_id_edge_cases(self) -> None:
        """Test sanitize_build_id_for_repository function with edge cases."""
        from pulp_tool.utils import sanitize_build_id_for_repository

        assert sanitize_build_id_for_repository(None) == "default-build"
        assert sanitize_build_id_for_repository("") == "default-build"
        assert sanitize_build_id_for_repository("///") == "default-build"
        long_string = "a" * 1000
        result = sanitize_build_id_for_repository(long_string)
        assert len(result) <= len(long_string)
        assert result != "default-build"

    def test_create_labels_edge_cases(self) -> None:
        """Test create_labels function with edge cases."""
        from pulp_tool.utils import create_labels

        labels = create_labels("", "", "", "", "")
        assert labels["build_id"] == ""
        assert labels["arch"] == ""
        assert labels["namespace"] == ""
        assert labels["date"] == ""
        assert "parent_package" not in labels
        labels = create_labels("", "", "", None, "")
        assert labels["build_id"] == ""
        assert labels["arch"] == ""
        assert labels["namespace"] == ""
        assert labels["date"] == ""
        assert "parent_package" not in labels
        labels = create_labels("", "", "", "test-package", "")
        assert labels["build_id"] == ""
        assert labels["arch"] == ""
        assert labels["namespace"] == ""
        assert labels["date"] == ""
        assert labels["parent_package"] == "test-package"
        labels = create_labels("test/build:123", "x86_64", "test-namespace", "test-package", "2024-01-01")
        assert labels["build_id"] == "test/build:123"

    def test_chunked_get_edge_cases(self, mock_config, httpx_mock) -> None:
        """Test _chunked_get method with edge cases."""
        client = PulpClient(mock_config)
        httpx_mock.get("https://test.com/api").mock(return_value=httpx.Response(200, json={"results": []}))
        response = client._chunked_get("https://test.com/api", {})
        assert response.status_code == 200
        assert response.json()["results"] == []
        response = client._chunked_get("https://test.com/api", None)
        assert response.status_code == 200
        assert response.json()["results"] == []
        params = {"other_param": "value"}
        response = client._chunked_get("https://test.com/api", params, chunk_param="missing_param")
        assert response.status_code == 200
        assert response.json()["results"] == []
        non_string_params: dict[str, int] = {"chunk_param": 123}
        response = client._chunked_get("https://test.com/api", non_string_params, chunk_param="chunk_param")
        assert response.status_code == 200
        assert response.json()["results"] == []
        params = {"chunk_param": "single_value"}
        response = client._chunked_get("https://test.com/api", params, chunk_param="chunk_param")
        assert response.status_code == 200
        assert response.json()["results"] == []

    def test_wait_for_finished_task_edge_cases(self, mock_config, httpx_mock) -> None:
        """Test wait_for_finished_task method with edge cases."""
        client = PulpClient(mock_config)
        httpx_mock.get("https://pulp.example.com/pulp/api/v3/tasks/12345/").mock(
            return_value=httpx.Response(200, json={"pulp_href": "/pulp/api/v3/tasks/12345/", "state": "completed"})
        )
        with patch("time.sleep"):
            result = client.wait_for_finished_task("/pulp/api/v3/tasks/12345/", timeout=1)
        from pulp_tool.models.pulp_api import TaskResponse

        assert isinstance(result, TaskResponse)
        assert result.state == "completed"
        httpx_mock.get("https://pulp.example.com/pulp/api/v3/tasks/12345/").mock(
            return_value=httpx.Response(200, json={"pulp_href": "/pulp/api/v3/tasks/12345/", "state": "failed"})
        )
        with patch("time.sleep"):
            result = client.wait_for_finished_task("/pulp/api/v3/tasks/12345/")
        assert isinstance(result, TaskResponse)
        assert result.state == "failed"

    def test_gather_content_data_edge_cases(self, mock_config, httpx_mock) -> None:
        """Test gather_content_data method with edge cases."""
        client = PulpClient(mock_config)
        httpx_mock.get(
            "https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/?pulp_label_select=build_id~test-build-123"
        ).mock(return_value=httpx.Response(200, json={"results": []}, headers={"content-type": "application/json"}))
        content_data = client.gather_content_data("test-build-123")
        assert content_data.content_results == []
        assert content_data.artifacts == []
        httpx_mock.get(
            "https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/?pulp_label_select=build_id~test-build-123"
        ).mock(return_value=httpx.Response(200, json={"results": []}, headers={"content-type": "application/json"}))
        content_data = client.gather_content_data("test-build-123", None)
        assert content_data.content_results == []
        assert content_data.artifacts == []

    def test_build_results_structure_edge_cases(self, mock_config) -> None:
        """Test build_results_structure method with edge cases."""
        from pulp_tool.models import RepositoryRefs
        from pulp_tool.models.artifacts import PulpContentRow

        client = PulpClient(mock_config)
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
        results_model = PulpResultsDocument(build_id="test-build", repositories=repositories)
        result = client.build_results_structure(results_model, [], {})
        assert result.artifact_count == 0
        results_model = PulpResultsDocument(build_id="test-build", repositories=repositories)
        content_results = [PulpContentRow.model_validate({"artifacts": {"file": "/pulp/api/v3/artifacts/12345/"}})]
        result = client.build_results_structure(results_model, content_results, {})
        assert result.artifact_count == 0
        results_model = PulpResultsDocument(build_id="test-build", repositories=repositories)
        content_results = [PulpContentRow.model_validate({"pulp_labels": {"build_id": "test"}})]
        result = client.build_results_structure(results_model, content_results, {})
        assert result.artifact_count == 0


class TestMemoryErrorHandling:
    """Test memory-related error handling."""

    def test_upload_content_large_file(self, mock_config, httpx_mock) -> None:
        """Test upload_content method with very large file."""
        client = PulpClient(mock_config)
        httpx_mock.post("https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/file/files/").mock(
            side_effect=MemoryError("Out of memory")
        )
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x" * (1024 * 1024))
            temp_path = f.name
        try:
            labels = {"build_id": "test-build"}
            with (
                patch("pulp_tool.utils.validation.file.validate_file_path"),
                patch("pulp_tool.api.pulp_client.client.logging") as mock_logging,
            ):
                with pytest.raises(MemoryError):
                    client.upload_content(temp_path, labels, file_type="File")
                mock_logging.error.assert_called()
        finally:
            os.unlink(temp_path)
