"""
Tests for upload utilities.

This module tests upload operations including label creation,
log uploads, and artifact uploads to repositories.
"""

import os
import tempfile
from unittest.mock import patch

import pytest

from pulp_tool.utils import upload_rpms
from pulp_tool.utils.uploads import rpm_directory_has_log_files


class TestUploadRpms:
    """Test upload_rpms function."""

    def test_upload_rpms_empty_list(self, mock_pulp_client) -> None:
        """Test upload_rpms with empty RPM list (lines 208-209)."""
        from pulp_tool.models.context import UploadRpmContext
        from pulp_tool.models.results import PulpResultsModel, RepositoryRefs

        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/test/rpms",
            sbom_path="/test/sbom.json",
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
        )
        results_model = PulpResultsModel(build_id="test-build", repositories=repositories)
        with patch("pulp_tool.utils.uploads.logging") as mock_logging:
            result = upload_rpms(
                [],
                context,
                mock_pulp_client,
                "x86_64",
                rpm_repository_href="/test/rpm-href",
                date="2024-01-01 00:00:00",
                results_model=results_model,
            )
            assert result == []
            mock_logging.debug.assert_called_with("No new RPMs to upload for %s", "x86_64")

    def test_upload_rpms_with_created_resources(self, mock_pulp_client) -> None:
        """Test upload_rpms with created resources (lines 225-227, 229-231)."""
        from pulp_tool.models.context import UploadRpmContext
        from pulp_tool.models.pulp_api import TaskResponse
        from pulp_tool.models.results import PulpResultsModel, RepositoryRefs

        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/test/rpms",
            sbom_path="/test/sbom.json",
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
        )
        results_model = PulpResultsModel(build_id="test-build", repositories=repositories)
        mock_artifacts = [("/path/to/package.rpm", "/rpm/artifact/1"), ("/path/to/package2.rpm", "/rpm/artifact/2")]
        mock_task_response = TaskResponse(
            pulp_href="/tasks/123/", state="completed", created_resources=["/resource/1", "/resource/2"]
        )
        mock_repo_task = TaskResponse(pulp_href="/tasks/123/", state="pending", created_resources=[])
        with (
            patch("pulp_tool.utils.uploads.upload_rpms_parallel", return_value=(mock_artifacts, [])),
            patch.object(mock_pulp_client, "add_content", return_value=mock_repo_task),
            patch.object(mock_pulp_client, "wait_for_finished_task", return_value=mock_task_response),
            patch("pulp_tool.utils.uploads.logging") as mock_logging,
        ):
            result = upload_rpms(
                ["/path/to/package.rpm", "/path/to/package2.rpm"],
                context,
                mock_pulp_client,
                "x86_64",
                rpm_repository_href="/test/rpm-href",
                date="2024-01-01 00:00:00",
                results_model=results_model,
            )
            assert result == ["/rpm/artifact/1", "/rpm/artifact/2"]
            assert results_model.uploaded_counts.rpms == 2
            mock_pulp_client.add_content.assert_called_once_with(
                "/test/rpm-href", ["/rpm/artifact/1", "/rpm/artifact/2"]
            )
            mock_logging.debug.assert_any_call("Adding %s RPM artifacts to repository", 2)
            mock_logging.debug.assert_any_call("Recorded %d RPM content href(s) for results gather fallback", 2)

    def test_upload_rpms_with_distribution_urls_adds_each_to_results(self, mock_pulp_client) -> None:
        """Passing distribution_urls records each uploaded RPM in results (incremental JSON)."""
        from pulp_tool.models.context import UploadRpmContext
        from pulp_tool.models.pulp_api import TaskResponse
        from pulp_tool.models.results import PulpResultsModel, RepositoryRefs

        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/test/rpms",
            sbom_path="/test/sbom.json",
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
        )
        results_model = PulpResultsModel(build_id="test-build", repositories=repositories)
        mock_artifacts = [("/path/to/a.rpm", "/rpm/artifact/1"), ("/path/to/b.rpm", "/rpm/artifact/2")]
        mock_task_response = TaskResponse(pulp_href="/tasks/123/", state="completed", created_resources=["/resource/1"])
        mock_repo_task = TaskResponse(pulp_href="/tasks/123/", state="pending", created_resources=[])
        with (
            patch("pulp_tool.utils.uploads.upload_rpms_parallel", return_value=(mock_artifacts, [])),
            patch.object(mock_pulp_client, "add_content", return_value=mock_repo_task),
            patch.object(mock_pulp_client, "wait_for_finished_task", return_value=mock_task_response),
            patch.object(mock_pulp_client, "add_uploaded_artifact_to_results_model") as mock_add,
        ):
            upload_rpms(
                ["/path/to/a.rpm", "/path/to/b.rpm"],
                context,
                mock_pulp_client,
                "x86_64",
                rpm_repository_href="/test/rpm-href",
                date="2024-01-01 00:00:00",
                results_model=results_model,
                distribution_urls={"rpms": "https://example.com/rpms/"},
                target_arch_repo=True,
            )
        assert mock_add.call_count == 2
        rpm_calls = [c.kwargs for c in mock_add.call_args_list]
        assert {c["local_path"] for c in rpm_calls} == {"/path/to/a.rpm", "/path/to/b.rpm"}
        assert all(c["is_rpm"] is True for c in rpm_calls)
        assert all(c["target_arch_repo"] is True for c in rpm_calls)

    def test_upload_rpms_with_signed_by_adds_label(self, mock_pulp_client) -> None:
        """Test upload_rpms adds signed_by to labels when context has signed_by (lines 212-214)."""
        from pulp_tool.models.context import UploadRpmContext
        from pulp_tool.models.pulp_api import TaskResponse
        from pulp_tool.models.results import PulpResultsModel, RepositoryRefs

        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/test/rpms",
            sbom_path="/test/sbom.json",
            signed_by="key-123",
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
        )
        results_model = PulpResultsModel(build_id="test-build", repositories=repositories)
        mock_artifacts = [("/path/to/package.rpm", "/rpm/artifact/1")]
        mock_task_response = TaskResponse(pulp_href="/tasks/123/", state="completed", created_resources=["/resource/1"])
        mock_repo_task = TaskResponse(pulp_href="/tasks/123/", state="pending", created_resources=[])
        with (
            patch("pulp_tool.utils.uploads.upload_rpms_parallel", return_value=(mock_artifacts, [])) as mock_parallel,
            patch.object(mock_pulp_client, "add_content", return_value=mock_repo_task),
            patch.object(mock_pulp_client, "wait_for_finished_task", return_value=mock_task_response),
        ):
            upload_rpms(
                ["/path/to/package.rpm"],
                context,
                mock_pulp_client,
                "x86_64",
                rpm_repository_href="/test/rpm-href",
                date="2024-01-01 00:00:00",
                results_model=results_model,
            )
        mock_parallel.assert_called_once()
        labels_passed = mock_parallel.call_args[0][2]
        assert labels_passed.get("signed_by") == "key-123"

    def test_upload_rpms_overwrite_calls_remove(self, mock_pulp_client) -> None:
        """Test upload_rpms with overwrite invokes remove_rpms_matching_local_files_from_repository."""
        from pulp_tool.models.context import UploadRpmContext
        from pulp_tool.models.pulp_api import TaskResponse
        from pulp_tool.models.results import PulpResultsModel, RepositoryRefs

        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/test/rpms",
            sbom_path="/test/sbom.json",
            signed_by="sig-1",
            overwrite=True,
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
        )
        results_model = PulpResultsModel(build_id="test-build", repositories=repositories)
        mock_artifacts = [("/path/to/package.rpm", "/rpm/artifact/1")]
        mock_task_response = TaskResponse(pulp_href="/tasks/123/", state="completed", created_resources=["/resource/1"])
        mock_repo_task = TaskResponse(pulp_href="/tasks/123/", state="pending", created_resources=[])
        with (
            patch("pulp_tool.utils.uploads.remove_rpms_matching_local_files_from_repository") as mock_remove,
            patch("pulp_tool.utils.uploads.upload_rpms_parallel", return_value=(mock_artifacts, [])),
            patch.object(mock_pulp_client, "add_content", return_value=mock_repo_task),
            patch.object(mock_pulp_client, "wait_for_finished_task", return_value=mock_task_response),
        ):
            upload_rpms(
                ["/path/to/package.rpm"],
                context,
                mock_pulp_client,
                "x86_64",
                rpm_repository_href="/test/rpm-href",
                date="2024-01-01 00:00:00",
                results_model=results_model,
            )
        mock_remove.assert_called_once_with(mock_pulp_client, ["/path/to/package.rpm"], "/test/rpm-href", "sig-1")

    def test_upload_rpms_no_created_resources(self, mock_pulp_client) -> None:
        """RPM content hrefs are returned even when add_content task reports no created_resources."""
        from pulp_tool.models.context import UploadRpmContext
        from pulp_tool.models.pulp_api import TaskResponse
        from pulp_tool.models.results import PulpResultsModel, RepositoryRefs

        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/test/rpms",
            sbom_path="/test/sbom.json",
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
        )
        results_model = PulpResultsModel(build_id="test-build", repositories=repositories)
        mock_artifacts = [("/path/to/package.rpm", "/rpm/artifact/1")]
        mock_task_response = TaskResponse(pulp_href="/tasks/123/", state="completed", created_resources=[])
        mock_repo_task = TaskResponse(pulp_href="/tasks/123/", state="pending", created_resources=[])
        with (
            patch("pulp_tool.utils.uploads.upload_rpms_parallel", return_value=(mock_artifacts, [])),
            patch.object(mock_pulp_client, "add_content", return_value=mock_repo_task),
            patch.object(mock_pulp_client, "wait_for_finished_task", return_value=mock_task_response),
            patch("pulp_tool.utils.uploads.logging") as mock_logging,
        ):
            result = upload_rpms(
                ["/path/to/package.rpm"],
                context,
                mock_pulp_client,
                "x86_64",
                rpm_repository_href="/test/rpm-href",
                date="2024-01-01 00:00:00",
                results_model=results_model,
            )
            assert result == ["/rpm/artifact/1"]
            assert results_model.uploaded_counts.rpms == 1
            mock_pulp_client.add_content.assert_called_once_with("/test/rpm-href", ["/rpm/artifact/1"])
            mock_logging.debug.assert_any_call("Recorded %d RPM content href(s) for results gather fallback", 1)

    def test_upload_rpms_empty_artifacts(self, mock_pulp_client) -> None:
        """Test upload_rpms with empty rpm_results_artifacts (not hitting lines 225-227)."""
        from pulp_tool.models.context import UploadRpmContext
        from pulp_tool.models.results import PulpResultsModel, RepositoryRefs

        context = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01 00:00:00",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/test/rpms",
            sbom_path="/test/sbom.json",
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
        )
        results_model = PulpResultsModel(build_id="test-build", repositories=repositories)
        with (
            patch("pulp_tool.utils.uploads.upload_rpms_parallel", return_value=([], [])),
            patch.object(mock_pulp_client, "add_content") as mock_add_content,
        ):
            with pytest.raises(ValueError, match="Failed to upload 1 of 1 RPM"):
                upload_rpms(
                    ["/path/to/package.rpm"],
                    context,
                    mock_pulp_client,
                    "x86_64",
                    rpm_repository_href="/test/rpm-href",
                    date="2024-01-01 00:00:00",
                    results_model=results_model,
                )
            assert results_model.uploaded_counts.rpms == 0
            mock_add_content.assert_not_called()


class TestRpmDirectoryHasLogFiles:
    """Tests for rpm_directory_has_log_files."""

    def test_true_when_log_under_arch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            arch_dir = os.path.join(tmp, "x86_64")
            os.makedirs(arch_dir)
            with open(os.path.join(arch_dir, "x.log"), "w", encoding="utf-8") as f:
                f.write("l")
            assert rpm_directory_has_log_files(tmp) is True

    def test_true_when_log_at_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "root.log"), "w", encoding="utf-8") as f:
                f.write("l")
            assert rpm_directory_has_log_files(tmp) is True

    def test_false_when_no_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "x86_64"))
            assert rpm_directory_has_log_files(tmp) is False

    def test_false_when_path_invalid(self) -> None:
        assert rpm_directory_has_log_files("/nonexistent/path/xyz") is False
