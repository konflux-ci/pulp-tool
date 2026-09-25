"""Tests for upload CLI (HTTP errors, results JSON)."""

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from click.testing import CliRunner

from pulp_tool.cli import cli


class TestUploadCommandErrorsAndResultsJson:
    """Upload command: HTTP errors, results JSON extraction."""

    @patch("pulp_tool.cli.upload_build.PulpClient")
    def test_upload_http_error(self, mock_client_class) -> None:
        """Test upload with HTTP error."""
        runner = CliRunner()
        mock_client_class.create_from_config_file.side_effect = httpx.HTTPError("Connection failed")
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
    def test_upload_auth_http_error_exits_one(self, mock_client_class) -> None:
        """Auth-style HTTP errors exit 1 like other HTTP failures."""
        runner = CliRunner()
        mock_client_class.create_from_config_file.side_effect = httpx.HTTPError("401 Unauthorized")
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
    def test_upload_runtime_error_no_access_token_exits_one(self, mock_client_class) -> None:
        """OAuth token failure (RuntimeError) is a failed upload."""
        runner = CliRunner()
        mock_client_class.create_from_config_file.side_effect = RuntimeError("Failed to obtain access token")
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

    def test_upload_missing_build_id(self) -> None:
        """Test upload command with missing build-id."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            rpm_dir = Path(tmpdir) / "rpms"
            rpm_dir.mkdir()
            sbom_path = Path(tmpdir) / "sbom.json"
            sbom_path.write_text("{}")
            result = runner.invoke(
                cli,
                [
                    "--namespace",
                    "test-ns",
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
            assert "--build-id is required" in result.output

    def test_upload_missing_namespace(self) -> None:
        """Test upload command with missing namespace."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            rpm_dir = Path(tmpdir) / "rpms"
            rpm_dir.mkdir()
            sbom_path = Path(tmpdir) / "sbom.json"
            sbom_path.write_text("{}")
            result = runner.invoke(
                cli,
                [
                    "--build-id",
                    "test-build",
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
            assert "--namespace is required" in result.output

    def test_upload_files_base_path_without_results_json(self) -> None:
        """Test --files-base-path without --results-json fails."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir) / "files"
            base_path.mkdir()
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
                    "--files-base-path",
                    str(base_path),
                ],
            )
            assert result.exit_code == 1
            assert "--files-base-path can only be used with --results-json" in result.output

    @patch("pulp_tool.cli.upload_build.PulpClient")
    @patch("pulp_tool.cli.upload_build.PulpHelper")
    def test_upload_with_results_json(self, mock_helper_class, mock_client_class) -> None:
        """Test upload with --results-json invokes process_uploads with results_json context."""
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
            results_json_path = Path(tmpdir) / "pulp_results.json"
            results_json_path.write_text('{"artifacts": {}}')
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
                    "--results-json",
                    str(results_json_path),
                    "--signed-by",
                    "key-123",
                ],
            )
            assert result.exit_code == 0
            mock_helper.setup_repositories.assert_called_once_with(
                "test-build",
                signed_by="key-123",
                skip_artifacts_repo=False,
                target_arch_repo=False,
                skip_logs_repo=True,
                skip_sbom_repo=True,
            )
            mock_helper.process_uploads.assert_called_once()
            call_args = mock_helper.process_uploads.call_args[0]
            assert call_args[2].rpms_href == "/test/"
            context = call_args[1]
            assert context.results_json == str(results_json_path)
            assert context.signed_by == "key-123"

    @patch("pulp_tool.cli.upload_build.PulpClient")
    @patch("pulp_tool.cli.upload_build.PulpHelper")
    def test_upload_results_json_extracts_build_id_namespace(self, mock_helper_class, mock_client_class) -> None:
        """Test upload with --results-json extracts build_id and namespace from artifact labels."""
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
            results_json_path = Path(tmpdir) / "pulp_results.json"
            results_json_path.write_text(
                json.dumps(
                    {
                        "artifacts": {
                            "x86_64/pkg.rpm": {
                                "labels": {
                                    "build_id": "extracted-build",
                                    "namespace": "extracted-ns",
                                    "arch": "x86_64",
                                },
                                "url": "https://example.com/pkg.rpm",
                                "sha256": "abc123",
                            }
                        }
                    }
                )
            )
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                '[cli]\nbase_url = "https://pulp.example.com"\napi_root = "/pulp/api/v3"\ndomain = "test-domain"'
            )
            result = runner.invoke(
                cli, ["--config", str(config_path), "upload", "--results-json", str(results_json_path)]
            )
            assert result.exit_code == 0
            mock_helper.setup_repositories.assert_called_once_with(
                "extracted-build",
                signed_by=None,
                skip_artifacts_repo=False,
                target_arch_repo=False,
                skip_logs_repo=True,
                skip_sbom_repo=True,
            )
            context = mock_helper.process_uploads.call_args[0][1]
            assert context.build_id == "extracted-build"
            assert context.namespace == "extracted-ns"

    def test_upload_results_json_missing_build_id_namespace_in_json(self) -> None:
        """Test upload with --results-json but no build_id/namespace in artifact labels fails."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            results_json_path = Path(tmpdir) / "pulp_results.json"
            results_json_path.write_text('{"artifacts": {}}')
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                '[cli]\nbase_url = "https://pulp.example.com"\napi_root = "/pulp/api/v3"\ndomain = "test-domain"'
            )
            result = runner.invoke(
                cli, ["--config", str(config_path), "upload", "--results-json", str(results_json_path)]
            )
            assert result.exit_code == 1
            assert "build_id and namespace" in result.output or "no artifacts" in result.output.lower()
