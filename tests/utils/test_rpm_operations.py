"""
Tests for RPM operation utility functions.

This module tests RPM checking, uploading, and processing functions.
"""

import os
from unittest.mock import Mock, patch

import httpx
import pytest

from pulp_tool.models.pulp_results import PulpResultsDocument
from pulp_tool.utils import upload_rpms_logs
from pulp_tool.utils.rpm_operations import (
    calculate_sha256_checksum,
    parse_rpm_filename_to_nvr,
    parse_rpm_filename_to_nvra,
    upload_rpms_parallel,
)


class TestChecksumUtilities:
    """Test checksum utility functions."""

    def test_calculate_sha256_checksum(self, temp_file) -> None:
        """Test _calculate_sha256_checksum function."""
        checksum = calculate_sha256_checksum(temp_file)
        assert len(checksum) == 64
        assert all(c in "0123456789abcdef" for c in checksum)

    def test_calculate_sha256_checksum_file_not_found(self) -> None:
        """Test _calculate_sha256_checksum function with non-existent file."""
        with pytest.raises(FileNotFoundError):
            calculate_sha256_checksum("/non/existent/file")

    def test_calculate_sha256_checksum_io_error(self) -> None:
        """Test _calculate_sha256_checksum with IO error."""
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name
            f.write(b"test content")
        try:
            os.chmod(temp_path, 0)
            with pytest.raises(IOError, match="Error reading file"):
                calculate_sha256_checksum(temp_path)
        finally:
            os.chmod(temp_path, 420)
            os.unlink(temp_path)


class TestParseRpmFilenameToNvr:
    """Test parse_rpm_filename_to_nvr function."""

    def test_parse_src_rpm(self) -> None:
        """Parse src.rpm filename."""
        result = parse_rpm_filename_to_nvr("osci-internal-test-package-0.2.0-257.el10.src.rpm")
        assert result == ("osci-internal-test-package", "0.2.0", "257.el10")

    def test_parse_x86_64_rpm(self) -> None:
        """Parse x86_64.rpm filename."""
        result = parse_rpm_filename_to_nvr("pkg-1.0-1.x86_64.rpm")
        assert result == ("pkg", "1.0", "1")

    def test_parse_with_path(self) -> None:
        """Parse filename with path - uses basename."""
        result = parse_rpm_filename_to_nvr("x86_64/pkg-1.0-1.x86_64.rpm")
        assert result == ("pkg", "1.0", "1")

    def test_parse_epoch_in_version(self) -> None:
        """Parse filename with epoch in version (name-epoch:version-release)."""
        result = parse_rpm_filename_to_nvr("pkg-1:2.3-4.el8.x86_64.rpm")
        assert result == ("pkg", "1:2.3", "4.el8")

    def test_parse_epoch_prefix(self) -> None:
        """Parse filename with epoch prefix (epoch:name-version-release, rpmUtils format)."""
        result = parse_rpm_filename_to_nvr("1:bar-9-123a.ia64.rpm")
        assert result == ("bar", "9", "123a")

    def test_parse_release_starts_with_letter(self) -> None:
        """Parse filename where release starts with letter (e.g. test_15.el10)."""
        result = parse_rpm_filename_to_nvr("libecpg-16.1-test_15.el10.src.rpm")
        assert result == ("libecpg", "16.1", "test_15.el10")
        result2 = parse_rpm_filename_to_nvr("libpgtypes-16.1-test_15.el10.s390x.rpm")
        assert result2 == ("libpgtypes", "16.1", "test_15.el10")

    def test_parse_noarch(self) -> None:
        """Parse noarch rpm."""
        result = parse_rpm_filename_to_nvr("my-pkg-0.1.0-1.noarch.rpm")
        assert result == ("my-pkg", "0.1.0", "1")

    def test_parse_aarch64(self) -> None:
        """Parse aarch64 rpm."""
        result = parse_rpm_filename_to_nvr("package-1.0.0-1.aarch64.rpm")
        assert result == ("package", "1.0.0", "1")

    def test_parse_invalid_no_rpm_suffix(self) -> None:
        """Return None for non-.rpm file."""
        assert parse_rpm_filename_to_nvr("pkg.tar.gz") is None

    def test_parse_invalid_malformed(self) -> None:
        """Return None for malformed rpm filename."""
        assert parse_rpm_filename_to_nvr("package.rpm") is None
        assert parse_rpm_filename_to_nvr("package-1.0.rpm") is None

    def test_parse_invalid_empty_name_version_or_release(self) -> None:
        """Return None when name, version, or release is empty after parsing (line 117)."""
        assert parse_rpm_filename_to_nvr("pkg-1.0-.rpm") is None
        assert parse_rpm_filename_to_nvr("pkg--1.rpm") is None


class TestParseRpmFilenameToNvra:
    """Test parse_rpm_filename_to_nvra function."""

    def test_parse_includes_arch(self) -> None:
        """Parse filename and extract architecture."""
        assert parse_rpm_filename_to_nvra("pkg-1.0-1.x86_64.rpm") == ("pkg", "1.0", "1", "x86_64")
        assert parse_rpm_filename_to_nvra("pkg-1.0-1.aarch64.rpm") == ("pkg", "1.0", "1", "aarch64")
        assert parse_rpm_filename_to_nvra("pkg-1.0-1.s390x.rpm") == ("pkg", "1.0", "1", "s390x")
        assert parse_rpm_filename_to_nvra("pkg-1.0-1.src.rpm") == ("pkg", "1.0", "1", "src")
        assert parse_rpm_filename_to_nvra("pkg-1.0-1.noarch.rpm") == ("pkg", "1.0", "1", "noarch")

    def test_parse_with_path(self) -> None:
        """Parse filename with path - uses basename for arch extraction."""
        result = parse_rpm_filename_to_nvra("x86_64/pkg-1.0-1.x86_64.rpm")
        assert result == ("pkg", "1.0", "1", "x86_64")

    def test_parse_invalid_returns_none(self) -> None:
        """Return None for unparseable filenames."""
        assert parse_rpm_filename_to_nvra("pkg.tar.gz") is None
        assert parse_rpm_filename_to_nvra("package.rpm") is None


class TestRPMUtilities:
    """Test RPM utility functions."""

    def test_upload_rpms_logs(self, mock_pulp_client, temp_rpm_file, httpx_mock) -> None:
        """Test upload_rpms_logs function."""
        from pulp_tool.models import RepositoryRefs

        httpx_mock.get(
            "https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/rpm/packages/"
            "?pulp_label_select=build_id~test-build"
        ).mock(return_value=httpx.Response(200, json={"results": []}))
        httpx_mock.post("https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/file/files/").mock(
            return_value=httpx.Response(202, json={"task": "/pulp/api/v3/tasks/12345/"})
        )
        httpx_mock.get("https://pulp.example.com/pulp/api/v3/tasks/12345/").mock(
            return_value=httpx.Response(
                200,
                json={"pulp_href": "/pulp/api/v3/tasks/12345/", "state": "completed", "result": {"status": "success"}},
            )
        )
        args = Mock()
        args.build_id = "test-build"
        args.namespace = "test-namespace"
        args.parent_package = "test-package"
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
        with (
            patch("glob.glob", return_value=[temp_rpm_file]),
            patch(
                "pulp_tool.utils.uploads.upload_rpms_parallel",
                return_value=([(temp_rpm_file, "/pulp/api/v3/content/rpm/packages/12345/")], []),
            ),
            patch.object(mock_pulp_client, "add_content") as mock_add,
            patch.object(mock_pulp_client, "wait_for_finished_task") as mock_wait,
        ):
            from pulp_tool.models.pulp_api import TaskResponse

            mock_add.return_value = TaskResponse(pulp_href="/tasks/1/", state="pending")
            mock_wait.return_value = TaskResponse(
                pulp_href="/tasks/1/", state="completed", created_resources=["/resource/1"]
            )
            result = upload_rpms_logs(
                os.path.dirname(temp_rpm_file),
                args,
                mock_pulp_client,
                "x86_64",
                rpm_repository_href="test-repo",
                file_repository_prn="test-file-repo",
                date="2024-01-01 12:00:00",
                results_model=results_model,
            )
        assert result.uploaded_rpms == [temp_rpm_file]

    def test_upload_rpms_logs_no_files(self, mock_pulp_client, temp_dir) -> None:
        """Test upload_rpms_logs with no RPMs or logs."""
        from pulp_tool.models import RepositoryRefs

        args = Mock()
        args.build_id = "test-build"
        args.namespace = "test-namespace"
        args.parent_package = "test-package"
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
        with patch("glob.glob", return_value=[]):
            result = upload_rpms_logs(
                temp_dir,
                args,
                mock_pulp_client,
                "x86_64",
                rpm_repository_href="test-repo",
                file_repository_prn="test-file-repo",
                date="2024-01-01 12:00:00",
                results_model=results_model,
            )
        assert result.uploaded_rpms == []

    def test_upload_rpms_logs_raises_when_logs_present_but_empty_prn(self, mock_pulp_client, temp_dir) -> None:
        """Log files require a non-empty logs repository PRN."""
        from pulp_tool.models import RepositoryRefs

        args = Mock()
        args.build_id = "test-build"
        args.namespace = "test-namespace"
        args.parent_package = "test-package"
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
        rpm_path = os.path.join(temp_dir, "pkg.rpm")
        log_path = os.path.join(temp_dir, "x.log")
        with patch("glob.glob", side_effect=[[rpm_path], [log_path]]):
            with pytest.raises(ValueError, match="logs repository PRN"):
                upload_rpms_logs(
                    temp_dir,
                    args,
                    mock_pulp_client,
                    "x86_64",
                    rpm_repository_href="test-repo",
                    file_repository_prn="",
                    date="2024-01-01 12:00:00",
                    results_model=results_model,
                )

    def test_upload_rpms_parallel_empty_list(self, mock_pulp_client) -> None:
        """Test upload_rpms_parallel with empty list."""
        result = upload_rpms_parallel(mock_pulp_client, [], {}, "x86_64")
        assert result == ([], [])

    def test_upload_rpms_parallel_with_rpms(self, mock_pulp_client, temp_rpm_file) -> None:
        """Test upload_rpms_parallel with RPMs."""
        mock_pulp_client.upload_content = Mock(return_value="/pulp/api/v3/content/rpm/packages/12345/")
        result, errors = upload_rpms_parallel(mock_pulp_client, [temp_rpm_file], {"arch": "x86_64"}, "x86_64")
        assert len(result) == 1
        assert errors == []
        assert result[0][0] == temp_rpm_file
        assert result[0][1] == "/pulp/api/v3/content/rpm/packages/12345/"
