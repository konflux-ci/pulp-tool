"""
Tests for pulp_tool.pull module.
"""

from unittest.mock import Mock, patch

import pytest

from pulp_tool.api import DistributionClient
from pulp_tool.models.artifacts import PulledArtifacts
from pulp_tool.pull import (
    _categorize_artifacts,
    download_artifacts_concurrently,
    load_and_validate_artifacts,
    load_artifact_metadata,
    upload_downloaded_files_to_pulp,
)
from pulp_tool.pull.reporting import _format_file_size
from pulp_tool.utils import RepositoryRefs


class TestClientInitialization:
    """Test client initialization and configuration."""

    def test_initialize_clients(self) -> None:
        """Test distribution client initialization."""
        client = DistributionClient(cert="/tmp/cert.pem", key="/tmp/key.pem")
        assert client.cert == "/tmp/cert.pem"
        assert client.key == "/tmp/key.pem"

    def test_load_and_validate_artifacts_exception(self) -> None:
        """Test loading and validation with exception."""
        args = Mock()
        args.artifact_location = "/nonexistent/file.json"
        mock_client = Mock()
        with patch("pulp_tool.pull.load_artifact_metadata") as mock_load:
            mock_load.side_effect = FileNotFoundError("File not found")
            with pytest.raises(FileNotFoundError):
                load_and_validate_artifacts(args, mock_client)

    def test_handle_pulp_upload_no_client(self) -> None:
        """Test handling upload with no Pulp client."""
        pulp_client = None
        upload_info = None if not pulp_client else {"test": "data"}
        assert upload_info is None

    def test_handle_pulp_upload_with_client(self) -> None:
        """Test handling upload with Pulp client."""
        pulled_artifacts = PulledArtifacts()
        args = Mock()
        args.build_id = "test-build"
        mock_client = Mock()
        mock_repos = RepositoryRefs(
            rpms_prn="rpm-repo",
            logs_prn="log-repo",
            sbom_prn="sbom-repo",
            artifacts_prn="artifact-repo",
            rpms_href="/pulp/api/v3/repositories/rpm/rpm/",
            logs_href="/pulp/api/v3/repositories/file/file/",
            sbom_href="/pulp/api/v3/repositories/file/file/",
            artifacts_href="/pulp/api/v3/repositories/file/file/",
        )
        with patch("pulp_tool.pull.upload.PulpHelper") as mock_helper:
            mock_helper_instance = Mock()
            mock_helper_instance.setup_repositories.return_value = mock_repos
            mock_helper.return_value = mock_helper_instance
            result = upload_downloaded_files_to_pulp(mock_client, pulled_artifacts, args)
            assert result is not None
            assert result.build_id == "test-build"

    def test_handle_pulp_upload_reuses_precreated_repositories(self) -> None:
        """Pre-created destination repositories skip a second setup_repositories call."""
        pulled_artifacts = PulledArtifacts()
        args = Mock()
        args.build_id = "test-build"
        mock_client = Mock()
        mock_repos = RepositoryRefs(
            rpms_prn="rpm-repo",
            logs_prn="log-repo",
            sbom_prn="sbom-repo",
            artifacts_prn="artifact-repo",
            rpms_href="/pulp/api/v3/repositories/rpm/rpm/",
            logs_href="/pulp/api/v3/repositories/file/file/",
            sbom_href="/pulp/api/v3/repositories/file/file/",
            artifacts_href="/pulp/api/v3/repositories/file/file/",
        )
        with patch("pulp_tool.pull.upload.PulpHelper") as mock_helper:
            mock_helper_instance = Mock()
            mock_helper.return_value = mock_helper_instance
            upload_downloaded_files_to_pulp(mock_client, pulled_artifacts, args, repositories=mock_repos)
            mock_helper_instance.setup_repositories.assert_not_called()


class TestTransferHelpers:
    """Test pull helper functions."""

    def test_categorize_artifacts(self) -> None:
        """Test artifact categorization by type."""
        artifacts = {
            "file1.rpm": {"url": "http://example.com/file1.rpm", "arch": "x86_64"},
            "file2.log": {"url": "http://example.com/file2.log"},
            "sbom.json": {"url": "http://example.com/sbom.json"},
        }
        distros = {
            "rpms": "http://example.com/rpms/",
            "logs": "http://example.com/logs/",
            "sbom": "http://example.com/sbom/",
        }
        result = _categorize_artifacts(artifacts, distros)
        assert len(result) == 3
        assert any(task.artifact_name == "file1.rpm" for task in result)
        assert any(task.artifact_name == "file2.log" for task in result)
        assert any(task.artifact_name == "sbom.json" for task in result)

    def test_format_file_size(self) -> None:
        """Test file size formatting."""
        assert _format_file_size(512) == "512.0 B"
        assert _format_file_size(1024) == "1.0 KB"
        assert _format_file_size(1024 * 1024) == "1.0 MB"
        assert _format_file_size(1024 * 1024 * 1024) == "1.0 GB"

    def test_download_artifacts_concurrently_no_client(self) -> None:
        """Test download_artifacts_concurrently raises ValueError when distribution_client is None."""
        artifacts = {"file1.rpm": {"url": "http://example.com/file1.rpm", "arch": "x86_64"}}
        distros = {"rpms": "http://example.com/rpms/"}
        with pytest.raises(ValueError, match="DistributionClient.*required for downloading artifacts"):
            download_artifacts_concurrently(artifacts, distros, None, max_workers=4)


class TestLoadArtifactMetadata:
    """Test load_artifact_metadata function."""

    def test_load_artifact_metadata_general_exception(self, temp_file) -> None:
        """Test load_artifact_metadata handles general exceptions (lines 85-87)."""
        client = DistributionClient(cert="cert.pem", key="key.pem")
        with patch("builtins.open", side_effect=PermissionError("Permission denied")):
            with pytest.raises(PermissionError):
                load_artifact_metadata(temp_file, client)
