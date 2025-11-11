"""
Tests for RPM operation utility functions.

This module tests RPM checking, uploading, and processing functions.
"""

import os
from unittest.mock import Mock, patch
import pytest
import httpx

from pulp_tool.utils import (
    upload_rpms_logs,
)
from pulp_tool.utils.rpm_operations import (
    _calculate_sha256_checksum,
    _create_batches,
    _get_nvra,
    upload_rpms_parallel,
)


class TestChecksumUtilities:
    """Test checksum utility functions."""

    def test_calculate_sha256_checksum(self, temp_file):
        """Test _calculate_sha256_checksum function."""
        checksum = _calculate_sha256_checksum(temp_file)

        assert len(checksum) == 64  # SHA256 hex length
        assert all(c in "0123456789abcdef" for c in checksum)

    def test_calculate_sha256_checksum_file_not_found(self):
        """Test _calculate_sha256_checksum function with non-existent file."""
        with pytest.raises(FileNotFoundError):
            _calculate_sha256_checksum("/non/existent/file")

    def test_calculate_sha256_checksum_io_error(self):
        """Test _calculate_sha256_checksum with IO error."""
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name
            f.write(b"test content")

        try:
            # Make the file unreadable
            os.chmod(temp_path, 0o000)

            with pytest.raises(IOError, match="Error reading file"):
                _calculate_sha256_checksum(temp_path)
        finally:
            os.chmod(temp_path, 0o644)
            os.unlink(temp_path)


class TestBatchProcessingUtilities:
    """Test batch processing utility functions."""

    def test_create_batches(self):
        """Test _create_batches function."""
        items = list(range(100))
        batches = list(_create_batches(items, batch_size=25))

        assert len(batches) == 4
        assert len(batches[0]) == 25
        assert len(batches[-1]) == 25

    def test_create_batches_empty(self):
        """Test _create_batches function with empty list."""
        batches = list(_create_batches([], batch_size=25))

        assert len(batches) == 0

    def test_create_batches_single_batch(self):
        """Test _create_batches function with single batch."""
        items = list(range(10))
        batches = list(_create_batches(items, batch_size=25))

        assert len(batches) == 1
        assert len(batches[0]) == 10


class TestNVRAUtilities:
    """Test NVRA utility functions."""

    def test_get_nvra(self):
        """Test _get_nvra function."""
        result = {"name": "test-package", "version": "1.0.0", "release": "1", "arch": "x86_64"}

        nvra = _get_nvra(result)
        assert nvra == "test-package-1.0.0-1.x86_64"

    def test_get_nvra_missing_fields(self):
        """Test _get_nvra function with missing fields."""
        result = {"name": "test-package", "version": "1.0.0"}

        nvra = _get_nvra(result)
        assert nvra == "test-package-1.0.0-None.None"


class TestRPMUtilities:
    """Test RPM utility functions."""

    def test_upload_rpms_logs(self, mock_pulp_client, temp_rpm_file, httpx_mock):
        """Test upload_rpms_logs function."""
        from pulp_tool.models import PulpResultsModel, RepositoryRefs

        # Mock the RPM search endpoint
        httpx_mock.get(
            "https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/rpm/packages/"
            "?pulp_label_select=build_id~test-build"
        ).mock(return_value=httpx.Response(200, json={"results": []}))

        # Mock the file content creation endpoint for log uploads
        httpx_mock.post("https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/file/files/").mock(
            return_value=httpx.Response(202, json={"task": "/pulp/api/v3/tasks/12345/"})
        )

        # Mock the task endpoint for wait_for_finished_task
        httpx_mock.get("https://pulp.example.com/pulp/api/v3/tasks/12345/").mock(
            return_value=httpx.Response(
                200,
                json={"pulp_href": "/pulp/api/v3/tasks/12345/", "state": "completed", "result": {"status": "success"}},
            )
        )

        args = Mock()
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

        with patch("glob.glob", return_value=[temp_rpm_file]), patch(
            "pulp_tool.utils.uploads.upload_rpms_parallel", return_value=[]
        ):

            result = upload_rpms_logs(
                os.path.dirname(temp_rpm_file),
                args,
                mock_pulp_client,
                "x86_64",
                rpm_repository_href="test-repo",
                file_repository_prn="test-file-repo",
                date="2024-01-01 12:00:00",
                results_model=results_model,
            )

        assert result.uploaded_rpms == [temp_rpm_file]

    def test_upload_rpms_logs_no_files(self, mock_pulp_client, temp_dir):
        """Test upload_rpms_logs with no RPMs or logs."""
        from pulp_tool.models import PulpResultsModel, RepositoryRefs

        args = Mock()
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

        with patch("glob.glob", return_value=[]):
            result = upload_rpms_logs(
                temp_dir,
                args,
                mock_pulp_client,
                "x86_64",
                rpm_repository_href="test-repo",
                file_repository_prn="test-file-repo",
                date="2024-01-01 12:00:00",
                results_model=results_model,
            )

        assert result.uploaded_rpms == []

    def test_upload_rpms_parallel_empty_list(self, mock_pulp_client):
        """Test upload_rpms_parallel with empty list."""
        result = upload_rpms_parallel(mock_pulp_client, [], {}, "x86_64")

        assert result == []

    def test_upload_rpms_parallel_with_rpms(self, mock_pulp_client, temp_rpm_file):
        """Test upload_rpms_parallel with RPMs."""
        mock_pulp_client.upload_content = Mock(return_value="/pulp/api/v3/content/rpm/packages/12345/")

        result = upload_rpms_parallel(mock_pulp_client, [temp_rpm_file], {"arch": "x86_64"}, "x86_64")

        assert len(result) == 1
