"""Tests for PulpHelper upload methods."""

from unittest.mock import patch

from pulp_tool.models.context import UploadFilesContext, UploadRpmContext
from pulp_tool.models.pulp_results import PulpResultsDocument
from pulp_tool.models.repository import RepositoryRefs
from pulp_tool.models.results import RpmUploadResult
from pulp_tool.utils import PulpHelper


class TestPulpHelperUploadMethods:
    """Test PulpHelper upload methods."""

    def test_process_architecture_uploads(self, mock_pulp_client) -> None:
        """Test process_architecture_uploads method (line 124)."""
        helper = PulpHelper(mock_pulp_client)
        args = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/test/rpms",
            sbom_path="/test/sbom.json",
        )
        repositories = RepositoryRefs(
            rpms_href="/test/",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        results_model = PulpResultsDocument(build_id="test-build", repositories=repositories)
        with (
            patch.object(helper, "get_distribution_urls_for_upload_context", return_value={"rpms": "https://x/"}),
            patch.object(helper._upload_orchestrator, "process_architecture_uploads") as mock_process,
        ):
            rpm_res = RpmUploadResult()
            mock_process.return_value = {"x86_64": rpm_res}
            result = helper.process_architecture_uploads(
                mock_pulp_client,
                args,
                repositories,
                date_str="2024-01-01",
                rpm_href="/test/",
                results_model=results_model,
            )
            assert result == {"x86_64": rpm_res}
            mock_process.assert_called_once_with(
                mock_pulp_client,
                args,
                repositories,
                date_str="2024-01-01",
                rpm_href="/test/",
                results_model=results_model,
                distribution_urls={"rpms": "https://x/"},
                pulp_helper=helper,
                target_arch_repo=False,
            )

    def test_get_distribution_urls_for_upload_context_target_arch_repo_branch(self, mock_pulp_client) -> None:
        """target_arch_repo=True calls get_distribution_urls with target_arch_repo=True (line 115)."""
        helper = PulpHelper(mock_pulp_client)
        context = UploadRpmContext(
            build_id="b123",
            date_str="2024-01-01 00:00:00",
            namespace="ns",
            parent_package="pkg",
            rpm_path="/r",
            sbom_path="/s",
            target_arch_repo=True,
        )
        with patch.object(helper, "get_distribution_urls", return_value={"rpms": "https://per-arch/"}) as mock_urls:
            out = helper.get_distribution_urls_for_upload_context("b123", context)
        assert out == {"rpms": "https://per-arch/"}
        mock_urls.assert_called_once_with(
            "b123", target_arch_repo=True, skip_logs_repo=False, skip_sbom_repo=False, skip_artifacts_repo=False
        )

    def test_get_distribution_urls_for_upload_context_signed_by_branch(self, mock_pulp_client) -> None:
        """Non-target_arch_repo + non-empty signed_by uses include_signed_rpm_distro."""
        helper = PulpHelper(mock_pulp_client)
        context = UploadRpmContext(
            build_id="b123",
            date_str="2024-01-01 00:00:00",
            namespace="ns",
            parent_package="pkg",
            rpm_path="/r",
            sbom_path="/s",
            signed_by=" signer-key ",
            target_arch_repo=False,
        )
        with patch.object(helper, "get_distribution_urls", return_value={"rpms": "https://signed/"}) as mock_urls:
            out = helper.get_distribution_urls_for_upload_context("b123", context)
        assert out == {"rpms": "https://signed/"}
        mock_urls.assert_called_once_with(
            "b123",
            include_signed_rpm_distro=True,
            skip_logs_repo=False,
            skip_sbom_repo=False,
            skip_artifacts_repo=False,
        )

    def test_get_distribution_urls_for_upload_context_passes_skip_repo_flags(self, mock_pulp_client) -> None:
        """skip_logs_repo and skip_sbom_repo are forwarded to get_distribution_urls."""
        helper = PulpHelper(mock_pulp_client)
        context = UploadRpmContext(
            build_id="b123",
            date_str="2024-01-01 00:00:00",
            namespace="ns",
            parent_package="pkg",
            rpm_path="/r",
            skip_logs_repo=True,
            skip_sbom_repo=True,
        )
        with patch.object(helper, "get_distribution_urls", return_value={"artifacts": "https://a/"}) as mock_urls:
            out = helper.get_distribution_urls_for_upload_context("b123", context)
        assert out == {"artifacts": "https://a/"}
        mock_urls.assert_called_once_with("b123", skip_logs_repo=True, skip_sbom_repo=True, skip_artifacts_repo=False)

    def test_get_distribution_urls_for_upload_context_local_artifact_results_skips_artifacts(
        self, mock_pulp_client
    ) -> None:
        """Folder --artifact-results (no comma) forwards skip_artifacts_repo=True."""
        helper = PulpHelper(mock_pulp_client)
        context = UploadRpmContext(
            build_id="b123",
            date_str="2024-01-01 00:00:00",
            namespace="ns",
            parent_package="pkg",
            rpm_path="/r",
            artifact_results="/out/dir",
        )
        with patch.object(helper, "get_distribution_urls", return_value={"rpms": "https://r/"}) as mock_urls:
            out = helper.get_distribution_urls_for_upload_context("b123", context)
        assert out == {"rpms": "https://r/"}
        mock_urls.assert_called_once_with("b123", skip_logs_repo=False, skip_sbom_repo=False, skip_artifacts_repo=True)

    def test_process_uploads(self, mock_pulp_client) -> None:
        """Test process_uploads method (line 142)."""
        helper = PulpHelper(mock_pulp_client)
        args = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/test/rpms",
            sbom_path="/test/sbom.json",
        )
        repositories = RepositoryRefs(
            rpms_href="/test/",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        with patch.object(helper._upload_orchestrator, "process_uploads") as mock_process:
            mock_process.return_value = "https://example.com/results.json"
            result = helper.process_uploads(mock_pulp_client, args, repositories)
            assert result == "https://example.com/results.json"
            mock_process.assert_called_once_with(mock_pulp_client, args, repositories, pulp_helper=helper)

    def test_process_file_uploads(self, mock_pulp_client) -> None:
        """Test process_file_uploads method"""
        helper = PulpHelper(mock_pulp_client)
        context = UploadFilesContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_files=["/path/to/package-1.0.0-1.x86_64.rpm"],
            file_files=["/path/to/file.txt"],
            log_files=["/path/to/build.log"],
            sbom_files=["/path/to/sbom.json"],
        )
        repositories = RepositoryRefs(
            rpms_href="/test/",
            rpms_prn="",
            logs_href="",
            logs_prn="logs_prn",
            sbom_href="",
            sbom_prn="sbom_prn",
            artifacts_href="",
            artifacts_prn="artifacts_prn",
        )
        with patch.object(helper._upload_orchestrator, "process_file_uploads") as mock_process:
            mock_process.return_value = "https://example.com/results.json"
            result = helper.process_file_uploads(mock_pulp_client, context, repositories)
            assert result == "https://example.com/results.json"
            mock_process.assert_called_once_with(mock_pulp_client, context, repositories)
