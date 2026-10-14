"""Tests for :class:`pulp_tool.upload.pipeline.UploadOrchestrator`."""

import os
import tempfile
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any
from unittest.mock import Mock, patch

import pytest

from pulp_tool.models.context import UploadFilesContext, UploadRpmContext
from pulp_tool.models.pulp_results import PulpResultsDocument
from pulp_tool.models.repository import RepositoryRefs
from pulp_tool.models.results import RpmUploadResult
from pulp_tool.upload.pipeline import UploadOrchestrator
from tests.support.upload_orchestrator_test_stub import PROCESS_FILE_UPLOAD_DIST_URLS as _PROCESS_FILE_UPLOAD_DIST_URLS


class TestUploadOrchestratorFindExistingArchitectures:
    """Tests for UploadOrchestrator._find_existing_architectures() method."""

    def test_find_existing_architectures_with_existing(self) -> None:
        """Test _find_existing_architectures finds existing architectures (lines 46-50)."""
        orchestrator = UploadOrchestrator()
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "x86_64"))
            os.makedirs(os.path.join(tmpdir, "aarch64"))
            result = orchestrator._find_existing_architectures(tmpdir)
            assert "x86_64" in result
            assert "aarch64" in result

    def test_find_existing_architectures_skips_non_existent(self) -> None:
        """Test _find_existing_architectures skips non-existent paths (lines 52-53)."""
        orchestrator = UploadOrchestrator()
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "x86_64"))
            with patch("pulp_tool.upload.pipeline.logging") as mock_logging:
                result = orchestrator._find_existing_architectures(tmpdir)
                assert "x86_64" in result
                debug_calls = [str(call) for call in mock_logging.debug.call_args_list]
                assert any("Skipping" in str(call) for call in debug_calls)

    def test_find_existing_architectures_empty(self) -> None:
        """Test _find_existing_architectures with no existing architectures."""
        orchestrator = UploadOrchestrator()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = orchestrator._find_existing_architectures(tmpdir)
            assert result == []


class TestUploadOrchestratorSubmitArchitectureTasks:
    """Tests for UploadOrchestrator._submit_architecture_tasks() method."""

    def test_submit_architecture_tasks(self) -> None:
        """Test _submit_architecture_tasks submits tasks (lines 84-87, 98-99)."""
        orchestrator = UploadOrchestrator()
        mock_executor = Mock()
        mock_future1 = Mock()
        mock_future2 = Mock()
        mock_executor.submit.side_effect = [mock_future1, mock_future2]
        existing_archs = ["x86_64", "aarch64"]
        rpm_path = "/test/rpms"
        args = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path=rpm_path,
            sbom_path="/test/sbom.json",
        )
        mock_client = Mock()
        rpm_href = "/test/rpm-href"
        logs_prn = "logs-prn"
        date_str = "2024-01-01"
        results_model = PulpResultsDocument(
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
        )
        with patch("pulp_tool.upload.pipeline.upload_rpms_logs"):
            future_to_arch = orchestrator._submit_architecture_tasks(
                mock_executor,
                existing_archs,
                rpm_path,
                args,
                mock_client,
                rpm_href,
                logs_prn,
                date_str,
                results_model,
                {},
            )
            assert len(future_to_arch) == 2
            assert mock_executor.submit.call_count == 2
            assert mock_future1 in future_to_arch
            assert mock_future2 in future_to_arch


class TestUploadOrchestratorCollectArchitectureResults:
    """Tests for UploadOrchestrator._collect_architecture_results() method."""

    def test_collect_architecture_results_success(self) -> None:
        """Test _collect_architecture_results collects results successfully (lines 114-120, 124)."""
        orchestrator = UploadOrchestrator()
        mock_future1: Future[Any] = Future()
        mock_future2: Future[Any] = Future()
        mock_result1 = RpmUploadResult(
            uploaded_rpms=["a", "b", "c", "d", "e"], created_resources=["/resource/1", "/resource/2"]
        )
        mock_result2 = RpmUploadResult(uploaded_rpms=["x", "y", "z"], created_resources=["/resource/3"])
        mock_future1.set_result(mock_result1)
        mock_future2.set_result(mock_result2)
        future_to_arch = {mock_future1: "x86_64", mock_future2: "aarch64"}
        with patch("pulp_tool.upload.pipeline.logging") as mock_logging:
            result = orchestrator._collect_architecture_results(future_to_arch)
            assert "x86_64" in result
            assert "aarch64" in result
            assert len(result["x86_64"].uploaded_rpms) == 5
            assert len(result["aarch64"].uploaded_rpms) == 3
            assert len(result["x86_64"].created_resources) == 2
            assert len(result["aarch64"].created_resources) == 1
            mock_logging.debug.assert_called()

    def test_collect_architecture_results_exception(self) -> None:
        """Test _collect_architecture_results handles exceptions (lines 129-132)."""
        orchestrator = UploadOrchestrator()
        mock_future: Future[Any] = Future()
        mock_future.set_exception(ValueError("Upload failed"))
        future_to_arch = {mock_future: "x86_64"}
        with patch("pulp_tool.upload.pipeline.handle_generic_error") as mock_handle_error:
            with pytest.raises(ValueError, match="Upload failed"):
                orchestrator._collect_architecture_results(future_to_arch)
            mock_handle_error.assert_called_once()
            assert mock_handle_error.call_args[0][1] == "process architecture x86_64"

    def test_collect_architecture_results_logs_processed(self) -> None:
        """Test _collect_architecture_results logs processed architectures (lines 134-135)."""
        orchestrator = UploadOrchestrator()
        mock_future: Future[Any] = Future()
        mock_result = RpmUploadResult(uploaded_rpms=["p"] * 5, created_resources=[])
        mock_future.set_result(mock_result)
        future_to_arch = {mock_future: "x86_64"}
        with patch("pulp_tool.upload.pipeline.logging") as mock_logging:
            orchestrator._collect_architecture_results(future_to_arch)
            debug_calls = [str(call) for call in mock_logging.debug.call_args_list]
            assert any("Processed architectures" in str(call) for call in debug_calls)


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
            with patch("pulp_tool.upload.pipeline.upload_rpms_logs", return_value=done) as mock_upload:
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
            mock_helper.ensure_rpm_repository_for_arch.assert_called_once()
            call_kw = mock_helper.ensure_rpm_repository_for_arch.call_args.kwargs
            assert call_kw.get("layout") is not None
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
            with patch("pulp_tool.upload.pipeline.logging") as mock_logging:
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
        with patch("pulp_tool.upload.pipeline.logging") as mock_logging:
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


class TestUploadOrchestratorProcessFileUploads:
    """Tests for UploadOrchestrator.process_file_uploads() method."""

    def test_process_file_uploads_all_file_types(self) -> None:
        """Test process_file_uploads with all file types."""
        orchestrator = UploadOrchestrator()
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
        mock_client = Mock()
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
        )
        with (
            patch("pulp_tool.utils.pulp_helper.PulpHelper") as mock_ph_cls,
            patch("pulp_tool.upload.pipeline.upload_rpms", return_value=["/rpm/resource/1"]),
            patch("pulp_tool.upload.pipeline.upload_log", return_value=["/log/resource/1"]),
            patch("pulp_tool.upload.sbom.upload_sbom", return_value=["/sbom/resource/1"]),
            patch("pulp_tool.upload.results.collect_results", return_value="https://example.com/results.json"),
            patch("pulp_tool.upload.pipeline.create_labels"),
            patch("pulp_tool.upload.pipeline.validate_file_path"),
            patch.object(mock_client, "create_file_content") as mock_create,
            patch.object(mock_client, "check_response"),
            patch.object(mock_client, "wait_for_finished_task") as mock_wait,
        ):
            mock_ph_cls.return_value.get_distribution_urls_for_upload_context.return_value = (
                _PROCESS_FILE_UPLOAD_DIST_URLS
            )
            mock_response = Mock()
            mock_response.json.return_value = {"task": "/api/v3/tasks/123/"}
            mock_create.return_value = mock_response
            mock_task_response = Mock()
            mock_task_response.created_resources = ["/file/resource/1"]
            mock_wait.return_value = mock_task_response
            result = orchestrator.process_file_uploads(mock_client, context, repositories)
            assert result == "https://example.com/results.json"
            assert mock_create.called

    def test_process_file_uploads_rpms_with_arch_detection(self) -> None:
        """Test process_file_uploads with RPMs requiring architecture detection."""
        orchestrator = UploadOrchestrator()
        context = UploadFilesContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_files=["/path/to/x86_64/package-1.0.0-1.rpm", "/path/to/package-1.0.0-1.aarch64.rpm"],
        )
        mock_client = Mock()
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        with (
            patch("pulp_tool.utils.pulp_helper.PulpHelper") as mock_ph_cls,
            patch("pulp_tool.utils.artifact_detection.detect_arch_from_filepath", side_effect=["x86_64", None]),
            patch("pulp_tool.utils.artifact_detection.detect_arch_from_rpm_filename", side_effect=["aarch64", None]),
            patch("pulp_tool.upload.pipeline.upload_rpms", return_value=["/rpm/resource/1"]) as mock_upload_rpms,
            patch("pulp_tool.upload.results.collect_results", return_value="https://example.com/results.json"),
        ):
            mock_ph_cls.return_value.get_distribution_urls_for_upload_context.return_value = (
                _PROCESS_FILE_UPLOAD_DIST_URLS
            )
            result = orchestrator.process_file_uploads(mock_client, context, repositories)
            assert result == "https://example.com/results.json"
            assert mock_upload_rpms.call_count == 2

    def test_process_file_uploads_rpms_skip_undetected_arch(self) -> None:
        """Test process_file_uploads skips RPMs with undetected architecture."""
        orchestrator = UploadOrchestrator()
        context = UploadFilesContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_files=["/path/to/package.rpm"],
        )
        mock_client = Mock()
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        with (
            patch("pulp_tool.utils.pulp_helper.PulpHelper") as mock_ph_cls,
            patch("pulp_tool.utils.artifact_detection.detect_arch_from_filepath", return_value=None),
            patch("pulp_tool.utils.artifact_detection.detect_arch_from_rpm_filename", return_value=None),
            patch("pulp_tool.upload.pipeline.upload_rpms") as mock_upload_rpms,
            patch("pulp_tool.upload.results.collect_results", return_value="https://example.com/results.json"),
            patch("pulp_tool.utils.artifact_detection.logging") as mock_logging,
        ):
            mock_ph_cls.return_value.get_distribution_urls_for_upload_context.return_value = (
                _PROCESS_FILE_UPLOAD_DIST_URLS
            )
            result = orchestrator.process_file_uploads(mock_client, context, repositories)
            assert result == "https://example.com/results.json"
            mock_upload_rpms.assert_not_called()
            mock_logging.warning.assert_called()

    def test_process_file_uploads_rpms_with_provided_arch(self) -> None:
        """Test process_file_uploads with RPMs using provided architecture."""
        orchestrator = UploadOrchestrator()
        context = UploadFilesContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_files=["/path/to/package.rpm"],
            arch="x86_64",
        )
        mock_client = Mock()
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        with (
            patch("pulp_tool.utils.pulp_helper.PulpHelper") as mock_ph_cls,
            patch("pulp_tool.upload.pipeline.upload_rpms", return_value=["/rpm/resource/1"]) as mock_upload_rpms,
            patch("pulp_tool.upload.results.collect_results", return_value="https://example.com/results.json"),
        ):
            mock_ph_cls.return_value.get_distribution_urls_for_upload_context.return_value = (
                _PROCESS_FILE_UPLOAD_DIST_URLS
            )
            result = orchestrator.process_file_uploads(mock_client, context, repositories)
            assert result == "https://example.com/results.json"
            mock_upload_rpms.assert_called_once()
            call_args = mock_upload_rpms.call_args
            assert call_args[0][3] == "x86_64"

    def test_process_file_uploads_logs_with_arch_detection(self) -> None:
        """Test process_file_uploads with logs using architecture detection."""
        orchestrator = UploadOrchestrator()
        context = UploadFilesContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            log_files=["/path/to/x86_64/build.log"],
        )
        mock_client = Mock()
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        with (
            patch("pulp_tool.utils.pulp_helper.PulpHelper") as mock_ph_cls,
            patch("pulp_tool.utils.artifact_detection.detect_arch_from_filepath", return_value="x86_64"),
            patch("pulp_tool.upload.pipeline.upload_log", return_value=["/log/resource/1"]) as mock_upload_log,
            patch("pulp_tool.upload.results.collect_results", return_value="https://example.com/results.json"),
            patch("pulp_tool.upload.pipeline.create_labels"),
        ):
            mock_ph_cls.return_value.get_distribution_urls_for_upload_context.return_value = (
                _PROCESS_FILE_UPLOAD_DIST_URLS
            )
            result = orchestrator.process_file_uploads(mock_client, context, repositories)
            assert result == "https://example.com/results.json"
            mock_upload_log.assert_called_once()
            call_args = mock_upload_log.call_args
            assert call_args[1]["arch"] == "x86_64"

    def test_process_file_uploads_logs_skip_undetected_arch(self) -> None:
        """Test process_file_uploads skips logs with undetected architecture."""
        orchestrator = UploadOrchestrator()
        context = UploadFilesContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            log_files=["/path/to/build.log"],
        )
        mock_client = Mock()
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        with (
            patch("pulp_tool.utils.pulp_helper.PulpHelper") as mock_ph_cls,
            patch("pulp_tool.utils.artifact_detection.detect_arch_from_filepath", return_value=None),
            patch("pulp_tool.upload.pipeline.upload_log") as mock_upload_log,
            patch("pulp_tool.upload.results.collect_results", return_value="https://example.com/results.json"),
            patch("pulp_tool.upload.pipeline.logging") as mock_logging,
        ):
            mock_ph_cls.return_value.get_distribution_urls_for_upload_context.return_value = (
                _PROCESS_FILE_UPLOAD_DIST_URLS
            )
            result = orchestrator.process_file_uploads(mock_client, context, repositories)
            assert result == "https://example.com/results.json"
            mock_upload_log.assert_not_called()
            mock_logging.warning.assert_called()
            warning_calls = [call for call in mock_logging.warning.call_args_list if "Skipping" in str(call)]
            assert len(warning_calls) > 0

    def test_process_file_uploads_logs_with_provided_arch(self) -> None:
        """Test process_file_uploads with logs using provided architecture."""
        orchestrator = UploadOrchestrator()
        context = UploadFilesContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            log_files=["/path/to/build.log"],
            arch="x86_64",
        )
        mock_client = Mock()
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        with (
            patch("pulp_tool.utils.pulp_helper.PulpHelper") as mock_ph_cls,
            patch("pulp_tool.upload.pipeline.upload_log", return_value=["/log/resource/1"]) as mock_upload_log,
            patch("pulp_tool.upload.results.collect_results", return_value="https://example.com/results.json"),
            patch("pulp_tool.upload.pipeline.create_labels"),
        ):
            mock_ph_cls.return_value.get_distribution_urls_for_upload_context.return_value = (
                _PROCESS_FILE_UPLOAD_DIST_URLS
            )
            result = orchestrator.process_file_uploads(mock_client, context, repositories)
            assert result == "https://example.com/results.json"
            mock_upload_log.assert_called_once()
            call_args = mock_upload_log.call_args
            assert call_args[1]["arch"] == "x86_64"

    def test_process_file_uploads_multiple_architectures(self) -> None:
        """Test process_file_uploads with RPMs from multiple architectures."""
        orchestrator = UploadOrchestrator()
        context = UploadFilesContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_files=["/path/to/package1-1.0.0-1.x86_64.rpm", "/path/to/package2-1.0.0-1.aarch64.rpm"],
        )
        mock_client = Mock()
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        with (
            patch("pulp_tool.utils.pulp_helper.PulpHelper") as mock_ph_cls,
            patch("pulp_tool.utils.artifact_detection.detect_arch_from_filepath", return_value=None),
            patch(
                "pulp_tool.utils.artifact_detection.detect_arch_from_rpm_filename", side_effect=["x86_64", "aarch64"]
            ),
            patch("pulp_tool.upload.pipeline.upload_rpms", return_value=["/rpm/resource/1"]) as mock_upload_rpms,
            patch("pulp_tool.upload.results.collect_results", return_value="https://example.com/results.json"),
        ):
            mock_ph_cls.return_value.get_distribution_urls_for_upload_context.return_value = (
                _PROCESS_FILE_UPLOAD_DIST_URLS
            )
            result = orchestrator.process_file_uploads(mock_client, context, repositories)
            assert result == "https://example.com/results.json"
            assert mock_upload_rpms.call_count == 2
            call_args_list = mock_upload_rpms.call_args_list
            archs = [call[0][3] for call in call_args_list]
            assert "x86_64" in archs
            assert "aarch64" in archs


class TestUploadOrchestratorTargetArchRepo:
    """process_uploads with --target-arch-repo."""

    def test_process_uploads_target_arch_repo_requires_pulp_helper(self) -> None:
        """Per-arch mode requires pulp_helper for ensure_rpm_repository_for_arch."""
        orchestrator = UploadOrchestrator()
        args = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package=None,
            rpm_path="/test/rpms",
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
            artifacts_prn="artifacts-prn",
        )
        with pytest.raises(ValueError, match="target_arch_repo requires PulpHelper"):
            orchestrator.process_uploads(mock_client, args, repositories)

    def test_process_uploads_target_arch_repo_allows_empty_rpms_href(self) -> None:
        """Bulk rpms_href may be empty when per-arch repos are created on demand."""
        orchestrator = UploadOrchestrator()
        args = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package=None,
            rpm_path="/test/rpms",
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
            artifacts_prn="artifacts-prn",
        )
        mock_helper = Mock()
        mock_helper.ensure_rpm_repository_for_arch.return_value = "/per-arch/rpm"
        with (
            patch.object(orchestrator, "process_architecture_uploads", return_value={}),
            patch("pulp_tool.upload.results.collect_results", return_value="https://example.com/results.json"),
        ):
            result = orchestrator.process_uploads(mock_client, args, repositories, pulp_helper=mock_helper)
        assert result == "https://example.com/results.json"


class TestUploadOrchestratorProcessUploads:
    """Tests for UploadOrchestrator.process_uploads() method."""

    def test_process_uploads_success(self) -> None:
        """Test process_uploads processes all uploads (lines 210-252)."""
        orchestrator = UploadOrchestrator()
        args = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/test/rpms",
            sbom_path="/test/sbom.json",
        )
        mock_client = Mock()
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="",
        )
        mock_processed_uploads = {
            "x86_64": RpmUploadResult(created_resources=["/resource/1", "/resource/2"]),
            "aarch64": RpmUploadResult(created_resources=["/resource/3"]),
        }
        with (
            patch("pulp_tool.utils.pulp_helper.PulpHelper") as mock_ph_cls,
            patch.object(orchestrator, "process_architecture_uploads", return_value=mock_processed_uploads),
            patch("pulp_tool.upload.sbom.upload_sbom", return_value=["/sbom/resource/1"]),
            patch("pulp_tool.upload.results.collect_results", return_value="https://example.com/results.json"),
            patch("pulp_tool.upload.pipeline.logging") as mock_logging,
        ):
            mock_ph_cls.return_value.get_distribution_urls_for_upload_context.return_value = {
                "rpms": "https://example.com/rpms/",
                "logs": "https://example.com/logs/",
                "sbom": "https://example.com/sbom/",
                "artifacts": "https://example.com/artifacts/",
            }
            result = orchestrator.process_uploads(mock_client, args, repositories)
            assert result == "https://example.com/results.json"
            assert mock_logging.info.call_count >= 2
            assert mock_logging.debug.call_count >= 1

    def test_process_uploads_missing_rpm_href(self) -> None:
        """Test process_uploads raises ValueError when rpms_href is missing (lines 213-214)."""
        orchestrator = UploadOrchestrator()
        args = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/test/rpms",
            sbom_path="/test/sbom.json",
        )
        mock_client = Mock()
        repositories = RepositoryRefs(
            rpms_href="",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        with pytest.raises(ValueError, match="RPM repository href is required"):
            orchestrator.process_uploads(mock_client, args, repositories)

    def test_process_uploads_signed_by_missing_signed_repo_href(self) -> None:
        """Test process_uploads raises when signed_by is set but rpms_signed_href is missing."""
        orchestrator = UploadOrchestrator()
        args = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/test/rpms",
            sbom_path="/test/sbom.json",
            signed_by="test-key-id",
        )
        mock_client = Mock()
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="",
            rpms_signed_href="",
            rpms_signed_prn="",
        )
        with pytest.raises(ValueError, match="signed_by requires signed RPM repository href"):
            orchestrator.process_uploads(mock_client, args, repositories)

    def test_rpm_repository_href_for_upload_requires_unsigned_href(self) -> None:
        """_rpm_repository_href_for_upload raises when unsigned upload has no rpms_href."""
        args = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/test/rpms",
        )
        repositories = RepositoryRefs(
            rpms_href="",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        with pytest.raises(ValueError, match="RPM repository href is required"):
            repositories.rpm_href_for_upload(args)

    def test_rpm_repository_href_for_upload_requires_signed_href(self) -> None:
        """_rpm_repository_href_for_upload raises when signed_by is set without rpms_signed_href."""
        args = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/test/rpms",
            signed_by="test-key-id",
        )
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
            rpms_signed_href="",
            rpms_signed_prn="",
        )
        with pytest.raises(ValueError, match="signed_by requires signed RPM repository href"):
            repositories.rpm_href_for_upload(args)

    def test_process_uploads_with_no_created_resources(self) -> None:
        """Test process_uploads handles empty created_resources."""
        orchestrator = UploadOrchestrator()
        args = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/test/rpms",
            sbom_path="/test/sbom.json",
        )
        mock_client = Mock()
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="",
        )
        mock_processed_uploads: dict[str, RpmUploadResult] = {"x86_64": RpmUploadResult()}
        with (
            patch("pulp_tool.utils.pulp_helper.PulpHelper") as mock_ph_cls,
            patch.object(orchestrator, "process_architecture_uploads", return_value=mock_processed_uploads),
            patch("pulp_tool.upload.sbom.upload_sbom", return_value=[]),
            patch("pulp_tool.upload.results.collect_results", return_value="https://example.com/results.json"),
            patch("pulp_tool.upload.pipeline.logging") as mock_logging,
        ):
            mock_ph_cls.return_value.get_distribution_urls_for_upload_context.return_value = {
                "rpms": "https://example.com/rpms/",
                "logs": "https://example.com/logs/",
                "sbom": "https://example.com/sbom/",
                "artifacts": "https://example.com/artifacts/",
            }
            result = orchestrator.process_uploads(mock_client, args, repositories)
            assert result == "https://example.com/results.json"
            assert mock_logging.info.call_count >= 1

    def test_process_uploads_without_sbom_path(self) -> None:
        """Test process_uploads when sbom_path is None (line 249)."""
        orchestrator = UploadOrchestrator()
        args = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/test/rpms",
            sbom_path=None,
        )
        mock_client = Mock()
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="",
        )
        mock_processed_uploads: dict[str, RpmUploadResult] = {
            "x86_64": RpmUploadResult(created_resources=["/resource/1"])
        }
        with (
            patch("pulp_tool.utils.pulp_helper.PulpHelper") as mock_ph_cls,
            patch.object(orchestrator, "process_architecture_uploads", return_value=mock_processed_uploads),
            patch("pulp_tool.upload.results.collect_results", return_value="https://example.com/results.json"),
            patch("pulp_tool.upload.pipeline.logging") as mock_logging,
        ):
            mock_ph_cls.return_value.get_distribution_urls_for_upload_context.return_value = {
                "rpms": "https://example.com/rpms/",
                "logs": "https://example.com/logs/",
                "sbom": "https://example.com/sbom/",
                "artifacts": "https://example.com/artifacts/",
            }
            result = orchestrator.process_uploads(mock_client, args, repositories)
            assert result == "https://example.com/results.json"
            mock_logging.debug.assert_any_call("Skipping SBOM upload - no sbom_path provided")
            assert mock_logging.info.call_count >= 1

    def test_process_uploads_root_level_rpms(self) -> None:
        """Test process_uploads uploads root-level RPMs when present in rpm_path (lines 241-265)."""
        orchestrator = UploadOrchestrator()
        args = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/test/rpms",
            sbom_path="/test/sbom.json",
        )
        mock_client = Mock()
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="",
        )
        mock_processed_uploads: dict[str, RpmUploadResult] = {"x86_64": RpmUploadResult()}
        root_rpm_files = ["/test/rpms/pkg.noarch.rpm"]
        with (
            patch("pulp_tool.utils.pulp_helper.PulpHelper") as mock_ph_cls,
            patch.object(orchestrator, "process_architecture_uploads", return_value=mock_processed_uploads),
            patch("pulp_tool.upload.pipeline.glob.glob", return_value=root_rpm_files),
            patch("pulp_tool.upload.pipeline.os.path.isfile", return_value=True),
            patch("pulp_tool.upload.pipeline.group_rpm_paths_by_arch", return_value={"noarch": root_rpm_files}),
            patch("pulp_tool.upload.pipeline.upload_rpms", return_value=["/rpm/resource/1"]) as mock_upload_rpms,
            patch("pulp_tool.upload.sbom.upload_sbom", return_value=[]),
            patch("pulp_tool.upload.results.collect_results", return_value="https://example.com/results.json"),
        ):
            mock_ph_cls.return_value.get_distribution_urls_for_upload_context.return_value = {
                "rpms": "https://example.com/rpms/",
                "logs": "https://example.com/logs/",
                "sbom": "https://example.com/sbom/",
                "artifacts": "https://example.com/artifacts/",
            }
            result = orchestrator.process_uploads(mock_client, args, repositories)
            assert result == "https://example.com/results.json"
            mock_upload_rpms.assert_called_once()
            call_pos, call_kw = mock_upload_rpms.call_args
            assert call_pos[3] == "noarch"
            assert call_kw["rpm_repository_href"] == "/test/rpm-href"

    def test_process_uploads_root_level_rpms_target_arch_repo(self) -> None:
        """Root-level RPMs use ensure_rpm_repository_for_arch when target_arch_repo is set."""
        orchestrator = UploadOrchestrator()
        args = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/test/rpms",
            sbom_path="/test/sbom.json",
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
        mock_helper = Mock()
        mock_helper.ensure_rpm_repository_for_arch.return_value = "/per-arch/href"
        mock_helper.get_distribution_urls_for_upload_context.return_value = {
            "rpms": "https://example.com/rpms/",
            "logs": "https://example.com/logs/",
            "sbom": "https://example.com/sbom/",
            "artifacts": "https://example.com/artifacts/",
        }
        mock_processed_uploads: dict[str, RpmUploadResult] = {"x86_64": RpmUploadResult()}
        root_rpm_files = ["/test/rpms/pkg.noarch.rpm"]
        with (
            patch.object(orchestrator, "process_architecture_uploads", return_value=mock_processed_uploads),
            patch("pulp_tool.upload.pipeline.glob.glob", return_value=root_rpm_files),
            patch("pulp_tool.upload.pipeline.os.path.isfile", return_value=True),
            patch("pulp_tool.upload.pipeline.group_rpm_paths_by_arch", return_value={"noarch": root_rpm_files}),
            patch("pulp_tool.upload.pipeline.upload_rpms", return_value=["/rpm/resource/1"]) as mock_upload_rpms,
            patch("pulp_tool.upload.sbom.upload_sbom", return_value=[]),
            patch("pulp_tool.upload.results.collect_results", return_value="https://example.com/results.json"),
        ):
            result = orchestrator.process_uploads(mock_client, args, repositories, pulp_helper=mock_helper)
            assert result == "https://example.com/results.json"
            mock_upload_rpms.assert_called_once()
            _call_pos, call_kw = mock_upload_rpms.call_args
            assert call_kw["rpm_repository_href"] == "/per-arch/href"
            mock_helper.ensure_rpm_repository_for_arch.assert_called_once()

    def test_process_architecture_uploads_target_arch_repo_requires_pulp_helper(self) -> None:
        """process_architecture_uploads raises when target_arch_repo set but pulp_helper is None."""
        orchestrator = UploadOrchestrator()
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
            with pytest.raises(ValueError, match="target_arch_repo requires PulpHelper"):
                orchestrator.process_architecture_uploads(
                    mock_client,
                    args,
                    repositories,
                    date_str="2024-01-01",
                    rpm_href="",
                    results_model=results_model,
                    distribution_urls={},
                    pulp_helper=None,
                )

    def test_process_uploads_signed_by_uses_rpms_signed_href(self) -> None:
        """Test process_uploads routes RPMs to the signed repository when signed_by is set."""
        orchestrator = UploadOrchestrator()
        args = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/test/rpms",
            sbom_path="/test/sbom.json",
            signed_by="test-key-id",
        )
        mock_client = Mock()
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="",
            rpms_signed_href="/test/rpm-signed-href",
            rpms_signed_prn="rpms-signed-prn",
        )
        with (
            patch("pulp_tool.utils.pulp_helper.PulpHelper") as mock_ph_cls,
            patch.object(orchestrator, "process_architecture_uploads", return_value={}) as mock_arch,
            patch("pulp_tool.upload.sbom.upload_sbom", return_value=[]),
            patch("pulp_tool.upload.results.collect_results", return_value="https://example.com/results.json"),
        ):
            mock_ph_cls.return_value.get_distribution_urls_for_upload_context.return_value = {}
            orchestrator.process_uploads(mock_client, args, repositories)
        assert mock_arch.call_args[1]["rpm_href"] == "/test/rpm-signed-href"

    def test_process_uploads_with_results_json(self) -> None:
        """Test process_uploads calls process_uploads_from_results_json when results_json is set."""
        orchestrator = UploadOrchestrator()
        args = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/test/rpms",
            sbom_path="/test/sbom.json",
            results_json="/test/pulp_results.json",
        )
        mock_client = Mock()
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="",
        )
        with patch(
            "pulp_tool.upload.batch_json.process_uploads_from_results_json",
            return_value="https://example.com/results-from-json.json",
        ) as mock_from_json:
            result = orchestrator.process_uploads(mock_client, args, repositories)
        assert result == "https://example.com/results-from-json.json"
        mock_from_json.assert_called_once_with(mock_client, args, repositories, pulp_helper=None)

    def test_process_uploads_results_json_model_returns_none(self) -> None:
        from pulp_tool.models.pulp_results import PulpResultsDocument

        orchestrator = UploadOrchestrator()
        args = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            results_json="/test/pulp_results.json",
        )
        repositories = RepositoryRefs(
            rpms_href="/r",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        model = PulpResultsDocument(build_id="test-build", repositories=repositories)
        with patch(
            "pulp_tool.upload.batch_json.process_uploads_from_results_json",
            return_value=model,
        ):
            assert orchestrator.process_uploads(Mock(), args, repositories) is None
