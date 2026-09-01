"""Tests for UploadOrchestrator process_uploads."""

import os
import tempfile
from unittest.mock import Mock, patch

import pytest

from pulp_tool.models.context import UploadRpmContext
from pulp_tool.models.repository import RepositoryRefs
from pulp_tool.models.results import PulpResultsModel, RpmUploadResult
from pulp_tool.utils.upload_orchestrator import (
    UploadOrchestrator,
    _rpm_repository_href_for_upload,
)


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
            patch("pulp_tool.services.upload_service.upload_sbom", return_value=["/sbom/resource/1"]),
            patch("pulp_tool.services.upload_service.collect_results", return_value="https://example.com/results.json"),
            patch("pulp_tool.utils.upload_orchestrator.logging") as mock_logging,
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
            _rpm_repository_href_for_upload(args, repositories)

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
            _rpm_repository_href_for_upload(args, repositories)

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
            patch("pulp_tool.services.upload_service.upload_sbom", return_value=[]),
            patch("pulp_tool.services.upload_service.collect_results", return_value="https://example.com/results.json"),
            patch("pulp_tool.utils.upload_orchestrator.logging") as mock_logging,
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
            patch("pulp_tool.services.upload_service.collect_results", return_value="https://example.com/results.json"),
            patch("pulp_tool.utils.upload_orchestrator.logging") as mock_logging,
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
            patch("pulp_tool.utils.upload_orchestrator.glob.glob", return_value=root_rpm_files),
            patch("pulp_tool.utils.upload_orchestrator.os.path.isfile", return_value=True),
            patch(
                "pulp_tool.utils.upload_orchestrator.group_rpm_paths_by_arch", return_value={"noarch": root_rpm_files}
            ),
            patch(
                "pulp_tool.utils.upload_orchestrator.upload_rpms", return_value=["/rpm/resource/1"]
            ) as mock_upload_rpms,
            patch("pulp_tool.services.upload_service.upload_sbom", return_value=[]),
            patch("pulp_tool.services.upload_service.collect_results", return_value="https://example.com/results.json"),
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
            patch("pulp_tool.utils.upload_orchestrator.glob.glob", return_value=root_rpm_files),
            patch("pulp_tool.utils.upload_orchestrator.os.path.isfile", return_value=True),
            patch(
                "pulp_tool.utils.upload_orchestrator.group_rpm_paths_by_arch", return_value={"noarch": root_rpm_files}
            ),
            patch(
                "pulp_tool.utils.upload_orchestrator.upload_rpms", return_value=["/rpm/resource/1"]
            ) as mock_upload_rpms,
            patch("pulp_tool.services.upload_service.upload_sbom", return_value=[]),
            patch("pulp_tool.services.upload_service.collect_results", return_value="https://example.com/results.json"),
        ):
            result = orchestrator.process_uploads(mock_client, args, repositories, pulp_helper=mock_helper)
            assert result == "https://example.com/results.json"
            mock_upload_rpms.assert_called_once()
            _call_pos, call_kw = mock_upload_rpms.call_args
            assert call_kw["rpm_repository_href"] == "/per-arch/href"
            mock_helper.ensure_rpm_repository_for_arch.assert_called_once_with("test-build", "noarch")

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
        results_model = PulpResultsModel(build_id="test-build", repositories=repositories)
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
            patch("pulp_tool.services.upload_service.upload_sbom", return_value=[]),
            patch("pulp_tool.services.upload_service.collect_results", return_value="https://example.com/results.json"),
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
            "pulp_tool.services.upload_service.process_uploads_from_results_json",
            return_value="https://example.com/results-from-json.json",
        ) as mock_from_json:
            result = orchestrator.process_uploads(mock_client, args, repositories)
        assert result == "https://example.com/results-from-json.json"
        mock_from_json.assert_called_once_with(mock_client, args, repositories, pulp_helper=None)
