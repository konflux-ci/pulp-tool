"""Tests for upload-files CLI (paths and multi-file uploads)."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from click.testing import CliRunner

from pulp_tool.cli import cli


class TestUploadFilesCommandBasics:
    """upload-files: validation, success, arch, multiple files."""

    def test_upload_files_missing_build_id(self) -> None:
        """Test upload-files command with missing build-id."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            rpm_file = Path(tmpdir) / "package.rpm"
            rpm_file.write_text("dummy")
            result = runner.invoke(
                cli, ["--namespace", "test-ns", "upload-files", "--parent-package", "test-pkg", "--rpm", str(rpm_file)]
            )
            assert result.exit_code == 1
            assert "build-id is required" in result.output

    def test_upload_files_missing_namespace(self) -> None:
        """Test upload-files command with missing namespace."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            rpm_file = Path(tmpdir) / "package.rpm"
            rpm_file.write_text("dummy")
            result = runner.invoke(
                cli,
                ["--build-id", "test-build", "upload-files", "--parent-package", "test-pkg", "--rpm", str(rpm_file)],
            )
            assert result.exit_code == 1
            assert "namespace is required" in result.output

    def test_upload_files_missing_parent_package(self) -> None:
        """Test upload-files command with missing parent-package."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            rpm_file = Path(tmpdir) / "package.rpm"
            rpm_file.write_text("dummy")
            result = runner.invoke(
                cli, ["--build-id", "test-build", "--namespace", "test-ns", "upload-files", "--rpm", str(rpm_file)]
            )
            assert result.exit_code != 0
            assert "Missing option" in result.output or "required" in result.output.lower()

    def test_upload_files_no_files_provided(self) -> None:
        """Test upload-files command with no files specified."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                '[cli]\nbase_url = "https://pulp.example.com"\napi_root = "/pulp/api/v3"\ndomain = "test-domain"'
            )
            result = runner.invoke(
                cli,
                [
                    "--build-id",
                    "test-build",
                    "--namespace",
                    "test-ns",
                    "--config",
                    str(config_path),
                    "upload-files",
                    "--parent-package",
                    "test-pkg",
                ],
            )
            assert result.exit_code == 1
            assert "At least one file must be specified" in result.output

    def test_upload_files_invalid_rpm_path(self) -> None:
        """Test upload-files with non-existent RPM file."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                '[cli]\nbase_url = "https://pulp.example.com"\napi_root = "/pulp/api/v3"\ndomain = "test-domain"'
            )
            result = runner.invoke(
                cli,
                [
                    "--build-id",
                    "test-build",
                    "--namespace",
                    "test-ns",
                    "--config",
                    str(config_path),
                    "upload-files",
                    "--parent-package",
                    "test-pkg",
                    "--rpm",
                    "/nonexistent/package.rpm",
                ],
            )
            assert result.exit_code != 0

    @patch("pulp_tool.cli.upload_files.PulpClient")
    @patch("pulp_tool.cli.upload_files.PulpHelper")
    def test_upload_files_passes_oci_storage_flag(self, mock_helper_class, mock_client_class, tmp_path: Path) -> None:
        mock_client = Mock()
        mock_client_class.create_from_config_file.return_value = mock_client
        mock_helper = Mock()
        mock_helper_class.return_value = mock_helper
        mock_helper.setup_repositories.return_value = Mock()
        mock_helper.process_file_uploads.return_value = "https://example.com/results.json"
        rpm = tmp_path / "test.rpm"
        rpm.write_bytes(b"rpm")
        config = tmp_path / "cli.toml"
        config.write_text("[cli]\nbase_url = 'https://pulp.example.com'\n")
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--build-id",
                "b",
                "--namespace",
                "ns",
                "--config",
                str(config),
                "upload-files",
                "--parent-package",
                "pkg",
                "--rpm",
                str(rpm),
                "--oci-storage",
                "quay.io/ns/repo:latest",
            ],
        )
        assert result.exit_code == 0
        context = mock_helper.process_file_uploads.call_args[0][1]
        assert context.oci_storage == "quay.io/ns/repo:latest"

    @patch("pulp_tool.cli.upload_files.PulpClient")
    @patch("pulp_tool.cli.upload_files.PulpHelper")
    def test_upload_files_success(self, mock_helper_class, mock_client_class) -> None:
        """Test successful upload-files flow with all file types."""
        runner = CliRunner()
        mock_client = Mock()
        mock_client.close = Mock()
        mock_client_class.create_from_config_file.return_value = mock_client
        mock_helper = Mock()
        from pulp_tool.models.repository import RepositoryRefs

        mock_repos = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        mock_helper.setup_repositories.return_value = mock_repos
        mock_helper.process_file_uploads.return_value = "https://example.com/results.json"
        mock_helper_class.return_value = mock_helper
        with tempfile.TemporaryDirectory() as tmpdir:
            rpm_file = Path(tmpdir) / "package.rpm"
            rpm_file.write_text("dummy rpm")
            file_file = Path(tmpdir) / "file.txt"
            file_file.write_text("dummy file")
            log_file = Path(tmpdir) / "build.log"
            log_file.write_text("dummy log")
            sbom_file = Path(tmpdir) / "sbom.json"
            sbom_file.write_text("{}")
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                '[cli]\nbase_url = "https://pulp.example.com"\napi_root = "/pulp/api/v3"\ndomain = "test-domain"'
            )
            result = runner.invoke(
                cli,
                [
                    "--build-id",
                    "test-build",
                    "--namespace",
                    "test-ns",
                    "--config",
                    str(config_path),
                    "upload-files",
                    "--parent-package",
                    "test-pkg",
                    "--rpm",
                    str(rpm_file),
                    "--file",
                    str(file_file),
                    "--log",
                    str(log_file),
                    "--sbom",
                    str(sbom_file),
                ],
            )
            assert result.exit_code == 0
            assert "RESULTS JSON:" in result.output
            assert "https://example.com/results.json" in result.output
            mock_helper.setup_repositories.assert_called_once_with(
                "test-build", skip_artifacts_repo=False, skip_logs_repo=False, skip_sbom_repo=False
            )
            mock_helper.process_file_uploads.assert_called_once()

    @patch("pulp_tool.cli.upload_files.PulpClient")
    @patch("pulp_tool.cli.upload_files.PulpHelper")
    def test_upload_files_artifact_results_folder_skips_artifacts_repo(
        self, mock_helper_class, mock_client_class
    ) -> None:
        """Test upload-files with --artifact-results as folder path skips artifacts repo."""
        runner = CliRunner()
        mock_client = Mock()
        mock_client.close = Mock()
        mock_client_class.create_from_config_file.return_value = mock_client
        mock_helper = Mock()
        from pulp_tool.models.repository import RepositoryRefs

        mock_repos = RepositoryRefs(
            rpms_href="/test/",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        mock_helper.setup_repositories.return_value = mock_repos
        mock_helper.process_file_uploads.return_value = "/tmp/output/pulp_results.json"
        mock_helper_class.return_value = mock_helper
        with tempfile.TemporaryDirectory() as tmpdir:
            rpm_file = Path(tmpdir) / "package.rpm"
            rpm_file.write_text("dummy rpm")
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                '[cli]\nbase_url = "https://pulp.example.com"\napi_root = "/pulp/api/v3"\ndomain = "test-domain"'
            )
            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()
            result = runner.invoke(
                cli,
                [
                    "--build-id",
                    "test-build",
                    "--namespace",
                    "test-ns",
                    "--config",
                    str(config_path),
                    "upload-files",
                    "--parent-package",
                    "test-pkg",
                    "--rpm",
                    str(rpm_file),
                    "--artifact-results",
                    str(output_dir),
                ],
            )
            assert result.exit_code == 0
            mock_helper.setup_repositories.assert_called_once_with(
                "test-build", skip_artifacts_repo=True, skip_logs_repo=True, skip_sbom_repo=True
            )

    @patch("pulp_tool.cli.upload_files.PulpClient")
    @patch("pulp_tool.cli.upload_files.PulpHelper")
    def test_upload_files_with_arch(self, mock_helper_class, mock_client_class) -> None:
        """Test upload-files with architecture specified."""
        runner = CliRunner()
        mock_client = Mock()
        mock_client.close = Mock()
        mock_client_class.create_from_config_file.return_value = mock_client
        mock_helper = Mock()
        from pulp_tool.models.repository import RepositoryRefs

        mock_repos = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        mock_helper.setup_repositories.return_value = mock_repos
        mock_helper.process_file_uploads.return_value = "https://example.com/results.json"
        mock_helper_class.return_value = mock_helper
        with tempfile.TemporaryDirectory() as tmpdir:
            rpm_file = Path(tmpdir) / "package.rpm"
            rpm_file.write_text("dummy rpm")
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                '[cli]\nbase_url = "https://pulp.example.com"\napi_root = "/pulp/api/v3"\ndomain = "test-domain"'
            )
            result = runner.invoke(
                cli,
                [
                    "--build-id",
                    "test-build",
                    "--namespace",
                    "test-ns",
                    "--config",
                    str(config_path),
                    "upload-files",
                    "--parent-package",
                    "test-pkg",
                    "--rpm",
                    str(rpm_file),
                    "--arch",
                    "x86_64",
                ],
            )
            assert result.exit_code == 0
            call_args = mock_helper.process_file_uploads.call_args
            context = call_args[0][1]
            assert context.arch == "x86_64"

    @patch("pulp_tool.cli.upload_files.PulpClient")
    @patch("pulp_tool.cli.upload_files.PulpHelper")
    def test_upload_files_multiple_files(self, mock_helper_class, mock_client_class) -> None:
        """Test upload-files with multiple files of the same type."""
        runner = CliRunner()
        mock_client = Mock()
        mock_client.close = Mock()
        mock_client_class.create_from_config_file.return_value = mock_client
        mock_helper = Mock()
        from pulp_tool.models.repository import RepositoryRefs

        mock_repos = RepositoryRefs(
            rpms_href="/test/rpm-href",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        mock_helper.setup_repositories.return_value = mock_repos
        mock_helper.process_file_uploads.return_value = "https://example.com/results.json"
        mock_helper_class.return_value = mock_helper
        with tempfile.TemporaryDirectory() as tmpdir:
            rpm_file1 = Path(tmpdir) / "package1.rpm"
            rpm_file1.write_text("dummy rpm 1")
            rpm_file2 = Path(tmpdir) / "package2.rpm"
            rpm_file2.write_text("dummy rpm 2")
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                '[cli]\nbase_url = "https://pulp.example.com"\napi_root = "/pulp/api/v3"\ndomain = "test-domain"'
            )
            result = runner.invoke(
                cli,
                [
                    "--build-id",
                    "test-build",
                    "--namespace",
                    "test-ns",
                    "--config",
                    str(config_path),
                    "upload-files",
                    "--parent-package",
                    "test-pkg",
                    "--rpm",
                    str(rpm_file1),
                    "--rpm",
                    str(rpm_file2),
                ],
            )
            assert result.exit_code == 0
            call_args = mock_helper.process_file_uploads.call_args
            context = call_args[0][1]
            assert len(context.rpm_files) == 2
