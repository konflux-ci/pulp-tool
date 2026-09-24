"""Tests for pull CLI (filters and transfer setup)."""

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from click.testing import CliRunner

from pulp_tool.cli import cli


class TestPullCommandFiltersAndTransfer:
    """Pull command: filters, local/remote transfer, config."""

    def test_pull_missing_artifact_location_and_build_id(self) -> None:
        """Test pull with neither artifact_location nor build_id provided."""
        runner = CliRunner()
        result = runner.invoke(cli, ["pull"])
        assert result.exit_code == 1
        assert "Either --artifact-location OR" in result.output

    def test_pull_build_id_without_namespace(self) -> None:
        """Test pull with build_id but no namespace."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--build-id", "test-build", "pull"])
        assert result.exit_code == 1
        assert "Both --build-id and --namespace must be provided" in result.output

    def test_pull_build_id_without_config(self) -> None:
        """Test pull with build_id+namespace but no --transfer-dest or --config."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--build-id", "test-build", "--namespace", "test-ns", "pull"])
        assert result.exit_code == 1
        assert "transfer-dest" in result.output.lower() or "config" in result.output.lower()

    def test_pull_conflicting_options(self) -> None:
        """Test pull with both artifact_location and build_id."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--build-id",
                "test-build",
                "--namespace",
                "test-ns",
                "pull",
                "--artifact-location",
                "http://example.com/artifact.json",
            ],
        )
        assert result.exit_code == 1
        assert "Cannot use --artifact-location with --build-id" in result.output

    @patch("pulp_tool.cli.pull.load_and_validate_artifacts")
    @patch("pulp_tool.cli.pull.setup_repositories_if_needed")
    @patch("pulp_tool.cli.pull.download_artifacts_concurrently")
    @patch("pulp_tool.cli.pull.generate_pull_report")
    def test_transfer_with_local_file(self, mock_report, mock_download, mock_setup, mock_load) -> None:
        """Test transfer with local artifact file."""
        runner = CliRunner()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as artifact_file:
            artifact_file.write('{"artifacts": {"test.rpm": {"labels": {"build_id": "test"}}}, "distributions": {}}')
            artifact_path = artifact_file.name
        try:
            from pulp_tool.models.artifacts import ArtifactData, ArtifactJsonResponse, ArtifactMetadata

            mock_artifact_data = ArtifactData(
                artifact_json=ArtifactJsonResponse(
                    artifacts={"test.rpm": ArtifactMetadata(labels={"build_id": "test"})}, distributions={}
                ),
                artifacts={"test.rpm": ArtifactMetadata(labels={"build_id": "test"})},
            )
            mock_load.return_value = mock_artifact_data
            mock_setup.return_value = None
            mock_result = Mock()
            mock_result.pulled_artifacts = Mock()
            mock_result.completed = 0
            mock_result.failed = 0
            mock_download.return_value = mock_result
            result = runner.invoke(cli, ["pull", "--artifact-location", artifact_path])
            assert result.exit_code == 0
        finally:
            os.unlink(artifact_path)

    @patch("pulp_tool.cli.pull.DistributionClient")
    @patch("pulp_tool.cli.pull.load_and_validate_artifacts")
    @patch("pulp_tool.cli.pull.setup_repositories_if_needed")
    @patch("pulp_tool.cli.pull.download_artifacts_concurrently")
    @patch("pulp_tool.cli.pull.generate_pull_report")
    def test_transfer_with_remote_url(
        self, mock_report, mock_download, mock_setup, mock_load, mock_dist_client
    ) -> None:
        """Test transfer with remote artifact URL."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = Path(tmpdir) / "cert.pem"
            cert_path.write_text("cert")
            key_path = Path(tmpdir) / "key.pem"
            key_path.write_text("key")
            config_path = Path(tmpdir) / "config.toml"
            config_content = f'[cli]\nbase_url = "https://pulp.example.com"\ncert = "{cert_path}"\nkey = "{key_path}"'
            config_path.write_text(config_content)
            from pulp_tool.models.artifacts import ArtifactData, ArtifactJsonResponse, ArtifactMetadata

            mock_artifact_data = ArtifactData(
                artifact_json=ArtifactJsonResponse(
                    artifacts={"test.rpm": ArtifactMetadata(labels={"build_id": "test"})}, distributions={}
                ),
                artifacts={"test.rpm": ArtifactMetadata(labels={"build_id": "test"})},
            )
            mock_load.return_value = mock_artifact_data
            mock_setup.return_value = None
            mock_client_instance = Mock()
            mock_dist_client.return_value = mock_client_instance
            mock_result = Mock()
            mock_result.pulled_artifacts = Mock()
            mock_result.completed = 0
            mock_result.failed = 0
            mock_download.return_value = mock_result
            result = runner.invoke(
                cli,
                [
                    "pull",
                    "--artifact-location",
                    "https://example.com/artifact.json",
                    "--cert-path",
                    str(cert_path),
                    "--key-path",
                    str(key_path),
                ],
            )
            assert result.exit_code == 0

    @patch("pulp_tool.cli.pull.DistributionClient")
    @patch("pulp_tool.cli.pull.load_and_validate_artifacts")
    @patch("pulp_tool.cli.pull.setup_repositories_if_needed")
    @patch("pulp_tool.cli.pull.download_artifacts_concurrently")
    @patch("pulp_tool.cli.pull.generate_pull_report")
    def test_transfer_with_key_from_config(
        self, mock_report, mock_download, mock_setup, mock_load, mock_dist_client
    ) -> None:
        """Test transfer with key_path loaded from config when not provided via CLI."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = Path(tmpdir) / "cert.pem"
            cert_path.write_text("cert")
            key_path = Path(tmpdir) / "key.pem"
            key_path.write_text("key")
            config_path = Path(tmpdir) / "config.toml"
            config_content = f'[cli]\nbase_url = "https://pulp.example.com"\ncert = "{cert_path}"\nkey = "{key_path}"'
            config_path.write_text(config_content)
            from pulp_tool.models.artifacts import ArtifactData, ArtifactJsonResponse, ArtifactMetadata

            mock_artifact_data = ArtifactData(
                artifact_json=ArtifactJsonResponse(
                    artifacts={"test.rpm": ArtifactMetadata(labels={"build_id": "test"})}, distributions={}
                ),
                artifacts={"test.rpm": ArtifactMetadata(labels={"build_id": "test"})},
            )
            mock_load.return_value = mock_artifact_data
            mock_setup.return_value = None
            mock_client_instance = Mock()
            mock_dist_client.return_value = mock_client_instance
            mock_result = Mock()
            mock_result.pulled_artifacts = Mock()
            mock_result.completed = 0
            mock_result.failed = 0
            mock_download.return_value = mock_result
            result = runner.invoke(
                cli,
                [
                    "pull",
                    "--artifact-location",
                    "https://example.com/artifact.json",
                    "--transfer-dest",
                    str(config_path),
                ],
            )
            assert result.exit_code == 0

    @patch("pulp_tool.cli.pull.DistributionClient")
    @patch("pulp_tool.cli.pull.load_and_validate_artifacts")
    @patch("pulp_tool.cli.pull.setup_repositories_if_needed")
    @patch("pulp_tool.cli.pull.download_artifacts_concurrently")
    @patch("pulp_tool.cli.pull.generate_pull_report")
    def test_pull_with_username_password_from_config(
        self, mock_report, mock_download, mock_setup, mock_load, mock_dist_client
    ) -> None:
        """Test pull with username/password from config (no cert/key)."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                '[cli]\nbase_url = "https://pulp.example.com"\nusername = "myuser"\npassword = "mypass"\n'
            )
            from pulp_tool.models.artifacts import ArtifactData, ArtifactJsonResponse, ArtifactMetadata

            mock_artifact_data = ArtifactData(
                artifact_json=ArtifactJsonResponse(
                    artifacts={"test.rpm": ArtifactMetadata(labels={"build_id": "test"})}, distributions={}
                ),
                artifacts={"test.rpm": ArtifactMetadata(labels={"build_id": "test"})},
            )
            mock_load.return_value = mock_artifact_data
            mock_setup.return_value = None
            mock_client_instance = Mock()
            mock_dist_client.return_value = mock_client_instance
            mock_result = Mock()
            mock_result.pulled_artifacts = Mock()
            mock_result.completed = 0
            mock_result.failed = 0
            mock_download.return_value = mock_result
            result = runner.invoke(
                cli,
                [
                    "pull",
                    "--artifact-location",
                    "https://example.com/artifact.json",
                    "--transfer-dest",
                    str(config_path),
                ],
            )
            assert result.exit_code == 0
            mock_dist_client.assert_called_once_with(username="myuser", password="mypass")

    @patch("pulp_tool.cli.pull.DistributionClient")
    @patch("pulp_tool.cli.pull.load_and_validate_artifacts")
    @patch("pulp_tool.cli.pull.setup_repositories_if_needed")
    @patch("pulp_tool.cli.pull.download_artifacts_concurrently")
    @patch("pulp_tool.cli.pull.generate_pull_report")
    def test_pull_with_distribution_config(
        self, mock_report, mock_download, mock_setup, mock_load, mock_dist_client
    ) -> None:
        """Test pull with --distribution-config overrides transfer-dest for auth."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            transfer_config = Path(tmpdir) / "transfer.toml"
            transfer_config.write_text(
                '[cli]\nbase_url = "https://pulp.example.com"\ncert = "/tmp/cert.pem"\nkey = "/tmp/key.pem"\n'
            )
            dist_config = Path(tmpdir) / "dist_auth.toml"
            dist_config.write_text('[cli]\nusername = "distuser"\npassword = "distpass"\n')
            from pulp_tool.models.artifacts import ArtifactData, ArtifactJsonResponse, ArtifactMetadata

            mock_artifact_data = ArtifactData(
                artifact_json=ArtifactJsonResponse(
                    artifacts={"test.rpm": ArtifactMetadata(labels={"build_id": "test"})}, distributions={}
                ),
                artifacts={"test.rpm": ArtifactMetadata(labels={"build_id": "test"})},
            )
            mock_load.return_value = mock_artifact_data
            mock_setup.return_value = None
            mock_client_instance = Mock()
            mock_dist_client.return_value = mock_client_instance
            mock_result = Mock()
            mock_result.pulled_artifacts = Mock()
            mock_result.completed = 0
            mock_result.failed = 0
            mock_download.return_value = mock_result
            result = runner.invoke(
                cli,
                [
                    "pull",
                    "--artifact-location",
                    "https://example.com/artifact.json",
                    "--transfer-dest",
                    str(transfer_config),
                    "--distribution-config",
                    str(dist_config),
                ],
            )
            assert result.exit_code == 0
            mock_dist_client.assert_called_once_with(username="distuser", password="distpass")

    @patch("pulp_tool.cli.pull.load_and_validate_artifacts")
    def test_transfer_config_load_exception(self, mock_load) -> None:
        """Test transfer when config file loading raises an exception."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "invalid_config.toml"
            config_path.write_text("invalid toml content [unclosed")
            result = runner.invoke(
                cli,
                [
                    "pull",
                    "--artifact-location",
                    "https://example.com/artifact.json",
                    "--transfer-dest",
                    str(config_path),
                ],
            )
            assert result.exit_code == 1
            mock_load.assert_not_called()

    @patch("pulp_tool.cli.pull.load_and_validate_artifacts")
    def test_transfer_remote_url_without_certs(self, mock_load) -> None:
        """Test transfer with remote URL but missing certificates."""
        runner = CliRunner()
        result = runner.invoke(cli, ["pull", "--artifact-location", "https://example.com/artifact.json"])
        assert result.exit_code == 1
        mock_load.assert_not_called()

    @patch("pulp_tool.cli.pull.load_and_validate_artifacts")
    def test_transfer_http_error(self, mock_load) -> None:
        """Test transfer with HTTP error."""
        runner = CliRunner()
        mock_load.side_effect = httpx.HTTPError("Connection failed")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as artifact_file:
            artifact_file.write("{}")
            artifact_path = artifact_file.name
        try:
            result = runner.invoke(cli, ["pull", "--artifact-location", artifact_path])
            assert result.exit_code == 1
        finally:
            os.unlink(artifact_path)

    @patch("pulp_tool.cli.pull.load_and_validate_artifacts")
    @patch("pulp_tool.cli.pull.setup_repositories_if_needed")
    @patch("pulp_tool.cli.pull.download_artifacts_concurrently")
    @patch("pulp_tool.cli.pull.generate_pull_report")
    def test_transfer_with_content_type_filter(self, mock_report, mock_download, mock_setup, mock_load) -> None:
        """Test transfer with --content-types filter."""
        runner = CliRunner()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as artifact_file:
            artifact_file.write('{"artifacts": [], "distributions": {}}')
            artifact_path = artifact_file.name
        try:
            from pulp_tool.models.artifacts import ArtifactData, ArtifactJsonResponse, ArtifactMetadata

            mock_artifact_data = ArtifactData(
                artifact_json=ArtifactJsonResponse(
                    artifacts={"test.rpm": ArtifactMetadata(labels={"build_id": "test"})}, distributions={}
                ),
                artifacts={"test.rpm": ArtifactMetadata(labels={"build_id": "test"})},
            )
            mock_load.return_value = mock_artifact_data
            mock_setup.return_value = None
            mock_result = Mock()
            mock_result.pulled_artifacts = Mock()
            mock_result.completed = 0
            mock_result.failed = 0
            mock_download.return_value = mock_result
            result = runner.invoke(cli, ["pull", "--artifact-location", artifact_path, "--content-types", "rpm"])
            assert result.exit_code == 0
            call_args = mock_download.call_args
            assert len(call_args.args) >= 6
            assert call_args.args[4] == ["rpm"]
            assert call_args.args[5] is None
        finally:
            os.unlink(artifact_path)

    @patch("pulp_tool.cli.pull.load_and_validate_artifacts")
    @patch("pulp_tool.cli.pull.setup_repositories_if_needed")
    @patch("pulp_tool.cli.pull.download_artifacts_concurrently")
    @patch("pulp_tool.cli.pull.generate_pull_report")
    def test_transfer_with_arch_filter(self, mock_report, mock_download, mock_setup, mock_load) -> None:
        """Test transfer with --archs filter."""
        runner = CliRunner()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as artifact_file:
            artifact_file.write('{"artifacts": [], "distributions": {}}')
            artifact_path = artifact_file.name
        try:
            from pulp_tool.models.artifacts import ArtifactData, ArtifactJsonResponse, ArtifactMetadata

            mock_artifact_data = ArtifactData(
                artifact_json=ArtifactJsonResponse(
                    artifacts={"test.rpm": ArtifactMetadata(labels={"build_id": "test"})}, distributions={}
                ),
                artifacts={"test.rpm": ArtifactMetadata(labels={"build_id": "test"})},
            )
            mock_load.return_value = mock_artifact_data
            mock_setup.return_value = None
            mock_result = Mock()
            mock_result.pulled_artifacts = Mock()
            mock_result.completed = 0
            mock_result.failed = 0
            mock_download.return_value = mock_result
            result = runner.invoke(cli, ["pull", "--artifact-location", artifact_path, "--archs", "x86_64"])
            assert result.exit_code == 0
            call_args = mock_download.call_args
            assert len(call_args.args) >= 6
            assert call_args.args[4] is None
            assert call_args.args[5] == ["x86_64"]
        finally:
            os.unlink(artifact_path)

    def test_pull_side_tag_without_transfer_dest(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["pull", "--side-tag", "mytest", "--artifact-results", "/u,/d"])
        assert result.exit_code == 1
        assert "--side-tag requires --transfer-dest" in result.output

    def test_pull_side_tag_without_oci_storage(self) -> None:
        runner = CliRunner()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as cfg:
            cfg.write("[cli]\nbase_url = 'https://pulp.example'\n")
            cfg_path = cfg.name
        try:
            result = runner.invoke(
                cli,
                ["pull", "--transfer-dest", cfg_path, "--side-tag", "mytest"],
            )
            assert result.exit_code == 1
            assert "oci_storage" in result.output
        finally:
            os.unlink(cfg_path)

    @patch("pulp_tool.cli.pull.ConfigManager")
    def test_pull_side_tag_config_load_exception(self, mock_config_manager) -> None:
        runner = CliRunner()
        mock_config_manager.side_effect = OSError("cannot read config")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as cfg:
            cfg.write("[cli]\n")
            cfg_path = cfg.name
        try:
            result = runner.invoke(
                cli,
                [
                    "pull",
                    "--transfer-dest",
                    cfg_path,
                    "--side-tag",
                    "mytest",
                    "--artifact-results",
                    "/tmp/url,/tmp/digest",
                ],
            )
            assert result.exit_code == 1
            assert "oci_storage" in result.output
        finally:
            os.unlink(cfg_path)

    def test_pull_side_tag_without_oci_storage_in_config(self) -> None:
        runner = CliRunner()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as cfg:
            cfg.write("[cli]\nbase_url = 'https://pulp.example'\n")
            cfg_path = cfg.name
        try:
            result = runner.invoke(
                cli,
                [
                    "pull",
                    "--transfer-dest",
                    cfg_path,
                    "--side-tag",
                    "mytest",
                    "--artifact-results",
                    "/tmp/url,/tmp/digest",
                ],
            )
            assert result.exit_code == 1
            assert "oci_storage" in result.output
        finally:
            os.unlink(cfg_path)

    def test_pull_side_tag_oci_storage_flag_without_config_key(self) -> None:
        """Konflux passes ociStorage as --oci-storage; config need not define cli.oci_storage."""
        runner = CliRunner()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as cfg:
            cfg.write("[cli]\nbase_url = 'https://pulp.example'\n")
            cfg_path = cfg.name
        try:
            result = runner.invoke(
                cli,
                [
                    "--build-id",
                    "b1",
                    "--namespace",
                    "ns",
                    "--config",
                    cfg_path,
                    "pull",
                    "--transfer-dest",
                    cfg_path,
                    "--side-tag",
                    "mytest",
                    "--oci-storage",
                    "quay.io/ns/repo:latest",
                ],
            )
            assert "cli.oci_storage is required" not in result.output
            assert "--oci-storage or cli.oci_storage" not in result.output
        finally:
            os.unlink(cfg_path)
