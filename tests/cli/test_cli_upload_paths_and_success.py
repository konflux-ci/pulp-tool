"""Tests for upload CLI (paths, success, artifacts)."""

import base64
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from click.testing import CliRunner

from pulp_tool.cli import cli


class TestUploadCommandPathsAndSuccess:
    """Upload command: paths, success, artifacts, results JSON folder."""

    def test_upload_invalid_rpm_path(self) -> None:
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

    def test_upload_invalid_sbom_path(self) -> None:
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

    @patch("pulp_tool.cli.upload_build.PulpClient")
    @patch("pulp_tool.cli.upload_build.PulpHelper")
    def test_upload_success(self, mock_helper_class, mock_client_class) -> None:
        """Test successful upload flow."""
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
                    "--parent-package",
                    "test-pkg",
                    "--rpm-path",
                    str(rpm_dir),
                    "--sbom-path",
                    str(sbom_path),
                ],
            )
            assert result.exit_code == 0
            assert "RESULTS JSON:" in result.output

    @patch("pulp_tool.cli.upload_build.PulpClient")
    @patch("pulp_tool.cli.upload_build.PulpHelper")
    def test_upload_target_arch_repo_flag(self, mock_helper_class, mock_client_class) -> None:
        """--target-arch-repo is passed to setup_repositories and UploadRpmContext."""
        runner = CliRunner()
        mock_client = Mock()
        mock_client.close = Mock()
        mock_client_class.create_from_config_file.return_value = mock_client
        mock_helper = Mock()
        from pulp_tool.models.repository import RepositoryRefs

        mock_repos = RepositoryRefs(
            rpms_href="",
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
                    "--parent-package",
                    "test-pkg",
                    "--rpm-path",
                    str(rpm_dir),
                    "--sbom-path",
                    str(sbom_path),
                    "--target-arch-repo",
                ],
            )
            assert result.exit_code == 0
            mock_helper.setup_repositories.assert_called_once_with(
                "test-build",
                signed_by=None,
                skip_artifacts_repo=False,
                target_arch_repo=True,
                skip_logs_repo=True,
                skip_sbom_repo=False,
            )
            context = mock_helper.process_uploads.call_args[0][1]
            assert context.target_arch_repo is True
            assert context.skip_logs_repo is True
            assert context.skip_sbom_repo is False

    @patch("pulp_tool.cli.upload_build.PulpClient")
    @patch("pulp_tool.cli.upload_build.PulpHelper")
    def test_upload_with_base64_config(self, mock_helper_class, mock_client_class) -> None:
        """Test upload command with base64-encoded config."""
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
        config_content = (
            '[cli]\nbase_url = "https://pulp.example.com"\napi_root = "/pulp/api/v3"\ndomain = "test-domain"'
        )
        base64_config = base64.b64encode(config_content.encode()).decode()
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
                    "--namespace",
                    "test-ns",
                    "--config",
                    base64_config,
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
            assert "RESULTS JSON:" in result.output
            assert mock_client_class.create_from_config_file.called
            call_args = mock_client_class.create_from_config_file.call_args
            assert call_args is not None
            if call_args.kwargs and "path" in call_args.kwargs:
                config_path = call_args.kwargs["path"]
            elif call_args.args and len(call_args.args) > 0:
                config_path = call_args.args[0]
            else:
                config_path = None
            assert config_path is not None
            assert config_path == base64_config

    @patch("pulp_tool.cli.upload_build.PulpClient")
    @patch("pulp_tool.cli.upload_build.PulpHelper")
    def test_upload_with_artifact_results(self, mock_helper_class, mock_client_class) -> None:
        """Test upload with artifact results output."""
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

    @patch("pulp_tool.cli.upload_build.PulpClient")
    @patch("pulp_tool.cli.upload_build.PulpHelper")
    def test_upload_with_artifact_results_folder(self, mock_helper_class, mock_client_class) -> None:
        """Test upload with --artifact-results as folder path (saves locally, skips Pulp upload)."""
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
            output_dir = Path(tmpdir) / "results"
            expected_path = str(output_dir / "pulp_results.json")
            mock_helper.process_uploads.return_value = expected_path
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
                    str(output_dir),
                ],
            )
            assert result.exit_code == 0
            assert "RESULTS JSON:" in result.output
            assert expected_path in result.output

    @patch("pulp_tool.cli.upload_build.resolve_oci_storage")
    @patch("pulp_tool.cli.upload_build.PulpClient")
    @patch("pulp_tool.cli.upload_build.PulpHelper")
    def test_upload_build_echoes_konflux_oci_results(
        self, mock_helper_class, mock_client_class, mock_resolve, tmp_path: Path
    ) -> None:
        mock_resolve.return_value = "quay.io/ns/repo:latest"
        mock_client = Mock()
        mock_client.close = Mock()
        mock_client_class.create_from_config_file.return_value = mock_client
        mock_helper = Mock()
        mock_helper.setup_repositories.return_value = Mock()
        mock_helper.process_uploads.return_value = "https://example.com/results.json"
        mock_helper_class.return_value = mock_helper
        url_path = tmp_path / "image_url"
        digest_path = tmp_path / "image_digest"
        url_path.write_text("quay.io/ns/repo:tag", encoding="utf-8")
        digest_path.write_text("sha256:abc", encoding="utf-8")
        rpm = tmp_path / "pkg.rpm"
        rpm.write_bytes(b"rpm")
        config = tmp_path / "cli.toml"
        config.write_text("[cli]\nbase_url = 'https://pulp.example.com'\n", encoding="utf-8")
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
                "upload-build",
                "--rpm-path",
                str(tmp_path),
                "--oci-storage",
                "quay.io/ns/repo:latest",
                "--artifact-results",
                f"{url_path},{digest_path}",
            ],
        )
        assert result.exit_code == 0
        assert "KONFLUX OCI IMAGE URL: quay.io/ns/repo:tag" in result.output
        assert "KONFLUX OCI IMAGE DIGEST: sha256:abc" in result.output

    @patch("pulp_tool.cli.upload_build.resolve_oci_storage")
    @patch("pulp_tool.cli.upload_build.PulpClient")
    @patch("pulp_tool.cli.upload_build.PulpHelper")
    def test_upload_build_oras_note_without_artifact_results(
        self, mock_helper_class, mock_client_class, mock_resolve, tmp_path: Path
    ) -> None:
        mock_resolve.return_value = "quay.io/ns/repo:latest"
        mock_client = Mock()
        mock_client.close = Mock()
        mock_client_class.create_from_config_file.return_value = mock_client
        mock_helper = Mock()
        mock_helper.setup_repositories.return_value = Mock()
        mock_helper.process_uploads.return_value = "https://example.com/results.json"
        mock_helper_class.return_value = mock_helper
        rpm = tmp_path / "pkg.rpm"
        rpm.write_bytes(b"rpm")
        config = tmp_path / "cli.toml"
        config.write_text("[cli]\nbase_url = 'https://pulp.example.com'\n", encoding="utf-8")
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
                "upload-build",
                "--rpm-path",
                str(tmp_path),
                "--oci-storage",
                "quay.io/ns/repo:latest",
            ],
        )
        assert result.exit_code == 0
        assert "PULP-IMAGE_URL / PULP-IMAGE_DIGEST" in result.output

    @patch("pulp_tool.cli.upload_build.resolve_oci_storage")
    @patch("pulp_tool.cli.upload_build.PulpClient")
    @patch("pulp_tool.cli.upload_build.PulpHelper")
    def test_upload_build_skips_konflux_echo_when_result_files_missing(
        self, mock_helper_class, mock_client_class, mock_resolve, tmp_path: Path
    ) -> None:
        mock_resolve.return_value = "quay.io/ns/repo:latest"
        mock_client = Mock()
        mock_client.close = Mock()
        mock_client_class.create_from_config_file.return_value = mock_client
        mock_helper = Mock()
        mock_helper.setup_repositories.return_value = Mock()
        mock_helper.process_uploads.return_value = "https://example.com/results.json"
        mock_helper_class.return_value = mock_helper
        rpm = tmp_path / "pkg.rpm"
        rpm.write_bytes(b"rpm")
        config = tmp_path / "cli.toml"
        config.write_text("[cli]\nbase_url = 'https://pulp.example.com'\n", encoding="utf-8")
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
                "upload-build",
                "--rpm-path",
                str(tmp_path),
                "--oci-storage",
                "quay.io/ns/repo:latest",
                "--artifact-results",
                f"{tmp_path / 'missing-url'},{tmp_path / 'missing-digest'}",
            ],
        )
        assert result.exit_code == 0
        assert "KONFLUX OCI IMAGE URL" not in result.output
