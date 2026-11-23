"""Tests for Click CLI commands."""

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from pulp_tool.cli import cli, main


class TestCLIEntryPoint:
    """Test CLI entry point and main function."""

    def test_main_function_success(self) -> None:
        """Test main() entry point calls cli successfully."""
        with patch("pulp_tool.cli.cli") as mock_cli:
            mock_cli.return_value = None
            main()
            mock_cli.assert_called_once()

    def test_main_function_keyboard_interrupt(self) -> None:
        """Test main() handles KeyboardInterrupt gracefully."""
        with patch("pulp_tool.cli.cli") as mock_cli, patch("pulp_tool.cli.sys.exit") as mock_exit:
            mock_cli.side_effect = KeyboardInterrupt()
            main()
            mock_exit.assert_called_once_with(130)


class TestCLIHelp:
    """Test CLI help commands."""

    @pytest.mark.parametrize("argv,expect_short_hint", [(["--help"], False), (["-h"], True)])
    def test_main_help(self, argv, expect_short_hint) -> None:
        """Main CLI help via ``--help`` or ``-h``."""
        runner = CliRunner()
        result = runner.invoke(cli, argv)
        assert result.exit_code == 0
        assert "Pulp Tool" in result.output
        assert "upload" in result.output
        assert "pull" in result.output
        assert "transfer" in result.output
        assert "search-by" in result.output
        assert "create-repository" in result.output
        assert "--config" in result.output
        assert "--build-id" in result.output
        assert "--namespace" in result.output
        assert "--debug" in result.output
        assert "--max-workers" in result.output
        if expect_short_hint:
            assert "-h, --help" in result.output

    def test_upload_help(self) -> None:
        """Test upload command help output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["upload", "--help"])
        assert result.exit_code == 0
        assert "Upload RPMs, logs, and SBOM files" in result.output
        assert "--parent-package" in result.output
        assert "--rpm-path" in result.output
        assert "--sbom-results" in result.output
        assert "--artifact-results" in result.output
        assert "--overwrite" in result.output
        assert "--target-arch-repo" in result.output

    def test_upload_files_help(self) -> None:
        """Test upload-files command help output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["upload-files", "--help"])
        assert result.exit_code == 0
        assert "Upload individual files" in result.output
        assert "--parent-package" in result.output
        assert "--rpm" in result.output
        assert "--file" in result.output
        assert "--log" in result.output
        assert "--sbom" in result.output
        assert "--arch" in result.output
        assert "--artifact-results" in result.output
        assert "--sbom-results" in result.output

    def test_pull_help(self) -> None:
        """Test pull command help output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["pull", "--help"])
        assert result.exit_code == 0
        assert "Download artifacts" in result.output
        assert "--artifact-location" in result.output
        assert "--content-types" in result.output
        assert "--archs" in result.output
        assert "--transfer-dest" not in result.output

    def test_transfer_help(self) -> None:
        """Test transfer command help output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["transfer", "--help"])
        assert result.exit_code == 0
        assert "promote them to release Pulp" in result.output
        assert "--side-tag" in result.output
        assert "--source-config" in result.output
        assert "--oras-cp-target" in result.output
        assert "--pulp-oras-cp-target" in result.output
        assert "--snapshot-path" in result.output

    def test_create_repository_help(self) -> None:
        """Test create-repository command help output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["create-repository", "--help"])
        assert result.exit_code == 0
        assert "Create a custom defined repository."
        assert "--repository-name" in result.output
        assert "--packages" in result.output
        assert "--compression-type" in result.output
        assert "--checksum-type" in result.output
        assert "--skip-publish" in result.output
        assert "--base-path" in result.output
        assert "--generate-repo-config" in result.output
        assert "-j" in result.output
        assert "--json-data" in result.output


class TestCLIValidation:
    """Test CLI input validation."""

    def test_upload_missing_required_args(self) -> None:
        """Test upload command with missing required arguments."""
        runner = CliRunner()
        result = runner.invoke(cli, ["upload"])
        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()

    def test_pull_missing_required_args(self) -> None:
        """Test pull command with missing required arguments."""
        runner = CliRunner()
        result = runner.invoke(cli, ["pull"], catch_exceptions=False, standalone_mode=False)
        assert result.exit_code != 0

    def test_create_repository_missing_required_args(self) -> None:
        """Test create-repository command with missing required arguments."""
        runner = CliRunner()
        result = runner.invoke(cli, ["create-repository"])
        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()

    def test_create_repository_missing_json_fields(self) -> None:
        """Test create-repository command with missing json fields."""
        runner = CliRunner()
        result = runner.invoke(cli, ["create-repository", "--json-data", "{}"])
        assert result.exit_code != 0
        assert "Field required" in result.output

    def test_create_repository_bad_json_arg(self) -> None:
        """Test create-repository command with impropper json"""
        runner = CliRunner()
        result = runner.invoke(cli, ["create-repository", "--json-data", "{"])
        assert result.exit_code != 0
        assert "Invalid JSON" in result.output


class TestCLIVersion:
    """Test CLI version output."""

    def test_version(self) -> None:
        """Test version flag."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
