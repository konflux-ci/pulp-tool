"""Tests for pulp_upload.py module."""

import logging
from unittest.mock import Mock, patch

from pulp_tool.models import RepositoryRefs
from pulp_tool.models.context import UploadContext, UploadRpmContext
from pulp_tool.models.pulp_results import PulpResultsDocument
from pulp_tool.services.upload_service import _add_distributions_to_results, _populate_results_model


class TestBuildResultsStructure:
    """Test _populate_results_model function."""

    def test_build_results_structure(self, mock_pulp_client) -> None:
        """Test _populate_results_model function (lines 364-367)."""
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
        from pulp_tool.models.artifacts import FileInfoModel, PulpContentRow

        content_results = [
            PulpContentRow.model_validate({"pulp_href": "/content/123/", "artifacts": {"test.txt": "/artifacts/123/"}})
        ]
        file_info_map: dict[str, FileInfoModel] = {
            "/artifacts/123/": FileInfoModel(pulp_href="/artifacts/123/", file="test.txt@sha256:abc", sha256="abc")
        }
        context = UploadContext(
            build_id="test-build", date_str="2024-01-01", namespace="test-namespace", parent_package="test-package"
        )
        with patch("pulp_tool.services.upload_collect.PulpHelper") as mock_helper_class:
            mock_helper = Mock()
            mock_helper.get_distribution_urls_for_upload_context.return_value = {
                "rpms": "https://example.com/rpms/",
                "logs": "https://example.com/logs/",
            }
            mock_helper_class.return_value = mock_helper
            mock_pulp_client.build_results_structure = Mock()
            _populate_results_model(mock_pulp_client, results_model, content_results, file_info_map, context)
            mock_pulp_client.build_results_structure.assert_called_once()
            call_args = mock_pulp_client.build_results_structure.call_args
            assert call_args[0][0] == results_model
            assert call_args[0][1] == content_results
            assert call_args[0][2] == file_info_map
            mock_helper_class.assert_called_once_with(mock_pulp_client, parent_package=context.parent_package)
            mock_helper.get_distribution_urls_for_upload_context.assert_called_once_with(context.build_id, context)
            assert call_args.kwargs.get("merge") is True

    def test_populate_results_model_target_arch_repo_uses_flagged_distribution_urls(self, mock_pulp_client) -> None:
        """With target_arch_repo, distribution URLs come from get_distribution_urls_for_upload_context."""
        from pulp_tool.models.artifacts import FileInfoModel

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
        content_results: list = []
        file_info_map: dict[str, FileInfoModel] = {}
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-namespace",
            parent_package="test-package",
            target_arch_repo=True,
        )
        with patch("pulp_tool.services.upload_collect.PulpHelper") as mock_helper_class:
            mock_helper = Mock()
            mock_helper.get_distribution_urls_for_upload_context.return_value = {"logs": "https://example.com/logs/"}
            mock_helper_class.return_value = mock_helper
            mock_pulp_client.build_results_structure = Mock()
            _populate_results_model(mock_pulp_client, results_model, content_results, file_info_map, context)
            mock_helper.get_distribution_urls_for_upload_context.assert_called_once_with("test-build", context)
            mock_pulp_client.build_results_structure.assert_called_once()
            assert mock_pulp_client.build_results_structure.call_args.kwargs["target_arch_repo"] is True

    def test_add_distributions_to_results_target_arch_repo(self, mock_pulp_client) -> None:
        """With target_arch_repo, per-arch RPM distribution URLs are added from artifact arch labels."""
        repositories = RepositoryRefs(
            rpms_href="",
            rpms_prn="",
            logs_href="/logs/",
            logs_prn="logs-prn",
            sbom_href="/sbom/",
            sbom_prn="sbom-prn",
            artifacts_href="/artifacts/",
            artifacts_prn="artifacts-prn",
        )
        results_model = PulpResultsDocument(build_id="test-build", repositories=repositories)
        results_model.add_artifact(
            "pkg.rpm",
            "https://example.com/pkg.rpm",
            "deadbeef",
            {"arch": "x86_64", "build_id": "test-build", "namespace": "test-namespace"},
        )
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-namespace",
            parent_package="test-package",
            target_arch_repo=True,
        )
        with patch("pulp_tool.services.upload_collect.PulpHelper") as mock_helper_class:
            mock_helper = Mock()
            mock_helper.get_distribution_urls_for_upload_context.return_value = {"logs": "https://example.com/logs/"}
            mock_helper.distribution_url_for_base_path.return_value = (
                "https://pulp.example.com/api/pulp-content/test-namespace/x86_64/"
            )
            mock_helper_class.return_value = mock_helper
            _add_distributions_to_results(mock_pulp_client, context, results_model)
            mock_helper.get_distribution_urls_for_upload_context.assert_called_once_with("test-build", context)
            mock_helper.distribution_url_for_base_path.assert_called_once_with("x86_64")
            assert (
                str(results_model.distributions["rpm_x86_64"])
                == "https://pulp.example.com/api/pulp-content/test-namespace/x86_64/"
            )

    def test_add_distributions_to_results_omits_artifacts_for_local_artifact_results(self, mock_pulp_client) -> None:
        """Folder --artifact-results must not add a synthetic artifacts distribution entry."""
        repositories = RepositoryRefs(
            rpms_href="/rpms/",
            rpms_prn="rpms-prn",
            logs_href="/logs/",
            logs_prn="logs-prn",
            sbom_href="/sbom/",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="",
        )
        results_model = PulpResultsDocument(build_id="my-build", repositories=repositories)
        context = UploadRpmContext(
            build_id="my-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/rpms",
            artifact_results="/data/results-out",
        )
        _add_distributions_to_results(mock_pulp_client, context, results_model)
        assert "artifacts" not in results_model.distributions
        assert "rpms" in results_model.distributions
        assert "logs" in results_model.distributions

    def test_add_distributions_to_results_warns_when_no_distribution_urls(self, mock_pulp_client, caplog) -> None:
        """When no build-scoped distribution URLs are returned, log a warning."""
        repositories = RepositoryRefs(
            rpms_href="",
            rpms_prn="",
            logs_href="/logs/",
            logs_prn="logs-prn",
            sbom_href="/sbom/",
            sbom_prn="sbom-prn",
            artifacts_href="/artifacts/",
            artifacts_prn="artifacts-prn",
        )
        results_model = PulpResultsDocument(build_id="test-build", repositories=repositories)
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-namespace",
            parent_package="test-package",
            target_arch_repo=False,
        )
        with patch("pulp_tool.services.upload_collect.PulpHelper") as mock_helper_class:
            mock_helper = Mock()
            mock_helper.get_distribution_urls_for_upload_context.return_value = {}
            mock_helper_class.return_value = mock_helper
            with caplog.at_level(logging.WARNING):
                _add_distributions_to_results(mock_pulp_client, context, results_model)
            assert "No distribution URLs found" in caplog.text
