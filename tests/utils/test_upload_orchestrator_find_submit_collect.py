"""Tests for UploadOrchestrator find/submit/collect paths."""

import os
import tempfile
from concurrent.futures import Future
from typing import Any
from unittest.mock import Mock, patch

import pytest

from pulp_tool.models.context import UploadRpmContext
from pulp_tool.models.pulp_results import PulpResultsDocument
from pulp_tool.models.repository import RepositoryRefs
from pulp_tool.models.results import RpmUploadResult
from pulp_tool.utils.upload_orchestrator import UploadOrchestrator


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
            with patch("pulp_tool.utils.upload_orchestrator.logging") as mock_logging:
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
        with patch("pulp_tool.utils.upload_orchestrator.upload_rpms_logs"):
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
        with patch("pulp_tool.utils.upload_orchestrator.logging") as mock_logging:
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
        with patch("pulp_tool.utils.upload_orchestrator.handle_generic_error") as mock_handle_error:
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
        with patch("pulp_tool.utils.upload_orchestrator.logging") as mock_logging:
            orchestrator._collect_architecture_results(future_to_arch)
            debug_calls = [str(call) for call in mock_logging.debug.call_args_list]
            assert any("Processed architectures" in str(call) for call in debug_calls)
