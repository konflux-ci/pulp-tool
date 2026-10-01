"""Tests for upload pipeline (process_uploads_from_results_json)."""

import json
import logging
from unittest.mock import Mock, patch

import pytest

from pulp_tool.models import RepositoryRefs
from pulp_tool.models.context import UploadRpmContext
from pulp_tool.models.pulp_results import PulpResultsDocument
from pulp_tool.services.upload_service import (
    process_uploads_from_results_json,
)


class TestProcessUploadsFromResultsJson:
    """Test process_uploads_from_results_json function."""

    def test_raises_when_logs_present_but_logs_repo_skipped(self, tmp_path, mock_pulp_client) -> None:
        """Guard: log uploads require logs_prn."""
        arch_dir = tmp_path / "x86_64"
        arch_dir.mkdir()
        log_path = arch_dir / "build.log"
        log_path.write_text("log line")
        results_json_path = tmp_path / "pulp_results.json"
        results_json_path.write_text(
            json.dumps({"artifacts": {"x86_64/build.log": {"pulp_labels": {"arch": "x86_64"}}}})
        )
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
            skip_logs_repo=True,
        )
        repositories = RepositoryRefs(
            rpms_href="/rpm",
            rpms_prn="rprn",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
        )
        with pytest.raises(ValueError, match="logs repository was not created"):
            process_uploads_from_results_json(mock_pulp_client, context, repositories)

    def test_raises_when_sbom_present_but_sbom_repo_skipped(self, tmp_path, mock_pulp_client) -> None:
        sbom_path = tmp_path / "sbom.spdx.json"
        sbom_path.write_text("{}")
        results_json_path = tmp_path / "pulp_results.json"
        results_json_path.write_text(json.dumps({"artifacts": {"sbom.spdx.json": {}}}))
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
            skip_sbom_repo=True,
        )
        repositories = RepositoryRefs(
            rpms_href="/rpm",
            rpms_prn="rprn",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
        )
        with pytest.raises(ValueError, match="SBOM repository was not created"):
            process_uploads_from_results_json(mock_pulp_client, context, repositories)

    def test_upload_from_results_json_basic(self, tmp_path, mock_pulp_client) -> None:
        """Test upload from JSON without signed-by."""
        rpm_file = tmp_path / "x86_64" / "pkg.rpm"
        rpm_file.parent.mkdir()
        rpm_file.write_bytes(b"fake rpm content")
        results_json_path = tmp_path / "pulp_results.json"
        results_data = {"artifacts": {"x86_64/pkg.rpm": {"pulp_labels": {"arch": "x86_64"}}}}
        results_json_path.write_text(json.dumps(results_data))
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
        )
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
            patch("pulp_tool.utils.uploads.upload_rpms", return_value=["/rpm/resource/1"]),
            patch("pulp_tool.services.upload_service.collect_results", return_value="https://example.com/results.json"),
        ):
            result = process_uploads_from_results_json(mock_pulp_client, context, repositories)
        assert result == "https://example.com/results.json"

    def test_upload_from_results_json_with_signed_by(self, tmp_path, mock_pulp_client) -> None:
        """Test upload with signed-by uses signed repos and labels."""
        rpm_file = tmp_path / "x86_64" / "pkg.rpm"
        rpm_file.parent.mkdir()
        rpm_file.write_bytes(b"fake rpm content")
        results_json_path = tmp_path / "pulp_results.json"
        results_data = {"artifacts": {"x86_64/pkg.rpm": {"pulp_labels": {"arch": "x86_64"}}}}
        results_json_path.write_text(json.dumps(results_data))
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
            signed_by="key-123",
        )
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
            rpms_signed_href="/test/rpm-signed-href",
            rpms_signed_prn="rpms-signed-prn",
            logs_signed_prn="logs-signed-prn",
            sbom_signed_prn="sbom-signed-prn",
            artifacts_signed_prn="artifacts-signed-prn",
        )
        with (
            patch("pulp_tool.utils.uploads.upload_rpms", return_value=["/rpm/resource/1"]) as mock_upload_rpms,
            patch("pulp_tool.services.upload_service.collect_results", return_value="https://example.com/results.json"),
        ):
            result = process_uploads_from_results_json(mock_pulp_client, context, repositories)
        assert result == "https://example.com/results.json"
        mock_upload_rpms.assert_called_once()
        call_kw = mock_upload_rpms.call_args[1]
        assert call_kw["rpm_repository_href"] == "/test/rpm-signed-href"
        call_context = mock_upload_rpms.call_args[0][1]
        assert call_context.signed_by == "key-123"

    def test_upload_from_results_json_target_arch_repo_uses_ensure_per_arch(self, tmp_path, mock_pulp_client) -> None:
        """target_arch_repo sets bulk rpm_href empty and uses ensure_rpm_repository_for_arch per arch."""
        rpm_file = tmp_path / "x86_64" / "pkg.rpm"
        rpm_file.parent.mkdir()
        rpm_file.write_bytes(b"x")
        results_json_path = tmp_path / "pulp_results.json"
        results_data = {"artifacts": {"x86_64/pkg.rpm": {"pulp_labels": {"arch": "x86_64"}}}}
        results_json_path.write_text(json.dumps(results_data))
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
            target_arch_repo=True,
        )
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
        mock_ph_instance = Mock()
        mock_ph_instance.ensure_rpm_repository_for_arch.return_value = "/per-arch/rpm"
        with (
            patch("pulp_tool.services.upload_service.PulpHelper", return_value=mock_ph_instance),
            patch("pulp_tool.utils.uploads.upload_rpms", return_value=["/r/1"]) as mock_upload_rpms,
            patch("pulp_tool.services.upload_service.collect_results", return_value="https://example.com/r.json"),
        ):
            result = process_uploads_from_results_json(
                mock_pulp_client, context, repositories, pulp_helper=mock_ph_instance
            )
        assert result == "https://example.com/r.json"
        mock_ph_instance.ensure_rpm_repository_for_arch.assert_called_once_with("test-build", "x86_64")
        assert mock_upload_rpms.call_args.kwargs["rpm_repository_href"] == "/per-arch/rpm"

    def test_upload_from_results_json_files_base_path(self, tmp_path, mock_pulp_client) -> None:
        """Test override base path for resolving artifact keys."""
        base_dir = tmp_path / "files"
        base_dir.mkdir()
        rpm_file = base_dir / "x86_64" / "pkg.rpm"
        rpm_file.parent.mkdir()
        rpm_file.write_bytes(b"fake rpm content")
        results_json_path = tmp_path / "pulp_results.json"
        results_data = {"artifacts": {"x86_64/pkg.rpm": {"pulp_labels": {"arch": "x86_64"}}}}
        results_json_path.write_text(json.dumps(results_data))
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
            files_base_path=str(base_dir),
        )
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
            patch("pulp_tool.utils.uploads.upload_rpms", return_value=["/rpm/resource/1"]),
            patch("pulp_tool.services.upload_service.collect_results", return_value="https://example.com/results.json"),
        ):
            result = process_uploads_from_results_json(mock_pulp_client, context, repositories)
        assert result == "https://example.com/results.json"

    def test_upload_from_results_json_missing_file(self, tmp_path, mock_pulp_client, caplog) -> None:
        """Test handling of missing file - skip with warning."""
        results_json_path = tmp_path / "pulp_results.json"
        results_data = {"artifacts": {"x86_64/pkg.rpm": {"pulp_labels": {"arch": "x86_64"}}}}
        results_json_path.write_text(json.dumps(results_data))
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
        )
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
            patch("pulp_tool.utils.uploads.upload_rpms", return_value=[]),
            patch("pulp_tool.services.upload_service.collect_results", return_value="https://example.com/results.json"),
            caplog.at_level(logging.WARNING),
        ):
            result = process_uploads_from_results_json(mock_pulp_client, context, repositories)
        assert result == "https://example.com/results.json"
        assert "Skipping missing file" in caplog.text

    def test_upload_from_results_json_empty_artifacts(self, tmp_path, mock_pulp_client) -> None:
        """Test empty artifacts creates minimal results."""
        results_json_path = tmp_path / "pulp_results.json"
        results_data: dict = {"artifacts": {}}
        results_json_path.write_text(json.dumps(results_data))
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
        )
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
        with patch(
            "pulp_tool.services.upload_service.collect_results", return_value="https://example.com/results.json"
        ):
            result = process_uploads_from_results_json(mock_pulp_client, context, repositories)
        assert result == "https://example.com/results.json"

    def test_upload_from_results_json_returns_none_when_no_results_json(self, mock_pulp_client) -> None:
        """Test returns None when results_json is not set."""
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=None,
        )
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
        result = process_uploads_from_results_json(mock_pulp_client, context, repositories)
        assert result is None

    def test_upload_from_results_json_json_read_error(self, tmp_path, mock_pulp_client) -> None:
        """Test process_uploads_from_results_json raises when JSON cannot be read."""
        results_json_path = tmp_path / "pulp_results.json"
        results_json_path.write_text('{"artifacts": {"x": {}}}')
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
        )
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
        with patch("builtins.open", side_effect=OSError("Permission denied")):
            with pytest.raises(OSError, match="Permission denied"):
                process_uploads_from_results_json(mock_pulp_client, context, repositories)

    def test_upload_from_results_json_signed_by_no_signed_repos(self, tmp_path, mock_pulp_client) -> None:
        """Test process_uploads_from_results_json raises when signed_by set but no signed repos."""
        rpm_file = tmp_path / "x86_64" / "pkg.rpm"
        rpm_file.parent.mkdir()
        rpm_file.write_bytes(b"fake rpm")
        results_json_path = tmp_path / "pulp_results.json"
        results_json_path.write_text(json.dumps({"artifacts": {"x86_64/pkg.rpm": {"pulp_labels": {"arch": "x86_64"}}}}))
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
            signed_by="key-123",
        )
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
            rpms_signed_href="",
            rpms_signed_prn="",
        )
        with pytest.raises(ValueError, match="signed_by requires signed repositories"):
            process_uploads_from_results_json(mock_pulp_client, context, repositories)

    def test_upload_from_results_json_invalid_artifact_entry(self, tmp_path, mock_pulp_client) -> None:
        """Non-dict artifact rows are dropped during ``from_raw`` normalization."""
        rpm_file = tmp_path / "pkg.rpm"
        rpm_file.write_bytes(b"fake rpm")
        results_json_path = tmp_path / "pulp_results.json"
        results_json_path.write_text(
            json.dumps({"artifacts": {"pkg.rpm": {"pulp_labels": {"arch": "noarch"}}, "bad": "not a dict"}})
        )
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
        )
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
            patch("pulp_tool.utils.uploads.upload_rpms", return_value=["/rpm/1"]),
            patch("pulp_tool.services.upload_service.collect_results", return_value="https://example.com/results.json"),
        ):
            result = process_uploads_from_results_json(mock_pulp_client, context, repositories)
        assert result == "https://example.com/results.json"

    def test_upload_from_results_json_log_and_sbom_and_artifact(self, tmp_path, mock_pulp_client) -> None:
        """Test process_uploads_from_results_json with log, sbom, and generic artifact."""
        log_file = tmp_path / "x86_64" / "state.log"
        log_file.parent.mkdir()
        log_file.write_text("log content")
        sbom_file = tmp_path / "sbom.json"
        sbom_file.write_text('{"sbom": true}')
        artifact_file = tmp_path / "data.txt"
        artifact_file.write_text("data")
        results_json_path = tmp_path / "pulp_results.json"
        results_json_path.write_text(
            json.dumps(
                {
                    "artifacts": {
                        "x86_64/state.log": {"pulp_labels": {"arch": "x86_64"}},
                        "sbom.json": {"pulp_labels": {}},
                        "data.txt": {"pulp_labels": {}},
                    }
                }
            )
        )
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
        )
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
        mock_resp = Mock()
        mock_resp.json.return_value = {"task": "/tasks/1/"}
        mock_task = Mock()
        mock_task.created_resources = ["/content/1/"]
        mock_pulp_client.create_file_content = Mock(return_value=mock_resp)
        mock_pulp_client.wait_for_finished_task = Mock(return_value=mock_task)
        mock_pulp_client.check_response = Mock()
        with (
            patch("pulp_tool.utils.uploads.upload_log", return_value=["/log/1"]),
            patch("pulp_tool.services.upload_service.collect_results", return_value="https://example.com/results.json"),
        ):
            result = process_uploads_from_results_json(mock_pulp_client, context, repositories)
        assert result == "https://example.com/results.json"

    def test_upload_from_results_json_arch_inference_from_path(self, tmp_path, mock_pulp_client) -> None:
        """Test process_uploads_from_results_json infers arch from path when not in labels."""
        rpm_file = tmp_path / "aarch64" / "pkg.rpm"
        rpm_file.parent.mkdir()
        rpm_file.write_bytes(b"fake rpm")
        results_json_path = tmp_path / "pulp_results.json"
        results_json_path.write_text(json.dumps({"artifacts": {"aarch64/pkg.rpm": {"pulp_labels": {}}}}))
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
        )
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
            patch("pulp_tool.utils.uploads.upload_rpms", return_value=["/rpm/1"]) as mock_upload_rpms,
            patch("pulp_tool.services.upload_service.collect_results", return_value="https://example.com/results.json"),
        ):
            result = process_uploads_from_results_json(mock_pulp_client, context, repositories)
        assert result == "https://example.com/results.json"
        mock_upload_rpms.assert_called_once()
        assert mock_upload_rpms.call_args[0][3] == "aarch64"

    def test_upload_from_results_json_log_arch_inference_from_path(self, tmp_path, mock_pulp_client) -> None:
        """Test process_uploads_from_results_json infers log arch from path (lines 290-291)."""
        log_file = tmp_path / "s390x" / "state.log"
        log_file.parent.mkdir()
        log_file.write_text("log")
        results_json_path = tmp_path / "pulp_results.json"
        results_json_path.write_text(json.dumps({"artifacts": {"s390x/state.log": {"pulp_labels": {}}}}))
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
        )
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
            patch("pulp_tool.utils.uploads.upload_log", return_value=["/log/1"]) as mock_upload_log,
            patch("pulp_tool.services.upload_service.collect_results", return_value="https://example.com/results.json"),
        ):
            result = process_uploads_from_results_json(mock_pulp_client, context, repositories)
        assert result == "https://example.com/results.json"
        mock_upload_log.assert_called_once()
        assert mock_upload_log.call_args[1]["arch"] == "s390x"

    def test_upload_from_results_json_arch_inference_noarch(self, tmp_path, mock_pulp_client) -> None:
        """Test process_uploads_from_results_json infers noarch when no arch in path (lines 283, 287-293)."""
        rpm_file = tmp_path / "pkg.rpm"
        rpm_file.write_bytes(b"fake rpm")
        log_file = tmp_path / "state.log"
        log_file.write_text("log")
        results_json_path = tmp_path / "pulp_results.json"
        results_json_path.write_text(
            json.dumps({"artifacts": {"pkg.rpm": {"pulp_labels": {}}, "state.log": {"pulp_labels": {}}}})
        )
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
        )
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
            patch("pulp_tool.utils.uploads.upload_rpms", return_value=["/rpm/1"]) as mock_upload_rpms,
            patch("pulp_tool.utils.uploads.upload_log", return_value=["/log/1"]),
            patch("pulp_tool.services.upload_service.collect_results", return_value="https://example.com/results.json"),
        ):
            result = process_uploads_from_results_json(mock_pulp_client, context, repositories)
        assert result == "https://example.com/results.json"
        mock_upload_rpms.assert_called_once()
        assert mock_upload_rpms.call_args[0][3] == "noarch"

    def test_upload_from_results_json_log_uses_unsigned_repo_with_signed_by(self, tmp_path, mock_pulp_client) -> None:
        """Test process_uploads_from_results_json uses unsigned logs repo when signed_by set (logs never signed)."""
        log_file = tmp_path / "x86_64" / "state.log"
        log_file.parent.mkdir()
        log_file.write_text("log")
        results_json_path = tmp_path / "pulp_results.json"
        results_json_path.write_text(
            json.dumps({"artifacts": {"x86_64/state.log": {"pulp_labels": {"arch": "x86_64"}}}})
        )
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/ignored",
            results_json=str(results_json_path),
            signed_by="key-123",
        )
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="sbom-prn",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
            rpms_signed_href="/test/rpm-signed-href",
            rpms_signed_prn="rpms-signed-prn",
        )
        with (
            patch("pulp_tool.utils.uploads.upload_log", return_value=["/log/1"]) as mock_upload_log,
            patch("pulp_tool.services.upload_service.collect_results", return_value="https://example.com/results.json"),
        ):
            result = process_uploads_from_results_json(mock_pulp_client, context, repositories)
        assert result == "https://example.com/results.json"
        mock_upload_log.assert_called_once()
        call_kw = mock_upload_log.call_args[1]
        assert "signed_by" not in call_kw["labels"]
        assert mock_upload_log.call_args[0][1] == "logs-prn"

    def test_defer_collect_empty_artifacts_returns_model(self, tmp_path, mock_pulp_client) -> None:
        results_json_path = tmp_path / "pulp_results.json"
        results_json_path.write_text('{"artifacts": {}}', encoding="utf-8")
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            results_json=str(results_json_path),
        )
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
        )

        out = process_uploads_from_results_json(mock_pulp_client, context, repositories, defer_collect=True)
        assert isinstance(out, PulpResultsDocument)

    def test_defer_collect_after_uploads(self, tmp_path, mock_pulp_client) -> None:
        rpm = tmp_path / "pkg.rpm"
        rpm.write_bytes(b"rpm")
        results_json_path = tmp_path / "pulp_results.json"
        results_json_path.write_text(
            json.dumps({"artifacts": {"pkg.rpm": {"pulp_labels": {"arch": "x86_64"}}}}),
            encoding="utf-8",
        )
        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            results_json=str(results_json_path),
            files_base_path=str(tmp_path),
        )
        repositories = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="rpms-prn",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="artifacts-prn",
        )

        with (
            patch("pulp_tool.utils.uploads.upload_rpms", return_value=[]),
            patch("pulp_tool.utils.pulp_tasks.create_file_content_and_wait", return_value=Mock()),
        ):
            out = process_uploads_from_results_json(
                mock_pulp_client,
                context,
                repositories,
                defer_collect=True,
            )
        assert isinstance(out, PulpResultsDocument)


class TestUploadPlanFromDocument:
    def test_plan_groups_rpm_log_and_sbom(self, tmp_path) -> None:
        from pulp_tool.services.upload_service import _plan_uploads_from_document

        rpm = tmp_path / "x86_64" / "pkg.rpm"
        rpm.parent.mkdir()
        rpm.write_bytes(b"rpm")
        log = tmp_path / "build.log"
        log.write_text("log", encoding="utf-8")
        sbom = tmp_path / "sbom.json"
        sbom.write_text("{}", encoding="utf-8")
        doc = PulpResultsDocument.from_raw(
            {
                "artifacts": {
                    "x86_64/pkg.rpm": {"pulp_labels": {"arch": "x86_64"}},
                    "build.log": {"pulp_labels": {}},
                    "sbom.json": {"pulp_labels": {}},
                }
            }
        )
        context = UploadRpmContext(
            build_id="b1",
            date_str="2024-01-01",
            namespace="ns",
            results_json=str(tmp_path / "pulp_results.json"),
        )
        plan = _plan_uploads_from_document(doc, base_path=tmp_path, context=context)
        assert plan.rpms_by_arch["x86_64"] == [str(rpm)]
        assert plan.logs_to_upload == [(str(log), "noarch")]
        assert plan.sboms_to_upload == [str(sbom)]

    def test_infer_arch_from_path_when_label_missing(self) -> None:
        from pulp_tool.services.upload_service import _infer_arch_from_key

        assert _infer_arch_from_key("aarch64/foo.rpm", "") == "aarch64"
        assert _infer_arch_from_key("pkg.rpm", "x86_64") == "x86_64"
