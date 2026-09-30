"""Tests for UploadOrchestrator process_architecture_uploads."""

import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from pulp_tool.models.context import UploadRpmContext
from pulp_tool.models.pulp_results import PulpResultsDocument
from pulp_tool.models.repository import RepositoryRefs
from pulp_tool.models.results import RpmUploadResult
from pulp_tool.utils.upload_orchestrator import UploadOrchestrator


class TestUploadOrchestratorProcessArchitectureUploads:
    """Tests for UploadOrchestrator.process_architecture_uploads() method."""

    def test_process_architecture_uploads_success(self) -> None:
        """Test process_architecture_uploads successfully processes architectures (lines 166, 173, 177, 190, 192)."""
        orchestrator = UploadOrchestrator()
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "x86_64"))
            os.makedirs(os.path.join(tmpdir, "aarch64"))
            args = UploadRpmContext(
                build_id="test-build",
                date_str="2024-01-01 00:00:00",
                namespace="test-ns",
                parent_package="test-pkg",
                rpm_path=tmpdir,
                sbom_path="/test/sbom.json",
            )
            mock_client = Mock()
            repositories = RepositoryRefs(
                rpms_href="/test/",
                rpms_prn="",
                logs_href="",
                logs_prn="logs-prn",
                sbom_href="",
                sbom_prn="",
                artifacts_href="",
                artifacts_prn="",
            )
            results_model = PulpResultsDocument(build_id="test-build", repositories=repositories)
            with (
                patch.object(orchestrator, "_submit_architecture_tasks") as mock_submit,
                patch.object(orchestrator, "_collect_architecture_results") as mock_collect,
            ):
                mock_future1 = Mock()
                mock_future2 = Mock()
                mock_submit.return_value = {mock_future1: "x86_64", mock_future2: "aarch64"}
                arch64 = RpmUploadResult()
                mock_collect.return_value = {"x86_64": RpmUploadResult(), "aarch64": arch64}
                result = orchestrator.process_architecture_uploads(
                    mock_client,
                    args,
                    repositories,
                    date_str="2024-01-01",
                    rpm_href="/test/",
                    results_model=results_model,
                    distribution_urls={"rpms": "https://example.com/rpms/"},
                )
                assert set(result.keys()) == {"x86_64", "aarch64"}
                assert all(isinstance(v, RpmUploadResult) for v in result.values())
                assert result["aarch64"] is arch64
                mock_submit.assert_called_once()
                mock_collect.assert_called_once()

    def test_submit_architecture_tasks_target_arch_repo_calls_ensure(self) -> None:
        """Per-arch mode resolves href via pulp_helper.ensure_rpm_repository_for_arch (line 94)."""
        orchestrator = UploadOrchestrator()
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "x86_64"))
            args = UploadRpmContext(
                build_id="test-build",
                date_str="2024-01-01 00:00:00",
                namespace="test-ns",
                parent_package=None,
                rpm_path=tmpdir,
                sbom_path=None,
                target_arch_repo=True,
            )
            mock_client = Mock()
            repositories = RepositoryRefs(
                rpms_href="",
                rpms_prn="",
                logs_href="",
                logs_prn="logs-prn",
                sbom_href="",
                sbom_prn="sbom-prn",
                artifacts_href="",
                artifacts_prn="",
            )
            results_model = PulpResultsDocument(build_id="test-build", repositories=repositories)
            mock_helper = Mock()
            mock_helper.ensure_rpm_repository_for_arch.return_value = "/arch-specific/rpm"
            done = RpmUploadResult(uploaded_rpms=[], created_resources=[])
            with patch("pulp_tool.utils.upload_orchestrator.upload_rpms_logs", return_value=done) as mock_upload:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future_to_arch = orchestrator._submit_architecture_tasks(
                        executor,
                        ["x86_64"],
                        tmpdir,
                        args,
                        mock_client,
                        "/bulk-ignored",
                        repositories.logs_prn,
                        "2024-01-01",
                        results_model,
                        {"logs": "https://example.com/logs/"},
                        pulp_helper=mock_helper,
                        target_arch_repo=True,
                    )
                    for fut in future_to_arch:
                        fut.result()
            mock_helper.ensure_rpm_repository_for_arch.assert_called_once_with("test-build", "x86_64")
            mock_upload.assert_called_once()
            assert mock_upload.call_args.kwargs["rpm_repository_href"] == "/arch-specific/rpm"

    def test_process_architecture_uploads_no_architectures(self) -> None:
        """Test process_architecture_uploads with no architectures (lines 168-170)."""
        orchestrator = UploadOrchestrator()
        with tempfile.TemporaryDirectory() as tmpdir:
            args = UploadRpmContext(
                build_id="test-build",
                date_str="2024-01-01 00:00:00",
                namespace="test-ns",
                parent_package="test-pkg",
                rpm_path=tmpdir,
                sbom_path="/test/sbom.json",
            )
            mock_client = Mock()
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
            with patch("pulp_tool.utils.upload_orchestrator.logging") as mock_logging:
                result = orchestrator.process_architecture_uploads(
                    mock_client,
                    args,
                    repositories,
                    date_str="2024-01-01",
                    rpm_href="/test/",
                    results_model=results_model,
                    distribution_urls={},
                )
                assert result == {}
                mock_logging.warning.assert_called_once()

    def test_process_architecture_uploads_no_rpm_path(self) -> None:
        """Test process_architecture_uploads when rpm_path is None (lines 168-170)."""
        orchestrator = UploadOrchestrator()
        args = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path=None,
            sbom_path="/test/sbom.json",
        )
        mock_client = Mock()
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
        with patch("pulp_tool.utils.upload_orchestrator.logging") as mock_logging:
            result = orchestrator.process_architecture_uploads(
                mock_client,
                args,
                repositories,
                date_str="2024-01-01",
                rpm_href="/test/",
                results_model=results_model,
                distribution_urls={},
            )
            assert result == {}
            mock_logging.warning.assert_called_once_with("rpm_path is not set, cannot process architecture uploads")
