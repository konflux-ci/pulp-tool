"""Tests for pull CLI (remaining transfer and errors)."""

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from click.testing import CliRunner

from pulp_tool.cli import cli


class TestPullCommandTransferAndErrors:
    """Pull command: filters off, build-id, failures, cleanup."""

    @patch("pulp_tool.cli.pull.load_and_validate_artifacts")
    @patch("pulp_tool.cli.pull.setup_repositories_if_needed")
    @patch("pulp_tool.cli.pull.download_artifacts_concurrently")
    @patch("pulp_tool.cli.pull.generate_pull_report")
    def test_transfer_with_multiple_filters(self, mock_report, mock_download, mock_setup, mock_load) -> None:
        """Test transfer with combined --content-types and --archs filters."""
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
            result = runner.invoke(
                cli,
                [
                    "pull",
                    "--artifact-location",
                    artifact_path,
                    "--content-types",
                    "rpm,log",
                    "--archs",
                    "x86_64,noarch",
                ],
            )
            assert result.exit_code == 0
            call_args = mock_download.call_args
            assert len(call_args.args) >= 6
            assert call_args.args[4] == ["rpm", "log"]
            assert call_args.args[5] == ["x86_64", "noarch"]
        finally:
            os.unlink(artifact_path)

    @patch("pulp_tool.cli.pull.load_and_validate_artifacts")
    @patch("pulp_tool.cli.pull.setup_repositories_if_needed")
    @patch("pulp_tool.cli.pull.download_artifacts_concurrently")
    @patch("pulp_tool.cli.pull.generate_pull_report")
    def test_transfer_without_filters(self, mock_report, mock_download, mock_setup, mock_load) -> None:
        """Test transfer without filters transfers all artifacts."""
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
            result = runner.invoke(cli, ["pull", "--artifact-location", artifact_path])
            assert result.exit_code == 0
            call_args = mock_download.call_args
            assert len(call_args.args) >= 6
            assert call_args.args[4] is None
            assert call_args.args[5] is None
        finally:
            os.unlink(artifact_path)

    def test_transfer_invalid_content_type(self) -> None:
        """Test transfer with invalid content type raises validation error."""
        runner = CliRunner()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as artifact_file:
            artifact_file.write('{"artifacts": [], "distributions": {}}')
            artifact_path = artifact_file.name
        try:
            result = runner.invoke(cli, ["pull", "--artifact-location", artifact_path, "--content-types", "invalid"])
            assert result.exit_code == 1
            output = str(result.output) + str(result.exception) if result.exception else str(result.output)
            assert "Invalid content type" in output or "validation error" in output.lower()
        finally:
            os.unlink(artifact_path)

    @patch("pulp_tool.cli.pull.DistributionClient")
    @patch("pulp_tool.cli.pull.load_and_validate_artifacts")
    @patch("pulp_tool.cli.pull.setup_repositories_if_needed")
    @patch("pulp_tool.cli.pull.download_artifacts_concurrently")
    @patch("pulp_tool.cli.pull.generate_pull_report")
    @patch("pulp_tool.cli.pull.upload_downloaded_files_to_pulp")
    def test_transfer_with_build_id_namespace(
        self, mock_upload, mock_report, mock_download, mock_setup, mock_load, mock_dist_client
    ) -> None:
        """Test transfer with build_id and namespace generates artifact_location."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = Path(tmpdir) / "cert.pem"
            cert_path.write_text("cert")
            key_path = Path(tmpdir) / "key.pem"
            key_path.write_text("key")
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                f'[cli]\nbase_url = "https://pulp.example.com"\ncert = "{cert_path}"\nkey = "{key_path}"'
            )
            mock_dist_client_instance = Mock()
            mock_dist_client_instance.session = Mock()
            mock_dist_client_instance.session.close = Mock()
            mock_dist_client.return_value = mock_dist_client_instance
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
            result = runner.invoke(
                cli,
                [
                    "--config",
                    str(config_path),
                    "--build-id",
                    "test-build",
                    "--namespace",
                    "test-ns",
                    "pull",
                    "--transfer-dest",
                    str(config_path),
                ],
            )
            assert result.exit_code == 0
            mock_load.assert_called_once()
            pull_ctx = mock_load.call_args.args[0]
            assert "pulp.example.com" in pull_ctx.artifact_location

    @patch("pulp_tool.cli.pull.DistributionClient")
    @patch("pulp_tool.cli.pull.load_and_validate_artifacts")
    @patch("pulp_tool.cli.pull.setup_repositories_if_needed")
    @patch("pulp_tool.cli.pull.download_artifacts_concurrently")
    @patch("pulp_tool.cli.pull.generate_pull_report")
    @patch("pulp_tool.cli.pull.upload_downloaded_files_to_pulp")
    def test_auto_artifact_location_uses_source_config_not_transfer_dest(
        self, mock_upload, mock_report, mock_download, mock_setup, mock_load, mock_dist_client
    ) -> None:
        """``--build-id`` auto URL must use group ``--config`` base_url, not ``--transfer-dest``."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = Path(tmpdir) / "cert.pem"
            cert_path.write_text("cert")
            key_path = Path(tmpdir) / "key.pem"
            key_path.write_text("key")
            source_cfg = Path(tmpdir) / "source.toml"
            source_cfg.write_text(
                f'[cli]\nbase_url = "https://source.pulp.example"\ncert = "{cert_path}"\nkey = "{key_path}"'
            )
            dest_cfg = Path(tmpdir) / "dest.toml"
            dest_cfg.write_text(
                f'[cli]\nbase_url = "https://dest.pulp.example"\ncert = "{cert_path}"\nkey = "{key_path}"'
            )
            mock_dist_client_instance = Mock()
            mock_dist_client_instance.session = Mock()
            mock_dist_client_instance.session.close = Mock()
            mock_dist_client.return_value = mock_dist_client_instance
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
            result = runner.invoke(
                cli,
                [
                    "--config",
                    str(source_cfg),
                    "--build-id",
                    "test-build",
                    "--namespace",
                    "test-ns",
                    "pull",
                    "--transfer-dest",
                    str(dest_cfg),
                ],
            )
            assert result.exit_code == 0
            pull_ctx = mock_load.call_args.args[0]
            assert pull_ctx.artifact_location.startswith("https://source.pulp.example/")
            assert "dest.pulp.example" not in pull_ctx.artifact_location

    @patch("pulp_tool.cli.pull.publish_side_tag_results")
    @patch("pulp_tool.cli.pull.upload_rpms_to_side_tag_repository")
    @patch("pulp_tool.cli.pull.DistributionClient")
    @patch("pulp_tool.cli.pull.load_and_validate_artifacts")
    @patch("pulp_tool.cli.pull.setup_repositories_if_needed")
    @patch("pulp_tool.cli.pull.download_artifacts_concurrently")
    @patch("pulp_tool.cli.pull.generate_pull_report")
    @patch("pulp_tool.cli.pull.upload_downloaded_files_to_pulp")
    def test_pull_side_tag_transfer_invokes_publish(
        self,
        mock_upload,
        mock_report,
        mock_download,
        mock_setup,
        mock_load,
        mock_dist_client,
        mock_side_upload,
        mock_publish,
    ) -> None:
        """Side-tag transfer runs upload and publish after mainline upload."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = Path(tmpdir) / "cert.pem"
            cert_path.write_text("cert")
            key_path = Path(tmpdir) / "key.pem"
            key_path.write_text("key")
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                f'[cli]\nbase_url = "https://pulp.example.com"\n'
                f'oci_storage = "quay.io/ns/repo:latest"\n'
                f'cluster = "c1"\n'
                f'cert = "{cert_path}"\nkey = "{key_path}"'
            )
            mock_dist_client_instance = Mock()
            mock_dist_client_instance.session = Mock()
            mock_dist_client_instance.session.close = Mock()
            mock_dist_client.return_value = mock_dist_client_instance
            from pulp_tool.models.artifacts import ArtifactData, ArtifactJsonResponse, ArtifactMetadata, PulledArtifacts

            rpm_meta = ArtifactMetadata(
                labels={"build_id": "test"},
                url="https://pulp.example.com/test.rpm",
            )
            mock_artifact_data = ArtifactData(
                artifact_json=ArtifactJsonResponse(artifacts={"test.rpm": rpm_meta}, distributions={}),
                artifacts={"test.rpm": rpm_meta},
            )
            mock_load.return_value = mock_artifact_data
            from pulp_tool.models.repository import RepositoryRefs
            from pulp_tool.pull.download import PullDestinationSetup

            repos = RepositoryRefs(
                rpms_prn="r",
                logs_prn="l",
                sbom_prn="s",
                artifacts_prn="a",
                rpms_href="/rpms/",
                logs_href="/logs/",
                sbom_href="/sbom/",
                artifacts_href="/artifacts/",
            )
            mock_setup.return_value = PullDestinationSetup(client=Mock(), repositories=repos)
            mock_result = Mock()
            mock_result.pulled_artifacts = PulledArtifacts()
            mock_result.completed = 0
            mock_result.failed = 0
            mock_download.return_value = mock_result
            from pulp_tool.models.results import PulpResultsModel

            mock_upload.return_value = PulpResultsModel(build_id="test", repositories=repos)
            from pulp_tool.pull.side_tag import SideTagUploadResult

            mock_side_upload.return_value = SideTagUploadResult([], "https://rok/side/")
            result = runner.invoke(
                cli,
                [
                    "--build-id",
                    "test-build",
                    "--namespace",
                    "test-ns",
                    "pull",
                    "--transfer-dest",
                    str(config_path),
                    "--side-tag",
                    "mytest",
                    "--oci-storage",
                    "quay.io/ns/repo:latest",
                ],
            )
            assert result.exit_code == 0
            mock_side_upload.assert_called_once()
            mock_publish.assert_called_once()

    @patch("pulp_tool.cli.pull.DistributionClient")
    @patch("pulp_tool.cli.pull.load_and_validate_artifacts")
    @patch("pulp_tool.cli.pull.setup_repositories_if_needed")
    @patch("pulp_tool.cli.pull.download_artifacts_concurrently")
    @patch("pulp_tool.cli.pull.generate_pull_report")
    @patch("pulp_tool.cli.pull.upload_downloaded_files_to_pulp")
    def test_pull_with_build_id_namespace_using_config(
        self, mock_upload, mock_report, mock_download, mock_setup, mock_load, mock_dist_client
    ) -> None:
        """Test pull with build_id and namespace using group-level --config instead of --transfer-dest."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = Path(tmpdir) / "cert.pem"
            cert_path.write_text("cert")
            key_path = Path(tmpdir) / "key.pem"
            key_path.write_text("key")
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                f'[cli]\nbase_url = "https://pulp.example.com"\ncert = "{cert_path}"\nkey = "{key_path}"'
            )
            mock_dist_client_instance = Mock()
            mock_dist_client_instance.session = Mock()
            mock_dist_client_instance.session.close = Mock()
            mock_dist_client.return_value = mock_dist_client_instance
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
            result = runner.invoke(
                cli, ["--config", str(config_path), "--build-id", "test-build", "--namespace", "test-ns", "pull"]
            )
            assert result.exit_code == 0
            mock_load.assert_called_once()
            mock_upload.assert_not_called()

    @patch("pulp_tool.cli.pull.load_and_validate_artifacts")
    @patch("pulp_tool.cli.pull.setup_repositories_if_needed")
    @patch("pulp_tool.cli.pull.download_artifacts_concurrently")
    @patch("pulp_tool.cli.pull.generate_pull_report")
    @patch("pulp_tool.cli.pull.upload_downloaded_files_to_pulp")
    def test_transfer_with_upload(self, mock_upload, mock_report, mock_download, mock_setup, mock_load) -> None:
        """Test transfer with pulp_client triggers upload."""
        runner = CliRunner()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as artifact_file:
            artifact_file.write('{"artifacts": [], "distributions": {}}')
            artifact_path = artifact_file.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as dest_cfg:
            dest_cfg.write('[cli]\nbase_url = "https://pulp.example.com"\n')
            transfer_config_path = dest_cfg.name
        try:
            from pulp_tool.models.artifacts import ArtifactData, ArtifactJsonResponse, ArtifactMetadata
            from pulp_tool.models.results import PulpResultsModel

            mock_artifact_data = ArtifactData(
                artifact_json=ArtifactJsonResponse(
                    artifacts={"test.rpm": ArtifactMetadata(labels={"build_id": "test"})}, distributions={}
                ),
                artifacts={"test.rpm": ArtifactMetadata(labels={"build_id": "test"})},
            )
            mock_load.return_value = mock_artifact_data
            mock_client = Mock()
            mock_client.close = Mock()
            from pulp_tool.models.repository import RepositoryRefs
            from pulp_tool.models.statistics import UploadCounts
            from pulp_tool.pull.download import PullDestinationSetup

            transfer_repos = RepositoryRefs(
                rpms_href="",
                rpms_prn="",
                logs_href="",
                logs_prn="",
                sbom_href="",
                sbom_prn="",
                artifacts_href="",
                artifacts_prn="",
            )
            mock_setup.return_value = PullDestinationSetup(client=mock_client, repositories=transfer_repos)
            mock_result = Mock()
            mock_result.pulled_artifacts = Mock()
            mock_result.completed = 1
            mock_result.failed = 0
            mock_download.return_value = mock_result

            mock_upload_info = PulpResultsModel(
                build_id="test-build",
                repositories=transfer_repos,
                artifacts={},
                distributions={},
                uploaded_counts=UploadCounts(),
            )
            mock_upload_info.upload_errors = []
            mock_upload.return_value = mock_upload_info
            result = runner.invoke(
                cli, ["pull", "--artifact-location", artifact_path, "--transfer-dest", transfer_config_path]
            )
            assert result.exit_code == 0
            mock_upload.assert_called_once()
        finally:
            os.unlink(transfer_config_path)
            os.unlink(artifact_path)

    @patch("pulp_tool.cli.pull.load_and_validate_artifacts")
    @patch("pulp_tool.cli.pull.setup_repositories_if_needed")
    @patch("pulp_tool.cli.pull.download_artifacts_concurrently")
    @patch("pulp_tool.cli.pull.generate_pull_report")
    @patch("pulp_tool.cli.pull.upload_downloaded_files_to_pulp")
    def test_transfer_with_download_failures(
        self, mock_upload, mock_report, mock_download, mock_setup, mock_load
    ) -> None:
        """Test transfer with download failures exits with error."""
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
            mock_result.completed = 1
            mock_result.failed = 1
            mock_download.return_value = mock_result
            result = runner.invoke(cli, ["pull", "--artifact-location", artifact_path])
            assert result.exit_code == 1
        finally:
            os.unlink(artifact_path)

    @patch("pulp_tool.cli.pull.load_and_validate_artifacts")
    @patch("pulp_tool.cli.pull.setup_repositories_if_needed")
    @patch("pulp_tool.cli.pull.download_artifacts_concurrently")
    @patch("pulp_tool.cli.pull.generate_pull_report")
    @patch("pulp_tool.cli.pull.upload_downloaded_files_to_pulp")
    def test_transfer_with_upload_errors(self, mock_upload, mock_report, mock_download, mock_setup, mock_load) -> None:
        """Test transfer with upload errors exits with error."""
        runner = CliRunner()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as artifact_file:
            artifact_file.write('{"artifacts": [], "distributions": {}}')
            artifact_path = artifact_file.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as dest_cfg:
            dest_cfg.write('[cli]\nbase_url = "https://pulp.example.com"\n')
            transfer_config_path = dest_cfg.name
        try:
            from pulp_tool.models.artifacts import ArtifactData, ArtifactJsonResponse, ArtifactMetadata
            from pulp_tool.models.results import PulpResultsModel

            mock_artifact_data = ArtifactData(
                artifact_json=ArtifactJsonResponse(
                    artifacts={"test.rpm": ArtifactMetadata(labels={"build_id": "test"})}, distributions={}
                ),
                artifacts={"test.rpm": ArtifactMetadata(labels={"build_id": "test"})},
            )
            mock_load.return_value = mock_artifact_data
            mock_client = Mock()
            mock_client.close = Mock()
            from pulp_tool.models.repository import RepositoryRefs
            from pulp_tool.models.statistics import UploadCounts
            from pulp_tool.pull.download import PullDestinationSetup

            transfer_repos = RepositoryRefs(
                rpms_href="",
                rpms_prn="",
                logs_href="",
                logs_prn="",
                sbom_href="",
                sbom_prn="",
                artifacts_href="",
                artifacts_prn="",
            )
            mock_setup.return_value = PullDestinationSetup(client=mock_client, repositories=transfer_repos)
            mock_result = Mock()
            mock_result.pulled_artifacts = Mock()
            mock_result.completed = 1
            mock_result.failed = 0
            mock_download.return_value = mock_result

            mock_upload_info = PulpResultsModel(
                build_id="test-build",
                repositories=transfer_repos,
                artifacts={},
                distributions={},
                uploaded_counts=UploadCounts(),
            )
            mock_upload_info.upload_errors = ["Error 1", "Error 2"]
            mock_upload.return_value = mock_upload_info
            result = runner.invoke(
                cli, ["pull", "--artifact-location", artifact_path, "--transfer-dest", transfer_config_path]
            )
            assert result.exit_code == 1
        finally:
            os.unlink(transfer_config_path)
            os.unlink(artifact_path)

    @patch("pulp_tool.cli.pull.load_and_validate_artifacts")
    def test_transfer_generic_exception(self, mock_load) -> None:
        """Test transfer with generic exception."""
        runner = CliRunner()
        mock_load.side_effect = ValueError("Unexpected error")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as artifact_file:
            artifact_file.write('{"artifacts": [], "distributions": {}}')
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
    def test_transfer_finally_block_cleanup(self, mock_report, mock_download, mock_setup, mock_load) -> None:
        """Test transfer finally block cleans up clients."""
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
            from pulp_tool.models.artifacts import PulledArtifacts

            mock_result = Mock()
            mock_result.pulled_artifacts = PulledArtifacts()
            mock_result.completed = 0
            mock_result.failed = 0
            mock_download.return_value = mock_result
            result = runner.invoke(cli, ["pull", "--artifact-location", artifact_path])
            assert result.exit_code == 0
        finally:
            os.unlink(artifact_path)
