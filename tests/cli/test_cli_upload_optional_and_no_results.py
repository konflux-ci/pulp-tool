"""Tests for upload CLI (optional paths, no results JSON)."""

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from click.testing import CliRunner

from pulp_tool.cli import cli


class TestUploadCommandOptionalAndNoResults:
    """Upload command: optional paths and edge cases."""

    def test_upload_results_json_invalid_json_fails(self) -> None:
        """Test upload with --results-json and invalid JSON raises clear error."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            results_json_path = Path(tmpdir) / "pulp_results.json"
            results_json_path.write_text("{ invalid json }")
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                '[cli]\nbase_url = "https://pulp.example.com"\napi_root = "/pulp/api/v3"\ndomain = "test-domain"'
            )
            result = runner.invoke(
                cli, ["--config", str(config_path), "upload", "--results-json", str(results_json_path)]
            )
            assert result.exit_code == 1
            assert "Failed to read results JSON" in result.output

    @patch("pulp_tool.cli.upload_build.PulpClient")
    @patch("pulp_tool.cli.upload_build.PulpHelper")
    def test_upload_no_results_json(self, mock_helper_class, mock_client_class) -> None:
        """Test upload when results JSON is not created."""
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
        mock_helper.process_uploads.return_value = None
        mock_helper_class.return_value = mock_helper
        with tempfile.TemporaryDirectory() as tmpdir:
            rpm_dir = Path(tmpdir) / "rpms"
            rpm_dir.mkdir()
            sbom_path = Path(tmpdir) / "sbom.json"
            sbom_path.write_text("{}")
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
                    "upload",
                    "--parent-package",
                    "test-pkg",
                    "--rpm-path",
                    str(rpm_dir),
                    "--sbom-path",
                    str(sbom_path),
                ],
            )
            assert result.exit_code == 1
            assert "results JSON was not created" in result.output

    @patch("pulp_tool.cli.upload_build.PulpClient")
    def test_upload_generic_exception(self, mock_client_class) -> None:
        """Test upload with generic exception."""
        runner = CliRunner()
        mock_client_class.create_from_config_file.side_effect = ValueError("Unexpected error")
        with tempfile.TemporaryDirectory() as tmpdir:
            rpm_dir = Path(tmpdir) / "rpms"
            rpm_dir.mkdir()
            sbom_path = Path(tmpdir) / "sbom.json"
            sbom_path.write_text("{}")
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
                    "upload",
                    "--parent-package",
                    "test-pkg",
                    "--rpm-path",
                    str(rpm_dir),
                    "--sbom-path",
                    str(sbom_path),
                ],
            )
            assert result.exit_code == 1

    @patch("pulp_tool.cli.upload_build.PulpClient")
    @patch("pulp_tool.cli.upload_build.PulpHelper")
    def test_upload_without_rpm_path(self, mock_helper_class, mock_client_class) -> None:
        """Test upload without rpm-path (should use current directory)."""
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
        mock_helper.process_uploads.return_value = "https://example.com/results.json"
        mock_helper_class.return_value = mock_helper
        with tempfile.TemporaryDirectory() as tmpdir:
            sbom_path = Path(tmpdir) / "sbom.json"
            sbom_path.write_text("{}")
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                '[cli]\nbase_url = "https://pulp.example.com"\napi_root = "/pulp/api/v3"\ndomain = "test-domain"'
            )
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                result = runner.invoke(
                    cli,
                    [
                        "--build-id",
                        "test-build",
                        "--namespace",
                        "test-ns",
                        "--config",
                        str(config_path),
                        "upload",
                        "--parent-package",
                        "test-pkg",
                        "--sbom-path",
                        str(sbom_path),
                    ],
                )
                assert result.exit_code == 0
                assert "RESULTS JSON:" in result.output
                call_args = mock_helper_class.call_args
                assert call_args is not None
            finally:
                os.chdir(original_cwd)

    @patch("pulp_tool.cli.upload_build.PulpClient")
    @patch("pulp_tool.cli.upload_build.PulpHelper")
    def test_upload_without_sbom_path(self, mock_helper_class, mock_client_class) -> None:
        """Test upload without sbom-path (should skip SBOM upload)."""
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
        mock_helper.process_uploads.return_value = "https://example.com/results.json"
        mock_helper_class.return_value = mock_helper
        with tempfile.TemporaryDirectory() as tmpdir:
            rpm_dir = Path(tmpdir) / "rpms"
            rpm_dir.mkdir()
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
                    "upload",
                    "--parent-package",
                    "test-pkg",
                    "--rpm-path",
                    str(rpm_dir),
                ],
            )
            assert result.exit_code == 0
            assert "RESULTS JSON:" in result.output

    @patch("pulp_tool.cli.upload_build.PulpClient")
    @patch("pulp_tool.cli.upload_build.PulpHelper")
    def test_upload_without_parent_package(self, mock_helper_class, mock_client_class) -> None:
        """Test upload without parent-package (should not include in labels)."""
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
        mock_helper.process_uploads.return_value = "https://example.com/results.json"
        mock_helper_class.return_value = mock_helper
        with tempfile.TemporaryDirectory() as tmpdir:
            rpm_dir = Path(tmpdir) / "rpms"
            rpm_dir.mkdir()
            sbom_path = Path(tmpdir) / "sbom.json"
            sbom_path.write_text("{}")
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
                    "upload",
                    "--rpm-path",
                    str(rpm_dir),
                    "--sbom-path",
                    str(sbom_path),
                ],
            )
            assert result.exit_code == 0
            assert "RESULTS JSON:" in result.output
            call_args = mock_helper_class.call_args
            assert call_args is not None
            assert call_args.kwargs.get("parent_package") is None

    @patch("pulp_tool.cli.upload_build.PulpClient")
    @patch("pulp_tool.cli.upload_build.PulpHelper")
    def test_upload_all_optional_omitted(self, mock_helper_class, mock_client_class) -> None:
        """Test upload with all optional parameters omitted."""
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
        mock_helper.process_uploads.return_value = "https://example.com/results.json"
        mock_helper_class.return_value = mock_helper
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                '[cli]\nbase_url = "https://pulp.example.com"\napi_root = "/pulp/api/v3"\ndomain = "test-domain"'
            )
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                result = runner.invoke(
                    cli, ["--build-id", "test-build", "--namespace", "test-ns", "--config", str(config_path), "upload"]
                )
                assert result.exit_code == 0
                assert "RESULTS JSON:" in result.output
            finally:
                os.chdir(original_cwd)
