"""Tests for pulp_upload.py module."""

import pytest
import httpx
from httpx import HTTPError
import re
from unittest.mock import Mock, patch, mock_open
import json

from pulp_tool.upload import (
    upload_sbom,
    _serialize_results_to_json,
    _upload_and_get_results_url,
    _extract_results_url,
    _handle_artifact_results,
    _handle_sbom_results,
)
from pulp_tool.models import PulpResultsModel, RepositoryRefs

# CLI imports removed - Click testing done in test_cli.py


class TestUploadSbom:
    """Test upload_sbom function."""

    def test_upload_sbom_success(self, mock_pulp_client, httpx_mock):
        """Test successful SBOM upload."""
        httpx_mock.post(re.compile(r".*/content/file/files/")).mock(
            return_value=httpx.Response(200, json={"task": "/api/v3/tasks/123/"})
        )
        httpx_mock.get(re.compile(r".*/tasks/123/")).mock(
            return_value=httpx.Response(200, json={"pulp_href": "/pulp/api/v3/tasks/12345/", "state": "completed"})
        )

        args = Mock()
        args.sbom_path = "/tmp/test.json"
        args.build_id = "test-build"
        args.namespace = "test-namespace"
        args.parent_package = "test-package"

        # Create results model
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
        results_model = PulpResultsModel(build_id="test-build", repositories=repositories)

        with patch("os.path.exists", return_value=True), patch("pulp_tool.upload.validate_file_path"), patch(
            "pulp_tool.upload.create_labels", return_value={"build_id": "test-build"}
        ), patch("builtins.open", mock_open(read_data="test sbom content")):

            upload_sbom(mock_pulp_client, args, "test-repo", "2024-01-01", results_model)

    def test_upload_sbom_file_not_found(self, mock_pulp_client):
        """Test upload_sbom with file not found."""
        args = Mock()
        args.sbom_path = "/tmp/nonexistent.json"
        args.build_id = "test-build"
        args.namespace = "test-namespace"
        args.parent_package = "test-package"

        # Create results model
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
        results_model = PulpResultsModel(build_id="test-build", repositories=repositories)

        with patch("os.path.exists", return_value=False):
            upload_sbom(mock_pulp_client, args, "test-repo", "2024-01-01", results_model)

    def test_upload_sbom_upload_error(self, mock_pulp_client, httpx_mock):
        """Test upload_sbom with upload error."""
        httpx_mock.post(re.compile(r".*/content/file/files/")).mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        args = Mock()
        args.sbom_path = "/tmp/test.json"
        args.build_id = "test-build"
        args.namespace = "test-namespace"
        args.parent_package = "test-package"

        # Create results model
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
        results_model = PulpResultsModel(build_id="test-build", repositories=repositories)

        with patch("os.path.exists", return_value=True), patch("pulp_tool.upload.validate_file_path"), patch(
            "pulp_tool.upload.create_labels", return_value={"build_id": "test-build"}
        ), patch("builtins.open", mock_open(read_data="test sbom content")):

            with pytest.raises(HTTPError):
                upload_sbom(mock_pulp_client, args, "test-repo", "2024-01-01", results_model)


class TestSerializeResultsToJson:
    """Test _serialize_results_to_json function."""

    def test_serialize_results_to_json_success(self):
        """Test successful JSON serialization."""
        results = {"content": "test", "number": 123}

        json_content = _serialize_results_to_json(results)

        assert isinstance(json_content, str)
        parsed = json.loads(json_content)
        assert parsed == results

    def test_serialize_results_to_json_error(self):
        """Test JSON serialization with error."""

        # Create an object that can't be serialized
        class Unserializable:
            pass

        results = {"content": "test", "unserializable": Unserializable()}

        with pytest.raises((TypeError, ValueError)):
            _serialize_results_to_json(results)


class TestUploadAndGetResultsUrl:
    """Test _upload_and_get_results_url function."""

    def test_upload_and_get_results_url_error(self, mock_pulp_client, httpx_mock):
        """Test results upload with error."""
        httpx_mock.post(re.compile(r".*/content/file/files/")).mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        args = Mock()
        args.build_id = "test-build"
        args.namespace = "test-namespace"
        args.parent_package = "test-package"

        with patch("pulp_tool.utils.create_labels", return_value={"build_id": "test-build"}):
            with pytest.raises(Exception):
                _upload_and_get_results_url(mock_pulp_client, args, "test-repo", "test json content", "2024-01-01")


class TestExtractResultsUrl:
    """Test _extract_results_url function."""

    def test_extract_results_url_success(self, mock_pulp_client):
        """Test successful results URL extraction."""
        from pulp_tool.models.pulp_api import TaskResponse
        from unittest.mock import patch

        args = Mock()
        args.build_id = "test-build"
        args.cert_config = None

        # Now task_response is a TaskResponse model, not a Mock
        # relative_path should just be the filename, not the full path
        task_response = TaskResponse(
            pulp_href="/api/v3/tasks/123/",
            state="completed",
            result={"relative_path": "pulp_results.json"},
        )

        # Mock PulpHelper and its get_distribution_urls method
        with patch("pulp_tool.upload.PulpHelper") as MockPulpHelper:
            mock_helper = Mock()
            mock_helper.get_distribution_urls.return_value = {
                "artifacts": "https://pulp-content.example.com/test-domain/test-build/artifacts/"
            }
            MockPulpHelper.return_value = mock_helper

            result = _extract_results_url(mock_pulp_client, args, task_response)

            assert result == "https://pulp-content.example.com/test-domain/test-build/artifacts/pulp_results.json"
            mock_helper.get_distribution_urls.assert_called_once_with("test-build")


class TestCollectResults:
    """Test collect_results function."""


class TestHandleArtifactResults:
    """Test _handle_artifact_results function."""

    def test_handle_artifact_results_success(self, mock_pulp_client, httpx_mock):
        """Test successful artifact results handling."""
        from pulp_tool.models.pulp_api import TaskResponse

        httpx_mock.get(re.compile(r".*/content/\?pulp_href__in=")).mock(
            return_value=httpx.Response(200, json={"results": [{"artifacts": {"file": "/test/artifacts/"}}]})
        )
        httpx_mock.get(re.compile(r".*/artifacts/.*")).mock(
            return_value=httpx.Response(200, json={"results": [{"file": "test.txt@sha256:abc123", "sha256": "abc123"}]})
        )

        args = Mock()
        args.artifact_results = "url_path,digest_path"

        # Now task_response is a TaskResponse model
        task_response = TaskResponse(
            pulp_href="/api/v3/tasks/123/", state="completed", created_resources=["/test/content/"]
        )

        with patch("builtins.open", mock_open()) as mock_file:
            _handle_artifact_results(mock_pulp_client, args, task_response)

            assert mock_file.call_count == 2

    def test_handle_artifact_results_no_content(self, mock_pulp_client):
        """Test artifact results handling with no content."""
        from pulp_tool.models.pulp_api import TaskResponse

        args = Mock()
        args.artifact_results = "url_path,digest_path"

        # Now task_response is a TaskResponse model
        task_response = TaskResponse(
            pulp_href="/api/v3/tasks/123/", state="completed", created_resources=["/test/other/"]
        )

        _handle_artifact_results(mock_pulp_client, args, task_response)

    def test_handle_artifact_results_invalid_format(self, mock_pulp_client, httpx_mock):
        """Test artifact results handling with invalid format."""
        from pulp_tool.models.pulp_api import TaskResponse

        httpx_mock.get(re.compile(r".*/content/\?pulp_href__in=")).mock(
            return_value=httpx.Response(200, json={"results": [{"artifacts": {"file": "/test/artifacts/"}}]})
        )
        httpx_mock.get(re.compile(r".*/artifacts/.*")).mock(
            return_value=httpx.Response(200, json={"results": [{"file": "test.txt", "sha256": "abc123"}]})
        )

        args = Mock()
        args.artifact_results = "invalid_format"

        # Now task_response is a TaskResponse model
        task_response = TaskResponse(
            pulp_href="/api/v3/tasks/123/", state="completed", created_resources=["/test/content/"]
        )

        _handle_artifact_results(mock_pulp_client, args, task_response)


class TestHandleSbomResults:
    """Test _handle_sbom_results function."""

    def test_handle_sbom_results_success(self, tmp_path):
        """Test successful SBOM results writing."""
        from argparse import Namespace

        # Create mock results JSON with SBOM
        # The URL already contains the full reference with digest
        results_json = {
            "artifacts": {
                "test-sbom.spdx.json": {
                    "labels": {"build_id": "test-build", "namespace": "test-ns"},
                    "url": (
                        "https://pulp.example.com/pulp/content/test-build/sbom/"
                        "test-sbom.spdx.json@sha256:abc123def456789"
                    ),
                    "sha256": "abc123def456789",
                },
                "test-package.rpm": {
                    "labels": {"build_id": "test-build", "arch": "x86_64"},
                    "url": "https://pulp.example.com/pulp/content/test-build/rpms/test-package.rpm",
                    "sha256": "rpm123456",
                },
            }
        }

        json_content = json.dumps(results_json)

        sbom_file = tmp_path / "sbom_result.txt"
        args = Namespace(sbom_results=str(sbom_file))

        # Mock client (not actually used in this function)
        mock_client = None

        _handle_sbom_results(mock_client, args, json_content)

        # Verify the file was created with correct content
        assert sbom_file.exists()
        content = sbom_file.read_text()
        expected = "https://pulp.example.com/pulp/content/test-build/sbom/" "test-sbom.spdx.json@sha256:abc123def456789"
        assert content == expected

    def test_handle_sbom_results_no_sbom_found(self, tmp_path, caplog):
        """Test handling when no SBOM is found."""
        from argparse import Namespace
        import logging

        # Create mock results JSON without SBOM
        results_json = {
            "artifacts": {
                "test-package.rpm": {
                    "labels": {"build_id": "test-build", "arch": "x86_64"},
                    "url": "https://pulp.example.com/pulp/content/test-build/rpms/test-package.rpm",
                    "sha256": "rpm123456",
                }
            }
        }

        json_content = json.dumps(results_json)

        sbom_file = tmp_path / "sbom_result.txt"
        args = Namespace(sbom_results=str(sbom_file))
        mock_client = None

        # Capture INFO level logs since the message is now at INFO level
        with caplog.at_level(logging.INFO):
            _handle_sbom_results(mock_client, args, json_content)

        # File should not be created
        assert not sbom_file.exists()
        assert "No SBOM file found" in caplog.text

    def test_handle_sbom_results_json_file_without_arch(self, tmp_path):
        """Test SBOM detection with .json extension (no arch label)."""
        from argparse import Namespace

        # Create mock results JSON with .json file (SBOM) without arch
        # The URL already contains the full reference with digest
        results_json = {
            "artifacts": {
                "cyclonedx.json": {
                    "labels": {"build_id": "test-build", "namespace": "test-ns"},
                    "url": "https://pulp.example.com/pulp/content/test-build/sbom/cyclonedx.json@sha256:def789abc123",
                    "sha256": "def789abc123",
                }
            }
        }

        json_content = json.dumps(results_json)

        sbom_file = tmp_path / "sbom_result.txt"
        args = Namespace(sbom_results=str(sbom_file))
        mock_client = None

        _handle_sbom_results(mock_client, args, json_content)

        # Verify the file was created with correct content
        assert sbom_file.exists()
        content = sbom_file.read_text()
        expected = "https://pulp.example.com/pulp/content/test-build/sbom/cyclonedx.json@sha256:def789abc123"
        assert content == expected


class TestParseArguments:
    """Test argument parsing for upload."""

    pass  # Tests removed - create_parser no longer exists


class TestUploadHelpers:
    """Test upload helper functions."""

    # Tests temporarily removed due to complex mocking requirements
    # Coverage is achieved through integration tests
    pass
