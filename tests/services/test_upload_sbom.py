"""Tests for pulp_upload.py module."""

import re
from unittest.mock import Mock, mock_open, patch

import httpx
import pytest
from httpx import HTTPError

from pulp_tool.models import RepositoryRefs
from pulp_tool.models.context import UploadRpmContext
from pulp_tool.models.pulp_results import PulpResultsDocument
from pulp_tool.services.upload_service import upload_sbom


class TestUploadSbom:
    """Test upload_sbom function."""

    def test_upload_sbom_success(self, mock_pulp_client, httpx_mock) -> None:
        """Test successful SBOM upload."""
        httpx_mock.post(re.compile(".*/content/file/files/")).mock(
            return_value=httpx.Response(200, json={"task": "/api/v3/tasks/123/"})
        )
        httpx_mock.get(re.compile(".*/tasks/123/")).mock(
            return_value=httpx.Response(200, json={"pulp_href": "/pulp/api/v3/tasks/12345/", "state": "completed"})
        )
        args = Mock()
        args.sbom_path = "/tmp/test.json"
        args.build_id = "test-build"
        args.namespace = "test-namespace"
        args.parent_package = "test-package"
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
        with (
            patch("os.path.exists", return_value=True),
            patch("pulp_tool.services.upload_service.validate_file_path"),
            patch("pulp_tool.services.upload_service.create_labels", return_value={"build_id": "test-build"}),
            patch("builtins.open", mock_open(read_data="test sbom content")),
        ):
            upload_sbom(mock_pulp_client, args, "test-repo", "2024-01-01", results_model, args.sbom_path)

    def test_upload_sbom_empty_repository_prn_raises(self, mock_pulp_client) -> None:
        """SBOM upload requires a non-empty repository PRN."""
        args = Mock()
        args.build_id = "test-build"
        args.namespace = "test-namespace"
        args.parent_package = "test-package"
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
        with patch("os.path.exists", return_value=True), patch("pulp_tool.services.upload_service.validate_file_path"):
            with pytest.raises(ValueError, match="SBOM repository PRN is empty"):
                upload_sbom(mock_pulp_client, args, "", "2024-01-01", results_model, "/tmp/x.json")

    def test_upload_sbom_no_signed_by_label(self, mock_pulp_client) -> None:
        """Test upload_sbom does not add signed_by (SBOMs are never signed)."""
        mock_resp = Mock()
        mock_resp.json.return_value = {"task": "/api/v3/tasks/123/"}
        mock_task = Mock()
        mock_task.created_resources = ["/content/1/"]
        mock_pulp_client.create_file_content = Mock(return_value=mock_resp)
        mock_pulp_client.wait_for_finished_task = Mock(return_value=mock_task)
        mock_pulp_client.check_response = Mock()
        args = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/rpms",
            sbom_path="/tmp/sbom.json",
            signed_by="key-123",
        )
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
        with (
            patch("os.path.exists", return_value=True),
            patch("pulp_tool.services.upload_service.validate_file_path"),
            patch("builtins.open", mock_open(read_data="{}")),
        ):
            upload_sbom(mock_pulp_client, args, "sbom-prn", "2024-01-01", results_model, "/tmp/sbom.json")
        call_kw = mock_pulp_client.create_file_content.call_args[1]
        assert "signed_by" not in call_kw["pulp_label"]

    def test_upload_sbom_distribution_urls_uses_task_result_relative_path(self, mock_pulp_client) -> None:
        """When task.result has relative_path, use it for incremental results (line 168)."""
        mock_resp = Mock()
        mock_resp.json.return_value = {"task": "/api/v3/tasks/123/"}
        mock_task = Mock()
        mock_task.created_resources = ["/content/file/1/"]
        mock_task.result = {"relative_path": "publish/foo/sbom.json"}
        mock_pulp_client.create_file_content = Mock(return_value=mock_resp)
        mock_pulp_client.wait_for_finished_task = Mock(return_value=mock_task)
        mock_pulp_client.check_response = Mock()
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/rpms",
            sbom_path="/tmp/sbom.json",
        )
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
        with (
            patch("os.path.exists", return_value=True),
            patch("pulp_tool.services.upload_service.validate_file_path"),
            patch("pulp_tool.services.upload_service.create_labels", return_value={"build_id": "test-build"}),
            patch("builtins.open", mock_open(read_data="{}")),
            patch.object(mock_pulp_client, "add_uploaded_artifact_to_results_model") as mock_add,
        ):
            upload_sbom(
                mock_pulp_client,
                context,
                "sbom-prn",
                "2024-01-01",
                results_model,
                "/tmp/sbom.json",
                distribution_urls={"sbom": "https://example.com/sbom/"},
            )
        mock_add.assert_called_once()
        assert mock_add.call_args.kwargs["file_relative_path"] == "publish/foo/sbom.json"

    def test_upload_sbom_file_not_found(self, mock_pulp_client) -> None:
        """Test upload_sbom with file not found."""
        args = Mock()
        args.sbom_path = "/tmp/nonexistent.json"
        args.build_id = "test-build"
        args.namespace = "test-namespace"
        args.parent_package = "test-package"
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
        with patch("os.path.exists", return_value=False):
            with pytest.raises(FileNotFoundError, match="SBOM file not found"):
                upload_sbom(mock_pulp_client, args, "test-repo", "2024-01-01", results_model, args.sbom_path)

    def test_upload_sbom_upload_error(self, mock_pulp_client, httpx_mock) -> None:
        """Test upload_sbom with upload error."""
        httpx_mock.post(re.compile(".*/content/file/files/")).mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        args = Mock()
        args.sbom_path = "/tmp/test.json"
        args.build_id = "test-build"
        args.namespace = "test-namespace"
        args.parent_package = "test-package"
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
        with (
            patch("os.path.exists", return_value=True),
            patch("pulp_tool.services.upload_service.validate_file_path"),
            patch("pulp_tool.services.upload_service.create_labels", return_value={"build_id": "test-build"}),
            patch("builtins.open", mock_open(read_data="test sbom content")),
            pytest.raises(HTTPError),
        ):
            upload_sbom(mock_pulp_client, args, "test-repo", "2024-01-01", results_model, args.sbom_path)
