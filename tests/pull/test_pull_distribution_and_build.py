"""
Tests for pulp_tool.pull module.
"""

import json
from unittest.mock import Mock, mock_open, patch

import httpx
import pytest
from httpx import HTTPError

from pulp_tool.api import DistributionClient
from pulp_tool.models.artifacts import PulledArtifacts
from pulp_tool.pull import _categorize_artifacts, load_artifact_metadata, setup_repositories_if_needed
from pulp_tool.utils import determine_build_id


class TestDistributionClient:
    """Test DistributionClient class functionality."""

    def test_init(self) -> None:
        """Test DistributionClient initialization."""
        client = DistributionClient(cert="cert.pem", key="key.pem")
        assert client.cert == "cert.pem"
        assert client.key == "key.pem"
        assert client.session is not None

    def test_create_session(self) -> None:
        """Test _create_session method."""
        client = DistributionClient(cert="cert.pem", key="key.pem")
        session = client._create_session()
        assert session is not None

    def test_pull_artifact(self, httpx_mock) -> None:
        """Test pull_artifact method."""
        client = DistributionClient(cert="cert.pem", key="key.pem")
        httpx_mock.get("https://example.com/artifacts.json").mock(
            return_value=httpx.Response(200, json={"artifacts": {"test.rpm": {"labels": {"build_id": "test"}}}})
        )
        response = client.pull_artifact("https://example.com/artifacts.json")
        assert response.status_code == 200
        assert response.json()["artifacts"]["test.rpm"]["labels"]["build_id"] == "test"

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


class TestArtifactManagement:
    """Test artifact loading and categorization functionality."""

    def test_load_artifact_metadata_success(self, httpx_mock) -> None:
        """Test loading artifact metadata successfully."""
        client = DistributionClient(cert="cert.pem", key="key.pem")
        httpx_mock.get("https://example.com/artifacts.json").mock(
            return_value=httpx.Response(200, json={"artifacts": {"test.rpm": {"labels": {"build_id": "test"}}}})
        )
        result = load_artifact_metadata("https://example.com/artifacts.json", client)
        assert "artifacts" in result
        assert result["artifacts"]["test.rpm"]["labels"]["build_id"] == "test"

    def test_load_artifact_metadata_file_not_found(self) -> None:
        """Test loading artifact metadata from non-existent file."""
        client = DistributionClient(cert="cert.pem", key="key.pem")
        with pytest.raises(FileNotFoundError):
            load_artifact_metadata("/nonexistent/file.json", client)

    def test_load_artifact_metadata_invalid_json(self, temp_file) -> None:
        """Test loading artifact metadata with invalid JSON."""
        client = DistributionClient(cert="cert.pem", key="key.pem")
        with open(temp_file, "w") as f:
            f.write("invalid json content")
        with pytest.raises(json.JSONDecodeError):
            load_artifact_metadata(temp_file, client)

    def test_load_artifact_metadata_remote_url_no_client(self) -> None:
        """Test loading artifact metadata from remote URL without distribution client raises ValueError."""
        with pytest.raises(ValueError, match="DistributionClient.*required for remote artifact locations"):
            load_artifact_metadata("https://example.com/artifacts.json", None)

    def test_categorize_artifacts(self) -> None:
        """Test categorizing artifacts by type."""
        artifacts = {
            "test.rpm": {"labels": {"arch": "x86_64"}},
            "test.sbom": {"labels": {"arch": "noarch"}},
            "test.log": {"labels": {"arch": "noarch"}},
        }
        distros = {
            "rpms": "https://example.com/rpms/",
            "sbom": "https://example.com/sbom/",
            "logs": "https://example.com/logs/",
        }
        result = _categorize_artifacts(artifacts, distros, embedded_urls_only=False)
        assert len(result) == 3
        artifact_types = [task.artifact_type for task in result]
        assert "rpm" in artifact_types
        assert "sbom" in artifact_types
        assert "log" in artifact_types
        for task in result:
            assert hasattr(task, "artifact_name")
            assert hasattr(task, "file_url")
            assert hasattr(task, "arch")
            assert hasattr(task, "artifact_type")


class TestRepositoryManagement:
    """Test repository setup and management functionality."""

    def test_setup_repositories_no_config(self) -> None:
        """Test setup_repositories_if_needed with no config."""
        args = Mock()
        args.config = None
        result = setup_repositories_if_needed(args)
        assert result is None

    def test_setup_repositories_success(self, mock_config, temp_config_file) -> None:
        """Test setup_repositories_if_needed with successful setup."""
        args = Mock()
        args.config = temp_config_file
        args.transfer_dest = temp_config_file
        args.build_id = "test-build"
        with (
            patch("pulp_tool.pull.download.PulpClient.create_from_config_file") as mock_create,
            patch("pulp_tool.pull.download.determine_build_id", return_value="test-build"),
            patch("pulp_tool.pull.download.PulpHelper") as mock_helper,
        ):
            mock_client = Mock()
            mock_create.return_value = mock_client
            mock_helper_instance = Mock()
            mock_helper.return_value = mock_helper_instance
            from pulp_tool.models.repository import RepositoryRefs

            mock_repos = RepositoryRefs(
                rpms_href="/test/",
                rpms_prn="",
                logs_href="",
                logs_prn="",
                sbom_href="",
                sbom_prn="",
                artifacts_href="",
                artifacts_prn="",
            )
            mock_helper_instance.setup_repositories.return_value = mock_repos
            result = setup_repositories_if_needed(args)
            assert result is not None
            assert result.client == mock_client
            assert result.repositories == mock_repos
            mock_helper_instance.setup_repositories.assert_called_once_with("test-build")

    def test_setup_repositories_exception(self, temp_config_file) -> None:
        """Test setup_repositories_if_needed with exception."""
        args = Mock()
        args.config = temp_config_file
        args.transfer_dest = temp_config_file
        with patch("pulp_tool.api.PulpClient.create_from_config_file", side_effect=ValueError("Config error")):
            result = setup_repositories_if_needed(args)
            assert result is None

    def test_setup_repositories_no_transfer_dest(self, temp_config_file) -> None:
        """Test setup_repositories_if_needed skips when --transfer-dest was not specified."""
        args = Mock()
        args.config = temp_config_file
        args.transfer_dest = None
        with patch("pulp_tool.pull.download.PulpClient.create_from_config_file") as mock_create:
            result = setup_repositories_if_needed(args)
        assert result is None
        mock_create.assert_not_called()


class TestBuildIdManagement:
    """Test build ID determination and management."""

    def test_determine_build_id_from_args(self) -> None:
        """Test determining build_id from command line arguments."""
        args = Mock()
        args.build_id = "test-build"
        args.artifact_file = None
        pulled_artifacts = PulledArtifacts(rpms={}, logs={}, sboms={})
        result = determine_build_id(args, pulled_artifacts=pulled_artifacts)
        assert result == "test-build"

    def test_determine_build_id_from_artifacts(self) -> None:
        """Test determining build_id from pulled artifacts."""
        args = Mock()
        args.build_id = None
        args.artifact_file = None
        pulled_artifacts = PulledArtifacts()
        pulled_artifacts.add_rpm("test.rpm", "/tmp/test.rpm", {"build_id": "test-build"})
        result = determine_build_id(args, pulled_artifacts=pulled_artifacts)
        assert result == "test-build"

    def test_determine_build_id_from_file(self, temp_file) -> None:
        """Test determining build_id from artifact file."""
        artifact_data = {"artifacts": {"test.rpm": {"labels": {"build_id": "test-build"}}}}
        with open(temp_file, "w") as f:
            json.dump(artifact_data, f)
        args = Mock()
        args.build_id = None
        args.artifact_location = temp_file
        result = determine_build_id(args, artifact_json=artifact_data)
        assert result == "test-build"
