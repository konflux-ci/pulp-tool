"""Tests for search-by --results-json (output and CLI errors)."""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from click.testing import CliRunner

from pulp_tool.cli import cli
from tests.support.constants import VALID_CHECKSUM_1
from tests.support.factories import make_rpm_list_response as _make_rpm_response
from tests.support.temp_config import tempfile_config


class TestSearchByResultsJsonOutputAndCliErrors:
    """search-by --results-json output files and read errors."""

    @patch("pulp_tool.services.search_by_service.PulpClient")
    @patch("pulp_tool.cli.runner_helpers.resolve_results_json_path")
    def test_results_json_oci_reference_cleans_temp_dir(
        self,
        mock_resolve,
        mock_client_class,
        tmp_path,
    ) -> None:
        """OCI ``--results-json`` uses a temp ORAS dir; finally block cleans it up."""
        results_output = tmp_path / "output.json"

        def write_pulled_json(_ref: str, dest_dir: Path) -> Path:
            path = dest_dir / "pulp_results.json"
            path.write_text(json.dumps({"artifacts": {}}), encoding="utf-8")
            return path

        mock_resolve.side_effect = write_pulled_json
        mock_client = Mock()
        mock_client.get_rpm_by_pkgIDs.return_value = _make_rpm_response([])
        mock_client.get_rpm_by_filenames.return_value = _make_rpm_response([])
        mock_client_class.create_from_config_file.return_value = mock_client
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(
                cli,
                [
                    "--config",
                    config_path,
                    "search-by",
                    "--results-json",
                    "quay.io/ns/repo@sha256:deadbeef",
                    "--output-results",
                    str(results_output),
                ],
            )
        assert result.exit_code == 0
        assert json.loads(results_output.read_text()) == {"artifacts": {}}

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_output_results_keep_files_preserves_logs_and_sboms(self, mock_client_class, tmp_path) -> None:
        """Test --keep-files: output-results preserves logs and sboms."""
        results_input = tmp_path / "input.json"
        results_output = tmp_path / "output.json"
        results_input.write_text(
            json.dumps(
                {
                    "artifacts": {
                        "pkg1.rpm": {
                            "pulp_labels": {"arch": "x86_64"},
                            "url": "https://example.com/pkg1.rpm",
                            "sha256": VALID_CHECKSUM_1,
                        },
                        "log.txt": {"pulp_labels": {}, "url": "https://example.com/log.txt", "sha256": "f" * 64},
                        "sbom.json": {"pulp_labels": {}, "url": "https://example.com/sbom.json", "sha256": "e" * 64},
                    },
                    "distributions": {"rpms": "https://example.com/rpms/"},
                },
                indent=2,
            )
        )
        mock_response = _make_rpm_response([])
        mock_client = Mock()
        mock_client.get_rpm_by_pkgIDs.return_value = mock_response
        mock_client.get_rpm_by_filenames.return_value = _make_rpm_response([])
        mock_client_class.create_from_config_file.return_value = mock_client
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(
                cli,
                [
                    "--config",
                    config_path,
                    "search-by",
                    "--checksum",
                    "--results-json",
                    str(results_input),
                    "--output-results",
                    str(results_output),
                    "--keep-files",
                ],
            )
        assert result.exit_code == 0
        out = json.loads(results_output.read_text())
        assert "pkg1.rpm" in out["artifacts"]
        assert "log.txt" in out["artifacts"]
        assert "sbom.json" in out["artifacts"]

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_results_json_no_matches_in_pulp(self, mock_client_class, tmp_path) -> None:
        """Test results.json when no RPMs are found in Pulp - all remain."""
        results_input = tmp_path / "input.json"
        results_output = tmp_path / "output.json"
        results_input.write_text(
            json.dumps(
                {
                    "artifacts": {
                        "pkg.rpm": {
                            "pulp_labels": {"arch": "x86_64"},
                            "url": "https://example.com/pkg.rpm",
                            "sha256": VALID_CHECKSUM_1,
                        }
                    },
                    "distributions": {},
                },
                indent=2,
            )
        )
        mock_response = _make_rpm_response([])
        mock_client = Mock()
        mock_client.get_rpm_by_pkgIDs.return_value = mock_response
        mock_client.get_rpm_by_filenames.return_value = _make_rpm_response([])
        mock_client_class.create_from_config_file.return_value = mock_client
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(
                cli,
                [
                    "--config",
                    config_path,
                    "search-by",
                    "--results-json",
                    str(results_input),
                    "--output-results",
                    str(results_output),
                ],
            )
        assert result.exit_code == 0
        assert "removed 0 found RPM" in result.output
        out = json.loads(results_output.read_text())
        assert "pkg.rpm" in out["artifacts"]

    def test_results_json_invalid_file(self, tmp_path) -> None:
        """Test error when results.json has invalid JSON (JSONDecodeError)."""
        results_input = tmp_path / "input.json"
        results_output = tmp_path / "output.json"
        results_input.write_text("not valid json {")
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(
                cli,
                [
                    "--config",
                    config_path,
                    "search-by",
                    "--results-json",
                    str(results_input),
                    "--output-results",
                    str(results_output),
                ],
            )
        assert result.exit_code == 1
        assert "Failed to read results.json" in result.output

    def test_results_json_path_is_directory(self, tmp_path) -> None:
        """Test error when results.json path is a directory (OSError on read)."""
        results_input = tmp_path / "input"
        results_input.mkdir()
        results_output = tmp_path / "output.json"
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(
                cli,
                [
                    "--config",
                    config_path,
                    "search-by",
                    "--results-json",
                    str(results_input),
                    "--output-results",
                    str(results_output),
                ],
            )
        assert result.exit_code == 1
        assert "Failed to read results.json" in result.output or "not found" in result.output.lower()

    def test_results_json_invalid_checksum_in_file(self, tmp_path) -> None:
        """Test error when results.json contains invalid RPM checksum (64 chars but non-hex)."""
        results_input = tmp_path / "input.json"
        results_output = tmp_path / "output.json"
        results_input.write_text(
            json.dumps(
                {
                    "artifacts": {
                        "pkg.rpm": {
                            "pulp_labels": {"arch": "x86_64"},
                            "url": "https://example.com/pkg.rpm",
                            "sha256": "g" * 64,
                        }
                    },
                    "distributions": {},
                },
                indent=2,
            )
        )
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(
                cli,
                [
                    "--config",
                    config_path,
                    "search-by",
                    "--results-json",
                    str(results_input),
                    "--output-results",
                    str(results_output),
                ],
            )
        assert result.exit_code == 1
        assert "Invalid checksum in results.json" in result.output

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_results_json_skips_non_dict_artifact_info(self, mock_client_class, tmp_path) -> None:
        """Test that non-dict artifact info is skipped when extracting checksums."""
        results_input = tmp_path / "input.json"
        results_output = tmp_path / "output.json"
        results_input.write_text(
            json.dumps(
                {
                    "artifacts": {
                        "pkg.rpm": "not_a_dict",
                        "valid.rpm": {
                            "pulp_labels": {"arch": "x86_64"},
                            "url": "https://example.com/valid.rpm",
                            "sha256": VALID_CHECKSUM_1,
                        },
                    },
                    "distributions": {},
                },
                indent=2,
            )
        )
        mock_response = _make_rpm_response([])
        mock_client = Mock()
        mock_client.get_rpm_by_pkgIDs.return_value = mock_response
        mock_client.get_rpm_by_filenames.return_value = _make_rpm_response([])
        mock_client_class.create_from_config_file.return_value = mock_client
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(
                cli,
                [
                    "--config",
                    config_path,
                    "search-by",
                    "--results-json",
                    str(results_input),
                    "--output-results",
                    str(results_output),
                ],
            )
        assert result.exit_code == 0
        out = json.loads(results_output.read_text())
        assert "pkg.rpm" in out["artifacts"]
        assert "valid.rpm" in out["artifacts"]

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_results_json_http_error(self, mock_client_class, tmp_path) -> None:
        """Test HTTP error when searching in results.json mode."""
        results_input = tmp_path / "input.json"
        results_output = tmp_path / "output.json"
        results_input.write_text(
            json.dumps(
                {
                    "artifacts": {
                        "pkg.rpm": {
                            "pulp_labels": {"arch": "x86_64"},
                            "url": "https://example.com/pkg.rpm",
                            "sha256": VALID_CHECKSUM_1,
                        }
                    },
                    "distributions": {},
                },
                indent=2,
            )
        )
        mock_client = Mock()
        mock_client.get_rpm_by_pkgIDs.side_effect = httpx.HTTPError("Connection failed")
        mock_client_class.create_from_config_file.return_value = mock_client
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(
                cli,
                [
                    "--config",
                    config_path,
                    "search-by",
                    "--results-json",
                    str(results_input),
                    "--output-results",
                    str(results_output),
                ],
            )
        assert result.exit_code == 1

    @patch("pulp_tool.services.search_by_service.PulpClient")
    def test_results_json_generic_exception(self, mock_client_class, tmp_path) -> None:
        """Test generic exception when searching in results.json mode."""
        results_input = tmp_path / "input.json"
        results_output = tmp_path / "output.json"
        results_input.write_text(
            json.dumps(
                {
                    "artifacts": {
                        "pkg.rpm": {
                            "pulp_labels": {"arch": "x86_64"},
                            "url": "https://example.com/pkg.rpm",
                            "sha256": VALID_CHECKSUM_1,
                        }
                    },
                    "distributions": {},
                },
                indent=2,
            )
        )
        mock_client_class.create_from_config_file.side_effect = ValueError("Config error")
        runner = CliRunner()
        with tempfile_config() as config_path:
            result = runner.invoke(
                cli,
                [
                    "--config",
                    config_path,
                    "search-by",
                    "--results-json",
                    str(results_input),
                    "--output-results",
                    str(results_output),
                ],
            )
        assert result.exit_code == 1
