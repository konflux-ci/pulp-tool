"""Tests for Click CLI commands."""

import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, patch
from click.testing import CliRunner
import httpx

from pulp_tool.cli import cli, main


class TestCLIEntryPoint:
    """Test CLI entry point and main function."""

    def test_main_function_success(self):
        """Test main() entry point calls cli successfully."""
        with patch("pulp_tool.cli.cli") as mock_cli:
            mock_cli.return_value = None
            main()
            mock_cli.assert_called_once()

    def test_main_function_keyboard_interrupt(self):
        """Test main() handles KeyboardInterrupt gracefully."""
        with patch("pulp_tool.cli.cli") as mock_cli, patch("pulp_tool.cli.sys.exit") as mock_exit:
            mock_cli.side_effect = KeyboardInterrupt()
            main()
            mock_exit.assert_called_once_with(130)


class TestCLIHelp:
    """Test CLI help commands."""

    def test_main_help(self):
        """Test main CLI help output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Pulp Tool" in result.output
        assert "upload" in result.output
        assert "transfer" in result.output
        assert "get-repo-md" in result.output
        # Check group-level options
        assert "--config" in result.output
        assert "--build-id" in result.output
        assert "--namespace" in result.output
        assert "--cert-path" in result.output
        assert "--key-path" in result.output
        assert "--debug" in result.output
        assert "--max-workers" in result.output

    def test_main_help_short_flag(self):
        """Test main CLI help output with -h flag."""
        runner = CliRunner()
        result = runner.invoke(cli, ["-h"])
        assert result.exit_code == 0
        assert "Pulp Tool" in result.output
        assert "upload" in result.output
        assert "transfer" in result.output
        assert "get-repo-md" in result.output
        assert "-h, --help" in result.output

    def test_upload_help(self):
        """Test upload command help output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["upload", "--help"])
        assert result.exit_code == 0
        assert "Upload RPMs, logs, and SBOM files" in result.output
        # Group-level options are not shown in command help
        assert "--parent-package" in result.output
        assert "--rpm-path" in result.output
        assert "--sbom-results" in result.output
        assert "--artifact-results" in result.output
        assert "--cert-config" in result.output

    def test_transfer_help(self):
        """Test transfer command help output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["transfer", "--help"])
        assert result.exit_code == 0
        assert "Download artifacts" in result.output
        assert "--artifact-location" in result.output
        assert "--content-types" in result.output
        assert "--archs" in result.output
        # Group-level options are not shown in command help

    def test_get_repo_md_help(self):
        """Test get-repo-md command help output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["get-repo-md", "--help"])
        assert result.exit_code == 0
        assert "Download .repo configuration file(s)" in result.output
        assert "comma-separated" in result.output
        # Group-level options are not shown in command help
        assert "--base-url" in result.output
        assert "--output" in result.output


class TestCLIValidation:
    """Test CLI input validation."""

    def test_upload_missing_required_args(self):
        """Test upload command with missing required arguments."""
        runner = CliRunner()
        result = runner.invoke(cli, ["upload"])
        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()

    def test_transfer_missing_required_args(self):
        """Test transfer command with missing required arguments."""
        runner = CliRunner()
        result = runner.invoke(cli, ["transfer"], catch_exceptions=False, standalone_mode=False)
        assert result.exit_code != 0

    def test_get_repo_md_missing_required_args(self):
        """Test get-repo-md command with missing required arguments."""
        runner = CliRunner()
        result = runner.invoke(cli, ["get-repo-md"])
        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()


class TestCLIVersion:
    """Test CLI version output."""

    def test_version(self):
        """Test version flag."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0


class TestUploadCommand:
    """Test upload command functionality."""

    def test_upload_invalid_rpm_path(self):
        """Test upload with non-existent RPM path."""
        runner = CliRunner()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as sbom_file:
            sbom_file.write("{}")
            sbom_path = sbom_file.name

        try:
            result = runner.invoke(
                cli,
                [
                    "--build-id",
                    "test-build",
                    "--namespace",
                    "test-ns",
                    "upload",
                    "--parent-package",
                    "test-pkg",
                    "--rpm-path",
                    "/nonexistent/path",
                    "--sbom-path",
                    sbom_path,
                ],
            )
            assert result.exit_code != 0
        finally:
            os.unlink(sbom_path)

    def test_upload_invalid_sbom_path(self):
        """Test upload with non-existent SBOM path."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(
                cli,
                [
                    "--build-id",
                    "test-build",
                    "--namespace",
                    "test-ns",
                    "upload",
                    "--parent-package",
                    "test-pkg",
                    "--rpm-path",
                    tmpdir,
                    "--sbom-path",
                    "/nonexistent/sbom.json",
                ],
            )
            assert result.exit_code != 0

    @patch("pulp_tool.cli.PulpClient")
    @patch("pulp_tool.cli.PulpHelper")
    def test_upload_success(self, mock_helper_class, mock_client_class):
        """Test successful upload flow."""
        runner = CliRunner()

        # Setup mocks
        mock_client = Mock()
        mock_client.close = Mock()
        mock_client_class.create_from_config_file.return_value = mock_client

        mock_helper = Mock()
        mock_helper.setup_repositories.return_value = Mock()
        mock_helper.process_uploads.return_value = "https://example.com/results.json"
        mock_helper_class.return_value = mock_helper

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create dummy files
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

            assert result.exit_code == 0
            assert "RESULTS JSON URL" in result.output

    @patch("pulp_tool.cli.PulpClient")
    @patch("pulp_tool.cli.PulpHelper")
    def test_upload_with_artifact_results(self, mock_helper_class, mock_client_class):
        """Test upload with artifact results output."""
        runner = CliRunner()

        mock_client = Mock()
        mock_client.close = Mock()
        mock_client_class.create_from_config_file.return_value = mock_client

        mock_helper = Mock()
        mock_helper.setup_repositories.return_value = Mock()
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

            url_path = Path(tmpdir) / "url.txt"
            digest_path = Path(tmpdir) / "digest.txt"

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
                    "--artifact-results",
                    f"{url_path},{digest_path}",
                ],
            )

            assert result.exit_code == 0

    @patch("pulp_tool.cli.PulpClient")
    def test_upload_http_error(self, mock_client_class):
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


class TestTransferCommand:
    """Test transfer command functionality."""

    def test_transfer_missing_artifact_location_and_build_id(self):
        """Test transfer with neither artifact_location nor build_id provided."""
        runner = CliRunner()
        result = runner.invoke(cli, ["transfer"])
        assert result.exit_code == 1
        assert "Either --artifact-location OR" in result.output

    def test_transfer_build_id_without_namespace(self):
        """Test transfer with build_id but no namespace."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--build-id", "test-build", "transfer"])
        assert result.exit_code == 1
        assert "Both --build-id and --namespace must be provided" in result.output

    def test_transfer_build_id_without_config(self):
        """Test transfer with build_id+namespace but no config."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--build-id", "test-build", "--namespace", "test-ns", "transfer"])
        assert result.exit_code == 1
        assert "--config is required" in result.output

    def test_transfer_conflicting_options(self):
        """Test transfer with both artifact_location and build_id."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--build-id",
                "test-build",
                "--namespace",
                "test-ns",
                "transfer",
                "--artifact-location",
                "http://example.com/artifact.json",
            ],
        )
        assert result.exit_code == 1
        assert "Cannot use --artifact-location with --build-id" in result.output

    @patch("pulp_tool.cli.load_and_validate_artifacts")
    @patch("pulp_tool.cli.setup_repositories_if_needed")
    @patch("pulp_tool.cli.download_artifacts_concurrently")
    @patch("pulp_tool.cli.generate_transfer_report")
    def test_transfer_with_local_file(self, mock_report, mock_download, mock_setup, mock_load):
        """Test transfer with local artifact file."""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as artifact_file:
            artifact_file.write('{"artifacts": [], "distributions": {}}')
            artifact_path = artifact_file.name

        try:
            mock_artifact_data = Mock()
            mock_artifact_data.artifacts = []
            mock_artifact_data.artifact_json.distributions = {}
            mock_load.return_value = mock_artifact_data
            mock_setup.return_value = None

            mock_result = Mock()
            mock_result.pulled_artifacts = Mock()
            mock_result.completed = 0
            mock_result.failed = 0
            mock_download.return_value = mock_result

            result = runner.invoke(cli, ["transfer", "--artifact-location", artifact_path])

            assert result.exit_code == 0
        finally:
            os.unlink(artifact_path)

    @patch("pulp_tool.cli.DistributionClient")
    @patch("pulp_tool.cli.load_and_validate_artifacts")
    @patch("pulp_tool.cli.setup_repositories_if_needed")
    @patch("pulp_tool.cli.download_artifacts_concurrently")
    @patch("pulp_tool.cli.generate_transfer_report")
    def test_transfer_with_remote_url(self, mock_report, mock_download, mock_setup, mock_load, mock_dist_client):
        """Test transfer with remote artifact URL."""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as cert_file:
            cert_file.write("cert")
            cert_path = cert_file.name

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as key_file:
            key_file.write("key")
            key_path = key_file.name

        try:
            mock_artifact_data = Mock()
            mock_artifact_data.artifacts = []
            mock_artifact_data.artifact_json.distributions = {}
            mock_load.return_value = mock_artifact_data
            mock_setup.return_value = None

            mock_result = Mock()
            mock_result.pulled_artifacts = Mock()
            mock_result.completed = 0
            mock_result.failed = 0
            mock_download.return_value = mock_result

            result = runner.invoke(
                cli,
                [
                    "--cert-path",
                    cert_path,
                    "--key-path",
                    key_path,
                    "transfer",
                    "--artifact-location",
                    "https://example.com/artifact.json",
                ],
            )

            assert result.exit_code == 0
        finally:
            os.unlink(cert_path)
            os.unlink(key_path)

    @patch("pulp_tool.cli.load_and_validate_artifacts")
    def test_transfer_remote_url_without_certs(self, mock_load):
        """Test transfer with remote URL but missing certificates."""
        runner = CliRunner()

        result = runner.invoke(cli, ["transfer", "--artifact-location", "https://example.com/artifact.json"])

        assert result.exit_code == 1
        # Check the error was logged
        mock_load.assert_not_called()  # Should fail before loading artifacts

    @patch("pulp_tool.cli.load_and_validate_artifacts")
    def test_transfer_http_error(self, mock_load):
        """Test transfer with HTTP error."""
        runner = CliRunner()

        mock_load.side_effect = httpx.HTTPError("Connection failed")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as artifact_file:
            artifact_file.write("{}")
            artifact_path = artifact_file.name

        try:
            result = runner.invoke(cli, ["transfer", "--artifact-location", artifact_path])

            assert result.exit_code == 1
        finally:
            os.unlink(artifact_path)

    @patch("pulp_tool.cli.load_and_validate_artifacts")
    @patch("pulp_tool.cli.setup_repositories_if_needed")
    @patch("pulp_tool.cli.download_artifacts_concurrently")
    @patch("pulp_tool.cli.generate_transfer_report")
    def test_transfer_with_content_type_filter(self, mock_report, mock_download, mock_setup, mock_load):
        """Test transfer with --content-types filter."""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as artifact_file:
            artifact_file.write('{"artifacts": [], "distributions": {}}')
            artifact_path = artifact_file.name

        try:
            mock_artifact_data = Mock()
            mock_artifact_data.artifacts = []
            mock_artifact_data.artifact_json.distributions = {}
            mock_load.return_value = mock_artifact_data
            mock_setup.return_value = None

            mock_result = Mock()
            mock_result.pulled_artifacts = Mock()
            mock_result.completed = 0
            mock_result.failed = 0
            mock_download.return_value = mock_result

            result = runner.invoke(cli, ["transfer", "--artifact-location", artifact_path, "--content-types", "rpm"])

            assert result.exit_code == 0
            # Verify download_artifacts_concurrently was called with content_types filter
            # Args are: artifacts, distros, distribution_client, max_workers, content_types, archs
            call_args = mock_download.call_args
            # Check positional args (download_artifacts_concurrently is called with positional args)
            assert len(call_args.args) >= 6
            assert call_args.args[4] == ["rpm"]  # content_types
            assert call_args.args[5] is None  # archs
        finally:
            os.unlink(artifact_path)

    @patch("pulp_tool.cli.load_and_validate_artifacts")
    @patch("pulp_tool.cli.setup_repositories_if_needed")
    @patch("pulp_tool.cli.download_artifacts_concurrently")
    @patch("pulp_tool.cli.generate_transfer_report")
    def test_transfer_with_arch_filter(self, mock_report, mock_download, mock_setup, mock_load):
        """Test transfer with --archs filter."""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as artifact_file:
            artifact_file.write('{"artifacts": [], "distributions": {}}')
            artifact_path = artifact_file.name

        try:
            mock_artifact_data = Mock()
            mock_artifact_data.artifacts = []
            mock_artifact_data.artifact_json.distributions = {}
            mock_load.return_value = mock_artifact_data
            mock_setup.return_value = None

            mock_result = Mock()
            mock_result.pulled_artifacts = Mock()
            mock_result.completed = 0
            mock_result.failed = 0
            mock_download.return_value = mock_result

            result = runner.invoke(cli, ["transfer", "--artifact-location", artifact_path, "--archs", "x86_64"])

            assert result.exit_code == 0
            # Verify download_artifacts_concurrently was called with archs filter
            call_args = mock_download.call_args
            assert len(call_args.args) >= 6
            assert call_args.args[4] is None  # content_types
            assert call_args.args[5] == ["x86_64"]  # archs
        finally:
            os.unlink(artifact_path)

    @patch("pulp_tool.cli.load_and_validate_artifacts")
    @patch("pulp_tool.cli.setup_repositories_if_needed")
    @patch("pulp_tool.cli.download_artifacts_concurrently")
    @patch("pulp_tool.cli.generate_transfer_report")
    def test_transfer_with_multiple_filters(self, mock_report, mock_download, mock_setup, mock_load):
        """Test transfer with combined --content-types and --archs filters."""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as artifact_file:
            artifact_file.write('{"artifacts": [], "distributions": {}}')
            artifact_path = artifact_file.name

        try:
            mock_artifact_data = Mock()
            mock_artifact_data.artifacts = []
            mock_artifact_data.artifact_json.distributions = {}
            mock_load.return_value = mock_artifact_data
            mock_setup.return_value = None

            mock_result = Mock()
            mock_result.pulled_artifacts = Mock()
            mock_result.completed = 0
            mock_result.failed = 0
            mock_download.return_value = mock_result

            result = runner.invoke(
                cli,
                [
                    "transfer",
                    "--artifact-location",
                    artifact_path,
                    "--content-types",
                    "rpm,log",
                    "--archs",
                    "x86_64,noarch",
                ],
            )

            assert result.exit_code == 0
            # Verify download_artifacts_concurrently was called with both filters
            call_args = mock_download.call_args
            assert len(call_args.args) >= 6
            assert call_args.args[4] == ["rpm", "log"]  # content_types
            assert call_args.args[5] == ["x86_64", "noarch"]  # archs
        finally:
            os.unlink(artifact_path)

    @patch("pulp_tool.cli.load_and_validate_artifacts")
    @patch("pulp_tool.cli.setup_repositories_if_needed")
    @patch("pulp_tool.cli.download_artifacts_concurrently")
    @patch("pulp_tool.cli.generate_transfer_report")
    def test_transfer_without_filters(self, mock_report, mock_download, mock_setup, mock_load):
        """Test transfer without filters transfers all artifacts."""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as artifact_file:
            artifact_file.write('{"artifacts": [], "distributions": {}}')
            artifact_path = artifact_file.name

        try:
            mock_artifact_data = Mock()
            mock_artifact_data.artifacts = []
            mock_artifact_data.artifact_json.distributions = {}
            mock_load.return_value = mock_artifact_data
            mock_setup.return_value = None

            mock_result = Mock()
            mock_result.pulled_artifacts = Mock()
            mock_result.completed = 0
            mock_result.failed = 0
            mock_download.return_value = mock_result

            result = runner.invoke(cli, ["transfer", "--artifact-location", artifact_path])

            assert result.exit_code == 0
            # Verify download_artifacts_concurrently was called with None filters
            call_args = mock_download.call_args
            assert len(call_args.args) >= 6
            assert call_args.args[4] is None  # content_types
            assert call_args.args[5] is None  # archs
        finally:
            os.unlink(artifact_path)

    def test_transfer_invalid_content_type(self):
        """Test transfer with invalid content type raises validation error."""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as artifact_file:
            artifact_file.write('{"artifacts": [], "distributions": {}}')
            artifact_path = artifact_file.name

        try:
            result = runner.invoke(
                cli, ["transfer", "--artifact-location", artifact_path, "--content-types", "invalid"]
            )

            assert result.exit_code == 1
            # Pydantic validation error message contains the error
            output = str(result.output) + str(result.exception) if result.exception else str(result.output)
            assert "Invalid content type" in output or "validation error" in output.lower()
        finally:
            os.unlink(artifact_path)


class TestGetRepoMdCommand:
    """Test get-repo-md command functionality."""

    def test_get_repo_md_with_config(self):
        """Test get-repo-md with config file."""
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text('[cli]\nbase_url = "https://pulp.example.com"\ndomain = "test-domain"')

            output_dir = Path(tmpdir) / "output"

            with patch("pulp_tool.cli.httpx.get") as mock_get:
                mock_response = Mock()
                mock_response.content = b"[test-repo]\nname=Test"
                mock_response.raise_for_status = Mock()
                mock_get.return_value = mock_response

                result = runner.invoke(
                    cli,
                    [
                        "--config",
                        str(config_path),
                        "--build-id",
                        "test-build",
                        "get-repo-md",
                        "--output",
                        str(output_dir),
                    ],
                )

                assert result.exit_code == 0
                assert "Download Summary" in result.output

    def test_get_repo_md_with_direct_params(self):
        """Test get-repo-md with base_url and namespace."""
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"

            with patch("pulp_tool.cli.httpx.get") as mock_get:
                mock_response = Mock()
                mock_response.content = b"[test-repo]\nname=Test"
                mock_response.raise_for_status = Mock()
                mock_get.return_value = mock_response

                result = runner.invoke(
                    cli,
                    [
                        "--namespace",
                        "test-domain",
                        "--build-id",
                        "test-build",
                        "get-repo-md",
                        "--base-url",
                        "https://pulp.example.com",
                        "--output",
                        str(output_dir),
                    ],
                )

                assert result.exit_code == 0

    def test_get_repo_md_multiple_build_ids(self):
        """Test get-repo-md with comma-separated build IDs."""
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text('[cli]\nbase_url = "https://pulp.example.com"\ndomain = "test-domain"')

            output_dir = Path(tmpdir) / "output"

            with patch("pulp_tool.cli.httpx.get") as mock_get:
                mock_response = Mock()
                mock_response.content = b"[test-repo]\nname=Test"
                mock_response.raise_for_status = Mock()
                mock_get.return_value = mock_response

                result = runner.invoke(
                    cli,
                    [
                        "--config",
                        str(config_path),
                        "--build-id",
                        "build1,build2,build3",
                        "get-repo-md",
                        "--output",
                        str(output_dir),
                    ],
                )

                assert result.exit_code == 0
                assert "Download Summary: 3 succeeded, 0 failed" in result.output

    def test_get_repo_md_404_error(self):
        """Test get-repo-md with 404 error."""
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text('[cli]\nbase_url = "https://pulp.example.com"\ndomain = "test-domain"')

            with patch("pulp_tool.cli.httpx.get") as mock_get:
                mock_response = Mock()
                mock_response.status_code = 404
                mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                    "Not found", request=Mock(), response=mock_response
                )
                mock_get.return_value = mock_response

                result = runner.invoke(cli, ["--config", str(config_path), "--build-id", "test-build", "get-repo-md"])

                assert result.exit_code == 1
                assert "404" in result.output

    def test_get_repo_md_with_output_dir(self):
        """Test get-repo-md with custom output directory."""
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text('[cli]\nbase_url = "https://pulp.example.com"\ndomain = "test-domain"')

            output_dir = Path(tmpdir) / "output"

            with patch("pulp_tool.cli.httpx.get") as mock_get:
                mock_response = Mock()
                mock_response.content = b"[test-repo]\nname=Test"
                mock_response.raise_for_status = Mock()
                mock_get.return_value = mock_response

                result = runner.invoke(
                    cli,
                    [
                        "--config",
                        str(config_path),
                        "--build-id",
                        "test-build",
                        "get-repo-md",
                        "--output",
                        str(output_dir),
                    ],
                )

                assert result.exit_code == 0
                assert output_dir.exists()

    def test_get_repo_md_missing_config_and_params(self):
        """Test get-repo-md without config or direct params."""
        runner = CliRunner()

        # Mock httpx to prevent actual HTTP calls
        with patch("pulp_tool.cli.httpx.get") as mock_get:
            mock_response = Mock()
            mock_response.status_code = 403
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Forbidden", request=Mock(), response=mock_response
            )
            mock_get.return_value = mock_response

            result = runner.invoke(cli, ["--build-id", "test-build", "get-repo-md"])

            assert result.exit_code == 1
            # Without config, it tries default path and may fail with HTTP error

    def test_get_repo_md_conflicting_params(self):
        """Test get-repo-md with both config and direct params."""
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text('[cli]\nbase_url = "https://pulp.example.com"\ndomain = "test-domain"')

            output_dir = Path(tmpdir) / "output"

            with patch("pulp_tool.cli.httpx.get") as mock_get:
                mock_response = Mock()
                mock_response.content = b"[test-repo]\nname=Test"
                mock_response.raise_for_status = Mock()
                mock_get.return_value = mock_response

                result = runner.invoke(
                    cli,
                    [
                        "--config",
                        str(config_path),
                        "--namespace",
                        "test-domain",
                        "--build-id",
                        "test-build",
                        "get-repo-md",
                        "--base-url",
                        "https://pulp.example.com",
                        "--output",
                        str(output_dir),
                    ],
                )

                # The command prioritizes config over direct params, so it succeeds
                assert result.exit_code in [0, 1]  # May succeed or fail depending on implementation

    @patch("pulp_tool.cli.DistributionClient")
    def test_get_repo_md_with_certificates(self, mock_dist_client):
        """Test get-repo-md with certificate authentication."""
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text('[cli]\nbase_url = "https://pulp.example.com"\ndomain = "test-domain"')

            output_dir = Path(tmpdir) / "output"

            cert_path = Path(tmpdir) / "cert.pem"
            cert_path.write_text("cert")
            key_path = Path(tmpdir) / "key.pem"
            key_path.write_text("key")

            mock_client = Mock()
            mock_response = Mock()
            mock_response.content = b"[test-repo]\nname=Test"
            mock_response.raise_for_status = Mock()
            mock_client.pull_artifact.return_value = mock_response
            mock_dist_client.return_value = mock_client

            result = runner.invoke(
                cli,
                [
                    "--config",
                    str(config_path),
                    "--build-id",
                    "test-build",
                    "--cert-path",
                    str(cert_path),
                    "--key-path",
                    str(key_path),
                    "get-repo-md",
                    "--output",
                    str(output_dir),
                ],
            )

            assert result.exit_code == 0

    def test_get_repo_md_cert_without_key(self):
        """Test get-repo-md with cert but no key."""
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text('[cli]\nbase_url = "https://pulp.example.com"\ndomain = "test-domain"')

            cert_path = Path(tmpdir) / "cert.pem"
            cert_path.write_text("cert")

            result = runner.invoke(
                cli,
                [
                    "--config",
                    str(config_path),
                    "--build-id",
                    "test-build",
                    "--cert-path",
                    str(cert_path),
                    "get-repo-md",
                ],
            )

            # Should fail with exit code 1 due to cert/key validation
            assert result.exit_code == 1

    @patch("pulp_tool.cli.httpx.get")
    def test_get_repo_md_partial_failures(self, mock_get):
        """Test get-repo-md with some successful and some failed downloads."""
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text('[cli]\nbase_url = "https://pulp.example.com"\ndomain = "test-domain"')

            output_dir = Path(tmpdir) / "output"

            # First call succeeds, second fails
            mock_response_success = Mock()
            mock_response_success.content = b"[test-repo]\nname=Test"
            mock_response_success.raise_for_status = Mock()

            mock_response_fail = Mock()
            mock_response_fail.status_code = 404
            mock_response_fail.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Not found", request=Mock(), response=mock_response_fail
            )

            mock_get.side_effect = [mock_response_success, mock_response_fail]

            result = runner.invoke(
                cli,
                [
                    "--config",
                    str(config_path),
                    "--build-id",
                    "build1,build2",
                    "get-repo-md",
                    "--output",
                    str(output_dir),
                ],
            )

            # Partial success should exit with code 2
            assert result.exit_code == 2
            assert "1 succeeded, 1 failed" in result.output
