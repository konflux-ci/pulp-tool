"""
Tests for upload utilities.

This module tests upload operations including label creation,
log uploads, and artifact uploads to repositories.
"""

import os
from unittest.mock import Mock, patch

import pytest
from httpx import HTTPError

from pulp_tool.utils import create_labels, upload_artifacts_to_repository, upload_log


class TestLabelUtilities:
    """Test label utility functions."""

    def test_create_labels(self) -> None:
        """Test create_labels function."""
        labels = create_labels(
            build_id="test-build-123",
            arch="x86_64",
            namespace="test-namespace",
            parent_package="test-package",
            date="2024-01-01 12:00:00",
        )
        expected = {
            "date": "2024-01-01 12:00:00",
            "build_id": "test-build-123",
            "arch": "x86_64",
            "namespace": "test-namespace",
            "parent_package": "test-package",
        }
        assert labels == expected

    def test_create_labels_without_parent_package(self) -> None:
        """Test create_labels function without parent_package."""
        labels = create_labels(
            build_id="test-build-123",
            arch="x86_64",
            namespace="test-namespace",
            parent_package=None,
            date="2024-01-01 12:00:00",
        )
        expected = {
            "date": "2024-01-01 12:00:00",
            "build_id": "test-build-123",
            "arch": "x86_64",
            "namespace": "test-namespace",
        }
        assert labels == expected
        assert "parent_package" not in labels


class TestUploadUtilities:
    """Test upload utility functions."""

    def test_upload_log(self, mock_pulp_client, temp_file) -> None:
        """Test upload_log function."""
        mock_response = Mock()
        mock_response.json.return_value = {"task": "/pulp/api/v3/tasks/12345/"}
        mock_task_response = Mock()
        mock_task_response.created_resources = ["/content/file/1/"]
        mock_pulp_client.create_file_content = Mock()
        mock_pulp_client.create_file_content.return_value = mock_response
        mock_pulp_client.wait_for_finished_task = Mock()
        mock_pulp_client.wait_for_finished_task.return_value = mock_task_response
        labels = {"build_id": "test-build", "arch": "x86_64"}
        created_resources = upload_log(
            mock_pulp_client, "test-repo", temp_file, build_id="test-build", labels=labels, arch="x86_64"
        )
        mock_pulp_client.create_file_content.assert_called_once()
        mock_pulp_client.wait_for_finished_task.assert_called_once()
        assert created_resources == ["/content/file/1/"]

    def test_upload_log_empty_repository_prn_raises(self, mock_pulp_client, temp_file) -> None:
        """upload_log requires a non-empty file repository PRN."""
        with pytest.raises(ValueError, match="logs repository PRN"):
            upload_log(
                mock_pulp_client, "", temp_file, build_id="test-build", labels={"build_id": "test-build"}, arch="x86_64"
            )

    def test_upload_log_incremental_uses_task_relative_path(self, mock_pulp_client, temp_file) -> None:
        """results_model + distribution_urls: relative_path from task.result when dict."""
        from pulp_tool.models.pulp_results import PulpResultsDocument
        from pulp_tool.models.repository import RepositoryRefs

        mock_response = Mock()
        mock_response.json.return_value = {"task": "/pulp/api/v3/tasks/1/"}
        mock_task = Mock()
        mock_task.created_resources = ["/content/file/2/"]
        mock_task.result = {"relative_path": "logs/x86_64/out/build.log"}
        mock_pulp_client.create_file_content = Mock(return_value=mock_response)
        mock_pulp_client.wait_for_finished_task = Mock(return_value=mock_task)
        mock_pulp_client.check_response = Mock()
        repos = RepositoryRefs(
            rpms_href="/r",
            rpms_prn="",
            logs_href="/l",
            logs_prn="",
            sbom_href="/s",
            sbom_prn="",
            artifacts_href="/a",
            artifacts_prn="",
        )
        results_model = PulpResultsDocument(build_id="test-build", repositories=repos)
        labels = {"build_id": "test-build", "arch": "x86_64"}
        with patch.object(mock_pulp_client, "add_uploaded_artifact_to_results_model") as mock_add:
            upload_log(
                mock_pulp_client,
                "logs-prn",
                temp_file,
                build_id="test-build",
                labels=labels,
                arch="x86_64",
                results_model=results_model,
                distribution_urls={"logs": "https://example.com/logs/"},
            )
        mock_add.assert_called_once()
        assert mock_add.call_args.kwargs["file_relative_path"] == "logs/x86_64/out/build.log"

    def test_upload_log_incremental_falls_back_arch_basename(self, mock_pulp_client, temp_file) -> None:
        """When task.result has no relative_path, use arch/basename."""
        from pulp_tool.models.pulp_results import PulpResultsDocument
        from pulp_tool.models.repository import RepositoryRefs

        mock_response = Mock()
        mock_response.json.return_value = {"task": "/pulp/api/v3/tasks/1/"}
        mock_task = Mock()
        mock_task.created_resources = []
        mock_task.result = None
        mock_pulp_client.create_file_content = Mock(return_value=mock_response)
        mock_pulp_client.wait_for_finished_task = Mock(return_value=mock_task)
        mock_pulp_client.check_response = Mock()
        repos = RepositoryRefs(
            rpms_href="/r",
            rpms_prn="",
            logs_href="/l",
            logs_prn="",
            sbom_href="/s",
            sbom_prn="",
            artifacts_href="/a",
            artifacts_prn="",
        )
        results_model = PulpResultsDocument(build_id="test-build", repositories=repos)
        labels = {"build_id": "test-build", "arch": "s390x"}
        with patch.object(mock_pulp_client, "add_uploaded_artifact_to_results_model") as mock_add:
            upload_log(
                mock_pulp_client,
                "logs-prn",
                temp_file,
                build_id="test-build",
                labels=labels,
                arch="s390x",
                results_model=results_model,
                distribution_urls={"logs": "https://example.com/logs/"},
            )
        mock_add.assert_called_once()
        assert mock_add.call_args.kwargs["file_relative_path"] == f"s390x/{os.path.basename(temp_file)}"

    def test_upload_artifacts_to_repository(self, mock_pulp_client, mock_pulled_artifacts) -> None:
        """Test upload_artifacts_to_repository function."""
        mock_response = Mock()
        mock_response.json.return_value = {"task": "/pulp/api/v3/tasks/12345/"}
        mock_pulp_client.create_file_content = Mock()
        mock_pulp_client.create_file_content.return_value = mock_response
        mock_pulp_client.wait_for_finished_task = Mock()
        mock_pulp_client.wait_for_finished_task.return_value = mock_response
        upload_count, errors = upload_artifacts_to_repository(
            mock_pulp_client, mock_pulled_artifacts.rpms, "test-repo", "RPM"
        )
        assert upload_count == 1
        assert len(errors) == 0
        mock_pulp_client.create_file_content.assert_called_once()

    def test_upload_artifacts_to_repository_error(self, mock_pulp_client) -> None:
        """Test upload_artifacts_to_repository function with error."""
        mock_pulp_client.create_file_content = Mock()
        mock_pulp_client.create_file_content.side_effect = HTTPError("Upload failed")
        artifacts = {"test-file": {"file": "/path/to/file", "pulp_labels": {"build_id": "test-build"}}}
        upload_count, errors = upload_artifacts_to_repository(mock_pulp_client, artifacts, "test-repo", "File")
        assert upload_count == 0
        assert len(errors) == 1
        assert "Upload failed" in errors[0]

    def test_upload_artifacts_immediate_success(self, mock_pulp_client) -> None:
        """Test upload_artifacts_to_repository with immediate success."""
        mock_response = Mock()
        mock_response.json.return_value = {"status": "success"}
        mock_pulp_client.create_file_content = Mock()
        mock_pulp_client.create_file_content.return_value = mock_response
        artifacts = {"test-file": {"file": "/path/to/file", "pulp_labels": {"build_id": "test-build"}}}
        upload_count, errors = upload_artifacts_to_repository(mock_pulp_client, artifacts, "test-repo", "File")
        assert upload_count == 1
        assert len(errors) == 0
