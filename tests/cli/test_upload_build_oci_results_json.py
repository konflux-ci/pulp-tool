"""Coverage for upload-build OCI --results-json resolution."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from pulp_tool.cli import cli


def test_upload_build_results_json_oci_resolves(tmp_path: Path) -> None:
    config = tmp_path / "cli.toml"
    config.write_text(
        '[cli]\nbase_url = "https://pulp.example"\napi_root = "/pulp/api/v3"\ndomain = "d"\n',
        encoding="utf-8",
    )
    local = tmp_path / "pulp_results.json"
    local.write_text(
        '{"version":1,"build_id":"b1","namespace":"ns1","artifacts":{}}',
        encoding="utf-8",
    )
    with patch("pulp_tool.cli.upload_build.PulpClient.create_from_config_file") as mock_client:
        mock_client.return_value = MagicMock()
        with patch("pulp_tool.cli.upload_build.PulpHelper") as mock_helper:
            mock_helper.return_value.setup_repositories.return_value = MagicMock()
            mock_helper.return_value.process_uploads.return_value = "https://example/results"
            with patch(
                "pulp_tool.cli.upload_build.resolve_results_json_local_path",
                return_value=(str(local), None),
            ):
                runner = CliRunner()
                result = runner.invoke(
                    cli,
                    [
                        "--config",
                        str(config),
                        "upload-build",
                        "--results-json",
                        "quay.io/ns/r@sha256:abc",
                        "--rpm-path",
                        str(tmp_path),
                    ],
                )
    assert result.exit_code == 0, result.output


def test_upload_build_results_json_oci_error(tmp_path: Path) -> None:
    config = tmp_path / "cli.toml"
    config.write_text(
        '[cli]\nbase_url = "https://pulp.example"\napi_root = "/pulp/api/v3"\ndomain = "d"\n',
        encoding="utf-8",
    )
    from pulp_tool.cli.runner_helpers import PullRunnerError

    with patch(
        "pulp_tool.cli.upload_build.resolve_results_json_local_path",
        side_effect=PullRunnerError("bad ref"),
    ):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--config",
                str(config),
                "upload-build",
                "--results-json",
                "quay.io/ns/r@sha256:abc",
            ],
        )
    assert result.exit_code != 0
    assert "bad ref" in result.output


def test_upload_build_results_json_local_missing(tmp_path: Path) -> None:
    config = tmp_path / "cli.toml"
    config.write_text(
        '[cli]\nbase_url = "https://pulp.example"\napi_root = "/pulp/api/v3"\ndomain = "d"\n',
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--config",
            str(config),
            "upload-build",
            "--results-json",
            str(tmp_path / "missing.json"),
        ],
    )
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_upload_build_cleans_up_oci_temp_directory(tmp_path: Path) -> None:
    config = tmp_path / "cli.toml"
    config.write_text(
        '[cli]\nbase_url = "https://pulp.example"\napi_root = "/pulp/api/v3"\ndomain = "d"\n',
        encoding="utf-8",
    )
    local = tmp_path / "pulp_results.json"
    local.write_text('{"build_id":"b1","namespace":"ns1","artifacts":{}}', encoding="utf-8")
    mock_temp = MagicMock()
    with patch("pulp_tool.cli.upload_build.PulpClient.create_from_config_file") as mock_client:
        mock_client.return_value = MagicMock()
        with patch("pulp_tool.cli.upload_build.PulpHelper") as mock_helper:
            mock_helper.return_value.setup_repositories.return_value = MagicMock()
            mock_helper.return_value.process_uploads.return_value = "https://example/results"
            with patch(
                "pulp_tool.cli.upload_build.resolve_results_json_local_path",
                return_value=(str(local), mock_temp),
            ):
                runner = CliRunner()
                result = runner.invoke(
                    cli,
                    [
                        "--config",
                        str(config),
                        "upload-build",
                        "--results-json",
                        "quay.io/ns/r@sha256:abc",
                        "--rpm-path",
                        str(tmp_path),
                    ],
                )
    assert result.exit_code == 0, result.output
    mock_temp.cleanup.assert_called_once()
