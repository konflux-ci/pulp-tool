"""
Tests for upload utilities.

This module tests upload operations including label creation,
log uploads, and artifact uploads to repositories.
"""

from unittest.mock import Mock
from httpx import HTTPError

from pulp_tool.utils import (
    create_labels,
    upload_log,
    upload_artifacts_to_repository,
)


class TestLabelUtilities:
    """Test label utility functions."""

    def test_create_labels(self):
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


class TestUploadUtilities:
    """Test upload utility functions."""

    def test_upload_log(self, mock_pulp_client, temp_file):
        """Test upload_log function."""
        mock_response = Mock()
        mock_response.json.return_value = {"task": "/pulp/api/v3/tasks/12345/"}

        mock_pulp_client.create_file_content = Mock()
        mock_pulp_client.create_file_content.return_value = mock_response
        mock_pulp_client.wait_for_finished_task = Mock()
        mock_pulp_client.wait_for_finished_task.return_value = mock_response

        labels = {"build_id": "test-build", "arch": "x86_64"}

        upload_log(mock_pulp_client, "test-repo", temp_file, build_id="test-build", labels=labels, arch="x86_64")

        mock_pulp_client.create_file_content.assert_called_once()
        mock_pulp_client.wait_for_finished_task.assert_called_once()

    def test_upload_artifacts_to_repository(self, mock_pulp_client, mock_pulled_artifacts):
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

    def test_upload_artifacts_to_repository_error(self, mock_pulp_client):
        """Test upload_artifacts_to_repository function with error."""
        mock_pulp_client.create_file_content = Mock()
        mock_pulp_client.create_file_content.side_effect = HTTPError("Upload failed")

        artifacts = {"test-file": {"file": "/path/to/file", "labels": {"build_id": "test-build"}}}

        upload_count, errors = upload_artifacts_to_repository(mock_pulp_client, artifacts, "test-repo", "File")

        assert upload_count == 0
        assert len(errors) == 1
        assert "Upload failed" in errors[0]

    def test_upload_artifacts_immediate_success(self, mock_pulp_client):
        """Test upload_artifacts_to_repository with immediate success."""
        mock_response = Mock()
        # Response without a 'task' key indicates immediate success
        mock_response.json.return_value = {"status": "success"}

        mock_pulp_client.create_file_content = Mock()
        mock_pulp_client.create_file_content.return_value = mock_response

        artifacts = {"test-file": {"file": "/path/to/file", "labels": {"build_id": "test-build"}}}

        upload_count, errors = upload_artifacts_to_repository(mock_pulp_client, artifacts, "test-repo", "File")

        assert upload_count == 1
        assert len(errors) == 0
