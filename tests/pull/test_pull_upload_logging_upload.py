"""
Tests for pulp_tool.pull module.
"""

import os
import re
import tempfile
from unittest.mock import Mock, mock_open, patch

import httpx
from httpx import HTTPError

from pulp_tool.models.artifacts import PulledArtifacts
from pulp_tool.models.pulp_results import PulpResultsDocument
from pulp_tool.pull import upload_downloaded_files_to_pulp
from pulp_tool.pull.upload import _upload_rpms_to_repository, _upload_sboms_and_logs
from pulp_tool.utils import RepositoryRefs


class TestUploadFunctionality:
    """Test upload functionality for different artifact types."""

    def test_upload_rpms_success(self, mock_pulp_client, httpx_mock) -> None:
        """Test successful RPM upload."""
        with tempfile.NamedTemporaryFile(suffix=".rpm", delete=False) as tmp_file:
            tmp_file.write(b"fake rpm content")
            tmp_file_path = tmp_file.name
        try:
            pulled_artifacts = PulledArtifacts()
            pulled_artifacts.add_rpm("test.rpm", tmp_file_path, {"build_id": "test-build", "arch": "x86_64"})
            repositories = RepositoryRefs(
                rpms_href="/pulp/api/v3/repositories/12345/",
                rpms_prn="",
                logs_href="",
                logs_prn="",
                sbom_href="",
                sbom_prn="",
                artifacts_href="",
                artifacts_prn="",
            )
            upload_info = PulpResultsDocument(build_id="test-build", repositories=repositories)
            httpx_mock.post(re.compile(".*/content/rpm/packages/upload/")).mock(
                return_value=httpx.Response(201, json={"pulp_href": "/pulp/api/v3/content/12345/"})
            )
            httpx_mock.post(re.compile(".*/repositories/12345/modify/")).mock(
                return_value=httpx.Response(202, json={"task": "/pulp/api/v3/tasks/67890/"})
            )
            httpx_mock.get(re.compile(".*/tasks/67890/")).mock(
                return_value=httpx.Response(
                    200, json={"pulp_href": "/pulp/api/v3/tasks/67890/", "state": "completed", "created_resources": []}
                )
            )
            with patch("pulp_tool.utils.validation.file.validate_file_path") as mock_validate:
                mock_validate.return_value = None
                _upload_rpms_to_repository(mock_pulp_client, pulled_artifacts, repositories, upload_info)
                assert upload_info.uploaded_counts.rpms == 1
        finally:
            if os.path.exists(tmp_file_path):
                os.unlink(tmp_file_path)

    def test_upload_rpms_exception(self, mock_pulp_client, httpx_mock) -> None:
        """Test RPM upload with exception."""
        pulled_artifacts = PulledArtifacts()
        pulled_artifacts.add_rpm("test.rpm", "/tmp/test.rpm", {"build_id": "test-build", "arch": "x86_64"})
        repositories = RepositoryRefs(
            rpms_href="/pulp/api/v3/repositories/12345/",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        upload_info = PulpResultsDocument(build_id="test-build", repositories=repositories)
        httpx_mock.post(re.compile(".*/content/rpm/packages/upload/")).mock(side_effect=HTTPError("Upload error"))
        with (
            patch("pulp_tool.utils.validation.file.validate_file_path") as mock_validate,
            patch("builtins.open", mock_open(read_data=b"fake rpm content")),
            patch("pulp_tool.utils.rpm_operations.logging") as mock_logging,
        ):
            mock_validate.return_value = None
            _upload_rpms_to_repository(mock_pulp_client, pulled_artifacts, repositories, upload_info)
            mock_logging.error.assert_called()

    def test_upload_sboms_and_logs(self, mock_pulp_client, httpx_mock) -> None:
        """Test uploading SBOMs and logs."""
        pulled_artifacts = PulledArtifacts()
        pulled_artifacts.add_sbom("test.sbom", "/tmp/test.sbom", {"build_id": "test"})
        pulled_artifacts.add_log("test.log", "/tmp/test.log", {"build_id": "test"})
        repositories = RepositoryRefs(
            rpms_href="",
            rpms_prn="",
            logs_href="",
            logs_prn="/pulp/api/v3/repositories/logs/12345/",
            sbom_href="",
            sbom_prn="/pulp/api/v3/repositories/sbom/12345/",
            artifacts_href="",
            artifacts_prn="",
        )
        upload_info = PulpResultsDocument(build_id="test", repositories=repositories)
        httpx_mock.post(re.compile(".*/content/file/files/")).mock(
            return_value=httpx.Response(202, json={"task": "/pulp/api/v3/tasks/12345/"})
        )
        httpx_mock.get(re.compile(".*/tasks/12345/")).mock(
            return_value=httpx.Response(200, json={"pulp_href": "/pulp/api/v3/tasks/12345/", "state": "completed"})
        )
        with patch("pulp_tool.utils.uploads.upload_artifacts_to_repository") as mock_upload:
            mock_upload.return_value = (1, [])
            _upload_sboms_and_logs(mock_pulp_client, pulled_artifacts, repositories, upload_info)
            assert upload_info.uploaded_counts.sboms == 1
            assert upload_info.uploaded_counts.logs == 1

    def test_upload_sboms_exception(self, mock_pulp_client, httpx_mock) -> None:
        """Test SBOM upload with exception handling (lines 53-55)."""
        pulled_artifacts = PulledArtifacts()
        pulled_artifacts.add_sbom("test.sbom", "/tmp/test.sbom", {"build_id": "test"})
        repositories = RepositoryRefs(
            rpms_href="",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="/pulp/api/v3/repositories/sbom/12345/",
            artifacts_href="",
            artifacts_prn="",
        )
        upload_info = PulpResultsDocument(build_id="test", repositories=repositories)
        with (
            patch.object(mock_pulp_client, "create_file_content", side_effect=ValueError("SBOM upload failed")),
            patch("pulp_tool.pull.upload.logging") as mock_logging,
        ):
            _upload_sboms_and_logs(mock_pulp_client, pulled_artifacts, repositories, upload_info)
            mock_logging.error.assert_called()
            assert len(upload_info.upload_errors) > 0
            assert upload_info.uploaded_counts.sboms == 0

    def test_upload_logs_exception(self, mock_pulp_client, httpx_mock) -> None:
        """Test log upload with exception handling (lines 81-83)."""
        pulled_artifacts = PulledArtifacts()
        pulled_artifacts.add_log("test.log", "/tmp/test.log", {"build_id": "test", "arch": "x86_64"})
        repositories = RepositoryRefs(
            rpms_href="",
            rpms_prn="",
            logs_href="",
            logs_prn="/pulp/api/v3/repositories/logs/12345/",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        upload_info = PulpResultsDocument(build_id="test", repositories=repositories)
        with (
            patch.object(mock_pulp_client, "create_file_content", side_effect=ValueError("Log upload failed")),
            patch("pulp_tool.pull.upload.logging") as mock_logging,
        ):
            _upload_sboms_and_logs(mock_pulp_client, pulled_artifacts, repositories, upload_info)
            mock_logging.error.assert_called()
            assert len(upload_info.upload_errors) > 0
            assert upload_info.uploaded_counts.logs == 0

    def test_upload_rpms_repository_addition_exception(self, mock_pulp_client, httpx_mock) -> None:
        """Test RPM upload with repository addition exception (lines 124-127)."""
        pulled_artifacts = PulledArtifacts()
        pulled_artifacts.add_rpm("test.rpm", "/tmp/test.rpm", {"build_id": "test-build", "arch": "x86_64"})
        repositories = RepositoryRefs(
            rpms_href="/pulp/api/v3/repositories/12345/",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        upload_info = PulpResultsDocument(build_id="test-build", repositories=repositories)
        with (
            patch("pulp_tool.pull.upload.upload_rpms_parallel") as mock_upload_rpms,
            patch("pulp_tool.utils.error_handling.logging") as mock_logging,
            patch("builtins.open", mock_open(read_data=b"fake rpm content")),
        ):
            mock_upload_rpms.return_value = ([("/fake/path.rpm", "/pulp/api/v3/content/rpm/packages/123/")], [])
            with patch.object(
                mock_pulp_client, "add_content", side_effect=httpx.HTTPError("Repository addition failed")
            ):
                _upload_rpms_to_repository(mock_pulp_client, pulled_artifacts, repositories, upload_info)
            mock_logging.error.assert_called()
            assert len(upload_info.upload_errors) > 0

    def test_upload_downloaded_files_success(self, mock_pulp_client, httpx_mock) -> None:
        """Test upload_downloaded_files_to_pulp success."""
        with patch("pulp_tool.utils.constants.REPOSITORY_SETUP_MAX_WORKERS", 1):
            httpx_mock.get(re.compile(".*/repositories/rpm/rpm/.*")).mock(
                side_effect=[
                    httpx.Response(200, json={"count": 0, "results": []}),
                    httpx.Response(
                        200,
                        json={
                            "count": 1,
                            "results": [
                                {"pulp_href": "/test/rpm-repo/", "prn": "pulp:///test/rpm-repo/", "name": "test/rpms"}
                            ],
                        },
                    ),
                ]
            )
            httpx_mock.post(re.compile(".*/repositories/rpm/rpm/")).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "pulp_href": "/test/rpm-repo/",
                        "prn": "pulp:///test/rpm-repo/",
                        "task": "/api/v3/tasks/123/",
                    },
                )
            )
            httpx_mock.get(re.compile(".*/distributions/rpm/rpm/.*")).mock(
                return_value=httpx.Response(200, json={"count": 0, "results": []})
            )
            httpx_mock.post(re.compile(".*/distributions/rpm/rpm/")).mock(
                return_value=httpx.Response(
                    200, json={"pulp_href": "/test/rpm-distro/", "base_path": "test", "task": "/api/v3/tasks/124/"}
                )
            )
            httpx_mock.get(re.compile(".*/tasks/124/")).mock(
                return_value=httpx.Response(200, json={"state": "completed", "pulp_href": "/api/v3/tasks/124/"})
            )
            httpx_mock.get(re.compile(".*/repositories/file/file/.*")).mock(
                side_effect=[
                    httpx.Response(200, json={"count": 0, "results": []}),
                    httpx.Response(
                        200,
                        json={
                            "count": 1,
                            "results": [
                                {
                                    "pulp_href": "/test/file-repo-logs/",
                                    "prn": "pulp:///test/file-repo-logs/",
                                    "name": "test/logs",
                                }
                            ],
                        },
                    ),
                    httpx.Response(200, json={"count": 0, "results": []}),
                    httpx.Response(
                        200,
                        json={
                            "count": 1,
                            "results": [
                                {
                                    "pulp_href": "/test/file-repo-sbom/",
                                    "prn": "pulp:///test/file-repo-sbom/",
                                    "name": "test/sbom",
                                }
                            ],
                        },
                    ),
                    httpx.Response(200, json={"count": 0, "results": []}),
                    httpx.Response(
                        200,
                        json={
                            "count": 1,
                            "results": [
                                {
                                    "pulp_href": "/test/file-repo-artifacts/",
                                    "prn": "pulp:///test/file-repo-artifacts/",
                                    "name": "test/artifacts",
                                }
                            ],
                        },
                    ),
                ]
            )
            httpx_mock.post(re.compile(".*/repositories/file/file/")).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "pulp_href": "/test/file-repo/",
                        "prn": "pulp:///test/file-repo/",
                        "task": "/api/v3/tasks/125/",
                    },
                )
            )
            httpx_mock.get(re.compile(".*/distributions/file/file/.*")).mock(
                return_value=httpx.Response(200, json={"count": 0, "results": []})
            )
            httpx_mock.post(re.compile(".*/distributions/file/file/")).mock(
                return_value=httpx.Response(
                    200, json={"pulp_href": "/test/file-distro/", "base_path": "test", "task": "/api/v3/tasks/126/"}
                )
            )
            httpx_mock.get(re.compile(".*/tasks/126/")).mock(
                return_value=httpx.Response(200, json={"state": "completed", "pulp_href": "/api/v3/tasks/126/"})
            )
            pulled_artifacts = PulledArtifacts()
            pulled_artifacts.add_rpm("test.rpm", "/tmp/test.rpm", {"build_id": "test"})
            args = Mock()
            args.build_id = "test-build"
            args.artifact_file = None
            mock_repositories = RepositoryRefs(
                rpms_href="/pulp/api/v3/repositories/rpm/12345/",
                rpms_prn="/pulp/api/v3/repositories/rpm/12345/",
                logs_href="/pulp/api/v3/repositories/logs/12345/",
                logs_prn="/pulp/api/v3/repositories/logs/12345/",
                sbom_href="/pulp/api/v3/repositories/sbom/12345/",
                sbom_prn="/pulp/api/v3/repositories/sbom/12345/",
                artifacts_href="/pulp/api/v3/repositories/artifacts/12345/",
                artifacts_prn="/pulp/api/v3/repositories/artifacts/12345/",
            )
            with (
                patch("pulp_tool.utils.determine_build_id", return_value="test"),
                patch("pulp_tool.pull.upload._upload_sboms_and_logs") as mock_upload_sboms,
                patch("pulp_tool.pull.upload._upload_rpms_to_repository") as mock_upload_rpms,
                patch.object(mock_pulp_client, "wait_for_finished_task") as mock_wait,
                patch("pulp_tool.utils.PulpHelper.setup_repositories", return_value=mock_repositories),
            ):
                mock_wait.return_value = Mock(json=lambda: {"state": "completed"})
                result = upload_downloaded_files_to_pulp(mock_pulp_client, pulled_artifacts, args)
                assert result.build_id == "test-build"
                mock_upload_sboms.assert_called_once()
                mock_upload_rpms.assert_called_once()
