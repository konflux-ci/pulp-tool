"""Tests for service modules."""

from unittest.mock import Mock, patch

from pulp_tool.models.artifacts import ArtifactData, ArtifactJsonResponse
from pulp_tool.models.context import PullContext, UploadRpmContext
from pulp_tool.services.pull_service import PullService
from pulp_tool.services.upload_service import UploadService


class TestPullService:
    """Test PullService class."""

    def test_pull_service_init(self) -> None:
        """Test PullService initialization."""
        service = PullService()
        assert service is not None

    @patch("pulp_tool.services.pull_service.load_and_validate_artifacts")
    @patch("pulp_tool.services.pull_service.logging")
    def test_load_artifacts(self, mock_logging, mock_load) -> None:
        """Test load_artifacts method."""
        service = PullService()
        context = PullContext(artifact_location="/test/path.json")
        mock_artifact_data = ArtifactData(
            artifact_json=ArtifactJsonResponse(artifacts={}, distributions={}), artifacts={}
        )
        mock_load.return_value = mock_artifact_data
        result = service.load_artifacts(context, None)
        assert result == mock_artifact_data
        mock_load.assert_called_once_with(context, None)
        assert mock_logging.info.call_count >= 2

    @patch("pulp_tool.services.pull_service.download_artifacts_concurrently")
    @patch("pulp_tool.services.pull_service.logging")
    def test_download_artifacts(self, mock_logging, mock_download) -> None:
        """Test download_artifacts method."""
        service = PullService()
        context = PullContext(artifact_location="/test/path.json")
        mock_artifact_data = ArtifactData(
            artifact_json=ArtifactJsonResponse(artifacts={}, distributions={}), artifacts={}
        )
        mock_result = Mock()
        mock_result.pulled_artifacts = Mock()
        mock_result.completed = 5
        mock_result.failed = 2
        mock_download.return_value = mock_result
        pulled, completed, failed = service.download_artifacts(mock_artifact_data, None, context, 4)
        assert completed == 5
        assert failed == 2
        mock_download.assert_called_once()
        assert mock_logging.info.call_count >= 2

    @patch("pulp_tool.services.pull_service.upload_downloaded_files_to_pulp")
    @patch("pulp_tool.services.pull_service.logging")
    def test_upload_artifacts(self, mock_logging, mock_upload) -> None:
        """Test upload_artifacts method."""
        service = PullService()
        context = PullContext(artifact_location="/test/path.json")
        mock_client = Mock()
        mock_pulled_artifacts = Mock()
        from pulp_tool.models.repository import RepositoryRefs
        from pulp_tool.models.results import PulpResultsModel
        from pulp_tool.models.statistics import UploadCounts

        mock_upload_info = PulpResultsModel(
            build_id="test-build",
            repositories=RepositoryRefs(
                rpms_href="",
                rpms_prn="",
                logs_href="",
                logs_prn="",
                sbom_href="",
                sbom_prn="",
                artifacts_href="",
                artifacts_prn="",
            ),
            artifacts={},
            distributions={},
            uploaded_counts=UploadCounts(rpms=5, logs=3, sboms=2),
        )
        mock_upload.return_value = mock_upload_info
        result = service.upload_artifacts(mock_client, mock_pulled_artifacts, context)
        assert result == mock_upload_info
        mock_upload.assert_called_once_with(mock_client, mock_pulled_artifacts, context, repositories=None)
        assert mock_logging.info.call_count >= 2

    @patch("pulp_tool.services.pull_service.setup_repositories_if_needed")
    @patch("pulp_tool.services.pull_service.logging")
    def test_setup_destination_repositories_with_config(self, mock_logging, mock_setup) -> None:
        """Test setup_destination_repositories with config and --transfer-dest."""
        service = PullService()
        context = PullContext(
            artifact_location="/test/path.json", config="/test/config.toml", transfer_dest="/test/config.toml"
        )
        mock_destination = Mock()
        mock_setup.return_value = mock_destination
        result = service.setup_destination_repositories(context)
        assert result == mock_destination
        mock_setup.assert_called_once()
        assert mock_logging.info.call_count >= 1

    @patch("pulp_tool.services.pull_service.setup_repositories_if_needed")
    @patch("pulp_tool.services.pull_service.logging")
    def test_setup_destination_repositories_config_without_transfer_dest(self, mock_logging, mock_setup) -> None:
        """Test setup_destination_repositories skips when only group config is set."""
        service = PullService()
        context = PullContext(artifact_location="/test/path.json", config="/test/config.toml")
        result = service.setup_destination_repositories(context)
        assert result is None
        mock_setup.assert_not_called()
        mock_logging.debug.assert_called_once()

    @patch("pulp_tool.services.pull_service.logging")
    def test_setup_destination_repositories_without_config(self, mock_logging) -> None:
        """Test setup_destination_repositories without config."""
        service = PullService()
        context = PullContext(artifact_location="/test/path.json", config=None)
        result = service.setup_destination_repositories(context)
        assert result is None
        mock_logging.debug.assert_called_once()

    @patch("pulp_tool.services.pull_service.generate_pull_report")
    def test_generate_report(self, mock_report) -> None:
        """Test generate_report method."""
        service = PullService()
        context = PullContext(artifact_location="/test/path.json")
        mock_pulled_artifacts = Mock()
        service.generate_report(mock_pulled_artifacts, 5, 0, context, None)
        mock_report.assert_called_once_with(mock_pulled_artifacts, 5, 0, context, None)


class TestUploadService:
    """Test UploadService class."""

    def test_upload_service_init(self) -> None:
        """Test UploadService initialization."""
        mock_client = Mock()
        service = UploadService(mock_client, parent_package="test-pkg")
        assert service.client == mock_client
        assert service.helper is not None

    def test_upload_service_init_no_parent_package(self) -> None:
        """Test UploadService initialization without parent_package."""
        mock_client = Mock()
        service = UploadService(mock_client)
        assert service.client == mock_client
        assert service.helper is not None

    @patch("pulp_tool.services.upload_service.PulpHelper")
    @patch("pulp_tool.services.upload_service.logging")
    def test_setup_repositories(self, mock_logging, mock_helper_class) -> None:
        """Test setup_repositories method."""
        mock_client = Mock()
        service = UploadService(mock_client)
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
        service.helper.setup_repositories.return_value = mock_repos
        result = service.setup_repositories("test-build")
        assert result == mock_repos
        service.helper.setup_repositories.assert_called_once_with("test-build")
        assert mock_logging.info.call_count >= 2

    @patch("pulp_tool.services.upload_service.PulpHelper")
    @patch("pulp_tool.services.upload_service.logging")
    def test_upload_artifacts(self, mock_logging, mock_helper_class) -> None:
        """Test upload_artifacts method."""
        mock_client = Mock()
        service = UploadService(mock_client)
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
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/test/rpms",
            sbom_path="/test/sbom.json",
        )
        service.helper.process_uploads.return_value = "https://example.com/results.json"
        result = service.upload_artifacts(context, mock_repos)
        assert result == "https://example.com/results.json"
        service.helper.process_uploads.assert_called_once_with(
            mock_client, context, mock_repos, pulp_helper=service.helper
        )
        assert mock_logging.info.call_count >= 2

    @patch("pulp_tool.services.upload_service.PulpHelper")
    @patch("pulp_tool.services.upload_service.logging")
    def test_upload_artifacts_no_results(self, mock_logging, mock_helper_class) -> None:
        """Test upload_artifacts when no results JSON URL is returned."""
        mock_client = Mock()
        service = UploadService(mock_client)
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
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/test/rpms",
            sbom_path="/test/sbom.json",
        )
        service.helper.process_uploads.return_value = None
        result = service.upload_artifacts(context, mock_repos)
        assert result is None
        mock_logging.error.assert_called_once()

    @patch("pulp_tool.services.upload_service.PulpHelper")
    def test_get_distribution_urls(self, mock_helper_class) -> None:
        """Test get_distribution_urls method."""
        mock_client = Mock()
        service = UploadService(mock_client)
        mock_urls = {"rpms": "https://example.com/rpms", "logs": "https://example.com/logs"}
        service.helper.get_distribution_urls.return_value = mock_urls
        result = service.get_distribution_urls("test-build")
        assert result == mock_urls
        service.helper.get_distribution_urls.assert_called_once_with("test-build")
